#!/usr/bin/env python3
"""Find optimal AIG (`andexact`) gate count for every NPNP-canonical 3-input
2-output function.

Reads /work/npnp/classes_n3_m2.txt, runs `andexact -m -M MAX -T PERM` on
each entry in a thread pool, and writes a tab-separated result file:

    tt0\ttt1\tstatus\tgates\twall_s\tchain

`status` ∈ {"sat", "timeout"}; `chain` is the raw gate listing from ABC's
solution printout (one line per gate, semicolon-separated), useful as a
proof-of-circuit. Hard cases that don't resolve within the per-function
wall budget are recorded as "timeout".
"""

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import time

ABC = "/work/abc/abc"
DEFAULT_INPUT = "/work/npnp/classes_n3_m2.txt"

GATE_LINE_RE = re.compile(r"^([A-P]) =\s*(.*)$")
GATES_RE = re.compile(r"using\s+(\d+)\s+two-input and-nodes")


def read_classes(path):
    out = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split()
            if len(parts) >= 2:
                out.append((parts[0], parts[1]))
    return out


def run_one(tt0, tt1, max_nodes, per_m_timeout, wall_timeout):
    """Return dict with keys: tt0, tt1, status, gates, wall_s, chain."""
    cmd = [
        ABC, "-q",
        f"andexact -N 3 -O 2 -m -M {max_nodes} -T {per_m_timeout} -s {tt0},{tt1}",
    ]
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=wall_timeout,
        )
        out = p.stdout + p.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        timed_out = True
    wall = time.time() - t0

    # Walk lines from the bottom of the last realization block (the SAT one).
    gates = None
    chain_lines = []
    capture = False
    last_block = []
    blocks = []
    for ln in out.splitlines():
        m = GATES_RE.search(ln)
        if m:
            gates = int(m.group(1))
            blocks.append(last_block)
            last_block = []
            capture = True
            continue
        if capture:
            if ln.startswith("Finished") or ln.startswith("Total runtime") \
               or ln.startswith("Running") or ln.strip() == "":
                continue
            stripped = ln.strip()
            if stripped:
                last_block.append(stripped)
    if last_block:
        blocks.append(last_block)
    if blocks:
        chain_lines = blocks[-1]

    if gates is not None:
        status = "sat"
    elif timed_out or "timed out" in out:
        status = "timeout"
    else:
        status = "unknown"

    return {
        "tt0": tt0,
        "tt1": tt1,
        "status": status,
        "gates": gates if gates is not None else "",
        "wall_s": f"{wall:.2f}",
        "chain": " ; ".join(chain_lines),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--output", default="/tmp/aig_npnp_n3_m2.tsv")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--max-nodes", type=int, default=12)
    ap.add_argument("--per-m-timeout", type=int, default=20,
                    help="ABC -T per-M timeout in seconds")
    ap.add_argument("--wall-timeout", type=int, default=120,
                    help="hard per-function wall timeout in seconds")
    ap.add_argument("--limit", type=int, default=0,
                    help="limit number of entries (debug)")
    args = ap.parse_args()

    cls = read_classes(args.input)
    if args.limit:
        cls = cls[: args.limit]

    print(f"Sweeping {len(cls)} classes with {args.workers} workers, "
          f"-M {args.max_nodes} -T {args.per_m_timeout} wall {args.wall_timeout}s",
          flush=True)

    rows = []
    started = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_one, t0, t1, args.max_nodes,
                        args.per_m_timeout, args.wall_timeout): (i, t0, t1)
            for i, (t0, t1) in enumerate(cls)
        }
        done = 0
        for fut in cf.as_completed(futures):
            i, t0, t1 = futures[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"tt0": t0, "tt1": t1, "status": f"err:{exc}",
                       "gates": "", "wall_s": "", "chain": ""}
            rows.append(row)
            done += 1
            if done % 25 == 0 or done == len(cls):
                el = time.time() - started
                ok = sum(1 for r in rows if r["status"] == "sat")
                to = sum(1 for r in rows if r["status"] == "timeout")
                print(f"[{done}/{len(cls)}] elapsed={el:.1f}s  sat={ok} timeout={to}",
                      flush=True)

    rows.sort(key=lambda r: (int(r["tt0"], 16), int(r["tt1"], 16)))
    with open(args.output, "w") as fh:
        fh.write("tt0\ttt1\tstatus\tgates\twall_s\tchain\n")
        for r in rows:
            fh.write(f"{r['tt0']}\t{r['tt1']}\t{r['status']}\t{r['gates']}\t{r['wall_s']}\t{r['chain']}\n")

    # quick histogram
    hist = {}
    for r in rows:
        k = r["gates"] if r["status"] == "sat" else r["status"]
        hist[k] = hist.get(k, 0) + 1
    print(f"\nWrote {args.output}\nGate-count histogram (gates → count):")
    for k in sorted(hist.keys(), key=lambda x: (str(x).isdigit() and int(x) or 999, str(x))):
        print(f"  {k}: {hist[k]}")


if __name__ == "__main__":
    main()
