import math

import pytest

from toolcall.effects import (
    cluster_bootstrap,
    contrast,
    ever_flip_rows,
    half_rows,
    holm,
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
