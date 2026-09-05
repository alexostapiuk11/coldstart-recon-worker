import pytest

from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags


def test_arm_pools_exclude_the_first_touch_run():
    """Artifact 1's single first-touch run (arm A, 2266.6 s) measures image
    distribution to a host that has never held the image, not a cold start.
    One such observation in 100 would dominate every p99 in the sweep."""
    lags = load_measured_lags("data/campaign.jsonl")

    assert len(lags["A"].samples) == 99
    assert len(lags["C"].samples) == 100
    assert max(lags["A"].samples) < 200.0


def test_measured_medians_match_artifact_ones_published_numbers():
    lags = load_measured_lags("data/campaign.jsonl")

    assert lags["A"].median() == pytest.approx(81.1, abs=0.5)
    assert lags["C"].median() == pytest.approx(39.4, abs=0.5)


def test_sampling_is_deterministic_given_a_seed():
    import random

    d = LagDistribution(samples=[10.0, 20.0, 30.0])

    first = [d.sample(random.Random(1)) for _ in range(5)]
    second = [d.sample(random.Random(1)) for _ in range(5)]

    assert first == second


def test_sampling_only_ever_returns_measured_values():
    """Resampling, not fitting. A value the campaign never observed must never
    come out -- that is the whole reason this is an ECDF and not a parametric
    fit (spec section 3)."""
    import random

    d = LagDistribution(samples=[10.0, 20.0, 30.0])
    rng = random.Random(7)

    drawn = {d.sample(rng) for _ in range(200)}

    assert drawn <= {10.0, 20.0, 30.0}


def test_an_empty_distribution_refuses_to_be_built():
    with pytest.raises(ValueError, match="at least one sample"):
        LagDistribution(samples=[])
