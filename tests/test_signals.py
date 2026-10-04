import dataclasses

import pytest

from autoscale.service import ServiceCurve
from autoscale.signals import (
    ALL_SIGNALS,
    SENSITIVITY_SIGNALS,
    SIGNALS,
    FleetState,
    in_flight_concurrency,
    queue_depth,
    utilization,
    utilization_throughput,
)
from autoscale.thresholds import SENSITIVITY_THRESHOLDS, THRESHOLDS

CURVE = ServiceCurve(
    points=[(1, 0.30, 53.0, 0.18), (8, 0.38, 337.0, 0.85), (32, 0.95, 539.0, 0.99)],
    measured=True,
)


def test_queue_depth_counts_waiting_requests_per_serving_replica():
    state = FleetState(waiting=12, in_flight=4, serving_replicas=2)
    assert queue_depth(state, CURVE) == pytest.approx(6.0)


def test_in_flight_concurrency_counts_active_requests_per_serving_replica():
    state = FleetState(waiting=12, in_flight=4, serving_replicas=2)
    assert in_flight_concurrency(state, CURVE) == pytest.approx(2.0)


def test_utilization_reads_the_measured_curve_and_saturates():
    """H2's mechanism: utilization is censored. Past the point where the curve
    reaches 1.0 the signal cannot distinguish busy from catastrophically
    overloaded, so a policy driven by it stops responding to worsening load."""
    mild = FleetState(waiting=0, in_flight=8, serving_replicas=1)
    severe = FleetState(waiting=500, in_flight=32, serving_replicas=1)
    catastrophic = FleetState(waiting=5000, in_flight=64, serving_replicas=1)

    assert utilization(mild, CURVE) == pytest.approx(0.85)
    assert utilization(severe, CURVE) == pytest.approx(0.99)
    assert utilization(catastrophic, CURVE) == utilization(severe, CURVE)


def test_the_other_two_signals_keep_discriminating_where_utilization_cannot():
    """The same two states utilization cannot separate."""
    severe = FleetState(waiting=500, in_flight=32, serving_replicas=1)
    catastrophic = FleetState(waiting=5000, in_flight=64, serving_replicas=1)

    assert queue_depth(catastrophic, CURVE) > queue_depth(severe, CURVE)
    assert in_flight_concurrency(catastrophic, CURVE) > in_flight_concurrency(severe, CURVE)


def test_signals_with_no_serving_replicas_report_maximum_pressure():
    """Zero serving replicas is the state right after a scale-from-zero, and it
    is the moment a policy most needs a defined signal. Dividing by zero
    replicas must not crash or silently read as 'no pressure'."""
    state = FleetState(waiting=50, in_flight=0, serving_replicas=0)

    assert queue_depth(state, CURVE) == float("inf")
    assert in_flight_concurrency(state, CURVE) == float("inf")
    assert utilization(state, CURVE) == 1.0


def test_an_idle_fleet_scaled_to_zero_reports_no_pressure_at_all():
    """The other half of the zero-replica state, and the half that decides
    whether scale-to-zero is reachable at all.

    Zero replicas with zero demand is a fleet correctly parked at zero, not a
    fleet in trouble. If it reported maximum pressure, every policy would
    scale straight back up the instant it reached zero and could never stay
    there -- and replica-seconds, the cost axis of every Pareto frontier in
    this artifact, is exactly what sitting at zero buys. The maximum-pressure
    reading is a response to unserved WORK, so it is conditioned on work
    existing.
    """
    idle = FleetState(waiting=0, in_flight=0, serving_replicas=0)

    assert queue_depth(idle, CURVE) == 0.0
    assert in_flight_concurrency(idle, CURVE) == 0.0
    assert utilization(idle, CURVE) == 0.0


def test_utilization_interpolates_the_fractional_per_replica_load():
    """The per-replica load is a fleet MEAN and is routinely fractional; the
    curve is a continuous interpolation built to be queried at exactly such a
    point. Rounding it to an integer first would throw that away and replace it
    with a quantization error pointing in one fixed direction -- and the
    direction would sit on top of the hypothesis under test.
    """
    state = FleetState(waiting=0, in_flight=3, serving_replicas=2)

    assert utilization(state, CURVE) == pytest.approx(CURVE.utilization_at(1.5))
    # Strictly between the two integers the naive roundings would have picked,
    # so this fails if the implementation floors (0.18) or ceils (~0.2757).
    assert CURVE.utilization_at(1) < utilization(state, CURVE) < CURVE.utilization_at(2)


def test_a_negative_count_is_rejected_rather_than_flipping_the_signal():
    """A negative count does not read as a small one -- it reads as the
    OPPOSITE of the truth. `waiting=-50` over two replicas is -25.0, far below
    any scale-up threshold, so a fleet drowning in a bookkeeping bug reports
    maximum slack. A negative replica count flips the sign of every signal at
    once for the same reason.
    """
    for kwargs in (
        {"waiting": -1, "in_flight": 0, "serving_replicas": 1},
        {"waiting": 0, "in_flight": -1, "serving_replicas": 1},
        {"waiting": 0, "in_flight": 0, "serving_replicas": -1},
    ):
        with pytest.raises(ValueError, match="negative"):
            FleetState(**kwargs)


def test_a_non_int_count_is_rejected_so_no_nan_can_reach_the_division():
    """The fields are counts of requests and replicas, so `int` is the whole
    honest domain -- and refusing anything else is what makes a NaN or an
    infinity impossible to construct. A NaN `waiting` would divide cleanly into
    a NaN signal, which compares False against every threshold a controller
    tests, so the policy would silently hold forever instead of raising. A bool
    is rejected too: `waiting=True` is a caller bug, and `isinstance(True, int)`
    is True.
    """
    for bad in (float("nan"), float("inf"), 12.0, True):
        with pytest.raises(ValueError, match="must be an int"):
            FleetState(waiting=bad, in_flight=0, serving_replicas=1)


def test_fleet_state_is_frozen_so_a_validated_state_stays_validated():
    """Every guard above runs once, in `__post_init__`. A mutable field would
    let a caller write a negative or non-int count straight past all of them.
    """
    state = FleetState(waiting=1, in_flight=1, serving_replicas=1)

    with pytest.raises(dataclasses.FrozenInstanceError):
        state.waiting = -5


def test_the_signals_registry_names_all_three_and_cannot_be_rewritten():
    """The registry is what lets a sweep iterate the arms by name. A plain dict
    at module scope could be rebound by any importer, which would silently swap
    the function a published arm was run with.
    """
    assert set(SIGNALS) == {"queue_depth", "in_flight_concurrency", "utilization"}

    with pytest.raises(TypeError):
        SIGNALS["queue_depth"] = utilization


def test_every_signal_shares_one_signature_so_the_controller_can_swap_them():
    """The uniform (state, curve) signature is the reason `queue_depth` and
    `in_flight_concurrency` accept a curve they never read."""
    state = FleetState(waiting=12, in_flight=4, serving_replicas=2)

    values = {name: fn(state, CURVE) for name, fn in SIGNALS.items()}

    assert values == {
        "queue_depth": pytest.approx(6.0),
        "in_flight_concurrency": pytest.approx(2.0),
        "utilization": pytest.approx(CURVE.utilization_at(2.0)),
    }


def _tp_curve():
    return ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (4, 0.4, 200.0, 1.0)],
                        measured=True)


def test_throughput_fraction_rises_with_load_where_nvidia_smi_is_flat():
    curve = _tp_curve()
    low = utilization_throughput(FleetState(waiting=0, in_flight=1, serving_replicas=1), curve)
    high = utilization_throughput(FleetState(waiting=0, in_flight=4, serving_replicas=1), curve)
    assert low == pytest.approx(0.25)
    assert high == pytest.approx(1.0)
    assert utilization(FleetState(0, 1, 1), curve) == utilization(FleetState(0, 4, 1), curve) == 1.0


def test_throughput_fraction_is_zero_when_idle_and_saturated_with_unserved_work():
    curve = _tp_curve()
    assert utilization_throughput(FleetState(0, 0, 1), curve) == 0.0
    assert utilization_throughput(FleetState(3, 0, 0), curve) == 1.0
    assert utilization_throughput(FleetState(0, 0, 0), curve) == 0.0


def test_the_headline_registry_is_unchanged_and_the_sensitivity_one_is_separate():
    assert sorted(SIGNALS) == ["in_flight_concurrency", "queue_depth", "utilization"]
    assert sorted(SENSITIVITY_SIGNALS) == ["utilization_throughput"]
    assert dict(ALL_SIGNALS) == {**SIGNALS, **SENSITIVITY_SIGNALS}


def test_the_sensitivity_signal_uses_utilizations_grid_outside_the_pre_registered_dict():
    assert SENSITIVITY_THRESHOLDS["utilization_throughput"] == THRESHOLDS["utilization"]
    assert "utilization_throughput" not in THRESHOLDS
