import pytest

from coldstart.analysis import economics
from placement.money import (
    DAYS_PER_MONTH,
    SECONDS_PER_HOUR,
    Assumptions,
    monthly_cost,
    monthly_difference,
)

RATE = Assumptions(gpu_hourly_rate=0.5, provenance="illustrative round number")


def test_the_calendar_agrees_with_artifact_one():
    """A test may import `coldstart`; the package may not."""
    assert SECONDS_PER_HOUR == economics.SECONDS_PER_HOUR
    assert DAYS_PER_MONTH == economics.DAYS_PER_MONTH


def test_a_fleet_costs_its_gpus_times_the_month():
    assert monthly_cost(10, RATE) == pytest.approx(10 * 24 * 365 / 12 * 0.5)


def test_the_crossover_in_dollars_is_the_gpu_difference_priced():
    assert monthly_difference(21, 12, RATE) == pytest.approx(9 * 24 * 365 / 12 * 0.5)


@pytest.mark.parametrize("rate", [0.0, -1.0, float("nan")])
def test_a_nonsensical_rate_is_refused(rate):
    with pytest.raises(ValueError):
        Assumptions(gpu_hourly_rate=rate, provenance="x")


def test_an_unlabelled_rate_is_refused():
    with pytest.raises(ValueError, match="provenance"):
        Assumptions(gpu_hourly_rate=1.0, provenance=" ")
