"""Business-framing metrics — spec 7: every finding travels in dollars as well as
seconds. Pure functions over data already collected elsewhere in this package;
no I/O, no records, no extra runs.
"""

import math
from dataclasses import dataclass

SECONDS_PER_HOUR = 3600.0

# DAYS_PER_MONTH is derived from DAYS_PER_YEAR (rather than a bare round 30.0)
# so "events/day" and "events/year" figures agree on how long a month is.
DAYS_PER_YEAR = 365.0
DAYS_PER_MONTH = DAYS_PER_YEAR / 12.0


def _require_finite(value: float, name: str) -> None:
    """Fail loudly: NaN and inf compare False against every ordering operator,
    so without this a non-finite value slides past every `<=`/`<` check below
    and silently poisons a published figure. Same pattern as
    coldstart/checks.py's `_validate_clock_inputs`, reimplemented here because
    the required range differs per call site (positive-only, non-negative, or
    unconstrained)."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _require_finite_non_negative(value: float, name: str) -> None:
    _require_finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value!r}")


def _require_finite_positive(value: float, name: str) -> None:
    _require_finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


@dataclass(frozen=True)
class Assumptions:
    """Published in the post so a reader can substitute their own — see spec 7.

    Validated at construction: every field feeds a number that gets
    published, so a nonsensical assumption (negative, zero where positive is
    required, or NaN/inf) must fail the moment it's constructed rather than
    propagate silently into a wrong headline figure several calls later.
    """

    gpu_hourly_rate: float
    scale_ups_per_day: float
    steady_state_tokens_per_sec: float
    volume_monthly_cost: float
    assumed_context_length: int
    # Optional: unlocks foregone_token_value / total_cost_per_scale_up. Spec
    # line 713 prices a scale-up event's cost as GPU rental *plus* the value
    # of foregone tokens, but publishes no token price among its three
    # standard assumptions — so this stays unset, and those two functions
    # stay unusable, until a reader supplies one.
    output_token_price_per_million: float | None = None

    def __post_init__(self) -> None:
        _require_finite_positive(self.gpu_hourly_rate, "gpu_hourly_rate")
        _require_finite_positive(self.scale_ups_per_day, "scale_ups_per_day")
        _require_finite_positive(
            self.steady_state_tokens_per_sec, "steady_state_tokens_per_sec"
        )
        _require_finite_non_negative(self.volume_monthly_cost, "volume_monthly_cost")
        _require_finite_positive(self.assumed_context_length, "assumed_context_length")
        if self.output_token_price_per_million is not None:
            _require_finite_non_negative(
                self.output_token_price_per_million, "output_token_price_per_million"
            )


def foregone_tokens(t_fast: float, assumptions: Assumptions) -> float:
    """Output the replica could have produced while starting or still slow."""
    _require_finite_non_negative(t_fast, "t_fast")
    return t_fast * assumptions.steady_state_tokens_per_sec


def gpu_cost_per_scale_up(t_fast: float, assumptions: Assumptions) -> float:
    """The GPU-rental share of a scale-up event's cost — not the total.

    See `total_cost_per_scale_up` for GPU cost plus foregone-token value,
    which is what spec line 713 actually defines "cost per scale-up event"
    to mean.
    """
    _require_finite_non_negative(t_fast, "t_fast")
    return (t_fast / SECONDS_PER_HOUR) * assumptions.gpu_hourly_rate


def foregone_token_value(t_fast: float, assumptions: Assumptions) -> float:
    """Dollar value of the tokens `foregone_tokens` counts — spec line 713's
    second cost term.

    Requires `assumptions.output_token_price_per_million`; raises rather than
    silently pricing the tokens at zero, which would be indistinguishable
    from "priced at zero" actually being the assumption.
    """
    if assumptions.output_token_price_per_million is None:
        raise ValueError(
            "foregone_token_value requires assumptions.output_token_price_per_million "
            "to be set"
        )
    tokens = foregone_tokens(t_fast, assumptions)
    return tokens * (assumptions.output_token_price_per_million / 1_000_000.0)


def total_cost_per_scale_up(t_fast: float, assumptions: Assumptions) -> float:
    """GPU rental cost plus the value of foregone tokens — spec line 713's
    full definition of a scale-up event's cost. Raises under the same
    condition as `foregone_token_value`."""
    return gpu_cost_per_scale_up(t_fast, assumptions) + foregone_token_value(t_fast, assumptions)


def annual_cost(cost_per_event: float, assumptions: Assumptions) -> float:
    """Annualizes a per-event cost over the calendar year (`DAYS_PER_YEAR`,
    365 days), not by compounding `DAYS_PER_MONTH` twelve times — stated
    explicitly so "annual" doesn't silently mean whichever convention a
    reader assumes. (The two are numerically equal here since
    `DAYS_PER_MONTH = DAYS_PER_YEAR / 12`, but this function doesn't rely on
    that; it uses `DAYS_PER_YEAR` directly.)
    """
    _require_finite_non_negative(cost_per_event, "cost_per_event")
    return cost_per_event * assumptions.scale_ups_per_day * DAYS_PER_YEAR


def supported_concurrency(kv_capacity_tokens: int, assumptions: Assumptions) -> int:
    """Always reported with its assumed context length attached.

    A KV cache smaller than one context is a real, if degenerate, deployment
    state — it returns 0 rather than raising. A negative or non-finite
    capacity cannot come from measuring a real cache, so those fail loudly
    instead of floor-dividing into a nonsensical negative concurrency.
    `kv_capacity_tokens` may arrive as a float (parsed vLLM log output), so
    the result is coerced back to `int` to honor the return type.
    """
    _require_finite_non_negative(kv_capacity_tokens, "kv_capacity_tokens")
    return int(kv_capacity_tokens // assumptions.assumed_context_length)


def compile_cache_term(s4b_cold: float, s4b_warm: float) -> float:
    """T_compile — the cost of a cold compile cache.

    May legitimately be negative or zero (measurement noise can make a
    "warm" run look no faster than, or even slower than, "cold") — that's a
    real result and is returned as-is. Non-finite inputs are not a real
    measurement, though, and fail loudly rather than propagating a NaN into
    a downstream break-even figure.
    """
    _require_finite(s4b_cold, "s4b_cold")
    _require_finite(s4b_warm, "s4b_warm")
    return s4b_cold - s4b_warm


def break_even_events_per_day(
    seconds_saved: float,
    assumptions: Assumptions,
    standing_monthly_cost: float | None = None,
    *,
    include_foregone_tokens: bool = False,
) -> float:
    """Scale-up frequency at which the weight cache pays for the continuous
    monthly rental cost of keeping it warm.

    This is the number a platform lead actually wants — "does caching help"
    is not a decision, "at what volume does it pay for itself" is. It prices
    a *rental* standing cost; the compile cache's standing cost is a
    different shape (a one-off re-warm charge per version change, not a
    monthly rental) — see `compile_cache_break_even_events_per_day`.

    `standing_monthly_cost` defaults to `assumptions.volume_monthly_cost` so
    the published `Assumptions` stay the single source of truth for the
    headline figure; pass an explicit value to price a different rental tier
    without editing the assumptions.

    By default a saved second is priced at the GPU rental rate alone
    (`assumptions.gpu_hourly_rate`) — the same partial accounting
    `gpu_cost_per_scale_up` uses, and the basis this module's published
    headline figure uses today, since spec 7 does not yet publish a token
    price. Pass `include_foregone_tokens=True` to also value the tokens that
    second could have produced (requires
    `assumptions.output_token_price_per_million`), matching
    `total_cost_per_scale_up`.

    `seconds_saved` may legitimately be negative — a cache that made cold
    starts slower is a real, if unfortunate, measurement, not invalid
    input — so it never breaks even either way, but the *sign* of the result
    keeps the two "never" cases distinguishable: `seconds_saved == 0` (the
    cache was a wash) returns `+inf`; `seconds_saved < 0` (the cache made
    things worse — a real regression) returns `-inf`. A reader seeing just
    "break-even: inf" can't tell noise from a regression; the sign lets them.
    """
    _require_finite(seconds_saved, "seconds_saved")
    if standing_monthly_cost is None:
        standing_monthly_cost = assumptions.volume_monthly_cost
    _require_finite_non_negative(standing_monthly_cost, "standing_monthly_cost")

    if seconds_saved < 0:
        return float("-inf")
    if seconds_saved == 0:
        return float("inf")

    hourly_rate = assumptions.gpu_hourly_rate
    if include_foregone_tokens:
        if assumptions.output_token_price_per_million is None:
            raise ValueError(
                "include_foregone_tokens=True requires "
                "assumptions.output_token_price_per_million to be set"
            )
        hourly_rate += (
            assumptions.steady_state_tokens_per_sec
            * (assumptions.output_token_price_per_million / 1_000_000.0)
            * SECONDS_PER_HOUR
        )

    saving_per_event = (seconds_saved / SECONDS_PER_HOUR) * hourly_rate
    events_per_month = standing_monthly_cost / saving_per_event
    return events_per_month / DAYS_PER_MONTH


def compile_cache_break_even_events_per_day(
    seconds_saved: float,
    rewarm_cost: float,
    version_changes_per_month: float,
    assumptions: Assumptions,
) -> float:
    """The compile cache's counterpart to `break_even_events_per_day` — spec
    line 717 requires a break-even for both caches.

    The weight cache's standing cost is a continuous monthly rental. The
    compile cache's standing cost is a one-off `rewarm_cost` paid each time
    the engine version changes and the cache must be rebuilt — a different
    shape, not just a different number. `version_changes_per_month` converts
    that lumpy, per-version cost into the monthly-equivalent figure the
    shared break-even formula expects, so the two caches' break-evens land in
    the same unit (events/day) and can be read side by side.
    """
    _require_finite_non_negative(rewarm_cost, "rewarm_cost")
    _require_finite_non_negative(version_changes_per_month, "version_changes_per_month")
    standing_monthly_cost = rewarm_cost * version_changes_per_month
    return break_even_events_per_day(seconds_saved, assumptions, standing_monthly_cost)


def cache_is_worth_renting(assumptions: Assumptions, break_even: float) -> bool:
    """The one-sentence verdict spec line 719 asks for: at the assumed
    scale-up frequency, does this cache earn back its standing cost?

    A `break_even` of `+inf` (no savings) or `-inf` (a regression) is never
    worth it, regardless of `assumptions.scale_ups_per_day` — `-inf` in
    particular must not compare as "worth it" just because every finite
    frequency is numerically greater than negative infinity. Only a finite,
    non-negative break-even below the assumed frequency clears the bar.
    """
    if not math.isfinite(break_even):
        return False
    return assumptions.scale_ups_per_day > break_even
