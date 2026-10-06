"""The post's four figures: content, legibility at phone width, nothing off canvas."""

import json
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
from autoscale import figures_a2_post as fp
from harness.figure_guards import MIN_PHONE_TEXT_PX

A = json.loads((Path(__file__).resolve().parents[1] / "data" / "a2" / "post-analysis.json")
               .read_text())


def _texts(fig):
    return [t.get_text() for t in fig.findobj(matplotlib.text.Text) if t.get_text().strip()]


def _legible_and_on_canvas(fig):
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    renderer = fig.canvas.get_renderer()
    for t in fig.findobj(matplotlib.text.Text):
        if t.get_text().strip() and t.get_visible():
            box = t.get_window_extent(renderer)
            assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, \
                t.get_text()


def _gids(fig):
    return [a.get_gid() for a in fig.findobj() if getattr(a, "get_gid", lambda: None)()]


def test_attempts_draws_both_panels_with_their_verdicts(tmp_path):
    fig = fp.validation_attempts(A, tmp_path / "a.png", return_figure=True)
    assert len(fig.axes) == 2
    assert _gids(fig).count("residual_series") == 6 and _gids(fig).count("zero") == 2
    text = " ".join(_texts(fig))
    assert "34 of 37" in text and "37 of 37" in text and "MEASURED" in text
    lo0, hi0 = fig.axes[0].get_ylim()
    assert lo0 == pytest.approx(-hi0) and fig.axes[1].get_ylim() == (lo0, hi0)
    _legible_and_on_canvas(fig)


def test_load_balancer_shows_the_ceiling_and_the_fill_first_routing(tmp_path):
    fig = fp.load_balancer(A, tmp_path / "lb.png", return_figure=True)
    assert len(fig.axes) == 2
    assert {"delivered_scaler_4", "delivered_scaler_128", "offered_equals_delivered",
            "cap_128"} <= set(_gids(fig))
    assert sum(1 for g in _gids(fig) if g.startswith("worker_bar")) >= 8
    assert "MEASURED" in " ".join(_texts(fig))
    _legible_and_on_canvas(fig)
