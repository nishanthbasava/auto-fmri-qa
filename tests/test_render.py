"""Renderer under real chromium: JPEG output, the template-layer guard, idempotency.

Marked `render` (needs `playwright install chromium`); a tiny cohort keeps the
module fast. The guard test forges two subjects with byte-identical registration
SVGs — the render must refuse to pass them off as distinct evidence.
"""
import hashlib
import os

import pytest

import autoqa
from autoqa import synth
from autoqa.pipeline.render import render_run
from autoqa.pipeline.state import RunState

pytestmark = pytest.mark.render


@pytest.fixture(scope="module")
def rendered_run(tmp_path_factory):
    """A 4-subject all-clean cohort rendered once, shared by the happy-path tests."""
    root = tmp_path_factory.mktemp("mini")
    synth.generate(str(root), subjects=4, seed=3, mix={"clean": 1.0})
    run = str(tmp_path_factory.mktemp("run") / "r1")
    res = autoqa.qc(str(root), out=run, render=True, quiet=True)
    return run, res


def test_every_figure_renders_to_a_jpeg(rendered_run):
    run, res = rendered_run
    state = RunState(run)
    assert state.data["stages"]["render"]["n"] > 0
    for s in state.scans().values():
        for kind, svg in s["figures"].items():
            if not svg:
                continue
            k = "t1norm" if kind.startswith("t1norm") else kind
            jpg = s["rendered"][k]
            assert jpg.endswith(".jpg") and os.path.getsize(jpg) > 0, (s["sub"], kind)
    figures_dir = os.path.join(run, "figures")
    assert not [f for f in os.listdir(figures_dir) if f.endswith(".png")], "tmp PNGs left behind"


def test_registration_renders_differ_across_subjects(rendered_run):
    run, _ = rendered_run
    digests = {}
    for key, s in RunState(run).scans().items():
        path = s["rendered"]["coreg"]
        digests[key] = hashlib.md5(open(path, "rb").read()).hexdigest()
    assert len(set(digests.values())) == len(digests), (
        "coreg renders must show subject data, not the template layer")


def test_identical_registration_renders_raise(tmp_path):
    root = tmp_path / "cohort"
    synth.generate(str(root), subjects=2, seed=5, mix={"clean": 1.0})
    res = autoqa.qc(str(root), out=str(tmp_path / "run"), quiet=True)
    a, b = (s["figures"]["coreg"] for s in res.scans[:2])
    with open(a) as f_in, open(b, "w") as f_out:
        f_out.write(f_in.read())  # two subjects, one image: the guard must object
    with pytest.raises(RuntimeError, match="identical registration renders"):
        render_run(RunState(str(tmp_path / "run")))


def test_rerender_is_a_noop(rendered_run):
    run, _ = rendered_run
    state = RunState(run)
    render_run(state)
    assert state.data["stages"]["render"]["n"] == 0
    assert state.data["stages"]["render"]["note"] == "up to date"
