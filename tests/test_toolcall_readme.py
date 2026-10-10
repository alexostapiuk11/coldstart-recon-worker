"""toolcall/README.md is the adopter's way in, so its examples must load and its
commands must exist. The tests read the README itself; nothing here is a copy."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from toolcall.grader import CATEGORIES
from toolcall.normalize import RULES
from toolcall.prices import PRICES
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
    example = next(b for b in json_blocks if "domain" in b and "expectation" not in b)
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


def test_every_toolcall_path_the_readme_names_exists(text):
    paths = set(re.findall(r"`(toolcall/[\w./-]+)`", text))
    assert {"toolcall/normalize.py", "toolcall/prices.py"} <= paths
    for p in paths:
        assert (ROOT / p).exists(), p


def test_the_category_table_names_the_graders_categories_in_order(text):
    rows = re.findall(r"^\| `([A-Z_]+)` \|", text, re.MULTILINE)
    assert tuple(rows) == CATEGORIES


def test_the_models_named_are_the_scripts_defaults_and_are_priced(text):
    spec = importlib.util.spec_from_file_location("a3_diagnose_readme",
                                                  ROOT / "scripts" / "a3_diagnose.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    named = set(re.findall(r"`((?:gpt|claude)-[\w.-]+)`", text))
    assert named == set(script.DEFAULT_MODEL.values())
    assert named <= set(PRICES)


def test_each_normalizer_rule_is_listed_once(text):
    listed = re.findall(r"^- (R\d+):", text, re.MULTILINE)
    assert listed == [rule_id for rule_id, _ in RULES]
    assert len(listed) == len(RULES)
