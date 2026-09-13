import random

from autoqa import synth
from autoqa.pipeline import discover


def _spec(sub, ses, tr=3.0, profile="clean"):
    return synth.ScanSpec(sub, ses, profile, tr, 20, "Siemens")


def test_each_session_is_its_own_scan(tmp_path):
    rng = random.Random(0)
    synth.write_scan(str(tmp_path), _spec("sub-001", "ses-v01"), rng)
    synth.write_scan(str(tmp_path), _spec("sub-001", "ses-v02"), rng)
    scans = discover.discover(str(tmp_path))
    assert [(s["sub"], s["ses"]) for s in scans] == [("sub-001", "ses-v01"), ("sub-001", "ses-v02")]
    assert all(not s["missing"] for s in scans)
    assert scans[0]["tr"] == 3.0


def test_subject_level_t1w_figure_is_shared(tmp_path):
    rng = random.Random(0)
    synth.write_scan(str(tmp_path), _spec("sub-002", "ses-v01"), rng, subject_level_t1=True)
    synth.write_scan(str(tmp_path), _spec("sub-002", "ses-v02"), rng, subject_level_t1=True)
    scans = discover.discover(str(tmp_path))
    assert len(scans) == 2
    assert all(s["t1norm_subject_level"] for s in scans)
    assert scans[0]["figures"]["t1norm"] == scans[1]["figures"]["t1norm"]


def test_missing_figure_is_reported(tmp_path):
    synth.write_scan(str(tmp_path), _spec("sub-003", "ses-v01", profile="missing"), random.Random(0))
    (s,) = discover.discover(str(tmp_path))
    assert s["missing"] == ["carpet"] and s["figures"]["carpet"] is None


def test_task_filter(tmp_path):
    synth.write_scan(str(tmp_path), _spec("sub-004", "ses-v01"), random.Random(0))
    assert discover.discover(str(tmp_path), task="nback") == []
