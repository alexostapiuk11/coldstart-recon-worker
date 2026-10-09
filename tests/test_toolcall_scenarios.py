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


def _call(**args_and_more):
    return {"tool": "search_flights", **args_and_more}


def _flight_with_call(call):
    return _with(expectation={"acceptable_calls": [call]})


JFK_SFO = {"origin": "JFK", "destination": "SFO", "date": "2026-11-03"}


@pytest.mark.parametrize("call, match", [
    (_call(args={**JFK_SFO, "cabin": "first"}), "breaks the canonical schema"),
    (_call(args={**JFK_SFO, "cabin": {"one_of": ["economy", "first"]}}),
     "breaks the canonical schema"),
    (_call(args={**JFK_SFO, "origin": "jfk"}), "breaks the canonical schema"),
    (_call(args={**JFK_SFO, "origin": {"pattern": "j.k", "example": "jfk"}}),
     "breaks the canonical schema"),
    (_call(args={**JFK_SFO, "origin": {"one_of": []}}), "non-empty list"),
    (_call(args={**JFK_SFO, "origin": {"one_of": "JFK"}}), "non-empty list"),
    (_call(args=JFK_SFO, may_include={"origin": "JFK"}), "both args and may_include"),
    (_call(args={**JFK_SFO, "origin": {"pattern": "(", "example": "JFK"}}), "is invalid"),
])
def test_acceptable_values_must_satisfy_the_canonical_schema_and_be_well_specified(call, match):
    with pytest.raises(ValueError, match=match):
        scenario_from_dict(_flight_with_call(call), library())


def test_duplicate_names_in_tools_or_confusables_are_refused():
    with pytest.raises(ValueError, match="duplicate names in tools"):
        scenario_from_dict(_with(tools=["search_flights", "search_flights"]), library())
    with pytest.raises(ValueError, match="duplicate names in confusables"):
        scenario_from_dict(_with(confusables=["flight_status", "flight_status", "flight_prices",
                                              "search_trains"]), library())


def _recovery_with(**changes):
    d = copy.deepcopy(RECOVERY)
    d["recovery"].update(changes)
    return d


@pytest.mark.parametrize("changes, match", [
    ({"success_claim_pattern": "("}, "does not compile"),
    ({"success_result": "ok"}, "success_result must be an object"),
    ({"contradicting_result": "no"}, "contradicting_result must be an object"),
    ({"param": "seat"}, "not a parameter"),
    ({"acceptable_recovery_calls": [{
        "tool": "flight_status", "args": {"flight_number": "UA1"}}]}, "not in the low set"),
    ({"acceptable_recovery_calls": [{
        "tool": "search_flights",
        "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"}}]},
     "could never occur"),
])
def test_invalid_recovery_blocks_are_refused(changes, match):
    with pytest.raises(ValueError, match=match):
        scenario_from_dict(_recovery_with(**changes), library())


def test_a_recovery_call_that_the_first_call_already_satisfies_is_refused_via_one_of():
    d = _recovery_with(acceptable_recovery_calls=[{
        "tool": "search_flights",
        "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01",
                 "passengers": {"one_of": [1, 2]}}}])
    d["expectation"]["acceptable_calls"][0]["args"]["passengers"] = {"one_of": [1, 2]}
    del d["expectation"]["acceptable_calls"][0]["may_include"]["passengers"]
    with pytest.raises(ValueError, match="could never occur"):
        scenario_from_dict(d, library())


def test_a_contradicting_result_recovery_may_share_the_first_call():
    d = _recovery_with(
        error_kind="contradicting_result",
        contradicting_result={"offers": []},
        acceptable_recovery_calls=[{
            "tool": "search_flights",
            "args": {"origin": "BOS", "destination": "ORD", "date": "2026-12-01"}}],
    )
    assert scenario_from_dict(d, library()).recovery.error_kind == "contradicting_result"
