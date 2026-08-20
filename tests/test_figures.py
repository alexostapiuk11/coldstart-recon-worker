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


def rows(n=30):
    out = []
    for i in range(n):
        arm = ["A", "B", "C"][i % 3]
        base = {"A": 160.0, "B": 95.0, "C": 60.0}[arm]
        out.append(
            {
                "arm": arm,
                "host_id": f"h{i % 5}",
                "t_total": base + i * 0.4,
                "t_platform": 18.0,
                "t_weights": base * 0.5,
                "s4_subphases": {"S4c": 6.0, "S4e": 12.0},
                "t_process": base - 18.0,
                "warmup": [{"req_index": k, "end_to_end": 2.0 * (1 + 2 * 0.55**k)} for k in range(10)],
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


def test_waterfall_unattributed_segment_floors_at_zero_instead_of_going_negative(tmp_path):
    """Arm C: t_process=42, t_weights=30, subphases sum to 18 -> raw
    unattributed would be -6. The chart must clamp to 0, not draw a
    negative-width bar."""
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    arm_c = ax.patches[10:15]
    assert arm_c[-1].get_width() == pytest.approx(0.0)


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


def test_warmup_curve_legend_labels_carry_each_arms_n(tmp_path):
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    _handles, labels = ax.get_legend_handles_labels()
    arm_labels = [lbl for lbl in labels if lbl != "steady-state band (±10%)"]
    assert len(arm_labels) == 3
    assert all("n=10" in lbl for lbl in arm_labels)


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


def test_warmup_curve_steady_state_band_uses_all_rows_not_just_the_first(tmp_path):
    """Steady state is computed from every row across every arm, not just
    `rows[0]` — a single row is one outlier away from anchoring the band
    incorrectly for curves compared across all three arms. Give row 0 (arm
    A) a wildly different tail; a rows[0]-only computation would center the
    band near 999, but the cross-row median must stay well below that."""
    data = rows()
    data[0] = dict(data[0])
    data[0]["warmup"] = [dict(w) for w in data[0]["warmup"]]
    for w in data[0]["warmup"][-3:]:
        w["end_to_end"] = 999.0

    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    band = next(p for p in ax.patches if p.get_label() == "steady-state band (±10%)")
    assert band.get_y() + band.get_height() < 500.0


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
