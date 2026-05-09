#!/usr/bin/env python3
"""Multi-output exact-synthesis benchmark harness.

Generates truth tables for a list of canonical small multi-output Boolean
functions and runs ABC's `andexact -O` to find a minimum-gate AIG. Verifies
each synthesized BLIF by reading it back and printing per-output truth tables.

Convention: variables are a, b, c, ... (LSB to MSB). For nVars inputs there
are 2^nVars minterms; minterm m has bit i = (m >> i) & 1, which is the value
of variable i (0-indexed), matching ABC's `andexact` parsing.
"""

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List


@dataclass
class Bench:
    name: str
    n_in: int
    out_names: List[str]
    out_funcs: List[Callable[[List[int]], int]]  # one per output
    # If set, search for the minimum starting at this node count; otherwise
    # use the script default. Tight bounds avoid wasteful UNSAT proofs.
    min_hint: int = 0
    max_hint: int = 0

    @property
    def n_out(self) -> int:
        return len(self.out_funcs)


def tt_hex(n_in: int, fn: Callable[[List[int]], int]) -> str:
    """Compute the truth table for `fn` over `n_in` inputs and return the hex
    string in ABC's format: most-significant hex digit first, last digit holds
    minterms 0..3 (bit 0 = minterm 0, etc.)."""
    n_mints = 1 << n_in
    n_digits = max(1, n_mints // 4)
    digits = []
    if n_in <= 1:
        # 1 hex digit covers up to 4 minterms; pad upper bits to 0
        bits = 0
        for m in range(n_mints):
            inputs = [(m >> i) & 1 for i in range(n_in)]
            v = fn(inputs) & 1
            bits |= (v & 1) << m
        digits.append(f"{bits:x}")
    else:
        for k in range(n_digits):
            v = 0
            for b in range(4):
                m = 4 * k + b
                inputs = [(m >> i) & 1 for i in range(n_in)]
                v |= (fn(inputs) & 1) << b
            digits.append(f"{v:x}")
        digits.reverse()
    return "".join(digits)


# ----------------------------- Benchmarks --------------------------------


def half_adder() -> Bench:
    return Bench(
        "half_adder", 2, ["carry", "sum"],
        [lambda x: x[0] & x[1], lambda x: x[0] ^ x[1]],
        min_hint=3, max_hint=3,
    )


def full_adder() -> Bench:
    return Bench(
        "full_adder", 3, ["carry", "sum"],
        [lambda x: int((x[0] + x[1] + x[2]) >= 2),
         lambda x: x[0] ^ x[1] ^ x[2]],
        min_hint=7, max_hint=7,
    )


def popcnt3() -> Bench:
    # Same I/O as full adder.
    return Bench(
        "popcnt3", 3, ["count1", "count0"],
        [lambda x: int((x[0] + x[1] + x[2]) >= 2),
         lambda x: x[0] ^ x[1] ^ x[2]],
        min_hint=7, max_hint=7,
    )


def popcnt4() -> Bench:
    return Bench(
        "popcnt4", 4, ["c2", "c1", "c0"],
        [lambda x: ((x[0] + x[1] + x[2] + x[3]) >> 2) & 1,
         lambda x: ((x[0] + x[1] + x[2] + x[3]) >> 1) & 1,
         lambda x: ((x[0] + x[1] + x[2] + x[3]) >> 0) & 1],
        min_hint=11, max_hint=16,
    )


def dec_2_to_4() -> Bench:
    return Bench(
        "dec_2_to_4", 2, ["m0", "m1", "m2", "m3"],
        [lambda x: int(x[0] == 0 and x[1] == 0),
         lambda x: int(x[0] == 1 and x[1] == 0),
         lambda x: int(x[0] == 0 and x[1] == 1),
         lambda x: int(x[0] == 1 and x[1] == 1)],
        min_hint=4, max_hint=4,
    )


def add_2bit() -> Bench:
    def s_bit(bit):
        return lambda x: ((2 * x[0] + x[1]) + (2 * x[2] + x[3])) >> bit & 1
    return Bench(
        "add_2bit", 4, ["s2", "s1", "s0"],
        [s_bit(2), s_bit(1), s_bit(0)],
        min_hint=12, max_hint=16,
    )


def cmp_2bit() -> Bench:
    return Bench(
        "cmp_2bit", 4, ["lt", "eq"],
        [lambda x: int((2 * x[0] + x[1]) < (2 * x[2] + x[3])),
         lambda x: int((2 * x[0] + x[1]) == (2 * x[2] + x[3]))],
        min_hint=8, max_hint=12,
    )


def mul_2x2() -> Bench:
    def p_bit(bit):
        return lambda x: ((2 * x[0] + x[1]) * (2 * x[2] + x[3])) >> bit & 1
    return Bench(
        "mul_2x2", 4, ["p3", "p2", "p1", "p0"],
        [p_bit(3), p_bit(2), p_bit(1), p_bit(0)],
        min_hint=7, max_hint=12,
    )


def inc_3bit() -> Bench:
    def i_bit(bit):
        return lambda x: ((4 * x[0] + 2 * x[1] + x[2]) + 1) >> bit & 1
    return Bench(
        "inc_3bit", 3, ["o3", "o2", "o1", "o0"],
        [i_bit(3), i_bit(2), i_bit(1), i_bit(0)],
        min_hint=6, max_hint=10,
    )


def mux_2to1() -> Bench:
    return Bench(
        "mux_2to1", 3, ["y"],
        [lambda x: x[1] if x[2] == 1 else x[0]],
        min_hint=3, max_hint=3,
    )


ALL_BENCHES = [
    half_adder(),
    full_adder(),
    popcnt3(),
    popcnt4(),
    dec_2_to_4(),
    add_2bit(),
    cmp_2bit(),
    mul_2x2(),
    inc_3bit(),
    mux_2to1(),
]


# ----------------------------- ABC harness --------------------------------


def find_abc() -> str:
    cand = "/work/abc/abc"
    if not os.path.exists(cand):
        sys.exit(f"abc binary not found at {cand}")
    return cand


PERCY_BIN = "/work/AQFP_TEST/mockturtle/build/experiments/multiout_andexact_compare"


def run_percy(b: Bench, timeout_s: int) -> tuple:
    """Run the percy reference. Returns (status, n_gates, time_s)."""
    if not os.path.exists(PERCY_BIN):
        return "missing", None, 0.0
    tts = ",".join(tt_hex(b.n_in, f) for f in b.out_funcs)
    import time
    t0 = time.time()
    try:
        p = subprocess.run(
            [PERCY_BIN, str(b.n_in), str(b.n_out), tts],
            capture_output=True, text=True, timeout=timeout_s,
        )
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return "timeout", None, time.time() - t0
    elapsed = time.time() - t0
    m = re.search(r"RESULT:\s+success\s+gates=(\d+)", out)
    if m:
        return "sat", int(m.group(1)), elapsed
    if "RESULT: timeout" in out:
        return "timeout", None, elapsed
    if "RESULT: failure" in out:
        return "failure", None, elapsed
    return "?", None, elapsed


def run_abc(abc: str, cmd: str, cwd: str = "/tmp", timeout: int = 60) -> tuple:
    try:
        p = subprocess.run([abc, "-q", cmd], cwd=cwd, capture_output=True,
                           text=True, timeout=timeout)
        return p.stdout + p.stderr, False
    except subprocess.TimeoutExpired as e:
        return (e.stdout or "") + (e.stderr or ""), True


GATES_RE = re.compile(r"using\s+(\d+)\s+two-input and-nodes")
NOSOL_RE = re.compile(r"The problem has no solution\.")


def synthesize_at(abc: str, b: Bench, m: int, runtime_lim: int) -> tuple:
    """Synthesize at exactly M = m nodes. Returns (status, n_gates, blif_path, time_s).
    status in {'sat', 'unsat', 'timeout'}."""
    tts = ",".join(tt_hex(b.n_in, f) for f in b.out_funcs)
    blif_dir = "/tmp/multiout_bench"
    os.makedirs(blif_dir, exist_ok=True)
    # Don't pass -s; we need the "no solution" / "timed out" messages parsed.
    cmd = f"andexact -N {b.n_in} -O {b.n_out} -M {m} -T {runtime_lim} -d {tts}"
    import time
    t0 = time.time()
    out, timed_out = run_abc(abc, cmd, cwd=blif_dir, timeout=runtime_lim + 30)
    elapsed = time.time() - t0
    pStr = tts if len(tts) <= 16 else tts[:16] + "_"
    blif_path = os.path.join(blif_dir, pStr + ".blif")
    if timed_out or "timed out" in out:
        return "timeout", None, blif_path, elapsed
    if NOSOL_RE.search(out):
        return "unsat", None, blif_path, elapsed
    n = None
    for ln in out.splitlines():
        mm = GATES_RE.search(ln)
        if mm:
            n = int(mm.group(1))
    if n is None:
        return "timeout", None, blif_path, elapsed  # garbled output
    return "sat", n, blif_path, elapsed


def find_min(abc: str, b: Bench, lo: int, hi: int, runtime_lim: int):
    """Find smallest M in [lo, hi] for which there's a SAT solution.

    Walks upward until first SAT, then walks downward refuting until UNSAT or
    timeout. The smallest SAT M we observe is the reported best. Returns
    (best_M, best_blif, sweep_log).
    """
    sweep = []
    best_n, best_blif = None, None
    # Walk upward from lo until SAT (or timeout).
    m = lo
    while m <= hi:
        status, n, blif, t = synthesize_at(abc, b, m, runtime_lim)
        sweep.append((m, status, t))
        if status == "sat":
            best_n, best_blif = n, blif
            break
        if status == "timeout":
            return None, None, sweep
        m += 1
    if best_n is None:
        return None, None, sweep
    # Walk downward refuting until UNSAT or timeout.
    m = best_n - 1
    while m >= 0:
        status, n, blif, t = synthesize_at(abc, b, m, runtime_lim)
        sweep.append((m, status, t))
        if status == "sat":
            best_n, best_blif = n, blif
            m -= 1
            continue
        # unsat or timeout: stop refuting
        break
    return best_n, best_blif, sweep


def parse_blif(path: str):
    """Parse a small BLIF (only .inputs/.outputs/.names with single-cube
    AND-of-literals or buffer/inverter forms) into (inputs, outputs, gates)
    where gates is a list of (name, [(fanin, polarity), ...], output_value).

    We assume every .names block has exactly one cube and the on-set value 1.
    """
    inputs, outputs = [], []
    gates = {}  # name -> ([(fanin, sign)], out_val)
    pending = None  # (name, fanins[])
    with open(path) as fh:
        for raw in fh:
            ln = raw.strip()
            if not ln or ln.startswith("#") or ln.startswith(".model") or ln.startswith(".end"):
                continue
            if ln.startswith(".inputs"):
                inputs = ln.split()[1:]
                continue
            if ln.startswith(".outputs"):
                outputs = ln.split()[1:]
                continue
            if ln.startswith(".names"):
                # finalize previous if any
                tokens = ln.split()[1:]
                fanins = tokens[:-1]
                name = tokens[-1]
                pending = (name, fanins)
                continue
            # cube line, e.g. "00 1" or "0 1" or "11 1"
            parts = ln.split()
            if pending is None or len(parts) != 2:
                continue
            cube_pattern, on_value = parts
            name, fanins = pending
            # Convert pattern to (fanin, expected_value) pairs.
            literals = [(fi, int(c)) for fi, c in zip(fanins, cube_pattern)]
            gates[name] = (literals, int(on_value))
            pending = None
    return inputs, outputs, gates


def simulate_blif(b: Bench, path: str) -> List[str]:
    inputs, outputs, gates = parse_blif(path)
    # Map each input letter to its variable index in our convention (a=0, b=1, ...).
    in_idx = {n: i for i, n in enumerate(inputs)}
    n_mints = 1 << b.n_in
    # Per-output bit pattern across minterms.
    bits_per_out = [[0] * n_mints for _ in range(b.n_out)]
    for m in range(n_mints):
        env = {}
        for name, i in in_idx.items():
            env[name] = (m >> i) & 1
        # Evaluate gates in topological order (assume the BLIF is already topo:
        # andexact emits internal nodes before their consumers).
        for gname, (lits, on_val) in gates.items():
            match = all(env.get(fi, 0) == polarity for fi, polarity in lits)
            env[gname] = on_val if match else (1 - on_val)
        for k, oname in enumerate(outputs):
            if k >= b.n_out:
                break
            bits_per_out[k][m] = env.get(oname, 0)
    # Convert each output's bit pattern to a hex string in ABC's convention
    # (least-significant hex digit holds minterms 0..3, bit 0 = mint 0).
    obs = []
    for bits in bits_per_out:
        if b.n_in <= 1:
            v = 0
            for m in range(n_mints):
                v |= bits[m] << m
            obs.append(f"{v:x}")
        else:
            n_digits = n_mints // 4
            digits = []
            for k in range(n_digits):
                v = 0
                for bb in range(4):
                    v |= bits[4 * k + bb] << bb
                digits.append(f"{v:x}")
            digits.reverse()
            obs.append("".join(digits))
    return obs


def verify_blif(abc: str, b: Bench, blif_path: str) -> List[str]:
    if not os.path.exists(blif_path):
        return ["?"] * b.n_out
    try:
        return simulate_blif(b, blif_path)
    except Exception as e:
        return [f"ERR:{e}"] * b.n_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", help="Filter by bench name(s)")
    ap.add_argument("-T", "--timeout", type=int, default=60,
                    help="Per-call timeout in seconds (passed to abc -T)")
    ap.add_argument("--no-percy", action="store_true",
                    help="Skip the percy comparison column")
    args = ap.parse_args()

    abc = find_abc()
    benches = [b for b in ALL_BENCHES if not args.names or b.name in args.names]

    hdr = f"{'name':<12} {'n_in':>4} {'n_out':>5} {'abc':>4} {'percy':>5} {'agree':>5} {'verify':>6}  {'TTs':<24} sweep (M:status@time)"
    print(hdr)
    print("-" * 130)
    for b in benches:
        tts = ",".join(tt_hex(b.n_in, f) for f in b.out_funcs)
        lo = b.min_hint or 1
        hi = b.max_hint or 16
        n_gates, blif, sweep = find_min(abc, b, lo, hi, args.timeout)
        sweep_str = " ".join(f"{m}:{s[:3]}@{t:.1f}s" for m, s, t in sweep)
        if n_gates is None:
            abc_col = "?"
            verify_col = "-"
        elif not os.path.exists(blif):
            abc_col = str(n_gates)
            verify_col = "NOBLIF"
        else:
            observed = verify_blif(abc, b, blif)
            expected = [tt_hex(b.n_in, f).lower() for f in b.out_funcs]
            ok = (observed == expected)
            abc_col = str(n_gates)
            verify_col = "OK" if ok else "FAIL"

        if args.no_percy:
            percy_col = "-"
            agree_col = "-"
        else:
            p_status, p_gates, p_time = run_percy(b, args.timeout)
            if p_gates is not None:
                percy_col = str(p_gates)
            else:
                percy_col = p_status[:5]
            if isinstance(n_gates, int) and isinstance(p_gates, int):
                agree_col = "yes" if n_gates == p_gates else f"{n_gates}vs{p_gates}"
            else:
                agree_col = "-"

        print(f"{b.name:<12} {b.n_in:>4} {b.n_out:>5} {abc_col:>4} {percy_col:>5} {agree_col:>5} {verify_col:>6}  {tts:<24} {sweep_str}")


if __name__ == "__main__":
    main()
