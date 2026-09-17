"""The closed loop.

`SLOW` is a replica that gets NOTHING from batching: latency rises linearly
with concurrency (1 s at 1, 4 s at 4) so throughput is pinned at 1 req/s, and
its measured range stops at 4. That shape is chosen against the per-replica
concurrency model in `sim`: fleet capacity is
`serving x max_measured_concurrency`, so a curve measured out to concurrency
100 -- as an earlier draft of this file used -- lets ONE replica hold the
entire 5 req/s trace with an empty queue, and every queue-depth policy below
correctly does nothing. The tests then pass or fail on the fixture rather than
on the loop. A replica has to be able to saturate before a scaling test means
anything.
"""

import random

import pytest

from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.service import ServiceCurve
from autoscale.sim import run_with_policy

SLOW = ServiceCurve(points=[(1, 1.0, 1.0, 0.5), (4, 4.0, 1.0, 1.0)], measured=True)
INSTANT_LAG = LagDistribution(samples=[0.0])
SLOW_LAG = LagDistribution(samples=[60.0])


def _controller():
    return Controller(scale_up_at=2.0, scale_down_at=0.5, cooldown=10.0, max_replicas=6)


def test_a_sustained_overload_adds_replicas():
    arrivals = [float(i) * 0.2 for i in range(200)]
    result = run_with_policy(
        arrivals=arrivals,
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.peak_replicas > 1
    assert result.scale_up_events > 0


def test_replicas_do_not_serve_before_their_lag_elapses():
    """The property the whole artifact is about. With a 60 s lag inside a 30 s
    window, a scale-up decision buys nothing and latency must reflect that."""
    arrivals = [float(i) * 0.2 for i in range(150)]
    result = run_with_policy(
        arrivals=arrivals,
        signal="queue_depth",
        controller=_controller(),
        lags=SLOW_LAG,
        curve=SLOW,
        until=30.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.peak_serving_replicas == 1
    assert result.scale_up_events > 0


def test_shorter_lag_produces_lower_p99_all_else_equal():
    """The composition claim in miniature: the only difference between these two
    runs is the lag distribution.

    700 arrivals over a 200 s window, not 400 over 120 s: `percentiles()`
    enforces artifact 1's sample floors and p99 needs 500 completions. The
    point of this test is a p99 comparison, so it has to clear the bar that
    reporting a p99 requires.
    """
    arrivals = [float(i) * 0.2 for i in range(700)]
    kwargs = {
        "arrivals": arrivals,
        "signal": "queue_depth",
        "curve": SLOW,
        "until": 200.0,
        "evaluate_every": 1.0,
    }
    slow = run_with_policy(
        controller=_controller(), lags=SLOW_LAG, rng=random.Random(2), **kwargs
    )
    fast = run_with_policy(
        controller=_controller(), lags=INSTANT_LAG, rng=random.Random(2), **kwargs
    )

    assert fast.percentiles()["p99"] < slow.percentiles()["p99"]


def test_the_same_seed_reproduces_the_run_exactly():
    arrivals = [float(i) * 0.2 for i in range(100)]
    kwargs = {
        "arrivals": arrivals,
        "signal": "utilization",
        "lags": LagDistribution(samples=[10.0, 20.0, 30.0]),
        "curve": SLOW,
        "until": 60.0,
        "evaluate_every": 1.0,
    }
    a = run_with_policy(controller=_controller(), rng=random.Random(9), **kwargs)
    b = run_with_policy(controller=_controller(), rng=random.Random(9), **kwargs)

    assert a.latencies == pytest.approx(b.latencies)
    assert a.scale_up_events == b.scale_up_events


def test_a_run_with_no_scaling_action_is_flagged_for_discard():
    """A pre-registered discard reason: a run where the policy never acted says
    nothing about the signal."""
    quiet = [0.0, 50.0]
    result = run_with_policy(
        arrivals=quiet,
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(4),
    )

    assert result.scale_up_events == 0
    assert result.discard_reason == "no_scaling_action"


def test_an_unknown_signal_name_is_refused():
    with pytest.raises(KeyError, match="not_a_signal"):
        run_with_policy(
            arrivals=[0.0],
            signal="not_a_signal",
            controller=_controller(),
            lags=INSTANT_LAG,
            curve=SLOW,
            until=1.0,
            evaluate_every=1.0,
            rng=random.Random(1),
        )


# --- Self-review: hand-computed scenarios ------------------------------------

# Capacity 2 per replica, and a replica that gains nothing from batching:
# latency_at(1) = 1.0 s, latency_at(2) = 2.0 s.
TINY = ServiceCurve(points=[(1, 1.0, 1.0, 0.5), (2, 2.0, 1.0, 1.0)], measured=True)
# Two requests per replica at half the latency, so a request finishes strictly
# between two evaluation ticks.
QUICK = ServiceCurve(points=[(1, 0.5, 2.0, 0.5), (2, 1.0, 2.0, 1.0)], measured=True)


def _eager(**kw):
    """A controller that acts at every evaluation: no cooldown to hide behind."""
    defaults = {"scale_up_at": 1.0, "scale_down_at": 0.5, "cooldown": 0.0, "max_replicas": 3}
    return Controller(**{**defaults, **kw})


def test_a_hand_computed_closed_loop_run_agrees_end_to_end():
    """Four simultaneous requests, capacity 2, a 2 s cold start, evaluated every
    second. Worked by hand, event by event:

    t=0   arrivals 1 and 2 dispatch at per-replica load ceil(1/1)=1 and
          ceil(2/1)=2, so they finish at t=1.0 and t=2.0; arrivals 3 and 4
          queue. The t=0 evaluation sees waiting=2 over 1 serving replica,
          queue_depth 2.0 >= 1.0, and launches replica 1 (ready t=2.0).
    t=1   the evaluation is pushed before the completion, so it runs first:
          still waiting=2 over 1 serving, so it launches replica 2 (ready
          t=3.0). Then request 1 completes (latency 1.0) and request 3
          dispatches at load ceil(2/1)=2, finishing at t=3.0.
    t=2   the evaluation sees waiting=1, in_flight=2, serving=2 (replica 1 has
          ripened), queue_depth 0.5 <= 0.5, so it scales DOWN -- and LIFO takes
          replica 2, which is still STARTING and has been billed a full
          replica-second. Request 4 then dispatches at load ceil(3/2)=2,
          finishing at t=4.0. Request 2 completes (latency 2.0).
    t=3   queue_depth 0.0 scales down again, taking replica 1. Request 3
          completes (latency 3.0).
    t=4   request 4 completes (latency 4.0); one replica holds to t=10.

    replica_seconds is the integral of the replica count over [0, 10]:
    2x1 + 3x1 + 2x1 + 1x1 + 1x6 = 14.0.
    """
    result = run_with_policy(
        arrivals=[0.0, 0.0, 0.0, 0.0],
        signal="queue_depth",
        controller=_eager(),
        lags=LagDistribution(samples=[2.0]),
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.latencies == [1.0, 2.0, 3.0, 4.0]
    assert result.completed == 4
    assert result.unfinished == 0
    assert result.scale_up_events == 2
    assert result.scale_down_events == 2
    assert result.peak_replicas == 3
    assert result.peak_serving_replicas == 2
    assert result.replica_seconds == pytest.approx(14.0)
    assert result.extrapolated_samples == 0
    # Replica 2 was launched at t=1, billed, and killed at t=2 while still
    # starting -- it never served. But replica 1 (launched at t=0) DID reach
    # SERVING at t=2 before it was removed at t=3, and the corrected rule
    # (docs/experiment-a2.md, amendment 2026-09-05) only discards a run when
    # NO launched replica ever served. One of two launched replicas serving is
    # enough to keep the run: its cost is billed, not thrown away.
    assert result.discard_reason is None


def test_scale_down_takes_the_newest_replica_even_while_it_is_starting():
    """LIFO deletion, stated as a claim rather than left as a property of
    `list.pop`. The fleet in the hand-computed run above reaches three replicas
    but only ever two serving, because the third was killed mid-start."""
    result = run_with_policy(
        arrivals=[0.0, 0.0, 0.0, 0.0],
        signal="queue_depth",
        controller=_eager(),
        lags=LagDistribution(samples=[2.0]),
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.peak_replicas == 3
    assert result.peak_serving_replicas < result.peak_replicas
    assert result.scale_down_events > 0


def test_a_replica_launched_and_never_ready_is_billed_for_every_second_it_ran():
    """You pay from launch, not from ready. One replica for the whole 20 s
    window plus one launched at t=0 that is still starting when it ends:
    20 + 20 = 40 replica-seconds for 20 seconds of one-replica service."""
    result = run_with_policy(
        arrivals=[0.0, 0.0, 0.0, 0.0],
        signal="queue_depth",
        controller=_eager(cooldown=1000.0),
        lags=LagDistribution(samples=[500.0]),
        curve=TINY,
        until=20.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events == 1
    assert result.peak_replicas == 2
    assert result.peak_serving_replicas == 1
    assert result.replica_seconds == pytest.approx(40.0)
    assert result.discard_reason == "replica_never_served"


def test_replica_seconds_bills_to_the_end_of_the_window_not_the_last_event():
    """The last event here is the evaluation at t=9; the window ends at t=10.
    Billing to the last event would report 9.0 replica-seconds for a fleet that
    existed for 10 -- and the size of that gap is set by `evaluate_every`, a
    swept parameter, so it would bias arms against each other on the cost axis.
    """
    result = run_with_policy(
        arrivals=[0.0],
        signal="queue_depth",
        controller=_eager(),
        lags=INSTANT_LAG,
        curve=TINY,
        until=10.0,
        evaluate_every=3.0,
        rng=random.Random(0),
    )

    assert result.replica_seconds == pytest.approx(10.0)


def test_a_replica_ripening_after_the_last_tick_still_counts_as_serving():
    """Evaluations at t=0, 5, 10 inside a 12 s window. A replica launched at
    t=0 with an 11 s lag is still STARTING at every tick and serving by the
    time the window ends; sampling only at ticks would report it as never
    having served -- and would then discard the run for it. The cooldown holds
    the fleet still so the drained queue cannot scale the replica away again
    before it ripens."""
    result = run_with_policy(
        arrivals=[0.0] * 6,
        signal="queue_depth",
        controller=_eager(cooldown=100.0),
        lags=LagDistribution(samples=[11.0]),
        curve=TINY,
        until=12.0,
        evaluate_every=5.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events == 1
    assert result.scale_down_events == 0
    assert result.peak_serving_replicas == 2
    assert result.discard_reason is None


def test_evaluation_ticks_land_on_multiples_of_the_interval_without_drift():
    """Every evaluation scales up here (a permanently deep queue, a 100 s lag
    so nothing ever ripens, headroom to 20 replicas), so `scale_up_events`
    counts the evaluations exactly.

    `until=1.0, evaluate_every=0.1` must evaluate 11 times, including at t=1.0
    itself -- `range(int(until // evaluate_every) + 1)` yields 10 because the
    float division rounds down. `until=0.7` must evaluate 7 times -- an
    accumulating `tick += 0.1` yields 8, because its eighth tick has drifted
    down to 0.6999999999999999.
    """
    def evaluations(until):
        return run_with_policy(
            arrivals=[0.0] * 20,
            signal="queue_depth",
            controller=_eager(max_replicas=20),
            lags=LagDistribution(samples=[100.0]),
            curve=TINY,
            until=until,
            evaluate_every=0.1,
            rng=random.Random(0),
        ).scale_up_events

    assert evaluations(1.0) == 11
    assert evaluations(0.7) == 7


# --- Self-review: determinism ------------------------------------------------


def test_the_same_seed_reproduces_every_field_of_a_run_that_actually_scales():
    """The plan's determinism test drives `utilization`, which is bounded at
    1.0 and so never crosses a scale_up_at of 2.0 -- it never launches a
    replica, never draws from `rng`, and therefore cannot detect a
    non-deterministic draw order. This one scales."""
    kwargs = {
        "arrivals": [float(i) * 0.2 for i in range(200)],
        "signal": "queue_depth",
        "lags": LagDistribution(samples=[3.0, 17.0, 41.0, 59.0]),
        "curve": SLOW,
        "until": 80.0,
        "evaluate_every": 1.0,
    }
    a = run_with_policy(controller=_controller(), rng=random.Random(11), **kwargs)
    b = run_with_policy(controller=_controller(), rng=random.Random(11), **kwargs)

    assert a.scale_up_events > 0
    assert a.latencies == b.latencies
    assert (a.completed, a.unfinished) == (b.completed, b.unfinished)
    assert (a.scale_up_events, a.scale_down_events) == (b.scale_up_events, b.scale_down_events)
    assert (a.peak_replicas, a.peak_serving_replicas) == (b.peak_replicas, b.peak_serving_replicas)
    assert a.replica_seconds == b.replica_seconds
    assert a.discard_reason == b.discard_reason


def test_a_different_seed_produces_a_different_run():
    """Guards the test above from passing vacuously: if the lag draw did not
    reach the outcome at all, every seed would agree and 'deterministic' would
    mean 'ignores the rng'."""
    kwargs = {
        "arrivals": [float(i) * 0.2 for i in range(200)],
        "signal": "queue_depth",
        "lags": LagDistribution(samples=[1.0, 90.0]),
        "curve": SLOW,
        "until": 80.0,
        "evaluate_every": 1.0,
    }
    runs = [
        run_with_policy(controller=_controller(), rng=random.Random(s), **kwargs)
        for s in range(8)
    ]

    assert len({tuple(r.latencies) for r in runs}) > 1


def test_the_rng_is_drawn_from_exactly_once_per_scale_up_in_launch_order():
    """The draw order must come from the event queue, not from a dict or set
    iteration. Replaying the same number of `choice` calls on a mirror
    generator and finding both in the same state afterwards pins both the
    count and the sequence."""
    samples = [3.0, 17.0, 41.0, 59.0]
    rng = random.Random(23)
    result = run_with_policy(
        arrivals=[float(i) * 0.2 for i in range(200)],
        signal="queue_depth",
        controller=_controller(),
        lags=LagDistribution(samples=samples),
        curve=SLOW,
        until=80.0,
        evaluate_every=1.0,
        rng=rng,
    )

    assert result.scale_up_events > 0
    mirror = random.Random(23)
    for _ in range(result.scale_up_events):
        mirror.choice(samples)
    assert rng.random() == mirror.random()


# --- Self-review: discard rules ----------------------------------------------


def test_a_run_whose_replica_never_serves_is_flagged_for_discard():
    """The corrected exclusion in docs/experiment-a2.md (amendment
    2026-09-05): every replica the policy launches, over the whole 30 s
    window, sits behind a 60 s lag -- none of them ever reaches SERVING, so
    the fleet never effectively grew and the run is discarded. `peak_serving
    == 1` pins that only the initial replica (always serving from t=0) ever
    served."""
    result = run_with_policy(
        arrivals=[float(i) * 0.2 for i in range(150)],
        signal="queue_depth",
        controller=_controller(),
        lags=SLOW_LAG,
        curve=SLOW,
        until=30.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.scale_up_events > 1  # more than one launched replica, ALL failing
    assert result.peak_serving_replicas == 1
    assert result.discard_reason == "replica_never_served"


def test_a_run_where_every_replica_serves_is_not_flagged():
    result = run_with_policy(
        arrivals=[float(i) * 0.2 for i in range(200)],
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.scale_up_events > 0
    assert result.discard_reason is None


def test_a_run_is_kept_when_some_launched_replicas_serve_and_others_do_not():
    """The rule the amendment exists to fix: it must range over ALL replicas
    the policy launches, not ANY of them. Two replicas launch back to back
    with a 5 s lag; the first ripens and serves for a while before the run
    ends, the second is scaled away (LIFO) while still starting and never
    does. Under the old 'any' rule this run was discarded -- exactly the
    defect that zeroed out the whole sweep. Under the corrected 'all' rule it
    is kept, because the fleet DID effectively grow."""
    result = run_with_policy(
        arrivals=[0.0] * 8,
        signal="queue_depth",
        controller=_eager(cooldown=0.0, max_replicas=4),
        lags=LagDistribution(samples=[5.0]),
        curve=TINY,
        until=20.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events >= 2
    assert result.scale_down_events >= 1
    # At least one launched replica reached SERVING and at least one did not,
    # otherwise this test would not distinguish the corrected rule from the
    # old one.
    assert 1 <= result.peak_serving_replicas < result.peak_replicas
    assert result.discard_reason is None


def test_a_run_is_discarded_only_when_every_launched_replica_fails():
    """The mirror of the test above, with the population made explicit: three
    replicas launch, all behind a lag longer than the window, and none of
    them is ever scaled down mid-start (a very long cooldown holds the fleet
    still after the first decision). Every one of the launched replicas fails
    to serve, so -- and only so -- the run is discarded."""
    result = run_with_policy(
        arrivals=[0.0] * 20,
        signal="queue_depth",
        controller=_eager(cooldown=0.0, max_replicas=4),
        lags=LagDistribution(samples=[1000.0]),
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events >= 2
    assert result.scale_down_events == 0
    assert result.peak_serving_replicas == 1  # only the initial replica ever serves
    assert result.discard_reason == "replica_never_served"


def test_no_scaling_action_outranks_the_never_served_reason():
    """A run that never scaled has no launched replica to have failed, so the
    two reasons cannot both be true -- this pins the precedence anyway, since
    `discard_reason` carries only one."""
    result = run_with_policy(
        arrivals=[0.0, 50.0],
        signal="queue_depth",
        controller=_controller(),
        lags=SLOW_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(4),
    )

    assert result.scale_up_events == 0
    assert result.discard_reason == "no_scaling_action"


# --- Self-review: refused inputs ---------------------------------------------


def _ok(**overrides):
    """Valid arguments, so each test below varies exactly one thing."""
    args = {
        "arrivals": [0.0],
        "signal": "queue_depth",
        "controller": _controller(),
        "lags": INSTANT_LAG,
        "curve": SLOW,
        "until": 10.0,
        "evaluate_every": 1.0,
        "rng": random.Random(0),
    }
    args.update(overrides)
    return args


def test_the_valid_baseline_arguments_actually_run():
    """Without this, every refusal test below could pass because the baseline
    is broken rather than because the guard fired."""
    assert run_with_policy(**_ok()).completed == 1


def test_an_empty_arrival_trace_is_refused():
    with pytest.raises(ValueError, match="empty arrival trace"):
        run_with_policy(**_ok(arrivals=[]))


def test_an_exhausted_iterable_is_refused_like_an_empty_list():
    with pytest.raises(ValueError, match="empty arrival trace"):
        run_with_policy(**_ok(arrivals=iter([])))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_window_is_refused(bad):
    with pytest.raises(ValueError, match="until"):
        run_with_policy(**_ok(until=bad))


def test_a_negative_window_is_refused():
    with pytest.raises(ValueError, match="non-negative"):
        run_with_policy(**_ok(until=-1.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_arrival_time_is_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        run_with_policy(**_ok(arrivals=[0.0, bad]))


def test_a_negative_arrival_time_is_refused():
    # Matched on this function's own wording, not just on "negative":
    # `EventQueue.push` also refuses a negative time, with a message that also
    # contains the word, so a looser match would pass with this guard deleted --
    # and would then be reporting the queue's backwards-clock error as if it
    # were the trace check.
    with pytest.raises(ValueError, match="arrived before the run began"):
        run_with_policy(**_ok(arrivals=[-0.5]))


def test_an_arrival_after_the_window_ends_is_refused():
    with pytest.raises(ValueError, match="after the window ends"):
        run_with_policy(**_ok(arrivals=[0.0, 10.5], until=10.0))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_evaluation_interval_is_refused(bad):
    with pytest.raises(ValueError, match="evaluate_every"):
        run_with_policy(**_ok(evaluate_every=bad))


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_non_positive_evaluation_interval_is_refused(bad):
    with pytest.raises(ValueError, match="must be positive"):
        run_with_policy(**_ok(evaluate_every=bad))


def test_a_controller_that_has_already_acted_is_refused():
    """Re-using one does not slightly perturb the cooldown, it freezes the
    policy: the second run's clock starts at 0 while the stamp holds a time
    from the first, so every `now - _last_action_at` is negative, every
    decision is HOLD, and the arm reports an inert signal."""
    used = _controller()
    run_with_policy(**_ok(controller=used, arrivals=[0.0] * 40, curve=TINY))
    assert used._last_action_at is not None

    with pytest.raises(ValueError, match="already acted"):
        run_with_policy(**_ok(controller=used))


def test_an_unknown_signal_is_refused_before_anything_else_is_validated():
    with pytest.raises(KeyError, match="not_a_signal"):
        run_with_policy(**_ok(signal="not_a_signal", arrivals=[]))


# --- Self-review: degenerate fleets ------------------------------------------


def test_a_fleet_scaled_to_zero_queues_its_work_instead_of_dividing_by_zero():
    """With min_replicas=0 the fleet parks at zero, and `queue_depth` reports
    +inf the moment work arrives with nothing to serve it. The controller
    compares that against a threshold and scales back up; nothing multiplies
    the signal by the replica count, so no NaN is produced."""
    result = run_with_policy(
        arrivals=[5.0],
        signal="queue_depth",
        controller=Controller(
            scale_up_at=2.0, scale_down_at=0.5, cooldown=0.0, max_replicas=3, min_replicas=0
        ),
        lags=INSTANT_LAG,
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.scale_down_events > 0
    assert result.scale_up_events > 0
    assert result.completed == 1
    assert result.latencies == [1.0]
    assert result.unfinished == 0


def test_a_negative_min_replicas_is_refused_rather_than_popping_an_empty_fleet():
    """`Controller.__post_init__` only checks max >= min, so min_replicas=-1
    reaches the scale-down branch with an empty fleet, where a bare
    `pop from empty list` would name neither the fleet nor the setting."""
    with pytest.raises(ValueError, match="no replicas left"):
        run_with_policy(
            arrivals=[0.0],
            signal="queue_depth",
            controller=Controller(
                scale_up_at=2.0,
                scale_down_at=0.5,
                cooldown=0.0,
                max_replicas=3,
                min_replicas=-1,
            ),
            lags=INSTANT_LAG,
            curve=QUICK,
            until=5.0,
            evaluate_every=1.0,
            rng=random.Random(0),
        )


def test_every_arrival_is_accounted_for_as_completed_or_unfinished():
    arrivals = [float(i) * 0.2 for i in range(150)]
    result = run_with_policy(
        arrivals=arrivals,
        signal="queue_depth",
        controller=_controller(),
        lags=SLOW_LAG,
        curve=SLOW,
        until=30.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.completed + result.unfinished == len(arrivals)


def test_a_replica_ready_exactly_when_the_window_ends_counts_as_having_served():
    """`Replica.state_at` returns SERVING at exactly `ready_at`, so the
    never-served test must be a strict `>`. At `>=` a replica that became
    available on the final instant of the window would be reported as one that
    never served, and the run discarded for it."""
    result = run_with_policy(
        arrivals=[0.0] * 6,
        signal="queue_depth",
        controller=_eager(cooldown=100.0),
        lags=LagDistribution(samples=[12.0]),
        curve=TINY,
        until=12.0,
        evaluate_every=5.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events == 1
    assert result.scale_down_events == 0
    assert result.peak_serving_replicas == 2
    assert result.discard_reason is None


def test_a_replica_removed_exactly_when_it_became_ready_counts_as_having_served():
    """The same boundary on the other end of a replica's life. Replica 1 is
    launched at t=0 with a 2 s lag, so it is SERVING from t=2.0 -- the t=2
    evaluation counts it, dispatches against it, and only then scales it away.
    It served; a `>=` comparison would say it never did."""
    result = run_with_policy(
        arrivals=[0.0, 0.0, 0.0],
        signal="queue_depth",
        controller=_eager(max_replicas=2),
        lags=LagDistribution(samples=[2.0]),
        curve=TINY,
        until=6.0,
        evaluate_every=2.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events == 1
    assert result.scale_down_events == 1
    assert result.peak_serving_replicas == 2
    assert result.discard_reason is None


def test_an_extrapolated_dispatch_is_counted_in_the_closed_loop_too():
    """A curve whose measured range ends at a fractional concurrency: capacity
    1.5 admits two requests, and the second one's per-replica load of 2 is
    above anything the curve measured. `run_fixed_capacity` counts that; the
    closed loop has to as well, or the sweep would report extrapolation-free
    runs that were not."""
    fractional = ServiceCurve(
        points=[(1, 1.0, 1.0, 0.5), (1.5, 1.5, 1.0, 1.0)], measured=True
    )
    result = run_with_policy(
        arrivals=[0.0, 0.0],
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=fractional,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.completed == 2
    assert result.extrapolated_samples == 1


def test_a_later_arrival_cannot_overtake_an_earlier_one():
    """FIFO, in the closed loop's own copy of the dispatch routine. Three
    requests at t=0 fill the capacity-2 replica and leave one queued; a fourth
    arrives at t=1 just as the first completes. The freed slot must go to the
    request that has been waiting since t=0, not to the one that just arrived.

    FIFO gives latencies [1.0, 2.0, 3.0, 3.0]; serving the newest first gives
    [1.0, 2.0, 2.0, 4.0] -- the same requests, one of them starved.
    """
    result = run_with_policy(
        arrivals=[0.0, 0.0, 0.0, 1.0],
        signal="queue_depth",
        # Thresholds placed out of reach in both directions, so the fleet holds
        # at one replica and the only thing under test is dispatch order.
        controller=Controller(
            scale_up_at=1000.0, scale_down_at=-1.0, cooldown=0.0, max_replicas=4
        ),
        lags=INSTANT_LAG,
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.scale_up_events == 0
    assert result.latencies == [1.0, 2.0, 3.0, 3.0]


def test_max_replicas_caps_the_fleet_not_just_the_serving_replicas():
    """The controller is told the fleet SIZE, not how much of it has ripened.
    Told the serving count instead, `replicas < max_replicas` would stay true
    all the way through a cold start and the policy would launch a replica at
    every evaluation -- eleven here instead of two -- so a slow cold start
    would produce a runaway fleet and bill for it.
    """
    result = run_with_policy(
        arrivals=[0.0] * 20,
        signal="queue_depth",
        controller=_eager(max_replicas=3),
        lags=LagDistribution(samples=[100.0]),
        curve=TINY,
        until=10.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )

    assert result.peak_serving_replicas == 1
    assert result.peak_replicas == 3
    assert result.scale_up_events == 2
