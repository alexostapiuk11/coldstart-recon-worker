"""H1, H2 and H4 on frontiers, as defined in the publication plan's Task 0."""

import pytest

from autoscale.frontier import PolicyPoint, gap_at_iso_cost, iso_cost_budget, pareto_frontier
from autoscale.hypotheses import h1_holds_on, h2_worst_on, h4_holds_on, ranking, reached_p99


def _pp(signal, cost, p99, up=1.0):
    return PolicyPoint(
        cost_samples=(cost,) * 3,
        p99_samples=(p99,) * 3,
        signal=signal,
        scale_up_at=up,
        scale_down_at=0.0,
        rep_indices=(0, 1, 2),
    )


def _fr(points):
    by = {}
    for p in points:
        by.setdefault(p.signal, []).append(p)
    return {s: pareto_frontier(v) for s, v in by.items()}


def test_reached_p99_is_the_gaps_own_slice():
    fr = _fr(
        [
            _pp("queue_depth", 10, 5.0),
            _pp("in_flight_concurrency", 20, 3.0),
            _pp("utilization", 30, 4.0),
        ]
    )
    budget = iso_cost_budget(fr)
    r = reached_p99(fr, budget)
    assert max(r.values()) - min(r.values()) == gap_at_iso_cost(fr, cost=budget)


def test_reached_p99_refuses_a_signal_that_cannot_reach_the_budget():
    fr = _fr(
        [
            _pp("queue_depth", 10, 5.0),
            _pp("in_flight_concurrency", 20, 3.0),
            _pp("utilization", 30, 4.0),
        ]
    )
    with pytest.raises(ValueError, match="cannot operate at this iso-cost budget"):
        reached_p99(fr, 15.0)


def test_h1_needs_every_other_frontier_point_dominated():
    dominant = _fr(
        [
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("queue_depth", 12, 3.0),
            _pp("utilization", 30, 2.0),
        ]
    )
    assert h1_holds_on(dominant) is True
    cheaper_queue = _fr(
        [
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("queue_depth", 5, 3.0),
            _pp("utilization", 30, 2.0),
        ]
    )
    assert h1_holds_on(cheaper_queue) is False


def test_h1_a_point_tied_on_both_axes_is_not_dominated():
    tied = _fr(
        [
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("queue_depth", 10, 2.0),
            _pp("utilization", 30, 3.0),
        ]
    )
    assert h1_holds_on(tied) is False


def test_h1_one_inflight_point_need_not_dominate_all_others():
    # Each other point is dominated by a DIFFERENT in-flight frontier point.
    fr = _fr(
        [
            _pp("in_flight_concurrency", 5, 8.0),
            _pp("in_flight_concurrency", 20, 2.0),
            _pp("queue_depth", 6, 9.0),
            _pp("queue_depth", 25, 3.0),
            _pp("utilization", 30, 4.0),
        ]
    )
    assert h1_holds_on(fr) is True


def test_h2_is_utilisation_strictly_worst_at_the_budget():
    fr = _fr(
        [
            _pp("queue_depth", 10, 3.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 4.0),
        ]
    )
    assert h2_worst_on(fr) is True
    fr = _fr(
        [
            _pp("queue_depth", 10, 5.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 4.0),
        ]
    )
    assert h2_worst_on(fr) is False


def test_h2_a_lead_within_one_millisecond_is_a_tie_not_worst():
    fr = _fr(
        [
            _pp("queue_depth", 10, 3.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0005),
        ]
    )
    assert h2_worst_on(fr) is False


def test_ranking_groups_ties_within_one_millisecond():
    fr = _fr(
        [
            _pp("queue_depth", 10, 3.0005),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0),
        ]
    )
    assert ranking(fr) == [["in_flight_concurrency"], ["queue_depth", "utilization"]]


def test_h4_needs_the_same_ranking_and_a_smaller_ramp_gap():
    step = _fr(
        [
            _pp("queue_depth", 10, 5.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0),
        ]
    )
    ramp_same = _fr(
        [
            _pp("queue_depth", 10, 4.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0),
        ]
    )
    assert h4_holds_on(step, ramp_same) is True
    ramp_wider = _fr(
        [
            _pp("queue_depth", 10, 9.0),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0),
        ]
    )
    assert h4_holds_on(step, ramp_wider) is False
    ramp_reordered = _fr(
        [
            _pp("queue_depth", 10, 2.5),
            _pp("in_flight_concurrency", 10, 2.0),
            _pp("utilization", 10, 3.0),
        ]
    )
    assert h4_holds_on(step, ramp_reordered) is False


def test_a_sensitivity_signal_in_the_dict_changes_nothing():
    base = [
        _pp("in_flight_concurrency", 10, 2.0),
        _pp("queue_depth", 12, 3.0),
        _pp("utilization", 30, 5.0),
    ]
    extra = _pp("utilization_throughput", 500, 0.5)  # costlier and faster than all three
    plain, with_extra = _fr(base), _fr(base + [extra])
    assert iso_cost_budget(plain) == 30
    assert reached_p99(with_extra, 30) == reached_p99(plain, 30)
    assert h1_holds_on(with_extra) is h1_holds_on(plain)
    assert h2_worst_on(with_extra) is h2_worst_on(plain)
    assert ranking(with_extra) == ranking(plain)
    assert h4_holds_on(with_extra, with_extra) is h4_holds_on(plain, plain)


def test_a_missing_compared_signal_is_refused_not_scored():
    fr = _fr([_pp("in_flight_concurrency", 10, 2.0), _pp("queue_depth", 12, 3.0)])
    for fn in (h1_holds_on, h2_worst_on, ranking):
        with pytest.raises(ValueError, match="utilization"):
            fn(fr)
