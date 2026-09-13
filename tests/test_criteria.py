import pytest
import yaml

from autoqa.criteria import Criteria, default_path, load_criteria


def test_packaged_default_is_valid():
    crit = load_criteria()
    assert crit.outlier_definition.mode in ("absolute", "relative", "tr_scaled")
    assert crit.version and crit.dated
    assert default_path().endswith("criteria.yaml")


def _write(tmp_path, **overrides):
    raw = yaml.safe_load(open(default_path()))
    for dotted, val in overrides.items():
        d = raw
        *parents, last = dotted.split(".")
        for k in parents:
            d = d[k]
        d[last] = val
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw))
    return str(p)


def test_typo_in_mode_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="outlier_definition.mode"):
        load_criteria(_write(tmp_path, **{"outlier_definition.mode": "relatve"}))


def test_reversed_band_rejected(tmp_path):
    with pytest.raises(ValueError, match="low < high"):
        load_criteria(_write(tmp_path, **{"verify_flags.borderline_mean_fd_band": [0.55, 0.45]}))


def test_band_must_bracket_threshold(tmp_path):
    with pytest.raises(ValueError, match="does not bracket"):
        load_criteria(_write(tmp_path, **{"exclusion.mean_fd_mm": 0.9}))


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_criteria(_write(tmp_path, **{"exclusion.mean_fd": 0.5}))


def test_env_override_wins(tmp_path, monkeypatch):
    p = _write(tmp_path, **{"version": "9.9-test"})
    monkeypatch.setenv("AFQ_CRITERIA", p)
    assert default_path() == p
    assert load_criteria().version == "9.9-test"


def test_as_dict_round_trips_bands(criteria):
    d = criteria.as_dict()
    assert isinstance(d["verify_flags"]["borderline_mean_fd_band"], list)
    assert Criteria.model_validate(d).as_dict() == d
