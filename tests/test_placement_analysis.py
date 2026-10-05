"""The analysis on hand-built evaluations whose sizing is known in advance."""

import dataclasses

import pytest
from a4_evaluations import (
    DESIGN,
    RATE,
    REPS,
    SLO,
    config,
    evaluation,
    swap_cheap,
    sweep,
)

from placement.analysis import analyse, fairness, point_view, size_by_aggregate
from placement.money import HOURS_PER_MONTH, SECONDS_PER_HOUR, monthly_cost

TOTAL_RATE, OUTPUT_LEN = 5.0, 256
REFERENCE = {"regime": "bursty", "s": 1.0}


def _view(e):
    return point_view(e, DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE)


def test_the_aggregate_sizes_a_fleet_the_coldest_decile_does_not_accept():
    e = swap_cheap(1.0, "spread")
    reps = list(range(REPS))
    assert size_by_aggregate(e.outcomes["swap"], reps, SLO) == 4
    view = _view(e)
    assert view["sized"] == {"dedicate": 10, "swap": 6, "colocate": 10}
    rule = view["aggregate_rule"]["swap"]
    assert rule["m"] == 4 and rule["coldest_decile_breach"] == 0.3
    assert rule["coldest_decile_p99"] == pytest.approx(50.02)
    assert rule["decile_p99"][0] == pytest.approx(5.02) and rule["decile_p99"][9] == rule[
        "coldest_decile_p99"]


def test_costs_are_the_sized_fleet_priced_three_ways():
    swap = _view(swap_cheap(1.0, "spread"))["strategies"]["swap"]
    cost = monthly_cost(6, RATE)
    assert swap["monthly_cost"] == pytest.approx(cost)
    assert swap["cost_per_tenant_month"] == pytest.approx(cost / 20)
    tokens = TOTAL_RATE * OUTPUT_LEN * HOURS_PER_MONTH * SECONDS_PER_HOUR
    assert swap["cost_per_million_tokens"] == pytest.approx(cost / tokens * 1e6)


def test_latency_hit_rate_and_swaps_are_read_at_the_sized_fleet():
    swap = _view(swap_cheap(1.0, "spread"))["strategies"]["swap"]
    ap = swap["aggregate_p99"]
    assert ap["lo"] <= ap["point"] <= ap["hi"] and ap["point"] == pytest.approx(4.02)
    assert swap["hit_rate"] == pytest.approx(0.9)
    # 12 swaps in the window from warm-up (100 s) to the end (3700 s).
    assert swap["swaps_per_hour"] == pytest.approx(12 / 3600.0 * 3600)
    assert swap["decile_p99"][9] == pytest.approx(5.02) and swap["decile_breach"][9] == 0.0


def test_a_cheapest_tie_and_the_dollar_gap_are_reported():
    view = _view(swap_cheap(1.0, "spread"))
    assert view["cheapest"] == ["swap"]
    assert view["dedicate_over_cheapest_per_month"] == pytest.approx(
        monthly_cost(10, RATE) - monthly_cost(6, RATE))


def test_a_point_under_the_floor_is_not_evaluable():
    thin = evaluation(1.0, "spread", swap_cheap(1.0, "spread").outcomes, counts=499)
    assert _view(thin) == {"regime": "spread", "s": 1.0, "window_s": 3600.0, "evaluable": False}


def test_fairness_pairs_by_repetition_at_the_larger_sized_fleet():
    e = evaluation(1.0, "bursty", {
        "dedicate": (config("dedicate", 10),),
        "swap": (config("swap", 6, cold_p99=6.0), config("swap", 8, cold_p99=6.0)),
        "colocate": (config("colocate", 8, cold_p99=5.0),),
    })
    result = fairness(e, {"dedicate": 10, "swap": 6, "colocate": 8})
    assert result["m"] == 8
    # Every repetition's coldest-decile difference is exactly 1.0 s.
    assert result["deciles"][9]["point"] == pytest.approx(1.0)
    assert result["deciles"][9]["lo"] == pytest.approx(1.0)
    assert result["deciles"][0]["point"] == pytest.approx(0.0)
    assert fairness(e, {"dedicate": 10, "swap": None, "colocate": 8}) is None


def test_the_full_analysis_states_the_decision_rule_and_the_crossover():
    result = analyse(sweep(), DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                     reference=REFERENCE)
    spread = result["regimes"]["spread"]
    # At s = 0.6 swap and co-locate only meet the SLO at dedicate's M: a
    # three-way tie, reported as a tie (amendment §8), not as a win for dedicate.
    assert spread["decision_rule"] == [
        {"from_s": 0.6, "to_s": 0.6, "cheapest": ["colocate", "dedicate", "swap"]},
        {"from_s": 1.0, "to_s": 1.0, "cheapest": ["swap"]},
    ]
    assert spread["crossover"]["between"] == [[0.6, 1.0]]
    c = spread["crossover"]
    assert c["no_crossing"] + c["one_crossing"] + c["many_crossings"] == c["iterations"]
    bursty = result["regimes"]["bursty"]
    assert bursty["decision_rule"] == [{"from_s": 0.6, "to_s": 1.0, "cheapest": ["swap"]}]
    assert bursty["crossover"]["between"] == []
    assert result["fairness"]["m"] == 10  # swap sized 6, co-locate 10
    assert result["rate"] == {"gpu_hourly_rate": 0.69, "provenance": "test rate"}
    assert result["design"]["skews"] == [0.6, 1.0]


def test_a_reference_that_is_not_a_grid_point_is_refused():
    with pytest.raises(ValueError, match="matches 0"):
        analyse(sweep(), DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                reference={"regime": "bursty", "s": 1.5})


def test_the_decision_rule_never_spans_a_point_that_said_nothing():
    """Swap is cheapest at 0.6 and 1.0, but 0.8 is not evaluable: two runs
    and a gap, not "s = 0.6-1.0: swap"."""
    thin = evaluation(0.8, "spread", swap_cheap(0.8, "spread").outcomes, counts=499)
    evaluations = [swap_cheap(0.6, "spread"), thin, swap_cheap(1.0, "spread"),
                   *[e for e in sweep() if e.point.regime == "bursty"]]
    design = dataclasses.replace(DESIGN, skews=(0.6, 0.8, 1.0))
    result = analyse(evaluations, design, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                     reference=REFERENCE)
    spread = result["regimes"]["spread"]
    assert spread["decision_rule"] == [
        {"from_s": 0.6, "to_s": 0.6, "cheapest": ["swap"]},
        {"from_s": 1.0, "to_s": 1.0, "cheapest": ["swap"]},
    ]
    assert spread["gaps"] == [{"s": 0.8, "reason": "not evaluable"}]


def test_a_point_where_nothing_meets_the_slo_is_a_gap():
    import placement.analysis as module

    view = {"s": 1.0, "evaluable": True, "cheapest": []}
    segments, gaps = module._segments([view])
    assert segments == [] and gaps == [{"s": 1.0, "reason": "no strategy meets the SLO"}]
