"""The whole offline path on the stub, which has known effects planted in it:
campaign, recovery, analysis. The analysis must recover what was put in.

Planted (toolcall/stub.py): tool count raises WRONG_TOOL, rich descriptions
cut it only at high count, strict schemas cut MALFORMED and WRONG_PARAMS and
leave WRONG_TOOL alone, and opaque errors bring more identical retries.
"""

import json

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.analysis import analyse
from toolcall.formulation import CELLS, parse_cell
from toolcall.providers import ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    lib = library()
    scs = scenarios(synthetic_suite(60, 6))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=8, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=400)
    client = ScriptedClient(prereg.primary, StubModel(lib, scs, seed=5, stickiness=0.5))
    calls = JsonlStore(tmp / "campaign.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, prereg.reps, 1), client, scs, lib,
                         calls, phase="campaign")
    rec_scs = [s for s in scs if s.recovery]
    recs = JsonlStore(tmp / "recovery.jsonl", RecoveryRecord)
    cells = [parse_cell("low-terse-loose"), parse_cell("high-rich-strict")]
    campaign.recovery_runs(campaign.schedule(cells, rec_scs, prereg.recovery_reps, 2,
                                             formats=["actionable", "opaque"]),
                           client, rec_scs, lib, recs)
    return calls.read_all(), recs.read_all(), scs, prereg


@pytest.fixture(scope="module")
def analysis(run):
    calls, recs, scs, prereg = run
    return analyse(calls, recs, scs, prereg)


def test_count_raises_wrong_tool(analysis):
    e = analysis["effects"]["WRONG_TOOL"]["main:count"]
    assert e["lo"] > 0


def test_richness_matters_at_high_count_and_little_at_low(analysis):
    eff = analysis["effects"]["WRONG_TOOL"]
    assert eff["at:richness:count:high"]["hi"] < 0
    assert eff["at:richness:count:low"]["lo"] < 0 < eff["at:richness:count:low"]["hi"]


def test_strictness_cuts_malformed_and_wrong_params_and_not_wrong_tool(analysis):
    assert analysis["effects"]["MALFORMED+WRONG_PARAMS"]["main:strictness"]["hi"] < 0
    s = analysis["effects"]["WRONG_TOOL"]["main:strictness"]
    assert s["lo"] < 0 < s["hi"]


def test_h4_finds_more_identical_retries_after_opaque_errors(analysis):
    h4 = analysis["hypotheses"]["H4"]
    assert h4["testable"] and h4["lo"] > 0 and h4["verdict"] == "supported"


def test_every_hypothesis_has_a_verdict_and_holm_was_applied(analysis):
    for h in analysis["hypotheses"].values():
        assert h["verdict"] in ("supported", "not supported", "not testable")
    assert all("holm_rejects" in h for h in analysis["hypotheses"].values()
               if h["verdict"] != "not testable")


def test_the_analysis_is_plain_json_and_deterministic(run, analysis):
    calls, recs, scs, prereg = run
    again = analyse(calls, recs, scs, prereg)
    assert json.dumps(analysis, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_counts_add_up(run, analysis):
    calls = run[0]
    assert sum(c["calls"] for c in analysis["counts"].values()) == len(calls)


def test_the_retry_policy_costs_more_than_the_independence_formula_says(analysis):
    """Sticky repetitions: a failing scenario fails again, so retrying is
    worse than c / (1 - f) assumes (amendment §4f). Checked on the worst cell."""
    worst = analysis["cost"][analysis["ranked_cells"]["worst"]]
    assert worst["retry"]["point"] > worst["geometric_usd_per_success"]


def test_excluded_scenarios_are_left_out(run):
    calls, recs, scs, _ = run
    keep = tuple(s.id for s in scs[:40])
    a = analyse(calls, recs, scs, example_prereg(included=keep, reps=8, recovery_reps=5,
                                                  slice_reps=5, approved_usd=1.0,
                                                  iterations=100))
    assert a["S"] == 40
