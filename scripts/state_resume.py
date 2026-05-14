#!/usr/bin/env python3
"""Continue a bound-tracking sweep: pick the next M to probe per row,
run fixed-M calls with the new budget, write a NEW state file.

The resume never overwrites the input file. Output is auto-versioned
(`state.tsv` → `state_v1.tsv`; `state_v1.tsv` → `state_v2.tsv`; ...)
unless --output is given explicitly.

Per-row probe selection
-----------------------

AIG (andexact):
  Goal: tighten the proven minimum.
  - If status=proven: nothing to do, skip.
  - If gap (hi_unsat+1 < lo_sat): probe smallest untried M in
    [hi_unsat+1, lo_sat-1]. If all are tried (every M in the gap was
    timeout last time), retry the smallest of those with the new budget.
  - If unbounded (no SAT yet): probe smallest untried M starting at
    (hi_unsat+1 if known else 0), bounded by --max-nodes.

AO (aoexact), with paired AIG-min K  (stored as initial lo_sat = 2*K):
  Per the experiment rules:
    1. No probes if status=aig_unproven (no proven K).
    2. Never probe M ≥ 2*K (constructive bound; SAT is guaranteed there).
    3. Don't probe M < lo_sat - 1 without SAT at lo_sat - 1.

  Effectively: walk down. Probe lo_sat - 1 if not yet probed (or last
  attempt timed out and we have more budget now). If everything from
  lo_sat - 1 down to hi_unsat + 1 is already settled, status would have
  been `proven` — so we never get here with no candidates.

Each probe records {M, budget_s, outcome, wall_s} in the row's attempts
list. SAT outcomes update lo_sat (and chain); UNSAT outcomes update
hi_unsat; timeouts only update attempts (so the resume can choose to
retry later with more budget).
"""
import argparse
import concurrent.futures as cf
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _state_io import (read_state, write_state, update_row_with_attempt,
                       next_version_path, derive_bounds, derive_status,
                       tried_with_min_budget, resolved_M_values)
from _exa_run import run_fixed_M


def _atomic_write_state(path, rows):
    """Write state then atomically replace `path`. POSIX rename ⇒ a kill
    mid-write leaves either the old file or the fully-written new one."""
    tmp = path + ".tmp"
    write_state(tmp, rows)
    os.replace(tmp, path)


def pick_next_M_aig(row, max_M, new_budget):
    """For AIG, probe smallest untried M in (hi_unsat, lo_sat). If
    everything in the gap is settled, return None. If everything is
    timed out, retry the smallest with a larger budget.

    For unbounded rows (no SAT yet), probe upward from hi_unsat+1
    up to max_M.
    """
    if row["status"] == "proven":
        return None
    hi = row["hi_unsat"] if row["hi_unsat"] is not None else -1
    lo = row["lo_sat"] if row["lo_sat"] is not None else (max_M + 1)
    settled = resolved_M_values(row["attempts"])
    timeouts = tried_with_min_budget(row["attempts"])

    # Smallest M in (hi, lo) that has no resolved outcome AND no prior
    # timeout (we'd rather try a fresh M before retrying a known-hard one).
    for M in range(hi + 1, lo):
        if M not in settled and M not in timeouts:
            return M
    # All gap-M either settled or timed out. Retry the smallest unsettled
    # timeout, only if the new budget exceeds what it last got.
    for M in range(hi + 1, lo):
        if M in timeouts and M not in settled and timeouts[M] < new_budget:
            return M
    return None


def pick_next_M_ao(row, new_budget):
    """For AO, the only legal probe is M = lo_sat - 1 (rule 3: don't
    probe below 2K-1 unless we have SAT at 2K-1). We never widen the
    upper bound (rule 2: SAT at M ≥ 2K is guaranteed, no point).

    Walk-down is implicit: when M=lo_sat-1 returns SAT, lo_sat moves
    down; the next call to this function picks the new (lower) lo_sat-1.
    """
    if row["status"] in ("proven", "aig_unproven"):
        return None
    if row["lo_sat"] is None:
        return None
    hi = row["hi_unsat"] if row["hi_unsat"] is not None else -1
    lo = row["lo_sat"]
    if hi + 1 >= lo:
        return None  # already proven, caught above by status check
    M = lo - 1
    settled = resolved_M_values(row["attempts"])
    if M in settled:
        # Should not happen: a settled M either tightens lo_sat (sat)
        # or fixes hi_unsat (unsat) and closes the gap → status=proven.
        return None
    timeouts = tried_with_min_budget(row["attempts"])
    if M in timeouts and timeouts[M] >= new_budget:
        return None  # already tried with ≥ new_budget, retrying is pointless
    return M


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="input state TSV")
    ap.add_argument("--output", default=None,
                    help="output state TSV (auto-versioned if omitted)")
    ap.add_argument("--wall-timeout", type=int, required=True,
                    help="per-probe wall ceiling (s)")
    ap.add_argument("--max-nodes", type=int, default=16,
                    help="upper M cap for AIG unbounded probes (ignored for AO)")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--only", default=None,
                    help="comma-separated tt(s) to probe (default: all eligible). "
                         "Multi-output TTs would be ambiguous if split on ','; for "
                         "those use --only-file instead.")
    ap.add_argument("--only-file", default=None,
                    help="path with one tt per line (whole-line match; safe for "
                         "multi-output comma-joined TTs)")
    ap.add_argument("--only-sat-rows", action="store_true",
                    help="restrict to rows whose attempts include at least one SAT "
                         "outcome — refines confirmed wins without re-probing "
                         "timeout-only rows when bumping the wall budget")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the planned probe set and a histogram, write "
                         "nothing, launch nothing")
    args = ap.parse_args()

    rows = read_state(args.input)
    out_path = args.output or next_version_path(args.input)
    if out_path == args.input:
        sys.exit("refusing to overwrite the input state file")

    only = set(args.only.split(",")) if args.only else None
    if args.only_file:
        with open(args.only_file) as fh:
            file_tts = {ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")}
        only = (only or set()) | file_tts

    # Build the probe list: (row_index, M)
    probes = []
    skipped_filter = 0
    skipped_sat_filter = 0
    skipped_eligible = 0
    for i, row in enumerate(rows):
        if only is not None and row["tt"] not in only:
            skipped_filter += 1
            continue
        if args.only_sat_rows and not any(
                a.get("outcome") == "sat" for a in row["attempts"]):
            skipped_sat_filter += 1
            continue
        if row["engine"] == "andexact":
            M = pick_next_M_aig(row, args.max_nodes, args.wall_timeout)
        elif row["engine"] == "aoexact":
            M = pick_next_M_ao(row, args.wall_timeout)
        else:
            continue
        if M is not None:
            probes.append((i, M))
        else:
            skipped_eligible += 1

    print(f"Resume {args.input} → {out_path}")
    print(f"  rows total:     {len(rows)}")
    print(f"  to probe:       {len(probes)}")
    print(f"  wall/probe:     {args.wall_timeout}s   workers: {args.workers}")
    if args.only_sat_rows:
        print(f"  --only-sat-rows skipped: {skipped_sat_filter}")
    if only is not None:
        print(f"  --only/--only-file skipped: {skipped_filter}")
    print(f"  eligible-but-settled at current budget: {skipped_eligible}")

    if args.dry_run:
        from collections import Counter
        m_hist = Counter(M for _, M in probes)
        eng_hist = Counter(rows[i]["engine"] for i, _ in probes)
        print("\n--- DRY RUN: no probes will launch, no files will be written ---")
        print(f"engine breakdown:  {dict(eng_hist)}")
        print("probe M histogram (M: count, top 20):")
        for M, c in sorted(m_hist.items())[:20]:
            print(f"  M={M:3d}  count={c}")
        if len(m_hist) > 20:
            print(f"  ... ({len(m_hist) - 20} more M values)")
        # Sample probes for spot-checking.
        print("\nfirst 10 probes (tt, engine, M, lo_sat, hi_unsat, status, attempts_at_M):")
        for i, M in probes[:10]:
            r = rows[i]
            prior = [a for a in r["attempts"] if a["M"] == M]
            print(f"  tt={r['tt']:20s}  {r['engine']:8s}  M={M:3d}  "
                  f"lo={r['lo_sat']} hi={r['hi_unsat']} st={r['status']:12s}  "
                  f"prior@M={prior}")
        return

    if not probes:
        print("Nothing to do — every eligible row is settled at current budget.")
        write_state(out_path, rows)
        print(f"Wrote {out_path} (unchanged content, just bumped filename).")
        return

    t0 = time.time()

    # Seed the output file with the input contents so any kill during the
    # loop still leaves a complete, well-formed state file on disk.
    _atomic_write_state(out_path, rows)

    def task(i, M):
        row = rows[i]
        r = run_fixed_M(row["engine"], row["n_in"], row["n_out"],
                        row["tt"], M, args.wall_timeout)
        return i, M, r

    settled_sat = settled_unsat = timed_out = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(task, i, M) for i, M in probes]
        done = 0
        for fut in cf.as_completed(futs):
            i, M, r = fut.result()
            outcome = r["outcome"]
            if outcome.startswith("unknown") or outcome in ("parse_fail",
                                                            "tt_mismatch",
                                                            "verify_mismatch"):
                # Record as a probe attempt anyway with a marker outcome so
                # operators can spot it; but don't treat it as sat/unsat.
                # We choose to map these to "timeout" semantics for
                # bookkeeping (they didn't resolve the question) but tag
                # the wall_s and keep the outcome literal.
                rows[i]["attempts"].append({
                    "M": M, "budget_s": float(args.wall_timeout),
                    "outcome": outcome, "wall_s": float(r["wall_s"]),
                })
                timed_out += 1
            else:
                update_row_with_attempt(
                    rows[i], M, args.wall_timeout, outcome,
                    r["wall_s"], chain=r.get("chain") or None,
                )
                if outcome == "sat":
                    settled_sat += 1
                elif outcome == "unsat":
                    settled_unsat += 1
                else:
                    timed_out += 1
            done += 1
            # Checkpoint after every probe so a kill never loses settled work.
            _atomic_write_state(out_path, rows)
            if done % 25 == 0 or done == len(probes):
                el = time.time() - t0
                print(f"  [{done}/{len(probes)}] el={el:.1f}s  "
                      f"sat={settled_sat} unsat={settled_unsat} "
                      f"timeout={timed_out}", flush=True)

    # Recompute statuses for any row we touched (update_row_with_attempt
    # already did this, but for the unknown-outcome branch we skipped it).
    for i, _ in probes:
        rows[i]["status"] = derive_status(rows[i]["hi_unsat"], rows[i]["lo_sat"])

    write_state(out_path, rows)
    print(f"\nWrote {out_path}")
    from collections import Counter
    c = Counter(r["status"] for r in rows)
    print("Final status breakdown:")
    for k in ("proven", "gap", "unbounded", "aig_unproven"):
        if c[k]:
            print(f"  {k:14s} {c[k]}")


if __name__ == "__main__":
    main()
