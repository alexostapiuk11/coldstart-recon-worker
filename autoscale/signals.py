"""The three scaling signals, each a pure function of fleet state.

Pure functions of one state object rather than methods on the simulator, so the
same code computes the signal in simulation and against a real deployment in
plan 2's closed-loop gate. The spec's confirmatory gate requires "same policy
code, real API"; that is only true if the signal is not entangled with the
simulator.

All three share one `(state, curve) -> float` signature so the controller can
hold any of them behind the same name, which is what makes the three arms of
the experiment differ in exactly one thing.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from autoscale.service import ServiceCurve

__all__ = ["ALL_SIGNALS", "SENSITIVITY_SIGNALS", "SIGNALS", "FleetState", "in_flight_concurrency",
           "queue_depth", "utilization", "utilization_throughput"]


@dataclass(frozen=True)
class FleetState:
    """One instant of fleet state: the whole input to every signal.

    Frozen, because every guard below runs exactly once in `__post_init__` and
    a mutable field would let a caller write a negative or non-integer count
    straight past all of them into a state the signals already trust. Its
    siblings `ServiceCurve` and `Replica` are frozen for the same reason.
    """

    waiting: int
    in_flight: int
    serving_replicas: int

    def __post_init__(self) -> None:
        for field_name, value in (
            ("waiting", self.waiting),
            ("in_flight", self.in_flight),
            ("serving_replicas", self.serving_replicas),
        ):
            # `type(...) is not int` rather than `isinstance`, matching
            # `sim.run_fixed_capacity`: it also rejects a bool (`waiting=True`
            # is a caller bug and `isinstance(True, int)` is True), and it
            # keeps the failure a ValueError carrying the reason, which is this
            # codebase's house style for invalid input.
            #
            # This is also, deliberately, the entire non-finite guard. The
            # siblings in `service.py` and `replica.py` need explicit
            # `math.isfinite` checks because their fields are genuinely floats;
            # here the fields are counts of requests and replicas, so `int` is
            # the honest domain and no int is non-finite. A NaN `waiting`
            # would otherwise divide cleanly into a NaN signal, and NaN
            # compares False against every threshold a controller tests, so the
            # policy would sit at HOLD forever while the fleet drowned --
            # silence, not an error. A NaN `serving_replicas` would additionally
            # slip past the `== 0` branch below and reach the division.
            if type(value) is not int:
                raise ValueError(
                    f"{field_name} must be an int, got {value!r} "
                    f"({type(value).__name__}); these are counts of requests "
                    "and replicas, and accepting a float admits NaN and "
                    "infinity, which divide into a NaN or infinite signal that "
                    "compares False against every controller threshold -- the "
                    "policy would hold forever instead of raising here"
                )
            # A negative count does not read as a small one, it reads as the
            # OPPOSITE of the truth: `waiting=-50` over two replicas is -25.0,
            # far below any scale-up threshold, so a fleet drowning in a
            # bookkeeping bug reports maximum slack. A negative replica count
            # flips the sign of all three signals at once. That is the
            # flattering direction of error, so it is refused rather than
            # clamped.
            if value < 0:
                raise ValueError(
                    f"{field_name} is {value!r}, which is negative; a count of "
                    "requests or replicas cannot be, and a negative one does "
                    "not read as a small signal but as a signal of the wrong "
                    "SIGN -- an overloaded fleet reporting maximum slack"
                )


def _zero_replica_reading(state: FleetState, saturated: float) -> float:
    """What a signal reports when no replica is serving.

    Two genuinely different states share `serving_replicas == 0`, and
    collapsing them is a real bug in either direction:

    - Work exists but nothing serves it -- the state right after a
      scale-from-zero, and the moment a policy most needs a defined signal.
      Reporting `saturated` (unbounded pressure for the two counting signals,
      1.0 for utilization) is the honest reading: the fleet cannot absorb
      anything. Reporting 0.0 would read as "no pressure" and leave the fleet
      parked at zero with a queue behind it.
    - No work exists either -- a fleet correctly parked at zero. Reporting
      `saturated` here would scale it straight back up the instant it reached
      zero, so it could never stay, and sitting at zero is exactly what
      replica-seconds (the cost axis of every Pareto frontier in this
      artifact) buys.

    So the maximum-pressure reading is a response to unserved WORK, and is
    conditioned on work existing.

    One constraint this puts on the controller: the two counting signals return
    `float("inf")` here, which is fine for a threshold comparison (`inf >=
    scale_up_at` is True) but not for arithmetic that multiplies the signal by
    the replica count -- `0 * inf` is NaN. Plan 2's controller is a threshold
    controller, and a ratio-based one would need a finite sentinel instead.
    """
    if state.waiting + state.in_flight == 0:
        return 0.0
    return saturated


def queue_depth(state: FleetState, curve: ServiceCurve) -> float:
    """Requests waiting per serving replica. `curve` is unused; the uniform
    signature is what lets the controller treat all three interchangeably."""
    if state.serving_replicas == 0:
        return _zero_replica_reading(state, float("inf"))
    return state.waiting / state.serving_replicas


def in_flight_concurrency(state: FleetState, curve: ServiceCurve) -> float:
    """Active requests per serving replica."""
    if state.serving_replicas == 0:
        return _zero_replica_reading(state, float("inf"))
    return state.in_flight / state.serving_replicas


def utilization(state: FleetState, curve: ServiceCurve) -> float:
    """GPU utilization, read off the measured curve at current per-replica load.

    This is the signal H2 predicts is worst, and the mechanism is visible right
    here: the curve saturates at 1.0, so beyond that point the signal returns
    the same value for a busy fleet and a collapsing one. A policy driven by it
    stops receiving information exactly when it most needs it. Queue depth and
    concurrency have no ceiling and keep discriminating.

    The per-replica load is passed to the curve UNROUNDED. `ServiceCurve`
    interpolates linearly and its query methods take floats, so a fractional
    load is a point the curve was built to answer at. `sim.run_fixed_capacity`
    rounds the same ratio UP, and that is not an inconsistency to reconcile: it
    is answering a different question. There it is charging one discrete
    request the load of the specific replica it lands on, and under even
    balancing an unevenly divided fleet has a busiest replica carrying
    `ceil(n / replicas)`. Here the signal is a fleet-wide gauge -- what an
    aggregated utilization metric reports across replicas -- which is a mean,
    and a mean is fractional. The two agree whenever the fleet divides evenly,
    and diverge only where rounding would be pure quantization error.

    Rounding either way would also put a fixed bias directly on top of the
    hypothesis under test. Flooring (the obvious `int(per_replica)`) reads
    utilization LOW, delaying every scale-up and making H2's prediction easier
    to confirm; ceiling reads it high and makes it harder. Neither belongs in a
    signal whose relative performance is the published result. Interpolating
    picks no side.
    """
    if state.serving_replicas == 0:
        return _zero_replica_reading(state, 1.0)
    per_replica = state.in_flight / state.serving_replicas
    return curve.utilization_at(per_replica)


def utilization_throughput(state: FleetState, curve: ServiceCurve) -> float:
    """Utilisation as the fraction of the replica's peak throughput in use.

    The sensitivity arm for H2 (owner decision 2026-10-04). nvidia-smi's
    utilisation, which `utilization` reads, saturates at one request in flight
    on this engine, so a policy on it cannot tell a lightly loaded replica from
    a collapsing one. That is what a DCGM-driven autoscaler sees, and it is
    the headline. This signal answers the obvious objection -- "you beat
    utilisation by picking its worst definition" -- with the best definition
    the measured curve supports: throughput at the current per-replica load
    over the curve's maximum throughput, which rises until the knee. Same
    fraction scale, so utilisation's threshold grid applies unchanged.
    Rejected: a fourth headline signal, which would change every figure and
    the pre-registered three-arm comparison.

    ASSUMPTION: throughput is non-decreasing in load up to the curve's cap, as
    it is on the measured curve. Past a peak the fraction would fall with load,
    and a collapsing replica would read as LESS utilised -- the censoring this
    arm exists to avoid, reintroduced from the other side. Rejected: a running
    maximum over load, which would flatten a non-monotone measurement into a
    plateau; a throughput that falls with load is a finding to investigate, not
    to smooth. The denominator is the maximum over all points for that reason.
    """
    if state.serving_replicas == 0:
        return _zero_replica_reading(state, 1.0)
    peak = max(p[2] for p in curve.points)
    if peak <= 0:
        raise ValueError(
            "the curve's maximum throughput is 0; a throughput fraction has no denominator, "
            "and returning 0 would read every load as idle"
        )
    per_replica = state.in_flight / state.serving_replicas
    # Only absorbs float-epsilon overshoot from the interpolation, as in
    # `ServiceCurve.utilization_at`; the ratio cannot otherwise exceed 1.
    return min(1.0, curve.throughput_at(per_replica) / peak)


# A read-only view, not a plain dict: this registry is how a sweep names the
# three arms, and a module-level dict could be mutated by any importer --
# silently swapping the function a published arm was actually run with.
# `ServiceCurve` normalises `points` to a tuple for the same reason.
SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {
        "queue_depth": queue_depth,
        "in_flight_concurrency": in_flight_concurrency,
        "utilization": utilization,
    }
)

# Signals run only when named: a sensitivity analysis, not an arm of the
# experiment. Kept out of SIGNALS so `run_sweep`'s default and every figure
# built on the three arms are untouched.
SENSITIVITY_SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {"utilization_throughput": utilization_throughput}
)

ALL_SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {**SIGNALS, **SENSITIVITY_SIGNALS}
)
