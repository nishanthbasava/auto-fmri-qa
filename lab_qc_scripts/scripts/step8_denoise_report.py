#!/usr/bin/env python3
"""STEP 8: single-file HTML review report for the denoised outputs.

Builds one self-contained HTML page from the per-scan QC figures that the
denoising step writes (qc/figures/*.png), ordered so flagged scans (from
step7's qa_denoise_flags.csv) come first with their reasons and metrics.
Thumbnails are embedded as base64 JPEGs, so the single output file can be
copied anywhere and opened in any browser -- the fMRIPrep-report experience,
for the denoise stage.

    python3 step8_denoise_report.py \
        --denoise-dir .../post_fmriprep_denoise \
        --qc-dir      .../output/denoise_qc \
        --out         .../output/denoise_qc/denoise_report.html

Flagged scans embed all three figures (motion_qc, temporal_qc,
temporal_qc_aligned); unflagged scans embed temporal_qc_aligned only, to keep
the file small (~tens of MB for 400 scans). Requires pandas + Pillow
(pip install pillow into the QC venv if missing).
"""
from __future__ import annotations

import argparse
import base64
import glob
import html
import io
import os

import pandas as pd
from PIL import Image

FLAG_W, OTHER_W = 900, 700   # thumbnail widths (px)
JPEG_Q = 62


def thumb_b64(path: str, width: int) -> str:
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_Q)
    return base64.b64encode(buf.getvalue()).decode()


def fmt(v, d=3):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "—"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--denoise-dir", required=True)
    ap.add_argument("--qc-dir", required=True,
                    help="step7 output dir (qa_denoise_metrics.csv / _flags.csv)")
    ap.add_argument("--out", required=True, help="output .html path")
    args = ap.parse_args()

    met = pd.read_csv(os.path.join(args.qc_dir, "qa_denoise_metrics.csv"))
    flags_path = os.path.join(args.qc_dir, "qa_denoise_flags.csv")
    try:
        flags = pd.read_csv(flags_path)
    except Exception:
        flags = pd.DataFrame(columns=["subject", "session", "reasons"])
    freasons = {(r.subject, r.session): r.reasons for r in flags.itertuples()}

    met["flagged"] = met.apply(lambda r: (r["subject"], r["session"]) in freasons, axis=1)
    met = met.sort_values(["flagged", "subject", "session"],
                          ascending=[False, True, True])

    cards = []
    n_missing_figs = 0
    for r in met.itertuples():
        base = os.path.join(args.denoise_dir, r.subject, r.session, "qc", "figures")
        flagged = (r.subject, r.session) in freasons
        kinds = (["motion_qc", "temporal_qc", "temporal_qc_aligned"]
                 if flagged else ["temporal_qc_aligned"])
        imgs = []
        for k in kinds:
            hits = glob.glob(os.path.join(base, k + ".png"))
            if hits:
                w = FLAG_W if flagged else OTHER_W
                imgs.append(f'<figure><figcaption>{k}</figcaption>'
                            f'<img loading="lazy" src="data:image/jpeg;base64,'
                            f'{thumb_b64(hits[0], w)}"></figure>')
            else:
                n_missing_figs += 1
                imgs.append(f'<p class="miss">missing figure: {k}.png</p>')
        reason = (f'<p class="reason">{html.escape(str(freasons[(r.subject, r.session)]))}</p>'
                  if flagged else "")
        metrics = (f'FD-DVARS corr {fmt(getattr(r, "pre_corr_dvars_fd", None), 2)} '
                   f'&rarr; {fmt(getattr(r, "post_corr_dvars_fd", None), 2)} &nbsp;|&nbsp; '
                   f'voxel-FD corr {fmt(getattr(r, "pre_mean_abs_corr_voxel_fd", None))} '
                   f'&rarr; {fmt(getattr(r, "post_mean_abs_corr_voxel_fd", None))} &nbsp;|&nbsp; '
                   f'tSNR {fmt(getattr(r, "pre_tsnr_mean", None), 0)} '
                   f'&rarr; {fmt(getattr(r, "post_tsnr_mean", None), 0)}')
        cards.append(
            f'<section class="{"flag" if flagged else "ok"}">'
            f'<h3>{r.subject} · {r.session}'
            f'{" <span class=badge>FLAGGED</span>" if flagged else ""}</h3>'
            f'{reason}<p class="m">{metrics}</p><div class="figs">{"".join(imgs)}</div>'
            f'</section>')

    n_flag = int(met["flagged"].sum())
    doc = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Denoise QC report</title>
<style>
 body{{font-family:-apple-system,'Segoe UI',sans-serif;margin:0;background:#f5f6f8;color:#1f2937}}
 header{{background:#1f2a44;color:#fff;padding:18px 28px}}
 header h1{{margin:0;font-size:20px}} header p{{margin:6px 0 0;color:#c7cddb;font-size:13px}}
 main{{max-width:1000px;margin:20px auto;padding:0 16px}}
 section{{background:#fff;border:1px solid #dde1e7;border-radius:8px;margin:14px 0;padding:14px 18px}}
 section.flag{{border-left:5px solid #c62828}}
 h3{{margin:0 0 4px;font-size:15px}}
 .badge{{background:#c62828;color:#fff;border-radius:9px;padding:1px 9px;font-size:11px;vertical-align:2px}}
 .reason{{color:#c62828;font-size:12.5px;margin:2px 0}}
 .m{{color:#6b7280;font-size:12px;margin:2px 0 8px}}
 figure{{margin:8px 0}} figcaption{{color:#9ca3af;font-size:11px;margin-bottom:2px}}
 img{{max-width:100%;border:1px solid #e5e7eb;border-radius:4px}}
 .miss{{color:#b45309;font-size:12px}}
</style></head><body>
<header><h1>Post-fMRIPrep denoise QC — visual report</h1>
<p>{len(met)} scans · {n_flag} flagged (shown first, all three figures) ·
unflagged scans show temporal_qc_aligned only · generated by step8_denoise_report.py</p>
</header><main>{"".join(cards)}</main></body></html>"""

    with open(args.out, "w") as f:
        f.write(doc)
    mb = os.path.getsize(args.out) / 1e6
    print(f"wrote {args.out} ({mb:.1f} MB, {len(met)} scans, {n_flag} flagged, "
          f"{n_missing_figs} missing figures)")


if __name__ == "__main__":
    main()
