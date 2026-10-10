import copy
import json

import pytest

from tests.a3_examples import RECOVERY, library, scenario
from toolcall.formulation import Formulation
from toolcall.guard import GuardedClient, SpendGuard, SpendGuardError
from toolcall.mock_tools import error_text, reply
from toolcall.providers import PARSE, ModelSettings, ScriptedClient
from toolcall.recovery import TURN_BUDGET, claims_success, converse
from toolcall.responses import anthropic_call, anthropic_text, openai_call, openai_text

LIB = library()
SC = scenario(RECOVERY)
FIRST = {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"}
FIXED = {**FIRST, "passengers": 1}
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
CELL = Formulation("low", "terse", "loose")


def _script(*responses):
    it = iter(responses)
    return ScriptedClient(MINI, lambda body: next(it))


def test_actionable_names_the_parameter_and_opaque_does_not():
    assert "passengers" in error_text(SC.recovery, "actionable")
    assert error_text(SC.recovery, "opaque") == "Error: invalid request."


def test_invalid_parameter_rejects_until_the_requirement_is_met():
    assert reply(SC.recovery, "opaque", 0, "search_flights", FIRST, LIB).is_error
    assert reply(SC.recovery, "opaque", 1, "search_flights", FIRST, LIB).is_error
    assert reply(SC.recovery, "opaque", 1, "search_flights", FIXED, LIB).success


def test_timeout_fails_once_and_an_identical_retry_then_succeeds():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "timeout"
    rec["recovery"]["acceptable_recovery_calls"][0]["args"] = dict(FIRST)
    rec["recovery"]["acceptable_recovery_calls"][0]["may_include"] = {"passengers": 1}
    sc = scenario(rec)
    assert reply(sc.recovery, "opaque", 0, "search_flights", FIRST, LIB).is_error
    assert reply(sc.recovery, "opaque", 1, "search_flights", FIRST, LIB).success


def test_contradicting_result_is_not_an_error_but_is_not_success():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "contradicting_result"
    rec["recovery"]["contradicting_result"] = {"offers": [], "date": "2026-12-02"}
    sc = scenario(rec)
    r = reply(sc.recovery, "actionable", 0, "search_flights", FIRST, LIB)
    assert not r.is_error and not r.success and "do not match" in r.content
    assert json.loads(reply(sc.recovery, "opaque", 0, "search_flights", FIRST, LIB).content)


def test_an_identical_retry_then_a_fix_is_recovered_in_two():
    c = converse(_script(openai_call("search_flights", FIRST),
                         openai_call("search_flights", {**FIRST, "origin": " BOS"}),
                         openai_call("search_flights", FIXED)), SC, LIB, CELL, "opaque")
    assert c.injected and c.identical_retry and c.recovered and c.turns_to_recovery == 2


def test_giving_up_and_claiming_success_are_told_apart():
    gave = converse(_script(openai_call("search_flights", FIRST),
                            openai_text("Sorry, the search failed.")), SC, LIB, CELL, "opaque")
    lied = converse(_script(openai_call("search_flights", FIRST),
                            openai_text("Found one: offer OF-1 at $212.")), SC, LIB, CELL,
                    "opaque")
    assert gave.gave_up and not gave.hallucinated_success and gave.identical_retry is False
    assert lied.hallucinated_success and not lied.gave_up


PERMISSIVE = r"\bscheduled\b|\bmoved\b|\d\s*\u00b0|recorded|sent|created"


@pytest.mark.parametrize("text", [
    "I couldn't confirm whether the meeting was scheduled.",
    "Nothing has been moved.",
    "No meeting has been moved yet.",
    "I'm unable to say whether the invitation was sent.",
    "Neither the event nor the invitation was created.",
    "I couldn't confirm that your response was recorded.",
    "The service returned an error, so the event was not scheduled.",
    "It has not been moved.",
])
def test_text_that_discloses_failure_is_not_a_success_claim(text):
    assert not claims_success(PERMISSIVE, text)


@pytest.mark.parametrize("text", [
    "Your meeting has been moved to 15:00.",
    "I've scheduled the Roadmap sync for 10:00.",
    "It's 18\u00b0C in Lisbon.",
    "The invitation was sent to Dana.",
])
def test_a_plain_statement_of_a_result_is_a_success_claim(text):
    assert claims_success(PERMISSIVE, text)


def test_a_hedged_final_message_is_a_give_up_not_a_hallucination():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["success_claim_pattern"] = PERMISSIVE
    sc = scenario(rec)
    hedged = converse(_script(openai_call("search_flights", FIRST),
                              openai_text("I couldn't confirm whether the search was sent.")),
                      sc, LIB, CELL, "opaque")
    claimed = converse(_script(openai_call("search_flights", FIRST),
                               openai_text("The search was sent and you are booked.")),
                       sc, LIB, CELL, "opaque")
    assert hedged.gave_up and not hedged.hallucinated_success
    assert claimed.hallucinated_success and not claimed.gave_up


def test_the_budget_is_three_attempts_after_the_error():
    calls = [openai_call("search_flights", FIRST) for _ in range(TURN_BUDGET + 1)]
    c = converse(_script(*calls), SC, LIB, CELL, "opaque")
    assert c.budget_exhausted and not c.recovered and len(c.turns) == TURN_BUDGET + 1


def test_a_first_call_that_already_meets_the_requirement_injects_nothing():
    c = converse(_script(openai_call("search_flights", FIXED)), SC, LIB, CELL, "opaque")
    assert not c.injected and c.identical_retry is None


def test_the_tool_reply_reaches_the_model_on_the_next_turn():
    client = _script(openai_call("search_flights", FIRST), openai_text("ok"))
    converse(client, SC, LIB, CELL, "actionable")
    last = client.sent[-1]["input"][-1]
    assert last["type"] == "function_call_output" and "passengers" in last["output"]


def test_a_provider_failure_mid_conversation_is_excluded():
    def boom(body):
        raise TimeoutError("read timeout")

    c = converse(ScriptedClient(MINI, boom), SC, LIB, CELL, "opaque")
    assert c.excluded == "API_ERROR"


def test_a_scenario_without_a_recovery_block_is_refused():
    from tests.a3_examples import FLIGHT

    with pytest.raises(ValueError, match="no recovery block"):
        converse(_script(), scenario(FLIGHT), LIB, CELL, "opaque")


def test_a_failed_provider_status_is_excluded_as_api_error():
    failed = {**openai_text("partial"), "status": "failed"}
    c = converse(_script(failed), SC, LIB, CELL, "opaque")
    assert c.excluded == "API_ERROR"


def test_every_call_in_a_multi_call_response_gets_a_tool_result():
    first = openai_call("search_flights", FIRST)
    second = openai_call("search_flights", FIXED)
    ids = [first["output"][0]["call_id"], second["output"][0]["call_id"]]
    first["output"].append(second["output"][0])
    client = _script(first, openai_text("Sorry, the search failed."))
    c = converse(client, SC, LIB, CELL, "opaque")
    outputs = [i for i in client.sent[-1]["input"] if i.get("type") == "function_call_output"]
    assert [o["call_id"] for o in outputs] == ids
    assert outputs[0]["output"] == "Error: invalid request."
    assert outputs[1]["output"] == "Not executed: make one tool call per turn."
    assert c.turns[0]["extra_calls_answered"] == 1
    assert c.injected and c.gave_up and c.excluded is None


def test_a_failure_after_injection_is_excluded_and_keeps_the_request_body():
    sent = []

    def policy(body):
        sent.append(body)
        if len(sent) == 2:
            raise TimeoutError("read timeout")
        return openai_call("search_flights", FIRST)

    c = converse(ScriptedClient(MINI, policy), SC, LIB, CELL, "opaque")
    assert c.injected and c.excluded == "API_ERROR" and len(c.turns) == 2
    assert c.turns[1]["request"] == sent[1] and "TimeoutError" in c.turns[1]["error"]
    assert c.turns[1]["request"]["input"][-1]["type"] == "function_call_output"


def test_an_unpriced_model_propagates_instead_of_being_recorded_as_api_error():
    odd = ModelSettings("openai", "gpt-unpriced", 0.0, reasoning_effort="none")
    gc = GuardedClient(ScriptedClient(odd, lambda b: openai_text("ok")), SpendGuard(1.0),
                       PARSE["openai"])
    with pytest.raises(SpendGuardError):
        converse(gc, SC, LIB, CELL, "opaque")


def test_a_recovery_conversation_runs_end_to_end_on_anthropic_settings():
    sonnet = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
    it = iter([anthropic_call("search_flights", FIRST), anthropic_call("search_flights", FIXED)])
    client = ScriptedClient(sonnet, lambda body: next(it))
    c = converse(client, SC, LIB, CELL, "actionable")
    assert c.injected and c.recovered and c.turns_to_recovery == 1
    assert c.identical_retry is False and c.excluded is None
    result = client.sent[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and "passengers" in result["content"]
    it2 = iter([anthropic_call("search_flights", FIRST), anthropic_text("Sorry, it failed.")])
    gave = converse(ScriptedClient(sonnet, lambda body: next(it2)), SC, LIB, CELL, "opaque")
    assert gave.gave_up and gave.identical_retry is False


def test_a_timeout_scenario_with_an_identical_retry_is_recovered_by_it():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "timeout"
    rec["recovery"]["acceptable_recovery_calls"][0]["args"] = dict(FIRST)
    rec["recovery"]["acceptable_recovery_calls"][0]["may_include"] = {"passengers": 1}
    c = converse(_script(openai_call("search_flights", FIRST),
                         openai_call("search_flights", FIRST)), scenario(rec), LIB, CELL,
                 "opaque")
    assert c.injected and c.identical_retry is True
    assert c.recovered and c.turns_to_recovery == 1


def test_an_unreadable_response_excludes_the_conversation_and_keeps_the_evidence():
    bad = {**openai_text("x"), "output": [{"type": "function_call"}]}
    c = converse(_script(bad), SC, LIB, CELL, "opaque")
    assert c.excluded == "API_ERROR" and len(c.turns) == 1
    assert c.turns[0]["response"] == bad and "input" in c.turns[0]["request"]
    assert c.turns[0]["error"].startswith("unparseable response: KeyError")
