"""End-to-end over the synthetic cohort: SDK, CLI, lists, and profile -> label."""
import csv
import json
import os

import pytest

import autoqa
from autoqa import cli
from autoqa.lists import write_lists


def test_qc_end_to_end(cohort, tmp_path):
    root, specs = cohort
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    assert len(res.scans) == len(specs)
    assert sum(res.counts.values()) == len(specs)
    assert res.n_subjects == len({s.sub for s in specs})
    state = json.load(open(tmp_path / "run" / "state.json"))
    assert state["criteria"]["version"] == res.criteria["version"]
    assert "metrics" in state["stages"]
    rows = list(csv.DictReader(open(res.csv_path)))
    assert len(rows) == len(specs)


def test_profiles_map_to_expected_labels(cohort, tmp_path):
    root, specs = cohort
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    by = {(s["sub"], s["ses"]): s for s in res.scans}
    for spec in specs:
        s = by[(spec.sub, spec.ses)]
        if spec.profile == "high_motion":
            assert s["status"] == "EXCLUDE" and "mean FD" in s["reasons"][0]
        elif spec.profile == "missing":
            assert s["status"] == "EXCLUDE" and "missing required outputs" in s["reasons"][0]
        elif spec.profile == "clean":
            assert s["status"] == "INCLUDE", (spec, s["metrics"])
        elif spec.profile == "borderline":
            assert any("borderline mean FD" in f for f in s["verify_flags"])
        elif spec.profile == "spiky":
            assert s["status"] in ("CAUTION", "INCLUDE") and s["metrics"]["mean_fd"] < 0.5


def test_sessions_never_pooled(cohort, tmp_path):
    root, specs = cohort
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    multi = {s.sub for s in specs if sum(1 for t in specs if t.sub == s.sub) > 1}
    assert multi, "cohort should contain two-session subjects"
    for sub in multi:
        rows = [s for s in res.scans if s["sub"] == sub]
        assert len(rows) == 2
        assert rows[0]["metrics"]["n_volumes"] > 0 and rows[1]["metrics"]["n_volumes"] > 0


def test_rerun_is_idempotent(cohort, tmp_path):
    root, _ = cohort
    a = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    b = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    assert [s["status"] for s in a.scans] == [s["status"] for s in b.scans]


def test_no_scans_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        autoqa.qc(str(tmp_path), out=str(tmp_path / "run"), quiet=True)


def test_cli_run_and_lists(cohort, tmp_path, capsys):
    root, specs = cohort
    run = tmp_path / "run"
    assert cli.main(["run", "--input", str(root), "--out", str(run)]) == 0
    assert cli.main(["lists", str(run), "-o", str(tmp_path / "lists")]) == 0
    out = capsys.readouterr().out
    assert "discovered" in out and "INCLUDE" in out
    counts = write_lists(str(run), str(tmp_path / "lists2"))
    assert sum(counts.values()) == len(specs)
    for name in ("included_scans.csv", "caution_scans.csv", "excluded_scans.csv"):
        assert os.path.exists(tmp_path / "lists" / name)


def test_cli_errors(capsys):
    assert cli.main(["nope"]) == 2
    assert cli.main(["--version"]) == 0
    assert "autoqa" in capsys.readouterr().out
    assert cli.main(["run", "--input", "/nonexistent", "--out", "/tmp/x"]) == 1


def test_demo_is_deterministic(tmp_path):
    from autoqa import synth
    a = synth.generate(str(tmp_path / "a"), subjects=6, seed=5)
    b = synth.generate(str(tmp_path / "b"), subjects=6, seed=5)
    assert [s.__dict__ for s in a] == [s.__dict__ for s in b]
    fa = open(tmp_path / "a" / a[0].sub / a[0].ses / "func" /
              f"{a[0].sub}_{a[0].ses}_task-rest_desc-confounds_timeseries.tsv").read()
    fb = open(tmp_path / "b" / b[0].sub / b[0].ses / "func" /
              f"{b[0].sub}_{b[0].ses}_task-rest_desc-confounds_timeseries.tsv").read()
    assert fa == fb
    assert json.load(open(tmp_path / "a" / "SYNTHETIC_COHORT.json"))["note"].startswith("synthetic")
