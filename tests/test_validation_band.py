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
        "print(sorted(m for m in sys.modules if m == 'coldstart' or m.startswith('coldstart.')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", (
        f"importing autoscale.validation_band loads {out.stdout.strip()}; artifact 4 "
        "imports this module precisely because it must not pull in artifact 1's package"
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


# ---- compare ----------------------------------------------------------------

def test_every_bin_inside_the_band_passes():
    v = compare(_pred([1.1] * 6), _band(6), min_compared_bins=MIN_COMPARED)
    assert v.outcome == "passed" and v.compared == 6 and v.max_miss_seconds == 0.0


def test_a_miss_is_reported_with_its_magnitude():
    v = compare(_pred([1.1] * 5 + [1.5]), _band(6), min_compared_bins=MIN_COMPARED)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.3)
    assert v.bins[-1].verdict == "outside"


def test_reality_backlogged_while_the_model_kept_up_is_a_miss():
    """The flattering direction: the model says the fleet coped and reality
    did not. Excluding the bin because reality is censored would pass exactly
    the failure the gate exists to catch."""
    b = _band(5) + [BandBin(50.0, 60.0, None, None, "censored")]
    v = compare(_pred([1.1] * 6), b, min_compared_bins=MIN_COMPARED)
    assert v.outcome == "failed"
    assert v.bins[-1].verdict == "censoring_disagreement"
    assert v.max_miss_seconds == float("inf")


def test_both_backlogged_in_the_same_bin_agree():
    pred = _pred([1.1] * 5) + [Bin(50.0, 60.0, 20, 15, 5, None, "censored")]
    b = _band(5) + [BandBin(50.0, 60.0, None, None, "censored")]
    assert compare(pred, b, min_compared_bins=MIN_COMPARED).outcome == "passed"


def test_the_model_backlogged_while_reality_kept_up_is_a_miss_too():
    """The other direction of a censoring disagreement. Less flattering, but
    still a model that says the fleet fell behind when it did not -- an
    autoscaling verdict built on it would buy capacity nobody needed."""
    pred = _pred([1.1] * 5) + [Bin(50.0, 60.0, 20, 15, 5, None, "censored")]
    v = compare(pred, _band(6), min_compared_bins=MIN_COMPARED)
    assert v.outcome == "failed"
    assert v.bins[-1].verdict == "censoring_disagreement"
    assert v.max_miss_seconds == float("inf")


def test_exactly_the_required_comparable_bins_is_evaluable():
    """The threshold is a minimum, so meeting it exactly is enough."""
    v = compare(_pred([1.1] * MIN_COMPARED), _band(MIN_COMPARED),
                min_compared_bins=MIN_COMPARED)
    assert v.outcome == "passed" and v.compared == MIN_COMPARED


def test_too_few_comparable_bins_is_not_evaluable_rather_than_a_pass():
    """Zero misses over too few compared bins is not agreement."""
    b = _band(MIN_COMPARED - 1) + [
        BandBin((MIN_COMPARED - 1) * 10.0, MIN_COMPARED * 10.0, None, None, "unstable")
    ]
    v = compare(_pred([1.1] * MIN_COMPARED), b, min_compared_bins=MIN_COMPARED)
    assert v.outcome == "not_evaluable"


def test_an_unstable_bin_is_excluded_from_judgement_and_reported():
    """The real system backlogged on some repeats and not others: there is no
    band to hold the model to, so the bin is neither a pass nor a miss -- but
    it is named, per bin and in the one-line summary, because a pass that
    quietly skipped bins reads like a pass over all of them."""
    b = _band(6) + [BandBin(60.0, 70.0, None, None, "unstable")]
    v = compare(_pred([1.1] * 6 + [5.0]), b, min_compared_bins=MIN_COMPARED)
    assert v.outcome == "passed" and v.compared == 6
    assert v.bins[-1].verdict == "excluded_unstable"
    assert "1 bins excluded, 1 of them unstable" in v.detail


def test_a_gate_that_requires_no_evidence_is_refused():
    with pytest.raises(ValueError, match="min_compared_bins"):
        compare(_pred([1.1] * 6), _band(6), min_compared_bins=0)


def test_mismatched_bin_edges_are_refused():
    with pytest.raises(ValueError, match="edges"):
        compare(_pred([1.1] * 6), _band(5), min_compared_bins=MIN_COMPARED)
