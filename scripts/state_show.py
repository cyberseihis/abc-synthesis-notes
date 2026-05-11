#!/usr/bin/env python3
"""Pretty-print a bound-tracking state TSV. With both an AIG and an AO
state file, also produces the 2× classification table.

Usage:
  state_show.py state_aig.tsv
  state_show.py state_aig.tsv state_ao.tsv
  state_show.py state_aig.tsv state_ao.tsv --list-gaps
  state_show.py state_aig.tsv state_ao.tsv --list-sub2x
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _state_io import read_state


def summarize(rows, label):
    c = Counter(r["status"] for r in rows)
    print(f"\n=== {label} ({len(rows)} rows) ===")
    for k in ("proven", "gap", "unbounded", "aig_unproven"):
        if c[k]:
            print(f"  {k:14s} {c[k]}")
    # Sat-bounds histogram (for proven rows: this is the true min)
    proven_hist = Counter(r["lo_sat"] for r in rows if r["status"] == "proven")
    if proven_hist:
        print("  proven lo_sat (=true min) histogram:")
        for k in sorted(proven_hist.keys()):
            print(f"    M={k}: {proven_hist[k]}")


def list_gaps(rows, label):
    print(f"\n--- {label}: unresolved gaps ---")
    rows = [r for r in rows if r["status"] in ("gap", "unbounded")]
    if not rows:
        print("  (none)")
        return
    rows.sort(key=lambda r: (r["lo_sat"] is None,
                             (r["lo_sat"] or 0) - (r["hi_unsat"] or -1) - 1,
                             r["tt"]))
    for r in rows:
        hi = r["hi_unsat"] if r["hi_unsat"] is not None else "-"
        lo = r["lo_sat"] if r["lo_sat"] is not None else "-"
        timeouts = sum(1 for a in r["attempts"] if a["outcome"] == "timeout")
        max_budget = max((a["budget_s"] for a in r["attempts"]), default=0)
        print(f"  {r['tt']:>10s}  hi_unsat={hi}  lo_sat={lo}  "
              f"timeouts={timeouts}  max_budget={max_budget:.0f}s")


def pair_2x(aig_rows, ao_rows):
    """Produce the 2× classification table:
    trivial / sub2x_proven / sub2x_sound / at2x_proven / at2x_sound /
    above2x / no_ao_bound / no_ao_row / aig_unproven."""
    by_tt_ao = {r["tt"]: r for r in ao_rows}
    bucket = Counter()
    details = []
    for ar in aig_rows:
        tt = ar["tt"]
        ao = by_tt_ao.get(tt)
        if ao is None:
            bucket["no_ao_row"] += 1
            continue
        if ar["status"] != "proven":
            bucket["aig_unproven"] += 1
            continue
        K = ar["lo_sat"]
        if K == 0:
            bucket["trivial"] += 1
            details.append((tt, K, ao["lo_sat"], "trivial"))
            continue
        if ao["status"] == "aig_unproven":
            # Shouldn't happen if pairing is consistent, but guard anyway.
            bucket["aig_unproven"] += 1
            continue
        if ao["lo_sat"] is None:
            bucket["no_ao_bound"] += 1
            details.append((tt, K, None, "no_ao_bound"))
            continue
        g = ao["lo_sat"]
        ao_proven = (ao["status"] == "proven")
        if g < 2 * K:
            label = "sub2x_proven" if ao_proven else "sub2x_sound"
        elif g == 2 * K:
            label = "at2x_proven" if ao_proven else "at2x_sound"
        else:
            label = "above2x"
        bucket[label] += 1
        details.append((tt, K, g, label))

    print("\n=== 2× classification ===")
    print(f"  Total AIG rows:      {len(aig_rows)}")
    for k in ("trivial",
              "sub2x_proven", "sub2x_sound",
              "at2x_proven",  "at2x_sound",
              "above2x", "no_ao_bound", "no_ao_row", "aig_unproven"):
        if bucket[k]:
            print(f"  {k:14s} {bucket[k]}")
    sub2x = bucket["sub2x_proven"] + bucket["sub2x_sound"]
    print(f"\n  sub-2× total (proven + sound): {sub2x}")
    return details, bucket


def list_sub2x(details, ao_rows):
    by_tt_ao = {r["tt"]: r for r in ao_rows}
    rows = [d for d in details if d[3] in ("sub2x_proven", "sub2x_sound")]
    if not rows:
        print("\n  No sub-2× rows.")
        return
    print(f"\n--- sub-2× rows ({len(rows)}) ---")
    rows.sort(key=lambda x: (x[3], x[1], x[2], x[0]))
    for tt, K, g, label in rows:
        chain = by_tt_ao[tt]["chain"][:120]
        if len(by_tt_ao[tt]["chain"]) > 120:
            chain += " ..."
        savings = (2 * K - g) / (2 * K) * 100 if K else 0
        print(f"  {tt:>10s}  aig={K}  ao={g}  (2K={2*K}, -{savings:4.1f}%)  "
              f"[{label}]")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("aig_state")
    ap.add_argument("ao_state", nargs="?", default=None)
    ap.add_argument("--list-gaps", action="store_true")
    ap.add_argument("--list-sub2x", action="store_true")
    args = ap.parse_args()

    aig_rows = read_state(args.aig_state)
    summarize(aig_rows, f"AIG state ({args.aig_state})")
    if args.list_gaps:
        list_gaps(aig_rows, "AIG")

    if not args.ao_state:
        return

    ao_rows = read_state(args.ao_state)
    summarize(ao_rows, f"AO state ({args.ao_state})")
    if args.list_gaps:
        list_gaps(ao_rows, "AO")

    details, _ = pair_2x(aig_rows, ao_rows)
    if args.list_sub2x:
        list_sub2x(details, ao_rows)


if __name__ == "__main__":
    main()
