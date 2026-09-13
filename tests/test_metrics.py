"""Hand-checkable traces so every expected number can be verified on paper."""
import copy

import pytest

from autoqa.pipeline import metrics as met

FD = [None, 0.12, 0.2, 0.6, 0.12, 0.12, 0.12, 0.9, 0.12, 0.12]  # 10 volumes, 2 FD spikes (>0.5)
DV = [1.0, 1.0, 1.0, 1.4, 1.0, 1.0, 2.0, 1.0, 1.0, 1.0]     # median 1.0; one DVARS spike (2.0)


def _crit(criteria_dict, mode):
    c = copy.deepcopy(criteria_dict)
    c["outlier_definition"]["mode"] = mode
    return c


def test_first_volume_has_no_fd(scan_writer):
    s = scan_writer(FD, DV)
    fd, dv = met.load_traces(s["confounds"])
    assert fd[0] is None and len(fd) == 10 and dv[0] == 1.0


@pytest.mark.parametrize("mode,expected_outliers", [
    ("absolute", 3),    # FD>0.5: vols 3,7  +  std_dvars>1.5: vol 6          -> 3
    ("relative", 3),    # FD>0.5: vols 3,7  +  std_dvars>1.5*median(1.0): 6  -> 3
    ("tr_scaled", 3),   # TR=3 so fd threshold unchanged                      -> 3
])
def test_outlier_count_by_mode(scan_writer, criteria_dict, mode, expected_outliers):
    s = scan_writer(FD, DV, tr=3.0)
    m = met.scan_metrics(s, _crit(criteria_dict, mode))
    assert m["n_outliers"] == expected_outliers
    assert m["outlier_percent"] == pytest.approx(100 * expected_outliers / 10)
    assert m["mean_fd"] == pytest.approx(sum(x for x in FD if x) / 9, abs=1e-4)
    assert m["max_fd"] == 0.9
    assert m["n_volumes"] == 10
    assert m["retained_minutes"] == pytest.approx((10 - expected_outliers) * 3 / 60, abs=1e-2)


def test_tr_scaled_shrinks_fd_threshold(scan_writer, criteria_dict):
    s = scan_writer(FD, DV, tr=0.6)
    m = met.scan_metrics(s, _crit(criteria_dict, "tr_scaled"))
    assert m["fd_spike_threshold"] == pytest.approx(0.5 * 0.6 / 3, abs=1e-4)   # 0.10 mm
    # with a ~0.10 mm bar every volume is a "spike": the TR-scaling trap.
    # (baseline is 0.12, not 0.10, so the comparison never sits exactly on the bar)
    fd_thr, dv_thr = m["fd_spike_threshold"], m["dvars_threshold"]
    expected = sum(1 for f, d in zip(FD, DV, strict=True) if (f is not None and f > fd_thr) or d > dv_thr)
    assert m["n_outliers"] == expected == 9
    assert m["is_fast_tr"] is True


def test_relative_mode_follows_scan_median(scan_writer, criteria_dict):
    high = [d * 1.3 for d in DV]           # a "Philips-like" scan: everything 30% higher
    s = scan_writer(FD, high)
    rel = met.scan_metrics(s, _crit(criteria_dict, "relative"))
    ab = met.scan_metrics(s, _crit(criteria_dict, "absolute"))
    assert rel["dvars_threshold"] == pytest.approx(1.5 * 1.3, abs=1e-4)
    assert rel["n_outliers"] == 3            # same three volumes as before
    assert ab["n_outliers"] == 3             # 1.4*1.3=1.82 > 1.5 -> absolute now over-flags... but
    # ...wait: vol 3 is already an FD spike, so counts coincide here; check the DVARS-only volume
    assert ab["dvars_threshold"] == 1.5 and rel["dvars_threshold"] > 1.5


def test_missing_columns_raise(tmp_path):
    p = tmp_path / "bad.tsv"
    p.write_text("a\tb\n1\t2\n")
    with pytest.raises(ValueError, match="std_dvars"):
        met.load_traces(str(p))
