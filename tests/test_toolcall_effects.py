import math
import random
from types import SimpleNamespace

import pytest

from toolcall.effects import (
    cluster_bootstrap,
    contrast,
    ever_flip_rows,
    graded_outcomes,
    half_rows,
    holm,
    per_scenario_wilson,
    rate_rows,
    weights,
    wilson,
)
from toolcall.formulation import CELLS


def test_wilson_matches_the_textbook_values():
    lo, hi = wilson(3, 100)
    assert lo == pytest.approx(0.01025, abs=1e-4) and hi == pytest.approx(0.08452, abs=1e-4)
    assert wilson(0, 20)[0] == 0.0 and wilson(20, 20)[1] == 1.0


def test_wilson_never_leaves_zero_to_one_where_the_normal_formula_would():
    p = 1 / 30
    normal_lo = p - 1.96 * math.sqrt(p * (1 - p) / 30)
    assert normal_lo < 0 < wilson(1, 30)[0]


def test_weights_are_the_standard_two_to_the_three_contrasts():
    w = weights("main:count")
    assert sum(w.values()) == 0 and w["high-rich-strict"] == 0.25
    i = weights("interaction:richness:count")
    assert i["high-rich-loose"] == 0.5 and i["low-rich-loose"] == -0.5
    at = weights("at:richness:count:high")
    assert at["low-rich-loose"] == 0 and at["high-rich-loose"] == 0.5


def _row(rate):
    return {c.name: rate(c) for c in CELLS}


def test_contrasts_recover_a_planted_main_effect_and_interaction():
    row = _row(lambda c: 0.1 + 0.2 * (c.count == "high")
               - 0.15 * (c.count == "high" and c.richness == "rich"))
    assert contrast(row, "at:richness:count:low") == pytest.approx(0.0)
    assert contrast(row, "at:richness:count:high") == pytest.approx(-0.15)
    assert contrast(row, "interaction:richness:count") == pytest.approx(-0.15)
    assert contrast(row, "main:count") == pytest.approx(0.2 - 0.075)
    assert contrast(row, "main:strictness") == pytest.approx(0.0)


def test_the_bootstrap_resamples_scenarios_and_refuses_too_few():
    units = [float(i % 2) for i in range(24)]
    r = cluster_bootstrap(units, lambda xs: sum(xs) / len(xs), iterations=500, seed=1)
    assert r["lo"] < 0.5 < r["hi"] and r["n_scenarios"] == 24
    with pytest.raises(ValueError, match="at least 20"):
        cluster_bootstrap(units[:19], sum)


def test_clustering_widens_the_interval_relative_to_pretending_calls_are_independent():
    """24 scenarios that each fail all 10 repetitions or none: 240 calls, but
    only 24 independent facts. The scenario bootstrap must be about as wide as
    a 24-sample interval, far wider than a 240-call Wilson interval."""
    rows = [1.0] * 6 + [0.0] * 18
    r = cluster_bootstrap(rows, lambda xs: sum(xs) / len(xs), iterations=2000, seed=2)
    w_lo, w_hi = wilson(60, 240)
    assert (r["hi"] - r["lo"]) > 1.8 * (w_hi - w_lo)


def test_one_sided_p_values():
    r = cluster_bootstrap([1.0] * 25, lambda xs: sum(xs) / len(xs), iterations=99, seed=0)
    assert r["p_le_0"] == pytest.approx(1 / 100) and r["p_ge_0"] == 1.0


def test_holm_steps_down_and_stops_at_the_first_failure():
    assert holm({"a": 0.01, "b": 0.02, "c": 0.04}, 0.05) == {"a": True, "b": True, "c": True}
    assert holm({"a": 0.01, "b": 0.03, "c": 0.04}, 0.05) == {"a": True, "b": False, "c": False}
    assert holm({"a": 0.2}, 0.05) == {"a": False}


def _outcomes(cats_by_block):
    return {"s1": {c.name: list(enumerate(cats_by_block)) for c in CELLS}}


def test_rates_flips_and_halves():
    o = _outcomes(["CORRECT", "WRONG_TOOL", "CORRECT", "CORRECT"])
    assert rate_rows(o, ("WRONG_TOOL",))[0]["low-terse-loose"] == 0.25
    assert ever_flip_rows(o) == [1.0]
    assert half_rows(o, ("WRONG_TOOL",))[0]["low-terse-loose"] == pytest.approx(-0.5)
    with pytest.raises(ValueError, match="no graded repetitions"):
        rate_rows({"s1": {}}, ("WRONG_TOOL",))


def test_wilson_endpoints_are_exact_at_the_extremes():
    assert wilson(0, 3)[0] == 0.0
    assert wilson(0, 1000)[0] == 0.0
    assert wilson(10, 10)[1] == 1.0
    assert 0.0 < wilson(0, 3)[1] < 1.0 and 0.0 < wilson(10, 10)[0] < 1.0


@pytest.mark.parametrize("estimand", [
    "at:richness:count:hgih",      # misspelled level
    "at:richness:count:rich",      # a richness level word for the count factor
    "at:count:count:high",         # a factor against itself
    "at:count:bogus:high",
    "interaction:count:count",
    "interaction:count",
    "main:bogus",
    "main:count:extra",
    "main",
    "nonsense",
])
def test_weights_refuse_a_malformed_estimand_and_name_it(estimand):
    with pytest.raises(ValueError, match=estimand):
        weights(estimand)


# rate = 0.1 + 0.2 [strict] - 0.1 [strict and rich] + 0.05 [strict and high]
def _strict_row():
    return _row(lambda c: 0.1 + 0.2 * (c.strictness == "strict")
                - 0.1 * (c.strictness == "strict" and c.richness == "rich")
                + 0.05 * (c.strictness == "strict" and c.count == "high"))


def test_the_other_main_effects_interactions_and_conditional_effects_by_hand():
    row = _row(lambda c: 0.1 + 0.2 * (c.count == "high")
               - 0.15 * (c.count == "high" and c.richness == "rich"))
    # richness: rich cells average (0.15 + 0.10) / 2, terse (0.30 + 0.10) / 2
    assert contrast(row, "main:richness") == pytest.approx(0.125 - 0.2)

    s = _strict_row()
    # richness at strict: -0.1 (the count term cancels); at loose: 0
    assert contrast(s, "at:richness:strictness:strict") == pytest.approx(-0.1)
    assert contrast(s, "at:richness:strictness:loose") == pytest.approx(0.0)
    assert contrast(s, "interaction:richness:strictness") == pytest.approx(-0.1)
    # count at strict: +0.05; at loose: 0
    assert contrast(s, "at:count:strictness:strict") == pytest.approx(0.05)
    assert contrast(s, "interaction:count:strictness") == pytest.approx(0.05)
    # strictness at rich: 0.2 - 0.1 + 0.05 / 2; at terse: 0.2 + 0.05 / 2
    assert contrast(s, "at:strictness:richness:rich") == pytest.approx(0.125)
    assert contrast(s, "at:strictness:richness:terse") == pytest.approx(0.225)
    assert contrast(s, "main:strictness") == pytest.approx(0.175)
    assert contrast(s, "at:strictness:count:high") == pytest.approx(0.2 - 0.05 + 0.05)
    assert contrast(s, "at:strictness:count:low") == pytest.approx(0.15)


def test_holm_on_the_textbook_set():
    # p sorted: 0.005, 0.01, 0.03, 0.04 with alpha 0.05 and m = 4. Thresholds
    # alpha / (m - rank): 0.0125, 0.01667, 0.025, 0.05.
    # 0.005 <= 0.0125 reject; 0.01 <= 0.01667 reject; 0.03 > 0.025 stop, so
    # 0.04 is not rejected even though it is below 0.05.
    got = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005}, 0.05)
    assert got == {"a": True, "b": False, "c": False, "d": True}


def test_one_sided_p_values_in_a_non_degenerate_case():
    units = [1.0] * 14 + [0.0] * 10  # mean 0.583; the statistic is mean - 0.5
    r = cluster_bootstrap(units, lambda xs: sum(xs) / len(xs) - 0.5, iterations=2000, seed=3)
    assert r["point"] == pytest.approx(14 / 24 - 0.5) and r["lo"] < r["point"] < r["hi"]
    assert 0.1 < r["p_le_0"] < 0.4
    assert r["p_ge_0"] > 0.6 and r["p_le_0"] < r["p_ge_0"]
    # draws at exactly zero count on both sides
    assert r["p_le_0"] + r["p_ge_0"] >= 1.0


def test_the_interval_is_calibrated_under_a_null_effect():
    """24 scenarios, no true effect, 200 datasets: a 95% percentile interval
    should cover zero about 95% of the time (a bit under at n = 24)."""
    covered = 0
    for d in range(200):
        rng = random.Random(1000 + d)
        units = [rng.gauss(0.0, 1.0) for _ in range(24)]
        r = cluster_bootstrap(units, lambda xs: sum(xs) / len(xs), iterations=200, seed=d)
        covered += r["lo"] <= 0.0 <= r["hi"]
    assert 0.88 <= covered / 200 <= 0.99


def _missing_cell_outcomes():
    o = _outcomes(["CORRECT", "WRONG_TOOL", "CORRECT", "CORRECT"])
    del o["s1"]["high-rich-strict"]
    return o


def test_every_consumer_refuses_a_scenario_missing_a_cell():
    o = _missing_cell_outcomes()
    msg = "scenario s1 has no graded repetitions in high-rich-strict"
    with pytest.raises(ValueError, match=msg):
        rate_rows(o, ("WRONG_TOOL",))
    with pytest.raises(ValueError, match=msg):
        ever_flip_rows(o)
    with pytest.raises(ValueError, match=msg):
        half_rows(o, ("WRONG_TOOL",))
    with pytest.raises(ValueError, match=msg):
        per_scenario_wilson(o, ("WRONG_TOOL",), "high-rich-strict")


def test_a_scenario_absent_altogether_is_refused_not_a_keyerror():
    o = _outcomes(["CORRECT", "WRONG_TOOL", "CORRECT", "CORRECT"])
    for call in (lambda: rate_rows(o, ("WRONG_TOOL",), scenarios=["s1", "s2"]),
                 lambda: ever_flip_rows(o, scenarios=["s2"]),
                 lambda: half_rows(o, ("WRONG_TOOL",), scenarios=["s2"])):
        with pytest.raises(ValueError, match="scenario s2 has no graded repetitions"):
            call()


def _rec(scenario, cell, block, category="CORRECT", run=0):
    return SimpleNamespace(scenario_id=scenario, cell=cell, block_index=block,
                           run_index=run, grade={"category": category})


def test_graded_outcomes_groups_records_and_refuses_a_duplicate_repetition():
    ok = graded_outcomes([_rec("s1", "low-terse-loose", 0), _rec("s1", "low-terse-loose", 1),
                          _rec("s2", "low-terse-loose", 0, "WRONG_TOOL")])
    assert ok == {"s1": {"low-terse-loose": [(0, "CORRECT"), (1, "CORRECT")]},
                  "s2": {"low-terse-loose": [(0, "WRONG_TOOL")]}}
    with pytest.raises(ValueError, match="duplicate record for scenario s1"):
        graded_outcomes([_rec("s1", "low-terse-loose", 0, run=0),
                         _rec("s1", "low-terse-loose", 0, run=7)])
