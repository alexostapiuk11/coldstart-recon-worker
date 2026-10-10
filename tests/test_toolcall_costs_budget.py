from types import SimpleNamespace

import pytest

from toolcall.budget import Line, effective_n, icc, reps_for, table, total
from toolcall.costs import _retry, _single, _units, break_even, cost_per_success
from toolcall.formulation import CELLS


def test_single_attempt_cost_is_spend_over_successes():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, True)]
    assert _single(reps) == (3.0, 2)


def test_the_retry_policy_stops_at_the_first_success_in_each_group():
    reps = [(0, 1.0, False), (1, 1.0, True), (2, 1.0, False),   # group 1: 2 spent, 1 win
            (3, 1.0, False), (4, 1.0, False), (5, 1.0, False),  # group 2: 3 spent, 0 wins
            (6, 1.0, True)]                                      # a partial group is dropped
    assert _retry(reps, 3) == (5.0, 1)


def _records(fail_scenarios: int = 0, n_scen: int = 24, reps: int = 6, cell_fail=None,
             cell_cost=None):
    """Every scenario x cell x block is CORRECT unless the scenario is in the
    failing set (MISSING in every repetition). `cell_fail` maps a cell name to
    its own set of failing scenario indices; `cell_cost` to its per-call cost."""
    out = []
    for s in range(n_scen):
        for cell in CELLS:
            failing = (cell_fail or {}).get(cell.name, set(range(fail_scenarios)))
            for b in range(reps):
                ok = s not in failing
                out.append(SimpleNamespace(
                    run_index=len(out), scenario_id=f"s{s:02d}", cell=cell.name,
                    block_index=b, cost_usd=(cell_cost or {}).get(cell.name, 0.001),
                    grade={"category": "CORRECT" if ok else "MISSING"}))
    return out


def _extra(index, cell, block, category, cost, scenario="s00"):
    return SimpleNamespace(run_index=index, scenario_id=scenario, cell=cell,
                           block_index=block, cost_usd=cost, grade={"category": category})


def test_persistent_failures_make_retrying_dearer_than_the_geometric_formula():
    costs = cost_per_success(_records(fail_scenarios=6), retry_cap=3, iterations=200, seed=1)
    cell = costs["low-terse-loose"]
    assert cell["failure_rate_pooled"] == pytest.approx(0.25)
    assert cell["geometric_usd_per_success"] == pytest.approx(0.001 / 0.75)
    assert cell["retry"]["point"] > cell["geometric_usd_per_success"]
    # 6 scenarios fail all 6 reps: 2 groups of 3 calls, 6 calls spent, no wins.
    # 18 scenarios succeed: 2 groups of 1 call each, 2 calls spent, 2 wins.
    # (6*6 + 18*2) calls * 0.001 / 36 wins = 0.002, against 0.001/0.75 = 0.00133.
    assert cell["retry"]["point"] == pytest.approx(0.002)
    assert cell["single"]["point"] == pytest.approx(cell["geometric_usd_per_success"])
    assert set(cell["retry"]) == {"point", "lo", "hi", "n_scenarios", "iterations", "alpha"}


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


def test_a_graded_call_with_no_metered_cost_is_refused_by_name():
    recs = [SimpleNamespace(run_index=7, scenario_id="s00", cell="low-terse-loose",
                            block_index=0, cost_usd=None, grade={"category": "CORRECT"})]
    with pytest.raises(ValueError, match="run 7 is graded CORRECT but carries no cost"):
        _units(recs)


def test_an_unbounded_upper_endpoint_is_none_and_the_lower_one_a_number():
    # One scenario in 24 succeeds, so about a third of resamples have no wins.
    costs = cost_per_success(_records(fail_scenarios=23), retry_cap=3, iterations=200, seed=1)
    single = costs["low-terse-loose"]["single"]
    assert single["hi"] is None
    assert isinstance(single["lo"], float)


def test_retry_cap_must_fit_inside_the_shortest_scenario_cell():
    with pytest.raises(ValueError, match="retry_cap"):
        cost_per_success(_records(reps=4), retry_cap=5, iterations=50, seed=1)
    with pytest.raises(ValueError, match="retry_cap"):
        cost_per_success(_records(), retry_cap=0, iterations=50, seed=1)
    ok = cost_per_success(_records(reps=4), retry_cap=4, iterations=50, seed=1)
    assert ok["low-terse-loose"]["calls_used_retry"] == 24 * 4


def test_a_missing_cell_and_a_duplicate_are_refused_like_in_effects():
    recs = [r for r in _records() if not (r.scenario_id == "s03" and r.cell == "low-terse-loose")]
    with pytest.raises(ValueError, match="scenario s03 has no graded repetitions in low-terse-loose"):
        cost_per_success(recs, retry_cap=3, iterations=50, seed=1)
    recs = _records()
    recs.append(_extra(9999, "low-terse-loose", 0, "CORRECT", 0.001, scenario="s00"))
    with pytest.raises(ValueError, match="duplicate record for scenario s00, cell low-terse-loose"):
        cost_per_success(recs, retry_cap=3, iterations=50, seed=1)


def test_paid_excluded_calls_are_spend_and_api_errors_are_not():
    cell = "low-terse-loose"
    recs = _records() + [_extra(9001, cell, 6, "REFUSED", 0.002),
                         _extra(9002, cell, 7, "TRUNCATED", 0.003),
                         _extra(9003, cell, 8, "API_ERROR", None)]
    costs = cost_per_success(recs, retry_cap=2, iterations=50, seed=1)
    entry = costs[cell]
    assert entry["excluded_by_category"] == {"API_ERROR": 1, "REFUSED": 1, "TRUNCATED": 1}
    assert entry["excluded_usd"] == pytest.approx(0.005)
    assert costs["high-rich-strict"]["excluded_usd"] == 0.0
    assert costs["high-rich-strict"]["excluded_by_category"] == {
        "API_ERROR": 0, "REFUSED": 0, "TRUNCATED": 0}
    # The rate is over graded calls only; spend includes the paid excluded ones.
    assert entry["calls"] == 144 and entry["failure_rate_pooled"] == 0.0
    assert entry["single"]["point"] == pytest.approx((0.144 + 0.005) / 144)
    # Retry, cap 2: 3 groups per scenario each spend 1 call for 1 win; s00's
    # extra group (REFUSED, TRUNCATED) spends 0.005 for no win.
    assert entry["retry"]["point"] == pytest.approx((24 * 3 * 0.001 + 0.005) / 72)


def test_units_skip_an_api_error_without_cost_but_refuse_a_paid_call_without_one():
    assert _units([_extra(1, "low-terse-loose", 0, "API_ERROR", None)]) == {}
    with pytest.raises(ValueError, match="run 2 is graded REFUSED but carries no cost"):
        _units([_extra(2, "low-terse-loose", 0, "REFUSED", None)])


def _verdict_pair(terse_fail, rich_fail, terse_cost=0.001, rich_cost=0.001):
    cell_fail = {"low-terse-loose": terse_fail, "low-rich-loose": rich_fail}
    cell_cost = {"low-terse-loose": terse_cost, "low-rich-loose": rich_cost}
    costs = cost_per_success(_records(cell_fail=cell_fail, cell_cost=cell_cost),
                             retry_cap=3, iterations=300, seed=1)
    return next(p for p in break_even(costs) if p["terse"] == "low-terse-loose")


def test_break_even_verdicts_pays_does_not_pay_and_undetermined():
    pays = _verdict_pair(terse_fail=set(range(12)), rich_fail=set(), rich_cost=0.0012)
    assert pays["retry_verdict"] == "pays"
    assert pays["cost_difference_retry"]["hi"] < 0
    dearer = _verdict_pair(terse_fail=set(), rich_fail=set(range(12)))
    assert dearer["retry_verdict"] == "does not pay"
    assert dearer["cost_difference_retry"]["lo"] > 0
    overlap = _verdict_pair(terse_fail=set(range(6)), rich_fail=set(range(3, 9)))
    assert overlap["retry_verdict"] == "undetermined"
    lo, hi = overlap["cost_difference_retry"]["lo"], overlap["cost_difference_retry"]["hi"]
    assert lo < 0 < hi


def test_a_terse_cell_that_never_succeeds_is_beaten_by_rich_that_sometimes_does():
    pair = _verdict_pair(terse_fail=set(range(24)), rich_fail=set(range(6)))
    assert pair["retry_verdict"] == "pays"
    assert pair["cost_difference_retry"] == {"point": None, "lo": None, "hi": None}


def test_the_geometric_required_rate_is_clamped_and_flagged_when_unachievable():
    # Rich costs 2x per call; terse fails half the time, so rich would need a
    # failure rate of 1 - 2 * 0.5 = 0: exactly achievable, and only at zero.
    even = _verdict_pair(terse_fail=set(range(12)), rich_fail=set(), rich_cost=0.002)
    assert even["required_rich_failure_rate_geometric"] == pytest.approx(0.0)
    assert even["achievable_geometric"] and even["pays_geometric"]
    # 3x per call against a 50% failing terse: 1 - 3 * 0.5 < 0, unachievable.
    never = _verdict_pair(terse_fail=set(range(12)), rich_fail=set(), rich_cost=0.003)
    assert never["required_rich_failure_rate_geometric"] == 0.0
    assert never["achievable_geometric"] is False and never["pays_geometric"] is False
    assert never["overhead_per_call"] == pytest.approx(2.0)


def test_icc_on_unequal_groups_is_an_interior_value():
    groups = [[1, 1, 1], [0, 0], [1, 0, 1, 0, 1], [0, 0, 0, 0]]
    # k=4, N=14, grand mean 3/7. SSB = 3*(4/7)^2 + 2*(3/7)^2 + 5*(6/35)^2 + 4*(3/7)^2
    # = 546/245, MSB = SSB/3 = 26/35. SSW = 1.2 (only group 3 varies), MSW = 1.2/10 = 3/25.
    # n0 = (14 - 54/14)/3 = 71/21. rho = (MSB - MSW) / (MSB + (n0 - 1) MSW)
    # = (109/175) / (36/35) = 109/180 = 0.60556.
    assert icc(groups) == pytest.approx(109 / 180)


def test_icc_is_undefined_without_within_group_information_or_variation():
    with pytest.raises(ValueError, match="two or more repetitions"):
        icc([[1], [0], [1]])
    assert icc([[1] * 4, [1] * 4, [1] * 4]) == 1.0   # undefined, treated as 1


def test_scenarios_keyword_restricts_spend_retry_and_guards_to_the_analysable_set():
    records = _records(fail_scenarios=6, n_scen=30)  # s00-s05 fail every repetition
    analysable = [f"s{i:02d}" for i in range(6, 30)]
    # A scenario outside the set whose paid call carries no cost would be
    # refused; outside the set it must never be read.
    records.append(_extra(9999, CELLS[0].name, 0, "MISSING", None, scenario="s99"))
    costs = cost_per_success(records, retry_cap=3, iterations=100, seed=1, scenarios=analysable)
    cell = costs["low-terse-loose"]
    assert cell["calls"] == 24 * 6
    assert cell["failure_rate_pooled"] == 0.0
    assert cell["single"]["n_scenarios"] == cell["retry"]["n_scenarios"] == 24
    assert cell["single"]["point"] == pytest.approx(0.001)
    # Default (None): every scenario in the records, as before.
    everyone = {f"s{i:02d}" for i in range(30)}
    default = cost_per_success(_records(fail_scenarios=6, n_scen=30), retry_cap=3,
                               iterations=100, seed=1)
    explicit = cost_per_success(_records(fail_scenarios=6, n_scen=30), retry_cap=3, iterations=100,
                                seed=1, scenarios=everyone)
    assert default == explicit
    assert default["low-terse-loose"]["retry"]["n_scenarios"] == 30
    # A scenario named in the set but absent from the records is refused.
    with pytest.raises(ValueError, match="s77"):
        cost_per_success(_records(n_scen=30), retry_cap=3, iterations=100, seed=1,
                         scenarios=[*sorted(everyone), "s77"])
