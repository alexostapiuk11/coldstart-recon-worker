"""The four figures, drawn from a stub analysis: they render, every text is
legible at phone width, N is on every figure, value axes start at zero, and an
empty input is refused. Looking at them is a separate, manual step (plan 1
Task 15); these tests guard what can be checked without eyes."""

import copy

import matplotlib.pyplot as plt
import matplotlib.text
import pytest

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.analysis import analyse
from toolcall.figures import FIGURES, WIDTH_IN
from toolcall.formulation import CELLS, parse_cell
from toolcall.providers import ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fig")
    lib, scs = library(), scenarios(synthetic_suite(60, 6))
    prereg = example_prereg(included=tuple(s.id for s in scs), reps=6, recovery_reps=5,
                            slice_reps=5, approved_usd=1.0, iterations=200)
    client = ScriptedClient(prereg.primary, StubModel(lib, scs, seed=2))
    calls = JsonlStore(tmp / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, scs, 6, 1), client, scs, lib, calls,
                         phase="campaign")
    rec = [s for s in scs if s.recovery]
    recs = JsonlStore(tmp / "r.jsonl", RecoveryRecord)
    campaign.recovery_runs(campaign.schedule([parse_cell("low-terse-loose")], rec, 5, 2,
                                             formats=["actionable", "opaque"]),
                           client, rec, lib, recs)
    return analyse(calls.read_all(), recs.read_all(), scs, prereg)


@pytest.mark.parametrize("name", list(FIGURES))
def test_every_figure_writes_a_file(analysis, tmp_path, name):
    FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert (tmp_path / f"{name}.png").stat().st_size > 10_000


@pytest.mark.parametrize("name", list(FIGURES))
def test_every_text_element_is_legible_at_phone_width(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip():
            px = t.get_fontsize() * PHONE_WIDTH_PX / (72 * WIDTH_IN)
            assert px >= MIN_PHONE_TEXT_PX, (name, t.get_text(), px)


@pytest.mark.parametrize("name", list(FIGURES))
def test_the_sample_size_is_on_the_figure(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert "scenarios" in fig._suptitle.get_text() or "units" in fig._suptitle.get_text()


@pytest.mark.parametrize("name", ["interaction", "flakiness", "identical_retry"])
def test_value_axes_start_at_zero(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert fig.axes[0].get_ylim()[0] == 0


def test_empty_input_is_refused(analysis, tmp_path):
    empty = {**analysis, "recovery": {}}
    with pytest.raises(ValueError, match="empty"):
        FIGURES["identical_retry"](empty, tmp_path / "x.png")


@pytest.mark.parametrize("name", ["taxonomy", "interaction"])
def test_the_suptitle_states_S_and_N(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    title = fig._suptitle.get_text()
    assert f"{analysis['S']} scenarios" in title
    assert f"up to {analysis['N']} repetitions" in title


def test_taxonomy_bars_stack_to_one_in_every_cell(analysis, tmp_path):
    fig = FIGURES["taxonomy"](analysis, tmp_path / "t.png")
    ax = fig.axes[0]
    totals = {}
    for patch in ax.patches:
        totals[patch.get_y()] = totals.get(patch.get_y(), 0.0) + patch.get_width()
    assert len(totals) == len(CELLS)
    for total in totals.values():
        assert abs(total - 1.0) < 1e-9


def test_interaction_point_is_the_difference_in_differences(analysis, tmp_path):
    m = analysis["marginal_count_richness"]
    did = ((m["high-rich"]["point"] - m["high-terse"]["point"])
           - (m["low-rich"]["point"] - m["low-terse"]["point"]))
    h1 = analysis["hypotheses"]["H1"]
    assert h1["point"] == pytest.approx(did, abs=1e-9)
    fig = FIGURES["interaction"](analysis, tmp_path / "i.png")
    assert h1["verdict"] in fig._suptitle.get_text()


def test_interaction_series_are_offset_so_markers_do_not_overlap(analysis, tmp_path):
    fig = FIGURES["interaction"](analysis, tmp_path / "i.png")
    ax = fig.axes[0]
    xs = [[round(float(x), 6) for x in line.get_xdata()] for line in ax.lines]
    assert [-0.03, 0.97] in xs and [0.03, 1.03] in xs
    assert list(ax.get_xticks()) == [0, 1]


def _doctored(analysis):
    a = copy.deepcopy(analysis)
    h1 = a["hypotheses"]["H1"]
    h1["point"] = h1["hi"] + 0.1
    m = a["marginal_count_richness"]["low-terse"]
    m["point"] = m["lo"] - 0.05
    cell = CELLS[0].name
    f = a["cell_rates"]["failure"][cell]
    f["point"] = f["lo"] - 0.05
    for rec in a["recovery"].values():
        ci = rec["identical_retry_persistent"]
        ci["point"] = ci["hi"] + 0.05
    return a


@pytest.mark.parametrize("name", list(FIGURES))
def test_a_point_outside_its_percentile_interval_still_renders(analysis, tmp_path, name):
    FIGURES[name](_doctored(analysis), tmp_path / f"{name}.png")


def test_identical_retry_needs_every_persistent_kind_interval(analysis, tmp_path):
    a = copy.deepcopy(analysis)
    fmt = next(iter(a["recovery"]))
    a["recovery"][fmt]["identical_retry_persistent"] = None
    with pytest.raises(ValueError, match="persistent"):
        FIGURES["identical_retry"](a, tmp_path / "x.png")


def test_identical_retry_labels_each_bar_with_its_own_n(analysis, tmp_path):
    fig = FIGURES["identical_retry"](analysis, tmp_path / "x.png")
    labels = [t.get_text() for t in fig.axes[0].get_xticklabels()]
    for label, fmt in zip(labels, ("actionable", "opaque"), strict=True):
        n = analysis["recovery"][fmt]["identical_retry_persistent"]["n_scenarios"]
        assert label == f"{fmt} error\n{n} scenarios"
    assert f"H4 pairs {analysis['hypotheses']['H4']['n_scenarios']} scenarios" in (
        fig._suptitle.get_text())


def test_flakiness_shows_an_empty_bar_for_a_missing_middle_count(analysis, tmp_path):
    a = copy.deepcopy(analysis)
    a["flakiness"]["distinct_categories_per_unit"] = {"1": 40, "3": 20}
    a["flakiness"]["units"] = 60
    fig = FIGURES["flakiness"](a, tmp_path / "f.png")
    bars = fig.axes[0].patches
    assert [round(b.get_height(), 6) for b in bars] == [round(40 / 60, 6), 0.0, round(20 / 60, 6)]
    assert len(bars) == 3


def test_the_interval_note_follows_the_interval_alpha(analysis, tmp_path):
    a = copy.deepcopy(analysis)
    a["hypotheses"]["H1"]["alpha"] = 0.10
    fig = FIGURES["interaction"](a, tmp_path / "i.png")
    assert "90% interval" in fig._suptitle.get_text()
    assert " pp" in fig._suptitle.get_text()
