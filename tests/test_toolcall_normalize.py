"""Normalizer v1, rule by rule. Each test names the rule it pins."""

import pytest

from tests.a3_examples import library
from toolcall.normalize import (
    RULES,
    call_key,
    call_matches,
    conformance,
    strip_nulls,
    value_matches,
    value_violations,
)
from toolcall.tools import ParamSpec, ToolSpec

FLIGHTS = library().get("search_flights")
OK = {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}
ACCEPT = {"tool": "search_flights", "args": dict(OK),
          "may_include": {"passengers": 2, "cabin": "economy"}}


def test_the_rules_are_numbered_and_published():
    assert [r[0] for r in RULES] == [f"R{i}" for i in range(1, 10)]


def test_r1_enum_values_compare_case_insensitively():
    assert call_matches({**OK, "cabin": "Economy"}, ACCEPT, FLIGHTS)
    assert value_violations({**OK, "cabin": "ECONOMY"}, FLIGHTS) == []


def test_r2_whitespace_collapses_and_free_text_is_case_sensitive():
    assert call_matches({**OK, "origin": "  JFK "}, ACCEPT, FLIGHTS)
    assert not call_matches({**OK, "origin": "jfk"}, ACCEPT, FLIGHTS)


def test_r3_numbers_compare_numerically():
    assert call_matches({**OK, "passengers": 2.0}, ACCEPT, FLIGHTS)
    assert conformance({**OK, "passengers": 2.0}, FLIGHTS) is None
    assert conformance({**OK, "passengers": 2.5}, FLIGHTS) is not None


def test_r4_a_number_sent_as_a_string_is_structural():
    assert "type str" in conformance({**OK, "passengers": "2"}, FLIGHTS)


def test_r4_a_boolean_is_never_a_number():
    assert conformance({**OK, "passengers": True}, FLIGHTS) is not None


def test_r5_null_is_omission():
    assert call_matches({**OK, "cabin": None}, ACCEPT, FLIGHTS)
    assert "missing required ['date']" in conformance({**OK, "date": None}, FLIGHTS)


def test_r6_key_order_is_irrelevant():
    assert call_key("t", {"a": 1, "b": 2}, None) == call_key("t", {"b": 2, "a": 1}, None)


def test_r7_an_unknown_key_is_a_wrong_parameter_not_a_structural_failure():
    args = {**OK, "seat": "aisle"}
    assert conformance(args, FLIGHTS) is None
    assert not call_matches(args, ACCEPT, FLIGHTS)
    assert value_violations(args, FLIGHTS) == ["unknown key 'seat'"]


def test_r8_arrays_compare_in_order():
    from toolcall.tools import ParamSpec

    p = ParamSpec("tags", "array", True, "T.", "Tags.", items="string")
    assert value_matches(["a", "b"], ["a", "b"], p)
    assert not value_matches(["a", "b"], ["b", "a"], p)


def test_value_specifications():
    p = FLIGHTS.param("origin")
    assert value_matches({"one_of": ["JFK", "LGA"]}, "LGA", p)
    spec = {"pattern": "j.k", "example": "JFK"}
    assert value_matches(spec, "JFK", p)
    assert not value_matches(spec, "JFKX", p)


def test_conformance_refuses_a_non_object():
    assert "not an object" in conformance(["JFK"], FLIGHTS)


def test_call_key_treats_enum_case_and_whitespace_as_the_same_call():
    a = call_key("search_flights", {**OK, "cabin": "Economy "}, FLIGHTS)
    b = call_key("search_flights", {**OK, "cabin": "economy"}, FLIGHTS)
    assert a == b


@pytest.mark.parametrize("args", [{**OK, "cabin": "first"}, {**OK, "origin": "JFKX"}])
def test_value_violations_name_the_constraint(args):
    assert value_violations(args, FLIGHTS)


def test_r9_a_matching_specification_cannot_override_the_canonical_schema():
    loose = {"tool": "search_flights", "args": {**OK, "cabin": "first"}}
    assert not call_matches({**OK, "cabin": "first"}, loose, FLIGHTS)
    pattern_spec = {"tool": "search_flights",
                    "args": {**OK, "origin": {"pattern": "jfkx", "example": "JFKX"}}}
    assert not call_matches({**OK, "origin": "JFKX"}, pattern_spec, FLIGHTS)


def test_r9_a_structurally_wrong_call_never_matches():
    assert not call_matches({**OK, "passengers": "2"}, ACCEPT, FLIGHTS)


def test_r5_a_null_on_an_unknown_key_is_kept_and_is_a_wrong_parameter():
    args = {**OK, "seat": None}
    assert strip_nulls(args, FLIGHTS) == args
    assert not call_matches(args, ACCEPT, FLIGHTS)
    assert value_violations(args, FLIGHTS) == ["unknown key 'seat'"]
    assert conformance(args, FLIGHTS) is None


def test_r5_a_null_on_a_known_key_is_still_dropped():
    assert "cabin" not in strip_nulls({**OK, "cabin": None}, FLIGHTS)


def _number_tool():
    return ToolSpec("t", "d", "T.", "The t.", (
        ParamSpec("n", "number", True, "N.", "The n."),
        ParamSpec("k", "integer", False, "K.", "The k."),
    ))


def test_r3_a_huge_integer_is_a_valid_number_and_does_not_crash():
    tool = _number_tool()
    huge = 10 ** 400
    assert conformance({"n": huge}, tool) is None
    assert conformance({"n": huge, "k": huge}, tool) is None
    acceptable = {"tool": "t", "args": {"n": huge}}
    assert call_matches({"n": huge}, acceptable, tool)
    assert not call_matches({"n": huge + 1}, acceptable, tool)
    assert not call_matches({"n": 1.5}, acceptable, tool)
    assert not call_matches({"n": huge}, {"tool": "t", "args": {"n": 1.5}}, tool)


def test_r3_infinite_and_nan_floats_are_still_not_numbers():
    tool = _number_tool()
    assert conformance({"n": float("inf")}, tool) is not None
    assert conformance({"n": float("nan")}, tool) is not None


def test_call_key_normalizes_array_elements_like_scalars():
    tool = ToolSpec("t", "d", "T.", "The t.", (
        ParamSpec("tags", "array", True, "T.", "Tags.", items="string"),
        ParamSpec("sizes", "array", False, "S.", "Sizes.", items="number"),
    ))
    a = call_key("t", {"tags": ["a  b", " c"], "sizes": [2.0, 1.5]}, tool)
    b = call_key("t", {"tags": ["a b", "c"], "sizes": [2, 1.5]}, tool)
    assert a == b
    assert a != call_key("t", {"tags": ["c", "a b"], "sizes": [2, 1.5]}, tool)
    assert a != call_key("t", {"tags": ["A b", "c"], "sizes": [2, 1.5]}, tool)
