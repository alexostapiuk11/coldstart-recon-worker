"""Poisson arrivals with a time-varying rate, in the two shapes the spec fixes.

The spike starts at t=0. Time before 0 is baseline warm-up the simulation needs
so the queue is not empty when the spike lands -- an autoscaler evaluated from a
cold, idle system would see a step from nothing, which is not the incident
operators care about.
"""

import math
import random
from dataclasses import dataclass

__all__ = ["SpikeShape", "arrival_times", "rate_at"]


@dataclass(frozen=True)
class SpikeShape:
    """The two spike shapes the design fixes, as one immutable, validated record.

    A step and a ramp are compared as a pair (H4): a lagging signal sees the
    step's demand before any indicator can move, while the ramp is where
    signals genuinely differentiate. Encoding both as the same type -- rather
    than two ad hoc parameter sets -- is what lets `rate_at` and
    `arrival_times` treat them identically and forces every difference
    between a run's step and ramp results back onto the shape, not onto
    incidental code-path differences.
    """

    kind: str  # "step" or "ramp"
    baseline_rate: float  # requests/second before and after the spike
    k: float  # peak is k x baseline
    ramp: float  # seconds to reach peak; 0 for a step
    sustain: float  # seconds at peak, measured from t=0

    def __post_init__(self) -> None:
        if self.kind not in ("step", "ramp"):
            raise ValueError(f"kind must be 'step' or 'ramp', got {self.kind!r}")
        if self.kind == "ramp" and self.ramp <= 0:
            raise ValueError(
                "a ramp shape needs ramp > 0; a zero ramp is a step wearing a "
                "different label, and H4 compares the two shapes by name"
            )
        if self.kind == "step" and self.ramp != 0:
            raise ValueError("a step shape must have ramp == 0")
        if self.baseline_rate <= 0 or self.k < 1 or self.sustain <= 0:
            raise ValueError(
                "baseline_rate and sustain must be positive and k at least 1"
            )


def rate_at(shape: SpikeShape, t: float) -> float:
    """Arrival rate in requests/second at time `t`.

    The spike occupies [0, ramp + sustain]: it rises (or jumps, for a step)
    over [0, ramp], then holds at peak for `sustain` seconds measured from
    the moment the peak is reached, not from t=0. Anchoring the hold to t=0
    instead would make a slower ramp eat into its own sustain window, so two
    shapes with the same `sustain` would spend different amounts of time at
    peak -- exactly the kind of hidden asymmetry H4 is designed to rule out.
    """
    peak = shape.baseline_rate * shape.k
    elevated_until = shape.ramp + shape.sustain
    if t < 0.0 or t > elevated_until:
        return shape.baseline_rate
    if shape.kind == "step":
        return peak
    if t >= shape.ramp:
        return peak
    fraction = t / shape.ramp
    return shape.baseline_rate + fraction * (peak - shape.baseline_rate)


def arrival_times(shape: SpikeShape, until: float, rng: random.Random) -> list[float]:
    """Arrival timestamps in [0, until], by thinning.

    Thinning rather than piecewise-exponential sampling: draw from a homogeneous
    Poisson process at the maximum rate and keep each point with probability
    rate_at(t)/max_rate. It is exact for any rate function, including the ramp,
    without special-casing the shape -- and the ramp is precisely where a
    hand-rolled piecewise sampler gets the boundary wrong.
    """
    if until < 0.0:
        # A negative window has no arrivals either way, but returning `[]`
        # silently would hide a caller bug (e.g. subtracting timestamps the
        # wrong way round) behind a plausible-looking empty result.
        raise ValueError(f"until must be non-negative, got {until!r}")
    max_rate = shape.baseline_rate * shape.k
    times: list[float] = []
    t = 0.0
    while True:
        t += -math.log(1.0 - rng.random()) / max_rate
        if t > until:
            return times
        if rng.random() <= rate_at(shape, t) / max_rate:
            times.append(t)
