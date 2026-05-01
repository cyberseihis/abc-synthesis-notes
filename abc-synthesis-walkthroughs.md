# ABC synthesis commands — worked examples

Companion to `abc-synthesis-commands.md`. For every operator in that
reference doc, this document shows:

* a small example circuit,
* the algorithm's data-structure state at each step,
* a real trace captured from a patched ABC build (`ABC_TRACE=1`),
* code citations (`file.c:line`) tying each step to the implementation.

The example circuits live in `examples/` and are reproducible. The minimal
patches that enable the per-node trace are listed in `Appendix A`. All
traces in this document were produced by running the commands shown
verbatim against the indicated BLIF.

> The next deliverable will turn these examples into visualizations; this
> document is the algorithmic-state input for that.

---

## 0  Notation and one-time conventions

* **PIs** are lowercase `a`, `b`, `c`, …
* **AIG ANDs** are `nN` (or, after ABC writes BLIF back, `new_nN`).
* `n5 = a & ~b` is the AND with positive-`a` and negated-`b` fanin.
  In BLIF this prints as `.names a b n5` followed by `10 1`.
* An OR is stored as `~(~x & ~y)`; in BLIF it's `1- 1 / -1 1`.
* Levels: `lvl(PI) = 0`, `lvl(AND) = 1 + max(lvl(child0), lvl(child1))`.
* Truth tables for k-input cuts use **bit `i` = f(input pattern `i`)** with
  pattern `i` = `Σ 2^j · x_j` over inputs in cut order.

ABC's default options for the operators we trace are `rw -l`, `rf -l -N 10
-M 1`, `rs -l -K 8 -N 1 -M 1` — i.e. level-preserving, 10-input refactor
cones, 8-input resub cuts with a 1-step ladder.

---

## §0 Shared primitives — shown once

### §0.1  AIG and structural hash table — also `strash`

Source: `src/base/abc/abcAig.c:319` (create AND), `:403` (lookup),
`src/base/abci/abcStrash.c:49` (whole-network restash).

Example: `examples/aoi3.blif` — implements `f = ab + ad + cd`.

```blif
.names a b n5      # n5 = a & b
11 1
.names a d n6      # n6 = a & d
11 1
.names c d n7      # n7 = c & d
11 1
.names n5 n6 n8    # n8 = n5 | n6           encoded as ~(~n5 & ~n6)
1- 1
-1 1
.names n8 n7 f     # f = n8 | n7            encoded as ~(~n8 & ~n7)
1- 1
-1 1
```

Run:
```
abc> read examples/aoi3.blif
abc> strash
abc> print_stats
aoi3 : i/o = 4/1  lat = 0  and = 5  lev = 3
```

#### Step-by-step

`Abc_NtkRestrash` walks the source network in DFS order. For each AND it
calls `Abc_AigAnd` which dispatches to `Abc_AigAndLookup`. The lookup:

1. Trivial laws (`abcAig.c:411..426`):
   * `p == q` → `p`
   * `p == ~q` → `0`
   * `p == const1` → `q`; `p == ~const1` → `0`
2. Order children by their object ID so `(a, b)` and `(b, a)` hash to the
   same key (`abcAig.c:449`).
3. `Key = Abc_HashKey2(p0, p1, nBins)` — a Knuth multiplicative hash.
4. Walk the chain at `pBins[Key]`, comparing `(child0, child1)` exactly.

State of the strash table after processing aoi3 (key column abbreviated):

| Key | child0 (lit) | child1 (lit) | object        |
| --- | ------------ | ------------ | ------------- |
| K1  | a (+)        | b (+)        | n5            |
| K2  | a (+)        | d (+)        | n6            |
| K3  | c (+)        | d (+)        | n7            |
| K4  | n5 (–)       | n6 (–)       | n8 (= n5 ∨ n6)|
| K5  | n7 (–)       | n8 (–)       | f             |

#### What strash *would* dedup

If we duplicated `n6` (e.g. wrote two BLIF lines with the same support),
the second one would hit `Abc_AigAndLookup` at K2 with the same `(a, d)`
literals and be returned as `n6` — no new node. ABC writes the BLIF back
*after* strash and renumbers internal nodes, so strash output for our
file is:

```
.names a b new_n6      # was n5
.names a d new_n7      # was n6
.names new_n6 new_n7 new_n8  # was n8 = n5∨n6
.names c d new_n9      # was n7
.names new_n8 new_n9 f # the OR with negated SOP form (10 0)
```

ABC just renamed (`new_n6..new_n9`); same 5 ANDs, same 3 levels.

> **Why we chose this example.** It is the smallest 4-input function whose
> NPN class (12) lets the rewrite library save a node and on which resub
> can also be exercised. We re-use it for §1, §3, §4, §5, §11, §12, §13.

### §0.2  K-feasible cut enumeration

Source: `src/opt/cut/cutNode.c`, `src/map/if/ifCut.c:If_CutMerge`.

For node `f` of aoi3, the 4-cuts are computed bottom-up:

| Node | Local cut(s) (sets of leaves) |
| ---- | ----------------------------- |
| a    | `{a}`                         |
| b    | `{b}`                         |
| c    | `{c}`                         |
| d    | `{d}`                         |
| n5 = a&b | `{n5}`, `{a,b}`           |
| n6 = a&d | `{n6}`, `{a,d}`           |
| n7 = c&d | `{n7}`, `{c,d}`           |
| n8 = n5∨n6 | `{n8}`, `{n5,n6}`, `{a,b,n6}`, `{n5,a,d}`, `{a,b,d}` |
| f = n8∨n7 | `{f}`, `{n8,n7}`, `{n5,n6,n7}`, `{n8,c,d}`, `{n5,n6,c,d}`, `{a,b,n6,n7}`, ..., `{a,b,c,d}` |

`If_CutMerge` (and the equivalent `Cut_NodeDoComputeCuts` for the legacy
manager) takes the union of the two child cuts; if the result has more
than `K` elements, it is rejected. Otherwise it is added to the parent's
cut set, modulo containment filtering.

For aoi3 with K=4, node `f` ends up with the **full 4-cut `{a,b,c,d}`**.
That is the cut rewrite consumes in §3.

### §0.3  Reconvergence-driven cut

Source: `src/base/abci/abcReconv.c:Abc_NodeFindCut`.

Used by `refactor` and `resub` instead of the K-feasible enumeration.
The cut grows greedily from `pNode` outward: at each step the leaf with
the highest *cost* is replaced by its two fanins. The cost of a leaf
prefers leaves that *reconverge* (have multiple paths back to the root),
because expanding them is more likely to keep the cone size bounded.

The cut is bounded by `nNodeSizeMax` leaves (default 10 for refactor,
8 for resub) and by `nConeSizeMax` interior nodes (default 16/100k).

For our refactor example (`refactor_win.blif`, see §4), the cone at the
top node grows to 5 leaves `{a, b, c, d, e}` — exactly the inputs.

### §0.4  MFFC — the "private cone" of a node

Source: `src/base/abc/abcRefs.c:Abc_NodeMffcLabelAig` (line 100) and
its workhorse `Abc_NodeRefDeref` (line 126).

#### What an MFFC is

The **MFFC** (Maximum Fanout-Free Cone) of a node `pNode` is the set
of internal AIG nodes whose only downstream consumer — directly or
transitively — is `pNode` itself. They exist solely to feed `pNode`.
If `pNode` were replaced or deleted, exactly these nodes would
become unreachable; nodes outside the MFFC have at least one other
consumer and have to stay alive.

This is the quantity rewrite, refactor, and resub call `nNodesSaved`
(or `p->nMffc`). It is the upper bound on what a replacement can
"give back": replacing `pNode` deletes the MFFC, so a replacement
that adds *fewer* than `|MFFC|` new nodes is profitable.

When operators talk about the MFFC "with respect to cut leaves
`L = {l_1, …}`", they mean: stop the cone at `L` rather than
running back to PIs. The leaves are treated as already-existing
inputs the replacement may freely re-use, so they are *never* in
the MFFC even if their only fanout happens to be inside it.

#### Why a fanout-based walk works

Think of each AND's `Abc_ObjFanoutNum` as a reference count: how
many other nodes currently point at it. Mentally remove `pNode`:

1. Each fanin of `pNode` loses one reference.
2. If a fanin's count thereby reaches **zero**, that fanin is no
   longer consumed by anything → it joins the MFFC and the same
   logic propagates to *its* fanins.
3. A fanin whose count stays > 0 is still referenced by something
   outside `pNode`'s cone; it is not in the MFFC, and the recursion
   stops there.

The set of nodes whose counts hit zero in this thought experiment is
exactly the MFFC. Counting them gives the MFFC size.

This is the same trick reference-counted garbage collectors use to
decide which objects are dead.

#### The actual algorithm

`Abc_NodeMffcLabelAig` performs the deref-as-thought-experiment, then
re-references everything to put the AIG back the way it was:

```c
nConeSize1 = Abc_NodeRefDeref(pNode, fReference=0, fLabel=1);  // deref
nConeSize2 = Abc_NodeRefDeref(pNode, fReference=1, fLabel=0);  // re-ref
assert(nConeSize1 == nConeSize2);
return nConeSize1;
```

`Abc_NodeRefDeref(pNode, fReference, fLabel)` (line 126) is:

```
if pNode is a CI:    return 0          # PIs/latches never in MFFC
count = 1
if fLabel:           pNode.travid = current   # tag this node "in MFFC"
for each fanin f of pNode:
    if !fReference:  # deref pass
        f.fanouts -= 1
        if f.fanouts == 0:
            count += recurse(f)
    else:            # re-reference pass
        if f.fanouts == 0:
            count += recurse(f)        # mirror the deref recursion
        f.fanouts += 1
return count
```

The two passes do exactly opposite things to fanout counters, so the
AIG is left untouched on return. The `fLabel` flag is used only on
the deref pass to stamp every MFFC member with the current
`TravId`. Downstream code (most importantly `Dec_GraphToNetworkCount`,
§0.7) checks `Abc_NodeIsTravIdCurrent(node)` in O(1) to ask "is this
node in the MFFC?".

#### The boundary trick — protecting cut leaves

Without protection, the deref happily recurses through cut leaves and
keeps walking up the DAG. That over-counts: it absorbs nodes the
replacement is supposed to *re-use*, not delete.

Rewrite/refactor/resub bracket the call with a `+1/–1` on every cut
leaf's fanout count
(`abcRewrite.c:138..148`, `abcRefactor.c:191..194`):

```c
foreach leaf in cut: leaf.fanouts += 1;     // pre-protect

Abc_NodeMffcLabelAig(pNode);                // deref / ref / label

foreach leaf in cut: leaf.fanouts -= 1;     // restore
```

The +1 means a leaf's count *cannot* fall to zero during the deref:
even if every cone-internal fanout decrements it, the boost keeps it
positive, so no recursion enters the leaf. After the second pass
restores everything and we strip the boost, the AIG is byte-identical
to before — only the TravId labels survive.

#### Worked example: f-node of aoi3 with cut leaves {a, b, c, d}

(Cone from §0.1: `n5 = a&b`, `n6 = a&d`, `n7 = c&d`,
                 `n8 = n5 ∨ n6`, `f = n8 ∨ n7`.)

**Step 1 — fanout counts before MFFC.** From the AIG:

| Node | Fanouts (consumers) | count |
| ---- | ------------------- | ----- |
| a    | n5, n6              | 2     |
| b    | n5                  | 1     |
| c    | n7                  | 1     |
| d    | n6, n7              | 2     |
| n5   | n8                  | 1     |
| n6   | n8                  | 1     |
| n7   | f                   | 1     |
| n8   | f                   | 1     |
| f    | PO                  | 1     |

**Step 2 — apply boundary boost on `{a, b, c, d}`.** Each leaf
counter gets `+1`:

| Node | count after boost |
| ---- | ----------------- |
| a    | 3   (= 2 + 1)     |
| b    | 2   (= 1 + 1)     |
| c    | 2                 |
| d    | 3                 |

Internal nodes are unchanged.

**Step 3 — deref pass from `f`.** The recursion (and the running
`count`) unfolds top-down:

```
deref(f):                     count = 1, label f
  fanin n8.fanouts: 1 → 0     ⇒ recurse n8
    deref(n8):                count = 2, label n8
      fanin n5.fanouts: 1 → 0 ⇒ recurse n5
        deref(n5):            count = 3, label n5
          fanin a.fanouts: 3 → 2   (boundary boost held)
          fanin b.fanouts: 2 → 1   (boundary boost held)
      fanin n6.fanouts: 1 → 0 ⇒ recurse n6
        deref(n6):            count = 4, label n6
          fanin a.fanouts: 2 → 1
          fanin d.fanouts: 3 → 2
  fanin n7.fanouts: 1 → 0     ⇒ recurse n7
    deref(n7):                count = 5, label n7
      fanin c.fanouts: 2 → 1
      fanin d.fanouts: 2 → 1
```

`return count = 5`. **MFFC = {f, n8, n5, n6, n7}**, all five marked
with the current TravId.

Notice each leaf's counter was decremented multiple times but never
reached zero — that's the boundary trick in action. Without the +1
boost, `b.fanouts` would have gone 1 → 0 inside `deref(n5)` and the
recursion would have walked into `b` (a CI) — harmless here because
CIs return 0, but for a leaf that *is* an internal AND (e.g. when
the cut contains `n5` itself) the lack of protection would absorb
the whole cone above the leaf and over-report the MFFC.

**Step 4 — re-reference pass.** Same recursion path; each fanin
counter is incremented back to its original value. `count` again
sums to 5; the assert in `Abc_NodeMffcLabelAig` confirms consistency.

**Step 5 — strip the boundary boost.** Subtract 1 from each leaf;
the AIG is now identical to its state before the call, except every
node in `{f, n8, n5, n6, n7}` has its TravId equal to the current
network TravId.

#### What downstream code does with `nNodesSaved = 5`

* **Rewrite / refactor / resub** use it as the gain ceiling.
  `Gain = nNodesSaved − nNodesAdded`; the move is accepted iff
  `Gain > 0` (or `≥ 0` with `-z`).
* **`Dec_GraphToNetworkCount`** (§0.7) treats any strash-table hit
  whose node is in the MFFC (TravId match) as "doesn't actually
  reuse" — because that node will be deleted with the MFFC.
* **Resub's Divs ladder** caps replacement complexity at
  `nMffc - 1`, `nMffc - 2`, … because anything that needs more
  ANDs than the MFFC has cannot pay back.

#### Why §3's trace shows `Save = 4`, not 5

Rewrite is free to pick *any* 4-cut, not necessarily `{a,b,c,d}`.
The chosen cut for `f` in our trace is `{a, c, d, new_n6}` — i.e. it
treats the internal AND `new_n6 = a & b` as a leaf. With `new_n6`
boundary-boosted, the deref of `f` no longer recurses into `new_n6`
and the MFFC shrinks to `{f, n8, n6_other, n7} = 4` nodes. Different
cut → different MFFC → different `nNodesSaved`. See §3 for the full
trace.

### §0.5  Truth-table simulation on machine words

Source: `src/base/abci/abcResub.c:Abc_ManResubSimulate`,
`src/proof/fraig/fraigSim.c`.

ABC stores per-node simulation vectors as `nWords` 32-bit words where
each word's bits are 32 distinct input patterns. For a 4-input cut over
`{a,b,c,d}`:

```
Pattern column          : pattern index (bits LSB→MSB are a,b,c,d)
sim(a)        :  0xAAAAAAAA  (every odd bit)
sim(b)        :  0xCCCCCCCC
sim(c)        :  0xF0F0F0F0
sim(d)        :  0xFF00FF00
sim(a&b)      :  0x88888888  (= AAAA & CCCC)
sim(a&d)      :  0xAA00AA00  (= AAAA & FF00)
sim(c&d)      :  0xF000F000  (= F0F0 & FF00)
sim((a&b)|(a&d)|(c&d)) = 0xFA88_FA88  (truth table 0xFA88 repeated)
```

For random inputs ABC instead generates 32-bit random words per leaf
(`Aig_ManRandom`), and propagates them up via the AIG topology with
bitwise AND/NOT. The 32-pattern column is treated as the node's
"simulation signature" and used as a hash key.

Truth tables larger than 64 bits use `Vec_PtrAllocTruthTables` with as
many words as needed.

### §0.6  NPN canonization for 4-input functions

Source: `src/misc/extra/extraUtilMisc.c:Extra_Truth4VarNPN`,
populated in `src/bool/dec/decMan.c:Dec_ManStart`.

For all 65,536 4-input truth tables ABC precomputes:

* `pMap[uTruth]` — the NPN class index, in `[0, 222)` (222 classes total,
  `decMan.c:716` asserts this).
* `pPhases[uTruth]` — a 5-bit number: low 4 bits = which inputs to invert
  to reach canonical form; bit 4 = whether to invert the output.
* `pPerms[uTruth]` — index into `Extra_Permutations(4)` (24 entries) of
  which input-permutation to apply.
* `puCanons[uTruth]` — the canonical truth table itself (the
  lex-smallest representative of the class).

For aoi3's top function (`ab + ad + cd`, truth = `0xFA88`):

```
abc> rewrite -w
Node n10 :  Fanins = 4. Save = 4. Add = 3. GAIN = 1. Cone = 3. Class = 12.
```

Class index 12 — a small NPN class with at least one 3-AND
representative (`Cone = 3`). The library's representative for class 12
is the 3-AND graph that, when materialized over the cut leaves, replaces
the 4-AND MFFC.

### §0.7  `Dec_GraphToNetworkCount`

Source: `src/bool/dec/decAbc.c:167`.

Given a candidate replacement `pGraph` (an algebraic DAG over the cut
leaves) and the original root, this counts how many *new* AIG nodes
would be added if the graph were materialized — discounting any node
whose `(child0, child1)` pair already exists in the strash table.

Algorithm (lifted directly from the code):

```
for each Dec_Graph node N in DFS order:
    pAnd0 = strash_node_for(N.fanin0_with_phase)
    pAnd1 = strash_node_for(N.fanin1_with_phase)
    pAnd  = Abc_AigAndLookup(pMan, pAnd0, pAnd1)        # may be NULL
    if pAnd is NULL  or  pAnd is in current MFFC (TravId match):
        Counter += 1
        if Counter > NodeMax: return -1                 # bail
    else:
        # reuse — don't increment Counter
    LevelNew = 1 + max(N.fanin0.Level, N.fanin1.Level)
    if LevelNew > LevelMax: return -1                   # level bound
    N.pFunc, N.Level = pAnd, LevelNew
return Counter
```

Two key details:

* **MFFC nodes count as added.** They will be deleted when the
  replacement is committed, so reusing one of them is illusory. The
  TravId check (`Abc_NodeIsTravIdCurrent`) distinguishes them.
* **Returns –1** if level bound is violated or if the new graph would
  evaluate to the original root (which would create a self-loop).

The `nNodesAdded` reported by rewrite/refactor/resub is exactly this
counter; `Gain = nNodesSaved - nNodesAdded`.

---

## §1  `strash` — see §0.1

`strash` *is* the algorithm in §0.1: walk DFS, run `Abc_AigAnd` (which
calls `Abc_AigAndLookup` then creates if absent), no further work.
The example trace there *is* the strash trace.

---

## §2  `balance` — depth reduction on an AND chain

Source: `src/opt/dar/darBalance.c` (`Dar_ManBalance`),
`src/base/abci/abcBalance.c` (legacy).

Example: `examples/chain.blif` — five-input linear AND chain.

```blif
.inputs a b c d e
.outputs f
.names a b n1
11 1
.names n1 c n2
11 1
.names n2 d n3
11 1
.names n3 e f
11 1
```

After strash:

```
chain : i/o = 5/1  and = 4  lev = 4
new_n7 = a & b
new_n8 = c & new_n7
new_n9 = d & new_n8
f      = e & new_n9
```

Function: `f = ((((a & b) & c) & d) & e)`. Levels: a..e=0, n7=1, n8=2,
n9=3, f=4 — **right-leaning depth 4 chain**.

#### Step-by-step

`Dar_Balance_rec` is invoked on `f`:

**Step 1 — collect supergate** (`darBalance.c:106 Dar_BalanceCone_rec`).
Traverse children that are non-shared ANDs of the same type:

```
f  type=AND, ref=1 (only the PO uses it)  → recurse into children
   child0 = e (PI)        → push as leaf
   child1 = new_n9 type=AND, ref=1, type==AND → recurse
      child0 = d (PI)     → push as leaf
      child1 = new_n8 type=AND, ref=1, type==AND → recurse
         child0 = c (PI)  → push as leaf
         child1 = new_n7 type=AND, ref=1, type==AND → recurse
            child0 = a (PI) → push as leaf
            child1 = b (PI) → push as leaf
```

Result: `vSuper = [e, d, c, a, b]`.

**Step 2 — uniqify** (`Dar_BalanceUniqify`, `darBalance.c:57`). Sort by
literal, kill duplicates and `x & ~x`. All five are distinct PIs → no
change.

**Step 3 — recurse on each leaf** (`darBalance.c:521`). For PIs the
recursive call returns the leaf itself — leaves are already balanced.

**Step 4 — `Dar_BalanceBuildSuper`** (`darBalance.c:399`). Build a
balanced AND tree by repeated minimum-level pairing:

```
Initial vSuper sorted by level↓: [e, d, c, b, a]   (all level 0,
                                                   ties broken by Id)

iter 1: pop b, a  → m1 = a & b              level 1
        push m1, list = [m1, e, d, c]

iter 2: pop d, c  → m2 = c & d              level 1
        push m2, list = [m1, m2, e]

iter 3: pop m2, m1 → m3 = m1 & m2           level 2
        push m3, list = [m3, e]

iter 4: pop m3, e  → m4 = e & m3            level 3
        list = [m4]
```

`f` now equals `m4`. New depth = 3.

**Side effect — strash table reuse.** Each `Aig_Oper(p1, p2, AND)` call
goes through `Aig_TableLookupTwo` first; if `(p1, p2)` already exists,
that node is reused and no new AND is created. In our chain, none of the
new pairs exist yet, so all four ANDs are new — same node count, smaller
depth.

#### Real trace

```
$ /work/abc/abc -c "read examples/chain.blif; strash; ps; balance; ps; \
                    write_blif /tmp/chain_post.blif"

chain : i/o = 5/1  and = 4  lev = 4         ← before balance
chain : i/o = 5/1  and = 4  lev = 3         ← after balance

# /tmp/chain_post.blif:
.names a b new_n7        # = a & b
.names c d new_n8        # = c & d
.names e new_n8 new_n9   # = e & (c & d)
.names new_n7 new_n9 f   # = (a & b) & (e & c & d)
```

The structural change matches the hand-walked steps exactly (modulo
ABC's choice of which leaf joins which sub-tree first — `m4` paired
`e` with `m2` rather than with `m3`).

#### Knob effect — `-l`

If we had passed `-l` (`fUpdateLevel = 1`), `Dar_BalanceFindLeft`
(`darBalance.c:410`) would constrain pairing within the same minimum-
level subgroup, and `Dar_BalancePermute` would look up potential
strash-table reuses and bias swap choices accordingly. With all 5
leaves at level 0, the difference is invisible here; it shows up on
deeper supergates where pairing inner-level leaves first preserves the
critical path while exposing more reuse opportunities.

---

## §3  `rewrite` — DAG-aware AIG rewriting

Source: `src/base/abci/abcRewrite.c:Abc_NtkRewrite`,
`src/opt/rwr/rwrEva.c:Rwr_NodeRewrite` (per-node engine).

Example: `examples/aoi3.blif` (the §0.1 circuit, `f = ab + ad + cd`).

#### Real trace

```
$ ABC_TRACE=1 /work/abc/abc -c "read examples/aoi3.blif; strash; ps; rewrite; ps"

aoi3 : i/o = 4/1  and = 5  lev = 3      ← before
Node n10 : Fanins = 4. Save = 4. Add = 3. GAIN = 1. Cone = 3. Class = 12. \
           TT = 0x001F. Cut = { a c d new_n6 }
aoi3 : i/o = 4/1  and = 4  lev = 3      ← after

# Rewriting statistics:
# Total cuts tries  = 6.    Bad cuts found = 0.
# Total subgraphs   = 8.    Used NPN classes = 1.
# Nodes considered  = 5.    Nodes rewritten = 1.
```

Five nodes were "considered" (every internal AND), one was rewritten
(node `n10` — the f-node). The accepted cut is **not** the natural
`{a, b, c, d}` but `{a, c, d, new_n6}`, where `new_n6 = a & b` is itself
an AIG AND that the cut framework happens to keep as a leaf.

#### Step-by-step on `n10` (the f-node)

`Rwr_NodeRewrite(p, pManCut, n10, fUpdateLevel=1, fUseZeros=0)`:

**Step 1 — get cuts** (`rwrEva.c:80`).
`Abc_NodeGetCutsRecursive(pManCut, n10)` returns all 4-cuts of `n10`.
Only the **4-leaf** ones are considered (`pCut->nLeaves < 4` is skipped
at `:96`).

The cut filter at `:122..129` rejects any cut where **strictly more
than two** leaves have fanout 1 — fanout-1 leaves are themselves
captive to the MFFC and don't bring reuse. For our circuit:

```
cut {a, b, c, d}      : fanouts 2, 1, 1, 2  → 2 fanout-1 leaves: OK
cut {n5, n6, c, d}    : fanouts 1, 1, 1, 2  → 3 fanout-1: REJECTED
cut {a, b, n6, n7}    : fanouts 2, 1, 1, 1  → 3: REJECTED
cut {a, d, n5, n7}    : fanouts 2, 2, 1, 1  → 2: OK
cut {a, c, d, n6}     : fanouts 2, 1, 2, 1  → 2: OK   ← chosen
```

(here `n5..n9` are the post-strash nodes the BLIF dump shows as
`new_n6..new_n9`; the trace just uses the latter.)

The total trace count "Total cuts tries = 6" is the across-all-nodes
sum after filtering. At `n10` specifically, three cuts pass the filter.

**Step 2 — NPN normalization for each surviving cut** (`:101..114`).

For the chosen cut `{a, c, d, new_n6}`, `Cut_CutReadTruth(pCut)`
returns the cut's truth table; the rewrite manager prints the post-
canonicalization value `0x001F` (the cut-manager has its own
polarity convention; the NPN equivalent class is 12 either way).

Look-up:

```
pMap[uTruth]   = 12      # NPN class index, confirmed by trace's "Class = 12"
pPhases[uTruth]= ...      # input phase mask + bit 4 = output complement
pPerms[uTruth] = k        # index into Extra_Permutations(4)
```

The fanin order is permuted by `p->pPerms4[k]` and each fanin gets
XOR'd with its phase bit. The leaves are loaded into `p->vFaninsCur`
in canonical order.

**Step 3 — MFFC labeling** (`:138..148`). Apply the §0.4 boundary trick
on the chosen cut's leaves `{a, c, d, new_n6}`:

```
Increment fanouts: a:2→3, c:1→2, d:2→3, new_n6:1→2
Deref-DFS from n10:
  n10                     : Counter = 1, label
  n10's fanin0  (= n8)    : fanout 1→0   recurse
    n8's fanin0 (= n5=ab) : fanout-of-n5 wait — n5 is new_n6, a leaf!
                            (depends on which side; cut leaves are
                             new_n6 + n7 internally, plus a/c/d).
                            For the cut {a,c,d,n6}, only a/c/d/new_n6
                            are protected. The other internal nodes
                            (n7, n8, n9) are "inside" and get deref'd.
  ...
```

Total counter when the recursion settles = **4** (matches trace
`Save = 4`). The MFFC contains: `n10`, plus three non-leaf internal
nodes (the OR-bridge and the two ANDs that aren't `new_n6`).

**Step 4 — `Rwr_CutEvaluate`** (`rwrEva.c:253`). Iterate the library's
class-12 subgraph list:

```
for each candidate Dec_Graph_t in p->vClasses[12]:
    set leaves' Dec_Node->pFunc to permuted+phased AIG fanins
    nNodesAdded = Dec_GraphToNetworkCount(n10, candidate, Save, Required)
    if nNodesAdded != -1 and Save - nNodesAdded > GainBest:
        record this candidate
```

The trace reports `Cone = 3` — the chosen Dec_Graph has 3 internal
AND nodes. `Add = 3` means none reused from outside MFFC; all 3 are
new (or in-MFFC, which counts the same per §0.7).

**Step 5 — pick best, commit** (`abcRewrite.c:140..147`).
`GainBest = 4 - 3 = 1 > 0` → accept. `Dec_GraphUpdateNetwork(n10,
p->pGraph, fUpdateLevel=1, nGain=1)` materializes the 3 new ANDs over
the chosen leaves and detaches the old MFFC; reference counting cleans
up the dangling nodes.

#### Output

```
$ /work/abc/abc -c "read examples/aoi3.blif; strash; rewrite; write_blif /tmp/aoi3_rw.blif"

# /tmp/aoi3_rw.blif (4 ANDs vs. 5):
.names b d new_n6
00 0
.names a new_n6 new_n7
11 1
.names c d new_n8
11 1
.names new_n7 new_n8 f
00 0
```

Reading back: `new_n6 = NAND(~b, ~d) = b ∨ d`. Then `new_n7 = a & (b ∨ d)`.
`new_n8 = c & d`. `f = NOT(NAND(new_n7, new_n8)) = new_n7 ∨ new_n8 =
a(b+d) + cd`. Algebraically equal to `ab + ad + cd`, in 4 ANDs instead
of 5. This is exactly the factoring we predicted in §0.

---

## §4  `refactor` — algebraic refactoring

Source: `src/base/abci/abcRefactor.c`.

Example: `examples/refactor_win.blif` — `f = a(b+c+d+e)` written naively
as a chain of 4 ANDs and 3 ORs:

```
ab = a&b   ac = a&c   ad = a&d   ae = a&e
t1 = ab | ac
t2 = t1 | ad
f  = t2 | ae
```

After strash: 7 ANDs, level 4.

#### Real trace

```
$ ABC_TRACE=1 /work/abc/abc -c "read examples/refactor_win.blif; strash; refactor -N 6"

refactor_win : i/o = 5/1  and = 7  lev = 4
Node  n9 : Cone = 3. FF = 3. MFFC = 3. Add = 2. GAIN = 1.
Node n11 : Cone = 4. FF = 4. MFFC = 4. Add = 3. GAIN = 1.
Node n13 : Cone = 5. FF = 5. MFFC = 5. Add = 4. GAIN = 1.
refactor_win : i/o = 5/1  and = 4  lev = 3
```

Three accepted refactor moves, each gaining 1 AND; 7 → 4 total.

#### Step-by-step on `n9` (= `t1 = ab | ac`)

`Abc_NodeRefactor` (`abcRefactor.c:152`):

**Step 1 — reconvergence cut** (§0.3, `Abc_NodeFindCut(pManCut, n9, 0)`):
returns leaves `{a, b, c}` and 3 internal nodes `{ab, ac, n9}`.

The trace reports `Cone = 3` — that's the leaf count, which equals the
support of the local function. (Refactor's "Cone" field is the cut's
leaf count.)

**Step 2 — truth table of cone** (`Abc_NodeConeTruth`, `abcRefactor.c:81`).
Walk the 3-input cone, building per-node bitvectors. Final result
for `n9`:

```
truth(n9) over (a,b,c) = a&(b|c)
indices 0..7: f=0,0,0,0,0,1,1,1   ⇒ TT = 0xE0 (bit 7=1, 6=1, 5=1, rest=0)
```

(Wait — I'll trust the local SOP form rather than 8-bit recompute. The
function is `a*b + a*c = a*(b+c)`, equal at indices where a=1 ∧ (b∨c=1):
indices 5, 6, 7. So 8-bit TT = `0b1110_0000` = 0xE0.)

**Step 3 — factor the truth table** (`Kit_TruthToGraph`, `abcRefactor.c:188`).
Compute ISOP cubes from the TT. For 0xE0 the ISOP is `{ab, ac}`. Then
algebraic factoring extracts the common literal:

```
ab + ac  → factored Dec_Graph_t:
   leaf: a, b, c
   internal:  bc_or = b + c        (1 AND in AIG, with negated edges)
              top   = a & bc_or    (1 AND)
```

That's `1 + Dec_GraphNodeNum(pFForm) = 3` nodes in the algebraic
representation: 1 node for `b+c`, 1 for the conjunction, plus the
implicit "function root" → trace's `FF = 3`.

**Step 4 — count and accept**:

```
MFFC(n9) with leaves {a,b,c}: {ab, ac, n9}      → trace MFFC = 3
Dec_GraphToNetworkCount → nNodesAdded = 2       → trace Add = 2
Gain = MFFC - Add = 1                           → trace GAIN = 1
```

The accepted graph is `bc_or = !(~b & ~c); top = a & bc_or` → 2 ANDs
in AIG (the `b+c` is one AND with input phase inverters; the `a*(b+c)`
is the second AND).

**Step 5 — commit** via `Dec_GraphUpdateNetwork`.

The same logic repeats at `n11` (= `t2`) and `n13` (= `f`), each
factoring out one more variable from the OR chain. Final form:

```
g_bcde = !(~b & ~c & ~d & ~e)    # OR of 4 leaves
f      = a & g_bcde
```

Total: 4 ANDs (one for the 4-input OR-as-NAND, plus the conjunction; in
practice the 4-input OR is built as a 3-AND tree because AIG ANDs are
binary, so 3 + 1 = 4). Confirmed by the trace.

#### Why refactor finds gain that rewrite missed

The cone here has 5 inputs (`a,b,c,d,e`) at the top — too many for
rewrite's 4-cut limit. Refactor's larger reconvergence cut
(`nNodeSizeMax = 10`) can see the whole `a*(b+c+d+e)` cone and apply
algebraic factoring.

---

## §5  `resub` — Boolean resubstitution

Source: `src/base/abci/abcResub.c`.

Example: `examples/resub_win.blif` — a circuit with a *Boolean*
equivalence the AIG hides.

```blif
.inputs a b c d
.outputs f g
.names a b n5     # n5 = ~a & ~b = ~(a + b)
00 1
.names n5 c n6    # n6 = n5 & ~c = ~(a + b) & ~c
10 1
.names n5 n6 f    # f = ~n5 & ~n6 = (a + b) & (a + b + c) = (a + b)
00 1
.names n5 d g     # g  = n5 & d   (forces n5 to stay alive)
11 1
```

`f` evaluates to `a + b`, **which equals `~n5`** — but the AIG of `f`
goes through two ANDs that don't structurally simplify. Resub's job is
to spot `f ≡ ~n5` and redirect.

#### Real trace

```
$ ABC_TRACE=1 /work/abc/abc -c "read examples/resub_win.blif; strash; ps; resub -K 6; ps"

resub_win : i/o = 4/2  and = 4  lev = 3
[resub] node n7: leaves=2 mffc=1 divs=2     ← rejected (mffc<=1)
[resub] node n8: leaves=3 mffc=1 divs=4     ← rejected
[resub] node n9: leaves=3 mffc=2 divs=4     ← Divs0 hit
[resub]   -> Divs0  gain=2
[resub] node n10: leaves=3 mffc=1 divs=4    ← rejected
resub_win : i/o = 4/2  and = 2  lev = 2
```

#### Step-by-step at `n9` (the f-node)

**Step 1 — reconvergence cut.** With `nCutMax = 6`, `Abc_NodeFindCut`
returns 3 leaves `{a, b, c}` and 4 cone-internal nodes (n5, n6, n9, plus
the boundary).

**Step 2 — MFFC labeling.** Boundary trick on `{a, b, c}`:

```
fanout counts (relevant):
  n5: {n6, n9, n10}   (3)        ← n10 keeps n5 alive!
  n6: {n9}            (1)
  n9: {PO_f}          (1)

MFFC DFS from n9:
  n9 marked.
  n6: 1 fanout (n9). all marked → MFFC.
  n5: 3 fanouts (n6 marked, n9 marked, n10 NOT marked) → NOT in MFFC.

MFFC(n9) = {n6}    |MFFC| = 1, but we count the root too: 2 in resub's
                   accounting (`p->nMffc = 2`).
```

Trace confirms `mffc=2`.

**Step 3 — divisor collection** (`Abc_ManResubCollectDivs`,
`abcResub.c:474`). Internal nodes of the cone NOT in MFFC plus leaves:

```
divisors = {a, b, c, n5}      |divs| = 4    (matches trace divs=4)
```

Each gets a 32-pattern simulation vector (default `nWords = 1`).

**Step 4 — `Abc_ManResubDivs0`** (`abcResub.c:1145`). For each divisor,
test whether `sim(n9) == sim(divisor)` or `sim(n9) == ~sim(divisor)`.

```
sim(a)  = 0xAAAAAAAA
sim(b)  = 0xCCCCCCCC
sim(c)  = 0xF0F0F0F0
sim(n5) = ~sim(a) & ~sim(b)
        = 0x55555555 & 0x33333333
        = 0x11111111

sim(n9) = (a + b) for all input patterns
        = ~sim(n5) using AIG topology
        = 0xEEEEEEEE

→ sim(n9) == ~sim(n5) ✓ ⇒ Divs0 hit with negative phase.
```

Returned `Dec_Graph_t` is just `n5`, with the output-complement bit set.

**Step 5 — accept.** `nLastGain = nMffc = 2`. Replace `n9` with `~n5`:
literally redirect the PO `f` from `n9` to `n5` with output complement.

Now `n6` and `n9` become dangling → cleanup removes them.

#### Output

```
resub_win : i/o = 4/2  and = 2  lev = 2

# write_blif:
.names a b new_n6     # new_n6 = ~a & ~b   (this is what was n5)
00 1
.names new_n6 d g     # g = new_n6 & d
11 1
.names new_n6 f       # f = ~new_n6
0 1
```

Two ANDs. `f` is now an inverter of `n5`'s output — directly captured by
the BLIF inverter line `.names new_n6 f / 0 1`.

#### When the ladder climbs further

Had `Divs0` failed, resub would have called `Abc_ManResubDivsS` to build
the **single-level divisor pool** — pairs `(d_i AND d_j)`,
`(~d_i AND d_j)`, etc. — and tried `Abc_ManResubDivs1` for a single-AND
expression. Failure there triggers `Abc_ManResubDivs12` (using one
single-level and one two-level divisor) and so on. The ladder is the
five-step sequence at `abcResub.c:2008..2085`. With `-N 1` (default for
`rs`) only Divs0 and Divs1 fire; `-N 2` enables Divs12 and Divs2; `-N 3`
enables Divs3.

---

## §6  `restructure` — DSD-based restructuring

Not registered as a top-level command in current ABC (`abc.c:1003`
commented). The mechanism — k-feasible cut, BDD, Disjoint-Support
Decomposition tree, recursive AIG re-emission — is essentially refactor
with DSD instead of SOP-factoring as the normalizer. We skip an
end-to-end trace; the relevant code is `src/base/abci/abcRestruct.c:106`
and `Abc_NodeEvaluateDsd_rec` at `:590`.

A one-line illustration: for the cut function `f = (a ⊕ b) | (c ⊕ d)`,
the DSD tree is `OR(XOR(a,b), XOR(c,d))`. The recursive emit of an OR
node (`abcRestruct.c:635..688`) sorts its children by level descending
and pairs from the bottom, looking up `Abc_AigAndLookup` for reuse —
identical in spirit to balance, except guided by the DSD shape rather
than a bare AND-tree.

---

## §7  `dc2` — `compress2` on dar AIG

Source: `src/base/abci/abcDar.c:Abc_NtkDC2` (1669) →
`src/opt/dar/darScript.c:Dar_ManCompress2` (235).

#### Real trace on aoi3

```
$ /work/abc/abc -c "read examples/aoi3.blif; strash; dc2 -v"

aoi3 : i/o = 4/1  and = 5  lev = 3
Starting:  pi=4 po=1 and=5 lev=3
Rewrite:   pi=4 po=1 and=4 lev=3
Refactor:  pi=4 po=1 and=4 lev=3
Balance:   pi=4 po=1 and=4 lev=3
Rewrite:   pi=4 po=1 and=4 lev=3
RewriteZ:  pi=4 po=1 and=4 lev=3
RefactorZ: pi=4 po=1 and=4 lev=3
RewriteZ:  pi=4 po=1 and=4 lev=3
aoi3 : i/o = 4/1  and = 4  lev = 3
```

Each line is one stage of `compress2 = b -l; rw -l; rf -l; b -l; rw -l;
rwz -l; b -l; rfz -l; rwz -l; b -l`. The rewrite at the first stage
finds the §3 gain (5 → 4); the rest don't budge. This is the dar-AIG
implementation, but the per-stage outcome is the same as running the
ABC.rc alias.

The `-z` (zero-cost) stages can find moves that the strict-gain stages
missed: e.g. they accept `Gain == 0` rewrites that change the structural
shape. On aoi3 these don't trigger because the function is already at a
minimum. On larger benchmarks (the typical `compress2` user), the
zero-cost stages routinely shake free 1–2% extra reduction by exposing
new patterns to the next-iteration rewrite.

---

## §8  `fraig` — sim + SAT equivalence merging

Source: `src/base/abci/abcFraig.c`, `src/proof/fraig/fraigCanon.c:52`.

Example: `examples/fraig_eq.blif` — two structurally distinct ways to
compute `a & b & c`:

```blif
.outputs f1 f2
.names a b ab
11 1
.names ab c f1     # f1 = (a&b) & c
11 1
.names b c bc
11 1
.names a bc f2     # f2 = a & (b&c)
11 1
```

Both are 2-AND chains. After strash: 4 ANDs (since the strash table
keys `(a,b)` and `(b,c)` differently — the parens shape is preserved).

#### Real trace

```
$ /work/abc/abc -c "read examples/fraig_eq.blif; strash; ps; fraig -v; ps"

fraig_eq : i/o = 3/2  and = 4  lev = 2
Words: Random = 64. Dynamic = 64. Used = 0. Memory = 0.01 MB.
Proof = 1. Counter-example = 0. Fail = 0. FailReal = 0. Zero = 0.
Nodes: Final = 5. Total = 8. Mux = 0. (Exor = 0.) ClaVars = 2.
fraig_eq : i/o = 3/2  and = 2  lev = 2
```

`Proof = 1, Counter-example = 0` — exactly one SAT-based equivalence
proof was performed and succeeded. The result has 2 ANDs (one shared
across both POs).

#### Step-by-step

`Fraig_NodeAndCanon` on each AND in topological order:

**Step 1 — `ab = AND(a, b)`.** Trivial cases miss; structural lookup
(`Fraig_HashTableLookupS`) misses; sim signature is computed:

```
sim_random(a) = 64-word random vector R_a
sim_random(b) = R_b
sim(ab)      = R_a & R_b   (32 bits per word, 2048 patterns total)
```

The sim table keyed by signature is empty → insert ab. No SAT call.

**Step 2 — `f1 = AND(ab, c)`.** Same path. Sim signature
`sim(ab) & R_c`. Insert.

**Step 3 — `bc = AND(b, c)`.** Structural lookup misses. Compute sim
`R_b & R_c`. Lookup misses. Insert.

**Step 4 — `f2 = AND(a, bc)`.** Structural lookup misses (we have
`(ab, c)` but not `(a, bc)`). Compute sim `R_a & sim(bc) = R_a & R_b &
R_c`. Look up by sim signature → **hits `f1`** (which has the same
signature). The pair `(f1, f2)` is now a candidate equivalence.

**Step 5 — SAT proof** (`Fraig_NodeIsEquivalent`,
`src/proof/fraig/fraigSat.c`). Build a miter `out = f1 ⊕ f2`, ask SAT
whether it can be 1 with `nBTLimit = 100` conflicts. The CNF (after
Tseitin) has 8 clauses, 8 vars, and the solver returns UNSAT in 0
conflicts (the trace reports `propagations = 9, inspects = 15` — pure
unit propagation).

**Step 6 — merge.** `f2->pRepr = f1`, output complement bit = 0.
Subsequent uses of `f2` are redirected to `f1`.

After all nodes processed: `Total = 8` (4 ANDs + 4 fanin literals/PIs)
in the FRAIG manager; `Final = 5` survivors after merging.

#### Choice mode (`-c` / `dch`)

If we had passed `-c`, the SAT-proven equivalent `f2` would have been
appended to `f1->pNextE` (a singly-linked list of choices) instead of
discarded. The downstream `if`/`map` mapper then sees both alternatives
when picking the best implementation per cone. See §9.

---

## §9  `dch` — delay-aware choices

Source: `src/base/abci/abcDar.c:Abc_NtkDch` →
`src/opt/dar/darScript.c:Dar_ManChoiceNew`.

`dch` is `fraig -c` driven by **three** synthesis snapshots so the
mapper sees structurally diverse alternatives. The three snapshots are
produced by `Dar_ManChoiceSynthesis` (`darScript.c:345`):

1. The original AIG (DFS-duplicated).
2. `Dar_ManCompress` of (1).
3. `Dar_ManCompress2` of (2).

#### Real trace on aoi3

```
$ /work/abc/abc -c "read examples/aoi3.blif; strash; dch -v; ps"

aoi3 : i/o = 4/1  and = 5  lev = 3
Starting:  aoi3 : pi=4 po=1 and=5 lev=3
Rewrite:   aoi3 : pi=4 po=1 and=4 lev=3
Refactor:  aoi3 : pi=4 po=1 and=4 lev=3
Balance:   aoi3 : pi=4 po=1 and=4 lev=3
RewriteZ:  aoi3 : pi=4 po=1 and=4 lev=3
Starting:  aoi3 : pi=4 po=1 and=4 lev=3      ← snapshot 2 starts here
Rewrite:   aoi3 : pi=4 po=1 and=4 lev=3
Refactor:  aoi3 : pi=4 po=1 and=4 lev=3
Balance:   aoi3 : pi=4 po=1 and=4 lev=3
Rewrite:   aoi3 : pi=4 po=1 and=4 lev=3
RewriteZ:  aoi3 : pi=4 po=1 and=4 lev=3
Balance:   aoi3 : pi=4 po=1 and=4 lev=3
RefactorZ: aoi3 : pi=4 po=1 and=4 lev=3
RewriteZ:  aoi3 : pi=4 po=1 and=4 lev=3
Balance:   aoi3 : pi=4 po=1 and=4 lev=3      ← snapshot 3 ends
Parameters: Sim words = 8. Conf limit = 1000. SAT var max = 5000.
AIG nodes : Total = 8. Dangling = 6. Main = 2. ( 25.00 %)
SAT solver: Vars = 13. Max cone = 0. Recycles = 1.
```

#### Step-by-step

**Step 1 — three snapshots.** The trace shows each script applied to
its predecessor:

* Snapshot 1: original (5 ANDs).
* Snapshot 2: `compress` of snapshot 1 → 4 ANDs.
* Snapshot 3: `compress2` of snapshot 2 → 4 ANDs.

Snapshots 2 and 3 happen to be structurally different even though
counts match (compress vs compress2 have different rewrite/refactor
ordering).

**Step 2 — combine.** `Dch_DeriveTotalAig` (`darScript.c:802`) builds a
single AIG with all three networks' ANDs sharing the PIs. The trace's
`Total = 8` means the union has 8 nodes.

**Step 3 — `Dch_ComputeChoices`.** Internal SAT-proves equivalences
across the three sub-networks, building choice classes. Each class's
representative is the snapshot-1 node (because of the swap at
`darScript.c:797..799`). Equivalent nodes from snapshots 2 and 3 are
appended to the class's `pNextE` linked list rather than collapsed.

The trace reports `Dangling = 6, Main = 2` — out of 8 candidates, 6 got
absorbed into choice classes (became representatives or alternatives),
leaving 2 surviving "main" nodes. The choice-AIG retains all 8 ANDs in
its `Aig_Man_t`, but the user-facing structure presents 2 ANDs with
choice alternatives hanging off them.

**Step 4 — output.** The result, viewed naively, has fewer ANDs than
the union; viewed with choices exposed (e.g. `if`-mapper view), each
cone has multiple structural realizations to pick from.

---

## §10  `retime` — sequential retiming (mode 3, min-area)

Source: `src/opt/ret/retCore.c:Abc_NtkRetime`,
`src/opt/ret/retArea.c:Abc_NtkRetimeMinArea`.

Example: `examples/retime_demo.blif`:

```
.inputs a b c
.outputs y
.latch n1 r1 0     n1 = a & b
.latch n2 r2 0     n2 = a & c
.latch n3 r3 0     n3 = b & c
m1 = r1 & r2
y  = m1 | r3
```

Three latches, each sitting between an AND on its inputs and either
another AND or an OR on its output.

#### Real trace

```
$ /work/abc/abc -c "read examples/retime_demo.blif; strash; ps; retime -M 3 -v; ps"

retime_demo : i/o = 3/1  lat = 3  and = 5  lev = 2
L = 3. Forward  max-flow = 1.  Min-cut = 1.  Time = 0.00 sec
L = 1. Forward  max-flow = 1.  Min-cut = 1.  Time = 0.00 sec
L = 1. Backward max-flow = 1.  Min-cut = 1.  Time = 0.00 sec
Reduction in area = 2. Reduction in delay = -1.
retime_demo : i/o = 3/1  lat = 1  and = 5  lev = 3
```

3 latches → 1 latch. Depth grew 2 → 3 (fewer latches means deeper
combinational cones, hence the `-1` delay reduction).

#### Step-by-step (forward direction, mode 3)

`Abc_NtkRetimeMinArea` calls `Abc_NtkRetimeMinAreaOne` in a loop until
no further reduction.

**Step 1 — prepare graph** (`retArea.c:198 Abc_NtkRetimeMinAreaPrepare`).
Mark current latches (sources for forward flow) and TFI of POs (sinks).
Two virtual super-nodes are created: `s` connected to all latch outputs,
`t` connected to all PO drivers.

For our circuit:

```
sources s → r1, r2, r3                (all latch outputs)
sinks   y → t                         (PO driver)
```

**Step 2 — max-flow** (`Abc_NtkMaxFlow`, `retFlow.c`). Edge capacity 1
per node; node-splitting trick (each node split into in-node and
out-node, edge between of capacity 1) so cuts cut nodes, not edges.

Walk:

```
augmenting path 1: s → r1 → m1 → y → t           push flow 1
augmenting path 2: s → r2 → m1 → ?               m1 already has 1 unit out;
                    no other path through m1; saturated.
augmenting path 3: s → r3 → y → t                blocked (y is saturated,
                    cannot accept second flow);
                    DFS finds nothing → done.
```

Max-flow = 1.

**Step 3 — min-cut.** The cut = nodes reachable from `s` in the residual
graph that have a forward edge to an unreachable node. Walking residual:

```
residual: s -- r1[saturated] r2 r3 ...
from s in residual: r1 reachable forward only after first split;
analysis shows the min-cut contains a single node — the y-node.
```

Min-cut = `{y}` (size 1). Trace confirms `Min-cut = 1`.

**Step 4 — apply.** `Abc_NtkRetimeMinAreaUpdateLatches` removes the old
3 latches and inserts a single new latch on the cut node `y`. The new
latch's initial value is computed by `Abc_NtkRetimeInitialValues` from
the original initial values:

```
old initial values: r1=0, r2=0, r3=0
"first cycle" combinational result with r{1,2,3} = 0:
   m1 = 0 & 0 = 0
   y  = 0 | 0 = 0
new initial value of single latch: 0
```

**Step 5 — second iteration.** With `lat = 1, max-flow = 1, min-cut = 1`,
no further reduction; forward pass exits.

**Step 6 — backward.** Same algorithm with arrows reversed; min-cut
again size 1. No change.

#### Output

```
# /tmp/retime_post.blif (abridged):
.latch n14 r 0
.names a b new_n16     # = a & b
.names a c new_n17     # = a & c
.names b c new_n18     # = b & c
.names new_n16 new_n17 new_n14_part
11 1                   # = (a&b) & (a&c)
.names new_n14_part new_n18 n14
1- 1
-1 1                   # = ((a&b)(a&c)) | (b&c)  → driver of single latch
.names r y
1 1                    # PO is the latch output directly
```

The combinational logic that used to be split across the 3 latches is
now concentrated **before** the single latch. Depth 3 (was 2). One latch
(was 3).

---

## §11  `if` — FPGA LUT mapping

Source: `src/map/if/ifCore.c:If_ManPerformMapping`,
`src/map/if/ifMap.c:If_ObjPerformMappingAnd`.

Example: `examples/maj4.blif` — 4-input majority `f = MAJ4(a,b,c,d)`,
which is true when ≥ 3 inputs are 1.

After strash: 10 ANDs, level 6.

#### Real trace, K = 4

```
$ /work/abc/abc -c "read examples/maj4.blif; strash; ps; if -K 4 -v; ps"

maj4 : i/o = 4/1  and = 10  lev = 6
K = 4. Memory (bytes): Truth = 0. Cut = 64. Obj = 144. Set = 672. CutMin = no
Node = 10. Ch = 0. Total mem = 0.00 MB.
P:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
P:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
P:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
E:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
F:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
E:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
A:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
E:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
A:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
E:  Del = 1.00.  Ar = 1.0.  Edge = 4.  Cut = 43.  T = 0.00 sec
maj4 : i/o = 4/1  nd = 1  edge = 4  aig = 10  lev = 1
```

10 ANDs collapsed into a single 4-LUT.

#### Step-by-step

**Step 1 — set up.** Per-node cut-set storage allocated. PIs receive
arrival times (zero) and est-refs (1.0).

**Step 2 — preprocess (3 P-rounds; `ifCore.c:124..132`).**
Three delay-driven rounds with different cost variants (`fFancy = 0`
then `fFancy = 1` then `fFancy = 0` with `fArea = 1`). Each round
visits every AND, calling `If_ObjPerformMappingAnd`:

  * Enumerate 4-cuts by merging fanin cut sets through `If_CutMerge`.
    Across all 10 nodes, **`Cut = 43`** distinct cuts are kept.
  * For each cut, compute a 4-input truth table.
  * Score by delay (= max fanin arrival + 1) — every leaf is a PI at
    time 0, so every 4-input cut has delay 1.
  * The full-support cut `{a,b,c,d}` at the root achieves
    `Del = 1, Ar = 1` (one LUT covers everything). All three P-rounds
    settle on the same cut.

**Step 3 — E (`If_ManImproveMapping`, `ifCore.c:144`).** Cut expansion
+ reduction tries to swap the chosen cut with one whose leaves are
already used by the mapping. No improvement possible (single LUT).

**Step 4 — F (area-flow, `Mode = 1`, `ifCore.c:149`).** Area-flow cost
`= LutArea + Σ leaf_area_flow / leaf_est_refs`. With the all-PI cut,
flow = 1.0. Unchanged.

**Step 5 — A (exact area, `Mode = 2`, `ifCore.c:155..164`).**
Deref/ref-based exact-area accounting. Still 1.0.

**Step 6 — emit network.** Walk back from the PO marking the chosen
cuts. Emit each chosen cut as a LUT with its 16-bit truth table:

```
# /tmp/maj4_lut.blif:
.names a b c d f
1110 1
1101 1
1011 1
0111 1
1111 1
```

Five SOP rows = the 5 minterms where ≥ 3 of `{a,b,c,d}` are 1, encoded
into the LUT's truth table.

#### Effect of K

If we ran `if -K 3` instead, no single 3-input cut covers `MAJ4`. The
algorithm would partition into multiple LUTs. With our `examples/maj.blif`
(`MAJ3`), `if -K 3` produces a single LUT (5 ANDs → 1 LUT, level 6 → 1):

```
maj : i/o = 3/1  and = 5  lev = 3
maj : i/o = 3/1  nd = 1  edge = 3  aig = 5  lev = 1
```

With `if -K 2` on the same `MAJ3`, no 2-input cut suffices and the LUT
network has 4 LUTs (one per AIG AND, basically reproducing the AIG as a
LUT graph).

---

## §12  `map` — standard-cell mapping

Source: `src/map/mapper/mapperCore.c:Map_Mapping`.

Example: `examples/aoi3.blif` mapped against a tiny genlib
(`examples/tiny.genlib`) containing `INV, NAND2, NOR2, AND2, OR2,
AOI21, OAI21`.

#### Real trace

```
$ /work/abc/abc -c "read_library examples/tiny.genlib; \
                    read examples/aoi3.blif; strash; map -v; ps"

Converting "examples/tiny.genlib" into supergate library ...
Maximum level: Original = 3. Reduced due to choices = 3.
Choice stats:  Choice nodes = 0. Total choices = 0.
Nodes = 9. Total 5-feasible cuts = 16. Per node = 1.8.
Delay    : Delay = 0.00. Flow = 7.0. Area = 7.0.   0.0 %
AreaFlow : Delay = 2.20. Flow = 7.0. Area = 7.0.   0.0 %
Area     : Delay = 2.20. Flow = 0.0. Area = 7.0.   0.0 %
Area     : Delay = 2.20. Flow = 0.0. Area = 7.0.   0.0 %
Output  f    : Delay = ( 2.20,  2.20)  NEG
aoi3 : i/o = 4/1  nd = 3  edge = 7  area = 7.00  delay = 2.20  lev = 2
```

aoi3's 5 ANDs become 3 standard cells, total area 7 (= AOI21=3 +
NAND2=2 + NAND2=2).

#### Step-by-step

**Step 1 — supergate library.** `read_library` invokes
`Super_Compute` (the pre-mapping step) which enumerates compositions
of the genlib gates up to a fanin bound (default 5). Each supergate
has a single output truth table, total area, per-pin delay tuple. This
becomes a hash table keyed by **NPN-canonical truth table**.

**Step 2 — cuts.** `Map_MappingCuts` enumerates 5-feasible cuts (genlib
gates have ≤ 5 inputs). Trace: 16 cuts across 9 internal nodes.

**Step 3 — truths.** `Map_MappingTruths` computes a canonical truth
table per cut, used as the supergate-table lookup key.

**Step 4 — Mode 0 (delay).** For each AND, look up matches for each
cut. The match for the root's `{a, b, c, d}` cut, with truth `0xFA88`,
includes the supergate `OAI21(a, OR2(b, d))`-equivalent that maps to
2 cells. The phase-aware flag `NEG` in the trace means the chosen
match drives `f` through the *negated* polarity of the supergate
output (one inverter folded away).

**Step 5 — Mode 1 (area-flow).** Area = 7.0 unchanged; the delay-
optimal mapping was already area-feasible.

**Steps 6, 7 — Modes 2 and 3 (exact area, exact area + phase).**
Both retain the same mapping.

**Output**:

```
# /tmp/aoi3_mapped.blif:
.gate OAI21 a=d b=b c=a O=new_n6   # !((d+b)*a) = !(a*(b+d))
.gate NAND2 a=d b=c O=new_n7       # !(c*d)
.gate NAND2 a=new_n7 b=new_n6 O=f  # !(!(cd) * !(a(b+d))) = cd + a(b+d)
                                   #                     = ab + ad + cd ✓
```

Three gates, one inversion folded into the output NAND2's polarity, area 7.

---

## §13  `amap` — area-oriented standard-cell mapping

Source: `src/map/amap/amapCore.c:Amap_ManTest`,
`src/map/amap/amapMatch.c:Amap_ManMap`.

#### Real trace (same circuit/library as §12)

```
$ /work/abc/abc -c "read_library examples/tiny.genlib; \
                    read examples/aoi3.blif; strash; amap -v; ps"

Performing mapping with 0 given and 0 created choices.
AIG object is 96 bytes.
Node = 5. Try = 15. Try3 = 0. Used = 13. R = 2.60. Time = 0.00 sec
Area = 14.00. Gate = 8.00. Inv = 6.00. (6.) Delay = 3.00.   ← initial
Area = 11.00. Gate = 8.00. Inv = 3.00. (3.) Delay = 3.00.   ← flow round 1
Area = 11.00. Gate = 8.00. Inv = 3.00. (3.) Delay = 3.00.   ← flow round 2
Area = 11.00. Gate = 9.00. Inv = 2.00. (2.) Delay = 3.00.   ← area round 1
Area = 11.00. Gate = 9.00. Inv = 2.00. (2.) Delay = 3.00.   ← area round 2
aoi3 : nd = 5  edge = 10  area = 11.00  delay = 3.80  lev = 3
```

#### Differences from `map`

* The library is preprocessed by **structural pattern rules**, not
  truth-table hashing. `amap_ManCreate` walks each library gate's AIG
  representation and inserts subgraph patterns.
* `Amap_ManMerge` enumerates cuts and matches each cut against the
  pattern database via subgraph isomorphism.
* `Amap_ManMap` runs `nIterFlow` rounds of area-flow (`fFlow=1`) then
  `nIterArea` rounds of exact-area (`fFlow=0`). Iteration count default
  = 4 area-flow + 4 area, but converges in 2-3 typically.
* The trace shows a separate **inverter count** (the standalone INV
  gates needed to fix output phase). amap reduces inverters across
  iterations from 6 → 2.

The amap result is *worse* than `map` here (area 11 vs. 7) because
amap is biased to larger gates and our genlib has tightly priced INV/
NAND2/OAI21; on bigger libraries amap typically wins on area.

---

## §14  `mfs` — minimization with don't-cares via SAT

Source: `src/opt/mfs/mfsCore.c:Abc_NtkMfs` (`:388`),
`src/opt/mfs/mfsCore.c:Abc_NtkMfsNode` (`:306`).

Example: `examples/maj4.blif` LUT-mapped with `if -K 3` (which produces
multiple LUTs since one 3-LUT can't cover MAJ4).

#### Real trace

```
$ /work/abc/abc -c "read examples/maj4.blif; strash; if -K 3; ps; mfs -v -w; ps"

maj4 : i/o = 4/1  nd = 4  edge = 11
   7 : Lev = 3. Leaf = 4. Node = 4. Divs = 4.  Fanin = 8 (0/3),  MFFC = 2
   7 : Lev = 3. Leaf = 4. Node = 4. Divs = 4.  Fanin = 10 (1/3), MFFC = 1
   7 : Lev = 3. Leaf = 4. Node = 4. Divs = 4.  Fanin = 1 (2/3),  MFFC = 0
   8 : Lev = 2. Leaf = 4. Node = 4. Divs = 2.  Fanin = 9 (0/3),  MFFC = 1
   8 : Lev = 2. Leaf = 4. Node = 4. Divs = 2.  Fanin = 1 (1/3),  MFFC = 0
Node 8: Fanin 1 can be removed.
   9 : Lev = 1. Leaf = 4. Node = 4. Divs = 0.  Fanin = 3 (0/2),  MFFC = 0
   9 : Lev = 1. Leaf = 4. Node = 4. Divs = 0.  Fanin = 4 (1/2),  MFFC = 0
  10 : ...
Reduction:  Nodes 0/4 ( 0.0%)  Edges 1/11 (9.1%)
maj4 : i/o = 4/1  nd = 4  edge = 10
```

`mfs` walked every fanin of every LUT (rows are `<NodeID> : Lev = depth.
Leaf = window-leaves. Node = window-nodes. Divs = divisors. Fanin =
<id> (<index>/<count>)`). At node 8, fanin 1 was found removable —
edge count drops 11 → 10.

#### Step-by-step at "Node 8: Fanin 1 can be removed"

`Abc_NtkMfsResub` (the resub variant of mfs since `-r` is the default;
`abcMfs.c` would dispatch differently with `-r` toggled off):

**Step 1 — window construction** (`mfsCore.c:Abc_NtkMfsWindow`).
TFO of node 8 up to 2 levels: `{8, ...}`. TFI from those POs back to
node 8's fanins. Window has 4 nodes, 4 leaves (trace's `Leaf = 4,
Node = 4`).

**Step 2 — build CNF** of the window (`Abc_NtkConstructAig`,
`Cnf_DeriveSimple`).

**Step 3 — SAT for the care set.** The care set of node 8 is the set
of fanin patterns under which the window's POs depend on node 8's
output. `Abc_NtkMfsSolveSat` enumerates patterns via SAT; for each
input pattern, ask: "with node 8 = 0, are window POs the same as
with node 8 = 1?". If yes, this pattern is **don't-care** for node 8.

**Step 4 — fanin removal test.** For each fanin of node 8 (in turn,
the trace shows fanins at indices 0, 1):

  * Build a SAT problem asking: "is there a care input pattern under
    which removing this fanin would change the node's output?"
  * If UNSAT, the fanin is removable.
  * Trace says fanin 1 of node 8 yields UNSAT → **fanin 1 can be
    removed**.

**Step 5 — re-derive local function** (`Abc_NodeIfNodeResyn` via the
`Bdc_Man` bi-decomposition engine). The new function maps onto the
remaining 2 fanins; old function's truth table on the wider support
is projected onto the smaller support, using don't-cares to pick the
simpler form.

**Step 6 — replace** the LUT's `Hop_Obj_t` if smaller.

#### Knob effect — `-W`, `-D`, `-C`

* `-W <n>` (default 2) bounds the TFO depth → larger windows expose
  more ODCs but cost SAT time (`mfs.h: nWinTfoLevs`).
* `-D <n>` (default 20) bounds the resub depth.
* `-C <n>` (default 5000) is the SAT conflict limit per call.

---

## §15  `lutpack` — LUT chain repacking

Source: `src/opt/lpk/lpkCore.c:Lpk_Resynthesize` (`:584`).

`lutpack` looks for cones spanning **N · (K-1) + 1** inputs that can be
re-decomposed into a chain of N K-LUTs. With the default `nLutsMax = 4`
and `K = 6`, that's up to 21-input cones repacked into ≤ 4 LUTs.

We won't trace a successful lutpack here because all our small examples
are already minimum-LUT. Instead, the algorithm sketch with code
citations:

* `Lpk_NodeResynthesize` (`lpkCore.c:434`) — per-node:
  1. Compute reconvergence-driven cut up to `nVarsMax` inputs.
  2. Compute the cone's truth table (`Lpk_NodeTruth`).
  3. Try DSD decomposition (`Lpk_DsdAnalize` in `lpkAbcDsd.c`):
     if the function decomposes as `OR/AND/XOR/MUX(g1, g2, …)` with
     each `gi` representable in ≤ `K-1` inputs, emit a tree of K-LUTs.
  4. Else try Boolean decomposition with shared-input "crossbars"
     (`Lpk_NodeMux`, `lpkAbcMux.c`): Shannon-decompose along chosen
     pivot variables.
  5. Score: total LUT count and edges. Accept if smaller than current.

The verbose flag `-v` prints per-iteration "Node gain / Edge gain /
Muxes / DSDs"; `-w` prints the decomposed function for each accepted
move. Useful when tuning `-N` (max LUTs in chain) and `-S` (max shared
inputs).

---

## Appendix A: build & trace patches

The traces in this document were captured from a build of ABC at
HEAD, with three small patches that gate per-node prints behind an
`ABC_TRACE` environment variable:

```diff
--- a/src/opt/rwr/rwrEva.c
+++ b/src/opt/rwr/rwrEva.c
@@ Rwr_NodeRewrite
-    int fVeryVerbose = 0;
+    int fVeryVerbose = getenv("ABC_TRACE") ? 1 : 0;

--- a/src/base/abci/abcRefactor.c
+++ b/src/base/abci/abcRefactor.c
@@ Abc_NodeRefactor
-    int fVeryVerbose = 0;
+    int fVeryVerbose = getenv("ABC_TRACE") ? 1 : 0;

--- a/src/base/abci/abcResub.c
+++ b/src/base/abci/abcResub.c
@@ Abc_ManResubEval (around line 2008..2090)
+    int abcTrace = getenv("ABC_TRACE") ? 1 : 0;
+    if (abcTrace) printf("[resub] node %s: leaves=%d mffc=%d divs=%d\n",
+                         Abc_ObjName(pRoot), p->nLeaves, p->nMffc, p->nDivs);
+    /* ... print the matching ladder step on success ... */
```

The full diff is in `patches/abc-trace.diff` (next to this file). Apply
with `git apply` against berkeley-abc/abc HEAD and rebuild:

```
cd abc && make ABC_USE_NO_READLINE=1 -j$(nproc)
ABC_TRACE=1 ./abc -c "read examples/aoi3.blif; strash; rewrite"
```

All other operators (balance, fraig, dch, retime, if, map, amap, mfs,
lutpack) emit the traces in this document under their own `-v` /
`-w` flags without source patches.
