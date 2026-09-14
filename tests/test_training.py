"""qcvlm: labels/kappa, dataset splits, metrics (vs sklearn when present), harness."""
import csv
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from qcvlm import dataset, evaluate, labels, metrics
from qcvlm.predictors import get_predictor
from qcvlm.schema import FAILURE_TYPES, RATINGS, Label, coarse

import autoqa

# ----------------------------------------------------------------- fixtures


@pytest.fixture
def rendered_run(cohort, tmp_path):
    root, _ = cohort
    run = tmp_path / "run"
    autoqa.qc(str(root), out=str(run), quiet=True)
    state = json.load(open(run / "state.json"))
    (run / "figures").mkdir()
    for s in state["scans"].values():
        s["rendered"] = {}
        for kind in ("carpet", "coreg", "t1norm"):
            p = run / "figures" / f"{s['sub']}_{s['ses']}_{kind}.jpg"
            Image.new("RGB", (8, 8), (10, 20, 30)).save(p)
            s["rendered"][kind] = str(p)
    json.dump(state, open(run / "state.json", "w"))
    return run


def _fill(sheet_in, sheet_out, rater, chooser):
    rows = list(csv.DictReader(open(sheet_in)))
    for i, r in enumerate(rows):
        rating, ft = chooser(i, r)
        r.update(rating=rating, panel="coreg" if rating != "clean" else "", failure_type=ft, note="")
    with open(sheet_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=labels.SHEET_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return sheet_out


def _rating_by_status(i, r):
    return {"EXCLUDE": ("bad", "truncated_fov"), "CAUTION": ("concern", "carpet_block")}.get(
        r["status"], ("clean", "none"))


# ----------------------------------------------------------------- labels

def test_export_import_agreement_and_merge(rendered_run, tmp_path):
    sheet = tmp_path / "sheet.csv"
    n = labels.export_sheet(str(rendered_run), str(sheet))
    rows = list(csv.DictReader(open(sheet)))
    assert n == len(rows) > 10 and rows[0]["carpet"].endswith("_carpet.jpg") and rows[0]["rating"] == ""
    assert labels.export_sheet(str(rendered_run), str(tmp_path / "f.csv"), only="flagged") < n

    a = _fill(sheet, tmp_path / "sheet_A.csv", "A", _rating_by_status)
    # rater B disagrees on every 5th item
    b = _fill(sheet, tmp_path / "sheet_B.csv", "B",
              lambda i, r: ("minor", "ghosting") if i % 5 == 0 else _rating_by_status(i, r))
    sa, sb = labels.read_sheet(str(a)), labels.read_sheet(str(b))
    assert next(iter(sa.values())).rater == "A"
    rep = labels.agreement({"A": sa, "B": sb})
    assert rep["n_common"] == n and 0 < rep["kappa"]["rating"] < 1
    assert len(rep["disagreements"]) == len([i for i in range(n) if i % 5 == 0])
    assert rep["kappa"]["coarse"] >= rep["kappa"]["rating"] - 0.3   # coarser labels agree at least as well, roughly

    gold, unresolved = labels.merge({"A": sa, "B": sb})
    assert len(unresolved) == len(rep["disagreements"]) and len(gold) + len(unresolved) == n
    adj = _fill(sheet, tmp_path / "adj.csv", "adj", _rating_by_status)
    gold2, unresolved2 = labels.merge({"A": sa, "B": sb}, labels.read_sheet(str(adj), rater="adjudicated"))
    assert not unresolved2 and len(gold2) == n
    assert {g.rater for g in gold2} == {"A+B", "adjudicated"}
    labels.write_gold(gold2, str(tmp_path / "gold.jsonl"))
    assert len(labels.read_gold(str(tmp_path / "gold.jsonl"))) == n


def test_sheet_validation_names_the_row(tmp_path):
    p = tmp_path / "sheet_X.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=labels.SHEET_COLUMNS)
        w.writeheader()
        w.writerow({"key": "sub-1|ses-1", "sub": "sub-1", "ses": "ses-1", "rating": "terrible"})
    with pytest.raises(ValueError, match="line 2"):
        labels.read_sheet(str(p))


def test_kappa_against_sklearn_or_known_values():
    a = ["clean", "clean", "bad", "minor", "bad", "clean", "concern", "clean"]
    b = ["clean", "minor", "bad", "minor", "bad", "clean", "clean", "clean"]
    k = labels.cohen_kappa(a, b)
    sk = pytest.importorskip("sklearn.metrics", reason="sklearn not installed; using known value")
    assert k == pytest.approx(sk.cohen_kappa_score(a, b), abs=1e-9)
    assert labels.cohen_kappa(a, a) == 1.0
    fk = labels.fleiss_kappa([[x, y, x] for x, y in zip(a, b, strict=True)], RATINGS)
    assert -1 <= fk <= 1


def test_kappa_known_value():
    # classic textbook case: 20 items, 2 raters; agreement 0.7, chance 0.5 -> kappa 0.4
    a = ["y"] * 10 + ["n"] * 10
    b = ["y"] * 7 + ["n"] * 3 + ["n"] * 7 + ["y"] * 3
    assert labels.cohen_kappa(a, b) == pytest.approx(0.4)


# ----------------------------------------------------------------- dataset

def _gold_from_run(run, path):
    state = json.load(open(run / "state.json"))
    gold = []
    for k, s in state["scans"].items():
        rating, ft = _rating_by_status(0, {"status": s["status"]})
        gold.append(Label(key=k, sub=s["sub"], ses=s["ses"], rating=rating,
                          panel="coreg" if rating != "clean" else "none", failure_type=ft, rater="A"))
    labels.write_gold(gold, str(path))
    return gold


def test_dataset_splits_by_subject_and_is_reproducible(rendered_run, tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    gold = _gold_from_run(rendered_run, gold_path)
    m1 = dataset.build(str(gold_path), str(rendered_run), str(tmp_path / "d1"), seed=3)
    m2 = dataset.build(str(gold_path), str(rendered_run), str(tmp_path / "d2"), seed=3)
    assert m1["examples"] == m2["examples"]            # same seed, same split
    total = sum(sum(c.values()) for c in m1["counts"].values())
    assert total == len(gold) and not m1["skipped_unrendered"]
    assert all(m1["counts"][s] for s in ("train", "validation", "test"))
    # no subject straddles splits
    sub_split = {}
    for split in ("train", "validation", "test"):
        for ex in dataset.load_split(str(tmp_path / "d1"), split):
            assert sub_split.setdefault(ex["sub"], split) == split
            assert ex["messages"][0]["role"] == "system" and "record_reviews" in ex["messages"][0]["content"]
            assert json.loads(ex["messages"][2]["content"])["rating"] == ex["label"]["rating"]
            assert len(ex["images"]) == 3 and ex["coarse"] == coarse(ex["label"]["rating"])
    assert len(m1["images"]) == 3 * len(gold) and all(len(h) == 64 for h in m1["images"].values())
    card = open(tmp_path / "d1" / "DATA_CARD.md").read()
    assert "| test |" in card and "never straddle" in card


def test_dataset_with_context_embeds_reference_notes(rendered_run, tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    dataset.build(str(gold_path), str(rendered_run), str(tmp_path / "d"), seed=1, with_context=True)
    ex = dataset.load_split(str(tmp_path / "d"), "train")[0]
    assert ex["messages"][1]["content"][0]["text"].startswith("Reference notes")


# ----------------------------------------------------------------- metrics

def test_metrics_match_sklearn_or_hand_values():
    yt = ["clean", "clean", "bad", "minor", "bad", "clean", "concern", "clean", "concern", "minor"]
    yp = ["clean", "minor", "bad", "minor", "clean", "clean", "concern", "clean", "bad", "minor"]
    pc = metrics.per_class(yt, yp, RATINGS)
    assert pc["clean"]["support"] == 4 and pc["bad"]["recall"] == 0.5 and pc["bad"]["precision"] == 0.5
    assert metrics.accuracy(yt, yp) == 0.7
    mf1 = metrics.macro_f1(yt, yp, RATINGS)
    try:
        from sklearn.metrics import f1_score
        assert mf1 == pytest.approx(f1_score(yt, yp, average="macro"), abs=1e-9)
    except ImportError:
        assert mf1 == pytest.approx((0.75 + 0.8 + 2 / 3 + 0.5) / 4, abs=1e-6)
    cm = metrics.confusion(yt, yp, RATINGS)
    assert cm["bad"]["clean"] == 1 and cm["concern"]["bad"] == 1 and sum(map(sum, (r.values() for r in cm.values()))) == 10


def test_bootstrap_ci_brackets_point_estimate_and_uses_groups():
    yt = ["clean"] * 30 + ["bad"] * 10
    yp = ["clean"] * 27 + ["bad"] * 3 + ["bad"] * 8 + ["clean"] * 2
    groups = [f"s{i // 2}" for i in range(40)]         # two scans per subject
    point = metrics.macro_f1(yt, yp, ("clean", "bad"))
    lo, hi = metrics.bootstrap_ci(yt, yp, groups, lambda a, b: metrics.macro_f1(a, b, ("clean", "bad")), n=300, seed=1)
    assert lo <= point <= hi and hi - lo > 0
    lo2, hi2 = metrics.bootstrap_ci(yt, yp, groups, lambda a, b: metrics.macro_f1(a, b, ("clean", "bad")), n=300, seed=1)
    assert (lo, hi) == (lo2, hi2)                       # seeded


# ----------------------------------------------------------------- harness

def test_evaluate_stub_and_results_table(rendered_run, tmp_path, capsys):
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    perfect = get_predictor("stub", cache_dir=str(tmp_path / "cache"))
    res = evaluate.evaluate(perfect, dataset.load_split(str(data), "test"), n_boot=50)
    assert res["macro_f1"] == 1.0 and res["accuracy"] == 1.0 and res["failure_type_accuracy"] == 1.0
    assert res["usage"]["n"] == res["n"] and res["usage"]["cache_hits"] == 0
    # second pass hits the cache
    res2 = evaluate.evaluate(perfect, dataset.load_split(str(data), "test"), n_boot=50)
    assert res2["usage"]["cache_hits"] == res["n"]
    noisy = get_predictor("stub", error_rate=0.5, seed=1)
    resn = evaluate.evaluate(noisy, dataset.load_split(str(data), "train"), n_boot=50)
    assert resn["macro_f1"] < 1.0 and resn["macro_f1_ci95"][0] <= resn["macro_f1"] <= resn["macro_f1_ci95"][1]
    row = evaluate.results_row(resn, "train")
    assert row.startswith("| stub:err=0.5 | train |")
    evaluate.append_results(str(tmp_path / "RESULTS.md"), row)
    evaluate.append_results(str(tmp_path / "RESULTS.md"), row)
    text = open(tmp_path / "RESULTS.md").read()
    assert text.count("| stub:err=0.5 |") == 2 and text.startswith("# Results")

    rc = evaluate.main(["--predictor", "stub", "--data", str(data), "--split", "validation",
                        "--n-boot", "20", "--cache", str(tmp_path / "c2"), "--out", str(tmp_path / "res")])
    assert rc == 0 and "macro-F1 1.000" in capsys.readouterr().out
    assert (tmp_path / "res" / "RESULTS.md").exists()


def test_predictor_errors_count_as_wrong_not_crash(rendered_run, tmp_path):
    from qcvlm.predictors.base import Predictor

    class Broken(Predictor):
        name = "broken"

        def _predict(self, example):
            raise RuntimeError("boom")

    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    exs = dataset.load_split(str(data), "test")
    res = evaluate.evaluate(Broken(), exs, n_boot=10)
    assert res["usage"]["failures"] == len(exs) and all(p["note"].startswith("PREDICTOR_ERROR") for p in
                                                        [Broken().predict(e) for e in exs[:1]])


def test_claude_predictor_uses_tool_contract_and_costs(rendered_run, tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    exs = dataset.load_split(str(data), "test")[:3]

    class Fake:
        def __init__(self):
            self.calls = []
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kw):
            self.calls.append(kw)
            block = SimpleNamespace(type="tool_use", name="record_review",
                                    input={"rating": "bad", "panel": "coreg",
                                           "failure_type": "truncated_fov", "note": "slab"})
            usage = SimpleNamespace(input_tokens=1000, output_tokens=50,
                                    cache_read_input_tokens=0, cache_creation_input_tokens=0)
            return SimpleNamespace(content=[block], usage=usage)

    fake = Fake()
    p = get_predictor("claude", model="claude-sonnet-4-5", _client=fake)
    res = evaluate.evaluate(p, exs, n_boot=10)
    assert len(fake.calls) == 3
    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "record_review"}
    assert sum(1 for b in call["messages"][0]["content"] if b["type"] == "image") == 3
    assert res["usage"]["usd"] == pytest.approx(3 * (1000 * 3 + 50 * 15) / 1e6, abs=1e-6)
    assert res["usage"]["usd_per_1k"] > 0 and res["predictor"] == "claude:claude-sonnet-4-5"
    assert all(p_["pred"] == "bad" for p_ in res["predictions"])
    assert set(FAILURE_TYPES) >= {p_["failure_pred"] for p_ in res["predictions"]}


# ----------------------------------------------------------------- qwen / lora (no GPU)

def test_qwen_message_formatting_and_parsing(rendered_run, tmp_path):
    from qcvlm import formatting
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    ex = dataset.load_split(str(data), "train")[0]
    msgs = formatting.to_qwen_messages(ex, include_assistant=True, max_pixels=1234)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    imgs = [b for b in msgs[1]["content"] if b["type"] == "image"]
    assert len(imgs) == 3 and imgs[0]["max_pixels"] == 1234 and imgs[0]["image"].endswith(".jpg")
    assert msgs[1]["content"][-1]["text"].startswith("Reply with ONLY a JSON object")
    assert json.loads(msgs[2]["content"])["rating"] == ex["label"]["rating"]

    assert formatting.parse_prediction('{"rating": "bad", "panel": "coreg", "failure_type": "truncated_fov", "note": "slab"}')["rating"] == "bad"
    assert formatting.parse_prediction('Sure! ```json\n{"rating": "Clean", "panel": "none", "failure_type": "none", "note": ""}\n```')["rating"] == "clean"
    assert formatting.parse_prediction('The scan looks fine. {"rating":"minor","panel":"carpet","failure_type":"motion","note":"x"} done')["panel"] == "carpet"
    with pytest.raises(ValueError):
        formatting.parse_prediction("no json here")
    with pytest.raises(Exception):  # noqa: B017 - pydantic wraps the enum error
        formatting.parse_prediction('{"rating": "meh", "panel": "none", "failure_type": "none"}')


def test_qwen_endpoint_backend_speaks_openai_and_caches(rendered_run, tmp_path):
    from qcvlm.predictors.qwen import QwenPredictor
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    exs = dataset.load_split(str(data), "test")[:2]
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return SimpleNamespace(raise_for_status=lambda: None,
                               json=lambda: {"choices": [{"message": {"content":
                                   '{"rating": "concern", "panel": "carpet", "failure_type": "carpet_block", "note": "band at 3 min"}'}}]})

    p = QwenPredictor(endpoint="http://gpu:8000/v1", model_id="qc", adapter="adapters/lora-r16",
                      _http=fake_post, cache_dir=str(tmp_path / "c"))
    assert p.ident() == "qwen:qc+lora:lora-r16@589824px"
    preds = [p.predict(e) for e in exs]
    assert all(q["rating"] == "concern" for q in preds) and len(calls) == 2
    url, body = calls[0]
    assert url == "http://gpu:8000/v1/chat/completions" and body["model"] == "qc"
    user = body["messages"][1]["content"]
    assert sum(1 for b in user if b["type"] == "image_url") == 3
    assert user[-1]["type"] == "text" and user[-1]["text"].startswith("Reply with ONLY")
    assert [p.predict(e) for e in exs] == preds and len(calls) == 2      # cache hit
    assert p.usage()["cache_hits"] == 2


def test_train_lora_dry_run_and_config(rendered_run, tmp_path, capsys):
    from qcvlm import train_lora
    gold_path = tmp_path / "gold.jsonl"
    _gold_from_run(rendered_run, gold_path)
    data = tmp_path / "d"
    dataset.build(str(gold_path), str(rendered_run), str(data), seed=5)
    cfg = train_lora.load_config("training/configs/lora.yaml")
    assert cfg["lora"]["r"] == 16 and cfg["lora"]["alpha"] == 32 and "visual" in cfg["lora"]["exclude_modules_regex"]
    rc = train_lora.main(["--config", "training/configs/lora.yaml", "--dry-run", "--limit", "4",
                          "--set", f"data_dir={data}", "--set", "lora.r=8"])
    out = capsys.readouterr().out
    assert rc == 0 and "train 4 examples" in out and "LoRA r=8" in out and "dry run OK" in out
    assert "[assistant]" in out and "<image" in out
    with pytest.raises(ValueError, match="missing"):
        bad = tmp_path / "bad.yaml"
        bad.write_text("model_id: x\n")
        train_lora.load_config(str(bad))
