#!/usr/bin/env python3
"""Protocol/vendor QC plots: DVARS time courses + image plots, and multiband
FD scaling analysis.

Run ON the cluster against the fMRIPrep derivatives (needs the bold.json
sidecars for TR and, where present, Manufacturer):

    python3 qc_protocol_plots.py \
        --deriv /panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives \
        --out   /panfs/accrepfs.vampire/data/neurogroup/ADNI/qc_analysis

Needs numpy + matplotlib (pip install --user numpy matplotlib if missing).

Outputs (in --out):
  dvars_timecourses.png   one panel per scanner group: every scan's std_dvars
                          trace as a faint line over minutes, group median in bold
  dvars_image_plots.png   one "carpet of DVARS" per group: scans as rows,
                          time (minutes) as x, std_dvars as color -- vendor
                          offsets and spike structure visible at a glance
  fd_hist_sb_vs_mb.png    per-frame FD histograms, single-band vs multiband,
                          log x, with 0.5 mm, naive TR-scaled 0.10 mm, and the
                          empirical suggestion marked
  fd_scale_factor.png     FD percentile curves SB vs MB with the percentile
                          ratios that motivate the suggested scale factor
  summary.txt             group stats + suggested multiband FD scale factor

Scale-factor logic: the naive factor is TR-based (0.5 mm x TR/3 = 0.10 mm) but
lands in the respiratory pseudomotion band. The empirical alternative asks:
what threshold flags the same *fraction* of multiband frames as 0.5 mm flags in
single-band? That is the SB exceedance quantile mapped onto the MB
distribution, reported alongside percentile ratios (P50/P90/P95/P99).
"""
import argparse
import glob
import json
import os
import re

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FD_SPIKE_SB = 0.5                        # mm, the TR=3s spike threshold

GROUP_COLORS = {"Siemens": "#1f77b4", "GE": "#2ca02c", "Philips": "#9467bd",
                "Multiband": "#d62728", "Unknown": "#7f7f7f"}


def vendor_name(raw):
    r = (raw or "").lower()
    if "siemens" in r:
        return "Siemens"
    if "ge" in r or "general electric" in r:
        return "GE"
    if "philips" in r:
        return "Philips"
    return "Unknown"


def load_scans(deriv, task="rest"):
    scans = []
    pats = [os.path.join(deriv, "sub-*", "ses-*", "func",
                         f"*task-{task}*desc-confounds_timeseries.tsv"),
            os.path.join(deriv, "sub-*", "func",
                         f"*task-{task}*desc-confounds_timeseries.tsv")]
    for tsv in sorted(set(sum((glob.glob(p) for p in pats), []))):
        base = os.path.basename(tsv)
        sub = re.search(r"(sub-[A-Za-z0-9]+)", base).group(1)
        ses_m = re.search(r"(ses-[A-Za-z0-9]+)", base)
        ses = ses_m.group(1) if ses_m else "ses-none"
        tr, vend = None, None
        for j in glob.glob(tsv.replace("_desc-confounds_timeseries.tsv", "*bold.json")):
            try:
                meta = json.load(open(j))
                tr = meta.get("RepetitionTime")
                vend = meta.get("Manufacturer")
                break
            except (OSError, json.JSONDecodeError):
                pass
        if not tr:
            continue
        with open(tsv) as f:
            header = f.readline().rstrip("\n").split("\t")
            try:
                i_fd = header.index("framewise_displacement")
                i_dv = header.index("std_dvars")
            except ValueError:
                continue
            fd, dv = [], []
            for line in f:
                p = line.rstrip("\n").split("\t")
                fd.append(p[i_fd])
                dv.append(p[i_dv])

        def col(vals):
            return np.array([float(v) if v not in ("n/a", "", "NaN") else np.nan
                             for v in vals])
        fd, dv = col(fd), col(dv)
        group = "Multiband" if tr < 1.0 else vendor_name(vend)
        scans.append({"sub": sub, "ses": ses, "tr": tr, "group": group,
                      "fd": fd, "dvars": dv,
                      "minutes": np.arange(len(fd)) * tr / 60.0})
    return scans


def resample(y, minutes, grid):
    ok = ~np.isnan(y)
    if ok.sum() < 2:
        return np.full_like(grid, np.nan)
    out = np.interp(grid, minutes[ok], y[ok])
    out[grid > minutes[-1]] = np.nan
    return out


def plot_timecourses(scans, groups, out):
    fig, axes = plt.subplots(len(groups), 1, figsize=(11, 2.3 * len(groups)),
                             sharex=True, sharey=True)
    axes = np.atleast_1d(axes)
    grid = np.arange(0, 10.01, 1 / 60.0)
    for ax, g in zip(axes, groups):
        rows = []
        for s in [s for s in scans if s["group"] == g]:
            r = resample(s["dvars"], s["minutes"], grid)
            rows.append(r)
            ax.plot(grid, r, lw=0.4, color=GROUP_COLORS[g], alpha=0.12)
        if rows:
            med = np.nanmedian(np.vstack(rows), axis=0)
            ax.plot(grid, med, color="black", lw=1.2, zorder=6, label="group median")
        ax.set_ylabel("std_dvars")
        ax.set_title(f"{g}  (n={sum(1 for s in scans if s['group'] == g)})",
                     loc="left", fontsize=10)
        ax.axhline(1.5, color="#999999", ls="--", lw=0.8)
        ax.legend(loc="upper right", fontsize=8, frameon=False)
        ax.set_ylim(0.5, 3.5)
    axes[-1].set_xlabel("minutes")
    fig.suptitle("Standardized DVARS time courses by scanner group "
                 "(dashed line: absolute 1.5 criterion)", y=0.995)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "dvars_timecourses.png"), dpi=150)
    plt.close(fig)


def plot_image(scans, groups, out):
    fig, axes = plt.subplots(len(groups), 1, figsize=(11, 2.6 * len(groups)),
                             sharex=True)
    axes = np.atleast_1d(axes)
    grid = np.arange(0, 10.01, 1 / 60.0)
    for ax, g in zip(axes, groups):
        gs = sorted([s for s in scans if s["group"] == g],
                    key=lambda s: np.nanmedian(s["dvars"]))
        if not gs:
            ax.set_visible(False)
            continue
        img = np.vstack([resample(s["dvars"], s["minutes"], grid) for s in gs])
        im = ax.imshow(img, aspect="auto", origin="lower", cmap="magma",
                       vmin=0.8, vmax=2.2,
                       extent=[0, grid[-1], 0, len(gs)])
        ax.set_ylabel(f"{g}\n({len(gs)} scans)", fontsize=9)
        fig.colorbar(im, ax=ax, pad=0.01, label="std_dvars")
    axes[-1].set_xlabel("minutes")
    fig.suptitle("DVARS image plots: one row per scan, sorted by median DVARS", y=0.995)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "dvars_image_plots.png"), dpi=150)
    plt.close(fig)


def fd_analysis(scans, out):
    sb = np.concatenate([s["fd"][~np.isnan(s["fd"])] for s in scans if s["group"] != "Multiband"])
    mb_scans = [s for s in scans if s["group"] == "Multiband"]
    if not mb_scans:
        return "no multiband scans found -- FD scaling analysis skipped\n"
    mb = np.concatenate([s["fd"][~np.isnan(s["fd"])] for s in mb_scans])

    # histogram
    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.logspace(np.log10(0.001), np.log10(3.0), 80)
    ax.hist(sb, bins=bins, density=True, alpha=0.55, label=f"single-band (TR 3 s, {len(sb):,} frames)",
            color="#1f77b4")
    ax.hist(mb, bins=bins, density=True, alpha=0.55, label=f"multiband (TR 0.6 s, {len(mb):,} frames)",
            color="#d62728")
    ax.set_xscale("log")
    ax.set_xlabel("framewise displacement (mm, log scale)")
    ax.set_ylabel("density")

    # empirical scale factor: threshold that flags the same frame fraction
    exceed = (sb > FD_SPIKE_SB).mean()
    emp_thr = float(np.quantile(mb, 1 - exceed)) if exceed > 0 else float("nan")
    naive_thr = FD_SPIKE_SB * (np.median([s["tr"] for s in mb_scans]) / 3.0)
    for x, lab, c in [(FD_SPIKE_SB, "0.5 mm (SB threshold)", "#1f77b4"),
                      (naive_thr, f"{naive_thr:.2f} mm naive TR-scaled", "#999999"),
                      (emp_thr, f"{emp_thr:.2f} mm empirical (matched exceedance)", "#d62728")]:
        ax.axvline(x, color=c, ls="--", lw=1.2)
        ax.text(x, ax.get_ylim()[1] * 0.95, " " + lab, rotation=90,
                va="top", fontsize=8, color=c)
    ax.legend(frameon=False)
    ax.set_title("Per-frame FD: single-band vs multiband")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fd_hist_sb_vs_mb.png"), dpi=150)
    plt.close(fig)

    # percentile curves + ratios
    qs = np.linspace(0.5, 0.999, 200)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(qs * 100, np.quantile(sb, qs), label="single-band", color="#1f77b4")
    ax.plot(qs * 100, np.quantile(mb, qs), label="multiband", color="#d62728")
    ax.set_yscale("log")
    ax.set_xlabel("percentile")
    ax.set_ylabel("FD (mm, log)")
    ax.set_title("FD percentile curves -- the SB/MB ratio is the scale factor")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "fd_scale_factor.png"), dpi=150)
    plt.close(fig)

    lines = ["FD scaling analysis: single-band vs multiband\n"]
    lines.append(f"frames: SB {len(sb):,}  MB {len(mb):,}   "
                 f"scans: SB {sum(1 for s in scans if s['group'] != 'Multiband')}  MB {len(mb_scans)}\n")
    for q in (0.50, 0.90, 0.95, 0.99):
        a, b = np.quantile(sb, q), np.quantile(mb, q)
        lines.append(f"P{int(q*100):2d}: SB {a:.4f} mm  MB {b:.4f} mm  ratio {a/b:.2f}x\n")
    lines.append(f"\nSB frames exceeding {FD_SPIKE_SB} mm: {exceed*100:.2f}%\n")
    lines.append(f"naive TR-scaled MB threshold: {naive_thr:.3f} mm\n")
    lines.append(f"empirical MB threshold (same exceedance as SB): {emp_thr:.3f} mm\n")
    lines.append(f"=> suggested scale factor {FD_SPIKE_SB/emp_thr:.1f}x "
                 f"(0.5 mm / {emp_thr:.3f} mm), vs naive {FD_SPIKE_SB/naive_thr:.1f}x\n")
    lines.append("\nCaveat: MB FD includes respiratory pseudomotion; an empirical\n"
                 "threshold matches flag *rates*, not physiology. Notch-filtered\n"
                 "motion parameters remain the principled fix.\n")
    return "".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deriv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", default="rest")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    scans = load_scans(args.deriv, args.task)
    if not scans:
        raise SystemExit("no scans found under --deriv")
    groups = [g for g in ("Siemens", "GE", "Philips", "Unknown", "Multiband")
              if any(s["group"] == g for s in scans)]
    print(f"{len(scans)} scans:",
          {g: sum(1 for s in scans if s['group'] == g) for g in groups})

    plot_timecourses(scans, groups, args.out)
    plot_image(scans, groups, args.out)
    summary = fd_analysis(scans, args.out)
    with open(os.path.join(args.out, "summary.txt"), "w") as f:
        f.write(summary)
    print(summary)
    print(f"plots -> {args.out}")


if __name__ == "__main__":
    main()
