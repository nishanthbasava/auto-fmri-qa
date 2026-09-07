"""Find scans in a derivatives-shaped tree and validate completeness.

A scan = one (subject, session, task) resting-state run. Metrics are ALWAYS
per scan -- sessions of the same subject are never pooled (see docs).
"""
import glob
import json
import os
import re


FIGURE_KINDS = {
    "coreg": "*desc-coreg_bold.svg",
    "carpet": "*desc-carpetplot_bold.svg",
    "t1norm_ses": "*space-MNI*_T1w.svg",   # session-tagged when present
}


def _entity(name: str, key: str):
    m = re.search(rf"({key}-[A-Za-z0-9]+)", name)
    return m.group(1) if m else None


def discover(input_dir: str, task: str = "rest"):
    """Return a list of scan dicts with paths to confounds, sidecar and figures."""
    scans = []
    pats = [
        os.path.join(input_dir, "sub-*", "ses-*", "func",
                     f"*task-{task}*desc-confounds_timeseries.tsv"),
        os.path.join(input_dir, "sub-*", "func",
                     f"*task-{task}*desc-confounds_timeseries.tsv"),
    ]
    for tsv in sorted(set(sum((glob.glob(p) for p in pats), []))):
        base = os.path.basename(tsv)
        sub, ses = _entity(base, "sub"), _entity(base, "ses") or "ses-none"
        subj_dir = os.path.join(input_dir, sub)
        tr = None
        for j in glob.glob(tsv.replace("_desc-confounds_timeseries.tsv", "*bold.json")):
            try:
                tr = json.load(open(j)).get("RepetitionTime")
                break
            except (OSError, json.JSONDecodeError):
                pass
        figdir = os.path.join(subj_dir, "figures")
        sespat = f"{sub}_{ses}_" if ses != "ses-none" else f"{sub}_"

        def fig(patt, allow_subject_level=False):
            # session-tagged first (e.g. sub-X_ses-Y_task-rest_desc-coreg_bold.svg)
            hits = glob.glob(os.path.join(figdir, sespat + patt))
            if not hits and allow_subject_level:
                # anatomical figures may be subject-level (single anat across sessions)
                hits = [h for h in glob.glob(os.path.join(figdir, f"{sub}_" + patt))
                        if "ses-" not in os.path.basename(h)]
            return hits[0] if hits else None

        coreg = fig(FIGURE_KINDS["coreg"])
        carpet = fig(FIGURE_KINDS["carpet"])
        t1norm = fig(FIGURE_KINDS["t1norm_ses"], allow_subject_level=True)
        missing = [k for k, v in
                   {"confounds": tsv, "TR": tr, "coreg": coreg,
                    "carpet": carpet, "t1norm": t1norm}.items() if not v]
        scans.append({
            "sub": sub, "ses": ses, "tr": tr, "confounds": tsv,
            "figures": {"coreg": coreg, "carpet": carpet, "t1norm": t1norm},
            "t1norm_subject_level": bool(t1norm and "ses-" not in os.path.basename(t1norm)),
            "missing": missing,
        })
    return scans
