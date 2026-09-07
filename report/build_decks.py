"""Build the flagged-scan review deck from a run.

    python -m report.build_decks runs/<run>/ [--deck review|all]

review: EXCLUDE section + CAUTION section + visual-flag appendix (scans whose
LLM/manual review rated concern/bad while metrics said INCLUDE) + Keep? table.
all: every scan, ordered by subject.

Requires pptxgenjs (npm i pptxgenjs) and rendered figures in the run.
"""
import argparse
import json
import os
import subprocess

from pipeline.state import RunState

COLORS = {"EXCLUDE": "C62828", "CAUTION": "E8890C", "INCLUDE": "2E7D32", "APPENDIX": "B45309"}


def scan_payload(s):
    return {
        "sub": s["sub"], "ses": s["ses"], "status": s["status"],
        "verify": bool(s["verify_flags"]),
        "note": "; ".join(s["reasons"] + s["verify_flags"])[:150],
        "metrics": s["metrics"], "figures": s.get("rendered", {}),
        "t1norm_subject_level": s.get("t1norm_subject_level", False),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--deck", choices=["review", "all"], default="review")
    args = ap.parse_args()
    state = RunState(args.run_dir)
    crit = state.data.get("criteria", {})
    scans = sorted(state.scans().values(), key=lambda s: (s["sub"], s["ses"]))

    if args.deck == "review":
        excl = [s for s in scans if s["status"] == "EXCLUDE"]
        caut = [s for s in scans if s["status"] == "CAUTION"]
        appendix = [s for s in scans if s["status"] == "INCLUDE"
                    and s.get("review", {}).get("rating") in ("concern", "bad")]
        sections = [
            {"heading": f"EXCLUDE — {len(excl)} scans", "color": COLORS["EXCLUDE"],
             "scans": [scan_payload(s) for s in excl]},
            {"heading": f"CAUTION — {len(caut)} scans", "color": COLORS["CAUTION"],
             "scans": [scan_payload(s) for s in caut]},
        ]
        if appendix:
            sections.append({"heading": f"Appendix — clean metrics, visual flags ({len(appendix)})",
                             "color": COLORS["APPENDIX"],
                             "scans": [scan_payload(s) for s in appendix]})
        title, out_name = "QC review — flagged scans", "review_deck.pptx"
        subtitle = (f"{len(excl)} EXCLUDE · {len(caut)} CAUTION · "
                    f"{len(appendix)} visual-flag appendix — decide keep/drop per scan")
    else:
        sections = [{"heading": f"All scans — {len(scans)}", "color": "1F2937",
                     "scans": [scan_payload(s) for s in scans]}]
        title, out_name = "QC — all scans", "all_scans_deck.pptx"
        subtitle = f"{len(scans)} scans, ordered by subject"

    payload = {"title": title, "subtitle": subtitle,
               "criteria_version": crit.get("version", "?"), "sections": sections}
    ppath = os.path.join(args.run_dir, "deck_payload.json")
    with open(ppath, "w") as f:
        json.dump(payload, f)
    out = os.path.join(args.run_dir, out_name)
    script = os.path.join(os.path.dirname(__file__), "deck_case_slides.js")
    subprocess.run(["node", "--max-old-space-size=4096", script, ppath, out], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
