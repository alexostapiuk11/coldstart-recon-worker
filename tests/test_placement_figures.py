"""Artifact 4's four figures on a complete synthetic analysis: every text
legible at phone width and on the canvas, N stated, and refusals instead of
charts that compare fewer things than they appear to.

These are layer-2 checks (geometry), not the visual check. The visual check is
a human looking at each render at full size and at 375 px, which plan 3's
figure task and its publication task both require."""

import copy

import matplotlib
import matplotlib.pyplot as plt
import pytest
from a4_analysis_example import example_analysis

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from placement.figures import FIGURES

NAMES = sorted(FIGURES)


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    return example_analysis(tmp_path_factory.mktemp("a4"))


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _draw(name, analysis, tmp_path):
    return FIGURES[name](analysis, tmp_path / f"{name}.png", return_figure=True)


def _visible_texts(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    artists = list(fig.texts)
    for ax in fig.axes:
        artists += [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]
        # Only ticks inside the view limits: an axis keeps labels for ticks it
        # never paints, and they report extents off the canvas (artifact 2's
        # tests/test_a2_figures.py met the same trap).
        for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            lo, hi = sorted(lim)
            artists += [tick.label1 for tick in axis.get_major_ticks() if lo <= tick.get_loc() <= hi]
        legend = ax.get_legend()
        if legend:
            artists += legend.get_texts()
    for legend in fig.legends:
        artists += legend.get_texts()
    return [(t, t.get_window_extent(renderer)) for t in artists
            if t.get_text().strip() and t.get_visible()]


@pytest.mark.parametrize("name", NAMES)
def test_the_figure_renders_to_a_png(name, analysis, tmp_path):
    out = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and out.stat().st_size > 20_000


@pytest.mark.parametrize("name", NAMES)
def test_every_text_clears_the_phone_floor(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    width_in = fig.get_size_inches()[0]
    for text in fig.findobj(match=matplotlib.text.Text):
        if text.get_text().strip():
            px = text.get_fontsize() * PHONE_WIDTH_PX / (72 * width_in)
            assert px >= MIN_PHONE_TEXT_PX, f"{text.get_text()!r} is {px:.1f}px on a phone"


@pytest.mark.parametrize("name", NAMES)
def test_no_text_runs_off_the_canvas(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    width_px, height_px = fig.get_size_inches() * fig.dpi
    for text, box in _visible_texts(fig):
        assert box.x0 >= -1 and box.x1 <= width_px + 1, f"{text.get_text()!r} is cut off sideways"
        assert box.y0 >= -1 and box.y1 <= height_px + 1, f"{text.get_text()!r} is cut off vertically"


@pytest.mark.parametrize("name", NAMES)
def test_n_is_stated(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    texts = " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))
    assert "n=" in texts or "n>=" in texts or "runs" in texts


def test_the_crossover_figure_marks_the_validated_point_and_dominated_strategies(analysis, tmp_path):
    fig = _draw("crossover", analysis, tmp_path)
    texts = [t.get_text() for t in fig.findobj(match=matplotlib.text.Text)]
    assert any("validated" in t for t in texts) and any("dominated" in t for t in texts)


def test_the_deciles_figure_shows_swap_sized_on_the_aggregate(analysis, tmp_path):
    fig = _draw("deciles", analysis, tmp_path)
    labels = [t.get_text() for ax in fig.axes for t in ax.get_legend().get_texts()]
    assert any("sized on aggregate" in label for label in labels)


def test_a_missing_regime_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["regimes"]["bursty"]
    for name in ("crossover", "deciles"):
        with pytest.raises(ValueError, match="regime"):
            FIGURES[name](broken, tmp_path / "x.png")


def test_a_regime_not_evaluable_at_the_reference_is_said_not_raised(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    for p in broken["regimes"]["spread"]["points"]:
        if p["s"] == broken["reference"]["s"]:
            p.clear()
            p.update({"regime": "spread", "s": broken["reference"]["s"], "window_s": 1.0,
                      "evaluable": False})
    fig = FIGURES["deciles"](broken, tmp_path / "x.png", return_figure=True)
    texts = [t.get_text() for t in fig.findobj(match=matplotlib.text.Text)]
    assert any("not evaluable here" in t for t in texts)


def test_figure_4_states_the_median_swap_beside_the_summed_stages(analysis, tmp_path):
    fig = FIGURES["swap_stages"](analysis, tmp_path / "x.png", return_figure=True)
    swap = analysis["inputs"]["stages"]["stages"]["swap_s"]
    texts = " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))
    assert f"Median swap: {swap:.1f} s" in texts and "Σ" in texts


def test_a_missing_stage_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["inputs"]["stages"]["stages"]["release_s"]
    with pytest.raises(ValueError, match="swap stage"):
        FIGURES["swap_stages"](broken, tmp_path / "x.png")


def test_a_surface_cell_without_its_summary_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["inputs"]["cells"]["pair:o8:n16"]
    with pytest.raises(ValueError, match="no summary"):
        FIGURES["interference"](broken, tmp_path / "x.png")


def test_the_render_script_writes_each_figure_and_its_phone_copy(analysis, tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    from matplotlib.image import imread

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("render", repo / "scripts" / "a4_render_figures.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(analysis))
    written = script.main(["--analysis", str(path), "--out", str(tmp_path / "figs")])
    assert len(written) == 8
    for name in NAMES:
        assert imread(tmp_path / "figs" / f"{name}-phone.png").shape[1] == PHONE_WIDTH_PX
    # Deterministic: a second render is byte-identical, which the drift test
    # added at publication relies on.
    again = script.main(["--analysis", str(path), "--out", str(tmp_path / "again")])
    assert [p.read_bytes() for p in written] == [p.read_bytes() for p in again]
