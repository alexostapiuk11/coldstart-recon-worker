import math
import random
from collections import Counter

import pytest

from placement.traffic import bursty_trace, decile_of, spread_trace, zipf_shares


def test_zipf_shares_sum_to_one_and_fall_with_rank():
    shares = zipf_shares(20, 1.0)
    assert math.isclose(sum(shares), 1.0)
    assert list(shares) == sorted(shares, reverse=True)


def test_zipf_shares_match_the_amendments_table():
    """Amendment §8: at s = 2.0 over 20 models the coldest decile (the two
    least popular models) carries 0.33% of traffic, and the hottest model
    62.7%."""
    shares = zipf_shares(20, 2.0)
    assert round(shares[18] + shares[19], 4) == 0.0033
    assert round(shares[0], 3) == 0.627


def test_s_zero_is_uniform():
    assert zipf_shares(4, 0.0) == (0.25, 0.25, 0.25, 0.25)


@pytest.mark.parametrize("n, s", [(1, 1.0), (20, -0.5), (20, float("nan")), (2.0, 1.0)])
def test_zipf_refuses_bad_parameters(n, s):
    with pytest.raises(ValueError):
        zipf_shares(n, s)


def test_deciles_split_models_evenly_hottest_first():
    assert decile_of(20) == tuple(k // 2 for k in range(20))
    with pytest.raises(ValueError):
        decile_of(25)


@pytest.mark.parametrize("generator", ["spread", "bursty"])
def test_long_run_rates_follow_the_shares(generator):
    """Pooled over ten seeds. One bursty run's rate for a model is set by its
    total ON time, which spreads by 3-4% per run at this window (measured over
    40 seeds while writing this test, with mean error under 0.5% for every
    model). Pooling ten runs puts 5% at about four standard errors, so the test
    checks the generator's bias, not one seed's luck."""
    shares = zipf_shares(4, 1.0)
    until = 100000.0
    totals = Counter()
    for seed in range(10):
        rng = random.Random(seed)
        if generator == "spread":
            trace = spread_trace(shares, 2.0, until, rng)
        else:
            trace = bursty_trace(shares, 2.0, until, mean_burst=20.0, duty=0.2, rng=rng)
        totals.update(model for _, model in trace)
    for k, share in enumerate(shares):
        assert totals[k] / (10 * until) == pytest.approx(2.0 * share, rel=0.05)


def _dispersion(trace, model, until, width):
    """Variance over mean of per-window request counts. About 1 for Poisson."""
    bins = [0] * int(until // width)
    for t, m in trace:
        if m == model and t < len(bins) * width:
            bins[int(t // width)] += 1
    mean = sum(bins) / len(bins)
    return sum((b - mean) ** 2 for b in bins) / len(bins) / mean


def test_bursty_clusters_and_spread_does_not():
    """The whole reason for two regimes: same shares, different clustering."""
    shares = zipf_shares(4, 1.0)
    until = 20000.0
    spread = spread_trace(shares, 2.0, until, random.Random(2))
    bursty = bursty_trace(shares, 2.0, until, 20.0, 0.2, random.Random(2))
    assert _dispersion(spread, 0, until, 10.0) == pytest.approx(1.0, abs=0.15)
    assert _dispersion(bursty, 0, until, 10.0) > 3.0


@pytest.mark.parametrize("generator", ["spread", "bursty"])
def test_a_trace_is_sorted_and_inside_the_window(generator):
    shares = zipf_shares(4, 0.5)
    rng = random.Random(5)
    if generator == "spread":
        trace = spread_trace(shares, 5.0, 100.0, rng)
    else:
        trace = bursty_trace(shares, 5.0, 100.0, 10.0, 0.3, rng)
    times = [t for t, _ in trace]
    assert times == sorted(times)
    assert all(0.0 < t <= 100.0 for t in times)
    assert {m for _, m in trace} <= {0, 1, 2, 3}


def test_traces_are_reproducible_from_the_seed():
    shares = zipf_shares(4, 1.0)
    assert spread_trace(shares, 3.0, 50.0, random.Random(8)) == spread_trace(
        shares, 3.0, 50.0, random.Random(8)
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shares": (0.5, 0.4), "total_rate": 1.0, "until": 10.0},
        {"shares": (0.5, 0.5), "total_rate": 0.0, "until": 10.0},
        {"shares": (0.5, 0.5), "total_rate": 1.0, "until": float("inf")},
        {"shares": (1.0, 0.0), "total_rate": 1.0, "until": 10.0},
    ],
)
def test_spread_refuses_inputs_that_misstate_the_load(kwargs):
    with pytest.raises(ValueError):
        spread_trace(rng=random.Random(0), **kwargs)


@pytest.mark.parametrize("duty", [0.0, 1.0, float("nan")])
def test_bursty_refuses_a_duty_that_is_not_a_burst(duty):
    with pytest.raises(ValueError):
        bursty_trace((0.5, 0.5), 1.0, 10.0, 5.0, duty, random.Random(0))
