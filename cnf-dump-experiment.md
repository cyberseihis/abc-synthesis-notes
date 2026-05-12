# CNF-dump experiment: kissat vs CaDiCaL on Exa9 / Exa10 CNFs

Investigation of whether switching the SAT backend from the bundled
Kissat to CaDiCaL (with various phase-strategy options) and adding a
"warm-start from 2K witness" step would meaningfully accelerate the
stuck `lo_sat - 1` probes in the bound-tracking pipeline. Conducted
2026-05-11 / 2026-05-12.

**Outcome: keep the kissat-based baseline.** CaDiCaL with the right
option (`target=2`) wins on some instances by 10-30×, but loses on
others. Warm-start from a 2K constructive witness helps UNSAT proofs
consistently but can actively hurt SAT search depending on the witness
neighborhood. No single configuration dominates kissat-default across
the test set.

## What was added to ABC

Two new commits on `andexact-relax-floor` (no functional behavior
change without flags):

1. **`exact synth: per-PO constant slots in the output 1-hot`**
   (`532d628b3`). Each output's one-hot literal pool grows by two
   constant-tie slots (k=0 and k=1). For non-constant targets both
   slots are unit-clause forced false, collapsing the encoding back to
   the original `2*nObjs` pool. Eliminates the trivial-function
   inflation where constant or single-literal targets had to consume
   an internal node. This was uncommitted WIP that the existing
   `/work/npnp/` data was built against; the commit makes it
   reproducible.

2. **`exact synth: -c flag to dump DIMACS alongside solving`**
   (`dafb96592`). `andexact` and `aoexact` learn a `-c` toggle that
   writes the per-call CNF as DIMACS to
   `<engine>_<tt>_N<n>_O<m>_M<k>.cnf` in the working directory while
   the normal kissat solve proceeds. Behavior is unchanged without
   `-c` — every dump-related branch is guarded by `fDumpCnf` /
   `pCnfFile`. The dump intercepts `Exa9_KissatAddClause` /
   `Exa10_KissatAddClause`, writes a placeholder header at solver
   alloc, and rewrites with the final var/clause counts at solver
   free.

## What was added in this repo

In `sat_bench/`:

- **`sat_bench.cpp`** — standalone DIMACS solver harness, linked
  against ABC's vendored Kissat and CaDiCaL `.o` files. Flags:
  `--kissat | --cadical`, `--phase FILE`, `--cad-opt name=val[,...]`,
  `--kis-opt name=val[,...]`, `--dump-model FILE`. Reports
  `SAT|UNSAT|UNKNOWN wall_s=<sec>`. Phase hints are only supported on
  CaDiCaL (Kissat has no per-variable phase API). Build expects
  `/work/abc` to have been compiled (so the vendored Kissat/CaDiCaL
  `.o` files exist).

- **`translate_model.py`** — pure-Python Exa10 model translator that
  takes a SAT assignment at M=K_src and emits phase hints for M=K_dst
  by replaying the role-to-variable-ID indexing formulas at both M
  values. Auxiliary 1-hot helper vars are deliberately not
  transferred — they're position-dependent encoding internals, not
  gate semantics.

- **`FINDINGS.md`** — fuller writeup of the benchmark data and
  per-instance numbers.

## Experiments and what we observed

### 1. Cold benchmark — kissat-default vs cadical-default

CNFs were dumped with `-c`, then re-solved under each backend.
Headline: **mixed picture**. CaDiCaL is competitive on `andexact`
(Exa9), slower on `aoexact` (Exa10) — sometimes by 10×.

| CNF | kissat | cadical-default |
| --- | --: | --: |
| andexact tt=06be M=8 (SAT) | 0.16s | 0.13s |
| andexact tt=036e M=8 (SAT) | 0.44s | 0.14s |
| aoexact tt=06be M=14 (SAT) | 27.19s | 85.35s |
| aoexact tt=96 M=12 (SAT) | 0.33s | 3.56s |
| aoexact tt=019e M=18 (SAT) | >180s | 169.22s |

The Exa10 slowdown is plausibly tied to the per-gate Op variable
(switches AND vs OR) — Exa10 dumps have 449 quaternary clauses per
typical instance, Exa9 has none, and the Op vars create a strong
function-switch branching choice that CaDiCaL's default heuristics
appear to handle worse than Kissat's.

### 2. CaDiCaL option sweep on aoexact tt=06be M=14

| option | wall |
| --- | --: |
| default | 84.62s |
| `elim=0` | 85.51s |
| `elim=0,vivify=0` | 48.16s |
| `target=2` | **2.65s** |
| `phase=0` | 2.80s |
| `target=2,phase=0` | 10.45s |

`target=2` (focused-phase mode) is the lever — drops to 2.64s, beating
kissat-default by 10×. But this is not unilateral; the cross-benchmark
showed `target=2` regressing on other instances (notably aoexact
tt=019e M=18, where default cadical SAT in 169s but `target=2` timed
out at 180s).

### 3. Warm-start (cross-M phase hints from 2K witness)

`translate_model.py` translates a SAT model at M=2K into phase hints
for M=2K-1, sharing variable IDs for every role (selection vars,
output selectors, Op vars, value vars) that exists at both M values.

| Class | M | status | target | cold | warm | warm/cold |
| --- | --- | --- | --- | --: | --: | --: |
| 06be (n=4) | 15 | SAT | default | 9.46s | 2.25s | 0.24 |
| 06be (n=4) | 15 | SAT | target=2 | 25.67s | **0.95s** | **0.04** |
| MAJ-3 e8 (n=3) | 7 | UNSAT | default | 0.26s | 0.20s | 0.78 |
| 036e (n=4) | 15 | SAT | default | 39.74s | 10.78s | 0.27 |
| 036e (n=4) | 15 | SAT | target=2 | **4.97s** | 22.29s | **4.49 (warm slower)** |
| 1bd8 (n=4) | 17 | SAT | default | 16.47s | 32.33s | **1.96 (warm slower)** |
| 1bd8 (n=4) | 17 | SAT | target=2 | 9.68s | 11.06s | 1.14 |
| 008e (n=4) | 9 | UNSAT | default | 44.33s | 25.92s | 0.58 |
| 008e (n=4) | 9 | UNSAT | target=2 | 42.26s | 26.57s | 0.63 |
| 0188 (n=4) | 11 | UNSAT | all 6 | >600s | >600s | — |

Observations:

- **Warm-start can hurt SAT.** On 1bd8 M=17 warm doubled the wall
  time under default and target=1. On 036e M=15 target=2 it was 4.5×
  slower than cold target=2. The 2K witness translates to "almost a
  2K-1 chain", but if the hinted neighborhood has no feasible 2K-1
  extension, the solver burns cycles confirming dead-end.
- **Warm-start consistently helps UNSAT** (~1.6-1.7× on 008e, modest
  on MAJ-3). Hints can't mislead when no feasible region exists; they
  accelerate initial propagation toward the contradiction.
- **`target=2` cold is sometimes startlingly fast** but is unstable
  across instances — it's a strong outlier when it works, harmful when
  it doesn't.
- **0188 M=11** didn't resolve under any 10-minute cadical config.
  Kissat's audit-recorded 27-min UNSAT proof on this class was a
  one-time win that CaDiCaL didn't replicate.

## Decision: keep the kissat-based baseline

The bound-tracking pipeline (`state_init.py`, `state_resume.py`)
continues to invoke `/work/abc/abc` with its kissat backend. Reasons:

1. No single CaDiCaL configuration dominates kissat across the test
   set. Switching unilaterally would speed up some classes 10-30× and
   slow down others 2-3×, with no easy a-priori way to pick.
2. The warm-start win on SAT is conditional and instance-dependent.
   The win on UNSAT is consistent but modest (~1.6×) — not large
   enough to offset the implementation cost given (1).
3. The lever that would actually pay off is a **portfolio**: race
   `{kissat-default, cadical-default, cadical-target=2,
   cadical-warm-default, cadical-warm-target=2}` on each `lo_sat - 1`
   probe and take the first to return. With 192 cores this is free,
   but it changes the state-system architecture more than a backend
   swap would. Not justified by current data alone.
4. The cleanest standalone win (independent of any backend question)
   is the De Morgan AIG→AO unroller — converts an AIG chain into an
   explicit AO chain at exactly `2K` gates without any SAT call. Kills
   the "no SAT chain at 2K found within budget" gap directly. Not
   implemented; flagged in `npnp-m1-savings.md:137`.

## Reproducing

```bash
# Build experimental ABC (with -c flag, same andexact-relax-floor branch)
cd /work/abc
ABC_USE_NO_READLINE=1 make -j32

# Dump a CNF for a representative class
cd /tmp
/work/abc/abc -q "aoexact -N 4 -O 1 -M 14 -c -T 30 06be"
ls aoexact_06be_N4_O1_M14.cnf

# Build the sat_bench harness (one-time)
cd /work/abc-synthesis-notes/sat_bench
g++ -O2 -std=c++17 -fno-exceptions \
  -DLIN64 -DSIZEOF_VOID_P=8 -DSIZEOF_LONG=8 -DSIZEOF_INT=4 \
  -I /work/abc/src/sat/cadical -I /work/abc/src \
  -c sat_bench.cpp -o sat_bench.o
g++ -O2 -std=c++17 -fno-exceptions sat_bench.o \
  $(ls /work/abc/src/sat/cadical/*.o | grep -vE "cadicalSolver|cadicalTest") \
  $(ls /work/abc/src/sat/kissat/*.o  | grep -vE "kissatSolver|kissatTest") \
  -lpthread -o sat_bench

# Run a 3-way comparison
cd /tmp
./sat_bench --kissat                            aoexact_06be_N4_O1_M14.cnf
./sat_bench --cadical                           aoexact_06be_N4_O1_M14.cnf
./sat_bench --cadical --cad-opt target=2        aoexact_06be_N4_O1_M14.cnf
```

For warm-start: solve at M=K, `--dump-model model.phase`, translate to
M=K-1 with `translate_model.py`, then `--phase model.phase` on the
M=K-1 CNF.
