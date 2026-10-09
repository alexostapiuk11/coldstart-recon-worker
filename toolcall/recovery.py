"""One recovery conversation: the first call meets an error, then up to
`TURN_BUDGET` attempts to recover (amendment §4e).

The measures, per conversation (August §4):

- injected: an error or contradiction reached the model. Every other measure
  is defined only when this is true; conversations without one are counted.
- recovered, turns_to_recovery: an attempt matched an acceptable recovery call.
- identical_retry: the first action after the error repeated the failing call
  unchanged, after normalization (`normalize.call_key`). The headline measure.
- gave_up: the model stopped calling without recovering, and its text does not
  claim success.
- hallucinated_success: it stopped calling without recovering, and its text
  matches the scenario's `success_claim_pattern`. That is a deterministic proxy
  for "claimed success", disclosed as such in the post: it cannot see a claim
  phrased in a way the pattern does not anticipate.
"""

import re
import time
from dataclasses import dataclass

from toolcall.formulation import Formulation, render
from toolcall.grader import grade, parse_arguments
from toolcall.guard import SpendCapReached
from toolcall.mock_tools import reply
from toolcall.normalize import call_key
from toolcall.providers import PARSE
from toolcall.scenarios import Scenario
from toolcall.tools import Library

TURN_BUDGET = 3
NOT_EXECUTED = "Not executed: make one tool call per turn."


@dataclass
class Conversation:
    turns: list  # one dict per model turn: request, response, parsed summary, tool reply
    first_grade: dict | None
    injected: bool
    recovered: bool
    turns_to_recovery: int | None
    identical_retry: bool | None
    gave_up: bool
    hallucinated_success: bool
    budget_exhausted: bool
    excluded: str | None  # API_ERROR / REFUSED / TRUNCATED mid-conversation, or None


def _summary(parsed) -> dict:
    return {"finish": parsed.finish, "text": parsed.text, "usage": parsed.usage,
            "model": parsed.model,
            "calls": [{"call_id": c.call_id, "name": c.name, "arguments": c.arguments}
                      for c in parsed.calls]}


def converse(client, scenario: Scenario, library: Library, formulation: Formulation,
             fmt: str) -> Conversation:
    rec = scenario.recovery
    if rec is None:
        raise ValueError(f"{scenario.id} has no recovery block")
    tools = render(scenario, library, formulation)
    rendered = [t["name"] for t in tools]
    transcript = [{"role": "user", "text": scenario.user_message}]
    turns: list = []
    out = {"first_grade": None, "injected": False, "recovered": False,
           "turns_to_recovery": None, "identical_retry": None, "gave_up": False,
           "hallucinated_success": False, "budget_exhausted": False, "excluded": None}
    failing_key = None
    for attempt in range(TURN_BUDGET + 1):
        t0 = time.monotonic()
        body = client.request(tools, transcript)  # kept even if the post raises
        try:
            response = client.post(body)
        except SpendCapReached:
            raise
        except Exception as e:  # noqa: BLE001 -- every provider failure is data here
            turns.append({"request": body, "error": f"{type(e).__name__}: {e}"})
            out["excluded"] = "API_ERROR"
            break
        try:
            parsed = PARSE[client.settings.provider](response)
        except SpendCapReached:
            raise
        except Exception as e:  # noqa: BLE001 -- a malformed response is data, not a crash
            # The guard has already charged the call, so the spend is counted.
            turns.append({"request": body, "response": response,
                          "error": f"unparseable response: {type(e).__name__}: {e}"})
            out["excluded"] = "API_ERROR"
            break
        turn = {"request": body, "response": response, "parsed": _summary(parsed),
                "seconds": time.monotonic() - t0}
        turns.append(turn)
        if attempt == 0:
            out["first_grade"] = grade(parsed, scenario, library, rendered).to_dict()
        if parsed.finish in ("refused", "truncated", "error"):
            out["excluded"] = {"refused": "REFUSED", "truncated": "TRUNCATED",
                               "error": "API_ERROR"}[parsed.finish]
            break
        if not parsed.calls:
            if attempt > 0:
                claims = re.search(rec.success_claim_pattern, parsed.text, re.IGNORECASE)
                out["hallucinated_success"] = bool(claims)
                out["gave_up"] = not claims
                if attempt == 1:  # stopped without any further call: not a retry
                    out["identical_retry"] = False
            break
        call = parsed.calls[0]
        args = parse_arguments(call.arguments)
        key = call_key(call.name, args, library.tools.get(call.name))
        if attempt == 1:
            out["identical_retry"] = key == failing_key
        r = reply(rec, fmt, attempt, call.name, args, library)
        turn["tool_reply"] = {"content": r.content, "is_error": r.is_error,
                              "success": r.success}
        if r.success:
            if attempt == 0:
                break  # accepted first time: nothing was injected
            out["recovered"] = True
            out["turns_to_recovery"] = attempt
            break
        if attempt == 0:
            out["injected"] = True
            failing_key = key
        transcript += [
            {"role": "assistant", "raw": parsed.raw_output},
            {"role": "tool", "call_id": call.call_id, "content": r.content,
             "is_error": r.is_error},
        ]
        # Grading and the mock reply use the first call only, but the provider
        # rejects a request in which any call_id lacks a result.
        extra = parsed.calls[1:]
        for other in extra:
            transcript.append({"role": "tool", "call_id": other.call_id,
                               "content": NOT_EXECUTED, "is_error": True})
        if extra:
            turn["extra_calls_answered"] = len(extra)
    else:
        out["budget_exhausted"] = True
    return Conversation(turns=turns, **out)
