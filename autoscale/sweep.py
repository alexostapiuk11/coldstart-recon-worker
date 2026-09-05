"""The threshold sweep: one controller, every signal, both shapes, both
measured lag distributions.

Repetitions are fixed at 30 per configuration by the pre-registration, before
any result was inspected, so the count cannot be chosen to make an interval
land where it is wanted.
"""

import hashlib
import math
import random
from dataclasses import dataclass

from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.frontier import PolicyPoint
from autoscale.service import ServiceCurve
from autoscale.signals import SIGNALS
from autoscale.sim import run_with_policy

__all__ = ["SweepConfig", "run_sweep"]

REPETITIONS = 30
COOLDOWN_SECONDS = 30.0
EVALUATE_EVERY_SECONDS = 5.0
MAX_REPLICAS = 12


def _derive_seed(seed: int, signal: str, up: float, down: float, rep: int) -> int:
    """A per-configuration seed that is stable ACROSS PROCESSES.

    Not `hash((seed, signal, up, down, rep))`: Python randomizes string hashing
    per process unless PYTHONHASHSEED is set, so a hash-derived seed would give
    a different sweep on every invocation while looking deterministic inside any
    single run -- including inside the test that checks reproducibility. The
    artifact's whole claim is that a reader re-running this gets these numbers.
    """
    key = f"{seed}|{signal}|{up}|{down}|{rep}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def _require_measured_curve(curve: ServiceCurve, allow_unmeasured: bool) -> None:
    """The artifact's whole claim is that every parameter is measured and only
    the control loop is modeled. Until plan 2's hardware sweep runs, the service
    curve is invented placeholder points; a sweep against them produces
    frontiers that look exactly like real ones. The flag is not a comment --
    reaching a result from unmeasured points requires typing
    `allow_unmeasured=True`, which is greppable in a way a stale comment is not.
    """
    if curve.measured or allow_unmeasured:
        return
    raise ValueError(
        "refusing to sweep against an unmeasured service curve. These points "
        "are invented placeholders and the frontiers derived from them would "
        "be indistinguishable from measured ones in every output format. Pass "
        "allow_unmeasured=True to run a layout or plumbing check against them."
    )


# PER-SIGNAL THRESHOLD GRIDS. The three signals do not share units, so one
# numeric grid cannot span all three:
#
#   queue_depth            requests waiting per replica     0 .. unbounded
#   in_flight_concurrency  active requests per replica      0 .. max_measured_concurrency
#   utilization            a FRACTION                       0 .. 1
#
# Sweeping the single grid (2, 4, 8, 16) across all three -- the original
# design -- puts every threshold above utilization's maximum possible value, so
# that policy never fires and its whole frontier collapses to one "never scale"
# point. H2 ("utilization is worst") would then be confirmed trivially by a
# units mismatch rather than by the censoring mechanism the artifact publishes,
# which would make the headline indefensible.
#
# This is NOT the per-signal tuning the design rejects. That rejection is about
# refusing to hand-pick each signal's best operating point; giving each signal a
# grid that spans its own range is what makes the frontiers comparable at all.
# The grids are pre-registered in docs/experiment-a2.md before any sweep runs,
# so they cannot be chosen to produce a result.
THRESHOLDS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    # signal: (scale_up_grid, scale_down_grid)
    "queue_depth": ((1.0, 2.0, 4.0, 8.0, 16.0), (0.0, 0.25, 0.5, 1.0)),
    "in_flight_concurrency": ((2.0, 4.0, 8.0, 12.0, 16.0), (0.5, 1.0, 2.0, 4.0)),
    "utilization": ((0.50, 0.65, 0.80, 0.90, 0.95), (0.05, 0.15, 0.30, 0.50)),
}


@dataclass(frozen=True)
class SweepConfig:
    shape: SpikeShape
    lags: LagDistribution
    curve: ServiceCurve
    arm: str
    until: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.until) or self.until <= 0:
            # `arrival_times` refuses a non-finite or negative window itself,
            # but only after the sweep has already entered its innermost loop,
            # and it ACCEPTS `until=0.0`: every repetition would then draw an
            # empty trace, be discarded as "empty_trace", and `run_sweep` would
            # return an empty point list with a full discard log -- a sweep
            # that ran nothing, reported as a sweep whose every run was
            # excluded by a pre-registered rule.
            raise ValueError(
                f"until is {self.until!r}; a sweep window must be a finite, "
                "positive number of seconds. A zero window produces an empty "
                "arrival trace for every repetition, so the whole sweep would "
                "return no points and a discard log implying the exclusion "
                "rules fired"
            )
        if not self.arm:
            # `arm` is the label the published frontier carries -- which
            # measured lag distribution this sweep was run against. An empty
            # one produces a figure whose arm cannot be identified from the
            # data, and arm A vs arm C is the entire H3 comparison.
            raise ValueError(
                "arm is empty; it labels which measured lag distribution the "
                "sweep ran against, and arm A vs arm C is the whole H3 "
                "comparison -- an unlabelled frontier cannot be attributed to "
                "either"
            )


def run_sweep(
    config: SweepConfig, seed: int, allow_unmeasured: bool = False
) -> tuple[list[PolicyPoint], list[str]]:
    """Every (signal, up, down) combination, `REPETITIONS` times each.

    Returns the policy points and the discard reasons encountered. Discards are
    returned rather than dropped so the count can be published per signal, as
    the pre-registration requires -- which is why each entry is
    `"{signal}:{reason}"` rather than the bare reason. A flat list of reasons
    cannot be split by signal after the fact, so the promise in this docstring
    would have been unkeepable and "reported by signal" would have quietly
    become "reported in total".

    `cost` and `p99` are the MEAN across repetitions of each run's own value.
    For p99 that is deliberately a mean of per-run tail statistics, not the p99
    of the pooled latencies: pooling estimates the tail of the mixture over
    runs (dominated by the few worst runs, and weighting each run by how many
    requests it happened to complete), whereas the design here is 30 equally
    weighted repetitions of one configuration, whose estimand is the p99 a
    typical run of that policy delivers. The pre-registration fixes the
    repetition count but not the aggregator, so this choice is documented here
    and reported alongside the frontiers.
    """
    _require_measured_curve(config.curve, allow_unmeasured)
    points: list[PolicyPoint] = []
    discards: list[str] = []

    for signal in sorted(SIGNALS):
        up_grid, down_grid = THRESHOLDS[signal]
        for up in up_grid:
            for down in down_grid:
                # `Controller` refuses `scale_down_at >= scale_up_at` outright
                # (overlapping thresholds oscillate), so these combinations are
                # skipped rather than run and discarded. Every signal's grid
                # still leaves valid combinations: 19 for queue_depth, 17 for
                # in_flight_concurrency, 19 for utilization.
                if down >= up:
                    continue
                costs: list[float] = []
                p99s: list[float] = []
                for rep in range(REPETITIONS):
                    rng = random.Random(_derive_seed(seed, signal, up, down, rep))
                    arrivals = arrival_times(config.shape, until=config.until, rng=rng)
                    if not arrivals:
                        discards.append(f"{signal}:empty_trace")
                        continue
                    result = run_with_policy(
                        arrivals=arrivals,
                        signal=signal,
                        controller=Controller(
                            scale_up_at=up,
                            scale_down_at=down,
                            cooldown=COOLDOWN_SECONDS,
                            max_replicas=MAX_REPLICAS,
                        ),
                        lags=config.lags,
                        curve=config.curve,
                        until=config.until,
                        evaluate_every=EVALUATE_EVERY_SECONDS,
                        rng=rng,
                    )
                    if result.discard_reason:
                        discards.append(f"{signal}:{result.discard_reason}")
                        continue
                    costs.append(result.replica_seconds)
                    p99s.append(result.percentiles()["p99"])
                if not costs:
                    continue
                points.append(
                    PolicyPoint(
                        cost=sum(costs) / len(costs),
                        p99=sum(p99s) / len(p99s),
                        signal=signal,
                        scale_up_at=up,
                        scale_down_at=down,
                    )
                )
    return points, discards
