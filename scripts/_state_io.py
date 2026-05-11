"""Shared state-file I/O for the bound-tracking sweep system.

State schema (one row per class), TSV with columns:

    tt        comma-joined hex truth table(s)   (e.g. "8e" or "8e,1f")
    engine    andexact | aoexact
    n_in      number of input variables
    n_out     number of outputs
    hi_unsat  highest M proven UNSAT          (int; empty = none)
    lo_sat    lowest M proven SAT             (int; empty = unbounded)
    status    proven | gap | unbounded | aig_unproven
    chain     BLIF-ish chain at lo_sat        (string; "" if no SAT yet)
    attempts  JSON list of {M, budget_s, outcome, wall_s}

Semantics:
    proven        hi_unsat + 1 == lo_sat   (true min = lo_sat)
    gap           lo_sat known but hi_unsat+1 < lo_sat (or hi_unsat empty)
    unbounded     no SAT yet (lo_sat empty)
    aig_unproven  AO-side block: paired AIG has no proven minimum, so we
                  refuse to probe (rule 1: no point running AO without K)

`attempts` is the authoritative trace; hi_unsat/lo_sat/status are derived
from it but stored explicitly for convenience.
"""
import csv
import json
import re

COLS = ["tt", "engine", "n_in", "n_out",
        "hi_unsat", "lo_sat", "status", "chain", "attempts"]


def _ival(s):
    return int(s) if s != "" and s is not None else None


def _sval(v):
    return "" if v is None else str(v)


def read_state(path):
    """Returns list of dicts with parsed fields."""
    rows = []
    with open(path) as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            attempts = json.loads(row["attempts"]) if row.get("attempts") else []
            rows.append({
                "tt":       row["tt"],
                "engine":   row["engine"],
                "n_in":     int(row["n_in"]),
                "n_out":    int(row["n_out"]),
                "hi_unsat": _ival(row["hi_unsat"]),
                "lo_sat":   _ival(row["lo_sat"]),
                "status":   row["status"],
                "chain":    row.get("chain", ""),
                "attempts": attempts,
            })
    return rows


def write_state(path, rows):
    with open(path, "w") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(COLS)
        for r in rows:
            w.writerow([
                r["tt"], r["engine"], r["n_in"], r["n_out"],
                _sval(r["hi_unsat"]), _sval(r["lo_sat"]),
                r["status"], r["chain"], json.dumps(r["attempts"], separators=(",", ":")),
            ])


def derive_bounds(attempts):
    """Compute (hi_unsat, lo_sat) from attempts list. Returns (int|None, int|None)."""
    sat_ms = [int(a["M"]) for a in attempts if a["outcome"] == "sat"]
    unsat_ms = [int(a["M"]) for a in attempts if a["outcome"] == "unsat"]
    hi = max(unsat_ms) if unsat_ms else None
    lo = min(sat_ms) if sat_ms else None
    return hi, lo


def derive_status(hi_unsat, lo_sat):
    if lo_sat is None:
        return "unbounded"
    if hi_unsat is None:
        # We have SAT but no UNSAT proof yet. Status `gap` unless lo_sat == 0
        # (then trivially proven, no M=-1 to prove UNSAT).
        return "proven" if lo_sat == 0 else "gap"
    if hi_unsat + 1 == lo_sat:
        return "proven"
    return "gap"


def update_row_with_attempt(row, M, budget_s, outcome, wall_s, chain=None):
    """Append an attempt and recompute hi_unsat/lo_sat/status.

    If outcome is `sat` and M tightens lo_sat, replace `chain` with the new
    one. Never widens bounds (a stale row should not invalidate a later
    tighter bound).
    """
    row["attempts"].append({"M": int(M), "budget_s": float(budget_s),
                            "outcome": outcome, "wall_s": float(wall_s)})
    if outcome == "sat":
        if row["lo_sat"] is None or int(M) < row["lo_sat"]:
            row["lo_sat"] = int(M)
            if chain is not None:
                row["chain"] = chain
    elif outcome == "unsat":
        if row["hi_unsat"] is None or int(M) > row["hi_unsat"]:
            row["hi_unsat"] = int(M)
    row["status"] = derive_status(row["hi_unsat"], row["lo_sat"])
    return row


def make_row(tt, engine, n_in, n_out, *,
             hi_unsat=None, lo_sat=None, chain="", attempts=None):
    if attempts is None:
        attempts = []
    return {
        "tt": tt, "engine": engine, "n_in": n_in, "n_out": n_out,
        "hi_unsat": hi_unsat, "lo_sat": lo_sat,
        "status": derive_status(hi_unsat, lo_sat),
        "chain": chain,
        "attempts": list(attempts),
    }


def next_version_path(path):
    """`foo.tsv` → `foo_v1.tsv`; `foo_v3.tsv` → `foo_v4.tsv`."""
    m = re.search(r"_v(\d+)(\.tsv)$", path)
    if m:
        n = int(m.group(1)) + 1
        return path[:m.start()] + f"_v{n}" + m.group(2)
    if path.endswith(".tsv"):
        return path[:-4] + "_v1.tsv"
    return path + "_v1"


def tried_M_values(attempts):
    """Set of M values already probed (any outcome)."""
    return {int(a["M"]) for a in attempts}


def tried_with_min_budget(attempts):
    """Map M → smallest budget already used (so we know if a retry is worth it)."""
    out = {}
    for a in attempts:
        M = int(a["M"])
        b = float(a["budget_s"])
        if a["outcome"] == "timeout":
            # Only timeouts are worth retrying; for sat/unsat the answer is settled.
            out[M] = min(out.get(M, float("inf")), b)
    return out


def timeout_Ms(attempts):
    """List of M values that ended in timeout (may include duplicates from
    multiple budget attempts)."""
    return [int(a["M"]) for a in attempts if a["outcome"] == "timeout"]


def resolved_M_values(attempts):
    """M values with a settled (sat/unsat) outcome."""
    return {int(a["M"]) for a in attempts if a["outcome"] in ("sat", "unsat")}
