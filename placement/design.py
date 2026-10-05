"""The sweep's design: every value the second pre-registration step fixes.

One record, so the measurement plan swaps the placeholder for the registered
design in one place. `preregistered` is False until the values come from a
committed `docs/experiment-a4.md`; the sweep script refuses an unregistered
design unless told otherwise, for the reason it refuses unmeasured inputs.
"""

import math
from dataclasses import dataclass

from placement.evaluate import REGIMES

__all__ = ["Design"]


@dataclass(frozen=True)
class Design:
    n_models: int
    offered_gpus: float
    hot_fraction: float
    warmup: float
    mean_burst: float
    duty: float
    skews: tuple[float, ...]
    regimes: tuple[str, ...]
    repetitions: int
    slo_seconds: float
    pilot_traces: int
    seed: int
    preregistered: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "skews", tuple(self.skews))
        object.__setattr__(self, "regimes", tuple(self.regimes))
        if list(self.skews) != sorted(set(self.skews)):
            raise ValueError(
                f"skews must be distinct and ascending, got {self.skews}; the "
                "crossover is located between neighbouring grid points"
            )
        if not self.regimes or not set(self.regimes) <= set(REGIMES):
            raise ValueError(f"regimes must be drawn from {REGIMES}, got {self.regimes}")
        if not math.isfinite(self.slo_seconds) or self.slo_seconds <= 0:
            raise ValueError(f"slo_seconds must be finite and positive, got {self.slo_seconds!r}")
