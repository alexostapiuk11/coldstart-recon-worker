from pathlib import Path

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,
    BASELINE_FRACTION_OF_SATURATION,
    RAMP_SECONDS,
    SUSTAIN_SECONDS,
    saturation_rps,
    spike_shape,
)

REPO = Path(__file__).resolve().parents[1]


def test_saturation_is_the_best_point_not_the_last():
    """Continuous batching makes throughput non-monotonic past the knee. On the
    placeholder the top point (64 at 2.10 s) sustains 30.5 rps while 32 at
    0.95 s sustains 33.7 -- reading the last point understates saturation 9%."""
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) == pytest.approx(32 / 0.95)
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) > 64 / 2.10


def test_every_constructible_curve_has_a_positive_concurrency_point():
    """`saturation_rps` takes a max over points with positive concurrency and
    has no empty-case guard, because ServiceCurve makes the empty case
    unconstructible: at least two points, distinct concurrencies, none
    negative -- so at least one is positive. Pinned here so that if
    ServiceCurve ever relaxes one of those, this fails instead of
    `saturation_rps` raising a context-free `max()` error."""
    with pytest.raises(ValueError, match="distinct"):
        ServiceCurve(points=[(0, 0.3, 1.0, 0.1), (0, 0.3, 1.0, 0.1)], measured=False)


def test_the_step_follows_the_preregistered_rule():
    sat = saturation_rps(SERVICE_CURVE_PLACEHOLDER)
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    assert shape.kind == "step"
    assert shape.baseline_rate == pytest.approx(0.70 * sat, rel=1e-15)
    assert shape.k == pytest.approx((0.70 + 0.25) / 0.70, rel=1e-12)
    assert shape.ramp == 0.0
    assert shape.sustain == 190.0


def test_the_ramp_is_half_the_sustain():
    assert spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp").ramp == 95.0


def test_a_reduced_window_keeps_r_equal_to_d_over_two():
    """The end-to-end test halves the window for speed. R = D/2 must hold there
    too, which is why the ramp is derived rather than accepted."""
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp", sustain=95.0)
    assert shape.ramp == 47.5


def test_a_candidate_regime_can_be_measured_before_it_is_adopted():
    shape = spike_shape(
        SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=0.40, additional_replicas=0.5
    )
    assert shape.k == pytest.approx((0.40 + 0.5) / 0.40)


@pytest.mark.parametrize("name", ["sustain", "baseline_fraction", "additional_replicas"])
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_parameters_are_refused(name, bad):
    with pytest.raises(ValueError, match=name):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", **{name: bad})


def test_the_constants_are_the_ones_the_preregistration_states():
    """An amendment to the traffic model is a change to a pre-registered
    quantity. It has to touch the document, not just this module."""
    prereg = (REPO / "docs" / "experiment-a2.md").read_text()
    assert BASELINE_FRACTION_OF_SATURATION == 0.70
    assert "baseline = **70%** of measured saturation" in prereg
    assert ADDITIONAL_REPLICAS_AT_PEAK == 0.25
    assert "**0.25 additional replicas**" in prereg
    assert SUSTAIN_SECONDS == 190.0
    assert "rounded to **190 s**" in prereg
    assert RAMP_SECONDS == 95.0
    assert "= **95 s**" in prereg
