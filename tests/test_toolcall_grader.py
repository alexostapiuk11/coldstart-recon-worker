"""Hand-labelled cases for all six categories and the three excluded outcomes,
including every precedence boundary (August §10's definition of done).

Each case is (label, scenario, response, expected category). The boundary
cases are the ones where two rules could both apply and the order decides.
"""

import json

import pytest

from tests.a3_examples import FLIGHT, SMALLTALK, library, scenario
from toolcall.formulation import tool_names
from toolcall.grader import CATEGORIES, EXCLUDED, Grade, grade, parse_arguments
from toolcall.providers import anthropic_parse, openai_parse
from toolcall.responses import (
    anthropic_call,
    anthropic_text,
    openai_call,
    openai_refusal,
    openai_text,
    openai_truncated,
)

OK = {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}
LIB = library()
FLIGHT_S, NOCALL_S = scenario(FLIGHT), scenario(SMALLTALK)
HIGH = tool_names(FLIGHT_S, LIB, "high")
NOCALL_HIGH = tool_names(NOCALL_S, LIB, "high")

CASES = [
    # --- one clear case per category
    ("correct", FLIGHT_S, openai_call("search_flights", {**OK, "passengers": 2}), "CORRECT"),
    ("correct, optional enum in another case", FLIGHT_S,
     openai_call("search_flights", {**OK, "cabin": "Economy"}), "CORRECT"),
    ("correct direct answer", NOCALL_S, openai_text("You're welcome!"), "CORRECT"),
    ("missing", FLIGHT_S, openai_text("There are usually morning flights."), "MISSING"),
    ("spurious", NOCALL_S, openai_call("airport_info", {"code": "JFK"}), "SPURIOUS"),
    ("wrong tool, a confusable", FLIGHT_S, openai_call("flight_prices", {
        "origin": "JFK", "destination": "SFO", "month": "2026-11"}), "WRONG_TOOL"),
    ("wrong params, a value", FLIGHT_S, openai_call("search_flights", {**OK, "date": "2026-11-04"}),
     "WRONG_PARAMS"),
    ("malformed, unparseable", FLIGHT_S,
     openai_call("search_flights", None, raw_arguments='{"origin": "JFK",'), "MALFORMED"),
    # --- precedence boundaries
    ("malformed beats spurious: a broken call where none was expected", NOCALL_S,
     openai_call("airport_info", None, raw_arguments="not json"), "MALFORMED"),
    ("malformed beats wrong tool: a hallucinated tool name", FLIGHT_S,
     openai_call("search_flights_v2", OK), "MALFORMED"),
    ("malformed beats wrong params: a required key missing", FLIGHT_S,
     openai_call("search_flights", {"origin": "JFK", "destination": "SFO"}), "MALFORMED"),
    ("malformed beats wrong params: wrong JSON type", FLIGHT_S,
     openai_call("search_flights", {**OK, "passengers": "2"}), "MALFORMED"),
    ("an enum outside the set is a value error, not structural", FLIGHT_S,
     openai_call("search_flights", {**OK, "cabin": "first"}), "WRONG_PARAMS"),
    ("a pattern violation is a value error, not structural", FLIGHT_S,
     openai_call("search_flights", {**OK, "origin": "New York"}), "WRONG_PARAMS"),
    ("an unknown key is a wrong parameter (R7)", FLIGHT_S,
     openai_call("search_flights", {**OK, "seat": "aisle"}), "WRONG_PARAMS"),
    ("spurious beats wrong tool: any well-formed call where none was expected", NOCALL_S,
     openai_call("search_flights", OK), "SPURIOUS"),
    ("wrong tool beats wrong params: the wrong tool with the right-looking args", FLIGHT_S,
     openai_call("search_trains", {"origin": "JFK", "destination": "SFO",
                                   "date": "2026-11-03"}), "WRONG_TOOL"),
    ("arguments that are not an object are malformed", FLIGHT_S,
     openai_call("search_flights", None, raw_arguments='["JFK"]'), "MALFORMED"),
    ("a call written in text is not a call", FLIGHT_S,
     openai_text('search_flights(origin="JFK", destination="SFO")'), "MISSING"),
    # --- excluded outcomes come first
    ("refusal", FLIGHT_S, openai_refusal(), "REFUSED"),
    ("truncated call", FLIGHT_S, openai_truncated(), "TRUNCATED"),
]


@pytest.mark.parametrize("label, sc, response, expected", CASES, ids=[c[0] for c in CASES])
def test_hand_labelled(label, sc, response, expected):
    rendered = NOCALL_HIGH if sc is NOCALL_S else HIGH
    assert grade(openai_parse(response), sc, LIB, rendered).category == expected


def test_every_category_and_exclusion_is_covered():
    assert {c[3] for c in CASES} == set(CATEGORIES) | (set(EXCLUDED) - {"API_ERROR"})


def test_a_provider_error_is_api_error():
    assert grade(None, FLIGHT_S, LIB, HIGH, error="RateLimitError: 429").category == "API_ERROR"


def test_a_provider_error_state_is_api_error():
    failed = openai_call("search_flights", OK)
    failed["status"] = "failed"
    no_usage = openai_call("search_flights", OK)
    del no_usage["usage"]
    for r in (failed, no_usage):
        g = grade(openai_parse(r), FLIGHT_S, LIB, HIGH)
        assert g.category == "API_ERROR" and "unrecognised terminal state" in g.detail


def test_a_tool_not_rendered_in_this_cell_is_malformed():
    low = tool_names(FLIGHT_S, LIB, "low")
    r = openai_call("flight_prices", {"origin": "JFK", "destination": "SFO", "month": "2026-11"})
    assert grade(openai_parse(r), FLIGHT_S, LIB, low).category == "MALFORMED"


def test_wrong_tool_records_whether_it_was_a_confusable_or_filler():
    conf = grade(openai_parse(openai_call("flight_status", {"flight_number": "UA1"})),
                 FLIGHT_S, LIB, HIGH)
    filler = next(n for n in HIGH if n.startswith("misc_tool"))
    fill = grade(openai_parse(openai_call(filler, {"value": "x"})), FLIGHT_S, LIB, HIGH)
    low = grade(openai_parse(openai_call("search_hotels", {
        "city": "SF", "check_in": "2026-11-03", "nights": 1})), FLIGHT_S, LIB, HIGH)
    assert (conf.wrong_tool_kind, fill.wrong_tool_kind, low.wrong_tool_kind) == (
        "confusable", "filler", "low_set")


def test_the_flags_are_recorded_but_do_not_change_the_category():
    g = grade(openai_parse(openai_text('Use search_flights(origin="JFK")')), FLIGHT_S, LIB, HIGH)
    assert g.category == "MISSING" and g.text_looks_like_call


def test_two_calls_are_graded_on_the_first_and_flagged():
    r = openai_call("search_flights", OK)
    r["output"].append({**r["output"][0], "name": "flight_status",
                        "arguments": json.dumps({"flight_number": "UA1"})})
    g = grade(openai_parse(r), FLIGHT_S, LIB, HIGH)
    assert g.category == "CORRECT" and g.multiple_calls


def test_grading_is_the_same_across_providers():
    oa = grade(openai_parse(openai_call("search_flights", OK)), FLIGHT_S, LIB, HIGH)
    an = grade(anthropic_parse(anthropic_call("search_flights", OK)), FLIGHT_S, LIB, HIGH)
    assert oa.category == an.category == "CORRECT"
    assert grade(anthropic_parse(anthropic_text("", stop_reason="max_tokens")), FLIGHT_S, LIB,
                 HIGH).category == "TRUNCATED"


def test_grading_twice_gives_the_same_answer():
    r = openai_parse(openai_call("search_flights", {**OK, "cabin": "first"}))
    assert grade(r, FLIGHT_S, LIB, HIGH) == grade(r, FLIGHT_S, LIB, HIGH)


def test_the_grade_does_not_depend_on_the_rendered_schema():
    """Amendment §4b: the grader takes the rendered tool names, never the
    rendered schemas, so an enum the loose cell never declared is graded
    against the canonical schema exactly as in the strict cell."""
    import inspect

    assert list(inspect.signature(grade).parameters) == [
        "parsed", "scenario", "library", "rendered", "error"]
    r = openai_parse(openai_call("search_flights", {**OK, "cabin": "first"}))
    assert grade(r, FLIGHT_S, LIB, tool_names(FLIGHT_S, LIB, "low")).category == "WRONG_PARAMS"


def test_arguments_that_make_the_json_parser_raise_are_malformed():
    huge = '{"origin": ' + "9" * 5000 + "}"
    deep = "[" * 100000
    for raw in (huge, deep):
        r = openai_call("search_flights", None, raw_arguments=raw)
        assert grade(openai_parse(r), FLIGHT_S, LIB, HIGH).category == "MALFORMED"
    assert parse_arguments(huge) is None and parse_arguments(deep) is None


def test_an_empty_answer_is_flagged_but_graded_by_the_same_rules():
    g = grade(openai_parse(openai_text("  \n")), NOCALL_S, LIB, NOCALL_HIGH)
    assert g.category == "CORRECT" and g.empty_response
    m = grade(openai_parse(openai_text("")), FLIGHT_S, LIB, HIGH)
    assert m.category == "MISSING" and m.empty_response
    spoken = grade(openai_parse(openai_text("hi")), NOCALL_S, LIB, NOCALL_HIGH)
    assert not spoken.empty_response
    called = grade(openai_parse(openai_call("search_flights", OK)), FLIGHT_S, LIB, HIGH)
    assert not called.empty_response


def test_text_looks_like_call_respects_word_boundaries():
    def flagged(text):
        return grade(openai_parse(openai_text(text)), FLIGHT_S, LIB, HIGH).text_looks_like_call

    assert flagged('search_flights(origin="JFK")')
    assert flagged("search_flights (origin)")
    assert flagged('{"name": "search_flights"}')
    assert not flagged("xsearch_flights(origin)")
    assert not flagged("api.search_flights(origin)")
    assert not flagged("I would search flights for you")


def test_refusal_and_truncation_win_even_when_a_call_is_present():
    refused = openai_refusal()
    refused["output"].append(openai_call("search_flights", OK)["output"][0])
    assert grade(openai_parse(refused), FLIGHT_S, LIB, HIGH).category == "REFUSED"
    assert grade(openai_parse(openai_truncated()), FLIGHT_S, LIB, HIGH).category == "TRUNCATED"


def test_an_api_error_wins_over_a_refusal():
    g = grade(openai_parse(openai_refusal()), FLIGHT_S, LIB, HIGH, error="timeout")
    assert g.category == "API_ERROR"


@pytest.mark.parametrize("raw", ["null", ""])
def test_null_or_empty_raw_arguments_are_malformed(raw):
    r = openai_call("search_flights", None, raw_arguments=raw)
    assert grade(openai_parse(r), FLIGHT_S, LIB, HIGH).category == "MALFORMED"


def test_null_values_follow_r5_through_the_grader():
    optional = openai_call("search_flights", {**OK, "cabin": None})
    assert grade(openai_parse(optional), FLIGHT_S, LIB, HIGH).category == "CORRECT"
    required = openai_call("search_flights", {**OK, "origin": None})
    assert grade(openai_parse(required), FLIGHT_S, LIB, HIGH).category == "MALFORMED"


def test_duplicate_keys_resolve_last_wins():
    raw = '{"origin": "LAX", "origin": "JFK", "destination": "SFO", "date": "2026-11-03"}'
    r = openai_call("search_flights", None, raw_arguments=raw)
    assert grade(openai_parse(r), FLIGHT_S, LIB, HIGH).category == "CORRECT"


def test_two_calls_whose_first_is_bad_are_malformed_and_flagged():
    r = openai_call("search_flights", {"origin": "JFK"})
    r["output"].append({**r["output"][0], "arguments": json.dumps(OK)})
    g = grade(openai_parse(r), FLIGHT_S, LIB, HIGH)
    assert g.category == "MALFORMED" and g.multiple_calls


def test_a_grade_round_trips_through_a_dict():
    g = grade(openai_parse(openai_text('search_flights(origin="JFK")')), FLIGHT_S, LIB, HIGH)
    assert g.text_looks_like_call and g.empty_response is False
    assert Grade.from_dict(g.to_dict()) == g
