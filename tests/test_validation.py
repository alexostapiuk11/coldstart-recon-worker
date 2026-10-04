"""Artifact 2's gate: its run record, the replay into the simulator, and its
pre-registered constants. The band and verdict arithmetic is tested in
tests/test_validation_band.py."""

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.validation import RealRun, predicted_trajectory, tolerance_band, validate


# 20 requests per 10 s bin, spaced 0.5 s: the p50 sample floor exactly, and
# sparse enough that one placeholder replica serves each alone at the
# concurrency-1 latency of 0.30 s.
def _schedule(bins):
    return tuple(i * 0.5 for i in range(20 * bins))


def _run(latency, bins=6, host="w1"):
    schedule = _schedule(bins)
    lat = latency if isinstance(latency, list) else [latency] * len(schedule)
    return RealRun(schedule=schedule, sent=schedule, latencies=tuple(lat),
                   replicas=1, until=10.0 * bins, host_ids=(host,))


def test_the_prediction_replays_the_schedule_through_the_simulator():
    bins = predicted_trajectory(_schedule(2), replicas=1, curve=SERVICE_CURVE_PLACEHOLDER,
                                until=20.0, bin_seconds=10.0)
    assert [b.p50 for b in bins] == pytest.approx([0.30, 0.30])


def test_the_replay_keeps_its_backlog_as_censored_bins():
    """The request arriving at 19.5 s is still in service when the window
    closes at 19.6 s. Dropping it would leave its bin 19 completions and call
    it thin; it is the backlog, so the bin is censored."""
    bins = predicted_trajectory(_schedule(2), replicas=1, curve=SERVICE_CURVE_PLACEHOLDER,
                                until=19.6, bin_seconds=10.0)
    assert (bins[-1].status, bins[-1].unfinished) == ("censored", 1)


def test_bins_are_keyed_by_scheduled_arrival_not_send_time():
    """The request scheduled at 9.5 s goes out at 10.0 s -- within the jitter
    bound, but across a bin boundary. Keyed by send time, bin 0 would drop to
    19 requests and go thin on this repeat alone: a difference the driver
    made, not the system."""
    schedule = _schedule(6)
    late = RealRun(schedule=schedule, sent=schedule[:19] + (10.0,) + schedule[20:],
                   latencies=(1.0,) * 120, replicas=1, until=60.0, host_ids=("w1",))
    band = tolerance_band([_run(1.0), _run(1.1), late], bin_seconds=10.0)
    assert band[0].status == "ok"


def test_the_band_comes_from_the_real_repeats():
    band = tolerance_band([_run(1.0), _run(1.2), _run(1.1)], bin_seconds=10.0)
    assert (band[0].lo, band[0].hi) == pytest.approx((1.0, 1.2))


def test_fewer_than_three_repeats_is_refused():
    with pytest.raises(ValueError, match="3"):
        tolerance_band([_run(1.0), _run(1.1)], bin_seconds=10.0)


def test_repeats_of_different_schedules_are_refused():
    """The band is the system's own reproducibility on ONE trace. Repeats of
    different traces fold traffic variance into it and widen it for free."""
    shifted = _schedule(6)[1:] + (59.9,)
    other = RealRun(schedule=shifted, sent=shifted, latencies=(1.0,) * 120,
                    replicas=1, until=60.0, host_ids=("w1",))
    with pytest.raises(ValueError, match="schedule"):
        tolerance_band([_run(1.0), _run(1.1), other], bin_seconds=10.0)


def test_a_run_that_did_not_hold_the_schedule_is_refused():
    schedule = _schedule(6)
    drifted = RealRun(schedule=schedule, sent=tuple(t + 2.0 for t in schedule),
                      latencies=(1.0,) * 120, replicas=1, until=60.0, host_ids=("w1",))
    with pytest.raises(ValueError, match="jitter"):
        tolerance_band([_run(1.0), _run(1.1), drifted], bin_seconds=10.0)


def test_real_runs_that_bracket_the_model_pass():
    runs = [_run(0.29), _run(0.30), _run(0.31)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER, bin_seconds=10.0).outcome == "passed"


def test_real_runs_far_from_the_model_fail_with_the_distance():
    v = validate([_run(1.0), _run(1.1), _run(1.2)], SERVICE_CURVE_PLACEHOLDER, bin_seconds=10.0)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.70)


def test_a_run_too_short_to_judge_is_not_evaluable():
    """Four 10 s bins is below the pre-registered five, so agreement on all of
    them is still not a pass."""
    runs = [_run(0.29, bins=4), _run(0.30, bins=4), _run(0.31, bins=4)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER, bin_seconds=10.0).outcome == "not_evaluable"


@pytest.mark.parametrize("override, match", [
    ({"sent": (0.0,)}, "length"),
    ({"host_ids": ()}, "host"),
    ({"latencies": (-1.0,) + (1.0,) * 119}, "latenc"),
    ({"replicas": True}, "replicas"),
    ({"until": 5.0}, "until"),
])
def test_a_malformed_real_run_is_refused(override, match):
    base = {"schedule": _schedule(6), "sent": _schedule(6), "latencies": (1.0,) * 120,
            "replicas": 1, "until": 60.0, "host_ids": ("w1",)}
    with pytest.raises(ValueError, match=match):
        RealRun(**{**base, **override})
