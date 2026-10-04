"""Artifact 2's gate: its run record, the replay into the simulator, and its
pre-registered constants. The band and verdict arithmetic is tested in
tests/test_validation_band.py."""

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.sim import run_fixed_capacity
from autoscale.validation import (
    MIN_COMPARED_BINS,
    RealRun,
    predicted_trajectory,
    tolerance_band,
    validate,
)
from autoscale.validation_band import trajectory

# Enough bins for MIN_COMPARED_BINS judged bins with two to spare.
BINS = MIN_COMPARED_BINS + 2


# 20 requests per 10 s bin, 0.4 s apart from the bin start: the p50 sample
# floor exactly. 0.4 s spacing against the placeholder's 0.30 s
# concurrency-1 latency means one replica serves each request alone, so the
# model predicts 0.30 s everywhere. The last arrival in a bin is at +7.6 s,
# leaving a 2.4 s drain margin: the fixture latencies (at most 1.2 s) all
# finish inside the window, so the window cut leaves them alone.
def _schedule(bins):
    return tuple(b * 10.0 + k * 0.4 for b in range(bins) for k in range(20))


def _run(latency, bins=BINS, *, sent=None, replicas=1, until=None):
    schedule = _schedule(bins)
    lat = latency if isinstance(latency, list) else [latency] * len(schedule)
    return RealRun(schedule=schedule, sent=schedule if sent is None else sent,
                   latencies=tuple(lat), replicas=replicas,
                   until=10.0 * bins if until is None else until, host_ids=("w1",))


def _send_one(at, index=20, bins=BINS):
    """The schedule, with request `index` sent at `at` instead. Index 20 is
    scheduled at exactly 10.0 s, so the jitter is exact in binary."""
    schedule = _schedule(bins)
    return schedule[:index] + (at,) + schedule[index + 1:]


def _per_bin(latencies_by_bin):
    return [lat for lat in latencies_by_bin for _ in range(20)]


# ---- the replay -------------------------------------------------------------

def test_the_prediction_replays_the_schedule_through_the_simulator():
    bins = predicted_trajectory(_schedule(2), replicas=1, curve=SERVICE_CURVE_PLACEHOLDER,
                                until=20.0, bin_seconds=10.0)
    assert [b.p50 for b in bins] == pytest.approx([0.30, 0.30])


def test_the_replay_keeps_its_backlog_as_censored_bins():
    """The request arriving at 17.6 s is still in service when the window
    closes at 17.7 s. Dropping it would leave its bin 19 completions and call
    it thin; it is the backlog, so the bin is censored."""
    bins = predicted_trajectory(_schedule(2), replicas=1, curve=SERVICE_CURVE_PLACEHOLDER,
                                until=17.7, bin_seconds=10.0)
    assert (bins[-1].status, bins[-1].unfinished) == ("censored", 1)


# ---- the window cut ---------------------------------------------------------

def _dense():
    """0.5 s spacing to the very end of a 60 s window: the request sent at
    59.5 s with a 1.0 s latency finishes after the window closes."""
    schedule = tuple(i * 0.5 for i in range(120))
    return RealRun(schedule=schedule, sent=schedule, latencies=(1.0,) * 120,
                   replicas=1, until=60.0, host_ids=("w1",))


def test_a_request_finishing_after_the_window_is_unfinished():
    run = _dense()
    assert run.windowed_latencies()[-1] is None
    assert run.latencies[-1] == 1.0  # the record itself is not rewritten
    band = tolerance_band([run, run, run])
    assert band[-1].status == "censored" and band[-2].status == "ok"


def test_a_request_finishing_exactly_at_the_window_end_is_completed():
    """Strict `>`, as the simulator's `event.time > until`."""
    assert _dense().windowed_latencies()[-2] == 1.0  # sent 59.0, latency 1.0


def test_the_cut_uses_the_send_time_not_the_schedule():
    """Latency is measured from the send, so the send is when the clock
    started: scheduled 59.2 + 0.5 = 59.7 would call it finished, but it was
    sent at 59.6 and finished at 60.1."""
    run = RealRun(schedule=(59.2,), sent=(59.6,), latencies=(0.5,), replicas=1,
                  until=60.0, host_ids=("w1",))
    assert run.windowed_latencies() == (None,)


def test_an_unfinished_request_stays_unfinished():
    run = RealRun(schedule=(1.0,), sent=(1.0,), latencies=(None,), replicas=1,
                  until=60.0, host_ids=("w1",))
    assert run.windowed_latencies() == (None,)


def test_the_window_cut_matches_the_simulators_bin_for_bin():
    """Steady load, then 40 rps into the last ten seconds -- above one
    placeholder replica's ~30 rps ceiling -- so requests queue and some finish
    after 60 s. Replayed with a long window, every request gets a latency; a
    perfect real run reporting those latencies must then bin, after the cut,
    exactly as the simulator does with the window closing at 60 s."""
    schedule = _schedule(5) + tuple(50.0 + i * 0.025 for i in range(400))
    drained = run_fixed_capacity(list(schedule), 1, SERVICE_CURVE_PLACEHOLDER, 1000.0)
    assert drained.unfinished == 0
    pairs = sorted(drained.completed_requests())
    assert tuple(a for a, _ in pairs) == schedule
    real = RealRun(schedule=schedule, sent=schedule, latencies=tuple(lat for _, lat in pairs),
                   replicas=1, until=60.0, host_ids=("w1",))
    cut = trajectory(real.schedule, real.windowed_latencies(), until=60.0, bin_seconds=10.0)
    predicted = predicted_trajectory(schedule, 1, SERVICE_CURVE_PLACEHOLDER, 60.0,
                                     bin_seconds=10.0)
    assert cut == predicted
    assert predicted[-1].status == "censored" and predicted[-1].completed > 0


# ---- the band ---------------------------------------------------------------

def test_bins_are_keyed_by_scheduled_arrival_not_send_time():
    """The request scheduled at 10.0 s goes out at 9.5 s -- within the jitter
    bound, but across a bin boundary. Keyed by send time, bin 1 would drop to
    19 requests and go thin on this repeat alone: a difference the driver
    made, not the system."""
    early = _run(1.0, sent=_send_one(9.5))
    band = tolerance_band([_run(1.0), _run(1.1), early])
    assert band[1].status == "ok"


def test_the_band_comes_from_the_real_repeats():
    band = tolerance_band([_run(1.0), _run(1.2), _run(1.1)])
    assert (band[0].lo, band[0].hi) == pytest.approx((1.0, 1.2))


@pytest.mark.parametrize("count", [2, 4])
def test_any_count_but_exactly_three_repeats_is_refused(count):
    """Fewer is too little spread to mean anything; more widens a min-max band,
    and an open count lets the band grow until the model fits."""
    with pytest.raises(ValueError, match="exactly 3"):
        tolerance_band([_run(1.0 + 0.1 * i) for i in range(count)])


def test_repeats_of_different_schedules_are_refused():
    """The band is the system's own reproducibility on ONE trace. Repeats of
    different traces fold traffic variance into it and widen it for free."""
    shifted = _schedule(BINS)[1:] + (BINS * 10.0 - 0.1,)
    other = RealRun(schedule=shifted, sent=shifted, latencies=(1.0,) * len(shifted),
                    replicas=1, until=BINS * 10.0, host_ids=("w1",))
    with pytest.raises(ValueError, match="schedule"):
        tolerance_band([_run(1.0), _run(1.1), other])


@pytest.mark.parametrize("override", [{"replicas": 2}, {"until": BINS * 10.0 + 10.0}])
def test_repeats_at_another_capacity_or_window_are_refused(override):
    with pytest.raises(ValueError, match="replicas or window"):
        tolerance_band([_run(1.0), _run(1.1), _run(1.2, **override)])


@pytest.mark.parametrize("sent", [
    tuple(t + 2.0 for t in _schedule(BINS)),  # the whole run late
    _send_one(9.0),                           # one request a second EARLY
    _send_one(10.5001),                       # just over the bound
])
def test_a_run_that_did_not_hold_the_schedule_is_refused(sent):
    with pytest.raises(ValueError, match="jitter"):
        tolerance_band([_run(1.0), _run(1.1), _run(1.2, sent=sent)])


def test_jitter_exactly_at_the_bound_is_accepted():
    band = tolerance_band([_run(1.0), _run(1.1), _run(1.2, sent=_send_one(10.5))])
    assert band[1].status == "ok"


# ---- the verdict ------------------------------------------------------------

def test_real_runs_that_bracket_the_model_pass():
    runs = [_run(0.29), _run(0.30), _run(0.31)]
    v = validate(runs, SERVICE_CURVE_PLACEHOLDER)
    assert (v.outcome, v.compared) == ("passed", BINS)


def test_real_runs_far_from_the_model_fail_with_the_distance():
    v = validate([_run(1.0), _run(1.1), _run(1.2)], SERVICE_CURVE_PLACEHOLDER)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.70)


def test_a_run_too_short_to_judge_is_not_evaluable():
    """One bin short of the pre-registered minimum: agreement on all of them
    is still not a pass."""
    bins = MIN_COMPARED_BINS - 1
    runs = [_run(0.29, bins=bins), _run(0.30, bins=bins), _run(0.31, bins=bins)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER).outcome == "not_evaluable"


@pytest.mark.parametrize("missing, outcome", [(BINS // 2, "passed"), (BINS // 2 + 1, "failed")])
def test_the_gate_tolerates_misses_in_up_to_half_the_bins(missing, outcome):
    """The model (0.30 s everywhere) sits inside the band in the first bins
    and far below it in the last `missing`."""
    def run(inside, outside):
        return _run(_per_bin([inside] * (BINS - missing) + [outside] * missing))
    runs = [run(0.29, 1.0), run(0.30, 1.1), run(0.31, 1.2)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER).outcome == outcome


@pytest.mark.parametrize("hi, outcome", [(0.2995, "passed"), (0.298, "failed")])
def test_the_band_edge_tolerance_is_a_millisecond(hi, outcome):
    """0.5 ms of residue at the edge is absorbed; 2 ms is a miss."""
    runs = [_run(0.29), _run(0.29), _run(hi)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER).outcome == outcome


# ---- the record -------------------------------------------------------------

@pytest.mark.parametrize("override, match", [
    ({"sent": (0.0,)}, "length"),
    ({"host_ids": ()}, "host"),
    ({"latencies": (-1.0,) + (1.0,) * 119}, "latenc"),
    ({"replicas": True}, "replicas"),
    ({"until": 5.0}, "until"),
    ({"schedule": (1.0, 0.5) + tuple(i * 0.5 for i in range(2, 120))}, "ascending"),
    ({"sent": (float("nan"),) + tuple(i * 0.5 for i in range(1, 120))}, "send time"),
])
def test_a_malformed_real_run_is_refused(override, match):
    schedule = tuple(i * 0.5 for i in range(120))
    base = {"schedule": schedule, "sent": schedule, "latencies": (1.0,) * 120,
            "replicas": 1, "until": 60.0, "host_ids": ("w1",)}
    with pytest.raises(ValueError, match=match):
        RealRun(**{**base, **override})


def test_the_constants_are_the_ones_the_preregistration_states():
    from pathlib import Path

    from autoscale import validation

    prereg = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a2.md").read_text()
    assert "## Validation gate — pass rule" in prereg
    assert validation.REPEATS == 3 and "exactly **3** real runs" in prereg
    assert validation.BIN_SECONDS == 10.0 and "**10 s** bin" in prereg
    assert validation.MAX_SEND_JITTER_SECONDS == 0.5 and "**0.5 s**" in prereg
    assert validation.MIN_COMPARED_BINS == 10 and "at least **10** judged bins" in prereg
    assert validation.MAX_MISS_FRACTION == 0.5 and "**no more than half**" in prereg
    assert validation.BAND_EDGE_TOLERANCE_SECONDS == 0.001 and "**1 ms**" in prereg
