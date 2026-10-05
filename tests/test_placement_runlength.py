import math

import pytest

from placement.runlength import pilot_window
from placement.traffic import decile_of, zipf_shares

DECILES_20 = decile_of(20)


def test_spread_matches_the_amendments_table():
    """Amendment §8: at s = 1.0 over 20 models, all 30 repetitions clear the
    floor with 95% probability at about 19,950 requests per run. The pilot
    finds its window empirically, so it lands near that, not on it."""
    shares = zipf_shares(20, 1.0)
    window = pilot_window(
        shares, DECILES_20, "spread", total_rate=100.0, repetitions=30,
        mean_burst=30.0, duty=0.2, pilot_traces=1200, seed=0, start=150.0, grow=1.02,
    )
    assert 100.0 * window == pytest.approx(19950, rel=0.05)


def test_bursty_needs_a_longer_window_than_spread():
    shares = zipf_shares(20, 1.0)
    common = {
        "total_rate": 100.0, "repetitions": 30, "mean_burst": 30.0, "duty": 0.2,
        "pilot_traces": 1200, "seed": 0, "start": 150.0, "grow": 1.05,
    }
    spread = pilot_window(shares, DECILES_20, "spread", **common)
    bursty = pilot_window(shares, DECILES_20, "bursty", **common)
    assert bursty > spread


def test_too_few_pilot_traces_to_allow_any_miss_are_refused():
    with pytest.raises(ValueError, match="pilot traces"):
        pilot_window(
            zipf_shares(20, 1.0), DECILES_20, "spread", 100.0, repetitions=30,
            mean_burst=30.0, duty=0.2, pilot_traces=500, seed=0, start=150.0,
        )


def test_the_pilot_is_reproducible():
    kwargs = {
        "shares": zipf_shares(20, 0.6), "deciles": DECILES_20, "regime": "bursty",
        "total_rate": 100.0, "repetitions": 30, "mean_burst": 30.0, "duty": 0.2,
        "pilot_traces": 600, "seed": 3, "start": 80.0,
    }
    assert pilot_window(**kwargs) == pilot_window(**kwargs)
    assert math.isfinite(pilot_window(**kwargs))
