import json
import random
import subprocess
import sys
from collections import Counter

import pytest

import autoscale.sweep
from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.frontier import (
    COMPARED_SIGNALS,
    PolicyPoint,
    gap_at_iso_cost,
    h3_verdict,
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


def _p(cost, p99, signal="queue_depth"):
    return PolicyPoint(cost=cost, p99=p99, signal=signal, scale_up_at=1.0, scale_down_at=0.1)


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
    point = PolicyPoint(cost=1.0, p99=2.0, signal="utilization", scale_up_at=0.8, scale_down_at=0.3)

    (survivor,) = pareto_frontier([point])

    assert (survivor.signal, survivor.scale_up_at, survivor.scale_down_at) == (
        "utilization",
        0.8,
        0.3,
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["cost", "p99", "scale_up_at", "scale_down_at"])
def test_a_non_finite_policy_point_is_refused(field, bad):
    """A NaN p99 fails `p99 < best_p99`, so the point would silently vanish
    from its own frontier rather than raising."""
    kwargs = {"cost": 1.0, "p99": 2.0, "signal": "queue_depth", "scale_up_at": 1.0,
              "scale_down_at": 0.1}
    kwargs[field] = bad

    with pytest.raises(ValueError, match="not finite"):
        PolicyPoint(**kwargs)


@pytest.mark.parametrize("field", ["cost", "p99"])
def test_a_negative_cost_or_p99_is_refused(field):
    """Lower is better on both axes, so a negative value dominates every
    honest point rather than reading as a small one."""
    kwargs = {"cost": 1.0, "p99": 2.0, "signal": "queue_depth", "scale_up_at": 1.0,
              "scale_down_at": 0.1}
    kwargs[field] = -1.0

    with pytest.raises(ValueError, match="negative"):
        PolicyPoint(**kwargs)


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
        "shape": SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=30.0),
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


def test_a_policy_point_is_the_mean_across_repetitions(monkeypatch):
    """Recomputed independently from the same derived seeds. Pins the
    aggregator, which the pre-registration fixes the repetition count for but
    not the summary: a mean of per-run p99s (the p99 a typical run of this
    policy delivers, 30 runs weighted equally) rather than the p99 of the
    pooled latencies (the tail of the mixture over runs, dominated by the worst
    few and weighting each run by how many requests it happened to complete).
    Either is defensible; which one was used must not be silently swappable."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 4)
    config = _config(until=150.0)

    points, _ = run_sweep(config, seed=4)

    checked = 0
    for point in points:
        costs, p99s = _recompute_repetitions(
            config, 4, point.signal, point.scale_up_at, point.scale_down_at, 4
        )
        if len(set(costs)) < 2 or len(set(p99s)) < 2:
            # A configuration whose repetitions all landed on the same number
            # cannot tell a mean from a max, so it proves nothing either way.
            continue
        checked += 1
        assert point.cost == pytest.approx(sum(costs) / len(costs))
        assert point.p99 == pytest.approx(sum(p99s) / len(p99s))
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
    shape=SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=30.0),
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

