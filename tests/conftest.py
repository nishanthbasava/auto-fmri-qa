"""Shared fixtures. Nothing here touches real data: every tree is synthetic."""
import random

import pytest

from autoqa import synth
from autoqa.criteria import load_criteria


@pytest.fixture(scope="session")
def criteria():
    return load_criteria()


@pytest.fixture(scope="session")
def criteria_dict(criteria):
    return criteria.as_dict()


@pytest.fixture(scope="session")
def cohort(tmp_path_factory):
    """A 40-subject synthetic cohort (session-scoped: generated once)."""
    root = tmp_path_factory.mktemp("cohort")
    specs = synth.generate(str(root), subjects=40, seed=11)
    return root, specs


@pytest.fixture
def scan_writer(tmp_path):
    """Write a single scan with explicit traces; returns the discovered scan dict."""
    from autoqa.pipeline import discover

    def _write(fd, dv, tr=3.0, sub="sub-001", ses="ses-v01", profile="clean"):
        spec = synth.ScanSpec(sub, ses, profile, tr, len(fd), "Siemens")
        rng = random.Random(0)
        # write the tree with synth, then overwrite the traces we care about
        synth.write_scan(str(tmp_path), spec, rng)
        tsv = (tmp_path / sub / ses / "func" / f"{sub}_{ses}_task-rest_desc-confounds_timeseries.tsv")
        with open(tsv, "w") as f:
            f.write("framewise_displacement\tstd_dvars\n")
            for a, b in zip(fd, dv, strict=True):
                f.write(f"{'n/a' if a is None else a}\t{b}\n")
        scans = discover.discover(str(tmp_path))
        return next(s for s in scans if s["sub"] == sub and s["ses"] == ses)

    return _write
