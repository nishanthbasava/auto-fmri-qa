#!/usr/bin/env python3
"""Step 5 sub-step: generate manual QA plots with Python + Nilearn."""

from __future__ import annotations

import argparse
import glob
import os
from typing import Iterable, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from nilearn import datasets, image, plotting

from qc_common import build_default_paths, ensure_output_dir


def normalize_subject(raw: str) -> str:
    s = raw.strip().split("#", 1)[0].strip()
    if not s:
        return ""
    if not s.startswith("sub-"):
        s = f"sub-{s}"
    return s


def collect_subjects(subject: str, subjects: str, subject_list_file: str) -> List[str]:
    out = []
    if subject:
        s = normalize_subject(subject)
        if s:
            out.append(s)
    if subjects:
        for token in subjects.split():
            s = normalize_subject(token)
            if s:
                out.append(s)
    if subject_list_file:
        with open(subject_list_file, "r", encoding="utf-8") as f:
            for line in f:
                s = normalize_subject(line)
                if s:
                    out.append(s)
    # unique keep order
    seen = set()
    uniq = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def pick_first_nonempty(patterns: Iterable[str]) -> str:
    for pattern in patterns:
        for p in sorted(glob.glob(pattern)):
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
    return ""


def find_native_bold(derivatives_dir: str, bids_dir: str, sub: str) -> str:
    candidates = [
        os.path.join(derivatives_dir, sub, "func", "*desc-preproc_bold.nii.gz"),
        os.path.join(derivatives_dir, "fmriprep", sub, "func", "*desc-preproc_bold.nii.gz"),
    ]
    for pattern in candidates:
        for p in sorted(glob.glob(pattern)):
            if "space-MNI152NLin2009cAsym" in p:
                continue
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
    # Fallback to raw/native BOLD in BIDS subject folder
    bids_candidates = [
        os.path.join(bids_dir, sub, "func", "*task-Rest*_bold.nii.gz"),
        os.path.join(bids_dir, sub, "func", "*_bold.nii.gz"),
    ]
    for pattern in bids_candidates:
        for p in sorted(glob.glob(pattern)):
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
    return ""


def find_native_mask(derivatives_dir: str, sub: str) -> str:
    # Prefer native-space BOLD brain masks from derivatives
    return pick_first_nonempty(
        [
            os.path.join(
                derivatives_dir,
                sub,
                "func",
                "*desc-brain_mask.nii.gz",
            ),
            os.path.join(
                derivatives_dir,
                "fmriprep",
                sub,
                "func",
                "*desc-brain_mask.nii.gz",
            ),
        ]
    )


def find_mni_bold(derivatives_dir: str, sub: str) -> str:
    return pick_first_nonempty(
        [
            os.path.join(
                derivatives_dir,
                sub,
                "func",
                "*space-MNI152NLin2009cAsym*desc-preproc_bold.nii.gz",
            ),
            os.path.join(
                derivatives_dir,
                "fmriprep",
                sub,
                "func",
                "*space-MNI152NLin2009cAsym*desc-preproc_bold.nii.gz",
            ),
        ]
    )


def find_t1w(derivatives_dir: str, bids_dir: str, sub: str) -> str:
    preproc = pick_first_nonempty(
        [
            os.path.join(derivatives_dir, sub, "anat", "*desc-preproc_T1w.nii.gz"),
            os.path.join(derivatives_dir, "fmriprep", sub, "anat", "*desc-preproc_T1w.nii.gz"),
        ]
    )
    if preproc:
        return preproc
    # Fallback to raw/native T1w in BIDS subject folder
    return pick_first_nonempty([os.path.join(bids_dir, sub, "anat", "*_T1w.nii.gz")])


def find_confounds(derivatives_dir: str, sub: str) -> str:
    return pick_first_nonempty(
        [
            os.path.join(derivatives_dir, sub, "func", "*desc-confounds_timeseries.tsv"),
            os.path.join(
                derivatives_dir, "fmriprep", sub, "func", "*desc-confounds_timeseries.tsv"
            ),
        ]
    )


def save_t1w_bold_overlay(
    t1w_path: str, native_bold_path: str, native_mask_path: str, out_png: str
) -> None:
    mean_bold = image.mean_img(native_bold_path)
    native_mask = image.load_img(native_mask_path)
    masked_mean_bold = image.math_img(
        "img1 * img2",
        img1=mean_bold,
        img2=native_mask,
    )
    smoothed_bold = image.smooth_img(masked_mean_bold, fwhm=1.5)
    # Registration QA should emphasize boundary alignment, not intensity opacity.
    disp = plotting.plot_anat(
        t1w_path,
        display_mode="ortho",
        cut_coords=None,
        draw_cross=False,
        title="T1w vs mean native-space BOLD",
    )
    disp.add_edges(smoothed_bold, color="r")
    disp.savefig(out_png, dpi=150)
    disp.close()


def save_mni_overlay(mni_bold_path: str, out_png: str, resolution: int) -> None:

    mean_mni = image.mean_img(mni_bold_path)

    template = datasets.load_mni152_template(
        resolution=resolution
    )
    mni_brain_mask = datasets.load_mni152_brain_mask(
        resolution=resolution
    )
    # Align mask grid to mean_mni before voxel-wise multiplication.
    mni_brain_mask = image.resample_to_img(
        mni_brain_mask,
        mean_mni,
        interpolation="nearest",
        force_resample=True,
        copy_header=True,
    )
    masked_mean_mni = image.math_img(
        "img1 * img2",
        img1=mean_mni,
        img2=mni_brain_mask,
    )

    disp = plotting.plot_anat(
        template,
        display_mode="mosaic",
        cut_coords=12,
        draw_cross=False,
        title="MNI template + mean MNI-space BOLD edges",
    )

    # Use masked mean BOLD edges to avoid spurious contours outside the brain.
    disp.add_edges(masked_mean_mni, color="r")

    disp.savefig(out_png,dpi=150)

    disp.close()


def save_native_mean_views(native_bold_path: str, out_ortho_png: str, out_mosaic_png: str) -> None:
    mean_bold = image.mean_img(native_bold_path)
    d1 = plotting.plot_epi(
        mean_bold,
        display_mode="ortho",
        cut_coords=None,
        title="Native-space mean BOLD (ortho)",
    )
    d1.savefig(out_ortho_png, dpi=150)
    d1.close()

    d2 = plotting.plot_epi(
        mean_bold,
        display_mode="z",
        cut_coords=18,
        title="Native-space mean BOLD (mosaic-like z-slices)",
    )
    d2.savefig(out_mosaic_png, dpi=150)
    d2.close()


def save_fd_dvars_global(confounds_tsv: str, out_png: str, sub: str) -> None:
    df = pd.read_csv(confounds_tsv, sep="\t")
    x = np.arange(df.shape[0])
    fd = pd.to_numeric(df.get("framewise_displacement"), errors="coerce")
    std_dvars = pd.to_numeric(df.get("std_dvars"), errors="coerce")
    global_signal = pd.to_numeric(df.get("global_signal"), errors="coerce")

    fig, ax1 = plt.subplots(figsize=(12, 4))
    ax1.set_title(f"{sub} - FD / std DVARS / global signal")
    ax1.set_xlabel("Volume")
    ax1.set_ylabel("FD / std DVARS")
    if fd is not None:
        ax1.plot(x, fd, color="tab:red", lw=1, label="FD")
    if std_dvars is not None:
        ax1.plot(x, std_dvars, color="tab:blue", lw=1, alpha=0.8, label="std DVARS")

    ax2 = ax1.twinx()
    ax2.set_ylabel("global signal")
    if global_signal is not None:
        ax2.plot(x, global_signal, color="tab:green", lw=1, alpha=0.7, label="global signal")

    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    if h1 or h2:
        ax1.legend(h1 + h2, l1 + l2, loc="upper right", frameon=False)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def main() -> None:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(
        description="Generate manual QA plots (Python + Nilearn) for selected subjects."
    )
    parser.add_argument("--derivatives-dir", default=defaults["derivatives_dir"])
    parser.add_argument(
        "--bids-dir",
        default=os.path.dirname(defaults["derivatives_dir"]),
        help="BIDS root (fallback for native/raw anat and func).",
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(defaults["output_dir"], "manualQA"),
        help="Output root; plots saved to output-dir/sub-XXXX/",
    )
    parser.add_argument("--subject-list-file", default="")
    parser.add_argument("--subjects", default="", help='Space-separated, e.g. "sub-AAA sub-BBB"')
    parser.add_argument("--subject", default="")
    parser.add_argument(
        "--mni-template-resolution",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="Resolution (mm) for nilearn MNI template.",
    )
    args = parser.parse_args()

    subjects = collect_subjects(args.subject, args.subjects, args.subject_list_file)
    if not subjects:
        raise SystemExit(
            "No subjects provided. Use --subject / --subjects / --subject-list-file."
        )

    ensure_output_dir(args.output_dir)
    print(f"Derivatives dir: {args.derivatives_dir}")
    print(f"BIDS dir:        {args.bids_dir}")
    print(f"Output dir:      {args.output_dir}")
    print(f"Subjects count:  {len(subjects)}")
    print("----")

    for sub in subjects:
        sub_out = os.path.join(args.output_dir, sub)
        ensure_output_dir(sub_out)
        print(f"[{sub}] processing...")

        native_bold = find_native_bold(args.derivatives_dir, args.bids_dir, sub)
        native_mask = find_native_mask(args.derivatives_dir, sub)
        mni_bold = find_mni_bold(args.derivatives_dir, sub)
        t1w = find_t1w(args.derivatives_dir, args.bids_dir, sub)
        conf = find_confounds(args.derivatives_dir, sub)

        if t1w and native_bold and native_mask:
            save_t1w_bold_overlay(
                t1w,
                native_bold,
                native_mask,
                os.path.join(sub_out, f"{sub}_01_T1w_BOLD_overlay.png"),
            )
        else:
            print("  WARN: missing T1w, native BOLD, or native brain mask; skip 01 overlay.")

        if mni_bold:
            save_mni_overlay(
                mni_bold,
                os.path.join(sub_out, f"{sub}_02_MNI_BOLD_overlay.png"),
                args.mni_template_resolution,
            )
        else:
            print("  WARN: missing MNI-space preproc BOLD; skip 02 overlay.")

        if native_bold:
            save_native_mean_views(
                native_bold,
                os.path.join(sub_out, f"{sub}_03_native_BOLD_mean_ortho.png"),
                os.path.join(sub_out, f"{sub}_03_native_BOLD_mean_mosaic.png"),
            )
        else:
            print("  WARN: missing native BOLD; skip 03 mean views.")

        if conf:
            save_fd_dvars_global(
                conf,
                os.path.join(sub_out, f"{sub}_04_fd_stdDVARS_globalSignal.png"),
                sub,
            )
        else:
            print("  WARN: missing confounds TSV; skip 04 timeseries plot.")

    print(f"Done. Outputs in: {args.output_dir}")


if __name__ == "__main__":
    main()
