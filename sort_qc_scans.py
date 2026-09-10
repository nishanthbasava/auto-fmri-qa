#!/usr/bin/env python3
"""Sort fMRIPrep scans into included/caution/excluded folders from QC lists.

Run this ON the cluster (like stage_inputs.py). Reads the three scan-level QC
lists (included_scans.csv, caution_scans.csv, excluded_scans.csv — as produced
by make_lists.py / lists_final) and builds, for every scan, a folder

    <out>/<group>/<subject>/<session>/{func,anat}

pointing at that scan's fMRIPrep outputs. Default mode is symlinks: instant,
zero storage, and downstream tools read through them transparently — but they
are views onto the shared derivatives, so write outputs elsewhere, never back
through the links. Use --mode copy for real duplicates (slow, heavy).

Examples:
    python3 sort_qc_scans.py \
        --deriv /panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives \
        --lists /panfs/accrepfs.vampire/data/neurogroup/ADNI/qc_sorted \
        --out   /panfs/accrepfs.vampire/data/neurogroup/ADNI/qc_sorted

    python3 sort_qc_scans.py --deriv ... --lists ... --out ... --mode copy --no-anat

Idempotent: safe to rerun after list changes; existing links are refreshed.
Scan-level on purpose: multi-session subjects can split across categories
(e.g. one session included, the other excluded), so everything keys on
subject+session, never bare subject IDs.
"""
import argparse
import csv
import os
import shutil
import sys

GROUPS = ("included", "caution", "excluded")


def link_or_copy(src: str, dst: str, mode: str) -> None:
    if mode == "link":
        tmp = dst + ".tmp"
        if os.path.islink(tmp):
            os.remove(tmp)
        os.symlink(src, tmp)
        os.replace(tmp, dst)          # atomic refresh, like ln -sfn
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deriv", required=True, help="fMRIPrep derivatives root (contains sub-*)")
    ap.add_argument("--lists", required=True, help="folder holding <group>_scans.csv")
    ap.add_argument("--out", required=True, help="output root (qc_sorted)")
    ap.add_argument("--mode", choices=["link", "copy"], default="link",
                    help="symlink (default) or copy the data")
    ap.add_argument("--no-anat", action="store_true", help="only link/copy func/")
    args = ap.parse_args()

    deriv = os.path.abspath(args.deriv)
    if not os.path.isdir(deriv):
        print(f"derivatives root not found: {deriv}", file=sys.stderr)
        return 1

    missing = []
    for grp in GROUPS:
        list_path = os.path.join(args.lists, f"{grp}_scans.csv")
        if not os.path.exists(list_path):
            print(f"list not found, skipping group: {list_path}", file=sys.stderr)
            continue
        n = 0
        with open(list_path) as f:
            for row in csv.DictReader(f):
                sub, ses = row["subject"], row["session"]
                src_func = os.path.join(deriv, sub, ses, "func")
                dst = os.path.join(args.out, grp, sub, ses)
                if not os.path.isdir(src_func):
                    missing.append((grp, sub, ses))
                    continue
                os.makedirs(dst, exist_ok=True)
                link_or_copy(src_func, os.path.join(dst, "func"), args.mode)
                if not args.no_anat:
                    # anat can be session-level or subject-level in fMRIPrep output
                    for cand in (os.path.join(deriv, sub, ses, "anat"),
                                 os.path.join(deriv, sub, "anat")):
                        if os.path.isdir(cand):
                            link_or_copy(cand, os.path.join(dst, "anat"), args.mode)
                            break
                n += 1
        print(f"{grp:9s} {n:4d} scans -> {os.path.join(args.out, grp)}")

    if missing:
        log = os.path.join(args.out, "missing.log")
        with open(log, "w") as f:
            for grp, sub, ses in missing:
                f.write(f"{grp}\t{sub}\t{ses}\n")
        print(f"WARNING: {len(missing)} scans had no func/ in derivatives -> {log}",
              file=sys.stderr)
        return 1
    print("no missing scans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
