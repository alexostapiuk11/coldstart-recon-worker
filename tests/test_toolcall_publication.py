"""The numbers block, the bring-your-own-tools path, the confidentiality scan
and the BFCL import. All offline."""

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
from toolcall.providers import ScriptedClient
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


def test_the_confidentiality_scan_reads_values_and_flags_the_vocabulary(tmp_path):
    (tmp_path / "ok.json").write_text(json.dumps({"success_claim_pattern": "x", "a": "flights"}))
    (tmp_path / "bad.json").write_text(json.dumps({"m": "File a claim under my policyholder ID"}))
    assert confidentiality.scan(tmp_path) == {"bad.json": ["claim", "policyholder"]}
    signoff = tmp_path / "confidentiality_signoff.json"
    signoff.write_text(json.dumps({"files": {"bad.json": {"signed_off": "2026-10-08",
                                                          "note": "test"}}}))
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
    sc = bfcl.draft_scenario(BFCL_ENTRY, BFCL_ANSWER, commit="abc123", domain="math")
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
    sc = bfcl.draft_scenario(BFCL_ENTRY, None, commit="abc", domain="math")
    assert sc["expectation"] == {"no_call_expected": True}
    assert sc["target_failure_mode"] == "SPURIOUS"


def test_bfcl_types_outside_the_subset_are_refused():
    fn = json.loads(json.dumps(BFCL_ENTRY["function"][0]))
    fn["parameters"]["properties"]["base"]["type"] = "tuple"
    with pytest.raises(ValueError, match="closed subset"):
        bfcl.draft_tool(fn)


def test_the_example_scenario_survives_a_json_round_trip():
    assert scenario_from_dict(json.loads(json.dumps(FLIGHT)), library()).id == FLIGHT["id"]


# --- scripts/a3_diagnose.py: the paid path follows the runner's spend rules --------

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "a3_diagnose.py"


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("a3_diagnose_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSDK:
    def __init__(self):
        from types import SimpleNamespace

        self.bodies = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **body):
        from types import SimpleNamespace

        from toolcall.responses import openai_call

        self.bodies.append(body)
        resp = openai_call(body["tools"][0]["name"], {}, model=body["model"],
                           input_tokens=500, output_tokens=40)
        return SimpleNamespace(model_dump=lambda **kw: resp)


def _argv(tmp_path, *extra, store="out/d.jsonl"):
    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    return ["--tools", str(tools_dir), "--scenarios", str(sc_dir), "--reps", "2",
            "--store", str(tmp_path / store), *extra]


def _cost(tmp_path):
    from toolcall.formulation import Formulation
    from toolcall.scenarios import load_scenarios
    from toolcall.tools import load_library

    tools_dir, sc_dir = write_suite(tmp_path / "suite")
    lib = load_library(tools_dir)
    scs = load_scenarios(sc_dir, lib, factorial=False)
    settings = example_prereg().primary
    from toolcall.runner import plan_cost

    return plan_cost(settings, lib, scs, [Formulation("low", "rich", "strict")], 2)


def test_the_script_dry_run_is_stub_only_and_writes_no_ledger(tmp_path, capsys):
    assert _script().main(_argv(tmp_path, "--dry-run")) == 0
    assert "6 graded calls; excluded: 0" in capsys.readouterr().out
    assert not (tmp_path / "out" / "diagnose.spend.jsonl").exists()


def test_the_script_refuses_a_store_or_ledger_that_already_holds_anything(tmp_path, monkeypatch):
    script = _script()
    sdk = _FakeSDK()
    monkeypatch.setattr(script, "Client", lambda settings: __import__(
        "toolcall.providers", fromlist=["Client"]).Client(settings, sdk=sdk))
    out = tmp_path / "out"
    out.mkdir()
    (out / "d.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        script.main(_argv(tmp_path, "--approved-usd", "50"))
    (out / "d.jsonl").unlink()
    (out / "diagnose.spend.jsonl").write_text('{"id": 0, "reserve": 1.0}\n')
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        script.main(_argv(tmp_path, "--approved-usd", "50"))
    (out / "d.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="store exists"):
        script.main(_argv(tmp_path, "--dry-run"))  # a dry run does not append to a used store
    assert sdk.bodies == []


def test_the_script_needs_an_approval_covering_the_estimate_plus_headroom(tmp_path, monkeypatch,
                                                                          capsys):
    from toolcall.guard import SpendCapReached

    script = _script()
    sdk = _FakeSDK()
    monkeypatch.setattr(script, "Client", lambda settings: __import__(
        "toolcall.providers", fromlist=["Client"]).Client(settings, sdk=sdk))
    calls, est, headroom = _cost(tmp_path)
    assert headroom > 0 and calls == 6
    with pytest.raises(SpendCapReached, match="finite positive"):
        script.main(_argv(tmp_path))
    with pytest.raises(SpendCapReached, match="exceeds"):
        script.main(_argv(tmp_path, "--approved-usd", repr(est)))  # the estimate alone
    assert f"{calls} calls, estimated ${est:.2f} + ${headroom:.2f} guard headroom" in \
        capsys.readouterr().out
    assert sdk.bodies == [] and not (tmp_path / "out" / "diagnose.spend.jsonl").exists()


def test_the_script_runs_a_covered_approval_through_a_ledger_and_releases_its_lock(
        tmp_path, monkeypatch):
    from toolcall.guard import SpendLedger

    script = _script()
    sdk = _FakeSDK()
    monkeypatch.setattr(script, "Client", lambda settings: __import__(
        "toolcall.providers", fromlist=["Client"]).Client(settings, sdk=sdk))
    _, est, headroom = _cost(tmp_path)
    assert script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom))) == 0
    assert len(sdk.bodies) == 6
    ledger = tmp_path / "out" / "diagnose.spend.jsonl"
    with SpendLedger(ledger) as held:  # the script's lock is gone
        assert 0 < held.total() <= est + headroom
    with pytest.raises(ValueError, match="store exists; choose a new --store"):
        script.main(_argv(tmp_path, "--approved-usd", repr(est + headroom)))
