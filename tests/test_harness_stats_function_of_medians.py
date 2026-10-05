import math

import pytest

from harness.stats import bootstrap_function_of_medians, bootstrap_median_diff


def _sample(offset: float, n: int = 30) -> list[float]:
    return [offset + (i % 7) * 0.5 for i in range(n)]


def test_it_reproduces_the_unpaired_median_difference_exactly():
    """A difference of two medians through the generic function must be the
    same computation as the fixed-shape bootstrap, draw for draw. Same seed,
    same resampling order, same interval -- otherwise the module has two
    definitions of one interval."""
    a, b = _sample(10.0), _sample(4.0)
    generic = bootstrap_function_of_medians(
        [a, b], lambda m: m[0] - m[1], iterations=500, seed=3
    )
    fixed = bootstrap_median_diff(a, b, iterations=500, seed=3)
    assert generic == fixed


def test_difference_in_differences_point_is_the_arithmetic_on_medians():
    groups = [_sample(10.0), _sample(4.0), _sample(7.0), _sample(3.0)]
    res = bootstrap_function_of_medians(
        groups, lambda m: (m[0] - m[1]) - (m[2] - m[3]), iterations=200, seed=1
    )
    assert math.isclose(res["point"], (10.0 - 4.0) - (7.0 - 3.0))
    assert res["lo"] <= res["point"] <= res["hi"]


def test_a_ratio_of_medians_is_supported():
    res = bootstrap_function_of_medians(
        [_sample(8.0), _sample(10.0)], lambda m: 1 - m[0] / m[1], iterations=200, seed=2
    )
    assert res["lo"] <= res["point"] <= res["hi"]


def test_every_group_must_meet_the_bootstrap_floor():
    with pytest.raises(ValueError, match="samples\\[1\\]"):
        bootstrap_function_of_medians([_sample(1.0), [1.0, 2.0]], lambda m: m[0] - m[1])


def test_a_non_finite_statistic_is_refused():
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_function_of_medians([_sample(1.0), _sample(2.0)], lambda m: math.inf)


def test_empty_samples_are_refused():
    with pytest.raises(ValueError, match="at least one group"):
        bootstrap_function_of_medians([], lambda m: 0.0)
