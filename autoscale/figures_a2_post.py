"""The four figures of the artifact 2 post.

Every figure takes the parsed `data/a2/post-analysis.json` and nothing else, so
a number on a chart cannot drift from the number in the prose: both come out of
the analysis file, which `scripts/a2_post_analysis.py` owns. The drawing idioms
(phone-pixel font sizes, banner, note, colours) are `autoscale.figures`'s and
are imported rather than copied, so the post's figures keep that module's
legibility guarantees without a second set of constants to keep in step.
"""

import math
import statistics

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import FixedLocator, FuncFormatter

from autoscale.figures import (
    CENSOR_COLOR,
    CURVE_COLOR,
    FIG_HEIGHT_IN,
    FIG_WIDTH_IN,
    MEASURED_BANNER,
    MEASURED_BG,
    MODELED_BG,
    PX_BANNER,
    PX_LEGEND,
    PX_SUBTITLE,
    SIGNAL_COLOR,
    _figure_banner,
    _finish,
    _note,
    _pt,
    _tidy,
)

__all__ = ["host_speed", "load_balancer", "simulator_answer", "validation_attempts"]

# (analysis key, panel label). The label names what was different about the
# attempt, because the two panels' whole point is that the same gate was run
# twice and the sign of the error changed in between.
ATTEMPTS = (("engine", "uncalibrated"), ("calibrated", "host-calibrated"))
BIN_WIDTH_S = 10.0
# The y axis is symmetric-log. Attempt 1's residuals reach 6 s and attempt 2's
# sit near 0.05 s with a few bins to 1.3 s; on a linear axis wide enough for the
# first, the second is a flat line on zero and the change of sign -- the whole
# point of the figure -- cannot be seen (the first render did exactly that, with
# the sign carried only by an annotation). Linear inside +-0.01 s, which is
# below every residual in the data, so zero stays a line and no value is
# squashed into it.
SYMLOG_LINTHRESH_S = 0.01
Y_TICKS_S = [-6, -1, -0.1, 0, 0.1, 1, 6]


def _series(residuals) -> tuple[list[float], list[float]]:
    """x (bin centre) and residual, with a missing residual as NaN.

    NaN breaks the line; a null is "no residual on both sides", not "zero
    residual", and drawing it as zero would paint agreement over bins nobody
    compared. Centre rather than start, as `autoscale.figures`'s residual figure
    does, so the point sits in the middle of the bin it summarises.
    """
    xs = [start + BIN_WIDTH_S / 2 for start, _ in residuals]
    ys = [math.nan if value is None else value for _, value in residuals]
    return xs, ys


def _judged_residuals(attempt: dict) -> list[float]:
    """The residuals of the bins the gate judged, across all repeats.

    The analysis does not list the judged bins, but it pins them down: the
    gate's `bins_used` equals `bins_judged` equals `compared`, and a bin is
    only used when it has an ok p50 on both sides in every repeat. So the
    judged bins are exactly those with a residual in every repeat, and that
    count is checked against `compared` rather than trusted. Counting every
    non-null residual instead gave 111 for one attempt and 112 for the other,
    because a repeat can have a residual in a bin the gate did not judge.
    """
    repeats = [dict(map(tuple, repeat)) for repeat in attempt["residuals"]]
    judged = sorted(
        start for start in repeats[0] if all(r.get(start) is not None for r in repeats)
    )
    if len(judged) != attempt["compared"]:
        raise ValueError(
            f"{len(judged)} bins have a residual in every repeat but the gate judged "
            f"{attempt['compared']}; the judged bins cannot be recovered from the residuals"
        )
    return [r[start] for r in repeats for start in judged]


def validation_attempts(analysis: dict, path, *, return_figure=False):
    """Figure A: the same gate, run twice, and the residual changed sign.

    Left is the first attempt (simulator fed the service curve measured on one
    host), right the second (the curve rescaled by the host-speed ratio). Each
    draws the three repeats' residuals -- real p50 minus predicted p50, per
    10 s bin of engine arrival -- against engine arrival time. Attempt 1's
    residuals are negative (the real engine was faster than predicted),
    attempt 2's positive (slower). Both failed, in opposite directions, and
    that is the picture: calibrating moved the error across zero instead of
    removing it.

    The y axis is shared and symmetric about zero, so "below" and "above" are
    equally far and the two panels are on one scale. Rejected: a free y axis
    per panel, which would stretch attempt 2's residuals to attempt 1's height
    and hide that its excursions are smaller; and a plain linear shared axis,
    on which attempt 2 is a flat line on zero (see `SYMLOG_LINTHRESH_S`). The
    symmetric-log scale costs the picture its sense of proportion -- attempt 1's
    6 s dip no longer looks a hundred times attempt 2's bumps -- so the note
    says which scale it is and each panel prints its median residual in
    seconds.
    """
    validation = analysis["validation"]
    fig, axes = plt.subplots(1, 2, sharey=True, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    left, right = 0.09, 0.96
    fig.subplots_adjust(left=left, right=right, top=0.78, bottom=0.26, wspace=0.12)

    drawn = {}
    for k, (axis, (key, label)) in enumerate(zip(axes, ATTEMPTS, strict=True), start=1):
        attempt = validation[key]
        for repeat in attempt["residuals"]:
            xs, ys = _series(repeat)
            axis.plot(xs, ys, color=MEASURED_BANNER, linewidth=1.1, marker="o",
                      markersize=2.5, alpha=0.8, gid="residual_series")
        axis.axhline(0.0, color=CURVE_COLOR, linewidth=2, gid="zero")
        values = _judged_residuals(attempt)
        drawn[key] = [y for repeat in attempt["residuals"] for _, y in repeat if y is not None]
        below = sum(v < 0 for v in values)
        above = sum(v > 0 for v in values)
        side, count = ("below", below) if below >= above else ("above", above)
        axis.text(
            0.5,
            0.97 if side == "below" else 0.03,
            f"median residual {statistics.median(values):+.3f} s\n".replace("-", "−")
            + f"{count} of {len(values)} repeat-bins {side} zero",
            transform=axis.transAxes,
            ha="center",
            va="top" if side == "below" else "bottom",
            fontsize=_pt(PX_LEGEND),
            color=CURVE_COLOR,
        )
        axis.set_title(
            f"attempt {k}: {label}\n{attempt['misses']} of {attempt['compared']} misses",
            fontsize=_pt(PX_LEGEND), fontweight="bold", color=CURVE_COLOR)
        _tidy(axis, "engine arrival time (s)", "real − predicted p50 (s)" if k == 1 else "",
              MEASURED_BG)
        axis.set_xlim(0, 400)

    half = 1.15 * max(abs(y) for values in drawn.values() for y in values)
    # Set on one axes: `sharey` carries scale, limits and ticks to the other.
    axes[0].set_yscale("symlog", linthresh=SYMLOG_LINTHRESH_S, linscale=0.5)
    axes[0].set_ylim(-half, half)
    axes[0].yaxis.set_major_locator(FixedLocator(Y_TICKS_S))
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}".replace("-", "−")))
    compared = validation["engine"]["compared"]
    _note(axes[0], f"n={compared} judged bins × 3 repeats = {compared * 3} repeat-bins; counts use judged bins only\n"
                   "residual = real − predicted p50 per 10 s bin, binned by engine arrival\n"
                   "y axis: symmetric log, linear within ±0.01 s; ticks in seconds",
          y=-0.20)
    _figure_banner(fig, left, right, "MEASURED", "1 replica, 3 repeats per attempt",
                   MEASURED_BANNER)
    return _finish(fig, path, return_figure)


# Probe number -> (gid, colour, label) for the left panel. Probe 1 is the
# RunPod default scaler value; probe 2 is the same two workers at 128 with no
# 502 retry. Probe 3 (128, with retry) belongs to the right panel only: it
# repeats probe 2's throughput and adds nothing to the left panel but a third
# line on top of the second.
DELIVERY_PROBES = (
    ("1", "delivered_scaler_4", "#c0392b", "scaler value 4 (default)"),
    ("2", "delivered_scaler_128", "#2f6fd0", "scaler value 128"),
)
WORKER_COLOR = {"worker 1": SIGNAL_COLOR["queue_depth"], "worker 2": "#d98a1f"}
WORKER_CAP = 128
BAR_WIDTH = 0.38


def _steps(analysis: dict, probe: str) -> list[tuple[int, dict]]:
    """A probe's steps as (offered rate, step), in numeric order.

    The JSON keys are strings and sort as text ("100" < "25"), which would draw
    the bars in the wrong order and the delivered-rate line as a zigzag.
    """
    steps = analysis["load_balancer"]["probes"][probe]["steps"]
    return sorted(((int(rate), step) for rate, step in steps.items()))


def load_balancer(analysis: dict, path, *, return_figure=False):
    """Figure B: the load balancer's ceiling at scaler value 4, and its routing at 128.

    Left, delivered completions per second against offered rate. At the default
    scaler value of 4 the load balancer delivered about 17 req/s whatever was
    offered, and the requests it did not deliver waited inside it (client p50
    52 s, server p50 0.31 s), so the ceiling is the load balancer's and not the
    workers'. At 128 delivery tracks the dashed y = x line until the two
    workers saturate. Right, probe 3's in-flight requests per worker: worker 1
    is filled to the cap before worker 2 gets any.

    Rejected: plotting client p50 on the left, which is the same story in
    seconds but puts a 52 s point on an axis that flattens every other probe;
    and a stacked bar per rate for the two workers, which shows the split of
    requests but not that each worker's PEAK sits at the cap of 128, which is
    what "fills to the cap" means. Mean is the solid bar and peak the lighter
    bar behind it, so the cap line is crossed by peaks, not by averages that
    could never reach it.

    Both axes start at zero. The plateau is 17 on a 0-450 axis and is a low flat
    line, which is the honest size of it next to what scaler value 128 delivers.
    """
    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    left, right = 0.09, 0.97
    fig.subplots_adjust(left=left, right=right, top=0.78, bottom=0.36, wspace=0.28)
    ax_rate, ax_bars = axes

    # Left panel.
    offered_max = 0
    for probe, gid, color, label in DELIVERY_PROBES:
        steps = _steps(analysis, probe)
        xs = [rate for rate, _ in steps]
        ys = [step["delivered_rate_rps"] for _, step in steps]
        offered_max = max(offered_max, max(xs))
        ax_rate.plot(xs, ys, color=color, linewidth=2.2, marker="o", markersize=5,
                     label=label, gid=gid)
    ax_rate.plot([0, offered_max], [0, offered_max], color=CURVE_COLOR, linewidth=1.3,
                 linestyle="--", label="delivered = offered", gid="offered_equals_delivered")
    plateau = statistics.mean(
        step["delivered_rate_rps"] for _, step in _steps(analysis, "1"))
    # Direct labels, not a legend: a legend in a panel this small lands on the
    # lines it names (the first render did exactly that), and the plateau, which
    # is the point of the panel, is a low flat line a label can sit above.
    ax_rate.text(offered_max * 0.30, plateau + 22, f"scaler value 4:\nstuck at ~{plateau:.0f} req/s",
                 fontsize=_pt(PX_LEGEND), fontweight="bold", color=DELIVERY_PROBES[0][2],
                 ha="left", va="bottom")
    end = _steps(analysis, "2")[-1]
    ax_rate.text(offered_max * 0.99, 118, f"scaler value 128:\n{end[1]['delivered_rate_rps']:.0f} at {end[0]}",
                 fontsize=_pt(PX_LEGEND), fontweight="bold", color=DELIVERY_PROBES[1][2],
                 ha="right", va="bottom")
    ax_rate.text(offered_max * 0.02, offered_max * 0.97, "dashed: delivered = offered",
                 fontsize=_pt(PX_LEGEND), color=CURVE_COLOR, ha="left", va="top")
    ax_rate.set_title("delivered vs offered rate", fontsize=_pt(PX_LEGEND),
                      fontweight="bold", color=CURVE_COLOR)
    _tidy(ax_rate, "offered rate (req/s)", "delivered (req/s)", MEASURED_BG)
    ax_rate.set_xlim(0, offered_max * 1.03)
    ax_rate.set_ylim(0, offered_max * 1.03)

    # Right panel.
    steps3 = _steps(analysis, "3")
    for i, (rate, step) in enumerate(steps3):
        conc = step["per_worker_concurrency"]
        for j, worker in enumerate(("worker 1", "worker 2")):
            stats = conc.get(worker, {"mean": 0.0, "max": 0})
            x = i + (j - 0.5) * BAR_WIDTH
            tag = f"w{j + 1}"
            ax_bars.bar(x, stats["max"], BAR_WIDTH, color=WORKER_COLOR[worker], alpha=0.35,
                        gid=f"worker_bar_{tag}_peak_{rate}")
            ax_bars.bar(x, stats["mean"], BAR_WIDTH, color=WORKER_COLOR[worker],
                        gid=f"worker_bar_{tag}_mean_{rate}")
    ax_bars.axhline(WORKER_CAP, color=CURVE_COLOR, linewidth=1.4, linestyle="--", gid="cap_128")
    shares = [
        step["per_worker_concurrency"]["worker 1"]["requests"] / step["requests"]
        for _, step in steps3
    ]
    ax_bars.set_xticks(range(len(steps3)))
    ax_bars.set_xticklabels(
        [f"{rate}\n{share * 100:.0f}" for (rate, _), share in zip(steps3, shares, strict=True)])
    ax_bars.set_title("probe 3: in flight per worker\nsolid bar: mean, light bar: peak", fontsize=_pt(PX_LEGEND),
                      fontweight="bold", color=CURVE_COLOR)
    _tidy(ax_bars, "offered rate (req/s)\nbelow: % of requests to worker 1",
          "requests in flight", MEASURED_BG)
    ax_bars.xaxis.set_major_locator(FixedLocator(range(len(steps3))))
    ax_bars.set_xlim(-0.6, len(steps3) - 0.4)
    top = WORKER_CAP * 1.6
    ax_bars.set_ylim(0, top)
    ax_bars.text(0.03, 0.97, "the load balancer fills\nworker 1 to the cap\nbefore worker 2",
                 transform=ax_bars.transAxes, ha="left", va="top",
                 fontsize=_pt(PX_LEGEND), fontweight="bold", color=CURVE_COLOR)
    ax_bars.text(0.03, WORKER_CAP / top + 0.01, f"cap {WORKER_CAP}",
                 transform=ax_bars.transAxes, ha="left", va="bottom",
                 fontsize=_pt(PX_LEGEND), color=CURVE_COLOR)
    ax_bars.legend(
        handles=[Patch(color=WORKER_COLOR["worker 1"], label="worker 1"),
                 Patch(color=WORKER_COLOR["worker 2"], label="worker 2")],
        loc="upper left", bbox_to_anchor=(0.0, 0.58), fontsize=_pt(PX_LEGEND),
        frameon=False, handlelength=1.0, borderaxespad=0.3)

    requests = [step["requests"] for _, step in steps3]
    rates = [rate for rate, _ in steps3]
    rates_1 = [rate for rate, _ in _steps(analysis, "1")]
    leg = analysis["load_balancer"]["per_worker_concurrency_return_leg_s"]
    _note(ax_rate,
          f"N = requests per step: {min(requests):,} at {min(rates)} req/s up to "
          f"{max(requests):,} at {max(rates)} req/s\n"
          f"probe 1: scaler 4, ran {rates_1[0]}-{rates_1[-1]} req/s only. "
          f"Probes 2, 3: scaler 128 (3: 502 retry)\n"
          f"In-flight counts use reconstructed server intervals (return_leg_s = {leg}):\n"
          f"each ends {leg} s before the client saw the response; length = stamped server latency",
          y=-0.41)
    _figure_banner(fig, left, right, "MEASURED",
                   "RunPod load-balancing endpoint, 2 workers, probes run 2026-10-05",
                   MEASURED_BANNER)
    return _finish(fig, path, return_figure)


HOST_LEVELS = ("32", "64", "128")
# (analysis key, gid, colour, marker, x offset, legend label). The two exploratory sweeps are
# the same host at two --max-num-seqs values; they get two colours and markers and are nudged
# apart on x so their min-max bars do not overlap.
EXPLORATORY_SWEEPS = (
    ("maxseqs128", "128", SIGNAL_COLOR["queue_depth"], "o", -0.16),
    ("maxseqs256", "256", SIGNAL_COLOR["in_flight_concurrency"], "s", 0.0),
)
CALIBRATED_COLOR = "#d98a1f"
CALIBRATED_OFFSET = 0.2
CALIBRATED_SPREAD = 0.045
RATIO_YLIM = (0.75, 1.05)


def host_speed(analysis: dict, path, *, return_figure=False):
    """Figure C: how fast three RunPod hosts were, relative to the host the curve came from.

    The simulator models one host's speed (the one the service curve was measured on);
    RunPod assigns hosts at random. y is that host's median server latency over the curve's
    at the same concurrency, so 1.0 is the curve's own host and below 1.0 is faster than the
    curve. `daps3haubwrzbn` was re-measured in two exploratory sweeps (median over 3 runs per
    level, bars min to max); `sef5s24viyecyr` is the host of the calibrated validation
    attempt, one point per calibrated repeat at the two concurrencies it was measured at.

    The y axis runs 0.75-1.05, not from zero, and the note says so. This is the
    deliberate exception to the module's zero-based rule: every point is a ratio within
    0.18 of 1, so on an axis from 0 the three hosts and the reference line are one smear
    at the top of the panel. The truncation is stated rather than hidden, and the reference
    line is drawn so the comparison is against 1.0 and not against the axis floor.

    Rejected: a bar chart of ratios (bars from a floor of 0.75 would read as sizes);
    plotting seconds (the three concurrencies span 0.38-0.61 s, which would bury the
    4-18% differences this figure exists to show); and a legend-free draw with direct
    labels, which collides at 375 px because the three series share the same 0.82-0.96 band.
    The x axis is categorical: 32, 64, 128 are the levels measured, not a scale to read
    between.
    """
    host = analysis["host_speed"]
    curve_hosts = sorted({h for hosts in host["curve_hosts"].values() for h in hosts})
    curve_host = " / ".join(curve_hosts)
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    left, right = 0.11, 0.96
    fig.subplots_adjust(left=left, right=right, top=0.80, bottom=0.38)
    xs_of = {level: i for i, level in enumerate(HOST_LEVELS)}

    ax.axhline(1.0, color=CURVE_COLOR, linewidth=2, gid="curve_host")
    ax.text(len(HOST_LEVELS) - 0.55, 1.008, f"{curve_host} (the curve)", ha="right", va="bottom",
            fontsize=_pt(PX_LEGEND), fontweight="bold", color=CURVE_COLOR)

    handles = []
    for key, seqs, color, marker, offset in EXPLORATORY_SWEEPS:
        (host_id, levels), = host["exploratory"][key].items()
        xs = [xs_of[lv] + offset for lv in HOST_LEVELS]
        mid = [levels[lv]["ratio"] for lv in HOST_LEVELS]
        lo = [levels[lv]["ratio"] - levels[lv]["ratio_min"] for lv in HOST_LEVELS]
        hi = [levels[lv]["ratio_max"] - levels[lv]["ratio"] for lv in HOST_LEVELS]
        ax.errorbar(xs, mid, yerr=[lo, hi], color=color, marker=marker, markersize=7,
                    linestyle="none", capsize=5, elinewidth=2, gid=f"{host_id}_{seqs}")
        handles.append(Line2D([], [], color=color, marker=marker, markersize=7, linestyle="-",
                              label=f"{host_id}, max-num-seqs {seqs}: median, min–max"))
    for host_id, levels in host["calibrated_ratios_by_host"].items():
        for level, ratios in levels.items():
            n = len(ratios)
            for r, ratio in enumerate(ratios):
                x = xs_of[level] + CALIBRATED_OFFSET + (r - (n - 1) / 2) * CALIBRATED_SPREAD
                ax.plot([x], [ratio], marker="D", markersize=7, color=CALIBRATED_COLOR,
                        linestyle="none", gid=host_id)
        handles.append(Line2D([], [], color=CALIBRATED_COLOR, marker="D", markersize=7,
                              linestyle="none",
                              label=f"{host_id}: one point per calibrated repeat (64, 128)"))

    ax.set_title("server-side latency ÷ the curve's (1.0 = the curve's host)", fontsize=_pt(PX_LEGEND),
                 fontweight="bold", color=CURVE_COLOR)
    _tidy(ax, "concurrency", "latency ratio to the curve", MEASURED_BG)
    ax.set_xticks(range(len(HOST_LEVELS)))
    ax.set_xticklabels(HOST_LEVELS)
    ax.xaxis.set_major_locator(FixedLocator(range(len(HOST_LEVELS))))
    ax.set_xlim(-0.5, len(HOST_LEVELS) - 0.45)
    ax.set_ylim(*RATIO_YLIM)
    # MaxNLocator's pick (0.88, 0.96, 1.04) puts no tick on 1.0, the one value the axis is about.
    ax.yaxis.set_major_locator(FixedLocator([0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05]))
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.19),
              fontsize=_pt(PX_LEGEND), frameon=False, borderaxespad=0.0)
    _note(ax, "ratio axis starting at 0.75, not 0: a ratio near 1 is unreadable on an axis from 0\n"
              "N: 3 runs per level (daps3haubwrzbn, each sweep); 3 repeats (sef5s24viyecyr)\n"
              "4 hosts seen, 3 measured; not a distribution",
          y=-0.60)
    _figure_banner(fig, left, right, "MEASURED",
                   "server-side latency on 3 RunPod hosts, relative to the curve's host",
                   MEASURED_BANNER)
    return _finish(fig, path, return_figure)


# Engine speed -> (gid-neutral label, colour, line style, marker, x offset, linewidth). x1.00 is
# the committed curve, the only one pre-registration covers, so it is the heaviest and darkest;
# the other two are exploratory and are drawn lighter, dashed or dotted. Colour AND line style
# separate them, so the three survive greyscale. The offsets nudge each speed sideways so the
# intervals, which overlap in the step panel (x0.88 and x1.12 sit 0.12 s apart at arm C), do not
# draw over one another.
ENGINE_SPEEDS = (
    ("1", "x1.00 (committed)", CURVE_COLOR, "-", "o", 0.0, 3.0),
    ("0.88", "x0.88 (exploratory)", "#2f6fd0", "--", "s", -0.07, 1.8),
    ("1.12", "x1.12 (exploratory)", "#d98a1f", ":", "D", 0.07, 1.8),
)
GAP_PANELS = (("step", "arm A", "arm C"), ("ramp", "ramp arm A", "ramp arm C"))
H3_MARKER_DX = 0.2


def _stamp(fig, left: float, right: float, word: str, subtitle: str) -> None:
    """The SIMULATED banner: red text on a hatched strip, in figure coordinates.

    The measured figures carry a solid white-on-green strip (`_figure_banner`). This one
    must not look like that family at a glance, so the strip is hatched in CENSOR_COLOR and
    the words are CENSOR_COLOR on an opaque white plate, which keeps them legible over the
    hatching. Rejected: reusing `_figure_banner` with CENSOR_COLOR, which would make the
    unvalidated figure the same solid slab as the measured ones in a different colour.
    """
    fig.add_artist(Rectangle((left, 0.925), right - left, 0.065, transform=fig.transFigure,
                             facecolor="white", edgecolor=CENSOR_COLOR, hatch="////",
                             linewidth=1.5, zorder=5))
    fig.text((left + right) / 2, 0.9575, word, ha="center", va="center",
             fontsize=_pt(PX_BANNER), fontweight="bold", color=CENSOR_COLOR, zorder=6,
             bbox={"facecolor": "white", "edgecolor": "none", "pad": 4})
    fig.text((left + right) / 2, 0.915, subtitle, ha="center", va="top",
             fontsize=_pt(PX_SUBTITLE), color=CENSOR_COLOR)


def simulator_answer(analysis: dict, path, *, return_figure=False):
    """Figure D: what the simulator says about H3, drawn so it cannot be read as a finding.

    H3 (the pre-registered headline) needed the p99 gap between the best and worst
    autoscaling signal at equal spend to at least halve from arm A's cold starts to arm C's,
    under both step and ramp traffic. Left step, right ramp; x is the arm (A: slow cold
    starts, C: fast) at its measured median lag; y is the gap in seconds, one line per
    engine speed. The committed x1.00 line rises in both panels, and on the step every speed
    rises. A hollow marker at arm C shows where H3 needed the x1.00 line to land.

    The simulator failed its pre-registered validation twice (engine latency 14% below its
    prediction, then 13% above after calibrating to the host), so the answer is stamped on
    the figure itself and not only in the prose. The x0.88 and x1.12 lines are an
    exploratory sensitivity check, not pre-registered: they bracket the validation errors.

    Rejected: a numeric x axis in seconds, which would put arm C (39 s) LEFT of arm A (81 s)
    and draw the pre-registered A-to-C contrast right to left, for two points; and a shared
    y axis if it hides the step panel (see the note on the axes below). The iso-cost budget
    is utilisation's floor, which sits at the 12-replica cap, so the slice does not
    constrain queue depth or in-flight; the note says so.
    """
    sim = analysis["simulator"]
    gaps, cold = sim["gaps"], sim["cold_start"]
    identity, noise = sim["identity"], sim["h2_noise"]["per_sweep"]
    fig, axes = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    left, right = 0.09, 0.97
    fig.subplots_adjust(left=left, right=right, top=0.76, bottom=0.46, wspace=0.28)

    for axis, (shape, tag_a, tag_c) in zip(axes, GAP_PANELS, strict=True):
        for factor, _label, color, style, marker, dx, width in ENGINE_SPEEDS:
            pts = [gaps[factor][tag_a], gaps[factor][tag_c]]
            xs = [0 + dx, 1 + dx]
            ys = [p["point"] for p in pts]
            axis.errorbar(xs, ys, yerr=[[p["point"] - p["lo"] for p in pts],
                                        [p["hi"] - p["point"] for p in pts]],
                          fmt="none", ecolor=color, elinewidth=width * 0.8, capsize=4,
                          zorder=2)
            axis.plot(xs, ys, color=color, linestyle=style, linewidth=width, marker=marker,
                      markersize=7 if factor == "1" else 5.5, zorder=3, gid="gap_series")
        needed = gaps["1"][tag_a]["point"] / 2
        axis.plot([1 + H3_MARKER_DX], [needed], marker="<", markersize=9, markerfacecolor="none",
                  markeredgecolor=CENSOR_COLOR, markeredgewidth=2, linestyle="none",
                  zorder=4, clip_on=False, gid="h3_needed")
        a, c = gaps["1"][tag_a]["point"], gaps["1"][tag_c]["point"]
        axis.set_title(f"{shape} traffic\nx1.00 gap: {a:.2f} s to {c:.2f} s",
                       fontsize=_pt(PX_LEGEND), fontweight="bold", color=CURVE_COLOR)
        _tidy(axis, "cold start (measured median)",
              "gap between best and worst signal (s)" if shape == "step" else "", MODELED_BG)
        axis.set_xticks([0, 1])
        axis.set_xticklabels([f"arm A\n{cold['A']['median']:.0f} s median",
                              f"arm C\n{cold['C']['median']:.0f} s median"])
        axis.xaxis.set_major_locator(FixedLocator([0, 1]))
        axis.set_xlim(-0.35, 1 + H3_MARKER_DX + 0.2)
        top = max(g["hi"] for tag in (tag_a, tag_c) for g in (gaps[f][tag] for f in gaps))
        axis.set_ylim(0, top * 1.08)

    handles = [Line2D([], [], color=color, linestyle=style, linewidth=width, marker=marker,
                      markersize=6, label=label)
               for _f, label, color, style, marker, _dx, width in ENGINE_SPEEDS]
    handles.append(Line2D([], [], color=CENSOR_COLOR, marker="<", markersize=9,
                          markerfacecolor="none", markeredgewidth=2, linestyle="none",
                          label="H3 needed at arm C: half of arm A's x1.00 gap"))
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.535, 0.325), ncol=2,
               fontsize=_pt(PX_LEGEND), frameon=False, borderaxespad=0.0,
               columnspacing=1.2, handlelength=2.4)
    budget = sim["sweeps"]["arm A"]["budget_replica_s"]
    reps = identity["repetitions"]
    constrained = [t for t, n in noise.items() if n["iso_cost_slice_constrains_others"]]
    caveat = ("it does not constrain queue depth or in-flight" if not constrained
              else f"it constrains the other signals in: {', '.join(constrained)}")
    _note(axes[0],
          "exploratory sensitivity (x0.88, x1.12) not pre-registered;\n"
          "the simulator failed its validation twice\n"
          f"N = {reps} paired repetitions per gap; bars: 95% bootstrap interval\n"
          "y axes differ between panels, both start at 0\n"
          f"iso-cost budget {budget:,.0f} replica-s = utilisation's floor at the "
          f"{identity['max_replicas']}-replica cap;\n{caveat}",
          y=-0.80)
    grew = sum(gaps[f]["arm C"]["point"] > gaps[f]["arm A"]["point"] for f in gaps)
    every = "all three" if grew == len(gaps) else f"{grew} of {len(gaps)}"
    _stamp(fig, left, right, "SIMULATED · FAILED VALIDATION",
           "H3 needed the gap to halve from arm A to arm C.\n"
           f"On the step it grew at {every} engine speeds.")
    return _finish(fig, path, return_figure)
