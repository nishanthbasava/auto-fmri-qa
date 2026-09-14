"""Build train/validation/test splits from gold labels + a rendered run.

    python -m qcvlm.dataset --labels data/labels/gold.jsonl --run RUN_DIR \
        --out data/processed [--seed 7] [--split 0.7 0.15 0.15] [--with-context]

Rules that make the evaluation honest:
  * split by SUBJECT, never by scan -- both sessions of a subject land in the
    same split (sessions share anatomy and site, so a scan-level split leaks);
  * stratify by (coarse label, TR regime) so each split sees every class;
  * the test split is written once, seeded, and hashed in MANIFEST.json --
    every image's sha256 is recorded, so a result can be tied to exact inputs.

Each example is one scan in chat format (system / user with images / assistant
JSON), which is what both the API predictors and the SFT trainer consume.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections import Counter, defaultdict

from .labels import read_gold
from .schema import Label, coarse

SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "autoqa", "agents", "prompts", "figure_review.md")


def system_prompt() -> str:
    with open(SYSTEM_PROMPT_PATH) as f:
        return f.read()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def example(lab: Label, scan: dict, context: str = "") -> dict:
    m = scan.get("metrics", {})
    figs = scan.get("rendered", {})
    images = [figs[k] for k in ("carpet", "coreg", "t1norm") if figs.get(k)]
    tr = m.get("tr")
    header = (f"Scan: sub={scan['sub']} ses={scan['ses']}; TR {tr} s"
              + (" (multiband/fast-TR)" if tr and tr < 1.0 else "")
              + f"; {m.get('n_volumes', '?')} volumes; mean FD {m.get('mean_fd')}; "
              f"outliers {m.get('outlier_percent')}%"
              + (f"; scanner {scan['vendor']}" if scan.get("vendor") else ""))
    user_text = (context + "\n\n" if context else "") + header
    target = {"rating": lab.rating, "panel": lab.panel,
              "failure_type": lab.failure_type, "note": lab.note}
    return {
        "id": lab.key, "sub": lab.sub, "ses": lab.ses,
        "fast_tr": bool(tr and tr < 1.0), "status": scan.get("status"),
        "images": images,
        "label": target, "coarse": coarse(lab.rating),
        "messages": [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": [{"type": "text", "text": user_text}]
                                        + [{"type": "image", "path": p} for p in images]},
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def split_subjects(examples: list[dict], seed: int, fractions=(0.7, 0.15, 0.15)) -> dict[str, str]:
    """subject -> split. Greedy stratified assignment: subjects are grouped by
    their (coarse, fast_tr) stratum, shuffled, and dealt out so every stratum is
    represented in every split in roughly the requested proportions."""
    rng = random.Random(seed)
    by_sub = defaultdict(list)
    for ex in examples:
        by_sub[ex["sub"]].append(ex)
    # a subject's stratum = its worst coarse label + TR regime
    order = {"usable": 0, "needs_review": 1, "unusable": 2}
    strata = defaultdict(list)
    for sub, exs in by_sub.items():
        worst = max((e["coarse"] for e in exs), key=order.get)
        strata[(worst, exs[0]["fast_tr"])].append(sub)
    names = ("train", "validation", "test")
    assign = {}
    for _stratum, subs in sorted(strata.items()):
        rng.shuffle(subs)
        n = len(subs)
        n_val = round(n * fractions[1])
        n_test = round(n * fractions[2])
        if n >= 3:
            n_val, n_test = max(1, n_val), max(1, n_test)
        for i, sub in enumerate(subs):
            if i < n_test:
                assign[sub] = names[2]
            elif i < n_test + n_val:
                assign[sub] = names[1]
            else:
                assign[sub] = names[0]
    return assign


def build(labels_path: str, run_dir: str, out_dir: str, seed: int = 7,
          fractions=(0.7, 0.15, 0.15), with_context: bool = False) -> dict:
    with open(os.path.join(run_dir, "state.json")) as f:
        state = json.load(f)
    labels = read_gold(labels_path)
    examples, skipped = [], []
    for lab in labels:
        scan = state["scans"].get(lab.key)
        if not scan or not scan.get("rendered"):
            skipped.append(lab.key)
            continue
        ctx = ""
        if with_context:
            from autoqa.agents import rag
            ctx = rag.format_context(rag.context_for_scans([scan], k=2))
        examples.append(example(lab, scan, ctx))
    assign = split_subjects(examples, seed, fractions)
    os.makedirs(out_dir, exist_ok=True)
    files = {s: open(os.path.join(out_dir, f"{s}.jsonl"), "w") for s in ("train", "validation", "test")}
    counts = {s: Counter() for s in files}
    manifest = {"seed": seed, "fractions": list(fractions), "labels": os.path.abspath(labels_path),
                "run_dir": os.path.abspath(run_dir), "with_context": with_context,
                "skipped_unrendered": skipped, "images": {}, "examples": {}}
    for ex in examples:
        split = assign[ex["sub"]]
        ex["split"] = split
        files[split].write(json.dumps(ex) + "\n")
        counts[split][ex["label"]["rating"]] += 1
        manifest["examples"][ex["id"]] = split
        for p in ex["images"]:
            manifest["images"].setdefault(p, sha256(p))
    for f in files.values():
        f.close()
    manifest["counts"] = {s: dict(c) for s, c in counts.items()}
    manifest["n_subjects"] = {s: len({e["sub"] for e in examples if assign[e["sub"]] == s}) for s in files}
    with open(os.path.join(out_dir, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    write_data_card(manifest, os.path.join(out_dir, "DATA_CARD.md"))
    return manifest


def write_data_card(m: dict, path: str) -> None:
    lines = ["# Data card: AutoQA figure-review dataset", "",
             f"Built from `{m['run_dir']}` with labels `{m['labels']}` (seed {m['seed']}, "
             f"split {m['fractions']} by subject).", "",
             "| split | scans | subjects | " + " | ".join(("clean", "minor", "concern", "bad")) + " |",
             "|---|---|---|---|---|---|---|"]
    for s in ("train", "validation", "test"):
        c = m["counts"][s]
        lines.append(f"| {s} | {sum(c.values())} | {m['n_subjects'][s]} | "
                     + " | ".join(str(c.get(r, 0)) for r in ("clean", "minor", "concern", "bad")) + " |")
    lines += ["", f"Images: {len(m['images'])} rendered fMRIPrep reportlets (JPEG), sha256 in MANIFEST.json.",
              f"Reference notes in the prompt: {'yes' if m['with_context'] else 'no'}.",
              "", "Subjects never straddle splits. The test split is frozen: do not re-split after "
              "looking at test results.",
              "", "Source data is ADNI (DUA-restricted): the JSONL and images are gitignored; only this "
              "card and the manifest are committed."]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def load_split(out_dir: str, split: str) -> list[dict]:
    with open(os.path.join(out_dir, f"{split}.jsonl")) as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--split", type=float, nargs=3, default=(0.7, 0.15, 0.15))
    ap.add_argument("--with-context", action="store_true", help="embed RAG reference notes")
    args = ap.parse_args(argv)
    m = build(args.labels, args.run, args.out, args.seed, tuple(args.split), args.with_context)
    for s in ("train", "validation", "test"):
        print(f"{s:10s} {sum(m['counts'][s].values()):4d} scans / {m['n_subjects'][s]:3d} subjects  {m['counts'][s]}")
    if m["skipped_unrendered"]:
        print(f"skipped {len(m['skipped_unrendered'])} labeled scans with no rendered figures")
    print(f"wrote {args.out}/{{train,validation,test}}.jsonl, MANIFEST.json, DATA_CARD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
