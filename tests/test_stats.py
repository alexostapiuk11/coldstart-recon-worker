import random
import statistics

import pytest

from coldstart.analysis.stats import (
    MIN_SAMPLES,
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    ecdf,
    percentiles,
    within_host_triples,
)

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


def test_p50_index_at_the_sample_floor_even_and_odd_n():
    """Pin the nearest-rank interpolation formula at p50, for both an even and
    an odd sample count, rather than re-deriving the same formula in the test."""
    # n=20 (even, exactly the p50 floor): round(0.5 * 19) == 10 -> xs[10] == 11
    assert percentiles(list(range(1, 21)), want=("p50",))["p50"] == 11
    # n=21 (odd): round(0.5 * 20) == 10 -> xs[10] == 11, the true middle value
    assert percentiles(list(range(1, 22)), want=("p50",))["p50"] == 11


def test_percentile_index_at_the_upper_extreme_for_each_floor():
    """Pin the index formula at the high end (p90/p95/p99), each exactly at its
    own sample floor, using a simple linear sequence so the expected value is
    obvious by construction."""
    assert percentiles(list(range(1, 51)), want=("p90",))["p90"] == 45
    assert percentiles(list(range(1, 81)), want=("p95",))["p95"] == 76
    assert percentiles(list(range(1, 501)), want=("p99",))["p99"] == 495


def test_percentiles_rejects_non_finite_values():
    with pytest.raises(ValueError):
        percentiles([1.0, float("nan")] + list(range(30)))
    with pytest.raises(ValueError):
        percentiles([1.0, float("inf")] + list(range(30)))


def test_percentiles_rejects_unknown_want_name():
    with pytest.raises(ValueError):
        percentiles(list(range(30)), want=("p50", "p42"))


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
    small_a, small_b = big_a[:12], big_b[:12]
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


def test_bootstrap_rejects_empty_sample():
    with pytest.raises(ValueError):
        bootstrap_median_diff([], [1.0, 2.0])


def test_bootstrap_rejects_non_positive_iterations():
    with pytest.raises(ValueError):
        bootstrap_median_diff([1.0, 2.0], [3.0, 4.0], iterations=0)


def test_bootstrap_rejects_alpha_out_of_range():
    with pytest.raises(ValueError):
        bootstrap_median_diff([1.0, 2.0], [3.0, 4.0], alpha=0.0)
    with pytest.raises(ValueError):
        bootstrap_median_diff([1.0, 2.0], [3.0, 4.0], alpha=1.0)


def test_bootstrap_rejects_non_finite_values():
    with pytest.raises(ValueError):
        bootstrap_median_diff([1.0, float("nan")], [3.0, 4.0])


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


def test_contrast_difference_rejects_empty_sample():
    with pytest.raises(ValueError):
        bootstrap_contrast_difference([], [1.0], [1.0])


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
