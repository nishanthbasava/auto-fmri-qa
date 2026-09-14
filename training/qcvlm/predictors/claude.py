"""Claude API baseline: the same prompt, images, and tool contract as the
production review agent, one scan per call so every prediction is attributable
and costed. Reuses autoqa.agents.llm (forced tool call, retries, pricing)."""
from __future__ import annotations

import os

from autoqa.agents import llm

from ..schema import PREDICTION_TOOL
from .base import Predictor


class ClaudePredictor(Predictor):
    name = "claude"

    def __init__(self, model: str | None = None, max_tokens: int = 400, _client=None, **kw):
        super().__init__(**kw)
        self.model = model or llm.MODEL
        self.max_tokens = max_tokens
        self._client = _client

    def ident(self) -> str:
        return f"claude:{self.model}"

    def _predict(self, example: dict) -> dict:
        system = example["messages"][0]["content"]
        content = []
        for block in example["messages"][1]["content"]:
            if block["type"] == "text":
                content.append({"type": "text", "text": block["text"]})
            else:
                if os.path.exists(block["path"]):
                    content.append(llm.image_block(block["path"]))
        content.append({"type": "text", "text": "Review this scan and call record_review."})
        res = llm.ask_tool(system, content, PREDICTION_TOOL, model=self.model,
                           max_tokens=self.max_tokens, _client=self._client)
        self.usd += res.usage.get("usd", 0.0)
        return res.input
