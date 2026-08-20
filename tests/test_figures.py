"""Tests for the four artifact figures.

These are charts, not UI: a test that only asserts a PNG file exists and is
"not tiny" (the plan's given test) proves a file was written, not that the
chart is correct. Every test here instead pins something matplotlib exposes
without rendering — bar counts, stacking order, colors, axis limits, legend
text, line data — so a mutation that scrambles the chart (wrong stacking
order, an arm silently dropped, axes that don't start at zero, a median that
drifts from the published percentile table) fails a test instead of just
being an ugly PNG nobody looked at closely enough.
"""

import copy
import statistics
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest

import coldstart.analysis.figures as figures_module
from coldstart.analysis.figures import (
    RESIDUAL_COLOR,
    ecdf_plot,
    per_host_medians,
    warmup_curve,
    waterfall,
)

# Distinct per-arm warmup shape (different plateau and different initial
# spike): a fixture where all three arms shared one warmup curve — the
# original version of this fixture — makes warmup_curve's three series draw
# exactly on top of each other. A test can only detect what its fixture can
# express, and a fixture like that cannot tell "three correct series" apart
# from "the same series plotted three times" or "two series silently
# dropped." Values are illustrative (a cached/compiled arm settling faster
# and lower), not measured.
_WARMUP_STEADY = {"A": 3.0, "B": 2.0, "C": 1.2}
_WARMUP_SPIKE = {"A": 3.5, "B": 2.5, "C": 1.6}

# Per-host additive offset on t_total. Every (arm, host) pair appears
# exactly twice in a 30-row fixture (lcm(3, 5) = 15), so each host's 6 rows
# split evenly 2/2/2 across arms and this offset shifts each host's own
# median by exactly this amount — it demonstrates real host heterogeneity
# (spec H4: host variance, not just within-stage variance, drives the tail)
# rather than the near-flat (<5% spread) bar chart the unshifted fixture
# produced. Kept below half the tightest inter-arm gap (B-C, 35s baseline)
# so ecdf_plot's three per-arm distributions stay visually separated
# instead of bleeding into each other.
_HOST_OFFSET = {"h0": -10.0, "h1": -5.0, "h2": 0.0, "h3": 5.0, "h4": 10.0}

# Per-arm S4 subphases. Arm A and B keep the original constants (6.0, 12.0);
# waterfall's exact-width assertions below are pinned against those two
# arms and are untouched by this change. Arm C cannot use the same
# constants: with t_process=42.0 and t_weights=30.0, a sub-phase sum of 18.0
# would make weights + subphases (48.0) exceed t_process (42.0) -- a
# negative "unattributed" term, which waterfall() now raises on instead of
# silently clamping to zero (see the dedicated negative-term tests). Arm C's
# subphases are scaled down so the *default* fixture is internally
# consistent; the negative case gets its own explicit, separately
# constructed fixture instead of hiding inside the everyday one.
_S4_SUBPHASES = {
    "A": {"S4c": 6.0, "S4e": 12.0},
    "B": {"S4c": 6.0, "S4e": 12.0},
    "C": {"S4c": 3.0, "S4e": 6.0},
}


def rows(n=30):
    out = []
    for i in range(n):
        arm = ["A", "B", "C"][i % 3]
        host = f"h{i % 5}"
        base = {"A": 160.0, "B": 95.0, "C": 60.0}[arm]
        steady = _WARMUP_STEADY[arm]
        spike = _WARMUP_SPIKE[arm]
        out.append(
            {
                "arm": arm,
                "host_id": host,
                "t_total": base + i * 0.4 + _HOST_OFFSET[host],
                "t_platform": 18.0,
                "t_weights": base * 0.5,
                "s4_subphases": dict(_S4_SUBPHASES[arm]),
                "t_process": base - 18.0,
                "warmup": [
                    {"req_index": k, "end_to_end": steady + spike * 0.55**k} for k in range(10)
                ],
            }
        )
    return out


def _call_capturing_axes(func, *args):
    """Capture the Axes matplotlib builds for `func`'s call, so tests can
    assert on axes/patches/lines directly instead of just "a file exists".

    Every figure function calls `plt.close(fig)` right before returning.
    That deregisters the figure from pyplot's manager but does not clear
    its artists (Figure.clf() is never called), so the Axes captured here
    via a `plt.subplots` spy stays fully introspectable after the function
    returns — the only thing lost is `plt.gcf()` returning it.
    """
    captured = {}
    real_subplots = plt.subplots

    def spy(*a, **kw):
        fig, ax = real_subplots(*a, **kw)
        captured["fig"], captured["ax"] = fig, ax
        return fig, ax

    with patch("coldstart.analysis.figures.plt.subplots", side_effect=spy):
        func(*args)
    return captured["fig"], captured["ax"]


# ---------------------------------------------------------------------------
# smoke test: all four write real files (the plan's given test, kept as a
# baseline — but not treated as sufficient on its own)
# ---------------------------------------------------------------------------


def test_all_four_figures_write_files(tmp_path: Path):
    data = rows()
    paths = [
        waterfall(data, tmp_path / "waterfall.png"),
        warmup_curve(data, tmp_path / "warmup.png"),
        ecdf_plot(data, tmp_path / "ecdf.png"),
        per_host_medians(data, tmp_path / "hosts.png"),
    ]
    for p in paths:
        assert p.exists() and p.stat().st_size > 5000, f"{p} looks empty"


# ---------------------------------------------------------------------------
# waterfall
# ---------------------------------------------------------------------------


def test_waterfall_draws_five_segments_per_arm_with_residual_first_and_correct_stacking(tmp_path):
    """Pins the exact segment widths and left offsets for arm A (measured
    branch), derived by hand from the fixture: t_platform=18 (constant),
    t_process=142, t_weights=80, S4c=6, S4e=12, so unattributed = 142 - 80 -
    18 = 44. This catches both a wrong stacking order and a wrong segment
    value, not just "some bars got drawn"."""
    data = rows()
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    assert len(ax.patches) == 15  # 3 arms x 5 segments (every row has t_weights set)

    residual_rgba = mcolors.to_rgba(RESIDUAL_COLOR)
    weights_rgba = mcolors.to_rgba("#2f6fd0")

    arm_a = ax.patches[0:5]
    assert arm_a[0].get_facecolor() == residual_rgba  # residual segment drawn first
    assert arm_a[1].get_facecolor() == weights_rgba
    widths = [p.get_width() for p in arm_a]
    assert widths == pytest.approx([18.0, 80.0, 6.0, 12.0, 44.0])
    lefts = [p.get_x() for p in arm_a]
    assert lefts == pytest.approx([0.0, 18.0, 98.0, 104.0, 116.0])


def test_waterfall_arm_c_segments_are_pinned_and_genuinely_positive(tmp_path):
    """Arm C: t_process=42, t_weights=30, S4c+S4e=9 -> unattributed = 42 -
    30 - 9 = 3, a small but genuinely positive residual (arm C's subphases
    are scaled down in the fixture specifically so this stays >= 0 -- see
    the fixture's `_S4_SUBPHASES` comment). The dedicated negative-term
    tests below cover the case that must now raise instead of clamp."""
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    arm_c = ax.patches[10:15]
    widths = [p.get_width() for p in arm_c]
    assert widths == pytest.approx([18.0, 30.0, 3.0, 6.0, 3.0])


def test_waterfall_yticklabels_carry_each_arms_n(tmp_path):
    data = rows()  # 30 rows, 10 per arm
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert len(labels) == 3
    for lbl in labels:
        assert "n=10" in lbl


def test_waterfall_xlim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    assert ax.get_xlim()[0] == 0


def test_waterfall_merged_branch_draws_two_segments_labeled_merged(tmp_path):
    """The plan's given fixture never sets t_weights=None, so it never
    exercises the merged-phase branch metrics.py's derive() produces when
    the engine doesn't delineate the S2/S3 boundary. Build that fixture
    explicitly."""
    data = rows()
    for r in data:
        r["t_weights"] = None
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    assert len(ax.patches) == 6  # 3 arms x 2 segments (platform + merged)

    residual_rgba = mcolors.to_rgba(RESIDUAL_COLOR)
    arm_a = ax.patches[0:2]
    assert len(arm_a) == 2
    assert arm_a[0].get_facecolor() == residual_rgba

    _handles, labels = ax.get_legend_handles_labels()
    assert any("merged" in lbl.lower() for lbl in labels)


def test_waterfall_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    waterfall(data, tmp_path / "w.png")
    assert data == before


def test_waterfall_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        waterfall([], tmp_path / "w.png")


def test_waterfall_rejects_an_arm_with_no_rows(tmp_path):
    """Silently dropping an arm's series (the plan's `if not rs: continue`)
    is a misleading chart, not a smaller one — it must raise instead."""
    data = [r for r in rows() if r["arm"] != "C"]
    with pytest.raises(ValueError, match="C"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_uses_the_shared_median_helper(tmp_path):
    """The required fix beyond the plan text: figures.py must call
    stats.median, not statistics.median, or a chart median could silently
    disagree with the published percentile table's median on the same
    data."""
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        waterfall(rows(), tmp_path / "w.png")
    assert spy.called


def test_waterfall_raises_on_a_negative_unattributed_term_instead_of_clamping(tmp_path):
    """If the measured sub-phases plus t_weights exceed t_process, the
    decomposition does not fit inside the thing it decomposes -- checks.py
    applies exactly this discipline to a single run's t_weights ("discard,
    don't silently correct"). A max(0.0, ...) clamp (the original behavior)
    would draw a plausible-looking but understated bar instead of surfacing
    the defect; this must raise, and name the offending arm."""
    data = rows()
    for r in data:
        if r["arm"] == "C":
            # arm C: t_process=42.0, t_weights=30.0; pushing S4e to 40.0
            # makes weights + subphases = 30 + 46 = 76, well past t_process.
            r["s4_subphases"] = {"S4c": 6.0, "S4e": 40.0}
    with pytest.raises(ValueError, match="C"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_negative_unattributed_message_names_the_actual_numbers(tmp_path):
    """Pins that the raised message carries the numbers a reader would need
    to investigate (not just "something is wrong somewhere"), and that a
    well-formed arm earlier in ARMS order doesn't mask a later arm's
    defect."""
    data = rows()
    for r in data:
        if r["arm"] == "C":
            r["s4_subphases"] = {"S4c": 6.0, "S4e": 40.0}
    with pytest.raises(ValueError, match=r"-34\.0"):
        waterfall(data, tmp_path / "w.png")


# ---------------------------------------------------------------------------
# warmup_curve
# ---------------------------------------------------------------------------


def test_warmup_curve_plots_the_number_of_requests_present_in_the_data(tmp_path):
    data = rows()  # every row has a 10-request warmup
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    for ln in arm_lines:
        assert list(ln.get_xdata()) == list(range(1, 11))


def test_warmup_curve_plots_a_different_request_count_when_the_data_has_fewer(tmp_path):
    """Pins that the request count comes from the data, not a hardcoded 10:
    a fixture with 4 warmup requests per row must produce 4-point lines."""
    data = rows()
    for r in data:
        r["warmup"] = r["warmup"][:4]
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    for ln in arm_lines:
        assert list(ln.get_xdata()) == [1, 2, 3, 4]


def test_warmup_curve_series_are_visually_distinct_not_identical(tmp_path):
    """Regression guard for the fixture itself: the original `rows()` gave
    every arm the exact same warmup shape, so only the last-drawn arm's line
    was visible (the other two were drawn underneath it). A test built on
    that fixture cannot tell "three correct series" from "one series plotted
    three times" or "two series silently dropped" -- both would pass every
    other assertion in this file. Each arm's y-data must actually differ."""
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    ydata = [tuple(ln.get_ydata()) for ln in arm_lines]
    assert len(set(ydata)) == 3


def test_warmup_curve_legend_labels_carry_each_arms_n(tmp_path):
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    _handles, labels = ax.get_legend_handles_labels()
    # Curve labels carry "(n=..)"; the per-arm band labels don't repeat it
    # (the band belongs to the curve right next to it in the legend), so
    # filtering on "n=" isolates just the three curve entries.
    arm_labels = [lbl for lbl in labels if "n=10" in lbl]
    assert len(arm_labels) == 3
    band_labels = [lbl for lbl in labels if "steady-state band" in lbl]
    assert len(band_labels) == 3
    assert len(labels) == 6


def test_warmup_curve_ylim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    assert ax.get_ylim()[0] == 0


def test_warmup_curve_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    warmup_curve(data, tmp_path / "w.png")
    assert data == before


def test_warmup_curve_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        warmup_curve([], tmp_path / "w.png")


def test_warmup_curve_rejects_an_arm_with_no_rows(tmp_path):
    data = [r for r in rows() if r["arm"] != "B"]
    with pytest.raises(ValueError, match="B"):
        warmup_curve(data, tmp_path / "w.png")


def test_warmup_curve_rejects_mismatched_warmup_lengths(tmp_path):
    """A row with a shorter warmup list than the rest must raise loudly
    instead of either IndexError-ing deep inside a comprehension or
    silently truncating every other row's curve to match it."""
    data = rows()
    data[0] = dict(data[0])
    data[0]["warmup"] = data[0]["warmup"][:5]
    with pytest.raises(ValueError, match="mismatch"):
        warmup_curve(data, tmp_path / "w.png")


def test_warmup_curve_steady_state_band_is_per_arm_not_pooled(tmp_path):
    """Each arm converges to its own plateau (A ~3.0, B ~2.0, C ~1.2 in this
    fixture) -- a single band pooled across all three arms would sit only
    near the middle arm's plateau, making the slowest arm look like it
    never reaches "steady state" and the fastest arm look permanently
    faster than it. A pooled-band implementation draws exactly one band
    (this asserts three, at three independently-verified levels) and fails
    this test."""
    data = rows()
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")

    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    assert len(bands) == 3  # one band per arm, not one pooled across all three

    by_arm = {a: [r for r in data if r["arm"] == a] for a in figures_module.ARMS}
    for arm, band in zip(figures_module.ARMS, bands, strict=True):
        vals = [r["warmup"][k]["end_to_end"] for r in by_arm[arm] for k in (-3, -2, -1)]
        expected = statistics.median(vals)
        assert band.get_y() == pytest.approx(expected * 0.9)
        assert band.get_y() + band.get_height() == pytest.approx(expected * 1.1)


def test_warmup_curve_steady_state_bands_are_colored_like_their_own_line(tmp_path):
    """A band drawn in the wrong arm's color (or a neutral gray shared by
    all three, the original pooled design) would be ambiguous about which
    curve it belongs to now that there are three. Each band's color must
    match its own arm's line color exactly."""
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    assert len(arm_lines) == len(bands) == 3
    for line, band in zip(arm_lines, bands, strict=True):
        assert mcolors.to_rgb(band.get_facecolor()[:3]) == mcolors.to_rgb(line.get_color())


def test_warmup_curve_per_arm_band_uses_all_of_that_arms_rows_not_just_the_first(tmp_path):
    """Same one-outlier-row concern as before, now scoped per arm: arm A's
    band must reflect all of arm A's rows, not just its first row. Give
    only arm A's first row a wildly different tail; a first-row-only
    computation would center arm A's band near 999, but the median across
    all of arm A's rows must stay well below that -- and arm B/C's bands,
    unaffected by an arm-A row, must stay near their own normal plateaus."""
    data = rows()
    for idx, r in enumerate(data):
        if r["arm"] == "A":
            data[idx] = dict(r)
            data[idx]["warmup"] = [dict(w) for w in r["warmup"]]
            for w in data[idx]["warmup"][-3:]:
                w["end_to_end"] = 999.0
            break

    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    arm_a_band, arm_b_band, arm_c_band = bands  # ARMS order is A, B, C
    assert arm_a_band.get_y() + arm_a_band.get_height() < 500.0
    assert arm_b_band.get_y() + arm_b_band.get_height() < 10.0
    assert arm_c_band.get_y() + arm_c_band.get_height() < 10.0


def test_warmup_curve_uses_the_shared_median_helper(tmp_path):
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        warmup_curve(rows(), tmp_path / "w.png")
    assert spy.called


# ---------------------------------------------------------------------------
# ecdf_plot
# ---------------------------------------------------------------------------


def test_ecdf_plot_one_step_series_per_arm(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    assert len(ax.lines) == 3


def test_ecdf_plot_legend_labels_carry_each_arms_n(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    _handles, labels = ax.get_legend_handles_labels()
    assert len(labels) == 3
    assert all("n=10" in lbl for lbl in labels)


def test_ecdf_plot_axes_start_at_zero_and_end_at_one(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    assert ax.get_xlim()[0] == 0
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    assert ylim == pytest.approx((0.0, 1.0))
    assert xlim[0] == pytest.approx(0.0)


def test_ecdf_plot_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    ecdf_plot(data, tmp_path / "e.png")
    assert data == before


def test_ecdf_plot_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        ecdf_plot([], tmp_path / "e.png")


def test_ecdf_plot_rejects_an_arm_with_no_rows(tmp_path):
    data = [r for r in rows() if r["arm"] != "A"]
    with pytest.raises(ValueError, match="A"):
        ecdf_plot(data, tmp_path / "e.png")


# ---------------------------------------------------------------------------
# per_host_medians
# ---------------------------------------------------------------------------


def test_per_host_medians_bar_count_matches_hosts(tmp_path):
    data = rows()  # host_id = f"h{i % 5}" -> 5 distinct hosts
    _fig, ax = _call_capturing_axes(per_host_medians, data, tmp_path / "h.png")
    assert len(ax.patches) == 5


def test_per_host_medians_xticklabels_carry_each_hosts_n(tmp_path):
    data = rows()  # 30 rows / 5 hosts = 6 rows per host
    _fig, ax = _call_capturing_axes(per_host_medians, data, tmp_path / "h.png")
    labels = [t.get_text() for t in ax.get_xticklabels()]
    assert len(labels) == 5
    for lbl in labels:
        assert "n=6" in lbl


def test_per_host_medians_shows_genuine_heterogeneity_not_a_flat_line(tmp_path):
    """Regression guard for the fixture: this figure exists to support the
    host-heterogeneity hypothesis (spec H4 -- host variance, not just
    within-stage variance, drives the tail). The original fixture pooled
    every host over a balanced 2/2/2 arm mix each, which made every host's
    median collapse to almost the same value (<5% spread) regardless of any
    real per-host effect -- a bug that erased host differences entirely
    would have been invisible against a chart that already looked flat."""
    _fig, ax = _call_capturing_axes(per_host_medians, rows(), tmp_path / "h.png")
    heights = [p.get_height() for p in ax.patches]
    avg = sum(heights) / len(heights)
    assert (max(heights) - min(heights)) / avg > 0.10


def test_per_host_medians_ylim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(per_host_medians, rows(), tmp_path / "h.png")
    assert ax.get_ylim()[0] == 0


def test_per_host_medians_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    per_host_medians(data, tmp_path / "h.png")
    assert data == before


def test_per_host_medians_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        per_host_medians([], tmp_path / "h.png")


def test_per_host_medians_uses_the_shared_median_helper(tmp_path):
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        per_host_medians(rows(), tmp_path / "h.png")
    assert spy.called


# ---------------------------------------------------------------------------
# sanity check on the fixture itself, so a broken fixture doesn't masquerade
# as a passing (but vacuous) test
# ---------------------------------------------------------------------------


def test_fixture_sanity_ten_rows_per_arm_five_hosts():
    data = rows()
    assert sorted({r["arm"] for r in data}) == ["A", "B", "C"]
    assert sum(1 for r in data if r["arm"] == "A") == 10
    assert len({r["host_id"] for r in data}) == 5
