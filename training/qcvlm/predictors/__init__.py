"""Predictors: anything that maps one dataset example -> a Prediction.

    from qcvlm.predictors import get_predictor
    p = get_predictor("claude", model="claude-sonnet-4-5")
    pred = p.predict(example)          # {"rating","panel","failure_type","note"}
    p.usage()                          # {"n","usd","seconds", ...}

Registered names: stub (tests), claude (API baseline), qwen / qwen-lora (GPU;
added with the fine-tuning work).
"""
from __future__ import annotations

from .base import Predictor


def get_predictor(name: str, **kw) -> Predictor:
    if name == "stub":
        from .stub import StubPredictor
        return StubPredictor(**kw)
    if name == "claude":
        from .claude import ClaudePredictor
        return ClaudePredictor(**kw)
    if name in ("qwen", "qwen-lora"):
        from .qwen import QwenPredictor
        return QwenPredictor(adapter=kw.pop("adapter", None) if name == "qwen-lora" else None, **kw)
    raise ValueError(f"unknown predictor {name!r}")
