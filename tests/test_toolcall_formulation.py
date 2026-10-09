"""One scenario, eight renderings, and only the manipulated part differs."""

import json

import pytest

from tests.a3_examples import library, scenario
from toolcall.formulation import (
    BASELINE,
    CELLS,
    HIGH_COUNT,
    Formulation,
    parse_cell,
    render,
    tool_names,
)


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
