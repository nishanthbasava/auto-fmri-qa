#!/usr/bin/env python3
"""Step 5 sub-step: generate manual QA plots with Python + Nilearn.

Plot IDs (default: 02,04 only):
  01) T1w/native-BOLD registration QA (masked mean BOLD edges on T1w)
  02) MNI-space EPI-to-MNI QA (masked mean MNI BOLD edges on MNI template, no title)
  03) Native-space mean BOLD views
  04) FD / std DVARS / global signal stacked plot (no FD threshold line)

Notes:
  - The MNI QA intentionally uses edge overlays, not raw intensity contours.
  - Masks are resampled to the corresponding BOLD mean image before masking.
  - If no native-space mask is found, a simple EPI mask is estimated as fallback.
"""

from __future__ import annotations

import argparse
import glob
import os
from typing import Iterable, List, Optional

import matplotlib

# Safe for headless cluster jobs.
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from nilearn import datasets, image, masking, plotting

from qc_common import build_default_paths, ensure_output_dir


plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["savefig.bbox"] = "tight"


def normalize_subject(raw: str) -> str:
    s = raw.strip().split("#", 1)[0].strip()
    if not s:
        return ""
    if not s.startswith("sub-"):
        s = f"sub-{s}"
    return s


def collect_subjects(subject: str, subjects: str, subject_list_file: str) -> List[str]:
    out: List[str] = []

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

    # Unique while preserving order.
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
    """Find native/non-standard-space preprocessed BOLD.

    If no native fMRIPrep BOLD is available, fall back to raw BIDS BOLD.
    This fallback is useful for visualizing native mean signal, but the T1w-BOLD
    overlay should be interpreted cautiously if raw BOLD is used.
    """
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

    # Fallback to raw/native BOLD in BIDS subject folder.
    bids_candidates = [
        os.path.join(bids_dir, sub, "func", "*task-Rest*_bold.nii.gz"),
        os.path.join(bids_dir, sub, "func", "*_bold.nii.gz"),
    ]
    return pick_first_nonempty(bids_candidates)


def find_native_mask(derivatives_dir: str, sub: str) -> str:
    """Find native-space BOLD brain mask.

    Excludes standard-space masks, because these may have a different grid and
    should not be used as native masks.
    """
    candidates = [
        os.path.join(derivatives_dir, sub, "func", "*desc-brain_mask.nii.gz"),
        os.path.join(derivatives_dir, "fmriprep", sub, "func", "*desc-brain_mask.nii.gz"),
    ]
    for pattern in candidates:
        for p in sorted(glob.glob(pattern)):
            if "space-MNI152NLin2009cAsym" in p:
                continue
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
    return ""


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

    # Fallback to raw/native T1w in BIDS subject folder.
    return pick_first_nonempty([os.path.join(bids_dir, sub, "anat", "*_T1w.nii.gz")])


def find_confounds(derivatives_dir: str, sub: str) -> str:
    return pick_first_nonempty(
        [
            os.path.join(derivatives_dir, sub, "func", "*desc-confounds_timeseries.tsv"),
            os.path.join(derivatives_dir, "fmriprep", sub, "func", "*desc-confounds_timeseries.tsv"),
        ]
    )


def _resample_mask_to_img(mask_img, target_img):
    """Nearest-neighbor resampling of a mask to a target image grid."""
    return image.resample_to_img(
        mask_img,
        target_img,
        interpolation="nearest",
        force_resample=True,
        copy_header=True,
    )


def _mask_and_smooth(mean_img, mask_img=None, fwhm: Optional[float] = 1.5):
    """Suppress outside-brain edges while preserving within-brain structure."""
    if mask_img is None:
        mask_img = masking.compute_epi_mask(mean_img)

    mask_img = _resample_mask_to_img(mask_img, mean_img)
    masked = image.math_img("img * (mask > 0.5)", img=mean_img, mask=mask_img)

    if fwhm is not None and fwhm > 0:
        return image.smooth_img(masked, fwhm=fwhm)
    return masked


def save_t1w_bold_overlay(
    t1w_path: str,
    native_bold_path: str,
    native_mask_path: str,
    out_png: str,
) -> None:
    mean_bold = image.mean_img(native_bold_path)

    native_mask = image.load_img(native_mask_path) if native_mask_path else None
    masked_mean_bold = _mask_and_smooth(mean_bold, native_mask, fwhm=1.5)

    disp = plotting.plot_anat(
        t1w_path,
        display_mode="ortho",
        cut_coords=None,
        draw_cross=False,
        colorbar=False,
        title="T1w + masked mean native-space BOLD edges",
    )
    disp.add_edges(masked_mean_bold, color="r")
    disp.savefig(out_png, dpi=150)
    disp.close()


def save_mni_overlay(mni_bold_path: str, out_png: str, resolution: int, n_cuts: int) -> None:
    """Plot EPI-to-MNI QA: MNI template background + masked MNI BOLD edges."""
    mean_mni = image.mean_img(mni_bold_path)

    template = datasets.load_mni152_template(resolution=resolution)
    mni_brain_mask = datasets.load_mni152_brain_mask(resolution=resolution)

    # The template mask and fMRIPrep BOLD may share template name but not image grid.
    # Always resample before voxel-wise masking.
    masked_mean_mni = _mask_and_smooth(mean_mni, mni_brain_mask, fwhm=1.5)

    disp = plotting.plot_anat(
        template,
        display_mode="mosaic",
        cut_coords=n_cuts,
        draw_cross=False,
        colorbar=False,
        title="",
    )
    disp.add_edges(masked_mean_mni, color="r")
    disp.savefig(out_png, dpi=150)
    disp.close()


def save_native_mean_views(native_bold_path: str, out_ortho_png: str, out_mosaic_png: str) -> None:
    mean_bold = image.mean_img(native_bold_path)

    d1 = plotting.plot_epi(
        mean_bold,
        display_mode="ortho",
        cut_coords=None,
        draw_cross=False,
        colorbar=False,
        title="Native-space mean BOLD (ortho)",
    )
    d1.savefig(out_ortho_png, dpi=150)
    d1.close()

    d2 = plotting.plot_epi(
        mean_bold,
        display_mode="mosaic",
        cut_coords=10,
        draw_cross=False,
        colorbar=False,
        title="Native-space mean BOLD (mosaic)",
    )
    d2.savefig(out_mosaic_png, dpi=150)
    d2.close()


def _numeric_column(df: pd.DataFrame, name: str) -> Optional[pd.Series]:
    if name not in df.columns:
        return None
    return pd.to_numeric(df[name], errors="coerce")


def save_fd_dvars_global(confounds_tsv: str, out_png: str, sub: str) -> None:
    df = pd.read_csv(confounds_tsv, sep="\t")
    x = np.arange(df.shape[0])

    series = [
        ("FD", _numeric_column(df, "framewise_displacement"), None),
        ("std DVARS", _numeric_column(df, "std_dvars"), None),
        ("Global signal", _numeric_column(df, "global_signal"), None),
    ]
    series = [(name, values, threshold) for name, values, threshold in series if values is not None]

    if not series:
        print(f"  WARN: no FD/DVARS/global_signal columns found in {confounds_tsv}")
        return

    fig, axes = plt.subplots(len(series), 1, figsize=(12, 2.2 * len(series)), sharex=True)
    if len(series) == 1:
        axes = [axes]

    fig.suptitle(f"{sub} - Motion and signal QA", fontsize=14)

    for ax, (name, values, threshold) in zip(axes, series):
        ax.plot(x, values.fillna(0), lw=1)
        if threshold is not None:
            ax.axhline(threshold, linestyle="--", color="black", alpha=0.5, lw=1)
        ax.set_ylabel(name)
        ax.grid(alpha=0.2)

    axes[-1].set_xlabel("Volume")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
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
        help="BIDS root; used as fallback for raw/native anat and func.",
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
        help="Resolution (mm) for Nilearn MNI template.",
    )
    parser.add_argument(
        "--mni-n-cuts",
        type=int,
        default=10,
        help="Number of cuts for the MNI mosaic QA figure.",
    )
    parser.add_argument(
        "--plots",
        default="02,04",
        help="Comma-separated plot IDs: 01,02,03,04. Default: 02,04 only.",
    )

    args = parser.parse_args()
    plot_set = {p.strip() for p in args.plots.split(",") if p.strip()}

    subjects = collect_subjects(args.subject, args.subjects, args.subject_list_file)
    if not subjects:
        raise SystemExit("No subjects provided. Use --subject / --subjects / --subject-list-file.")

    ensure_output_dir(args.output_dir)
    print(f"Derivatives dir: {args.derivatives_dir}")
    print(f"BIDS dir:        {args.bids_dir}")
    print(f"Output dir:      {args.output_dir}")
    print(f"Subjects count:  {len(subjects)}")
    print(f"Plots:           {','.join(sorted(plot_set))}")
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

        if "01" in plot_set:
            if t1w and native_bold:
                if not native_mask:
                    print("  WARN: native brain mask not found; estimating an EPI mask for 01 overlay.")
                save_t1w_bold_overlay(
                    t1w,
                    native_bold,
                    native_mask,
                    os.path.join(sub_out, f"{sub}_01_T1w_BOLD_overlay.png"),
                )
            else:
                print("  WARN: missing T1w or native BOLD; skip 01 overlay.")

        if "02" in plot_set:
            if mni_bold:
                save_mni_overlay(
                    mni_bold,
                    os.path.join(sub_out, f"{sub}_02_MNI_BOLD_overlay.png"),
                    args.mni_template_resolution,
                    args.mni_n_cuts,
                )
            else:
                print("  WARN: missing MNI-space preproc BOLD; skip 02 overlay.")

        if "03" in plot_set:
            if native_bold:
                save_native_mean_views(
                    native_bold,
                    os.path.join(sub_out, f"{sub}_03_native_BOLD_mean_ortho.png"),
                    os.path.join(sub_out, f"{sub}_03_native_BOLD_mean_mosaic.png"),
                )
            else:
                print("  WARN: missing native BOLD; skip 03 mean views.")

        if "04" in plot_set:
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
