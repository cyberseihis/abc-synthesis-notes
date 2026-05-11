# Single-output (m=1) dual-rail savings

Comparison of optimal gate count between `andexact` (AIG) and `aoexact`
(dual-rail monotonic AND/OR) for every NPN-canonical Boolean function in:

* **n=3 m=1** — 14 classes (`/work/npnp/classes_n3_m1.txt`)
* **n=4 m=1** — 222 classes (`/work/npnp/classes_n4_m1.txt`)

Both engines use the patched ABC fork on branch `andexact-relax-floor`,
including the PO-only constant-slot patch (May 2026).

## Headline

| n m | classes | trivial | sub-2× proven | sub-2× sound | at-2× proven | at-2× sound | above-2× (SAT budget) | no-AO-bound |
| --- | --: | --: | --: | --: | --: | --: | --: | --: |
| 3 1 | 14 | 2 | 0 | 0 | 10 | 2 | 0 | 0 |
| 4 1 | 222 | 2 | 0 | 22 | 47 | 141 | 9 | 1 |

**Zero classes exceed 2× empirically**, modulo SAT-search budget
artifacts. The constructive 2× bound is mathematically proven (every
polarized AND `y = (a^pa) ∧ (b^pb)` becomes one AND on positive rails
plus one OR on negative rails — total 2·aig gates), so the 9 above-2×
rows in n=4 m=1 are SAT-search artifacts, not real violations.

## n=3 m=1: 2× is exact

All 14 NPN classes hit `ao = 2·aig` exactly or are trivial.
**No sub-2× class exists in this regime.**

| AIG gates | classes | corresponding AO gates |
| --: | --: | --: |
| 0 | 2 | 0 |
| 1 | 1 | 2 |
| 2 | 2 | 4 |
| 3 | 2 | 6 |
| 4 | 4 | 8 |
| 5 | 1 | 10 |
| 6 | 2 | 12 |

Audit verdicts:

* **AIG** (`audit_aig_n3_m1.tsv`): 12 proven + 2 trivial. Every AIG count
  is the proven minimum.
* **AO** (`audit_ao_n3_m1.tsv`): 10 proven + 2 trivial + 2 upper_bound.
  The two ub rows are AIG=6 / AO=12 — they could in principle drop to 11
  with a longer SAT budget, but the structural intuition (`andexact`
  captures gate-level reuse via per-fanin polarity bits) says 2× is tight
  here. With one logical output, F and FN have no sibling cones to share
  with.

## n=4 m=1: 22 sub-2× wins, all sound

| (sub-2x sound) | tt | aig | ao_bound | 2·aig | saved | audit verdict |
| --: | --- | --: | --: | --: | --: | --- |
| 1 | `0198` | 8 | 14 | 16 | 2 (12.5%) | WRONG (audit found SAT at 14) |
| 2 | `036e` | 8 | 14 | 16 | 2 (12.5%) | WRONG (audit found SAT at 14) |
| 3 | `06be` | 8 | 14 | 16 | 2 (12.5%) | upper_bound |
| 4 | `1bd8` | 9 | 16 | 18 | 2 (11.1%) | upper_bound |
| 5 | `012e` | 7 | 13 | 14 | 1 ( 7.1%) | upper_bound |
| 6 | `012c` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 7 | `016e` | 8 | 15 | 16 | 1 ( 6.2%) | WRONG |
| 8 | `019a` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 9 | `01be` | 8 | 15 | 16 | 1 ( 6.2%) | WRONG |
| 10 | `069e` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 11 | `07b2` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 12 | `1696` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 13 | `169a` | 8 | 15 | 16 | 1 ( 6.2%) | WRONG |
| 14 | `169e` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 15 | `178e` | 8 | 15 | 16 | 1 ( 6.2%) | upper_bound |
| 16 | `17ac` | 8 | 15 | 16 | 1 ( 6.2%) | WRONG |
| 17 | `0168` | 9 | 17 | 18 | 1 ( 5.6%) | upper_bound |
| 18 | `0692` | 9 | 17 | 18 | 1 ( 5.6%) | WRONG |
| 19 | `06b8` | 9 | 17 | 18 | 1 ( 5.6%) | WRONG |
| 20 | `168e` | 9 | 17 | 18 | 1 ( 5.6%) | WRONG |
| 21 | `1698` | 9 | 17 | 18 | 1 ( 5.6%) | WRONG |
| 22 | `1796` | 9 | 17 | 18 | 1 ( 5.6%) | upper_bound |

**0 of these are fully proven** on both sides. The AO column is the
best-bound combined view (with WRONG verdicts already folded in). For
each `audit verdict = WRONG`, the audit at `M = k − 1` returned SAT,
which means the true AO minimum is ≤ k − 1 *at least* — possibly even
lower with deeper chase rounds (we haven't recursed). For each
`audit verdict = upper_bound`, the audit's M-1 probe timed out, so the
displayed `ao_bound` may or may not be the true minimum.

The biggest empirical savings: **`0198` / `036e` / `06be`** save 2
gates out of the 16-gate ceiling (= **12.5 %**). All have AIG = 8.
For comparison, the n=3 m=2 dataset has a stronger 20 % proven win
(`(2e, e2)`).

### Class `0x012e` — first surprising case

Truth table (4 vars; bit i = f(i) with a = LSB):

```
m  abcd  f                m  abcd  f
0  0000  0                8  0001  1
1  1000  1                9  1001  0
2  0100  1               10  1010  0
3  1100  1               11  1011  0
4  0010  0               12  0011  1
5  1010  0               13  1011  0
6  0110  0               14  0111  0
7  1110  0               15  1111  0
```

ON-set = {1, 2, 3, 5, 8}. The function is non-trivial — depends on all
4 inputs. Saved at `/work/npnp/circuits_n4_m1/012e.blif` (AIG) and
`/work/npnp/circuits_n4_m1/012e_ao.blif` (dual-rail).

* **AIG (7 gates, proven minimum)** — see the BLIF.
* **AO (13 gates, ub)** — saved 1 gate vs 14-gate (= 2·7) ceiling.
  The dual-rail chain shares two intermediates between the F and FN
  cones; see the BLIF file for the structure.

## Above-2× rows: SAT-budget artifacts

9 n=4 m=1 classes still show `ao_bound > 2·aig` in the combined view
after all chase + probe rounds (main sweep, retry, retry-iter chase,
fixed-M probe at 2·aig). Each one is a class where the SAT solver
couldn't find the dual-rail chain at M ≤ 2·aig within budget. The
constructive bound proves the chain exists, so these are SAT-search
limits, not real 2× violations.

| tt | aig | 2·aig | best ao_bound | gap |
| --- | --: | --: | --: | --: |
| `019e` | 9 | 18 | 19 | +1 |
| `0368` | 8 | 16 | 17 | +1 |
| `06bc` | 8 | 16 | 17 | +1 |
| `079e` | 8 | 16 | 17 | +1 |
| `1668` | 9 | 18 | 21 | +3 |
| `166a` | 9 | 18 | 19 | +1 |
| `1896` | 9 | 18 | 19 | +1 |
| `19a6` | 8 | 16 | 17 | +1 |
| `2996` | 10 | 20 | 21 | +1 |

To convince ourselves these classes fit the 2× bound: write an explicit
AIG → dual-rail AO converter that emits the De Morgan unrolling (one
AND of positive rails + one OR of negative rails per AIG gate). That
would be a proof rather than a SAT search. Not implemented.

## One unresolved class: `299e`

`299e` (aig=10) timed out in every AO sweep round: main (10 min),
retry (2 h), retry2 chase (4 h). No AO chain is currently known for
this class at any M ≤ 25. The constructive bound says one exists at
M ≤ 20.

## Soundness checks

* **Chain verification**: `scripts/verify_chain.py` re-simulates every
  `sat`/`ub` chain in pure Python. All rows pass.
* **AIG-side audit** (`audit_aig_n4_m1.tsv`): 218 proven + 2 trivial +
  2 ub. Every reported AIG count is at most 1 gate higher than its
  proven minimum.
* **AO-side audit** (`audit_ao_n4_m1_combined.tsv` against the combined
  view): 47 proven + 2 trivial + 136 upper_bound + 36 WRONG. The WRONG
  verdicts have already been folded into the displayed `ao_bound`
  (i.e. we use the audit's `probe_M = k − 1` instead of the sweep's
  `k`), and the displayed bounds are correct given the audit data.

## Artifact layout

The TSVs in `/work/npnp/` (`aig_npnp_n*_m*.tsv`, `aoexact_npnp_n*_m*.tsv`
and the retry/combined/audit variants for n=4 m=1) were produced by an
earlier sweep harness that has since been removed in favour of the
bound-tracking state system. They remain as the historical evidence
backing the tables above, and `verify_chain.py` /
`render_sub2x_formulas.py` still read them.

## Reproducing (state system)

```bash
cd /work/abc-synthesis-notes/scripts

# AIG side: iter from 0, then resume with longer budget for any gaps.
python3 state_init.py --engine andexact --n-in 4 --n-out 1 \
    --classes /work/npnp/classes_n4_m1.txt \
    --output /work/npnp/state_aig_n4_m1_v0.tsv \
    --max-nodes 12 --per-m-timeout 60 --wall-timeout 600 --workers 32
python3 state_resume.py --input /work/npnp/state_aig_n4_m1_v0.tsv \
    --wall-timeout 1800 --workers 32

# AO side: derive lo_sat = 2·K from the proven AIG state, then walk down.
python3 state_init.py --engine aoexact --n-in 4 --n-out 1 \
    --aig-state /work/npnp/state_aig_n4_m1_v1.tsv \
    --output /work/npnp/state_ao_n4_m1_v0.tsv
python3 state_resume.py --input /work/npnp/state_ao_n4_m1_v0.tsv \
    --wall-timeout 1800 --workers 32
# repeat with bigger budgets until status counts stop changing
python3 state_resume.py --input /work/npnp/state_ao_n4_m1_v1.tsv \
    --wall-timeout 7200 --workers 12

# Final 2× classification.
python3 state_show.py \
    /work/npnp/state_aig_n4_m1_v1.tsv \
    /work/npnp/state_ao_n4_m1_v2.tsv \
    --list-sub2x
```

Use `--n-out 2` and a multi-output class list (`tt0 tt1` per line) for
the n=3 m=2 sweep.
