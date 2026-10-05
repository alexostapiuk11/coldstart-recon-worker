"""Latency of a co-located model as a function of two loads.

`autoscale.service.ServiceCurve` is indexed by one concurrency. A co-located
model's latency depends on its own load and on its neighbour's, because the two
engines contend for compute and memory bandwidth rather than a cleanly divided
resource (August design §5.2). So the measured object is a surface: latency at
each (own, neighbour) grid point, interpolated bilinearly between them.

Bilinear rather than anything smoother, for the reason `ServiceCurve` gives for
linear: a smoother fit invents curvature between measured points.

At the grid's edges, queries are clamped, not extrapolated, matching
`ServiceCurve`. `is_extrapolating` reports when a query went above the grid, so
the simulator can count it instead of hiding it.
"""

import bisect
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["ColocatedSurface"]


def _grid(values: Sequence[float], name: str) -> tuple[float, ...]:
    xs = tuple(float(v) for v in values)
    if len(xs) < 2:
        raise ValueError(f"{name} needs at least two points to interpolate between")
    for v in xs:
        if not math.isfinite(v) or v < 0:
            raise ValueError(
                f"{name} contains {v!r}; a load is a finite, non-negative "
                "concurrency, and anything else poisons the interpolation"
            )
    if any(b <= a for a, b in itertools.pairwise(xs)):
        raise ValueError(
            f"{name} must be strictly ascending; a repeated point makes the "
            "interpolation divide by zero for any query landing on it"
        )
    return xs


def _bracket(grid: tuple[float, ...], x: float) -> tuple[int, float]:
    """Index i and fraction f with x = grid[i] + f * (grid[i+1] - grid[i]),
    clamped to the grid."""
    if x <= grid[0]:
        return 0, 0.0
    if x >= grid[-1]:
        return len(grid) - 2, 1.0
    i = bisect.bisect_right(grid, x) - 1
    return i, (x - grid[i]) / (grid[i + 1] - grid[i])


@dataclass(frozen=True)
class ColocatedSurface:
    """`latency[i][j]` is the latency in seconds of one request of a model at
    own concurrency `own[i]` while its neighbour runs at `neighbour[j]`.

    The neighbour-0 column is the solo-at-split curve: one engine, the other
    idle but resident. `measured` is False for a placeholder.
    """

    own: tuple[float, ...]
    neighbour: tuple[float, ...]
    latency: tuple[tuple[float, ...], ...]
    measured: bool

    def __post_init__(self) -> None:
        own = _grid(self.own, "own")
        neighbour = _grid(self.neighbour, "neighbour")
        rows = tuple(tuple(float(v) for v in row) for row in self.latency)
        if len(rows) != len(own) or any(len(row) != len(neighbour) for row in rows):
            raise ValueError(
                f"latency must be {len(own)} rows of {len(neighbour)} values, one "
                "per (own, neighbour) grid point; a ragged table would pair "
                "latencies with the wrong loads"
            )
        for row in rows:
            for v in row:
                if not math.isfinite(v) or v < 0:
                    raise ValueError(f"latency contains {v!r}; it must be finite and non-negative")
        object.__setattr__(self, "own", own)
        object.__setattr__(self, "neighbour", neighbour)
        object.__setattr__(self, "latency", rows)

    @property
    def max_own_concurrency(self) -> float:
        """The most requests one co-located model was measured serving. The
        simulator caps a pair GPU's per-model load here, as artifact 2 caps a
        replica at its curve's top measured concurrency."""
        return self.own[-1]

    def is_extrapolating(self, own: float, neighbour: float) -> bool:
        if math.isnan(own) or math.isnan(neighbour):
            raise ValueError("a NaN load compares False against both grid bounds")
        return own > self.own[-1] or neighbour > self.neighbour[-1]

    def latency_at(self, own: float, neighbour: float) -> float:
        if math.isnan(own) or math.isnan(neighbour):
            raise ValueError(
                "a NaN load compares False against every grid bound and would "
                "return a plausible latency computed from nothing"
            )
        i, fi = _bracket(self.own, own)
        j, fj = _bracket(self.neighbour, neighbour)
        z = self.latency
        return (
            z[i][j] * (1 - fi) * (1 - fj)
            + z[i + 1][j] * fi * (1 - fj)
            + z[i][j + 1] * (1 - fi) * fj
            + z[i + 1][j + 1] * fi * fj
        )
