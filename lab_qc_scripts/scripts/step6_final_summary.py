#!/usr/bin/env python3
"""STEP 6: summarize first-pass and final QA counts."""

from __future__ import annotations

import argparse
import os
from typing import Iterable

# before running this script, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
#   source /home/yur5/Documents/mytorch/bin/activate
# according to the instructions in qc/README.md「ACCRE cluster」, activate the virtual environment containing numpy/pandas.
import pandas as pd

from qc_common import build_default_paths, ensure_output_dir


def read_subject_list(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def ensure_files_exist(paths: Iterable[str]) -> None:
    for p in paths:
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8"):
                pass


def main() -> None:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(description="STEP 6 - final QA summary table")
    parser.add_argument("--output-dir", default=defaults["output_dir"])
    args = parser.parse_args()

    ensure_output_dir(args.output_dir)
    success_csv = os.path.join(args.output_dir, "qa_success_check.csv")

    first_exclude = os.path.join(args.output_dir, "first_pass_exclude_subjects.txt")
    first_caution = os.path.join(args.output_dir, "first_pass_caution_subjects.txt")
    final_exclude = os.path.join(args.output_dir, "final_exclude_subjects.txt")
    final_caution = os.path.join(args.output_dir, "final_caution_subjects.txt")
    final_include = os.path.join(args.output_dir, "final_include_subjects.txt")

    ensure_files_exist([final_exclude, final_caution, final_include])

    success_df = pd.read_csv(success_csv)
    total_subjects = int(success_df.shape[0])
    complete_subjects = int((success_df["success"].fillna(0).astype(int) == 1).sum())

    rows = [
        ("total_subjects", total_subjects),
        ("complete_subjects", complete_subjects),
        ("first_pass_exclude", len(read_subject_list(first_exclude))),
        ("first_pass_caution", len(read_subject_list(first_caution))),
        ("final_exclude", len(read_subject_list(final_exclude))),
        ("final_caution", len(read_subject_list(final_caution))),
        ("final_include", len(read_subject_list(final_include))),
    ]

    out_csv = os.path.join(args.output_dir, "qc_summary.csv")
    pd.DataFrame(rows, columns=["category", "count"]).to_csv(out_csv, index=False)
    print(f"Wrote: {out_csv}")


if __name__ == "__main__":
    main()
