#!/usr/bin/env python3
"""Roll up audit_*.tsv files into a single summary table.

Reads every audit_<engine>_n<N>_m<M>.tsv passed on the command line; reports
the verdict distribution and lists any rows that need attention (WRONG or
upper_bound)."""
import csv, sys
from collections import Counter

def main():
    if len(sys.argv) < 2:
        print("usage: audit_summary.py <audit.tsv> [...]", file=sys.stderr)
        sys.exit(2)
    print(f"{'audit file':<50} {'rows':>5} {'verdicts':<60}")
    print("-" * 120)
    flagged = []
    for path in sys.argv[1:]:
        rows = list(csv.DictReader(open(path), delimiter="\t"))
        c = Counter(r["verdict"] for r in rows)
        verdict_str = ", ".join(f"{k}={v}" for k, v in c.most_common())
        print(f"{path:<50} {len(rows):>5} {verdict_str}")
        for r in rows:
            if r["verdict"] in ("proven", "trivial"):
                continue
            flagged.append((path, r))
    if flagged:
        print("\nNon-trivial / non-proven rows:")
        for path, r in flagged:
            print(f"  {path:<50} tt={r['tt']} k={r['reported_k']} probe_M={r['probe_M']} "
                  f"status={r['probe_status']} verify={r['verify']} -> {r['verdict']}")

if __name__ == "__main__":
    main()
