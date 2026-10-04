import subprocess
import sys
from pathlib import Path

import pytest

from autoscale.validation_band import BandBin, Bin, band, compare, trajectory

REPO = Path(__file__).resolve().parents[1]
# The comparison threshold these tests hold compare() to. Chosen here, not
# imported from any artifact: each artifact pre-registers its own.
MIN_COMPARED = 5


def _schedule(bins):
    """20 requests per 10 s bin, spaced 0.5 s: exactly the p50 sample floor."""
    return tuple(i * 0.5 for i in range(20 * bins))


def _trajectory(latency, bins=6):
    schedule = _schedule(bins)
    lat = latency if isinstance(latency, list) else [latency] * len(schedule)
    return trajectory(schedule, lat, until=10.0 * bins, bin_seconds=10.0)


def _pred(p50s):
    return [Bin(i * 10.0, (i + 1) * 10.0, 20, 20, 0, p, "ok") for i, p in enumerate(p50s)]


def _band(n, lo=1.0, hi=1.2, status="ok"):
    return [BandBin(i * 10.0, (i + 1) * 10.0, lo, hi, status) for i in range(n)]


# ---- the boundary this module exists for -----------------------------------

def test_importing_it_does_not_load_artifact_one():
    """Artifact 4's placement simulator imports this module across a
    TRANSITIVE boundary against `coldstart`. `autoscale.sim` reaches
    `coldstart` through `autoscale.coldstart_ecdf`, so one convenience import
    of it here would end the arrangement silently -- and
    tests/test_autoscale_boundary.py checks direct imports only, so it would
    not notice. A fresh interpreter, because this test process has already
    loaded `coldstart` through other test modules."""
    code = (
        "import sys; import autoscale.validation_band; "
        "print(sorted(m for m in sys.modules if m == 'coldstart' or m.startswith('coldstart.')"
        " or m in ('autoscale.sim', 'autoscale.coldstart_ecdf')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", (
        f"importing autoscale.validation_band loads {out.stdout.strip()}; artifact 4 "
        "imports this module precisely because it must not pull in artifact 1's package, "
        "and `autoscale.sim` / `autoscale.coldstart_ecdf` are the road to it"
    )


# ---- trajectory -------------------------------------------------------------

def test_a_bin_with_enough_completed_requests_reports_its_median():
    [first, second] = trajectory(_schedule(2), [1.0] * 40, until=20.0, bin_seconds=10.0)
    assert (first.status, first.p50, first.requests) == ("ok", 1.0, 20)
    assert second.status == "ok"


def test_a_bin_with_any_unfinished_request_is_censored_not_summarised():
    """The median of the requests that FINISHED, in a bin where some did not,
    is biased low by exactly the slow ones that are missing."""
    lat = [1.0] * 40
    lat[5] = None
    first, _ = trajectory(_schedule(2), lat, until=20.0, bin_seconds=10.0)
    assert first.status == "censored" and first.p50 is None and first.unfinished == 1


def test_a_bin_below_the_sample_floor_is_thin():
    first, _ = trajectory(_schedule(2)[:19] + (15.0,), [1.0] * 20, until=20.0, bin_seconds=10.0)
    assert first.status == "thin" and first.p50 is None


def test_an_empty_bin_is_empty():
    bins = trajectory([15.0] * 20, [1.0] * 20, until=20.0, bin_seconds=10.0)
    assert bins[0].status == "empty"


def test_an_arrival_at_the_window_edge_lands_in_the_last_bin():
    bins = trajectory([20.0], [1.0], until=20.0, bin_seconds=10.0)
    assert bins[-1].requests == 1


@pytest.mark.parametrize("t", [-5.0, 20.5, float("nan")])
def test_an_arrival_outside_the_window_is_refused(t):
    """A negative arrival would index the bin list from the END and land in
    the last bin; one past `until` would be clamped into it. Either way a
    request is reported in a bin it never arrived in."""
    with pytest.raises(ValueError, match="window"):
        trajectory([1.0] * 19 + [t], [1.0] * 20, until=20.0, bin_seconds=10.0)


@pytest.mark.parametrize("lat", [-1.0, float("nan"), float("inf")])
def test_a_latency_that_is_not_a_duration_is_refused(lat):
    with pytest.raises(ValueError, match="latenc"):
        trajectory([1.0] * 20, [1.0] * 19 + [lat], until=20.0, bin_seconds=10.0)


@pytest.mark.parametrize("values, p50", [
    ([1.0] * 19 + [100.0], 1.0),   # mean 5.95, max 100.0: only a median gives 1.0
    ([1.0] * 10 + [3.0] * 10, 2.0),  # even count: interpolated, not min or nearest rank
])
def test_the_per_bin_statistic_is_the_interpolated_median(values, p50):
    [only] = trajectory([float(i) * 0.5 for i in range(20)], values, until=10.0, bin_seconds=10.0)
    assert only.p50 == p50


def test_a_window_that_is_not_a_whole_number_of_bins_ends_in_a_partial_bin():
    """Merging the last 5 s into its neighbour would make that bin 15 s wide;
    leaving its end at 70 would claim 5 s the run never covered."""
    bins = trajectory([62.0], [1.0], until=65.0, bin_seconds=10.0)
    assert len(bins) == 7 and bins[-1].end == 65.0 and bins[6].requests == 1


def test_the_bin_width_has_no_default():
    """Each artifact pre-registers its own. A default here would let one
    artifact silently run on another's."""
    with pytest.raises(TypeError):
        trajectory([1.0], [1.0], until=20.0)


# ---- band -------------------------------------------------------------------

def test_the_band_is_the_spread_of_the_repeats():
    b = band([_trajectory(1.0), _trajectory(1.2), _trajectory(1.1)], min_repeats=3)
    assert all(x.status == "ok" for x in b)
    assert (b[0].lo, b[0].hi) == pytest.approx((1.0, 1.2))


def test_fewer_repeats_than_required_is_refused():
    with pytest.raises(ValueError, match="at least 3"):
        band([_trajectory(1.0), _trajectory(1.1)], min_repeats=3)


def test_a_band_of_one_run_is_refused_whatever_the_caller_asks_for():
    """One run has zero spread, so the band would hold a model to that run's
    noise exactly."""
    with pytest.raises(ValueError, match="at least two"):
        band([_trajectory(1.0)], min_repeats=1)


def test_repeats_binned_differently_are_refused():
    with pytest.raises(ValueError, match="edges"):
        band([_trajectory(1.0), _trajectory(1.0, bins=5), _trajectory(1.0)], min_repeats=3)


def test_a_bin_the_system_itself_disagrees_about_is_unstable():
    lat = [1.0] * 120
    lat[3] = None
    b = band([_trajectory(1.0), _trajectory(1.1), _trajectory(lat)], min_repeats=3)
    assert b[0].status == "unstable"


def test_a_column_no_repeat_could_summarise_is_insufficient_not_unstable():
    """Thin on every repeat is too few requests, not a system disagreeing
    with itself; calling it unstable would misreport why it was excluded."""
    thin = trajectory([0.0] * 10, [1.0] * 10, until=10.0, bin_seconds=10.0)
    [only] = band([thin, thin, thin], min_repeats=3)
    assert only.status == "insufficient"


# ---- compare ----------------------------------------------------------------

def _cmp(pred, band_bins, *, frac=0.5, tol=0.0, min_bins=MIN_COMPARED):
    """compare() with this file's choices spelled out. No artifact's values:
    each artifact pre-registers its own."""
    return compare(pred, band_bins, min_compared_bins=min_bins, max_miss_fraction=frac,
                   edge_tolerance_seconds=tol)


def _censored_pred(start):
    return Bin(start, start + 10.0, 20, 15, 5, None, "censored")


def _censored_band(start):
    return BandBin(start, start + 10.0, None, None, "censored")


def test_every_bin_inside_the_band_passes():
    v = _cmp(_pred([1.1] * 6), _band(6))
    assert v.outcome == "passed" and v.compared == 6 and v.max_miss_seconds == 0.0


def test_a_miss_is_reported_with_its_magnitude():
    v = _cmp(_pred([1.1] * 5 + [1.5]), _band(6), frac=0.0)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.3)
    assert v.bins[-1].verdict == "outside"


@pytest.mark.parametrize("p50", [1.0, 1.2])
def test_a_prediction_on_a_band_edge_is_inside(p50):
    """The band is closed: the repeats themselves reached that value."""
    v = _cmp(_pred([1.1] * 5 + [p50]), _band(6), frac=0.0)
    assert v.outcome == "passed" and v.bins[-1].verdict == "inside"


def test_exactly_half_missing_passes():
    """'No more than half': the boundary is on the passing side."""
    v = _cmp(_pred([1.1] * 5 + [1.5] * 5), _band(10))
    assert (v.outcome, v.compared, v.agreeing) == ("passed", 10, 5)


def test_one_more_than_half_missing_fails():
    v = _cmp(_pred([1.1] * 4 + [1.5] * 6), _band(10))
    assert v.outcome == "failed"


def test_reality_backlogged_while_the_model_kept_up_is_a_miss():
    """The flattering direction: the model says the fleet coped and reality
    did not. Excluding the bin because reality is censored would pass exactly
    the failure the gate exists to catch."""
    b = _band(5) + [_censored_band(50.0)]
    v = _cmp(_pred([1.1] * 6), b, frac=0.0)
    assert v.outcome == "failed"
    assert v.bins[-1].verdict == "censoring_disagreement"
    assert v.max_miss_seconds == float("inf")


def test_the_model_backlogged_while_reality_kept_up_is_a_miss_too():
    """The other direction of a censoring disagreement. Less flattering, but
    still a model that says the fleet fell behind when it did not -- an
    autoscaling verdict built on it would buy capacity nobody needed."""
    pred = _pred([1.1] * 5) + [_censored_pred(50.0)]
    v = _cmp(pred, _band(6), frac=0.0)
    assert v.outcome == "failed"
    assert v.bins[-1].verdict == "censoring_disagreement"
    assert v.max_miss_seconds == float("inf")


def test_a_censoring_disagreement_counts_as_a_judged_miss():
    """2 inside, 2 outside, 2 disagreements: 4 misses of 6 judged. Excluded,
    it would leave 4 judged (not evaluable); counted as agreement, 2 of 6
    (a pass). Only counting it as a miss fails."""
    pred = _pred([1.1, 1.1, 1.5, 1.5]) + [_censored_pred(40.0), Bin(50.0, 60.0, 20, 20, 0, 1.1, "ok")]
    b = _band(4) + [BandBin(40.0, 50.0, 1.0, 1.2, "ok"), _censored_band(50.0)]
    v = _cmp(pred, b)
    assert (v.outcome, v.compared, v.agreeing) == ("failed", 6, 2)


def test_both_backlogged_in_the_same_bin_agree_without_being_judged():
    pred = _pred([1.1] * 5) + [_censored_pred(50.0)]
    b = _band(5) + [_censored_band(50.0)]
    v = _cmp(pred, b, frac=0.0)
    assert (v.outcome, v.compared) == ("passed", 5)
    assert v.bins[-1].verdict == "agree_censored"
    assert "1 both censored" in v.detail


def test_a_backlogged_tail_does_not_count_toward_the_minimum():
    """Both sides censored says nothing about the model's latency. Counted,
    a run that agreed on 4 bins and then backlogged would pass on its tail."""
    pred = _pred([1.1] * 4) + [_censored_pred(40.0 + 10.0 * i) for i in range(6)]
    b = _band(4) + [_censored_band(40.0 + 10.0 * i) for i in range(6)]
    v = _cmp(pred, b)
    assert (v.outcome, v.compared) == ("not_evaluable", 4)


def test_a_prediction_within_the_edge_tolerance_is_inside():
    v = _cmp(_pred([1.1] * 4 + [1.2005, 0.9995]), _band(6), frac=0.0, tol=0.001)
    assert v.outcome == "passed"
    assert [x.verdict for x in v.bins[-2:]] == ["inside", "inside"]


def test_a_miss_beyond_the_tolerance_is_measured_from_the_unwidened_edge():
    """The tolerance decides inside or out; it does not shrink the miss."""
    v = _cmp(_pred([1.1] * 5 + [1.202]), _band(6), frac=0.0, tol=0.001)
    assert v.bins[-1].verdict == "outside"
    assert v.bins[-1].miss_seconds == pytest.approx(0.002, abs=1e-9)


def test_a_thin_prediction_is_excluded_not_judged():
    pred = _pred([1.1] * 5) + [Bin(50.0, 60.0, 10, 10, 0, None, "thin")]
    v = _cmp(pred, _band(6), frac=0.0)
    assert v.bins[-1].verdict == "excluded_insufficient" and v.compared == 5


def test_exactly_the_required_comparable_bins_is_evaluable():
    """The threshold is a minimum, so meeting it exactly is enough."""
    v = _cmp(_pred([1.1] * MIN_COMPARED), _band(MIN_COMPARED))
    assert v.outcome == "passed" and v.compared == MIN_COMPARED


def test_too_few_comparable_bins_is_not_evaluable_rather_than_a_pass():
    """Zero misses over too few compared bins is not agreement."""
    b = _band(MIN_COMPARED - 1) + [
        BandBin((MIN_COMPARED - 1) * 10.0, MIN_COMPARED * 10.0, None, None, "unstable")
    ]
    v = _cmp(_pred([1.1] * MIN_COMPARED), b)
    assert v.outcome == "not_evaluable"


def test_an_unstable_bin_is_excluded_from_judgement_and_reported():
    """The real system backlogged on some repeats and not others: there is no
    band to hold the model to, so the bin is neither a pass nor a miss -- but
    it is named, per bin and in the one-line summary, because a pass that
    quietly skipped bins reads like a pass over all of them."""
    b = _band(6) + [BandBin(60.0, 70.0, None, None, "unstable")]
    v = _cmp(_pred([1.1] * 6 + [5.0]), b, frac=0.0)
    assert v.outcome == "passed" and v.compared == 6
    assert v.bins[-1].verdict == "excluded_unstable"
    assert "1 excluded (1 unstable)" in v.detail


def test_an_insufficient_bin_is_reported_as_excluded_but_not_unstable():
    b = _band(6) + [BandBin(60.0, 70.0, None, None, "insufficient")]
    v = _cmp(_pred([1.1] * 7), b, frac=0.0)
    assert v.bins[-1].verdict == "excluded_insufficient"
    assert "1 excluded (0 unstable)" in v.detail


def test_a_gate_that_requires_no_evidence_is_refused():
    with pytest.raises(ValueError, match="min_compared_bins"):
        _cmp(_pred([1.1] * 6), _band(6), min_bins=0)


@pytest.mark.parametrize("frac", [-0.1, 1.0, float("nan"), float("inf")])
def test_a_miss_fraction_outside_zero_to_one_is_refused(frac):
    with pytest.raises(ValueError, match="max_miss_fraction"):
        _cmp(_pred([1.1] * 6), _band(6), frac=frac)


@pytest.mark.parametrize("tol", [-0.001, float("nan"), float("inf")])
def test_an_edge_tolerance_that_is_not_a_small_duration_is_refused(tol):
    with pytest.raises(ValueError, match="edge_tolerance_seconds"):
        _cmp(_pred([1.1] * 6), _band(6), tol=tol)


def test_the_new_thresholds_have_no_defaults():
    with pytest.raises(TypeError):
        compare(_pred([1.1] * 6), _band(6), min_compared_bins=MIN_COMPARED)


def test_mismatched_bin_edges_are_refused():
    with pytest.raises(ValueError, match="edges"):
        _cmp(_pred([1.1] * 6), _band(5))
