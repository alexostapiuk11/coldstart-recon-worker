"""The whole offline path on the stub, which has known effects planted in it:
campaign, recovery, analysis. The analysis must recover what was put in.

Planted (toolcall/stub.py): tool count raises WRONG_TOOL, rich descriptions
cut it only at high count, strict schemas cut MALFORMED and WRONG_PARAMS and
leave WRONG_TOOL alone, and opaque errors bring more identical retries.
"""

import json
from dataclasses import replace

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.analysis import ESTIMANDS, analyse
from toolcall.effects import average, contrast, graded_outcomes, half_rows, rate_rows
from toolcall.formulation import CELLS, parse_cell
from toolcall.grader import FAILURES
from toolcall.hypotheses import bootstrap_params
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


# --- the pre-registered scenario floor, the sensitivity analysis, flag counts ---

N_SCEN = 66  # synthetic_suite(60, 6): 60 call scenarios and 6 more
CELL_A = "low-terse-loose"
CELL_B = "high-terse-loose"


def _api_error(r):
    """A call the provider never answered: ungradable, unmetered, no cost."""
    return replace(r, grade={**r.grade, "category": "API_ERROR"}, usage=None, cost_usd=None,
                   unmetered=True)


def _variant(run, mutate, **prereg_overrides):
    calls, recs, scs, _ = run
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=8, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=100, **prereg_overrides)
    return analyse([mutate(r) for r in calls], recs, scs, prereg), calls, scs


@pytest.fixture(scope="module")
def trimmed(run):
    """Scenario 0 keeps one graded repetition in CELL_A (below the floor of 3);
    scenarios 1-10 lose two repetitions to API errors in CELL_B (above it);
    two calls have no response text."""
    scs = run[2]
    short = scs[0].id
    thinned = {s.id for s in scs[1:11]}

    def mutate(r):
        if r.scenario_id == short and r.cell == CELL_A and r.block_index >= 1:
            return _api_error(r)
        if r.scenario_id in thinned and r.cell == CELL_B and r.block_index < 2:
            return _api_error(r)
        if r.scenario_id == scs[20].id and r.cell == CELL_A and r.block_index < 2:
            return replace(r, grade={**r.grade, "empty_response": True})
        return r

    analysis, calls, scs = _variant(run, mutate)
    return analysis, calls, short, thinned


def test_a_scenario_below_the_floor_is_dropped_and_disclosed(analysis, trimmed):
    a, _, short, _ = trimmed
    assert analysis["S"] == N_SCEN and analysis["dropped_scenarios"] == []
    assert a["S"] == N_SCEN - 1
    (d,) = a["dropped_scenarios"]
    assert d["scenario"] == short
    assert d["graded_by_cell"][CELL_A] == 1
    assert all(n == 8 for c, n in d["graded_by_cell"].items() if c != CELL_A)
    assert CELL_A in d["reason"]


def test_every_estimate_is_about_the_same_analysable_scenarios(trimmed):
    a, *_ = trimmed
    assert a["effects"]["failure"]["main:count"]["n_scenarios"] == N_SCEN - 1
    assert a["cell_rates"]["failure"][CELL_A]["n_scenarios"] == N_SCEN - 1
    assert a["hypotheses"]["H1"]["n_scenarios"] == N_SCEN - 1
    assert a["hypotheses"]["H3"]["n_scenarios"] == N_SCEN - 1
    assert a["hypotheses"]["H5"]["n_scenarios"] == N_SCEN - 1
    assert a["cost"][CELL_A]["retry"]["n_scenarios"] == N_SCEN - 1
    sens = a["sensitivity_exclusions_as_failures"]["effects"]
    assert sens["main:count"]["n_scenarios"] == N_SCEN - 1
    assert a["flakiness"]["ever_flip"]["n_scenarios"] == N_SCEN - 1


def test_ever_flip_counts_only_units_with_two_or_more_graded_repetitions(run, analysis):
    assert analysis["flakiness"]["units_with_two_or_more"] == N_SCEN * 8
    a, _, _ = _variant(
        run, lambda r: _api_error(r) if (r.scenario_id == run[2][0].id and r.cell == CELL_A
                                         and r.block_index >= 1) else r,
        min_graded_per_cell=1, retry_cap=1)  # costs need retry_cap <= the shortest cell
    # With a floor of 1 the scenario stays, and its one-repetition cell is not
    # an informative unit: it cannot flip, so it is left out of the fraction.
    assert a["S"] == N_SCEN and a["dropped_scenarios"] == []
    assert a["flakiness"]["units_with_two_or_more"] == N_SCEN * 8 - 1
    assert a["flakiness"]["units"] == N_SCEN * 8


def test_the_sensitivity_analysis_recomputes_every_estimand_and_is_labelled(analysis, trimmed):
    a, *_ = trimmed
    block = a["sensitivity_exclusions_as_failures"]
    assert "exploratory" in block["label"]
    assert set(block["effects"]) == set(ESTIMANDS)
    for e in block["effects"].values():
        assert e["lo"] <= e["point"] <= e["hi"]
    # Counting API errors as failures moves the failure effect it is meant to probe.
    assert (block["effects"]["main:count"]["point"]
            != a["effects"]["failure"]["main:count"]["point"])
    # Nothing excluded in the clean stub run, so there the two agree exactly.
    clean = analysis["sensitivity_exclusions_as_failures"]["effects"]
    for e in ESTIMANDS:
        assert clean[e]["point"] == pytest.approx(analysis["effects"]["failure"][e]["point"])


def test_counts_report_empty_responses_and_unmetered_calls_per_cell(analysis, trimmed):
    a, calls, _short, thinned = trimmed
    assert all(c["empty_response"] == 0 and c["unmetered"] == 0
               for c in analysis["counts"].values())
    assert a["counts"][CELL_A]["empty_response"] == 2
    assert a["counts"][CELL_A]["unmetered"] == 7  # the dropped scenario's API errors
    assert a["counts"][CELL_B]["unmetered"] == 2 * len(thinned)
    assert a["counts"][CELL_B]["API_ERROR"] == 2 * len(thinned)
    # `counts` covers every call of the included scenarios, dropped ones too.
    assert sum(c["calls"] for c in a["counts"].values()) == len(calls)


def test_h5_pairs_each_scenario_with_its_own_aa_contrast_and_drops_empty_halves(run):
    scs = run[2]
    odd_less = scs[5].id

    def mutate(r):  # in one cell, every odd repetition is lost: no odd half
        if r.scenario_id == odd_less and r.cell == CELL_A and r.block_index % 2 == 1:
            return _api_error(r)
        return r

    a, calls, _ = _variant(run, mutate)
    assert a["S"] == N_SCEN and a["dropped_scenarios"] == []  # four graded reps remain
    h5 = a["hypotheses"]["H5"]
    assert h5["dropped_scenarios"] == [odd_less] == a["h5_dropped_scenarios"]
    assert h5["n_scenarios"] == N_SCEN - 1 and a["hypotheses"]["H1"]["n_scenarios"] == N_SCEN
    keep = sorted(s.id for s in scs if s.id != odd_less)
    outcomes = graded_outcomes([mutate(r) for r in calls])
    rows = rate_rows(outcomes, FAILURES, scenarios=keep)
    aa = half_rows(outcomes, FAILURES, scenarios=keep)
    expected = (abs(average(contrast(r, "main:count") for r in rows))
                - abs(average(contrast(h, "main:count") for h in aa)))
    assert h5["point"] == pytest.approx(expected)


def test_one_helper_carries_the_bootstrap_settings(analysis, run):
    prereg = run[3]
    assert bootstrap_params(prereg) == {"iterations": prereg.iterations,
                                        "seed": prereg.bootstrap_seed, "alpha": prereg.alpha}
    assert analysis["effects"]["failure"]["main:count"]["iterations"] == prereg.iterations
    assert analysis["cost"][CELL_A]["retry"]["iterations"] == prereg.iterations
    assert analysis["hypotheses"]["H4"]["iterations"] == prereg.iterations


def test_the_analysis_flags_fewer_analysable_scenarios_than_s_floor(run, analysis, trimmed):
    assert analysis["analysable_below_s_floor"] is False
    assert trimmed[0]["analysable_below_s_floor"] is False
    short = run[2][0].id

    def mutate(r):
        return _api_error(r) if (r.scenario_id == short and r.cell == CELL_A
                                 and r.block_index >= 1) else r

    a, _, _ = _variant(run, mutate, s_floor=N_SCEN)  # one scenario is dropped: S < s_floor
    assert a["S"] == N_SCEN - 1 and a["analysable_below_s_floor"] is True
    assert a["hypotheses"]["H1"]["n_scenarios"] == N_SCEN - 1  # the estimates still run


def test_h2_reads_p_ge_0_and_is_holm_rejected_on_the_planted_strictness_effect(analysis):
    h2 = analysis["hypotheses"]["H2"]
    assert h2["point"] < 0
    assert h2["p"] == h2["p_ge_0"] < h2["p_le_0"]
    assert h2["holm_rejects"] is True
    assert h2["failed_part"] in (None, "equivalence")
    assert (h2["failed_part"] is None) == (h2["verdict"] == "supported")


def _slice_records(calls, cells, mutate=lambda r: r, only=None):
    return [mutate(r) for r in calls if r.cell in cells and (only is None or r.scenario_id in only)]


def test_slice_models_use_the_scenarios_they_have_and_say_which_are_left_out(
        run, analysis):
    calls, recs, scs, _ = run
    cells = (analysis["ranked_cells"]["best"], analysis["ranked_cells"]["worst"])
    thin = scs[3].id
    few = {s.id for s in scs[:10]}
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=8, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=100)
    a = analyse(calls, recs, scs, prereg, slices={
        "full": _slice_records(calls, cells),
        "thin": _slice_records(calls, cells, lambda r: _api_error(r) if (
            r.scenario_id == thin and r.cell == cells[1] and r.block_index >= 1) else r),
        "tiny": _slice_records(calls, cells, only=few),
    })["slice"]
    assert a["full"]["estimable"] and a["full"]["dropped_scenarios"] == []
    assert a["full"]["difference"]["n_scenarios"] == N_SCEN
    assert a["thin"]["estimable"] and a["thin"]["difference"]["n_scenarios"] == N_SCEN - 1
    (d,) = a["thin"]["dropped_scenarios"]
    assert d["scenario"] == thin and d["graded_by_cell"][cells[1]] == 1
    assert a["tiny"]["estimable"] is False and "bootstrap floor" in a["tiny"]["reason"]
    assert len(a["tiny"]["dropped_scenarios"]) == N_SCEN - len(few)
    assert "difference" not in a["tiny"]


def test_exploratory_calls_are_counted_on_the_analysable_set_and_must_be_in_the_best_cell(
        run, analysis, trimmed):
    calls, recs, scs, _ = run
    best = analysis["ranked_cells"]["best"]
    explo = [r for r in calls if r.cell == best]
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=8, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=100)
    short = trimmed[2]  # dropped when its CELL_A calls are thinned
    thinned = [_api_error(r) if (r.scenario_id == short and r.cell == CELL_A
                                 and r.block_index >= 1) else r for r in calls]
    a = analyse(thinned, recs, scs, prereg, exploratory=explo)
    assert a["exploratory_constrained"]["cell"] == a["ranked_cells"]["best"]
    assert a["dropped_scenarios"][0]["scenario"] == short  # not analysable, so not counted
    assert sum(a["exploratory_constrained"]["counts"].values()) == sum(
        r.scenario_id != short for r in explo)
    other = next(r for r in calls if r.cell != best)
    with pytest.raises(ValueError, match="best cell"):
        analyse(calls, recs, scs, prereg, exploratory=[*explo, other])
