"""API smoke tests. The app reads its settings at import, so each test module
configures the environment first and imports afresh."""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AFQ_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("AFQ_STAGED", str(tmp_path / "staged"))
    monkeypatch.setenv("APP_PASSWORD", "lab-secret")
    from autoqa.api import main as m
    importlib.reload(m)
    return m, tmp_path


def _seed_run(m, tmp_path, run_id="qc1"):
    d = tmp_path / "runs" / run_id
    d.mkdir(parents=True)
    state = {"created": "2026-09-13T00:00:00", "stages": {"metrics": {}},
             "criteria": {"version": "t"}, "scans": {
                 "sub-001|ses-v01": {"sub": "sub-001", "ses": "ses-v01", "status": "CAUTION",
                                     "reasons": ["outliers 25% > 20%"], "verify_flags": [],
                                     "missing": [], "metrics": {"mean_fd": 0.2, "tr": 3.0}}}}
    (d / "state.json").write_text(json.dumps(state))
    return run_id


def test_refuses_without_password(tmp_path, monkeypatch):
    # empty string, not delenv: python-dotenv would otherwise re-load the repo's .env
    monkeypatch.setenv("APP_PASSWORD", "")
    monkeypatch.setenv("AFQ_RUNS", str(tmp_path))
    from autoqa.api import main as m
    importlib.reload(m)
    c = TestClient(m.app)
    assert c.get("/api/health").json()["auth_configured"] is False
    assert c.get("/api/runs").status_code == 503


def test_bad_token_is_401(app_env):
    m, _ = app_env
    c = TestClient(m.app)
    assert c.get("/api/runs").status_code == 401
    assert c.get("/api/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_list_and_read_run(app_env):
    m, tmp = app_env
    _seed_run(m, tmp)
    c = TestClient(m.app, headers={"Authorization": "Bearer lab-secret"})
    runs = c.get("/api/runs").json()["runs"]
    assert runs[0]["run_id"] == "qc1" and runs[0]["counts"] == {"CAUTION": 1}
    scans = c.get("/api/runs/qc1/scans").json()["scans"]
    assert scans[0]["key"] == "sub-001|ses-v01" and scans[0]["decision"] is None


def test_decision_appends_audit_log_and_never_touches_status(app_env):
    m, tmp = app_env
    _seed_run(m, tmp)
    c = TestClient(m.app, headers={"Authorization": "Bearer lab-secret"})
    r = c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision",
               json={"decision": "drop", "by": "NB", "note": "blocky carpet"})
    assert r.status_code == 200 and r.json()["decision"]["status_at_decision"] == "CAUTION"
    r = c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision", json={"decision": "clear"})
    assert r.json()["decision"] is None
    state = json.load(open(tmp / "runs" / "qc1" / "state.json"))
    scan = state["scans"]["sub-001|ses-v01"]
    assert scan["status"] == "CAUTION" and len(scan["decision_log"]) == 2
    assert c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision",
                  json={"decision": "maybe"}).status_code == 400


def test_path_traversal_rejected(app_env):
    m, tmp = app_env
    _seed_run(m, tmp)
    c = TestClient(m.app, headers={"Authorization": "Bearer lab-secret"})
    assert c.get("/api/runs/..%2F..%2Fetc/scans").status_code in (400, 404)
    assert c.get("/api/runs/qc1/figures/..%2Fstate.json").status_code in (400, 404)
    assert c.post("/api/runs", json={"run_id": "../x", "input": "."}).status_code == 400
