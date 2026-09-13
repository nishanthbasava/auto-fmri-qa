"""Per-scan motion/artifact metrics from the fMRIPrep confounds TSV.

Reads only two columns (framewise_displacement, std_dvars). All statistics are
computed within a single run -- never pooled across sessions of a subject.
"""
import csv
import statistics as st


def load_traces(tsv_path: str):
    fd, dv = [], []
    with open(tsv_path) as f:
        r = csv.reader(f, delimiter="\t")
        hdr = next(r)
        try:
            fi, di = hdr.index("framewise_displacement"), hdr.index("std_dvars")
        except ValueError as e:
            raise ValueError(f"{tsv_path}: missing FD/std_dvars column ({e})")
        for row in r:
            fd.append(_num(row[fi]))
            dv.append(_num(row[di]))
    return fd, dv


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None  # first volume has no FD


def outlier_thresholds(criteria: dict, tr: float, median_dvars: float):
    """Resolve the per-volume spike thresholds for the configured definition."""
    od = criteria["outlier_definition"]
    mode = od["mode"]
    fd_thr = od["fd_spike_mm"]
    if mode == "tr_scaled":
        fd_thr = od["fd_spike_mm"] * (tr / 3.0)
    if mode == "absolute":
        dv_thr = od["dvars_abs"]
    else:  # relative / tr_scaled
        dv_thr = od["dvars_rel_mult"] * median_dvars
    return fd_thr, dv_thr


def scan_metrics(scan: dict, criteria: dict) -> dict:
    fd, dv = load_traces(scan["confounds"])
    n = len(fd)
    fds = [x for x in fd if x is not None]
    dvs = [x for x in dv if x is not None]
    med_dv = st.median(dvs) if dvs else float("nan")
    tr = scan["tr"] or 3.0
    fd_thr, dv_thr = outlier_thresholds(criteria, tr, med_dv)
    out = sum(1 for f, d in zip(fd, dv)
              if (f is not None and f > fd_thr) or (d is not None and d > dv_thr))
    retained_min = (n - out) * tr / 60.0
    return {
        "n_volumes": n,
        "tr": tr,
        "duration_min": round(n * tr / 60.0, 2),
        "mean_fd": round(st.mean(fds), 4) if fds else None,
        "max_fd": round(max(fds), 4) if fds else None,
        "median_std_dvars": round(med_dv, 4),
        "fd_spike_threshold": round(fd_thr, 4),
        "dvars_threshold": round(dv_thr, 4),
        "n_outliers": out,
        "outlier_percent": round(100.0 * out / n, 2) if n else None,
        "retained_minutes": round(retained_min, 2),
        "is_fast_tr": tr < criteria["multiband"]["fast_tr_threshold_s"],
    }
