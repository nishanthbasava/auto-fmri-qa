"""Deterministic predictor for tests and dry runs: answers from a mapping,
otherwise echoes the gold label with a configurable error rate."""
from __future__ import annotations

import random

from ..schema import RATINGS
from .base import Predictor


class StubPredictor(Predictor):
    name = "stub"

    def __init__(self, answers: dict | None = None, error_rate: float = 0.0, seed: int = 0, **kw):
        super().__init__(**kw)
        self.answers = answers or {}
        self.error_rate = error_rate
        self.rng = random.Random(seed)

    def ident(self) -> str:
        return f"stub:err={self.error_rate}"

    def _predict(self, example: dict) -> dict:
        if example["id"] in self.answers:
            return self.answers[example["id"]]
        lab = dict(example["label"])
        if self.rng.random() < self.error_rate:
            lab["rating"] = self.rng.choice([r for r in RATINGS if r != lab["rating"]])
        return lab
