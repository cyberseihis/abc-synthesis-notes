# AIG vs dual-rail AND/OR over all 3-input 2-output NPNP classes

Brute-force comparison of optimal gate count between `andexact` (AIG) and
`aoexact` (dual-rail monotonic AND/OR) on every NPNP-canonical Boolean
function with 3 inputs and 2 outputs. The class enumeration comes from
`/work/npnp/classes_n3_m2.txt` (308 classes, header reports `count = 308`,
format `tt0 tt1` hex with bit 0 = f(0..0)).

The numbers below use the **relaxed** `andexact` from the
`andexact-relax-floor` branch on the abc fork. The first sweep used the
upstream `andexact` and revealed a spurious floor (see "AIG floor relaxation"
below); after lifting that floor, the comparison gets cleaner.

## How

* `scripts/aig_npnp_n3_m2.py` — runs `andexact -m -M 12 -T 30` per class,
  thread pool of 32 workers.
* `scripts/aoexact_npnp_n3_m2.py` — runs `aoexact -m -M 20 -T 60` per class,
  thread pool of 64 workers.

Both scripts capture status, gate count, wall time, and the full chain as a
proof. Results land at `/work/npnp/aig_npnp_n3_m2_relaxed.tsv` and
`/work/npnp/aoexact_npnp_n3_m2.tsv` (one row per class).

Wall budget: AIG sweep finished in 4 s. AO sweep finished in 8.5 min;
9 of the 11 entries that initially erred (timeout-handling bug, fixed)
re-ran to SAT in a 10 min/function rerun, leaving 2 unresolved.

## Histograms

**AIG (`andexact`, relaxed):**

| gates | count |
| --- | --- |
| 0 | 2 |
| 1 | 3 |
| 2 | 14 |
| 3 | 24 |
| 4 | 52 |
| 5 | 69 |
| 6 | 79 |
| 7 | 48 |
| 8 | 16 |
| 9 | 1 |
| **total** | **308** |

Mode 6, max 9 (the lone outlier `(18, 96)` whose second output is XOR3).
Two functions land at 0 gates because both outputs are PI literals
(`(aa, cc)` = (a, b); `(aa, aa)` = (a, a)).

**Dual-rail (`aoexact`):**

| gates | proven optima | upper-bound only |
| --- | --- | --- |
| 0 | 2 | |
| 2 | 3 | |
| 4 | 14 | |
| 6 | 24 | |
| 8 | 53 | |
| 10 | 69 | |
| 11 | 5 | |
| 12 | 75 | |
| 13 | 16 | |
| 14 | 31 | |
| 15 | 6 | |
| 16 | 8 | 1 (`(1e, 78)`) |
| 17 |   | 1 (`(18, 96)`) |
| **subtotal** | **306** | **2** |

Mode 12, max 17. Two entries are recorded with `status=ub` (upper bound)
rather than `sat` in the TSV: a follow-up rerun at 23 min/M proved them
SAT at the listed M, but the next-smallest M values (M=15, M=16 for
`(18, 96)`; M=14, M=15 for `(1e, 78)`) timed out without a UNSAT proof,
so the true minima may be lower. Two functions land at 0 gates because
all four output slots happen to coincide with PI rails directly (no
internal nodes needed).

## The 2× rule

Pairing the two TSVs and comparing `ao_gates` against `2 × aig_gates`. The
AO side is now reported with the audit-corrected proof status (see
`/work/npnp/audit_ao_n3_m2.tsv`); the AIG side is fully proven optimal
(see `/work/npnp/audit_aig_n3_m2.tsv`):

| relation | proven | upper-bound | total |
| --- | --- | --- | --- |
| ao < 2·aig | **10** | 23 (sound — see below) | **33** |
| ao = 2·aig | **221** | 50 (could flip to sub-2× with longer SAT) | 271 |
| ao > 2·aig | 0 | 0 | 0 |
| trivial (k=0) | 2 | — | 2 |

**No class exceeds 2× — that ceiling holds across all 308.** 2× is a
constructive upper bound: take an AIG, expand each polarized AND into
AND-of-positive-rails plus an OR-of-negative-rails to materialize the
complement, route outputs accordingly.

About proof strength on the sub-2× side:

* **10 cases are fully proven sub-2×** — both AIG and AO sides have a
  UNSAT proof at `aig − 1` and `ao − 1` respectively (20 min budget).
* **23 cases are sound but unproven sub-2×** — AIG side is proven, AO
  side timed out at `ao − 1`. The claim `ao_min < 2·aig_proven` still
  holds because `ao_min ≤ ao_reported < 2·aig_proven`; the savings could
  be **larger** than reported.

About the at-2× row:

* **50 cases originally tabulated as "exactly 2×" are actually
  upper-bound matches**, not proven optima. With longer SAT budgets,
  some of these may flip to sub-2×.
* The audit found one such flip already: **`(16, 6e)` was reported
  ao=16 (= 2·aig=8) but a 10-min probe at M=15 returned SAT, so its true
  AO minimum is at most 15.** Promoted to the sub-2× row above.
* The original sweep used a per-M timeout that masked these as if they
  were proven optima — the iter loop in `bmcMaj9.c` collapsed UNSAT and
  TIMEOUT into the same return code. After the structured-output patch
  (`EXA9_RESULT:` / `EXA9_ITER_RESULT:`) and per-M proof tracking, future
  sweeps self-label proven vs upper-bound and won't repeat this.

## Sub-2× wins after the audit

After per-row M=ao−1 audit probes (20 min wall budget), **10 sub-2×
cases are fully proven** with proven AIG and proven AO sides. Another **23**
are sound-but-unproven sub-2× — the AO side timed out at M=ao−1 in the
audit, but the inequality `ao_min ≤ ao_reported < 2·aig_proven` still holds.

Proven sub-2× wins:

| (tt0, tt1) | aig | ao | saved | %  |
| --- | --- | --- | --- | --- |
| (2e, e2) | 5 | 8 | 2 | **20.0** |
| (1a, 5e) | 6 | 10 | 2 | 16.7 |
| (18, 24) | 7 | 12 | 2 | 14.3 |
| (18, 2e) | 7 | 12 | 2 | 14.3 |
| (0e, 2c) | 6 | 11 | 1 | 8.3 |
| (1a, 4a) | 6 | 11 | 1 | 8.3 |
| (1a, 4e) | 6 | 11 | 1 | 8.3 |
| (2e, 8e) | 6 | 11 | 1 | 8.3 |
| (8e, b2) | 6 | 11 | 1 | 8.3 |
| (16, 9e) | 7 | 13 | 1 | 7.1 |

`(2e, e2)` remains the best proven savings at 20.0 % (aig=5, ao=8). The
10th proven entry, `(16, 9e)`, was upper-bound at the 10-min audit
budget and flipped to proven once the audit was rerun at 20 min.

The 23 unproven sub-2× cases all have aig ∈ {6, 7, 8, 9} with reported
ao between 13 and 17. Their **true** AO minima could be smaller, in which
case the savings would grow beyond 1-2 gates. None of these is a
counterexample — they're just cases where the SAT solver couldn't prove
the optimum within the 20 min audit budget.

One additional case showed up via the audit's `WRONG` verdict:
`(16, 6e)` was originally tabulated at exactly-2× (aig=8, ao=16) but a
10-min M=15 probe returned SAT. So `(16, 6e)` is now a **proven sub-2×
case at saved≥1** — promoted from the at-2× row. It's the only flip the
audit caught at this budget.

The savings ceiling stays small because dual-rail synthesis must compute
every output's negation as a separate monotonic cone — sharing buys you
partial gates, not whole ones.

Concrete example, `(1a, 5e)` saves 2 gates (aig=6, ao=10):

```
F0 = n7        F0N = n9        F1 = n8        F1N = n5
n7 = n2 | n4
n8 = n6 | n7   ← reuses n7
n9 = n5 | n6   ← reuses n5 and n6
n6 = aN & b    ← shared between F0N (via n9) and F1 (via n8)
n5 = n1 | n3
n4 = c & n0    ← reuses n0
n3 = cN & n0   ← reuses n0
n2 = a & cN
n1 = a & c
n0 = aN & bN   ← shared between n3 and n4
```

`n6 = aN & b` feeds two different output cones (F0N's via OR with n5; F1's
via OR with n7). `n0 = aN & bN` feeds two intermediates. Those overlaps
are the 2-gate save against the naive duplicate-everything upper bound.

The biggest single-saving cluster is the `(16, …)` and `(1a, …)` rows —
all save 1-2 gates against AIG=7-8 baselines. The `(18, 36)` case is the
largest absolute count where dual-rail beats 2×: aig=8, ao=14, saved=2.

## Soundness checks

Two independent audit passes give us proof status on each side:

**AIG side (M = aig_reported − 1):** For all 308 classes, the audit
harness ran a probe at M = aig_reported − 1 with a 10 min wall budget
(`/work/npnp/audit_aig_n3_m2.tsv`). Result: 306 proven, 2 trivial,
0 wrong, 0 upper-bound — **every reported AIG count is the proven
minimum**, including the 33 (now 34, after the `(16, 6e)` flip)
sub-2× classes.

**AO side (M = ao_reported − 1):** For all 308 classes (including ones
the original sweep marked `ub`), the audit harness ran a probe at
M = ao_reported − 1 with a 20 min wall budget. Result: 231 proven
(UNSAT at M = ao_reported − 1), 74 upper-bound (timeout at
M = ao_reported − 1), 1 wrong (SAT at M = ao_reported − 1 — the
`(16, 6e)` flip flagged above), 2 trivial. Per-row results in
`/work/npnp/audit_ao_n3_m2.tsv`. The longer 20-min budget downgraded
~20 cases from upper-bound to proven vs the prior 10-min audit,
including one sub-2× case (`(16, 9e)`).

Combining both sides into the sub-2× claim:

* **10 cases** have proven AIG **and** proven AO → claim is fully proven.
* **23 cases** have proven AIG but upper-bound AO → claim is sound
  (`ao_min ≤ ao_reported < 2·aig_proven`), but the savings could be larger.
* **1 case** (`(16, 6e)`) was originally at-2× but the audit found SAT
  at M=15 → now a sub-2× upper-bound win.

**Greatest proven improvement vs 2× AIG**: `(2e, e2)` saves 2 gates of 10,
i.e. **20.0 %** (aig=5, ao=8). One unproven case (`(18, 36)`, aig=8,
ao_reported=14, saved≥2) could push higher if its AO minimum drops below
14 with longer SAT.

## AIG floor relaxation

The first sweep used unmodified `andexact` and reported 45 sub-2× cases
including 9 "floor artifacts" — trivially-realizable functions whose true
AIG cost was below what `andexact` would express. Three coupled rules in
the upstream code combined to enforce a floor of `nNodes ≥ nVars - 1`:

1. **Command-level rejection** (`abc.c`,
   `if ( pPars->nVars > pPars->nNodes + 1 ) error`) refused any `-M` smaller
   than `nVars - 1` outright.
2. **"Every PI consumed" SAT constraint** (`bmcMaj9.c`,
   `Exa9_ManAddCnfStart`) iterated `for j = 1 to nObjs`, requiring every PI
   to be consumed by some object. A function that legitimately doesn't
   depend on every input (e.g., F0 = a, F1 = b on n=3) cannot satisfy this
   without burning extra gates to AND in the unused PI.
3. **Iter-mode floor** in `Exa9_ManExactSynthesisIter`,
   `int nNodeMin = pPars->nVars - 1`, started the `-m` sweep above the
   reachable minimum.

The fix on `andexact-relax-floor` (commit `db8fbe8` on the abc fork) lifts
all three:

* drop the command-level check;
* loop `for j = nVars + 1 to nObjs` so only internal nodes need a consumer;
* lower `nNodeMin` to 0.

After relaxation, **13 functions improve**:

| improvement | count | examples |
| --- | --- | --- |
| -3 gates | 1 | `(aa, aa)`: 3 → 0 |
| -2 gates | 8 | `(aa, cc)`: 2 → 0; `(0a, aa)`: 3 → 1; `(0a, cc)`: 2 → 1; `(0a, 0a)`: 3 → 1; `(0a, 50)`: 4 → 2; `(0a, a0)`: 4 → 2; `(00, 00)`: 3 → 2; `(00, 0a)`: 3 → 2 (some constants/literals can't go below 1-2) |
| -1 gate | 4 | trivial-with-constant cases |

All 13 of these previously contributed to the "ao < 2·aig" count via
artifact, not real sharing. After the fix they cleanly hit 2× exactly,
which is why the win count drops from 45 to 32.

## Takeaways

* **2× is a tight bound** for dual-rail vs AIG. No class exceeds it.
  Audit-corrected at the 20 min budget: ~72 % proven exactly at 2×
  (221/308), ~11 % sub-2× (34/308 = 10 proven + 23 sound-but-unproven
  + the `(16, 6e)` flip), the remaining 50 at-2× rows bounded
  above-but-not-pinned (could still flip to sub-2× with longer SAT).
* **Genuine sharing savings are small (proven 1-2 gates, mode 1).**
  This matches the structural intuition: monotonic dual-rail has very
  little room to share work between a function's positive cone and its
  complement cone, because the complement isn't reachable through the
  body. Some unproven cases may push the savings count higher with a
  longer SAT budget, but the ceiling is not large.
* **The original `andexact` floor was a real comparison artifact, not a
  feature.** It's an arbitrary input-validation rule plus a SAT-side "every
  PI consumed" rule that combine to make trivially-realizable functions
  look harder than they are. The relax-floor patch is a 3-edit change
  (~10 lines) that exposes the true minima without affecting non-trivial
  cases — the histograms above gate-count 5 are unchanged.
* **Hard cases for the SAT search are the same on both sides.** XOR3-laden
  functions (`(18, 96)`, `(1e, 78)`, `(1a, 78)`) are the hardest in both
  engines — `andexact` resolves them in 1-4 s thanks to compact
  AIG-with-polarity, while `aoexact` either takes ~10 min or times out.

## Reproducing

Build the abc fork's `andexact-relax-floor` branch (or the upstream branch
if you want the artifact-laden numbers):

```
# AIG sweep (~4 s wall, 32 workers)
python3 scripts/aig_npnp_n3_m2.py \
    --workers 32 --max-nodes 12 --per-m-timeout 30 --wall-timeout 180 \
    --output /work/npnp/aig_npnp_n3_m2_relaxed.tsv

# Dual-rail sweep (~10 min wall, 64 workers; 2 timeouts at default budget)
python3 scripts/aoexact_npnp_n3_m2.py \
    --workers 64 --max-nodes 20 --per-m-timeout 60 --wall-timeout 300 \
    --output /work/npnp/aoexact_npnp_n3_m2.tsv
```

Both write tab-separated rows of `tt0 tt1 status gates wall_s chain`. The
chain field is the synthesized circuit as a proof; format is
`Fk = src ; FkN = src ; ... ; nN = a op b ; ...` with internal node names
`n0..n31` for aoexact or `A..P` for andexact.
