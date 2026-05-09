# `aoexact`: dual-rail monotonic AND/OR exact synthesis

Multi-output exact synthesis with two-input AND/OR gates, dual-rail primary
inputs, and dual-rail primary outputs. The synthesized network body contains
no inversions — every gate is monotonic in its fanins.

Implemented as engine `Exa10` in `src/sat/bmc/bmcMaj10.c`, exposed as the
ABC command `aoexact`. Built on top of the multi-output `andexact` work
(`Bmc_EsPar_t.nOuts`, comma-separated TT input).

## Command

```
aoexact [-NOMTSH <num>] [-dsmvh] <hex>[,<hex>...]
```

Same flag conventions as `andexact -O`: `-N` is the number of *logical*
inputs, `-O` is the number of *logical* outputs, `-M` is the gate count, `-T`
is the per-call wall timeout, `-H` selects the one-hot encoding (naive / seq
/ bim / cmd), `-d` dumps the result to BLIF, `-m` sweeps gate counts up from
zero. Truth tables are given comma-separated, one per logical output, in the
same hex MSB-first format as `andexact`.

Example:

```
abc -q "aoexact -N 2 -O 2 -M 6 -d 8,6"
```

synthesizes the half adder (carry = `8`, sum = `6`) in dual-rail form using
exactly six 2-input AND/OR gates.

## What's dual-rail here

Per the user-facing contract:

* Each logical input `x_k` is exposed to the synthesized network as **two**
  rails: the positive rail `x_k` and the negative rail `~x_k`.
* Each logical output is required in **two** polarities: the engine has to
  realize both `f_k` and `~f_k` as separate output cones over the monotonic
  body.
* Internal gates are 2-input AND or OR — one Boolean op bit per gate, no
  fanin polarity bits, no output polarity bits.

The interface artifact is one inverter cell per primary input in the dumped
BLIF, materializing the negative rail. The synthesis body itself contains
zero inversions.

## CNF shape

For `nIn` logical inputs and `nOut` logical outputs:

* PI rails: `2 * nIn` (1-based, positive rail = obj `2k+1`, negative = obj `2k+2`).
* Output slots: `2 * nOut` (slot `2k` = `f_k`, slot `2k+1` = `~f_k`).
* Internal nodes: `nNodes` (the `-M` argument).
* Source candidates per fanin: `nObjs = 2*nIn + nNodes`.
* Minterm enumeration: `2^nIn` (NOT `2^(2*nIn)` — the rails are dual, not
  independent).

CNF variable layout:

| Range | Meaning |
| --- | --- |
| Sel(n, k, j) | Fanin selector for node n's slot k pointing at source j (no polarity) |
| SelOut(o, j) | Output slot o picks source j (no polarity) |
| aux pool | Per-encoding auxiliaries for one-hot constraints |
| Op(n) | One bit per node: 0 = AND, 1 = OR |
| Value(j, place, m) | Computed wire value (place ∈ {fan0, fan1, out}) at minterm m |

Symmetry breaking carried over from `andexact` / Exa9:

* Strict fanin order `iA < iB` per gate (AND/OR are commutative; equality
  collapses the gate to one fanin).
* Topological order via the Sel domain.
* "Each gate must be used" — at least one consumer (later gate's fanin or
  some output selector) for every internal node.

New constraint specific to dual-rail:

* Forbid `Sel(n, 0, 2k+1) ∧ Sel(n, 1, 2k+2)` for every logical input k.
  The pair `(positive rail, negative rail of the same logical input)` is
  always strictly ordered, so this single 2-clause per (gate, logical input)
  pair rules out `AND(x, ~x) = 0` and `OR(x, ~x) = 1` constant gates.

## Comparison with AIG (`andexact`)

Both engines synthesize the same multi-output Boolean targets but optimize
for different gate models. Numbers below come from
`scripts/aoexact_benchmarks.py` (timeout 120 s/M unless noted).

| Bench | n_in | n_out | AIG (`andexact`) | dual-rail (`aoexact`) | ratio |
| --- | --- | --- | --- | --- | --- |
| half_adder | 2 | 2 | 3 | **6** | 2.0× |
| dec_2_to_4 | 2 | 4 | 4 | **8** | 2.0× |
| mux_2to1 | 3 | 1 | 3 | **6** | 2.0× |
| inc_3bit | 3 | 4 | 6 | **12** | 2.0× |
| full_adder | 3 | 2 | 7 | 12 ≤ x ≤ **14** | 1.71×–2.0× |
| popcnt3 | 3 | 2 | 7 | 12 ≤ x ≤ **14** | 1.71×–2.0× |
| cmp_2bit | 4 | 2 | 8 | 12 ≤ x ≤ **16** | 1.5×–2.0× |
| mul_2x2 | 4 | 4 | 8 | 13 ≤ x ≤ **16** | 1.6×–2.0× |
| add_2bit | 4 | 3 | 10 | 13 ≤ x ≤ **22** | 1.3×–2.2× |
| popcnt4 | 4 | 3 | timeout | unmeasured | — |

Bold values are proven optimal (SAT at that M, UNSAT at M-1). Ranges show
the gap between the highest UNSAT proof we got and the smallest SAT we
landed on; the optimum sits somewhere inside.

The four exactly-resolved cases all land at precisely **2.0×** the AIG count.
The intuition is that dual-rail forces both `f` and `~f` to exist as
independent monotonic cones with no inverter sharing, so each polarized AIG
AND becomes one monotonic AND plus a DeMorgan-dual OR for the complement
output. Two-times is also a cheap upper bound by construction (build the
AIG, then duplicate-and-flip).

The unresolved 4-input cases hit the same SAT-search wall the AIG version
of the harness does — the lower bounds from UNSAT sweeps are themselves a
useful artifact even when SAT can't close the gap.

## Verification

The BLIF dumper emits:

* `n` real `.inputs` (the logical inputs only).
* One `.names` inverter cell per PI to materialize the negative rail.
* Internal gates: `.names a b N\n11 1` (AND) or `.names a b N\n1- 1\n-1 1` (OR).
* Dual-rail outputs: `F0`, `F0N`, `F1`, `F1N`, …

`scripts/aoexact_benchmarks.py` re-simulates each dumped BLIF and checks
both the positive and negative rails of every output against the original
truth table.

## Files

* `src/sat/bmc/bmcMaj10.c` — engine.
* `src/sat/bmc/module.make` — build wiring.
* `src/base/abci/abc.c` — `Abc_CommandAOExact` and registration.
* `scripts/aoexact_benchmarks.py` (this repo) — verification harness.
