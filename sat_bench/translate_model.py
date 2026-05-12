#!/usr/bin/env python3
"""Translate an Exa10 (aoexact) SAT model from M=N_src to M=N_dst phase hints.

Var IDs differ between M values because nObjs = nVars + N is in the
indexing formulas. This script computes, for each "role" (SelVar / SelVarOut /
SelVarOutConst / OpVar / ValueVar), the src and dst var IDs and emits the
appropriate ± phase line for every role that exists at both M values.

Aux vars (the 1-hot helpers) are deliberately *not* transferred — their
purpose is internal to the cardinality encoding, and their values
depend on local 1-hot ordering rather than gate semantics.

Usage:
  translate_model.py --n-in N --n-out M --m-src K_src --m-dst K_dst \
                     model_src.phase model_dst.phase
"""
import argparse
import sys


def make_layout(n_in, n_out, N):
    """Return Exa10 var-ID functions for the given M=N instance."""
    nVars     = 2 * n_in
    nOutsTot  = 2 * n_out
    nMints    = 1 << n_in
    nObjs     = nVars + N
    nSelVars  = 2 * N * nObjs + nOutsTot * nObjs + 2 * nOutsTot

    def SelVar(iNode, iFanin, iObj):
        return 1 + (iNode * 2 + iFanin) * nObjs + (iObj - 1)

    def SelVarOut(iOut, iObj):
        return 1 + 2 * N * nObjs + iOut * nObjs + (iObj - 1)

    def SelVarOutConst(iOut, val):
        return 1 + 2 * N * nObjs + nOutsTot * nObjs + (iOut * 2 + val)

    def OpVar(iNode):
        return 1 + 2 * nSelVars + iNode

    def ValueVar(iObj, Place, iMint):
        return 1 + 2 * nSelVars + N + ((iObj - 1) * 3 + Place) * nMints + iMint

    return {
        "nVars": nVars, "nOutsTot": nOutsTot, "nMints": nMints,
        "N": N, "nObjs": nObjs, "nSelVars": nSelVars,
        "SelVar": SelVar, "SelVarOut": SelVarOut,
        "SelVarOutConst": SelVarOutConst,
        "OpVar": OpVar, "ValueVar": ValueVar,
    }


def read_model(path):
    """Phase file: one signed int per line (positive = true, negative = false)."""
    m = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("c"):
                continue
            lit = int(s)
            if lit == 0:
                continue
            m[abs(lit)] = 1 if lit > 0 else -1
    return m


def translate(model_src, n_in, n_out, N_src, N_dst):
    src = make_layout(n_in, n_out, N_src)
    dst = make_layout(n_in, n_out, N_dst)

    nVars = 2 * n_in
    common_N = min(N_src, N_dst)
    common_nObjs = nVars + common_N

    out = []

    # SelVar(iNode in [0, common_N), iFanin in {0,1}, iObj in [1, common_nObjs])
    for iNode in range(common_N):
        for iFanin in (0, 1):
            for iObj in range(1, common_nObjs + 1):
                sid = src["SelVar"](iNode, iFanin, iObj)
                did = dst["SelVar"](iNode, iFanin, iObj)
                v = model_src.get(sid)
                if v is not None:
                    out.append(did * v)

    # SelVarOut(iOut in [0, nOutsTot), iObj in [1, common_nObjs])
    for iOut in range(src["nOutsTot"]):
        for iObj in range(1, common_nObjs + 1):
            sid = src["SelVarOut"](iOut, iObj)
            did = dst["SelVarOut"](iOut, iObj)
            v = model_src.get(sid)
            if v is not None:
                out.append(did * v)

    # SelVarOutConst(iOut, val) — same shape in both
    for iOut in range(src["nOutsTot"]):
        for val in (0, 1):
            sid = src["SelVarOutConst"](iOut, val)
            did = dst["SelVarOutConst"](iOut, val)
            v = model_src.get(sid)
            if v is not None:
                out.append(did * v)

    # OpVar(iNode in [0, common_N))
    for iNode in range(common_N):
        sid = src["OpVar"](iNode)
        did = dst["OpVar"](iNode)
        v = model_src.get(sid)
        if v is not None:
            out.append(did * v)

    # ValueVar(iObj in [1, common_nObjs], Place in {0,1,2}, iMint)
    for iObj in range(1, common_nObjs + 1):
        for Place in (0, 1, 2):
            for iMint in range(src["nMints"]):
                sid = src["ValueVar"](iObj, Place, iMint)
                did = dst["ValueVar"](iObj, Place, iMint)
                v = model_src.get(sid)
                if v is not None:
                    out.append(did * v)

    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-in", type=int, required=True)
    ap.add_argument("--n-out", type=int, required=True)
    ap.add_argument("--m-src", type=int, required=True)
    ap.add_argument("--m-dst", type=int, required=True)
    ap.add_argument("src", help="Source phase file (model at M=m-src)")
    ap.add_argument("dst", help="Output phase file (translated to M=m-dst)")
    args = ap.parse_args()

    model = read_model(args.src)
    out = translate(model, args.n_in, args.n_out, args.m_src, args.m_dst)

    with open(args.dst, "w") as f:
        for lit in out:
            f.write(f"{lit}\n")

    sys.stderr.write(
        f"translated {len(out)} phase hints from M={args.m_src} to M={args.m_dst} "
        f"(source model had {len(model)} entries)\n"
    )


if __name__ == "__main__":
    main()
