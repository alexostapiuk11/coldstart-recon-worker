import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from matplotlib.patches import Rectangle
from PIL import Image

from autoscale.figures import (
    SIGNAL_ORDER,
    UTILIZATION_CENSOR_AT,
    censoring_onset,
    convergence,
    frontiers,
    service_curve,
    validation_overlay,
)
from autoscale.frontier import PolicyPoint
from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.thresholds import THRESHOLDS
from autoscale.validation import RealRun, predicted_trajectory, tolerance_band
from autoscale.validation import validate as _validate
from autoscale.validation_band import BandBin
from autoscale.validation_band import trajectory as _trajectory
from autoscale.validation_schedule import build_schedule as _build_schedule

# `harness.figure_guards` does not exist yet -- the harness extraction that owns
# it has not run. `coldstart.analysis.figures` is where the constant currently
# lives, and it is the SAME constant the artifact-1 figures are held to, which
# is the point: artifact 2's charts are published in the same post, on the same
# phones, and must clear the same calibrated floor. Re-point this import at
# `harness.figure_guards` when the extraction lands.
from coldstart.analysis.figures import MIN_PHONE_TEXT_PX

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _close_figures():
    """`return_figure=True` hands the caller an open pyplot figure, and pyplot
    keeps every one it made until something closes it. Without this the module
    leaks a figure per test and matplotlib starts warning partway through the
    run -- noise that would sit on top of any real warning a later test emits."""
    yield
    plt.close("all")


def _point(cost, p99, signal, n=30):
    """A policy point from repetition samples. `n` copies of one value means the
    median is that value, so every figure fixture in this file draws exactly
    what it drew when PolicyPoint carried scalars -- while clearing the
    bootstrap floor for the interval bands the figures now render."""
    return PolicyPoint(
        cost_samples=(float(cost),) * n,
        p99_samples=(float(p99),) * n,
        signal=signal,
        scale_up_at=1.0,
        scale_down_at=0.1,
    )


def _points(signal, offset):
    return [
        _point(c, c / 10 + offset, signal)
        for c in (100.0, 200.0, 400.0)
    ]


FRONTIERS_A = {s: _points(s, i) for i, s in enumerate(SIGNAL_ORDER, start=1)}
FRONTIERS_C = {s: _points(s, i * 0.3) for i, s in enumerate(SIGNAL_ORDER, start=1)}
# Two signals, on BOTH arms. The arms agree, so the asymmetry guard is silent,
# and until the completeness guard existed this rendered as a three-signal
# comparison showing two -- the same defect `frontiers` has always refused, on
# the figure that carries the artifact's argument.
TWO_SIGNAL_A = {s: _points(s, i) for i, s in enumerate(["queue_depth", "utilization"], start=1)}
TWO_SIGNAL_C = {
    s: _points(s, i * 0.3) for i, s in enumerate(["queue_depth", "utilization"], start=1)
}
ALL_THREE = {s: _points(s, i + 1) for i, s in enumerate(SIGNAL_ORDER)}
SWEPT = {20.0: 6.0, 80.0: 12.0}


def _frontier_shaped(signal, offset, scale=1.0):
    """Points whose p99 FALLS as cost rises, so `pareto_frontier` keeps all of
    them. `_points` above is the plan's fixture and every one of its points but
    the cheapest is dominated, which collapses each frontier to a single marker
    -- fine for the refusal tests, useless for the layout ones: a chart with one
    point per series has short tick labels and no crowding, so it clears every
    legibility and overlap check a real frontier would fail."""
    return [
        _point(c, (9000.0 / c) * scale + offset, signal)
        for c in (120.0, 240.0, 480.0, 960.0, 1680.0)
    ]


WIDE_A = {s: _frontier_shaped(s, 2.0 + i) for i, s in enumerate(SIGNAL_ORDER)}
WIDE_C = {s: _frontier_shaped(s, 0.6 + i * 0.3, 0.5) for i, s in enumerate(SIGNAL_ORDER)}
WIDE_SWEPT = {20.0: 1.1, 40.0: 2.4, 60.0: 3.9, 80.0: 5.2, 120.0: 8.6}

# Ten levels, wide tick labels, the knee mid-range: what a measured sweep looks
# like, rather than the placeholder's seven tidy powers of two.
WIDE_CURVE = ServiceCurve(
    points=[(c, 0.28 + 0.0009 * c * c, min(560.0, 55.0 * c), min(1.0, 0.16 * c ** 0.55))
            for c in (1, 2, 4, 6, 8, 12, 16, 24, 32, 48)],
    measured=True,
)

# Both a minimal chart and a full-width one, because the layout defects this
# module keeps producing are data-dependent: wide tick labels, six overlapping
# series and a five-point sweep are what push text off the canvas, and a fixture
# whose frontiers collapse to one point each would never reproduce them.
LAYOUT_CASES = ["minimal", "realistic"]


def _draw(figure, case, tmp_path):
    if figure == "convergence":
        minimal = case == "minimal"
        args = (FRONTIERS_A, FRONTIERS_C, SWEPT) if minimal else (WIDE_A, WIDE_C, WIDE_SWEPT)
        return convergence(*args, path=tmp_path / "c.png", curve_measured=True, return_figure=True)
    if figure == "service_curve":
        curve = SERVICE_CURVE_PLACEHOLDER if case == "minimal" else WIDE_CURVE
        return service_curve(curve, path=tmp_path / "s.png", return_figure=True)
    data = ALL_THREE if case == "minimal" else WIDE_A
    return frontiers(data, path=tmp_path / "f.png", return_figure=True, context="arm A, step spike")


def _texts(fig):
    return [t.get_text() for t in fig.findobj(match=matplotlib.text.Text) if t.get_text().strip()]


def test_convergence_figure_renders_both_panels(tmp_path):
    out = convergence(FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True)
    assert out.exists()


def test_the_modeled_panel_is_labelled_on_the_chart_itself(tmp_path):
    """Spec section 11: the measured/modeled boundary is drawn on the chart, not
    left to the caption, so a reader who only looks at figures still sees which
    half is measurement."""
    fig = convergence(
        FRONTIERS_A,
        FRONTIERS_C,
        swept=SWEPT,
        path=tmp_path / "c.png", curve_measured=True,
        return_figure=True,
    )
    texts = [t.lower() for t in _texts(fig)]

    assert any("measured" in t for t in texts)
    assert any("modeled" in t for t in texts)


@pytest.mark.parametrize("case", LAYOUT_CASES)
@pytest.mark.parametrize("figure", ["convergence", "frontiers", "service_curve"])
def test_every_text_artist_clears_the_phone_legibility_floor(tmp_path, figure, case):
    fig = _draw(figure, case, tmp_path)
    width_in = fig.get_size_inches()[0]

    for text in fig.findobj(match=matplotlib.text.Text):
        if not text.get_text().strip():
            continue
        px = text.get_fontsize() * 375 / (72 * width_in)
        assert px >= MIN_PHONE_TEXT_PX, f"{text.get_text()!r} renders at {px:.1f}px on a phone"


@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
def test_n_is_stated_on_the_figure(tmp_path, figure):
    if figure == "convergence":
        fig = convergence(
            FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
        )
    else:
        fig = frontiers(ALL_THREE, path=tmp_path / "f.png", return_figure=True)
    texts = " ".join(_texts(fig)).lower()
    assert "n=" in texts


def test_each_panel_says_on_itself_whether_it_is_measurement(tmp_path):
    """Stronger than the spec check above, which the figure passes even with the
    MEASURED strip deleted: "NOT MEASURED" on the other panel contains the
    substring "measured", so a whole-figure text search cannot tell the two
    panels apart. Mutation-tested -- deleting either banner survives the
    whole-figure version of this and fails this one."""
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
    )
    measured, modeled = (
        " | ".join(t.get_text().lower() for t in axis.texts if t.get_text().strip())
        for axis in (fig.axes[0], fig.axes[1])
    )

    assert "measured" in measured
    assert "not measured" not in measured, "the measured panel disclaims itself"
    assert "modeled" in modeled
    assert "not measured" in modeled


def test_each_panel_states_its_own_n(tmp_path):
    """N per panel, not once for the figure. The two panels count different
    things -- swept policies against invented lag values -- so one N covering
    both would be a number that describes neither."""
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
    )
    for axis in (fig.axes[0], fig.axes[1]):
        assert any("n=" in t.get_text().lower() for t in axis.texts)


def test_frontiers_figure_refuses_to_silently_drop_a_signal(tmp_path):
    with pytest.raises(ValueError, match="utilization"):
        frontiers({"queue_depth": _points("queue_depth", 1)}, path=tmp_path / "f.png")


def test_frontiers_figure_renders_with_all_three(tmp_path):
    assert frontiers(ALL_THREE, path=tmp_path / "f.png").exists()


def test_frontiers_figure_draws_a_line_and_a_legend_entry_per_signal(tmp_path):
    """A chart that appears to compare three signals while showing two is a
    misleading chart, not a smaller one. Refusing on a MISSING key is not
    enough -- the drawing loop must actually put all three on the canvas."""
    # WIDE_A, not ALL_THREE: ALL_THREE's frontiers collapse to one point each,
    # which `_band` now draws as an error bar -- several Line2D artists per
    # signal -- so counting lines there measures the error bars, not the
    # series. A multi-point fixture is what this test means by "a line".
    fig = frontiers(WIDE_A, path=tmp_path / "f.png", return_figure=True)
    axis = fig.axes[0]

    assert len(axis.get_lines()) == len(SIGNAL_ORDER)
    legend_texts = {t.get_text() for t in axis.get_legend().get_texts()}
    assert len(legend_texts) == len(SIGNAL_ORDER)


def test_convergence_refuses_an_asymmetric_comparison(tmp_path):
    """Arm A and arm C are the two halves of one comparison. If a signal is
    present on one arm and absent from the other, the chart still draws -- and
    reads as though both arms were compared on the same signals, with the
    missing one invisible rather than reported."""
    with pytest.raises(ValueError, match="different signals"):
        convergence(ALL_THREE, TWO_SIGNAL_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True)


def test_convergence_refuses_two_arms_that_agree_on_an_INCOMPLETE_signal_set(tmp_path):
    """The guarding was backwards. `convergence` checked only that the two arms
    AGREE on their signal set, never that either set is complete -- so a
    two-signal "three-signal comparison" rendered without complaint, on the one
    figure that carries the artifact's argument, while `frontiers` next to it
    refused exactly that input. Agreement is not coverage."""
    with pytest.raises(ValueError, match="in_flight_concurrency"):
        convergence(TWO_SIGNAL_A, TWO_SIGNAL_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True)


def test_convergence_refuses_an_empty_arm(tmp_path):
    with pytest.raises(ValueError, match="no frontiers"):
        convergence({}, {}, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True)


def test_convergence_refuses_an_empty_sweep(tmp_path):
    """An empty swept dict draws an empty modeled panel beside a full measured
    one -- which reads as 'the model showed nothing', not 'nothing was run'."""
    with pytest.raises(ValueError, match="swept"):
        convergence(FRONTIERS_A, FRONTIERS_C, swept={}, path=tmp_path / "c.png", curve_measured=True)


@pytest.mark.parametrize("case", LAYOUT_CASES)
@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
def test_no_axis_is_truncated(tmp_path, figure, case):
    """Both frontier axes are ratio-scale quantities with a real zero; starting
    either above zero exaggerates every difference drawn on it."""
    fig = _draw(figure, case, tmp_path)

    for axis in fig.axes:
        assert axis.get_xlim()[0] == 0
        assert axis.get_ylim()[0] == 0


def test_the_two_arms_are_distinguishable_without_colour(tmp_path):
    """The measured panel separates arm A from arm C by line style as well as by
    legend text; colour alone encodes the signal, so a greyscale print or a
    colourblind reader would otherwise see the two arms as identical lines."""
    # Multi-point frontiers, so the only Line2D artists are the two arms'
    # series: single-point frontiers draw error bars, whose own lines carry a
    # third linestyle ("none") and break the count.
    fig = convergence(
        WIDE_A, WIDE_C, swept=WIDE_SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
    )
    styles = {line.get_linestyle() for line in fig.axes[0].get_lines()}
    assert len(styles) == 2


def test_the_measured_and_modeled_panels_are_tinted_differently(tmp_path):
    """The boundary is drawn on the chart, not left to the caption: the two
    panels carry different backgrounds as well as different titles."""
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
    )
    left, right = fig.axes[0], fig.axes[1]
    assert left.get_facecolor() != right.get_facecolor()


def _rendered(fig):
    """Every text artist that is actually PAINTED, with its rendered pixel box.

    `get_window_extent` needs a drawn canvas; without the explicit draw the
    boxes come back from a stale renderer and every containment check below
    passes vacuously.

    `findobj` is not used here: an Axis keeps Text artists for ticks outside the
    current view limits, which are never painted but do report window extents
    far off the canvas. Asserting over those reports clipping that no reader can
    see, and the true positives would be lost in the noise.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    artists = list(fig.texts)
    for axis in fig.axes:
        artists += list(axis.texts)
        artists += [axis.title, axis.xaxis.label, axis.yaxis.label]
        for matplotlib_axis, lim in ((axis.xaxis, axis.get_xlim()), (axis.yaxis, axis.get_ylim())):
            lo, hi = sorted(lim)
            # Each tick paired with ITS OWN label. Zipping get_majorticklocs()
            # against get_majorticklabels() only lines up while every label is
            # visible: shared axes hide the upper panels' labels, the label list
            # comes back shorter, and the pairing is off by however many were
            # hidden. Hidden labels are dropped by the get_visible() filter below.
            artists += [
                tick.label1
                for tick in matplotlib_axis.get_major_ticks()
                if lo <= tick.get_loc() <= hi
            ]
        if axis.get_legend() is not None:
            artists += list(axis.get_legend().get_texts())
    for legend in fig.legends:
        artists += list(legend.get_texts())
    return [
        (t, t.get_window_extent(renderer))
        for t in artists
        if t.get_text().strip() and t.get_visible()
    ]


@pytest.mark.parametrize("case", LAYOUT_CASES)
@pytest.mark.parametrize("figure", ["convergence", "frontiers", "service_curve"])
def test_no_text_runs_off_the_canvas(tmp_path, figure, case):
    """The defect this repo keeps shipping: a label that renders, passes every
    assertion about its data, and is cut in half by the canvas edge. Artifact 1
    published one. The first draft of THIS module published three -- two banner
    strips clipped at both ends and a legend hanging past the left edge -- and
    every test in this file passed while it did."""
    fig = _draw(figure, case, tmp_path)
    width_px, height_px = fig.get_size_inches() * fig.dpi

    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.x1 <= width_px + 1, (
            f"{text.get_text()!r} spans x {box.x0:.0f}..{box.x1:.0f} on a "
            f"{width_px:.0f}px canvas"
        )
        assert box.y0 >= -1 and box.y1 <= height_px + 1, (
            f"{text.get_text()!r} spans y {box.y0:.0f}..{box.y1:.0f} on a "
            f"{height_px:.0f}px canvas"
        )


@pytest.mark.parametrize("curve_measured", [True, False])
def test_the_banners_and_notes_fit_inside_the_panel_they_describe(curve_measured, tmp_path):
    """A banner wider than its own panel spills across the divider and starts
    describing the other half of the figure -- which, on the one figure whose
    job is to separate measurement from model, is the worst place for it.

    Parameterised over `curve_measured` because it was NOT, and that was the
    blind spot: the unmeasured branch draws a different, longer banner, and its
    first draft ("MEASURED LAG, MODELED LATENCY") overflowed the panel and
    rendered clipped to "...SURED LAG, MODELED LAT" while this guard passed on
    the measured branch it was only ever given.
    """
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png",
        curve_measured=curve_measured, return_figure=True,
    )
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()

    for axis in fig.axes:
        panel = axis.get_window_extent(renderer)
        for text in axis.texts:
            if not text.get_text().strip():
                continue
            box = text.get_window_extent(renderer)
            assert panel.x0 - 1 <= box.x0 and box.x1 <= panel.x1 + 1, (
                f"{text.get_text()!r} spans {box.x0:.0f}..{box.x1:.0f}, outside "
                f"its panel at {panel.x0:.0f}..{panel.x1:.0f}"
            )


def test_no_series_is_hidden_under_another(tmp_path):
    """Six lines share the measured panel. Two that coincide exactly would draw
    as one, and the figure would look like a four-way comparison."""
    fig = _draw("convergence", "realistic", tmp_path)
    seen = set()
    for line in fig.axes[0].get_lines():
        key = (tuple(line.get_xdata()), tuple(line.get_ydata()))
        assert key not in seen, "two series in the measured panel have identical data"
        seen.add(key)
    assert len(seen) == 2 * len(WIDE_A)


@pytest.mark.parametrize("case", LAYOUT_CASES)
@pytest.mark.parametrize("figure", ["convergence", "frontiers", "service_curve"])
def test_no_two_labels_are_printed_on_top_of_each_other(tmp_path, figure, case):
    """Artifact 1 shipped a figure that stamped three labels on one point. The
    first draft of the frontier figure here printed its N statement across the
    legend's first entry, and every other test in this file passed while it did:
    overlapping text is legal matplotlib, correct data, and unreadable."""
    fig = _draw(figure, case, tmp_path)

    # Boxes shrunk slightly before comparing: a text extent includes the font's
    # own ascent/descent padding, so two comfortably separated lines of type
    # report touching boxes and every figure would fail this.
    boxes = [(t.get_text(), b.expanded(0.94, 0.88)) for t, b in _rendered(fig)]
    for i, (label_a, box_a) in enumerate(boxes):
        for label_b, box_b in boxes[i + 1 :]:
            assert not box_a.overlaps(box_b), (
                f"{label_a!r} and {label_b!r} are drawn on top of each other"
            )


@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
def test_the_figure_states_the_p99_span_its_zero_based_axis_can_flatten(tmp_path, figure):
    """Rendered against the real sweep, every frontier sat near 39 s and the
    zero-based y axis drew all three as one hairline at the top of an empty
    panel -- a picture that reads "identical" for data that differed by 0.6 s.
    The axis stays honest; the range is stated in words beside it."""
    fig = _draw(figure, "realistic", tmp_path)
    axis = fig.axes[0]
    stated = " ".join(t.get_text() for t in axis.texts).lower()
    assert "p99 spans" in stated or "all frontiers at p99" in stated


def test_the_span_reports_a_flat_frontier_as_flat_not_as_a_range(tmp_path):
    """The degenerate case the note exists for: every point at the same p99."""
    flat = {
        s: [
            _point(c, 4.0, s)
            for c in (100.0, 200.0)
        ]
        for s in SIGNAL_ORDER
    }
    fig = frontiers(flat, path=tmp_path / "f.png", return_figure=True)
    stated = " ".join(t.get_text() for t in fig.axes[0].texts).lower()
    assert "all frontiers at p99 4 s" in stated


# --- interval bands ----------------------------------------------------------

SWEPT_WITH_INTERVALS = {
    20.0: {"point": 0.8, "lo": 0.5, "hi": 1.1, "budget": 100.0},
    40.0: {"point": 0.6, "lo": 0.4, "hi": 0.9, "budget": 100.0},
    60.0: {"point": 0.5, "lo": 0.2, "hi": 0.9, "budget": 100.0},
}


def _bands(axis):
    """The interval bands on an axis.

    `isinstance`, not `type(c).__name__ == "PolyCollection"`: matplotlib 3.11
    returns a `FillBetweenPolyCollection`, which IS a `PolyCollection` but does
    not share its name. An exact-name check finds nothing and reads as "the
    figure draws no bands" -- the failure looks like the bug it is supposed to
    catch, which is the worst way for a guard to be wrong.
    """
    return [c for c in axis.collections if isinstance(c, PolyCollection)]


def test_the_frontier_figure_draws_an_interval_band_per_signal(tmp_path):
    """Spec 11 requires an interval on every published figure. Without one, a
    30-repetition frontier and a 1-repetition frontier are the same picture.

    This test used ALL_THREE and was VACUOUS. Those frontiers collapse to one
    point per signal, and `fill_between` over a single x-coordinate returns a
    PolyCollection that paints nothing -- so it counted three band objects
    while the rendered figure showed zero bands, which is exactly the defect it
    was written to catch. Presence of the artist is not presence of the band;
    the extent assertion below is what makes it a real check.
    """
    fig = frontiers(WIDE_A, path=tmp_path / "f.png", return_figure=True)
    bands = _bands(fig.axes[0])
    assert len(bands) == len(SIGNAL_ORDER)
    for band in bands:
        (x0, y0), (x1, y1) = band.get_datalim(fig.axes[0].transData).get_points()
        assert x1 - x0 > 0 and y1 - y0 > 0, (
            "the band has zero extent, so it paints nothing -- the artist "
            "exists and the figure shows no interval"
        )
    plt.close(fig)


def test_the_convergence_figure_draws_an_interval_band_on_the_swept_curve(tmp_path):
    fig = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png", curve_measured=True,
        return_figure=True,
    )
    assert _bands(fig.axes[1]), "the modeled panel's gap curve carries no interval"
    plt.close(fig)


def test_a_bare_float_sweep_still_renders_but_without_a_band(tmp_path):
    """The modeled panel is a sensitivity sweep over invented lags, and a caller
    sweeping it cheaply without bootstrapping each point is doing something
    reasonable. What must never happen is a value WITH an interval drawn
    without it."""
    fig = convergence(WIDE_A, WIDE_C, swept=WIDE_SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True)
    assert not _bands(fig.axes[1])
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "bootstrap interval" not in text
    plt.close(fig)


@pytest.mark.parametrize("draw", ["frontiers", "convergence"])
def test_the_figure_states_the_repetition_count_behind_it(draw, tmp_path):
    """`n=55 policy points` said how many policies were drawn, never how many
    runs each was estimated from -- so a 1-repetition sweep and a 30-repetition
    sweep carried identical annotations."""
    if draw == "frontiers":
        fig = frontiers(ALL_THREE, path=tmp_path / "f.png", return_figure=True)
    else:
        fig = convergence(
            WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png", curve_measured=True, return_figure=True
        )
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "repetitions" in text, f"no repetition count anywhere on the figure: {text!r}"
    plt.close(fig)


def test_the_stated_repetition_count_is_a_range_when_the_points_disagree(tmp_path):
    """The exclusion rules discard runs, so policies routinely carry different
    numbers of surviving repetitions. Stating one number would be a claim the
    data does not support."""
    mixed = {s: list(_points(s, i)) for i, s in enumerate(SIGNAL_ORDER)}
    mixed["queue_depth"][0] = _point(100.0, 1.0, "queue_depth", n=24)
    fig = frontiers(mixed, path=tmp_path / "f.png", return_figure=True)
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "24-30 repetitions" in text, text
    plt.close(fig)


def test_a_frontier_point_with_too_few_repetitions_refuses_to_draw_a_band(tmp_path):
    """Drawing the band without those points, or pinching it to zero width at
    them, both publish a narrower interval than the data supports -- and the
    pinch reads as CERTAINTY about exactly the policy we know least about."""
    thin = {s: list(_points(s, i)) for i, s in enumerate(SIGNAL_ORDER)}
    thin["queue_depth"][0] = _point(100.0, 1.0, "queue_depth", n=11)
    with pytest.raises(ValueError, match="surviving repetitions"):
        frontiers(thin, path=tmp_path / "f.png")


# --- the MEASURED banner depends on the service curve ------------------------


def test_the_measured_banner_requires_a_measured_service_curve(tmp_path):
    """The banner said MEASURED because the LAG arms are measured. The p99 axis
    those arms are drawn against comes entirely from the placeholder service
    curve's invented points -- so the panel claimed measurement for numbers that
    were invented, using the very labelling built to stop that claim being
    made."""
    fig = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png",
        curve_measured=False, return_figure=True,
    )
    words = [t.get_text() for t in fig.findobj(plt.Text)]
    assert "LAG MEASURED" in words
    assert "MEASURED" not in words
    assert any("placeholder curve" in w for w in words)
    plt.close(fig)


def test_the_measured_banner_is_restored_by_a_measured_curve(tmp_path):
    fig = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png",
        curve_measured=True, return_figure=True,
    )
    words = [t.get_text() for t in fig.findobj(plt.Text)]
    assert "MEASURED" in words
    assert "LAG MEASURED" not in words
    plt.close(fig)


def test_curve_measured_must_be_stated(tmp_path):
    """No default. A default of True publishes an unmeasured curve as measured
    whenever a caller forgets; a default of False silently downgrades a real
    result. The caller knows which curve it passed to the sweep."""
    with pytest.raises(TypeError, match="curve_measured"):
        convergence(WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png")


def test_the_unmeasured_panel_does_not_wear_the_measured_background(tmp_path):
    """The green ground is half the signal at a glance; leaving it green under a
    'modeled latency' banner would say measured and not-measured at once."""
    unmeasured = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "u.png",
        curve_measured=False, return_figure=True,
    )
    measured = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "m.png",
        curve_measured=True, return_figure=True,
    )
    assert unmeasured.axes[0].get_facecolor() != measured.axes[0].get_facecolor()
    assert unmeasured.axes[0].get_facecolor() == unmeasured.axes[1].get_facecolor()
    plt.close(unmeasured)
    plt.close(measured)


def test_the_interval_opt_out_draws_no_band_rather_than_a_partial_one(tmp_path):
    """A partial band is worse than none: it would cover only the points that
    happened to clear the floor, and read as an interval over the whole
    frontier."""
    thin = {s: [_point(100.0 * (i + 1), 2.0 + i, s, n=3) for i in range(3)] for s in SIGNAL_ORDER}
    fig = frontiers(
        thin, path=tmp_path / "f.png", return_figure=True, allow_missing_intervals=True
    )
    assert not _bands(fig.axes[0])
    plt.close(fig)


def test_the_opt_out_is_off_by_default(tmp_path):
    """The default has to refuse, so an under-powered sweep cannot reach a
    published figure by accident."""
    thin = {s: [_point(100.0 * (i + 1), 2.0 + i, s, n=3) for i in range(3)] for s in SIGNAL_ORDER}
    with pytest.raises(ValueError, match="surviving repetitions"):
        frontiers(thin, path=tmp_path / "f.png")


def test_a_signal_that_could_not_be_banded_is_named_on_the_figure(tmp_path):
    """A signal drawn without a band beside two that have one reads as the
    CERTAIN one, which is exactly backwards: it is the one whose runs the
    pre-registered exclusions ate."""
    arm_a = {s: list(_points(s, i)) for i, s in enumerate(SIGNAL_ORDER)}
    arm_a["queue_depth"] = [_point(c, 9.0 - c / 200, "queue_depth", n=4) for c in (100.0, 200.0)]
    fig = convergence(
        arm_a,
        {s: list(_points(s, i * 0.3)) for i, s in enumerate(SIGNAL_ORDER)},
        swept=SWEPT_WITH_INTERVALS,
        path=tmp_path / "c.png",
        curve_measured=False,
        return_figure=True,
    )
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "no interval (too few reps)" in text
    assert "queue depth" in text
    plt.close(fig)


def test_a_single_point_frontier_still_shows_its_interval(tmp_path):
    """`fill_between` over one x-coordinate has zero width and paints nothing,
    so a signal whose frontier collapses to one operating point was drawn as a
    bare marker beside two banded curves -- and a series with no band beside
    two that have one reads as the CERTAIN one, which `_band`'s own refusal
    path exists to prevent.

    Not hypothetical: on the arm-A sweep every queue_depth policy costs the
    same 670 replica-seconds, so its frontier is exactly one point, and
    queue_depth is the signal carrying this artifact's headline finding.
    """
    one_point = {
        "queue_depth": [_point(670.0, 6.0, "queue_depth")],
        "in_flight_concurrency": _frontier_shaped("in_flight_concurrency", 1.0),
        "utilization": _frontier_shaped("utilization", 2.0),
    }

    fig = frontiers(one_point, path=tmp_path / "f.png", return_figure=True)
    axis = fig.axes[0]
    bars = [c for c in axis.containers if type(c).__name__ == "ErrorbarContainer"]
    assert bars, (
        "the single-point frontier drew no interval at all; a bare marker "
        "beside two banded curves reads as the certain one"
    )
    plt.close(fig)


# --- figure 4: the service curve ----------------------------------------------


def test_censoring_starts_where_utilization_crosses_the_top_of_its_grid():
    """Placeholder: utilization 0.85 at 8, 0.96 at 16. Linear interpolation --
    the same ServiceCurve uses -- puts 0.95 at 8 + 0.10/0.11 x 8."""
    assert UTILIZATION_CENSOR_AT == 0.95
    # Read off the pre-registered grid, not chosen for the chart: if the grid's
    # top moves, the shading has to move with it.
    assert UTILIZATION_CENSOR_AT == max(THRESHOLDS["utilization"][0])
    assert censoring_onset(SERVICE_CURVE_PLACEHOLDER) == pytest.approx(8 + 0.10 / 0.11 * 8)


def test_the_censoring_threshold_follows_the_grid_when_the_grid_moves():
    """Equality with the grid's top cannot tell "read off the grid" from "0.95
    typed in" while both are 0.95. A fresh interpreter edits the grid BEFORE
    the figure module is imported, which only the first survives."""
    code = (
        "import autoscale.thresholds as t; "
        "t.THRESHOLDS['utilization'] = ((0.5, 0.88), (0.1,)); "
        "import autoscale.figures as f; print(f.UTILIZATION_CENSOR_AT)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "0.88"


def test_utilization_reaching_the_threshold_exactly_at_the_last_level_starts_censoring_there():
    """"Reaches" includes "equals": every utilization policy's top threshold
    is crossed AT 0.95, so a curve that tops out exactly there is censored from
    that level on, not uncensored."""
    edge = ServiceCurve(points=[(1, 0.3, 50.0, 0.5), (8, 0.4, 300.0, UTILIZATION_CENSOR_AT)], measured=False)
    assert censoring_onset(edge) == 8.0


def test_a_utilization_dip_after_the_onset_is_refused(tmp_path):
    """Shading runs from the onset to the edge and says "utilization >= 0.95"
    over all of it. A curve that falls back below the threshold has a stretch
    inside that band where the utilization policy CAN still act -- the band
    would claim censoring where there is none."""
    dip = ServiceCurve(
        points=[
            (c, 0.3 + 0.02 * c, 50.0 + 7.0 * c, u)
            for c, u in zip((1, 8, 16, 32, 64), (0.20, 0.96, 0.90, 0.93, 0.97), strict=True)
        ],
        measured=False,
    )
    with pytest.raises(ValueError, match="can still act"):
        censoring_onset(dip)
    with pytest.raises(ValueError, match="can still act"):
        service_curve(dip, path=tmp_path / "s.png")


def test_censoring_starts_at_the_first_level_when_utilization_is_already_over():
    """No pair of points brackets the threshold when the FIRST one is already
    above it, so the interpolation loop alone returns None -- and the figure
    would say "never reached" about a curve that is censored everywhere."""
    hot = ServiceCurve(points=[(2, 0.5, 400.0, 0.97), (8, 1.2, 500.0, 1.0)], measured=False)
    assert censoring_onset(hot) == 2.0


def test_no_censoring_when_utilization_never_reaches_the_threshold(tmp_path):
    low = ServiceCurve(points=[(1, 0.3, 50.0, 0.2), (8, 0.4, 300.0, 0.6)], measured=False)
    assert censoring_onset(low) is None
    fig = service_curve(low, path=tmp_path / "s.png", return_figure=True)
    assert not [p for ax in fig.axes for p in ax.patches if p.get_gid() == "censored"]
    assert "never reached" in " ".join(_texts(fig))


def test_the_censored_region_is_painted_on_every_panel(tmp_path):
    """Not "a patch exists" -- a zero-width span exists and paints nothing,
    which is the defect a presence check would pass. Real pixel width."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    spans = [p for ax in fig.axes for p in ax.patches if p.get_gid() == "censored"]
    assert len(spans) == 3
    assert all(p.get_window_extent(renderer).width > 20 for p in spans)
    assert all(p.get_facecolor()[3] > 0 for p in spans), "the band is fully transparent"


def test_the_censored_band_changes_the_saved_pixels_on_every_panel(tmp_path):
    """Width and alpha are properties of the artist; this is the PNG. Each
    panel is sampled inside the band, low in the panel where no curve runs,
    and the pixel must differ from that panel's own background -- a band that
    is wide, opaque on paper and drawn under the background still fails."""
    path = tmp_path / "s.png"
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=path, return_figure=True)
    fig.canvas.draw()
    image = Image.open(path).convert("RGB")
    scale = image.width / fig.bbox.width
    onset = censoring_onset(SERVICE_CURVE_PLACEHOLDER)
    for axis in fig.axes:
        x = axis.transData.transform(((onset + axis.get_xlim()[1]) / 2, 0))[0]
        y = axis.transAxes.transform((0, 0.08))[1]
        pixel = image.getpixel((round(x * scale), round(image.height - y * scale)))
        background = tuple(round(255 * c) for c in to_rgb(axis.get_facecolor()))
        assert sum(abs(a - b) for a, b in zip(pixel, background, strict=True)) > 30, (
            f"inside the band the PNG shows {pixel}, which is the panel's own "
            f"background {background}: the band paints nothing"
        )


def test_the_censored_band_starts_at_the_censoring_onset_on_every_panel(tmp_path):
    """Width alone passes a band drawn from zero. Pinned in pixels against the
    onset `censoring_onset` computes, which is the number the note prints."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    onset = censoring_onset(SERVICE_CURVE_PLACEHOLDER)
    for axis in fig.axes:
        [span] = [p for p in axis.patches if p.get_gid() == "censored"]
        expected = axis.transData.transform((onset, 0))[0]
        assert span.get_window_extent(renderer).x0 == pytest.approx(expected, abs=1)


def test_the_note_states_where_censoring_starts(tmp_path):
    """The number is computed here independently of `censoring_onset`, so a
    wrong onset cannot agree with itself: 0.95 is 0.10 of the way from 0.85 to
    0.96, which is 8 + 0.10/0.11 x 8."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    note = " ".join(t.get_text() for t in fig.axes[2].texts)
    assert f"from {8 + 0.10 / 0.11 * 8:.1f})" in note, note


def test_an_unmeasured_curve_says_so_on_the_chart(tmp_path):
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    assert "NOT MEASURED" in _texts(fig)


def test_a_measured_curve_is_labelled_measured(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    words = _texts(fig)
    assert "MEASURED" in words and "NOT MEASURED" not in words


def test_n_is_stated_on_the_service_curve(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    assert "n=10" in " ".join(_texts(fig))


def test_every_service_curve_axis_starts_at_zero(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    for axis in fig.axes:
        assert axis.get_ylim()[0] == 0 and axis.get_xlim()[0] == 0


@pytest.mark.parametrize("curve", [SERVICE_CURVE_PLACEHOLDER, WIDE_CURVE], ids=["placeholder", "measured"])
def test_the_figure_4_banner_holds_its_word_and_clears_the_panels(curve, tmp_path):
    """The first draft reused `_banner`, which sizes its strip as a fraction of
    ONE panel's height. On three short stacked panels the strip came out
    shorter than the word inside it and the subtitle landed on the top panel --
    while every legibility and off-canvas test in this file passed."""
    fig = service_curve(curve, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    [strip] = [a for a in fig.get_children() if isinstance(a, Rectangle) and a is not fig.patch]
    # Attached to the figure, not just appended to a list it happens to draw:
    # an artist with no figure has no dpi to resolve against.
    assert strip.get_figure() is fig
    strip_box = strip.get_window_extent(renderer)
    word = next(t for t in fig.texts if t.get_text() in ("MEASURED", "NOT MEASURED"))
    word_box = word.get_window_extent(renderer)
    assert strip_box.y0 <= word_box.y0 and word_box.y1 <= strip_box.y1, (
        f"banner word spans y {word_box.y0:.0f}..{word_box.y1:.0f}, outside its "
        f"strip at {strip_box.y0:.0f}..{strip_box.y1:.0f}"
    )
    top_panel = fig.axes[0].get_window_extent(renderer)
    for text in fig.texts:
        assert text.get_window_extent(renderer).y0 >= top_panel.y1, (
            f"{text.get_text()!r} overlaps the top panel"
        )


def test_each_y_label_fits_the_height_of_its_own_panel(tmp_path):
    """Three short panels leave little height for a rotated label. The first
    draft's single-line labels ran past their panels and into each other.
    Checked against each label's OWN panel rather than against its neighbours:
    a neighbour-overlap check misses one long label beside two short ones."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for axis in fig.axes:
        panel = axis.get_window_extent(renderer)
        label = axis.yaxis.label.get_window_extent(renderer)
        assert panel.y0 - 1 <= label.y0 and label.y1 <= panel.y1 + 1, (
            f"{axis.yaxis.label.get_text()!r} spans y {label.y0:.0f}..{label.y1:.0f}, "
            f"past its panel at {panel.y0:.0f}..{panel.y1:.0f}"
        )


def test_the_censored_band_reaches_the_right_edge(tmp_path):
    """A band that stops at the last measured point reads as censoring that
    ENDS there."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    for axis in fig.axes:
        [span] = [p for p in axis.patches if p.get_gid() == "censored"]
        x1 = span.get_x() + span.get_width()
        assert x1 == pytest.approx(axis.get_xlim()[1])


def test_the_censoring_threshold_is_drawn_across_the_utilization_panel(tmp_path):
    """The dotted line is what ties the shading to a utilization VALUE: without
    it the band's left edge is a concurrency with no visible reason. Mutation
    check found nothing held it in place."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    lines = [
        line for line in fig.axes[2].get_lines()
        if list(line.get_ydata()) == [UTILIZATION_CENSOR_AT] * 2
        and list(line.get_xdata()) == [0, 1]
    ]
    assert len(lines) == 1, "no full-width line at the censoring threshold on the utilization panel"


def test_importing_the_figures_does_not_load_the_simulator_or_artifact_one():
    """A fresh interpreter, because in-process `sys.modules` already holds
    whatever other test modules imported. `tests/test_autoscale_boundary.py`
    parses DIRECT imports only, and the road to `coldstart` here was
    transitive: figure 4 read the utilization grid from `autoscale.sweep`,
    which imports `autoscale.sim` and `autoscale.coldstart_ecdf`, so a module
    that only draws charts could no longer be imported without artifact 1's
    package."""
    code = (
        "import sys; import autoscale.figures; "
        "print(sorted(m for m in sys.modules if m == 'coldstart' or m.startswith('coldstart.')"
        " or m in ('autoscale.sim', 'autoscale.coldstart_ecdf')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", (
        f"importing autoscale.figures loads {out.stdout.strip()}; a plotting module "
        "that drags in the simulator and artifact 1's package cannot be rendered, "
        "reused or tested without them"
    )


def test_the_threshold_grid_has_one_home_and_sweep_re_exports_it():
    """Moved, not copied: a second dict with the same values would drift the
    first time a grid is edited, and figure 4 would shade against a grid the
    sweep no longer uses."""
    import autoscale.sweep
    import autoscale.thresholds

    assert autoscale.sweep.THRESHOLDS is autoscale.thresholds.THRESHOLDS


# --- Task 7: figure 4 on the measured curve, figure 2 names its curve --------

from autoscale.measured_curve import DEFAULT_PATH as _MEASURED_PATH
from autoscale.measured_curve import load_measured_curve

MEASURED = load_measured_curve(REPO / _MEASURED_PATH)


def _draw_measured(tmp_path):
    return service_curve(MEASURED.curve, tmp_path / "m.png", return_figure=True, measured=MEASURED)


def _gid_count(axis, gid):
    return sum(1 for a in axis.findobj() if getattr(a, "get_gid", lambda: None)() == gid)


def test_measured_figure_4_draws_an_interval_bar_set_on_every_panel(tmp_path):
    fig = _draw_measured(tmp_path)
    assert len(fig.axes) == 3
    for axis in fig.axes:
        assert _gid_count(axis, "interval") == 1


def test_measured_figure_4_marks_the_idle_point_apart(tmp_path):
    fig = _draw_measured(tmp_path)
    # Throughput and utilisation only: latency has no idle reading to show.
    assert [_gid_count(axis, "idle") for axis in fig.axes] == [0, 1, 1]


def test_measured_figure_4_states_runs_levels_and_the_unservable_level(tmp_path):
    text = " ".join(_texts(_draw_measured(tmp_path)))
    assert "n=8 levels × 3 runs" in text
    assert "256 not servable" in text
    assert "from 0.95" in text
    assert "MEASURED" in text and "NOT MEASURED" not in text


def test_measured_figure_4_clears_the_phone_floor_and_stays_on_canvas(tmp_path):
    fig = _draw_measured(tmp_path)
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(match=matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    w, h = fig.canvas.get_width_height()
    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, text


def test_the_interval_bars_change_the_saved_pixels(tmp_path):
    """The same MeasuredCurve drawn twice, once with its intervals collapsed to
    zero width, compared over the first panel's window only. Against a bare
    `service_curve(curve)` the diff would also include the idle-point segment
    and the note and subtitle text, and would pass with the bars deleted."""
    import dataclasses

    from PIL import ImageChops

    def panel(figure, name):
        figure.canvas.draw()
        box = figure.axes[0].get_window_extent()
        h = figure.canvas.get_width_height()[1]
        crop = (round(box.x0), round(h - box.y1), round(box.x1), round(h - box.y0))
        path = tmp_path / name
        figure.savefig(path)
        return Image.open(path).convert("RGB").crop(crop)

    flat = dataclasses.replace(
        MEASURED,
        intervals=tuple(
            {**i, **{k: [v, v] for k, v in zip(
                ("latency_s_range", "throughput_tps_range", "gpu_util_range"),
                (p[1], p[2], p[3]), strict=True)}}
            for i, p in zip(MEASURED.intervals, MEASURED.measured_points, strict=True)
        ),
    )
    with_bars = panel(_draw_measured(tmp_path), "a.png")
    without = panel(service_curve(MEASURED.curve, tmp_path / "b0.png", return_figure=True,
                                  measured=flat), "b.png")
    assert ImageChops.difference(with_bars, without).getbbox() is not None


def test_measured_requires_the_matching_curve(tmp_path):
    with pytest.raises(ValueError, match="same curve"):
        service_curve(SERVICE_CURVE_PLACEHOLDER, tmp_path / "x.png", measured=MEASURED)


def test_figure_2_names_its_curve_only_when_told(tmp_path):
    base = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "f.png", return_figure=True)))
    assert "measured curve" not in base and "PLACEHOLDER curve" not in base
    meas = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "g.png", return_figure=True,
                                     curve_measured=True)))
    assert "measured curve" in meas
    ph = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "h.png", return_figure=True,
                                   curve_measured=False)))
    assert "PLACEHOLDER curve" in ph


@pytest.mark.parametrize("curve_measured", [True, False])
@pytest.mark.parametrize("context", ["arm A", "ramp arm A"])
def test_figure_2_note_stays_on_canvas_with_its_curve_label(tmp_path, curve_measured, context):
    fig = frontiers(WIDE_A, tmp_path / "f.png", return_figure=True, context=context,
                    curve_measured=curve_measured)
    width_in = fig.get_size_inches()[0]
    w, h = fig.canvas.get_width_height()
    for t in fig.findobj(match=matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, text


_OV_CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                         measured=True)


def _overlay_inputs(factors=(0.97, 1.0, 1.03)):
    from autoscale.sim import run_fixed_capacity
    until = 200.0
    s = _build_schedule(_OV_CURVE, replicas=2, kind="step", until=until, drain=20.0, seed=1)
    by_arrival = dict(run_fixed_capacity(list(s), 2, _OV_CURVE, until).completed_requests())
    runs = [RealRun(schedule=s, sent=s, latencies=[by_arrival[t] * f for t in s], replicas=2,
                    until=until, host_ids=("w1", "w2")) for f in factors]
    predicted = predicted_trajectory(s, 2, _OV_CURVE, until)
    band_bins = tolerance_band(runs)
    repeats = [_trajectory(r.schedule, r.windowed_latencies(), until=until, bin_seconds=10.0)
               for r in runs]
    return predicted, band_bins, _validate(runs, _OV_CURVE), repeats, len(s)


def _draw_overlay(tmp_path, factors=(0.97, 1.0, 1.03)):
    predicted, band_bins, verdict, repeats, n = _overlay_inputs(factors)
    return validation_overlay(predicted, band_bins, verdict, repeats, tmp_path / "v.png",
                              replicas=2, requests_per_run=n, latency_source="server",
                              return_figure=True)


def test_overlay_draws_band_prediction_and_repeats(tmp_path):
    fig = _draw_overlay(tmp_path)
    gids = [a.get_gid() for a in fig.findobj() if hasattr(a, "get_gid")]
    assert gids.count("band") == 1 and gids.count("predicted") == 1 and gids.count("repeat") == 3


def test_overlay_marks_every_judged_miss(tmp_path):
    fig = _draw_overlay(tmp_path, factors=(1.4, 1.45, 1.5))
    _, _, verdict, _, _ = _overlay_inputs((1.4, 1.45, 1.5))
    misses = [a for a in fig.findobj() if getattr(a, "get_gid", lambda: None)() == "miss"]
    assert len(misses) == 1
    assert len(misses[0].get_xdata()) == verdict.misses


def test_overlay_states_n_outcome_source_and_banner(tmp_path):
    text = " ".join(_texts(_draw_overlay(tmp_path)))
    assert "MEASURED" in text and "2 replicas pinned, 3 real runs of one schedule" in text
    assert "requests per run" in text and "passed" in text and "server-side latency" in text


def test_overlay_axes_start_at_zero_and_text_is_legible_and_on_canvas(tmp_path):
    fig = _draw_overlay(tmp_path)
    axis = fig.axes[0]
    assert axis.get_ylim()[0] == 0 and axis.get_xlim()[0] == 0
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(match=matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    w, h = fig.canvas.get_width_height()
    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, text


def test_the_band_changes_the_saved_pixels(tmp_path):
    """The same overlay drawn with and without the band's ranges: a band that was
    computed but never reached the canvas would leave the two PNGs identical."""
    predicted, band_bins, verdict, repeats, n = _overlay_inputs()
    kw = {"replicas": 2, "requests_per_run": n, "latency_source": "server"}
    with_band = validation_overlay(predicted, band_bins, verdict, repeats, tmp_path / "a.png", **kw)
    bare = [BandBin(b.start, b.end, None, None, "insufficient") for b in band_bins]
    without = validation_overlay(predicted, bare, verdict, repeats, tmp_path / "b.png", **kw)
    a, b = (Image.open(p).convert("RGB") for p in (with_band, without))
    differing = sum(1 for x, y in zip(a.tobytes(), b.tobytes(), strict=True) if x != y)
    assert differing > 5000


def test_overlay_refuses_a_count_of_repeats_other_than_three(tmp_path):
    predicted, band_bins, verdict, repeats, n = _overlay_inputs()
    with pytest.raises(ValueError, match="3 repeats"):
        validation_overlay(predicted, band_bins, verdict, repeats[:2], tmp_path / "x.png",
                           replicas=2, requests_per_run=n, latency_source="server")
