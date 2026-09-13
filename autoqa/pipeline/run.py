"""Orchestrator: discover -> metrics -> classify [-> render].

    autoqa run --input staged/ --out runs/qc1 [--criteria my.yaml] [--render]

Writes runs/<run>/scans.csv (one row per scan) and state.json. Deterministic:
no LLM involved. Rendering is optional here because it is the slow stage;
agents and reports both read state.json afterwards.

The same logic is available as a function for SDK use: `qc(...)`.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

from ..criteria import Criteria, load_criteria
from . import classify as cls
from . import discover as disc
from . import metrics as met
from .state import RunState

CSV_COLUMNS = ["subject", "session", "status", "tr_s", "n_volumes", "mean_fd",
               "max_fd", "outlier_percent", "retained_minutes", "verify_flags", "reasons"]


@dataclass
class RunResult:
    """What one QC run produced. `scans` are the per-scan records from state.json."""
    run_dir: str
    criteria: dict
    scans: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        out = {"INCLUDE": 0, "CAUTION": 0, "EXCLUDE": 0}
        for s in self.scans:
            out[s["status"]] = out.get(s["status"], 0) + 1
        return out

    @property
    def n_subjects(self) -> int:
        return len({s["sub"] for s in self.scans})

    @property
    def csv_path(self) -> str:
        return os.path.join(self.run_dir, "scans.csv")


def qc(input_dir: str, out: str, criteria: Optional[str | Criteria] = None,
       task: str = "rest", render: bool = False, quiet: bool = False) -> RunResult:
    """Run discover -> metrics -> classify on a derivatives-shaped tree.

    Raises FileNotFoundError when no scans are found (bad --input/--task) and
    ValueError when the criteria file is invalid.
    """
    crit = criteria if isinstance(criteria, Criteria) else load_criteria(criteria)
    crit_dict = crit.as_dict()
    log = (lambda *a: None) if quiet else (lambda *a: print(*a))

    state = RunState(out)
    state.data["criteria"] = crit_dict
    state.data["input"] = os.path.abspath(input_dir)

    scans = disc.discover(input_dir, task=task)
    if not scans:
        raise FileNotFoundError(f"no task-{task} scans found under {input_dir}")
    log(f"discovered {len(scans)} scans ({len({s['sub'] for s in scans})} subjects)")

    counts = {"INCLUDE": 0, "CAUTION": 0, "EXCLUDE": 0}
    for s in scans:
        key = f"{s['sub']}|{s['ses']}"
        m = met.scan_metrics(s, crit_dict) if not s["missing"] or s["confounds"] else {}
        c = cls.classify(s, m, crit_dict)
        counts[c["status"]] += 1
        state.scans()[key] = {**s, "metrics": m, **c}
    state.mark_stage("metrics", n=len(scans), counts=counts)
    log("counts:", counts)

    csv_path = os.path.join(out, "scans.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        for key in sorted(state.scans()):
            s = state.scans()[key]
            m = s["metrics"]
            w.writerow([s["sub"], s["ses"], s["status"], m.get("tr"),
                        m.get("n_volumes"), m.get("mean_fd"), m.get("max_fd"),
                        m.get("outlier_percent"), m.get("retained_minutes"),
                        "; ".join(s["verify_flags"]), "; ".join(s["reasons"])])
    log(f"wrote {csv_path}")

    if render:
        from . import render as rend
        rend.render_run(state)
    return RunResult(run_dir=out, criteria=crit_dict,
                     scans=[state.scans()[k] for k in sorted(state.scans())])


def add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--input", required=True, help="derivatives-shaped tree (see README)")
    ap.add_argument("--criteria", default=None,
                    help="criteria YAML (default: $AFQ_CRITERIA or the packaged criteria.yaml)")
    ap.add_argument("--out", required=True, help="run directory to create/resume")
    ap.add_argument("--task", default="rest")
    ap.add_argument("--render", action="store_true", help="also render figures to JPEG")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    add_args(ap)
    args = ap.parse_args(argv)
    try:
        qc(args.input, args.out, criteria=args.criteria, task=args.task, render=args.render)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
