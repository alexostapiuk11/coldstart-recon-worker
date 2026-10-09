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

`SpendCapReached` deliberately is not caught by the campaign's error handling:
it stops the run, and the records already stored stay stored.
"""

import json

from toolcall.prices import PRICES, cost_usd

CHARS_PER_TOKEN_BOUND = 2.0
TOKENIZER_FACTOR = {"openai": 1.0, "anthropic": 1.3}  # amendment §8


class SpendCapReached(RuntimeError):
    pass


def input_tokens_bound(settings, body: dict) -> float:
    return len(json.dumps(body)) / CHARS_PER_TOKEN_BOUND * TOKENIZER_FACTOR[settings.provider]


def call_bound_usd(settings, body: dict) -> float:
    p = PRICES[settings.model]
    return (input_tokens_bound(settings, body) * p.input
            + settings.max_output_tokens * p.output) / 1e6


def bound_held(settings, body: dict, usage: dict) -> bool:
    return usage["input"] <= input_tokens_bound(settings, body)


def check_estimate(estimate_usd: float, approved_usd: float) -> None:
    if approved_usd <= 0:
        raise SpendCapReached("no spend approved: pass --approved-usd with the amount agreed")
    if estimate_usd > approved_usd:
        raise SpendCapReached(
            f"estimated ${estimate_usd:.2f} exceeds the approved ${approved_usd:.2f}; "
            "ask the author for a new approval rather than raising the number"
        )


class SpendGuard:
    def __init__(self, approved_usd: float):
        if approved_usd <= 0:
            raise SpendCapReached("no spend approved")
        self.approved = approved_usd
        self.spent = 0.0
        self.calls = 0

    def before(self, bound_usd: float) -> None:
        if self.spent + bound_usd > self.approved:
            raise SpendCapReached(
                f"stopping: ${self.spent:.4f} spent over {self.calls} calls, and the next "
                f"(up to ${bound_usd:.4f}) could exceed the approved ${self.approved:.2f}"
            )

    def add(self, model: str, usage: dict) -> float:
        cost = cost_usd(model, usage)
        self.spent += cost
        self.calls += 1
        return cost


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
        self.guard.before(call_bound_usd(self.settings, body))
        response = self.client.post(body)
        self.guard.add(self.settings.model, self._parse(response).usage)
        return response

    def send(self, tools, transcript):
        body = self.request(tools, transcript)
        return body, self.post(body)
