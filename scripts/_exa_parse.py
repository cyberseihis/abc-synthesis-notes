"""Shared parser for ABC's structured exact-synthesis output.

Patched ABC (commit 8472861, andexact-relax-floor branch) emits one structured
line per call and one summary line per iter-mode invocation:

    EXA9_RESULT: status=sat|unsat|timeout M=<int> nVars=<int> nOuts=<int>
                 verify=ok|mismatch|n/a runtime_s=<float> tt=<comma-csv>
    EXA9_ITER_RESULT: status=proven|upper_bound|no_sat_inconclusive|
                              no_sat_proven_unsat
                      sat_M=<int> proven_lb=<int> first_timeout_M=<int>
                      M_range=[<lo>,<hi>]

(Same for EXA10_RESULT / EXA10_ITER_RESULT from aoexact.)

Iter mode walks M upward inside the wall. status=proven means every smaller
M returned UNSAT and an SAT was found at sat_M -- proven minimum. status=
upper_bound means at least one smaller M timed out, so the chain at sat_M
is a valid upper bound but the true optimum could be lower.
"""
import shlex


PREFIXES = {
    "andexact": ("EXA9_RESULT:",  "EXA9_ITER_RESULT:"),
    "aig":      ("EXA9_RESULT:",  "EXA9_ITER_RESULT:"),
    "aoexact":  ("EXA10_RESULT:", "EXA10_ITER_RESULT:"),
    "ao":       ("EXA10_RESULT:", "EXA10_ITER_RESULT:"),
}


def _parse_kv(line, prefix):
    if not line.startswith(prefix):
        return None
    body = line[len(prefix):].lstrip()
    out = {}
    for tok in shlex.split(body):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def parse_run_output(out, engine):
    """Walk lines once and collect every structured result."""
    result_pfx, iter_pfx = PREFIXES[engine]
    results, iter_result = [], None
    for ln in out.splitlines():
        kv = _parse_kv(ln, result_pfx)
        if kv is not None:
            results.append(kv)
            continue
        kv = _parse_kv(ln, iter_pfx)
        if kv is not None:
            iter_result = kv
    sat = next((r for r in results if r.get("status") == "sat"), None)
    return {"results": results, "iter_result": iter_result, "sat_result": sat}


def classify_iter(parsed, wall_killed, expected_tt=None):
    """Return (status, gates_or_None, verify) for an iter-mode call.

    Status alphabet:
      sat            -- proven minimum (iter walked through UNSAT to SAT)
      ub             -- valid upper bound (iter saw at least one timeout
                        below the SAT M, so the optimum could be lower)
      unsat          -- no realization in [0, M_max] (rare for sane M_max)
      timeout        -- wall-killed or iter ran out of budget without SAT
      tt_mismatch    -- ABC reported a tt different from what we asked for
      verify_mismatch-- ABC's internal verifier flagged the chain
      iter_status_X  -- iter result reported a status we don't recognize
      unknown        -- no iter_result line and no SAT result (ABC died)
    """
    sat = parsed["sat_result"]
    iter_r = parsed["iter_result"]
    gates = int(sat["M"]) if sat else None
    verify = sat.get("verify", "n/a") if sat else "n/a"

    # Sanity: did ABC report the truth table we asked for?
    if sat is not None and expected_tt is not None:
        if sat.get("tt", "").lower() != expected_tt.lower():
            return "tt_mismatch", gates, verify

    # Sanity: ABC's internal verifier on the printed chain
    if sat is not None and verify == "mismatch":
        return "verify_mismatch", gates, verify

    # If the wall killed us, the iter loop was interrupted.
    if wall_killed:
        # We may still have a SAT chain from before the kill -- it's a
        # valid upper bound (we just don't know what was below it).
        return ("ub", gates, verify) if sat is not None else ("timeout", None, "n/a")

    # Clean exit: trust the EXA*_ITER_RESULT line.
    if iter_r is None:
        # Should never happen in iter mode -- means ABC died after the SAT
        # call but before printing the iter summary. Treat as ub if we have
        # a SAT chain (the chain is real), otherwise unknown.
        return ("ub", gates, verify) if sat is not None else ("unknown", None, "n/a")

    s = iter_r.get("status", "")
    if s == "proven":
        return "sat", gates, verify
    if s == "upper_bound":
        return "ub", gates, verify
    if s == "no_sat_proven_unsat":
        return "unsat", None, "n/a"
    if s == "no_sat_inconclusive":
        return "timeout", None, "n/a"
    return f"iter_status_{s}", gates, verify
