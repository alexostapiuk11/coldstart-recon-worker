"""The numbers block, the bring-your-own-tools path, the confidentiality scan
and the BFCL import. All offline."""

import functools
import json
import tempfile
from pathlib import Path

import pytest

from harness.store import JsonlStore
from tests.a3_examples import (
    FLIGHT,
    MISC,
    TRAVEL,
    example_prereg,
    library,
    scenarios,
    synthetic_suite,
    write_suite,
)
from toolcall import bfcl, campaign, confidentiality
from toolcall.analysis import analyse
from toolcall.diagnose import diagnose, report
from toolcall.formulation import CELLS
from toolcall.numbers import END, START, block_in, numbers_block, pct, pp, replace_block
from toolcall.providers import ModelSettings, ScriptedClient
from toolcall.records import CallRecord
from toolcall.scenarios import scenario_from_dict
from toolcall.stub import StubModel
from toolcall.tools import tool_from_dict


def test_formatting():
    assert pct(0.1234) == "12.3%" and pp(-0.145) == "-14.5 pp" and pp(0.005) == "+0.5 pp"


def test_the_block_is_replaced_between_its_markers_only():
    post = f"intro\n{START}\nold\n{END}\noutro"
    new = replace_block(post, f"{START}\nnew\n{END}")
    assert new == f"intro\n{START}\nnew\n{END}\noutro"
    with pytest.raises(ValueError, match="no a3-numbers block"):
        block_in("no markers")


def test_the_numbers_block_renders_from_a_stub_analysis():
    a = json.loads(json.dumps(_stub_analysis()))
    block = numbers_block(a)
    assert block.startswith(START) and block.endswith(END)
    assert "H1, richness × count interaction" in block and "95% interval" in block


@functools.cache
def _stub_analysis():
    lib, scs = library(), scenarios(synthetic_suite(24, 2))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=5, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=100)
    store = JsonlStore(Path(tempfile.mkdtemp()) / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, 5, 1),
                         ScriptedClient(prereg.primary, StubModel(lib, scs, seed=1)),
                         scs, lib, store, phase="campaign")
    return analyse(store.read_all(), [], scs, prereg)


def test_bring_your_own_tools_runs_the_baseline_only_and_reports_a_taxonomy(tmp_path):
    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    lib = load_library(tools_dir)
    scs = load_scenarios(sc_dir, lib, factorial=False)
    client = ScriptedClient(example_prereg().primary, StubModel(lib, scs, seed=0))
    summary = diagnose(client, tools_dir, sc_dir, tmp_path / "d.jsonl", reps=5)
    assert summary["graded"] == 15
    assert sum(r["calls"] for r in summary["categories"]) == 15
    assert all(len(b["tools"]) <= 4 for b in client.sent)
    assert "| WRONG_TOOL |" in report(summary)


def _sign(signoff, root, name, *, date="2026-10-08", note="reviewed", hits=None, sha256=None):
    """Write a sign-off entry for `name`, pinned to the file's current bytes."""
    path = Path(root) / name
    entry = {"signed_off": date, "note": note,
             "sha256": sha256 or confidentiality.file_sha256(path),
             "hits": confidentiality.hits(path) if hits is None else hits}
    existing = json.loads(signoff.read_text())["files"] if signoff.exists() else {}
    signoff.write_text(json.dumps({"files": {**existing, name: entry}}))


def test_the_confidentiality_scan_reads_values_and_flags_the_vocabulary(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps({"success_claim_pattern": "x", "a": "flights"}))
    (tmp_path / "bad.json").write_text(json.dumps({"m": "File a claim under my policyholder ID"}))
    assert confidentiality.scan(tmp_path) == {"bad.json": ["claim", "policyholder"]}
    signoff = tmp_path / "confidentiality_signoff.json"
    _sign(signoff, tmp_path, "bad.json")
    assert confidentiality.unsigned(tmp_path, signoff) == {}


def test_the_example_travel_library_would_need_a_signoff_for_its_cabin_class(tmp_path):
    """`premium` is a cabin class here, and an insurance word too: the scan
    flags it, and only a signed-off entry clears it. That is the mechanism."""
    (tmp_path / "travel.json").write_text(json.dumps(TRAVEL))
    (tmp_path / "misc.json").write_text(json.dumps(MISC))
    assert set(confidentiality.scan(tmp_path)) == {"travel.json"}


BFCL_ENTRY = {
    "id": "simple_7",
    "question": [[{"role": "user", "content": "Find the area of a triangle, base 10, height 5."}]],
    "function": [{
        "name": "geometry.area_triangle",
        "description": "Calculate the area of a triangle. Uses base times height over two.",
        "parameters": {"type": "dict", "properties": {
            "base": {"type": "integer", "description": "The base."},
            "height": {"type": "integer", "description": "The height."},
            "unit": {"type": "string", "description": "Unit of measure."}},
            "required": ["base", "height"]}}],
}
BFCL_ANSWER = {"id": "simple_7", "ground_truth": [
    {"geometry.area_triangle": {"base": [10], "height": [5], "unit": ["units", ""]}}]}


def test_a_bfcl_entry_becomes_a_draft_that_the_loader_refuses():
    tool = bfcl.draft_tool(BFCL_ENTRY["function"][0])
    sc = bfcl.draft_scenario(BFCL_ENTRY, BFCL_ANSWER, commit="abc123", domain="math",
                             irrelevance=False)
    assert tool["name"] == "geometry_area_triangle" and tool["draft"]
    assert sc["expectation"]["acceptable_calls"] == [{
        "tool": "geometry_area_triangle", "args": {"base": 10, "height": 5},
        "may_include": {"unit": "units"}}]
    assert sc["source"] == {"kind": "bfcl", "id": "simple_7", "commit": "abc123"}
    with pytest.raises(ValueError, match="draft"):
        tool_from_dict(tool, "math")
    with pytest.raises(ValueError, match="draft"):
        scenario_from_dict(sc, library())


def test_an_irrelevance_entry_becomes_a_no_call_draft():
    sc = bfcl.draft_scenario(BFCL_ENTRY, None, commit="abc", domain="math", irrelevance=True)
    assert sc["expectation"] == {"no_call_expected": True}
    assert sc["target_failure_mode"] == "SPURIOUS"


def test_bfcl_types_outside_the_subset_are_refused():
    fn = json.loads(json.dumps(BFCL_ENTRY["function"][0]))
    fn["parameters"]["properties"]["base"]["type"] = "tuple"
    with pytest.raises(ValueError, match="closed subset"):
        bfcl.draft_tool(fn)


def test_the_example_scenario_survives_a_json_round_trip():
    assert scenario_from_dict(json.loads(json.dumps(FLIGHT)), library()).id == FLIGHT["id"]


# --- the confidentiality scan reads identifiers and keys ---------------------------


def _hits_of(tmp_path, payload):
    (tmp_path / "f.json").write_text(json.dumps(payload))
    return confidentiality.hits(tmp_path / "f.json")


@pytest.mark.parametrize("payload", [
    {"tools": [{"name": "file_claim"}]},
    {"claim_id": 1},
    {"claim_status": "open"},
    {"x": "policy_number"},
    {"x": "policyNumber"},
    {"x": "policy-holder"},
    {"x": "loss_ratio"},
    {"x": "first_notice_of_loss"},
    {"x": "fnol_report"},
    {"a": {"deep": [{"claim_id": 1}]}},
    {"a": [{"b": {"c": ["underwriting"]}}]},
    "top-level claim string",
])
def test_identifiers_keys_and_nested_values_are_scanned(tmp_path, payload):
    assert _hits_of(tmp_path, payload)


@pytest.mark.parametrize("word", [
    "insures", "insuring", "reinsurance", "reinsure", "uninsured", "underinsured", "insurable",
    "claimed", "claiming", "indemnify", "indemnification", "policy\nholder",
    "first  notice\nof loss", "claimId", "Insurance", "co-insurance", "adjustor",
])
def test_inflections_and_spellings_of_the_vocabulary_are_flagged(tmp_path, word):
    assert _hits_of(tmp_path, {"m": word})


@pytest.mark.parametrize("word", [
    "exclaim", "disclaimer", "flights", "weather", "adjusted", "adjust the seat",
    "Search flights between two airports", "book_flight", "cabin", "airports",
])
def test_ordinary_words_and_lookalikes_are_not_flagged(tmp_path, word):
    assert _hits_of(tmp_path, {"m": word, "search_hotels": 1}) == []


def test_hits_are_reported_normalised_and_sorted(tmp_path):
    assert _hits_of(tmp_path, {"m": "Claims and policyHolder", "policy_number": 1}) == [
        "claims", "policy holder", "policy number"]


def test_the_signoff_file_is_skipped_by_path_not_by_name(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "confidentiality_signoff.json").write_text(json.dumps({"m": "claim"}))
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(json.dumps({"files": {}, "note": "a claim about something"}))
    assert set(confidentiality.scan(tmp_path, skip=signoff)) == {"sub/confidentiality_signoff.json"}


def test_a_signoff_is_pinned_to_the_files_bytes(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"m": "claim"}))
    signoff = tmp_path / "confidentiality_signoff.json"
    _sign(signoff, tmp_path, "bad.json")
    assert confidentiality.unsigned(tmp_path, signoff) == {}
    f.write_text(json.dumps({"m": "claim, and later text the author never read"}))
    assert confidentiality.unsigned(tmp_path, signoff) == {"bad.json": ["claim"]}


def test_a_signoff_must_cover_every_current_hit(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"m": "claim and underwriting"}))
    signoff = tmp_path / "confidentiality_signoff.json"
    _sign(signoff, tmp_path, "bad.json", hits=["claim"])
    assert confidentiality.unsigned(tmp_path, signoff) == {
        "bad.json": ["claim", "underwriting"]}


@pytest.mark.parametrize("entry, message", [
    ({"signed_off": "9999-99-99", "note": "n"}, "signed_off"),
    ({"signed_off": "2026-13-01", "note": "n"}, "signed_off"),
    ({"signed_off": "20261008", "note": "n"}, "signed_off"),
    ({"signed_off": "2026-10-08", "note": "  "}, "note"),
    ({"signed_off": "2026-10-08"}, "note"),
    ({"signed_off": "2026-10-08", "note": "n", "sha256": "abc", "hits": []}, "sha256"),
    ({"signed_off": "2026-10-08", "note": "n", "sha256": "0" * 64, "hits": "claim"}, "hits"),
    ({"signed_off": "2026-10-08", "note": "n", "hits": []}, "sha256"),
])
def test_a_malformed_signoff_entry_raises_a_clear_error(tmp_path, entry, message):
    (tmp_path / "bad.json").write_text(json.dumps({"m": "claim"}))
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(json.dumps({"files": {"bad.json": entry}}))
    with pytest.raises(ValueError, match=message):
        confidentiality.unsigned(tmp_path, signoff)


@pytest.mark.parametrize("text", ["not json", "[]", '{"files": []}', '{"files": {"a": 1}}', "{}"])
def test_a_malformed_signoff_file_raises(tmp_path, text):
    (tmp_path / "bad.json").write_text(json.dumps({"m": "claim"}))
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(text)
    with pytest.raises(ValueError, match="sign-off"):
        confidentiality.unsigned(tmp_path, signoff)


def test_a_missing_signoff_file_means_nothing_is_signed(tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps({"m": "claim"}))
    assert confidentiality.unsigned(tmp_path, tmp_path / "nope.json") == {"bad.json": ["claim"]}


def test_the_helper_prints_the_hash_and_hits_for_the_author(tmp_path, capsys):
    f = tmp_path / "bad.json"
    f.write_text(json.dumps({"m": "File a claim"}))
    assert confidentiality.main([str(f)]) == 0
    entry = json.loads(capsys.readouterr().out)["bad.json"]
    assert entry["sha256"] == confidentiality.file_sha256(f) and entry["hits"] == ["claim"]
    assert entry["signed_off"] == "YYYY-MM-DD" and entry["note"] == ""
    # the template is not a valid sign-off until the author fills it in
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(json.dumps({"files": {"bad.json": entry}}))
    with pytest.raises(ValueError, match="signed_off"):
        confidentiality.unsigned(tmp_path, signoff)


# --- numbers: strict markers, honest labels, values from the analysis ------------------


def _analysis():
    return json.loads(json.dumps(_stub_analysis()))


def test_pp_and_pct_never_print_a_negative_zero():
    assert pp(-0.0004) == "+0.0 pp" and pp(-0.0) == "+0.0 pp" and pct(-0.0001) == "0.0%"
    assert pp(-0.00051) == "-0.1 pp"


def test_the_interval_level_comes_from_each_intervals_alpha():
    from toolcall.numbers import ci_pct, ci_pp

    ci = {"point": 0.1, "lo": 0.05, "hi": 0.2, "alpha": 0.1}
    assert "90% interval" in ci_pp(ci) and "90% interval" in ci_pct(ci)
    assert "97.5% interval" in ci_pct({**ci, "alpha": 0.025})
    block = numbers_block(_analysis())
    assert "95% interval" in block and "(90% interval, margin ±2 pp)" in block


def test_a_not_testable_h5_is_stated_not_a_keyerror():
    a = _analysis()
    a["hypotheses"]["H5"] = {"testable": False, "reason": "7 scenarios with both halves",
                             "verdict": "not testable", "estimand": "e"}
    block = numbers_block(a)
    assert "not testable: 7 scenarios with both halves" in block


def test_no_label_or_value_carries_a_pipe_that_would_split_a_table_row():
    for line in numbers_block(_analysis()).splitlines()[3:-1]:
        assert line.count("|") == 3, line


def test_the_h5_rows_say_what_they_show_and_print_the_count_effect():
    a = _analysis()
    h5 = a["hypotheses"]["H5"]
    block = numbers_block(a)
    assert "H5, absolute count effect minus absolute rerun A/A contrast" in block
    assert "H5, count effect alone" in block
    assert pp(h5["count_effect"]["point"]) in block


def test_h2_says_which_part_failed():
    a = _analysis()
    a["hypotheses"]["H2"].update({"verdict": "not supported", "failed_part": "equivalence"})
    assert "not supported (the equivalence part failed)" in numbers_block(a)
    a["hypotheses"]["H2"].update({"failed_part": "difference"})
    assert "not supported (the difference part failed)" in numbers_block(a)
    a["hypotheses"]["H2"].update({"verdict": "supported", "failed_part": None})
    assert "failed" not in numbers_block(a).split("H2, strictness on malformed")[1].split("\n")[0]


def test_the_retry_cap_and_baseline_cell_come_from_the_analysis():
    from toolcall.formulation import CELLS

    a = _analysis()
    assert a["retry_cap"] == 3 and a["baseline_cell"] == "low-terse-loose"
    a["retry_cap"] = 2
    other = next(c.name for c in CELLS if c.name != a["baseline_cell"] and
                 c.name != a["ranked_cells"]["best"] and c.name != a["ranked_cells"]["worst"])
    a["baseline_cell"] = other
    block = numbers_block(a)
    assert "retrying up to 2 times" in block and "retrying up to 3 times" not in block
    assert f"baseline cell ({other})" in block and "low-terse-loose" not in block.replace(
        a["ranked_cells"]["best"], "").replace(a["ranked_cells"]["worst"], "")
    assert pct(a["cell_rates"]["failure"][other]["point"]) in block


def test_dropped_scenarios_and_a_missed_scenario_floor_are_printed():
    a = _analysis()
    clean = numbers_block(a)
    assert "| Scenarios dropped from the analysis | 0 |" in clean
    assert "scenario floor" not in clean and "dropped from H5" not in clean
    a["dropped_scenarios"] = [{"scenario": "s1"}, {"scenario": "s2"}]
    a["analysable_below_s_floor"] = True
    a["h5_dropped_scenarios"] = ["s3"]
    block = numbers_block(a)
    assert "| Scenarios dropped from the analysis | 2 |" in block
    assert "below the pre-registered scenario floor" in block
    assert "| Scenarios dropped from H5 only | 1 |" in block


def test_every_printed_value_equals_the_analysis_value():
    from toolcall.numbers import usd

    a = _analysis()
    block = numbers_block(a)
    base = a["cell_rates"]["failure"]["low-terse-loose"]
    assert f"{100 * base['point']:.1f}%" in block
    assert f"{100 * base['lo']:.1f}%" in block and f"{100 * base['hi']:.1f}%" in block
    h1 = a["hypotheses"]["H1"]
    assert f"{100 * h1['point']:+.1f} pp" in block
    retry = a["cost"]["low-terse-loose"]["retry"]
    assert usd(retry["point"]) in block and usd(retry["lo"]) in block and usd(retry["hi"]) in block
    assert f"{a['S']} scenarios" in block


def test_analyse_emits_the_retry_cap_and_baseline_cell_it_was_given():
    a = _analysis()
    prereg = example_prereg()
    assert a["retry_cap"] == prereg.retry_cap and a["baseline_cell"] == prereg.baseline_cell


@pytest.mark.parametrize("post, message", [
    (f"a {START} b {START} c {END}", "2 start markers"),
    (f"{START}\nx\n{END}\n{START}\ny\n{END}", "2 start markers"),
    (f"{END}\nx\n{START}", "end marker comes before"),
    (f"{START}\nx", "no end marker"),
    (f"x\n{END}", "no start marker"),
    (f"prose mentions `{START}` and `{END}`\n{START}\nold\n{END}", "2 start markers"),
    ("no markers at all", "no a3-numbers block"),
])
def test_the_block_needs_exactly_one_start_and_one_end_in_order(post, message):
    with pytest.raises(ValueError, match=message):
        block_in(post)
    with pytest.raises(ValueError, match=message):
        replace_block(post, f"{START}\nnew\n{END}")


def test_replace_block_keeps_the_markers_and_refuses_a_block_without_them():
    post = f"intro\n{START}\nold\n{END}\noutro {START[:4]}"
    assert replace_block(post, f"{START}\nnew\n{END}") == (
        f"intro\n{START}\nnew\n{END}\noutro {START[:4]}")
    for bad in ("new", f"{START}\nnew", f"new\n{END}", f"{END}\nnew\n{START}"):
        with pytest.raises(ValueError, match="start with"):
            replace_block(post, bad)


# --- diagnose ----------------------------------------------------------------------


class _Rec:
    def __init__(self, scenario_id, category):
        self.scenario_id, self.grade = scenario_id, {"category": category}


def test_a_run_whose_every_call_was_excluded_summarises_without_dividing_by_zero():
    from toolcall.diagnose import summarise

    summary = summarise([_Rec("s1", "API_ERROR"), _Rec("s1", "REFUSED"), _Rec("s2", "TRUNCATED")])
    text = report(summary)
    assert summary["graded"] == 0 and summary["excluded"] == {
        "API_ERROR": 1, "REFUSED": 1, "TRUNCATED": 1}
    assert all(r["share"] is None and r["pooled_wilson_lo"] is None
               for r in summary["categories"])
    assert "0 graded calls" in text and summary["note"] in text


def test_the_report_prints_the_per_scenario_breakdown_its_note_points_at():
    from toolcall.diagnose import summarise

    summary = summarise([_Rec("s1", "CORRECT"), _Rec("s1", "WRONG_TOOL"), _Rec("s2", "CORRECT")])
    text = report(summary)
    assert "| scenario |" in text and "| s1 | 0 | 0 | 0 | 1 | 0 | 1 |" in text
    assert "| s2 | 0 | 0 | 0 | 0 | 0 | 1 |" in text
    assert text.index("| category |") < text.index("| scenario |") < text.index(summary["note"])


def test_diagnose_takes_loaded_objects_and_summarises_only_its_own_run(tmp_path):
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    lib = load_library(tools_dir)
    scs = load_scenarios(sc_dir, lib, factorial=False)
    client = ScriptedClient(example_prereg().primary, StubModel(lib, scs, seed=0))
    summary = diagnose(client, lib, scs, tmp_path / "d.jsonl", reps=2)
    assert summary["graded"] == 6
    with pytest.raises(ValueError, match="store exists"):
        diagnose(client, lib, scs, tmp_path / "d.jsonl", reps=2)
    assert len(JsonlStore(tmp_path / "d.jsonl", CallRecord).read_all()) == 6


# --- bfcl --------------------------------------------------------------------------


def _entry(props, required=(), name="f.g", user="hi", fid="simple_1"):
    return {"id": fid, "question": [[{"role": "user", "content": user}]] if user else [[]],
            "function": [{"name": name, "description": "Does a thing. More.",
                          "parameters": {"type": "dict", "properties": props,
                                         "required": list(required)}}]}


def _truth(*calls, fid="simple_1"):
    return {"id": fid, "ground_truth": [{"f.g": c} for c in calls]}


def test_several_acceptable_values_become_one_of_and_an_empty_string_makes_it_optional():
    e = _entry({"a": {"type": "integer", "description": "A"},
                "b": {"type": "integer", "description": "B"}}, ["a"])
    sc = bfcl.draft_scenario(e, _truth({"a": [1, 2], "b": [3, ""]}), commit="c", domain="d",
                             irrelevance=False)
    assert sc["expectation"]["acceptable_calls"] == [{
        "tool": "f_g", "args": {"a": {"one_of": [1, 2]}}, "may_include": {"b": 3}}]


def test_an_argument_whose_only_value_is_the_empty_string_is_left_out():
    e = _entry({"a": {"type": "integer", "description": "A"},
                "c": {"type": "string", "description": "C"}}, ["a"])
    call = bfcl.draft_scenario(e, _truth({"a": [1], "c": [""]}), commit="c", domain="d",
                               irrelevance=False)["expectation"]["acceptable_calls"][0]
    assert call == {"tool": "f_g", "args": {"a": 1}, "may_include": {}}


def test_array_answers_are_kept_as_lists():
    e = _entry({"b": {"type": "array", "items": {"type": "integer"}, "description": "B"}}, ["b"])
    one = bfcl.draft_scenario(e, _truth({"b": [[1, 2]]}), commit="c", domain="d",
                              irrelevance=False)["expectation"]["acceptable_calls"][0]
    many = bfcl.draft_scenario(e, _truth({"b": [[1, 2], [2, 1]]}), commit="c", domain="d",
                               irrelevance=False)["expectation"]["acceptable_calls"][0]
    assert one["args"] == {"b": [1, 2]}
    assert many["args"] == {"b": {"one_of": [[1, 2], [2, 1]]}}


def test_parallel_or_multiple_ground_truth_is_refused_not_cut_to_one_call():
    e = _entry({"a": {"type": "integer", "description": "A"}}, ["a"])
    with pytest.raises(ValueError, match="exactly one"):
        bfcl.draft_scenario(e, _truth({"a": [1]}, {"a": [2]}), commit="c", domain="d",
                            irrelevance=False)
    with pytest.raises(ValueError, match="exactly one"):
        bfcl.draft_scenario(e, {"id": "x", "ground_truth": []}, commit="c", domain="d",
                            irrelevance=False)


def test_irrelevance_is_stated_not_inferred_from_a_missing_answer():
    e = _entry({"a": {"type": "integer", "description": "A"}}, ["a"])
    with pytest.raises(ValueError, match="answer"):
        bfcl.draft_scenario(e, None, commit="c", domain="d", irrelevance=False)
    with pytest.raises(ValueError, match="irrelevance"):
        bfcl.draft_scenario(e, _truth({"a": [1]}), commit="c", domain="d", irrelevance=True)


def test_an_entry_with_no_user_message_is_a_value_error():
    e = _entry({"a": {"type": "integer", "description": "A"}}, ["a"], user=None)
    with pytest.raises(ValueError, match="user message"):
        bfcl.draft_scenario(e, None, commit="c", domain="d", irrelevance=True)


# --- scripts/a3_import_bfcl.py -----------------------------------------------------

IMPORTER = Path(__file__).resolve().parents[1] / "scripts" / "a3_import_bfcl.py"


def _importer():
    import importlib.util

    spec = importlib.util.spec_from_file_location("a3_import_bfcl_script", IMPORTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fn(name, ptype="integer"):
    return {"name": name, "description": "Does x. More.",
            "parameters": {"type": "dict", "properties": {"a": {"type": ptype, "description": "A"}},
                           "required": ["a"]}}


def _bfcl_files(tmp_path, ids=("simple_1", "simple_2", "simple_3")):
    qs = [{"id": i, "question": [[{"role": "user", "content": "hello"}]],
           "function": [_fn(f"fn_{i}", "tuple" if i == "simple_3" else "integer")]} for i in ids]
    ans = [{"id": i, "ground_truth": [{f"fn_{i}": {"a": [1]}}]} for i in ids]
    q, a = tmp_path / "q.json", tmp_path / "a.json"
    q.write_text("\n".join(json.dumps(x) for x in qs) + "\n")
    a.write_text("\n".join(json.dumps(x) for x in ans) + "\n")
    return q, a


def _run_importer(tmp_path, *extra, ids=("simple_1", "simple_2"), domain="math", files=None):
    q, a = files or _bfcl_files(tmp_path)
    argv = ["--questions", str(q), "--ids", *ids, "--commit", "abc", "--domain", domain,
            "--out", str(tmp_path / "drafts")]
    if "--no-answers" in extra:
        extra = tuple(x for x in extra if x != "--no-answers")
    else:
        argv += ["--answers", str(a)]
    return _importer().main(argv + list(extra))


def test_the_importer_writes_drafts_the_loaders_refuse(tmp_path):
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    assert _run_importer(tmp_path) == 0
    drafts = tmp_path / "drafts"
    assert sorted(p.name for p in (drafts / "scenarios").iterdir()) == [
        "bfcl-simple_1.json", "bfcl-simple_2.json"]
    with pytest.raises(ValueError, match="draft"):
        load_library(drafts / "tools")
    with pytest.raises(ValueError, match="draft"):
        load_scenarios(drafts / "scenarios", library())


def test_the_importer_skips_and_reports_an_unsupported_entry(tmp_path, capsys):
    assert _run_importer(tmp_path, ids=("simple_1", "simple_3", "simple_2")) == 0
    out = capsys.readouterr().out
    assert "[draft] bfcl-simple_1" in out and "[draft] bfcl-simple_2" in out
    assert "[skip] simple_3" in out and "closed subset" in out
    assert not (tmp_path / "drafts" / "scenarios" / "bfcl-simple_3.json").exists()
    tools = json.loads((tmp_path / "drafts" / "tools" / "math.json").read_text())["tools"]
    assert [t["name"] for t in tools] == ["fn_simple_1", "fn_simple_2"]


def test_the_importer_refuses_to_overwrite_a_scenario_and_writes_nothing(tmp_path):
    drafts = tmp_path / "drafts"
    (drafts / "scenarios").mkdir(parents=True)
    (drafts / "scenarios" / "bfcl-simple_2.json").write_text("{}")
    with pytest.raises(ValueError, match="already exists"):
        _run_importer(tmp_path)
    assert not (drafts / "scenarios" / "bfcl-simple_1.json").exists()
    assert not (drafts / "tools").exists()
    assert (drafts / "scenarios" / "bfcl-simple_2.json").read_text() == "{}"


def test_the_importer_merges_into_an_existing_tools_file(tmp_path):
    files = _bfcl_files(tmp_path)
    assert _run_importer(tmp_path, ids=("simple_1",), files=files) == 0
    assert _run_importer(tmp_path, ids=("simple_2",), files=files) == 0
    tools = json.loads((tmp_path / "drafts" / "tools" / "math.json").read_text())["tools"]
    assert [t["name"] for t in tools] == ["fn_simple_1", "fn_simple_2"]


def test_the_importer_refuses_a_tool_name_collision_with_a_different_definition(tmp_path):
    files = _bfcl_files(tmp_path)
    assert _run_importer(tmp_path, ids=("simple_1",), files=files) == 0
    q = tmp_path / "q2.json"
    q.write_text(json.dumps({"id": "simple_9", "question": [[{"role": "user", "content": "x"}]],
                             "function": [_fn("fn_simple_1", "string")]}) + "\n")
    a = tmp_path / "a2.json"
    a.write_text(json.dumps({"id": "simple_9", "ground_truth": [{"fn_simple_1": {"a": ["x"]}}]})
                 + "\n")
    before = (tmp_path / "drafts" / "tools" / "math.json").read_text()
    with pytest.raises(ValueError, match="different definition"):
        _run_importer(tmp_path, ids=("simple_9",), files=(q, a))
    assert (tmp_path / "drafts" / "tools" / "math.json").read_text() == before
    assert not (tmp_path / "drafts" / "scenarios" / "bfcl-simple_9.json").exists()


def test_the_importer_accepts_the_same_definition_twice(tmp_path):
    files = _bfcl_files(tmp_path)
    assert _run_importer(tmp_path, ids=("simple_1",), files=files) == 0
    (tmp_path / "drafts" / "scenarios" / "bfcl-simple_1.json").unlink()
    assert _run_importer(tmp_path, ids=("simple_1",), files=files) == 0
    tools = json.loads((tmp_path / "drafts" / "tools" / "math.json").read_text())["tools"]
    assert [t["name"] for t in tools] == ["fn_simple_1"]


def test_the_importer_names_an_unknown_id(tmp_path):
    with pytest.raises(ValueError, match="simple_99.*not in"):
        _run_importer(tmp_path, ids=("simple_1", "simple_99"))
    assert not (tmp_path / "drafts").exists()


def test_the_importer_refuses_an_id_missing_from_the_answers(tmp_path):
    q, _ = _bfcl_files(tmp_path)
    a = tmp_path / "partial.json"
    a.write_text(json.dumps({"id": "simple_1", "ground_truth": [{"fn_simple_1": {"a": [1]}}]})
                 + "\n")
    with pytest.raises(ValueError, match="simple_2.*answers"):
        _run_importer(tmp_path, ids=("simple_1", "simple_2"), files=(q, a))
    assert not (tmp_path / "drafts").exists()


def test_without_answers_every_entry_is_an_irrelevance_draft(tmp_path):
    assert _run_importer(tmp_path, "--no-answers", ids=("simple_1",)) == 0
    sc = json.loads((tmp_path / "drafts" / "scenarios" / "bfcl-simple_1.json").read_text())
    assert sc["expectation"] == {"no_call_expected": True}


@pytest.mark.parametrize("domain", ["Math", "../x", "a b", "", "m.json", "a/b"])
def test_the_importer_sanitises_the_domain(tmp_path, domain):
    with pytest.raises(ValueError, match="domain"):
        _run_importer(tmp_path, domain=domain)
    assert not (tmp_path / "drafts").exists()


def test_the_importer_makes_no_network_import():
    text = IMPORTER.read_text()
    assert not any(w in text for w in ("urllib", "requests", "http.client", "socket"))


# --- scripts/a3_diagnose.py: the paid path follows the runner's spend rules --------

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a3_diagnose.py"


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("a3_diagnose_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSDK:
    """Stands where `openai.OpenAI()` or `anthropic.Anthropic()` would."""

    def __init__(self):
        from types import SimpleNamespace

        self.bodies = []
        self.responses = SimpleNamespace(create=self._openai)
        self.messages = SimpleNamespace(create=self._anthropic)

    def _reply(self, make, body):
        from types import SimpleNamespace

        self.bodies.append(body)
        resp = make(body["tools"][0]["name"], {}, model=body["model"], input_tokens=500,
                    output_tokens=40)
        return SimpleNamespace(model_dump=lambda **kw: resp)

    def _openai(self, **body):
        from toolcall.responses import openai_call

        return self._reply(openai_call, body)

    def _anthropic(self, **body):
        from toolcall.responses import anthropic_call

        return self._reply(anthropic_call, body)


@pytest.fixture
def paid(monkeypatch):
    """The script with its Client on a fake SDK and dummy keys in the environment."""
    from types import SimpleNamespace

    from toolcall.providers import Client as RealClient

    script, sdk = _script(), _FakeSDK()
    monkeypatch.setattr(script, "Client", lambda settings: RealClient(settings, sdk=sdk))
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    return SimpleNamespace(script=script, sdk=sdk, monkeypatch=monkeypatch)


def _argv(tmp_path, *extra, store="out/d.jsonl", with_store=True):
    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    argv = ["--tools", str(tools_dir), "--scenarios", str(sc_dir), "--reps", "2", *extra]
    return argv + (["--store", str(tmp_path / store)] if with_store else [])


def _ledger(tmp_path):
    return tmp_path / "out" / "d.jsonl.spend.jsonl"


def _cost(tmp_path, settings=None):
    from toolcall.formulation import Formulation
    from toolcall.runner import plan_cost
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    lib = load_library(tools_dir)
    scs = load_scenarios(sc_dir, lib, factorial=False)
    return plan_cost(settings or example_prereg().primary, lib, scs,
                     [Formulation("low", "rich", "strict")], 2)


def test_the_script_dry_run_is_stub_only_and_writes_no_ledger(tmp_path, capsys):
    assert _script().main(_argv(tmp_path, "--dry-run")) == 0
    assert "6 graded calls; excluded: 0" in capsys.readouterr().out
    assert not _ledger(tmp_path).exists()


def test_the_script_dry_run_needs_no_store(tmp_path, capsys):
    assert _script().main(_argv(tmp_path, "--dry-run", with_store=False)) == 0
    assert "6 graded calls" in capsys.readouterr().out


def test_a_paid_run_needs_a_store(paid, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        paid.script.main(_argv(tmp_path, "--approved-usd", "50", with_store=False))
    assert e.value.code == 2 and "--store" in capsys.readouterr().err
    assert paid.sdk.bodies == []


def test_reps_must_be_at_least_one(paid, tmp_path, capsys):
    for bad in ("0", "-3"):
        argv = _argv(tmp_path, "--dry-run")
        argv[argv.index("--reps") + 1] = bad
        with pytest.raises(SystemExit) as e:
            paid.script.main(argv)
        assert e.value.code == 2 and "--reps" in capsys.readouterr().err


def test_the_script_refuses_a_store_or_ledger_that_already_holds_anything(paid, tmp_path):
    script = paid.script
    out = tmp_path / "out"
    out.mkdir()
    (out / "d.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        script.main(_argv(tmp_path, "--approved-usd", "50"))
    (out / "d.jsonl").unlink()
    _ledger(tmp_path).write_text('{"id": 0, "reserve": 1.0}\n')
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        script.main(_argv(tmp_path, "--approved-usd", "50"))
    (out / "d.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="store exists"):
        script.main(_argv(tmp_path, "--dry-run"))  # a dry run does not append to a used store
    assert paid.sdk.bodies == []


def test_the_ledger_is_named_after_the_store(paid, tmp_path):
    _, est, headroom = _cost(tmp_path)
    assert paid.script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom),
                                  store="out/run7.jsonl")) == 0
    assert (tmp_path / "out" / "run7.jsonl.spend.jsonl").exists()


def test_the_script_needs_an_approval_covering_the_estimate_plus_headroom(paid, tmp_path, capsys):
    from toolcall.guard import SpendCapReached

    calls, est, headroom = _cost(tmp_path)
    assert headroom > 0 and calls == 6
    with pytest.raises(SpendCapReached, match="finite positive"):
        paid.script.main(_argv(tmp_path))
    with pytest.raises(SpendCapReached, match="exceeds"):
        paid.script.main(_argv(tmp_path, "--approved-usd", repr(est)))  # the estimate alone
    assert f"{calls} calls, estimated ${est:.2f} + ${headroom:.2f} guard headroom" in \
        capsys.readouterr().out
    assert paid.sdk.bodies == [] and not _ledger(tmp_path).exists()


def test_the_script_runs_a_covered_approval_through_a_ledger_and_releases_its_lock(
        paid, tmp_path):
    from toolcall.guard import SpendLedger

    _, est, headroom = _cost(tmp_path)
    assert paid.script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom))) == 0
    assert len(paid.sdk.bodies) == 6
    with SpendLedger(_ledger(tmp_path)) as held:  # the script's lock is gone
        assert 0 < held.total() <= est + headroom
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        paid.script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom)))


def test_an_anthropic_run_works_through_the_same_path(paid, tmp_path):
    settings = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
    _, est, headroom = _cost(tmp_path, settings)
    assert paid.script.main(_argv(tmp_path, "--provider", "anthropic",
                                  "--approved-usd", repr(est + headroom))) == 0
    assert len(paid.sdk.bodies) == 6 and all(
        b["model"] == "claude-sonnet-5-5" for b in paid.sdk.bodies)


def test_the_default_model_follows_the_provider(paid, tmp_path):
    _, est, headroom = _cost(tmp_path)
    paid.script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom)))
    assert {b["model"] for b in paid.sdk.bodies} == {"gpt-5.4-mini-2026-03-17"}


@pytest.mark.parametrize("provider, model", [("anthropic", "gpt-5.4-mini-2026-03-17"),
                                             ("openai", "claude-sonnet-5-5")])
def test_a_model_of_the_other_provider_is_refused(paid, tmp_path, provider, model):
    with pytest.raises(ValueError, match="provider"):
        paid.script.main(_argv(tmp_path, "--provider", provider, "--model", model,
                               "--approved-usd", "50"))
    assert paid.sdk.bodies == [] and not _ledger(tmp_path).exists()


@pytest.mark.parametrize("provider, var", [("openai", "OPENAI_API_KEY"),
                                           ("anthropic", "ANTHROPIC_API_KEY")])
def test_a_missing_api_key_is_refused_before_the_lock_or_any_post(paid, tmp_path, provider, var):
    paid.monkeypatch.delenv(var)
    with pytest.raises(ValueError, match=var):
        paid.script.main(_argv(tmp_path, "--provider", provider, "--approved-usd", "50"))
    assert paid.sdk.bodies == [] and not _ledger(tmp_path).exists()
    assert not (tmp_path / "out" / "d.jsonl.spend.lock").exists()


def test_the_script_exits_nonzero_when_nothing_was_graded(paid, tmp_path, capsys):
    from toolcall.diagnose import summarise

    paid.monkeypatch.setattr(paid.script, "diagnose", lambda *a, **k: summarise([]))
    assert paid.script.main(_argv(tmp_path, "--dry-run")) == 1
    assert "no graded calls" in capsys.readouterr().err
