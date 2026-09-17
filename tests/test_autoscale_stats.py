"""Artifact 2's statistics, pinned to artifact 1's conventions.

The conformance test at the bottom is the point of this file: `autoscale`
cannot import `coldstart` (tests/test_autoscale_boundary.py), so these are a
second implementation of the same conventions, and a second implementation that
nothing compares is a second answer waiting to be published.
"""

import pytest

from autoscale.stats import (
    MIN_SAMPLES,
    bootstrap_interval,
    median,
    percentiles,
    quantile,
)


def test_quantile_interpolates_between_order_statistics():
    # Not nearest-rank: q=0.5 on four points is the mean of the middle two.
    assert quantile(sorted([1.0, 2.0, 3.0, 4.0]), 0.5) == pytest.approx(2.5)


def test_quantile_at_the_endpoints_is_the_endpoint():
    xs = sorted([1.0, 5.0, 9.0])
    assert quantile(xs, 0.0) == 1.0
    assert quantile(xs, 1.0) == 9.0


def test_median_of_an_even_sample_is_the_mean_of_the_middle_two():
    assert median([4.0, 1.0, 3.0, 2.0]) == pytest.approx(2.5)


def test_an_empty_sample_is_refused():
    with pytest.raises(ValueError, match="must not be empty"):
        median([])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_sample_value_is_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        median([1.0, bad, 3.0])


def test_percentiles_below_the_sample_floor_are_refused():
    """A percentile from too few samples is an observation, not a measurement.
    p99 needs 500; asking for it from 30 must raise rather than return a number
    that looks like the other four."""
    with pytest.raises(ValueError, match="p99"):
        percentiles([float(i) for i in range(30)], want=("p99",))


def test_percentiles_above_the_floor_are_reported():
    xs = [float(i) for i in range(600)]
    got = percentiles(xs, want=("p50", "p99"))
    assert got["p50"] == pytest.approx(299.5)
    assert got["p99"] == pytest.approx(593.01)


def test_bootstrap_interval_brackets_the_point_estimate():
    xs = [float(i) for i in range(40)]
    got = bootstrap_interval(xs, iterations=2000, seed=0)
    assert got["lo"] <= got["point"] <= got["hi"]
    assert got["point"] == pytest.approx(median(xs))


def test_bootstrap_interval_is_reproducible_from_its_seed():
    xs = [float(i) for i in range(40)]
    assert bootstrap_interval(xs, iterations=500, seed=7) == bootstrap_interval(
        xs, iterations=500, seed=7
    )


def test_bootstrap_interval_below_the_floor_is_refused():
    """The confidence-interval equivalent of reporting p99 from two points:
    without this, a single observation yields a confident-looking zero-width
    interval."""
    with pytest.raises(ValueError, match="at least"):
        bootstrap_interval([1.0], iterations=100, seed=0)


@pytest.mark.parametrize(
    ("iterations", "alpha"),
    [
        (1, 0.05),  # hi_idx goes NEGATIVE and would index from the end
        (3, 0.99),  # lo_idx overtakes hi_idx: 1 > 0
        (5, 0.90),  # and again at 2 > 1
    ],
)
def test_too_few_iterations_for_the_alpha_is_refused(iterations, alpha):
    """The percentile-method endpoints invert rather than raise on their own,
    returning a backwards interval.

    The parameters matter and are easy to get wrong -- an earlier draft of this
    test used iterations=5, alpha=0.01, which gives lo=0 and hi=3 and does not
    invert at all, so it asserted a raise that the guard had no reason to make.
    Inversion needs either a single draw (hi_idx = -1, which Python would
    happily read as the LAST element rather than erroring) or an alpha extreme
    enough that the two indices cross.
    """
    with pytest.raises(ValueError, match="too few"):
        bootstrap_interval(
            [float(i) for i in range(30)], iterations=iterations, alpha=alpha, seed=0
        )


def test_a_zero_width_sample_gives_a_zero_width_interval():
    """Not a degenerate case to guard against -- it is the correct answer, and
    it is one artifact 2 actually hits: under some regimes every repetition of
    a policy delivers the identical p99."""
    got = bootstrap_interval([3.0] * 30, iterations=500, seed=0)
    assert got == {"point": 3.0, "lo": 3.0, "hi": 3.0}


def test_it_agrees_with_artifact_ones_implementation():
    """The anti-drift device. `autoscale` cannot import `coldstart`, so these
    conventions are implemented twice; this test is the only thing making the
    second copy a copy rather than a second answer. Tests may import artifact 1
    -- tests/test_autoscale_boundary.py scans `autoscale/`, not `tests/`."""
    from coldstart.analysis import stats as a1

    xs = [
        3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0, 5.0, 8.0,
        9.0, 7.0, 9.0, 3.0, 2.0, 3.0, 8.0, 4.0, 6.0, 2.0, 6.0, 4.0,
    ]  # fmt: skip

    assert median(xs) == a1.median(xs)
    assert MIN_SAMPLES == a1.MIN_SAMPLES
    for q in (0.0, 0.1, 0.25, 0.5, 0.9, 0.99, 1.0):
        assert quantile(sorted(xs), q) == a1._quantile(sorted(xs), q)
