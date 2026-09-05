"""Poisson arrivals with a time-varying rate, in the two shapes the spec fixes.

The spike starts at t=0. `rate_at` accepts negative t and returns the baseline
rate there, so a caller who wants baseline warm-up before the spike lands can
generate it separately by sampling `rate_at` (or their own homogeneous
process) over a negative window -- but `arrival_times` always starts its
window at t=0.0 and never emits a negative timestamp, so it does not generate
that warm-up itself.
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
    sustain: float  # seconds held at peak, measured from when the peak is
    # reached (t=ramp)

    def __post_init__(self) -> None:
        if self.kind not in ("step", "ramp"):
            raise ValueError(f"kind must be 'step' or 'ramp', got {self.kind!r}")
        # NaN compares False against every `<`/`>`/`<=` below, including
        # against itself, so every check that follows would silently pass a
        # NaN through; +-inf compare as ordinary (extreme) floats and pass
        # those same checks legitimately, but then poison the arithmetic
        # downstream. Reject all four fields up front, before any of the
        # comparison-based checks run, so neither failure mode reaches them.
        for field_name, value, consequence in (
            (
                "baseline_rate",
                self.baseline_rate,
                (
                    "it feeds max_rate = baseline_rate * k directly in "
                    "arrival_times, so a non-finite baseline_rate makes "
                    "every candidate draw divide by inf (zero progress) or "
                    "compare against NaN -- either way arrival_times loops "
                    "forever"
                ),
            ),
            (
                "k",
                self.k,
                (
                    "it feeds max_rate = baseline_rate * k directly in "
                    "arrival_times, so a non-finite k makes every candidate "
                    "draw divide by inf (zero progress) or compare against "
                    "NaN -- either way arrival_times loops forever"
                ),
            ),
            (
                "ramp",
                self.ramp,
                (
                    "elevated_until = ramp + sustain would be non-finite, "
                    "so `t > elevated_until` is never true and rate_at "
                    "returns peak forever -- a spike with no end, and if "
                    "ramp itself is infinite the spike never even reaches "
                    "peak"
                ),
            ),
            (
                "sustain",
                self.sustain,
                (
                    "elevated_until = ramp + sustain would be non-finite, "
                    "so `t > elevated_until` is never true and rate_at "
                    "returns peak forever -- a spike with no end, "
                    "fabricated silently and reported as a normal, bounded "
                    "one"
                ),
            ),
        ):
            if not math.isfinite(value):
                raise ValueError(
                    f"{field_name} is {value!r}, which is not finite; {consequence}"
                )
        if self.kind == "ramp" and self.ramp <= 0:
            raise ValueError(
                "a ramp shape needs ramp > 0; a zero ramp is a step wearing a "
                "different label, and H4 compares the two shapes by name"
            )
        if self.kind == "step" and self.ramp != 0:
            raise ValueError("a step shape must have ramp == 0")
        if self.k < 1:
            raise ValueError(
                f"k must be at least 1, got {self.k!r}; k below 1 inverts "
                "the spike into a dip, so a run labelled \"spike\" would "
                "measure the autoscaler's response to a traffic DROP instead"
            )
        if self.baseline_rate <= 0:
            raise ValueError(
                f"baseline_rate must be positive, got {self.baseline_rate!r}; "
                "a non-positive baseline_rate makes max_rate non-positive, "
                "so arrival_times divides by zero or spins forever"
            )
        if self.sustain <= 0:
            raise ValueError(
                f"sustain must be positive, got {self.sustain!r}; a "
                "non-positive sustain collapses the hold at peak to "
                "nothing, so the shape produces no spike at all despite "
                "being labeled one"
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
    if math.isnan(t):
        # `t < 0.0` and `t > elevated_until` are both False for NaN, so
        # without this guard NaN would fall through both branches and
        # silently return peak -- for any shape, regardless of parameters.
        raise ValueError(
            "t is NaN; NaN compares False against both `t < 0.0` and "
            "`t > elevated_until`, so it would silently fall through and "
            "return the peak rate instead of raising"
        )
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

    Common-random-number coupling: two shapes built with the same
    baseline_rate and k (as a step and a ramp are, for an H4 comparison)
    share the identical max_rate, so for the same rng seed they draw
    candidate timestamps from the identical homogeneous process and consume
    the same two rng.random() calls per candidate regardless of whether
    either shape's rate_at accepts it. Their candidate streams are therefore
    identical until per-candidate acceptance -- which does differ between
    the shapes -- thins them apart; in practice a large fraction of the
    accepted timestamps still end up shared between the two traces. Example:
    a step (baseline_rate=2, k=4, ramp=0, sustain=190) and a ramp
    (baseline_rate=2, k=4, ramp=95, sustain=190) drawn from the same
    random.Random(42) over until=400 share 1634 of their accepted
    timestamps. This is deliberate variance reduction for comparing shapes
    head-to-head, but it means the two arrival traces are NOT independent
    draws: a confidence interval on the step-vs-ramp margin must account
    for this correlation rather than treating the traces as independent
    samples.
    """
    if not math.isfinite(until) or until < 0.0:
        if math.isnan(until):
            raise ValueError(
                "until is NaN; `t > until` compares False against a NaN "
                "until forever, so arrival_times would never stop drawing "
                "candidates and loop until memory is exhausted"
            )
        if math.isinf(until):
            raise ValueError(
                f"until is {until!r}; an infinite window means `t > until` "
                "is never true, so arrival_times would draw candidates "
                "forever instead of returning"
            )
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
