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
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pytest

import coldstart.analysis.figures as figures_module
from coldstart.analysis.figures import (
    MIN_PHONE_TEXT_PX,
    PHONE_WIDTH_PX,
    RESIDUAL_COLOR,
    ecdf_plot,
    per_host_medians,
    warmup_curve,
    waterfall,
)
from coldstart.analysis.metrics import steady_state_latency
from coldstart.analysis.pipeline import NotPublishableError

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

# Per-arm chronological stage breakdown, replacing the old {"S4c","S4e"}-only
# fixture now that waterfall() draws every named stage (B2 fix) instead of
# two hardcoded sub-phases plus a catch-all "unattributed" that silently
# absorbed S1, S4a/S4b/S4d, S5, and S6. Each arm's components are hand-picked
# to sum exactly to that arm's t_process (base - 18.0), leaving a small
# genuinely positive "unattributed within S4" remainder -- never a
# suspiciously exact zero, matching the spec's honesty claim.
#
# Arm C's S4b (compile term) is deliberately far smaller than A's and B's
# (1.5 vs 25.0 and 13.0) -- that shrink *is* H3/the compile-cache effect,
# and a fixture where every arm shared the same S4b could not distinguish
# "the effect was measured" from "the effect was silently dropped".
_STAGES = {
    "A": {
        "t_s1": 4.0,
        "t_weights": 80.0,
        "t_s4_bracket": 50.0,
        "subphases": {"S4a": 3.0, "S4b": 25.0, "S4c": 5.0, "S4d": 3.0, "S4e": 10.0},
        "t_s5": 6.0,
        "t_s6": 2.0,
    },
    "B": {
        "t_s1": 4.0,
        "t_weights": 47.5,
        "t_s4_bracket": 21.0,
        "subphases": {"S4a": 2.0, "S4b": 13.0, "S4c": 2.0, "S4d": 1.0, "S4e": 2.0},
        "t_s5": 3.0,
        "t_s6": 1.5,
    },
    "C": {
        "t_s1": 4.0,
        "t_weights": 30.0,
        "t_s4_bracket": 5.0,
        "subphases": {"S4a": 1.0, "S4b": 1.5, "S4c": 1.0, "S4d": 0.5, "S4e": 0.5},
        "t_s5": 2.0,
        "t_s6": 1.0,
    },
}


def rows(n=30):
    out = []
    for i in range(n):
        arm = ["A", "B", "C"][i % 3]
        host = f"h{i % 5}"
        base = {"A": 160.0, "B": 95.0, "C": 60.0}[arm]
        steady = _WARMUP_STEADY[arm]
        spike = _WARMUP_SPIKE[arm]
        st = _STAGES[arm]
        # Per-row jitter on top of the arm's shared curve shape (B5): without
        # this, every row of an arm has *exactly* the same warmup list, which
        # makes "pool every row's last three requests into one list and take
        # its median" and "take the median of each row's own last-three
        # median" numerically identical -- the two estimators only diverge
        # when rows differ from each other, and this fixture must be able to
        # tell them apart (see test_warmup_curve_steady_state_band_is_per_arm_not_pooled
        # below, which is pinned against this exact jitter).
        row_jitter = 0.05 * (i // 3)
        row = {
            "arm": arm,
            "host_id": host,
            "t_total": base + i * 0.4 + _HOST_OFFSET[host],
            "t_platform": 18.0,
            "t_process": base - 18.0,
            "t_s1": st["t_s1"],
            "t_weights": st["t_weights"],
            "t_s4_bracket": st["t_s4_bracket"],
            "t_s5": st["t_s5"],
            "t_s6": st["t_s6"],
            "warmup": [
                {"req_index": k, "end_to_end": steady + spike * 0.55**k + row_jitter}
                for k in range(10)
            ],
        }
        for key, val in st["subphases"].items():
            row[f"t_{key.lower()}"] = val
        out.append(row)
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


def test_waterfall_draws_every_named_stage_per_arm_with_residual_first_and_correct_stacking(
    tmp_path,
):
    """Pins the exact segment widths and left offsets for arm A (measured
    branch), derived by hand from the fixture (`_STAGES["A"]`):
    T_platform=18, S1=4, T_weights=80, S4a=3, S4b=25, S4c=5, S4d=3, S4e=10,
    unattributed = 50 - (3+25+5+3+10) = 4, S5=6, S6=2 -- 11 segments summing
    to 160, every one individually labelled (B2 fix: previously S1, S4a,
    S4b, S4d, S5 and S6 were all invisible, folded into a mislabelled
    'unattributed' bar). This catches a wrong stacking order or a wrong
    segment value, not just "some bars got drawn"."""
    data = rows()
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    assert len(ax.patches) == 33  # 3 arms x 11 segments

    residual_rgba = mcolors.to_rgba(RESIDUAL_COLOR)

    arm_a = ax.patches[0:11]
    assert arm_a[0].get_facecolor() == residual_rgba  # residual segment drawn first
    widths = [p.get_width() for p in arm_a]
    assert widths == pytest.approx([18.0, 4.0, 80.0, 3.0, 25.0, 5.0, 3.0, 10.0, 4.0, 6.0, 2.0])
    lefts = [p.get_x() for p in arm_a]
    assert lefts == pytest.approx(
        [0.0, 18.0, 22.0, 102.0, 105.0, 130.0, 135.0, 138.0, 148.0, 152.0, 158.0]
    )


def test_waterfall_arm_c_segments_are_pinned_with_a_much_smaller_compile_term(tmp_path):
    """Arm C (`_STAGES["C"]`): T_platform=18, S1=4, T_weights=30, S4a=1,
    S4b=1.5, S4c=1, S4d=0.5, S4e=0.5, unattributed = 5 - 4.5 = 0.5, S5=2,
    S6=1 -- summing to 60, a small but genuinely positive unattributed
    residual (the dedicated negative-term tests below cover the case that
    must raise instead of clamp). Arm C's S4b (index 4) is pinned at 1.5s,
    versus arm A's 25.0s and arm B's 13.0s -- the compile-cache effect must
    actually be visible as a shrinking segment, not just present as a
    number nobody plots."""
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    arm_a, arm_b, arm_c = ax.patches[0:11], ax.patches[11:22], ax.patches[22:33]
    widths_c = [p.get_width() for p in arm_c]
    assert widths_c == pytest.approx([18.0, 4.0, 30.0, 1.0, 1.5, 1.0, 0.5, 0.5, 0.5, 2.0, 1.0])

    s4b_a, s4b_b, s4b_c = arm_a[4].get_width(), arm_b[4].get_width(), arm_c[4].get_width()
    assert s4b_c < s4b_b < s4b_a
    assert s4b_c == pytest.approx(1.5)


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


def test_waterfall_text_is_legible_at_phone_width(tmp_path):
    """Supersedes a floor on absolute point sizes (title >= 13, ticks >= 10,
    legend >= 9). That guard could not do its job and did not: the waterfall
    was later widened from 8in to 10.9in to fit its legend, every one of those
    absolute floors still passed, and the arm labels dropped to 5.3px on a
    phone -- illegible. Point size alone never determined legibility; the ratio
    to figure width does. Asserted here for the waterfall specifically because
    it is the densest of the four and the one that regressed.
    """
    fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    width_in = fig.get_size_inches()[0]

    def rendered_px(pt):
        return pt * PHONE_WIDTH_PX / (72 * width_in)

    assert rendered_px(ax.title.get_fontsize()) >= 9.0
    assert rendered_px(ax.xaxis.label.get_fontsize()) >= MIN_PHONE_TEXT_PX
    for tick_label in ax.get_xticklabels() + ax.get_yticklabels():
        assert rendered_px(tick_label.get_fontsize()) >= MIN_PHONE_TEXT_PX

    # The legend belongs to the figure, not the axes -- centring it on the
    # axes pushed it off the right margin, because the arm labels inset the
    # axes from the canvas edge.
    assert ax.get_legend() is None
    (legend,) = fig.legends
    assert len(legend.get_texts()) >= 5
    for text in legend.get_texts():
        assert rendered_px(text.get_fontsize()) >= MIN_PHONE_TEXT_PX


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


def test_waterfall_raises_not_publishable_when_t_platform_is_missing(tmp_path):
    """B4: a row from a failed run (metrics.derive()'s 6-key row) has no
    `t_platform` key at all. Before the fix this was a bare KeyError from
    inside `median()`; it must now name the row and the field instead."""
    data = rows()
    del data[0]["t_platform"]
    with pytest.raises(NotPublishableError, match=r"has no 't_platform'"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_raises_not_publishable_when_t_platform_is_none(tmp_path):
    """B4: an inconsistent run's `t_platform` is `None`, not absent. Before
    the fix this reached `median()` and failed with a bare, context-free
    TypeError from inside math.isfinite."""
    data = rows()
    data[0]["t_platform"] = None
    with pytest.raises(NotPublishableError, match=r"'t_platform' = None"):
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
    """If the measured sub-phases exceed the S4 bracket that is supposed to
    contain them, the decomposition does not fit inside the thing it
    decomposes -- checks.py applies exactly this discipline to a single
    run's t_weights ("discard, don't silently correct"). A max(0.0, ...)
    clamp (the original behavior) would draw a plausible-looking but
    understated bar instead of surfacing the defect; this must raise, and
    name the offending arm."""
    data = rows()
    for r in data:
        if r["arm"] == "C":
            # arm C: t_s4_bracket=5.0; pushing S4b to 10.0 makes the
            # sub-phase sum 1+10+1+0.5+0.5=13.0, well past the bracket.
            r["t_s4b"] = 10.0
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
            r["t_s4b"] = 10.0
    with pytest.raises(ValueError, match=r"-8\.0"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_labels_a_fully_merged_subphase_rather_than_drawing_nothing(tmp_path):
    """A sub-phase the pinned engine version never delineates (every row in
    the arm reports it absent, not zero) must not silently vanish: its
    duration still belongs to *some* visible, named segment. It folds into
    'unattributed within S4' honestly (that's exactly what the bracket
    formula does), and the merge is stated in that segment's label rather
    than the chart just being short one bar with no explanation."""
    data = rows()
    for r in data:
        if r["arm"] == "B":
            r["t_s4d"] = None
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")

    # The legend still carries an "S4d" entry (arms A and C still delineate
    # it, and the legend is deduplicated by label text across arms) -- the
    # thing that must be visible instead is a distinct entry stating S4d
    # was merged into arm B's unattributed segment.
    _handles, labels = ax.get_legend_handles_labels()
    assert any("merged" in lbl.lower() and "S4d" in lbl for lbl in labels)

    # Arm B now draws one fewer segment than arm A (no standalone S4d bar).
    arm_a = ax.patches[0:11]
    arm_b = ax.patches[11:21]
    assert len(arm_a) == 11
    assert len(arm_b) == 10

    # Arm B, unattributed segment (index 7 -- one slot earlier than arm A's
    # index 8, since S4d's bar was skipped): bracket 21.0 minus the four
    # *present* sub-phases (2+13+2+2=19.0) = 2.0 -- S4d's missing 1.0s
    # folds in rather than silently shrinking the bar by 1.0s.
    assert arm_b[7].get_width() == pytest.approx(2.0)


def test_waterfall_handles_a_wholly_unmeasured_s4_bracket_without_crashing_or_substituting(
    tmp_path,
):
    """The probe emits S4_start/S4_end on every run, so this is the
    degraded case: a row that lost them. waterfall() must not crash, and it must not
    silently substitute S5_ready - S3_load_done (unavailable here, and
    wrong anyway -- see the spec's Attribution caveat and the dedicated
    metrics.py regression test). The whole S4+S5 span collapses to one
    honestly-labelled merged segment instead."""
    data = rows()
    for r in data:
        if r["arm"] == "A":
            r["t_s4_bracket"] = None
            r["t_s5"] = None
            for key in ("t_s4a", "t_s4b", "t_s4c", "t_s4d", "t_s4e"):
                r[key] = None
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")

    _handles, labels = ax.get_legend_handles_labels()
    assert any("merged" in lbl.lower() and "S4" in lbl for lbl in labels)
    assert not any(lbl.startswith("S4b") for lbl in labels[:6])  # no fake S4b for arm A

    # Arm A: process(142) - S1(4) - weights(80) - S6(2) = 56.0, the honest
    # combined S4+S5 remainder computable without the missing bracket mark.
    arm_a = ax.patches[0:5]  # platform, S1, weights, merged S4+S5, S6 (5 segments)
    assert len(arm_a) == 5
    assert arm_a[3].get_width() == pytest.approx(56.0)


# ---------------------------------------------------------------------------
# warmup_curve
# ---------------------------------------------------------------------------


def _arm_lines(ax):
    """The three per-arm curves, selected by their legend label.

    Not by marker: each arm now draws a different marker and dash pattern so
    that three curves which coincide to within a millisecond on real data stay
    individually readable. A selector keyed to one marker silently matched a
    single arm once that changed.
    """
    return [ln for ln in ax.lines if "n=" in (ln.get_label() or "")]


def test_warmup_curve_plots_the_number_of_requests_present_in_the_data(tmp_path):
    data = rows()  # every row has a 10-request warmup
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    arm_lines = _arm_lines(ax)
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
    arm_lines = _arm_lines(ax)
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
    arm_lines = _arm_lines(ax)
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


def test_warmup_curve_raises_not_publishable_when_warmup_is_missing(tmp_path):
    """B4: a failed run's row has no `warmup` key at all."""
    data = rows()
    del data[0]["warmup"]
    with pytest.raises(NotPublishableError, match="warmup"):
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
    this test.

    The three band centers are hand-computed literals, not a recomputation
    of the implementation's formula (`statistics.median` on pooled values,
    the pre-B5 version of this test): each arm's per-row last-three median
    is `steady + spike*0.55**k` for k in (7,8,9) plus that row's jitter
    (0, 0.05, ..., 0.45 across the arm's 10 rows -- see `rows()`); jitter
    shifts a row's three values equally, so it shifts that row's own median
    by the same amount. Sorting the resulting 10 per-row medians and
    averaging the two middle ones (arm has an even row count) gives the
    B5-correct band center -- metrics.py's per-run definition, aggregated
    across rows the same way the published T_fast table is. This is *not*
    the same number pooling all 30 raw values would give (see the dedicated
    divergence test below); using the old pooled formula here would fail.
    """
    data = rows()
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")

    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    assert len(bands) == 3  # one band per arm, not one pooled across all three

    expected_center = {
        "A": 3.254306878261719,
        "B": 2.245933484472656,
        "C": 1.4383974300625,
    }
    for arm, band in zip(figures_module.ARMS, bands, strict=True):
        center = expected_center[arm]
        assert band.get_y() == pytest.approx(center * 0.9)
        assert band.get_y() + band.get_height() == pytest.approx(center * 1.1)


def test_warmup_curve_band_matches_metrics_steady_state_not_a_pooled_median(tmp_path):
    """B5: the chart band must use exactly metrics.steady_state_latency's
    per-run definition, aggregated across an arm's rows -- not a pooled
    median over every row's combined last-three values. A fixture where
    every row of an arm shares one warmup curve cannot tell these two
    estimators apart (they're numerically identical there); this fixture
    is built so they disagree by a clean, hand-verified margin.

    Arm A: two rows plateau at [10, 20, 30] (median 20), one row plateaus at
    [100, 200, 300] (median 200). Per-run median-of-medians:
    median([20, 20, 200]) = 20 -- the correct, per-B5 answer. Pooling all
    nine raw values instead: sorted [10,10,20,20,30,30,100,200,300], median
    (5th of 9) = 30 -- what the pre-fix implementation would have drawn.
    """

    def warmup10(last3):
        # Only the last three values feed the steady-state estimator; the
        # first seven are irrelevant filler so the line/x-axis machinery has
        # ten points to plot.
        return [{"req_index": k, "end_to_end": 50.0} for k in range(7)] + [
            {"req_index": 7 + j, "end_to_end": v} for j, v in enumerate(last3)
        ]

    arm_a_rows = [
        {"arm": "A", "warmup": warmup10([10.0, 20.0, 30.0])},
        {"arm": "A", "warmup": warmup10([10.0, 20.0, 30.0])},
        {"arm": "A", "warmup": warmup10([100.0, 200.0, 300.0])},
    ]
    other_rows = [
        {"arm": "B", "warmup": warmup10([1.0, 1.0, 1.0])},
        {"arm": "C", "warmup": warmup10([1.0, 1.0, 1.0])},
    ]
    data = arm_a_rows + other_rows

    # Confirm the fixture matches the hand-derived numbers in the docstring
    # (the "table" side, independent of figures.py entirely).
    assert steady_state_latency(arm_a_rows[0]["warmup"]) == pytest.approx(20.0)
    assert steady_state_latency(arm_a_rows[2]["warmup"]) == pytest.approx(200.0)

    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    arm_a_band = bands[0]  # ARMS order is A, B, C
    center = (arm_a_band.get_y() + arm_a_band.get_y() + arm_a_band.get_height()) / 2
    assert center == pytest.approx(20.0)
    assert center != pytest.approx(30.0)  # the pooled estimator's (wrong) answer


def test_warmup_curve_collapses_t_fast_when_every_arm_shares_the_request(tmp_path):
    """Spec figures section: figure 2 must have T_fast annotated. When every
    arm reaches tolerance on the *same* request -- which is what the campaign
    actually produced, all three on request 1 -- annotating per arm stamped
    three identical labels on one point and laid one of them off the left edge
    of the canvas. The shared case collapses to a single label.

    One row per arm removes the median-across-rows step, so the annotated
    point is a hand-computed literal: steady = median(last three of
    [.., 3.2, 3.0, 3.0]) = 3.0, threshold = 3.0*1.1 = 3.3, and request 7
    (index 6, value 3.2) is the first request at or below it."""
    e2e = [10.0, 8.0, 6.0, 5.0, 4.0, 3.5, 3.2, 3.0, 3.0, 3.0]
    warmup = [{"req_index": k, "end_to_end": v} for k, v in enumerate(e2e)]
    data = [{"arm": a, "warmup": [dict(w) for w in warmup]} for a in ("A", "B", "C")]

    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")

    assert len(ax.collections) == 1
    (x, y) = ax.collections[0].get_offsets()[0]
    assert x == pytest.approx(7.0)
    assert y == pytest.approx(3.2)

    fast_texts = [t for t in ax.texts if "T_fast" in t.get_text()]
    assert len(fast_texts) == 1
    assert "7" in fast_texts[0].get_text()
    assert "all three arms" in fast_texts[0].get_text()


def test_warmup_curve_annotates_t_fast_per_arm_when_the_arms_differ(tmp_path):
    """The collapse is only for the shared case. Arms that reach tolerance on
    different requests each keep their own marker and label, because the
    figure is then reporting three distinct facts."""

    def curve(plateau_from):
        e2e = [10.0 - k for k in range(plateau_from)] + [3.0] * (10 - plateau_from)
        return [{"req_index": k, "end_to_end": v} for k, v in enumerate(e2e)]

    data = [
        {"arm": "A", "warmup": curve(3)},
        {"arm": "B", "warmup": curve(5)},
        {"arm": "C", "warmup": curve(7)},
    ]
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")

    assert len(ax.collections) == 3
    fast_texts = [t for t in ax.texts if "T_fast" in t.get_text()]
    assert len(fast_texts) == 3
    # Each label is offset *inward* from the edge it sits nearest, which is
    # what stops a T_fast on request 1 being laid out past the left margin.
    for txt in fast_texts:
        req = txt.xy[0]
        dx = txt.get_position()[0]
        assert (dx > 0) == (req <= 5.5), f"label for request {req} offset outward (dx={dx})"


def test_warmup_curve_steady_state_bands_are_colored_like_their_own_line(tmp_path):
    """A band drawn in the wrong arm's color (or a neutral gray shared by
    all three, the original pooled design) would be ambiguous about which
    curve it belongs to now that there are three. Each band's color must
    match its own arm's line color exactly."""
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    arm_lines = _arm_lines(ax)
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


def test_warmup_curve_band_width_tracks_metrics_fast_tolerance_not_a_hardcoded_duplicate(
    tmp_path,
):
    """B5: FAST_TOLERANCE must be routed from metrics.py into figures.py so
    the pre-registered tolerance exists in exactly one place. Before this
    fix, `warmup_curve` hardcoded the same 0.10 value as literal `0.9`/`1.1`
    multipliers -- a second copy of a pre-registered parameter, free to
    drift from `metrics.FAST_TOLERANCE` after data arrives. Patching the
    name `figures.py` actually reads and checking the drawn band widens
    accordingly is the only way to tell "reads the constant" apart from "a
    hardcoded literal that happens to equal the constant's current value" --
    both draw an identical band at the default 0.10."""
    with patch("coldstart.analysis.figures.FAST_TOLERANCE", 0.30):
        _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    center = 3.254306878261719  # arm A, same fixture/derivation as the test above
    assert bands[0].get_y() == pytest.approx(center * 0.70)
    assert bands[0].get_y() + bands[0].get_height() == pytest.approx(center * 1.30)


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


def test_ecdf_plot_raises_not_publishable_when_t_total_is_none(tmp_path):
    """B4: an inconsistent or warmup-incomplete run's `t_total` is `None`;
    before the fix this reached `ecdf()` and failed with a bare TypeError."""
    data = rows()
    data[0]["t_total"] = None
    with pytest.raises(NotPublishableError, match=r"'t_total' = None"):
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


def test_per_host_medians_raises_not_publishable_when_t_total_is_missing(tmp_path):
    """B4: a failed run's row has no `t_total` key at all."""
    data = rows()
    del data[0]["t_total"]
    with pytest.raises(NotPublishableError, match=r"has no 't_total'"):
        per_host_medians(data, tmp_path / "h.png")


# ---------------------------------------------------------------------------
# sanity check on the fixture itself, so a broken fixture doesn't masquerade
# as a passing (but vacuous) test
# ---------------------------------------------------------------------------


def test_fixture_sanity_ten_rows_per_arm_five_hosts():
    data = rows()
    assert sorted({r["arm"] for r in data}) == ["A", "B", "C"]
    assert sum(1 for r in data if r["arm"] == "A") == 10
    assert len({r["host_id"] for r in data}) == 5


# --- phone legibility -------------------------------------------------------


def test_every_figure_clears_the_phone_text_floor(tmp_path):
    """The post is read on phones, and a figure that is illegible there still
    renders, still passes every assertion about its data, and looks correct on
    the laptop it was written on. This module has shipped that defect twice --
    once fixed by enlarging the waterfall's text, then reintroduced when the
    waterfall was widened to fit its legend, which cancelled the enlargement
    exactly (`rendered_px = pt * 375 / (72 * width_in)`: the denominator grew
    with the numerator).

    Asserts the arithmetic directly on every text artist matplotlib will draw,
    so neither a smaller font nor a wider canvas can regress it silently.
    """
    renderers = (
        (waterfall, rows()),
        (warmup_curve, rows()),
        (ecdf_plot, rows()),
        (per_host_medians, rows()),
    )
    for render, data in renderers:
        fig, ax = _call_capturing_axes(render, data, tmp_path / "f.png")
        width_in = fig.get_size_inches()[0]

        texts = [(t.get_text(), t.get_fontsize()) for t in ax.texts]
        texts += [(ax.get_title(), ax.title.get_fontsize())]
        texts += [(ax.get_xlabel(), ax.xaxis.label.get_fontsize())]
        texts += [(ax.get_ylabel(), ax.yaxis.label.get_fontsize())]
        texts += [(lab.get_text(), lab.get_fontsize()) for lab in ax.get_xticklabels()]
        texts += [(lab.get_text(), lab.get_fontsize()) for lab in ax.get_yticklabels()]
        legend = ax.get_legend()
        if legend is not None:
            texts += [(t.get_text(), t.get_fontsize()) for t in legend.get_texts()]

        for label, pt in texts:
            if not label.strip():
                continue
            rendered_px = pt * PHONE_WIDTH_PX / (72 * width_in)
            assert rendered_px >= MIN_PHONE_TEXT_PX, (
                f"{render.__name__}: {label!r} renders at {rendered_px:.1f}px at phone "
                f"width ({pt:.1f}pt on a {width_in:.1f}in canvas); "
                f"floor is {MIN_PHONE_TEXT_PX}px"
            )


def test_figures_do_not_widen_the_canvas_on_save(tmp_path):
    """`bbox_inches="tight"` expands the written PNG past `figsize` by however
    much an outside-the-axes legend needs, making the true width -- the
    denominator the test above depends on -- unknowable from the code. That is
    how the waterfall's phone regression got in. Pin that the saved pixel width
    matches the declared figure width."""
    for render in (waterfall, warmup_curve, ecdf_plot, per_host_medians):
        out = tmp_path / f"{render.__name__}.png"
        fig, _ax = _call_capturing_axes(render, rows(), out)
        expected = round(fig.get_size_inches()[0] * 150)
        actual = mpimg.imread(out).shape[1]
        assert actual == expected, (
            f"{render.__name__}: saved {actual}px wide but figsize declares {expected}px"
        )
