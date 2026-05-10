#!/usr/bin/env python3
"""End-to-end correctness check: re-simulate every SAT chain in an iter-mode TSV
and confirm it computes the claimed truth table(s).

Catches bugs that the regex-and-trust workflow would miss:
- chain printing bug in ABC
- sweep-harness mis-pairing of tt with chain
- truth-table format drift between sweeps

Two chain dialects supported:

  andexact:  letters A..Z (or AA..) for internal nodes, & for AND, ! for NOT
  aoexact:   n0, n1, ... for internal nodes; & for AND, | for OR
             (input rails written as `aN`, `bN`, ... = negated PI; positive PI
              is just `a`, `b`, ...)

Output format from each tool, as it appears in the TSV `chain` field:
  andexact:  "F = !G ; G = !D & !F ; F = C & E ; ... ; A = b & !c"
  aoexact:   "F = n12 ; FN = n11 ; n0 = aN & bN ; ..."  (multi-output: F0/F0N/...)
"""
import argparse, csv, re, sys
from collections import Counter


def parse_chain(chain_str, dialect):
    """Returns list of (lhs, expr) entries in declaration order."""
    parts = [p.strip() for p in chain_str.split(";") if p.strip()]
    out = []
    for part in parts:
        if "=" not in part:
            raise ValueError(f"no '=' in part: {part!r}")
        lhs, rhs = part.split("=", 1)
        out.append((lhs.strip(), rhs.strip()))
    return out


# ---------- expression evaluator ----------
# Each leaf is a name (PI or internal node) optionally negated with a leading '!'.
# Operators: '&' (AND), '|' (OR). At most one binary op per expression in our
# chains (each gate is 2-input). Either fanin can be a single (possibly-negated)
# leaf, and for aoexact the fanin can also reference `aN` (negated PI rail).

_LEAF_RE = re.compile(r"^\s*(!?)\s*([A-Za-z][A-Za-z0-9]*)\s*$")
# 2-input gate: <fanin1> <op> <fanin2>
_BIN_RE  = re.compile(r"^\s*(.+?)\s*([&|])\s*(.+?)\s*$")


def eval_leaf(token, env):
    m = _LEAF_RE.match(token)
    if not m:
        raise ValueError(f"unparseable leaf {token!r}")
    neg, name = m.group(1), m.group(2)
    if name not in env:
        raise KeyError(f"undefined name {name!r}")
    v = env[name]
    return (~v) & 0xFFFFFFFF if neg == "!" else v


def eval_expr(expr, env, n_bits):
    """Evaluate a single chain RHS; returns an integer bitmask of length n_bits."""
    mask = (1 << n_bits) - 1
    bm = _BIN_RE.match(expr)
    if bm:
        a, op, b = bm.group(1), bm.group(2), bm.group(3)
        va = eval_leaf(a, env)
        vb = eval_leaf(b, env)
        if op == "&":
            return (va & vb) & mask
        elif op == "|":
            return (va | vb) & mask
    # else: pure leaf alias (e.g., F = n12, F = !G)
    return eval_leaf(expr, env) & mask


# ---------- per-row simulation ----------

def make_pi_columns(n_in):
    """Return dict mapping PI name -> truth-table column bitmask of length 2^n.
    Convention: bit i of the column is value of that PI on minterm i,
    where minterm i = (a, b, c, ...) with a = bit0 of i."""
    n = 1 << n_in
    env = {}
    for k, name in enumerate(["a", "b", "c", "d", "e", "f", "g"][:n_in]):
        col = 0
        for i in range(n):
            if (i >> k) & 1:
                col |= (1 << i)
        env[name] = col
        env[name + "N"] = (~col) & ((1 << n) - 1)
    return env


def simulate(chain_entries, n_in, dialect):
    env = make_pi_columns(n_in)
    n_bits = 1 << n_in
    # Process in declaration order; for andexact the chain is printed
    # output-first then internal in reverse build order. We need to process
    # ASSIGNMENTS in dependency order, but each line is `<lhs> = <expr>` and
    # we don't know ordering a priori — so we iterate fixpoint-style.
    pending = list(chain_entries)
    last_progress = -1
    while pending and last_progress != len(pending):
        last_progress = len(pending)
        next_pending = []
        for lhs, rhs in pending:
            try:
                v = eval_expr(rhs, env, n_bits)
            except KeyError:
                next_pending.append((lhs, rhs))
                continue
            env[lhs] = v
        pending = next_pending
    if pending:
        raise ValueError(f"could not resolve dependencies: {pending}")
    return env


def tt_from_hex(hex_str, n_in):
    """Convert hex truth table (bit 0 = f(0..0)) to a bitmask of length 2^n_in.
    The input string must have exactly 2^n_in / 4 hex digits."""
    n_bits = 1 << n_in
    expected = max(1, n_bits // 4)
    s = hex_str.lower()
    if len(s) < expected:
        s = s.zfill(expected)
    if len(s) != expected:
        raise ValueError(f"truth table {hex_str!r} should have {expected} hex digits")
    val = int(s, 16)
    return val & ((1 << n_bits) - 1)


# ---------- driver ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="TSV from a sweep")
    ap.add_argument("--n-in", type=int, required=True)
    ap.add_argument("--dialect", choices=["aig", "ao"], required=True,
                    help="aig=andexact, ao=aoexact (different node naming)")
    ap.add_argument("--report", help="write per-row outcome TSV")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.input), delimiter="\t"))
    n_bits = 1 << args.n_in
    mask = (1 << n_bits) - 1
    outcomes = Counter()
    failures = []
    detailed = []
    for r in rows:
        # Verify any row that has a chain — sat/ub are valid SAT solutions;
        # timeout rows have no chain and are skipped.
        if r.get("status") not in ("sat", "ok", "ub") or not r.get("chain"):
            outcomes["skip_no_chain"] += 1
            detailed.append((r, "skip_no_chain", ""))
            continue
        try:
            chain = parse_chain(r["chain"], args.dialect)
        except Exception as e:
            outcomes["parse_fail"] += 1
            failures.append((r, f"parse: {e}"))
            detailed.append((r, "parse_fail", str(e)))
            continue
        try:
            env = simulate(chain, args.n_in, args.dialect)
        except Exception as e:
            outcomes["sim_fail"] += 1
            failures.append((r, f"sim: {e}"))
            detailed.append((r, "sim_fail", str(e)))
            continue
        # Check each output truth table
        # tt0 always present; tt1, tt2, ... if multi-output
        tt_cols = []
        for col in ("tt0", "tt1", "tt2", "tt3"):
            if col in r and r[col]:
                tt_cols.append(r[col])
        # Output names follow tool convention
        if args.dialect == "aig":
            # andexact prints F (1-output) or F0/F1 (multi-output)
            out_names = ["F"] if len(tt_cols) == 1 else [f"F{i}" for i in range(len(tt_cols))]
        else:
            # aoexact prints F (1-out) or F0..Fk (multi-out); FN-rails are
            # outputs but should match ~F
            out_names = ["F"] if len(tt_cols) == 1 else [f"F{i}" for i in range(len(tt_cols))]
        ok = True
        detail = []
        for nm, tt_hex in zip(out_names, tt_cols):
            if nm not in env:
                ok = False
                detail.append(f"missing output {nm}")
                continue
            got = env[nm] & mask
            want = tt_from_hex(tt_hex, args.n_in)
            if got != want:
                ok = False
                detail.append(f"{nm}: got 0x{got:0{max(1,n_bits//4)}x} want 0x{want:0{max(1,n_bits//4)}x}")
        # For aoexact, also verify FN-rail equals ~F where present
        if args.dialect == "ao":
            for nm in out_names:
                fn = nm + "N"
                if fn in env:
                    got = env[fn] & mask
                    want = (~env[nm]) & mask
                    if got != want:
                        ok = False
                        detail.append(f"{fn}: got 0x{got:x} not equal to ~{nm}=0x{want:x}")
        if ok:
            outcomes["ok"] += 1
            detailed.append((r, "ok", ""))
        else:
            outcomes["MISMATCH"] += 1
            failures.append((r, "; ".join(detail)))
            detailed.append((r, "MISMATCH", "; ".join(detail)))

    print(f"input: {args.input}")
    print(f"rows: {len(rows)}")
    for k, v in outcomes.most_common():
        print(f"  {k}: {v}")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r, msg in failures[:15]:
            tt0 = r.get("tt0", "?")
            tt1 = r.get("tt1", "")
            print(f"  tt={tt0}{','+tt1 if tt1 else ''} k={r.get('gates','?')}: {msg}")

    if args.report:
        with open(args.report, "w") as f:
            w = csv.writer(f, delimiter="\t")
            tts = [c for c in ("tt0", "tt1") if c in (rows[0] if rows else {})]
            w.writerow(tts + ["status", "gates", "verify_outcome", "verify_detail"])
            for r, outcome, det in detailed:
                w.writerow([r.get(c, "") for c in tts] + [r.get("status", ""), r.get("gates", ""), outcome, det])
        print(f"\nWrote per-row report to {args.report}")

    sys.exit(1 if outcomes["MISMATCH"] or outcomes["sim_fail"] or outcomes["parse_fail"] else 0)


if __name__ == "__main__":
    main()
