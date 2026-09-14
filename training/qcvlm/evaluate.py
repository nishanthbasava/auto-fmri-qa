"""Evaluate a predictor on a split and append the result to RESULTS.md.

    python -m qcvlm.evaluate --predictor claude --data data/processed --split test
    python -m qcvlm.evaluate --predictor stub --data data/processed --split validation --error-rate 0.2

Writes results/<predictor>__<split>.json with macro-F1 (+95% bootstrap CI over
subjects), per-class P/R/F1, confusion matrix, coarse-label metrics,
failure-type accuracy, and cost/latency from the predictor's own accounting.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time

from .dataset import load_split
from .metrics import summarize
from .predictors import get_predictor
from .schema import FAILURE_TYPES, RATINGS


def evaluate(predictor, examples: list[dict], n_boot: int = 1000, seed: int = 0,
             limit: int | None = None) -> dict:
    examples = examples[:limit] if limit else examples
    preds = [predictor.predict(ex) for ex in examples]
    res = summarize(examples, preds, RATINGS, FAILURE_TYPES, n_boot=n_boot, seed=seed)
    res["usage"] = predictor.usage()
    res["predictor"] = predictor.ident()
    res["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    res["predictions"] = [{"id": e["id"], "true": e["label"]["rating"], "pred": p["rating"],
                           "failure_true": e["label"]["failure_type"],
                           "failure_pred": p.get("failure_type"), "note": p.get("note", "")}
                          for e, p in zip(examples, preds, strict=True)]
    return res


def results_row(res: dict, split: str) -> str:
    u = res["usage"]
    lo, hi = res["macro_f1_ci95"]
    return (f"| {res['predictor']} | {split} | {res['n']} | {res['macro_f1']:.3f} "
            f"[{lo:.3f}, {hi:.3f}] | {res['accuracy']:.3f} | {res['coarse_macro_f1']:.3f} | "
            f"{res['failure_type_accuracy']:.3f} | {u['usd_per_1k'] if u['usd_per_1k'] is not None else '—'} | "
            f"{u['s_per_example'] if u['s_per_example'] is not None else '—'} | {res['finished'][:10]} |")


def append_results(path: str, row: str) -> None:
    header = ("| predictor | split | n | macro-F1 [95% CI] | acc | coarse F1 | failure-type acc | "
              "$/1k | s/example | date |\n|---|---|---|---|---|---|---|---|---|---|\n")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write("# Results\n\nAppended by `python -m qcvlm.evaluate`; one row per run.\n\n" + header)
    with open(path, "a") as f:
        f.write(row + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictor", required=True, help="stub | claude | qwen | qwen-lora")
    ap.add_argument("--data", default="data/processed")
    ap.add_argument("--split", default="test", choices=["train", "validation", "test"])
    ap.add_argument("--model", default=None, help="model id (claude / qwen)")
    ap.add_argument("--adapter", default=None, help="LoRA adapter path (qwen-lora)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--error-rate", type=float, default=0.0, help="stub only")
    ap.add_argument("--cache", default="results/cache")
    ap.add_argument("--out", default="results")
    ap.add_argument("--no-append", action="store_true")
    args = ap.parse_args(argv)

    kw = {"cache_dir": args.cache}
    if args.predictor == "stub":
        kw["error_rate"] = args.error_rate
    if args.model:
        kw["model"] = args.model
    if args.adapter:
        kw["adapter"] = args.adapter
    predictor = get_predictor(args.predictor, **kw)
    examples = load_split(args.data, args.split)
    res = evaluate(predictor, examples, n_boot=args.n_boot, limit=args.limit)
    os.makedirs(args.out, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", res["predictor"])
    out = os.path.join(args.out, f"{stem}__{args.split}.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=1)
    lo, hi = res["macro_f1_ci95"]
    print(f"{res['predictor']} on {args.split} (n={res['n']}, {res['n_subjects']} subjects)")
    print(f"  macro-F1 {res['macro_f1']:.3f}  95% CI [{lo:.3f}, {hi:.3f}]   accuracy {res['accuracy']:.3f}")
    print(f"  coarse macro-F1 {res['coarse_macro_f1']:.3f}   failure-type acc {res['failure_type_accuracy']:.3f}")
    for c, d in res["per_class"].items():
        print(f"  {c:8s} P {d['precision']:.2f} R {d['recall']:.2f} F1 {d['f1']:.2f}  (n={d['support']})")
    u = res["usage"]
    print(f"  cost ${u['usd']:.4f} (${u['usd_per_1k']}/1k)  {u['s_per_example']} s/example  "
          f"cache hits {u['cache_hits']}  failures {u['failures']}")
    print(f"  -> {out}")
    if not args.no_append:
        append_results(os.path.join(args.out, "..", "RESULTS.md") if args.out == "results"
                       else os.path.join(args.out, "RESULTS.md"), results_row(res, args.split))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
