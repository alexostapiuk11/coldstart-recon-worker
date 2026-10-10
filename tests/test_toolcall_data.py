"""Every file under toolcall/data/ is valid, renders in all eight cells, fits
the provider strict-mode caps, and passes the confidentiality guard.

These run on whatever the suite holds at the time. The suite's size and
coverage are checked separately, by tests/test_toolcall_suite.py, which is
added when authoring is complete (plan 1 Task 19)."""

import json
import re
from pathlib import Path

import pytest

from toolcall import confidentiality
from toolcall.formulation import CELLS, Formulation, render
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

DATA = Path(__file__).resolve().parents[1] / "toolcall" / "data"
LIB = load_library(DATA / "tools")
SCENARIOS = load_scenarios(DATA / "scenarios", LIB)
# Anthropic's strict-mode limits, read 2026-10-08 (amendment §3): the
# exploratory slice must stay within them if it is ever repeated on Claude.
MAX_STRICT_TOOLS, MAX_OPTIONAL = 20, 24


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
    assert len(tools) <= MAX_STRICT_TOOLS and optional <= MAX_OPTIONAL, (len(tools), optional)


@pytest.mark.parametrize("s", SCENARIOS, ids=[s.id for s in SCENARIOS])
def test_the_user_message_names_no_tool(s):
    """The message must not hand the model a tool name; that would test
    reading, not choosing."""
    assert not [t for t in LIB.tools if t in s.user_message]


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
