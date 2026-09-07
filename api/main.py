"""FastAPI backend for auto-fmri-qa.

    uvicorn api.main:app --host 0.0.0.0 --port 8000     (from the repo root)

Auth: shared lab password. Set APP_PASSWORD in .env; every request must send
    Authorization: Bearer <APP_PASSWORD>
If APP_PASSWORD is unset the API refuses to start (fail closed -- ADNI data).

Everything is journal-driven: the API never computes QC itself. It launches the
existing CLI stages as background jobs (api.jobs) and reads runs/<run>/state.json
for progress, scans, and figures. Human keep/drop decisions are appended to the
journal with who/when -- the pipeline's own status fields are never overwritten.
"""
import glob
import json
import os
import re
import time

try:  # load .env (APP_PASSWORD, ANTHROPIC_API_KEY) before reading env vars
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import jobs

REPO = jobs.REPO
RUNS_DIR = os.environ.get("AFQ_RUNS", os.path.join(REPO, "runs"))
STAGED_DIR = os.environ.get("AFQ_STAGED", os.path.join(REPO, "staged"))
APP_PASSWORD = os.environ.get("APP_PASSWORD")

app = FastAPI(title="auto-fmri-qa", version="1.0")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # run ids / path segments


def _check_auth(request: Request) -> None:
    if not APP_PASSWORD:
        raise HTTPException(503, "APP_PASSWORD is not set; refusing all requests")
    header = request.headers.get("authorization", "")
    if header != f"Bearer {APP_PASSWORD}":
        raise HTTPException(401, "bad or missing bearer token")


auth = Depends(_check_auth)


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


def _save_state(run_id: str, data: dict) -> None:
    p = os.path.join(_run_dir(run_id), "state.json")
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, p)


def _summary(run_id: str, state: dict) -> dict:
    scans = state.get("scans", {})
    counts: dict = {}
    for s in scans.values():
        counts[s.get("status", "?")] = counts.get(s.get("status", "?"), 0) + 1
    return {
        "run_id": run_id,
        "created": state.get("created"),
        "input": state.get("input"),
        "job": jobs.status(run_id),
        "stages": {k: v.get("finished") for k, v in state.get("stages", {}).items()},
        "n_scans": len(scans),
        "counts": counts,
        "n_verify": sum(1 for s in scans.values() if s.get("verify_flags")),
        "n_decided": sum(1 for s in scans.values() if s.get("decision")),
        "has_deck": os.path.exists(os.path.join(RUNS_DIR, run_id, "review_deck.pptx")),
    }


# ---------------------------------------------------------------- endpoints

@app.get("/api/health")
def health():
    return {"ok": True, "auth_configured": bool(APP_PASSWORD)}


@app.get("/api/inputs", dependencies=[auth])
def list_inputs():
    """Staged input folders the launcher can point at (subfolders of staged/)."""
    if not os.path.isdir(STAGED_DIR):
        return {"staged_dir": STAGED_DIR, "inputs": []}
    out = []
    for d in sorted(os.listdir(STAGED_DIR)):
        full = os.path.join(STAGED_DIR, d)
        if os.path.isdir(full):
            out.append({"name": d,
                        "subjects": len(glob.glob(os.path.join(full, "sub-*")))})
    # staged/ itself may directly be a derivatives tree
    if glob.glob(os.path.join(STAGED_DIR, "sub-*")):
        out.insert(0, {"name": ".",
                       "subjects": len(glob.glob(os.path.join(STAGED_DIR, "sub-*")))})
    return {"staged_dir": STAGED_DIR, "inputs": out}


class LaunchBody(BaseModel):
    run_id: str
    input: str            # subfolder of staged/ (or "." for staged/ itself)
    render: bool = True
    review: bool = False  # agent figure review (needs ANTHROPIC_API_KEY)


@app.post("/api/runs", dependencies=[auth])
def launch_run(body: LaunchBody):
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
    criteria = os.path.join(REPO, "criteria.yaml")
    try:
        jobs.launch(run_id, run_dir, input_dir, criteria,
                    do_render=body.render, do_review=body.review)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"run_id": run_id, "job": jobs.status(run_id)}


@app.get("/api/runs", dependencies=[auth])
def list_runs():
    if not os.path.isdir(RUNS_DIR):
        return {"runs": []}
    out = []
    for d in sorted(os.listdir(RUNS_DIR)):
        if os.path.exists(os.path.join(RUNS_DIR, d, "state.json")):
            out.append(_summary(d, _load_state(d)))
    return {"runs": out}


@app.get("/api/runs/{run_id}", dependencies=[auth])
def run_detail(run_id: str):
    state = _load_state(run_id)
    return {**_summary(run_id, state), "criteria": state.get("criteria")}


@app.get("/api/runs/{run_id}/scans", dependencies=[auth])
def run_scans(run_id: str):
    state = _load_state(run_id)
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
            "review": s.get("review"),          # agent figure review, if run
            "decision": s.get("decision"),      # human keep/drop, if made
            "figures": {k: os.path.basename(v) if v else None
                        for k, v in s.get("rendered", {}).items()},
        })
    return {"run_id": run_id, "scans": rows}


class DecisionBody(BaseModel):
    decision: str       # "keep" | "drop" | "clear"
    by: str = ""        # reviewer initials/name
    note: str = ""


@app.post("/api/runs/{run_id}/scans/{key}/decision", dependencies=[auth])
def decide(run_id: str, key: str, body: DecisionBody):
    if body.decision not in ("keep", "drop", "clear"):
        raise HTTPException(400, "decision must be keep, drop or clear")
    state = _load_state(run_id)
    if key not in state.get("scans", {}):
        raise HTTPException(404, f"scan {key} not in run {run_id}")
    scan = state["scans"][key]
    entry = {"decision": body.decision, "by": body.by, "note": body.note,
             "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "status_at_decision": scan.get("status")}
    scan["decision"] = None if body.decision == "clear" else entry
    scan.setdefault("decision_log", []).append(entry)   # full audit trail
    _save_state(run_id, state)
    return {"key": key, "decision": scan["decision"]}


@app.get("/api/runs/{run_id}/figures/{name}", dependencies=[auth])
def figure(run_id: str, name: str):
    if "/" in name or ".." in name or not name.endswith(".jpg"):
        raise HTTPException(400, "bad figure name")
    p = os.path.join(_run_dir(run_id), "figures", name)
    if not os.path.exists(p):
        raise HTTPException(404, "figure not rendered")
    return FileResponse(p, media_type="image/jpeg")


@app.get("/api/runs/{run_id}/deck", dependencies=[auth])
def deck(run_id: str):
    p = os.path.join(_run_dir(run_id), "review_deck.pptx")
    if not os.path.exists(p):
        raise HTTPException(404, "deck not built yet (POST /api/runs/{id}/deck)")
    return FileResponse(
        p, filename=f"{run_id}_review_deck.pptx",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")


@app.post("/api/runs/{run_id}/deck", dependencies=[auth])
def build_deck(run_id: str, kind: str = "review"):
    if kind not in ("review", "all"):
        raise HTTPException(400, "kind must be review or all")
    run_dir = _run_dir(run_id)
    if jobs.status(run_id)["phase"] in ("starting", "pipeline", "review", "deck"):
        raise HTTPException(409, "a job is already running for this run")
    jobs.launch_cmd(run_id, run_dir, "deck",
                    ["python3", "-m", "report.build_decks", run_dir, "--deck", kind])
    return {"run_id": run_id, "job": jobs.status(run_id)}


@app.get("/api/runs/{run_id}/log", dependencies=[auth])
def job_log(run_id: str, tail: int = 100):
    p = os.path.join(_run_dir(run_id), "job.log")
    if not os.path.exists(p):
        return {"log": ""}
    with open(p) as f:
        lines = f.readlines()
    return {"log": "".join(lines[-max(1, min(tail, 2000)):])}
