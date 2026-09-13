"""Boundary tests for classify(): the thresholds are strict '>' comparisons."""
import copy

import pytest

from autoqa.pipeline import classify as cls


def _scan(missing=()):
    return {"sub": "sub-001", "ses": "ses-v01", "missing": list(missing)}


def _m(mean_fd=0.15, outlier_percent=2.0, retained=9.0, fast=False):
    return {"mean_fd": mean_fd, "outlier_percent": outlier_percent,
            "retained_minutes": retained, "is_fast_tr": fast}


@pytest.mark.parametrize("mean_fd,status", [
    (0.4999, "INCLUDE"), (0.5, "INCLUDE"), (0.5001, "EXCLUDE"), (1.2, "EXCLUDE")])
def test_mean_fd_exclusion_is_strict(criteria_dict, mean_fd, status):
    assert cls.classify(_scan(), _m(mean_fd=mean_fd), criteria_dict)["status"] == status


@pytest.mark.parametrize("pct,status", [(19.9, "INCLUDE"), (20.0, "INCLUDE"), (20.1, "CAUTION")])
def test_outlier_percent_caution_is_strict(criteria_dict, pct, status):
    assert cls.classify(_scan(), _m(outlier_percent=pct), criteria_dict)["status"] == status


def test_exclusion_beats_caution(criteria_dict):
    c = cls.classify(_scan(), _m(mean_fd=0.8, outlier_percent=50), criteria_dict)
    assert c["status"] == "EXCLUDE" and "mean FD" in c["reasons"][0]


def test_missing_outputs_exclude_before_metrics(criteria_dict):
    c = cls.classify(_scan(missing=["carpet"]), _m(), criteria_dict)
    assert c["status"] == "EXCLUDE" and "missing required outputs: carpet" in c["reasons"]


def test_borderline_bands_flag_without_changing_status(criteria_dict):
    c = cls.classify(_scan(), _m(mean_fd=0.47, outlier_percent=19.0), criteria_dict)
    assert c["status"] == "INCLUDE"
    assert any("borderline mean FD" in f for f in c["verify_flags"])
    assert any("borderline outlier%" in f for f in c["verify_flags"])


def test_band_edges(criteria_dict):
    # band is (lo, hi]: lo itself is not flagged, hi is
    assert not cls.classify(_scan(), _m(mean_fd=0.45), criteria_dict)["verify_flags"]
    assert cls.classify(_scan(), _m(mean_fd=0.55), criteria_dict)["verify_flags"]


def test_fast_tr_flag(criteria_dict):
    c = cls.classify(_scan(), _m(fast=True), criteria_dict)
    assert c["status"] == "INCLUDE" and any("fast-TR" in f for f in c["verify_flags"])


def test_retained_minutes_floor_when_enabled(criteria_dict):
    crit = copy.deepcopy(criteria_dict)
    crit["caution"]["min_retained_minutes"] = 5.0
    c = cls.classify(_scan(), _m(retained=4.0), crit)
    assert c["status"] == "CAUTION" and "floor" in c["reasons"][0]
    assert cls.classify(_scan(), _m(retained=4.0), criteria_dict)["status"] == "INCLUDE"
