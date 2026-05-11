# AIG vs dual-rail AND/OR over all 3-input 2-output NPN(P) classes

Empirical comparison of optimal gate count between `andexact` (AIG) and
`aoexact` (dual-rail monotonic AND/OR) on every NPN(P)-canonical Boolean
function with 3 inputs and 2 outputs. Class list at
`/work/npnp/classes_n3_m2.txt` (308 classes, header reports `count = 308`,
format `tt0 tt1` hex with bit 0 = f(0..0)).

## Headline

* **2× upper bound holds.** Constructively, dual-rail cost is `≤ 2 · AIG`
  (every polarized AND fans into one AND of positive rails and one OR of
  negative rails). Empirically no class exceeds 2× across all 308.
* **34 classes beat 2×** (10.4 %; 12.7 % of the non-degenerate 268).
  Of those, 9 are fully proven minima on both sides; 25 are sound
  upper-bound wins (AIG proven, AO `ub`).
* **Best proven savings: 20 % on `(2e, e2)`** (aig=5, ao=8). The shared
  cube is `a ∧ ¬b`, appearing in both F0 = `(a∧¬b) ∨ (b∧¬c)` and
  F1 = `(b∧c) ∨ (a∧¬b)`.
* No class has both POs trivial (constant or ±PI) and aig > 0. The
  patched `andexact`/`aoexact` synthesize the 4 fully-trivial classes
  at 0 gates via their new PO-only constant slots.

## Artifacts

```
/work/npnp/
  aig_npnp_n3_m2.tsv                  raw   andexact sweep
  audit_aig_n3_m2.tsv                 audit AIG probe at M = reported_k − 1
  aoexact_npnp_n3_m2.tsv              raw   aoexact main sweep (5 min/class)
  aoexact_npnp_n3_m2_retry.tsv        raw   aoexact retry on main-sweep timeouts (30 min/class)
  aoexact_npnp_n3_m2_retry2.tsv       raw   aoexact long-budget chase for one audit-flipped row
  aoexact_npnp_n3_m2_combined.tsv     derived: best-bound merge of {main, retry, retry2}
  audit_ao_n3_m2_combined.tsv         audit AO probe at M = combined_k − 1
```

These TSVs were produced by an earlier sweep harness that has since been
removed in favour of the bound-tracking state system. They remain as the
historical evidence behind this report, and
`verify_chain.py` / `render_sub2x_formulas.py` still consume them.

## Methods

Patched ABC fork on branch `andexact-relax-floor` (commits through the
PO-only const-slot patch, May 2026):
* **`andexact -M k -m`** — iter-mode AIG exact synthesis (walks `M` from
  0 upward, returns at first SAT).
* **`aoexact -M k -m`** — same for dual-rail AND/OR.
* Both engines emit `EXAN_RESULT:` / `EXAN_ITER_RESULT:` structured lines
  the harness parses; `proven` requires every smaller `M` to have returned
  UNSAT (not timeout).

Audit verdict (legacy pipeline) per row: `proven` (UNSAT at M = k − 1),
`upper_bound` (timeout at M = k − 1), `WRONG` (SAT at M = k − 1 — the
sweep's k was over-counted), `trivial` (k = 0; nothing to probe). The
`WRONG` verdict on the first audit pass surfaced one anomaly; see
[Audit-discovered correction](#audit-discovered-correction). The state
system that replaced this pipeline makes the same distinctions
structurally: `status=proven` requires both ends of the bound to be
settled, `gap` exposes an unproven upper bound, and a former-`WRONG`
row simply can't appear (the SAT outcome would already have tightened
`lo_sat`).

## AIG result

All 308 classes resolved to SAT. Audit verdicts: 304 proven + 4 trivial,
0 ub, 0 WRONG. **Every reported AIG count is the proven minimum.**

| AIG gates | count |
| --: | --: |
| 0 | 4 |
| 1 | 4 |
| 2 | 13 |
| 3 | 24 |
| 4 | 54 |
| 5 | 66 |
| 6 | 80 |
| 7 | 46 |
| 8 | 16 |
| 9 | 1 |
| **total** | **308** |

The four 0-gate classes are functions where both POs are trivial: `(00, 00)`,
`(00, aa)`, `(aa, aa)`, `(aa, cc)`. They were AIG = 2 in pre-patch sweeps;
the PO-only constant-slot patch makes constant outputs cost 0 gates.

The single 9-gate outlier is `(18, 96)`, whose F1 = `a ⊕ b ⊕ c`.

## AO result

Combined view, classified by audit verdict:

| AO gates | proven | upper-bound | total |
| --: | --: | --: | --: |
| 0 | 4 |   | 4 |
| 2 | 4 |   | 4 |
| 4 | 13 |   | 13 |
| 6 | 24 |   | 24 |
| 8 | 55 |   | 55 |
| 10 | 66 |   | 66 |
| 11 | 5 |   | 5 |
| 12 | 62 | 14 | 76 |
| 13 |   | 16 | 16 |
| 14 |   | 29 | 29 |
| 15 |   | 7 | 7 |
| 16 |   | 8 | 8 |
| 17 |   | 1 | 1 |
| **total** | **233** | **75** | **308** |

(`proven` here folds in the 4 trivial classes at aig=ao=0.)

## The 2× rule

| relation | proven (both sides) | sound (AIG proven, AO ub) | total |
| --- | --: | --: | --: |
| ao < 2 · aig | **9** | **25** | **34** |
| ao = 2 · aig | 220 | 50 | 270 |
| ao > 2 · aig | 0 | 0 | 0 |
| trivial (aig = 0) | 4 | — | 4 |

**Zero classes exceed 2×** across all 308.

* **proven sub-2×** — both AIG and AO sides have UNSAT at their `k − 1`
  probes. `ao_min < 2·aig_min` with both minima pinned exactly.
* **sound sub-2×** — AIG side proven; AO side's `k` is an upper bound.
  The inequality `ao_min ≤ ao_reported < 2·aig_min` still holds; the
  savings could grow if longer SAT runs lower `ao_reported`.

## Proven sub-2× wins

| (tt0, tt1) | aig | ao | saved | 2× % |
| --- | --: | --: | --: | --: |
| (2e, e2) | 5 | 8 | 2 | 20.0 |
| (1a, 5e) | 6 | 10 | 2 | 16.7 |
| (18, 24) | 7 | 12 | 2 | 14.3 |
| (18, 2e) | 7 | 12 | 2 | 14.3 |
| (0e, 2c) | 6 | 11 | 1 | 8.3 |
| (1a, 4a) | 6 | 11 | 1 | 8.3 |
| (1a, 4e) | 6 | 11 | 1 | 8.3 |
| (2e, 8e) | 6 | 11 | 1 | 8.3 |
| (8e, b2) | 6 | 11 | 1 | 8.3 |

`scripts/render_sub2x_formulas.py` emits the Boolean-formula table for all
34 sub-2× classes (proven + sound). The renderer round-trip-checks every
formula against the source truth-table before printing.

Concrete sharing in the 16.7 % winner `(1a, 5e)` (chain from the sweep):

```
F0  = n7          F0N = n9          F1 = n8         F1N = n5
n9  = n5 | n6     ← n5 also feeds F1N directly
n8  = n6 | n7     ← n7 also feeds F0; n6 also feeds n9
n7  = n2 | n4
n6  = aN & b      ← shared between F0N (via n9) and F1 (via n8)
n5  = n1 | n3
n4  = c & n0      ← n0 reused
n3  = cN & n0     ← n0 reused
n2  = a & cN
n1  = a & c
n0  = aN & bN     ← shared between n3 and n4
```

Two whole-gate savings against the constructive 12-gate (= 2·6) ceiling
come from `n0` (fans into both `n3` and `n4`) and `n6` (fans into both
F0N's and F1's cones).

## Audit-discovered correction

The first audit pass over the combined view flagged one row as `WRONG`:
**`(16, 96)`** was reported `ub:15`, but a fixed-`M = 14` probe with a
20-min budget returned SAT in 51 s — meaning the sweep had over-counted
by ≥ 1. A long-budget iter chase
(`scripts/aoexact_npnp_n3_m2.py --per-m-timeout 1800 --wall 10800`) landed
at `ub:14` (chain verified), so the true minimum is ≤ 14. With aig = 7,
`(16, 96)` thus sits at exactly 2× rather than above — and the 2× bound
holds globally.

The chase's output is stored as `aoexact_npnp_n3_m2_retry2.tsv` and folded
into the combined view by the same `combine_ao_sweep.py` that consumed the
main retry. The audit re-run on the tighter combined view returned
**0 WRONG** verdicts.

This is the kind of fault the audit harness exists to catch: `iter`
mode's `k = first SAT during walk` is only a true minimum when every
prior `M` returned UNSAT, *not timeout*. The structured-output patch
distinguishes these cleanly in `EXA10_ITER_RESULT`, but a sweep with a
short per-M budget can still report a too-large `k` (status = `ub`,
not `sat`). The audit's fixed-M probe with a longer budget is the
safety net.

## Degeneracy

A class is *degenerate* if some PO is constant or a single ±PI literal
(PO-degenerate) or some PI doesn't affect any PO (PI-degenerate). Such
classes collapse to a smaller (m or n) problem.

| degeneracy kind | count | % |
| --- | --: | --: |
| ≥ 1 PO trivial (const or ±PI) | 35 | 11.4 |
| ≥ 1 PI unused | 13 | 4.2 |
| Either kind | 40 | 13.0 |
| Fully non-degenerate | 268 | 87.0 |

**None of the 34 sub-2× classes is degenerate.** Every sub-2× class has
two non-trivial POs that depend on all 3 inputs. Stripping degenerate
classes from the denominator: **34 / 268 ≈ 12.7 %** of "real" 3-input
2-output classes beat 2×; **9 / 268 ≈ 3.4 %** are fully proven.

## Take-aways

* The 2× upper bound is tight and never violated.
* Sub-2× savings come exclusively from genuine inter-cone sharing.
  Mode is 1 gate; max is 2 gates (`(2e, e2)`, `(1a, 5e)`, `(18, 24)`,
  `(18, 2e)`).
* The audit's fixed-M probe is essential: a single `WRONG` verdict in
  the first audit pass exposed `(16, 96)`'s over-counted `k`. Without
  the audit, that row would have appeared to violate the 2× bound.
* `andexact`'s PO-only const-slot patch eliminates the "AIG ≥ 2 for
  constant POs" artifact. 4 classes now correctly sit at AIG = 0.

## Reproducing (state system)

```bash
cd /work/abc-synthesis-notes/scripts

# 1. AIG: iter walk + resume any remaining gaps.
python3 state_init.py --engine andexact --n-in 3 --n-out 2 \
    --classes /work/npnp/classes_n3_m2.txt \
    --output /work/npnp/state_aig_n3_m2_v0.tsv \
    --max-nodes 12 --per-m-timeout 30 --wall-timeout 180 --workers 32
python3 state_resume.py --input /work/npnp/state_aig_n3_m2_v0.tsv \
    --wall-timeout 1200 --workers 32

# 2. AO: derive lo_sat = 2·K, walk down from lo_sat - 1.
python3 state_init.py --engine aoexact --n-in 3 --n-out 2 \
    --aig-state /work/npnp/state_aig_n3_m2_v1.tsv \
    --output /work/npnp/state_ao_n3_m2_v0.tsv
python3 state_resume.py --input /work/npnp/state_ao_n3_m2_v0.tsv \
    --wall-timeout 300 --workers 32
# repeat with longer budgets to tighten remaining gap rows
python3 state_resume.py --input /work/npnp/state_ao_n3_m2_v1.tsv \
    --wall-timeout 1800 --workers 9

# 3. Final classification + sub-2× listing.
python3 state_show.py \
    /work/npnp/state_aig_n3_m2_v1.tsv \
    /work/npnp/state_ao_n3_m2_v2.tsv \
    --list-sub2x

# 4. Independent chain re-simulation (against the legacy TSVs that this
#    report is built from — adapting verify_chain.py to state TSVs is open work).
python3 verify_chain.py --input /work/npnp/aig_npnp_n3_m2.tsv \
    --n-in 3 --dialect aig
python3 verify_chain.py --input /work/npnp/aoexact_npnp_n3_m2_combined.tsv \
    --n-in 3 --dialect ao

# 5. Sub-2× Boolean-formula table (reads the legacy TSVs).
python3 render_sub2x_formulas.py --format markdown
```
