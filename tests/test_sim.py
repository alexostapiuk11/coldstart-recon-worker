import pytest

from autoscale.service import ServiceCurve
from autoscale.sim import SimResult, run_fixed_capacity

FLAT = ServiceCurve(
    points=[(1, 0.5, 2.0, 0.5), (100, 0.5, 200.0, 1.0)], measured=True
)


def test_one_arrival_on_an_idle_replica_waits_only_for_service():
    result = run_fixed_capacity(arrivals=[0.0], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5])


def test_requests_beyond_capacity_queue_rather_than_vanish():
    """Three simultaneous arrivals, one replica, 0.5 s service: they complete
    at 0.5, 1.0 and 1.5, so latencies are 0.5, 1.0, 1.5."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5, 1.0, 1.5])
    assert len(result.latencies) == 3


def test_two_replicas_halve_the_queue():
    result = run_fixed_capacity(arrivals=[0.0, 0.0], replicas=2, curve=FLAT, until=10.0)
    assert result.latencies == pytest.approx([0.5, 0.5])


def test_requests_still_in_flight_when_the_window_ends_are_counted_not_dropped():
    """Dropping them would make every overloaded policy look better than it is,
    which is the exact direction of error that would flatter a lagging signal."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=FLAT, until=0.6)

    assert result.completed == 1
    assert result.unfinished == 2


def test_zero_replicas_is_refused():
    with pytest.raises(ValueError, match="at least one replica"):
        run_fixed_capacity(arrivals=[0.0], replicas=0, curve=FLAT, until=1.0)


def test_an_empty_arrival_trace_is_refused():
    """A discard reason in the pre-registration, surfaced as an error here so it
    cannot silently produce a run with no latencies and a perfect p99."""
    with pytest.raises(ValueError, match="empty"):
        run_fixed_capacity(arrivals=[], replicas=1, curve=FLAT, until=1.0)


def test_result_reports_the_percentiles_the_pre_registration_names():
    result = run_fixed_capacity(
        arrivals=[float(i) * 0.1 for i in range(200)], replicas=2, curve=FLAT, until=100.0
    )

    assert set(result.percentiles()) == {"p50", "p90", "p95", "p99"}
    assert result.percentiles()["p50"] <= result.percentiles()["p99"]


# --- self-review additions -------------------------------------------------
#
# `RISING` is the shape that makes the concurrency-dependent service time
# observable at all: FLAT returns 0.5 s at every concurrency, so it cannot
# distinguish "reads the curve at the right concurrency" from "ignores
# concurrency". Its measured range stops at 2, so a query at 3 is
# extrapolation and the sim must say so.
RISING = ServiceCurve(points=[(1, 1.0, 10.0, 0.2), (2, 2.0, 12.0, 0.4)], measured=True)


def test_a_hand_computed_two_replica_run_with_staggered_arrivals():
    """Worked by hand against RISING, replicas=2, arrivals at 0.0, 0.5, 0.6:

    t=0.0  A arrives, fleet idle -> curve at concurrency 1 = 1.0 s, done 1.0
    t=0.5  B arrives, one in flight -> curve at concurrency 2 = 2.0 s, done 2.5
    t=0.6  C arrives, both positions full -> queues
    t=1.0  A completes, latency 1.0 - 0.0 = 1.0; C dispatched at concurrency 2
           = 2.0 s, done 3.0
    t=2.5  B completes, latency 2.5 - 0.5 = 2.0
    t=3.0  C completes, latency 3.0 - 0.6 = 2.4
    """
    result = run_fixed_capacity(arrivals=[0.0, 0.5, 0.6], replicas=2, curve=RISING, until=10.0)

    assert result.latencies == pytest.approx([1.0, 2.0, 2.4])
    assert result.completed == 3
    assert result.unfinished == 0


def test_a_later_arrival_cannot_overtake_an_earlier_one():
    """FIFO, checked with distinct arrival times so LIFO would give a different
    answer: 0.0/0.1/0.2 on one replica at 0.5 s complete at 0.5, 1.0 and 1.5,
    for latencies 0.5, 0.9, 1.3. Serving the queue from the back would instead
    give 0.5, 0.8, 1.4 -- the earliest arrival punished worst."""
    result = run_fixed_capacity(arrivals=[0.0, 0.1, 0.2], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5, 0.9, 1.3])


def test_simultaneous_dispatches_read_the_curve_at_one_two_and_three():
    """Documents the within-batch skew the module docstring names: three
    requests arriving at the same instant on three replicas are charged the
    curve at concurrency 1, 2 and 3 as the positions fill, not a common value.
    RISING stops at concurrency 2, so the third is extrapolation and is
    counted."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=3, curve=RISING, until=10.0)

    assert result.latencies == pytest.approx([1.0, 2.0, 2.0])
    assert result.extrapolated_samples == 1


def test_nothing_is_extrapolated_inside_the_measured_range():
    result = run_fixed_capacity(arrivals=[0.0, 0.0], replicas=2, curve=RISING, until=10.0)

    assert result.extrapolated_samples == 0


def test_requests_left_in_flight_and_requests_left_waiting_are_both_counted():
    """Both terms of the unfinished tally, separately: with two replicas and
    two arrivals nothing queues, so the count is entirely in-flight; with one
    replica and three arrivals one is in flight and two are still waiting."""
    in_flight_only = run_fixed_capacity(
        arrivals=[0.0, 0.0], replicas=2, curve=FLAT, until=0.3
    )
    assert (in_flight_only.completed, in_flight_only.unfinished) == (0, 2)

    with_a_queue = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=FLAT, until=0.3)
    assert (with_a_queue.completed, with_a_queue.unfinished) == (0, 3)


def test_every_arrival_is_accounted_for_however_the_window_falls():
    """completed + unfinished == len(arrivals), unconditionally. This is what
    stops an overloaded run from looking uncongested: no request can leave the
    accounting by being cut off at the window boundary."""
    arrivals = [float(i) * 0.05 for i in range(40)]
    for until in (0.0, 0.3, 1.0, 2.5, 7.0, 60.0):
        result = run_fixed_capacity(
            arrivals=[t for t in arrivals if t <= until], replicas=2, curve=FLAT, until=until
        )
        assert result.completed + result.unfinished == len([t for t in arrivals if t <= until])


def test_an_arrival_after_the_window_ends_is_refused_not_silently_dropped():
    """Such a request is popped after the loop has broken, so it lands in
    neither tally and vanishes -- which would make an overloaded arm replayed
    against a short window look uncongested."""
    with pytest.raises(ValueError, match="after the window ends"):
        run_fixed_capacity(arrivals=[0.0, 5.0], replicas=1, curve=FLAT, until=1.0)


@pytest.mark.parametrize("until", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_window_is_refused(until):
    """NaN never trips `event.time > until`, so the window silently becomes
    unbounded and the run reports zero unfinished; -inf ends it before the
    first event."""
    with pytest.raises(ValueError, match="until is"):
        run_fixed_capacity(arrivals=[0.0, 0.0], replicas=1, curve=FLAT, until=until)


def test_a_negative_window_is_refused():
    with pytest.raises(ValueError, match="until must be non-negative"):
        run_fixed_capacity(arrivals=[0.0], replicas=1, curve=FLAT, until=-1.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_arrival_time_is_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        run_fixed_capacity(arrivals=[0.0, bad], replicas=1, curve=FLAT, until=10.0)


def test_a_negative_arrival_time_is_refused():
    with pytest.raises(ValueError, match="is negative"):
        run_fixed_capacity(arrivals=[0.0, -1.0], replicas=1, curve=FLAT, until=10.0)


def test_an_unsorted_trace_replays_as_if_it_had_been_sorted():
    """Documented, not accidental: every arrival is pushed before the first
    pop, so the heap orders them and the queue is still served in arrival
    order. A caller handing over an unsorted trace gets the right answer
    rather than a subtly reordered one."""
    shuffled = run_fixed_capacity(arrivals=[0.2, 0.0, 0.1], replicas=1, curve=FLAT, until=10.0)
    ordered = run_fixed_capacity(arrivals=[0.0, 0.1, 0.2], replicas=1, curve=FLAT, until=10.0)

    assert shuffled.latencies == pytest.approx(ordered.latencies)


@pytest.mark.parametrize("bad", [1.5, 2.0, float("nan"), float("inf"), True])
def test_a_non_integer_replica_count_is_refused(bad):
    """`len(in_flight) < 1.5` admits two requests, so a fractional count
    silently rounds capacity up; a NaN count blocks every dispatch and reports
    the whole trace unfinished. Neither raises on its own."""
    with pytest.raises(ValueError, match="replicas must be an int"):
        run_fixed_capacity(arrivals=[0.0, 0.0], replicas=bad, curve=FLAT, until=10.0)


def test_capacity_actually_limits_concurrency():
    """Three arrivals on two replicas: two are served at once and the third
    waits, so the latencies are 0.5, 0.5, 1.0 rather than three 0.5s."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=2, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5, 0.5, 1.0])


def test_percentiles_over_zero_completions_refuse_rather_than_report_zeros():
    """A stalled run is the worst outcome, not the best. Reporting p50=p99=0.0
    for it is the same flattering error `unfinished` exists to prevent."""
    with pytest.raises(ValueError, match="no completed requests"):
        SimResult().percentiles()

    stalled = run_fixed_capacity(arrivals=[0.0, 0.0], replicas=1, curve=FLAT, until=0.2)
    assert stalled.completed == 0
    with pytest.raises(ValueError, match="no completed requests"):
        stalled.percentiles()


def test_an_exhausted_iterable_is_refused_like_an_empty_list():
    """A generator is truthy even when it yields nothing, so without
    materialising the trace first it would slip past the emptiness check and
    produce a run over zero requests."""
    with pytest.raises(ValueError, match="empty"):
        run_fixed_capacity(arrivals=(t for t in []), replicas=1, curve=FLAT, until=1.0)
