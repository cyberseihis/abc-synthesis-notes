#!/usr/bin/env python3
"""Audit existing andexact/aoexact iter-mode TSV results.

For each row with reported gate count k, run a fixed-M probe at M = k-1 with
a long timeout. The probe's outcome decides whether the original report was a
proven minimum:

  status=sat     -> reported k is NOT minimum -> verdict='WRONG' (bug)
  status=unsat   -> reported k IS the proven minimum -> verdict='proven'
  status=timeout -> reported k is only an upper bound -> verdict='upper_bound'

Parses ABC's structured output line (EXA9_RESULT:/EXA10_RESULT:) — no free-text
regex. Also surfaces verify=mismatch (would indicate an internal ABC bug) and
sanity-checks that the result line's tt matches the requested truth table.
"""
import argparse, csv, shlex, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

ABC = "/work/abc/abc"

PREFIX = {
    "aig": "EXA9_RESULT:",
    "ao":  "EXA10_RESULT:",
}
CMD_NAME = {"aig": "andexact", "ao": "aoexact"}

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["aig", "ao"], required=True)
    p.add_argument("--n-in",   type=int, required=True)
    p.add_argument("--input",  required=True, help="prior-sweep TSV")
    p.add_argument("--output", required=True, help="audit TSV path")
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--timeout", type=int, default=600,
                   help="per-probe wall budget (s)")
    return p.parse_args()


def parse_kv_line(line):
    """Parse `KEY: a=1 b=foo c=hello world` into a dict.

    Permits values containing spaces only via the last key (we don't need that).
    """
    if ":" not in line:
        return {}
    _, body = line.split(":", 1)
    out = {}
    for tok in shlex.split(body):
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def probe_one(engine, n_in, tt_field, k, wall):
    """Run engine at fixed M=k-1; return dict including verdict."""
    if k <= 0:
        return {"verdict": "trivial", "probe_status": "skipped",
                "probe_M": -1, "probe_wall_s": 0.0, "verify": "n/a"}
    cmd_name = CMD_NAME[engine]
    target_m = k - 1
    cmd = f"{cmd_name} -N {n_in} -M {target_m} -T {max(1, wall - 5)} {tt_field}"
    t0 = time.time()
    try:
        r = subprocess.run([ABC, "-c", cmd], capture_output=True, text=True,
                           timeout=wall + 30)
    except subprocess.TimeoutExpired:
        return {"verdict": "upper_bound", "probe_status": "wall_kill",
                "probe_M": target_m, "probe_wall_s": time.time() - t0,
                "verify": "n/a"}
    out = r.stdout
    dt = time.time() - t0
    prefix = PREFIX[engine]
    # Single canonical result line emitted by ABC. If absent, the run died.
    result_line = next((ln for ln in out.splitlines() if ln.startswith(prefix)),
                       None)
    if result_line is None:
        return {"verdict": "PARSE_FAIL", "probe_status": "no_result_line",
                "probe_M": target_m, "probe_wall_s": dt, "verify": "n/a",
                "raw_tail": out[-300:]}
    kv = parse_kv_line(result_line)
    status = kv.get("status", "missing")
    verify = kv.get("verify", "missing")
    # tt sanity check
    requested_tt = tt_field
    reported_tt = kv.get("tt", "")
    tt_ok = (requested_tt.lower() == reported_tt.lower())
    out_M = int(kv.get("M", target_m))
    if status == "sat":
        verdict = "WRONG"      # k-1 was satisfiable -> reported k is not minimum
    elif status == "unsat":
        verdict = "proven"
    elif status == "timeout":
        verdict = "upper_bound"
    else:
        verdict = f"unknown_status_{status}"
    if verify == "mismatch":
        verdict = "VERIFY_MISMATCH"   # ABC internal verifier flagged the chain
    if not tt_ok:
        verdict = f"TT_MISMATCH_{requested_tt}_vs_{reported_tt}"
    return {"verdict": verdict, "probe_status": status, "probe_M": out_M,
            "probe_wall_s": dt, "verify": verify}


def main():
    args = parse_args()
    rows = list(csv.DictReader(open(args.input), delimiter="\t"))
    work = []
    for r in rows:
        st = r.get("status", "")
        # 'sat' and 'ok' are confident SAT-resolved; 'ub' is also a SAT result
        # (the chain is realized at the listed M) but the optimum was unproven —
        # M-1 probe is exactly the right way to either downgrade 'ub' to 'proven'
        # (UNSAT at M-1) or confirm it's still bounded above (timeout at M-1).
        if st not in ("sat", "ok", "ub"):
            continue
        try:
            k = int(r["gates"])
        except (KeyError, ValueError):
            continue
        if "tt1" in r and r["tt1"]:
            tt_field = f"{r['tt0']},{r['tt1']}"
        else:
            tt_field = r["tt0"]
        work.append((tt_field, k))

    print(f"Auditing {len(work)} rows from {args.input}", file=sys.stderr)
    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(probe_one, args.engine, args.n_in, tt, k, args.timeout): (tt, k)
            for tt, k in work
        }
        done = 0
        for fut in as_completed(futs):
            tt, k = futs[fut]
            try:
                results[(tt, k)] = fut.result()
            except Exception as e:
                results[(tt, k)] = {"verdict": f"exception_{type(e).__name__}",
                                    "probe_status": str(e)[:120],
                                    "probe_M": k - 1, "probe_wall_s": 0.0,
                                    "verify": "n/a"}
            done += 1
            if done % 25 == 0 or done == len(work):
                print(f"  {done}/{len(work)}", file=sys.stderr)

    with open(args.output, "w") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["tt", "reported_k", "probe_M", "probe_status",
                    "probe_wall_s", "verify", "verdict"])
        for tt, k in work:
            d = results[(tt, k)]
            w.writerow([tt, k, d["probe_M"], d["probe_status"],
                        f"{d['probe_wall_s']:.1f}", d["verify"], d["verdict"]])
    print(f"Wrote {args.output}", file=sys.stderr)

if __name__ == "__main__":
    main()
