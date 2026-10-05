"""A measured sample to draw from, resampled rather than fitted.

Artifact 2 draws cold-start lags the same way, through
`autoscale.coldstart_ecdf.LagDistribution`. That class is not reused: its
module imports `coldstart` when it loads, and nothing in `placement/` may load
`coldstart` (tests/test_placement_boundary.py). The idea is reused; the
dependency is not.

Resampling, not fitting, for artifact 2's reason: a parametric tail invents
structure the data does not show, and the swap-time tail is what decides how
badly swap treats cold tenants.
"""

import math
import random
from dataclasses import dataclass

__all__ = ["EmpiricalDistribution"]


@dataclass(frozen=True)
class EmpiricalDistribution:
    """Measured durations in seconds. `measured` is False for a placeholder.

    The flag exists for the reason `ServiceCurve.measured` does: a sweep run on
    invented numbers produces output that looks exactly like a real one, so the
    sweep script refuses an unmeasured input unless told otherwise.
    """

    samples: tuple[float, ...]
    measured: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))
        if not self.samples:
            raise ValueError(
                "an empirical distribution needs at least one sample; an empty "
                "one has nothing to draw, and a caller that defaulted it to zero "
                "would simulate swaps that cost nothing"
            )
        for i, v in enumerate(self.samples):
            if isinstance(v, bool) or not isinstance(v, int | float):
                # ValueError, not TypeError: every sibling check here raises
                # ValueError naming the index, so a caller catches one type.
                raise ValueError(  # noqa: TRY004
                    f"sample [{i}] is {v!r}, not a number; a bool passes "
                    "isinstance(v, int) and would be drawn as 0 or 1 seconds"
                )
            if not math.isfinite(v):
                raise ValueError(
                    f"sample [{i}] is {v!r}; a non-finite duration either raises "
                    "deep inside the event loop or, as +inf, parks a GPU forever"
                )
            if v < 0:
                raise ValueError(
                    f"sample [{i}] is {v!r}; a negative swap time would make a "
                    "GPU ready before its swap began"
                )

    def draw(self, rng: random.Random) -> float:
        """One value. The caller supplies `rng`, so a run is reproducible from one seed."""
        return rng.choice(self.samples)
