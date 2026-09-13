"""Agent layer tests with a fake Anthropic client: no network, no API key."""
import json
import os
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

import autoqa
from autoqa.agents import llm, rag, review_figures
from autoqa.agents.schemas import REVIEW_TOOL, ReviewBatch

# ----------------------------------------------------------------- fakes

class FakeClient:
    """Scripted responses: each item is either a dict (tool input), an
    Exception (raised), or a callable(request kwargs) -> dict."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(kw)
        block = SimpleNamespace(type="tool_use", name=REVIEW_TOOL["name"], input=item)
        usage = SimpleNamespace(input_tokens=1200, output_tokens=80,
                                cache_read_input_tokens=1000, cache_creation_input_tokens=0)
        return SimpleNamespace(content=[block], usage=usage)


def _reviews_for(kw, rating="clean", note=""):
    """Build a valid reply from the scan headers in the request."""
    out = []
    for block in kw["messages"][0]["content"]:
        if block["type"] == "text" and block["text"].startswith("Scan: sub="):
            head = block["text"].split(";")[0]
            sub = head.split("sub=")[1].split()[0]
            ses = head.split("ses=")[1].split()[0]
            out.append({"sub": sub, "ses": ses, "rating": rating,
                        "panel": "none" if rating == "clean" else "coreg", "note": note})
    return {"reviews": out}


class RetryableError(Exception):
    status_code = 429


@pytest.fixture
def rendered_run(cohort, tmp_path):
    """A run whose scans have (tiny, fake) rendered JPEGs, as after --render."""
    root, _ = cohort
    run = tmp_path / "run"
    autoqa.qc(str(root), out=str(run), quiet=True)
    state = json.load(open(run / "state.json"))
    figdir = run / "figures"
    figdir.mkdir()
    keys = sorted(state["scans"])[:6]           # keep it small
    state["scans"] = {k: state["scans"][k] for k in keys}
    for s in state["scans"].values():
        s["rendered"] = {}
        for kind in ("carpet", "coreg", "t1norm"):
            p = figdir / f"{s['sub']}_{s['ses']}_{kind}.jpg"
            Image.new("RGB", (8, 8), (40, 40, 40)).save(p)
            s["rendered"][kind] = str(p)
    json.dump(state, open(run / "state.json", "w"))
    return run


# ----------------------------------------------------------------- llm

def test_ask_tool_retries_then_succeeds():
    fake = FakeClient([RetryableError("rate limited"), RetryableError("overloaded"),
                       {"reviews": [{"sub": "s", "ses": "v", "rating": "clean", "panel": "none"}]}])
    sleeps = []
    res = llm.ask_tool("sys", [{"type": "text", "text": "x"}], REVIEW_TOOL,
                       model="claude-sonnet-4-5", _client=fake, _sleep=sleeps.append)
    assert res.attempts == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0]
    assert res.input["reviews"][0]["rating"] == "clean"
    # cost: 1200 in @3 + 80 out @15 + 1000 cache read @0.30 per Mtok
    assert res.usage["usd"] == pytest.approx((1200 * 3 + 80 * 15 + 1000 * 0.30) / 1e6, abs=1e-6)
    req = fake.calls[-1]
    assert req["tool_choice"] == {"type": "tool", "name": "record_reviews"}
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_ask_tool_gives_up_on_non_retryable():
    class Fatal(Exception):
        status_code = 400
    fake = FakeClient([Fatal("bad request")])
    with pytest.raises(Fatal):
        llm.ask_tool("sys", [], REVIEW_TOOL, _client=fake, _sleep=lambda s: None)


def test_schema_rejects_bad_values():
    with pytest.raises(ValidationError):
        ReviewBatch.model_validate({"reviews": [{"sub": "a", "ses": "b", "rating": "meh", "panel": "none"}]})
    with pytest.raises(ValidationError):
        ReviewBatch.model_validate({"reviews": []})
    assert REVIEW_TOOL["input_schema"]["properties"]["reviews"]


# ----------------------------------------------------------------- rag

def test_fallback_retrieval_finds_protocol_passages():
    hits = rag.retrieve("multiband fast TR respiratory pseudomotion", k=2)
    assert hits and any("pseudomotion" in h["section"].lower() or "multiband" in h["section"].lower()
                        or "pseudomotion" in h["text"].lower() for h in hits)
    assert {"file", "section", "text", "distance"} <= set(hits[0])


def test_context_is_scan_specific_and_deduplicated():
    fast = {"sub": "a", "ses": "b", "tr": 0.607, "metrics": {"tr": 0.607, "n_volumes": 976},
            "rendered": {"carpet": "x", "coreg": "y"}}
    slow = {"sub": "c", "ses": "d", "tr": 3.0, "vendor": "Philips",
            "metrics": {"tr": 3.0, "n_volumes": 197}, "rendered": {"carpet": "x"}}
    assert "pseudomotion" in rag.scan_query(fast) and "Philips" in rag.scan_query(slow)
    ctx = rag.context_for_scans([fast, fast, slow], k=2, cap=4)
    keys = [(p["file"], p["section"]) for p in ctx]
    assert len(keys) == len(set(keys)) and 1 <= len(ctx) <= 4
    text = rag.format_context(ctx)
    assert text.startswith("Reference notes") and "[1]" in text
    assert rag.format_context([]) == ""


# ----------------------------------------------------------------- review loop

def test_review_writes_grounded_results_and_costs(rendered_run):
    fake = FakeClient([lambda kw: _reviews_for(kw), lambda kw: _reviews_for(kw, "bad", "truncated FOV")])
    rc = review_figures.main([str(rendered_run), "--batch", "3"], _client=fake, _sleep=lambda s: None)
    assert rc == 0 and len(fake.calls) == 2
    state = json.load(open(rendered_run / "state.json"))
    reviews = [s["review"] for s in state["scans"].values()]
    assert len(reviews) == 6 and all(r["context"] for r in reviews)   # grounded: passages recorded
    bad = [s for s in state["scans"].values() if s["review"]["rating"] == "bad"]
    assert len(bad) == 3 and all(any("visual review (bad)" in f for f in s["verify_flags"]) for s in bad)
    assert all(s["status"] in ("INCLUDE", "CAUTION", "EXCLUDE") for s in bad)   # status untouched
    assert all("citations" in s["review"] for s in bad)
    stage = state["stages"]["review"]
    assert stage["batches"] == 2 and stage["scans"] == 6 and stage["rag"] is True
    assert stage["usage"]["usd"] > 0 and stage["usage"]["input_tokens"] == 2400
    first = fake.calls[0]["messages"][0]["content"]
    assert first[0]["text"].startswith("Reference notes")
    assert sum(1 for b in first if b["type"] == "image") == 9   # 3 scans x 3 figures
    assert os.path.exists(rendered_run / "review.json")


def test_no_rag_omits_reference_notes(rendered_run):
    fake = FakeClient([lambda kw: _reviews_for(kw)] * 2)
    review_figures.main([str(rendered_run), "--batch", "3", "--no-rag"], _client=fake, _sleep=lambda s: None)
    first = fake.calls[0]["messages"][0]["content"]
    assert not first[0]["text"].startswith("Reference notes")
    state = json.load(open(rendered_run / "state.json"))
    assert state["stages"]["review"]["rag"] is False
    assert all(s["review"]["context"] == [] for s in state["scans"].values())


def test_invalid_output_is_retried_then_recorded_as_failure(rendered_run):
    # batch 1: garbage, then valid  -> succeeds on retry with the error shown to the model
    # batch 2: garbage twice        -> recorded as a failed batch, scans left unreviewed
    fake = FakeClient([{"reviews": [{"sub": "x", "ses": "y", "rating": "clean", "panel": "none"}]},
                       lambda kw: _reviews_for(kw),
                       {"nonsense": 1}, {"nonsense": 2}])
    rc = review_figures.main([str(rendered_run), "--batch", "3"], _client=fake, _sleep=lambda s: None)
    assert rc == 1
    retry_msg = fake.calls[1]["messages"][0]["content"][-1]["text"]
    assert "rejected" in retry_msg and "no review for" in retry_msg
    state = json.load(open(rendered_run / "state.json"))
    reviewed = [s for s in state["scans"].values() if "review" in s]
    assert len(reviewed) == 3
    assert state["stages"]["review"]["failed_batches"] == 1


def test_dry_run_prints_prompt_without_calling_model(rendered_run, capsys):
    fake = FakeClient([])
    rc = review_figures.main([str(rendered_run), "--dry-run"], _client=fake, _sleep=lambda s: None)
    out = capsys.readouterr().out
    assert rc == 0 and not fake.calls
    assert "record_reviews" in out and "Reference notes" in out and "<image>" in out


def test_only_flagged_and_resume(rendered_run):
    fake = FakeClient([lambda kw: _reviews_for(kw)] * 4)
    review_figures.main([str(rendered_run), "--only", "flagged"], _client=fake, _sleep=lambda s: None)
    state = json.load(open(rendered_run / "state.json"))
    assert all("review" in s for s in state["scans"].values() if s["status"] != "INCLUDE")
    n_first = len(fake.calls)
    review_figures.main([str(rendered_run)], _client=fake, _sleep=lambda s: None)   # resumes: only unreviewed
    state = json.load(open(rendered_run / "state.json"))
    assert all("review" in s for s in state["scans"].values())
    assert len(fake.calls) >= n_first
