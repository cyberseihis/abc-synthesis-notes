#!/usr/bin/env python3
"""Render each sub-2x class's truth-table pair as a Boolean formula.

A class (tt0, tt1) is `sub-2x` when ao_min < 2 * aig_min, where:
  * aig_min comes from an `andexact` sweep (column 'gates', status=sat)
  * ao_min comes from an `aoexact` sweep (combined view: column 'gates' on
    status sat or ub; rows with status=timeout are skipped).

The class is `proven` sub-2x if the AO row is sat; `sound` if it is ub
(the AO chain has gate count k, but the engine couldn't prove k-1 UNSAT).

F0 and F1 are rendered via `sympy.simplify_logic` (DNF preferred for
sum-of-cubes readability). For F = XOR-of-all-vars we substitute the XOR
form, which is concise where simplify_logic produces 4 minterms.
"""
import argparse
import csv
import sys

from sympy import symbols, simplify_logic
from sympy.logic.boolalg import SOPform


def read_tsv(path):
    with open(path) as f:
        header = next(csv.reader(f, delimiter="\t"))
        return [dict(zip(header, p)) for p in csv.reader(f, delimiter="\t")]


def render_formula(tt, vars_):
    n = len(vars_)
    on = [i for i in range(1 << n) if (tt >> i) & 1]
    if not on:
        return "0"
    if len(on) == (1 << n):
        return "1"
    # Convention bridge: SOPform treats the FIRST variable in `vars_` as MSB of
    # the minterm index. Our sweep TSVs encode the LSB as `a` (bit 0 of `tt`).
    # Pass vars in reverse to SOPform so that minterm index i decodes as
    # (a = i&1, b = (i>>1)&1, c = (i>>2)&1) — matching the TSV convention.
    sop = SOPform(list(reversed(vars_)), on)
    f_dnf = simplify_logic(sop, form="dnf", deep=True)
    f_cnf = simplify_logic(sop, form="cnf", deep=True)
    s_dnf = str(f_dnf).replace(" ", "")
    s_cnf = str(f_cnf).replace(" ", "")
    candidates = [s_dnf, s_cnf]
    # Detect parity (XOR of all vars): on-set = all minterms with odd popcount.
    odd_pop = {i for i in range(1 << n) if bin(i).count("1") & 1}
    if set(on) == odd_pop:
        candidates.append(" ^ ".join(str(v) for v in vars_))
    # Round-trip: evaluate the chosen formula at every input and confirm it
    # reproduces `tt` exactly. Cheap (2^n evals) and catches convention bugs.
    chosen = min(candidates, key=len)
    chosen_expr = simplify_logic(sop, form="dnf", deep=True)  # canonical for eval
    recomputed = 0
    for i in range(1 << n):
        env = {v: bool((i >> idx) & 1) for idx, v in enumerate(vars_)}
        if bool(chosen_expr.subs(env)):
            recomputed |= (1 << i)
    if recomputed != tt:
        raise AssertionError(
            f"formula round-trip mismatch for tt=0x{tt:02x}: "
            f"recomputed=0x{recomputed:02x}, formula={chosen_expr}"
        )
    return chosen


def collect_sub2x(aig_path, ao_path, ao_audit_path=None):
    aig = {(r["tt0"], r["tt1"]): r for r in read_tsv(aig_path)}
    ao  = {(r["tt0"], r["tt1"]): r for r in read_tsv(ao_path)}
    ao_audit = {}
    if ao_audit_path:
        try:
            for r in read_tsv(ao_audit_path):
                t = r["tt"].split(",")
                ao_audit[(t[0], t[1])] = r["verdict"]
        except FileNotFoundError:
            print(f"# warning: AO audit TSV {ao_audit_path} not found; "
                  "using sweep status only", file=sys.stderr)
    out = []
    for k, ar in aig.items():
        aig_k = int(ar["gates"])
        if aig_k == 0:
            continue
        or_ = ao[k]
        if or_["status"] == "timeout":
            continue
        ao_k = int(or_["gates"])
        if ao_k < 2 * aig_k:
            # "proven sub-2x" requires AO_min pinned exactly. We mark a row as
            # `proven` if either (a) sweep iter-status is sat (every smaller M
            # was UNSAT during the iter walk), OR (b) the audit returned proven
            # / trivial at M = k − 1. Otherwise `sound` — the inequality still
            # holds, but the savings could be larger.
            verdict = ao_audit.get(k)
            is_proven = (or_["status"] == "sat") or (verdict in ("proven", "trivial"))
            out.append({
                "tt0": k[0], "tt1": k[1],
                "aig": aig_k, "ao": ao_k,
                "saved": 2 * aig_k - ao_k,
                "pct": 100.0 * (2 * aig_k - ao_k) / (2 * aig_k),
                "verdict": "proven" if is_proven else "sound",
            })
    out.sort(key=lambda r: (-r["pct"], r["aig"]))
    return out


def render_table(rows, vars_, fmt):
    if fmt == "markdown":
        print("| # | (tt0, tt1) | aig | ao | saved | proof | F0 | F1 |")
        print("|--:|---|--:|--:|--:|---|---|---|")
        for i, r in enumerate(rows, start=1):
            f0 = render_formula(int(r["tt0"], 16), vars_)
            f1 = render_formula(int(r["tt1"], 16), vars_)
            print(f"| {i} | ({r['tt0']}, {r['tt1']}) | {r['aig']} | {r['ao']} | "
                  f"{r['saved']} ({r['pct']:.0f}%) | {r['verdict']} | "
                  f"{f0} | {f1} |")
    else:
        print(f"# {len(rows)} sub-2x classes (n={len(vars_)}, m=2)")
        hdr = f"{'#':>3}  {'(tt0,tt1)':10s}  {'aig':>3s} {'ao':>3s} {'sav':>3s} {'pct':>5s}  {'verdict':6s}"
        print(hdr + "   F0                                F1")
        print("-" * 130)
        for i, r in enumerate(rows, start=1):
            f0 = render_formula(int(r["tt0"], 16), vars_)
            f1 = render_formula(int(r["tt1"], 16), vars_)
            print(f"{i:>3}  ({r['tt0']}, {r['tt1']})    {r['aig']:>3d} {r['ao']:>3d} "
                  f"{r['saved']:>3d} {r['pct']:>4.1f}%  {r['verdict']:6s}   "
                  f"{f0:32s}   {f1}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aig", default="/work/npnp/aig_npnp_n3_m2.tsv",
                    help="andexact sweep TSV (default: %(default)s)")
    ap.add_argument("--ao",  default="/work/npnp/aoexact_npnp_n3_m2_combined.tsv",
                    help="aoexact combined-view TSV (default: %(default)s)")
    ap.add_argument("--ao-audit", default="/work/npnp/audit_ao_n3_m2_combined.tsv",
                    help="AO audit TSV used to upgrade sweep-ub to proven where possible "
                         "(default: %(default)s)")
    ap.add_argument("--n-in", type=int, default=3, help="number of input vars (default: 3)")
    ap.add_argument("--format", choices=["text", "markdown"], default="markdown")
    args = ap.parse_args()

    vars_ = symbols(" ".join("abcdefghij"[:args.n_in]))
    if args.n_in == 1:
        vars_ = (vars_,)
    rows = collect_sub2x(args.aig, args.ao, args.ao_audit)
    render_table(rows, vars_, args.format)


if __name__ == "__main__":
    main()
