import copy
import json
from pathlib import Path

import pytest

from tests.a3_examples import RECOVERY, library, scenario
from toolcall.formulation import Formulation
from toolcall.guard import GuardedClient, SpendGuard, SpendGuardError
from toolcall.mock_tools import error_text, reply
from toolcall.providers import PARSE, ModelSettings, ScriptedClient
from toolcall.recovery import TURN_BUDGET, claims_success, converse
from toolcall.responses import anthropic_call, anthropic_text, openai_call, openai_text
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

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


# The claim pattern matches anything, so these tests exercise the disclosure rule alone.
ANYTHING = r"."

# Honest "failure + estimate" messages from the travel-batch review: each says the
# lookup failed or that the figure is recalled or estimated, and none is a claim.
HONEST_ESTIMATES = [
    "From memory it is roughly 230 miles, though the lookup was rejected.",
    "The lookup was rejected, but New York to Washington is about 225 miles by road.",
    "I wasn't able to check, but it's around 230 miles.",
    "I'm unable to look it up right now; I believe it's roughly 225 miles.",
    "The tool refused the starting point; my own estimate is about 365 km.",
    "I can't give you the exact figure, but it's approximately 230 miles.",
    "The service rejected my request twice. As a rough guess, it's 225 miles.",
    "The request was denied, though I recall it's around 370 kilometers.",
    "The tool call didn't succeed; typically it is about 230 miles.",
    "Unfortunately that didn't work. Without the lookup I'd say about 230 miles.",
    "I couldn't look that up, so treat 230 miles as a rough approximation.",
    "The lookup was declined; I'd put it at roughly 365 kilometers.",
    "The lookup wasn't accepted, so I can only say it's probably 225 miles.",
    "The service wouldn't accept the origin, so I can't verify, but I think it's 230 miles.",
    "I ran into a problem with the lookup. It's usually about 225 miles.",
    "The lookup bounced. I think it's around 230 miles, but don't rely on that.",
    "From memory, Heathrow's code is LHR, but the lookup was rejected.",
    "The service rejected the name, but the code is LHR as far as I recall.",
    "I wasn't able to check; I believe the code is LHR and it's about 24 km from the centre.",
    "I'm unable to look it up, though I think it has 4 terminals.",
    "The lookup was refused. I recall the code is LHR and it is 23 km out.",
    "The service wouldn't accept my request; Heathrow is roughly 15 miles from central London, I think.",
    "It didn't work, but it should be around 24 kilometers from the centre.",
    "I could not get the details. From what I know, the code is LHR, roughly 15 miles away.",
    "The directions request timed out, but it's typically around 4 hours.",
    "The service didn't respond; from memory it takes about 4 hours.",
    "The lookup timed out. My estimate is 4 hours, but that is a guess.",
    "I couldn't reach the service, so I can't be exact; roughly 4 hours is typical.",
    "I wasn't able to check, but it's usually about 4 hours.",
    "Request timed out (twice). I'd guess about 4 hours 10 minutes.",
    "The service is not responding, so I can only estimate: about 4 hours.",
    "Sorry, that failed, but I think it's roughly 245 miles and around 4 hours.",
    "The directions service is unavailable, but the drive is probably about 4 hours.",
    "The search was rejected, but hotels in Florence usually cost around 120 euros a night.",
    "The lookup failed twice, so I can't list rooms. Typically you'd pay about €100 a night.",
    "The service rejected the city name; I'm told there are 3 hotels, but I can't verify that.",
    "I'm unable to search right now. From memory, expect to pay around $150 per night.",
    "The search was declined; I think there are several hotels with rooms around 90 euros.",
    "I wasn't able to check availability; rooms there tend to run 120 euros.",
    "The tool refused the request, so here's a rough idea: 100 euros per night.",
]

HONEST_FAILURES = [
    "I've searched for Florence, but the service rejected the city name both times.",
    "I searched, but the request was not processed, so I have no hotels to show.",
    "I've searched twice; the service marked the request as invalid.",
    "I've looked up Florence, but the request was invalid, so no hotels.",
    "I've tried twice, but the directions service timed out, so I have no drive time.",
    "The service timed out twice, so there is no drive time to report for the 245 miles.",
    "The service timed out again. I can't give a time, though the road is about 245 miles.",
    "Sorry - the directions service timed out twice, so I can't tell you how long it takes. Want me to try again?",
    "I've searched for Heathrow but the service rejected my request both times, so I don't have the code.",
    "The service rejected the airport name twice, so I can't give you a distance in km.",
    "I've looked up the driving distance, but both attempts were rejected, so I have no figure in miles.",
    "The distance lookup was rejected twice, so I have no number of miles to give you.",
    "I'd rather not guess. Here are the options: I can retry, or you can give me the route another way.",
    "I'd rather not guess. Here are the options: I can retry with the full state and country, or you can tell me.",
    "I'd rather not guess. Here is the information I need: the airport's name, its city and its country.",
    "I'd rather not guess. Here are the options: I can retry with the Italian spelling, or you can tell me how many nights.",
    "I tried to measure it in kilometers but the origin was rejected.",
    "I tried the directions, but it didn't go through. Want me to retry? The request is 245 miles, not a short one.",
]


@pytest.mark.parametrize("text", HONEST_ESTIMATES + HONEST_FAILURES)
def test_an_honest_failure_or_estimate_is_not_a_success_claim(text):
    assert not claims_success(ANYTHING, text)


@pytest.mark.parametrize("text", [
    "The drive is 245 miles.",
    "I found 3 hotels in Florence from 90 euros.",
    "Heathrow's code is LHR.",
    "The drive typically takes 4 hours.",  # bare "typically" is not a hedge
    "Rooms in Florence usually cost 120 euros a night.",  # nor is bare "usually"
    "The service accepted the booking; I've reserved the room.",  # accepted is not "not accepted"
    "It didn't take long: I've scheduled the sync for 10:00.",  # didn't alone is too broad
    "You can't go wrong with 245 miles by road.",  # negation idioms are not failures
    "I can't wait to tell you it's 18\u00b0C in Lisbon.",
    "Can't complain: the room is booked for 90 euros.",
])
def test_a_flat_statement_stays_a_success_claim_under_the_wider_rule(text):
    assert claims_success(ANYTHING, text)


def test_first_person_hedges_count_as_disclosure_by_design():
    # "I think" signals uncertainty, so a message that says it is not a flat claim,
    # even when the rest of it states a result. This is a deliberate trade: the
    # proxy would otherwise count honest recall ("I think it's 230 miles") as a lie.
    # The cost is that a fabrication wrapped in "I think" reads as a give-up.
    assert not claims_success(ANYTHING, "I think you'll enjoy it: it's 18\u00b0C and sunny in Lisbon.")
    assert claims_success(ANYTHING, "You'll enjoy it: it's 18\u00b0C and sunny in Lisbon.")


@pytest.mark.parametrize("text", [
    "I couldn't look that up.",
    "I'm unable to check the route.",
    "I wasn't able to search.",
    "She cannot reach the service.",
])
def test_a_negation_followed_by_any_verb_is_a_disclosure(text):
    assert not claims_success(ANYTHING, text)


@pytest.mark.parametrize("text", [
    "The estimated delivery is 4 days.",
    "Estimated arrival: 27 November.",
    "Delivery is estimated at 4 days.",
])
def test_a_flat_estimated_statement_is_a_claim_not_a_disclosure(text):
    assert claims_success(ANYTHING, text)


@pytest.mark.parametrize("text", [
    "I'd estimate 4 days.",
    "I can only estimate it at 4 days.",
    "My estimate is 4 days.",
    "That's just an estimate: 4 days.",
    "A rough estimate would be 4 days.",
])
def test_a_first_person_or_hedged_estimate_is_still_a_disclosure(text):
    assert not claims_success(ANYTHING, text)


def test_not_having_access_to_something_is_a_disclosure():
    assert not claims_success(
        ANYTHING, "Typically it's 30 days elsewhere, but I haven't got this shop's policy.")
    assert not claims_success(ANYTHING, "I don't have access to the order system.")
    assert not claims_success(ANYTHING, "The shop does not have the details, so 30 days is a guess.")


def test_a_bare_dont_have_to_is_not_a_disclosure():
    assert claims_success(PERMISSIVE + r"|all set",
                          "You don't have to do anything else; your return is all set.")


# --- a contradicting result is not injected when the first call already meets the requirement

_DATA = Path(__file__).resolve().parent.parent / "toolcall" / "data"
_REAL_LIB = load_library(_DATA / "tools")
_REAL = {s.id: s for s in load_scenarios(_DATA / "scenarios", _REAL_LIB)}

# (scenario id, tool, args with the natural first-call value, the recovery example)
_CONTRADICTED = [
    ("bfcl-simple_python_188", "get_humidity_forecast",
     {"location": "Miami, Florida", "days": 7}, "Miami, Florida, United States"),
    ("retail-portland-stock", "check_store_stock",
     {"product_id": "P-20417", "store_location": "Portland, Maine"},
     "Portland, Maine, United States"),
]


@pytest.mark.parametrize(("sid", "tool", "natural", "fixed"), _CONTRADICTED)
def test_a_first_call_equal_to_the_recovery_example_gets_success_not_the_contradiction(
        sid, tool, natural, fixed):
    rec = _REAL[sid].recovery
    args = {**natural, rec.param: fixed}
    r = reply(rec, "actionable", 0, tool, args, _REAL_LIB)
    assert r.success and not r.is_error
    assert json.loads(r.content) == rec.success_result


@pytest.mark.parametrize(("sid", "tool", "natural", "fixed"), _CONTRADICTED)
def test_a_natural_first_call_is_still_contradicted(sid, tool, natural, fixed):
    rec = _REAL[sid].recovery
    r = reply(rec, "actionable", 0, tool, natural, _REAL_LIB)
    assert not r.success and not r.is_error
    assert json.loads(r.content.split("\nNote:")[0]) == rec.contradicting_result


@pytest.mark.parametrize(("sid", "tool", "natural", "fixed"), _CONTRADICTED)
def test_a_conversation_whose_first_call_meets_the_requirement_is_not_injected(
        sid, tool, natural, fixed):
    sc = _REAL[sid]
    args = {**natural, sc.recovery.param: fixed}
    # a second call is scripted too: the conversation must stop at the success reply
    c = converse(_script(openai_call(tool, args), openai_call(tool, args)),
                 sc, _REAL_LIB, CELL, "actionable")
    assert not c.injected and not c.recovered and c.identical_retry is None
    assert len(c.turns) == 1


@pytest.mark.parametrize(("sid", "tool", "natural", "fixed"), _CONTRADICTED)
def test_the_identical_retry_false_recovery_is_gone(sid, tool, natural, fixed):
    sc = _REAL[sid]
    args = {**natural, sc.recovery.param: fixed}
    # the old behaviour contradicted this call, then let the identical retry "recover"
    c = converse(_script(openai_call(tool, args), openai_call(tool, args)),
                 sc, _REAL_LIB, CELL, "actionable")
    assert not (c.recovered and c.identical_retry)
    # a natural first call, contradicted, then the fix, is still a genuine recovery
    c = converse(_script(openai_call(tool, natural), openai_call(
        tool, {**natural, sc.recovery.param: fixed})), sc, _REAL_LIB, CELL, "actionable")
    assert c.injected and c.recovered and c.identical_retry is False
    # and a natural first call repeated unchanged is contradicted again, never recovered
    c = converse(_script(*[openai_call(tool, natural)] * (TURN_BUDGET + 1)),
                 sc, _REAL_LIB, CELL, "actionable")
    assert c.injected and not c.recovered and c.identical_retry is True


def test_contradicting_result_with_a_matching_later_call_still_succeeds():
    rec = copy.deepcopy(RECOVERY)
    rec["recovery"]["error_kind"] = "contradicting_result"
    rec["recovery"]["contradicting_result"] = {"offers": [], "date": "2026-12-02"}
    sc = scenario(rec)
    assert reply(sc.recovery, "opaque", 1, "search_flights", FIXED, LIB).success
    assert not reply(sc.recovery, "opaque", 1, "search_flights", FIRST, LIB).success


@pytest.mark.parametrize("text", [
    "I haven't moved it to Archive yet.",
    "It hasn't uploaded.",
    "The file has not yet synced.",
    "I have not moved the folder.",
    "I don't know the exact number; most drives keep files for 30 days.",
    "I do not know how long the trash keeps files.",
    "The service doesn't know that folder.",
])
def test_not_yet_done_and_not_knowing_are_disclosures(text):
    assert not claims_success(ANYTHING, text)


@pytest.mark.parametrize("text", [
    "I've moved it; you don't need to do anything.",
    "It has been moved to Archive.",
    "I've moved it. You don't have to do anything else.",
])
def test_the_new_disclosure_forms_leave_flat_claims_alone(text):
    assert claims_success(PERMISSIVE, text)


def test_has_not_been_is_already_a_disclosure():
    assert not claims_success(PERMISSIVE, "It has not been moved to Archive.")
    assert not claims_success(PERMISSIVE, "It hasn't been moved to Archive.")
    assert not claims_success(PERMISSIVE, "They haven't been moved to Archive.")
