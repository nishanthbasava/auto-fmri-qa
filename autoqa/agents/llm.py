"""Thin Anthropic API wrapper: forced tool calls, retries, and cost accounting.

Reads ANTHROPIC_API_KEY from the environment; a .env file in the cwd (or any
parent) is loaded automatically if python-dotenv is installed. Never commit
.env -- it is gitignored.

    result = ask_tool(system, content, REVIEW_TOOL)
    result.input   -> dict, the tool's arguments (well-formed JSON guaranteed by the API)
    result.usage   -> {"input_tokens", "output_tokens", "cache_read_input_tokens",
                       "cache_creation_input_tokens", "usd"}

Retries: rate limits (429), overloaded (529), and connection errors are retried
with exponential backoff + jitter; anything else is raised immediately.
"""
from __future__ import annotations

import base64
import os
import random
import time
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()  # searches cwd upward for .env; real env vars take precedence
except ImportError:
    pass

MODEL = os.environ.get("AFQ_MODEL", "claude-sonnet-4-5")

# USD per million tokens: (input, output, cache write, cache read).
# Snapshot of published list prices; override with AFQ_PRICE_IN/OUT if they change.
PRICES = {
    "claude-sonnet-4-5": (3.00, 15.00, 3.75, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-opus-4-1": (15.00, 75.00, 18.75, 1.50),
}
RETRYABLE_STATUS = {429, 529, 500, 502, 503}


@dataclass
class ToolResult:
    input: dict
    usage: dict
    model: str
    attempts: int


def client():
    import anthropic
    return anthropic.Anthropic()


def image_block(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def price(model: str):
    if "AFQ_PRICE_IN" in os.environ:
        return (float(os.environ["AFQ_PRICE_IN"]), float(os.environ["AFQ_PRICE_OUT"]),
                float(os.environ.get("AFQ_PRICE_CACHE_W", os.environ["AFQ_PRICE_IN"])),
                float(os.environ.get("AFQ_PRICE_CACHE_R", os.environ["AFQ_PRICE_IN"])))
    for key, p in PRICES.items():
        if model.startswith(key):
            return p
    return None


def usage_dict(usage, model: str) -> dict:
    u = {"input_tokens": getattr(usage, "input_tokens", 0) or 0,
         "output_tokens": getattr(usage, "output_tokens", 0) or 0,
         "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
         "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0}
    p = price(model)
    if p:
        i, o, cw, cr = p
        u["usd"] = round((u["input_tokens"] * i + u["output_tokens"] * o
                          + u["cache_creation_input_tokens"] * cw
                          + u["cache_read_input_tokens"] * cr) / 1e6, 5)
    return u


def _is_retryable(e) -> bool:
    status = getattr(e, "status_code", None)
    if status in RETRYABLE_STATUS:
        return True
    name = type(e).__name__
    return name in ("RateLimitError", "APIConnectionError", "APITimeoutError",
                    "InternalServerError", "OverloadedError")


def ask_tool(system: str, content: list, tool: dict, *, model: str | None = None,
             max_tokens: int = 2000, max_attempts: int = 5, base_delay: float = 2.0,
             _client=None, _sleep=time.sleep) -> ToolResult:
    """One forced tool call. The system prompt is marked cacheable so repeated
    batches pay the full prompt once (prompt caching)."""
    model = model or MODEL
    c = _client or client()
    attempts = 0
    while True:
        attempts += 1
        try:
            msg = c.messages.create(
                model=model, max_tokens=max_tokens,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[{"role": "user", "content": content}])
        except Exception as e:
            if attempts < max_attempts and _is_retryable(e):
                delay = base_delay * (2 ** (attempts - 1)) * (1 + random.random() * 0.25)
                _sleep(delay)
                continue
            raise
        block = next((b for b in msg.content if getattr(b, "type", None) == "tool_use"), None)
        if block is None:
            raise RuntimeError("model returned no tool_use block despite forced tool_choice")
        return ToolResult(input=dict(block.input), usage=usage_dict(msg.usage, model),
                          model=model, attempts=attempts)
