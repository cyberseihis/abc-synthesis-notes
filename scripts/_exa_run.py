"""Shared single-call runner for andexact / aoexact.

Wraps a fixed-M call (no iter walk) and returns a standardized result dict.
Used by state_init.py and state_resume.py for individual probes.

Iter-mode helper also provided for state_init's AIG bootstrap (cheap walk
from 0 within a wall budget).
"""
import re
import subprocess
import time

from _exa_parse import parse_run_output, classify_iter

ABC = "/work/abc/abc"

GATES_RE_AIG = re.compile(r"using\s+(\d+)\s+two-input and-nodes")
GATES_RE_AO  = re.compile(r"using\s+(\d+)\s+two-input AND/OR gates")


def _capture_chain(out_text, engine):
    """Grab the last realization block (BLIF-ish lines after the gate-count
    header line that the engine prints before each SAT chain)."""
    gates_re = GATES_RE_AO if engine == "aoexact" else GATES_RE_AIG
    blocks, cur, capture = [], [], False
    for ln in out_text.splitlines():
        if gates_re.search(ln):
            blocks.append(cur)
            cur, capture = [], True
            continue
        if capture:
            if (ln.startswith("Finished") or ln.startswith("Total runtime") or
                ln.startswith("Running")  or ln.startswith("EXA9_") or
                ln.startswith("EXA10_")   or ln.startswith("Iter result:") or
                ln.strip() == ""):
                continue
            s = ln.strip()
            if s:
                cur.append(s)
    if cur:
        blocks.append(cur)
    return " ; ".join(blocks[-1]) if blocks else ""


def run_fixed_M(engine, n_in, n_out, tt, M, wall_timeout):
    """Single-M probe. tt is the comma-joined TT string.

    Returns dict: {outcome, M, wall_s, verify, chain}
      outcome ∈ {"sat", "unsat", "timeout", "parse_fail", "tt_mismatch",
                 "verify_mismatch"}
    """
    cmd = [ABC, "-q",
           f"{engine} -N {n_in} -O {n_out} -M {M} "
           f"-T {max(1, wall_timeout - 5)} -s {tt}"]
    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=wall_timeout)
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        def _s(v):
            if v is None: return ""
            if isinstance(v, bytes): return v.decode("utf-8", "replace")
            return v
        out = _s(e.stdout) + _s(e.stderr)
        timed_out = True
    wall = time.time() - t0

    parsed = parse_run_output(out, engine)
    results = parsed["results"]

    # Find the result for our M (there should be exactly one in fixed-M mode).
    me = next((r for r in results if r.get("M") == str(M)), None)
    if timed_out and me is None:
        return {"outcome": "timeout", "M": M, "wall_s": wall,
                "verify": "n/a", "chain": ""}
    if me is None:
        return {"outcome": "parse_fail", "M": M, "wall_s": wall,
                "verify": "n/a", "chain": out[:300].replace("\n", " ⏎ ")}

    status = me.get("status", "unknown")
    verify = me.get("verify", "n/a")
    if status == "sat":
        if me.get("tt", "").lower() != tt.lower():
            return {"outcome": "tt_mismatch", "M": M, "wall_s": wall,
                    "verify": verify, "chain": ""}
        if verify == "mismatch":
            return {"outcome": "verify_mismatch", "M": M, "wall_s": wall,
                    "verify": verify, "chain": _capture_chain(out, engine)}
        return {"outcome": "sat", "M": M, "wall_s": wall,
                "verify": verify, "chain": _capture_chain(out, engine)}
    if status == "unsat":
        return {"outcome": "unsat", "M": M, "wall_s": wall,
                "verify": "n/a", "chain": ""}
    if status == "timeout":
        return {"outcome": "timeout", "M": M, "wall_s": wall,
                "verify": "n/a", "chain": ""}
    return {"outcome": f"unknown:{status}", "M": M, "wall_s": wall,
            "verify": verify, "chain": ""}


def run_iter(engine, n_in, n_out, tt, max_M, per_m_timeout, wall_timeout):
    """Iter-mode walk M=0..max_M. Returns dict with per-M results and the
    overall iter verdict.

      {attempts: [{M, budget_s, outcome, wall_s}, ...],
       lo_sat: int|None, hi_unsat: int|None,
       chain: str (at lo_sat), iter_verdict: proven|upper_bound|...}

    Per-M outcomes come from EXA9_RESULT / EXA10_RESULT lines. The iter
    verdict comes from EXA9_ITER_RESULT / EXA10_ITER_RESULT (proven means
    every smaller M was UNSAT and the SAT is the true min).

    `budget_s` recorded for each attempt is the per-M timeout the iter call
    was configured with — that's the per-M wall ceiling for the individual
    SAT call, not the cumulative iter wall.
    """
    cmd = [ABC, "-q",
           f"{engine} -N {n_in} -O {n_out} -m -M {max_M} "
           f"-T {per_m_timeout} -s {tt}"]
    t0 = time.time()
    timed_out = False
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=wall_timeout)
        out = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        def _s(v):
            if v is None: return ""
            if isinstance(v, bytes): return v.decode("utf-8", "replace")
            return v
        out = _s(e.stdout) + _s(e.stderr)
        timed_out = True
    wall = time.time() - t0

    parsed = parse_run_output(out, engine)
    results = parsed["results"]

    attempts = []
    for r in results:
        try:
            M = int(r["M"])
        except (KeyError, ValueError):
            continue
        s = r.get("status", "unknown")
        runtime = float(r.get("runtime_s", "0") or "0")
        outcome = s if s in ("sat", "unsat", "timeout") else f"unknown:{s}"
        attempts.append({"M": M, "budget_s": float(per_m_timeout),
                         "outcome": outcome, "wall_s": runtime})

    lo_sat = min((a["M"] for a in attempts if a["outcome"] == "sat"),
                 default=None)
    hi_unsat = max((a["M"] for a in attempts if a["outcome"] == "unsat"),
                   default=None)
    chain = _capture_chain(out, engine) if lo_sat is not None else ""

    iter_verdict = None
    if parsed["iter_result"]:
        iter_verdict = parsed["iter_result"].get("status")
    elif timed_out:
        iter_verdict = "wall_killed"
    return {"attempts": attempts, "lo_sat": lo_sat, "hi_unsat": hi_unsat,
            "chain": chain, "iter_verdict": iter_verdict,
            "iter_wall_s": wall, "wall_killed": timed_out}
