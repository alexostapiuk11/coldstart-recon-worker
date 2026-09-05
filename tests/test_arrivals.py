import random

import pytest

from autoscale.arrivals import SpikeShape, arrival_times, rate_at


def test_step_rate_jumps_at_spike_start_and_holds():
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)

    assert rate_at(shape, -1.0) == 2.0
    assert rate_at(shape, 0.0) == 8.0
    assert rate_at(shape, 189.0) == 8.0
    assert rate_at(shape, 191.0) == 2.0


def test_ramp_rises_linearly_then_holds():
    shape = SpikeShape(kind="ramp", baseline_rate=2.0, k=4.0, ramp=95.0, sustain=190.0)

    assert rate_at(shape, 0.0) == 2.0
    assert rate_at(shape, 47.5) == pytest.approx(5.0)
    assert rate_at(shape, 95.0) == pytest.approx(8.0)
    assert rate_at(shape, 200.0) == pytest.approx(8.0)
    assert rate_at(shape, 300.0) == 2.0


def test_arrivals_are_reproducible_from_a_seed():
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=10.0)

    a = arrival_times(shape, until=20.0, rng=random.Random(3))
    b = arrival_times(shape, until=20.0, rng=random.Random(3))

    assert a == b


def test_arrival_times_are_sorted_and_within_the_window():
    shape = SpikeShape(kind="step", baseline_rate=5.0, k=3.0, ramp=0.0, sustain=10.0)

    times = arrival_times(shape, until=30.0, rng=random.Random(11))

    assert times == sorted(times)
    assert all(0.0 <= t <= 30.0 for t in times)
    assert len(times) > 0


def test_the_spike_produces_more_arrivals_than_the_same_span_of_baseline():
    """The thinning must actually thin. A bug that ignored rate_at would still
    produce sorted times in range and pass every other test here."""
    shape = SpikeShape(kind="step", baseline_rate=1.0, k=10.0, ramp=0.0, sustain=100.0)
    times = arrival_times(shape, until=200.0, rng=random.Random(5))

    during = len([t for t in times if 0.0 <= t < 100.0])
    after = len([t for t in times if 100.0 <= t < 200.0])

    assert during > 3 * after


def test_a_ramp_shape_with_zero_ramp_is_rejected():
    """A ramp of zero is a step wearing a different label, and publishing it as
    a ramp would misreport which shape produced a result (H4)."""
    with pytest.raises(ValueError, match="ramp"):
        SpikeShape(kind="ramp", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)


def test_rate_at_holds_peak_for_the_full_sustain_after_the_ramp_completes():
    """sustain is measured from the moment the peak is reached, not from t=0.
    Anchoring it to t=0 instead would make a slower ramp eat into its own
    sustain window, so a step and a ramp built from the same `sustain` would
    spend different amounts of time at peak -- an asymmetry H4 must not have."""
    shape = SpikeShape(kind="ramp", baseline_rate=2.0, k=4.0, ramp=95.0, sustain=190.0)

    assert rate_at(shape, 285.0) == pytest.approx(8.0)
    assert rate_at(shape, 285.0001) == 2.0


def test_a_negative_until_is_rejected_rather_than_silently_returning_no_arrivals():
    """An empty list is what a negative window would produce anyway, so a bug
    that passes a negative duration by mistake would go unnoticed without an
    explicit check."""
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=10.0)
    with pytest.raises(ValueError, match="until"):
        arrival_times(shape, until=-5.0, rng=random.Random(1))
