"""Thin Anthropic API wrapper.

Reads ANTHROPIC_API_KEY from the environment; a .env file in the repo root
(or any parent of the cwd) is loaded automatically if python-dotenv is
installed. Never commit .env -- it is gitignored.
"""
import base64
import json
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # searches cwd upward for .env; real env vars take precedence
except ImportError:
    pass

MODEL = os.environ.get("AFQ_MODEL", "claude-sonnet-4-5")


def client():
    import anthropic
    return anthropic.Anthropic()


def image_block(path: str) -> dict:
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def ask_json(system: str, content: list, max_tokens: int = 4000):
    """One call, expects a JSON body in the reply; tolerates code fences."""
    msg = client().messages.create(
        model=MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": content}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    return json.loads(text)
