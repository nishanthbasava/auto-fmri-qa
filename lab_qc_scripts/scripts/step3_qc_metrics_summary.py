#!/usr/bin/env python3
"""STEP 3: cohort-level QC metrics summary (runs after Step 2, before Step 4)."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

# before running this script, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
import pandas as pd

from qc_common import build_default_paths, ensure_output_dir


def count_gt(series: pd.Series, threshold: float) -> int:
    s = pd.to_numeric(series, errors="coerce")
    return int((s > threshold).sum())


def main() -> None:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(description="STEP 3 - QC metrics cohort summary")
    parser.add_argument("--output-dir", default=defaults["output_dir"])
    parser.add_argument("--out-file", default="qa_metrics_summary.txt")
    args = parser.parse_args()

    ensure_output_dir(args.output_dir)
    success_csv = os.path.join(args.output_dir, "qa_success_check.csv")
    metrics_csv = os.path.join(args.output_dir, "qa_confounds_metrics.csv")
    out_path = os.path.join(args.output_dir, args.out_file)

    success_df = pd.read_csv(success_csv)
    metrics_df = pd.read_csv(metrics_csv)

    total_subjects = int(success_df.shape[0])
    n_missing_outputs = int((success_df["success"].fillna(0).astype(int) == 0).sum())

    # Metric counts: subjects with confounds metrics available
    n_mean_fd_gt_0p5 = count_gt(metrics_df["mean_fd"], 0.5)
    n_mean_fd_gt_0p2 = count_gt(metrics_df["mean_fd"], 0.2)
    n_fd_gt_0p5_percent_gt_20 = count_gt(metrics_df["fd_gt_0p5_percent"], 20.0)
    n_fd_gt_0p2_percent_gt_20 = count_gt(metrics_df["fd_gt_0p2_percent"], 20.0)
    n_fd_gt_0p5_percent_gt_5 = count_gt(metrics_df["fd_gt_0p5_percent"], 5.0)
    n_motion_outlier_percent_gt_50 = count_gt(metrics_df["motion_outlier_percent"], 50.0)
    n_max_fd_gt_5 = count_gt(metrics_df["max_fd"], 5.0)
    n_max_fd_gt_1 = count_gt(metrics_df["max_fd"], 1.0)
    n_std_dvars_gt_1p5_percent_gt_20 = count_gt(metrics_df["std_dvars_gt_1p5_percent"], 20.0)
    n_motion_outlier_percent_gt_20 = count_gt(metrics_df["motion_outlier_percent"], 20.0)

    n_with_metrics = int(metrics_df.shape[0])
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "QC metrics summary (subject counts)",
        f"Generated: {generated}",
        f"Sources: {os.path.basename(success_csv)}, {os.path.basename(metrics_csv)}",
        "",
        f"Total subjects (from {os.path.basename(success_csv)}): {total_subjects}",
        (
            "Missing required outputs (HTML / BOLD / confounds): "
            f"{n_missing_outputs}"
        ),
        "",
        (
            f"Subjects with confounds metrics ({os.path.basename(metrics_csv)}): "
            f"{n_with_metrics}"
        ),
        "Counts below are among subjects with confounds metrics only.",
        "",
        f"mean_fd > 0.5 mm: {n_mean_fd_gt_0p5}",
        f"mean_fd > 0.2 mm: {n_mean_fd_gt_0p2}",
        f"FD > 0.5 mm for > 20% of volumes (fd_gt_0p5_percent > 20%): {n_fd_gt_0p5_percent_gt_20}",
        f"FD > 0.2 mm for > 20% of volumes (fd_gt_0p2_percent > 20%): {n_fd_gt_0p2_percent_gt_20}",
        f"FD > 0.5 mm for > 5% of volumes (fd_gt_0p5_percent > 5%): {n_fd_gt_0p5_percent_gt_5}",
        f"motion_outlier_percent > 50%: {n_motion_outlier_percent_gt_50}",
        f"max_fd > 5 mm: {n_max_fd_gt_5}",
        f"max_fd > 1 mm: {n_max_fd_gt_1}",
        (
            "std_dvars > 1.5 for > 20% of volumes "
            f"(std_dvars_gt_1p5_percent > 20%): {n_std_dvars_gt_1p5_percent_gt_20}"
        ),
        f"motion_outlier_percent > 20%: {n_motion_outlier_percent_gt_20}",
        "",
    ]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
