"""FastAPI backend for auto-fmri-qa.

    autoqa serve   (== uvicorn autoqa.api.main:app --host 0.0.0.0 --port 8000)

Auth: per-user accounts (argon2 passwords, JWT sessions) with three roles --
viewer (read), reviewer (record keep/drop decisions), admin (launch runs, build
decks, read the audit log, manage users). See auth.py. The legacy shared
APP_PASSWORD is still accepted as a bearer token for the built-in admin.

Data: runs/<run>/state.json stays the pipeline's own journal (metrics, labels,
figures, LLM review). Human decisions and the audit trail live in the database
(SQLite by default, Postgres via DATABASE_URL) -- see autoqa.db. The scans
endpoint overlays the latest decision from the DB onto each journal record.

Observability: every request is timed and tagged with X-Request-ID;
GET /api/metrics exposes p50/p95/p99 per route in Prometheus text format.
"""
from __future__ import annotations

import glob
import json
import os
import re
from contextlib import asynccontextmanager

try:  # load .env (APP_PASSWORD, JWT_SECRET, DATABASE_URL, ANTHROPIC_API_KEY)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..criteria import default_path
from ..db import migrate
from ..db.models import DECISIONS, Decision, User
from ..db.session import get_session
from . import audit, jobs
from .auth import Principal, authenticate, create_token, current_user, require_role
from .observability import STATS, TimingMiddleware

REPO = jobs.REPO
RUNS_DIR = os.environ.get("AFQ_RUNS", os.path.join(REPO, "runs"))
STAGED_DIR = os.environ.get("AFQ_STAGED", os.path.join(REPO, "staged"))
CRITERIA = default_path()   # $AFQ_CRITERIA or the packaged autoqa/data/criteria.yaml


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate.upgrade()          # idempotent; the schema is always current when serving
    yield


app = FastAPI(title="auto-fmri-qa", version="1.1", lifespan=lifespan)
app.add_middleware(TimingMiddleware)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # run ids / path segments

viewer = Depends(require_role("viewer"))
reviewer = Depends(require_role("reviewer"))
admin = Depends(require_role("admin"))


def _safe_id(value: str, what: str = "id") -> str:
    if not _ID_RE.match(value or ""):
        raise HTTPException(400, f"invalid {what}")
    return value


def _run_dir(run_id: str) -> str:
    d = os.path.join(RUNS_DIR, _safe_id(run_id, "run id"))
    if not os.path.isdir(d):
        raise HTTPException(404, f"run {run_id} not found")
    return d


def _load_state(run_id: str) -> dict:
    p = os.path.join(_run_dir(run_id), "state.json")
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def _latest_decisions(db: Session, run_id: str) -> dict[str, dict | None]:
    """scan_key -> current decision dict (None after a 'clear')."""
    rows = db.scalars(select(Decision).where(Decision.run_id == run_id)
                      .order_by(Decision.id)).all()
    out: dict[str, dict | None] = {}
    for d in rows:
        out[d.scan_key] = None if d.decision == "clear" else d.as_dict()
    return out


def _summary(run_id: str, state: dict, db: Session) -> dict:
    scans = state.get("scans", {})
    counts: dict = {}
    for s in scans.values():
        counts[s.get("status", "?")] = counts.get(s.get("status", "?"), 0) + 1
    decided = sum(1 for v in _latest_decisions(db, run_id).values() if v)
    return {
        "run_id": run_id,
        "created": state.get("created"),
        "input": state.get("input"),
        "job": jobs.status(run_id),
        "stages": {k: v.get("finished") for k, v in state.get("stages", {}).items()},
        "n_scans": len(scans),
        "counts": counts,
        "n_verify": sum(1 for s in scans.values() if s.get("verify_flags")),
        "n_decided": decided,
        "has_deck": os.path.exists(os.path.join(RUNS_DIR, run_id, "review_deck.pptx")),
    }


# ---------------------------------------------------------------- auth

class LoginBody(BaseModel):
    username: str
    password: str


@app.get("/api/health")
def health():
    return {"ok": True, "auth": "users+jwt",
            "legacy_password": bool(os.environ.get("APP_PASSWORD"))}


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_session)):
    user = authenticate(db, body.username, body.password)
    if not user:
        audit.record(db, body.username, "login.failed", request=request)
        db.commit()   # the failure row must survive the exception that follows
        raise HTTPException(401, "bad username or password")
    audit.record(db, user.username, "login", request=request)
    return {"token": create_token(user),
            "user": {"username": user.username, "role": user.role}}


@app.get("/api/auth/me")
def me(user: Principal = Depends(current_user)):
    return {"username": user.username, "role": user.role}


# ---------------------------------------------------------------- inputs / runs

@app.get("/api/inputs", dependencies=[viewer])
def list_inputs():
    """Staged input folders the launcher can point at (subfolders of staged/)."""
    if not os.path.isdir(STAGED_DIR):
        return {"staged_dir": STAGED_DIR, "inputs": []}
    out = []
    for d in sorted(os.listdir(STAGED_DIR)):
        full = os.path.join(STAGED_DIR, d)
        if os.path.isdir(full):
            out.append({"name": d, "subjects": len(glob.glob(os.path.join(full, "sub-*")))})
    if glob.glob(os.path.join(STAGED_DIR, "sub-*")):
        out.insert(0, {"name": ".", "subjects": len(glob.glob(os.path.join(STAGED_DIR, "sub-*")))})
    return {"staged_dir": STAGED_DIR, "inputs": out}


class LaunchBody(BaseModel):
    run_id: str
    input: str            # subfolder of staged/ (or "." for staged/ itself)
    render: bool = True
    review: bool = False  # agent figure review (needs ANTHROPIC_API_KEY)


@app.post("/api/runs")
def launch_run(body: LaunchBody, request: Request, user: Principal = admin,
               db: Session = Depends(get_session)):
    run_id = _safe_id(body.run_id, "run id")
    if body.input != ".":
        _safe_id(body.input, "input name")
    input_dir = os.path.normpath(os.path.join(STAGED_DIR, body.input))
    if not input_dir.startswith(os.path.abspath(STAGED_DIR)):
        raise HTTPException(400, "input must live under staged/")
    if not glob.glob(os.path.join(input_dir, "sub-*")):
        raise HTTPException(400, f"no sub-* folders under {body.input}")
    run_dir = os.path.join(RUNS_DIR, run_id)
    if os.path.exists(os.path.join(run_dir, "state.json")):
        raise HTTPException(409, f"run {run_id} already exists")
    if not os.path.exists(CRITERIA):
        raise HTTPException(500, f"criteria file not found: {CRITERIA}")
    try:
        jobs.launch(run_id, run_dir, input_dir, CRITERIA,
                    do_render=body.render, do_review=body.review)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    audit.record(db, user.username, "run.launch", run_id,
                 {"input": body.input, "render": body.render, "review": body.review}, request)
    return {"run_id": run_id, "job": jobs.status(run_id)}


@app.get("/api/runs", dependencies=[viewer])
def list_runs(db: Session = Depends(get_session)):
    if not os.path.isdir(RUNS_DIR):
        return {"runs": []}
    out = []
    for d in sorted(os.listdir(RUNS_DIR)):
        if os.path.exists(os.path.join(RUNS_DIR, d, "state.json")):
            out.append(_summary(d, _load_state(d), db))
    return {"runs": out}


@app.get("/api/runs/{run_id}", dependencies=[viewer])
def run_detail(run_id: str, db: Session = Depends(get_session)):
    state = _load_state(run_id)
    return {**_summary(run_id, state, db), "criteria": state.get("criteria")}


@app.get("/api/runs/{run_id}/scans", dependencies=[viewer])
def run_scans(run_id: str, db: Session = Depends(get_session)):
    state = _load_state(run_id)
    decisions = _latest_decisions(db, run_id)
    rows = []
    for key in sorted(state.get("scans", {})):
        s = state["scans"][key]
        m = s.get("metrics", {})
        rows.append({
            "key": key, "sub": s["sub"], "ses": s["ses"],
            "status": s.get("status"), "reasons": s.get("reasons", []),
            "verify_flags": s.get("verify_flags", []),
            "tr": m.get("tr"), "n_volumes": m.get("n_volumes"),
            "mean_fd": m.get("mean_fd"), "max_fd": m.get("max_fd"),
            "outlier_percent": m.get("outlier_percent"),
            "retained_minutes": m.get("retained_minutes"),
            "missing": s.get("missing", []),
            "vendor": s.get("vendor"),
            "review": s.get("review"),                 # agent figure review, if run
            "decision": decisions.get(key),            # latest human decision from the DB
            "figures": {k: os.path.basename(v) if v else None
                        for k, v in s.get("rendered", {}).items()},
        })
    return {"run_id": run_id, "scans": rows}


# ---------------------------------------------------------------- decisions

class DecisionBody(BaseModel):
    decision: str       # "keep" | "drop" | "clear"
    note: str = ""


@app.post("/api/runs/{run_id}/scans/{key}/decision")
def decide(run_id: str, key: str, body: DecisionBody, request: Request,
           user: Principal = reviewer, db: Session = Depends(get_session)):
    if body.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {DECISIONS}")
    state = _load_state(run_id)
    if key not in state.get("scans", {}):
        raise HTTPException(404, f"scan {key} not in run {run_id}")
    if user.id is None:
        raise HTTPException(403, "the legacy shared password cannot record decisions; log in as a user")
    row = Decision(run_id=run_id, scan_key=key, decision=body.decision, note=body.note,
                   status_at_decision=state["scans"][key].get("status"), user_id=user.id)
    db.add(row)
    db.flush()
    db.refresh(row)
    audit.record(db, user.username, "decision", f"{run_id}/{key}",
                 {"decision": body.decision, "note": body.note}, request)
    return {"key": key, "decision": None if body.decision == "clear" else row.as_dict()}


@app.get("/api/runs/{run_id}/scans/{key}/history", dependencies=[viewer])
def decision_history(run_id: str, key: str, db: Session = Depends(get_session)):
    _run_dir(run_id)
    rows = db.scalars(select(Decision).where(Decision.run_id == run_id, Decision.scan_key == key)
                      .order_by(Decision.id)).all()
    return {"key": key, "history": [d.as_dict() for d in rows]}


# ---------------------------------------------------------------- figures / deck / log

@app.get("/api/runs/{run_id}/figures/{name}", dependencies=[viewer])
def figure(run_id: str, name: str):
    if "/" in name or ".." in name or not name.endswith(".jpg"):
        raise HTTPException(400, "bad figure name")
    p = os.path.join(_run_dir(run_id), "figures", name)
    if not os.path.exists(p):
        raise HTTPException(404, "figure not rendered")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/runs/{run_id}/deck", dependencies=[viewer])
def deck(run_id: str):
    p = os.path.join(_run_dir(run_id), "review_deck.pptx")
    if not os.path.exists(p):
        raise HTTPException(404, "deck not built yet (POST /api/runs/{id}/deck)")
    return FileResponse(
        p, filename=f"{run_id}_review_deck.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.post("/api/runs/{run_id}/deck")
def build_deck(run_id: str, request: Request, kind: str = "review", user: Principal = admin,
               db: Session = Depends(get_session)):
    if kind not in ("review", "all"):
        raise HTTPException(400, "kind must be review or all")
    run_dir = _run_dir(run_id)
    if jobs.status(run_id)["phase"] in ("starting", "pipeline", "review", "deck"):
        raise HTTPException(409, "a job is already running for this run")
    jobs.launch_cmd(run_id, run_dir, "deck",
                    jobs.PY + ["report", "deck", run_dir, "--deck", kind])
    audit.record(db, user.username, "deck.build", run_id, {"kind": kind}, request)
    return {"run_id": run_id, "job": jobs.status(run_id)}


@app.get("/api/runs/{run_id}/log", dependencies=[viewer])
def job_log(run_id: str, tail: int = 100):
    p = os.path.join(_run_dir(run_id), "job.log")
    if not os.path.exists(p):
        return {"log": ""}
    with open(p) as f:
        lines = f.readlines()
    return {"log": "".join(lines[-max(1, min(tail, 2000)):])}


# ---------------------------------------------------------------- audit / users / metrics

@app.get("/api/audit", dependencies=[admin])
def audit_log(db: Session = Depends(get_session), run: str | None = None,
              actor: str | None = None, action: str | None = None,
              limit: int = Query(200, ge=1, le=2000)):
    from ..db.models import AuditEvent
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if run:
        q = q.where(AuditEvent.target.like(f"{_safe_id(run, 'run id')}%"))
    if actor:
        q = q.where(AuditEvent.actor == actor)
    if action:
        q = q.where(AuditEvent.action == action)
    return {"events": [e.as_dict() for e in db.scalars(q).all()]}


@app.get("/api/users", dependencies=[admin])
def list_users(db: Session = Depends(get_session)):
    rows = db.scalars(select(User).order_by(User.username)).all()
    return {"users": [{"username": u.username, "role": u.role, "active": u.active} for u in rows]}


@app.get("/api/metrics", dependencies=[viewer])
def metrics():
    return PlainTextResponse(STATS.prometheus(), media_type="text/plain; version=0.0.4")


@app.get("/api/metrics.json", dependencies=[viewer])
def metrics_json():
    return STATS.snapshot()
