#!/usr/bin/env python3
"""STEP 4: generate first-pass exclude/caution/include lists."""

from __future__ import annotations

import argparse
import os
from typing import List, Set

# before running this script, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
#   source /home/yur5/Documents/mytorch/bin/activate
# according to the instructions in qc/README.md「ACCRE cluster」, activate the virtual environment containing numpy/pandas.
import pandas as pd

from qc_common import build_default_paths, ensure_output_dir


def write_subject_list(path: str, subjects: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for sub in subjects:
            f.write(f"{sub}\n")


def combine_or(parts: List[pd.Series]) -> pd.Series:
    if not parts:
        return pd.Series(dtype=bool)
    out = parts[0]
    for p in parts[1:]:
        out = out | p
    return out


def main() -> None:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(description="STEP 4 - first-pass QC lists")
    parser.add_argument(
        "--output-dir",
        default=defaults["output_dir"],
        help="Directory containing qa_success_check.csv and qa_confounds_metrics.csv.",
    )

    # Default strict (always on): missing outputs + mean_fd > threshold
    parser.add_argument(
        "--strict-mean-fd",
        type=float,
        default=0.5,
        help="Default strict rule: exclude if mean_fd exceeds this (mm).",
    )

    # Optional strict rules (off unless --enable-*)
    parser.add_argument(
        "--enable-strict-fd-gt-0p5-percent",
        action="store_true",
        help="Optional strict: fd_gt_0p5_percent > threshold.",
    )
    parser.add_argument("--strict-fd-gt-0p5-percent", type=float, default=20.0)
    parser.add_argument(
        "--enable-strict-motion-outlier-percent",
        action="store_true",
        help="Optional strict: motion_outlier_percent > threshold.",
    )
    parser.add_argument("--strict-motion-outlier-percent", type=float, default=50.0)
    parser.add_argument(
        "--enable-strict-max-fd",
        action="store_true",
        help="Optional strict: max_fd > threshold (mm).",
    )
    parser.add_argument("--strict-max-fd", type=float, default=5.0)

    # Default caution (always on): motion_outlier_percent > threshold
    parser.add_argument(
        "--caution-motion-outlier-percent",
        type=float,
        default=20.0,
        help="Default caution rule: flag if motion_outlier_percent exceeds this.",
    )

    # Optional caution rules (off unless --enable-*)
    parser.add_argument(
        "--enable-caution-mean-fd",
        action="store_true",
        help="Optional caution: mean_fd > threshold.",
    )
    parser.add_argument("--caution-mean-fd", type=float, default=0.2)
    parser.add_argument(
        "--enable-caution-fd-gt-0p2-percent",
        action="store_true",
        help="Optional caution: fd_gt_0p2_percent > threshold.",
    )
    parser.add_argument("--caution-fd-gt-0p2-percent", type=float, default=20.0)
    parser.add_argument(
        "--enable-caution-max-fd",
        action="store_true",
        help="Optional caution: max_fd > threshold (mm).",
    )
    parser.add_argument("--caution-max-fd", type=float, default=1.0)
    parser.add_argument(
        "--enable-caution-fd-gt-0p5-percent",
        action="store_true",
        help="Optional caution: fd_gt_0p5_percent > threshold.",
    )
    parser.add_argument("--caution-fd-gt-0p5-percent", type=float, default=5.0)
    parser.add_argument(
        "--enable-caution-std-dvars-gt-1p5-percent",
        action="store_true",
        help="Optional caution: std_dvars_gt_1p5_percent > threshold.",
    )
    parser.add_argument("--caution-std-dvars-gt-1p5-percent", type=float, default=20.0)

    args = parser.parse_args()

    ensure_output_dir(args.output_dir)
    success_csv = os.path.join(args.output_dir, "qa_success_check.csv")
    metrics_csv = os.path.join(args.output_dir, "qa_confounds_metrics.csv")

    success_df = pd.read_csv(success_csv)
    metrics_df = pd.read_csv(metrics_csv)
    df = pd.merge(success_df, metrics_df, on="subject", how="left")

    all_subjects = sorted(success_df["subject"].astype(str).tolist())
    missing_required = set(
        df.loc[df["success"].fillna(0).astype(int) == 0, "subject"].astype(str).tolist()
    )

    strict_parts: List[pd.Series] = [df["mean_fd"] > args.strict_mean_fd]
    if args.enable_strict_fd_gt_0p5_percent:
        strict_parts.append(df["fd_gt_0p5_percent"] > args.strict_fd_gt_0p5_percent)
    if args.enable_strict_motion_outlier_percent:
        strict_parts.append(
            df["motion_outlier_percent"] > args.strict_motion_outlier_percent
        )
    if args.enable_strict_max_fd:
        strict_parts.append(df["max_fd"] > args.strict_max_fd)

    strict_quality = set(df.loc[combine_or(strict_parts), "subject"].astype(str).tolist())
    strict_exclude: Set[str] = missing_required | strict_quality

    caution_parts: List[pd.Series] = [
        df["motion_outlier_percent"] > args.caution_motion_outlier_percent
    ]
    if args.enable_caution_mean_fd:
        caution_parts.append(df["mean_fd"] > args.caution_mean_fd)
    if args.enable_caution_fd_gt_0p2_percent:
        caution_parts.append(df["fd_gt_0p2_percent"] > args.caution_fd_gt_0p2_percent)
    if args.enable_caution_max_fd:
        caution_parts.append(df["max_fd"] > args.caution_max_fd)
    if args.enable_caution_fd_gt_0p5_percent:
        caution_parts.append(df["fd_gt_0p5_percent"] > args.caution_fd_gt_0p5_percent)
    if args.enable_caution_std_dvars_gt_1p5_percent:
        caution_parts.append(
            df["std_dvars_gt_1p5_percent"] > args.caution_std_dvars_gt_1p5_percent
        )

    caution = set(df.loc[combine_or(caution_parts), "subject"].astype(str).tolist())
    caution -= strict_exclude

    include = sorted(set(all_subjects) - strict_exclude - caution)
    exclude = sorted(strict_exclude)
    caution = sorted(caution)

    exclude_path = os.path.join(args.output_dir, "first_pass_exclude_subjects.txt")
    caution_path = os.path.join(args.output_dir, "first_pass_caution_subjects.txt")
    include_path = os.path.join(args.output_dir, "first_pass_include_subjects.txt")
    rules_path = os.path.join(args.output_dir, "first_pass_rules.txt")

    write_subject_list(exclude_path, exclude)
    write_subject_list(caution_path, caution)
    write_subject_list(include_path, include)

    with open(rules_path, "w", encoding="utf-8") as f:
        f.write("First-pass rules (CLI flags override thresholds)\n\n")
        f.write("Strict exclusion — default (always on):\n")
        f.write("1) Missing required outputs (HTML, preprocessed BOLD, or confounds TSV).\n")
        f.write(f"2) mean_fd > {args.strict_mean_fd} mm.\n\n")
        f.write("Strict exclusion — optional (enabled in this run):\n")
        opt_strict = []
        if args.enable_strict_fd_gt_0p5_percent:
            opt_strict.append(
                f"fd_gt_0p5_percent > {args.strict_fd_gt_0p5_percent}%"
            )
        if args.enable_strict_motion_outlier_percent:
            opt_strict.append(
                f"motion_outlier_percent > {args.strict_motion_outlier_percent}%"
            )
        if args.enable_strict_max_fd:
            opt_strict.append(f"max_fd > {args.strict_max_fd} mm")
        if opt_strict:
            for i, rule in enumerate(opt_strict, 1):
                f.write(f"{i}) {rule}.\n")
        else:
            f.write("(none — pass --enable-strict-* flags to turn on)\n")
        f.write("\nCaution / sensitivity — default (always on):\n")
        f.write(
            f"1) motion_outlier_percent > {args.caution_motion_outlier_percent}%.\n\n"
        )
        f.write("Caution — optional (enabled in this run):\n")
        opt_caution = []
        if args.enable_caution_mean_fd:
            opt_caution.append(f"mean_fd > {args.caution_mean_fd} mm")
        if args.enable_caution_fd_gt_0p2_percent:
            opt_caution.append(f"fd_gt_0p2_percent > {args.caution_fd_gt_0p2_percent}%")
        if args.enable_caution_max_fd:
            opt_caution.append(f"max_fd > {args.caution_max_fd} mm")
        if args.enable_caution_fd_gt_0p5_percent:
            opt_caution.append(f"fd_gt_0p5_percent > {args.caution_fd_gt_0p5_percent}%")
        if args.enable_caution_std_dvars_gt_1p5_percent:
            opt_caution.append(
                f"std_dvars_gt_1p5_percent > {args.caution_std_dvars_gt_1p5_percent}%"
            )
        if opt_caution:
            for i, rule in enumerate(opt_caution, 1):
                f.write(f"{i}) {rule}.\n")
        else:
            f.write("(none — pass --enable-caution-* flags to turn on)\n")
        f.write("\n")
        f.write(f"n_exclude={len(exclude)}\n")
        f.write(f"n_caution={len(caution)}\n")
        f.write(f"n_include={len(include)}\n")

    print(f"Wrote: {exclude_path}")
    print(f"Wrote: {caution_path}")
    print(f"Wrote: {include_path}")
    print(f"Wrote: {rules_path}")


if __name__ == "__main__":
    main()
