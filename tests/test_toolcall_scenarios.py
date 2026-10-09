import copy

import pytest

from tests.a3_examples import FLIGHT, RECOVERY, SMALLTALK, library, write_suite
from toolcall.scenarios import load_scenarios, scenario_from_dict


def _with(**changes):
    d = copy.deepcopy(FLIGHT)
    d.update(changes)
    return d


def test_the_three_examples_load():
    lib = library()
    for d in (FLIGHT, SMALLTALK, RECOVERY):
        s = scenario_from_dict(d, lib)
        assert s.id == d["id"]
    assert scenario_from_dict(RECOVERY, lib).recovery.error_kind == "invalid_parameter"


@pytest.mark.parametrize("changes, match", [
    ({"tools": ["search_flights"]}, "2-4"),
    ({"confusables": ["flight_status"]}, "4-6"),
    ({"confusables": ["search_flights", "flight_status", "flight_prices", "search_trains"]},
     "both in the low set"),
    ({"target_failure_mode": "CORRECT"}, "target_failure_mode"),
    ({"expectation": {}}, "exactly one"),
    ({"draft": True}, "draft"),
    ({"tools": ["search_flights", "no_such_tool"]}, "no tool named"),
])
def test_invalid_scenarios_are_refused(changes, match):
    with pytest.raises((ValueError, KeyError), match=match):
        scenario_from_dict(_with(**changes), library())


def test_an_acceptable_call_must_itself_be_well_formed():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "search_flights", "args": {"origin": "JFK", "destination": "SFO",
                                            "date": "2026-11-03", "passengers": "two"}}]})
    with pytest.raises(ValueError, match="canonical type"):
        scenario_from_dict(bad, library())


@pytest.mark.parametrize("spec, match", [
    ({"pattern": "jfk"}, "exactly an `example`"),
    ({"pattern": "jfk", "example": "LGA"}, "fails its pattern"),
    ({"any": ["JFK"]}, "unknown value specification"),
])
def test_value_specifications_are_checked_at_load(spec, match):
    bad = _with(expectation={"acceptable_calls": [{"tool": "search_flights", "args": {
        "origin": spec, "destination": "SFO", "date": "2026-11-03"}}]})
    with pytest.raises(ValueError, match=match):
        scenario_from_dict(bad, library())


def test_an_acceptable_call_must_give_every_required_argument():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "search_flights", "args": {"origin": "JFK"}}]})
    with pytest.raises(ValueError, match="omits required"):
        scenario_from_dict(bad, library())


def test_an_acceptable_call_must_use_the_low_set():
    bad = _with(expectation={"acceptable_calls": [
        {"tool": "flight_status", "args": {"flight_number": "UA1"}}]})
    with pytest.raises(ValueError, match="not in the low set"):
        scenario_from_dict(bad, library())


def test_a_no_call_scenario_targets_spurious():
    bad = copy.deepcopy(SMALLTALK)
    bad["target_failure_mode"] = "MISSING"
    with pytest.raises(ValueError, match="SPURIOUS"):
        scenario_from_dict(bad, library())


def test_bring_your_own_mode_relaxes_only_the_factorial_counts():
    d = _with(tools=["search_flights"], confusables=[])
    s = scenario_from_dict(d, library(), factorial=False)
    assert s.tools == ("search_flights",)


def test_load_scenarios_requires_the_id_to_match_the_file_name(tmp_path):
    tools_dir, sc_dir = write_suite(tmp_path)
    from toolcall.tools import load_library

    lib = load_library(tools_dir)
    assert len(load_scenarios(sc_dir, lib)) == 3
    (sc_dir / "renamed.json").write_text((sc_dir / f"{FLIGHT['id']}.json").read_text())
    with pytest.raises(ValueError, match="must equal the file name"):
        load_scenarios(sc_dir, lib)
