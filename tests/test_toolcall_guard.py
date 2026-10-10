import json
import math

import pytest

from toolcall.guard import (
    INPUT_OVERHEAD_TOKENS,
    SDK_MAX_RETRIES,
    GuardedClient,
    SpendCapReached,
    SpendGuard,
    SpendGuardError,
    call_bound_usd,
    check_estimate,
    input_tokens_bound,
)
from toolcall.prices import PRICES
from toolcall.providers import PARSE, ModelSettings, ScriptedClient
from toolcall.responses import anthropic_text, openai_text

MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
SONNET = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
BODY = {"input": "x" * 400}


def _guarded(settings, policy, approved=1.0):
    client = ScriptedClient(settings, policy)
    guard = SpendGuard(approved)
    return GuardedClient(client, guard, PARSE[settings.provider]), guard, client


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_a_non_finite_or_non_positive_approval_is_refused(bad):
    with pytest.raises(SpendCapReached):
        SpendGuard(bad)
    with pytest.raises(SpendCapReached):
        check_estimate(1.0, bad)


def test_a_non_finite_estimate_is_refused():
    with pytest.raises(SpendCapReached):
        check_estimate(math.nan, 5.0)
    with pytest.raises(SpendCapReached):
        check_estimate(math.inf, 5.0)
    check_estimate(4.0, 5.0)
    with pytest.raises(SpendCapReached):
        check_estimate(6.0, 5.0)


def test_the_bound_includes_the_overhead_and_the_dearer_input_price():
    chars = len(json.dumps(BODY))
    assert input_tokens_bound(MINI, BODY) == chars / 2.0 + INPUT_OVERHEAD_TOKENS
    assert input_tokens_bound(SONNET, BODY) == chars / 2.0 * 1.3 + INPUT_OVERHEAD_TOKENS
    # OpenAI has no cache-write price, so its input price is the larger one.
    p = PRICES[MINI.model]
    assert call_bound_usd(MINI, BODY) == pytest.approx(
        ((chars / 2.0 + 500) * p.input + MINI.max_output_tokens * p.output) / 1e6)
    # Anthropic's cache write (2.50) costs more than its input (2.00).
    p = PRICES[SONNET.model]
    assert p.cache_write > p.input
    assert call_bound_usd(SONNET, BODY) == pytest.approx(
        ((chars / 2.0 * 1.3 + 500) * p.cache_write + SONNET.max_output_tokens * p.output) / 1e6)


def test_a_raising_post_is_charged_the_worst_case_and_reraised():
    def boom(body):
        raise TimeoutError("read timeout")

    gc, guard, _ = _guarded(MINI, boom)
    bound = call_bound_usd(MINI, BODY)
    with pytest.raises(TimeoutError):
        gc.post(BODY)
    assert guard.spent == pytest.approx(bound * (1 + SDK_MAX_RETRIES))
    assert guard.unmetered == 1 and guard.calls == 1
    with pytest.raises(TimeoutError):
        gc.post(BODY)
    assert guard.spent == pytest.approx(2 * bound * (1 + SDK_MAX_RETRIES))  # later calls see it


def test_the_cap_check_covers_the_retry_worst_case():
    bound = call_bound_usd(MINI, BODY)
    gc, _, client = _guarded(MINI, lambda b: openai_text("ok"),
                                 approved=bound * (1 + SDK_MAX_RETRIES) * 0.99)
    with pytest.raises(SpendCapReached):
        gc.post(BODY)
    assert client.sent == []  # refused before anything was sent


def test_a_response_without_usage_is_charged_the_bound_not_zero():
    gc, guard, _ = _guarded(MINI, lambda b: {**openai_text("ok"), "usage": {}})
    gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))
    assert guard.unmetered == 1


def test_a_metered_response_is_charged_its_own_usage():
    gc, guard, _ = _guarded(MINI, lambda b: openai_text("ok"))
    gc.post(BODY)
    assert guard.unmetered == 0 and guard.calls == 1
    assert guard.spent == pytest.approx((1000 * 0.75 + 40 * 4.50) / 1e6)


def test_an_unreadable_response_is_charged_the_bound():
    gc, guard, _ = _guarded(MINI, lambda b: {"output": [{"type": "function_call"}], "usage": {}})
    gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))


def test_an_unpriced_model_stops_the_run_before_any_call():
    odd = ModelSettings("openai", "gpt-unpriced", 0.0, reasoning_effort="none")
    gc, guard, client = _guarded(odd, lambda b: openai_text("ok"))
    with pytest.raises(SpendGuardError, match="no pinned price"):
        gc.post(BODY)
    assert client.sent == [] and guard.spent == 0.0
    assert issubclass(SpendGuardError, SpendCapReached)


def test_usage_the_price_table_cannot_cost_stops_the_run():
    bad = openai_text("ok")
    bad["usage"]["input_tokens"] = 10
    bad["usage"]["input_tokens_details"]["cached_tokens"] = 50
    gc, guard, _ = _guarded(MINI, lambda b: bad)
    with pytest.raises(SpendGuardError, match="cannot meter"):
        gc.post(BODY)
    assert guard.spent == pytest.approx(call_bound_usd(MINI, BODY))  # the call happened


def test_spend_never_exceeds_the_approval_when_some_posts_raise():
    state = {"n": 0}

    def alternate(body):
        state["n"] += 1
        if state["n"] % 2 == 0:
            raise ConnectionError("reset")
        return openai_text("ok")

    bound = call_bound_usd(MINI, BODY)
    approved = bound * 10
    gc, guard, _ = _guarded(MINI, alternate, approved=approved)
    stopped = False
    for _ in range(100):
        try:
            gc.post(BODY)
        except ConnectionError:
            pass
        except SpendCapReached:
            stopped = True
            break
        assert guard.spent <= approved
    assert stopped and guard.unmetered > 0 and guard.spent <= approved


def test_the_anthropic_response_is_metered_with_cache_writes():
    gc, guard, _ = _guarded(SONNET, lambda b: anthropic_text("ok"))
    gc.post(BODY)
    assert guard.spent == pytest.approx((1000 * 2.00 + 40 * 10.00) / 1e6)


def test_a_seeded_guard_counts_prior_spend_against_the_approval():
    bound = call_bound_usd(MINI, BODY)
    guard = SpendGuard(bound * 10, spent=bound * 8)
    assert guard.spent == pytest.approx(bound * 8)
    with pytest.raises(SpendCapReached, match="stopping"):
        guard.before(bound * 3)
    guard.before(bound)  # still fits


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.01, True])
def test_a_bad_seed_is_refused(bad):
    with pytest.raises(SpendCapReached, match="seed"):
        SpendGuard(1.0, spent=bad)
