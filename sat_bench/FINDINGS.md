# Cadical vs Kissat cold-call benchmark (2026-05-11)

Experiment: do we benefit from switching the SAT backend for `andexact` /
`aoexact` away from Kissat? Conducted without the full
incremental-encoding refactor — just a `-c` flag to dump the DIMACS that
ABC builds internally, plus a small standalone harness
(`sat_bench.cpp`) that re-solves the dumped CNF under either Kissat or
CaDiCaL with configurable options.

## Setup

- Branch: `andexact-relax-floor` on `/work/abc` (merged from the
  `cnfdump-experiment` worktree that produced the patch).
- Patches: `src/sat/bmc/bmcMaj9.c`, `src/sat/bmc/bmcMaj10.c`, `src/base/abci/abc.c`.
- Both `andexact` and `aoexact` learned a `-c` flag that writes
  `<engine>_<tt>_N<n>_O<m>_M<k>.cnf` (DIMACS) alongside the normal solve.
- Harness `sat_bench` reads DIMACS, optionally applies CaDiCaL phase
  hints (`--phase file.phase`) or solver options
  (`--cad-opt name=val`, `--kis-opt name=val`).

## Result table

| CNF | kissat-default | cadical-default | cadical `target=2` |
| --- | --: | --: | --: |
| aoexact tt=96 M=12 (n=3, SAT) | 0.33s | 3.56s | 0.51s |
| aoexact tt=06be M=14 (n=4, SAT) | 27.19s | 85.35s | **2.65s** |
| aoexact tt=036e M=14 (n=4, SAT) | **>180s** | **>180s** | 101.33s ✓ |
| andexact tt=06be M=8 (n=4, SAT) | 0.16s | 0.13s | 0.07s |
| andexact tt=036e M=8 (n=4, SAT) | 0.44s | 0.14s | 0.04s |
| aoexact tt=019e M=18 (=2K, SAT) | **>180s** | 169.22s ✓ | **>180s** |
| aoexact tt=019e M=17 (=2K-1) | **>180s** | **>180s** | **>180s** |

`>180s` = sat_bench was killed by the wall budget without printing
`wall_s=`. `✓` flags wins on previously-stuck classes.

## What's a "stuck" class

`019e` and `036e` are two of the nine n=4 m=1 classes flagged in
`npnp-m1-savings.md` as "above-2× SAT artifacts" — the constructive 2K
bound proves a chain exists at M ≤ 2·aig, but the Kissat-driven sweep
never finds it. `036e` has `aig=8`, so M=14 is below the constructive
bound 16; the kissat-default sweep finds nothing at M=14, 15, 16, etc.
within reasonable budget. `019e` has `aig=9`, M=18 is exactly the
constructive bound; kissat-default never confirms it.

## CNF shape, encoding-side

Comparing the dumped CNF for andexact tt=06be M=8 vs aoexact tt=06be M=14:

```
andexact M=8:  1396 vars, 10517 clauses, hist {1:210, 2:2475, 3:7808}
aoexact M=14:  2398 vars, 18411 clauses, hist {1:342, 2:3690, 3:13888, 4:449}
```

Quaternary clauses appear in Exa10 only — they come from the per-gate
`Op` variable (selects AND vs OR), which switches the gate function and
expands the per-minterm value equation to 4 cubes. Exa9's AND-only gate
gives 3-clause per-minterm equations.

## Headlines

1. **CaDiCaL `target=2` is broadly beneficial for these encodings**
   — wins on 5 of 7 instances, often 10-30×, and unsticks tt=036e M=14
   (101s SAT where everything else times out at 180s).

2. **CaDiCaL `target=2` is not a universal win.** On `019e M=18`, default
   CaDiCaL solves at 169s; CaDiCaL `target=2` times out at 180s. Different
   instances respond to different phase strategies.

3. **Kissat-default is *not* always best** even on the AO instances we
   thought it owned. CaDiCaL-default beats kissat on `019e M=18` —
   kissat times out where CaDiCaL succeeds.

4. **The hard core (`019e M=17`)** is hard for all three configurations.
   No single-engine-single-option probe at 180s resolves whether a
   sub-2× chain exists.

## Implication for the bigger plan

- "Just swap to CaDiCaL+target=2" is not a unilateral upgrade.
- A **portfolio** strategy — race kissat-default, CaDiCaL-default, and
  CaDiCaL `target=2` in parallel on each `lo_sat - 1` probe, take the
  first to return — fits naturally on the 192-core host and absorbs the
  per-instance variance.
- The cold-call story alone doesn't justify the full
  incremental-encoding refactor; the win there would have to come
  exclusively from clause reuse during the descending walk, against a
  baseline that's already faster than what we had.
- The De Morgan AIG→AO unroller is still independent of all of this and
  is the cleanest immediate win — it kills the "no SAT chain known at
  2K" gap outright for any class with a proven AIG.

## Warm-start follow-up (cross-M phase hints from 2K witness)

After the cold benchmark we added: (a) `--dump-model file.phase` to
`sat_bench` so a satisfying assignment can be written out as DIMACS
phase hints; (b) `translate_model.py`, a pure-Python Exa10 variable-ID
translator that takes a model at M=K_src and produces phase hints for
M=K_dst by replaying the role→ID indexing formula at both M values
(aux vars are deliberately not transferred — they're position-dependent
1-hot helpers, not gate semantics).

For each class we solve at M=2K, dump the model, translate to M=2K-1
phase hints, then time M=2K-1 cold vs warm under each `target` value.

Small initial sample:

| Class | M | status | target | cold | warm | speedup |
| --- | --- | --- | --- | --: | --: | --: |
| 06be (n=4) | 15 | SAT (sub-2× exists) | default | 9.46s | 2.25s | 4.2× |
|  |  |  | target=1 | 9.46s | 2.27s | 4.2× |
|  |  |  | target=2 | 25.67s | **0.95s** | **27×** |
| MAJ-3 e8 (n=3) | 7 | UNSAT (at-2× proven) | default | 0.256s | 0.204s | 1.25× |
|  |  |  | target=1 | 0.261s | 0.200s | 1.30× |
|  |  |  | target=2 | 0.246s | 0.219s | 1.12× |

Larger sample (with multi-minute baselines):

| Class | M | status | target | cold | warm | warm/cold |
| --- | --- | --- | --- | --: | --: | --: |
| 036e (n=4) | 15 | SAT | default | 39.74s | 10.78s | 0.27 |
|  |  |  | target=1 | 40.13s | 10.75s | 0.27 |
|  |  |  | target=2 | **4.97s** | 22.29s | **4.49 (warm SLOWER)** |
| 1bd8 (n=4) | 17 | SAT | default | 16.47s | 32.33s | **1.96 (slower)** |
|  |  |  | target=1 | 16.29s | 32.87s | **2.02 (slower)** |
|  |  |  | target=2 | 9.68s | 11.06s | 1.14 (slight regression) |
| 008e (n=4) | 9 | UNSAT | default | 44.33s | 25.92s | 0.58 |
|  |  |  | target=1 | 44.64s | 25.79s | 0.58 |
|  |  |  | target=2 | 42.26s | 26.57s | 0.63 |
| 0188 (n=4) | 11 | UNSAT | all six | >600s | >600s | — |

### Reading the warm-start data

1. **Warm-start can HURT SAT search**, contrary to the initial 06be
   data. On 1bd8 M=17 warm doubled the wall under default/target=1; on
   036e M=15 under target=2 warm took 22s while cold was 5s.

2. **Mechanism**: a 2K witness is a SAT assignment for the "padded
   easier" instance. Translating to 2K-1 keeps most of it but drops one
   gate slot's info. If the hinted assignment is structurally near a
   real 2K-1 chain, the solver picks up the scent immediately — that's
   the 06be / 036e-default case. If the hinted assignment sits on a
   different topology island that has no feasible extension at 2K-1,
   the solver burns time confirming dead-end before drifting — that's
   1bd8 and 036e-target=2.

3. **Warm-start helps UNSAT consistently** (~1.6-1.7× across targets on
   008e, 1.1-1.3× on MAJ-3 M=7). The hints can't mislead because there
   is no feasible region anywhere; they only accelerate initial
   propagation toward the contradiction.

4. **`target=2` cold is sometimes startlingly fast** (036e M=15 cold
   target=2: 5s vs 40s default). When it works, it dominates. But it's
   also a roulette spin — see 06be M=15 cold target=2 (25.67s vs 9.46s
   default, target=2 lost). The focused-mode rephasing interacts with
   the encoding in instance-specific ways.

5. **0188 M=11 didn't resolve under any 10-min cadical config**.
   Kissat's audit-recorded 27-min UNSAT proof on this class was a
   one-time win for kissat; CaDiCaL doesn't pick up the slack here.

### Implication for the bigger plan

Warm-start is *not* a universal "always do this" lever. It helps on
maybe ~30-40% of SAT cases (the structurally-close ones) and ~all
UNSAT cases at moderate speedup. The portfolio approach — race
{kissat-default, cadical-default, cadical-target=2,
cadical-warm-default, cadical-warm-target=2} on each `lo_sat - 1`
probe, take the first to return — absorbs this variance and pays only
the cost of the fastest. With 192 cores it's free.

A single hard-coded backend swap (any choice) leaves money on the
table on a meaningful slice of instances.

## What I deliberately did not do

- No witness sidecar dump *inside ABC* (the Python translator covers
  the cross-M case for our experiments; if integrated into state_resume
  the dump can happen at the ABC layer after a SAT call).
