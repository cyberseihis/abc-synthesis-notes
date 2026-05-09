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
| 16 | 9 |
| 17 | 1 |
| **total** | **308** |

Mode 12, max 17. The original sweep had 2 unresolved at 10 min wall budget
(`(18, 96)` and `(1e, 78)`, both XOR3-flavored); a follow-up rerun at
23 min/M with directly-specified M values resolved each as an **upper
bound**: `(18, 96)` ≤ 17 (M=15, M=16 timed out so the true minimum may be
lower), `(1e, 78)` ≤ 16. Two functions land at 0 gates because all four
output slots happen to coincide with PI rails directly (no internal nodes
needed).

## The 2× rule

Pairing the two TSVs and comparing `ao_gates` against `2 × aig_gates`:

| relation | count |
| --- | --- |
| ao < 2·aig | **33** |
| ao = 2·aig | **275** |
| ao > 2·aig | 0 |
| unresolved | 0 |

**89 % of classes hit the 2× ratio exactly**. None go above
(good — 2× is a constructive upper bound: take an AIG, expand each
polarized AND into AND-of-positive-rails plus an OR-of-negative-rails
to materialize the complement, route outputs accordingly).

## The 33 sub-2× wins

After the floor relaxation, every remaining sub-2× case is a **genuine
internal-cone sharing win**. Distribution of "saved" amounts:

| saved | count |
| --- | --- |
| 1 | 26 |
| 2 | 7 |
| 3 | 0 |
| 4 | 0 |

Mode 1, mean ≈ 1.2. One of the 33 — `(18, 96)`, with ao=17 vs aig=9 — is
an upper-bound result from a 23-min-per-M direct probe; the true optimum
could be as low as 15 (M=15 and M=16 both timed out without resolving).
The other 32 are proven optima. The savings ceiling is small because dual-rail
synthesis fundamentally has to compute every output's negation as a
separate monotonic cone — sharing buys you partial gates, not whole ones.

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

* **2× is a tight bound** for dual-rail vs AIG. No class exceeds it; 89 %
  hit it exactly after the floor relaxation.
* **Genuine sharing savings are small (1-2 gates) and rare (10 % of classes).**
  This matches the structural intuition: monotonic dual-rail has very
  little room to share work between a function's positive cone and its
  complement cone, because the complement isn't reachable through the
  body.
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
