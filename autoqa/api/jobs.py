"""Background pipeline jobs.

Each run executes the existing CLI stages as subprocesses in a worker thread,
appending to runs/<run>/job.log. Progress is whatever state.json says -- the
pipeline was already resumable/journaled, so the API just reads the journal.

Job status lives in the jobs table, not a process-local dict, so it survives
an API restart: a row still marked running whose host_pid is not this process
was orphaned by a restart and is reported (and recorded) as "interrupted".
"""
import os
import subprocess
import sys
import threading

from ..db import models
from ..db.session import session

_LOCK = threading.Lock()   # serialises the check-then-insert in _start

# Working directory for subprocess stages. In a checkout this is the repo root
# (parent of the autoqa/ package); in the Docker image it is /app. Stages are
# launched as `python -m autoqa.cli ...` so they resolve the same installed package.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = [sys.executable, "-m", "autoqa.cli"]

IDLE = {"phase": "idle", "returncode": None}


def _latest(s, run_id: str) -> models.Job | None:
    return (s.query(models.Job).filter_by(run_id=run_id)
            .order_by(models.Job.id.desc()).first())


def _reap(job: models.Job | None) -> None:
    """A running row owned by another (dead) process means the API restarted
    mid-job: the worker thread is gone, so record the interruption."""
    if job is not None and job.returncode is None and job.host_pid != os.getpid():
        job.phase, job.returncode = "interrupted", -1
        job.finished_at = models.utcnow()


def _start(run_id: str, phase: str) -> int:
    with _LOCK, session() as s:
        job = _latest(s, run_id)
        _reap(job)
        if job is not None and job.returncode is None:
            raise RuntimeError(f"run {run_id} already in progress")
        job = models.Job(run_id=run_id, phase=phase, host_pid=os.getpid())
        s.add(job)
        s.flush()
        return job.id


def _update(job_id: int, phase: str | None = None, returncode: int | None = None) -> None:
    with session() as s:
        job = s.get(models.Job, job_id)
        if phase is not None:
            job.phase = phase
        if returncode is not None:
            job.returncode = returncode
            job.phase = "done" if returncode == 0 else "failed"
            job.finished_at = models.utcnow()


def launch(run_id: str, run_dir: str, input_dir: str, criteria: str,
           do_render: bool = True, do_review: bool = False) -> None:
    job_id = _start(run_id, "starting")
    t = threading.Thread(target=_work, daemon=True,
                         args=(job_id, run_dir, input_dir, criteria, do_render, do_review))
    t.start()


def launch_cmd(run_id: str, run_dir: str, phase: str, cmd: list) -> None:
    """Run a single arbitrary stage (e.g. deck build) as a background job."""
    job_id = _start(run_id, phase)
    t = threading.Thread(target=_work_one, daemon=True,
                         args=(job_id, run_dir, phase, cmd))
    t.start()


def status(run_id: str) -> dict:
    with session() as s:
        job = _latest(s, run_id)
        _reap(job)
        return {"phase": job.phase, "returncode": job.returncode} if job else dict(IDLE)


def _work_one(job_id, run_dir, phase, cmd):
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "job.log"), "a") as log:
        log.write(f"\n=== {phase}: {' '.join(cmd)}\n")
        log.flush()
        rc = subprocess.call(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        if rc != 0:
            log.write(f"=== {phase} FAILED rc={rc}\n")
    _update(job_id, returncode=rc)


def _work(job_id, run_dir, input_dir, criteria, do_render, do_review):
    os.makedirs(run_dir, exist_ok=True)
    log = open(os.path.join(run_dir, "job.log"), "a")
    steps = [("pipeline",
              PY + ["run", "--input", input_dir, "--criteria", criteria, "--out", run_dir]
              + (["--render"] if do_render else []))]
    if do_review:
        steps.append(("review", PY + ["review", run_dir]))
    rc = 0
    for phase, cmd in steps:
        _update(job_id, phase=phase)
        log.write(f"\n=== {phase}: {' '.join(cmd)}\n")
        log.flush()
        rc = subprocess.call(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        if rc != 0:
            log.write(f"=== {phase} FAILED rc={rc}\n")
            break
    _update(job_id, returncode=rc)
    log.close()
