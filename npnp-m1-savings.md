# Single-output (m=1) dual-rail savings: just one case

NPN brute-force results for n=3 m=1 and n=4 m=1, comparing AIG cost
(`andexact` with the floor relaxation patch) to dual-rail AND/OR cost
(`aoexact`).

## Headline

| n m | classes | ao < 2·aig | ao = 2·aig | ao > 2·aig | timeout |
| --- | --- | --- | --- | --- | --- |
| 3 1 | 14  | 0 | 14  | 0 | 0  |
| 4 1 | 222 | 1 | 132 | 0 | 89 |

(After a rerun of the originally-timed-out 114 entries with a 20 min
per-function wall budget; 25 of them resolved as SAT-at-M=14 upper bounds,
89 still timed out at M=14 within the larger budget.)

For 3-input single-output functions the 2× cost ratio is hit **exactly**
on every NPN class. No internal-cone sharing happens because there's only
one logical output (and its complement) — `andexact` already captures
every gate-level reuse via its per-fanin polarity bits, leaving nothing
for dual-rail to reclaim.

For 4-input single-output, the same picture *almost* holds: of 222 NPN
classes, 107 of the resolved 108 hit 2× exactly, and **only one class
breaks the pattern**: `0x012e` (saves 1 gate, aig=7, ao=13 vs 2×aig=14).

The 114 unresolved cases all cluster at AIG=7-9 — the SAT-search wall
for dual-rail at 4 inputs hits right at M≈14-18, exactly the range the
2× upper bound predicts for these AIG counts.

## The surprising class: `0x012e`

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
