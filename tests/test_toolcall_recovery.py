import copy
import json

import pytest

from tests.a3_examples import RECOVERY, library, scenario
from toolcall.formulation import Formulation
from toolcall.mock_tools import error_text, reply
from toolcall.providers import ModelSettings, ScriptedClient
from toolcall.recovery import TURN_BUDGET, converse
from toolcall.responses import openai_call, openai_text

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
