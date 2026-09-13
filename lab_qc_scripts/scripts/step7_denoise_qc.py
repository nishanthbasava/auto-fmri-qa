#!/usr/bin/env python3
"""STEP 7: QC of post-fMRIPrep denoised outputs (frame drop + nuisance regression).

Runs against RAW_bids/derivatives/post_fmriprep_denoise. Everything is SCAN-level
(subject x session) -- sessions of the same subject are never pooled.

    python3 step7_denoise_qc.py \
        --denoise-dir /panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives/post_fmriprep_denoise \
        --expected    /panfs/accrepfs.vampire/data/neurogroup/ADNI/code/adni_fmriprep/fmriprep_qc/output/after_manual/fmriprep_final_pass_scans.txt \
        --output-dir  OUTPUT_DIR

Checks and outputs:
  qa_denoise_completeness.csv   per expected scan: denoised BOLD present and
                                nonempty, run_meta/motion_qc/temporal_qc present,
                                volume-drop check (n_volumes_after_drop consistent
                                with drop_initial_volumes)
  qa_denoise_metrics.csv        per scan: pre/post motion-BOLD coupling
                                (corr_dvars_fd, mean/max voxel-FD corr), pre/post
                                tSNR and DVARS, TR, volumes; cross-cohort z-scores
  qa_denoise_flags.csv          scans flagged for review: residual motion coupling
                                after denoising, tSNR that failed to improve, or
                                cohort-level outliers (|z| > 3)
  qa_denoise_summary.txt        cohort summary (counts, medians pre vs post)

Flag rules (advisory; thresholds at top of file):
  post_corr_dvars_fd > 0.30        denoising left substantial FD-DVARS coupling
  post_mean_abs_corr_voxel_fd > 0.10   voxelwise motion coupling remains
  tsnr_post <= tsnr_pre            regression should not reduce tSNR
  |z| > 3 on post-coupling or post-tSNR within the cohort

Only numpy/pandas required (same venv as steps 2-6).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import re

import numpy as np
import pandas as pd

THR_POST_CORR_DVARS_FD = 0.30
THR_POST_VOXEL_FD_CORR = 0.10
Z_FLAG = 3.0


def parse_expected(path: str):
    """Extract (sub-XXX, ses-XXX) pairs from a scan-list file, format-tolerant."""
    pairs = []
    with open(path) as f:
        for line in f:
            sub = re.search(r"(sub-[A-Za-z0-9]+)", line)
            ses = re.search(r"(ses-[A-Za-z0-9]+)", line)
            if sub and ses:
                pairs.append((sub.group(1), ses.group(1)))
    return sorted(set(pairs))


def discover_scans(denoise_dir: str):
    pairs = []
    for d in sorted(glob.glob(os.path.join(denoise_dir, "sub-*", "ses-*"))):
        if os.path.isdir(d):
            ses = os.path.basename(d)
            sub = os.path.basename(os.path.dirname(d))
            pairs.append((sub, ses))
    return pairs


def read_kv_csv(path: str):
    """motion_qc.csv / temporal_qc_summary.csv readers return {} on any problem."""
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--denoise-dir", required=True,
                    help="post_fmriprep_denoise root")
    ap.add_argument("--expected", default=None,
                    help="scan list file (e.g. fmriprep_final_pass_scans.txt); "
                         "if omitted, QC covers whatever exists")
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    found = discover_scans(args.denoise_dir)
    expected = parse_expected(args.expected) if args.expected else found
    found_set, expected_set = set(found), set(expected)

    # ---------------- completeness ----------------
    comp_rows = []
    for sub, ses in sorted(expected_set | found_set):
        base = os.path.join(args.denoise_dir, sub, ses)
        bolds = glob.glob(os.path.join(base, "func", "*desc-nuisanceReg_bold.nii.gz"))
        bold_ok = any(os.path.getsize(b) > 0 for b in bolds) if bolds else False
        meta_p = os.path.join(base, "run_meta.json")
        meta = None
        if os.path.isfile(meta_p):
            try:
                meta = json.load(open(meta_p))
            except Exception:
                meta = None
        vol_ok = ""
        if meta is not None:
            nd = meta.get("n_volumes_after_drop")
            dr = meta.get("drop_initial_volumes")
            vol_ok = int(nd is not None and dr is not None and nd > 0)
        comp_rows.append({
            "subject": sub, "session": ses,
            "in_expected_list": int((sub, ses) in expected_set),
            "found_on_disk": int((sub, ses) in found_set),
            "has_denoised_bold": int(bold_ok),
            "has_run_meta": int(meta is not None),
            "has_motion_qc": int(os.path.isfile(os.path.join(base, "qc", "motion_qc.csv"))),
            "has_temporal_qc": int(os.path.isfile(os.path.join(base, "qc", "temporal_qc_summary.csv"))),
            "drop_initial_volumes": meta.get("drop_initial_volumes") if meta else "",
            "n_volumes_after_drop": meta.get("n_volumes_after_drop") if meta else "",
            "volumes_recorded_ok": vol_ok,
            "complete": int(bold_ok and meta is not None
                            and os.path.isfile(os.path.join(base, "qc", "motion_qc.csv"))
                            and os.path.isfile(os.path.join(base, "qc", "temporal_qc_summary.csv"))),
        })
    comp_df = pd.DataFrame(comp_rows)
    comp_csv = os.path.join(args.output_dir, "qa_denoise_completeness.csv")
    comp_df.to_csv(comp_csv, index=False)

    # ---------------- per-scan metrics ----------------
    met_rows = []
    for sub, ses in sorted(found_set):
        base = os.path.join(args.denoise_dir, sub, ses)
        row = {"subject": sub, "session": ses}
        meta_p = os.path.join(base, "run_meta.json")
        try:
            meta = json.load(open(meta_p))
            row["tr_sec"] = meta.get("tr_sec")
            row["drop_initial_volumes"] = meta.get("drop_initial_volumes")
            row["n_volumes_after_drop"] = meta.get("n_volumes_after_drop")
            row["n_design_columns"] = len(meta.get("design_columns", []))
        except Exception:
            pass
        mq = read_kv_csv(os.path.join(base, "qc", "motion_qc.csv"))
        if mq is not None and "stage" in mq.columns:
            mq = mq.set_index("stage")
            for stage in ("pre", "post"):
                if stage in mq.index:
                    row[f"{stage}_corr_dvars_fd"] = mq.loc[stage].get("corr_dvars_fd")
                    row[f"{stage}_abs_corr_global_fd"] = mq.loc[stage].get("abs_corr_global_mean_signal_fd")
                    row[f"{stage}_mean_abs_corr_voxel_fd"] = mq.loc[stage].get("mean_abs_corr_voxel_fd")
                vs = f"{stage}_voxel_sample"
                if vs in mq.index:
                    row[f"{stage}_max_abs_corr_voxel_fd"] = mq.loc[vs].get("max_abs_corr_voxel_fd")
        tq = read_kv_csv(os.path.join(base, "qc", "temporal_qc_summary.csv"))
        if tq is not None and {"metric", "pre", "post"}.issubset(tq.columns):
            tq = tq.set_index("metric")
            for name, col in [("tsnr_mean", "tsnr_mean_over_voxels"),
                              ("tsnr_median", "tsnr_median_over_voxels"),
                              ("dvars_mean", "dvars_mean")]:
                if col in tq.index:
                    row[f"pre_{name}"] = tq.loc[col, "pre"]
                    row[f"post_{name}"] = tq.loc[col, "post"]
        met_rows.append(row)
    met_df = pd.DataFrame(met_rows)

    # coupling reduction and tSNR gain
    if {"pre_mean_abs_corr_voxel_fd", "post_mean_abs_corr_voxel_fd"}.issubset(met_df.columns):
        met_df["coupling_reduction"] = (
            pd.to_numeric(met_df["pre_mean_abs_corr_voxel_fd"], errors="coerce")
            - pd.to_numeric(met_df["post_mean_abs_corr_voxel_fd"], errors="coerce"))
    if {"pre_tsnr_mean", "post_tsnr_mean"}.issubset(met_df.columns):
        met_df["tsnr_gain"] = (pd.to_numeric(met_df["post_tsnr_mean"], errors="coerce")
                               - pd.to_numeric(met_df["pre_tsnr_mean"], errors="coerce"))

    def z(col):
        s = pd.to_numeric(met_df.get(col), errors="coerce")
        sd = s.std(ddof=1)
        return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else pd.Series(np.nan, index=met_df.index)

    met_df["z_post_mean_abs_corr_voxel_fd"] = z("post_mean_abs_corr_voxel_fd")
    met_df["z_post_tsnr_mean"] = z("post_tsnr_mean")
    met_csv = os.path.join(args.output_dir, "qa_denoise_metrics.csv")
    met_df.sort_values(["subject", "session"]).to_csv(met_csv, index=False)

    # ---------------- flags ----------------
    flags = []
    for _, r in met_df.iterrows():
        reasons = []
        pc = pd.to_numeric(pd.Series([r.get("post_corr_dvars_fd")]), errors="coerce").iloc[0]
        pv = pd.to_numeric(pd.Series([r.get("post_mean_abs_corr_voxel_fd")]), errors="coerce").iloc[0]
        tp = pd.to_numeric(pd.Series([r.get("pre_tsnr_mean")]), errors="coerce").iloc[0]
        tq_ = pd.to_numeric(pd.Series([r.get("post_tsnr_mean")]), errors="coerce").iloc[0]
        if pd.notna(pc) and pc > THR_POST_CORR_DVARS_FD:
            reasons.append(f"post FD-DVARS corr {pc:.2f} > {THR_POST_CORR_DVARS_FD}")
        if pd.notna(pv) and pv > THR_POST_VOXEL_FD_CORR:
            reasons.append(f"post voxel-FD corr {pv:.3f} > {THR_POST_VOXEL_FD_CORR}")
        if pd.notna(tp) and pd.notna(tq_) and tq_ <= tp:
            reasons.append(f"tSNR did not improve ({tp:.0f} -> {tq_:.0f})")
        for zc in ("z_post_mean_abs_corr_voxel_fd", "z_post_tsnr_mean"):
            zv = pd.to_numeric(pd.Series([r.get(zc)]), errors="coerce").iloc[0]
            if pd.notna(zv) and abs(zv) > Z_FLAG:
                reasons.append(f"{zc} = {zv:.1f}")
        if reasons:
            flags.append({"subject": r["subject"], "session": r["session"],
                          "reasons": "; ".join(reasons)})
    flags_df = pd.DataFrame(flags)
    flags_csv = os.path.join(args.output_dir, "qa_denoise_flags.csv")
    flags_df.to_csv(flags_csv, index=False)

    # ---------------- summary ----------------
    missing = comp_df[(comp_df["in_expected_list"] == 1) & (comp_df["found_on_disk"] == 0)]
    unexpected = comp_df[(comp_df["in_expected_list"] == 0) & (comp_df["found_on_disk"] == 1)]
    incomplete = comp_df[(comp_df["found_on_disk"] == 1) & (comp_df["complete"] == 0)]

    def med(col):
        s = pd.to_numeric(met_df.get(col), errors="coerce").dropna()
        return f"{s.median():.3f}" if len(s) else "n/a"

    lines = [
        "Post-fMRIPrep denoise QC summary",
        f"expected scans: {len(expected_set)}   found on disk: {len(found_set)}",
        f"missing (expected, not found): {len(missing)}",
        f"unexpected (found, not in list): {len(unexpected)}",
        f"incomplete outputs: {len(incomplete)}",
        f"flagged for review: {len(flags_df)}",
        "",
        "cohort medians (pre -> post):",
        f"  FD-DVARS corr:        {med('pre_corr_dvars_fd')} -> {med('post_corr_dvars_fd')}",
        f"  voxel-FD corr (mean): {med('pre_mean_abs_corr_voxel_fd')} -> {med('post_mean_abs_corr_voxel_fd')}",
        f"  tSNR (mean):          {med('pre_tsnr_mean')} -> {med('post_tsnr_mean')}",
    ]
    if len(missing):
        lines.append("\nmissing scans:")
        lines += [f"  {r.subject} {r.session}" for r in missing.itertuples()]
    if len(incomplete):
        lines.append("\nincomplete scans:")
        lines += [f"  {r.subject} {r.session}" for r in incomplete.itertuples()]
    summary = "\n".join(lines) + "\n"
    with open(os.path.join(args.output_dir, "qa_denoise_summary.txt"), "w") as f:
        f.write(summary)
    print(summary)
    print(f"Wrote: {comp_csv}\nWrote: {met_csv}\nWrote: {flags_csv}")


if __name__ == "__main__":
    main()
