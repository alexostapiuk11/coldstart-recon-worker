"""The money view: a sized fleet in monthly dollars.

A fixed fleet runs all month, so monthly cost is M GPUs times the hours in a
month times the hourly rate. The crossover in dollars is the difference in M
between two strategies, priced the same way (August design §8).

The calendar constants are defined here rather than imported, because their
home, `coldstart.analysis.economics`, is artifact 1's module and `placement/`
may not load `coldstart`. tests/test_placement_money.py pins them equal to
artifact 1's, so the two artifacts cannot disagree about how long a month is.
"""

import math
from dataclasses import dataclass

__all__ = ["DAYS_PER_MONTH", "SECONDS_PER_HOUR", "Assumptions", "monthly_cost", "monthly_difference"]

SECONDS_PER_HOUR = 3600.0
DAYS_PER_YEAR = 365.0
DAYS_PER_MONTH = DAYS_PER_YEAR / 12.0
HOURS_PER_MONTH = 24.0 * DAYS_PER_MONTH


@dataclass(frozen=True)
class Assumptions:
    """Published beside the result, so a reader can substitute their own."""

    gpu_hourly_rate: float
    provenance: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.gpu_hourly_rate) or self.gpu_hourly_rate <= 0:
            raise ValueError(f"gpu_hourly_rate must be finite and positive, got {self.gpu_hourly_rate!r}")
        if not self.provenance.strip():
            raise ValueError(
                "provenance must say where the rate came from; an unlabelled "
                "illustrative rate reads as a quoted price"
            )


def monthly_cost(m: int, assumptions: Assumptions) -> float:
    if type(m) is not int or m < 0:
        raise ValueError(f"m must be a non-negative GPU count, got {m!r}")
    return m * HOURS_PER_MONTH * assumptions.gpu_hourly_rate


def monthly_difference(m_more: int, m_fewer: int, assumptions: Assumptions) -> float:
    """What the larger fleet costs per month over the smaller."""
    return monthly_cost(m_more, assumptions) - monthly_cost(m_fewer, assumptions)
