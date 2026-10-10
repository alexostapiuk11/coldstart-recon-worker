"""The spend guard (amendment §7).

The portfolio rule: no paid call without the author's explicit yes, stating the
number of calls and the estimated cost. A paid script therefore takes an
`--approved-usd` amount and does three things with it:

1. Before anything runs, it refuses if its own estimate exceeds the amount
   (`check_estimate`).
2. Before every call, it refuses if that call's upper bound could take total
   spend past the amount (`SpendGuard.before`).
3. After every call, it adds that call's metered cost from the response.

The per-call bound (`call_bound_usd`) is an upper bound, not an estimate: the
output can never exceed `max_output_tokens`, and the input is counted at two
characters of request JSON per token, where the providers' tokenizers average
three to four on this text. Plan 2 checks that assumption against the pilot's
recorded usage (`bound_held`). A bound rather than the largest call seen so far,
because a call larger than any before it would otherwise cross the cap.

Metering is only as good as the response in hand, so the guard charges what it
cannot meter rather than assuming it was free:

- A post that raises may or may not have been billed, and the SDKs retry
  transport failures internally (`SDK_MAX_RETRIES`, each retry a separate
  provider call). The guard therefore checks the cap against the call's bound
  times `1 + SDK_MAX_RETRIES`, and charges that worst case when the post raises.
- A response with no usable usage, or one the parser cannot read, is charged the
  bound for one attempt.
- A call that succeeds after internal retries is metered at its own usage only.
  Billed retries that left no response are invisible to the guard. The spend
  record's billed-versus-metered comparison (amendment §8) is what catches them,
  which is why that comparison is a gate and not a courtesy.

`SpendCapReached` deliberately is not caught by the campaign's error handling:
it stops the run, and the records already stored stay stored. `SpendGuardError`
subclasses it, so a guard-internal failure (a model with no pinned price, usage
the price table cannot cost) stops the run the same way instead of being
recorded as a provider error and quietly skipping the meter.
"""

import json
import math

from toolcall.prices import PRICES, cost_usd

CHARS_PER_TOKEN_BOUND = 2.0
TOKENIZER_FACTOR = {"openai": 1.0, "anthropic": 1.3}  # amendment §8
# Providers add hidden tool-use prompt tokens and render the schemas internally,
# so the request JSON alone undercounts the input; this fixed allowance covers it.
INPUT_OVERHEAD_TOKENS = 500
# The SDKs' default internal transport retries; each one is a separate provider
# call. Client.post sets it explicitly so the bound below does not depend on a
# default the SDKs may change.
SDK_MAX_RETRIES = 2


class SpendCapReached(RuntimeError):
    pass


class SpendGuardError(SpendCapReached):
    """The guard itself failed (unpriced model, usage it cannot cost)."""


def _require_finite_positive(amount: float, what: str) -> None:
    # NaN compares false with everything, so `spent + bound > NaN` would never
    # trip and a NaN or infinite amount would silently disable the cap.
    if not math.isfinite(amount) or amount <= 0:
        raise SpendCapReached(f"{what} must be a finite positive amount, got {amount!r}")


def input_tokens_bound(settings, body: dict) -> float:
    return (len(json.dumps(body)) / CHARS_PER_TOKEN_BOUND * TOKENIZER_FACTOR[settings.provider]
            + INPUT_OVERHEAD_TOKENS)


def call_bound_usd(settings, body: dict) -> float:
    try:
        p = PRICES[settings.model]
    except KeyError:
        raise SpendGuardError(
            f"no pinned price for {settings.model!r}; add it with its source first") from None
    # A cache write costs more than a plain input token, and the bound cannot
    # know which tokens a provider will cache, so the dearer price is used.
    return (input_tokens_bound(settings, body) * max(p.input, p.cache_write)
            + settings.max_output_tokens * p.output) / 1e6


def bound_held(settings, body: dict, usage: dict) -> bool:
    return usage["input"] <= input_tokens_bound(settings, body)


def check_estimate(estimate_usd: float, approved_usd: float) -> None:
    _require_finite_positive(approved_usd, "the approved amount (--approved-usd)")
    if not math.isfinite(estimate_usd):
        raise SpendCapReached(f"the estimate is not finite ({estimate_usd!r}); fix it first")
    if estimate_usd > approved_usd:
        raise SpendCapReached(
            f"estimated ${estimate_usd:.2f} exceeds the approved ${approved_usd:.2f}; "
            "ask the author for a new approval rather than raising the number"
        )


class SpendGuard:
    def __init__(self, approved_usd: float, spent: float = 0.0):
        """`spent` seeds a resumed phase with what its stored records already cost,
        so the approved amount caps the whole phase across resumes."""
        _require_finite_positive(approved_usd, "the approved amount")
        if isinstance(spent, bool) or not math.isfinite(spent) or spent < 0:
            raise SpendCapReached(f"the seed spend must be a finite amount >= 0, got {spent!r}")
        self.approved = approved_usd
        self.spent = spent
        self.calls = 0
        self.unmetered = 0  # calls charged at a bound because usage was unavailable

    def before(self, bound_usd: float) -> None:
        if self.spent + bound_usd > self.approved:
            raise SpendCapReached(
                f"stopping: ${self.spent:.4f} spent over {self.calls} calls, and the next "
                f"(up to ${bound_usd:.4f}) could exceed the approved ${self.approved:.2f}"
            )

    def add(self, model: str, usage: dict) -> float:
        try:
            cost = cost_usd(model, usage)
        except (KeyError, ValueError) as e:
            raise SpendGuardError(f"cannot meter this call: {e}") from e
        self.spent += cost
        self.calls += 1
        return cost

    def charge_unmetered(self, usd: float) -> None:
        """Charge a call whose cost is unknown at the amount it could have cost."""
        self.spent += usd
        self.calls += 1
        self.unmetered += 1


class GuardedClient:
    """Wraps a client so every post passes through the guard. Same interface."""

    def __init__(self, client, guard: SpendGuard, parse):
        self.client = client
        self.settings = client.settings
        self.guard = guard
        self._parse = parse

    def request(self, tools, transcript):
        return self.client.request(tools, transcript)

    def post(self, body):
        bound = call_bound_usd(self.settings, body)
        worst = bound * (1 + SDK_MAX_RETRIES)
        self.guard.before(worst)
        try:
            response = self.client.post(body)
        except SpendCapReached:
            raise
        except Exception:
            # Unknown whether it was billed, and the SDK may have retried:
            # assume the worst rather than $0.
            self.guard.charge_unmetered(worst)
            raise
        try:
            usage = self._parse(response).usage
        except Exception:  # noqa: BLE001 -- an unreadable response was still billed
            self.guard.charge_unmetered(bound)
            return response
        if usage["input"] == 0 and usage["output"] == 0:
            self.guard.charge_unmetered(bound)
            return response
        try:
            self.guard.add(self.settings.model, usage)
        except SpendGuardError:
            self.guard.charge_unmetered(bound)
            raise
        return response

    def send(self, tools, transcript):
        body = self.request(tools, transcript)
        return body, self.post(body)
