"""Review-surface metric: how much of the cohort still needs human eyes.

    autoqa audit surface RUN_DIR

Baseline: without tooling, every scan is opened by a reviewer (N).
With AutoQA, a human looks only at scans the pipeline could not clear:

    surface = EXCLUDE ∪ CAUTION ∪ (INCLUDE with VERIFY flags) ∪ (LLM review concern/bad)

The reduction (1 - surface/N) is only meaningful next to what the triage
missed, so when human keep/drop decisions exist in the journal the report also
prints how many INCLUDE scans a reviewer later dropped ("misses") and how many
flagged scans they kept ("false alarms").

Two variants are reported because they answer different questions:
  strict   -- EXCLUDE scans still count as reviewed (someone confirms each drop)
  triage   -- EXCLUDE scans are dropped on the metrics alone; humans review the rest
"""
from __future__ import annotations

import argparse
import json
import os

from ..pipeline.state import RunState


def _metric_verify_flags(s: dict) -> list:
    """Criteria-band VERIFY flags only; 'visual review' flags are the LLM's and are
    attributed to the llm bucket (review_figures appends one per concern/bad rating)."""
    return [f for f in s.get("verify_flags", []) if not f.startswith("visual review")]


def surface(run_dir: str) -> dict:
    state = RunState(run_dir)
    scans = list(state.scans().values())
    n = len(scans)
    excl = [s for s in scans if s["status"] == "EXCLUDE"]
    caut = [s for s in scans if s["status"] == "CAUTION"]
    verify = [s for s in scans if s["status"] == "INCLUDE" and _metric_verify_flags(s)]
    llm = [s for s in scans if s["status"] == "INCLUDE" and not _metric_verify_flags(s)
           and (s.get("review") or {}).get("rating") in ("concern", "bad")]
    strict = len(excl) + len(caut) + len(verify) + len(llm)
    triage = len(caut) + len(verify) + len(llm)

    decided = [s for s in scans if s.get("decision")]
    misses = [s for s in scans if s["status"] == "INCLUDE" and not s.get("verify_flags")
              and (s.get("decision") or {}).get("decision") == "drop"]
    false_alarms = [s for s in scans if s["status"] != "INCLUDE"
                    and (s.get("decision") or {}).get("decision") == "keep"]
    reviewed = sum(1 for s in scans if s.get("review"))

    r = {
        "n_scans": n,
        "exclude": len(excl), "caution": len(caut), "verify_only": len(verify),
        "llm_flagged": len(llm), "llm_reviewed": reviewed,
        "surface_strict": strict, "surface_triage": triage,
        "reduction_strict_pct": round(100 * (1 - strict / n), 1) if n else None,
        "reduction_triage_pct": round(100 * (1 - triage / n), 1) if n else None,
        "n_decided": len(decided), "misses": len(misses), "false_alarms": len(false_alarms),
        "criteria_version": state.data.get("criteria", {}).get("version"),
    }
    os.makedirs(os.path.join(run_dir, "analysis"), exist_ok=True)
    with open(os.path.join(run_dir, "analysis", "review_surface.json"), "w") as f:
        json.dump(r, f, indent=1)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    args = ap.parse_args(argv)
    r = surface(args.run_dir)
    n = r["n_scans"]
    print(f"criteria {r['criteria_version']}; {n} scans")
    print(f"  EXCLUDE {r['exclude']}  CAUTION {r['caution']}  INCLUDE+VERIFY {r['verify_only']}  "
          f"LLM concern/bad {r['llm_flagged']} (of {r['llm_reviewed']} reviewed)")
    print(f"  review surface, strict : {r['surface_strict']:4d} / {n}  "
          f"-> {r['reduction_strict_pct']}% fewer scans opened")
    print(f"  review surface, triage : {r['surface_triage']:4d} / {n}  "
          f"-> {r['reduction_triage_pct']}% fewer scans opened")
    if r["n_decided"]:
        print(f"  human decisions: {r['n_decided']}  misses (clean INCLUDE later dropped): "
              f"{r['misses']}  false alarms (flagged but kept): {r['false_alarms']}")
    else:
        print("  no human decisions in the journal yet: the reduction is unqualified until misses are known")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
