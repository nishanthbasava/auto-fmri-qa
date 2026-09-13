"""Synthetic fMRIPrep-shaped cohort generator.

    autoqa demo --out staged/demo [--subjects 24] [--seed 7]

Produces a derivatives-shaped tree that `autoqa run` accepts, with NO real
imaging data in it: confounds TSVs are simulated motion traces, sidecars carry a
plausible TR/manufacturer, and the figures are minimal SVGs that mimic
fMRIPrep's two-layer reportlet markup (`.background-svg` / `.foreground-svg`)
closely enough to exercise the renderer's template-layer guard.

Used for the test-suite fixtures, the public demo deployment, and for anyone
who wants to try the pipeline without ADNI access. Deterministic for a seed.

Scan profiles (chosen per scan; the mix is controlled by `--profiles`):
    clean        low baseline FD, a couple of small spikes           -> INCLUDE
    spiky        clean baseline but many FD/DVARS spikes             -> CAUTION
    high_motion  sustained FD well above the exclusion mean          -> EXCLUDE
    borderline   mean FD just under the exclusion threshold          -> INCLUDE + VERIFY
    missing      confounds present but the carpet figure is absent   -> EXCLUDE (missing outputs)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from dataclasses import dataclass

PROFILES = ("clean", "spiky", "high_motion", "borderline", "missing")
DEFAULT_MIX = {"clean": 0.70, "spiky": 0.12, "high_motion": 0.08,
               "borderline": 0.06, "missing": 0.04}
VENDORS = {"Siemens": 1.00, "GE": 1.12, "Philips": 1.30}   # std_dvars baseline multiplier
CONFOUND_COLUMNS = ["global_signal", "csf", "white_matter", "dvars", "std_dvars",
                    "framewise_displacement", "trans_x", "trans_y", "trans_z",
                    "rot_x", "rot_y", "rot_z"]


@dataclass
class ScanSpec:
    sub: str
    ses: str
    profile: str
    tr: float
    n_volumes: int
    vendor: str


def _fmt(x):
    return "n/a" if x is None else f"{x:.6f}"


def simulate_traces(spec: ScanSpec, rng: random.Random):
    """Return (fd, std_dvars) lists of length n_volumes; fd[0] is None like fMRIPrep."""
    n, tr = spec.n_volumes, spec.tr
    fast = tr < 1.0
    base = {"clean": 0.14, "spiky": 0.16, "high_motion": 0.75,
            "borderline": 0.47, "missing": 0.14}[spec.profile]
    if fast:
        base *= 0.55                      # per-frame motion shrinks with shorter TR
    spike_p = {"clean": 0.01, "spiky": 0.26, "high_motion": 0.25,
               "borderline": 0.04, "missing": 0.01}[spec.profile]
    spike_lo, spike_hi = {"clean": (0.6, 1.5), "spiky": (0.55, 1.1), "high_motion": (0.8, 2.5),
                          "borderline": (0.55, 0.8), "missing": (0.6, 1.5)}[spec.profile]
    noise = 0.05 if spec.profile == "borderline" else 0.25   # borderline hugs its mean
    fd, dv = [None], []
    x = base
    dv_base = VENDORS[spec.vendor]
    for t in range(n):
        # AR(1) around the profile baseline; respiratory pseudomotion on fast TR
        x = base + 0.7 * (x - base) + rng.gauss(0, base * noise)
        val = max(0.0, x)
        if fast:
            val += 0.06 * (1 + math.sin(2 * math.pi * 0.3 * t * tr))
        spike = rng.random() < spike_p
        if spike:
            val += rng.uniform(spike_lo, spike_hi)
        if t > 0:
            fd.append(val)
        d = dv_base + rng.gauss(0, 0.06) + (rng.uniform(0.6, 1.5) if spike else 0.0)
        dv.append(max(0.5, d))
    if spec.profile == "borderline":
        # force the session mean into the verify band (0.45, 0.5]
        vals = [v for v in fd if v is not None]
        shift = 0.48 - sum(vals) / len(vals)          # additive: keeps spike count intact
        fd = [None] + [max(0.0, v + shift) for v in vals]
    return fd, dv


def _svg(kind: str, seed_text: str, w=1108, h=586) -> str:
    """Minimal fMRIPrep-like reportlet. Registration kinds get the two-layer
    flicker markup; the background carries subject-specific content so renders
    differ across scans (the renderer asserts this)."""
    rng = random.Random(seed_text)
    blobs = "".join(
        f'<ellipse cx="{rng.randint(100, w - 100)}" cy="{rng.randint(80, h - 80)}" '
        f'rx="{rng.randint(20, 90)}" ry="{rng.randint(15, 60)}" fill="#{rng.randint(0x30, 0xC0):02x}'
        f'{rng.randint(0x30, 0xC0):02x}{rng.randint(0x30, 0xC0):02x}"/>' for _ in range(12))
    if kind in ("coreg", "t1norm"):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
                f'<style>.foreground-svg{{animation:flicker 1s infinite;animation-play-state:paused}}</style>'
                f'<g class="background-svg"><rect width="{w}" height="{h}" fill="#000"/>{blobs}'
                f'<text x="20" y="30" fill="#fff" font-size="18">{seed_text}</text></g>'
                f'<g class="foreground-svg"><rect width="{w}" height="{h}" fill="#000"/>'
                f'<ellipse cx="{w // 2}" cy="{h // 2}" rx="300" ry="200" fill="none" stroke="#f00" stroke-width="2"/></g>'
                f'</svg>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
            f'<rect width="{w}" height="{h}" fill="#fff"/>{blobs}'
            f'<text x="20" y="30" fill="#000" font-size="18">carpet {seed_text}</text></svg>')


def write_scan(root: str, spec: ScanSpec, rng: random.Random,
               subject_level_t1: bool = False) -> dict:
    """Write one scan's files under root. Returns the paths written."""
    func = os.path.join(root, spec.sub, spec.ses, "func")
    figs = os.path.join(root, spec.sub, "figures")
    os.makedirs(func, exist_ok=True)
    os.makedirs(figs, exist_ok=True)
    stem = f"{spec.sub}_{spec.ses}_task-rest"
    fd, dv = simulate_traces(spec, rng)
    tsv = os.path.join(func, f"{stem}_desc-confounds_timeseries.tsv")
    with open(tsv, "w") as f:
        f.write("\t".join(CONFOUND_COLUMNS) + "\n")
        for i in range(spec.n_volumes):
            row = [rng.gauss(500, 5), rng.gauss(480, 5), rng.gauss(520, 5),
                   dv[i] * 20, dv[i], fd[i]] + [rng.gauss(0, 0.05) for _ in range(6)]
            f.write("\t".join(_fmt(v) for v in row) + "\n")
    sidecar = os.path.join(func, f"{stem}_desc-preproc_bold.json")
    with open(sidecar, "w") as f:
        json.dump({"RepetitionTime": spec.tr, "Manufacturer": spec.vendor,
                   "TaskName": "rest", "SkullStripped": False}, f, indent=1)
    out = {"confounds": tsv, "sidecar": sidecar, "figures": {}}
    kinds = [("coreg", f"{stem}_desc-coreg_bold.svg"),
             ("carpet", f"{stem}_desc-carpetplot_bold.svg")]
    t1name = (f"{spec.sub}_space-MNI152NLin2009cAsym_T1w.svg" if subject_level_t1
              else f"{spec.sub}_{spec.ses}_space-MNI152NLin2009cAsym_T1w.svg")
    kinds.append(("t1norm", t1name))
    for kind, name in kinds:
        if spec.profile == "missing" and kind == "carpet":
            continue
        p = os.path.join(figs, name)
        if not os.path.exists(p):
            with open(p, "w") as f:
                f.write(_svg(kind, f"{spec.sub} {spec.ses} {kind}"))
        out["figures"][kind] = p
    return out


def generate(out: str, subjects: int = 24, seed: int = 7,
             mix: dict | None = None, two_session_fraction: float = 0.3,
             fast_tr_fraction: float = 0.15) -> list[ScanSpec]:
    """Write a whole cohort. Returns the specs (so tests know expected labels)."""
    rng = random.Random(seed)
    mix = mix or DEFAULT_MIX
    names, weights = zip(*mix.items())
    specs = []
    for i in range(subjects):
        sub = f"sub-{i + 1:03d}S{rng.randint(1000, 9999)}"
        sessions = ["ses-v01", "ses-v02"] if rng.random() < two_session_fraction else ["ses-v01"]
        vendor = rng.choice(list(VENDORS))
        fast = rng.random() < fast_tr_fraction
        tr, n = (0.607, 976) if fast else (3.0, rng.choice([140, 197, 200]))
        subject_level = len(sessions) > 1 and rng.random() < 0.5
        for ses in sessions:
            profile = rng.choices(names, weights)[0]
            spec = ScanSpec(sub, ses, profile, tr, n, vendor)
            write_scan(out, spec, rng, subject_level_t1=subject_level)
            specs.append(spec)
    with open(os.path.join(out, "SYNTHETIC_COHORT.json"), "w") as f:
        json.dump({"seed": seed, "subjects": subjects, "note": "synthetic data; no real participants",
                   "scans": [spec.__dict__ for spec in specs]}, f, indent=1)
    return specs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--subjects", type=int, default=24)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--profiles", default=None,
                    help="comma list like clean=0.7,spiky=0.2,high_motion=0.1")
    args = ap.parse_args(argv)
    mix = None
    if args.profiles:
        mix = {}
        for part in args.profiles.split(","):
            k, v = part.split("=")
            if k not in PROFILES:
                ap.error(f"unknown profile {k!r}; choose from {PROFILES}")
            mix[k] = float(v)
    specs = generate(args.out, subjects=args.subjects, seed=args.seed, mix=mix)
    by = {}
    for s in specs:
        by[s.profile] = by.get(s.profile, 0) + 1
    print(f"wrote {len(specs)} synthetic scans for {args.subjects} subjects -> {args.out}")
    print("profiles:", dict(sorted(by.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
