#!/usr/bin/env python3
"""Generalized NPNP-class sweep: runs `andexact` or `aoexact` on every class
in a /work/npnp/classes_nN_mM.txt file and writes a TSV with the proven
minimum gate count + chain.

Usage:
  python3 exact_npnp_sweep.py --engine andexact --n-in 3 --n-out 1 \
      --input /work/npnp/classes_n3_m1.txt --output /work/npnp/aig_npnp_n3_m1.tsv

Status field uses 'sat' for proven minima from the -m sweep, 'ub' for
upper-bound results from a direct -M probe (set --status-override ub),
and 'timeout' / 'unknown' otherwise.
"""

import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import time

ABC = "/work/abc/abc"

GATES_RE_AIG = re.compile(r"using\s+(\d+)\s+two-input and-nodes")
GATES_RE_AO = re.compile(r"using\s+(\d+)\s+two-input AND/OR gates")


def read_classes(path):
    """Read class file. Returns list of TT tuples (one per line, possibly
    multi-output as space-separated hex)."""
    out = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            out.append(tuple(ln.split()))
    return out


def run_one(engine, n_in, n_out, tts, max_nodes, per_m_timeout, wall_timeout, sweep=True):
    tts_arg = ",".join(tts)
    if sweep:
        m_flag = f"-m -M {max_nodes}"
    else:
        m_flag = f"-M {max_nodes}"
    cmd = [ABC, "-q",
           f"{engine} -N {n_in} -O {n_out} {m_flag} -T {per_m_timeout} -s {tts_arg}"]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=wall_timeout)
        out = p.stdout + p.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        def _s(v):
            if v is None: return ""
            if isinstance(v, bytes): return v.decode("utf-8", "replace")
            return v
        out = _s(e.stdout) + _s(e.stderr)
        timed_out = True
    wall = time.time() - t0

    GATES_RE = GATES_RE_AO if engine == "aoexact" else GATES_RE_AIG

    # Capture the LAST realization block (the SAT one).
    gates = None
    blocks = []
    last_block = []
    capture = False
    for ln in out.splitlines():
        m = GATES_RE.search(ln)
        if m:
            gates = int(m.group(1))
            blocks.append(last_block)
            last_block = []
            capture = True
            continue
        if capture:
            if (ln.startswith("Finished") or ln.startswith("Total runtime") or
                ln.startswith("Running") or ln.strip() == ""):
                continue
            stripped = ln.strip()
            if stripped:
                last_block.append(stripped)
    if last_block:
        blocks.append(last_block)
    chain_lines = blocks[-1] if blocks else []

    if gates is not None:
        status = "sat"
    elif timed_out or "timed out" in out:
        status = "timeout"
    else:
        status = "unknown"

    return {"tts": tts, "status": status,
            "gates": gates if gates is not None else "",
            "wall_s": f"{wall:.2f}",
            "chain": " ; ".join(chain_lines)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=["andexact", "aoexact"])
    ap.add_argument("--n-in", type=int, required=True)
    ap.add_argument("--n-out", type=int, required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--max-nodes", type=int, default=16)
    ap.add_argument("--per-m-timeout", type=int, default=30)
    ap.add_argument("--wall-timeout", type=int, default=180)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cls = read_classes(args.input)
    if args.limit:
        cls = cls[: args.limit]

    print(f"Engine={args.engine} n={args.n_in} m={args.n_out} count={len(cls)} "
          f"workers={args.workers} M<={args.max_nodes} T={args.per_m_timeout} "
          f"wall={args.wall_timeout}", flush=True)

    rows = []
    started = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(run_one, args.engine, args.n_in, args.n_out, t,
                            args.max_nodes, args.per_m_timeout,
                            args.wall_timeout): t
                for t in cls}
        done = 0
        for fut in cf.as_completed(futs):
            t = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"tts": t, "status": f"err:{exc}", "gates": "",
                       "wall_s": "", "chain": ""}
            rows.append(row)
            done += 1
            if done % 25 == 0 or done == len(cls):
                el = time.time() - started
                ok = sum(1 for r in rows if r["status"] == "sat")
                to = sum(1 for r in rows if r["status"] == "timeout")
                print(f"[{done}/{len(cls)}] elapsed={el:.1f}s  sat={ok} timeout={to}",
                      flush=True)

    rows.sort(key=lambda r: tuple(int(x, 16) for x in r["tts"]))

    cols = [f"tt{i}" for i in range(args.n_out)]
    with open(args.output, "w") as fh:
        fh.write("\t".join(cols + ["status", "gates", "wall_s", "chain"]) + "\n")
        for r in rows:
            fh.write("\t".join(list(r["tts"])
                               + [r["status"], str(r["gates"]),
                                  r["wall_s"], r["chain"]]) + "\n")

    hist = {}
    for r in rows:
        k = r["gates"] if r["status"] == "sat" else r["status"]
        hist[k] = hist.get(k, 0) + 1
    print(f"\nWrote {args.output}\nHistogram:")
    for k in sorted(hist.keys(),
                    key=lambda x: (str(x).isdigit() and int(x) or 999, str(x))):
        print(f"  {k}: {hist[k]}")


if __name__ == "__main__":
    main()
