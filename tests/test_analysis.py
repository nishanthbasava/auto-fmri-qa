"""Audits over constructed cohorts whose expected numbers are known by design."""
import json
import random

import autoqa
from autoqa import synth
from autoqa.analysis import pooling_audit, resolve_input_path, surface


def _two_session_subject(root, sub, p1, p2, rng):
    synth.write_scan(str(root), synth.ScanSpec(sub, "ses-v01", p1, 3.0, 150, "Siemens"), rng)
    synth.write_scan(str(root), synth.ScanSpec(sub, "ses-v02", p2, 3.0, 150, "Siemens"), rng)


def test_pooling_flips_a_clean_plus_bad_subject(tmp_path):
    root = tmp_path / "cohort"
    rng = random.Random(1)
    _two_session_subject(root, "sub-001", "clean", "high_motion", rng)   # pooled mean ~0.45-0.6
    _two_session_subject(root, "sub-002", "clean", "clean", rng)         # no flip
    synth.write_scan(str(root), synth.ScanSpec("sub-003", "ses-v01", "high_motion", 3.0, 150, "GE"), rng)
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    by = {(s["sub"], s["ses"]): s["status"] for s in res.scans}
    assert by[("sub-001", "ses-v01")] == "INCLUDE" and by[("sub-001", "ses-v02")] == "EXCLUDE"

    r = pooling_audit.audit(str(tmp_path / "run"))
    assert r["n_multi_session_subjects"] == 2 and r["n_multi_session_scans"] == 4
    # pooling sub-001 gives one label to both sessions, so at least one of them flips;
    # sub-002 (clean+clean) and the single-session sub-003 never appear
    flipped = {(f["subject"], f["session"]) for f in r["flips"]}
    assert flipped and all(s == "sub-001" for s, _ in flipped)
    assert r["n_flips"] == len(flipped)
    dirs = {f["direction"] for f in r["flips"]}
    assert dirs <= {"pooling hides a problem", "pooling penalises a clean scan"}
    rows = open(tmp_path / "run" / "analysis" / "pooling_flips.csv").read().splitlines()
    assert len(rows) == 1 + r["n_flips"]


def test_pooling_audit_with_no_multi_session_subjects(cohort, tmp_path):
    root, _ = cohort
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    r = pooling_audit.audit(str(tmp_path / "run"))
    assert r["n_scans"] == len(res.scans)
    assert 0 <= r["flip_rate_all"] <= 100
    # every flip must involve a subject with two sessions
    subs = {s["sub"] for s in res.scans}
    assert all(f["subject"] in subs for f in r["flips"])


def test_resolve_input_path_reroots_moved_trees(tmp_path):
    (tmp_path / "new" / "sub-001").mkdir(parents=True)
    (tmp_path / "new" / "sub-001" / "x.tsv").write_text("")
    old_abs = "/cluster/derivatives/sub-001/x.tsv"
    assert resolve_input_path(old_abs, "/cluster/derivatives", str(tmp_path / "new")).endswith("new/sub-001/x.tsv")
    rel = "staged/new/sub-001/x.tsv"
    assert resolve_input_path(rel, None, str(tmp_path / "new")).endswith("new/sub-001/x.tsv")
    try:
        resolve_input_path("/nowhere/x.tsv", None, None)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass


def test_surface_counts_and_misses(cohort, tmp_path):
    root, _ = cohort
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    r = surface.surface(str(tmp_path / "run"))
    n = r["n_scans"]
    assert r["surface_strict"] == r["exclude"] + r["caution"] + r["verify_only"] + r["llm_flagged"]
    assert r["surface_triage"] == r["surface_strict"] - r["exclude"]
    assert r["reduction_triage_pct"] >= r["reduction_strict_pct"]
    assert r["n_decided"] == 0 and r["misses"] == 0

    # simulate a reviewer dropping a clean INCLUDE and keeping a CAUTION
    state_path = tmp_path / "run" / "state.json"
    state = json.load(open(state_path))
    clean, clean2 = [k for k, s in state["scans"].items()
                     if s["status"] == "INCLUDE" and not s["verify_flags"]][:2]
    caut = next(k for k, s in state["scans"].items() if s["status"] == "CAUTION")
    # what review_figures.py writes for a bad rating: the review AND a verify flag;
    # the reviewer then drops it -- surfaced by the LLM, so a catch, not a miss
    state["scans"][clean]["review"] = {"rating": "bad", "panel": "coreg", "note": "truncated FOV"}
    state["scans"][clean]["verify_flags"].append("visual review (bad): truncated FOV")
    state["scans"][clean]["decision"] = {"decision": "drop", "by": "NB"}
    state["scans"][clean2]["decision"] = {"decision": "drop", "by": "NB"}   # a true miss
    state["scans"][caut]["decision"] = {"decision": "keep", "by": "NB"}     # a false alarm
    json.dump(state, open(state_path, "w"))
    r2 = surface.surface(str(tmp_path / "run"))
    assert r2["n_decided"] == 3 and r2["misses"] == 1 and r2["false_alarms"] == 1
    # the LLM catch is attributed to the llm bucket, not lumped into INCLUDE+VERIFY
    assert r2["llm_flagged"] == 1 and r2["surface_strict"] == r["surface_strict"] + 1
    assert r2["verify_only"] == r["verify_only"]
    assert (tmp_path / "run" / "analysis" / "review_surface.json").exists()
    assert n == len(res.scans)


def test_cli_audit(cohort, tmp_path, capsys):
    from autoqa import cli
    root, _ = cohort
    run = str(tmp_path / "run")
    autoqa.qc(str(root), out=run, quiet=True)
    assert cli.main(["audit", "pooling", run]) == 0
    assert cli.main(["audit", "surface", run]) == 0
    out = capsys.readouterr().out
    assert "label flips if sessions are pooled" in out and "review surface, triage" in out
    assert cli.main(["audit", "nope", run]) == 2
