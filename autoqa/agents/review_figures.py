"""LLM visual review of rendered QC figures.

    autoqa review runs/<run>/ [--only flagged|all] [--batch 4] [--k 2] [--no-rag]
                              [--model MODEL] [--dry-run]

Reads state.json (after `autoqa run --render`), sends each scan's figures to the
model with the checklist prompt and retrieved protocol context, and writes
structured results back into state.json under scan["review"] and to review.json.

Review output is ADVISORY: it never changes a computed status. "concern"/"bad"
ratings become VERIFY flags on the scan.

Grounding: before each batch, `rag.context_for_scans` retrieves the knowledge
passages relevant to those scans (TR regime, vendor, panels) and they go into
the prompt as "Reference notes". `--no-rag` disables this (for ablations); the
passages used are recorded per scan under review["context"].

Output contract: the model must call the `record_reviews` tool; its arguments
are validated with pydantic (see schemas.py). A batch that fails validation is
retried once with the error shown to the model, then recorded as failed.

Cost: token usage and an estimated USD figure are accumulated per batch under
state["stages"]["review"].
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from pydantic import ValidationError

from ..pipeline.state import RunState
from . import llm, rag
from .schemas import REVIEW_TOOL, ReviewBatch

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "figure_review.md")


def load_prompt() -> str:
    with open(PROMPT_PATH) as f:
        return f.read()


def scan_header(s: dict) -> str:
    m = s.get("metrics") or {}
    tr = m.get("tr") or s.get("tr")
    bits = [f"Scan: sub={s['sub']} ses={s['ses']}",
            f"TR {tr} s" + (" (multiband/fast-TR)" if tr and tr < 1.0 else ""),
            f"{m.get('n_volumes', '?')} volumes",
            f"mean FD {m.get('mean_fd')}", f"outliers {m.get('outlier_percent')}%"]
    if s.get("vendor"):
        bits.append(f"scanner {s['vendor']}")
    return "; ".join(bits)


def build_content(batch: list[tuple], passages: list[dict]) -> list[dict]:
    """The user turn for one batch: reference notes, then per-scan text + images."""
    content = []
    ctx = rag.format_context(passages)
    if ctx:
        content.append({"type": "text", "text": ctx})
    for _key, s, figs in batch:
        content.append({"type": "text", "text": scan_header(s)})
        for kind in ("carpet", "coreg", "t1norm"):
            if kind in figs and os.path.exists(figs[kind]):
                content.append({"type": "text", "text": f"[{kind}]"})
                content.append(llm.image_block(figs[kind]))
    content.append({"type": "text",
                    "text": f"Review the {len(batch)} scan(s) above and call record_reviews "
                            f"with exactly one entry per scan, using the sub/ses labels given."})
    return content


def review_batch(system: str, content: list, expected: set[str], *, model=None,
                 _client=None, _sleep=time.sleep) -> tuple[ReviewBatch, dict, int]:
    """Call the model, validate; on a validation failure retry once with the error."""
    msgs = list(content)
    last_err = None
    usage_total = {}
    attempts = 0
    for _ in range(2):
        res = llm.ask_tool(system, msgs, REVIEW_TOOL, model=model, _client=_client, _sleep=_sleep)
        attempts += res.attempts
        for k, v in res.usage.items():
            usage_total[k] = round(usage_total.get(k, 0) + v, 5)
        try:
            batch = ReviewBatch.model_validate(res.input)
            got = {f"{r.sub}|{r.ses}" for r in batch.reviews}
            missing = expected - got
            if missing:
                raise ValueError(f"no review for: {sorted(missing)}")
            return batch, usage_total, attempts
        except (ValidationError, ValueError) as e:
            last_err = e
            msgs = content + [{"type": "text", "text":
                               f"Your previous record_reviews call was rejected: {e}\n"
                               f"Call it again with one valid entry per scan."}]
    raise RuntimeError(f"review output failed validation twice: {last_err}")


def main(argv=None, _client=None, _sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--only", choices=["flagged", "all"], default="all",
                    help="review only CAUTION/EXCLUDE scans, or everything")
    ap.add_argument("--batch", type=int, default=4, help="scans per model call")
    ap.add_argument("--k", type=int, default=2, help="passages retrieved per scan")
    ap.add_argument("--no-rag", action="store_true", help="no reference notes in the prompt")
    ap.add_argument("--model", default=None, help=f"override model (default {llm.MODEL})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the assembled prompt for the first batch and exit")
    args = ap.parse_args(argv)

    state = RunState(args.run_dir)
    system = load_prompt()
    todo = []
    for key, s in sorted(state.scans().items()):
        if "review" in s:
            continue
        if args.only == "flagged" and s["status"] == "INCLUDE":
            continue
        figs = s.get("rendered", {})
        if not figs:
            print(f"skip {key}: no rendered figures (run `autoqa run --render` or `autoqa render`)")
            continue
        todo.append((key, s, figs))
    if not todo:
        print("nothing to review")
        return 0
    print(f"reviewing {len(todo)} scans in batches of {args.batch} "
          f"(rag={'off' if args.no_rag else f'k={args.k}'}, model={args.model or llm.MODEL})")

    stage = state.data["stages"].setdefault("review", {
        "batches": 0, "failed_batches": 0, "scans": 0, "model": args.model or llm.MODEL,
        "rag": not args.no_rag, "k": args.k, "usage": {}})
    failures = 0
    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        passages = [] if args.no_rag else rag.context_for_scans([s for _, s, _ in batch], k=args.k)
        content = build_content(batch, passages)
        if args.dry_run:
            print("=== system ===\n" + system)
            print("=== user ===")
            for block in content:
                print(block["text"] if block["type"] == "text" else "<image>")
            return 0
        expected = {key for key, _, _ in batch}
        try:
            result, usage, attempts = review_batch(system, content, expected, model=args.model,
                                                   _client=_client, _sleep=_sleep)
        except Exception as e:  # keep going; record the failure
            failures += 1
            stage["failed_batches"] += 1
            print(f"batch {i // args.batch + 1}: failed: {e}", file=sys.stderr)
            state.save()
            continue
        by_key = {f"{r.sub}|{r.ses}": r for r in result.reviews}
        for key, s, _ in batch:
            r = by_key[key]
            s["review"] = {"rating": r.rating, "panel": r.panel, "note": r.note,
                           "model": args.model or llm.MODEL,
                           "context": [{"file": p["file"], "section": p["section"]}
                                       for p in passages]}
            if r.rating in ("concern", "bad"):
                s["verify_flags"].append(f"visual review ({r.rating}): {r.note}")
                cites = rag.retrieve(f"{r.panel} {r.note} TR {s['metrics'].get('tr')}", k=2)
                if cites:
                    s["review"]["citations"] = [{"source": c["source"], "section": c["section"]}
                                                for c in cites]
        stage["batches"] += 1
        stage["scans"] += len(batch)
        for k, v in usage.items():
            stage["usage"][k] = round(stage["usage"].get(k, 0) + v, 5)
        state.save()
        print(f"  batch {i // args.batch + 1}: {len(result.reviews)} reviews, "
              f"{attempts} call(s), ${usage.get('usd', 0):.4f}")

    stage["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state.save()
    with open(os.path.join(args.run_dir, "review.json"), "w") as f:
        json.dump({k: s.get("review") for k, s in state.scans().items() if s.get("review")},
                  f, indent=1)
    n = sum(1 for s in state.scans().values()
            if (s.get("review") or {}).get("rating") in ("concern", "bad"))
    print(f"done; {n} scans rated concern/bad; {failures} failed batch(es); "
          f"total ${stage['usage'].get('usd', 0):.4f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
