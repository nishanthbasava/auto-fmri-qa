"""Orchestrator: discover -> metrics -> classify [-> render].

    python -m pipeline.run --input staged/ --criteria criteria.yaml --out runs/qc1
    python -m pipeline.run --input staged/ --criteria criteria.yaml --out runs/qc1 --render

Writes runs/<run>/scans.csv (one row per scan) and state.json. Deterministic:
no LLM involved. Rendering is optional here because it is the slow stage;
agents and reports both read state.json afterwards.
"""
import argparse
import csv
import os
import sys

import yaml

from . import discover as disc
from . import metrics as met
from . import classify as cls
from .state import RunState


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--criteria", default="criteria.yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--task", default="rest")
    ap.add_argument("--render", action="store_true", help="also render figures to JPEG")
    args = ap.parse_args()

    with open(args.criteria) as f:
        criteria = yaml.safe_load(f)
    state = RunState(args.out)
    state.data["criteria"] = criteria
    state.data["input"] = os.path.abspath(args.input)

    scans = disc.discover(args.input, task=args.task)
    if not scans:
        print("no scans found -- check --input and --task", file=sys.stderr)
        return 1
    print(f"discovered {len(scans)} scans "
          f"({len({s['sub'] for s in scans})} subjects)")

    counts = {"INCLUDE": 0, "CAUTION": 0, "EXCLUDE": 0}
    for s in scans:
        key = f"{s['sub']}|{s['ses']}"
        m = met.scan_metrics(s, criteria) if not s["missing"] or s["confounds"] else {}
        c = cls.classify(s, m, criteria)
        counts[c["status"]] += 1
        state.scans()[key] = {**s, "metrics": m, **c}
    state.mark_stage("metrics", n=len(scans), counts=counts)
    print("counts:", counts)

    csv_path = os.path.join(args.out, "scans.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject", "session", "status", "tr_s", "n_volumes", "mean_fd",
                    "max_fd", "outlier_percent", "retained_minutes",
                    "verify_flags", "reasons"])
        for key in sorted(state.scans()):
            s = state.scans()[key]
            m = s["metrics"]
            w.writerow([s["sub"], s["ses"], s["status"], m.get("tr"),
                        m.get("n_volumes"), m.get("mean_fd"), m.get("max_fd"),
                        m.get("outlier_percent"), m.get("retained_minutes"),
                        "; ".join(s["verify_flags"]), "; ".join(s["reasons"])])
    print(f"wrote {csv_path}")

    if args.render:
        from . import render
        render.render_run(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
