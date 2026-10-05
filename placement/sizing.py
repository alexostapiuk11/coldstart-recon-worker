"""Fleet sizing: the smallest M at which a strategy meets the SLO.

The SLO is a p99 target that every popularity decile must meet, where a
decile's p99 is the median across repetitions of its per-repetition p99. That
is artifact 2's estimand: the p99 a typical run delivers.

Sizing is done once per grid point over a set of repetitions, not once per
repetition (amendment §7). The bootstrap in `crossover` calls this with
resampled repetition ids, duplicates included, to put the uncertainty into the
sizing itself.
"""

import math
from collections.abc import Sequence

from harness.stats import median
from placement.evaluate import ConfigOutcome, PointEvaluation
from placement.fleet import STRATEGIES
from placement.traffic import DECILES

__all__ = ["size", "sized_fleet"]


def size(outcomes: Sequence[ConfigOutcome], reps: Sequence[int], slo: float) -> int | None:
    """The smallest M in `outcomes` that meets `slo` in every decile.

    None means dominated: no configuration up to dedicate's M meets the SLO.
    """
    if not math.isfinite(slo) or slo <= 0:
        raise ValueError(f"slo must be a finite, positive number of seconds, got {slo!r}")
    if not reps:
        raise ValueError("sizing needs at least one repetition")
    ms = [o.m for o in outcomes]
    if ms != sorted(ms):
        raise ValueError(
            f"configurations must come in ascending M, got {ms}; out of order, "
            "the first to meet the SLO is not the cheapest"
        )
    for outcome in outcomes:
        meets = True
        for d in range(DECILES):
            values = [outcome.decile_p99s[r][d] for r in reps]
            if any(v is None for v in values):
                raise ValueError(
                    f"decile {d} is under the p99 floor in a repetition; the grid "
                    "point is not evaluable and must be excluded before sizing"
                )
            if median(values) > slo:
                meets = False
                break
        if meets:
            return outcome.m
    return None


def sized_fleet(
    evaluation: PointEvaluation, reps: Sequence[int], slo: float
) -> dict[str, int | None] | None:
    """Sized M per strategy, or None when the grid point is not evaluable.

    Not evaluable means some decile missed the p99 floor in some repetition.
    Publishing that decile from the repetitions that did clear it would keep
    the runs that happened to send more traffic to the cold tail (§8).
    """
    if not evaluation.floor_met:
        return None
    return {strategy: size(evaluation.outcomes[strategy], reps, slo) for strategy in STRATEGIES}
