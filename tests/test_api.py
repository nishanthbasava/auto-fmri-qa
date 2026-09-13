"""API tests against a throwaway SQLite database per test.

The app reads its settings at import, so each test configures the environment,
reloads the module, and enters the TestClient context (which runs the lifespan
hook -> migrations)."""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from autoqa.db import session as dbsession  # noqa: E402


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AFQ_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("AFQ_STAGED", str(tmp_path / "staged"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("APP_PASSWORD", "lab-secret")
    dbsession.reset()
    from autoqa.api import main as m
    importlib.reload(m)
    m.STATS.__init__()          # per-test metrics reservoir
    yield m, tmp_path
    dbsession.reset()


def _seed_run(tmp_path, run_id="qc1"):
    d = tmp_path / "runs" / run_id
    d.mkdir(parents=True)
    state = {"created": "2026-09-13T00:00:00", "stages": {"metrics": {}},
             "criteria": {"version": "t"}, "scans": {
                 "sub-001|ses-v01": {"sub": "sub-001", "ses": "ses-v01", "status": "CAUTION",
                                     "reasons": ["outliers 25% > 20%"], "verify_flags": [],
                                     "missing": [], "metrics": {"mean_fd": 0.2, "tr": 3.0}},
                 "sub-002|ses-v01": {"sub": "sub-002", "ses": "ses-v01", "status": "INCLUDE",
                                     "reasons": [], "verify_flags": [], "missing": [],
                                     "metrics": {"mean_fd": 0.1, "tr": 3.0}}}}
    (d / "state.json").write_text(json.dumps(state))
    return run_id


def _users(m):
    from autoqa.api.auth import create_user
    from autoqa.db.session import session
    with session() as db:
        create_user(db, "viv", "viv-pw", "viewer")
        create_user(db, "rae", "rae-pw", "reviewer")
        create_user(db, "adm", "adm-pw", "admin")


def _login(c, user, pw):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_health_and_unauthenticated(app_env):
    m, tmp = app_env
    with TestClient(m.app) as c:
        assert c.get("/api/health").json()["auth"] == "users+jwt"
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/runs", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert "x-request-id" in c.get("/api/health").headers


def test_login_roles_and_audit(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        _users(m)
        assert c.post("/api/auth/login", json={"username": "rae", "password": "wrong"}).status_code == 401
        viv, rae, adm = _login(c, "viv", "viv-pw"), _login(c, "rae", "rae-pw"), _login(c, "adm", "adm-pw")
        assert c.get("/api/auth/me", headers=rae).json() == {"username": "rae", "role": "reviewer"}

        # viewer: read yes, decide no
        assert c.get("/api/runs", headers=viv).status_code == 200
        r = c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision", json={"decision": "drop"}, headers=viv)
        assert r.status_code == 403 and "reviewer" in r.json()["detail"]
        # reviewer: decide yes, launch/audit no
        assert c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision",
                      json={"decision": "drop", "note": "blocky carpet"}, headers=rae).status_code == 200
        assert c.get("/api/audit", headers=rae).status_code == 403
        assert c.post("/api/runs", json={"run_id": "x", "input": "."}, headers=rae).status_code == 403
        # admin: everything, including the audit log
        ev = c.get("/api/audit", headers=adm).json()["events"]
        actions = [e["action"] for e in ev]
        assert "login.failed" in actions and "login" in actions and "decision" in actions
        dec = next(e for e in ev if e["action"] == "decision")
        assert dec["actor"] == "rae" and dec["target"] == "qc1/sub-001|ses-v01"
        assert dec["detail"]["note"] == "blocky carpet" and dec["ip"]
        assert c.get("/api/audit?actor=rae&action=decision", headers=adm).json()["events"][0]["actor"] == "rae"
        users = c.get("/api/users", headers=adm).json()["users"]
        assert {u["username"] for u in users} == {"viv", "rae", "adm"}


def test_decisions_are_append_only_and_overlaid(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        _users(m)
        rae = _login(c, "rae", "rae-pw")
        key = "sub-001|ses-v01"
        r = c.post(f"/api/runs/qc1/scans/{key}/decision", json={"decision": "drop", "note": "n1"}, headers=rae)
        assert r.json()["decision"]["by"] == "rae" and r.json()["decision"]["status_at_decision"] == "CAUTION"
        c.post(f"/api/runs/qc1/scans/{key}/decision", json={"decision": "keep", "note": "n2"}, headers=rae)
        scans = c.get("/api/runs/qc1/scans", headers=rae).json()["scans"]
        by = {s["key"]: s for s in scans}
        assert by[key]["decision"]["decision"] == "keep" and by[key]["status"] == "CAUTION"
        assert by["sub-002|ses-v01"]["decision"] is None
        c.post(f"/api/runs/qc1/scans/{key}/decision", json={"decision": "clear"}, headers=rae)
        assert c.get("/api/runs/qc1/scans", headers=rae).json()["scans"][0]["decision"] is None
        hist = c.get(f"/api/runs/qc1/scans/{key}/history", headers=rae).json()["history"]
        assert [h["decision"] for h in hist] == ["drop", "keep", "clear"]
        assert c.get("/api/runs", headers=rae).json()["runs"][0]["n_decided"] == 0
        assert c.post(f"/api/runs/qc1/scans/{key}/decision", json={"decision": "maybe"}, headers=rae).status_code == 400
        assert c.post("/api/runs/qc1/scans/nope/decision", json={"decision": "keep"}, headers=rae).status_code == 404
        # the journal was never touched by the API
        state = json.load(open(tmp / "runs" / "qc1" / "state.json"))
        assert "decision" not in state["scans"][key]


def test_sync_journal_copies_db_decisions(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        _users(m)
        rae = _login(c, "rae", "rae-pw")
        c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision", json={"decision": "drop"}, headers=rae)
    from autoqa.db.sync import sync_journal
    assert sync_journal(str(tmp / "runs" / "qc1")) == 1
    state = json.load(open(tmp / "runs" / "qc1" / "state.json"))
    assert state["scans"]["sub-001|ses-v01"]["decision"]["decision"] == "drop"
    assert len(state["scans"]["sub-001|ses-v01"]["decision_log"]) == 1


def test_legacy_password_is_admin_but_cannot_decide(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        lab = {"Authorization": "Bearer lab-secret"}
        assert c.get("/api/auth/me", headers=lab).json() == {"username": "lab", "role": "admin"}
        assert c.get("/api/audit", headers=lab).status_code == 200
        r = c.post("/api/runs/qc1/scans/sub-001|ses-v01/decision", json={"decision": "keep"}, headers=lab)
        assert r.status_code == 403


def test_expired_and_deactivated_tokens(app_env, monkeypatch):
    m, tmp = app_env
    with TestClient(m.app) as c:
        _users(m)
        from autoqa.api import auth
        monkeypatch.setattr(auth, "TOKEN_TTL_HOURS", -1)      # already expired
        r = c.post("/api/auth/login", json={"username": "viv", "password": "viv-pw"})
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 401
        monkeypatch.setattr(auth, "TOKEN_TTL_HOURS", 1)
        viv = _login(c, "viv", "viv-pw")
        from sqlalchemy import select

        from autoqa.db.models import User
        from autoqa.db.session import session
        with session() as db:
            db.scalar(select(User).where(User.username == "viv")).active = False
        assert c.get("/api/auth/me", headers=viv).status_code == 401


def test_metrics_endpoint_reports_percentiles(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        _users(m)
        viv = _login(c, "viv", "viv-pw")
        for _ in range(5):
            c.get("/api/runs/qc1/scans", headers=viv)
        text = c.get("/api/metrics", headers=viv).text
        assert 'autoqa_request_latency_ms{route="GET /api/runs/{run_id}/scans",quantile="p50"}' in text
        assert 'autoqa_requests_total{route="GET /api/runs/{run_id}/scans",status="200"} 5' in text
        snap = c.get("/api/metrics.json", headers=viv).json()
        r = snap["routes"]["GET /api/runs/{run_id}/scans"]
        assert r["n"] == 5 and r["p50_ms"] <= r["p95_ms"] <= r["p99_ms"]


def test_path_traversal_rejected(app_env):
    m, tmp = app_env
    _seed_run(tmp)
    with TestClient(m.app) as c:
        lab = {"Authorization": "Bearer lab-secret"}
        assert c.get("/api/runs/..%2F..%2Fetc/scans", headers=lab).status_code in (400, 404)
        assert c.get("/api/runs/qc1/figures/..%2Fstate.json", headers=lab).status_code in (400, 404)
        assert c.post("/api/runs", json={"run_id": "../x", "input": "."}, headers=lab).status_code == 400


def test_password_hashing():
    from autoqa.api.auth import hash_password, verify_password
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$") and "hunter2" not in h
    assert verify_password("hunter2", h) and not verify_password("hunter3", h)
    assert hash_password("hunter2") != h        # salted
