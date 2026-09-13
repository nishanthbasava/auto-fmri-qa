"""Session-pooling audit: what changes if a subject's sessions are pooled?

    autoqa audit pooling RUN_DIR [--input STAGED_DIR]

The lab's original workflow concatenated every confounds file of a subject
before computing motion metrics (`pd.concat(dfs)` in step2) and then wrote
subject-level include/exclude lists. AutoQA computes metrics per scan. This
audit recomputes every multi-session subject BOTH ways under the run's own
criteria and reports every session whose label differs: the "flips".

Why it matters: pooling averages a clean session with a bad one, so the bad
session can slip under the mean-FD bar (a missed EXCLUDE) while the clean one is
dragged into CAUTION by the other session's spikes (a false CAUTION). Either
way the wrong scans reach the analysis.

Output: RUN_DIR/analysis/pooling_flips.csv and a summary on stdout.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics as st
from collections import defaultdict

from ..pipeline import classify as cls
from ..pipeline import metrics as met
from ..pipeline.state import RunState
from . import resolve_input_path

_RANK = {"INCLUDE": 0, "CAUTION": 1, "EXCLUDE": 2}


def pooled_metrics(scans: list[dict], criteria: dict, state_input, override) -> dict:
    """Metrics over the concatenation of every session's traces (the pooled path)."""
    fd_all, dv_all, trs = [], [], []
    for s in scans:
        if not s.get("confounds"):
            continue
        fd, dv = met.load_traces(resolve_input_path(s["confounds"], state_input, override))
        fd_all += fd
        dv_all += dv
        trs.append(s.get("tr") or 3.0)
    n = len(fd_all)
    fds = [x for x in fd_all if x is not None]
    dvs = [x for x in dv_all if x is not None]
    med_dv = st.median(dvs) if dvs else float("nan")
    tr = st.mean(trs) if trs else 3.0
    fd_thr, dv_thr = met.outlier_thresholds(criteria, tr, med_dv)
    out = sum(1 for f, d in zip(fd_all, dv_all, strict=True)
              if (f is not None and f > fd_thr) or (d is not None and d > dv_thr))
    return {
        "n_volumes": n, "tr": tr,
        "mean_fd": round(st.mean(fds), 4) if fds else None,
        "max_fd": round(max(fds), 4) if fds else None,
        "outlier_percent": round(100.0 * out / n, 2) if n else None,
        "retained_minutes": round((n - out) * tr / 60.0, 2),
        "is_fast_tr": tr < criteria["multiband"]["fast_tr_threshold_s"],
    }


def _direction(per_scan: str, pooled: str) -> str:
    if _RANK[pooled] < _RANK[per_scan]:
        return "pooling hides a problem"        # e.g. an EXCLUDE scan reported as INCLUDE
    return "pooling penalises a clean scan"     # e.g. an INCLUDE scan reported as CAUTION


def audit(run_dir: str, input_override: str | None = None) -> dict:
    state = RunState(run_dir)
    criteria = state.data["criteria"]
    by_sub = defaultdict(list)
    for s in state.scans().values():
        by_sub[s["sub"]].append(s)

    flips, multi = [], 0
    for sub, scans in sorted(by_sub.items()):
        if len(scans) < 2:
            continue
        multi += 1
        pooled_scan = {"sub": sub, "ses": "pooled",
                       "missing": sorted({m for s in scans for m in s.get("missing", [])})}
        pm = pooled_metrics(scans, criteria, state.data.get("input"), input_override)
        pooled = cls.classify(pooled_scan, pm, criteria)["status"]
        for s in sorted(scans, key=lambda x: x["ses"]):
            if s["status"] != pooled:
                flips.append({
                    "subject": sub, "session": s["ses"],
                    "per_scan": s["status"], "pooled": pooled,
                    "direction": _direction(s["status"], pooled),
                    "scan_mean_fd": s["metrics"].get("mean_fd"),
                    "pooled_mean_fd": pm["mean_fd"],
                    "scan_outlier_pct": s["metrics"].get("outlier_percent"),
                    "pooled_outlier_pct": pm["outlier_percent"],
                })

    os.makedirs(os.path.join(run_dir, "analysis"), exist_ok=True)
    out = os.path.join(run_dir, "analysis", "pooling_flips.csv")
    cols = ["subject", "session", "per_scan", "pooled", "direction", "scan_mean_fd",
            "pooled_mean_fd", "scan_outlier_pct", "pooled_outlier_pct"]
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(flips)

    n_scans = len(state.scans())
    n_multi_scans = sum(len(v) for v in by_sub.values() if len(v) > 1)
    dirs = defaultdict(int)
    for fl in flips:
        dirs[fl["direction"]] += 1
    return {
        "n_scans": n_scans, "n_subjects": len(by_sub),
        "n_multi_session_subjects": multi, "n_multi_session_scans": n_multi_scans,
        "n_flips": len(flips),
        "flip_rate_all": round(100 * len(flips) / n_scans, 2) if n_scans else 0,
        "flip_rate_multi": round(100 * len(flips) / n_multi_scans, 2) if n_multi_scans else 0,
        "by_direction": dict(dirs), "csv": out, "flips": flips,
        "criteria_version": criteria.get("version"),
        "outlier_mode": criteria["outlier_definition"]["mode"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--input", default=None, help="re-root the staged tree recorded in state.json")
    args = ap.parse_args(argv)
    r = audit(args.run_dir, args.input)
    print(f"criteria {r['criteria_version']} (outlier mode: {r['outlier_mode']})")
    print(f"{r['n_scans']} scans / {r['n_subjects']} subjects; "
          f"{r['n_multi_session_subjects']} subjects have >1 session ({r['n_multi_session_scans']} scans)")
    print(f"label flips if sessions are pooled: {r['n_flips']} / {r['n_scans']} scans "
          f"({r['flip_rate_all']}% of cohort, {r['flip_rate_multi']}% of multi-session scans)")
    for d, n in sorted(r["by_direction"].items()):
        print(f"  {n:3d}  {d}")
    if r["flips"]:
        print(f"\n{'subject':16s} {'session':9s} {'per-scan':9s} {'pooled':9s} scan mFD  pooled mFD")
        for fl in r["flips"]:
            print(f"{fl['subject']:16s} {fl['session']:9s} {fl['per_scan']:9s} {fl['pooled']:9s} "
                  f"{fl['scan_mean_fd']!s:>8} {fl['pooled_mean_fd']!s:>10}")
    print(f"\nwrote {r['csv']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
