"""Split a run's scans.csv into the three scan-level QC lists.

    autoqa lists runs/<run>/ [-o lists/]

Writes included_scans.csv, caution_scans.csv, excluded_scans.csv -- the files
`scripts/sort_qc_scans.py` consumes on the cluster. Rows are scan-level
(subject + session) on purpose: sessions of one subject can land in different
lists and are never merged.
"""
from __future__ import annotations

import argparse
import csv
import os

COLUMNS = ["subject", "session", "tr_s", "n_volumes", "mean_fd", "max_fd", "outlier_percent"]
FILES = {"INCLUDE": "included_scans.csv", "CAUTION": "caution_scans.csv",
         "EXCLUDE": "excluded_scans.csv"}


def write_lists(run_dir: str, out_dir: str) -> dict[str, int]:
    rows = {k: [] for k in FILES}
    with open(os.path.join(run_dir, "scans.csv")) as f:
        for r in csv.DictReader(f):
            rows[r["status"]].append(r)
    os.makedirs(out_dir, exist_ok=True)
    counts = {}
    for status, name in FILES.items():
        out = sorted(rows[status], key=lambda r: (r["subject"], r["session"]))
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for r in out:
                w.writerow([r[c] for c in COLUMNS])
        counts[status] = len(out)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("-o", "--out", default="lists")
    args = ap.parse_args(argv)
    for status, n in write_lists(args.run_dir, args.out).items():
        print(f"{status:8s} {n:4d} -> {os.path.join(args.out, FILES[status])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
