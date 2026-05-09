#!/usr/bin/env python3
"""Dual-rail AND/OR exact-synthesis benchmark harness.

Runs ABC's `aoexact -O` on a set of canonical small multi-output functions and
verifies the dumped BLIF by re-simulating it. The BLIF declares N logical
inputs and 2*M outputs (F0, F0N, F1, F1N, ...) where F<k> = f_k(x) and
F<k>N = ~f_k(x). Internal cells are 2-input AND or OR (no inversions);
per-PI inverter cells materialize the negative input rail.
"""

import argparse
import os
import re
import subprocess
import sys

# Reuse the bench definitions from the andexact harness so the two stay in sync.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiout_benchmarks import (
    ALL_BENCHES,
    tt_hex,
)

ABC_BIN = "/work/abc/abc"
WORK_DIR = "/tmp/aoexact_bench"


def run_abc(cmd, cwd=WORK_DIR, timeout=600):
    p = subprocess.run([ABC_BIN, "-q", cmd], cwd=cwd, capture_output=True,
                       text=True, timeout=timeout)
    return p.stdout + p.stderr


GATES_RE = re.compile(r"using\s+(\d+)\s+two-input AND/OR gates")
NOSOL_RE = re.compile(r"The problem has no solution\.")


def synthesize_at(b, m, runtime_lim):
    tts = ",".join(tt_hex(b.n_in, f) for f in b.out_funcs)
    cmd = f"aoexact -N {b.n_in} -O {b.n_out} -M {m} -T {runtime_lim} -d {tts}"
    out = run_abc(cmd, timeout=runtime_lim + 30)
    pStr = tts if len(tts) <= 16 else tts[:16] + "_"
    blif_path = os.path.join(WORK_DIR, pStr + "_ao.blif")
    if "timed out" in out:
        return "timeout", None, blif_path
    if NOSOL_RE.search(out):
        return "unsat", None, blif_path
    n = None
    for ln in out.splitlines():
        mm = GATES_RE.search(ln)
        if mm:
            n = int(mm.group(1))
    if n is None:
        return "timeout", None, blif_path
    return "sat", n, blif_path


def find_min(b, lo, hi, runtime_lim):
    sweep = []
    best_n, best_blif = None, None
    m = lo
    while m <= hi:
        status, n, blif = synthesize_at(b, m, runtime_lim)
        sweep.append((m, status))
        if status == "sat":
            best_n, best_blif = n, blif
            break
        if status == "timeout":
            return None, None, sweep
        m += 1
    if best_n is None:
        return None, None, sweep
    m = best_n - 1
    while m >= 0:
        status, n, blif = synthesize_at(b, m, runtime_lim)
        sweep.append((m, status))
        if status == "sat":
            best_n, best_blif = n, blif
            m -= 1
            continue
        break
    return best_n, best_blif, sweep


def parse_blif(path):
    inputs, outputs = [], []
    gates = []  # ordered list of (name, [(fanin, polarity)...], onset_value)
    with open(path) as fh:
        pending = None
        cubes = []
        def finalize():
            nonlocal pending, cubes
            if pending is None:
                return
            name, fanins = pending
            gates.append((name, fanins, list(cubes)))
            pending = None
            cubes = []
        for raw in fh:
            ln = raw.strip()
            if not ln or ln.startswith("#") or ln.startswith(".model"):
                continue
            if ln.startswith(".end"):
                finalize()
                continue
            if ln.startswith(".inputs"):
                inputs = ln.split()[1:]
                continue
            if ln.startswith(".outputs"):
                outputs = ln.split()[1:]
                continue
            if ln.startswith(".names"):
                finalize()
                tokens = ln.split()[1:]
                pending = (tokens[-1], tokens[:-1])
                cubes = []
                continue
            parts = ln.split()
            if pending is None:
                continue
            if len(parts) == 2:
                cubes.append((parts[0], int(parts[1])))
            elif len(parts) == 1:
                # constant 1
                cubes.append(("", int(parts[0])))
        finalize()
    return inputs, outputs, gates


def simulate_blif(b, path):
    inputs, outputs, gates = parse_blif(path)
    in_idx = {n: i for i, n in enumerate(inputs)}
    n_mints = 1 << b.n_in
    bits_per_out = {oname: [0] * n_mints for oname in outputs}
    for m in range(n_mints):
        env = {}
        for name, i in in_idx.items():
            env[name] = (m >> i) & 1
        for name, fanins, cubes in gates:
            on_set = 0
            for cube_pat, val in cubes:
                ok = True
                for fi, ch in zip(fanins, cube_pat):
                    fv = env.get(fi, 0)
                    if ch == "1" and fv != 1:
                        ok = False; break
                    if ch == "0" and fv != 0:
                        ok = False; break
                if ok:
                    on_set = val
                    break
            else:
                # no cube matched; output is 1 - on_set polarity (i.e., 0 for 1-on-set, 1 for 0-on-set)
                # In BLIF, missing match means default = the complement of the cube polarity.
                # Standard: if all cubes have on_value 1, default = 0; if all have 0, default = 1.
                if cubes:
                    on_set = 1 - cubes[0][1]
                else:
                    on_set = 0
            env[name] = on_set
        for oname in outputs:
            bits_per_out[oname][m] = env.get(oname, 0)
    return bits_per_out


def bits_to_hex(b, bits):
    n_mints = 1 << b.n_in
    if b.n_in <= 1:
        v = 0
        for m in range(n_mints):
            v |= bits[m] << m
        return f"{v:x}"
    n_digits = n_mints // 4
    digits = []
    for k in range(n_digits):
        v = 0
        for bb in range(4):
            v |= bits[4 * k + bb] << bb
        digits.append(f"{v:x}")
    digits.reverse()
    return "".join(digits)


def verify_blif(b, blif_path):
    """Return (ok, observed_pos, observed_neg, expected_pos)."""
    if not os.path.exists(blif_path):
        return False, None, None, None
    obs = simulate_blif(b, blif_path)
    # Outputs are F0, F0N, F1, F1N, ...; or for nOut=1, F, FN.
    if b.n_out == 1:
        names_pos = ["F"]
        names_neg = ["FN"]
    else:
        names_pos = [f"F{k}" for k in range(b.n_out)]
        names_neg = [f"F{k}N" for k in range(b.n_out)]
    expected_pos = [tt_hex(b.n_in, f).lower() for f in b.out_funcs]
    n_mints = 1 << b.n_in
    expected_neg = ["".join(reversed([
        f"{(~v & 0xf):x}" for v in [
            int(expected_pos[k][len(expected_pos[k]) - 1 - q], 16)
            for q in range(len(expected_pos[k]))
        ]
    ])) for k in range(b.n_out)]
    # Easier: rebuild ~TT directly.
    expected_neg = []
    for k in range(b.n_out):
        bits = [1 - ((tt_hex_int(b, k) >> m) & 1) for m in range(n_mints)]
        expected_neg.append(bits_to_hex(b, bits))
    obs_pos = [bits_to_hex(b, obs.get(nm, [0] * n_mints)) for nm in names_pos]
    obs_neg = [bits_to_hex(b, obs.get(nm, [0] * n_mints)) for nm in names_neg]
    ok = (obs_pos == expected_pos) and (obs_neg == expected_neg)
    return ok, obs_pos, obs_neg, (expected_pos, expected_neg)


def tt_hex_int(b, k):
    n_mints = 1 << b.n_in
    v = 0
    for m in range(n_mints):
        inputs = [(m >> i) & 1 for i in range(b.n_in)]
        v |= (b.out_funcs[k](inputs) & 1) << m
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*")
    ap.add_argument("-T", "--timeout", type=int, default=120)
    args = ap.parse_args()

    os.makedirs(WORK_DIR, exist_ok=True)
    benches = [b for b in ALL_BENCHES if not args.names or b.name in args.names]

    print(f"{'name':<12} {'n_in':>4} {'n_out':>5} {'gates':>5} {'verify':>6}  sweep")
    print("-" * 100)
    for b in benches:
        # Sensible bounds for dual-rail: floor at 0, ceiling at 4*max_hint or 24.
        lo = max(0, (b.min_hint or 1) - 1)
        hi = max(b.max_hint or 16, b.n_out * 2 + 4)
        # Boost ceiling for dual-rail (likely doubles for nontrivial cases).
        hi = max(hi, 2 * (b.max_hint or 16))
        n_gates, blif, sweep = find_min(b, lo, hi, args.timeout)
        sweep_str = " ".join(f"{m}:{s[:3]}" for m, s in sweep)
        if n_gates is None:
            print(f"{b.name:<12} {b.n_in:>4} {b.n_out:>5} {'?':>5} {'-':>6}  {sweep_str}")
            continue
        ok, op, on_, _exp = verify_blif(b, blif)
        verify_col = "OK" if ok else "FAIL"
        print(f"{b.name:<12} {b.n_in:>4} {b.n_out:>5} {n_gates:>5} {verify_col:>6}  {sweep_str}")
        if not ok:
            print(f"  observed pos={op}")
            print(f"  observed neg={on_}")


if __name__ == "__main__":
    main()
