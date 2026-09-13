#!/usr/bin/env python3
"""Stage the light QC subset out of an fMRIPrep derivatives tree.

Run this ON the cluster. Copies only what QC needs -- confounds TSVs, BOLD JSON
sidecars, and the figures/ SVGs -- into an output folder that mirrors the
derivatives layout. NIfTIs are never touched (~MBs per subject instead of GBs).

    python stage_inputs.py /path/to/derivatives -o staged/ [--task rest]

The output folder is a valid --input for pipeline.run.
"""
import argparse
import glob
import os
import shutil
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("derivatives", help="fMRIPrep derivatives root")
    ap.add_argument("-o", "--out", required=True, help="output folder for the staged subset")
    ap.add_argument("--task", default=None, help="only stage this task (e.g. rest)")
    args = ap.parse_args()

    root = os.path.abspath(args.derivatives)
    out = os.path.abspath(args.out)
    task = f"*task-{args.task}*" if args.task else "*"

    patterns = [
        f"sub-*/ses-*/func/{task}desc-confounds_timeseries.tsv",
        f"sub-*/func/{task}desc-confounds_timeseries.tsv",
        f"sub-*/ses-*/func/{task}bold.json",
        f"sub-*/func/{task}bold.json",
        "sub-*/figures/*.svg",
        "sub-*/ses-*/figures/*.svg",
    ]
    n = 0
    for pat in patterns:
        for src in glob.glob(os.path.join(root, pat)):
            rel = os.path.relpath(src, root)
            dst = os.path.join(out, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                n += 1
    subjects = len(glob.glob(os.path.join(out, "sub-*")))
    print(f"staged {n} files for {subjects} subjects -> {out}")
    if subjects == 0:
        print("WARNING: nothing found. Is this the right derivatives root? "
              "(fMRIPrep output may sit one level deeper, e.g. derivatives/fmriprep)",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
