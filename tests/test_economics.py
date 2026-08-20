import math

import pytest

from coldstart.analysis.economics import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    SECONDS_PER_HOUR,
    Assumptions,
    annual_cost,
    break_even_events_per_day,
    compile_cache_term,
    cost_per_scale_up,
    foregone_tokens,
    supported_concurrency,
)

ASSUME = Assumptions(
    gpu_hourly_rate=0.80,
    scale_ups_per_day=48,
    steady_state_tokens_per_sec=40.0,
    volume_monthly_cost=7.0,
    assumed_context_length=2048,
)


def _assumptions(**overrides):
    """ASSUME with one or more fields overridden, for tests that isolate a
    single field's effect on a formula."""
    fields = {
        "gpu_hourly_rate": ASSUME.gpu_hourly_rate,
        "scale_ups_per_day": ASSUME.scale_ups_per_day,
        "steady_state_tokens_per_sec": ASSUME.steady_state_tokens_per_sec,
        "volume_monthly_cost": ASSUME.volume_monthly_cost,
        "assumed_context_length": ASSUME.assumed_context_length,
    }
    fields.update(overrides)
    return Assumptions(**fields)


# ---------------------------------------------------------------------------
# Plan's seven tests, verbatim
# ---------------------------------------------------------------------------


def test_foregone_tokens_is_time_times_throughput():
    assert foregone_tokens(t_fast=120.0, assumptions=ASSUME) == pytest.approx(4800.0)


def test_cost_per_scale_up_prices_the_gpu_seconds():
    # 120s at $0.80/hr = $0.02666...
    assert cost_per_scale_up(t_fast=120.0, assumptions=ASSUME) == pytest.approx(0.026667, abs=1e-5)


def test_annual_cost_scales_by_frequency():
    per_event = cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)
    assert annual_cost(per_event, ASSUME) == pytest.approx(per_event * 48 * 365)


def test_supported_concurrency_divides_capacity_by_context():
    assert supported_concurrency(kv_capacity_tokens=131072, assumptions=ASSUME) == 64


def test_break_even_is_where_savings_cover_the_standing_cost():
    # Saving 60s per event at $0.80/hr = $0.01333 per event.
    # A $7/month volume needs 525 events/month = ~17.5/day to pay for itself.
    ev = break_even_events_per_day(seconds_saved=60.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == pytest.approx(17.5, rel=0.02)


def test_break_even_is_infinite_when_nothing_is_saved():
    ev = break_even_events_per_day(seconds_saved=0.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == float("inf")


def test_compile_cache_term_is_cold_minus_warm():
    assert compile_cache_term(s4b_cold=42.0, s4b_warm=3.0) == pytest.approx(39.0)


# ---------------------------------------------------------------------------
# Assumptions validation — every field is exercised at least once here, since
# `volume_monthly_cost` is otherwise never read by any formula in this module
# (break_even takes its own `standing_monthly_cost` argument instead) and
# would go completely untested without this.
# ---------------------------------------------------------------------------


def test_assumptions_rejects_non_positive_gpu_hourly_rate():
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        _assumptions(gpu_hourly_rate=0.0)


def test_assumptions_rejects_non_positive_scale_ups_per_day():
    with pytest.raises(ValueError, match="scale_ups_per_day"):
        _assumptions(scale_ups_per_day=0)


def test_assumptions_rejects_non_positive_steady_state_tokens_per_sec():
    with pytest.raises(ValueError, match="steady_state_tokens_per_sec"):
        _assumptions(steady_state_tokens_per_sec=-1.0)


def test_assumptions_rejects_negative_volume_monthly_cost():
    with pytest.raises(ValueError, match="volume_monthly_cost"):
        _assumptions(volume_monthly_cost=-0.01)


def test_assumptions_accepts_zero_volume_monthly_cost():
    # Zero is a real state (no standing rental cost at all), unlike negative.
    _assumptions(volume_monthly_cost=0.0)


def test_assumptions_rejects_non_positive_assumed_context_length():
    with pytest.raises(ValueError, match="assumed_context_length"):
        _assumptions(assumed_context_length=0)


# ---------------------------------------------------------------------------
# foregone_tokens
# ---------------------------------------------------------------------------


def test_foregone_tokens_scales_with_steady_state_tokens_per_sec():
    fast = _assumptions(steady_state_tokens_per_sec=100.0)
    assert foregone_tokens(t_fast=10.0, assumptions=fast) == pytest.approx(1000.0)


def test_foregone_tokens_at_zero_t_fast_is_zero():
    assert foregone_tokens(t_fast=0.0, assumptions=ASSUME) == 0.0


def test_foregone_tokens_rejects_negative_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        foregone_tokens(t_fast=-1.0, assumptions=ASSUME)


def test_foregone_tokens_rejects_non_finite_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        foregone_tokens(t_fast=float("nan"), assumptions=ASSUME)


# ---------------------------------------------------------------------------
# cost_per_scale_up
# ---------------------------------------------------------------------------


def test_cost_per_scale_up_at_one_hour_equals_the_hourly_rate():
    # Pins SECONDS_PER_HOUR exactly: at t_fast == SECONDS_PER_HOUR the result
    # must equal gpu_hourly_rate with no tolerance, unlike the plan's looser
    # 120s check.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    assert cost_per_scale_up(t_fast=SECONDS_PER_HOUR, assumptions=rate_one) == pytest.approx(1.0)


def test_cost_per_scale_up_at_zero_t_fast_is_zero():
    assert cost_per_scale_up(t_fast=0.0, assumptions=ASSUME) == 0.0


def test_cost_per_scale_up_rejects_negative_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        cost_per_scale_up(t_fast=-1.0, assumptions=ASSUME)


# ---------------------------------------------------------------------------
# annual_cost
# ---------------------------------------------------------------------------


def test_annual_cost_scales_with_scale_ups_per_day():
    ten = _assumptions(scale_ups_per_day=10)
    twenty = _assumptions(scale_ups_per_day=20)
    cost = 0.05
    assert annual_cost(cost, twenty) == pytest.approx(2 * annual_cost(cost, ten))


def test_annual_cost_uses_days_per_year_exactly():
    # cost_per_event chosen so scale_ups_per_day cancels to 1/day; any drift
    # in DAYS_PER_YEAR shows up directly in the result.
    one_per_day = _assumptions(scale_ups_per_day=1)
    assert annual_cost(1.0, one_per_day) == pytest.approx(DAYS_PER_YEAR)


def test_annual_cost_at_zero_cost_per_event_is_zero():
    assert annual_cost(0.0, ASSUME) == 0.0


# ---------------------------------------------------------------------------
# supported_concurrency
# ---------------------------------------------------------------------------


def test_supported_concurrency_when_capacity_smaller_than_one_context_is_zero():
    # A real deployment state (a KV cache too small to hold even one
    # context), not an error — must not raise and must not floor-divide to
    # a nonsensical negative or fractional value.
    assert supported_concurrency(kv_capacity_tokens=100, assumptions=ASSUME) == 0


def test_supported_concurrency_at_exact_context_boundary():
    ctx = ASSUME.assumed_context_length
    assert supported_concurrency(kv_capacity_tokens=ctx, assumptions=ASSUME) == 1
    assert supported_concurrency(kv_capacity_tokens=ctx - 1, assumptions=ASSUME) == 0
    assert supported_concurrency(kv_capacity_tokens=2 * ctx, assumptions=ASSUME) == 2


def test_supported_concurrency_rejects_negative_capacity():
    with pytest.raises(ValueError, match="kv_capacity_tokens"):
        supported_concurrency(kv_capacity_tokens=-1, assumptions=ASSUME)


# ---------------------------------------------------------------------------
# compile_cache_term
# ---------------------------------------------------------------------------


def test_compile_cache_term_is_zero_when_cold_equals_warm():
    assert compile_cache_term(s4b_cold=10.0, s4b_warm=10.0) == 0.0


def test_compile_cache_term_is_negative_when_warm_exceeds_cold():
    # Measurement noise can make a "warm" run look slower than "cold" — the
    # function reports that honestly rather than clamping it away.
    assert compile_cache_term(s4b_cold=5.0, s4b_warm=10.0) == pytest.approx(-5.0)


# ---------------------------------------------------------------------------
# break_even_events_per_day
# ---------------------------------------------------------------------------


def test_break_even_is_infinite_when_the_cache_made_things_slower():
    # seconds_saved < 0 is a real state (a cache that regressed cold start),
    # not invalid input — it must not raise, and must land in the same
    # "never breaks even" bucket as zero.
    ev = break_even_events_per_day(
        seconds_saved=-30.0, standing_monthly_cost=7.0, assumptions=ASSUME
    )
    assert ev == float("inf")


def test_break_even_rejects_non_finite_seconds_saved():
    with pytest.raises(ValueError, match="seconds_saved"):
        break_even_events_per_day(
            seconds_saved=float("nan"), standing_monthly_cost=7.0, assumptions=ASSUME
        )


def test_break_even_rejects_negative_standing_monthly_cost():
    with pytest.raises(ValueError, match="standing_monthly_cost"):
        break_even_events_per_day(
            seconds_saved=60.0, standing_monthly_cost=-1.0, assumptions=ASSUME
        )


def test_break_even_is_zero_when_standing_cost_is_zero():
    # No standing cost to recoup means the cache "pays for itself" at any
    # frequency, including zero.
    ev = break_even_events_per_day(
        seconds_saved=60.0, standing_monthly_cost=0.0, assumptions=ASSUME
    )
    assert ev == pytest.approx(0.0)


def test_break_even_scales_inversely_with_gpu_hourly_rate():
    cheap = _assumptions(gpu_hourly_rate=1.0)
    pricey = _assumptions(gpu_hourly_rate=2.0)
    ev_cheap = break_even_events_per_day(
        seconds_saved=3600.0, standing_monthly_cost=100.0, assumptions=cheap
    )
    ev_pricey = break_even_events_per_day(
        seconds_saved=3600.0, standing_monthly_cost=100.0, assumptions=pricey
    )
    assert ev_pricey == pytest.approx(ev_cheap / 2)


def test_break_even_uses_days_per_year_over_twelve_for_month_length():
    # Ties DAYS_PER_MONTH to DAYS_PER_YEAR / 12 directly through the public
    # function: 1 event/day at $1/event, with the standing monthly cost set
    # to exactly one "average" month of that spend, must break even at
    # 1 event/day.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    ev = break_even_events_per_day(
        seconds_saved=SECONDS_PER_HOUR,
        standing_monthly_cost=DAYS_PER_YEAR / 12.0,
        assumptions=rate_one,
    )
    assert ev == pytest.approx(1.0)


def test_days_per_month_is_derived_from_days_per_year():
    assert DAYS_PER_MONTH == pytest.approx(DAYS_PER_YEAR / 12.0)
    assert not math.isclose(DAYS_PER_MONTH, 30.0)
