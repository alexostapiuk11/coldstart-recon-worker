import math
import random
import statistics

import pytest

import coldstart.analysis.stats as stats_module
from coldstart.analysis.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    MIN_SAMPLES,
    _percentile_interval,
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_contrast_difference,
    bootstrap_paired_median_diff,
    ecdf,
    percentiles,
    within_host_triples,
)

# ---------------------------------------------------------------------------
# shared fixture helpers
# ---------------------------------------------------------------------------


def _triple(idx, host, a, b, c, field="t_total"):
    return [
        {"triple_index": idx, "arm": "A", "host_id": host, field: a},
        {"triple_index": idx, "arm": "B", "host_id": host, field: b},
        {"triple_index": idx, "arm": "C", "host_id": host, field: c},
    ]


def _const_triples(n, a, b, c, field="t_total"):
    return [_triple(i, f"h{i}", a, b, c, field=field) for i in range(n)]


def _value_triples(values, field="t_total"):
    """One triple per value in `values`, with B = C = 0.0. Both a paired
    median-diff on (A, B) and a paired contrast (A-B)-(B-C) reduce to A
    exactly under this construction, so the same helper builds fixtures with
    a hand-known per-triple statistic for either function."""
    return [_triple(i, f"h{i}", v, 0.0, 0.0, field=field) for i, v in enumerate(values)]


def _gauss_triples(rng, n, mean_a, mean_b, mean_c, sd=10.0, host_offset_sd=0.0):
    triples = []
    for i in range(n):
        offset = rng.gauss(0.0, host_offset_sd) if host_offset_sd else 0.0
        a = mean_a + offset + rng.gauss(0.0, sd)
        b = mean_b + offset + rng.gauss(0.0, sd)
        c = mean_c + offset + rng.gauss(0.0, sd)
        triples.append(_triple(i, f"h{i}", a, b, c))
    return triples


# ---------------------------------------------------------------------------
# percentiles
# ---------------------------------------------------------------------------


def test_percentiles_reports_p50_p90_p95():
    p = percentiles(list(range(1, 101)))
    assert p["p50"] == pytest.approx(50.5, abs=1.0)
    assert "p90" in p and "p95" in p


def test_p99_is_refused_below_the_sample_floor():
    with pytest.raises(ValueError) as e:
        percentiles(list(range(100)), want=("p99",))
    assert "p99" in str(e.value)


def test_p99_is_allowed_with_enough_samples():
    p = percentiles(list(range(1000)), want=("p50", "p99"))
    assert "p99" in p


# Hardcoded, not read from MIN_SAMPLES: if the test derived `need` from the
# module's own dict, a mutation to a floor's value would be self-consistent
# with the test (both the code and the test would move together) and the
# mutation would survive. Pinning the expected numbers here is what makes
# this a real pre-registration check rather than a tautology.
_EXPECTED_FLOORS = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}


def test_min_samples_matches_the_pre_registered_floors():
    assert MIN_SAMPLES == _EXPECTED_FLOORS


@pytest.mark.parametrize("name", sorted(_EXPECTED_FLOORS))
def test_every_percentile_floor_is_enforced_independently(name):
    """Each entry in MIN_SAMPLES is its own pre-registered parameter. A mutation
    that changes any single floor (not just p99's) must fail a test."""
    need = _EXPECTED_FLOORS[name]
    with pytest.raises(ValueError) as e:
        percentiles(list(range(need - 1)), want=(name,))
    assert name in str(e.value)
    # exactly at the floor it must be allowed
    p = percentiles(list(range(need)), want=(name,))
    assert name in p


def test_p50_at_the_sample_floor_even_and_odd_n():
    """Pin the linear-interpolation formula (numpy method="linear", see the
    module docstring) at p50, for both an even and an odd sample count.
    This is NOT nearest-rank: at even n the two middle order statistics are
    averaged, matching statistics.median, rather than one of them being
    picked by rounding. Values independently verified against
    numpy.percentile(xs, 50, method="linear")."""
    # n=20 (even, exactly the p50 floor): idx = 0.5*19 = 9.5 -> average of
    # xs[9]=10 and xs[10]=11 -> 10.5
    assert percentiles(list(range(1, 21)), want=("p50",))["p50"] == pytest.approx(10.5)
    # n=21 (odd): idx = 0.5*20 = 10.0 exactly -> xs[10] = 11, the true middle
    assert percentiles(list(range(1, 22)), want=("p50",))["p50"] == pytest.approx(11.0)


def test_percentile_at_the_upper_extreme_for_each_floor():
    """Pin the interpolation formula at the high end (p90/p95/p99), each
    exactly at its own sample floor. Values independently verified against
    numpy.percentile(xs, q, method="linear") on the same linear sequences."""
    assert percentiles(list(range(1, 51)), want=("p90",))["p90"] == pytest.approx(45.1)
    assert percentiles(list(range(1, 81)), want=("p95",))["p95"] == pytest.approx(76.05)
    assert percentiles(list(range(1, 501)), want=("p99",))["p99"] == pytest.approx(495.01)


def test_percentiles_rejects_non_finite_values():
    """NEW-4: `want=("p50",)` only, so the p90/p95 sample-size floors (which
    this 32-element fixture is below) can't fire and mask the non-finite
    check — the only guard that can raise here is the one under test."""
    with pytest.raises(ValueError, match="non-finite"):
        percentiles([1.0, float("nan")] + list(range(30)), want=("p50",))
    with pytest.raises(ValueError, match="non-finite"):
        percentiles([1.0, float("inf")] + list(range(30)), want=("p50",))


def test_percentiles_rejects_unknown_want_name():
    with pytest.raises(ValueError):
        percentiles(list(range(30)), want=("p50", "p42"))


def test_percentiles_p50_matches_a_bootstraps_point_estimate_on_the_same_data():
    """C1: percentiles()['p50'] and every bootstrap's point estimate must be
    the exact same quantity, computed the exact same way, not two
    definitions of 'median' that happen to agree except at even n. Isolate
    median(xs) from bootstrap_median_diff by subtracting a constant-zero
    group of the same size, and cross-check against the stdlib's own
    statistics.median as an independent oracle."""
    rng = random.Random(777)
    xs = [rng.lognormvariate(math.log(100.0), 0.5) for _ in range(100)]  # n=100
    p50 = percentiles(xs, want=("p50",))["p50"]
    zeros = [0.0] * len(xs)
    res = bootstrap_median_diff(xs, zeros, iterations=2, seed=0)
    assert p50 == res["point"]
    assert p50 == pytest.approx(statistics.median(xs))


# ---------------------------------------------------------------------------
# ecdf
# ---------------------------------------------------------------------------


def test_ecdf_is_sorted_and_ends_at_one():
    xs, ys = ecdf([3.0, 1.0, 2.0])
    assert xs == [1.0, 2.0, 3.0]
    assert ys[-1] == pytest.approx(1.0)


def test_ecdf_step_values_are_evenly_spaced():
    _xs, ys = ecdf([10.0, 20.0, 30.0, 40.0])
    assert ys == [pytest.approx(v) for v in (0.25, 0.5, 0.75, 1.0)]


def test_ecdf_on_empty_list_raises_instead_of_dividing_by_zero():
    with pytest.raises(ValueError):
        ecdf([])


def test_ecdf_tie_behavior_is_one_point_per_observation_not_per_distinct_x():
    """M6: repeated values must not be deduplicated — this is a step-plot
    shape (one (x, y) pair per observation), so the CDF value AT a tied x
    is read from the LAST occurrence, not the first."""
    xs, ys = ecdf([1.0, 2.0, 2.0, 2.0, 5.0])
    assert xs == [1.0, 2.0, 2.0, 2.0, 5.0]
    assert ys == [pytest.approx(v) for v in (0.2, 0.4, 0.6, 0.8, 1.0)]


# ---------------------------------------------------------------------------
# module documentation (I1, I2)
# ---------------------------------------------------------------------------


def test_module_docstring_states_the_percentile_and_interval_conventions():
    """I1/I2: the interpolation method and its numpy equivalent, and the
    bootstrap interval method and its limitation, must be stated somewhere
    a reader will find them — not left to be inferred from the formula."""
    doc = (stats_module.__doc__ or "").lower()
    assert "linear" in doc
    assert "numpy" in doc
    assert "percentile-method" in doc or "percentile method" in doc
    assert "biased" in doc


# ---------------------------------------------------------------------------
# _percentile_interval (C2, I4, I5)
# ---------------------------------------------------------------------------


def test_percentile_interval_pins_exact_endpoint_indices():
    """C2/I4: alpha/2 vs alpha, and the '-1' on the upper index, are exactly
    the mutations no relational assertion (lo < point < hi, or comparing
    widths across alpha) can distinguish. `draws` is a literal,
    already-known (and deliberately unsorted, to also exercise the internal
    sort) list, so the expected lo/hi are pinned by hand, not re-derived
    from the formula under test."""
    draws = [8.0, 3.0, 1.0, 6.0, 2.0, 7.0, 5.0, 4.0]  # sorted: 1..8

    # alpha=0.5: lo index = int(0.25 * 8) = 2 -> sorted[2] = 3.0
    #            hi index = int(0.75 * 8) - 1 = 5 -> sorted[5] = 6.0
    assert _percentile_interval(draws, alpha=0.5) == (3.0, 6.0)

    # alpha=0.25: lo index = int(0.125 * 8) = 1 -> sorted[1] = 2.0
    #             hi index = int(0.875 * 8) - 1 = 6 -> sorted[6] = 7.0
    assert _percentile_interval(draws, alpha=0.25) == (2.0, 7.0)


def test_percentile_interval_rejects_an_infeasible_iterations_alpha_combination():
    """I5: with too few draws for how extreme alpha is, the naive index
    arithmetic inverts. This exact input previously produced lo=900.0,
    hi=1.0 (backwards) instead of raising."""
    draws = [1.0, 50.0, 900.0]  # 3 draws
    with pytest.raises(ValueError):
        _percentile_interval(draws, alpha=0.99)


def test_percentile_interval_single_draw_does_not_wrap_around():
    """A single draw and the default-ish alpha computes hi index = -1 via
    the raw formula, which Python would silently resolve to the last
    element instead of raising."""
    with pytest.raises(ValueError):
        _percentile_interval([42.0], alpha=0.05)


def test_bootstrap_median_diff_rejects_infeasible_iterations_alpha_instead_of_inverting():
    """I5, end to end: the reviewer's exact failing example. Arrays are
    padded to clear MIN_BOOTSTRAP_SAMPLES; the bug is triggered by
    `iterations`/`alpha`, not by sample size."""
    a = [1.0, 50.0, 900.0] * 7  # 21 elements
    b = [0.0] * 21
    with pytest.raises(ValueError):
        bootstrap_median_diff(a, b, iterations=3, alpha=0.99, seed=5)


def test_bootstrap_median_diff_matches_an_independent_replay_of_the_resample_loop():
    """C2, end to end: replay bootstrap_median_diff's documented algorithm
    by hand (same seed, same per-iteration draw order: len(a) indices for
    a, then len(b) indices for b) and assert the function's lo/hi equal the
    exact order statistics of that independently-replayed draw list. `a`
    and `b` have different lengths so a bug that resampled the wrong side
    to the wrong length (I7) would also break this replay match."""
    a = [
        10.0, 12.0, 15.0, 20.0, 22.0, 25.0, 30.0, 33.0, 40.0, 45.0,
        50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0,
    ]  # n=20
    b = [
        1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
        11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0,
        21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0,
    ]  # n=30
    iterations, seed, alpha = 40, 314, 0.5

    rng = random.Random(seed)
    replayed_draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        replayed_draws.append(statistics.median(ra) - statistics.median(rb))
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_median_diff(a, b, iterations=iterations, seed=seed, alpha=alpha)
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


# ---------------------------------------------------------------------------
# bootstrap_median_diff
# ---------------------------------------------------------------------------


def test_bootstrap_interval_brackets_a_known_difference():
    a = [100.0] * 50
    b = [70.0] * 50
    res = bootstrap_median_diff(a, b, iterations=500, seed=1)
    assert res["point"] == pytest.approx(30.0)
    assert res["lo"] <= 30.0 <= res["hi"]


def test_bootstrap_actually_resamples():
    """Constant inputs make every resample identical, so they cannot prove the
    bootstrap resamples at all — a version that skipped resampling entirely would
    pass. Spread inputs give the interval something to be wider than the point."""
    rng = random.Random(11)
    a = [rng.gauss(100.0, 15.0) for _ in range(60)]
    b = [rng.gauss(70.0, 15.0) for _ in range(60)]
    res = bootstrap_median_diff(a, b, iterations=800, seed=3)
    assert res["lo"] < res["point"] < res["hi"]
    assert res["lo"] > 0.0  # the real 30s gap survives resampling


def test_smaller_samples_give_wider_intervals():
    """The sample floor exists because small n buys a wide interval, not a wrong
    one. This pins that relationship instead of asserting it in prose."""
    rng = random.Random(12)
    big_a = [rng.gauss(100.0, 15.0) for _ in range(200)]
    big_b = [rng.gauss(70.0, 15.0) for _ in range(200)]
    small_a, small_b = big_a[:MIN_BOOTSTRAP_SAMPLES], big_b[:MIN_BOOTSTRAP_SAMPLES]
    wide = bootstrap_median_diff(small_a, small_b, iterations=800, seed=4)
    narrow = bootstrap_median_diff(big_a, big_b, iterations=800, seed=4)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])


def test_bootstrap_same_seed_is_reproducible_different_seed_is_not():
    """Published intervals must be reproducible from the recorded seed, so the
    same seed must give byte-identical output, and a different seed must
    actually move the resampled interval (not just be accepted as a no-op)."""
    rng = random.Random(20)
    a = [rng.gauss(100.0, 15.0) for _ in range(80)]
    b = [rng.gauss(70.0, 15.0) for _ in range(80)]
    r1 = bootstrap_median_diff(a, b, iterations=500, seed=42)
    r2 = bootstrap_median_diff(a, b, iterations=500, seed=42)
    assert r1 == r2

    r3 = bootstrap_median_diff(a, b, iterations=500, seed=43)
    assert r3 != r1


def test_bootstrap_wider_alpha_gives_narrower_interval():
    """alpha is the significance level (1 - confidence). A larger alpha demands
    less confidence, which must shrink the interval width for the same draws."""
    rng = random.Random(13)
    a = [rng.gauss(100.0, 15.0) for _ in range(80)]
    b = [rng.gauss(70.0, 15.0) for _ in range(80)]
    narrow_conf = bootstrap_median_diff(a, b, iterations=1000, seed=5, alpha=0.20)
    wide_conf = bootstrap_median_diff(a, b, iterations=1000, seed=5, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_bootstrap_median_diff_uses_median_not_mean_on_skewed_data():
    """C3: on symmetric (gaussian) fixtures mean ~= median, so a mutation
    swapping the median for the mean survives every gaussian/constant test
    in this file. Cold-start distributions are right-skewed — the spec's
    central premise, stated in bold — so only a right-skewed (lognormal)
    fixture can catch that mutation. The point estimate is an exact
    computation (no resampling noise), so this compares the two exactly."""
    rng = random.Random(556)
    a = [rng.lognormvariate(math.log(120.0), 0.5) for _ in range(60)]
    b = [rng.lognormvariate(math.log(90.0), 0.5) for _ in range(60)]
    expected_median_diff = statistics.median(a) - statistics.median(b)
    expected_mean_diff = statistics.mean(a) - statistics.mean(b)
    assert abs(expected_median_diff - expected_mean_diff) > 1.0  # fixture sanity

    res = bootstrap_median_diff(a, b, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median_diff)
    assert res["point"] != pytest.approx(expected_mean_diff, rel=1e-3)


def test_bootstrap_median_diff_rejects_below_the_bootstrap_sample_floor():
    """I3: the reviewer's exact failing example — a "95% CI" from n=1."""
    with pytest.raises(ValueError, match="at least"):
        bootstrap_median_diff([100.0], [70.0])


def test_bootstrap_median_diff_allows_exactly_at_the_bootstrap_sample_floor():
    a = [100.0] * MIN_BOOTSTRAP_SAMPLES
    b = [70.0] * MIN_BOOTSTRAP_SAMPLES
    res = bootstrap_median_diff(a, b, iterations=50, seed=1)
    assert res["point"] == pytest.approx(30.0)


def test_bootstrap_rejects_empty_sample():
    """NEW-3: `b` is padded above MIN_BOOTSTRAP_SAMPLES so only `a`'s
    emptiness can raise; `match=` pins which guard fired."""
    with pytest.raises(ValueError, match="empty"):
        bootstrap_median_diff([], [1.0] * MIN_BOOTSTRAP_SAMPLES)


def test_bootstrap_rejects_non_positive_iterations():
    """NEW-3: the original 2-element fixtures are below MIN_BOOTSTRAP_SAMPLES,
    so deleting the iterations check entirely still raises via the sample
    floor and this test can't tell the difference. Arrays are padded above
    the floor, and `match=` pins the iterations-specific message."""
    a = [1.0] * MIN_BOOTSTRAP_SAMPLES
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_median_diff(a, b, iterations=0)


def test_bootstrap_rejects_alpha_out_of_range():
    """NEW-3: same masking concern as the iterations test above."""
    a = [1.0] * MIN_BOOTSTRAP_SAMPLES
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_median_diff(a, b, alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_median_diff(a, b, alpha=1.0)


def test_bootstrap_rejects_non_finite_values():
    """NEW-4: `a` is padded to exactly MIN_BOOTSTRAP_SAMPLES so the floor
    can't fire instead of the non-finite check."""
    a = [1.0, float("nan")] + [2.0] * (MIN_BOOTSTRAP_SAMPLES - 2)
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_median_diff(a, b)


# ---------------------------------------------------------------------------
# bootstrap_contrast_difference
# ---------------------------------------------------------------------------


def test_contrast_difference_interval_brackets_a_known_gap():
    """Spread (non-constant) inputs so the interval can genuinely differ from
    the point estimate — constant inputs make every resample identical and
    cannot prove resampling happened."""
    rng = random.Random(21)
    a = [rng.gauss(100.0, 10.0) for _ in range(60)]
    b = [rng.gauss(70.0, 10.0) for _ in range(60)]
    c = [rng.gauss(60.0, 10.0) for _ in range(60)]
    expected_point = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    res = bootstrap_contrast_difference(a, b, c, iterations=600, seed=2)
    assert res["point"] == pytest.approx(expected_point)
    assert res["lo"] < res["point"] < res["hi"]


def test_contrast_difference_uses_median_not_mean_on_skewed_data():
    """C3: right-skewed fixture, applied to the ranking-claim function
    specifically — this is the entry point the spec singles out as
    deciding whether "compile cache mattered more" is a finding, so a
    silent mean-for-median swap here is the highest-stakes version of this
    bug in the module."""
    rng = random.Random(2024)
    a = [rng.lognormvariate(math.log(150.0), 0.6) for _ in range(30)]
    b = [rng.lognormvariate(math.log(100.0), 0.6) for _ in range(30)]
    c = [rng.lognormvariate(math.log(80.0), 0.6) for _ in range(30)]
    expected_median_contrast = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    expected_mean_contrast = (statistics.mean(a) - statistics.mean(b)) - (
        statistics.mean(b) - statistics.mean(c)
    )
    assert abs(expected_median_contrast - expected_mean_contrast) > 5.0  # fixture sanity

    res = bootstrap_contrast_difference(a, b, c, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median_contrast)
    assert res["point"] != pytest.approx(expected_mean_contrast, rel=1e-3)


def test_contrast_difference_rejects_empty_sample():
    with pytest.raises(ValueError, match="empty"):
        bootstrap_contrast_difference([], [1.0] * MIN_BOOTSTRAP_SAMPLES, [1.0] * MIN_BOOTSTRAP_SAMPLES)


def test_contrast_difference_rejects_below_the_bootstrap_sample_floor():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_contrast_difference([1.0] * 5, [1.0] * 5, [1.0] * 5)


def test_contrast_difference_same_seed_reproducible_different_seed_is_not():
    """I6: bootstrap_contrast_difference carries the ranking claim and was
    the least-tested of the four entry points — ignoring `seed` entirely
    previously survived the whole suite."""
    rng = random.Random(41)
    a = [rng.gauss(100.0, 15.0) for _ in range(40)]
    b = [rng.gauss(70.0, 15.0) for _ in range(40)]
    c = [rng.gauss(60.0, 15.0) for _ in range(40)]
    r1 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=9)
    r2 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=9)
    assert r1 == r2

    r3 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=10)
    assert r3 != r1


def test_contrast_difference_wider_alpha_gives_narrower_interval():
    """I6."""
    rng = random.Random(42)
    a = [rng.gauss(100.0, 15.0) for _ in range(40)]
    b = [rng.gauss(70.0, 15.0) for _ in range(40)]
    c = [rng.gauss(60.0, 15.0) for _ in range(40)]
    narrow_conf = bootstrap_contrast_difference(a, b, c, iterations=800, seed=6, alpha=0.20)
    wide_conf = bootstrap_contrast_difference(a, b, c, iterations=800, seed=6, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_contrast_difference_handles_unequal_length_arms():
    """I7: real arms have unequal n after failure exclusion. A version that
    resampled b or c to len(a), or used a hardcoded resample length, would
    still run without crashing — only the point estimate's agreement with
    an independent computation, and the interval's sanity, would be off."""
    rng = random.Random(43)
    a = [rng.gauss(100.0, 10.0) for _ in range(20)]
    b = [rng.gauss(70.0, 10.0) for _ in range(35)]
    c = [rng.gauss(60.0, 10.0) for _ in range(50)]
    expected_point = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    res = bootstrap_contrast_difference(a, b, c, iterations=300, seed=1)
    assert res["point"] == pytest.approx(expected_point)
    assert res["lo"] < res["point"] < res["hi"]


def test_contrast_difference_matches_an_independent_replay_of_the_resample_loop():
    """I7/C2, end to end: the point estimate alone can't catch a wrong
    resample length — it's computed from the original a/b/c, not the
    resampled draws — so a version that resampled b or c to len(a) instead
    of their own length would still pass the point-estimate check above.
    Replay the documented algorithm by hand (same seed, same per-iteration
    draw order: len(a), then len(b), then len(c)) with three different
    lengths, and assert the function's lo/hi equal the exact order
    statistics of that independently-replayed draw list."""
    rng = random.Random(44)
    a = [rng.gauss(100.0, 10.0) for _ in range(20)]
    b = [rng.gauss(70.0, 10.0) for _ in range(33)]
    c = [rng.gauss(60.0, 10.0) for _ in range(47)]
    iterations, seed, alpha = 50, 315, 0.5

    replay_rng = random.Random(seed)
    replayed_draws = []
    for _ in range(iterations):
        ra = [a[replay_rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[replay_rng.randrange(len(b))] for _ in range(len(b))]
        rc = [c[replay_rng.randrange(len(c))] for _ in range(len(c))]
        replayed_draws.append(
            (statistics.median(ra) - statistics.median(rb))
            - (statistics.median(rb) - statistics.median(rc))
        )
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_contrast_difference(a, b, c, iterations=iterations, seed=seed, alpha=alpha)
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


# ---------------------------------------------------------------------------
# within_host_triples
# ---------------------------------------------------------------------------


def test_within_host_triples_keeps_only_complete_same_host_groups():
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
        {"triple_index": 1, "arm": "A", "host_id": "h1"},
        {"triple_index": 1, "arm": "B", "host_id": "h2"},
        {"triple_index": 1, "arm": "C", "host_id": "h1"},
    ]
    kept = within_host_triples(rows, arms=("A", "B", "C"))
    assert [t[0]["triple_index"] for t in kept] == [0]


def test_within_host_triples_rejects_wrong_arm_count():
    """Two runs instead of three: incomplete triple, must not be kept."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_duplicate_arm():
    """Three runs, right count, but arm B is missing and A is duplicated —
    the set of arms present doesn't match the required set."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_mixed_hosts():
    """All three arms present, correct count, but not all on the same host."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h2"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_an_extra_duplicate_arm():
    """NEW-5: a set comparison would wrongly accept this group — the SET of
    arms present is {A, B, C}, matching `arms` — but there are 4 rows, not
    3 (A appears twice). This is the exact multiset-vs-set distinction the
    docstring cites to justify dropping the separate arm-count check (M2),
    so it should be the one thing that is actually pinned. The existing
    rejection tests ([A, A, C] and [A, B]) both also fail a set comparison,
    so they can't tell a multiset check from a set check apart."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_output_is_sorted_by_triple_index():
    """M8: rows arrive with triple 2 before triple 0 before triple 1; the
    kept groups must come back ordered by triple_index, not input order."""
    rows = []
    for idx in (2, 0, 1):
        rows.extend(
            [
                {"triple_index": idx, "arm": "A", "host_id": f"h{idx}"},
                {"triple_index": idx, "arm": "B", "host_id": f"h{idx}"},
                {"triple_index": idx, "arm": "C", "host_id": f"h{idx}"},
            ]
        )
    kept = within_host_triples(rows, arms=("A", "B", "C"))
    assert [t[0]["triple_index"] for t in kept] == [0, 1, 2]


# ---------------------------------------------------------------------------
# bootstrap_paired_median_diff / bootstrap_paired_contrast_difference
#
# within_host_triples produces *paired* data: the three runs in a triple are
# correlated (same host), not independent draws. bootstrap_median_diff and
# bootstrap_contrast_difference resample arms independently, which is correct
# for the pooled, unpaired analysis but wrong here — it would silently
# reintroduce the host confound the pairing exists to remove. These two
# functions resample whole triples with replacement instead, and report the
# median of per-triple deltas rather than a difference of two medians.
# ---------------------------------------------------------------------------


def test_paired_median_diff_point_is_median_of_per_triple_deltas():
    # 20 triples with delta 30.0, one outlier triple with delta 999.0.
    # median of 21 values, 20 of which are 30.0, is 30.0.
    deltas = [30.0] * 20 + [999.0]
    triples = _value_triples(deltas)
    res = bootstrap_paired_median_diff(triples, "A", "B", iterations=50, seed=1)
    assert res["point"] == pytest.approx(statistics.median(deltas))


def test_paired_contrast_difference_point_is_median_of_per_triple_contrasts():
    # Under the B=C=0 construction, (A-B)-(B-C) reduces to A.
    contrasts = [20.0] * 20 + [-500.0]
    triples = _value_triples(contrasts)
    res = bootstrap_paired_contrast_difference(triples, iterations=50, seed=1)
    assert res["point"] == pytest.approx(statistics.median(contrasts))


def test_paired_contrast_difference_uses_the_correct_contrast_formula():
    """NEW-1 (critical): every other test of this statistic uses
    `_value_triples`, whose B=C=0 construction makes (A-B)-(B-C) and
    (A-B)-(C-B) collapse to the same value (A), so a sign-flip mutation on
    the second term is invisible to them. B=70, C=60 here are distinct and
    non-zero, so the correct formula (A-B)-(B-C) = 30-10 = 20 is
    distinguishable from the wrong one (A-B)-(C-B) = 30-(-10) = 40, which
    is also just A-C."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    res = bootstrap_paired_contrast_difference(triples, iterations=10, seed=1)
    assert res["point"] == pytest.approx(20.0)


def test_paired_median_diff_accepts_a_callable_value_extractor():
    """value can be a key name (the default) or a callable — both t_total and
    t_weights get this treatment, so it must not be hardcoded to one field."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    res = bootstrap_paired_median_diff(
        triples, "A", "B", value=lambda r: r["t_total"] * 2, iterations=10, seed=1
    )
    assert res["point"] == pytest.approx(60.0)  # 2 * (100 - 70)


def test_paired_median_diff_accepts_a_different_key_name():
    """M4: `value`'s string-key branch was only ever exercised with
    't_total' — the docstring promises t_weights works too."""
    triples = _const_triples(20, 100.0, 70.0, 60.0, field="t_weights")
    res = bootstrap_paired_median_diff(
        triples, "A", "B", value="t_weights", iterations=20, seed=1
    )
    assert res["point"] == pytest.approx(30.0)


def test_paired_bootstrap_resamples_whole_triples_and_an_outlier_widens_it():
    """The unit of resampling is the triple, not the delta list flattened by
    coincidence. 21 constant-delta triples give a degenerate interval on
    their own; replacing a third of them with a much larger outlier delta
    must widen the interval, because an outlier triple can now be drawn
    0, 1, 2... times per resample. A version that dropped the outlier's
    leverage (e.g. sampling without replacement, or capping each triple to
    appear once) would keep this degenerate."""
    without_outlier = _value_triples([30.0] * 21)
    res_without = bootstrap_paired_median_diff(without_outlier, "A", "B", iterations=3000, seed=9)
    assert res_without["lo"] == res_without["hi"] == pytest.approx(30.0)

    with_outlier = _value_triples([30.0] * 14 + [300.0] * 7)
    res_with = bootstrap_paired_median_diff(with_outlier, "A", "B", iterations=3000, seed=9)
    assert (res_with["hi"] - res_with["lo"]) > 0.0


def test_paired_median_diff_matches_an_independent_replay_of_the_resample_loop():
    """NEW-2, mirroring the unpaired replay tests: the same reasoning
    ('a point estimate alone cannot catch a wrong resample size') applies
    to the paired engine, which is exactly where the "resample the whole
    triple" claim lives — and it was not covered. `for _ in range(1)`
    (resample of size 1) and `rng.randrange(n - 1)` (the last triple never
    drawn) both previously passed the whole suite. Replay the documented
    algorithm by hand (same seed, one randrange draw per position in the
    deltas list) and assert lo/hi equal the exact order statistics of the
    independently-replayed draws."""
    rng = random.Random(50)
    deltas = [rng.gauss(30.0, 15.0) for _ in range(25)]
    triples = _value_triples(deltas)
    iterations, seed, alpha = 40, 316, 0.5

    replay_rng = random.Random(seed)
    n = len(deltas)
    replayed_draws = []
    for _ in range(iterations):
        resample = [deltas[replay_rng.randrange(n)] for _ in range(n)]
        replayed_draws.append(statistics.median(resample))
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_paired_median_diff(
        triples, "A", "B", iterations=iterations, seed=seed, alpha=alpha
    )
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


def test_paired_median_diff_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(30)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    r1 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    r2 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    assert r1 == r2

    r3 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=12)
    assert r3 != r1


def test_paired_median_diff_wider_alpha_gives_narrower_interval():
    rng = random.Random(31)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    narrow_conf = bootstrap_paired_median_diff(
        triples, "A", "B", iterations=800, seed=15, alpha=0.20
    )
    wide_conf = bootstrap_paired_median_diff(triples, "A", "B", iterations=800, seed=15, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_paired_median_diff_uses_median_not_mean_on_skewed_data():
    """C3, paired version: lognormal per-triple deltas via the B=C=0
    construction, so the delta list is directly a right-skewed sample."""
    rng = random.Random(42)
    deltas = [rng.lognormvariate(math.log(50.0), 1.0) for _ in range(25)]
    expected_median = statistics.median(deltas)
    expected_mean = statistics.mean(deltas)
    assert abs(expected_median - expected_mean) > 5.0  # fixture sanity

    triples = _value_triples(deltas)
    res = bootstrap_paired_median_diff(triples, "A", "B", iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median)
    assert res["point"] != pytest.approx(expected_mean, rel=1e-3)


def test_paired_contrast_difference_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(32)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    r1 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    r2 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    assert r1 == r2

    r3 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=17)
    assert r3 != r1


def test_paired_contrast_difference_wider_alpha_gives_narrower_interval():
    rng = random.Random(33)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    narrow_conf = bootstrap_paired_contrast_difference(
        triples, iterations=800, seed=18, alpha=0.20
    )
    wide_conf = bootstrap_paired_contrast_difference(triples, iterations=800, seed=18, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_paired_contrast_difference_uses_median_not_mean_on_skewed_data():
    """C3, paired contrast version."""
    rng = random.Random(43)
    contrasts = [rng.lognormvariate(math.log(50.0), 1.0) for _ in range(25)]
    expected_median = statistics.median(contrasts)
    expected_mean = statistics.mean(contrasts)
    assert abs(expected_median - expected_mean) > 5.0  # fixture sanity

    triples = _value_triples(contrasts)
    res = bootstrap_paired_contrast_difference(triples, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median)
    assert res["point"] != pytest.approx(expected_mean, rel=1e-3)


def test_paired_interval_is_tighter_than_unpaired_when_host_effect_dominates():
    """The spec's own claim: disagreement between the paired and unpaired
    estimates is itself a finding, so the two must actually be *capable* of
    disagreeing. Build triples where a large per-host offset is common to
    all three arms within a triple (so it cancels in the paired delta) but
    is not accounted for by the unpaired bootstrap, which pools all A-values
    and all B-values and resamples them independently of which host/triple
    they came from. If a paired function were implemented by just calling
    the unpaired one on the pooled per-arm lists (losing the pairing), this
    assertion would fail: the widths would come out equal."""
    rng = random.Random(99)
    triples = []
    a_vals, b_vals = [], []
    for i in range(30):
        host_offset = rng.gauss(0.0, 50.0)  # dominant, shared within a triple
        a = 100.0 + host_offset + rng.gauss(0.0, 2.0)
        b = 70.0 + host_offset + rng.gauss(0.0, 2.0)
        c = 60.0 + host_offset + rng.gauss(0.0, 2.0)
        triples.append(_triple(i, f"h{i}", a, b, c))
        a_vals.append(a)
        b_vals.append(b)

    paired = bootstrap_paired_median_diff(triples, "A", "B", iterations=1500, seed=7)
    unpaired = bootstrap_median_diff(a_vals, b_vals, iterations=1500, seed=7)

    paired_width = paired["hi"] - paired["lo"]
    unpaired_width = unpaired["hi"] - unpaired["lo"]
    assert paired_width < unpaired_width


def test_paired_median_diff_rejects_below_the_bootstrap_sample_floor():
    """I3: within-host triples are explicitly expected to be a minority of
    the data, so this is the path most likely to be called with too few
    units."""
    triples = _const_triples(5, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_median_diff(triples, "A", "B")


def test_paired_contrast_difference_rejects_below_the_bootstrap_sample_floor():
    triples = _const_triples(5, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_median_diff_rejects_empty_triples():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_median_diff([], "A", "B")


def test_paired_contrast_difference_rejects_empty_triples():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_contrast_difference([])


def test_paired_median_diff_rejects_a_triple_missing_an_arm():
    """19 well-formed triples clear MIN_BOOTSTRAP_SAMPLES; the 20th is
    missing arm B, which is what this test actually exercises."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [{"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0}]
    ]
    with pytest.raises(ValueError, match="missing arm"):
        bootstrap_paired_median_diff(triples, "A", "B")


def test_paired_contrast_difference_rejects_a_triple_missing_an_arm():
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 70.0},
        ]
    ]
    with pytest.raises(ValueError, match="missing arm"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_finite_values():
    """19 well-formed triples clear the floor; the 20th carries the NaN
    this test is actually checking for."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [_triple(19, "h19", float("nan"), 70.0, 60.0)]
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_paired_median_diff(triples, "A", "B")
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_positive_iterations():
    """NEW-3 (same masking class, applied here proactively): a 1-triple
    fixture is below MIN_BOOTSTRAP_SAMPLES, so deleting the iterations
    check entirely would still raise via the floor and this test couldn't
    tell. 20 triples clear the floor; `match=` pins the right message."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_paired_median_diff(triples, "A", "B", iterations=0)
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_paired_contrast_difference(triples, iterations=0)


def test_paired_functions_reject_alpha_out_of_range():
    """NEW-3: same masking concern as the iterations test above."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_median_diff(triples, "A", "B", alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_contrast_difference(triples, alpha=1.0)


def test_paired_median_diff_checks_alpha_before_triples_count():
    """M7: cheap parameter checks (iterations, alpha) must run before the
    triples-count / per-triple delta work, so a caller passing both a bad
    alpha and too few (here, zero) triples gets the alpha error, not a
    "not enough triples" error that hides it."""
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_median_diff([], "A", "B", alpha=1.5)


def test_paired_contrast_difference_checks_alpha_before_triples_count():
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_contrast_difference([], alpha=1.5)


def test_paired_median_diff_rejects_a_triple_with_a_duplicate_arm():
    """Two rows both claim arm A; C is present too, so a missing-arm check
    alone would not catch this — the ambiguous duplicate must be its own
    rejection, not silently resolved by whichever row was written last.
    19 well-formed triples clear the floor; the 20th is the duplicate."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 999.0},
            {"triple_index": 19, "arm": "C", "host_id": "h19", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError, match="duplicate arm"):
        bootstrap_paired_median_diff(triples, "A", "C")


def test_paired_contrast_difference_rejects_a_triple_with_a_duplicate_arm():
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 999.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 70.0},
            {"triple_index": 19, "arm": "C", "host_id": "h19", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError, match="duplicate arm"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_contrast_difference_rejects_wrong_arms_length():
    """The contrast (A-B)-(B-C) is only defined for exactly three arms. A
    2-tuple or 4-tuple must be rejected explicitly rather than crashing on
    an IndexError deep inside the per-triple delta computation."""
    triples = [_triple(0, "h1", 100.0, 70.0, 60.0)]
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B"))
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B", "C", "D"))


def test_paired_contrast_difference_rejects_a_padded_duplicate_arms_tuple():
    """A length check is not fully subsumed by a distinctness check: a
    4-tuple with one internal duplicate (A, B, B, C) has only 3 unique
    values, so `len(set(arms)) != 3` alone would wrongly accept it — the
    length must be checked too. 20 triples clear MIN_BOOTSTRAP_SAMPLES so
    the floor check can't mask this guard the way a 1-triple fixture would."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B", "B", "C"))


def test_paired_median_diff_rejects_non_distinct_arms():
    """M5: arm_a == arm_b must be rejected, not silently returned as a
    'point': 0.0 confidence interval on nothing. Uses enough triples to
    clear MIN_BOOTSTRAP_SAMPLES, so the floor check can't mask this guard —
    a single triple would raise for the wrong reason and this test would
    pass even with the arm-distinctness guard deleted."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "A")


def test_paired_contrast_difference_rejects_non_distinct_arms():
    """M5. Same floor-masking concern as the median-diff version above."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "A", "A"))
