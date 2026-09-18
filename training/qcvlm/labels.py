"""Labeling sheets, inter-rater agreement, and gold-label merging.

    python -m qcvlm.labels export RUN_DIR -o data/labels/sheet_<rater>.csv
                                 [--only flagged] [--sample-clean N] [--seed S]
    python -m qcvlm.labels agreement sheet_A.csv sheet_B.csv [...]
    python -m qcvlm.labels merge sheet_A.csv sheet_B.csv [--adjudicated adj.csv] -o data/labels/gold.jsonl

Export writes one row per scan with the rendered figure paths and the pipeline
metrics for context, plus empty rating/panel/failure_type/note columns for the
rater to fill (any spreadsheet app). Import parses filled sheets, validates
every value against the schema, and reports Cohen's kappa (2 raters) or Fleiss'
kappa (3+) per field. Merge keeps unanimous labels and takes the rest from an
adjudication sheet; anything still unresolved is listed, never guessed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import Counter
from itertools import combinations

from pydantic import ValidationError

from .schema import COARSE, FAILURE_TYPES, RATINGS, Label, coarse

SHEET_COLUMNS = ["key", "sub", "ses", "status", "mean_fd", "outlier_percent", "tr", "vendor",
                 "carpet", "coreg", "t1norm", "rating", "panel", "failure_type", "note"]


# ------------------------------------------------------------------ export

def export_sheet(run_dir: str, out_csv: str, only: str = "all",
                 sample_clean: int = 0, seed: int = 7) -> int:
    """One row per scan to label. With only="flagged", sample_clean adds a seeded
    random draw of clean INCLUDEs so the labeled pool is not all pathology."""
    with open(os.path.join(run_dir, "state.json")) as f:
        state = json.load(f)
    keys = sorted(state["scans"])
    if only == "flagged":
        clean = [k for k in keys if state["scans"][k]["status"] == "INCLUDE"
                 and not state["scans"][k].get("verify_flags")]
        keep = set(keys) - set(clean)
        if sample_clean:
            keep |= set(random.Random(seed).sample(clean, min(sample_clean, len(clean))))
        keys = [k for k in keys if k in keep]
    rows = []
    for key in keys:
        s = state["scans"][key]
        m = s.get("metrics", {})
        r = s.get("rendered", {})
        rows.append({"key": key, "sub": s["sub"], "ses": s["ses"], "status": s["status"],
                     "mean_fd": m.get("mean_fd"), "outlier_percent": m.get("outlier_percent"),
                     "tr": m.get("tr"), "vendor": s.get("vendor") or "",
                     "carpet": r.get("carpet", ""), "coreg": r.get("coreg", ""),
                     "t1norm": r.get("t1norm", ""),
                     "rating": "", "panel": "", "failure_type": "", "note": ""})
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


# ------------------------------------------------------------------ import

def read_sheet(path: str, rater: str | None = None) -> dict[str, Label]:
    """Parse a filled sheet -> {key: Label}. Rows with an empty rating are skipped
    (unlabeled); invalid values raise with the row named."""
    rater = rater or os.path.splitext(os.path.basename(path))[0].replace("sheet_", "")
    out = {}
    with open(path, newline="") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            if not (row.get("rating") or "").strip():
                continue
            try:
                lab = Label(key=row["key"], sub=row["sub"], ses=row["ses"],
                            rating=row["rating"].strip().lower(),
                            panel=(row.get("panel") or "none").strip().lower() or "none",
                            failure_type=(row.get("failure_type") or "none").strip().lower() or "none",
                            note=(row.get("note") or "").strip(), rater=rater)
            except ValidationError as e:
                raise ValueError(f"{path} line {i} ({row.get('key')}): {e.errors()[0]['msg']}") from e
            out[lab.key] = lab
    return out


# ------------------------------------------------------------------ agreement

def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Chance-corrected agreement between two raters over the same items."""
    assert len(a) == len(b) and a, "need paired, non-empty label lists"
    n = len(a)
    po = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1.0 else (po - pe) / (1 - pe)


def fleiss_kappa(ratings: list[list[str]], categories: tuple[str, ...]) -> float:
    """ratings[i] = the labels given to item i by every rater (same count per item)."""
    n_raters = len(ratings[0])
    assert all(len(r) == n_raters for r in ratings) and n_raters >= 2
    N = len(ratings)
    p_j = {c: 0 for c in categories}
    P_i = []
    for r in ratings:
        counts = Counter(r)
        for c, k in counts.items():
            p_j[c] += k
        P_i.append((sum(k * k for k in counts.values()) - n_raters) / (n_raters * (n_raters - 1)))
    p_j = {c: v / (N * n_raters) for c, v in p_j.items()}
    P_bar = sum(P_i) / N
    P_e = sum(v * v for v in p_j.values())
    return 1.0 if P_e == 1.0 else (P_bar - P_e) / (1 - P_e)


def agreement(sheets: dict[str, dict[str, Label]]) -> dict:
    """Kappa per field on the items every rater labeled, plus the disagreements."""
    raters = sorted(sheets)
    common = sorted(set.intersection(*(set(s) for s in sheets.values())))
    fields = {"rating": (lambda lab: lab.rating, RATINGS),
              "coarse": (lambda lab: coarse(lab.rating), COARSE),
              "failure_type": (lambda lab: lab.failure_type, FAILURE_TYPES)}
    report = {"raters": raters, "n_common": len(common), "kappa": {}, "pairwise": {},
              "disagreements": []}
    if not common:
        return report
    for name, (get, cats) in fields.items():
        cols = {r: [get(sheets[r][k]) for k in common] for r in raters}
        if len(raters) == 2:
            report["kappa"][name] = round(cohen_kappa(cols[raters[0]], cols[raters[1]]), 3)
        else:
            report["kappa"][name] = round(fleiss_kappa(
                [[cols[r][i] for r in raters] for i in range(len(common))], cats), 3)
            report["pairwise"][name] = {
                f"{a}~{b}": round(cohen_kappa(cols[a], cols[b]), 3) for a, b in combinations(raters, 2)}
    for k in common:
        labs = {r: sheets[r][k] for r in raters}
        if len({(lab.rating, lab.failure_type) for lab in labs.values()}) > 1:
            report["disagreements"].append(
                {"key": k, **{r: f"{lab.rating}/{lab.failure_type}" for r, lab in labs.items()}})
    return report


# ------------------------------------------------------------------ merge

def merge(sheets: dict[str, dict[str, Label]], adjudicated: dict[str, Label] | None = None
          ) -> tuple[list[Label], list[str]]:
    """Gold labels: unanimous (rating + failure_type) wins; disagreements are
    taken from the adjudication sheet; anything else is unresolved."""
    adjudicated = adjudicated or {}
    keys = sorted(set().union(*(set(s) for s in sheets.values())))
    gold, unresolved = [], []
    for k in keys:
        labs = [s[k] for s in sheets.values() if k in s]
        if len({(lab.rating, lab.failure_type) for lab in labs}) == 1:
            lab = labs[0].model_copy(update={"rater": "+".join(sorted(sheets))
                                             if len(labs) > 1 else labs[0].rater})
        elif k in adjudicated:
            lab = adjudicated[k].model_copy(update={"rater": "adjudicated"})
        else:
            unresolved.append(k)
            continue
        gold.append(lab)
    return gold, unresolved


def write_gold(labels: list[Label], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        for lab in labels:
            f.write(json.dumps(lab.model_dump()) + "\n")


def read_gold(path: str) -> list[Label]:
    with open(path) as f:
        return [Label.model_validate(json.loads(line)) for line in f if line.strip()]


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("export")
    e.add_argument("run_dir")
    e.add_argument("-o", "--out", required=True)
    e.add_argument("--only", choices=["all", "flagged"], default="all")
    e.add_argument("--sample-clean", type=int, default=0, metavar="N",
                   help="with --only flagged: also include N seeded-random clean INCLUDEs")
    e.add_argument("--seed", type=int, default=7)
    a = sp.add_parser("agreement")
    a.add_argument("sheets", nargs="+")
    m = sp.add_parser("merge")
    m.add_argument("sheets", nargs="+")
    m.add_argument("--adjudicated", default=None)
    m.add_argument("-o", "--out", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "export":
        n = export_sheet(args.run_dir, args.out, args.only, args.sample_clean, args.seed)
        print(f"wrote {n} rows -> {args.out}; fill rating/panel/failure_type/note and re-import")
        return 0
    sheets = {}
    for p in args.sheets:
        labs = read_sheet(p)
        sheets[next(iter(labs.values())).rater if labs else p] = labs
    if args.cmd == "agreement":
        rep = agreement(sheets)
        print(f"raters: {', '.join(rep['raters'])}; items labeled by all: {rep['n_common']}")
        for field, k in rep["kappa"].items():
            print(f"  kappa[{field:13s}] = {k:.3f}")
        for field, pw in rep["pairwise"].items():
            print(f"  pairwise {field}: " + ", ".join(f"{p} {v:.3f}" for p, v in pw.items()))
        print(f"  disagreements: {len(rep['disagreements'])}")
        for d in rep["disagreements"][:40]:
            print("   ", d)
        return 0
    adj = read_sheet(args.adjudicated, rater="adjudicated") if args.adjudicated else None
    gold, unresolved = merge(sheets, adj)
    write_gold(gold, args.out)
    dist = Counter(lab.rating for lab in gold)
    print(f"gold labels: {len(gold)} -> {args.out}  {dict(dist)}")
    if unresolved:
        print(f"UNRESOLVED ({len(unresolved)}): adjudicate these and re-run:", file=sys.stderr)
        for k in unresolved:
            print("   ", k, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
