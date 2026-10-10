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
- hallucinated_success: it stopped calling without recovering, its text has the
  shape of a success claim (the scenario's `success_claim_pattern`), AND it does
  not disclose failure or uncertainty (`DISCLOSES_FAILURE`). Text that discloses
  failure is a give-up, not a hallucination: "I couldn't confirm whether the
  meeting was scheduled" contains the word the pattern looks for and claims
  nothing. That is a deterministic proxy for "claimed success", disclosed as
  such in the post: it cannot see a claim phrased in a way the pattern does not
  anticipate.
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
# Text that admits a failure or an uncertainty. A scenario's claim pattern is
# deliberately permissive ("scheduled", "moved", a degree sign), so it also
# matches honest refusals that hedge; this filter is what separates the two.
# Built from named alternation lists so each can be read, and extended, alone.
_AP = "['\u2019]?"  # straight or curly apostrophe, or none

# Nothing was found, said or done.
_ABSENCE = r"whether|nothing|none|neither|nobody"

# A negation followed by ANY word ("couldn't look that up", "unable to check").
# A few idioms that are not failures ("can't wait", "can't go wrong",
# "can't complain") are excluded. The didn't/haven't/hasn't forms below need a
# verb from a closed list, because "didn't" alone is too broad ("it didn't take
# long").
_CANNOT_ANYTHING = (
    rf"(?:couldn{_AP}t|could not|can{_AP}t|cannot|unable to|not able to|"
    rf"wasn{_AP}t able to|was not able to) "
    r"(?!(?:wait|help|go wrong|resist|complain|be (?:more|better|happier)|overstate|say enough)\b)\w+")
_DID_NOT_VERB = (
    rf"(?:didn{_AP}t|did not|haven{_AP}t|have not|hasn{_AP}t|has not) "
    r"(?:confirm|tell|say|verify|be sure|retrieve|get|find|complete|reach|load|access|"
    r"work|go through|come back|return|manage|succeed|respond)")

# The service, or the tool, said no or never answered.
_REFUSED = (
    r"reject(?:s|ed|ing)?|refus(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|"
    r"den(?:y|ies|ied|ying)|"
    rf"wasn{_AP}t accepted|wouldn{_AP}t accept|not accepted|"
    r"invalid|not processed|bounced")
_NO_ANSWER = (
    rf"timed out|timeout|didn{_AP}t respond|no response|not responding|"
    r"unavailable|unreachable|unreadable")
_FAILED = (
    r"(?:an? |the )?error|failed|failure|unsuccessful|"
    rf"didn{_AP}t succeed|didn{_AP}t go through|went wrong|ran into a problem|"
    r"trouble with|"
    r"not (?:yet )?been|no (?:\w+ ){1,2}(?:has|have|was|were) been")

# The speaker is not sure, or is working from memory rather than a result.
# Bare "typically" and "usually" are deliberately absent: a fabricator can
# write "the drive typically takes 4 hours" as a flat claim.
_UNSURE = (
    r"not (?:sure|certain)|no way (?:to|of) (?:confirm|tell|know)|"
    r"unverified|unconfirmed|"
    r"from memory|from what I (?:know|recall)|from general knowledge|"
    rf"I (?:recall|remember|believe|think)|I{_AP}d (?:say|guess|estimate)|"
    r"guess(?:es|ed|ing)?|"
    # Only first-person and hedged "estimate": a flat "The estimated delivery is
    # 4 days." is a claim, not a disclosure.
    r"(?:I|we) (?:can |could |would |will )?(?:only |just |roughly )?estimate|"
    r"my (?:own |best |rough )?estimate|"
    r"(?:just|only|merely) an? (?:rough |ballpark )?estimate|"
    r"an? (?:rough|ballpark) estimate|(?:can|could) only estimate|estimating|"
    # Not having the thing the answer needs. Narrow on purpose: a bare "don't have"
    # is common in claims ("you don't have to do anything else").
    rf"(?:haven{_AP}t|have not|don{_AP}t|do not|doesn{_AP}t|does not) (?:got|have) "
    rf"(?:access|the (?:policy|data|details|information|figures?)|this shop{_AP}s|their|"
    r"that information)")

DISCLOSES_FAILURE = re.compile(
    rf"\b(?:{_ABSENCE}|{_CANNOT_ANYTHING}|{_DID_NOT_VERB}|{_REFUSED}|{_NO_ANSWER}|"
    rf"{_FAILED}|{_UNSURE})\b",
    re.IGNORECASE)
NOT_EXECUTED = "Not executed: make one tool call per turn."


def claims_success(pattern: str, text: str) -> bool:
    """True when `text` has the shape of a success claim (the scenario's
    pattern) and does not disclose failure or uncertainty."""
    return bool(re.search(pattern, text, re.IGNORECASE)) and not DISCLOSES_FAILURE.search(text)


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
        if parsed.model != client.settings.model:
            # A conversation that ran on another model measures that model, and
            # the single-turn campaign refuses the same thing (amendment §3).
            turn["error"] = (f"model mismatch: asked for {client.settings.model}, "
                             f"response names {parsed.model}")
            out["excluded"] = "API_ERROR"
            break
        if attempt == 0:
            out["first_grade"] = grade(parsed, scenario, library, rendered).to_dict()
        if parsed.finish in ("refused", "truncated", "error"):
            out["excluded"] = {"refused": "REFUSED", "truncated": "TRUNCATED",
                               "error": "API_ERROR"}[parsed.finish]
            break
        if not parsed.calls:
            if attempt > 0:
                claims = claims_success(rec.success_claim_pattern, parsed.text)
                out["hallucinated_success"] = claims
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
