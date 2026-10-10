import math
from dataclasses import MISSING, fields
from types import SimpleNamespace

import pytest

from tests.a3_examples import example_prereg, scenarios, synthetic_suite
from toolcall.budget import Line, table
from toolcall.formulation import CELLS
from toolcall.prereg import STEP2, prereg_table
from toolcall.providers import ModelSettings
from toolcall.selection import baseline_table, rho, step2_proposal, table_markdown


def test_the_example_is_valid_and_step_two_starts_unset():
    p = example_prereg()
    assert not p.step2_complete
    with pytest.raises(ValueError, match="step 2 is not committed"):
        p.require_step2()


@pytest.mark.parametrize("kw, match", [
    ({"band": (0.9, 0.1)}, "band"),
    ({"n_floor": 1}, "A/A"),
    ({"s_floor": 10}, "bootstrap floor"),
    ({"normalizer_version": 2}, "grading rules changed"),
    ({"baseline_cell": "mid-terse-loose"}, "count"),
    ({"included": ("a",) * 30}, "duplicates"),
    ({"included": tuple(f"s{i}" for i in range(10))}, "below s_floor"),
    ({"reps": 3}, "outside"),
])
def test_invalid_values_are_refused(kw, match):
    with pytest.raises(ValueError, match=match):
        example_prereg(**kw)


def test_the_table_names_every_field():
    table = prereg_table(example_prereg())
    for f in fields(example_prereg()):
        assert f"| `{f.name}` |" in table


def _pilot(rates: dict[str, float], reps=10):
    out = []
    for sid, rate in rates.items():
        k = round(rate * reps)
        for b in range(reps):
            out.append(_rec(sid, b, "CORRECT" if b < k else "WRONG_TOOL"))
    return out


def _rec(sid, b, category, cell="low-terse-loose"):
    return SimpleNamespace(scenario_id=sid, cell=cell, run_index=b, block_index=b, usage=None,
                           grade={"category": category})


def test_selection_keeps_the_band_and_lists_every_candidate_with_its_reason():
    scs = scenarios(synthetic_suite(3, 0))
    rates = {scs[0].id: 1.0, scs[1].id: 0.5, scs[2].id: 0.0}
    rows = baseline_table(_pilot(rates), scs, example_prereg())
    assert {r["scenario"]: r["include"] for r in rows} == {
        scs[0].id: False, scs[1].id: True, scs[2].id: False}
    reasons = {r["scenario"]: r["reason"] for r in rows}
    assert reasons[scs[0].id] == "at or near ceiling" and reasons[scs[2].id] == "at or near floor"
    md = table_markdown(rows)
    assert md.count("\n") == len(rows) + 1


def test_selection_refuses_pilot_runs_outside_the_baseline_cell():
    scs = scenarios(synthetic_suite(1, 0))
    bad = [_rec(scs[0].id, 0, "CORRECT", cell="high-rich-strict")]
    with pytest.raises(ValueError, match="not the baseline cell"):
        baseline_table(bad, scs, example_prereg())


def test_rho_from_the_pilot():
    recs = _pilot({"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0})
    assert rho(recs, {"a", "b", "c", "d"}) == 1.0


def test_min_graded_per_cell_defaults_to_three_and_appears_in_the_table():
    p = example_prereg()
    assert p.min_graded_per_cell == 3
    assert "| `min_graded_per_cell` | `3` |" in prereg_table(p)


@pytest.mark.parametrize("value", [1, 2])
def test_min_graded_per_cell_below_retry_cap_is_refused(value):
    with pytest.raises(ValueError, match="full group of retry_cap"):
        example_prereg(retry_cap=3, min_graded_per_cell=value)
    example_prereg(retry_cap=value, min_graded_per_cell=value)  # at the cap is allowed


@pytest.mark.parametrize("value", [0, 6])
def test_min_graded_per_cell_outside_one_to_n_floor_is_refused(value):
    with pytest.raises(ValueError, match="min_graded_per_cell"):
        example_prereg(min_graded_per_cell=value)


def _step2(**overrides):
    values = {"included": tuple(f"s{i}" for i in range(24)), "reps": 5,
              "recovery_reps": 5, "slice_reps": 5, "approved_usd": 100.0}
    values.update(overrides)
    return values


def test_a_complete_step_two_is_accepted():
    p = example_prereg(**_step2())
    assert p.step2_complete
    p.require_step2()


def test_step_two_is_the_trailing_default_none_fields():
    trailing = []
    for f in reversed(fields(example_prereg())):
        if f.default is None:
            trailing.append(f.name)
        else:
            break
    assert STEP2 == tuple(reversed(trailing))
    assert all(f.default is not MISSING for f in fields(example_prereg()) if f.name in STEP2)


_ANTHROPIC = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
_PRIMARY = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
_NANO = ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0, reasoning_effort="none")


@pytest.mark.parametrize("kw, match", [
    ({"pilot_reps": True}, "pilot_reps must be a positive int"),
    ({"n_cap": 20.0}, "n_cap must be a positive int"),
    ({"iterations": "300"}, "iterations must be a positive int"),
    ({"bootstrap_seed": None}, "bootstrap_seed must be an int"),
    ({"bootstrap_seed": "7"}, "bootstrap_seed must be an int"),
    ({"bootstrap_seed": True}, "bootstrap_seed must be an int"),
    ({"schedule_seed": None}, "schedule_seed must be an int"),
    ({"schedule_seed": 1.5}, "schedule_seed must be an int"),
    ({"min_graded_per_cell": True}, "min_graded_per_cell must be an int"),
    ({"primary": "gpt-5.4-mini-2026-03-17"}, "must be ModelSettings"),
    ({"primary": ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0,
                               reasoning_effort="none", constrained=True)}, "constrained"),
    ({"slice_models": ()}, "non-empty"),
    ({"slice_models": [_NANO]}, "non-empty tuple"),
    ({"slice_models": (_NANO, _NANO)}, "distinct"),
    ({"slice_models": (_PRIMARY,)}, "distinct"),
    ({"slice_models": (ModelSettings("openai", "gpt-unpriced", 0.0, reasoning_effort="none"),)},
     "no pinned price"),
    ({"band": [0.1, 0.9]}, "band must be a"),
    ({"iterations": 99}, "below 100"),
    ({"alpha": 0.6}, "alpha"),
    ({"alpha": 0.26}, "alpha"),
    ({"alpha": 0.5}, "alpha"),  # H2 would use 2*alpha = 1, which harness.stats refuses
    ({"alpha": 0.0}, "alpha"),
    ({"reps": 5}, "partly committed"),
    ({"approved_usd": 10.0}, "partly committed"),
    (_step2(included=[f"s{i}" for i in range(24)]), "included must be a tuple"),
    (_step2(reps=True), "reps must be a positive int"),
    (_step2(reps=5.0), "reps must be a positive int"),
    (_step2(recovery_reps=21), "recovery_reps 21 outside"),
    (_step2(slice_reps=21), "slice_reps 21 outside"),
    (_step2(slice_reps=4), "slice_reps 4 outside"),
    (_step2(approved_usd=math.nan), "approved_usd"),
    (_step2(approved_usd=math.inf), "approved_usd"),
    (_step2(approved_usd=0.0), "approved_usd"),
    (_step2(approved_usd=-5.0), "approved_usd"),
    (_step2(approved_usd=True), "approved_usd"),
    (_step2(approved_usd="100"), "approved_usd"),
])
def test_unusable_values_are_refused(kw, match):
    with pytest.raises(ValueError, match=match):
        example_prereg(**kw)


def test_boundary_values_are_accepted():
    example_prereg(iterations=100, alpha=0.25, bootstrap_seed=0, schedule_seed=-3,
                   slice_models=(_NANO, _ANTHROPIC))
    example_prereg(**_step2(recovery_reps=20, slice_reps=5))


def test_the_table_is_stable_for_tuples():
    assert "`(0.1, 0.9)`" in prereg_table(example_prereg())


def test_band_endpoints_are_included():
    scs = scenarios(synthetic_suite(2, 0))
    rows = baseline_table(_pilot({scs[0].id: 0.1, scs[1].id: 0.9}), scs, example_prereg())
    assert [r["include"] for r in rows] == [True, True]
    assert all(r["reason"] == "inside the band" for r in rows)


def test_a_candidate_with_no_graded_repetitions_is_listed_and_excluded():
    scs = scenarios(synthetic_suite(3, 0))
    pilot = _pilot({scs[0].id: 0.5, scs[1].id: 0.5})
    pilot += [_rec(scs[2].id, b, "API_ERROR") for b in range(3)]
    rows = baseline_table(pilot, scs, example_prereg())
    zero = rows[2]
    assert zero["scenario"] == scs[2].id
    assert (zero["n"], zero["rate"], zero["include"], zero["excluded"]) == (0, None, False, 3)
    assert zero["reason"] == "no graded pilot repetitions"
    md = table_markdown(rows)
    assert md.count("\n") == len(rows) + 1
    assert f"| `{scs[2].id}` | | 0 / 0 | | | 3 | exclude: no graded pilot repetitions |" in md
    assert "| excluded |" in md
    # a candidate absent from the pilot altogether gets the same row, with none excluded
    assert baseline_table(_pilot({scs[0].id: 0.5}), scs, example_prereg())[1]["excluded"] == 0


def test_excluded_categories_leave_the_rate_and_rho_and_appear_in_their_column():
    scs = scenarios(synthetic_suite(2, 0))
    a, b = scs[0].id, scs[1].id
    pilot = ([_rec(a, i, "CORRECT") for i in range(3)] + [_rec(a, 3, "WRONG_TOOL")]
             + [_rec(a, 4, "API_ERROR"), _rec(a, 5, "REFUSED"), _rec(a, 6, "TRUNCATED")]
             + [_rec(b, i, "WRONG_TOOL") for i in range(3)] + [_rec(b, 3, "CORRECT")])
    row = baseline_table(pilot, scs, example_prereg())[0]
    assert (row["n"], row["correct"], row["rate"], row["excluded"]) == (4, 3, 0.75, 3)
    assert "| 3 / 4 | 0.75 |" in table_markdown(baseline_table(pilot, scs, example_prereg()))
    # the three excluded runs of `a` do not enter rho: a is [1,1,1,0], b is [0,0,0,1]
    assert rho(pilot, {a, b}) == pytest.approx(0.2)


def test_rho_is_not_degenerate_for_a_mixed_pilot():
    scs = scenarios(synthetic_suite(3, 0))
    recs = _pilot({scs[0].id: 0.8, scs[1].id: 0.2, scs[2].id: 0.5})
    assert 0.0 < rho(recs, {s.id for s in scs}) < 1.0


def test_selection_refuses_unknown_scenarios_and_repeated_blocks():
    scs = scenarios(synthetic_suite(1, 0))
    with pytest.raises(ValueError, match="not among the candidates"):
        baseline_table([_rec("nope", 0, "CORRECT")], scs, example_prereg())
    twice = [_rec(scs[0].id, 0, "CORRECT"), _rec(scs[0].id, 0, "WRONG_TOOL")]
    with pytest.raises(ValueError, match="appears twice"):
        baseline_table(twice, scs, example_prereg())


def test_a_candidate_below_the_graded_minimum_is_excluded_whatever_its_rate():
    scs = scenarios(synthetic_suite(1, 0))
    sid = scs[0].id
    pilot = [_rec(sid, 0, "CORRECT"), _rec(sid, 1, "WRONG_TOOL")] + [
        _rec(sid, b, "API_ERROR") for b in range(2, 10)]
    kept = baseline_table(pilot, scs, example_prereg(min_graded_per_cell=2, retry_cap=2))[0]
    assert kept["include"] and kept["reason"] == "inside the band"
    dropped = baseline_table(pilot, scs, example_prereg(min_graded_per_cell=3, retry_cap=2))[0]
    assert not dropped["include"] and dropped["reason"] == "too few graded repetitions"
    assert dropped["n"] == 2 and dropped["excluded"] == 8


def test_the_budget_table_total_label_can_be_set_and_defaults_to_total():
    lines = [Line("a", 10, 0.5)]
    assert "| **total** |" in table(lines)
    assert "| **total, plan 3's phases only** |" in table(
        lines, total_label="total, plan 3's phases only")


def _fake_pilot(scs, cell_usd, recovery_usd, slice_usd_by_cell):
    baseline = []
    for s in scs:
        baseline += [_rec(s.id, b, "CORRECT" if b % 2 else "WRONG_TOOL") for b in range(4)]
    cells = [SimpleNamespace(cell=c.name, cost_usd=cell_usd[c.name], usage=None)
             for c in CELLS for _ in range(2)]
    recovery = [SimpleNamespace(cost_usd=recovery_usd, settings=_PRIMARY.to_dict(), turns=[],
                                run_index=0)]
    slice_recs = [SimpleNamespace(cell=cell, cost_usd=usd, usage=None)
                  for cell, usd in slice_usd_by_cell for _ in range(2)]
    return {"baseline": baseline, "cells": cells, "recovery": recovery,
            "slice": {"gpt-5.4-nano-2026-03-17": slice_recs}}


def test_step_two_prices_the_recovery_and_slice_at_the_dearest_cell():
    scs = scenarios(synthetic_suite(24, 0))
    prereg = example_prereg()
    cell_usd = {c.name: 0.01 * (i + 1) for i, c in enumerate(CELLS)}  # dearest 0.08
    pilot = _fake_pilot(scs, cell_usd, 0.02, [("low-terse-loose", 0.1), ("high-rich-strict", 0.3)])
    out = step2_proposal(pilot, scs, prereg)
    base = cell_usd[prereg.baseline_cell]
    assert out["usd_per_recovery_conversation_baseline"] == pytest.approx(0.02)
    assert out["usd_per_recovery_conversation"] == pytest.approx(0.02 * 0.08 / base)
    s, n = len(out["included"]), out["reps"]
    n_rec = out["recovery_scenarios"]
    assert n_rec == 8  # every third synthetic call scenario carries the recovery block
    expected = (8 * s * n * sum(cell_usd.values()) / 8
                + 4 * n_rec * n * 0.02 * 0.08 / base
                + s * n * 0.08
                + 2 * s * n * 0.3)  # the slice model's dearest cell, not its overall mean 0.2
    assert out["estimate_usd"] == pytest.approx(expected)
    assert "total, plan 3's phases only (the pilot is sunk)" in out["budget_table"]


def test_step_two_names_an_empty_recovery_store_and_a_model_with_no_slice_records():
    scs = scenarios(synthetic_suite(24, 0))
    cell_usd = {c.name: 0.01 for c in CELLS}
    pilot = _fake_pilot(scs, cell_usd, 0.02, [("low-terse-loose", 0.1)])
    with pytest.raises(ValueError, match="recovery store is empty"):
        step2_proposal({**pilot, "recovery": []}, scs, example_prereg())
    with pytest.raises(ValueError, match="slice model gpt-5.4-nano"):
        step2_proposal({**pilot, "slice": {"gpt-5.4-nano-2026-03-17": []}}, scs, example_prereg())
