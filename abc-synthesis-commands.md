# ABC synthesis commands — a source-level walkthrough

This document covers the ABC commands that downstream flows (Yosys's
`abc.script`, OpenROAD's `abc_script`, the `&deepsyn`/`compress` scripts) rely
on. For each command it gives the command-handler location, the algorithmic
core, and enough internals to reason about cost models, options, and pitfalls.

All file paths are relative to the repo root (cloned at `/work/abc`). The
authoritative command-registration table is `src/base/abci/abc.c` (search for
`Cmd_CommandAdd`).

---

## 0  Background you need before reading the rest

### 0.1  Three AIG flavors

ABC carries three AIG data structures, and most commands have a "legacy" and a
"new" variant that differ only in which one they consume.

| Manager      | Object        | Where                           | Used by                                    |
| ------------ | ------------- | ------------------------------- | ------------------------------------------ |
| `Abc_Ntk_t`  | `Abc_Obj_t`   | `src/base/abc/`                 | The user-visible network. `b/rw/rf/rs`, `map`, `mfs`, `retime` operate on it. |
| `Aig_Man_t`  | `Aig_Obj_t`   | `src/aig/aig/`                  | "dar"-AIG: more compact, packed memory. `dc2`, `dch`, `dretime`, `if` consume it. |
| `Gia_Man_t`  | (just an int) | `src/aig/gia/`                  | Single-array AIG used by `&`-prefixed commands and CEC; the modern engine. |

Conversion: `Abc_NtkToDar` / `Abc_NtkFromDar` (see `src/base/abci/abcDar.c`).

The three managers all encode a 2-input AND graph with edge complement bits;
they only differ in storage layout. Algorithms are the same.

### 0.2  Algorithm primitives reused everywhere

* **Structural hash table.** Every AND is keyed by its (sorted) child literals.
  Insertion goes through `Abc_AigAndLookup` (`src/base/abc/abcAig.c:403`),
  which folds the trivial laws (`x&x = x`, `x&~x = 0`, `1&x = x`) and returns
  an existing node when one matches. Whenever an algorithm "adds" an AND it
  actually calls a function that hits this hash table first.

* **K-feasible cuts.** A cut for node `n` is a set of nodes whose conjunction
  of fanout cones contains `n`. ABC computes them bottom-up by merging child
  cut sets (`src/opt/cut/`, `src/map/if/ifCut.c`). These bound the inputs
  the operator considers around each node.

* **Reconvergence-driven cuts.** A different cut shape used by `refactor` and
  `resub`: grow the leaf set greedily, biased toward leaves with high
  reconvergence with already-included nodes; bounded by `nNodeSizeMax`
  inputs. Implemented in `src/base/abci/abcReconv.c`.

* **MFFC (Maximum Fanout-Free Cone).** The set of nodes that would become
  dangling if `n` were replaced. To label one in-place, ABC uses the
  "boundary trick": temporarily increment the fanout count of the leaves so
  they look "external", then DFS marking nodes whose every fanout is marked.
  Restoring the leaf counts gives the MFFC. The labelled count `nNodesSaved`
  is the size of the MFFC.

* **NPN equivalence + library.** All 4-input Boolean functions partition
  into 222 NPN classes (input permutation, input negation, output negation).
  The rewriting library (`src/opt/rwr/rwrLib.c`) precomputes, for each class,
  several optimal AIG implementations.

* **Dec_Graph / Hop / Kit.** Common factored-form / decomposition graph data
  structures. Used as a vehicle for "here's the new local function in DAG
  form, please materialize me into the AIG":
    * `Dec_GraphToNetworkCount(root, graph, NodeMax, LevelMax)` — counts how
      many AIG nodes would actually be added if the graph were materialized,
      reusing existing nodes via `Abc_AigAndLookup`. Returns `-1` if a level
      bound would be violated. This is the gain estimator that every
      DAG-aware operator uses.
    * `Dec_GraphUpdateNetwork(root, graph, fUpdateLevel, nGain)` — actually
      replaces the MFFC with the new structure; also drives reverse-level /
      required-time bookkeeping.

* **The `b/rw/rf/rs` cocktail.** From `abc.rc`:
    ```
    alias resyn       "b; rw; rwz; b; rwz; b"
    alias resyn2      "b; rw; rf; b; rw; rwz; b; rfz; rwz; b"
    alias resyn3      "b; rs; rs -K 6; b; rsz; rsz -K 6; b; rsz -K 5; b"
    alias compress    "b -l; rw -l; rwz -l; b -l; rwz -l; b -l"
    alias compress2   "b -l; rw -l; rf -l; b -l; rw -l; rwz -l; b -l; rfz -l; rwz -l; b -l"
    alias choice      "fraig_store; resyn; fraig_store; resyn2; fraig_store; fraig_restore"
    ```
    The trailing `z` in `rwz`/`rfz`/`rsz` enables zero-cost moves (gain ≥ 0 instead of > 0). The `-l` suffix activates the level-update mode (the move is rejected if it lengthens the longest path).

---

## 1  `strash` — structural hashing

Files: `src/base/abci/abcStrash.c`.

Walks the network in DFS order and re-inserts every AND through
`Abc_AigAnd → Abc_AigAndLookup`. Two effects:

* Gathers identical subgraphs into a single node (they hash to the same key).
* Folds the trivial laws (constant absorption, `x&~x → 0`).

Strash is the canonical "into-AIG" entry point; most other commands assert
`Abc_NtkIsStrash(pNtk)`. It removes choice nodes (warn at line 60).

The function `Abc_NtkRestrash` (line 49) re-runs strash on an already-strashed
network — used as a self-check after invasive transforms.

---

## 2  `balance` (`b`) — algebraic AIG balancing

Files: `src/opt/dar/darBalance.c` (used by the `b` command via
`Abc_NtkBalance` → `Dar_ManBalance` after a quick AIG conversion). The legacy
implementation lives in `src/base/abci/abcBalance.c`.

### What it does

For every AND-tree (or XOR-tree) of identical type bounded by fanout >1
nodes, balance reorders the operands to minimize the depth of the
implementing AIG. It is **purely associativity-based** — Boolean function is
unchanged.

### How it does it

1. **Collect a "supergate".** For each AND node `r`,
   `Dar_BalanceCone_rec` (`darBalance.c:106`) collects all leaves of the
   maximal AND-tree rooted at `r`: it walks down through children of the
   same type (`Aig_ObjType(child) == Aig_ObjType(r)`) that are not shared
   (`Aig_ObjRefs == 1`). Crossing a fanout-cone boundary or a type boundary
   stops the recursion and the node is recorded as a leaf.

2. **Deduplicate.** `Dar_BalanceUniqify` (`:57`) sorts leaves by literal,
   removes duplicates (`x & x = x`), kills the supergate if `x & ~x` appears
   (`AND` becomes `0`), and removes pairs of identical XOR operands.

3. **Recurse.** Each leaf is itself rebuilt by `Dar_Balance_rec` (`:502`)
   before being used, so leaves carry already-balanced levels.

4. **Build a balanced tree.** `Dar_BalanceBuildSuper` (`:399`) sorts the
   leaves by *current* level, then repeatedly pops the two cheapest leaves,
   creates an AND of them (`Aig_Oper`, which itself goes through structural
   hashing — so existing AND nodes are reused), and inserts the result back
   into the sorted list. This is Huffman coding on levels: shallowest leaves
   are paired first so the depth grows logarithmically.

   `Dar_BalancePermute` does a small look-ahead: if among the leaves at the
   current minimum level there is a pair whose AND already exists in the
   strash table, swap into a pairing that triggers reuse.

### Knobs

* `-l` (`fUpdateLevel`): pass `1` to keep timing cones balanced for
  delay-bounded later moves.
* The `Aig_BaseSize` / `USE_LUTSIZE_BALANCE` macro path (commented out by
  default) builds K-LUT-bounded supergates instead of binary trees — used
  when balance is run as a precursor to LUT mapping.

### Why it matters

Balance is the cheap depth-only cleanup that runs between every other
operator in `compress*`. It does not reduce node count by itself but creates
the regular tree shape that `rewrite` / `refactor` / `resub` need to
recognize patterns.

---

## 3  `rewrite` (`rw`, `rwz`) — DAG-aware rewriting

Files: `src/base/abci/abcRewrite.c` (driver), `src/opt/rwr/` (engine and
4-input library), `src/opt/rwr/rwrEva.c` (per-node evaluation).

### What it does

For every AND, look at all of its 4-input cuts; for each cut, look up its
truth table's NPN class in a precomputed library of equivalent AIG
sub-circuits; pick the best replacement that, after MFFC accounting, reduces
node count.

### How it does it

`Rwr_NodeRewrite` in `rwrEva.c:59` is the per-node engine.

1. **Cuts.** `Abc_NodeGetCutsRecursive(pManCut, pNode, 0, 0)` returns all
   k-cuts (default `k=4`). The rewrite manager only cares about full
   4-cuts (`pCut->nLeaves < 4` is skipped, `:96`).

2. **Library lookup.** The library (built by `rwrLib.c` and persisted to
   the static array in `rwrTemp.c`) maps each 4-input truth table to:
    * `pPerms[uTruth]` — index into a pre-tabulated input permutation; this
      tells you how to permute the 4 fanins so that the truth table reaches
      its NPN canonical form.
    * `pPhases[uTruth]` — bitmask of which input phases / output phase need
      complementing.
    * `pMap[uTruth]` — index of the NPN class.

   Per class, `vClasses[i]` is a list of `Rwr_Node_t *`, each pointing to a
   `Dec_Graph_t` realization of the class (multiple AIG implementations per
   class).

3. **MFFC count.** Lines 138–148 push fanout counters on the cut leaves so
   they look "outside the network", then `Abc_NodeMffcLabelAig` returns the
   number of nodes that would become dangling if `pNode` were replaced —
   this is `nNodesSaved`.

4. **Evaluate each candidate.** `Rwr_CutEvaluate` (`:253`) iterates the
   class's subgraph list. For each `pGraphCur`, `Dec_GraphToNetworkCount`
   simulates re-materializing it: it walks the graph bottom-up, calling the
   strash hash table at each AND. Existing AND nodes count as zero added;
   only new ANDs count. The tally is `nNodesAdded`. The first candidate
   with `nNodesAdded ≤ nNodesSaved` is feasible; among feasible ones, the
   cheapest wins. A delay constraint (`LevelMax`) rejects candidates whose
   computed level exceeds the required time.

5. **Apply.** If `GainBest > 0` (strict gain) or `fUseZeros && GainBest ==
   0` (the `z` flag), `Dec_GraphUpdateNetwork` replaces the MFFC with the
   new graph. Reverse levels and required times are updated in place so
   subsequent nodes see the new timing.

### Knobs

* `-l`: pass `fUpdateLevel = 1` — accept moves only if level bound holds.
* `-z` (`rwz`): allow zero-gain moves. This usually helps because a future
  `rf` or `rs` round can extract gain from the new shape.
* `-N` (`fPlaceEnable`): wire to a placement-aware update path
  (`Abc_PlaceUpdate`); off by default.

### Why it matters

Rewrite is the workhorse local optimization. It is fast (constant-time
per-cut lookup) and deterministic (the library is fixed). Without it, the
later phases have nothing to chew on.

---

## 4  `refactor` (`rf`, `rfz`) — algebraic refactoring

Files: `src/base/abci/abcRefactor.c`. Modern variant: `src/opt/dar/darRefact.c`.

### What it does

For each node, take a *larger* (default 10-input) reconvergence-driven cut,
compute the cone's truth table, derive a fresh factored form from the truth
table, count the cost of materializing it (with structural-hash reuse), and
keep it if it shrinks the AIG.

### How it does it

`Abc_NtkRefactor` and `Abc_NodeRefactor` in `abcRefactor.c`:

1. **Cut.** `Abc_NodeFindCut(pManCut, pNode, fUseDcs)` returns a
   reconvergence-driven cut limited to `nNodeSizeMax = 10` leaves and
   `nConeSizeMax = 16` interior nodes (defaults; `-N` and `-K` override).

2. **Truth table.** `Abc_NodeConeTruth` (`abcRefactor.c:81`) walks the cone
   in topological order, simulating booleans bit-by-bit on
   `Abc_Truth6WordNum(nVars)` 64-bit words.

3. **Constant short-circuit.** If the cone is constant 0 or 1 (which
   *is* possible because of don't-cares contributed by upstream
   simplifications), replace with `const0`/`const1` immediately —
   `nLastGain = nMffc`.

4. **Factor.** `Kit_TruthToGraph` (defined in `bool/kit/`) computes an ISOP
   from the truth table and runs algebraic factoring on the SOP, returning
   a `Dec_Graph_t`. The factoring uses common-cube extraction +
   Boole-divisor selection — the same algorithm SIS used.

5. **Cost & accept.** Same MFFC labeling, same `Dec_GraphToNetworkCount`,
   same accept-rule as rewrite, except the threshold is `nMinSaved` (passed
   by the user via `-N`; with `-z` it becomes 0 for zero-cost moves).

### Knobs

* `-N <k>`: max input count of the cone (default 10).
* `-Z`/`-z`: allow zero-gain moves (`fUseZeros`).
* `-D`: use observability don't-cares in factoring (`fUseDcs`).
* `-l`: level-aware acceptance.

### Why it matters

Where rewrite is library-bounded to 4 inputs, refactor handles up to 10
inputs at the cost of building a fresh factored form per cone. It typically
finds gain that rewrite cannot, but it is much slower (BDD/ISOP cost grows
with cone size) and produces less regular shapes — that is why `compress2`
sandwiches rewrite + refactor + balance.

---

## 5  `resub` (`rs`, `rsz`) — Boolean resubstitution

File: `src/base/abci/abcResub.c` (modern engine — `darResub.c` is empty).

### What it does

For each node, try to express it as an AND/OR of ≤ `k` already-existing
nodes from a "divisor pool" inside its reconvergence-driven cut. If the
node's MFFC has more than `k` nodes the move is gainful by `nMffc - k`.

### How it does it

`Abc_NtkResubstitute` (`abcResub.c:144`) is the driver; per-node logic is
`Abc_ManResubEval` and the ladder of `Abc_ManResubDivs0/1/12/2/3` at
`abcResub.c:2008–2085`.

1. **Cut.** `Abc_NodeFindCut(pManCut, pNode, 0)` — same reconvergence cut as
   refactor but bounded by `nCutMax` (default 8 for `rs`, 6/5 in
   `resyn3`).

2. **Divisor collection.** `Abc_ManResubCollectDivs` (`:474`) gathers all
   internal nodes inside the cone (between the cut leaves and the root) plus
   the cut leaves themselves. Each gets simulated with random patterns
   (~32 words, simple tabular eval).

3. **Care-set.** Optional ODC computation
   (`Abc_NtkDontCareCompute(pManOdc, pNode, vLeaves, p->pCareSet)`) for
   `-L <levels>` of fanout simulation. A divisor only needs to match the
   target on the care-set patterns.

4. **The k-step ladder.** `Abc_ManResubEval` tries replacements of
   increasing complexity, returning at the first success:

    * `Divs0` — the node's truth equals some divisor's truth (or its
      negation). Gain = full MFFC; replacement is just that divisor.
    * `Divs1` — node = AND/OR of one divisor and one literal of another.
      Gain = `nMffc - 1`.
    * `Divs12` — node = AND-OR-AND of three divisors (one shared). Gain =
      `nMffc - 2`.
    * `Divs2` — node = AND/OR of two two-literal terms (4 divisors, 2 new
      ANDs). Gain = `nMffc - 2`.
    * `Divs3` — three new ANDs. Gain = `nMffc - 3`.

   `DivsS` and `DivsD` (`:916`, `:992`) precompute single-level and
   two-level divisor combinations; the matching itself is bitwise on the
   simulation vectors. Because the simulation may not be functionally
   distinguishing, a SAT-based check is performed before commit
   (`pManRes->pSat`) in some paths. False positives just waste work; they
   never produce a wrong result.

5. **Apply.** Replacement is converted to a `Dec_Graph_t` and committed via
   `Dec_GraphUpdateNetwork`.

### Knobs

* `-K <k>`: max cut size (default 8). `resyn3` uses 6 and 5.
* `-N <s>`: max steps in the ladder (default 1).
* `-F <l>`: ODC fanout depth (`nLevelsOdc`).
* `-z`, `-l` as elsewhere.

### Why it matters

Resub finds gain that rewrite + refactor cannot: it can collapse a whole
sub-cone into an AND of two pre-existing internal signals when the Boolean
relationship happens to hold. It is sensitive to the divisor pool — that's
why `resyn3` runs three different cut sizes consecutively.

---

## 6  `restructure` (`re`, `rez`) — DSD-based local restructuring

File: `src/base/abci/abcRestruct.c`. **Note**: registration is commented out
in `abc.c:1003` — kept around for documentation / experiments. Yosys does
not call it.

For each node, take a k-feasible cut, build a BDD of the cone, compute its
Disjoint Support Decomposition (DSD) tree (OR/EXOR/PRIME nodes), and
recursively re-emit it as an AIG, balancing OR/EXOR by levels and reusing
existing AND nodes via `Abc_AigAndLookup` (`:655`). Gives up if the new node
count exceeds the MFFC.

In effect: refactor with DSD instead of SOP-factoring as the normal-form
producer.

---

## 7  `dc2` — combinational AIG optimization on the dar manager

Files: command handler `Abc_CommandDc2` at `src/base/abci/abc.c:17941`;
implementation `Abc_NtkDC2` at `src/base/abci/abcDar.c:1669`.

`dc2` is `compress2` (the abc.rc alias `b -l; rw -l; rf -l; b -l; rw -l;
rwz -l; b -l; rfz -l; rwz -l; b -l`) implemented on the **dar `Aig_Man_t`
manager** instead of the legacy `Abc_Ntk_t` — it converts in, runs
`Dar_ManCompress2`, and converts back. Each operator is the dar version
(`Dar_ManRewrite`, `Dar_ManRefactor`, `Dar_ManBalance`) and consumes 2–3×
less memory and CPU than the equivalent abc.rc script. Same outputs (modulo
node IDs).

The script body is in `src/opt/dar/darScript.c:235`. Sequence:

```
Aig_ManDupDfs
b -l    (Dar_ManBalance)
rw -l   (Dar_ManRewrite, fUseZeros=0, fFanout=1)
rf -l   (Dar_ManRefactor)
b -l
rw -l
rwz -l  (fUseZeros=1)
b -l
rfz -l
rwz -l
b -l
```

`-b -f -p -l -v` cmdline switches toggle balance, fanout-tracking,
power-aware rewrite, level update and verbose, respectively.

---

## 8  `fraig` — functionally reduced AIG via SAT

Files: command handler `Abc_CommandFraig` at `src/base/abci/abc.c`;
implementation `Abc_NtkFraig` at `src/base/abci/abcFraig.c:58`; engine in
`src/proof/fraig/`.

### What it does

Walks the AIG bottom-up. At every AND, ask: "is there an already-built node
that is functionally equivalent to this one?". If yes, redirect future
references to the existing node, eliminating the duplicate.

### How it does it

`Fraig_NodeAndCanon` (`src/proof/fraig/fraigCanon.c:52`) is the core:

1. **Trivial cases** (constants, `x & ~x`, etc.) — handled before any work.

2. **Structural hashing** — `Fraig_HashTableLookupS`. Hits when the two
   incoming literals already form an AND. This is the cheap dedup step.

3. **Simulation classes.** Every node carries a vector of simulated values
   on (initially) random input patterns. `Fraig_HashTableLookupF` /
   `…LookupF0` hash on the simulation signature. Nodes with identical
   simulation vectors *might* be functionally equivalent.

4. **SAT proof.** `Fraig_NodeIsEquivalent(pNodeOld, pNodeNew, nBTLimit, ...)`
   asserts a miter that the two nodes' XOR is 1, runs a SAT solver with
   conflict limit `nBTLimit` (default 100). Outcomes:
    * **UNSAT** → nodes are equivalent. Set `pNodeNew->pRepr = pNodeOld`.
      If choicing is enabled (`fChoicing=1`), append `pNodeNew` to
      `pNodeOld->pNextE`'s linked list of choice alternatives instead of
      discarding it. Otherwise drop `pNodeNew`.
    * **SAT (counterexample)** → nodes are inequivalent. The counterexample
      pattern is appended to the simulation vectors so future simulation
      buckets distinguish them. Keep both nodes.
    * **TIMEOUT** → bail out without committing equivalence.

5. **Repeat** for every new AND. The result is "functionally reduced":
   structurally distinct ANDs are guaranteed inequivalent (modulo SAT
   timeouts).

### Knobs (matching `abc -h fraig`)

* `-R`/`-D` — number of random / dynamic simulation patterns (`nPatsRand`,
  `nPatsDyna`).
* `-C` — SAT conflict limit per pair (`nBTLimit`).
* `-r` — proof in reverse topological order.
* `-c` — record choices (`fChoicing`) for downstream mappers.
* `-p` — try to prove the network is a constant-0 miter (`fTryProve`).

### `ifraig` (incremental fraig)

Files: `Abc_CommandIFraig` → `Abc_NtkDarFraig` (`abcDar.c:1500`) → 
`Fra_FraigPerform` (`src/proof/fra/fraCore.c`).

Same idea, but built on the `Aig_Man_t` manager and **incremental**: it
keeps the SAT solver alive across nodes, reusing learned clauses, and
re-simulates dynamically on every counterexample. In practice ifraig is
strictly faster than fraig at the same `-C`. Yosys uses `ifraig` in its
`abc.script`.

### `dch` — delay-aware choices

Files: `Abc_CommandDch` (`abc.c:18130`) → `Abc_NtkDch`
(`src/base/abci/abcDar.c:1722`) → `Dar_ManChoiceNew` (`darScript.c:849`).

A choice node is an AIG node carrying a linked list of *functionally
equivalent* alternatives so a downstream mapper (`if`, `map`) can pick the
one that maps best. `dch` does this:

1. **Synthesis phase** — `Dar_ManChoiceSynthesis` (`darScript.c:345`) runs
   three different scripts in series (the original AIG → `compress` →
   `compress2`) and stores the three resulting AIGs.

2. **Choice phase** — `Dch_ComputeChoices` or `Cec_ComputeChoices` builds a
   miter of the three AIGs (since they have the same I/O), strash-hashes
   them into one combined network, and runs SAT-based equivalence checking
   to merge functionally identical nodes. Equivalences are recorded as
   choice links rather than collapsed.

The three input AIGs are deliberately produced by different rewriting
sequences so the mapper sees a diverse set of structural alternatives for
each function.

### Knobs

* `-C` — SAT conflict limit.
* `-S` — number of simulation rounds.
* `-p` — power-aware (synthesis stage).
* `-x` — switch to GIA-based engine (`fUseGia → Cec_ComputeChoices`).
* `-l`, `-f` — light synthesis / `Dar_NewChoiceSynthesis`.

In Yosys's flow `dch` typically immediately precedes `if` so that the
mapper exploits the alternatives.

---

## 9  Sequential — `retime`, `dretime`

File: `src/opt/ret/retCore.c` is the dispatcher; sub-modes in
`retArea.c`, `retIncrem.c`, `retLvalue.c`.

### Modes

`retime -M <n>` selects one of six algorithms (`Abc_NtkRetime`, `:47`):

| `-M` | Name              | Implementation                | What it does                                                                       |
| ---- | ----------------- | ----------------------------- | ---------------------------------------------------------------------------------- |
| 1    | forward           | `Abc_NtkRetimeIncremental`    | Greedy: while a node has all-latch fanin (or symmetric for backward), pull latches forward. |
| 2    | backward          | same                          | Mirror of `1`.                                                                      |
| 3    | min-area          | `Abc_NtkRetimeMinArea`        | One forward pass, then iterated backward passes; each pass computes a min-cut between latch outputs (sources) and POs+latch inputs (sinks). The min-cut becomes the new latch boundary. Iterated until no further reduction. Backward passes also extract "pre-circuit" combinational logic into a side network used to recompute initial values. |
| 4    | min-delay         | `Abc_NtkRetimeIncremental`(`fMinDelay=1`) | Forward + backward incremental retiming under a level/delay budget (`-D`).        |
| 5    | min-area+min-delay| both                         | `3` then `4`.                                                                       |
| 6    | Pan's algorithm   | `Abc_NtkRetimeLValue`         | Treats min-clock-period retiming as a longest-path problem: assign each node an `l-value` (= arrival time minus retimable latches), binary search clock period, derive lags. **Lags are computed but not committed** — the function prints "Currently, network is not modified." Useful for budgeting only. |

The min-area pass (`retArea.c`) is the canonical Leiserson–Saxe formulation:
build the FFG, mark TFI of POs and TFO of current latches, run a max-flow
between them, the resulting min-cut tells you where the new latches go.
Initial values for the new latches are recovered by simulating the
"pre-cut" combinational network in `Abc_NtkRetimeInitialValues`.

### `dretime`

Same algorithms reimplemented on `Aig_Man_t` (`Abc_NtkDarRetime*` in
`abcDar.c`). Faster on large designs. Default mode is min-area iterative
(20 iterations).

### Knobs

* `-M <n>` — mode (default 5).
* `-D <n>` — delay limit (mode 4/5).
* `-f` / `-b` — forward-only / backward-only restrictions.
* `-I <n>` — Pan-mode iteration limit.
* `-s` — only one step per direction.

---

## 10  FPGA mapping — `if`

Files: `src/map/if/`. Driver `If_ManPerformMapping`
(`src/map/if/ifCore.c:82`) → `If_ManPerformMappingComb` (`:106`); per-node
work in `src/map/if/ifMap.c:If_ObjPerformMappingAnd` (`:162`).

### What it does

Choose a K-feasible cover of the AIG with K-LUTs that minimizes
delay then area, optionally with edge or power side-objectives.

### Pipeline (combinational)

`If_ManPerformMappingComb` issues several "rounds" (`If_ManPerformMappingRound`,
`ifMap.c:676`); each round visits every AND in topological order:

1. **Cut enumeration.** Per node, generate up to `nCutsMax` (default 8)
   K-feasible cuts by merging pairs of cuts from the two fanins (`If_CutMerge`
   or `If_CutMergeOrdered`). The merged cut is rejected if its support
   exceeds `K = nLutSize` (default 6). Filter contained cuts
   (`If_CutFilter`).

2. **Truth table.** If `fTruth` is on, compute the cut's NPN-canonical truth
   table for downstream cost models (DSD balance, exact-area, etc.).

3. **Cost model.** Each cut carries `(Delay, Area, Edge, Power)`.
    * `Delay`: max over leaves of `arrival(leaf) + 1` for plain LUT delay,
      or via a more sophisticated model (`If_CutDelaySop`,
      `If_CutDsdBalanceEval`, `If_CutDelayLutStruct`) if those flags are
      set.
    * `Area-flow`: `LutArea + Σ leaf_area_flow / leaf_est_refs`. This is the
      "smeared" area where shared cones get amortized over their estimated
      fanouts. `Mode = 1`.
    * `Exact area`: deref/ref the cut's MFFC to count actually-saved LUTs.
      `Mode = 2`.

4. **Best-cut selection per node.** A second mode-dependent comparator
   (`If_CutCompareDelay`, `If_CutCompareArea`, …) picks the winning cut.

5. **Round schedule** (the heart of the algorithm):
    * Round 1 — Mode 0 (delay-driven). Establishes minimum delay possible.
    * Optional preprocessing rounds with `fFancy` for variant delay shapes.
    * `nFlowIters` rounds — Mode 1 (area-flow). Shrinks area while keeping
      delay ≤ required.
    * `nAreaIters` rounds — Mode 2 (exact area). Final tightening.
    * Between rounds, `If_ManImproveMapping` (`fExpRed`) does cut expansion
      + reduction: try replacing a cut by a cheaper one whose leaves are
      already used.

6. **Network materialization.** After the last round, walk back from POs
   collecting the chosen cuts; emit each as a LUT.

### Choice nodes

`If_ObjPerformMappingChoice` (`ifMap.c:591`) — when a node has alternatives
(set up by `dch`/`fraig -c`), evaluate each one and pick the alternative
whose best cut wins. This is why `dch; if` is the standard FPGA sequence.

### Knobs (selected)

* `-K <k>` — LUT size (default 6).
* `-C <n>` — cuts per node.
* `-F <n>` — area-flow iterations.
* `-A <n>` — exact-area iterations.
* `-a` — area-only (skip delay round).
* `-x` — `fExpRed` cut expansion/reduction.
* `-D` — delay budget.
* `-S <pq>` — LUT-cascade structure.
* `-t`/`-y`/`-z`/etc. — alternative cost models (DSD balance, SOP balance,
  exact synthesis, REC library, LUT-decomposition).

---

## 11  Standard-cell mapping — `map`

Files: `src/map/mapper/`. Driver `Map_Mapping` at
`src/map/mapper/mapperCore.c:50`.

### Pipeline

Same shape as `if`, but the matching primitive is **NPN-canonical truth-
table → supergate library**, not LUT acceptance.

1. **Library prep.** `read_library`/`read_genlib` parses a genlib (or
   `read_super` reads a precomputed supergate file). Each "supergate" is a
   tree of standard cells with a known truth table, area, and per-pin
   delay. Library construction is in `mapperSuper.c`.

2. **Cuts.** `Map_MappingCuts` enumerates k-feasible cuts (default `k=5`).
   `Map_MappingTruths` computes a canonical truth table per cut.

3. **Matches.** `Map_MappingMatches` (`mapperMatch.c`) looks up each cut's
   truth table in the library's hash table, recording every matching
   supergate plus the input-permutation needed.

4. **Round schedule** (in `Map_Mapping`, `:50`):
    * `fMappingMode = 0` → delay-only mapping. Sets `RequiredGlo`.
    * `fMappingMode = 1` → area-flow recovery (one pass).
    * `fMappingMode = 2` → exact-area recovery.
    * `fMappingMode = 3` → exact-area recovery with phase-aware costing
      (the same cut may match the function or its complement; this round
      picks per-node phase).
    * `fSwitching` enables a switching-power-driven round in addition.

5. **Inversion folding.** Standard cells often come in inverting and
   non-inverting variants; `Map_MatchCompare` accounts for the cost of
   inserting an inverter when the chosen match's output phase doesn't
   line up.

### Knobs

* `-D` — delay constraint.
* `-A` — area objective (skip delay-first round).
* `-s`/`-S` — switching-power-aware mapping.
* `-G` — global/local matching.
* `-C` — number of cuts per node.

### `amap`

Files: `src/map/amap/`. `Amap_ManMap` (`amapMatch.c:657`).

An **area-oriented** standard-cell mapper that uses *structural* (rule-based,
subgraph-isomorphism) library matching instead of truth-table matching:

1. The library is preprocessed (`amapLib.c`) into a database of small AIG
   patterns ("rules"); each rule has a covering supergate.
2. `Amap_ManMerge` enumerates cuts per AIG node and matches each cut into
   one or more rules.
3. `Amap_ManMap` runs `nIterFlow` rounds of area-flow followed by
   `nIterArea` rounds of exact-area `Amap_ManMatch`.

`amap` typically gives smaller area than `map` on libraries that don't
factor cleanly into NPN-tabulated supergates (e.g. complex cells with
internal MUX/XOR), at the cost of being delay-blind.

---

## 12  Post-mapping local opts — `mfs`, `lutpack`

### `mfs` — minimization with don't-cares via SAT

Files: `src/opt/mfs/`. Driver `Abc_NtkMfs` (`mfsCore.c:388`); per-node
`Abc_NtkMfsNode` (`:306`).

Operates on a **mapped logic network** (LUTs or SOP nodes). For each node:

1. **Window.** `Abc_MfsComputeRoots` collects the TFO of the node up to
   `nWinTfoLevs` levels (with at most `nFanoutsMax` fanouts), plus its
   TFI support. The window is the local sub-network whose output behavior
   constrains the node's function.

2. **CNF.** Build an AIG of the window (`Abc_NtkConstructAig`) and convert
   to CNF (`Cnf_DeriveSimple`). Optionally add one-hotness / external care.

3. **SAT for the care set.** `Abc_NtkMfsSolveSat` enumerates patterns at
   the node's fanin support, marking each as care/don't-care depending on
   whether it changes the window's output. Output is a 64-bit `uCare` mask
   over the node's fanin combinations.

4. **Bi-decomposition.** `Abc_NodeIfNodeResyn` re-derives the node's local
   function over the relaxed care set using a bi-decomposition engine
   (`Bdc_Man`). If the resulting `Hop_Obj_t` DAG is smaller than the
   original, accept it.

`mfs2` is a faster reimplementation; `&mfs` is the GIA variant.

### Knobs

* `-W <n>` — TFO window levels (default 2).
* `-F <n>` — max fanouts to traverse.
* `-C <n>` — SAT conflict limit.
* `-r` — resub mode (faster, smaller acceptance window).

### `lutpack` — LUT repacking

Files: `src/opt/lpk/`. Driver `Lpk_Resynthesize` (`lpkCore.c:584`).

Takes a K-LUT-mapped network and tries to repack each LUT's local cone
into a chain of K-LUTs that uses fewer LUTs total. The cone span is
`nVarsMax = nLutsMax * (K-1) + 1` (so e.g. with K=6 and nLutsMax=2,
spans 11-input cones). `nVarsShared` allows shared inputs ("crossbars")
across the repacked chain. Decomposition uses DSD + Bool factoring
(`lpkAbcDsd.c`, `lpkAbcDec.c`, `lpkAbcMux.c`).

It is the only ABC command that can *increase* node count locally to
decrease area globally, since two simpler LUTs may pack into a smaller
total than one wide LUT.

---

## 13  Wrapping up: what runs in real flows

* **Yosys default `abc.script`**:
  `strash; ifraig; scorr; dc2; dretime; strash; dch; if; mfs2`
  (slight variations across versions).

* **OpenROAD default**: similar; `dch; if; mfs` is the core mapping
  triplet.

* **Hand-tuned area scripts**: typically string `compress2; compress2; …`
  several times before mapping; `&deepsyn` does this on the GIA side.

* **For sequential designs**: `dretime -M 5` is the usual go-to for joint
  area+delay retiming.

The right model when reading these scripts:

* `b/rw/rf/rs` are *Boolean-equivalent* AIG transforms; they only differ
  in (a) what cut shape they use and (b) how they propose a replacement
  function. They are accepted only if they shrink the AIG (or break even
  with `-z`).
* `fraig`/`ifraig` *prove* equivalences and merge them.
* `dch` *records* equivalences as choices for the mapper.
* `retime`/`dretime` move latches without changing the combinational
  function between them.
* `if`/`map`/`amap` consume an AIG and produce a mapped network.
* `mfs`/`lutpack` are post-mapping cleanups that rely on don't-cares
  exposed by the mapping itself.
