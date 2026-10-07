"""The four figures on artifact 4's real analysis (`data/a4/analysis.json`).

`tests/test_placement_figures.py` renders a synthetic analysis, where every
label fits. Real data put labels where the synthetic data did not, and a look at
the first real render found three: a note straddling an axes frame, a legend
sitting on a curve, and a bar label clipped by the canvas edge. These checks are
geometry (layer 2), so they would have failed on those renders; the visual
check is still a person looking at each figure at full size and at 375 px."""

import json
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pytest

from placement.figures import FIGURES

matplotlib.use("Agg")

ANALYSIS = json.loads((Path(__file__).resolve().parents[1] / "data" / "a4" / "analysis.json").read_text())
NAMES = sorted(FIGURES)
MARGIN_PX = 4


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _draw(name, tmp_path):
    fig = FIGURES[name](ANALYSIS, tmp_path / f"{name}.png", return_figure=True)
    fig.canvas.draw()
    return fig, fig.canvas.get_renderer()


def _series(ax):
    """Data points of every plotted series, in display pixels: lines with
    several points, not the reference lines (SLO, validated point, KV full)."""
    out = []
    for line in ax.lines:
        xy = np.column_stack([np.asarray(line.get_xdata(), dtype=float),
                              np.asarray(line.get_ydata(), dtype=float)])
        if len(xy) >= 3 and np.isfinite(xy).all():
            out.append(ax.transData.transform(xy))
    return out


@pytest.mark.parametrize("name", NAMES)
def test_every_text_is_inside_the_canvas_with_a_margin(name, tmp_path):
    fig, renderer = _draw(name, tmp_path)
    width, height = fig.canvas.get_width_height()
    artists = list(fig.texts)
    for ax in fig.axes:
        artists += [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]
        for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            lo, hi = sorted(lim)
            artists += [t.label1 for t in axis.get_major_ticks() if lo <= t.get_loc() <= hi]
        if ax.get_legend():
            artists += ax.get_legend().get_texts()
    for legend in fig.legends:
        artists += legend.get_texts()
    for t in artists:
        if not t.get_text().strip() or not t.get_visible():
            continue
        box = t.get_window_extent(renderer)
        assert box.x0 >= MARGIN_PX and box.y0 >= MARGIN_PX, (name, t.get_text(), box)
        assert box.x1 <= width - MARGIN_PX and box.y1 <= height - MARGIN_PX, (name, t.get_text(), box)


@pytest.mark.parametrize("name", NAMES)
def test_no_legend_sits_on_a_plotted_point(name, tmp_path):
    fig, renderer = _draw(name, tmp_path)
    for ax in fig.axes:
        legend = ax.get_legend()
        if legend is None:
            continue
        box = legend.get_window_extent(renderer)
        for points in _series(ax):
            inside = [p for p in points if box.x0 <= p[0] <= box.x1 and box.y0 <= p[1] <= box.y1]
            assert not inside, (name, "a series passes through the legend", inside[:2])


@pytest.mark.parametrize("name", NAMES)
def test_no_note_sits_on_a_plotted_point_or_astride_the_frame(name, tmp_path):
    fig, renderer = _draw(name, tmp_path)
    for ax in fig.axes:
        frame = ax.get_window_extent(renderer)
        for text in ax.texts:
            if not text.get_text().strip():
                continue
            box = text.get_window_extent(renderer)
            crosses = (box.x0 < frame.x0 < box.x1) or (box.x0 < frame.x1 < box.x1) \
                or (box.y0 < frame.y0 < box.y1) or (box.y0 < frame.y1 < box.y1)
            assert not crosses, (name, text.get_text(), "straddles an axes frame")
            for points in _series(ax):
                inside = [p for p in points if box.x0 <= p[0] <= box.x1 and box.y0 <= p[1] <= box.y1]
                assert not inside, (name, text.get_text(), "a series passes through the note")


@pytest.mark.parametrize("name", NAMES)
def test_no_note_runs_into_a_vertical_reference_line(name, tmp_path):
    """The validated-point line and the KV-full lines are vertical; a note that
    touches one reads as part of it."""
    fig, renderer = _draw(name, tmp_path)
    for ax in fig.axes:
        verticals = []
        for line in ax.lines:
            xs = np.asarray(line.get_xdata(), dtype=float)
            if len(xs) == 2 and xs[0] == xs[1]:
                verticals.append(ax.transData.transform([[xs[0], 0.0]])[0][0])
        for text in ax.texts:
            if not text.get_text().strip():
                continue
            box = text.get_window_extent(renderer)
            for x in verticals:
                assert not (box.x0 - 2 <= x <= box.x1 + 2), (name, text.get_text(), "touches a vertical line")
