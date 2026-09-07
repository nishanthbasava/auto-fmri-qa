"""Render fMRIPrep QC SVGs to JPEG via headless chromium (playwright).

fMRIPrep registration reportlets are two-layer flicker SVGs: `.background-svg`
holds the subject data, `.foreground-svg` the reference/template and it sits on
top (CSS animation, paused). A naive render therefore shows the TEMPLATE --
identical pixels for every subject. We remove the foreground layer before the
screenshot and afterwards assert that registration renders are unique across
scans (md5), which catches this failure mode if fMRIPrep changes its markup.
"""
import hashlib
import os
import re

from PIL import Image

REG_KINDS = ("coreg", "t1norm")  # layered; carpet renders as-is


def render_run(state, scale: float = 1.5, quality: int = 85):
    from playwright.sync_api import sync_playwright

    out_dir = os.path.join(state.run_dir, "figures")
    os.makedirs(out_dir, exist_ok=True)
    jobs = []  # (svg, out_jpg, is_registration)
    for key, s in state.scans().items():
        for kind, svg in s["figures"].items():
            if not svg:
                continue
            k = "t1norm" if kind.startswith("t1norm") else kind
            name = f"{s['sub']}_{s['ses']}_{k}.jpg"
            out = os.path.join(out_dir, name)
            s.setdefault("rendered", {})[k] = out
            if not os.path.exists(out):
                jobs.append((svg, out, k in REG_KINDS))
    if not jobs:
        state.mark_stage("render", n=0, note="up to date")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for svg, out, is_reg in jobs:
            head = open(svg).read(200000)
            m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', head)
            w, h = (float(m.group(1)), float(m.group(2))) if m else (1108, 586)
            page = browser.new_page(
                viewport={"width": int(w), "height": int(round(h))},
                device_scale_factor=scale)
            page.goto("file://" + os.path.abspath(svg))
            if is_reg:
                page.evaluate(
                    "document.querySelectorAll('.foreground-svg').forEach(e=>e.remove())")
            page.wait_for_timeout(150)
            tmp = out + ".png"
            page.screenshot(path=tmp)
            page.close()
            Image.open(tmp).convert("RGB").save(out, quality=quality)
            os.remove(tmp)
        browser.close()

    # integrity: registration renders must be unique per subject
    seen = {}
    dupes = []
    for key, s in state.scans().items():
        for k in REG_KINDS:
            path = s.get("rendered", {}).get(k)
            if not path or not os.path.exists(path):
                continue
            if k == "t1norm" and s.get("t1norm_subject_level"):
                continue  # legitimately shared across a subject's sessions
            digest = hashlib.md5(open(path, "rb").read()).hexdigest()
            if digest in seen and seen[digest].split("_")[0] != s["sub"]:
                dupes.append((seen[digest], os.path.basename(path)))
            seen[digest] = os.path.basename(path)
    if dupes:
        raise RuntimeError(
            f"identical registration renders across subjects (template-layer bug?): {dupes[:5]}")
    state.mark_stage("render", n=len(jobs))
    print(f"rendered {len(jobs)} figures -> {out_dir}")
