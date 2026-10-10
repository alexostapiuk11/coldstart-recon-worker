from dataclasses import fields
from types import SimpleNamespace

import pytest

from tests.a3_examples import example_prereg, scenarios, synthetic_suite
from toolcall.prereg import prereg_table
from toolcall.selection import baseline_table, rho, table_markdown


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
            out.append(SimpleNamespace(scenario_id=sid, cell="low-terse-loose", run_index=b,
                                       grade={"category": "CORRECT" if b < k else "WRONG_TOOL"}))
    return out


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
    bad = [SimpleNamespace(scenario_id=scs[0].id, cell="high-rich-strict", run_index=0,
                           grade={"category": "CORRECT"})]
    with pytest.raises(ValueError, match="not the baseline cell"):
        baseline_table(bad, scs, example_prereg())


def test_rho_from_the_pilot():
    recs = _pilot({"a": 1.0, "b": 0.0, "c": 1.0, "d": 0.0})
    assert rho(recs, {"a", "b", "c", "d"}) == 1.0
