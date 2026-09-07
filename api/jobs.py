"""Background pipeline jobs.

Each run executes the existing CLI stages as subprocesses in a worker thread,
appending to runs/<run>/job.log. Progress is whatever state.json says -- the
pipeline was already resumable/journaled, so the API just reads the journal.
"""
import os
import subprocess
import threading

_LOCK = threading.Lock()
_ACTIVE: dict[str, dict] = {}   # run_id -> {"phase": str, "returncode": int|None}

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def launch(run_id: str, run_dir: str, input_dir: str, criteria: str,
           do_render: bool = True, do_review: bool = False) -> None:
    with _LOCK:
        if run_id in _ACTIVE and _ACTIVE[run_id]["returncode"] is None:
            raise RuntimeError(f"run {run_id} already in progress")
        _ACTIVE[run_id] = {"phase": "starting", "returncode": None}
    t = threading.Thread(target=_work, daemon=True,
                         args=(run_id, run_dir, input_dir, criteria, do_render, do_review))
    t.start()


def launch_cmd(run_id: str, run_dir: str, phase: str, cmd: list) -> None:
    """Run a single arbitrary stage (e.g. deck build) as a background job."""
    with _LOCK:
        if run_id in _ACTIVE and _ACTIVE[run_id]["returncode"] is None:
            raise RuntimeError(f"run {run_id} already in progress")
        _ACTIVE[run_id] = {"phase": phase, "returncode": None}
    t = threading.Thread(target=_work_one, daemon=True,
                         args=(run_id, run_dir, phase, cmd))
    t.start()


def status(run_id: str) -> dict:
    with _LOCK:
        return dict(_ACTIVE.get(run_id, {"phase": "idle", "returncode": None}))


def _work_one(run_id, run_dir, phase, cmd):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "job.log"), "a") as log:
        log.write(f"\n=== {phase}: {' '.join(cmd)}\n")
        log.flush()
        rc = subprocess.call(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        if rc != 0:
            log.write(f"=== {phase} FAILED rc={rc}\n")
    with _LOCK:
        _ACTIVE[run_id]["phase"] = "done" if rc == 0 else "failed"
        _ACTIVE[run_id]["returncode"] = rc


def _work(run_id, run_dir, input_dir, criteria, do_render, do_review):
    os.makedirs(run_dir, exist_ok=True)
    log = open(os.path.join(run_dir, "job.log"), "a")
    steps = [("pipeline",
              ["python3", "-m", "pipeline.run", "--input", input_dir,
               "--criteria", criteria, "--out", run_dir]
              + (["--render"] if do_render else []))]
    if do_review:
        steps.append(("review", ["python3", "-m", "agents.review_figures", run_dir]))
    rc = 0
    for phase, cmd in steps:
        with _LOCK:
            _ACTIVE[run_id]["phase"] = phase
        log.write(f"\n=== {phase}: {' '.join(cmd)}\n")
        log.flush()
        rc = subprocess.call(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        if rc != 0:
            log.write(f"=== {phase} FAILED rc={rc}\n")
            break
    with _LOCK:
        _ACTIVE[run_id]["phase"] = "done" if rc == 0 else "failed"
        _ACTIVE[run_id]["returncode"] = rc
    log.close()
