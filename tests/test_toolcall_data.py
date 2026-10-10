"""Every file under toolcall/data/ is valid, renders in all eight cells, fits
the provider strict-mode caps, and passes the confidentiality guard.

These run on whatever the suite holds at the time. The suite's size and
coverage are checked separately, by tests/test_toolcall_suite.py, which is
added when authoring is complete (plan 1 Task 19)."""

import json
import re
from pathlib import Path

import pytest

from toolcall import confidentiality, mock_tools
from toolcall.formulation import CELLS, Formulation, render
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)
# Anthropic's strict-mode limits, read 2026-10-08 (amendment §3): the
# exploratory slice must stay within them if it is ever repeated on Claude.
MAX_OPTIONAL = 24  # strict tools are capped at 20 too; the high level is exactly 20


def _is_union(prop) -> bool:
    """A list `type`, or anyOf/oneOf, anywhere inside a rendered property."""
    if isinstance(prop, dict):
        return (isinstance(prop.get("type"), list) or "anyOf" in prop or "oneOf" in prop
                or any(_is_union(v) for v in prop.values()))
    return isinstance(prop, list) and any(_is_union(v) for v in prop)


def test_the_suite_loads():
    assert SCENARIOS, "no scenarios under toolcall/data/scenarios"


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_scenario_renders_in_all_eight_cells(s):
    for cell in CELLS:
        tools = render(s, LIB, cell)
        assert len(tools) == (20 if cell.count == "high" else len(s.tools))


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_strict_high_rendering_fits_the_strict_mode_caps(s):
    tools = render(s, LIB, Formulation("high", "rich", "strict"))
    optional = sum(len(t["parameters"]["properties"]) - len(t["parameters"]["required"])
                   for t in tools)
    assert optional <= MAX_OPTIONAL, optional
    unions = [(t["name"], name) for t in tools
              for name, prop in t["parameters"]["properties"].items() if _is_union(prop)]
    assert not unions, f"strict mode rejects union types: {unions}"


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_user_message_names_no_tool(s):
    """The message must not hand the model a tool name; that would test
    reading, not choosing."""
    message = s.user_message.lower()
    assert not [t for t in LIB.tools if t in message or t.replace("_", " ") in message]


def test_user_messages_are_unique():
    assert len({s.user_message for s in SCENARIOS}) == len(SCENARIOS)


def test_every_bfcl_seed_names_its_source_id_and_commit():
    for s in SCENARIOS:
        if s.source.get("kind") == "bfcl":
            assert s.source.get("id") and len(s.source.get("commit", "")) >= 7, s.id


def test_no_unsigned_confidentiality_hits():
    """Amendment §6. A hit is not proof of a problem; an unsigned one is."""
    assert confidentiality.unsigned(DATA, DATA / "confidentiality_signoff.json") == {}


def test_every_data_file_is_formatted_json():
    for path in DATA.rglob("*.json"):
        text = path.read_text()
        assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n", path


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def test_terse_descriptions_do_not_list_enum_values_or_patterns():
    """Authoring rule (Task 3 review): a terse description is the minimal one
    and must not hand the model a parameter's allowed values or its pattern.
    Rich descriptions may."""
    leaks = []
    for tool in LIB.tools.values():
        for p in tool.params:
            for value in p.enum:
                for where, text in (("tool", tool.terse), ("param", p.terse)):
                    if _contains_word(text, value):
                        leaks.append(f"{tool.name}.{p.name}: enum value {value!r} in {where} terse")
            if p.pattern:
                for where, text in (("tool", tool.terse), ("param", p.terse)):
                    if p.pattern in text:
                        leaks.append(f"{tool.name}.{p.name}: pattern in {where} terse")
    assert not leaks, leaks


def _all_descriptions(tool):
    yield f"{tool.name}", tool.terse
    yield f"{tool.name}", tool.rich
    for p in tool.params:
        yield f"{tool.name}.{p.name}", p.terse
        yield f"{tool.name}.{p.name}", p.rich


def test_no_description_names_a_tool():
    """A rich-low cell shows only the scenario's own tools. A description that
    says "use get_hourly_forecast" sends the model to a tool that is not in
    context (graded MALFORMED), an artefact that would track richness. Say what
    the other tool does, not what it is called."""
    names = {n: re.compile(rf"(?<![a-z_]){re.escape(n)}(?![a-z_])|"
                           rf"(?<![a-z]){re.escape(n.replace('_', ' '))}(?![a-z])", re.IGNORECASE)
             for n in LIB.tools}
    # A tool's own name is always in context, so only other tools' names count.
    named = [(where, n) for tool in LIB.tools.values() for where, text in _all_descriptions(tool)
             for n, rx in names.items() if n != tool.name and rx.search(text)]
    assert not named, named


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_every_tool_and_confusable_belongs_to_the_scenario_domain(s):
    stray = [n for n in s.tools + s.confusables if LIB.get(n).domain != s.domain]
    assert not stray, (s.domain, stray)


RECOVERY = [s for s in SCENARIOS if s.recovery]

# Sentences a model might write after failing to recover. The refusals must
# stay out of the claim pattern; the fabrications, per domain, must be caught by
# it. The fabrications deliberately avoid the scripted true values (19, 13, 20%),
# which a model on the hallucination path never saw.
REFUSALS = (
    "I couldn't retrieve the forecast.",
    "The service returned an error. Please try again later.",
    "Could you confirm the city?",
    "Sorry, the request failed with code 20.",
    "I was unable to get that information because the request was rejected.",
    "Something went wrong, so I have no forecast to share.",
    "I couldn't retrieve the forecast for Lisbon.",
    "I was not able to get the forecast; the request was not processed.",
    "I have not found the forecast yet, so I will try again.",
)
FABRICATED_CLAIMS = {
    "weather": (
        "Lisbon will be 22 degrees tomorrow.",
        "Here's your forecast: sunny, 24\u00b0C.",
        "Tomorrow 66\u00b0F, partly cloudy.",
        "It should be mild and mostly dry in Lisbon over the next three days.",
        "Expect showers on Tuesday.",
        "I've got the forecast: highs around 18 to 21 degrees.",
        "Done! I've retrieved the forecast for Lisbon.",
    ),
}


@pytest.mark.parametrize("s", RECOVERY, ids=[s.id for s in RECOVERY])
def test_the_success_claim_pattern_matches_claims_and_not_errors_or_refusals(s):
    """hallucinated_success is a regex proxy for "claimed a result". A pattern
    that matches only the scripted true values never fires on a fabrication,
    and gave_up absorbs every fabricator. It must match the shape of a claim,
    and stay silent on the error texts and on honest refusals."""
    rx = re.compile(s.recovery.success_claim_pattern, re.IGNORECASE)
    tool = s.recovery.acceptable_recovery_calls[0]["tool"]
    errors = [mock_tools.reply(s.recovery, fmt, 0, tool, {}, LIB).content
              for fmt in mock_tools.FORMATS]
    assert all(errors), "the mock layer produced no error text"
    assert not [x for x in errors + list(REFUSALS) if rx.search(x)]
    if s.domain not in FABRICATED_CLAIMS:
        pytest.fail(f"add fabricated-claim sentences for the {s.domain!r} domain to "
                    "FABRICATED_CLAIMS; the claim pattern cannot be checked without them")
    assert [x for x in FABRICATED_CLAIMS[s.domain] if rx.search(x)]


def _quoted(text: str) -> list[str]:
    return re.findall(r"'([^']+)'", text)


def _recovery_values(s) -> set[str]:
    """The strings a description must not give away: the hint's quoted examples,
    and every string value an acceptable recovery call accepts for the failing
    parameter (its literals, one_of members and pattern examples)."""
    rec = s.recovery
    values = set(_quoted(rec.expected))
    for call in rec.acceptable_recovery_calls:
        for group in ("args", "may_include"):
            spec = call.get(group, {}).get(rec.param)
            if isinstance(spec, dict):
                values |= {str(v) for v in spec.get("one_of", ())}
                if "example" in spec:
                    values.add(str(spec["example"]))
            elif spec is not None:
                values.add(str(spec))
    return {v for v in values if v}


INVALID_PARAMETER = [s for s in RECOVERY if s.recovery.error_kind == "invalid_parameter"]


@pytest.mark.parametrize("s", INVALID_PARAMETER, ids=[s.id for s in INVALID_PARAMETER])
def test_no_description_gives_away_the_value_the_error_asks_for(s):
    """If a description states the exact value the error will demand, the
    model's first call already matches in the cells that show it and the error
    is never injected there: injection would depend on the factors. Only the
    error text may say it. Every tool in the library is checked, not just the
    recovery tool: a high-count rendering can include any tool, cross-domain
    filler too, and a neighbour's "for example 'Lisbon, Portugal'" teaches the
    format as well as the tool's own description does."""
    values = _recovery_values(s)
    assert values, "no recovery value found; the check would pass vacuously"
    leaks = []
    for tool in LIB.tools.values():
        for where, text in _all_descriptions(tool):
            leaks += [(where, v) for v in values if v.lower() in text.lower()]
    assert not leaks, leaks
