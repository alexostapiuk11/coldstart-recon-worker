"""The measured service curve as the simulator reads it."""

import json
from pathlib import Path

import pytest

from autoscale.measured_curve import (
    DEFAULT_PATH,
    IDLE_CONCURRENCY,
    MeasuredCurve,
    load_measured_curve,
    select_curve,
)
from autoscale.service import SERVICE_CURVE_PLACEHOLDER

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "data" / "a2" / "service-sweep.jsonl"


def _doc(**over):
    doc = {
        "measured": True,
        "gpu_util_method": "windowed",
        "prompt_path": "random-fallback",
        "max_num_seqs": 256,
        "points": [[1, 0.28, 56.0, 1], [2, 0.31, 104.0, 1], [128, 0.61, 3270.0, 1]],
        "intervals": [
            {"concurrency": 1, "latency_s_range": [0.27, 0.29], "throughput_tps_range": [55, 57],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.02, 0.03]},
            {"concurrency": 2, "latency_s_range": [0.30, 0.32], "throughput_tps_range": [103, 105],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.02, 0.03]},
            {"concurrency": 128, "latency_s_range": [0.60, 0.62], "throughput_tps_range": [3200, 3300],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.16, 0.2]},
        ],
        "excluded_levels": [{"concurrency": 256, "reason": "OOM", "n_failed": 3, "n_runs": 3,
                             "run_ids": ["a", "b", "c"], "failure_details": []}],
    }
    doc.update(over)
    return doc


def _write(tmp_path, doc):
    path = tmp_path / "curve.json"
    path.write_text(json.dumps(doc))
    return path


def test_the_idle_point_is_prepended_and_reads_zero(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert isinstance(m, MeasuredCurve)
    assert m.curve.points[0] == (IDLE_CONCURRENCY, 0.28, 0.0, 0.0)
    assert m.curve.utilization_at(0) == 0.0
    assert m.curve.utilization_at(0.5) == pytest.approx(0.5)
    assert m.curve.utilization_at(1) == 1.0


def test_latency_and_cap_are_the_measured_ones(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert m.curve.latency_at(1) == 0.28
    assert m.curve.latency_at(128) == 0.61
    assert m.curve.max_measured_concurrency == 128
    assert m.curve.measured is True


def test_measured_points_exclude_the_idle_point(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert [p[0] for p in m.measured_points] == [1, 2, 128]
    assert [i["concurrency"] for i in m.intervals] == [1, 2, 128]
    assert m.excluded_levels[0]["concurrency"] == 256
    assert m.max_num_seqs == 256
    assert m.gpu_util_method == "windowed"
    assert m.runs_per_level == ()


def test_runs_per_level_come_from_the_level_rows(tmp_path):
    doc = _doc(levels=[{"n_runs": 3}, {"n_runs": 3}, {"n_runs": 2}])
    assert load_measured_curve(_write(tmp_path, doc)).runs_per_level == (3, 3, 2)
    with pytest.raises(ValueError, match="level rows"):
        load_measured_curve(_write(tmp_path, _doc(levels=[{"n_runs": 3}])))


def test_an_unmeasured_curve_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not measured"):
        load_measured_curve(_write(tmp_path, _doc(measured=False)))


def test_a_curve_that_mixes_or_lacks_the_windowed_method_is_refused(tmp_path):
    with pytest.raises(ValueError, match="windowed"):
        load_measured_curve(_write(tmp_path, _doc(gpu_util_method="whole-call")))


def test_a_curve_already_holding_a_zero_level_is_refused(tmp_path):
    doc = _doc(points=[[0, 0.2, 0.0, 0.0], [1, 0.28, 56.0, 1]])
    doc["intervals"] = doc["intervals"][:2]
    doc["intervals"][0]["concurrency"] = 0
    doc["intervals"][1]["concurrency"] = 1
    with pytest.raises(ValueError, match="idle point"):
        load_measured_curve(_write(tmp_path, doc))


def test_intervals_must_match_the_points_level_for_level(tmp_path):
    doc = _doc()
    doc["intervals"] = doc["intervals"][:2]
    with pytest.raises(ValueError, match="intervals"):
        load_measured_curve(_write(tmp_path, doc))


def test_an_excluded_level_inside_the_measured_range_is_refused(tmp_path):
    doc = _doc()
    doc["excluded_levels"][0]["concurrency"] = 64
    with pytest.raises(ValueError, match="inside the measured range"):
        load_measured_curve(_write(tmp_path, doc))


def test_the_committed_curve_loads():
    m = load_measured_curve(REPO / DEFAULT_PATH)
    assert m.curve.measured
    assert m.curve.max_measured_concurrency == 128
    assert [e["concurrency"] for e in m.excluded_levels] == [256]
    assert m.curve.utilization_at(0) == 0.0
    assert m.runs_per_level == (3,) * 8


def test_the_store_shows_an_idle_gpu_reads_zero():
    """The idle point's evidence: in every successful sweep run, at least 80% of
    the samples outside its measured span (the engine idle while the bench tool
    starts and stops) read 0. At least 80%, not all: the first samples and those
    at the span's edges can catch the warm-up wave or the prompt probe just
    before or after the measured requests (run 9efd5a52..., level 32, has 30
    zeros of 33 out-of-span samples; owner decision 2026-10-04). If a future
    store breaks this, the idle point is no longer a measurement and Task 2 has
    to be revisited, not this test loosened further."""
    runs = [json.loads(line) for line in STORE.read_text().splitlines() if line.strip()]
    ok = [r for r in runs if r["outcome"] == "ok"]
    assert ok
    for r in ok:
        samples = [s["util_pct"] for s in r["summary"]["gpu"]["samples"]
                   if s.get("util_pct") is not None]
        zeros = sum(1 for v in samples if v == 0)
        outside = r["summary"]["gpu_util_n_outside_span"]
        assert outside > 0 and zeros >= 0.8 * outside, (r["run_id"], zeros, outside)


def test_select_curve_defaults_to_the_measured_one(tmp_path):
    curve, measured = select_curve(_write(tmp_path, _doc()), placeholder=False)
    assert measured is not None and curve is measured.curve


def test_select_curve_placeholder_returns_the_placeholder():
    curve, measured = select_curve(None, placeholder=True)
    assert curve is SERVICE_CURVE_PLACEHOLDER and measured is None
