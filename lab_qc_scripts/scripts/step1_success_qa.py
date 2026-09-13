#!/usr/bin/env python3
"""STEP 1: check fMRIPrep output completeness per subject."""

from __future__ import annotations

import csv
import os

# Step1 only depends on Python standard library, running on login node usually works; if you want to run Step2–6 in the same shell, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
# according to the instructions in qc/README.md「ACCRE cluster」, activate the virtual environment containing numpy/pandas.

from qc_common import (
    ensure_output_dir,
    find_subject_files,
    is_nonempty_file,
    list_subjects,
    parse_common_args,
)


def has_nonempty_match(paths: list[str]) -> int:
    return 1 if any(is_nonempty_file(p) for p in paths) else 0


def main() -> None:
    args = parse_common_args("STEP 1 - fMRIPrep output completeness QA")
    ensure_output_dir(args.output_dir)

    subjects = list_subjects(args.derivatives_dir)
    out_csv = os.path.join(args.output_dir, "qa_success_check.csv")
    out_summary = os.path.join(args.output_dir, "qa_success_summary.txt")

    rows = []
    incomplete = []
    complete_count = 0

    for subject in subjects:
        html_candidates = [
            os.path.join(args.derivatives_dir, f"{subject}.html"),
            os.path.join(args.derivatives_dir, "fmriprep", f"{subject}.html"),
        ]
        has_html = has_nonempty_match(html_candidates)

        bold_matches = find_subject_files(
            args.derivatives_dir,
            subject,
            "func/*space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz",
        )
        has_bold = has_nonempty_match(bold_matches)

        confound_matches = find_subject_files(
            args.derivatives_dir,
            subject,
            "func/*desc-confounds_timeseries.tsv",
        )
        has_confounds = has_nonempty_match(confound_matches)

        success = 1 if (has_html and has_bold and has_confounds) else 0
        if success:
            complete_count += 1
        else:
            incomplete.append(subject)

        rows.append(
            {
                "subject": subject,
                "has_html": has_html,
                "has_bold": has_bold,
                "has_confounds": has_confounds,
                "success": success,
            }
        )

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["subject", "has_html", "has_bold", "has_confounds", "success"]
        )
        writer.writeheader()
        writer.writerows(rows)

    with open(out_summary, "w", encoding="utf-8") as f:
        f.write(f"Complete subjects: {complete_count}\n")
        f.write(f"Incomplete subjects: {len(incomplete)}\n")
        f.write(
            "Incomplete subject IDs: "
            + (", ".join(incomplete) if incomplete else "(none)")
            + "\n"
        )
        f.write(f"Total preprocessed subject folders detected: {len(subjects)}\n")

    print(f"Wrote: {out_csv}")
    print(f"Wrote: {out_summary}")


if __name__ == "__main__":
    main()
