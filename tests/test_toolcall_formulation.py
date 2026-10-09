"""One scenario, eight renderings, and only the manipulated part differs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.a3_examples import library, scenario, scenarios
from toolcall.formulation import (
    BASELINE,
    CELLS,
    HIGH_COUNT,
    Formulation,
    parse_cell,
    render,
    tool_names,
)
from toolcall.tools import Library


def test_eight_cells_with_unique_names_and_a_baseline_among_them():
    assert len({c.name for c in CELLS}) == 8
    assert BASELINE in CELLS
    assert parse_cell("high-rich-strict") == Formulation("high", "rich", "strict")


def test_low_count_is_the_low_set_and_high_count_is_twenty():
    s, lib = scenario(), library()
    assert sorted(tool_names(s, lib, "low")) == sorted(s.tools)
    high = tool_names(s, lib, "high")
    assert len(high) == HIGH_COUNT == len(set(high))
    assert set(s.tools) | set(s.confusables) <= set(high)


def test_tool_order_depends_on_scenario_and_count_only():
    s, lib = scenario(), library()
    orders = {tuple(t["name"] for t in render(s, lib, c)) for c in CELLS if c.count == "high"}
    assert len(orders) == 1


def test_richness_changes_only_descriptions():
    s, lib = scenario(), library()
    terse = render(s, lib, Formulation("high", "terse", "strict"))
    rich = render(s, lib, Formulation("high", "rich", "strict"))

    def strip(tools):
        out = json.loads(json.dumps(tools))
        for t in out:
            t.pop("description")
            for p in t["parameters"]["properties"].values():
                p.pop("description")
        return out

    assert strip(terse) == strip(rich)
    assert terse != rich


def test_strictness_changes_only_schema_keywords():
    s, lib = scenario(), library()
    loose = {t["name"]: t for t in render(s, lib, Formulation("low", "rich", "loose"))}
    strict = {t["name"]: t for t in render(s, lib, Formulation("low", "rich", "strict"))}
    f_loose, f_strict = loose["search_flights"], strict["search_flights"]
    assert f_loose["description"] == f_strict["description"]
    assert f_strict["parameters"]["required"] == ["origin", "destination", "date"]
    assert f_loose["parameters"]["required"] == ["origin"]
    assert f_strict["parameters"]["additionalProperties"] is False
    assert "additionalProperties" not in f_loose["parameters"]
    assert f_strict["parameters"]["properties"]["cabin"]["enum"]
    assert "enum" not in f_loose["parameters"]["properties"]["cabin"]
    assert "pattern" not in f_loose["parameters"]["properties"]["origin"]


@pytest.mark.parametrize("bad", ["mid-terse-loose", "low-terse", "low-short-loose"])
def test_unknown_cells_are_refused(bad):
    with pytest.raises(ValueError):
        parse_cell(bad)


REPO = Path(__file__).resolve().parent.parent
RICHNESS = ("terse", "rich")
STRICTNESS = ("loose", "strict")


def _strip_descriptions(tools):
    out = json.loads(json.dumps(tools))
    for t in out:
        t.pop("description")
        for p in t["parameters"]["properties"].values():
            p.pop("description")
    return out


def _loosen(rendered, lib):
    """The strict rendering with only the strictness keywords taken away."""
    out = json.loads(json.dumps(rendered))
    for t in out:
        schema = t["parameters"]
        schema.pop("additionalProperties", None)
        primary = lib.get(t["name"]).primary_param
        schema["required"] = [primary.name] if primary else []
        for p in schema["properties"].values():
            p.pop("enum", None)
            p.pop("pattern", None)
    return out


@pytest.mark.parametrize("s", scenarios(), ids=lambda s: s.id)
@pytest.mark.parametrize("count", ["low", "high"])
def test_only_the_manipulated_factor_differs(s, count):
    lib = library()
    renders = {
        (r, st): render(s, lib, Formulation(count, r, st))
        for r in RICHNESS
        for st in STRICTNESS
    }
    # (i) the same tools in the same order in all four cells of this count level
    names = tool_names(s, lib, count)
    for tools in renders.values():
        assert [t["name"] for t in tools] == names
    # (ii) strictness is only schema keywords
    for r in RICHNESS:
        assert _loosen(renders[(r, "strict")], lib) == renders[(r, "loose")]
    # (iii) richness is only descriptions
    for st in STRICTNESS:
        terse = _strip_descriptions(renders[("terse", st)])
        rich = _strip_descriptions(renders[("rich", st)])
        assert terse == rich


def test_a_library_too_small_for_twenty_is_refused_naming_the_scenario():
    s, lib = scenario(), library()
    wanted = set(s.tools) | set(s.confusables)
    small = Library({n: t for n, t in lib.tools.items() if n in wanted})
    assert len(small.tools) < HIGH_COUNT
    with pytest.raises(ValueError, match=s.id):
        tool_names(s, small, "high")
    assert sorted(tool_names(s, small, "low")) == sorted(s.tools)


def test_filler_already_in_the_scenarios_tools_is_not_repeated():
    s, lib = scenario(), library()
    same_domain = {t.name for t in lib.domain(s.domain)}
    assert set(s.tools) <= same_domain  # the dedupe path is exercised
    high = tool_names(s, lib, "high")
    assert len(high) == len(set(high)) == HIGH_COUNT
    for name in set(s.tools) | set(s.confusables):
        assert high.count(name) == 1


def test_filler_is_seeded_per_scenario_and_stable_across_processes():
    s, lib = scenario(), library()
    in_process = tool_names(s, lib, "high")
    assert tool_names(s, lib, "high") == in_process
    code = (
        "import json; from tests.a3_examples import library, scenario; "
        "from toolcall.formulation import tool_names; "
        "print(json.dumps(tool_names(scenario(), library(), 'high')))"
    )
    outputs = []
    for seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO)}
        done = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO, env=env, capture_output=True, text=True, check=True,
        )
        outputs.append(json.loads(done.stdout))
    assert outputs[0] == outputs[1] == in_process
