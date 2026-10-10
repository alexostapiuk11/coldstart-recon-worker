"""H1-H5 on small synthetic data where the true effect is known by construction:
each hypothesis is rejected when its effect is clearly in the predicted
direction and has a large p when it is clearly the opposite way. A hypothesis
that reads the wrong tail of the bootstrap fails the second kind of test, or
the first (H2 once could never be rejected)."""

from types import SimpleNamespace

import pytest

from tests.a3_examples import example_prereg
from toolcall import hypotheses
from toolcall.formulation import CELLS
from toolcall.hypotheses import _h1, _h2, _h3, _h4, _h5, evaluate

N = 24  # scenarios: above the bootstrap floor of 20
REPS = 4
PREREG = example_prereg(iterations=300)
SCENARIOS = [f"s{i:02d}" for i in range(N)]


def fails(k, cat="WRONG_TOOL"):
    return [cat] * k + ["CORRECT"] * (REPS - k)


def build(fn):
    """{scenario: {cell: [(block, category)]}} from fn(cell, i) -> categories."""
    return {sid: {cell.name: list(enumerate(fn(cell, i))) for cell in CELLS}
            for i, sid in enumerate(SCENARIOS)}


def test_h1_is_rejected_for_a_negative_interaction_and_not_for_a_positive_one():
    def make(hot_richness):
        """Failures are high only at high count with `hot_richness` descriptions."""
        def fn(cell, i):
            hot = cell.count == "high" and cell.richness == hot_richness
            return fails(3 + i % 2 if hot else i % 2)
        return build(fn)

    good = _h1(make("terse"), SCENARIOS, PREREG)  # richness helps at high count only
    bad = _h1(make("rich"), SCENARIOS, PREREG)  # richness hurts at high count only
    assert good["point"] < 0 < bad["point"]
    assert good["p"] == good["p_ge_0"] < 0.01
    assert bad["p"] > 0.9


def test_h2_reads_the_tail_for_its_own_direction_part_one_negative_part_two_flat():
    def make(strict_helps):
        def fn(cell, i):
            helped = (cell.strictness == "strict") == strict_helps
            malformed = i % 2 if helped else 3
            return (["MALFORMED"] * malformed + ["WRONG_TOOL"] * (i % 2)
                    + ["CORRECT"] * (REPS - malformed - i % 2))
        return build(fn)

    good = _h2(make(True), SCENARIOS, PREREG)
    bad = _h2(make(False), SCENARIOS, PREREG)
    assert good["point"] < 0 < bad["point"]
    assert good["p"] == good["p_ge_0"] and good["p"] < 0.01 and good["p_le_0"] > 0.9
    assert bad["p"] > 0.9
    assert good["equivalence"]["passes"]  # strictness leaves WRONG_TOOL exactly alone


def test_h3_is_rejected_when_count_raises_wrong_tool_and_not_when_it_lowers_it():
    def make(count_raises):
        def fn(cell, i):
            return fails(3 + i % 2 if (cell.count == "high") == count_raises else i % 2)
        return build(fn)

    good = _h3(make(True), SCENARIOS, PREREG)
    bad = _h3(make(False), SCENARIOS, PREREG)
    assert good["point"] > 0 > bad["point"]
    assert good["p"] < 0.01
    assert bad["p"] > 0.9
    assert "p_le_0" not in good and "p_ge_0" not in good  # they belong to parts["count"]
    assert set(good["parts"]) == {"count", "richness", "strictness"}


def test_h3_p_is_the_largest_of_its_three_parts():
    """Count raises WRONG_TOOL by 0.25, but richness lowers it by 0.5: the count
    part alone would reject, the margin over richness does not."""
    def fn(cell, i):
        return fails(2 + (cell.count == "high") - 2 * (cell.richness == "rich") + 0 * i)
    h3 = _h3(build(fn), SCENARIOS, PREREG)
    ps = {k: part["p_le_0"] for k, part in h3["parts"].items()}
    assert h3["p"] == max(ps.values())
    assert ps["count"] < 0.01 < ps["richness"] and h3["p"] == ps["richness"] > 0.9


def _recovery(rates):
    """rates: {(scenario index, cell, fmt): [identical_retry, ...]}."""
    return [SimpleNamespace(scenario_id=SCENARIOS[i], cell=cell, fmt=fmt, excluded=None,
                            injected=True, error_kind="invalid_parameter",
                            identical_retry=v)
            for (i, cell, fmt), vs in rates.items() for v in vs]


def _both(opaque, actionable, n=N):
    return {(i, c, f): v for i in range(n) for c in ("cA", "cB")
            for f, v in (("opaque", opaque), ("actionable", actionable))}


def test_h4_is_rejected_for_more_opaque_retries_and_not_for_fewer():
    good = _h4(_recovery(_both([True, True], [False, False])), PREREG)
    bad = _h4(_recovery(_both([True, False], [True, True])), PREREG)  # opaque 0.5, actionable 1.0
    assert good["testable"] and good["point"] > 0 and good["p"] == good["p_le_0"] < 0.01
    assert bad["testable"] and bad["point"] < 0 and bad["p"] > 0.9


def test_h4_is_not_testable_with_too_few_scenarios_or_an_opaque_rate_under_the_floor():
    few = _h4(_recovery(_both([True], [False], n=10)), PREREG)
    assert few["testable"] is False and "bootstrap floor" in few["reason"] and "p" not in few
    low = _h4(_recovery(_both([False, False], [False, False])), PREREG)
    assert low["testable"] is False and "below the floor" in low["reason"]
    assert low["opaque_rate"] == 0.0


def test_h4_compares_the_two_formats_only_on_cells_where_both_ran():
    """Opaque ran in cell cA only for scenario i (always identical retries) and
    in both cells otherwise; the cA-only cell must not enter the comparison."""
    rates = {}
    for i in range(N):
        rates[(i, "cA", "opaque")] = [True]
        rates[(i, "cB", "opaque")] = [False]
        rates[(i, "cB", "actionable")] = [False]
    h4 = _h4(_recovery(rates), PREREG)
    assert h4["opaque_rate"] == 0.0 and h4["n_scenarios"] == N  # not 0.5
    # A scenario with no cell holding both formats is not a unit at all.
    del rates[(0, "cB", "actionable")]
    assert _h4(_recovery(rates), PREREG)["n_scenarios"] == N - 1


def _h5_data(shift):
    """Failures sit at blocks 0..k-1 with k in {2, 4}, which puts the same share
    in the even and the odd half: the A/A contrast is exactly 0. `shift(i)` is
    +1 when high count fails more for scenario i (rate +0.5) and -1 when less."""
    def fn(cell, i):
        return fails(4 if (cell.count == "high") == (shift(i) > 0) else 2)
    return build(fn)


def test_h5_is_rejected_for_a_real_count_effect_and_not_for_one_that_straddles_zero():
    real = _h5(_h5_data(lambda i: 1), SCENARIOS, PREREG)
    assert real["testable"] and real["count_effect"]["point"] > 0
    assert real["p"] < 0.05
    # Half the scenarios get a positive count effect, half a negative one: the
    # mean is 0 and its interval straddles zero; the A/A contrast is exactly 0, so
    # |t| - |a| is positive on almost every draw and alone would "reject".
    null = _h5(_h5_data(lambda i: 1 if i % 2 else -1), SCENARIOS, PREREG)
    assert null["count_effect"]["point"] == pytest.approx(0.0)
    assert null["count_effect"]["lo"] < 0 < null["count_effect"]["hi"]
    assert null["parts"]["abs_count_minus_abs_aa"]["p"] < 0.5
    assert null["parts"]["count_effect_nonzero"]["p"] > 0.9
    assert null["p"] == max(part["p"] for part in null["parts"].values()) > 0.9


def _stub_hypotheses(monkeypatch, ps, h2_equivalent=True, h4_testable=True):
    def fake(p, **extra):
        return lambda *a, **k: {"p": p, **extra}
    monkeypatch.setattr(hypotheses, "_h1", fake(ps["H1"]))
    monkeypatch.setattr(hypotheses, "_h2", fake(ps["H2"], equivalence={"passes": h2_equivalent}))
    monkeypatch.setattr(hypotheses, "_h3", fake(ps["H3"]))
    monkeypatch.setattr(hypotheses, "_h4", fake(ps["H4"], testable=h4_testable))
    monkeypatch.setattr(hypotheses, "_h5", fake(ps["H5"]))


def test_holm_can_withhold_a_verdict_from_a_hypothesis_with_p_below_alpha(monkeypatch):
    # alpha 0.05, five tests: the smallest p must be <= 0.01. H1 has 0.04 < alpha
    # alone, but nothing clears 0.05/5, so Holm rejects nothing.
    _stub_hypotheses(monkeypatch, {"H1": 0.04, "H2": 0.5, "H3": 0.6, "H4": 0.7, "H5": 0.8})
    out = evaluate({}, [], PREREG)
    assert out["H1"]["p"] < PREREG.alpha
    assert out["H1"]["holm_rejects"] is False and out["H1"]["verdict"] == "not supported"
    # The same p with a much smaller one beside it: Holm moves on and rejects H1 too.
    _stub_hypotheses(monkeypatch, {"H1": 0.012, "H2": 0.001, "H3": 0.6, "H4": 0.7, "H5": 0.8})
    assert evaluate({}, [], PREREG)["H1"]["verdict"] == "supported"


def test_h2_names_the_part_that_failed(monkeypatch):
    ps = {"H1": 0.5, "H2": 0.001, "H3": 0.6, "H4": 0.7, "H5": 0.8}
    _stub_hypotheses(monkeypatch, ps)
    h2 = evaluate({}, [], PREREG)["H2"]
    assert h2["verdict"] == "supported" and h2["failed_part"] is None
    _stub_hypotheses(monkeypatch, ps, h2_equivalent=False)
    h2 = evaluate({}, [], PREREG)["H2"]
    assert h2["verdict"] == "not supported" and h2["failed_part"] == "equivalence"
    _stub_hypotheses(monkeypatch, {**ps, "H2": 0.4})
    h2 = evaluate({}, [], PREREG)["H2"]
    assert h2["verdict"] == "not supported" and h2["failed_part"] == "difference"


def test_a_hypothesis_that_is_not_testable_stays_out_of_holm(monkeypatch):
    _stub_hypotheses(monkeypatch, {"H1": 0.012, "H2": 0.5, "H3": 0.6, "H4": 0.001, "H5": 0.8},
                     h4_testable=False)
    out = evaluate({}, [], PREREG)
    assert out["H4"]["verdict"] == "not testable" and "holm_rejects" not in out["H4"]
    # Four tests now: H1's 0.012 <= 0.05/4 is rejected, which five would not allow.
    assert out["H1"]["verdict"] == "supported"
