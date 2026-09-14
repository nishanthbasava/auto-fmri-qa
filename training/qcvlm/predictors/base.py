from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod

from ..schema import Prediction


class Predictor(ABC):
    """One example in, one validated prediction out, with cost/latency tracked.

    Subclasses implement `_predict(example) -> dict`. This base class validates
    the dict against the schema, times the call, and (optionally) caches
    results on disk keyed by (predictor id, example id, image hashes) so
    re-running an evaluation is free."""

    name = "base"

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = cache_dir
        self.n = 0
        self.seconds = 0.0
        self.usd = 0.0
        self.cache_hits = 0
        self.failures = 0

    def ident(self) -> str:
        return self.name

    @abstractmethod
    def _predict(self, example: dict) -> dict: ...

    def _cache_key(self, example: dict) -> str:
        h = hashlib.sha256(self.ident().encode())
        h.update(example["id"].encode())
        for p in example.get("images", []):
            try:
                with open(p, "rb") as f:
                    h.update(hashlib.sha256(f.read()).digest())
            except OSError:
                h.update(p.encode())
        h.update(example["messages"][1]["content"][0]["text"].encode())
        return h.hexdigest()

    def predict(self, example: dict) -> dict:
        path = None
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
            path = os.path.join(self.cache_dir, self._cache_key(example) + ".json")
            if os.path.exists(path):
                with open(path) as f:
                    self.cache_hits += 1
                    return json.load(f)
        t0 = time.perf_counter()
        try:
            raw = self._predict(example)
            pred = Prediction.model_validate(raw).model_dump()
        except Exception as e:                      # a failed call is a wrong answer, not a crash
            self.failures += 1
            pred = {"rating": "clean", "panel": "none", "failure_type": "none",
                    "note": f"PREDICTOR_ERROR: {type(e).__name__}: {e}"[:200]}
        self.seconds += time.perf_counter() - t0
        self.n += 1
        if path:
            with open(path, "w") as f:
                json.dump(pred, f)
        return pred

    def usage(self) -> dict:
        return {"predictor": self.ident(), "n": self.n, "cache_hits": self.cache_hits,
                "failures": self.failures, "seconds": round(self.seconds, 2),
                "s_per_example": round(self.seconds / self.n, 3) if self.n else None,
                "usd": round(self.usd, 5),
                "usd_per_1k": round(1000 * self.usd / self.n, 2) if self.n else None}
