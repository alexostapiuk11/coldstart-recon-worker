"""The traffic model, stated once.

docs/experiment-a2.md fixes the traffic model as a RULE over the service curve
-- baseline a fraction of one replica's saturation, `k` sized to require some
number of additional replicas at the measured service rate -- with "the two
absolute rates computed from the service curve and committed before any policy
sweep runs". Literals fixed against one curve silently stop implementing the
rule the moment the curve is replaced, which is exactly what plan 2's measured
sweep will do. The simulator plan's first draft did exactly this, with
`baseline_rate=2.0, k=4.0`: about a sixth of what the rule as first registered
gave against the placeholder curve. At that load one replica absorbed the whole
spike, queue depth never crossed its lowest threshold, and every policy was
discarded as `no_scaling_action`.

Until this module the rule lived in four places: the render script, the
noise-floor diagnostic, the regime probe (twice, inline) and the end-to-end
test. They agreed because a test compared two of them and because the
2026-09-17 amendment was applied by hand in each. When the measured curve
lands, one place changes.

R = D/2 is encoded structurally: `spike_shape` derives the ramp from the
sustain instead of accepting both, so no caller can pass a pair that breaks the
pre-registered relationship -- including the end-to-end test's halved window.
"""

import math

from autoscale.arrivals import SpikeShape
from autoscale.service import ServiceCurve

__all__ = [
    "ADDITIONAL_REPLICAS_AT_PEAK",
    "BASELINE_FRACTION_OF_SATURATION",
    "RAMP_SECONDS",
    "SUSTAIN_SECONDS",
    "saturation_rps",
    "spike_shape",
]

# D = 2 x p95(arm A) = 192.7 s, rounded. Pinned to arm A and held constant
# across both distributions so the composition comparison varies one thing.
SUSTAIN_SECONDS = 190.0
# R = D / 2, evaluated at the default sustain above -- kept as a module
# constant for display and for the render script's own test (inventory row
# 11: it imports RAMP_SECONDS and checks the source calls spike_shape with
# kind="ramp"). `spike_shape` does not read this constant back: it derives R
# from whichever `sustain` its caller passes, on purpose, so a caller with a
# different D (the end-to-end test's halved window) still gets R = D/2 for
# ITS D, not this one.
RAMP_SECONDS = SUSTAIN_SECONDS / 2
# Both amended 2026-09-17 from 40% and 3. As first registered they put the peak
# at 3.4x one replica's saturation and every policy delivered an identical p99;
# docs/experiment-a2.md states the old values, the evidence and the search.
BASELINE_FRACTION_OF_SATURATION = 0.70
ADDITIONAL_REPLICAS_AT_PEAK = 0.25


def saturation_rps(curve: ServiceCurve) -> float:
    """Requests per second one replica sustains at its best operating point.

    A max over the measured points rather than the value at the last one:
    continuous batching makes throughput non-monotonic past the latency knee.

    No empty-case guard: ServiceCurve refuses fewer than two points, duplicate
    concurrencies and negative ones, so at least one point is positive.
    `tests/test_traffic.py` pins that guarantee rather than testing a branch
    that cannot run.
    """
    return max(c / curve.latency_at(c) for c, _, _, _ in curve.points if c > 0)


def spike_shape(
    curve: ServiceCurve,
    kind: str,
    *,
    sustain: float = SUSTAIN_SECONDS,
    baseline_fraction: float = BASELINE_FRACTION_OF_SATURATION,
    additional_replicas: float = ADDITIONAL_REPLICAS_AT_PEAK,
) -> SpikeShape:
    """The pre-registered spike of `kind`, derived from `curve`.

    `baseline_fraction` and `additional_replicas` default to the pre-registered
    values. The regime probe and the noise-floor diagnostic override them to
    measure a candidate BEFORE the pre-registration is amended to adopt it;
    any caller that overrides them is running a different experiment and
    should say so wherever it prints.

    The arithmetic order -- baseline, then peak as baseline plus the additional
    rate, then k as their ratio -- is the order every previous copy used, kept
    so the consolidation changes no float in any shape. Two algebraically
    equal rewrites were rejected for exactly that reason: `k = 1 +
    additional_replicas / baseline_fraction`, and folding the two
    multiplications together as `peak = (baseline_fraction +
    additional_replicas) * saturation`. Both differ from this order in the
    last bit for several `(baseline_fraction, additional_replicas)` pairs on
    the placeholder curve -- `tests/test_traffic.py`'s bit-exact test pins
    two of them -- and a one-ulp change in `k` can flip a single candidate's
    accept/reject in `autoscale.arrivals.arrival_times`'s thinning test,
    changing which timestamps land in the arrival trace.
    """
    for name, value, consequence in (
        (
            "sustain",
            sustain,
            (
                "a zero or negative sustain holds the peak for no time, so "
                "the run measures no spike, while an infinite or NaN "
                "sustain makes `ramp + sustain` in `rate_at` non-finite, so "
                "the elevated period never ends"
            ),
        ),
        (
            "baseline_fraction",
            baseline_fraction,
            (
                "a zero or negative baseline_fraction makes `baseline` "
                "zero or negative, so `k = peak / baseline` divides by "
                "zero or the spike inverts into a dip, while an infinite "
                "or NaN value poisons `baseline` and every rate computed "
                "from it"
            ),
        ),
        (
            "additional_replicas",
            additional_replicas,
            (
                "a zero or negative additional_replicas is not a spike -- "
                "peak would be at or below baseline, putting k at or below "
                "1 -- while an infinite or NaN value poisons `peak` and "
                "`k` with the same non-finite value"
            ),
        ),
    ):
        if isinstance(value, bool):
            raise TypeError(
                f"{name} is {value!r}, a bool; bool is a subclass of int in "
                "Python, so it passes both the finiteness and positivity "
                "checks below and would silently be treated as 0.0 or 1.0 "
                "seconds/fraction/replicas instead of being refused as the "
                "wrong type"
            )
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"{name} is {value!r}, which must be finite and positive; {consequence}"
            )
    saturation = saturation_rps(curve)
    baseline = baseline_fraction * saturation
    peak = baseline + additional_replicas * saturation
    return SpikeShape(
        kind=kind,
        baseline_rate=baseline,
        k=peak / baseline,
        ramp=sustain / 2 if kind == "ramp" else 0.0,
        sustain=sustain,
    )
