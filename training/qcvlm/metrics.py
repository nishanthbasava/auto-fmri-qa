"""Classification metrics with subject-level bootstrap confidence intervals.

Pure Python on purpose: the harness must run anywhere (CI, a laptop, the lab
machine) without numpy/sklearn; sklearn parity is checked in the tests.

Why bootstrap over SUBJECTS: two sessions of one subject are not independent
samples, so resampling scans would understate the interval.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence


def confusion(y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]) -> dict:
    m = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred, strict=True):
        m[t][p] += 1
    return m


def per_class(y_true, y_pred, labels) -> dict[str, dict]:
    out = {}
    for c in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[c] = {"precision": prec, "recall": rec, "f1": f1, "support": tp + fn}
    return out


def macro_f1(y_true, y_pred, labels) -> float:
    """Unweighted mean of per-class F1 over the classes that occur in y_true or
    y_pred (sklearn's default) -- every present class counts equally, so the
    rare 'bad' class is not drowned out by the common 'clean' one, and a class
    absent from a small test split does not score a spurious zero."""
    present = [c for c in labels if c in set(y_true) | set(y_pred)]
    if not present:
        return 0.0
    return sum(v["f1"] for v in per_class(y_true, y_pred, present).values()) / len(present)


def accuracy(y_true, y_pred) -> float:
    return sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p) / len(y_true) if y_true else 0.0


def bootstrap_ci(y_true, y_pred, groups, fn: Callable, n: int = 1000, seed: int = 0,
                 alpha: float = 0.05) -> tuple[float, float]:
    """Percentile CI of fn(y_true, y_pred) under resampling of GROUPS (subjects)."""
    rng = random.Random(seed)
    by_group = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    keys = list(by_group)
    stats = []
    for _ in range(n):
        idx = [i for g in rng.choices(keys, k=len(keys)) for i in by_group[g]]
        stats.append(fn([y_true[i] for i in idx], [y_pred[i] for i in idx]))
    stats.sort()
    lo = stats[int(alpha / 2 * n)]
    hi = stats[min(n - 1, int((1 - alpha / 2) * n))]
    return lo, hi


def summarize(examples: list[dict], preds: list[dict], labels_rating: Sequence[str],
              labels_failure: Sequence[str], n_boot: int = 1000, seed: int = 0) -> dict:
    yt = [e["label"]["rating"] for e in examples]
    yp = [p["rating"] for p in preds]
    groups = [e["sub"] for e in examples]
    ft_t = [e["label"]["failure_type"] for e in examples]
    ft_p = [p.get("failure_type", "none") for p in preds]
    from .schema import coarse
    ct, cp = [coarse(t) for t in yt], [coarse(p) for p in yp]
    mf1 = macro_f1(yt, yp, labels_rating)
    lo, hi = bootstrap_ci(yt, yp, groups, lambda a, b: macro_f1(a, b, labels_rating), n_boot, seed)
    return {
        "n": len(examples), "n_subjects": len(set(groups)),
        "macro_f1": round(mf1, 4), "macro_f1_ci95": [round(lo, 4), round(hi, 4)],
        "accuracy": round(accuracy(yt, yp), 4),
        "coarse_macro_f1": round(macro_f1(ct, cp, ("usable", "needs_review", "unusable")), 4),
        "coarse_accuracy": round(accuracy(ct, cp), 4),
        "failure_type_accuracy": round(accuracy(ft_t, ft_p), 4),
        "per_class": {c: {k: round(v, 4) for k, v in d.items()} for c, d in
                      per_class(yt, yp, labels_rating).items()},
        "confusion": confusion(yt, yp, labels_rating),
        "label_distribution": dict(Counter(yt)),
    }
