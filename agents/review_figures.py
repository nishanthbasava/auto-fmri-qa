"""LLM visual review of rendered QC figures.

    python -m agents.review_figures runs/<run>/ [--only flagged|all] [--batch 4]

Reads state.json (after pipeline.run --render), sends each scan's figures to
the model with the checklist prompt, writes structured results back into
state.json under scan["review"] and to review.json.

Review output is ADVISORY: it never changes a computed status. "concern"/"bad"
ratings become VERIFY flags on the scan.
"""
import argparse
import json
import os
import sys

from pipeline.state import RunState
from . import llm

PROMPT = open(os.path.join(os.path.dirname(__file__), "prompts", "figure_review.md")).read()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--only", choices=["flagged", "all"], default="all",
                    help="review only CAUTION/EXCLUDE scans, or everything")
    ap.add_argument("--batch", type=int, default=4, help="scans per model call")
    args = ap.parse_args()

    state = RunState(args.run_dir)
    todo = []
    for key, s in sorted(state.scans().items()):
        if "review" in s:
            continue
        if args.only == "flagged" and s["status"] == "INCLUDE":
            continue
        figs = s.get("rendered", {})
        if not figs:
            print(f"skip {key}: no rendered figures (run pipeline with --render)")
            continue
        todo.append((key, s, figs))
    if not todo:
        print("nothing to review")
        return 0
    print(f"reviewing {len(todo)} scans in batches of {args.batch}")

    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        content = []
        for key, s, figs in batch:
            content.append({"type": "text",
                            "text": f"Scan: sub={s['sub']} ses={s['ses']} "
                                    f"(mean FD {s['metrics'].get('mean_fd')}, "
                                    f"outliers {s['metrics'].get('outlier_percent')}%)"})
            for kind in ("carpet", "coreg", "t1norm"):
                if kind in figs and os.path.exists(figs[kind]):
                    content.append({"type": "text", "text": f"[{kind}]"})
                    content.append(llm.image_block(figs[kind]))
        try:
            results = llm.ask_json(PROMPT, content)
        except Exception as e:  # keep going; record the failure
            print(f"batch {i // args.batch}: model call failed: {e}", file=sys.stderr)
            continue
        by_key = {f"{r.get('sub')}|{r.get('ses')}": r for r in results}
        for key, s, _ in batch:
            r = by_key.get(key)
            if not r:
                continue
            s["review"] = {"rating": r.get("rating"), "panel": r.get("panel"),
                           "note": r.get("note", "")}
            if r.get("rating") in ("concern", "bad"):
                s["verify_flags"].append(f"visual review ({r.get('rating')}): {r.get('note')}")
        state.save()
        print(f"  batch {i // args.batch + 1}: {len(results)} results")

    with open(os.path.join(args.run_dir, "review.json"), "w") as f:
        json.dump({k: s.get("review") for k, s in state.scans().items()
                   if s.get("review")}, f, indent=1)
    n = sum(1 for s in state.scans().values()
            if s.get("review", {}).get("rating") in ("concern", "bad"))
    print(f"done; {n} scans rated concern/bad")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
