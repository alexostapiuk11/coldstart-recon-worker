import json
import random
import subprocess
import sys
from collections import Counter

import pytest

import autoscale.frontier
import autoscale.sweep
from autoscale import stats
from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.frontier import (
    COMPARED_SIGNALS,
    PolicyPoint,
    gap_at_iso_cost,
    gap_interval,
    h3_verdict,
    iso_cost_budget,
    pareto_frontier,
)
from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.signals import SIGNALS
from autoscale.sim import run_with_policy
from autoscale.sweep import (
    COOLDOWN_SECONDS,
    EVALUATE_EVERY_SECONDS,
    MAX_REPLICAS,
    REPETITIONS,
    THRESHOLDS,
    SweepConfig,
    _derive_seed,
    run_sweep,
)


def _p(cost, p99, signal="queue_depth", up=1.0, down=0.1, n=30):
    """A policy point from repetition samples rather than scalars.

    `n` copies of one value keeps every frontier test asserting exactly what it
    asserted when these were scalars -- the median of n identical values is that
    value -- while clearing the bootstrap's sample floor wherever a test asks
    for an interval.
    """
    return PolicyPoint(
        cost_samples=(float(cost),) * n,
        p99_samples=(float(p99),) * n,
        signal=signal,
        scale_up_at=up,
        scale_down_at=down,
    )


def test_frontier_keeps_only_non_dominated_points():
    points = [_p(10, 5), _p(12, 6), _p(20, 2), _p(15, 3)]

    frontier = pareto_frontier(points)

    assert [(f.cost, f.p99) for f in frontier] == [(10, 5), (15, 3), (20, 2)]


def test_a_point_dominated_on_both_axes_is_dropped():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5), _p(11, 6)])] == [(10, 5)]


def test_ties_on_cost_keep_the_better_p99():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5), _p(10, 3)])] == [(10, 3)]


def test_gap_at_iso_cost_is_the_spread_between_best_and_worst_signal():
    """The H3 metric, in seconds, at equal spend."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 2.0, "queue_depth")],
        "utilization": [_p(10, 9.0, "utilization"), _p(20, 7.0, "utilization")],
        "in_flight_concurrency": [
            _p(10, 3.0, "in_flight_concurrency"),
            _p(20, 1.5, "in_flight_concurrency"),
        ],
    }

    assert gap_at_iso_cost(frontiers, cost=10) == pytest.approx(6.0)
    assert gap_at_iso_cost(frontiers, cost=20) == pytest.approx(5.5)


def test_h3_holds_only_when_the_gap_halves_under_both_shapes():
    """Pre-registered: a halving under one shape only is a partial result, not
    a confirmation. H4 already predicts the ramp's margins shrink, which makes a
    ramp-only halving the easy and less interesting outcome."""
    both = h3_verdict(step_gap_a=10.0, step_gap_c=4.0, ramp_gap_a=8.0, ramp_gap_c=3.0)
    assert both.holds is True

    ramp_only = h3_verdict(step_gap_a=10.0, step_gap_c=9.0, ramp_gap_a=8.0, ramp_gap_c=3.0)
    assert ramp_only.holds is False
    assert ramp_only.partial is True
    assert "ramp" in ramp_only.detail

    neither = h3_verdict(step_gap_a=10.0, step_gap_c=9.5, ramp_gap_a=8.0, ramp_gap_c=7.9)
    assert neither.holds is False
    assert neither.partial is False


def test_exactly_half_counts_as_holding():
    """'at least half' is inclusive; stating it here so the boundary is not
    decided by a floating-point comparison written in a hurry."""
    assert h3_verdict(step_gap_a=10.0, step_gap_c=5.0, ramp_gap_a=8.0, ramp_gap_c=4.0).holds


def test_an_empty_frontier_is_refused():
    with pytest.raises(ValueError, match="empty"):
        pareto_frontier([])


# --- pareto_frontier, hand-computed ------------------------------------------


def test_a_single_point_is_its_own_frontier():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5)])] == [(10, 5)]


def test_ties_on_p99_keep_the_cheaper_point():
    """(20, 5) is dominated by (10, 5): no worse on p99 and strictly cheaper.
    Domination is "at least as good on both axes", so the tie loses."""
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(20, 5), _p(10, 5)])] == [(10, 5)]


def test_identical_points_collapse_to_one():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5), _p(10, 5)])] == [(10, 5)]


def test_all_mutually_non_dominated_points_survive():
    """Hand-computed: each point is cheaper than the next and worse on p99 than
    the next, so none dominates another and the frontier is the whole set."""
    points = [_p(30, 1.0), _p(10, 3.0), _p(20, 2.0)]

    assert [(f.cost, f.p99) for f in pareto_frontier(points)] == [(10, 3.0), (20, 2.0), (30, 1.0)]


def test_the_frontier_is_returned_ascending_by_cost_and_descending_by_p99():
    frontier = pareto_frontier([_p(12, 6), _p(20, 2), _p(10, 5), _p(15, 3), _p(11, 9)])

    costs = [f.cost for f in frontier]
    p99s = [f.p99 for f in frontier]
    assert costs == sorted(costs)
    assert p99s == sorted(p99s, reverse=True)


def test_the_frontier_carries_the_thresholds_not_just_the_axes():
    """A frontier point has to say which policy produced it; the sweep's whole
    output is (signal, thresholds) -> (cost, p99)."""
    point = _p(1.0, 2.0, signal="utilization", up=0.8, down=0.3)

    (survivor,) = pareto_frontier([point])

    assert (survivor.signal, survivor.scale_up_at, survivor.scale_down_at) == (
        "utilization",
        0.8,
        0.3,
    )


def _kwargs(**overrides):
    base = {
        "cost_samples": (1.0, 1.5),
        "p99_samples": (2.0, 2.5),
        "signal": "queue_depth",
        "scale_up_at": 1.0,
        "scale_down_at": 0.1,
    }
    return base | overrides


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["cost_samples", "p99_samples", "scale_up_at", "scale_down_at"])
def test_a_non_finite_policy_point_is_refused(field, bad):
    """A NaN p99 fails `p99 < best_p99`, so the point would silently vanish
    from its own frontier rather than raising.

    The two sample fields are checked per ELEMENT: the bad value goes in beside
    a good one, so this pins that every repetition is validated rather than
    just the first.
    """
    value = (1.0, bad) if field.endswith("_samples") else bad

    with pytest.raises(ValueError, match="not finite"):
        PolicyPoint(**_kwargs(**{field: value}))


@pytest.mark.parametrize("field", ["cost_samples", "p99_samples"])
def test_a_negative_cost_or_p99_is_refused(field):
    """Lower is better on both axes, so a negative value dominates every
    honest point rather than reading as a small one."""
    with pytest.raises(ValueError, match="negative"):
        PolicyPoint(**_kwargs(**{field: (1.0, -1.0)}))


# --- gap_at_iso_cost ----------------------------------------------------------


def test_the_gap_slices_below_the_budget_not_at_it():
    """The budget is a ceiling: the best p99 among policies costing at most
    `cost`, so a slice between two frontier points reads the cheaper one."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 2.0, "queue_depth")],
        "utilization": [_p(10, 9.0, "utilization"), _p(20, 7.0, "utilization")],
    }

    assert gap_at_iso_cost(
        frontiers, cost=19.9, expected=("queue_depth", "utilization")
    ) == pytest.approx(5.0)


def test_a_gap_over_fewer_than_the_compared_signals_is_refused():
    """The defect: a one-signal dict returned 0.0, and `h3_verdict` reads a zero
    arm-C gap as a halving. So an arm that LOST signals -- every run discarded --
    confirmed the artifact's headline out of missing data, while the arm that
    kept all three supplied the numerator. `figures.frontiers` already refuses to
    DRAW a chart missing a signal; the number it is drawn from had no such
    guard."""
    with pytest.raises(ValueError, match="in_flight_concurrency"):
        gap_at_iso_cost({"queue_depth": [_p(10, 4.0)]}, cost=10)


def test_the_incompleteness_refusal_names_every_missing_signal():
    with pytest.raises(ValueError, match="utilization"):
        gap_at_iso_cost(
            {
                "queue_depth": [_p(10, 4.0, "queue_depth")],
                "in_flight_concurrency": [_p(10, 3.0, "in_flight_concurrency")],
            },
            cost=10,
        )


def test_the_compared_signal_set_defaults_to_the_three_the_artifact_compares():
    assert COMPARED_SIGNALS == set(SIGNALS)


def test_a_deliberately_narrower_comparison_has_to_be_asked_for():
    """The guard is a default, not a wall: a caller comparing a stated subset
    says so, and the narrowed set is then what the completeness check enforces --
    so a signal missing from the SUBSET is still refused."""
    two = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "utilization": [_p(10, 9.0, "utilization")],
    }

    assert gap_at_iso_cost(two, cost=10, expected=("queue_depth", "utilization")) == pytest.approx(
        5.0
    )
    with pytest.raises(ValueError, match="utilization"):
        gap_at_iso_cost(
            {"queue_depth": [_p(10, 4.0)]}, cost=10, expected=("queue_depth", "utilization")
        )


def test_an_extra_signal_beyond_the_compared_set_is_not_silently_ignored():
    """Completeness is checked, not equality-with-a-shrug: a fourth frontier
    handed in is still scored, so it cannot be added and then quietly dropped
    from a spread published as a three-signal comparison."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(10, 3.0, "in_flight_concurrency")],
        "utilization": [_p(10, 9.0, "utilization")],
        "future_signal": [_p(10, 20.0, "future_signal")],
    }

    assert gap_at_iso_cost(frontiers, cost=10) == pytest.approx(17.0)


def test_a_signal_that_can_only_operate_above_the_budget_refuses_the_slice():
    """Not a crash to paper over: dropping the unaffordable signal would report
    the spread between the OTHER signals under the same name, and would flatter
    the one that was dropped by never scoring it."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "utilization": [_p(50, 9.0, "utilization")],
    }

    with pytest.raises(ValueError, match="cannot operate"):
        gap_at_iso_cost(frontiers, cost=10, expected=("queue_depth", "utilization"))


def test_the_refusal_names_the_cheapest_policy_that_signal_has():
    """So the finding -- "this signal cannot operate below X" -- is readable
    off the error rather than requiring a re-run to discover."""
    with pytest.raises(ValueError, match="50"):
        gap_at_iso_cost(
            {"utilization": [_p(50, 9.0, "utilization")]},
            cost=10,
            expected=("utilization",),
        )


def test_an_empty_frontier_in_the_comparison_is_refused():
    """Matched on the specific message, not just "empty": without the guard,
    `min(p.cost for p in frontier)` in the unaffordable branch raises "min()
    iterable argument is empty" from the builtin, which would satisfy a looser
    match and let the missing guard pass as if it were present."""
    with pytest.raises(ValueError, match="no p99 to read"):
        gap_at_iso_cost(
            {"queue_depth": [_p(10, 4.0)], "utilization": []},
            cost=10,
            expected=("queue_depth", "utilization"),
        )


def test_a_gap_over_no_frontiers_at_all_is_refused():
    """`max([]) - min([])` would raise a bare "max() arg is an empty sequence"
    from inside the metric; a spread between zero signals is undefined."""
    with pytest.raises(ValueError, match="no frontiers"):
        gap_at_iso_cost({}, cost=10)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_iso_cost_budget_is_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        gap_at_iso_cost({"queue_depth": [_p(10, 4.0)]}, cost=bad, expected=("queue_depth",))


# --- h3_verdict ---------------------------------------------------------------


def test_a_step_only_halving_is_partial_and_names_the_step():
    step_only = h3_verdict(step_gap_a=10.0, step_gap_c=3.0, ramp_gap_a=8.0, ramp_gap_c=7.0)

    assert step_only.holds is False
    assert step_only.partial is True
    assert "step" in step_only.detail


def test_a_gap_that_grew_does_not_hold():
    verdict = h3_verdict(step_gap_a=4.0, step_gap_c=9.0, ramp_gap_a=4.0, ramp_gap_c=9.0)

    assert (verdict.holds, verdict.partial) == (False, False)


def test_a_hair_above_half_does_not_hold_under_that_shape():
    """The inclusive boundary is a boundary, not a tolerance."""
    verdict = h3_verdict(
        step_gap_a=10.0, step_gap_c=5.000001, ramp_gap_a=8.0, ramp_gap_c=4.0
    )

    assert verdict.holds is False
    assert verdict.partial is True
    assert "ramp" in verdict.detail


def test_an_ordinary_verdict_is_evaluable():
    assert h3_verdict(step_gap_a=10.0, step_gap_c=4.0, ramp_gap_a=8.0, ramp_gap_c=3.0).evaluable


@pytest.mark.parametrize(
    ("gaps", "shape"),
    [
        ({"step_gap_a": 0.0, "step_gap_c": 0.0, "ramp_gap_a": 8.0, "ramp_gap_c": 1.0}, "step"),
        ({"step_gap_a": 10.0, "step_gap_c": 1.0, "ramp_gap_a": 0.0, "ramp_gap_c": 0.0}, "ramp"),
    ],
)
def test_a_zero_arm_a_gap_makes_the_verdict_unevaluable(gaps, shape):
    """`gap_c <= gap_a / 2` is satisfied by two zeros, which would confirm the
    artifact's headline out of an absence of any effect to halve. There was no
    inter-signal gap under the SLOW distribution, so "it shrank by half" has no
    truth value -- reported as neither held nor refuted."""
    verdict = h3_verdict(**gaps)

    assert verdict.evaluable is False
    assert (verdict.holds, verdict.partial) == (False, False)
    assert shape in verdict.detail


def test_both_shapes_vacuous_is_reported_for_both():
    verdict = h3_verdict(step_gap_a=0.0, step_gap_c=0.0, ramp_gap_a=0.0, ramp_gap_c=0.0)

    assert verdict.evaluable is False
    assert "step" in verdict.detail
    assert "ramp" in verdict.detail


@pytest.mark.parametrize(
    "name", ["step_gap_a", "step_gap_c", "ramp_gap_a", "ramp_gap_c"]
)
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_gap_is_refused(name, bad):
    """A NaN gap compares False against the halving test, so H3 would be
    reported as refuted on the strength of a number that does not exist."""
    gaps = {"step_gap_a": 10.0, "step_gap_c": 4.0, "ramp_gap_a": 8.0, "ramp_gap_c": 3.0}
    gaps[name] = bad

    with pytest.raises(ValueError, match="not finite"):
        h3_verdict(**gaps)


@pytest.mark.parametrize(
    "name", ["step_gap_a", "step_gap_c", "ramp_gap_a", "ramp_gap_c"]
)
def test_a_negative_gap_is_refused(name):
    """A gap is max - min across signals and cannot be negative. A negative
    arm-C gap would satisfy the halving test automatically; a negative arm-A
    gap would be mistaken for the vacuous-zero case."""
    gaps = {"step_gap_a": 10.0, "step_gap_c": 4.0, "ramp_gap_a": 8.0, "ramp_gap_c": 3.0}
    gaps[name] = -1.0

    with pytest.raises(ValueError, match="negative"):
        h3_verdict(**gaps)


# --- the sweep ----------------------------------------------------------------


def _measured_curve():
    """The placeholder's shape, flagged measured, so a sweep test exercises the
    sweep rather than the unmeasured-curve refusal."""
    return ServiceCurve(points=SERVICE_CURVE_PLACEHOLDER.points, measured=True)


def _config(**overrides):
    kwargs = {
        "shape": SpikeShape(kind="step", baseline_rate=12.0, k=4.0, ramp=0.0, sustain=30.0),
        "lags": LagDistribution(samples=[40.0, 80.0]),
        "curve": _measured_curve(),
        "arm": "A",
        "until": 60.0,
    }
    kwargs.update(overrides)
    return SweepConfig(**kwargs)


def test_the_pre_registered_repetition_count_is_thirty():
    """Fixed by docs/experiment-a2.md before any result was inspected, so the
    count cannot be chosen to make an interval land where it is wanted."""
    assert REPETITIONS == 30


def test_the_threshold_grids_match_the_pre_registration():
    """docs/experiment-a2.md, "Threshold grids, per signal"."""
    assert THRESHOLDS == {
        "queue_depth": ((1.0, 2.0, 4.0, 8.0, 16.0), (0.0, 0.25, 0.5, 1.0)),
        "in_flight_concurrency": ((2.0, 4.0, 8.0, 12.0, 16.0), (0.5, 1.0, 2.0, 4.0)),
        "utilization": ((0.50, 0.65, 0.80, 0.90, 0.95), (0.05, 0.15, 0.30, 0.50)),
    }


def test_every_signal_has_its_own_grid():
    """One grid across all three would put every threshold above utilization's
    maximum of 1.0, so that policy could never fire and H2 would be confirmed
    by a units mismatch instead of by censoring."""
    assert set(THRESHOLDS) == set(SIGNALS)


def test_the_down_below_up_rule_leaves_every_signal_with_combinations():
    """Hand-counted. queue_depth: up=1 admits 3 of its 4 down values, the other
    four ups admit all 4 -> 19. in_flight_concurrency: up=2 admits 2, up=4
    admits 3, the other three admit 4 -> 17. utilization: up=0.50 admits 3, the
    other four admit 4 -> 19. No signal is silently swept out of existence."""
    counts = {
        signal: sum(1 for up in ups for down in downs if down < up)
        for signal, (ups, downs) in THRESHOLDS.items()
    }

    assert counts == {"queue_depth": 19, "in_flight_concurrency": 17, "utilization": 19}


def test_an_unmeasured_service_curve_is_refused():
    """The placeholder's numbers are invented, and frontiers built on them are
    indistinguishable from measured ones in every output format."""
    with pytest.raises(ValueError, match="allow_unmeasured"):
        run_sweep(_config(curve=SERVICE_CURVE_PLACEHOLDER), seed=1)


def test_an_unmeasured_curve_runs_only_on_a_deliberate_opt_in(monkeypatch):
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 1)

    points, _ = run_sweep(
        _config(curve=SERVICE_CURVE_PLACEHOLDER), seed=1, allow_unmeasured=True
    )

    assert isinstance(points, list)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_degenerate_sweep_window_is_refused(bad):
    """`until=0.0` would make every repetition draw an empty trace and be
    discarded, so a sweep that ran nothing would report as one whose every run
    hit a pre-registered exclusion."""
    with pytest.raises(ValueError, match="until"):
        _config(until=bad)


def test_an_unlabelled_arm_is_refused():
    """Arm A vs arm C is the entire H3 comparison."""
    with pytest.raises(ValueError, match="arm"):
        _config(arm="")


def test_discards_are_attributable_to_a_signal(monkeypatch):
    """The pre-registration requires discards counted and reported BY SIGNAL; a
    flat list of bare reasons cannot be split up after the fact."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 2)

    _, discards = run_sweep(_config(), seed=7)

    assert discards
    by_signal = Counter(entry.split(":")[0] for entry in discards)
    assert set(by_signal) <= set(SIGNALS)
    assert all(entry.split(":")[1] in {"empty_trace", "no_scaling_action",
                                       "replica_never_served"} for entry in discards)


def test_an_empty_arrival_trace_is_discarded_under_its_signal(monkeypatch):
    """A window this short draws no arrivals for most repetitions. The
    exclusion is pre-registered, and like the other two it has to be
    attributable to a signal to be reported the way the pre-registration says."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 5)

    _, discards = run_sweep(_config(until=0.05), seed=5)

    assert any(entry.endswith(":empty_trace") for entry in discards)
    assert all(entry.split(":")[0] in SIGNALS for entry in discards)


def test_a_sweep_produces_points_labelled_with_their_policy(monkeypatch):
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 2)

    points, _ = run_sweep(_config(), seed=7)

    assert points
    for point in points:
        assert point.signal in SIGNALS
        ups, downs = THRESHOLDS[point.signal]
        assert point.scale_up_at in ups
        assert point.scale_down_at in downs
        assert point.scale_down_at < point.scale_up_at


def test_the_fixed_control_loop_parameters_are_pinned():
    """Cooldown, evaluation interval, and the replica ceiling are held constant
    across every arm, so they are not swept -- which also means nothing else in
    the suite would notice one of them changing. They set every published cost
    and p99, so a change to any of them has to show up as a failing test rather
    than as a quietly different frontier. Unlike REPETITIONS and the threshold
    grids above, these are not in the pre-registration; this test pins them, it
    does not cite it."""
    assert (COOLDOWN_SECONDS, EVALUATE_EVERY_SECONDS, MAX_REPLICAS) == (30.0, 5.0, 12)


def _spread(values) -> float:
    """Range of a sample. Used to decide whether a set of repetitions varies
    enough to distinguish one aggregator from another -- see the comment at its
    call site for why exact float distinctness is not that test."""
    return max(values) - min(values)


def _recompute_repetitions(config, seed, signal, up, down, repetitions):
    """One configuration's repetitions, replayed independently of run_sweep."""
    costs, p99s = [], []
    for rep in range(repetitions):
        rng = random.Random(_derive_seed(seed, up, down, rep))
        arrivals = arrival_times(config.shape, until=config.until, rng=rng)
        if not arrivals:
            continue
        result = run_with_policy(
            arrivals=arrivals,
            signal=signal,
            controller=Controller(
                scale_up_at=up,
                scale_down_at=down,
                cooldown=COOLDOWN_SECONDS,
                max_replicas=MAX_REPLICAS,
            ),
            lags=config.lags,
            curve=config.curve,
            until=config.until,
            evaluate_every=EVALUATE_EVERY_SECONDS,
            rng=rng,
        )
        if result.discard_reason:
            continue
        costs.append(result.replica_seconds)
        p99s.append(result.percentiles()["p99"])
    return costs, p99s


def test_a_policy_point_is_the_median_across_repetitions(monkeypatch):
    """Recomputed independently from the same derived seeds. Pins the
    aggregator, which the pre-registration fixes the repetition count for but
    not the summary: the MEDIAN of per-run p99s (the p99 a typical run of this
    policy delivers, repetitions weighted equally) rather than the p99 of the
    pooled latencies (the tail of the mixture over runs, dominated by the worst
    few and weighting each run by how many requests it happened to complete).

    It was the mean until 2026-09-17. Artifact 1's standing rule is that a mean
    is never published for right-skewed data, and per-run p99s of a
    heavy-tailed workload are right-skewed. Either is defensible; which one was
    used must not be silently swappable, which is what this test enforces."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 4)
    config = _config(until=150.0)

    points, _ = run_sweep(config, seed=4)

    checked = 0
    for point in points:
        costs, p99s = _recompute_repetitions(
            config, 4, point.signal, point.scale_up_at, point.scale_down_at, 4
        )
        # A configuration whose repetitions all landed on the same number
        # cannot tell a mean from a max, so it proves nothing either way.
        #
        # `len(set(...)) < 2` is NOT the right test for that: replica-seconds is
        # a sum of floats, so four repetitions identical in every way a reader
        # cares about still come back as four DISTINCT floats
        # (269.9999999999996 through 270.00000000000034 on this config). They
        # pass a distinctness check and then fail the "not a max" assertion
        # below, because at that spread the mean and the max are the same number
        # to any tolerance. Require real spread instead.
        if _spread(costs) < 1e-6 or _spread(p99s) < 1e-6:
            continue
        checked += 1
        assert point.cost == pytest.approx(stats.median(costs))
        assert point.p99 == pytest.approx(stats.median(p99s))
        assert point.cost != pytest.approx(max(costs))
        assert point.p99 != pytest.approx(max(p99s))
    assert checked, "no configuration had repetitions that varied; the aggregator is untested"


def test_the_same_seed_gives_the_same_sweep(monkeypatch):
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 2)

    first, _ = run_sweep(_config(), seed=11)
    second, _ = run_sweep(_config(), seed=11)

    assert first == second


def test_a_different_seed_gives_a_different_sweep(monkeypatch):
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 2)

    first, _ = run_sweep(_config(), seed=11)
    second, _ = run_sweep(_config(), seed=12)

    assert first != second


_CROSS_PROCESS_SCRIPT = """
import json, sys
import autoscale.sweep as sweep
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve

sweep.REPETITIONS = 2
config = sweep.SweepConfig(
    shape=SpikeShape(kind="step", baseline_rate=12.0, k=4.0, ramp=0.0, sustain=30.0),
    lags=LagDistribution(samples=[40.0, 80.0]),
    curve=ServiceCurve(points=SERVICE_CURVE_PLACEHOLDER.points, measured=True),
    arm="A",
    until=60.0,
)
points, discards = sweep.run_sweep(config, seed=11)
json.dump(
    {
        "points": [
            [p.cost, p.p99, p.signal, p.scale_up_at, p.scale_down_at] for p in points
        ],
        "discards": discards,
        "seeds": [
            sweep._derive_seed(11, 2.0, 0.5, rep) for rep in range(3)
        ],
    },
    sys.stdout,
)
"""


def _sweep_in_a_fresh_interpreter(hash_seed):
    completed = subprocess.run(
        [sys.executable, "-c", _CROSS_PROCESS_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ".", "PYTHONHASHSEED": hash_seed},
    )
    return json.loads(completed.stdout)


def test_the_sweep_is_reproducible_across_processes():
    """The defect sha256 seeding exists to prevent. `hash()` on a str is salted
    per process, so a hash-derived seed gives a different sweep on every
    invocation while passing any in-process reproducibility test -- and the
    artifact's published claim is that a reader re-running this gets these
    numbers. Two interpreters, two different hash salts, identical output."""
    first = _sweep_in_a_fresh_interpreter("0")
    second = _sweep_in_a_fresh_interpreter("12345")

    assert first["seeds"] == second["seeds"]
    assert first["points"] == second["points"]
    assert first["discards"] == second["discards"]
    assert first["points"], "a sweep that produced no points would compare equal trivially"


def test_derived_seeds_differ_across_threshold_pairs_and_repetitions():
    """Every repetition of every threshold pair draws its own arrival trace; a
    collision would silently make two THRESHOLD PAIRS share a trace.

    The signal is deliberately not part of this: sharing a trace ACROSS SIGNALS
    at one threshold pair is the common-random-number coupling H3's gap is read
    from, not a collision. See
    `test_the_three_signals_are_scored_on_one_shared_arrival_trace`.
    """
    seeds = [
        _derive_seed(1, up, down, rep)
        for up in (1.0, 2.0)
        for down in (0.0, 0.5)
        for rep in range(5)
    ]

    assert len(set(seeds)) == len(seeds)


def test_the_derived_seed_is_a_fixed_value():
    """Pinned so a change to the derivation shows up as a failing test rather
    than as a quietly different published sweep."""
    assert _derive_seed(11, 2.0, 0.5, 0) == 15743821937205418989


def test_the_three_signals_are_scored_on_one_shared_arrival_trace(monkeypatch):
    """The defect: `signal` was part of the seed key, so at the same
    (seed, up, down, rep) the three signals were replayed against three
    COMPLETELY DIFFERENT random spikes -- measured over 30 repetitions of the
    published shape, queue_depth and in_flight_concurrency shared 0 of ~24,600
    arrival timestamps per repetition. The H3 headline is the p99 spread BETWEEN
    signals, so every bit of traffic-to-traffic variance landed directly on the
    published number: per-signal sems of 0.33-0.53 s, and max-minus-min is
    biased upward by noise, so a non-zero gap was reported no matter what.
    Sharing the trace makes the gap a paired within-trace difference and cancels
    the traffic variance -- at one threshold pair (4.0, 0.5) the same two
    signals' p99 then agree to the last digit in all 30 repetitions, where
    unpaired they differed by ~1 s of pure noise.

    `arrivals.arrival_times` already documents this coupling as deliberate
    variance reduction, and the seed key already preserved it for arm A vs arm C
    (no `arm` in the key) and for step vs ramp (no `kind`) -- it destroyed it for
    the one axis the headline measures.
    """
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 3)
    # One threshold pair, shared by all three signals, so the comparison this
    # test makes is possible at all: the published grids are in three different
    # units and `utilization` overlaps neither of the other two.
    monkeypatch.setattr("autoscale.sweep.THRESHOLDS", {s: ((4.0,), (0.5,)) for s in SIGNALS})
    replayed: dict[str, list[tuple[float, ...]]] = {}
    real = autoscale.sweep.run_with_policy

    def spy(**kwargs):
        replayed.setdefault(kwargs["signal"], []).append(tuple(kwargs["arrivals"]))
        return real(**kwargs)

    monkeypatch.setattr("autoscale.sweep.run_with_policy", spy)

    run_sweep(_config(until=120.0), seed=13)

    assert set(replayed) == set(SIGNALS), "every signal must have been run"
    traces = list(replayed.values())
    assert traces[0] == traces[1] == traces[2]
    assert len(set(traces[0])) == 3, (
        "the three repetitions collapsed onto one trace; the signals would be "
        "paired but the sweep would be replaying a single spike 30 times"
    )


def test_the_sweep_feeds_the_frontier(monkeypatch):
    """End to end: sweep -> frontier -> iso-cost gap, on the placeholder curve
    with the opt-in, which is the only thing available before hardware."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 2)
    points, _ = run_sweep(_config(until=120.0), seed=3)

    by_signal: dict[str, list[PolicyPoint]] = {}
    for point in points:
        by_signal.setdefault(point.signal, []).append(point)
    frontiers = {signal: pareto_frontier(pts) for signal, pts in by_signal.items()}

    budget = max(f[0].cost for f in frontiers.values())
    # `expected` is the set this reduced sweep actually produced, stated rather
    # than defaulted: at 2 repetitions over a 120 s window a signal can be swept
    # out entirely by the pre-registered exclusions, and this test is about the
    # sweep -> frontier -> gap PLUMBING, not about coverage. Coverage of all
    # three is asserted on the real path in tests/test_a2_end_to_end.py, and the
    # default set is what guards the published number.
    assert gap_at_iso_cost(frontiers, cost=budget, expected=tuple(frontiers)) >= 0.0



# --- PolicyPoint carries its repetitions -------------------------------------


def test_a_policy_point_carries_its_repetitions():
    p = PolicyPoint(
        cost_samples=(10.0, 12.0, 14.0),
        p99_samples=(1.0, 2.0, 3.0),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    assert p.n == 3
    assert p.cost == pytest.approx(12.0)  # median, not mean
    assert p.p99 == pytest.approx(2.0)


def test_the_point_estimate_is_a_median_not_a_mean():
    """Artifact 1's rule -- never a mean for right-skewed data -- applies to the
    per-run p99s too. One catastrophic repetition should not move a policy's
    published p99 by a thirtieth of its own excess."""
    p = PolicyPoint(
        cost_samples=(10.0,) * 30,
        p99_samples=(1.0,) * 29 + (100.0,),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    assert p.p99 == pytest.approx(1.0)
    assert sum(p.p99_samples) / len(p.p99_samples) > 4.0  # the mean it is not


def test_a_policy_point_with_no_repetitions_is_refused():
    with pytest.raises(ValueError, match="no repetitions"):
        PolicyPoint(
            cost_samples=(),
            p99_samples=(),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_mismatched_sample_counts_are_refused():
    """cost and p99 come from the same runs, so unequal lengths mean the two
    axes of one point were computed over different repetition sets -- and
    `gap_interval` resamples ONE index list for both."""
    with pytest.raises(ValueError, match="SAME runs"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0,),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_sample_is_still_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        PolicyPoint(
            cost_samples=(1.0, bad),
            p99_samples=(1.0, 2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_a_negative_sample_is_still_refused():
    with pytest.raises(ValueError, match="negative"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0, -2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_a_policy_points_interval_brackets_its_point_estimate():
    p = PolicyPoint(
        cost_samples=tuple(float(i) for i in range(30)),
        p99_samples=tuple(float(i) for i in range(30)),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    lo, hi = p.p99_interval(iterations=500, seed=0)
    assert lo <= p.p99 <= hi
    lo_c, hi_c = p.cost_interval(iterations=500, seed=0)
    assert lo_c <= p.cost <= hi_c


# --- iso_cost_budget ---------------------------------------------------------


def test_the_budget_is_the_cheapest_at_which_every_signal_can_operate():
    """The rule: max over signals of that signal's cheapest frontier point. Any
    lower and some signal has nothing affordable, so the gap is undefined
    rather than smaller."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization"), _p(40, 7.0, "utilization")],
    }
    assert iso_cost_budget(frontiers) == pytest.approx(25.0)


def test_the_budget_binds_on_at_least_one_signal():
    """The defect this rule replaces: at `min(cost) * 2` every frontier was
    fully affordable, so the slice constrained nothing and the "iso-cost gap"
    was the spread between each signal's unconstrained best. At this rule the
    most expensive-floor signal has exactly one affordable policy, by
    construction."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "utilization": [_p(25, 9.0, "utilization"), _p(40, 7.0, "utilization")],
    }
    budget = iso_cost_budget(frontiers)
    affordable = {s: [p for p in f if p.cost <= budget] for s, f in frontiers.items()}
    assert min(len(v) for v in affordable.values()) == 1
    assert all(v for v in affordable.values())


def test_the_budget_of_an_empty_frontier_set_is_refused():
    with pytest.raises(ValueError, match="no frontiers"):
        iso_cost_budget({})


def test_the_budget_of_a_frontier_with_no_points_is_refused():
    with pytest.raises(ValueError, match="utilization"):
        iso_cost_budget({"queue_depth": [_p(10, 4.0)], "utilization": []})


def test_the_budget_is_always_sliceable_by_gap_at_iso_cost():
    """The two functions are a pair: a budget this returns must never make
    `gap_at_iso_cost` raise `no point costs X or less`."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization")],
    }
    assert gap_at_iso_cost(frontiers, cost=iso_cost_budget(frontiers)) == pytest.approx(5.5)


# --- gap_interval ------------------------------------------------------------


def test_the_gap_interval_brackets_the_point_gap():
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization")],
    }
    got = gap_interval(frontiers, iterations=400, seed=0)
    assert got["lo"] <= got["point"] <= got["hi"]
    assert got["point"] == pytest.approx(gap_at_iso_cost(frontiers, iso_cost_budget(frontiers)))
    assert got["budget"] == pytest.approx(iso_cost_budget(frontiers))


def test_identical_repetitions_give_a_zero_width_gap_interval():
    """Not a corner case -- it is what a degenerate operating regime produces,
    and a reader must be able to tell "the gap is 0.5 s and certain" from "the
    gap is 0.5 s and we have no idea"."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(10, 4.0, "in_flight_concurrency")],
        "utilization": [_p(10, 4.5, "utilization")],
    }
    got = gap_interval(frontiers, iterations=400, seed=0)
    assert got["lo"] == got["hi"] == pytest.approx(0.5)


def test_the_gap_interval_widens_with_noisier_repetitions():
    """The property that makes the interval worth publishing."""

    def noisy(spread, signal):
        return PolicyPoint(
            cost_samples=(10.0,) * 30,
            p99_samples=tuple(4.0 + spread * (i % 5) for i in range(30)),
            signal=signal,
            scale_up_at=2.0,
            scale_down_at=0.5,
        )

    def width(spread):
        f = {
            "queue_depth": [noisy(spread, "queue_depth")],
            "in_flight_concurrency": [noisy(spread * 2, "in_flight_concurrency")],
            "utilization": [noisy(spread * 3, "utilization")],
        }
        got = gap_interval(f, iterations=800, seed=3)
        return got["hi"] - got["lo"]

    assert width(1.0) > width(0.1)


def test_the_gap_interval_resamples_one_index_list_for_every_policy(monkeypatch):
    """The pairing the seed fix bought is destroyed by resampling each policy's
    repetitions independently: repetition r of queue_depth and repetition r of
    in_flight_concurrency are the SAME arrival trace, and a bootstrap that
    breaks that correspondence re-introduces exactly the traffic variance
    `_derive_seed` was changed to cancel."""
    seen = []
    real = autoscale.frontier._take

    def spy(point, field, reps):
        seen.append(tuple(reps))
        return real(point, field, reps)

    monkeypatch.setattr("autoscale.frontier._take", spy)
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
    }
    gap_interval(
        frontiers, iterations=3, seed=0, expected=("queue_depth", "in_flight_concurrency")
    )
    # Three policies x two sample fields x three draws, but only three DISTINCT
    # repetition lists -- one per draw, shared by every policy in it.
    assert len(seen) == 18
    assert len(set(seen)) <= 3


def test_a_points_samples_are_read_by_repetition_id_not_by_position():
    """The exclusion rules discard different runs for different policies, so
    position 3 is repetition 3 for one policy and repetition 4 for another that
    lost an earlier run. Pairing on position would compare two different arrival
    traces -- the exact thing the shared seed exists to prevent."""
    point = PolicyPoint(
        cost_samples=(1.0, 2.0, 3.0),
        p99_samples=(10.0, 20.0, 30.0),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
        rep_indices=(5, 7, 9),
    )

    # By id: repetition 9 is 30.0, not "position 9" (which does not exist).
    assert autoscale.frontier._take(point, "p99_samples", (9, 5)) == [30.0, 10.0]
    # Repeats are kept -- the draw is with replacement.
    assert autoscale.frontier._take(point, "p99_samples", (7, 7)) == [20.0, 20.0]


def test_a_repetition_this_point_lost_is_omitted_rather_than_mispaired():
    """A policy that lost repetition r contributes the drawn ones it has. The
    alternative -- requiring every policy to hold every drawn repetition -- is
    an intersection, and on real sweeps it is ruinous."""
    point = PolicyPoint(
        cost_samples=(1.0, 2.0),
        p99_samples=(10.0, 20.0),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
        rep_indices=(5, 7),
    )

    assert autoscale.frontier._take(point, "p99_samples", (5, 6, 7)) == [10.0, 20.0]


def test_signals_sharing_a_repetition_are_scored_on_it_together():
    """The property the pairing buys, end to end: two policies whose values
    agree repetition-by-repetition produce a gap of exactly zero in every draw,
    however their repetitions are labelled."""
    reps = tuple(range(30))
    same = {
        s: [
            PolicyPoint(
                cost_samples=(10.0,) * 30,
                p99_samples=tuple(float(r) for r in reps),
                signal=s,
                scale_up_at=2.0,
                scale_down_at=0.5,
                rep_indices=reps,
            )
        ]
        for s in SIGNALS
    }

    got = gap_interval(same, iterations=200, seed=0)
    assert got["point"] == got["lo"] == got["hi"] == pytest.approx(0.0)


def test_ragged_repetition_counts_are_normal_and_not_refused():
    """An earlier version demanded equal counts and refused to run on any real
    sweep: a real arm comes back with 26, 29 and 30 survivors across policies.
    Ragged discards are the normal case here, and the pre-registration already
    requires them to be counted and reported rather than treated as an error."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth", n=26)],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency", n=29)],
        "utilization": [_p(25, 9.0, "utilization", n=30)],
    }
    got = gap_interval(frontiers, iterations=200, seed=0)
    # 30, not 26: the population is every repetition any policy kept, and each
    # policy contributes the drawn ones it has. The intersection (26) is what
    # an earlier version drew from, and on a real sweep it collapsed to 19.
    assert got["paired_repetitions"] == 30
    assert got["point"] == pytest.approx(5.5)


def test_the_gap_interval_refuses_an_incomplete_signal_set():
    """Same reason `gap_at_iso_cost` does, and it matters more here: an interval
    on a spread between the wrong set of signals reads as an interval on the
    headline."""
    with pytest.raises(ValueError, match="in_flight_concurrency"):
        gap_interval({"queue_depth": [_p(10, 4.0)]}, iterations=100, seed=0)


def test_a_policy_below_the_bootstrap_floor_is_refused():
    """Ragged counts are fine; a POLICY with fewer repetitions than the
    bootstrap floor is not. Below it that policy's resampled median is a
    handful of repeated values, and the gap's interval inherits it."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth", n=30)],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency", n=12)],
        "utilization": [_p(25, 9.0, "utilization", n=30)],
    }
    with pytest.raises(ValueError, match="surviving repetitions"):
        gap_interval(frontiers, iterations=100, seed=0)


def test_one_policys_lost_run_does_not_remove_it_from_the_others():
    """The defect that forced this design. An intersection over frontier points
    drops repetition r from EVERY policy as soon as ONE lost it, so ten points
    each missing a few different runs collapse 30 repetitions to 19 and the
    bootstrap refuses -- on a sweep where every signal had points with all 30."""
    everything = tuple(range(30))
    missing_one = {
        s: [
            PolicyPoint(
                cost_samples=(10.0,) * 29,
                p99_samples=(4.0,) * 29,
                signal=s,
                scale_up_at=2.0,
                scale_down_at=0.5,
                # Each signal lost a DIFFERENT run, so the intersection is 27
                # while the population is still 30.
                rep_indices=tuple(r for r in everything if r != i),
            )
        ]
        for i, s in enumerate(SIGNALS)
    }
    got = gap_interval(missing_one, iterations=100, seed=0)
    assert got["paired_repetitions"] == 30


def test_rep_indices_must_match_the_sample_count():
    with pytest.raises(ValueError, match="rep_indices has"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0, 2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
            rep_indices=(0,),
        )


def test_duplicate_rep_indices_are_refused():
    """Two samples cannot both be repetition r, and a duplicate would let one
    run be drawn twice per resample while another is never drawn at all."""
    with pytest.raises(ValueError, match="duplicates"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0, 2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
            rep_indices=(3, 3),
        )


def test_the_gap_interval_is_reproducible_from_its_seed():
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization")],
    }
    assert gap_interval(frontiers, iterations=200, seed=5) == gap_interval(
        frontiers, iterations=200, seed=5
    )


# --- h3_verdict's unevaluable guard ------------------------------------------


def test_a_gap_whose_interval_covers_zero_is_unevaluable():
    """The defect: `evaluable=False` fired only on an EXACT zero arm-A gap, and
    a gap measured around a true zero is never exactly zero. Under artifact 2's
    original traffic model the true gap was zero and the measurement came out
    at 0.314 -- the guard passed it through and reported an ordinary verdict on
    a quantity that had none."""
    verdict = h3_verdict(
        step_gap_a=0.314,
        step_gap_c=0.120,
        ramp_gap_a=0.290,
        ramp_gap_c=0.110,
        step_gap_a_interval=(0.0, 0.86),
        ramp_gap_a_interval=(0.0, 0.79),
    )
    assert not verdict.evaluable
    assert not verdict.holds
    assert "indistinguishable from zero" in verdict.detail


def test_a_gap_whose_interval_excludes_zero_is_evaluated_normally():
    verdict = h3_verdict(
        step_gap_a=3.0681,
        step_gap_c=2.6094,
        ramp_gap_a=3.0,
        ramp_gap_c=2.5,
        step_gap_a_interval=(2.94, 3.20),
        ramp_gap_a_interval=(2.87, 3.13),
    )
    assert verdict.evaluable
    assert not verdict.holds  # 2.6094 > 3.0681 / 2
    assert not verdict.partial


def test_the_intervals_are_optional_and_an_exact_zero_is_still_unevaluable():
    """Callers without intervals keep the old behaviour, so this is an added
    guard rather than a replaced one."""
    verdict = h3_verdict(0.0, 0.0, 1.0, 0.4)
    assert not verdict.evaluable
    assert "exactly zero" in verdict.detail


def test_an_interval_that_only_touches_zero_is_still_unevaluable():
    """`lo == 0.0` exactly. A lower bound sitting ON zero does not exclude it,
    and the bootstrap produces exactly this when the sample is degenerate."""
    verdict = h3_verdict(
        1.0, 0.4, 1.0, 0.4, step_gap_a_interval=(0.0, 2.0), ramp_gap_a_interval=(0.5, 2.0)
    )
    assert not verdict.evaluable
    assert "step" in verdict.detail


def test_costs_differing_only_by_floating_point_dust_are_one_operating_point():
    """`replica_seconds` is an integral accumulated by float addition, so two
    policies that cost the SAME 670 replica-seconds physically come back as
    669.9999999999985 and 670.000000000001. Sorting on that dust turned 19
    queue_depth policies into a three-point "Pareto frontier" whose staircase
    was ordered by the 13th significant digit -- measured on the real arm-A
    sweep, build/a2-figures-final/sweep-cache.json.

    Two consequences, one cosmetic and one not. The figure drew that signal as
    a vertical smear with no interval band, on the very series carrying the
    artifact's headline finding. And `gap_at_iso_cost` reads
    `min(p99 for affordable)`, so a budget landing BETWEEN two dust values
    would silently change the published gap. It does not today -- the budget
    sits well above the tied cluster -- which is exactly why this needs a test
    rather than a reader noticing later.
    """
    dust = [
        _p(669.9999999999985, 6.24, "queue_depth", up=16.0, down=0.0),
        _p(670.0, 6.02, "queue_depth", up=1.0, down=0.0),
        _p(670.000000000001, 5.88, "queue_depth", up=4.0, down=1.0),
    ]

    front = pareto_frontier(dust)

    assert len(front) == 1, (
        f"kept {len(front)} points at one physical cost; costs "
        f"{[p.cost for p in front]} differ by ~1e-12, which is float noise in "
        "an accumulated integral, not a cost/latency tradeoff"
    )
    assert front[0].p99 == pytest.approx(5.88), "the survivor must be the best of the tied set"


def test_a_real_cost_difference_is_still_a_frontier_step():
    """The tolerance must not swallow differences that are physically real. One
    replica-second apart on a ~670 s integral is 1.5e-3 relative -- six orders
    of magnitude above the dust above."""
    front = pareto_frontier(
        [_p(670.0, 6.0, "queue_depth"), _p(671.0, 5.0, "queue_depth")]
    )
    assert len(front) == 2
