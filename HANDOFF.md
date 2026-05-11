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

* **n=3, m=1** (14 classes): never. 2× is hit exactly on every class
  (or it's a 0-gate trivial class).
* **n=4, m=1** (222 classes): a handful beat 2× (savings 1-2 gates).
* **n=3, m=2** (308 classes): **34 classes beat 2×** — 9 fully proven,
  25 sound (AIG proven, AO ub). Best proven savings: 20% on `(2e, e2)`.

See `npnp-m1-savings.md` and `npnp-n3-m2-comparison.md` for the full
tables and proven-vs-upper-bound breakdown.

**Pipeline.** Sweeps run through the bound-tracking state system
(`state_init.py` / `state_resume.py` / `state_show.py`). Each row of
the state TSV stores the highest UNSAT and lowest SAT seen so far for
its truth-table, plus an `attempts` log of every probe and its budget.
Resuming with a longer wall writes a new versioned file rather than
mutating the previous one, and only re-runs M values whose prior
budget was strictly smaller. The state schema enforces the three
experiment-scope rules mechanically:

1. No AO probes if AIG isn't proven (no proven `K`).
2. No AO probes at `M ≥ 2K` (constructive bound already covers it).
3. No AO probes below `lo_sat − 1` unless SAT was proven at `lo_sat − 1`.

Over-counts are structurally impossible: SAT outcomes can only ever
tighten `lo_sat` downward, UNSAT outcomes can only push `hi_unsat`
upward. The report numbers above predate the state system and were
produced by a now-removed legacy sweep harness; the data files
themselves live in `/work/npnp/` and remain consumable by
`verify_chain.py` and `render_sub2x_formulas.py`.

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

### PO-only constant slots (May 2026)

`andexact` and `aoexact` both lacked a way to emit a constant 0 or 1
directly at a PO. The model had no Const-0 or Const-1 object, and the
strict fanin-ordering symmetry-breaker forbade degenerate `x ∧ ¬x`
internal gates (which would otherwise have been the only way to
manufacture a constant). As a result, classes whose POs are constant
needed at least one extra gate of internal scaffolding (e.g.
`F = ¬a ∧ (a ∧ b) = 0` consumes 2 AIG gates), or in the AO engine the
output cone simply couldn't be expressed at all.

The patch adds two PO-only constant selectors per output slot (one for
the constant-0 case, one for the constant-1 case). Internal gate fanins
cannot pick them; they only widen the per-PO one-hot. Unit clauses force
the slot off unless the target truth table is the matching constant, so
non-constant targets see no behavior change. After the patch:

* `andexact` synthesizes 4 n=3 m=2 classes at AIG = 0 that previously
  needed AIG = 2 (`(00, 00)`, `(00, aa)`, plus the literal pairs
  `(aa, aa)` and `(aa, cc)` that were already at 0).
* `aoexact` synthesizes those same classes at AO = 0.
* No other class's gate count changes.

Edits live in `src/sat/bmc/bmcMaj9.c` (Exa9) and
`src/sat/bmc/bmcMaj10.c` (Exa10). Solution-reading helpers
(`*_ManFindOutput`, `*_ManIsOutputConst`, BLIF dump) handle the new
slot type. The Boolean-formula renderer
(`scripts/render_sub2x_formulas.py`) round-trip-checks every formula
against the source truth table before printing.

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

*Bound-tracking state system* (every run records
`(hi_unsat, lo_sat, attempts)` so the next run knows what to retry;
resume always writes a new versioned file):
- `state_init.py` — first pass. AIG: iter from 0 with a per-class wall
  budget. AO: derives `lo_sat = 2·K` from a proven-AIG state file
  (rule 1: no probes if AIG isn't proven).
- `state_resume.py` — picks the next M per row using the pruning rules,
  runs fixed-M probes, writes a new state file (auto-versioned). AIG:
  walks up inside the `(hi_unsat, lo_sat)` gap. AO: walks down from
  `lo_sat − 1` (rule 3); never probes `M ≥ 2K` (rule 2).
- `state_show.py` — pretty-print a state file; pair AIG + AO to get the
  2× classification table (`--list-gaps`, `--list-sub2x`).
- `_state_io.py` — schema + helpers (`read_state`, `write_state`,
  `derive_status`, `next_version_path`, …).
- `_exa_run.py` — single ABC-call wrapper (`run_fixed_M`, `run_iter`).
- `_exa_parse.py` — parser for ABC's structured `EXA*_RESULT:` lines.

*Independent verification / rendering* (orthogonal to bound tracking):
- `verify_chain.py` — re-simulates every chain in pure Python. Reads
  the legacy TSV format; adapting it to read state TSVs is open work.
- `render_sub2x_formulas.py` — Boolean-formula renderer for each
  sub-2× class. Reads the legacy TSV format; adapting it to state
  TSVs is open work.

*Engine bring-up benchmarks* (predate the NPNP sweep effort; useful
as hand-picked smoke tests against ABC):
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

**State TSVs** (bound-tracking format, written by `state_init.py` /
`state_resume.py`; each resume writes a new versioned file):
- `state_aig_n<N>_m<M>_v<k>.tsv` — AIG sweep state
- `state_ao_n<N>_m<M>_v<k>.tsv` — AO sweep state

**Legacy sweep TSVs** (produced by an earlier harness now removed;
retained as the data backing the existing reports):
- `aig_npnp_n<N>_m<M>.tsv`, `aoexact_npnp_n<N>_m<M>.tsv`,
  `aoexact_npnp_n<N>_m<M>_retry*.tsv`,
  `aoexact_npnp_n<N>_m<M>_probe_2x.tsv`,
  `aoexact_npnp_n<N>_m<M>_combined.tsv`,
  `audit_aig_n<N>_m<M>.tsv`, `audit_ao_n<N>_m<M>_combined.tsv`.
  These are read by `verify_chain.py` and `render_sub2x_formulas.py`.

**Archive**: Pre-cleanup snapshots (before the May 2026 redo with const-PO
slots) live in `/work/npnp/archive/`. The `data-snapshot` directory in
`/work/abc-synthesis-notes/archive/` holds a duplicate of the prior
`/work/npnp/` TSV set and the previous report draft.

**Sample circuits**: `circuits_n4_m1/*.blif`.

### Data flow

```
npnp.c / npnp_canon.py    [n,m]  →  npnp_n<N>_m<M>.bin
        │
        ▼
npnp_print.py              .bin  →  classes_n<N>_m<M>.txt
        │
        ▼
state_init.py --engine andexact     →   state_aig_n<N>_m<M>_v0.tsv
        │
state_resume.py (longer budget)     →   state_aig_n<N>_m<M>_v1.tsv ...
        │  (repeat until no gap rows are budget-limited)
        ▼
state_init.py --engine aoexact      →   state_ao_n<N>_m<M>_v0.tsv
   (--aig-state state_aig_...)         (sets lo_sat = 2·K per row)
        │
state_resume.py (probes lo_sat − 1) →   state_ao_n<N>_m<M>_v1.tsv ...
        │  (repeat with larger budgets to walk down)
        ▼
state_show.py aig_state ao_state    →   2× classification table
        │
        ▼
render_sub2x_formulas.py             →   Boolean-formula table (uses
                                          legacy TSVs today; adapting
                                          to state files is open work)
```

Resume never overwrites: each call writes `*_v<n+1>.tsv` from `*_v<n>.tsv`.
The state file's `attempts` JSON records every probe (`M`, `budget_s`,
`outcome`, `wall_s`); a retry only fires when the new budget exceeds
what that M last got. The `(hi_unsat, lo_sat)` pair is monotone:
SAT outcomes can only tighten `lo_sat` downward, UNSAT outcomes can
only push `hi_unsat` upward, so an over-count is structurally
impossible — the file itself is the audit.

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

### Run a sweep (state system)

Each step writes a TSV with per-class `(hi_unsat, lo_sat, attempts)`;
resume picks the next M to probe automatically and never overwrites the
input. Works the same for single-output and multi-output (pass
`--n-out 2` and a class file with `tt0 tt1` lines).

```bash
cd /work/abc-synthesis-notes/scripts

# 1. AIG init — iter walks 0..max-nodes with the wall budget.
python3 state_init.py --engine andexact --n-in 4 --n-out 1 \
    --classes /work/npnp/classes_n4_m1.txt \
    --output /work/npnp/state_aig_n4_m1_v0.tsv \
    --max-nodes 12 --per-m-timeout 60 --wall-timeout 600 --workers 32

# 2. AIG resume — tightens any remaining gaps with a longer budget.
#    Writes state_aig_n4_m1_v1.tsv (auto-versioned).
python3 state_resume.py --input /work/npnp/state_aig_n4_m1_v0.tsv \
    --wall-timeout 1800 --workers 32

# 3. AO init — derives lo_sat = 2·K from the proven-AIG state.
#    Rows whose AIG isn't proven get status=aig_unproven (rule 1: skip).
python3 state_init.py --engine aoexact --n-in 4 --n-out 1 \
    --aig-state /work/npnp/state_aig_n4_m1_v1.tsv \
    --output /work/npnp/state_ao_n4_m1_v0.tsv

# 4. AO resume — probes M = lo_sat − 1 (rule 3); never probes ≥ 2K (rule 2).
#    UNSAT closes the gap; SAT shifts lo_sat down and the next resume
#    probes lo_sat − 1 again.
python3 state_resume.py --input /work/npnp/state_ao_n4_m1_v0.tsv \
    --wall-timeout 1800 --workers 32
# repeat with larger budgets until status breakdown stops changing
python3 state_resume.py --input /work/npnp/state_ao_n4_m1_v1.tsv \
    --wall-timeout 7200 --workers 12

# 5. Summary + 2× classification.
python3 state_show.py \
    /work/npnp/state_aig_n4_m1_v1.tsv \
    /work/npnp/state_ao_n4_m1_v2.tsv \
    --list-sub2x
```

`state_show.py` pairs the two state files and produces the
trivial / sub-2× proven / sub-2× sound / at-2× proven / at-2× sound /
above-2× / no_ao classification. Add `--list-gaps` to see exactly
which rows still have an unresolved bound and what budget they last
got; `--list-sub2x` lists the wins with their chains.

The state TSVs are self-describing: `tt engine n_in n_out hi_unsat
lo_sat status chain attempts` (attempts is JSON). The `attempts` log is
the authoritative trace — every probe records `{M, budget_s, outcome,
wall_s}`, so the resume always knows exactly what's been tried and at
what budget, and only re-runs a timed-out M when the new budget is
strictly larger.

### Verify chains (independent re-simulation)

```bash
python3 verify_chain.py --input /work/npnp/aig_npnp_n4_m1.tsv \
    --n-in 4 --dialect aig
python3 verify_chain.py --input /work/npnp/aoexact_npnp_n4_m1.tsv \
    --n-in 4 --dialect ao
```

Expected output: `ok: <total>` with no MISMATCH/parse_fail/sim_fail.

`verify_chain.py` currently reads the legacy TSV format that lives in
`/work/npnp/` from earlier sweep runs. Adapting it to read state-system
chains (`tt`/`chain` columns) is open work — the chain text format is
unchanged, only the surrounding TSV schema differs.

---

## 6. Soundness of sub-2× claims

A sub-2× claim has the form `ao_min < 2 × aig_min`. The state system
makes the soundness argument mechanical: each row stores
`(hi_unsat, lo_sat)` plus the full `attempts` log, and `status`
derives from them.

* `status=proven` requires `hi_unsat + 1 == lo_sat`, which means an
  UNSAT proof at `lo_sat − 1` and a SAT chain at `lo_sat` — so the
  true minimum is exactly `lo_sat`.
* `status=gap` means only an upper bound is known: `min ≤ lo_sat`.
  Paired with a proven AIG `K`, this still gives a sound sub-2× claim
  whenever `lo_sat < 2K`, even without a UNSAT at `lo_sat − 1`.
* `status=aig_unproven` blocks AO probing entirely (rule 1: no proven
  `K` ⇒ no sound 2× claim possible).

Over-counts are structurally impossible: every SAT outcome only ever
tightens `lo_sat` downward and atomically replaces the chain. There's
no separate audit pass — the state file is the audit.

For independent verification of the chain text itself,
`verify_chain.py` re-simulates each chain in pure Python (currently
against legacy TSVs; adapting it to state TSVs is open work). This
is an orthogonal safety net against bugs in ABC's chain emitter or
the parser.

For historical context: the May 2026 sweep redo found and fixed real
over-counts in legacy data — e.g. `(16, 96)` in n=3 m=2 was originally
reported `ub:15`, audit found SAT at M=14, chase landed at `ub:14`
(still ≤ 2·7 = 14). In the state system that bug couldn't arise: the
M=15 probe would never have been recorded as the minimum without an
explicit UNSAT at M=14.

---

## 7. Open work

* **n=4 m=1 AO**: 1 class (`299e`) and ~9 above-2× rows (SAT-search
  budget artifacts) didn't fit the constructive 2× bound empirically
  even with 4 h iter + 30 min fixed-M probes. The constructive bound
  proves they fit at 2·aig; the SAT solver couldn't realize the
  construction. Options to close this gap: longer SAT runs, a smarter
  SAT encoding, or — most reliably — implementing a hand-rolled
  AIG → dual-rail AO converter that emits the De Morgan unrolling
  explicitly. The latter would turn the 2× bound into a constructive
  proof for every class without needing SAT.
* **n=4 m=2 and beyond**: not attempted — search space grows quickly.
* **Sub-2× lower bounds**: we only state savings as `≥ reported`. To
  state exact savings, the AO-side audit must come back `proven` for
  the relevant cases. Per the n=3 m=2 result, 9 of 34 sub-2× wins are
  fully proven on both sides; the rest are sound upper bounds.
* **`render_sub2x_formulas.py`**: currently 3-input only by default.
  Generalize to n=4 (uses sympy.simplify_logic; should just work with
  --n-in 4).
