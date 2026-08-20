import math
from dataclasses import replace

import pytest

from coldstart.analysis.economics import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    Assumptions,
    annual_cost,
    break_even_events_per_day,
    cache_is_worth_renting,
    compile_cache_break_even_events_per_day,
    compile_cache_term,
    foregone_token_value,
    foregone_tokens,
    gpu_cost_per_scale_up,
    supported_concurrency,
    total_cost_per_scale_up,
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
    single field's effect on a formula. Goes through `Assumptions.__post_init__`
    just like any other construction, so an override that violates validation
    still raises."""
    return replace(ASSUME, **overrides)


# ---------------------------------------------------------------------------
# Plan's seven tests (cost_per_scale_up renamed to gpu_cost_per_scale_up per
# code review C2; break-even's signature and tolerance updated per I3/I10 —
# behavior for these specific calls is unchanged).
# ---------------------------------------------------------------------------


def test_foregone_tokens_is_time_times_throughput():
    assert foregone_tokens(t_fast=120.0, assumptions=ASSUME) == pytest.approx(4800.0)


def test_gpu_cost_per_scale_up_prices_the_gpu_seconds():
    # 120s at $0.80/hr = $0.02666...
    result = gpu_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)
    assert result == pytest.approx(0.026667, abs=1e-5)


def test_annual_cost_scales_by_frequency():
    per_event = gpu_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)
    assert annual_cost(per_event, ASSUME) == pytest.approx(per_event * 48 * 365)


def test_supported_concurrency_divides_capacity_by_context():
    assert supported_concurrency(kv_capacity_tokens=131072, assumptions=ASSUME) == 64


def test_break_even_is_where_savings_cover_the_standing_cost():
    # Saving 60s per event at $0.80/hr = $0.01333 per event. A $7/month
    # volume needs 525 events/month = 17.260274 events/day to pay for
    # itself, using DAYS_PER_MONTH = DAYS_PER_YEAR / 12 (not a bare 30 —
    # see the reconciliation note on the constants). Tight tolerance: a
    # bare-30.0 DAYS_PER_MONTH would give 17.5, which this must reject.
    ev = break_even_events_per_day(seconds_saved=60.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == pytest.approx(17.260274, abs=1e-5)


def test_break_even_is_infinite_when_nothing_is_saved():
    ev = break_even_events_per_day(seconds_saved=0.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == float("inf")


def test_compile_cache_term_is_cold_minus_warm():
    assert compile_cache_term(s4b_cold=42.0, s4b_warm=3.0) == pytest.approx(39.0)


# ---------------------------------------------------------------------------
# Assumptions validation — range checks. volume_monthly_cost and
# output_token_price_per_million are otherwise never read by a formula that
# also takes an explicit override (break_even's standing_monthly_cost /
# include_foregone_tokens argument), so construction-time validation is the
# only place either field is exercised as "live" data at all.
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
    assert _assumptions(volume_monthly_cost=0.0).volume_monthly_cost == 0.0


def test_assumptions_rejects_non_positive_assumed_context_length():
    with pytest.raises(ValueError, match="assumed_context_length"):
        _assumptions(assumed_context_length=0)


def test_assumptions_rejects_negative_output_token_price_per_million():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        _assumptions(output_token_price_per_million=-0.01)


def test_assumptions_defaults_output_token_price_per_million_to_none():
    assert Assumptions(
        gpu_hourly_rate=0.80,
        scale_ups_per_day=48,
        steady_state_tokens_per_sec=40.0,
        volume_monthly_cost=7.0,
        assumed_context_length=2048,
    ).output_token_price_per_million is None


# ---------------------------------------------------------------------------
# Assumptions validation — NaN and inf, per field (code review C1). NaN
# fails every `<=`/`<` comparison, so a validator written as a bare range
# check waves it through; each of these would have passed silently before
# the fix routed every field through the finite check first.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf")], ids=["nan", "inf"])
@pytest.mark.parametrize(
    "field",
    [
        "gpu_hourly_rate",
        "scale_ups_per_day",
        "steady_state_tokens_per_sec",
        "volume_monthly_cost",
        "assumed_context_length",
        "output_token_price_per_million",
    ],
)
def test_assumptions_rejects_non_finite_field(field, bad_value):
    with pytest.raises(ValueError, match=field):
        _assumptions(**{field: bad_value})


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
# gpu_cost_per_scale_up
# ---------------------------------------------------------------------------


def test_gpu_cost_per_scale_up_at_one_hour_equals_the_hourly_rate():
    # Literal 3600.0, not SECONDS_PER_HOUR, on the input side: importing the
    # module's own constant here would make the assertion pass even under a
    # mutant that changes SECONDS_PER_HOUR, since the same (wrong) constant
    # would cancel out of both the input and the implementation.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    assert gpu_cost_per_scale_up(t_fast=3600.0, assumptions=rate_one) == pytest.approx(1.0)


def test_gpu_cost_per_scale_up_at_zero_t_fast_is_zero():
    assert gpu_cost_per_scale_up(t_fast=0.0, assumptions=ASSUME) == 0.0


def test_gpu_cost_per_scale_up_rejects_negative_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        gpu_cost_per_scale_up(t_fast=-1.0, assumptions=ASSUME)


# ---------------------------------------------------------------------------
# foregone_token_value / total_cost_per_scale_up — spec line 713's full,
# two-term definition of a scale-up event's cost (code review C2).
# ---------------------------------------------------------------------------


def test_foregone_token_value_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        foregone_token_value(t_fast=120.0, assumptions=ASSUME)


def test_foregone_token_value_prices_the_tokens():
    priced = _assumptions(output_token_price_per_million=2.0)
    # foregone_tokens = 120 * 40 = 4800; value = 4800 * (2.0 / 1e6) = 0.0096
    assert foregone_token_value(t_fast=120.0, assumptions=priced) == pytest.approx(0.0096)


def test_total_cost_per_scale_up_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        total_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)


def test_total_cost_per_scale_up_is_gpu_cost_plus_foregone_value():
    priced = _assumptions(output_token_price_per_million=2.0)
    # gpu_cost = 120/3600*0.8 = 0.026667; foregone_value = 0.0096; sum = 0.036267
    result = total_cost_per_scale_up(t_fast=120.0, assumptions=priced)
    assert result == pytest.approx(0.036267, abs=1e-5)
    assert result == pytest.approx(
        gpu_cost_per_scale_up(120.0, priced) + foregone_token_value(120.0, priced)
    )


# ---------------------------------------------------------------------------
# annual_cost
# ---------------------------------------------------------------------------


def test_annual_cost_scales_with_scale_ups_per_day():
    ten = _assumptions(scale_ups_per_day=10)
    twenty = _assumptions(scale_ups_per_day=20)
    cost = 0.05
    assert annual_cost(cost, twenty) == pytest.approx(2 * annual_cost(cost, ten))


def test_annual_cost_uses_days_per_year_exactly():
    # cost_per_event and scale_ups_per_day chosen to be 1, so the result is
    # DAYS_PER_YEAR alone. Literal 365.0 on the expectation side, not
    # DAYS_PER_YEAR — a mutant changing DAYS_PER_YEAR would otherwise cancel
    # against itself here.
    one_per_day = _assumptions(scale_ups_per_day=1)
    assert annual_cost(1.0, one_per_day) == pytest.approx(365.0)


def test_annual_cost_at_zero_cost_per_event_is_zero():
    assert annual_cost(0.0, ASSUME) == 0.0


def test_annual_cost_rejects_negative_cost_per_event():
    with pytest.raises(ValueError, match="cost_per_event"):
        annual_cost(-1.0, ASSUME)


def test_annual_cost_rejects_non_finite_cost_per_event():
    with pytest.raises(ValueError, match="cost_per_event"):
        annual_cost(float("nan"), ASSUME)


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


def test_supported_concurrency_rejects_non_finite_capacity():
    with pytest.raises(ValueError, match="kv_capacity_tokens"):
        supported_concurrency(kv_capacity_tokens=float("nan"), assumptions=ASSUME)


def test_supported_concurrency_coerces_float_capacity_to_int():
    # kv_capacity_tokens can arrive as a float from parsed vLLM log output;
    # the -> int contract must hold regardless.
    result = supported_concurrency(kv_capacity_tokens=131072.0, assumptions=ASSUME)
    assert result == 64
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# compile_cache_term
# ---------------------------------------------------------------------------


def test_compile_cache_term_is_zero_when_cold_equals_warm():
    assert compile_cache_term(s4b_cold=10.0, s4b_warm=10.0) == 0.0


def test_compile_cache_term_is_negative_when_warm_exceeds_cold():
    # Measurement noise can make a "warm" run look slower than "cold" — the
    # function reports that honestly rather than clamping it away.
    assert compile_cache_term(s4b_cold=5.0, s4b_warm=10.0) == pytest.approx(-5.0)


def test_compile_cache_term_rejects_non_finite_cold():
    with pytest.raises(ValueError, match="s4b_cold"):
        compile_cache_term(s4b_cold=float("nan"), s4b_warm=3.0)


def test_compile_cache_term_rejects_non_finite_warm():
    with pytest.raises(ValueError, match="s4b_warm"):
        compile_cache_term(s4b_cold=42.0, s4b_warm=float("inf"))


# ---------------------------------------------------------------------------
# break_even_events_per_day
# ---------------------------------------------------------------------------


def test_break_even_is_negative_infinite_when_the_cache_made_things_slower():
    # seconds_saved < 0 is a real state (a cache that regressed cold start),
    # not invalid input — it must not raise. It returns -inf rather than
    # +inf so a reader can tell this apart from the "no difference" case
    # (code review I7): a bare "break-even: inf" doesn't distinguish noise
    # from a real regression.
    ev = break_even_events_per_day(
        seconds_saved=-30.0, assumptions=ASSUME, standing_monthly_cost=7.0
    )
    assert ev == float("-inf")


def test_break_even_rejects_non_finite_seconds_saved():
    with pytest.raises(ValueError, match="seconds_saved"):
        break_even_events_per_day(
            seconds_saved=float("nan"), assumptions=ASSUME, standing_monthly_cost=7.0
        )


def test_break_even_rejects_negative_standing_monthly_cost():
    with pytest.raises(ValueError, match="standing_monthly_cost"):
        break_even_events_per_day(
            seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=-1.0
        )


def test_break_even_is_zero_when_standing_cost_is_zero():
    # No standing cost to recoup means the cache "pays for itself" at any
    # frequency, including zero.
    ev = break_even_events_per_day(
        seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=0.0
    )
    assert ev == pytest.approx(0.0)


def test_break_even_scales_inversely_with_gpu_hourly_rate():
    cheap = _assumptions(gpu_hourly_rate=1.0)
    pricey = _assumptions(gpu_hourly_rate=2.0)
    ev_cheap = break_even_events_per_day(
        seconds_saved=3600.0, assumptions=cheap, standing_monthly_cost=100.0
    )
    ev_pricey = break_even_events_per_day(
        seconds_saved=3600.0, assumptions=pricey, standing_monthly_cost=100.0
    )
    assert ev_pricey == pytest.approx(ev_cheap / 2)


def test_break_even_uses_days_per_year_over_twelve_for_month_length():
    # Ties DAYS_PER_MONTH to DAYS_PER_YEAR / 12 through the public function:
    # 1 event/day at $1/event, with the standing monthly cost set to exactly
    # one "average" month of that spend, must break even at 1 event/day.
    # seconds_saved is the literal 3600.0 (not SECONDS_PER_HOUR) so a
    # SECONDS_PER_HOUR mutation can't cancel out of this test too.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    ev = break_even_events_per_day(
        seconds_saved=3600.0,
        assumptions=rate_one,
        standing_monthly_cost=DAYS_PER_YEAR / 12.0,
    )
    assert ev == pytest.approx(1.0)


def test_break_even_defaults_standing_cost_to_assumptions_volume_monthly_cost():
    # Code review I3: volume_monthly_cost must be a live input, not dead
    # data next to a separately-supplied standing_monthly_cost argument.
    # Compared against an explicit call carrying the *same* nonzero value
    # (not against another fallback call) so a mutant that replaces the
    # fallback with a constant (e.g. always 0.0) can't hide by having both
    # sides of the comparison degenerate to the same wrong answer.
    custom = _assumptions(volume_monthly_cost=14.0)
    ev_via_default = break_even_events_per_day(seconds_saved=60.0, assumptions=custom)
    ev_via_explicit = break_even_events_per_day(
        seconds_saved=60.0, assumptions=custom, standing_monthly_cost=14.0
    )
    assert ev_via_default == pytest.approx(ev_via_explicit)
    assert ev_via_default != pytest.approx(0.0)


def test_break_even_explicit_standing_cost_overrides_assumptions():
    ev_override = break_even_events_per_day(
        seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=3.5
    )
    ev_default = break_even_events_per_day(seconds_saved=60.0, assumptions=ASSUME)
    assert ev_override == pytest.approx(ev_default / 2)  # 3.5 is half of ASSUME's 7.0


def test_break_even_include_foregone_tokens_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        break_even_events_per_day(
            seconds_saved=60.0,
            assumptions=ASSUME,
            standing_monthly_cost=7.0,
            include_foregone_tokens=True,
        )


def test_break_even_include_foregone_tokens_lowers_the_break_even():
    # Valuing the foregone tokens too makes each saved second worth more,
    # so fewer events/day are needed to recoup the same standing cost.
    priced = _assumptions(output_token_price_per_million=1.0)
    ev_gpu_only = break_even_events_per_day(
        seconds_saved=60.0, assumptions=priced, standing_monthly_cost=7.0
    )
    ev_total = break_even_events_per_day(
        seconds_saved=60.0,
        assumptions=priced,
        standing_monthly_cost=7.0,
        include_foregone_tokens=True,
    )
    assert ev_total < ev_gpu_only


# ---------------------------------------------------------------------------
# compile_cache_break_even_events_per_day — spec line 717's break-even for
# the compile cache, whose standing cost is a one-off re-warm charge per
# version change rather than a monthly rental (code review I4).
# ---------------------------------------------------------------------------


def test_compile_cache_break_even_converts_rewarm_cost_exactly():
    # seconds_saved=3600s at rate=1.0 -> $1 saved/event. rewarm_cost=1.0 at
    # DAYS_PER_MONTH version changes/month -> standing_monthly_cost =
    # DAYS_PER_MONTH exactly -> events_per_month = DAYS_PER_MONTH ->
    # events_per_day = 1.0. An implementation that added rather than
    # multiplied rewarm_cost and version_changes_per_month would drift
    # noticeably off 1.0.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=3600.0,
        rewarm_cost=1.0,
        version_changes_per_month=DAYS_PER_MONTH,
        assumptions=rate_one,
    )
    assert ev == pytest.approx(1.0)


def test_compile_cache_break_even_is_negative_infinite_when_slower():
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=-5.0,
        rewarm_cost=5.0,
        version_changes_per_month=2.0,
        assumptions=ASSUME,
    )
    assert ev == float("-inf")


def test_compile_cache_break_even_at_zero_version_changes_is_zero():
    # No version changes means the re-warm cost never recurs — free.
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=60.0,
        rewarm_cost=5.0,
        version_changes_per_month=0.0,
        assumptions=ASSUME,
    )
    assert ev == pytest.approx(0.0)


def test_compile_cache_break_even_rejects_negative_rewarm_cost():
    with pytest.raises(ValueError, match="rewarm_cost"):
        compile_cache_break_even_events_per_day(
            seconds_saved=60.0,
            rewarm_cost=-1.0,
            version_changes_per_month=2.0,
            assumptions=ASSUME,
        )


def test_compile_cache_break_even_rejects_negative_version_changes_per_month():
    with pytest.raises(ValueError, match="version_changes_per_month"):
        compile_cache_break_even_events_per_day(
            seconds_saved=60.0,
            rewarm_cost=5.0,
            version_changes_per_month=-1.0,
            assumptions=ASSUME,
        )


# ---------------------------------------------------------------------------
# cache_is_worth_renting — the one-sentence verdict, spec line 719 (code
# review I8).
# ---------------------------------------------------------------------------


def test_cache_is_worth_renting_true_when_frequency_exceeds_break_even():
    assert cache_is_worth_renting(ASSUME, 17.260274) is True  # 48/day > 17.26/day


def test_cache_is_worth_renting_false_when_frequency_is_below_break_even():
    assert cache_is_worth_renting(ASSUME, 100.0) is False  # 48/day < 100/day


def test_cache_is_worth_renting_false_at_exact_break_even():
    assert cache_is_worth_renting(ASSUME, 48.0) is False  # equal, not "exceeds"


def test_cache_is_worth_renting_false_for_infinite_break_even():
    assert cache_is_worth_renting(ASSUME, float("inf")) is False


def test_cache_is_worth_renting_false_for_negative_infinite_break_even():
    # A naive `scale_ups_per_day > break_even` is True for any finite
    # frequency against -inf; a regression must never read as "worth it".
    assert cache_is_worth_renting(ASSUME, float("-inf")) is False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_days_per_month_is_derived_from_days_per_year():
    assert DAYS_PER_MONTH == pytest.approx(DAYS_PER_YEAR / 12.0)
    assert not math.isclose(DAYS_PER_MONTH, 30.0)
