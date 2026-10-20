"""Validation of a unit's practice.json, the second page of a study unit.

The study page (page.html) is the 45-minute read; the practice page holds what is done
rather than read: drills, an estimation, a design scenario, a lab, a calculator, recall
cards and a review schedule. It builds from docs/learning/study/<unit>/practice.json and the
unit's own content.json, which supplies the unit's title, its concept ids (for the "if you
missed it, review ..." links), its prereqs and links (for [text](unit:concept) links) and its
sources (practice numbers trace to them, see study.trace).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable

from study.calc import FUNCTIONS, CalcError, evaluate, fmt_number, names, parse
from study.schema import (
    ContentError,
    _cross_page,
    _finite,
    _get,
    _label,
    _opt_str,
)

MIN_MINUTES, MAX_MINUTES = 20, 40
OBJECTIVES = (3, 6)
MAX_OBJECTIVE = 140
PREREQ_CHECKS = 3
MAX_Q = 300
MAX_PREREQ_A = 400
DRILLS = (8, 12)
MAX_DRILL_A = 600
MAX_RED_FLAG = 300
ESTIMATIONS = (1, 2)
MAX_EST_TITLE = 80
MAX_PROBLEM = 500
EST_STEPS = (2, 8)
MAX_STEP = 300
MAX_ANSWER = 300
MAX_SCENARIO_PROMPT = 600
OUTLINE = (3, 8)
PITFALLS = (2, 6)
MAX_POINT = 300
LAB_COSTS = ("none", "local", "gpu", "paid")
LAB_SETUP, LAB_STEPS, LAB_METRICS = (1, 8), (2, 12), (1, 6)
MAX_LAB_LINE = 300
MAX_METRIC = 200
MAX_LAB_EXPECTED = 500
MAX_LAB_NOTE = 300
CARDS = (1, 25)
MAX_TAG = 30
MAX_FRONT = 200
MAX_BACK = 400
SCHEDULE = (3, 5)
MAX_WHEN = 40
MAX_TEST = 200
MAX_CALC_TITLE = 70
MAX_CALC_NOTE = 300
CALC_INPUTS, CALC_OUTPUTS = (1, 6), (1, 6)
MAX_CALC_LABEL = 40
MAX_CALC_UNIT = 12
MAX_ASSUMED_VALUE = 40
MAX_ASSUMED_WHY = 200
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

FIELDS = ("unit", "title", "minutes", "objectives", "prereq_check", "drills", "estimation",
          "scenario", "lab", "cards", "schedule", "calculator", "assumed_numbers",
          "derived_numbers")
REQUIRED = ("unit", "title", "minutes", "objectives", "prereq_check", "drills", "estimation",
            "scenario", "lab", "cards", "schedule")

LoadUnit = Callable[[str], "dict | None"]


def num_str(v: float) -> str:
    """A number as the shortest text that reads back as the same value: 250.0 -> '250'."""
    v = float(v)
    return str(int(v)) if v == int(v) and abs(v) < 1e15 else repr(v)


def _text(d, key, where, limit):
    """A required string: not blank, at most `limit` characters."""
    v = _get(d, key, str, where)
    if not v.strip():
        raise ContentError(f"{where}.{key} is empty")
    if len(v) > limit:
        raise ContentError(f"{where}.{key} longer than {limit} characters")
    return v


def _count(items, where, lo, hi):
    if len(items) < lo or len(items) > hi:
        bound = f"exactly {lo}" if lo == hi else f"{lo} to {hi}"
        raise ContentError(f"{where}: needs {bound} items, has {len(items)}")


def _objects(d, key, where, bounds):
    """d[key], a list of objects with a number of items within `bounds`."""
    items = _get(d, key, list, where)
    _count(items, f"{where}.{key}", *bounds)
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ContentError(f"{where}.{key}[{i}]: expected dict")
    return items


def _strings(d, key, where, bounds, limit):
    """d[key], a list of non-blank strings within `bounds` items, each <= `limit`."""
    items = _get(d, key, list, where)
    _count(items, f"{where}.{key}", *bounds)
    for i, s in enumerate(items):
        w = f"{where}.{key}[{i}]"
        if not isinstance(s, str):
            raise ContentError(f"{w}: expected str")
        if not s.strip():
            raise ContentError(f"{w} is empty")
        if len(s) > limit:
            raise ContentError(f"{w} longer than {limit} characters")
    return items


def concept_ids(unit: dict) -> list[str]:
    return [t["id"] for t in unit.get("concepts", []) if isinstance(t, dict) and "id" in t]


def split_review(review: str, unit_id: str) -> tuple[str, str]:
    """(unit id, concept id) of a `review` value: 'arms' is this unit's, 'p1:units' is p1's."""
    if ":" in review:
        other, _, cid = review.partition(":")
        return other, cid
    return unit_id, review


def _review(review, w, unit, load_unit):
    if not review.strip():
        raise ContentError(f"{w}.review is empty")
    if review.count(":") > 1 or review.startswith(":") or review.endswith(":"):
        raise ContentError(f"{w}.review '{review}' must be a concept id or "
                           "'<unit>:<concept id>'")
    other, cid = split_review(review, unit["id"])
    if other == unit["id"]:
        ids = concept_ids(unit)
        if cid not in ids:
            have = f"use one of: {', '.join(ids)}" if ids else "the unit has no concept ids"
            raise ContentError(f"{w}.review '{review}' is not a concept id of {unit['id']}; "
                               f"{have}")
        return
    if load_unit is None:
        return
    target = load_unit(other)
    if target is None:
        raise ContentError(f"{w}.review '{review}': no unit '{other}'")
    if cid not in concept_ids(target):
        raise ContentError(f"{w}.review '{review}': unit {other} has no concept with id "
                           f"'{cid}'")


def review_target(review: str, unit: dict, load_unit: LoadUnit | None) -> tuple[str, str, str]:
    """(unit id, concept term, relative href) for a `review` value. The href points at the
    concept's card on the unit's page; it works when the files sit side by side (local
    viewing) and is the only link a published practice page cannot follow."""
    other, cid = split_review(review, unit["id"])
    owner = unit if other == unit["id"] else (load_unit(other) if load_unit else None)
    term = next((t["term"] for t in (owner or {}).get("concepts", []) if t.get("id") == cid),
                cid)
    href = f"page.html#c-{cid}" if other == unit["id"] else f"../{other}/page.html#c-{cid}"
    return other, term, href


def link_context(p: dict, unit: dict) -> dict:
    """The practice content as a unit-shaped dict for the link checks and resolve_links: the
    unit's id, `links` and `prereqs` (so [text](unit:concept) means what it does there)."""
    ctx = {**p, "id": unit["id"]}
    for key in ("links", "prereqs"):
        if unit.get(key):
            ctx[key] = unit[key]
    return ctx


def _calc_input(it, w):
    if not _get(it, "id", str, w).strip():
        raise ContentError(f"{w}.id is empty")
    if not IDENT.fullmatch(it["id"]):
        raise ContentError(f"{w}.id '{it['id']}' is not an identifier (letters, digits and "
                           "underscores, not starting with a digit)")
    if it["id"] in FUNCTIONS:
        raise ContentError(f"{w}.id '{it['id']}' is a function name")
    _text(it, "label", w, MAX_CALC_LABEL)
    _opt_str(it, "unit", w, MAX_CALC_UNIT)
    lo, hi = _finite(it, "min", w), _finite(it, "max", w)
    value, step = _finite(it, "value", w), _finite(it, "step", w)
    if not lo < hi:
        raise ContentError(f"{w}: needs min < max, got {num_str(lo)} and {num_str(hi)}")
    if not lo <= value <= hi:
        raise ContentError(f"{w}.value {num_str(value)} is outside min {num_str(lo)} and max "
                           f"{num_str(hi)}")
    if step <= 0:
        raise ContentError(f"{w}.step must be above zero")


def _calc_env(inputs, pick) -> dict[str, float]:
    return {it["id"]: float(pick(it)) for it in inputs}


def _calc_output(o, w, inputs):
    _text(o, "label", w, MAX_CALC_LABEL)
    _opt_str(o, "unit", w, MAX_CALC_UNIT)
    if not 0 <= _get(o, "digits", int, w) <= 4:
        raise ContentError(f"{w}.digits must be 0 to 4")
    try:
        tree = parse(_get(o, "expr", str, w))
    except CalcError as e:
        raise ContentError(f"{w}.expr: {e}") from None
    ids = [it["id"] for it in inputs]
    for name in sorted(names(tree)):
        if name not in ids:
            raise ContentError(f"{w}.expr reads '{name}', which is not an input id; the "
                               f"inputs are {', '.join(ids)}")
    try:
        evaluate(tree, _calc_env(inputs, lambda it: it["value"]))
    except CalcError as e:
        raise ContentError(f"{w}.expr fails at the default inputs: {e}") from None
    for combo in itertools.product(*[(it["min"], it["max"]) for it in inputs]):
        env = {it["id"]: float(v) for it, v in zip(inputs, combo)}
        try:
            evaluate(tree, env)
        except CalcError as e:
            at = ", ".join(f"{k}={num_str(v)}" for k, v in env.items())
            raise ContentError(f"{w}.expr fails when {at}: {e}") from None
    return tree


def _calculator(calc, w):
    _text(calc, "title", w, MAX_CALC_TITLE)
    if "note" in calc:
        _text(calc, "note", w, MAX_CALC_NOTE)
    inputs = _objects(calc, "inputs", w, CALC_INPUTS)
    seen = []
    for i, it in enumerate(inputs):
        wi = f"{w}.inputs[{i}]"
        _calc_input(it, wi)
        if it["id"] in seen:
            raise ContentError(f"{wi}: duplicate id '{it['id']}'")
        seen.append(it["id"])
    read = set()
    for i, o in enumerate(_objects(calc, "outputs", w, CALC_OUTPUTS)):
        read |= names(_calc_output(o, f"{w}.outputs[{i}]", inputs))
    for i, it in enumerate(inputs):
        if it["id"] not in read:
            raise ContentError(f"{w}.inputs[{i}] '{it['id']}' is read by no output")


def calculator_defaults(calc: dict) -> list[tuple[str, str, str]]:
    """[(output label, its value at the default inputs, formatted, unit)]."""
    env = _calc_env(calc["inputs"], lambda it: it["value"])
    return [(o["label"], fmt_number(evaluate(parse(o["expr"]), env), o["digits"]),
             o.get("unit", "")) for o in calc["outputs"]]


def validate_practice(p: dict, unit: dict, folder: str,
                      load_unit: LoadUnit | None = None) -> None:
    """Raise ContentError, naming the field, if practice.json (`p`) cannot be rendered.

    `unit` is the unit's content.json (already valid), `folder` the unit's folder name and
    `load_unit(id)` returns another unit's content (or None) so a `review` of 'p1:<concept>'
    can be checked; without it other units' concepts are not checked.
    """
    where = f"{unit['id']}.practice"
    if not isinstance(p, dict):
        raise ContentError(f"{where}: expected dict")
    for banned in ("sources", "links"):
        if banned in p:
            raise ContentError(f"{where}.{banned}: not allowed; numbers trace to the unit's "
                               "own sources and links come from the unit")
    for key in p:
        if key not in FIELDS:
            raise ContentError(f"{where}: unknown field '{key}'; the fields are "
                               f"{', '.join(FIELDS)}")
    for key in REQUIRED:
        if key not in p:
            raise ContentError(f"{where}: missing '{key}'")
    if _get(p, "unit", str, where) != folder:
        raise ContentError(f"{where}.unit '{p['unit']}' must equal the folder name '{folder}'")
    _text(p, "title", where, 70)
    if not MIN_MINUTES <= _get(p, "minutes", int, where) <= MAX_MINUTES:
        raise ContentError(f"{where}.minutes must be {MIN_MINUTES} to {MAX_MINUTES}")
    _strings(p, "objectives", where, OBJECTIVES, MAX_OBJECTIVE)

    for i, it in enumerate(_objects(p, "prereq_check", where, (PREREQ_CHECKS, PREREQ_CHECKS))):
        w = f"{where}.prereq_check[{i}]"
        _text(it, "q", w, MAX_Q)
        _text(it, "a", w, MAX_PREREQ_A)
        _review(_get(it, "review", str, w), w, unit, load_unit)
    for i, it in enumerate(_objects(p, "drills", where, DRILLS)):
        w = f"{where}.drills[{i}]"
        _text(it, "q", w, MAX_Q)
        _text(it, "a", w, MAX_DRILL_A)
        _text(it, "red_flag", w, MAX_RED_FLAG)
    for i, it in enumerate(_objects(p, "estimation", where, ESTIMATIONS)):
        w = f"{where}.estimation[{i}]"
        _text(it, "title", w, MAX_EST_TITLE)
        _text(it, "problem", w, MAX_PROBLEM)
        _strings(it, "steps", w, EST_STEPS, MAX_STEP)
        _text(it, "answer", w, MAX_ANSWER)

    sc = _get(p, "scenario", dict, where)
    w = f"{where}.scenario"
    _text(sc, "prompt", w, MAX_SCENARIO_PROMPT)
    _strings(sc, "outline", w, OUTLINE, MAX_POINT)
    _strings(sc, "pitfalls", w, PITFALLS, MAX_POINT)

    lab = _get(p, "lab", dict, where)
    w = f"{where}.lab"
    _text(lab, "goal", w, MAX_LAB_LINE)
    _strings(lab, "setup", w, LAB_SETUP, MAX_LAB_LINE)
    _strings(lab, "steps", w, LAB_STEPS, MAX_LAB_LINE)
    _strings(lab, "metrics", w, LAB_METRICS, MAX_METRIC)
    _text(lab, "expected", w, MAX_LAB_EXPECTED)
    _text(lab, "demonstrates", w, MAX_LAB_LINE)
    if _get(lab, "cost", str, w) not in LAB_COSTS:
        raise ContentError(f"{w}.cost '{lab['cost']}' not in {LAB_COSTS}")
    if "note" in lab:
        _text(lab, "note", w, MAX_LAB_NOTE)

    for i, it in enumerate(_objects(p, "cards", where, CARDS)):
        w = f"{where}.cards[{i}]"
        _text(it, "tag", w, MAX_TAG)
        _text(it, "front", w, MAX_FRONT)
        _text(it, "back", w, MAX_BACK)
        if "draw" in it:
            _get(it, "draw", bool, w)
    for i, it in enumerate(_objects(p, "schedule", where, SCHEDULE)):
        w = f"{where}.schedule[{i}]"
        _text(it, "when", w, MAX_WHEN)
        _text(it, "test", w, MAX_TEST)

    if "calculator" in p:
        _calculator(_get(p, "calculator", dict, where), f"{where}.calculator")
    if "assumed_numbers" in p:
        for i, it in enumerate(_get(p, "assumed_numbers", list, where)):
            w = f"{where}.assumed_numbers[{i}]"
            _text(it, "value", w, MAX_ASSUMED_VALUE)
            _text(it, "why", w, MAX_ASSUMED_WHY)
    if "derived_numbers" in p:
        for i, it in enumerate(_get(p, "derived_numbers", list, where)):
            _label(it, "value", f"{where}.derived_numbers[{i}]")
            _label(it, "how", f"{where}.derived_numbers[{i}]")

    _cross_page(link_context(p, unit), where)
