import random
import statistics

import pytest

from coldstart.analysis.stats import (
    MIN_SAMPLES,
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_contrast_difference,
    bootstrap_paired_median_diff,
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


def _triple(idx, host, a, b, c, field="t_total"):
    return [
        {"triple_index": idx, "arm": "A", "host_id": host, field: a},
        {"triple_index": idx, "arm": "B", "host_id": host, field: b},
        {"triple_index": idx, "arm": "C", "host_id": host, field: c},
    ]


def test_paired_median_diff_point_is_median_of_per_triple_deltas():
    # A-B deltas: 30, 20, 70 -> median 30
    triples = [
        _triple(0, "h1", 100.0, 70.0, 60.0),
        _triple(1, "h2", 110.0, 90.0, 50.0),
        _triple(2, "h3", 130.0, 60.0, 40.0),
    ]
    res = bootstrap_paired_median_diff(triples, "A", "B", iterations=200, seed=1)
    assert res["point"] == pytest.approx(30.0)


def test_paired_contrast_difference_point_is_median_of_per_triple_contrasts():
    # (A-B)-(B-C) per triple: 20, -20, 50 -> median 20
    triples = [
        _triple(0, "h1", 100.0, 70.0, 60.0),
        _triple(1, "h2", 110.0, 90.0, 50.0),
        _triple(2, "h3", 130.0, 60.0, 40.0),
    ]
    res = bootstrap_paired_contrast_difference(triples, iterations=200, seed=1)
    assert res["point"] == pytest.approx(20.0)


def test_paired_median_diff_accepts_a_callable_value_extractor():
    """value can be a key name (the default) or a callable — both t_total and
    t_weights get this treatment, so it must not be hardcoded to one field."""
    triples = [_triple(0, "h1", 100.0, 70.0, 60.0)]
    res = bootstrap_paired_median_diff(
        triples, "A", "B", value=lambda r: r["t_total"] * 2, iterations=10, seed=1
    )
    assert res["point"] == pytest.approx(60.0)  # (200 - 140)


def test_paired_bootstrap_resamples_whole_triples_and_an_outlier_widens_it():
    """The unit of resampling is the triple, not the delta list flattened by
    coincidence. Five triples share the same delta (a degenerate interval on
    their own); adding one outlier triple must widen the interval, because
    the outlier can now be drawn 0, 1, 2... times per resample. A version
    that dropped the outlier's leverage (e.g. sampling without replacement,
    or capping each triple to appear once) would keep this degenerate."""
    normal = [_triple(i, f"h{i}", 100.0, 70.0, 60.0) for i in range(5)]  # delta 30
    without_outlier = bootstrap_paired_median_diff(normal, "A", "B", iterations=3000, seed=9)
    assert without_outlier["lo"] == without_outlier["hi"] == pytest.approx(30.0)

    with_outlier = normal + [_triple(5, "h5", 300.0, 0.0, 0.0)]  # delta 300
    res = bootstrap_paired_median_diff(with_outlier, "A", "B", iterations=3000, seed=9)
    assert (res["hi"] - res["lo"]) > 0.0


def test_paired_median_diff_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(30)
    triples = [
        _triple(i, f"h{i}", 100.0 + rng.gauss(0, 10), 70.0 + rng.gauss(0, 10), 60.0)
        for i in range(40)
    ]
    r1 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    r2 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    assert r1 == r2

    r3 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=12)
    assert r3 != r1


def test_paired_median_diff_wider_alpha_gives_narrower_interval():
    rng = random.Random(31)
    triples = [
        _triple(i, f"h{i}", 100.0 + rng.gauss(0, 10), 70.0 + rng.gauss(0, 10), 60.0)
        for i in range(40)
    ]
    narrow_conf = bootstrap_paired_median_diff(triples, "A", "B", iterations=800, seed=15, alpha=0.20)
    wide_conf = bootstrap_paired_median_diff(triples, "A", "B", iterations=800, seed=15, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_paired_contrast_difference_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(32)
    triples = [
        _triple(
            i,
            f"h{i}",
            100.0 + rng.gauss(0, 10),
            70.0 + rng.gauss(0, 10),
            60.0 + rng.gauss(0, 10),
        )
        for i in range(40)
    ]
    r1 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    r2 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    assert r1 == r2

    r3 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=17)
    assert r3 != r1


def test_paired_contrast_difference_wider_alpha_gives_narrower_interval():
    rng = random.Random(33)
    triples = [
        _triple(
            i,
            f"h{i}",
            100.0 + rng.gauss(0, 10),
            70.0 + rng.gauss(0, 10),
            60.0 + rng.gauss(0, 10),
        )
        for i in range(40)
    ]
    narrow_conf = bootstrap_paired_contrast_difference(triples, iterations=800, seed=18, alpha=0.20)
    wide_conf = bootstrap_paired_contrast_difference(triples, iterations=800, seed=18, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


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


def test_paired_median_diff_rejects_empty_triples():
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff([], "A", "B")


def test_paired_contrast_difference_rejects_empty_triples():
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference([])


def test_paired_median_diff_rejects_a_triple_missing_an_arm():
    triples = [[{"triple_index": 0, "arm": "A", "host_id": "h1", "t_total": 100.0}]]
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "B")


def test_paired_contrast_difference_rejects_a_triple_missing_an_arm():
    triples = [
        [
            {"triple_index": 0, "arm": "A", "host_id": "h1", "t_total": 100.0},
            {"triple_index": 0, "arm": "B", "host_id": "h1", "t_total": 70.0},
        ]
    ]
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_finite_values():
    triples = [_triple(0, "h1", float("nan"), 70.0, 60.0)]
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "B")
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_positive_iterations():
    triples = [_triple(0, "h1", 100.0, 70.0, 60.0)]
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "B", iterations=0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, iterations=0)


def test_paired_functions_reject_alpha_out_of_range():
    triples = [_triple(0, "h1", 100.0, 70.0, 60.0)]
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "B", alpha=0.0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, alpha=1.0)


def test_paired_median_diff_rejects_a_triple_with_a_duplicate_arm():
    """Two rows both claim arm A; C is present too, so a missing-arm check
    alone would not catch this — the ambiguous duplicate must be its own
    rejection, not silently resolved by whichever row was written last."""
    triples = [
        [
            {"triple_index": 0, "arm": "A", "host_id": "h1", "t_total": 100.0},
            {"triple_index": 0, "arm": "A", "host_id": "h1", "t_total": 999.0},
            {"triple_index": 0, "arm": "C", "host_id": "h1", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "C")


def test_paired_contrast_difference_rejects_a_triple_with_a_duplicate_arm():
    triples = [
        [
            {"triple_index": 0, "arm": "A", "host_id": "h1", "t_total": 100.0},
            {"triple_index": 0, "arm": "B", "host_id": "h1", "t_total": 999.0},
            {"triple_index": 0, "arm": "B", "host_id": "h1", "t_total": 70.0},
            {"triple_index": 0, "arm": "C", "host_id": "h1", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError):
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
