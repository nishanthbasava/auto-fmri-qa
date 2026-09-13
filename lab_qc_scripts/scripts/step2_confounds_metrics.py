#!/usr/bin/env python3
"""STEP 2: compute confounds-derived QA metrics."""

from __future__ import annotations

import math
import os
from typing import Iterable

# before running this script, please activate the virtual environment containing numpy/pandas according to the instructions in qc/README.md「ACCRE cluster」.
# default python3 on ACCRE usually does not have numpy; when you cannot randomly pip install to the system Python, you must use your own venv.
# according to the instructions in qc/README.md「ACCRE cluster」, activate the virtual environment containing numpy/pandas.
import numpy as np
import pandas as pd

from qc_common import ensure_output_dir, find_subject_files, list_subjects, parse_common_args


def safe_series(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[col], errors="coerce").dropna()


def mean_or_nan(values: pd.Series) -> float:
    return float(values.mean()) if len(values) else math.nan


def median_or_nan(values: pd.Series) -> float:
    return float(values.median()) if len(values) else math.nan


def max_or_nan(values: pd.Series) -> float:
    return float(values.max()) if len(values) else math.nan


def count_prefix(columns: Iterable[str], prefix: str) -> int:
    return sum(1 for c in columns if c.startswith(prefix))


def main() -> None:
    args = parse_common_args("STEP 2 - confounds metrics QA")
    ensure_output_dir(args.output_dir)

    subjects = list_subjects(args.derivatives_dir)
    metrics_rows = []

    for subject in subjects:
        confound_paths = find_subject_files(
            args.derivatives_dir,
            subject,
            "func/*desc-confounds_timeseries.tsv",
        )
        if not confound_paths:
            continue

        dfs = []
        for p in confound_paths:
            try:
                dfs.append(pd.read_csv(p, sep="\t"))
            except Exception:
                continue
        if not dfs:
            continue

        df = pd.concat(dfs, ignore_index=True)
        n_volume = int(df.shape[0])

        fd = safe_series(df, "framewise_displacement")
        dvars = safe_series(df, "dvars")
        std_dvars = safe_series(df, "std_dvars")

        fd_gt_0p2_count = int((fd > 0.2).sum()) if len(fd) else 0
        fd_gt_0p5_count = int((fd > 0.5).sum()) if len(fd) else 0
        fd_gt_0p2_percent = 100.0 * fd_gt_0p2_count / n_volume if n_volume else math.nan
        fd_gt_0p5_percent = 100.0 * fd_gt_0p5_count / n_volume if n_volume else math.nan

        # Usable volumes under FD < 0.2 mm (same threshold family as fd_gt_0p2; excludes NaN FD rows)
        fd_all = (
            pd.to_numeric(df["framewise_displacement"], errors="coerce")
            if "framewise_displacement" in df.columns
            else pd.Series(dtype=float)
        )
        n_volumes_after_scrubbing = int((fd_all < 0.2).sum())
        percent_remaining_after_scrubbing = (
            100.0 * n_volumes_after_scrubbing / n_volume if n_volume else math.nan
        )

        std_dvars_gt_1p5_count = int((std_dvars > 1.5).sum()) if len(std_dvars) else 0
        std_dvars_gt_1p5_percent = (
            100.0 * std_dvars_gt_1p5_count / n_volume if n_volume else math.nan
        )

        motion_outlier_cols = sorted([c for c in df.columns if c.startswith("motion_outlier")])
        n_motion_outliers = len(motion_outlier_cols)
        motion_outlier_percent = (
            100.0 * n_motion_outliers / n_volume if n_volume else math.nan
        )

        global_signal = safe_series(df, "global_signal")
        csf = safe_series(df, "csf")
        white_matter = safe_series(df, "white_matter")
        if white_matter.empty and "csf_wm" in df.columns:
            white_matter = safe_series(df, "csf_wm")

        trans_x = safe_series(df, "trans_x")
        trans_y = safe_series(df, "trans_y")
        trans_z = safe_series(df, "trans_z")
        rot_x = safe_series(df, "rot_x")
        rot_y = safe_series(df, "rot_y")
        rot_z = safe_series(df, "rot_z")

        rms_trans_mean = math.nan
        if {"trans_x", "trans_y", "trans_z"}.issubset(df.columns):
            trans_xyz = df[["trans_x", "trans_y", "trans_z"]].apply(
                pd.to_numeric, errors="coerce"
            )
            arr_t = trans_xyz.to_numpy(dtype=float, copy=False)
            rms_trans = np.sqrt(np.nansum(arr_t * arr_t, axis=1))
            rms_trans_mean = float(np.nanmean(rms_trans))

        rms_rot_mean = math.nan
        if {"rot_x", "rot_y", "rot_z"}.issubset(df.columns):
            rot_xyz = df[["rot_x", "rot_y", "rot_z"]].apply(pd.to_numeric, errors="coerce")
            arr_r = rot_xyz.to_numpy(dtype=float, copy=False)
            rms_rot = np.sqrt(np.nansum(arr_r * arr_r, axis=1))
            rms_rot_mean = float(np.nanmean(rms_rot))

        corr_fd_dvars = math.nan
        if "framewise_displacement" in df.columns and "dvars" in df.columns:
            fd_c = pd.to_numeric(df["framewise_displacement"], errors="coerce")
            dv_c = pd.to_numeric(df["dvars"], errors="coerce")
            ok = fd_c.notna() & dv_c.notna()
            if int(ok.sum()) >= 2 and fd_c[ok].std() > 0 and dv_c[ok].std() > 0:
                corr_fd_dvars = float(fd_c[ok].corr(dv_c[ok]))

        metrics_rows.append(
            {
                "subject": subject,
                "n_volume": n_volume,
                "mean_fd": mean_or_nan(fd),
                "median_fd": median_or_nan(fd),
                "max_fd": max_or_nan(fd),
                "fd_gt_0p2_count": fd_gt_0p2_count,
                "fd_gt_0p2_percent": fd_gt_0p2_percent,
                "n_volumes_after_scrubbing": n_volumes_after_scrubbing,
                "percent_remaining_after_scrubbing": percent_remaining_after_scrubbing,
                "fd_gt_0p5_count": fd_gt_0p5_count,
                "fd_gt_0p5_percent": fd_gt_0p5_percent,
                "mean_dvars": mean_or_nan(dvars),
                "max_dvars": max_or_nan(dvars),
                "mean_std_dvars": mean_or_nan(std_dvars),
                "max_std_dvars": max_or_nan(std_dvars),
                "corr_fd_dvars": corr_fd_dvars,
                "std_dvars_gt_1p5_count": std_dvars_gt_1p5_count,
                "std_dvars_gt_1p5_percent": std_dvars_gt_1p5_percent,
                "n_motion_outliers": n_motion_outliers,
                "motion_outlier_percent": motion_outlier_percent,
                "mean_global_signal": mean_or_nan(global_signal),
                "std_global_signal": float(global_signal.std()) if len(global_signal) else math.nan,
                "mean_csf": mean_or_nan(csf),
                "std_csf": float(csf.std()) if len(csf) else math.nan,
                "mean_white_matter": mean_or_nan(white_matter),
                "std_white_matter": float(white_matter.std()) if len(white_matter) else math.nan,
                "max_abs_trans_x": float(trans_x.abs().max()) if len(trans_x) else math.nan,
                "max_abs_trans_y": float(trans_y.abs().max()) if len(trans_y) else math.nan,
                "max_abs_trans_z": float(trans_z.abs().max()) if len(trans_z) else math.nan,
                "max_abs_rot_x": float(rot_x.abs().max()) if len(rot_x) else math.nan,
                "max_abs_rot_y": float(rot_y.abs().max()) if len(rot_y) else math.nan,
                "max_abs_rot_z": float(rot_z.abs().max()) if len(rot_z) else math.nan,
                "rms_trans_mean": rms_trans_mean,
                "rms_rot_mean": rms_rot_mean,
                "n_a_comp_cor": count_prefix(df.columns, "a_comp_cor_"),
                "n_t_comp_cor": count_prefix(df.columns, "t_comp_cor_"),
                "n_c_comp_cor": count_prefix(df.columns, "c_comp_cor_"),
                "n_w_comp_cor": count_prefix(df.columns, "w_comp_cor_"),
                "n_edge_comp": count_prefix(df.columns, "edge_comp"),
            }
        )

    out_csv = os.path.join(args.output_dir, "qa_confounds_metrics.csv")
    out_df = pd.DataFrame(metrics_rows).sort_values("subject")

    # Cross-subject z-scores for outlier screening (within this run’s cohort)
    def zscore_series(s: pd.Series) -> pd.Series:
        s = pd.to_numeric(s, errors="coerce")
        mu = s.mean()
        sigma = s.std(ddof=1)
        if sigma is None or not np.isfinite(sigma) or sigma == 0:
            return pd.Series(np.nan, index=s.index)
        return (s - mu) / sigma

    out_df["z_mean_fd"] = zscore_series(out_df["mean_fd"])
    out_df["z_std_dvars"] = zscore_series(out_df["mean_std_dvars"])

    out_df.to_csv(out_csv, index=False)
    print(f"Wrote: {out_csv}")


if __name__ == "__main__":
    main()
