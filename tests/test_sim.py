import pytest

from autoscale.service import ServiceCurve
from autoscale.sim import SimResult, run_fixed_capacity

# 0.5 s at every concurrency, measured out to 100. Wide enough that capacity
# (`replicas * max_measured_concurrency`) never binds, so it is the curve for
# tests about accounting and input validation rather than about queueing.
FLAT = ServiceCurve(
    points=[(1, 0.5, 2.0, 0.5), (100, 0.5, 200.0, 1.0)], measured=True
)

# Also 0.5 s at every concurrency, but measured only to 2, so one replica
# holds two requests and a third queues. This is the curve for the queueing
# tests: capacity binds at a hand-checkable size and the arithmetic stays
# trivial because the latency never moves.
NARROW = ServiceCurve(points=[(1, 0.5, 2.0, 0.5), (2, 0.5, 4.0, 0.6)], measured=True)


def test_one_arrival_on_an_idle_replica_waits_only_for_service():
    result = run_fixed_capacity(arrivals=[0.0], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5])


def test_requests_beyond_capacity_queue_rather_than_vanish():
    """Three simultaneous arrivals on one replica whose curve was measured to
    concurrency 2, so capacity is 2:

    t=0.0  A dispatched at per-replica load ceil(1/1)=1 -> 0.5 s, done 0.5
           B dispatched at per-replica load ceil(2/1)=2 -> 0.5 s, done 0.5
           C queues: two in flight is the whole capacity
    t=0.5  A completes (latency 0.5); C dispatched at load ceil(2/1)=2 ->
           0.5 s, done 1.0
    t=0.5  B completes (latency 0.5)
    t=1.0  C completes, latency 1.0 - 0.0 = 1.0
    """
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=NARROW, until=10.0)

    assert result.latencies == pytest.approx([0.5, 0.5, 1.0])
    assert len(result.latencies) == 3


def test_two_replicas_remove_the_queue_one_replica_cannot_hold():
    """Four simultaneous arrivals against NARROW (two requests per replica).

    One replica, capacity 2: A and B are served at once and complete at 0.5;
    C and D are dispatched as those two complete and finish at 1.0, so their
    latencies are 1.0.

    Two replicas, capacity 4: all four are dispatched at t=0, at per-replica
    loads ceil(1/2)=1, ceil(2/2)=1, ceil(3/2)=2, ceil(4/2)=2 -- all 0.5 s on
    this curve -- so nothing queues and every latency is 0.5.
    """
    one = run_fixed_capacity(arrivals=[0.0] * 4, replicas=1, curve=NARROW, until=10.0)
    two = run_fixed_capacity(arrivals=[0.0] * 4, replicas=2, curve=NARROW, until=10.0)

    assert one.latencies == pytest.approx([0.5, 0.5, 1.0, 1.0])
    assert two.latencies == pytest.approx([0.5, 0.5, 0.5, 0.5])


def test_requests_still_in_flight_when_the_window_ends_are_counted_not_dropped():
    """Dropping them would make every overloaded policy look better than it is,
    which is the exact direction of error that would flatter a lagging signal.

    Three arrivals, one replica, capacity 2: A and B complete at 0.5, C is
    dispatched at 0.5 and would complete at 1.0, past the window.
    """
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=NARROW, until=0.6)

    assert result.completed == 2
    assert result.unfinished == 1


def test_an_event_landing_exactly_on_the_window_boundary_is_inside_it():
    """`until` is inclusive: a completion at exactly `until` counts. Making the
    break `>=` would discard it and report a finished request as unfinished."""
    result = run_fixed_capacity(arrivals=[0.0], replicas=1, curve=FLAT, until=0.5)

    assert (result.completed, result.unfinished) == (1, 0)
    assert result.latencies == pytest.approx([0.5])


def test_zero_replicas_is_refused():
    with pytest.raises(ValueError, match="at least one replica"):
        run_fixed_capacity(arrivals=[0.0], replicas=0, curve=FLAT, until=1.0)


def test_an_empty_arrival_trace_is_refused():
    """A discard reason in the pre-registration, surfaced as an error here so it
    cannot silently produce a run with no latencies and a perfect p99."""
    with pytest.raises(ValueError, match="empty"):
        run_fixed_capacity(arrivals=[], replicas=1, curve=FLAT, until=1.0)


def test_result_reports_the_percentiles_the_pre_registration_names():
    # 600 arrivals, not 200: `percentiles` enforces artifact 1's sample floors
    # and p99 needs 500. A spike in the real sweep generates thousands, which
    # is the justification the pre-registration gives for reporting p99 at all,
    # so a test asserting the p99 key exists has to clear the same bar.
    result = run_fixed_capacity(
        arrivals=[float(i) * 0.1 for i in range(600)], replicas=2, curve=FLAT, until=100.0
    )

    assert set(result.percentiles()) == {"p50", "p90", "p95", "p99"}
    assert result.percentiles()["p50"] <= result.percentiles()["p99"]


# --- self-review additions -------------------------------------------------
#
# `RISING` is the shape that makes the concurrency-dependent service time
# observable at all: FLAT and NARROW return 0.5 s at every concurrency, so
# they cannot distinguish "reads the curve at the right per-replica load" from
# "ignores load". Measured to 2, so one replica holds two requests.
RISING = ServiceCurve(points=[(1, 1.0, 10.0, 0.2), (2, 2.0, 12.0, 0.4)], measured=True)

# The placeholder's shape, truncated at the concurrency-16 point: latency flat
# then rising, and a measured range wide enough to show one replica batching.
# latency_at: 1 -> 0.30, 2 -> 0.31, 4 -> 0.33, 8 -> 0.38, 16 -> 0.52, with
# linear interpolation in between (3 -> 0.32, 5 -> 0.3425, 6 -> 0.355,
# 7 -> 0.3675, 9 -> 0.3975, 10 -> 0.415, ... 15 -> 0.5025).
BATCHING = ServiceCurve(
    points=[
        (1, 0.30, 53.0, 0.18),
        (2, 0.31, 103.0, 0.34),
        (4, 0.33, 194.0, 0.61),
        (8, 0.38, 337.0, 0.85),
        (16, 0.52, 492.0, 0.96),
    ],
    measured=True,
)

# Service times of one replica batching 1..16 requests, read off BATCHING by
# hand. Spelled out rather than computed from the curve so the test checks the
# simulator against arithmetic done independently of it.
BATCHING_1_TO_16 = [
    0.30,
    0.31,
    0.32,
    0.33,
    0.3425,
    0.355,
    0.3675,
    0.38,
    0.3975,
    0.415,
    0.4325,
    0.45,
    0.4675,
    0.485,
    0.5025,
    0.52,
]


def test_a_hand_computed_two_replica_run_with_staggered_arrivals():
    """Worked by hand against RISING, replicas=2 (capacity 2*2=4), arrivals at
    0.0, 0.5, 0.6. Per-replica load is ceil(in_flight / replicas):

    t=0.0  A arrives, fleet idle -> load ceil(1/2)=1, curve 1.0 s, done 1.0
    t=0.5  B arrives, one in flight -> load ceil(2/2)=1 (one request each),
           curve 1.0 s, done 1.5
    t=0.6  C arrives, two in flight -> load ceil(3/2)=2, curve 2.0 s, done 2.6
    t=1.0  A completes, latency 1.0 - 0.0 = 1.0
    t=1.5  B completes, latency 1.5 - 0.5 = 1.0
    t=2.6  C completes, latency 2.6 - 0.6 = 2.0

    Under the old fleet-concurrency model B was charged the curve at 2 and
    C queued behind a two-request capacity; both are wrong for two replicas
    that between them were measured serving four.
    """
    result = run_fixed_capacity(arrivals=[0.0, 0.5, 0.6], replicas=2, curve=RISING, until=10.0)

    assert result.latencies == pytest.approx([1.0, 1.0, 2.0])
    assert result.completed == 3
    assert result.unfinished == 0


def test_a_later_arrival_cannot_overtake_an_earlier_one():
    """FIFO, checked with two requests in the queue at once so LIFO gives a
    different answer. NARROW, one replica (capacity 2), arrivals 0.0/0.1/0.2/0.3:

    t=0.0  A dispatched (load 1), done 0.5
    t=0.1  B dispatched (load 2), done 0.6
    t=0.2  C queues;  t=0.3  D queues
    t=0.5  A completes (latency 0.5); FIFO takes C -> done 1.0
    t=0.6  B completes (latency 0.5); FIFO takes D -> done 1.1
    t=1.0  C completes, latency 1.0 - 0.2 = 0.8
    t=1.1  D completes, latency 1.1 - 0.3 = 0.8

    Serving the queue from the back would give 0.5, 0.5, 0.7, 0.9 instead --
    D overtaking C, and C punished worst for arriving first.
    """
    result = run_fixed_capacity(
        arrivals=[0.0, 0.1, 0.2, 0.3], replicas=1, curve=NARROW, until=10.0
    )

    assert result.latencies == pytest.approx([0.5, 0.5, 0.8, 0.8])


def test_simultaneous_arrivals_spread_across_replicas_each_see_load_one():
    """Eight requests arriving at once on eight replicas: even balancing puts
    one on each, so every one of them is charged the curve at per-replica load
    ceil(i/8)=1, i.e. 0.30 s. The old model charged the last-dispatched the
    curve at fleet concurrency 8 (0.38 s) even though its replica was serving
    one request."""
    result = run_fixed_capacity(
        arrivals=[0.0] * 8, replicas=8, curve=BATCHING, until=10.0
    )

    assert result.latencies == pytest.approx([0.30] * 8)
    assert result.completed == 8


def test_one_replica_batches_up_to_its_measured_concurrency():
    """Eight requests arriving at once on ONE replica whose curve was measured
    to 16: capacity is 16, so all eight are dispatched immediately and none
    queues. They fill the batch one at a time, so the per-replica load rises
    1, 2, ... 8 as they go in and the service times are the hand-read curve
    values 0.30, 0.31, 0.32, 0.33, 0.3425, 0.355, 0.3675, 0.38.

    All arrive at 0.0, so latency equals service time, and every one lands
    inside a 0.4 s window. Under the old model capacity would be 1: one
    request served and seven queued, with completions marching out past 2 s.
    """
    result = run_fixed_capacity(arrivals=[0.0] * 8, replicas=1, curve=BATCHING, until=0.4)

    assert result.latencies == pytest.approx(BATCHING_1_TO_16[:8])
    assert (result.completed, result.unfinished) == (8, 0)


def test_twenty_requests_on_one_replica_dispatch_sixteen_and_queue_four():
    """Capacity is 1 * 16, so sixteen of the twenty go in at t=0 and four wait.

    The sixteen are charged loads 1..16, completing at those same times
    (0.30 ... 0.52). Each of the first four completions frees a slot, and the
    replacement is dispatched into a batch of sixteen again -- load ceil(16/1)
    = 16, service 0.52 -- so the queued four complete at 0.30+0.52=0.82,
    0.31+0.52=0.83, 0.32+0.52=0.84 and 0.33+0.52=0.85.
    """
    result = run_fixed_capacity(arrivals=[0.0] * 20, replicas=1, curve=BATCHING, until=10.0)

    assert result.latencies[:16] == pytest.approx(BATCHING_1_TO_16)
    assert result.latencies[16:] == pytest.approx([0.82, 0.83, 0.84, 0.85])
    assert (result.completed, result.unfinished) == (20, 0)


def test_adding_replicas_reduces_latency_monotonically():
    """Thirty-two simultaneous requests against BATCHING, replicas 1/2/4/8.

    r=1: capacity 16, so sixteen queue; each queued request is dispatched into
         a full batch (0.52 s) as a slot frees, and the last one leaves at
         0.52 + 0.52 = 1.04.
    r=2: capacity 32, loads ceil(i/2) = 1,1,2,2,...,16,16 -> worst 0.52.
    r=4: loads ceil(i/4) = 1,1,1,1,...,8,8,8,8 -> worst latency_at(8) = 0.38.
    r=8: loads ceil(i/8) = 1..4 -> worst latency_at(4) = 0.33.

    Reads the MAXIMUM, not `percentiles()["p99"]`. It used to read the p99, but
    the quantity it is about is the worst request, and "p99 of 32 samples" was
    only ever a spelling of that -- one that happened to coincide under
    nearest-rank indexing (index 31) and does not under the interpolated
    convention artifact 1 uses. `percentiles()` now enforces a 500-sample floor
    for p99 precisely so that "p99" cannot mean "the worst of 32", so this test
    says what it means instead of being given an exemption.
    """
    p99 = {
        r: max(
            run_fixed_capacity(
                arrivals=[0.0] * 32, replicas=r, curve=BATCHING, until=100.0
            ).latencies
        )
        for r in (1, 2, 4, 8)
    }

    assert p99[1] == pytest.approx(1.04)
    assert p99[2] == pytest.approx(0.52)
    assert p99[4] == pytest.approx(0.38)
    assert p99[8] == pytest.approx(0.33)
    assert p99[1] > p99[2] > p99[4] > p99[8]


def test_nothing_is_extrapolated_inside_the_measured_range():
    """With capacity = replicas * max_measured_concurrency and load
    ceil(in_flight / replicas), the load can never exceed the measured range
    for a curve whose top point is a whole number of requests -- which is the
    point of tying capacity to the measured range."""
    result = run_fixed_capacity(arrivals=[0.0] * 32, replicas=2, curve=BATCHING, until=100.0)

    assert result.extrapolated_samples == 0


def test_a_fractional_measured_range_can_still_admit_an_extrapolated_request():
    """The one way the load leaves the measured range, and why the guard stays.

    This curve's top measured point is 1.5, so one replica has capacity 1.5 --
    which admits TWO requests, because `len(in_flight) < 1.5` is true at one.
    The second is then charged the curve at load 2, above anything measured.
    Hand-computed: A goes in at load 1 (0.5 s, done 0.5); B at load 2
    (extrapolated, clamped to 0.6, done 0.6); C queues, is dispatched at 0.5
    at load 2 (extrapolated again, 0.6) and completes at 1.1.
    """
    fractional = ServiceCurve(
        points=[(1, 0.5, 2.0, 0.5), (1.5, 0.6, 3.0, 0.6)], measured=True
    )

    result = run_fixed_capacity(arrivals=[0.0] * 3, replicas=1, curve=fractional, until=10.0)

    assert result.latencies == pytest.approx([0.5, 0.6, 1.1])
    assert result.extrapolated_samples == 2


def test_requests_left_in_flight_and_requests_left_waiting_are_both_counted():
    """Both terms of the unfinished tally, separately: with two replicas and
    two arrivals nothing queues, so the count is entirely in-flight; with one
    replica on NARROW and three arrivals, two are in flight and one is still
    waiting, so a tally that counted only in-flight would report 2."""
    in_flight_only = run_fixed_capacity(
        arrivals=[0.0, 0.0], replicas=2, curve=FLAT, until=0.3
    )
    assert (in_flight_only.completed, in_flight_only.unfinished) == (0, 2)

    with_a_queue = run_fixed_capacity(
        arrivals=[0.0, 0.0, 0.0], replicas=1, curve=NARROW, until=0.3
    )
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
    rather than a subtly reordered one. Checked on NARROW, where capacity
    binds, so a reordering would actually change the latencies."""
    shuffled = run_fixed_capacity(arrivals=[0.2, 0.0, 0.1], replicas=1, curve=NARROW, until=10.0)
    ordered = run_fixed_capacity(arrivals=[0.0, 0.1, 0.2], replicas=1, curve=NARROW, until=10.0)

    assert ordered.latencies == pytest.approx([0.5, 0.5, 0.8])
    assert shuffled.latencies == pytest.approx(ordered.latencies)


@pytest.mark.parametrize("bad", [1.5, 2.0, float("nan"), float("inf"), True])
def test_a_non_integer_replica_count_is_refused(bad):
    """A fractional count makes both halves of the model incoherent: capacity
    `1.5 * max_measured_concurrency` is not a whole number of requests, and
    `ceil(in_flight / 1.5)` is a per-replica load on a replica that does not
    exist. A NaN count blocks every dispatch and reports the whole trace
    unfinished. Neither raises on its own."""
    with pytest.raises(ValueError, match="replicas must be an int"):
        run_fixed_capacity(arrivals=[0.0, 0.0], replicas=bad, curve=FLAT, until=10.0)


def test_capacity_is_replicas_times_the_measured_concurrency():
    """Five simultaneous arrivals, two replicas, NARROW (measured to 2), so
    capacity is 2*2 = 4: four are served at once at loads 1, 1, 2, 2 and
    complete at 0.5, and the fifth is dispatched as the first slot frees and
    completes at 1.0. Capacity = replicas alone would serve two and give
    0.5, 0.5, 1.0, 1.0, 1.5; capacity = the curve's range alone would do the
    same."""
    result = run_fixed_capacity(arrivals=[0.0] * 5, replicas=2, curve=NARROW, until=10.0)

    assert result.latencies == pytest.approx([0.5, 0.5, 0.5, 0.5, 1.0])


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


def _result_with_latencies(latencies):
    """A SimResult carrying only what `percentiles()` reads, so these tests do
    not depend on the simulator's other bookkeeping."""
    return SimResult(latencies=list(latencies), completed=len(latencies))


def test_percentiles_use_the_same_convention_as_artifact_one():
    """Artifact 2 used nearest-rank (`ordered[int(p * n)]`) while artifact 1
    interpolates. Two artifacts in one publication reporting "p50" two ways is
    a discrepancy a reader finds and an author cannot explain."""
    from autoscale.stats import quantile

    ordered = [float(i) for i in range(1000)]
    got = _result_with_latencies(ordered).percentiles()
    assert got["p50"] == pytest.approx(quantile(ordered, 0.50))
    assert got["p99"] == pytest.approx(quantile(ordered, 0.99))


def test_percentiles_refuse_a_run_with_too_few_completions():
    """A run that completed 12 requests has no p99 -- it has a second-worst
    latency. Before the floor, that number was reported in the same dict field
    as a p99 backed by thousands of requests, and the sweep averaged the two
    together.

    The refusal names p50, not p99: at 12 samples every floor is unmet and the
    first one checked is the one reported. That is the right message -- nothing
    about this run is publishable -- and asserting on "p99" here would be
    asserting on iteration order.
    """
    with pytest.raises(ValueError, match="p50 needs at least 20"):
        _result_with_latencies([float(i) for i in range(12)]).percentiles()


def test_p99_has_its_own_floor_above_the_others():
    """100 completions clear p50 (20), p90 (50) and p95 (80) but not p99 (500).
    This is the case the p99 floor exists for: a run with enough data to report
    a median and not nearly enough to report a tail."""
    hundred = [float(i) for i in range(100)]
    with pytest.raises(ValueError, match="p99 needs at least 500"):
        _result_with_latencies(hundred).percentiles()

    from autoscale.stats import percentiles as raw

    assert set(raw(hundred, want=("p50", "p90", "p95"))) == {"p50", "p90", "p95"}
