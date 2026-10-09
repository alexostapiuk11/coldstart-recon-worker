from types import SimpleNamespace

import pytest

from toolcall.budget import Line, effective_n, icc, reps_for, table, total
from toolcall.costs import _retry, _single, break_even, cost_per_success
from toolcall.formulation import CELLS


def test_single_attempt_cost_is_spend_over_successes():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, True)]
    assert _single(reps) == (3.0, 2)


def test_the_retry_policy_stops_at_the_first_success_in_each_group():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, False),   # group 1: 2 spent, 1 win
            (3, 1.0, False), (4, 1.0, False), (5, 1.0, False),  # group 2: 3 spent, 0 wins
            (6, 1.0, True)]                                      # a partial group is dropped
    assert _retry(reps, 3) == (5.0, 1)


def _records(fail_scenarios: int, n_scen: int = 24, reps: int = 6):
    out = []
    for s in range(n_scen):
        for cell in CELLS:
            for b in range(reps):
                ok = s >= fail_scenarios
                out.append(SimpleNamespace(scenario_id=f"s{s:02d}", cell=cell.name,
                                           block_index=b, cost_usd=0.001,
                                           grade={"category": "CORRECT" if ok else "MISSING"}))
    return out


def test_persistent_failures_make_retrying_dearer_than_the_geometric_formula():
    costs = cost_per_success(_records(fail_scenarios=6), retry_cap=3, iterations=200, seed=1)
    cell = costs["low-terse-loose"]
    assert cell["failure_rate_pooled"] == pytest.approx(0.25)
    assert cell["geometric_usd_per_success"] == pytest.approx(0.001 / 0.75)
    assert cell["retry"]["point"] > cell["geometric_usd_per_success"]


def test_a_cell_with_no_successes_reports_unbounded_not_infinity():
    costs = cost_per_success(_records(fail_scenarios=24), retry_cap=3, iterations=50, seed=1)
    assert costs["low-terse-loose"]["single"]["point"] is None


def test_break_even_pairs_terse_with_rich_at_each_count_and_strictness():
    costs = cost_per_success(_records(fail_scenarios=6), retry_cap=3, iterations=50, seed=1)
    pairs = break_even(costs)
    assert {(p["terse"], p["rich"]) for p in pairs} == {
        ("low-terse-loose", "low-rich-loose"), ("low-terse-strict", "low-rich-strict"),
        ("high-terse-loose", "high-rich-loose"), ("high-terse-strict", "high-rich-strict")}


def test_icc_is_one_when_scenarios_never_vary_and_zero_when_they_do_not_cluster():
    assert icc([[1] * 5, [0] * 5, [1] * 5]) == 1.0
    assert icc([[1, 0] * 5, [0, 1] * 5, [1, 0] * 5]) == 0.0


def test_effective_n_and_the_rule_for_n():
    assert effective_n(30, 5, 0.9) == pytest.approx(32.6, abs=0.1)
    assert effective_n(30, 40, 0.9) == pytest.approx(33.2, abs=0.1)
    assert reps_for(0.9, 5, 20) == 5     # extra repetitions buy almost nothing
    assert reps_for(0.5, 5, 20) == 19
    assert reps_for(0.1, 5, 20) == 20    # capped
    assert reps_for(0.0, 5, 20) == 20


def test_the_budget_table_adds_up():
    lines = [Line("a", 100, 0.01), Line("b", 10, 0.5)]
    assert total(lines) == pytest.approx(6.0)
    assert "**6.00**" in table(lines) and "7.50" in table(lines)
