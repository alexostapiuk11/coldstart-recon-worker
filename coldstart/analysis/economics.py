"""Business-framing metrics — spec 7: every finding travels in dollars as well as
seconds. Pure functions over data already collected elsewhere in this package;
no I/O, no records, no extra runs.
"""

import math
from dataclasses import dataclass

SECONDS_PER_HOUR = 3600.0

# DAYS_PER_YEAR is the calendar year used to annualize a per-event cost.
# DAYS_PER_MONTH is derived from it, rather than a bare round 30.0, so that
# "events/day" and "events/year" figures agree on how long a month is. A bare
# 30.0 would understate DAYS_PER_MONTH by ~1.4% against 365/12 — a small,
# silent, systematic bias in exactly the numbers this module hands to a
# budget owner, and there is no economic reason for a "month" here to mean
# something different from one twelfth of the "year" used two lines above.
DAYS_PER_YEAR = 365.0
DAYS_PER_MONTH = DAYS_PER_YEAR / 12.0


@dataclass(frozen=True)
class Assumptions:
    """Published in the post so a reader can substitute their own — see spec 7.

    Validated at construction: every field here feeds a number that gets
    published, so a nonsensical assumption (a negative price, a zero context
    length) must fail the moment it's constructed rather than propagate
    silently into a wrong headline figure several calls later.
    """

    gpu_hourly_rate: float
    scale_ups_per_day: float
    steady_state_tokens_per_sec: float
    volume_monthly_cost: float
    assumed_context_length: int

    def __post_init__(self) -> None:
        if self.gpu_hourly_rate <= 0:
            raise ValueError(f"gpu_hourly_rate must be positive, got {self.gpu_hourly_rate!r}")
        if self.scale_ups_per_day <= 0:
            raise ValueError(
                f"scale_ups_per_day must be positive, got {self.scale_ups_per_day!r}"
            )
        if self.steady_state_tokens_per_sec <= 0:
            raise ValueError(
                "steady_state_tokens_per_sec must be positive, got "
                f"{self.steady_state_tokens_per_sec!r}"
            )
        if self.volume_monthly_cost < 0:
            raise ValueError(
                f"volume_monthly_cost must be non-negative, got {self.volume_monthly_cost!r}"
            )
        if self.assumed_context_length <= 0:
            raise ValueError(
                f"assumed_context_length must be positive, got {self.assumed_context_length!r}"
            )


def _require_finite_non_negative(value: float, name: str) -> None:
    """Fail loudly: a negative or non-finite value here would silently poison
    a published dollar or token figure rather than crash where the bad data
    actually entered."""
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite, non-negative number, got {value!r}")


def foregone_tokens(t_fast: float, assumptions: Assumptions) -> float:
    """Output the replica could have produced while starting or still slow."""
    _require_finite_non_negative(t_fast, "t_fast")
    return t_fast * assumptions.steady_state_tokens_per_sec


def cost_per_scale_up(t_fast: float, assumptions: Assumptions) -> float:
    _require_finite_non_negative(t_fast, "t_fast")
    return (t_fast / SECONDS_PER_HOUR) * assumptions.gpu_hourly_rate


def annual_cost(cost_per_event: float, assumptions: Assumptions) -> float:
    return cost_per_event * assumptions.scale_ups_per_day * DAYS_PER_YEAR


def supported_concurrency(kv_capacity_tokens: int, assumptions: Assumptions) -> int:
    """Always reported with its assumed context length attached.

    A KV cache smaller than one context is a real, if degenerate, deployment
    state — it returns 0 rather than raising. A negative capacity cannot come
    from measuring a real cache, so it fails loudly instead of floor-dividing
    into a nonsensical negative concurrency.
    """
    if kv_capacity_tokens < 0:
        raise ValueError(f"kv_capacity_tokens must be non-negative, got {kv_capacity_tokens!r}")
    return kv_capacity_tokens // assumptions.assumed_context_length


def compile_cache_term(s4b_cold: float, s4b_warm: float) -> float:
    """T_compile — the cost of a cold compile cache."""
    return s4b_cold - s4b_warm


def break_even_events_per_day(
    seconds_saved: float, standing_monthly_cost: float, assumptions: Assumptions
) -> float:
    """Scale-up frequency at which a cache pays for the cost of keeping it warm.

    Below this, the cache costs more than it saves. This is the number a
    platform lead actually wants — "does caching help" is not a decision,
    "at what volume does it pay for itself" is.

    `seconds_saved` may legitimately be negative — a cache that made cold
    starts slower is a real, if unfortunate, measurement, not invalid input —
    so it is folded into the same "never breaks even" branch as zero, rather
    than raising.
    """
    if not math.isfinite(seconds_saved):
        raise ValueError(f"seconds_saved must be finite, got {seconds_saved!r}")
    _require_finite_non_negative(standing_monthly_cost, "standing_monthly_cost")
    if seconds_saved <= 0:
        return float("inf")
    saving_per_event = (seconds_saved / SECONDS_PER_HOUR) * assumptions.gpu_hourly_rate
    events_per_month = standing_monthly_cost / saving_per_event
    return events_per_month / DAYS_PER_MONTH
