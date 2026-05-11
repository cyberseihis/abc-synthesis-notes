#!/usr/bin/env python3
"""Initialize a bound-tracking state TSV for an (engine, n, m) sweep.

For `andexact` (AIG):
    For each truth-table in --classes, run iter mode 0..max-nodes within
    the per-class wall budget. Records every per-M outcome (sat/unsat/
    timeout) in the attempts list; derives hi_unsat/lo_sat/status.

For `aoexact` (AO):
    Per rule 1 (no point running AO without proven AIG min K), this script
    does NOT probe AO directly. Instead it reads an AIG state TSV via
    --aig-state and, for each row with status=proven, emits an AO row
    with lo_sat = 2*K (constructive bound), hi_unsat = (2*K - 1 - 1) only
    if K == 0 (trivial case: AO = 0 too). Otherwise hi_unsat empty and
    status=gap. Rows where AIG is not proven get status=aig_unproven and
    no probes are scheduled; resume will skip them too.

State file is overwritten by this command (it's the v0 baseline). Resume
always writes new files (state_resume.py auto-increments).
"""
import argparse
import concurrent.futures as cf
import os
import sys
import time

# Allow running as `python3 scripts/state_init.py` from project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _state_io import (write_state, read_state, make_row, derive_status,
                       derive_bounds)
from _exa_run import run_iter


def read_classes(path):
    out = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            out.append(ln.split())
    return out


def init_aig(args):
    classes = read_classes(args.classes)
    print(f"AIG init: {len(classes)} classes, max-M={args.max_nodes}, "
          f"per-M={args.per_m_timeout}s, wall={args.wall_timeout}s, "
          f"workers={args.workers}", flush=True)

    def task(tts):
        tt = ",".join(tts)
        r = run_iter("andexact", args.n_in, args.n_out, tt,
                     args.max_nodes, args.per_m_timeout, args.wall_timeout)
        return tts, r

    rows = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(task, t): t for t in classes}
        done = 0
        for fut in cf.as_completed(futs):
            tts, r = fut.result()
            tt = ",".join(tts)
            row = make_row(tt, "andexact", args.n_in, args.n_out,
                           hi_unsat=r["hi_unsat"], lo_sat=r["lo_sat"],
                           chain=r["chain"], attempts=r["attempts"])
            rows.append(row)
            done += 1
            if done % 25 == 0 or done == len(classes):
                el = time.time() - t0
                proven = sum(1 for x in rows if x["status"] == "proven")
                gap = sum(1 for x in rows if x["status"] == "gap")
                unb = sum(1 for x in rows if x["status"] == "unbounded")
                print(f"  [{done}/{len(classes)}] el={el:.1f}s  "
                      f"proven={proven} gap={gap} unbounded={unb}", flush=True)
    rows.sort(key=lambda r: tuple(int(x, 16) for x in r["tt"].split(",")))
    write_state(args.output, rows)
    summarize(rows)


def init_ao(args):
    if not args.aig_state:
        sys.exit("aoexact init requires --aig-state pointing at a proven AIG state TSV")
    aig_rows = read_state(args.aig_state)
    # Validate n_in/n_out match.
    mismatch = [r for r in aig_rows
                if r["n_in"] != args.n_in or r["n_out"] != args.n_out]
    if mismatch:
        sys.exit(f"AIG state has n_in/n_out mismatch with requested "
                 f"({args.n_in},{args.n_out}); first offender: {mismatch[0]['tt']}")

    rows = []
    n_aig_proven = 0
    n_trivial = 0
    n_aig_unproven = 0
    for ar in aig_rows:
        tt = ar["tt"]
        if ar["status"] == "proven":
            K = ar["lo_sat"]
            n_aig_proven += 1
            if K == 0:
                # Trivial AIG (constant or PI). AO must be 0 too (PO can
                # select const / dual-rail PI directly without gates).
                row = make_row(tt, "aoexact", args.n_in, args.n_out,
                               hi_unsat=None, lo_sat=0, chain="",
                               attempts=[])
                n_trivial += 1
            else:
                # Constructive bound: AO ≤ 2*K. We don't run probes here.
                row = make_row(tt, "aoexact", args.n_in, args.n_out,
                               hi_unsat=None, lo_sat=2 * K, chain="",
                               attempts=[])
        else:
            # Rule 1: no proven K → don't run AO at all.
            row = make_row(tt, "aoexact", args.n_in, args.n_out,
                           hi_unsat=None, lo_sat=None, chain="", attempts=[])
            row["status"] = "aig_unproven"
            n_aig_unproven += 1
        rows.append(row)
    rows.sort(key=lambda r: tuple(int(x, 16) for x in r["tt"].split(",")))
    write_state(args.output, rows)
    print(f"AO init from AIG state {args.aig_state}:")
    print(f"  AIG proven (incl. trivial): {n_aig_proven}  "
          f"(trivial K=0: {n_trivial})")
    print(f"  AIG unproven (skipped):     {n_aig_unproven}")
    summarize(rows)


def summarize(rows):
    from collections import Counter
    c = Counter(r["status"] for r in rows)
    print(f"\nWrote state with {len(rows)} rows. Status breakdown:")
    for k in ("proven", "gap", "unbounded", "aig_unproven"):
        if c[k]:
            print(f"  {k:14s} {c[k]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["andexact", "aoexact"], required=True)
    ap.add_argument("--n-in", type=int, required=True)
    ap.add_argument("--n-out", type=int, required=True)
    ap.add_argument("--output", required=True, help="state TSV to write")
    # AIG-only
    ap.add_argument("--classes", help="class-list file (for AIG init)")
    ap.add_argument("--max-nodes", type=int, default=16,
                    help="iter walks 0..max-nodes (AIG only)")
    ap.add_argument("--per-m-timeout", type=int, default=30,
                    help="per-M wall ceiling inside iter (AIG only)")
    ap.add_argument("--wall-timeout", type=int, default=180,
                    help="overall per-class wall budget (AIG only)")
    ap.add_argument("--workers", type=int, default=32)
    # AO-only
    ap.add_argument("--aig-state",
                    help="proven AIG state TSV (required for aoexact init)")
    args = ap.parse_args()

    if args.engine == "andexact":
        if not args.classes:
            sys.exit("--classes is required for andexact init")
        init_aig(args)
    else:
        init_ao(args)


if __name__ == "__main__":
    main()
