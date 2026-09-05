import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve


def test_latency_interpolates_between_measured_points():
    curve = ServiceCurve(
        points=[(1, 0.10, 100.0, 0.20), (10, 0.30, 400.0, 0.80)], measured=True
    )

    assert curve.latency_at(1) == pytest.approx(0.10)
    assert curve.latency_at(10) == pytest.approx(0.30)
    assert curve.latency_at(5) == pytest.approx(0.10 + (4 / 9) * 0.20, abs=1e-6)


def test_concurrency_below_the_first_measured_point_clamps():
    curve = ServiceCurve(points=[(2, 0.10, 100.0, 0.2), (10, 0.30, 400.0, 0.8)], measured=True)
    assert curve.latency_at(1) == pytest.approx(0.10)


def test_concurrency_above_the_last_measured_point_is_flagged_extrapolation():
    """The spec requires extrapolation beyond the validated range to be visible
    rather than silently plausible."""
    curve = ServiceCurve(points=[(1, 0.10, 100.0, 0.2), (10, 0.30, 400.0, 0.8)], measured=True)

    assert curve.is_extrapolating(11) is True
    assert curve.is_extrapolating(10) is False


def test_utilization_saturates_at_one():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.4), (10, 0.3, 400.0, 0.99)], measured=True)
    assert curve.utilization_at(10) == pytest.approx(0.99)
    assert curve.utilization_at(50) <= 1.0


def test_the_placeholder_curve_knows_it_is_not_measured():
    """Plan 2 replaces this with the real sweep. Until then nothing may publish
    a number derived from it without saying so."""
    assert SERVICE_CURVE_PLACEHOLDER.measured is False


def test_an_unsorted_or_empty_curve_is_rejected():
    with pytest.raises(ValueError, match="ascending"):
        ServiceCurve(points=[(10, 0.3, 400.0, 0.8), (1, 0.1, 100.0, 0.2)], measured=True)
    with pytest.raises(ValueError, match="at least two"):
        ServiceCurve(points=[(1, 0.1, 100.0, 0.2)], measured=True)


def test_duplicate_concurrency_values_are_rejected():
    """Two points at the same concurrency would make `_interpolate`'s
    `(x1 - x0)` a division by zero for any query landing exactly on it."""
    with pytest.raises(ValueError, match="distinct"):
        ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (1, 0.3, 400.0, 0.8)], measured=True)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field_index", [0, 1, 2, 3])
def test_non_finite_point_fields_are_rejected(bad, field_index):
    """Every field in every point must be finite: NaN compares False against
    the ascending-order check and every interpolation comparison, and +-inf
    poisons the interpolation arithmetic -- either way a non-finite field
    would silently produce a plausible-looking but meaningless curve."""
    # The bad value goes on the SECOND point. Putting it on the first point's
    # concurrency (field_index 0) would make that point's concurrency `inf`,
    # which is both non-finite AND out of ascending order against the second
    # point's `10` -- two guards would fire on the same input, and if the
    # ascending-order check ever moved above the finiteness loop this test
    # would start failing on the wrong message for the wrong reason. Using
    # the second point isolates the finiteness guard regardless of guard
    # ordering.
    good_point = (1, 0.1, 100.0, 0.2)
    point = [10, 0.3, 400.0, 0.8]
    point[field_index] = bad
    with pytest.raises(ValueError, match="not finite"):
        ServiceCurve(points=[good_point, tuple(point)], measured=True)


def test_negative_concurrency_latency_or_throughput_is_rejected():
    """A negative reading has no physical meaning for any of these fields --
    a replica cannot serve at negative concurrency, take negative time, or
    emit negative throughput -- and would silently poison every downstream
    interpolation with a sign error instead of raising here."""
    with pytest.raises(ValueError, match="concurrency"):
        ServiceCurve(points=[(-1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="latency"):
        ServiceCurve(points=[(1, -0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="throughput"):
        ServiceCurve(points=[(1, 0.1, -100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)


def test_utilization_outside_zero_to_one_is_rejected():
    """A utilization above 1 is exactly the measurement bug a hardware sweep
    might produce -- a normalization error, a >100% nvidia-smi reading -- and
    `min(1.0, ...)` in `utilization_at` would silently render it invisible if
    it were allowed to construct at all."""
    with pytest.raises(ValueError, match="utilization"):
        ServiceCurve(points=[(1, 0.1, 100.0, 0.4), (10, 0.3, 400.0, 1.7)], measured=True)
    with pytest.raises(ValueError, match="utilization"):
        ServiceCurve(points=[(1, 0.1, 100.0, -0.1), (10, 0.3, 400.0, 0.8)], measured=True)


def test_service_curve_is_frozen():
    """`measured=False` on the placeholder is inert if the flag can just be
    flipped after construction -- a frozen dataclass makes it tamper-evident
    instead of merely a documented convention."""
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(AttributeError):
        curve.measured = False
    with pytest.raises(AttributeError):
        curve.points = ((1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8))


def test_service_curve_points_are_a_tuple_and_cannot_be_extended():
    """A list can be mutated in place past every `__post_init__` guard --
    `curve.points.append(...)` would add an unvalidated, unsorted point that
    every later query trusts. Normalising to a tuple in `__post_init__`
    closes that even though the constructor still accepts a list."""
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    assert isinstance(curve.points, tuple)
    with pytest.raises(AttributeError):
        curve.points.append((20, 0.5, 500.0, 0.9))


def test_max_measured_concurrency_matches_the_last_point():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    assert curve.max_measured_concurrency == 10
    assert SERVICE_CURVE_PLACEHOLDER.max_measured_concurrency == SERVICE_CURVE_PLACEHOLDER.points[-1][0]


def test_latency_at_rejects_nan_concurrency():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="NaN"):
        curve.latency_at(float("nan"))


def test_throughput_at_rejects_nan_concurrency():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="NaN"):
        curve.throughput_at(float("nan"))


def test_utilization_at_rejects_nan_concurrency():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="NaN"):
        curve.utilization_at(float("nan"))


def test_is_extrapolating_rejects_nan_concurrency():
    """Must agree with latency_at: silently returning False for a NaN query
    would tell a caller checking before calling latency_at that the query is
    safe, when latency_at raises on that exact input."""
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.2), (10, 0.3, 400.0, 0.8)], measured=True)
    with pytest.raises(ValueError, match="NaN"):
        curve.is_extrapolating(float("nan"))
