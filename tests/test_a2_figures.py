import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest
from matplotlib.collections import PolyCollection

from autoscale.figures import SIGNAL_ORDER, convergence, frontiers
from autoscale.frontier import PolicyPoint

# `harness.figure_guards` does not exist yet -- the harness extraction that owns
# it has not run. `coldstart.analysis.figures` is where the constant currently
# lives, and it is the SAME constant the artifact-1 figures are held to, which
# is the point: artifact 2's charts are published in the same post, on the same
# phones, and must clear the same calibrated floor. Re-point this import at
# `harness.figure_guards` when the extraction lands.
from coldstart.analysis.figures import MIN_PHONE_TEXT_PX


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
@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
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
    fig = frontiers(ALL_THREE, path=tmp_path / "f.png", return_figure=True)
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
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
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
            artists += [
                label
                for loc, label in zip(
                    matplotlib_axis.get_majorticklocs(),
                    matplotlib_axis.get_majorticklabels(),
                    strict=True,
                )
                if lo <= loc <= hi
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
@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
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


def test_the_banners_and_notes_fit_inside_the_panel_they_describe(tmp_path):
    """A banner wider than its own panel spills across the divider and starts
    describing the other half of the figure -- which, on the one figure whose
    job is to separate measurement from model, is the worst place for it."""
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept=SWEPT, path=tmp_path / "c.png", curve_measured=True, return_figure=True
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
@pytest.mark.parametrize("figure", ["convergence", "frontiers"])
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
    30-repetition frontier and a 1-repetition frontier are the same picture."""
    fig = frontiers(ALL_THREE, path=tmp_path / "f.png", return_figure=True)
    assert len(_bands(fig.axes[0])) == len(SIGNAL_ORDER)
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
    assert "MEASURED LAG, MODELED LATENCY" in words
    assert "MEASURED" not in words
    assert any("placeholder service curve" in w for w in words)
    plt.close(fig)


def test_the_measured_banner_is_restored_by_a_measured_curve(tmp_path):
    fig = convergence(
        WIDE_A, WIDE_C, swept=SWEPT_WITH_INTERVALS, path=tmp_path / "c.png",
        curve_measured=True, return_figure=True,
    )
    words = [t.get_text() for t in fig.findobj(plt.Text)]
    assert "MEASURED" in words
    assert "MEASURED LAG, MODELED LATENCY" not in words
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
