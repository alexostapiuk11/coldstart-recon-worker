"""toolcall/README.md is the adopter's way in, so its examples must load and its
commands must exist. The tests read the README itself; nothing here is a copy."""

import json
import re
from pathlib import Path

import pytest

from toolcall.scenarios import scenario_from_dict
from toolcall.tools import load_library, tool_from_dict

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "toolcall" / "README.md"
DATA = ROOT / "toolcall" / "data"


@pytest.fixture(scope="module")
def text() -> str:
    return README.read_text()


@pytest.fixture(scope="module")
def json_blocks(text) -> list:
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)```", text, re.DOTALL)]


def test_every_json_block_parses(json_blocks):
    assert len(json_blocks) >= 2  # the tool-library and the scenario example


def test_the_tool_library_example_loads(json_blocks):
    example = next(b for b in json_blocks if "tools" in b)
    tools = [tool_from_dict(d, example["domain"]) for d in example["tools"]]
    assert tools
    # a faithful subset: each tool is the one in the shipped file, field for field
    shipped = json.loads((DATA / "tools" / f"{example['domain']}.json").read_text())
    by_name = {d["name"]: d for d in shipped["tools"]}
    for d in example["tools"]:
        assert d == by_name[d["name"]]


def test_the_scenario_example_loads_against_the_shipped_library(json_blocks):
    example = next(b for b in json_blocks if "expectation" in b)
    library = load_library(DATA / "tools")
    scenario = scenario_from_dict(example, library, factorial=False)
    assert scenario.acceptable_calls
    shipped = json.loads((DATA / "scenarios" / f"{example['id']}.json").read_text())
    for key, value in example.items():
        assert shipped[key] == value


def test_every_script_path_exists(text):
    paths = set(re.findall(r"scripts/[\w./-]+\.py", text))
    assert "scripts/a3_diagnose.py" in paths
    for p in paths:
        assert (ROOT / p).is_file(), p


def test_every_flag_is_one_the_script_defines(text):
    source = (ROOT / "scripts" / "a3_diagnose.py").read_text()
    defined = set(re.findall(r'add_argument\(\s*"(--[\w-]+)"', source))
    used = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", text))
    assert {"--tools", "--scenarios", "--dry-run", "--store", "--approved-usd"} <= used
    assert used <= defined, sorted(used - defined)
