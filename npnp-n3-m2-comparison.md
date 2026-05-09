# AIG vs dual-rail AND/OR over all 3-input 2-output NPNP classes

Brute-force comparison of optimal gate count between `andexact` (AIG) and
`aoexact` (dual-rail monotonic AND/OR) on every NPNP-canonical Boolean
function with 3 inputs and 2 outputs. The class enumeration comes from
`/work/npnp/classes_n3_m2.txt` (308 classes, header reports `count = 308`,
format `tt0 tt1` hex with bit 0 = f(0..0)).

## How

* `scripts/aig_npnp_n3_m2.py` — runs `andexact -m -M 12 -T 30` per class,
  thread pool of 32 workers.
* `scripts/aoexact_npnp_n3_m2.py` — runs `aoexact -m -M 20 -T 60` per class,
  thread pool of 64 workers.

Both scripts capture status, gate count, wall time, and the full chain as a
proof. Results land at `/work/npnp/aig_npnp_n3_m2.tsv` and
`/work/npnp/aoexact_npnp_n3_m2.tsv` (one row per class).

Wall budget: AIG sweep finished in 4.4 s. AOA sweep finished in 8.5 min;
9 of the 11 entries that initially erred (timeout-handling bug, fixed) re-ran
to SAT in a 10 min/function rerun, leaving 2 unresolved.

## Histograms

**AIG (`andexact`):**

| gates | count |
| --- | --- |
| 2 | 12 |
| 3 | 26 |
| 4 | 53 |
| 5 | 73 |
| 6 | 79 |
| 7 | 48 |
| 8 | 16 |
| 9 | 1 |
| **total** | **308** |

Mode 6, max 9 (the lone outlier `(18, 96)` whose second output is XOR3).
Floor at 2 is `andexact`'s own input-validation rule
(`pPars->nVars > pPars->nNodes + 1` rejects `M < nVars - 1`), not the SAT.

**Dual-rail (`aoexact`):**

| gates | count |
| --- | --- |
| 0 | 2 |
| 2 | 3 |
| 4 | 14 |
| 6 | 24 |
| 8 | 53 |
| 10 | 69 |
| 11 | 5 |
| 12 | 75 |
| 13 | 16 |
| 14 | 31 |
| 15 | 6 |
| 16 | 8 |
| timeout | 2 |
| **total** | **308** |

Mode 12, max 16. Two unresolved at 10 min wall budget: `(18, 96)` and
`(1e, 78)`, both XOR3-flavored. Two functions land at exactly **0 gates**
because all four output slots happen to coincide with PI rails directly
(no internal nodes needed).

## The 2× rule

Pairing the two TSVs and comparing `ao_gates` against `2 × aig_gates`:

| relation | count |
| --- | --- |
| ao < 2·aig | **45** |
| ao = 2·aig | **261** |
| ao > 2·aig | 0 |
| unresolved | 2 |

**85 % of resolved classes hit the 2× ratio exactly**. None go above (good —
2× is a constructive upper bound: take an AIG, expand each polarized AND
into AND-of-positive-rails plus an OR-of-negative-rails to materialize the
complement, route outputs accordingly).

## Drilling into the 45 sub-2× wins

The list breaks down into three distinct mechanisms:

### 1. AIG floor artifacts (9 cases)

`andexact` rejects `M < nVars - 1` outright. For trivially-realizable
functions, this inflates the AIG count above the true minimum, while
`aoexact` (whose `-m` floor is 0) reports the actual optimum:

| tt0 tt1 | aig (ABC) | true | ao | comment |
| --- | --- | --- | --- | --- |
| `aa cc` | 2 | 0 | 0 | F0=a, F1=b, both literal |
| `aa aa` | 3 | 0 | 0 | F0=F1=a |
| `0a cc` | 2 | 1 | 2 | F0=a&~c (1 gate), F1=b literal |
| `0a aa` | 3 | 1 | 2 | F0=a&~c, F1=a literal |
| `0a 0a` | 3 | 1 | 2 | F0=F1=a&~c |
| `0a 50` | 4 | 2 | 4 | both outputs are `a&literal` shape |
| `0a a0` | 4 | 2 | 4 | similar |
| `00 0a` | 3 | irreducible | 4 | const + literal |
| `00 00` | 3 | irreducible | 4 | both constant 0 |

These aren't real "savings" — both engines could match the true minimum if
the AIG-side floor were removed.

The deeper reason for the ABC floor: `andexact` requires every PI to be
consumed by some object (gate fanin or output selector), and a tree
consuming `nVars` PIs needs `≥ nVars - 1` internal gates. `aoexact` only
requires *internal* nodes to be consumed; PI rails are allowed to dangle.
That difference is the structural source of these artifacts.

### 2. PI-rail output (1 case)

| tt0 tt1 | aig | ao | F1 | F1N |
| --- | --- | --- | --- | --- |
| `3c cc` | 5 | 6 | `b` | `bN` |

TT `cc = b` literal, so dual-rail's F1 and F1N both directly select PI rails
without spending any gates. The other output (`3c = b^c`) absorbs all the
cost. Saved 4 gates against the 2× ceiling.

This *is* still a real comparison artifact: `andexact` would also let F1
select the PI literal directly via its output-polarity bit, but the
`nNodes ≥ 2` floor forces it to spend at least 5 gates to legally close
the network.

### 3. Genuine internal-cone sharing (35 cases)

The remaining wins come from intermediate gates that get *reused* between
the positive and negative output cones. Most save 1 gate; a handful save
2-4.

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

Other notable saves in this category:

| tt0 tt1 | aig | ao | saved | shape |
| --- | --- | --- | --- | --- |
| `3c 3c` | 5 | 6 | 4 | F0=F1 (same function `b^c`), so the XOR cone serves both outputs |
| `0a 5a` | 5 | 6 | 4 | strong cross-output overlap |

Distribution of "saved" amounts among the 35 genuine wins:

| saved | count |
| --- | --- |
| 1 | 25 |
| 2 | 7 |
| 3 | 0 |
| 4 | 3 |

Mode 1, mean ≈ 1.4. The savings ceiling is small because dual-rail
synthesis fundamentally has to compute every output's negation as a
separate monotonic cone — sharing buys you partial gates, not whole ones.

## Takeaways

* **2× is a tight bound.** No class exceeded it; 85 % hit it exactly.
* **The "every PI consumed" rule in `andexact` is the dominant artifact**
  separating the two engines on trivial functions. It's an arbitrary
  validation rule, not a SAT constraint, and could be lifted for a more
  apples-to-apples comparison on small classes. `aoexact` doesn't enforce
  it (intentionally, since dual-rail can have logically unused inputs).
* **Hard cases for the SAT search are the same on both sides.** XOR3-laden
  functions (`(18, 96)`, `(1e, 78)`, `(1a, 78)`) are the hardest in both
  engines — `andexact` resolves them in 1-4 s thanks to compact
  AIG-with-polarity, while `aoexact` either takes ~10 min or times out.
* **Genuine sharing savings are small (1-4 gates) and rare (~11 % of classes).**
  This is consistent with the structural intuition: monotonic dual-rail
  has very little room to share work between a function's positive cone
  and its complement cone, because the complement isn't reachable through
  the body.

## Reproducing

```
# AIG sweep (4 s wall, 32 workers)
python3 scripts/aig_npnp_n3_m2.py \
    --workers 32 --max-nodes 12 --per-m-timeout 30 --wall-timeout 180 \
    --output /work/npnp/aig_npnp_n3_m2.tsv

# Dual-rail sweep (~10 min wall, 64 workers; 2 timeouts at default budget)
python3 scripts/aoexact_npnp_n3_m2.py \
    --workers 64 --max-nodes 20 --per-m-timeout 60 --wall-timeout 300 \
    --output /work/npnp/aoexact_npnp_n3_m2.tsv
```

Both write tab-separated rows of `tt0 tt1 status gates wall_s chain`. The
chain field is the synthesized circuit as a proof; format is
`Fk = src ; FkN = src ; ... ; nN = a op b ; ...` with internal node names
`n0..n31` for both engines (aoexact) or `A..P` (andexact).
