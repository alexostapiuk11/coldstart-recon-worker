"""Where the cheapest SLO-meeting strategy changes along the skew axis.

Sizing is once per grid point, so a strategy's cost there is one integer M,
not a per-repetition sample. A paired difference of per-repetition costs would
have zero width. The uncertainty lives in the sizing, so the interval comes
from resampling repetitions and re-sizing every strategy inside each draw,
then re-locating the crossover (amendment §8). This is the approach artifact
2's gap interval takes through its frontier selection.

A crossover is reported as the pair of adjacent evaluable grid points it lies
between. Cost is integer M, and interpolating between grid points would invent
precision the sizing does not have.
"""

import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# Private in the shared module, and imported rather than copied: it is the one
# percentile-method endpoint computation every interval in this publication
# uses, and a local copy would be a third implementation of it.
from harness.stats import MIN_BOOTSTRAP_SAMPLES, _percentile_interval
from placement.evaluate import PointEvaluation
from placement.sizing import sized_fleet

__all__ = ["CrossoverEstimate", "cheapest", "choices", "crossings", "estimate_crossover"]

Choice = frozenset[str] | None  # None: grid point not evaluable


def cheapest(sized: dict[str, int | None]) -> frozenset[str]:
    """The strategies tied for the smallest sized M. Empty when all are dominated."""
    feasible = {s: m for s, m in sized.items() if m is not None}
    if not feasible:
        return frozenset()
    best = min(feasible.values())
    return frozenset(s for s, m in feasible.items() if m == best)


def choices(evaluations: Sequence[PointEvaluation], reps: Sequence[int], slo: float) -> list[Choice]:
    out: list[Choice] = []
    for evaluation in evaluations:
        sized = sized_fleet(evaluation, reps, slo)
        out.append(None if sized is None else cheapest(sized))
    return out


def crossings(chosen: Sequence[Choice]) -> tuple[tuple[int, int], ...]:
    """Adjacent pairs of located grid points whose cheapest set differs.

    A point is located when it is evaluable and some strategy meets the SLO
    there. Points that are not are skipped, so a crossing is between the two
    nearest located points on either side of it.
    """
    located = [(i, c) for i, c in enumerate(chosen) if c]
    return tuple(
        (i, j) for (i, a), (j, b) in itertools.pairwise(located) if a != b
    )


@dataclass(frozen=True)
class CrossoverEstimate:
    chosen: tuple[Choice, ...]  # cheapest strategies per grid point, all repetitions
    point: tuple[tuple[int, int], ...]  # crossings on all repetitions
    iterations: int
    no_crossing: int  # draws with none in the swept range
    one_crossing: int
    many_crossings: int
    # Percentile-method bounds on the lower grid index of the crossing, over
    # the draws with exactly one. None when too few draws located one.
    interval: tuple[int, int] | None


def estimate_crossover(
    evaluations: Sequence[PointEvaluation],
    slo: float,
    iterations: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> CrossoverEstimate:
    """Evaluations must be one locality regime, in ascending skew."""
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    skews = [e.point.s for e in evaluations]
    if skews != sorted(skews) or len({e.point.regime for e in evaluations}) != 1:
        raise ValueError("evaluations must be one regime, in ascending skew")
    reps = {e.repetitions for e in evaluations}
    if len(reps) != 1:
        raise ValueError(f"every grid point needs the same repetition count, got {sorted(reps)}")
    (n,) = reps
    if n < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{n} repetitions; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES}, or it is an artifact of a thin sample"
        )
    everything = list(range(n))
    chosen = choices(evaluations, everything, slo)
    rng = random.Random(seed)
    counts = {0: 0, 1: 0, 2: 0}
    located: list[float] = []
    for _ in range(iterations):
        # One resample of repetition ids for every strategy at every grid
        # point, so the pairing through common traces survives the resample.
        draw = [rng.randrange(n) for _ in everything]
        found = crossings(choices(evaluations, draw, slo))
        counts[min(len(found), 2)] += 1
        if len(found) == 1:
            located.append(float(found[0][0]))
    interval = None
    if located:
        try:
            lo, hi = _percentile_interval(located, alpha)
        except ValueError:
            # Too few single-crossing draws for this alpha. The counts above
            # are published beside the estimate, and they say why.
            interval = None
        else:
            interval = (math.floor(lo), math.floor(hi))
    return CrossoverEstimate(
        chosen=tuple(chosen),
        point=crossings(chosen),
        iterations=iterations,
        no_crossing=counts[0],
        one_crossing=counts[1],
        many_crossings=counts[2],
        interval=interval,
    )
