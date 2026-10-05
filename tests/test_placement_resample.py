import random

import pytest

from placement.resample import EmpiricalDistribution


def test_a_draw_is_always_a_measured_value():
    dist = EmpiricalDistribution(samples=(12.0, 18.5, 30.0), measured=True)
    rng = random.Random(3)
    assert {dist.draw(rng) for _ in range(200)} == {12.0, 18.5, 30.0}


def test_draws_are_reproducible_from_the_seed():
    dist = EmpiricalDistribution(samples=(1.0, 2.0, 3.0, 4.0), measured=True)
    first = [dist.draw(random.Random(9)) for _ in range(5)]
    again = [dist.draw(random.Random(9)) for _ in range(5)]
    assert first == again


@pytest.mark.parametrize(
    "samples",
    [(), (float("nan"),), (float("inf"),), (-1.0,), (True,), ("3",)],
)
def test_it_refuses_samples_that_would_corrupt_a_run(samples):
    with pytest.raises(ValueError):
        EmpiricalDistribution(samples=samples, measured=True)


def test_samples_cannot_be_mutated_after_validation():
    dist = EmpiricalDistribution(samples=[1.0, 2.0], measured=True)
    assert isinstance(dist.samples, tuple)
