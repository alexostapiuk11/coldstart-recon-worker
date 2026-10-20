"""Tests for the practice page: the calculator language, schema, page, brief, tracing."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from study.build import build_practice, has_practice
from study.calc import CALC_JS, CalcError, evaluate, fmt_number, names, parse
from study.page import TOKENS_CSS
from study.practice import calculator_defaults, validate_practice
from study.practice_brief import DRILL_PROMPT, render_practice_brief
from study.practice_page import render_practice_page
from study.schema import ContentError
from study.trace import untraced_practice_numbers
from tests.study_examples import artifact_unit_with_links, practice_block, prereq_unit

# ---- the calculator expression language ----

CASES = [
    # expression, variables, value
    ("2+3*4", {}, 14),
    ("(2+3)*4", {}, 20),
    (" 2 +  3 * 4 ", {}, 14),
    ("10-4-3", {}, 3),
    ("100/10/5", {}, 2),
    ("2^3^2", {}, 512),  # right associative
    ("-2^2", {}, -4),  # a minus binds looser than ^
    ("2^-1", {}, 0.5),
    ("(-2)^2", {}, 4),
    ("--3", {}, 3),
    ("+3", {}, 3),
    ("10/4", {}, 2.5),
    ("1.5e3 + .5", {}, 1500.5),
    ("ceil(7/2)", {}, 4),
    ("floor(-0.5)", {}, -1),
    ("min(4, 2, 9)", {}, 2),
    ("max(a, b) * 2", {"a": 3, "b": 8}, 16),
    ("log2(1024)", {}, 10),
    ("log10(1000)", {}, 3),
    ("sqrt(16) + abs(-3)", {}, 7),
    ("tokens * price / 1000000", {"tokens": 2500000, "price": 3}, 7.5),
    ("ceil(load / (gpus * rate))", {"load": 1000, "gpus": 3, "rate": 120}, 3),
    ("a_1 + _b2", {"a_1": 1, "_b2": 2}, 3),
    ("min(max(1, x), 5)", {"x": 9}, 5),
    ("2^0.5 * 2^0.5", {}, 2.0000000000000004),
]


@pytest.mark.parametrize("expr,env,want", CASES)
def test_python_evaluates_the_grammar(expr, env, want):
    assert evaluate(parse(expr), env) == pytest.approx(want, rel=1e-12)


@pytest.mark.parametrize("expr,message", [
    ("", "empty"),
    ("2 +", "unexpected end"),
    ("(1", "missing '\\)'"),
    ("1)", "unexpected '\\)'"),
    ("1 2", "unexpected number"),
    ("1 $ 2", "unexpected character '\\$'"),
    ("foo(1)", "unknown function 'foo'"),
    ("min(1)", "min needs at least 2 arguments"),
    ("ceil(1, 2)", "ceil takes 1 argument"),
    ("max()", "unexpected '\\)'"),
    ("2 3", "unexpected number"),
    ("a b", "unexpected name 'b'"),
    ("* 2", "unexpected '\\*'"),
    ("1.2.3", "unexpected number"),
])
def test_bad_syntax_is_reported(expr, message):
    with pytest.raises(CalcError, match=message):
        parse(expr)


@pytest.mark.parametrize("expr,env,message", [
    ("1/0", {}, "division by zero"),
    ("1/(x-2)", {"x": 2}, "division by zero"),
    ("sqrt(-1)", {}, "sqrt of a negative"),
    ("log2(0)", {}, "log2 of a non-positive"),
    ("log10(-5)", {}, "log10 of a non-positive"),
    ("(-8)^0.5", {}, "not a finite number"),
    ("10^400", {}, "not a finite number"),
    ("0^-1", {}, "not a finite number"),
    ("x + 1", {}, "no value for 'x'"),
])
def test_evaluation_errors_are_reported_not_inf_or_nan(expr, env, message):
    with pytest.raises(CalcError, match=message):
        evaluate(parse(expr), env)


def test_names_lists_the_input_ids_an_expression_reads():
    assert names(parse("ceil(load / (gpus * rate)) + min(a, 3) + a")) == {
        "load", "gpus", "rate", "a"}
    assert names(parse("2 * 3")) == set()


def test_an_expression_is_bounded():
    with pytest.raises(CalcError, match="longer than 200"):
        parse("1+" * 101 + "1")
    with pytest.raises(CalcError, match="nested deeper than"):
        parse("(" * 40 + "1" + ")" * 40)


@pytest.mark.parametrize("value,digits,want", [
    (1234.5, 0, "1,235"),
    (2.5, 0, "3"),  # halves round up, as JavaScript's toFixed does
    (-2.5, 0, "-3"),
    (0.5, 0, "1"),
    (1234567.891, 2, "1,234,567.89"),
    (0, 3, "0.000"),
    (-0.001, 2, "0.00"),  # never "-0.00"
    (1000, 1, "1,000.0"),
    (0.00005, 4, "0.0001"),
    (999999999999999, 0, "999,999,999,999,999"),
    (1e15, 2, "1.00e+15"),
    (1000500000000000.0 * 10, 3, "1.001e+16"),
    (-3.2e20, 1, "-3.2e+20"),
])
def test_fmt_number_is_fixed_point_with_thousands_commas(value, digits, want):
    assert fmt_number(value, digits) == want


# JavaScript parity: the page evaluates with CALC_JS; both must print the same text.

PARITY = [(e, v) for e, v, _ in CASES] + [
    ("1/0", {}), ("sqrt(-1)", {}), ("log2(0)", {}), ("(-8)^0.5", {}), ("10^400", {}),
    ("0^-1", {}), ("x + 1", {}), ("7/3", {}), ("1/3", {}), ("2/3 * 1000", {}),
    ("10^15", {}), ("10^15 * 1.0005", {}), ("2^60", {}), ("2^-20", {}), ("0.1 + 0.2", {}),
    ("1000 * 1.15", {}), ("1.005 * 1000", {}), ("12345.6789 * 100", {}),
    ("ceil(2.0000001)", {}), ("log2(1000)", {}), ("log10(2)", {}), ("sqrt(2) * 1e6", {}),
    ("min(2.5, 3.5) * 1", {}), ("-0.4999", {}), ("-0.5", {}), ("0.4999", {}), ("2.5", {}),
    ("3.5", {}), ("0.125", {}), ("1e21", {}), ("123456789012345678", {}),
]


def _py_text(expr, env, digits):
    try:
        return fmt_number(evaluate(parse(expr), env), digits)
    except CalcError:
        return "n/a"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_javascript_evaluator_prints_exactly_what_python_prints():
    script = CALC_JS + """
const cases = JSON.parse(process.argv[1]);
const out = cases.map(([expr, env, digits]) => {
  try { return calcFmt(calcEval(calcParse(expr), env), digits); }
  catch (e) { return 'n/a'; }
});
console.log(JSON.stringify(out));
"""
    cases = [(e, v, d) for e, v in PARITY for d in (0, 2, 4)]
    run = subprocess.run(["node", "-e", script, json.dumps(cases)], capture_output=True,
                         text=True, check=True)
    got = json.loads(run.stdout)
    want = [_py_text(e, v, d) for e, v, d in cases]
    assert [(c, g) for c, g, w in zip(cases, got, want) if g != w] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_javascript_parser_rejects_what_python_rejects():
    bad = ["", "2 +", "(1", "1)", "1 2", "1 $ 2", "foo(1)", "min(1)", "ceil(1, 2)", "max()",
           "a b", "* 2", "1.2.3", "1+" * 101 + "1", "(" * 40 + "1" + ")" * 40]
    script = CALC_JS + """
const out = JSON.parse(process.argv[1]).map(s => {
  try { calcParse(s); return 'parsed'; } catch (e) { return 'error'; }
});
console.log(JSON.stringify(out));
"""
    run = subprocess.run(["node", "-e", script, json.dumps(bad)], capture_output=True,
                         text=True, check=True)
    assert json.loads(run.stdout) == ["error"] * len(bad)


def test_the_javascript_evaluator_does_not_use_eval_or_new_function():
    for banned in ("eval(", "new Function", "Function(", "setTimeout(", "import("):
        assert banned not in CALC_JS, banned
    assert "</script" not in CALC_JS.lower()


# ---- the practice.json schema ----


def _unit():
    return artifact_unit_with_links()


def _loader(unit_id):
    """Other units a review may name: p1, whose concept 'units' exists."""
    if unit_id != "p1":
        return None
    u = prereq_unit()
    u["id"] = "p1"
    u["concepts"][0]["id"] = "units"
    return u


def _ok(p=None):
    validate_practice(p or practice_block(), _unit(), "x1", _loader)


def _bad(p, match, loader=_loader):
    with pytest.raises(ContentError, match=match):
        validate_practice(p, _unit(), "x1", loader)


def test_a_valid_practice_passes_with_or_without_the_optional_parts():
    _ok()
    p = practice_block()
    for k in ("calculator", "assumed_numbers", "derived_numbers"):
        del p[k]
    p["lab"].pop("note")
    for c in p["cards"]:
        c.pop("draw", None)
    _ok(p)
    validate_practice(practice_block(), _unit(), "x1")  # no loader: other units unchecked


def test_unit_must_equal_the_folder_name():
    p = practice_block()
    p["unit"] = "a6"
    _bad(p, r"x1\.practice\.unit 'a6' must equal the folder name 'x1'")
    del p["unit"]
    _bad(p, r"x1\.practice: missing 'unit'")


def test_unknown_fields_are_named():
    p = practice_block()
    p["prereq_checks"] = []
    _bad(p, r"x1\.practice: unknown field 'prereq_checks'")
    p = practice_block()
    p["sources"] = [{"file": "a", "section": "b"}]
    _bad(p, r"x1\.practice\.sources: not allowed; numbers trace to the unit's own sources")
    p = practice_block()
    p["links"] = {}
    _bad(p, r"x1\.practice\.links: not allowed")


@pytest.mark.parametrize("field", ["unit", "title", "minutes", "objectives", "prereq_check",
                                   "drills", "estimation", "scenario", "lab", "cards",
                                   "schedule"])
def test_every_required_field_is_named_when_missing(field):
    p = practice_block()
    del p[field]
    _bad(p, rf"x1\.practice: missing '{field}'")


def test_title_minutes_and_objectives_are_bounded():
    p = practice_block()
    p["title"] = "x" * 71
    _bad(p, r"x1\.practice\.title longer than 70 characters")
    p["title"] = " "
    _bad(p, r"x1\.practice\.title is empty")
    p = practice_block()
    for bad in (19, 41):
        p["minutes"] = bad
        _bad(p, r"x1\.practice\.minutes must be 20 to 40")
    p["minutes"] = "30"
    _bad(p, r"x1\.practice\.minutes: expected int")
    p = practice_block()
    p["objectives"] = p["objectives"][:2]
    _bad(p, r"x1\.practice\.objectives: needs 3 to 6 items, has 2")
    p["objectives"] = ["Goal."] * 7
    _bad(p, r"x1\.practice\.objectives: needs 3 to 6 items, has 7")
    p["objectives"] = ["Goal."] * 2 + ["x" * 141]
    _bad(p, r"x1\.practice\.objectives\[2\] longer than 140 characters")
    p["objectives"] = ["Goal."] * 2 + [5]
    _bad(p, r"x1\.practice\.objectives\[2\]: expected str")


def test_prereq_check_is_exactly_three_questions_with_answers_and_a_review_target():
    p = practice_block()
    p["prereq_check"] = p["prereq_check"][:2]
    _bad(p, r"x1\.practice\.prereq_check: needs exactly 3 items, has 2")
    p = practice_block()
    del p["prereq_check"][1]["a"]
    _bad(p, r"x1\.practice\.prereq_check\[1\]: missing 'a'")
    p = practice_block()
    p["prereq_check"][0]["q"] = "x" * 301
    _bad(p, r"x1\.practice\.prereq_check\[0\]\.q longer than 300 characters")
    p["prereq_check"][0]["q"] = "Q?"
    p["prereq_check"][0]["a"] = "x" * 401
    _bad(p, r"x1\.practice\.prereq_check\[0\]\.a longer than 400 characters")


def test_review_names_a_concept_of_this_unit_or_of_another_one():
    p = practice_block()
    p["prereq_check"][0]["review"] = "nope"
    _bad(p, r"x1\.practice\.prereq_check\[0\]\.review 'nope' is not a concept id of x1; "
            r"use one of: arms, contrast")
    p = practice_block()
    p["prereq_check"][2]["review"] = "p1:nope"
    _bad(p, r"prereq_check\[2\]\.review 'p1:nope': unit p1 has no concept with id 'nope'")
    p["prereq_check"][2]["review"] = "p9:units"
    _bad(p, r"prereq_check\[2\]\.review 'p9:units': no unit 'p9'")
    p["prereq_check"][2]["review"] = "p1:units:extra"
    _bad(p, r"prereq_check\[2\]\.review 'p1:units:extra' must be a concept id or "
            r"'<unit>:<concept id>'")
    p["prereq_check"][2]["review"] = ""
    _bad(p, r"prereq_check\[2\]\.review is empty")
    u = _unit()
    for t in u["concepts"]:
        del t["id"]
    p = practice_block()
    p["prereq_check"][0]["review"] = "arms"
    with pytest.raises(ContentError, match=r"is not a concept id of x1; the unit has no concept ids"):
        validate_practice(p, u, "x1", _loader)


def test_drills_are_eight_to_twelve_with_bounded_answers():
    p = practice_block()
    p["drills"] = p["drills"][:7]
    _bad(p, r"x1\.practice\.drills: needs 8 to 12 items, has 7")
    p["drills"] = practice_block()["drills"] * 2
    _bad(p, r"x1\.practice\.drills: needs 8 to 12 items, has 16")
    p = practice_block()
    p["drills"][3]["a"] = "x" * 601
    _bad(p, r"x1\.practice\.drills\[3\]\.a longer than 600 characters")
    p = practice_block()
    del p["drills"][4]["red_flag"]
    _bad(p, r"x1\.practice\.drills\[4\]: missing 'red_flag'")
    p["drills"][4]["red_flag"] = "x" * 301
    _bad(p, r"x1\.practice\.drills\[4\]\.red_flag longer than 300 characters")
    p = practice_block()
    p["drills"][0]["q"] = "x" * 301
    _bad(p, r"x1\.practice\.drills\[0\]\.q longer than 300 characters")
    p = practice_block()
    p["drills"] += [dict(p["drills"][0])] * 4
    _ok(p)  # twelve


def test_estimation_is_one_or_two_problems_with_steps_and_an_answer():
    p = practice_block()
    p["estimation"] = []
    _bad(p, r"x1\.practice\.estimation: needs 1 to 2 items, has 0")
    p["estimation"] = [practice_block()["estimation"][0]] * 3
    _bad(p, r"x1\.practice\.estimation: needs 1 to 2 items, has 3")
    p = practice_block()
    p["estimation"][0]["steps"] = []
    _bad(p, r"x1\.practice\.estimation\[0\]\.steps: needs 2 to 8 items, has 0")
    p["estimation"][0]["steps"] = ["a"] * 9
    _bad(p, r"x1\.practice\.estimation\[0\]\.steps: needs 2 to 8 items, has 9")
    p["estimation"][0]["steps"] = ["a", "x" * 301]
    _bad(p, r"x1\.practice\.estimation\[0\]\.steps\[1\] longer than 300 characters")
    p = practice_block()
    p["estimation"][0]["problem"] = "x" * 501
    _bad(p, r"x1\.practice\.estimation\[0\]\.problem longer than 500 characters")
    p = practice_block()
    del p["estimation"][0]["answer"]
    _bad(p, r"x1\.practice\.estimation\[0\]: missing 'answer'")
    p["estimation"][0]["answer"] = "x" * 301
    _bad(p, r"x1\.practice\.estimation\[0\]\.answer longer than 300 characters")
    p = practice_block()
    p["estimation"][0]["title"] = "x" * 81
    _bad(p, r"x1\.practice\.estimation\[0\]\.title longer than 80 characters")


def test_scenario_has_a_prompt_an_outline_and_pitfalls():
    p = practice_block()
    p["scenario"]["prompt"] = "x" * 601
    _bad(p, r"x1\.practice\.scenario\.prompt longer than 600 characters")
    p = practice_block()
    p["scenario"]["outline"] = ["a", "b"]
    _bad(p, r"x1\.practice\.scenario\.outline: needs 3 to 8 items, has 2")
    p = practice_block()
    p["scenario"]["pitfalls"] = ["a"]
    _bad(p, r"x1\.practice\.scenario\.pitfalls: needs 2 to 6 items, has 1")
    p = practice_block()
    p["scenario"]["pitfalls"] = ["a", "x" * 301]
    _bad(p, r"x1\.practice\.scenario\.pitfalls\[1\] longer than 300 characters")
    p = practice_block()
    del p["scenario"]["outline"]
    _bad(p, r"x1\.practice\.scenario: missing 'outline'")


def test_lab_fields_cost_and_bounds():
    for cost in ("none", "local", "gpu", "paid"):
        p = practice_block()
        p["lab"]["cost"] = cost
        _ok(p)
    p = practice_block()
    p["lab"]["cost"] = "free"
    _bad(p, r"x1\.practice\.lab\.cost 'free' not in \('none', 'local', 'gpu', 'paid'\)")
    for f in ("goal", "setup", "steps", "metrics", "expected", "demonstrates", "cost"):
        p = practice_block()
        del p["lab"][f]
        _bad(p, rf"x1\.practice\.lab: missing '{f}'")
    p = practice_block()
    p["lab"]["setup"] = []
    _bad(p, r"x1\.practice\.lab\.setup: needs 1 to 8 items, has 0")
    p = practice_block()
    p["lab"]["steps"] = ["one"]
    _bad(p, r"x1\.practice\.lab\.steps: needs 2 to 12 items, has 1")
    p = practice_block()
    p["lab"]["metrics"] = ["a"] * 7
    _bad(p, r"x1\.practice\.lab\.metrics: needs 1 to 6 items, has 7")
    p = practice_block()
    p["lab"]["expected"] = "x" * 501
    _bad(p, r"x1\.practice\.lab\.expected longer than 500 characters")
    p = practice_block()
    p["lab"]["note"] = ""
    _bad(p, r"x1\.practice\.lab\.note is empty")
    p["lab"]["note"] = "x" * 301
    _bad(p, r"x1\.practice\.lab\.note longer than 300 characters")


def test_cards_are_one_to_twenty_five_and_draw_is_a_bool():
    p = practice_block()
    p["cards"] = []
    _bad(p, r"x1\.practice\.cards: needs 1 to 25 items, has 0")
    p["cards"] = [practice_block()["cards"][0]] * 26
    _bad(p, r"x1\.practice\.cards: needs 1 to 25 items, has 26")
    p["cards"] = [practice_block()["cards"][0]] * 25
    _ok(p)
    p = practice_block()
    p["cards"][1]["draw"] = "yes"
    _bad(p, r"x1\.practice\.cards\[1\]\.draw: expected bool")
    p = practice_block()
    p["cards"][2]["tag"] = "x" * 31
    _bad(p, r"x1\.practice\.cards\[2\]\.tag longer than 30 characters")
    p = practice_block()
    p["cards"][0]["front"] = "x" * 201
    _bad(p, r"x1\.practice\.cards\[0\]\.front longer than 200 characters")
    p = practice_block()
    p["cards"][0]["back"] = "x" * 401
    _bad(p, r"x1\.practice\.cards\[0\]\.back longer than 400 characters")
    p = practice_block()
    del p["cards"][0]["back"]
    _bad(p, r"x1\.practice\.cards\[0\]: missing 'back'")


def test_schedule_is_three_to_five_slots():
    p = practice_block()
    p["schedule"] = p["schedule"][:2]
    _bad(p, r"x1\.practice\.schedule: needs 3 to 5 items, has 2")
    p["schedule"] = practice_block()["schedule"] * 2
    _bad(p, r"x1\.practice\.schedule: needs 3 to 5 items, has 6")
    p = practice_block()
    p["schedule"][1]["when"] = "x" * 41
    _bad(p, r"x1\.practice\.schedule\[1\]\.when longer than 40 characters")
    p = practice_block()
    p["schedule"][1]["test"] = "x" * 201
    _bad(p, r"x1\.practice\.schedule\[1\]\.test longer than 200 characters")


def _calc(p, **change):
    p["calculator"].update(change)
    return p


def test_calculator_inputs_and_outputs_are_bounded_and_located():
    p = practice_block()
    p["calculator"]["title"] = "x" * 71
    _bad(p, r"x1\.practice\.calculator\.title longer than 70 characters")
    p = practice_block()
    p["calculator"]["inputs"] = []
    _bad(p, r"x1\.practice\.calculator\.inputs: needs 1 to 6 items, has 0")
    p["calculator"]["inputs"] = [dict(practice_block()["calculator"]["inputs"][0],
                                      id=f"v{i}") for i in range(7)]
    _bad(p, r"x1\.practice\.calculator\.inputs: needs 1 to 6 items, has 7")
    p = practice_block()
    p["calculator"]["outputs"] = []
    _bad(p, r"x1\.practice\.calculator\.outputs: needs 1 to 6 items, has 0")
    p = practice_block()
    p["calculator"]["outputs"] = [practice_block()["calculator"]["outputs"][0]] * 7
    _bad(p, r"x1\.practice\.calculator\.outputs: needs 1 to 6 items, has 7")
    p = practice_block()
    p["calculator"]["note"] = "x" * 301
    _bad(p, r"x1\.practice\.calculator\.note longer than 300 characters")


@pytest.mark.parametrize("change,match", [
    ({"id": "2fast"}, r"inputs\[0\]\.id '2fast' is not an identifier"),
    ({"id": "has space"}, r"inputs\[0\]\.id 'has space' is not an identifier"),
    ({"id": "min"}, r"inputs\[0\]\.id 'min' is a function name"),
    ({"label": "x" * 41}, r"inputs\[0\]\.label longer than 40 characters"),
    ({"unit": "x" * 13}, r"inputs\[0\]\.unit longer than 12 characters"),
    ({"min": 2000}, r"inputs\[0\]: needs min < max, got 2000 and 2000"),
    ({"value": 5}, r"inputs\[0\]\.value 5 is outside min 10 and max 2000"),
    ({"value": 2001}, r"inputs\[0\]\.value 2001 is outside min 10 and max 2000"),
    ({"step": 0}, r"inputs\[0\]\.step must be above zero"),
    ({"step": -1}, r"inputs\[0\]\.step must be above zero"),
    ({"value": "250"}, r"inputs\[0\]\.value: expected float"),
    ({"value": float("nan")}, r"inputs\[0\]\.value must be a finite number"),
])
def test_calculator_inputs_are_checked(change, match):
    p = practice_block()
    p["calculator"]["inputs"][0].update(change)
    _bad(p, r"x1\.practice\.calculator\." + match)


def test_calculator_input_ids_are_unique():
    p = practice_block()
    p["calculator"]["inputs"][1]["id"] = "rps"
    _bad(p, r"x1\.practice\.calculator\.inputs\[1\]: duplicate id 'rps'")


@pytest.mark.parametrize("change,match", [
    ({"digits": 5}, r"outputs\[1\]\.digits must be 0 to 4"),
    ({"digits": -1}, r"outputs\[1\]\.digits must be 0 to 4"),
    ({"digits": 1.5}, r"outputs\[1\]\.digits: expected int"),
    ({"label": ""}, r"outputs\[1\]\.label is empty"),
    ({"unit": "x" * 13}, r"outputs\[1\]\.unit longer than 12 characters"),
    ({"expr": "rps *"}, r"outputs\[1\]\.expr: unexpected end of the expression"),
    ({"expr": "rps ** 2"}, r"outputs\[1\]\.expr: unexpected '\*'"),
    ({"expr": "x" * 201}, r"outputs\[1\]\.expr: the expression is longer than 200"),
    ({"expr": "rps * gpus"}, (r"outputs\[1\]\.expr reads 'gpus', which is not an input id; "
                             r"the inputs are rps, seconds, slots, target")),
    ({"expr": "rps / 0"}, r"outputs\[1\]\.expr fails at the default inputs: division by zero"),
    ({"expr": 5}, r"outputs\[1\]\.expr: expected str"),
])
def test_calculator_outputs_are_checked(change, match):
    p = practice_block()
    p["calculator"]["outputs"][1].update(change)
    _bad(p, r"x1\.practice\.calculator\." + match)


def test_an_expression_must_stay_finite_at_every_min_and_max_combination():
    p = practice_block()
    p["calculator"]["inputs"][1].update(min=0, value=0.8)  # seconds may reach 0
    p["calculator"]["outputs"][1]["expr"] = "rps / seconds"
    _bad(p, r"outputs\[1\]\.expr fails when rps=10, seconds=0, slots=1, target=0.3: "
            r"division by zero")
    p = practice_block()
    p["calculator"]["outputs"][0]["expr"] = "2 ^ (rps * 100)"  # overflows at the maximum
    _bad(p, r"outputs\[0\]\.expr fails (at the default inputs|when rps=\d+).*finite")


def test_every_input_must_feed_an_output():
    p = practice_block()
    p["calculator"]["inputs"].append({"id": "spare", "label": "Spare", "value": 1, "min": 0,
                                      "max": 2, "step": 1})
    _bad(p, r"x1\.practice\.calculator\.inputs\[4\] 'spare' is read by no output")


def test_assumed_and_derived_numbers_have_their_reasons():
    p = practice_block()
    p["assumed_numbers"][0]["why"] = ""
    _bad(p, r"x1\.practice\.assumed_numbers\[0\]\.why is empty")
    p = practice_block()
    del p["assumed_numbers"][1]["value"]
    _bad(p, r"x1\.practice\.assumed_numbers\[1\]: missing 'value'")
    p = practice_block()
    p["assumed_numbers"][1]["value"] = "x" * 41
    _bad(p, r"x1\.practice\.assumed_numbers\[1\]\.value longer than 40 characters")
    p = practice_block()
    del p["derived_numbers"][0]["how"]
    _bad(p, r"x1\.practice\.derived_numbers\[0\]: missing 'how'")


def test_inline_links_are_checked_like_the_units_other_text():
    p = practice_block()
    p["drills"][2]["a"] = "See [the arm](x1:arms) and [it](nowhere:term)."
    _bad(p, r"x1\.practice\.drills\[2\]\.a: link to unknown unit 'nowhere'")
    p["drills"][2]["a"] = "See [the arm](x1:arms)."
    _ok(p)
    p = practice_block()
    p["cards"][0]["back"] = "bad \x01 char"
    _bad(p, r"x1\.practice\.cards\[0\]\.back: contains a control character")


def test_calculator_defaults_are_computed_in_python():
    assert calculator_defaults(practice_block()["calculator"]) == [
        ("Requests in flight", "200", ""),
        ("Servers needed", "36", ""),
        ("Real utilisation", "69.4", "%"),
    ]


# ---- tracing: practice numbers trace to the unit's sources or are declared ----


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def _traced_unit(tmp_path):
    u = _unit()
    u["sources"] = [{"file": _write(tmp_path, "post.md", "# Title\nMedian 81.12 s and 35,792 "
                                                        "tokens.\n"), "section": "Title"}]
    u["derived_numbers"] = [{"value": "4.75", "how": "invented"}]
    return u


def test_the_fixture_has_no_untraced_numbers(tmp_path):
    assert untraced_practice_numbers(practice_block(), _traced_unit(tmp_path)) == []


def test_numbers_trace_to_the_units_sources_and_derived_numbers(tmp_path):
    u, p = _traced_unit(tmp_path), practice_block()
    p["drills"][0]["a"] = "It took 81.12 s, 35,792 tokens and 4.75 of something."
    assert untraced_practice_numbers(p, u) == []
    p["drills"][1]["a"] = "It took 99.99 s, and 1234 of those."
    assert untraced_practice_numbers(p, u) == ["99.99", "1234"]


def test_practice_derived_and_assumed_numbers_are_declared_numbers(tmp_path):
    u, p = _traced_unit(tmp_path), practice_block()
    p["cards"][0]["back"] = "Roughly 777 and 8.25, and 5.60."
    assert untraced_practice_numbers(p, u) == ["777", "8.25"]  # 5.60 is the derived 5.6
    p["assumed_numbers"].append({"value": "777 requests", "why": "A round example."})
    p["derived_numbers"].append({"value": "8.25", "how": "33 / 4"})
    assert untraced_practice_numbers(p, u) == []


def test_the_declarations_themselves_and_the_calculator_expression_are_not_scanned(tmp_path):
    u, p = _traced_unit(tmp_path), practice_block()
    p["assumed_numbers"].append({"value": "5555", "why": "Used for 6666 too."})
    p["derived_numbers"][0]["how"] = "7777 / 2"
    p["calculator"]["outputs"][0]["expr"] = "rps * seconds * 1024"
    p["unit"] = "x1"
    assert untraced_practice_numbers(p, u) == []


def test_calculator_prose_is_scanned_but_its_numeric_fields_are_not(tmp_path):
    u, p = _traced_unit(tmp_path), practice_block()
    p["calculator"]["note"] = "Try 4242 requests."
    p["calculator"]["inputs"][0]["value"] = 999
    assert untraced_practice_numbers(p, u) == ["4242"]


# ---- the page ----


def _page(p=None, unit=None, loader=_loader):
    return render_practice_page(p or practice_block(), unit or _unit(), loader)


def _brief(p=None, unit=None, loader=_loader):
    return render_practice_brief(p or practice_block(), unit or _unit(), loader)


def _section(page, sid):
    return page.split(f'<section id="{sid}">')[1].split("</section>")[0]


def _css(page):
    return page.split("<style>")[1].split("</style>")[0]


def test_the_page_is_one_self_contained_file_the_publish_script_can_extract():
    page = _page()
    assert page.startswith("<!doctype html>") and page.count("<style>") == 1
    assert page.count("<script>") == 1 and page.count("<title>") == 1
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in page
    # the scratchpad extract.py takes the title, the style and everything inside <body>
    assert re.search(r"<title>.*?</title>", page, re.DOTALL) and re.search(r"<style>.*?</style>", page, re.DOTALL)
    body = re.search(r"<body[^>]*>(.*)</body>", page, re.DOTALL).group(1)
    assert body.startswith("<main>") and body.rstrip().endswith("</script>")
    assert "<title>Practice: reading a cold start</title>" in page
    for banned in ("http://", "https://", "src=", "@import", "url("):
        assert banned not in page, banned


def test_the_page_shares_the_study_pages_tokens_and_dark_mode():
    css = _css(_page())
    assert css.startswith(TOKENS_CSS)
    assert "prefers-color-scheme: dark" in css and ':root[data-theme="dark"]' in css
    rest = css[len(TOKENS_CSS):]
    # only the phone pills bar's scroll-fade mask (copied from the study page) is black
    assert set(re.findall(r"#[0-9a-fA-F]{3,8}\b", rest)) <= {"#000"} and "rgb" not in rest


def test_sections_come_in_the_specified_order_with_a_pill_each():
    page = _page()
    ids = re.findall(r'<section id="([\w-]+)"', page)
    assert ids == ["objectives", "check", "estimation", "drills", "scenario", "lab",
                   "calculator", "cards", "schedule", "assumptions"]
    nav = page.split('<nav class="pills">')[1].split("</nav>")[0]
    assert re.findall(r'<a href="#([\w-]+)">([^<]+)</a>', nav) == [
        ("objectives", "Objectives"), ("check", "Check first"), ("estimation", "Estimation"),
        ("drills", "Drills"), ("scenario", "Scenario"), ("lab", "Lab"),
        ("calculator", "Calculator"), ("cards", "Cards"), ("schedule", "Schedule"),
        ("assumptions", "Assumptions")]
    p = practice_block()
    del p["calculator"], p["assumed_numbers"], p["derived_numbers"]
    assert "calculator" not in re.findall(r'<section id="([\w-]+)"', _page(p))
    assert "assumptions" not in re.findall(r'<section id="([\w-]+)"', _page(p))


def test_dom_ids_are_unique():
    ids = re.findall(r' id="([^"]+)"', _page())
    assert len(ids) == len(set(ids))


def test_header_has_title_unit_and_minutes():
    hero = _page().split('<header class="hero">')[1].split("</header>")[0]
    assert "<h1>Practice: reading a cold start</h1>" in hero
    assert "Practice for: Example artifact" in hero and "about 30 min" in hero


def test_objectives_are_a_list():
    sec = _section(_page(), "objectives")
    assert sec.count("<li>") == 3 and "Say where the time of one cold start goes" in sec


def test_prereq_check_hides_the_answer_and_names_the_concept_to_review():
    sec = _section(_page(), "check")
    items = re.findall(r'<div class="card pq">(.*?)</details></div>', sec, re.DOTALL)
    assert len(items) == 3
    first = items[0]
    assert "What is an arm?" in first.split("<details>")[0]
    assert "One set-up under test." not in first.split("<details>")[0]
    inside = first.split("<details>")[1]
    assert "One set-up under test." in inside
    assert 'If you missed it, review <a href="page.html#c-arms">Arm</a>' in inside
    assert ('review <a href="../p1/page.html#c-units">Term 0</a>' in items[2])


def test_a_review_of_an_unloadable_unit_still_links_by_concept_id():
    sec = _section(_page(loader=None), "check")
    assert 'href="../p1/page.html#c-units">units</a>' in sec


def test_drills_show_the_question_and_hide_both_answers():
    sec = _section(_page(), "drills")
    cards = re.findall(r'<div class="card drill" id="drill-(\d+)">(.*?)</details></div>', sec,
                       re.DOTALL)
    assert [n for n, _ in cards] == [str(i) for i in range(1, 9)]
    html_ = cards[2][1]
    shown = html_.split("<details")[0]
    assert "Drill 3 of 8" in shown and "Drill question 3?" in shown
    assert "Model answer 3" not in shown and "tempting wrong answer 3" not in shown
    assert html_.count("<details") == 2
    assert "<summary>Model answer</summary>" in html_ and "Model answer 3, with" in html_
    assert "<summary>Red-flag answer</summary>" in html_ and "tempting wrong answer 3" in html_
    assert html_.index("Model answer</summary>") < html_.index("Red-flag answer</summary>")


def test_estimation_hides_steps_and_answer():
    sec = _section(_page(), "estimation")
    assert "Servers for a steady load" in sec
    shown = sec.split("<details")[0]
    assert "250 requests a second" in shown and "About 36 servers." not in shown
    body = sec.split("<details")[1]
    assert body.count("<li>") == 3 and "About 36 servers." in body


def test_scenario_shows_the_prompt_and_hides_the_outline_and_pitfalls():
    sec = _section(_page(), "scenario")
    shown = sec.split("<details")[0]
    assert "Design the harness that runs one cold start many times" in shown
    assert "Interleave the runs" not in shown and "Retrying a failed run." not in shown
    assert sec.count("<details") == 2
    assert "Interleave the runs; never batch an arm." in sec.split("<details")[1]
    assert "Retrying a failed run." in sec.split("<details")[2]


def test_lab_card_has_a_cost_badge_words_and_colour_class():
    sec = _section(_page(), "lab")
    assert '<span class="badge cost-local">Runs on your machine</span>' in sec
    for cost, words in (("none", "No cost"), ("gpu", "Needs a GPU"), ("paid", "Paid API calls")):
        p = practice_block()
        p["lab"]["cost"] = cost
        assert f'<span class="badge cost-{cost}">{words}</span>' in _section(_page(p), "lab")
    assert "Reproduce the phase split of one cold start on a laptop." in sec
    assert sec.count("<li>") == 2 + 2 + 2  # setup, steps, metrics
    assert "Nothing here calls a paid API." in sec
    # the expected result and what it shows are behind a disclosure
    assert "Loading weights is the largest phase." not in sec.split("<details")[0]
    assert "The split can be re-derived with no GPU." in sec.split("<details")[1]
    p = practice_block()
    del p["lab"]["note"]
    assert "Nothing here" not in _section(_page(p), "lab")


def test_cards_show_the_front_hide_the_back_and_mark_the_ones_to_draw():
    sec = _section(_page(), "cards")
    cards = re.findall(r'<details class="rcard[^"]*">(.*?)</details>', sec, re.DOTALL)
    assert len(cards) == 3
    summary, back = cards[0].split("</summary>")
    assert "Name the phases of a cold start." in summary and "phases" in summary
    assert "Load, compile, warm up, serve." in back and "Load, compile" not in summary
    assert "Draw it" not in cards[0] and "Draw it" in cards[1].split("</summary>")[0]
    assert sec.count('rcard draw') == 1


def test_schedule_lists_each_slot():
    sec = _section(_page(), "schedule")
    assert sec.count("<li>") == 3
    assert "<b>Same day</b>" in sec and "The scenario, out loud, in five minutes." in sec


def test_assumptions_are_listed_collapsed():
    sec = _section(_page(), "assumptions")
    assert "<details" in sec and "<code>250</code>" in sec
    assert "A round request rate chosen for the example." in sec


def test_text_is_escaped_and_inline_markup_and_links_work():
    p = practice_block()
    p["drills"][0]["q"] = "Why <script>alert(1)</script> and **bold** and `code`?"
    p["drills"][0]["a"] = "See [the arm](x1:arms) and [units](p1:units)."
    unit = _unit()
    unit["prereqs"] = [{"unit": "p1", "label": "Units"}]
    page = _page(p, unit)
    assert "<script>alert" not in page and "&lt;script&gt;alert(1)" in page
    assert "<strong>bold</strong>" in page and "<code>code</code>" in page
    assert '<a href="page.html#c-arms" target="_blank" rel="noopener">the arm</a>' in page
    assert 'href="../p1/page.html#c-units"' in page


def test_the_page_reads_without_scripts_and_the_script_only_enhances():
    page = _page()
    body = page.split("<body>")[1].split("<script>")[0]
    # only the JS-only reset button is hidden by the HTML
    assert body.count("hidden") == body.count('class="calc-reset" hidden') == 1
    assert "<details open" not in body
    js = page.split("<script>")[1]
    for banned in ("eval(", "new Function", "Function("):
        assert banned not in js


def test_phone_and_dark_mode_rules_exist():
    css = _css(_page())
    assert "@media (max-width:600px)" in css and "overflow-wrap" in css
    assert "details.src" not in css  # the page's own css, not a copy of the study page's


# ---- the calculator on the page ----


def test_the_calculator_renders_defaults_computed_in_python_and_the_expressions():
    sec = _section(_page(), "calculator")
    assert "How many servers?" in sec and "Change the load and watch the count move." in sec
    outs = re.findall(r'<output[^>]*data-expr="([^"]*)"[^>]*data-digits="(\d)"[^>]*>([^<]*)</output>',
                      sec)
    assert outs == [("rps * seconds", "0", "200"),
                    ("ceil(rps * seconds / (slots * target))", "0", "36"),
                    ("rps * seconds / (ceil(rps * seconds / (slots * target)) * slots) * 100",
                     "1", "69.4")]
    assert sec.count('type="number"') == 4 and sec.count('type="range"') == 4
    assert re.search(r'<input type="number" id="calc-rps" data-id="rps" value="250" min="10" '
                     r'max="2000" step="any" disabled>', sec)
    assert re.search(r'<input type="range" data-for="rps" value="250" min="10" max="2000" '
                     r'step="10" disabled', sec)
    assert "req/s" in sec and ">%<" in sec
    assert "data-calc" in sec and "Reset" in sec


def test_the_calculator_script_and_style_ship_only_with_a_calculator():
    p = practice_block()
    del p["calculator"]
    page = _page(p)
    for marker in ("calcParse", "data-calc", ".calc-", "calcFmt"):
        assert marker not in page, marker
    full = _page()
    assert "function calcParse" in full.split("<script>")[1] and ".calc-row" in _css(full)


def test_the_calculator_page_script_is_calc_js_plus_the_wiring():
    js = _page().split("<script>")[1]
    assert CALC_JS.strip() in js
    assert "calcEval" in js.split(CALC_JS.strip())[1]


# ---- the brief ----


def test_brief_has_every_section_in_order_and_ends_with_the_drill_prompt():
    brief = _brief()
    heads = re.findall(r"^## (.+)$", brief, re.MULTILINE)
    assert heads == ["How to use this brief", "Objectives", "Check yourself first",
                     "Estimation drills", "Deep-dive drills", "Design scenario", "Lab",
                     "Calculator", "Recall cards", "Review schedule", "Assumed numbers",
                     "Drill mode (paste this to an AI chat)"]
    assert brief.rstrip().endswith(DRILL_PROMPT.rstrip())
    assert brief.startswith("# Practice: reading a cold start: practice brief")


def test_brief_marks_every_answer_as_the_key_and_names_the_red_flag():
    brief = _brief()
    drills = brief.split("## Deep-dive drills")[1].split("\n## ")[0]
    assert drills.count("KEY:") == 8 and drills.count("RED FLAG:") == 8
    assert "Q: Drill question 3?\nKEY: Model answer 3, with the reason.\n" \
           "RED FLAG: The tempting wrong answer 3." in drills
    check = brief.split("## Check yourself first")[1].split("\n## ")[0]
    assert "KEY: One set-up under test." in check
    assert "If missed, review: Arm" in check and "Term 0 (P1: units)" in check
    est = brief.split("## Estimation drills")[1].split("\n## ")[0]
    assert "Problem: A service gets 250" in est and "KEY steps:" in est
    assert "KEY answer: About 36 servers." in est
    scenario = brief.split("## Design scenario")[1].split("\n## ")[0]
    assert "Prompt: Design the harness" in scenario and "KEY outline:" in scenario
    assert "KEY pitfalls:" in scenario
    cards = brief.split("## Recall cards")[1].split("\n## ")[0]
    assert "- [phases] Name the phases of a cold start. -> KEY: Load, compile, warm up, " \
           "serve." in cards
    assert "[draw]" in cards and cards.count("KEY:") == 3


def test_brief_has_the_lab_calculator_schedule_and_assumptions_as_plain_text():
    brief = _brief()
    lab = brief.split("## Lab")[1].split("\n## ")[0]
    assert "Cost: runs on your machine" in lab and "Goal: Reproduce the phase split" in lab
    assert "KEY expected result: Loading weights is the largest phase." in lab
    calc = brief.split("## Calculator")[1].split("\n## ")[0]
    assert "- Requests per second: 250 req/s (range 10 to 2000)" in calc
    assert "- Servers needed = 36" in calc and "- Real utilisation = 69.4 %" in calc
    assert "ceil(rps * seconds / (slots * target))" in calc
    sched = brief.split("## Review schedule")[1].split("\n## ")[0]
    assert "- Same day: Drills 1 to 4 and the cards." in sched
    assert "- 250: A round request rate chosen for the example." in brief
    assert "<" not in brief.replace("->", "").replace("<=", "")  # no html


def test_brief_resolves_links_to_text():
    p = practice_block()
    p["drills"][0]["a"] = "See [the arm](x1:arms) and [units](p1:units)."
    unit = _unit()
    unit["prereqs"] = [{"unit": "p1", "label": "Units"}]
    assert "See the arm and units (P1: units)." in _brief(p, unit)


def test_brief_stays_compact_for_a_typical_unit():
    assert len(_brief().encode()) < 16 * 1024


def test_the_drill_prompt_has_the_rules():
    for needle in ("one question at a time", "KEY", "RED FLAG", "Review schedule",
                   "the brief does not say"):
        assert needle in DRILL_PROMPT, needle


# ---- building ----


def _make_unit_dir(tmp_path, practice=None):
    study = tmp_path / "study"
    (study / "x1").mkdir(parents=True)
    unit = _traced_unit(tmp_path)
    (study / "x1" / "content.json").write_text(json.dumps(unit))
    if practice is not False:
        (study / "x1" / "practice.json").write_text(json.dumps(practice or practice_block()))
    p1 = prereq_unit()
    p1["id"] = "p1"
    p1["concepts"][0]["id"] = "units"
    (study / "p1").mkdir()
    (study / "p1" / "content.json").write_text(json.dumps(p1))
    return study


def test_build_practice_validates_and_renders_both_files(tmp_path):
    study = _make_unit_dir(tmp_path)
    assert has_practice(study / "x1") and not has_practice(study / "p1")
    page, brief = build_practice(study / "x1")
    assert page == _page() and brief == _brief()  # p1 was found next to x1


def test_build_practice_names_the_field_of_a_bad_file(tmp_path):
    p = practice_block()
    p["drills"][1]["a"] = "x" * 601
    study = _make_unit_dir(tmp_path, p)
    with pytest.raises(ContentError, match=r"x1\.practice\.drills\[1\]\.a longer than 600"):
        build_practice(study / "x1")


def test_build_practice_checks_a_review_in_another_unit(tmp_path):
    p = practice_block()
    p["prereq_check"][2]["review"] = "p1:nope"
    study = _make_unit_dir(tmp_path, p)
    with pytest.raises(ContentError, match=r"unit p1 has no concept with id 'nope'"):
        build_practice(study / "x1")


def _build_script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "build_study.py"
    spec = importlib.util.spec_from_file_location("build_study", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_build_script_writes_practice_files_only_for_units_that_have_one(tmp_path):
    study = _make_unit_dir(tmp_path)
    assert _build_script().main([], study_dir=study) == 0
    assert (study / "x1" / "page.html").exists() and (study / "x1" / "brief.md").exists()
    assert (study / "x1" / "practice.html").read_text() == _page()
    assert (study / "x1" / "practice-brief.md").read_text() == _brief()
    assert not (study / "p1" / "practice.html").exists()
    assert not (study / "p1" / "practice-brief.md").exists()
