"""Turn dataset examples into what a VLM sees, and parse what it says back.

The dataset stores messages in a neutral form (text blocks + image paths).
Qwen2.5-VL's chat template wants `{"type": "image", "image": <path>}` blocks and
a plain string for the assistant turn; `to_qwen_messages` does that mapping.
`parse_prediction` is deliberately tolerant: a fine-tuned model emits clean
JSON, but a zero-shot one may wrap it in prose or code fences.
"""
from __future__ import annotations

import json
import re

from .schema import Prediction

JSON_INSTRUCTION = ('Reply with ONLY a JSON object: {"rating": "clean|minor|concern|bad", '
                    '"panel": "carpet|coreg|t1norm|multiple|none", '
                    '"failure_type": "truncated_fov|saturated_epi|misregistration|skull_strip|'
                    'carpet_block|ghosting|motion|other|none", "note": "<=140 chars"}')


def to_qwen_messages(example: dict, include_assistant: bool = False,
                     max_pixels: int | None = None) -> list[dict]:
    system, user, assistant = example["messages"][:3]
    content = []
    for block in user["content"]:
        if block["type"] == "text":
            content.append({"type": "text", "text": block["text"]})
        else:
            img = {"type": "image", "image": block["path"]}
            if max_pixels:
                img["max_pixels"] = max_pixels
            content.append(img)
    content.append({"type": "text", "text": JSON_INSTRUCTION})
    msgs = [{"role": "system", "content": system["content"]},
            {"role": "user", "content": content}]
    if include_assistant:
        msgs.append({"role": "assistant", "content": assistant["content"]})
    return msgs


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_prediction(text: str) -> dict:
    """Extract the first JSON object from model text and validate it."""
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no JSON object in model output: {text[:120]!r}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = json.loads(text[start:i + 1])
                raw = {k: (v.strip().lower() if isinstance(v, str) and k != "note" else v)
                       for k, v in raw.items()}
                return Prediction.model_validate(raw).model_dump()
    raise ValueError("unbalanced JSON in model output")
