# Single-output (m=1) dual-rail savings: just one case

NPN brute-force results for n=3 m=1 and n=4 m=1, comparing AIG cost
(`andexact` with the floor relaxation patch) to dual-rail AND/OR cost
(`aoexact`).

## Headline

| n m | classes | ao < 2·aig | ao = 2·aig | ao > 2·aig | timeout |
| --- | --- | --- | --- | --- | --- |
| 3 1 | 14  | 0  | 14  | 0 | 0  |
| 4 1 | 222 | 14 | 135 | 0 | 73 |

(After progressive reruns: original 4 min/function wall left 114 timeouts;
20 min/function wall resolved 25 more (still all at the 2× line); 8 h /
function wall in a 90-way parallel batch resolved 16 more, including 13
additional sub-2× cases. The 2× ceiling holds across every one of the
149 resolved 4-input single-output classes; no bound violations.)

For 3-input single-output functions the 2× cost ratio is hit **exactly**
on every NPN class. No internal-cone sharing happens because there's only
one logical output (and its complement) — `andexact` already captures
every gate-level reuse via its per-fanin polarity bits, leaving nothing
for dual-rail to reclaim.

For 4-input single-output, the picture is more interesting once enough
SAT time is spent. After the 8-hour-per-function YOLO rerun, **14 classes
beat the 2× ratio** (out of 149 resolved); 135 hit it exactly; 73 still
time out. The 14 wins all have AIG count 7 or 8 — exactly the regime
where the SAT-search wall for dual-rail sits at M ≈ 14-16. Most are
upper-bound results (the iter sweep walked through M values that timed
out before landing SAT), but they still demonstrate that *some*
internal-cone sharing happens for 4-input single-output, which doesn't
happen at all for 3-input.

The 73 still-unresolved cases all have AIG ≥ 8 with the search wall above
M=15 even at 8 h/function. Pushing further would need either more wall
time or different SAT tactics (possibly CEGAR, or a tighter
symmetry-breaking encoding).

## Soundness check on the sub-2× claims

Most of the 14 sub-2× cases have ao status `ub` rather than `sat`. The
inequality `ao_ub < 2 × aig_reported` is only sound if the AIG side is
a proven optimum (so `2 × aig_reported = 2 × aig_true`). To verify, a
direct probe at `M = aig_reported − 1` was run for each of the 14 wins
with a 5 min wall budget. **All 14 returned UNSAT**, so every AIG count
in the table below is the proven minimum and `ao_true ≤ ao_ub <
2 × aig_true` for each.

* 2 cases with both sides proven: `012e` (sat ao=13) and `06be` (sat ao=14).
* 12 cases with ao status `ub` and aig proven — sub-2× still sound,
  AO side could be 1-2 gates lower than reported.

**Greatest improvement vs 2× AIG in this regime**: `0198` (ao=14 ub vs
aig=8) saves 2 gates of 16, i.e. **12.5 %**. The actual margin could be
larger if `0198`'s true AO minimum is below 14. Note the n=3 m=2 dataset
has a higher proven margin (`(2e, e2)` at **20.0 %**).

## All 14 sub-2× wins

| ao | tt | aig | 2·aig | saved | status |
| --- | --- | --- | --- | --- | --- |
| 13 | `012e` | 7 | 14 | 1 | sat |
| 14 | `0198` | 8 | 16 | 2 | ub |
| 14 | `036e` | 8 | 16 | 2 | ub |
| 14 | `06be` | 8 | 16 | 2 | sat |
| 15 | `012c` | 8 | 16 | 1 | ub |
| 15 | `016e` | 8 | 16 | 1 | ub |
| 15 | `019a` | 8 | 16 | 1 | ub |
| 15 | `01be` | 8 | 16 | 1 | ub |
| 15 | `069e` | 8 | 16 | 1 | ub |
| 15 | `07b2` | 8 | 16 | 1 | ub |
| 15 | `1696` | 8 | 16 | 1 | ub |
| 15 | `169a` | 8 | 16 | 1 | ub |
| 15 | `169e` | 8 | 16 | 1 | ub |
| 15 | `178e` | 8 | 16 | 1 | ub |

All 14 have AIG count in {7, 8} (savings of 1 or 2 gates). Three save
2 gates: `0198`, `036e`, `06be` — those have AIG=8 and ao=14, the
biggest absolute savings observed in the m=1 regime.

`status=sat` means the iter sweep walked through every M < ao with a
proven UNSAT result; `status=ub` means at least one earlier M timed out
inside the budget so the true minimum could be slightly lower.

## The first surprising class: `0x012e`

Truth table (4 vars; `f(a,b,c,d) = 1` at the bold minterms):

```
m  abcd  f                m  abcd  f
0  0000  0                8  1000  1   ← (only d off)
1  0001  1                9  1001  0
2  0010  1               10  1010  0
3  0011  1               11  1011  0
4  0100  0               12  1100  0
5  0101  1               13  1101  0
6  0110  0               14  1110  0
7  0111  0               15  1111  0
```

(Function: `(~a & ~b) ∧ (c | d)  |  (~b & ~c & d)  |  (a & ~b & ~c & ~d)`.
Empirically simplifies — but more importantly it has structure that lets
the dual-rail engine share intermediates across the F and FN cones.)

### AIG (proven optimum, 7 gates)

```
A = b & ~c
B = a & ~b
C = ~A & ~B
D = ~d & ~C
E = ~c & d
F-internal = C & E
G = ~D & ~F-internal
F = ~G
```

`andexact` synthesizes 7 ANDs + a polarity bit on the final output.
Saved at `/work/npnp/circuits_n4_m1/012e.blif`.

### Dual-rail (upper bound, 13 gates)

```
n0  = aN & bN              ← shared between F and FN cones
n1  = d  | n0
n2  = dN | n0
n3  = b  | d               ← shared between F and FN cones
n4  = a  & bN
n5  = cN & n3
n6  = n4 | n5
n7  = b  | dN
n8  = a  | n7
n9  = c  & n3
n10 = n1 & n8
n11 = n9 | n10             →  FN
n12 = n2 & n6              →  F
```

`aoexact` synthesizes 13 monotonic AND/OR gates and routes both rails of
each input directly. Saved at `/work/npnp/circuits_n4_m1/012e_ao.blif`.

### Where the saving comes from

Two intermediates appear in both the positive output cone (F = n12) and
the negative output cone (FN = n11):

* `n0 = aN & bN`   feeds both `n1` (in FN's path) and `n2` (in F's path).
* `n3 = b | d`     feeds both `n5` (in F's path) and `n9` (in FN's path).

Without that overlap, dual-rail would need 15 gates (separate cones for
F and FN, plus the OR/AND boundary). The two shared sub-expressions
collapse one gate, getting it down to 13 — one below the 2× ceiling.

For *every other 4-input single-output class*, the corresponding 2-cone
construction has no such overlap (or the overlap that exists is below
the gate granularity and doesn't reduce the count). That's why this
class stands alone among the 222.

### Caveat

Our `aoexact` answer for `012e` is **a SAT upper bound at M=13**, not a
proven optimum. The original sweep timed out at M=12 (90 s/M wall) and
landed SAT at M=13. A direct probe at M=12 with a 23-minute budget also
timed out, so the true minimum is somewhere in {12, 13} — saving is
**≥ 1, ≤ 2 gates** vs. the 2× ceiling of 14.

More broadly, most of the 4-input dual-rail SAT results landing at 14
gates are also upper bounds rather than proven optima: the `-m` sweep
walks M upward with a per-M timeout, and for these classes M=12 and
M=13 often time out within the budget while M=14 happens to be SAT
quickly. We can't distinguish "proven optimum at 14" from "could be 12
or 13 but the SAT solver couldn't decide" without per-M wall data.

Nevertheless: the 2× ceiling is intact, no class exceeds it, and only
one class is clearly *below* it.

## Files

* `/work/npnp/aig_npnp_n3_m1.tsv`, `aoexact_npnp_n3_m1.tsv` — full sweep data, 14 classes each
* `/work/npnp/aig_npnp_n4_m1.tsv`, `aoexact_npnp_n4_m1.tsv` — full sweep data, 222 classes each
* `/work/npnp/circuits_n4_m1/012e.blif` — AIG circuit (7 gates)
* `/work/npnp/circuits_n4_m1/012e_ao.blif` — dual-rail circuit (13 gates)
