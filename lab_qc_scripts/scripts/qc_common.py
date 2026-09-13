#!/usr/bin/env python3
"""Common helpers for fMRIPrep preprocessing QA scripts."""

from __future__ import annotations

import argparse
import glob
import os
from typing import Dict, List


def build_default_paths() -> Dict[str, str]:
    """Build default derivatives/output paths relative to this package."""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    qc_dir = os.path.dirname(scripts_dir)
    mri_dir = os.path.dirname(qc_dir)
    derivatives_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(mri_dir))),
        "datasets",
        "camcan_bids",
        "cc700",
        "mri_bids",
        "derivatives",
    )
    output_dir = os.path.join(qc_dir, "output")
    return {
        "scripts_dir": scripts_dir,
        "qc_dir": qc_dir,
        "mri_dir": mri_dir,
        "derivatives_dir": derivatives_dir,
        "output_dir": output_dir,
    }


def parse_common_args(description: str) -> argparse.Namespace:
    defaults = build_default_paths()
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--derivatives-dir",
        default=defaults["derivatives_dir"],
        help="Path to fMRIPrep derivatives directory.",
    )
    parser.add_argument(
        "--output-dir",
        default=defaults["output_dir"],
        help="Directory for QA outputs.",
    )
    return parser.parse_args()


def ensure_output_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def list_subjects(derivatives_dir: str) -> List[str]:
    """Detect subjects by derivatives/sub-* directories."""
    subject_paths = sorted(
        p
        for p in glob.glob(os.path.join(derivatives_dir, "sub-*"))
        if os.path.isdir(p)
    )
    return [os.path.basename(p) for p in subject_paths]


def find_subject_files(derivatives_dir: str, subject: str, suffix_pattern: str) -> List[str]:
    """
    Find subject files from either:
    - derivatives/sub-*/...
    - derivatives/fmriprep/sub-*/...
    """
    patterns = [
        os.path.join(derivatives_dir, subject, "**", suffix_pattern),
        os.path.join(derivatives_dir, "fmriprep", subject, "**", suffix_pattern),
    ]
    matches: List[str] = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern, recursive=True))
    return sorted(set(matches))


def is_nonempty_file(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0
