"""The four figures, drawn from a stub analysis: they render, every text is
legible at phone width, N is on every figure, value axes start at zero, and an
empty input is refused. Looking at them is a separate, manual step (plan 1
Task 15); these tests guard what can be checked without eyes."""

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
