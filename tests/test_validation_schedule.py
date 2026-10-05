"""The validation schedule: one replica-scaled step, ending in a drain tail."""

import pytest

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.service import ServiceCurve
from autoscale.traffic import ADDITIONAL_REPLICAS_AT_PEAK, spike_shape
from autoscale.validation import RealRun
from autoscale.validation_schedule import (
    LATENCY_SOURCE,
    VALIDATION_ADDITIONAL_REPLICAS,
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    build_schedule,
    schedule_facts,
    validation_shape,
)

CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                     measured=True)


def test_the_constants_are_the_proposed_operating_point():
    assert (VALIDATION_REPLICAS, VALIDATION_KIND, VALIDATION_UNTIL, VALIDATION_DRAIN_SECONDS,
            VALIDATION_SEED, LATENCY_SOURCE) == (2, "step", 400.0, 30.0, 20261004, "server")


def test_the_shape_scales_the_baseline_by_the_replica_count_and_nothing_else():
    one = spike_shape(CURVE, "step", additional_replicas=VALIDATION_ADDITIONAL_REPLICAS)
    two = validation_shape(CURVE, replicas=2, kind="step")
    assert two.baseline_rate == pytest.approx(2 * one.baseline_rate)
    assert (two.k, two.ramp, two.sustain, two.kind) == (one.k, one.ramp, one.sustain, "step")


def test_the_validation_spike_is_pinned_and_does_not_follow_the_sweep():
    """The 2026-10-04 (second) amendment moved the sweep to 0.5 and kept the
    gate at the signed 0.25: a traffic amendment must not silently move a
    paid run's operating point."""
    assert VALIDATION_ADDITIONAL_REPLICAS == 0.25
    assert ADDITIONAL_REPLICAS_AT_PEAK != VALIDATION_ADDITIONAL_REPLICAS
    sweep = spike_shape(CURVE, "step")
    two = validation_shape(CURVE, replicas=2, kind="step")
    assert two.k != sweep.k
    assert two.k == spike_shape(CURVE, "step", additional_replicas=0.25).k


def test_no_arrival_falls_in_the_drain_tail():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    assert s and 89.0 < max(s) <= 90.0 and min(s) > 0.0
    assert list(s) == sorted(s)


def test_the_same_seed_gives_the_same_schedule():
    a = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    b = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    assert a == b


def test_different_seeds_give_different_schedules():
    a = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    b = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=4)
    assert a != b


def test_a_schedule_the_model_cannot_finish_is_refused():
    slow = ServiceCurve(points=[(0, 5.0, 0.0, 0.0), (1, 5.0, 1.0, 1.0), (2, 9.0, 1.5, 1.0)],
                        measured=True)
    with pytest.raises(ValueError, match="unfinished"):
        build_schedule(slow, replicas=1, kind="step", until=60.0, drain=1.0, seed=3)


def test_a_drain_not_shorter_than_the_window_is_refused():
    with pytest.raises(ValueError, match="drain"):
        build_schedule(CURVE, replicas=2, kind="step", until=30.0, drain=30.0, seed=3)


def test_the_schedule_is_a_valid_real_run_schedule():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    RealRun(schedule=s, sent=s, latencies=[0.2] * len(s), replicas=2, until=120.0,
            host_ids=("w1", "w2"))


def test_facts_report_size_rates_and_the_models_prediction():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    f = schedule_facts(s, CURVE, replicas=2, until=120.0)
    assert f["requests"] == len(s)
    assert f["last_arrival_s"] == pytest.approx(max(s))
    assert f["predicted_unfinished"] == 0
    assert f["peak_bin_rps"] >= f["mean_rps"] > 0
    # Pinned on the small CURVE: 4614 requests over the 90 s arrival window
    # (until - drain, not the last arrival's timestamp); bins 0-8 each hold >= 20.
    assert len(s) == 4614
    assert f["mean_rps"] == pytest.approx(4614 / 90.0)
    assert f["bins_with_20_requests"] == 9
    assert set(f) >= {"predicted_p50_s", "predicted_p99_s", "bins_with_20_requests"}


def test_the_committed_curve_gives_a_finishable_schedule():
    m = load_measured_curve(DEFAULT_PATH)
    s = build_schedule(m.curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                       until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                       seed=VALIDATION_SEED)
    f = schedule_facts(s, m.curve, replicas=VALIDATION_REPLICAS, until=VALIDATION_UNTIL)
    assert f["predicted_unfinished"] == 0
    assert f["bins_with_20_requests"] >= 30
    assert abs(f["last_arrival_s"] - (VALIDATION_UNTIL - VALIDATION_DRAIN_SECONDS)) < 1.0
    # The amendment quotes this size; a change must fail loudly, not drift.
    assert len(s) == 129876
