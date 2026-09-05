"""Artifact 1's measured cold-start distributions, as a resampling source.

The ONLY module in this package that imports `coldstart`. Everything else takes
plain numbers, which keeps the simulator testable without artifact 1's data on
disk and confines the pending harness extraction to one file.

Resampling, not fitting. Artifact 1 measured p95/p50 of about 1.2 on both arms;
fitting a parametric tail to that would invent structure the data does not show,
and the tail is exactly where an autoscaling simulation is most sensitive.
"""

import random
from dataclasses import dataclass

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    annotate_first_touch,
    partition,
)
from coldstart.store import JsonlStore

__all__ = ["LagDistribution", "load_measured_lags"]


@dataclass
class LagDistribution:
    """An empirical distribution of scale-up lag, in seconds.

    `samples` is the measured population itself, not summary statistics: a draw
    returns a value the campaign actually observed or it returns nothing.
    """

    samples: list[float]

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(
                "a lag distribution needs at least one sample; an empty one "
                "would make every scale-up instantaneous and silently turn the "
                "simulation into a no-cold-start baseline"
            )

    def sample(self, rng: random.Random) -> float:
        """One draw. `rng` is supplied by the caller so a whole simulation run
        is reproducible from a single seed."""
        return rng.choice(self.samples)

    def median(self) -> float:
        ordered = sorted(self.samples)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2


def load_measured_lags(store_path: str) -> dict[str, LagDistribution]:
    """Artifact 1's per-arm lag distributions, keyed by arm.

    Repeat-host runs only. Artifact 1's one first-touch run took 2266.6 s
    against a 39-96 s norm because the host had never pulled the image; it is
    a platform event, not a cold start, and artifact 1 excluded it from its own
    ECDF on a mechanical first-on-its-host rule applied to every run. The same
    rule applies here. Host novelty is carried as a named risk and recorded per
    replica during validation instead.
    """
    records = JsonlStore(store_path).read_all()
    rows = annotate_first_touch([derive(r) for r in records])
    publishable = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable

    by_arm: dict[str, list[float]] = {}
    for row in publishable:
        if row.get("first_touch") is not False:
            continue
        by_arm.setdefault(row["arm"], []).append(row["t_total"])
    return {arm: LagDistribution(samples=vals) for arm, vals in by_arm.items()}
