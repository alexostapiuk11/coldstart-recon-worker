"""Artifact 4's model class and validation outcome travel with its costs.

Artifact 4's cost file gained two top-level keys at its d7cf0c3, `model` and
`validation`, because the simulator behind the dedicated and swapped costs
failed its pre-registered validation. The analysis copies them, unchanged and
underived, into `a4_context`; the cost figure says so under its axis. An old
file without them must analyse and draw exactly as before."""

import copy
import json

import matplotlib.text
import pytest

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora import figures
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint
from tests.conftest import example_prereg

A4_OLD = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}

# Artifact 4's d7cf0c3, verbatim.
MODEL = {"id": "Qwen/Qwen3-1.7B", "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"}
VALIDATION = {
    "outcome": "failed",
    "latency": {
        "outcome": "failed",
        "detail": "10 of 13 judged bins miss, more than the 0.5 allowed; largest miss 67.8 s; "
                  "16 excluded (0 unstable); 1 both censored (agreement, not judged)",
        "compared": 13,
        "agreeing": 3,
        "max_miss_seconds": 67.78256704869813,
    },
    "swaps": {"predicted": 11, "real": [10, 10, 10], "agree": True},
    "held_out_cells": {"passed": 1, "total": 2},
    "note": "Validation outcome: failed. 10 of 13 judged bins missed the band of three real "
            "repeats (largest miss 67.8 s); the swap count agreed (11 predicted, real "
            "[10, 10, 10]). 1 of 2 held-out interference cells passed. These costs come from "
            "that simulator; see docs/post-a4.md and docs/findings-a4-validation-swap-cost.md.",
}
A4_NEW = {**A4_OLD, "model": MODEL, "validation": VALIDATION}

EXPECTED_CONTEXT = {
    "model": MODEL,
    "validation": {
        "outcome": "failed",
        "latency": {"compared": 13, "agreeing": 3},
        "held_out_cells": {"passed": 1, "total": 2},
        "swaps": {"predicted": 11, "real": [10, 10, 10], "agree": True},
        "note": VALIDATION["note"],
    },
}


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    figures.plt.close("all")


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    tmp = tmp_path_factory.mktemp("a4ctx")
    out = {}
    for name, schedule in (("campaign", campaign_schedule(prereg)), ("gate", gate_schedule(prereg))):
        store = JsonlStore(tmp / f"{name}.jsonl", InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=2).run), store, prereg)
        out[name] = store.read_all()
    return prereg, out


def _analyse(stores, a4):
    prereg, s = stores
    return analyse(s["campaign"], s["gate"], prereg, a4=a4, iterations=200)


@pytest.fixture(scope="module")
def old(stores):
    return _analyse(stores, copy.deepcopy(A4_OLD))


@pytest.fixture(scope="module")
def new(stores):
    return _analyse(stores, copy.deepcopy(A4_NEW))


# The analysis


def test_the_analysis_carries_artifact_4s_model_and_validation_unchanged(new):
    assert new["a4_context"] == EXPECTED_CONTEXT


def test_the_old_file_shape_has_no_a4_context(old):
    assert "a4_context" not in old


def test_no_artifact_4_file_has_no_a4_context(stores):
    assert "a4_context" not in _analyse(stores, None)


def test_half_a_context_is_refused(stores):
    for key in ("model", "validation"):
        partial = {k: v for k, v in copy.deepcopy(A4_NEW).items() if k != key}
        with pytest.raises(ValueError, match="model.*validation"):
            _analyse(stores, partial)


def test_nothing_else_in_the_analysis_changes(old, new):
    assert {k: v for k, v in new.items() if k != "a4_context"} == old


def test_the_context_is_json_serialisable_and_deterministic(stores, new):
    again = _analyse(stores, copy.deepcopy(A4_NEW))
    text = json.dumps(new, indent=1, sort_keys=True)
    assert text == json.dumps(again, indent=1, sort_keys=True)
    assert json.loads(text)["a4_context"] == EXPECTED_CONTEXT


def test_the_context_is_a_copy_not_the_callers_dict(stores):
    a4 = copy.deepcopy(A4_NEW)
    result = _analyse(stores, a4)
    a4["validation"]["swaps"]["real"].append(99)
    assert result["a4_context"]["validation"]["swaps"]["real"] == [10, 10, 10]


# The cost figure


def _texts(fig) -> list[str]:
    return [t.get_text() for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip()]


def _note(fig) -> str:
    return "\n".join(t.get_text() for t in fig.texts)


def test_the_figure_renders_both_ways(old, new, tmp_path):
    for name, analysis in (("old", old), ("new", new)):
        figures.cost_per_tenant(analysis, tmp_path / f"{name}.png")
        assert (tmp_path / f"{name}.png").stat().st_size > 10_000


def test_the_miss_count_is_derived_and_is_the_number_on_the_figure(new, tmp_path):
    context = new["a4_context"]
    missed = figures.a4_bins_missed(context)
    latency = context["validation"]["latency"]
    assert missed == latency["compared"] - latency["agreeing"] == 10
    note = _note(figures.cost_per_tenant(new, tmp_path / "c.png"))
    assert f"({missed} of {latency['compared']} bins missed)" in note
    assert "(10 of 13 bins missed)" in note


def test_the_note_names_both_model_classes_and_says_nothing_is_validated(new, tmp_path):
    note = _note(figures.cost_per_tenant(new, tmp_path / "c.png"))
    assert "dedicated and swapped: artifact 4's simulator, Qwen3-1.7B; adapter: Qwen3-4B" in note
    assert "failed its validation" in note
    assert "none of its numbers is validated" in note


def test_the_existing_note_lines_are_kept(old, new, tmp_path):
    before = _note(figures.cost_per_tenant(old, tmp_path / "a.png"))
    after = _note(figures.cost_per_tenant(new, tmp_path / "b.png"))
    assert after.startswith(before + "\n")


def test_the_old_shape_gets_no_new_note(old, tmp_path):
    note = _note(figures.cost_per_tenant(old, tmp_path / "a.png"))
    assert "simulator" not in note and "validat" not in note


def test_no_bar_is_marked_validated_or_unvalidated(new, tmp_path):
    fig = figures.cost_per_tenant(new, tmp_path / "c.png")
    ax = fig.axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ["dedicated", "swapped", "adapter"]
    assert not any("validat" in t.get_text() for t in ax.texts)


def test_an_outcome_the_note_was_not_written_for_is_refused(new, tmp_path):
    passed = copy.deepcopy(new)
    passed["a4_context"]["validation"]["outcome"] = "passed"
    with pytest.raises(ValueError, match="outcome"):
        figures.cost_per_tenant(passed, tmp_path / "c.png")


def test_every_text_is_legible_at_phone_width(new, tmp_path):
    fig = figures.cost_per_tenant(new, tmp_path / "c.png")
    width_in = fig.get_size_inches()[0]
    for text in fig.findobj(matplotlib.text.Text):
        if text.get_text().strip():
            px = text.get_fontsize() * PHONE_WIDTH_PX / (72 * width_in)
            assert px >= MIN_PHONE_TEXT_PX, f"{text.get_text()!r} is {px:.2f}px on a phone"


def _boxes(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    artists = list(fig.texts) + [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]
    for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
        lo, hi = sorted(lim)
        artists += [tick.label1 for tick in axis.get_major_ticks() if lo <= tick.get_loc() <= hi]
    return [(t, t.get_window_extent(renderer)) for t in artists if t.get_text().strip()]


def test_no_text_runs_off_the_canvas(new, tmp_path):
    fig = figures.cost_per_tenant(new, tmp_path / "c.png")
    width_px, height_px = fig.get_size_inches() * fig.dpi
    for text, box in _boxes(fig):
        assert box.x0 >= -1 and box.x1 <= width_px + 1, f"{text.get_text()!r} is cut off sideways"
        assert box.y0 >= -1 and box.y1 <= height_px + 1, f"{text.get_text()!r} is cut off vertically"


def test_the_note_overlaps_nothing_on_the_axes(new, tmp_path):
    fig = figures.cost_per_tenant(new, tmp_path / "c.png")
    boxes = _boxes(fig)
    notes = [box for t, box in boxes if t in fig.texts]
    others = [(t, box) for t, box in boxes if t not in fig.texts]
    axes_box = fig.axes[0].get_window_extent()
    for note in notes:
        assert not note.overlaps(axes_box)
        for t, box in others:
            assert not note.overlaps(box), f"the note overlaps {t.get_text()!r}"
