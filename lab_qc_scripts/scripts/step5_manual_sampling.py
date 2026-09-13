#!/usr/bin/env python3
"""STEP 5: build manual QA sample lists."""

from __future__ import annotations

import argparse
import os
import random

# before running this script, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
#   source /home/yur5/Documents/mytorch/bin/activate
# according to the instructions in qc/README.md「ACCRE cluster」, activate the virtual environment containing numpy/pandas.
import pandas as pd

from qc_common import build_default_paths, ensure_output_dir


def write_list(path: str, items: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(f"{item}\n")


def unique_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def top_subjects(df: pd.DataFrame, metric: str, n: int) -> list[str]:
    if metric not in df.columns:
        return []
    top_df = df.sort_values(metric, ascending=False).head(n)
    return top_df["subject"].astype(str).tolist()


def main() -> None:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(description="STEP 5 - manual QA sampling")
    parser.add_argument("--output-dir", default=defaults["output_dir"])
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--median-n", type=int, default=10)
    parser.add_argument("--random-ratio", type=float, default=0.05)
    parser.add_argument("--random-seed", type=int, default=42)
    args = parser.parse_args()

    ensure_output_dir(args.output_dir)
    metrics_csv = os.path.join(args.output_dir, "qa_confounds_metrics.csv")
    success_csv = os.path.join(args.output_dir, "qa_success_check.csv")

    mdf = pd.read_csv(metrics_csv)
    sdf = pd.read_csv(success_csv)
    complete_subs = set(
        sdf.loc[sdf["success"].fillna(0).astype(int) == 1, "subject"].astype(str).tolist()
    )
    df = mdf[mdf["subject"].astype(str).isin(complete_subs)].copy()

    top_mean_fd = top_subjects(df, "mean_fd", args.top_n)
    top_max_fd = top_subjects(df, "max_fd", args.top_n)
    top_std_dvars = top_subjects(df, "mean_std_dvars", args.top_n)
    top_motion_outlier_percent = top_subjects(df, "motion_outlier_percent", args.top_n)

    median_neighbors: list[str] = []
    if "mean_fd" in df.columns and not df["mean_fd"].dropna().empty:
        median_val = df["mean_fd"].median()
        near_df = df.assign(_dist=(df["mean_fd"] - median_val).abs()).sort_values("_dist")
        median_neighbors = near_df["subject"].astype(str).head(args.median_n).tolist()

    include_path = os.path.join(args.output_dir, "first_pass_include_subjects.txt")
    include_subs: list[str] = []
    if os.path.exists(include_path):
        with open(include_path, "r", encoding="utf-8") as f:
            include_subs = [line.strip() for line in f if line.strip()]
    else:
        include_subs = sorted(complete_subs)

    random.seed(args.random_seed)
    n_random = max(1, int(round(len(include_subs) * args.random_ratio))) if include_subs else 0
    random_sample = random.sample(include_subs, min(n_random, len(include_subs)))

    out_top_mean = os.path.join(args.output_dir, "top20_mean_fd.txt")
    out_top_max = os.path.join(args.output_dir, "top20_max_fd_subjects.txt")
    out_top_std = os.path.join(args.output_dir, "top20_std_dvars_subjects.txt")
    out_top_motion = os.path.join(args.output_dir, "top20_motion_outlier_percent_subjects.txt")
    out_median = os.path.join(args.output_dir, "median_mean_fd_10_subjects.txt")
    out_random = os.path.join(args.output_dir, "random_5_percent_subjects.txt")
    out_union = os.path.join(args.output_dir, "sample_for_manual_check.txt")

    write_list(out_top_mean, top_mean_fd)
    write_list(out_top_max, top_max_fd)
    write_list(out_top_std, top_std_dvars)
    write_list(out_top_motion, top_motion_outlier_percent)
    write_list(out_median, median_neighbors)
    write_list(out_random, random_sample)

    combined = unique_keep_order(
        top_mean_fd
        + top_max_fd
        + top_std_dvars
        + top_motion_outlier_percent
        + median_neighbors
        + random_sample
    )
    write_list(out_union, combined)

    print(f"Wrote: {out_top_mean}")
    print(f"Wrote: {out_top_max}")
    print(f"Wrote: {out_top_std}")
    print(f"Wrote: {out_top_motion}")
    print(f"Wrote: {out_median}")
    print(f"Wrote: {out_random}")
    print(f"Wrote: {out_union}")


if __name__ == "__main__":
    main()
