"""Amendment §14, decided by the owner on 2026-10-04: in the bursty regime the
hot-model rule and dedicate's fleet size are set on a model's ON-period load.

A bursty model gets all of its traffic while ON, a fraction `duty` of the time,
so its load then is its average divided by duty. Plan 1 sized on the average,
and on its placeholder sweep every strategy, dedicate included, came out
dominated in the bursty regime: a GPU sized for the average carried five times
that during a burst. The rule stays one rule, applied to all three strategies.
"""

import math

import pytest

from placement.evaluate import GridPoint, evaluate_point, sizing_load_factor
from placement.fleet import family, hot_allocation
from placement.traffic import zipf_shares
from tests.test_placement_evaluate import ENGINES, SCENARIO, SWAP


def test_the_peak_factor_scales_every_models_load():
    # Loads at factor 5 are 3.0, 1.0, 0.5, 0.5 GPUs: model 0 needs
    # ceil(3.0 / 0.7) = 5 pinned GPUs and model 1 ceil(1.0 / 0.7) = 2.
    shares = (0.6, 0.2, 0.1, 0.1)
    assert hot_allocation(shares, offered_gpus=1.0, hot_fraction=0.7) == {}
    assert hot_allocation(shares, offered_gpus=1.0, hot_fraction=0.7, peak_factor=5.0) == {0: 5, 1: 2}


@pytest.mark.parametrize("bad", [0.5, math.nan, math.inf])
def test_a_peak_factor_below_one_or_not_finite_is_refused(bad):
    with pytest.raises(ValueError, match="peak_factor"):
        hot_allocation((0.5, 0.5), offered_gpus=1.0, hot_fraction=0.7, peak_factor=bad)


def test_spread_sizes_on_the_average_and_bursty_on_the_on_period():
    assert sizing_load_factor("spread", 0.2) == 1.0
    assert sizing_load_factor("bursty", 0.2) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        sizing_load_factor("bursty", 1.0)
    with pytest.raises(ValueError):
        sizing_load_factor("steady", 0.2)


def _dedicate_m(shares, peak_factor):
    hot = hot_allocation(shares, SCENARIO.offered_gpus, SCENARIO.hot_fraction, peak_factor)
    (only,) = family("dedicate", shares, hot)
    return only.m


def test_the_evaluation_applies_the_regimes_factor_to_every_strategy():
    shares = zipf_shares(SCENARIO.n_models, 1.0)
    for regime, factor in (("spread", 1.0), ("bursty", 1.0 / SCENARIO.duty)):
        evaluation = evaluate_point(GridPoint(1.0, regime, 40.0), SCENARIO, ENGINES, SWAP,
                                    repetitions=1, seed=0)
        assert evaluation.outcomes["dedicate"][0].m == _dedicate_m(shares, factor), regime
        hot = hot_allocation(shares, SCENARIO.offered_gpus, SCENARIO.hot_fraction, factor)
        # Swap and co-locate start from the same pinned GPUs: one rule for all three.
        assert evaluation.outcomes["swap"][0].m == sum(hot.values()) + 1, regime
    assert _dedicate_m(shares, 1.0 / SCENARIO.duty) > _dedicate_m(shares, 1.0)
