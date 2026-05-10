# Handoff: AIG vs dual-rail AND/OR exact-synthesis comparison

This repo holds notes, scripts, and reports for an empirical comparison
between two exact-synthesis engines:

* **`andexact`** (Exa9) — minimum 2-input AND graph with input/output
  polarity bits (effectively AIG), the existing ABC engine.
* **`aoexact`** (Exa10) — minimum 2-input **dual-rail monotonic AND/OR**
  network, added as part of this work.

The empirical question: for every NPN(P)-canonical Boolean function in
small input/output regimes, how much larger is the dual-rail optimum
vs. the AIG optimum, and is the constructive 2× upper bound ever beaten?

The companion ABC fork lives at `/work/abc` (branch
`andexact-relax-floor`).

---

## 1. What we're looking for

**The 2× claim.** Any AIG of size `k` can be mechanically converted into
a dual-rail AND/OR network of size `≤ 2k`: each polarized AND
`y = (a^pa) & (b^pb)` becomes one AND of positive rails plus one OR of
negative rails (De Morgan). So dual-rail cost is bounded above by 2×
AIG cost, by construction. Open question: when can sharing across the
F-cone and FN-cone do better than 2×?

**Per-class breakdown.** For a class to beat 2×, sharing must save at
least one whole gate. Empirically we find:

* **n=3, m=1** (14 classes): never. 2× is hit exactly on every class.
* **n=4, m=1** (222 classes): 14 classes beat 2× (savings 1-2 gates).
* **n=3, m=2** (308 classes): 34 classes beat 2× (best save 20% on
  `(2e, e2)`).

See `npnp-m1-savings.md` and `npnp-n3-m2-comparison.md` for the full
tables and proven-vs-upper-bound breakdown.

---

## 2. ABC patches (branch `andexact-relax-floor`)

### Multi-output `andexact` (commit `36179e5`)

Upstream `andexact` was single-output. We added `-O <int>` and made the
engine accept comma-separated truth tables. Internally, `Bmc_EsPar_t`
gained `nOuts`, the CNF gained per-output selector variables, and the
top-of-network polarity bit became per-output.

### Dual-rail AND/OR engine `aoexact` / Exa10 (commit `70c7f6d`)

New engine in `src/sat/bmc/bmcMaj10.c`, exposed as ABC command
`aoexact`. Differs from `andexact` in three ways:

* **Inputs come dual-rail** — each logical input `x_k` is two object
  slots: positive rail `x_k`, negative rail `~x_k`. The synthesis body
  sees both; no inverter cells inside the body.
* **Outputs are dual-rail** — every logical output `f_k` is required
  in two polarities (`f_k` *and* `~f_k`) as separate cones.
* **Gates are monotonic** — each internal gate has one Boolean-op bit
  (AND or OR), no fanin polarity bits. No inversion anywhere in the
  body.

The interface materializes the negative rails as one inverter per PI
in the dumped BLIF; the synthesis body itself has zero inversions.
Full CNF and command-flag detail in `aoexact-dual-rail.md`.

### Floor-check relaxation (commit `db8fbe8`)

The original `andexact` rejected `nVars > nNodes + 1` outright and
required every PI to be consumed by some object. Both rules made
trivially-realizable functions (constants, single-literal projections)
report a fake floor. The patch drops the command-level rejection,
loops over internal nodes only when enforcing "consumed", and lowers
`nNodeMin` to 0. Affects 13 classes in n=3 m=2.

### Structured output for proven-vs-upper-bound labelling (commit `8472861`)

The pre-patch iter loop (`-m`) walked M upward and collapsed UNSAT and
TIMEOUT into one return code, so a per-M timeout would silently mask
as "every smaller M was UNSAT" → a chain at M=k would print as if it
were the proven minimum. The patch:

* Tracks `firstSatM` and `firstTimeoutM` separately during the iter
  walk in both `Exa9_ManExactSynthesisIter` and
  `Exa10_ManExactSynthesisIter`.
* Emits a per-call structured line at the end of each
  `ExaN_ManExactSynthesis` call:
  ```
  EXA9_RESULT: status=sat|unsat|timeout M=<int> nVars=<int> nOuts=<int>
               verify=ok|mismatch|n/a runtime_s=<float> tt=<comma-csv>
  ```
  `verify` exposes ABC's internal-verifier outcome on the SAT chain.
* Emits a per-iter summary line:
  ```
  EXA9_ITER_RESULT: status=proven|upper_bound|no_sat_inconclusive|
                            no_sat_proven_unsat
                    sat_M=<int> proven_lb=<int>
                    first_timeout_M=<int> M_range=[<lo>,<hi>]
  ```

Downstream Python harnesses parse these key=value lines instead of
regex-matching free text.

(Same instrumentation applies to the AO engine via `EXA10_RESULT:` /
`EXA10_ITER_RESULT:`.)

### `ABC_TRACE` debug instrumentation (commit `4dffca2`)

Env-gated tracing in three rewriting code paths
(`abcRefactor.c`, `abcResub.c`, `rwrEva.c`). Unrelated to exact synth;
only fires when `ABC_TRACE=1` is set in the environment.

---

## 3. Dual-rail circuit structure

A dual-rail network of width `(n_in, n_out)` with `M` gates:

```
PI rails:        a, aN, b, bN, c, cN, ...        (2 * n_in)
internal nodes:  n0, n1, ..., n[M-1]              (each: AND or OR
                                                   with two fanins)
outputs:         F0, F0N, F1, F1N, ...            (2 * n_out, each
                                                   pointing to a node
                                                   or PI rail)
```

Constraints:

* Each internal node is a 2-input gate; the op is AND (`&`) or OR (`|`).
* Fanins reference earlier nodes or PI rails. No inversions inside the
  body.
* Output `F_k` must compute `f_k`; output `F_kN` must compute `~f_k`.
* Sharing happens when an internal node is referenced by both the
  F-cone and the FN-cone (or by multiple outputs).

Example chain (n=3 m=1, function `0x02`, ao=4):
```
n0 = aN & b
n1 = bN & c
n2 = n0 | n1     ← shared between F and FN reasoning
n3 = a  & n2
F   = n3
FN  = !F          (formally a separate cone, but for tiny cases the
                   engine sometimes lands FN as a thin wrapper)
```

For multi-output functions the savings come from sharing both within
each function's two cones and across different output functions. The
report `npnp-n3-m2-comparison.md` has worked examples.

---

## 4. Repository layout

### `/work/abc` — ABC fork (branch `andexact-relax-floor`)

| path | role |
|---|---|
| `src/sat/bmc/bmcMaj9.c` | Exa9 engine (`andexact`). |
| `src/sat/bmc/bmcMaj10.c` | Exa10 engine (`aoexact`). |
| `src/sat/bmc/bmc.h` | Header decls. |
| `src/sat/bmc/module.make` | Build rule. |
| `src/base/abci/abc.c` | Command registration + arg parsing. |

Build: `cd /work/abc && make -j8 ABC_USE_NO_READLINE=1`
(produces `/work/abc/abc`).

### `/work/abc-synthesis-notes` — this repo (branch `dual-rail-aoexact`)

**Reports:**
- `npnp-m1-savings.md` — n=3 m=1 and n=4 m=1 results
- `npnp-n3-m2-comparison.md` — n=3 m=2 results
- `aoexact-dual-rail.md` — engine reference (CNF shape, flags)
- `abc-synthesis-commands.md`, `abc-synthesis-walkthroughs.md` — ABC
  command reference and tutorials
- `HANDOFF.md` — this file

**Pipeline scripts** in `scripts/`:

*Sweep harnesses* (drive ABC, write source TSVs):
- `exact_npnp_sweep.py` — general single-output sweeper
- `aig_npnp_n3_m2.py` — multi-output AIG sweeper (n=3 m=2)
- `aoexact_npnp_n3_m2.py` — multi-output AO sweeper (n=3 m=2)
- `_exa_parse.py` — shared parser for ABC's structured output

*Verification* (independent of sweeps):
- `audit_iter_results.py` — re-runs ABC at M-1 to label proven vs UB
- `verify_chain.py` — re-simulates every chain in pure Python
- `audit_summary.py` — roll-up reporter

*Older / tangential:*
- `aoexact_benchmarks.py`, `multiout_benchmarks.py`,
  `run-all-traces.sh`

### `/work/npnp` — NPN(P) class enumeration + result data

**Class-list generation** (independent of the synthesis pipeline):
- `npnp.c` (compile to `npnp` binary) — fast C enumerator
- `npnp_canon.py` — pure-Python canonicalizer (slow, used for
  cross-checks)
- `npnp_print.py` — converts `*.bin` to `classes_n<N>_m<M>.txt`
- `verify.py` — sanity checks for the canonicalizer

**Class lists** (sweep inputs): `classes_n3_m1.txt` (14 classes),
`classes_n4_m1.txt` (222), `classes_n3_m2.txt` (308), and larger m's.

**Sweep result TSVs** (sweep outputs):
- `aig_npnp_n<N>_m<M>.tsv`, `aoexact_npnp_n<N>_m<M>.tsv`
- `aig_npnp_n3_m2_relaxed.tsv` (post floor-relaxation patch)

**Audit TSVs** (verification outputs):
- `audit_aig_n<N>_m<M>.tsv`, `audit_ao_n<N>_m<M>.tsv`

**Sample circuits**: `circuits_n4_m1/*.blif`.

### Data flow

```
npnp.c / npnp_canon.py    [n,m]  →  npnp_n<N>_m<M>.bin
        │
        ▼
npnp_print.py              .bin  →  classes_n<N>_m<M>.txt
        │
        ▼
exact_npnp_sweep.py /
aig_npnp_n3_m2.py /
aoexact_npnp_n3_m2.py    classes  →  aig_/aoexact_npnp_n<N>_m<M>.tsv
                                     (via _exa_parse over patched ABC)
        │
        ├──► verify_chain.py   ← re-simulates every printed chain
        │
        └──► audit_iter_results.py  →  audit_<engine>_n<N>_m<M>.tsv
                       │
                       ▼
              audit_summary.py  →  roll-up
                       │
                       ▼
              report .md files in this repo
```

---

## 5. How to reproduce results

### One-time setup

```bash
# build patched ABC
cd /work/abc && make -j8 ABC_USE_NO_READLINE=1

# build NPNP class enumerator
cd /work/npnp && gcc -O3 -march=native -o npnp npnp.c
```

### Generate class lists (already done; skip if `classes_*.txt` exists)

```bash
cd /work/npnp
./npnp 3 1 && python3 npnp_print.py --classes-only npnp_n3_m1.bin > classes_n3_m1.txt
./npnp 4 1 && python3 npnp_print.py --classes-only npnp_n4_m1.bin > classes_n4_m1.txt
./npnp 3 2 && python3 npnp_print.py --classes-only npnp_n3_m2.bin > classes_n3_m2.txt
```

### Run a sweep (single-output)

```bash
cd /work/abc-synthesis-notes/scripts

# AIG side, n=4 m=1, generous budget for the harder classes
python3 exact_npnp_sweep.py --engine andexact --n-in 4 --n-out 1 \
    --input /work/npnp/classes_n4_m1.txt \
    --output /work/npnp/aig_npnp_n4_m1.tsv \
    --workers 32 --max-nodes 12 --per-m-timeout 60 --wall-timeout 600

# AO side, n=4 m=1, dual-rail ceiling is roughly 2x
python3 exact_npnp_sweep.py --engine aoexact --n-in 4 --n-out 1 \
    --input /work/npnp/classes_n4_m1.txt \
    --output /work/npnp/aoexact_npnp_n4_m1.tsv \
    --workers 32 --max-nodes 24 --per-m-timeout 120 --wall-timeout 1800
```

### Run a sweep (multi-output, n=3 m=2)

```bash
python3 aig_npnp_n3_m2.py --output /work/npnp/aig_npnp_n3_m2_relaxed.tsv \
    --workers 32 --max-nodes 12 --per-m-timeout 60 --wall-timeout 600

python3 aoexact_npnp_n3_m2.py --output /work/npnp/aoexact_npnp_n3_m2.tsv \
    --workers 32 --max-nodes 20 --per-m-timeout 120 --wall-timeout 1800
```

The harness self-labels each row as `sat` (proven), `ub` (chain valid,
optimum unproven), `unsat`, `timeout`, or a diagnostic. No manual
`--status-override` needed.

### Verify chains (cheap, run after every sweep)

```bash
python3 verify_chain.py --input /work/npnp/aig_npnp_n4_m1.tsv \
    --n-in 4 --dialect aig
python3 verify_chain.py --input /work/npnp/aoexact_npnp_n4_m1.tsv \
    --n-in 4 --dialect ao
```

Expected output: `ok: <total>` with no MISMATCH/parse_fail/sim_fail.

### Audit (independent re-probe at M = reported_k − 1)

```bash
python3 audit_iter_results.py --engine aig --n-in 4 \
    --input /work/npnp/aig_npnp_n4_m1.tsv \
    --output /work/npnp/audit_aig_n4_m1.tsv \
    --workers 32 --timeout 1200

python3 audit_iter_results.py --engine ao --n-in 4 \
    --input /work/npnp/aoexact_npnp_n4_m1.tsv \
    --output /work/npnp/audit_ao_n4_m1.tsv \
    --workers 32 --timeout 1200

python3 audit_summary.py /work/npnp/audit_aig_n4_m1.tsv \
    /work/npnp/audit_ao_n4_m1.tsv
```

Verdicts: `proven` (UNSAT at M-1), `upper_bound` (timeout at M-1),
`WRONG` (SAT at M-1 — flags an over-count bug), `trivial`,
`tt_mismatch`, `verify_mismatch`, `parse_fail`.

---

## 6. Soundness of sub-2× claims

A sub-2× claim has the form `ao_min < 2 × aig_min`. Three independent
checks back it:

1. **Chain re-simulator** confirms `ao_chain` actually computes the
   listed truth table (so `ao_reported ≥ ao_min`).
2. **AIG-side audit** must return `proven` (so `aig_reported = aig_min`).
3. The arithmetic `ao_reported < 2 × aig_reported` is then sound:
   `ao_min ≤ ao_reported < 2 × aig_min`.

The AO-side audit (`proven` vs `upper_bound`) only changes whether we
*also* know `ao_min` exactly. It does **not** affect sub-2× soundness.

The audit found two over-counts caused by the pre-patch UNSAT/timeout
collapse: `1886` (AIG n=4 m=1, was 11, true 10) and `(16,6e)` (AO n=3
m=2, was 16, true ≤ 15). Both are reflected in the reports. With the
structured-output patch and harness update, fresh sweeps self-label
proven vs ub correctly, so this class of error cannot recur silently.

---

## 7. Open work

* **n=4 m=1 AO**: 73 classes still time out at every M tried in the
  most generous sweep (8 h/function). They have no chain and no upper
  bound from us. Would need either much longer wall, a better SAT
  encoding, or CEGAR-style techniques.
* **n=4 m=2 and beyond**: not attempted — search space is much larger.
* **Sub-2× lower bounds**: we only state savings as `≥ reported`. To
  state exact savings, the AO-side audit would need to come back
  proven for the relevant cases.
