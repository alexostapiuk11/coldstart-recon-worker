"""The open-loop gate's operating point, and the one schedule its repeats replay.

Spec §10 fixes the gate's rules (`autoscale/validation.py`) but not where it
is run: how many replicas, which spike, how the schedule ends. These constants
are that choice, pre-registered in docs/experiment-a2.md (amendment
2026-10-04) and pinned to it by tests/test_prereg_a2_plan2b.py.

The shape is the frontiers' own step, `traffic.spike_shape`, with the
baseline multiplied by the replica count. The pre-registered rates are ONE
replica's, so unscaled, two pinned replicas would run at half the per-replica
load the frontiers are computed at, and the gate would validate a regime the
results never use. Scaling keeps `k`, the sustain and the ramp unchanged.

The schedule ends in a drain tail: no arrival in the last
`VALIDATION_DRAIN_SECONDS` before `until`, so the final requests finish inside
the window. Without it the last bins are censored on purpose, which costs
judged bins against the 10-bin minimum, or censored on one side only, which is
an unbounded miss the design created rather than the model (plan 2a's
whole-implementation review). The builder also refuses a schedule the
simulator predicts would leave work unfinished at `until`. That checks the
schedule, not the model: a schedule built to censor its own tail cannot test
anything there.
"""

import math
import random

from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.stats import percentiles
from autoscale.traffic import spike_shape

__all__ = [
    "LATENCY_SOURCE", "VALIDATION_DRAIN_SECONDS", "VALIDATION_KIND", "VALIDATION_REPLICAS",
    "VALIDATION_SEED", "VALIDATION_UNTIL", "WARMUP_MAX_SECONDS", "WARMUP_MIN_SECONDS",
    "WARMUP_RPS", "build_schedule", "schedule_facts", "validation_shape",
]

VALIDATION_REPLICAS = 2
VALIDATION_KIND = "step"
VALIDATION_UNTIL = 400.0
VALIDATION_DRAIN_SECONDS = 30.0
VALIDATION_SEED = 20261004
# The gate judges the engine's own latency, stamped by worker/a2_middleware.py:
# it is the quantity the simulator models. Client latency adds the WAN and the
# load balancer, which no part of the model represents; it is recorded per
# request and published beside the verdict, not judged.
LATENCY_SOURCE = "server"
WARMUP_RPS = 20.0
WARMUP_MIN_SECONDS = 30.0
WARMUP_MAX_SECONDS = 900.0


def validation_shape(curve: ServiceCurve, *, replicas: int, kind: str) -> SpikeShape:
    if type(replicas) is not int or replicas < 1:
        raise ValueError(
            f"replicas is {replicas!r}; the pinned fleet is a positive int, and a scaled rate "
            "for a fractional fleet is a load no endpoint can be pinned to"
        )
    one = spike_shape(curve, kind)
    return SpikeShape(kind=one.kind, baseline_rate=one.baseline_rate * replicas, k=one.k,
                      ramp=one.ramp, sustain=one.sustain)


def build_schedule(curve: ServiceCurve, *, replicas: int, kind: str, until: float,
                   drain: float, seed: int) -> tuple[float, ...]:
    """The one schedule: arrivals drawn over `until - drain`, so none lands in the tail.

    Why `until - drain` and not `until`: the last requests need time to finish
    inside the window. Why the simulator check on top of the drain: a drain
    length is a guess about latency, and trusting it would let a slow curve or
    a heavy load quietly censor the final bins; running the model against the
    schedule makes that a refusal. Rejected: truncating a full-window schedule,
    which leaves the rate shape cut off mid-stream rather than ended on purpose.
    """
    if not (math.isfinite(until) and math.isfinite(drain)) or drain <= 0 or drain >= until:
        raise ValueError(
            f"drain {drain!r} with window {until!r}: the drain must be positive and shorter "
            "than the window, or the schedule is empty or has no tail to drain into"
        )
    shape = validation_shape(curve, replicas=replicas, kind=kind)
    arrivals = arrival_times(shape, until - drain, random.Random(seed))
    if not arrivals:
        raise ValueError("the schedule drew no arrivals; a validation run of nothing judges nothing")
    result = run_fixed_capacity(list(arrivals), replicas, curve, until)
    if result.unfinished:
        raise ValueError(
            f"the simulator predicts {result.unfinished} requests unfinished at {until:g} s for "
            f"this schedule; its final bins would be censored by design. Lengthen the drain or "
            "lower the load"
        )
    return tuple(arrivals)


def schedule_facts(schedule, curve: ServiceCurve, *, replicas: int, until: float,
                   drain: float = VALIDATION_DRAIN_SECONDS) -> dict:
    """What the amendment states about the schedule, computed, not typed.

    `mean_rps` divides by the arrival window `until - drain`, the span the
    arrivals were drawn over, not by the last arrival's timestamp.
    """
    result = run_fixed_capacity(list(schedule), replicas, curve, until)
    bins = [0] * math.ceil(until / 10.0)
    for t in schedule:
        bins[min(int(t // 10.0), len(bins) - 1)] += 1
    pct = percentiles(result.latencies, want=("p50", "p99"))
    return {
        "requests": len(schedule),
        "last_arrival_s": max(schedule),
        "mean_rps": len(schedule) / (until - drain),
        "peak_bin_rps": max(bins) / 10.0,
        "bins_with_20_requests": sum(1 for b in bins if b >= 20),
        "predicted_p50_s": pct["p50"],
        "predicted_p99_s": pct["p99"],
        "predicted_unfinished": result.unfinished,
    }
