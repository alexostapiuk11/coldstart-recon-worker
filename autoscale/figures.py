"""Artifact 2's body figures.

Same constraints as artifact 1: no truncated axes, N stated on the figure,
legible at phone width, no series silently dropped, and rendered output looked
at by a human before anything is called done.

The convergence figure carries the artifact's argument and has one job artifact
1's figures did not: it puts measured and modeled results side by side, so the
boundary between them has to be visible ON the chart. A reader who only looks at
figures must not come away believing the swept-lag panel was measured. That
boundary is drawn four ways, because each one alone fails for some reader: a
coloured banner strip over each panel (survives skimming), the words MEASURED
and NOT MEASURED in those strips (survives greyscale), a background tint per
panel (survives a glance too fast to read anything), and a rule down the middle
of the canvas (survives cropping one panel out of the other).

TEXT BUDGET, which drove the layout and is the reason the labels are terse.
Artifact 1's `phone_pt` relation is `px = pt * 375 / (72 * width_in)`, so figure
WIDTH cancels: widening the canvas to fit more words shrinks every word by
exactly the room it gained. At the `MIN_PHONE_TEXT_PX` floor that leaves roughly
90 characters across the whole figure, ~45 per panel, no matter what
`FIG_WIDTH_IN` says. The first draft of this module ignored that and rendered
two banners clipped off both canvas edges, a legend hanging past the left edge
and covering the measured frontier, and axes collapsed to a sliver by
`tight_layout` trying to make room for it all. Height is the free dimension --
it does not enter the relation at all -- so this figure is tall rather than
wide, the legend is one shared row under both panels rather than a box on top of
the data, and margins are set explicitly instead of by `tight_layout`, which
cannot see the out-of-axes artists and collapses the axes rather than the
labels.

Refusals rather than best-effort drawing, in four places:

- `frontiers` refuses a `by_signal` missing any of the three signals. A chart
  that appears to compare three signals while showing two is a misleading
  chart, not a smaller one. This is not hypothetical: against the placeholder
  service curve, queue depth never crosses even its lowest threshold, and this
  guard is what stops that becoming a published two-signal chart.
- `convergence` refuses arms whose signal sets differ. Arm A and arm C are the
  two halves of one comparison; a signal drawn on one arm and absent from the
  other still renders, and reads as though both arms were compared on the same
  signals with the missing one simply overlapping.
- `convergence` refuses an empty arm, and refuses an empty sweep. Both draw a
  blank panel that reads as "the model showed nothing" rather than "nothing was
  run".
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

from autoscale.frontier import pareto_frontier

__all__ = ["SIGNAL_ORDER", "convergence", "frontiers"]

SIGNAL_ORDER = ("queue_depth", "in_flight_concurrency", "utilization")
# Short enough to survive the text budget above. The long forms live in the
# caption; these have to fit next to two others in one legend row.
SIGNAL_LABEL = {
    "queue_depth": "queue depth",
    "in_flight_concurrency": "in-flight conc.",
    "utilization": "GPU util.",
}
SIGNAL_COLOR = {
    "queue_depth": "#2f6fd0",
    "in_flight_concurrency": "#2f7d32",
    "utilization": "#c0392b",
}
UNKNOWN_SIGNAL_COLOR = "#555555"

FIG_WIDTH_IN = 11.0
FIG_HEIGHT_IN = 8.0
MEASURED_BG = "#eef7ee"
MODELED_BG = "#e8f1ff"
MEASURED_BANNER = "#2f6b34"
MODELED_BANNER = "#1f4f9e"
NOTE_COLOR = "#3f3f3f"

# Figure-x of the measured panel's centre, given the `subplots_adjust` below.
# matplotlib sizes each column as (right - left) / (ncols + wspace).
LEFT_PANEL_CENTRE = 0.095 + (0.985 - 0.095) / (2 + 0.30) / 2

# Arm A and arm C are separated by line STYLE as well as by legend text, so the
# measured panel survives greyscale printing and colourblind readers: colour
# alone encodes the signal there, and without a second channel the panel would
# show pairs of indistinguishable lines.
ARM_STYLE = {"A": "-", "C": "--"}
ARM_LABEL = {"A": "arm A (p50 81 s)", "C": "arm C (p50 39 s)"}

# Phone pixels, converted to points by `_pt`. MIN_PHONE_TEXT_PX is 7.5; nothing
# here is written below 7.8, so a small edit cannot slide a label under the
# floor without the legibility test noticing.
PX_BANNER = 10.0
PX_SUBTITLE = 8.4
PX_AXIS_LABEL = 8.4
PX_TICK = 7.9
PX_LEGEND = 8.2
PX_NOTE = 7.9


def _pt(px: float) -> float:
    """Point size rendering at `px` pixels once downscaled to 375 px width.

    Every size in this module is written in phone pixels and converted here,
    rather than as a point size that silently changes meaning the moment
    `FIG_WIDTH_IN` is edited. See the text-budget note in the module docstring.
    """
    return px * 72 * FIG_WIDTH_IN / 375


def _ordered(signals) -> list[str]:
    """Known signals in the canonical order, then anything unrecognised, so the
    legend order does not depend on dict insertion order -- which is the sweep's
    iteration order, not a publication decision."""
    known = [s for s in SIGNAL_ORDER if s in signals]
    return known + sorted(s for s in signals if s not in SIGNAL_ORDER)


def _banner(axis, word: str, subtitle: str, color: str) -> None:
    """The measured/modeled label as a full-width strip above the panel.

    A `bbox` on a text artist hugs the text, so a long label produces a badge
    wider than the panel that is then clipped at the canvas edge -- which is
    exactly what the first draft did. A rectangle in axes coordinates is pinned
    to the panel's own width instead, and the word inside it is kept short
    enough to fit that width at `PX_BANNER`.
    """
    axis.add_patch(
        Rectangle(
            (0.0, 1.10),
            1.0,
            0.115,
            transform=axis.transAxes,
            facecolor=color,
            edgecolor="none",
            clip_on=False,
            zorder=5,
        )
    )
    axis.text(
        0.5,
        1.1575,
        word,
        transform=axis.transAxes,
        ha="center",
        va="center",
        fontsize=_pt(PX_BANNER),
        fontweight="bold",
        color="white",
        zorder=6,
    )
    axis.text(
        0.5,
        1.025,
        subtitle,
        transform=axis.transAxes,
        ha="center",
        va="bottom",
        fontsize=_pt(PX_SUBTITLE),
        color=color,
    )


def _note(axis, text: str, y: float = -0.20) -> None:
    """N, stated under the axes rather than inside them.

    Inside the axes it sits on the frontier's cheap end, which is where the
    interesting curvature is; under them it cannot cover data at any zoom. `y`
    is in axes coordinates and has to clear whatever else was put below the
    axes -- on the frontier figure that is the legend, and the first draft
    printed this line straight across its first entry.
    """
    axis.text(
        0.0,
        y,
        text,
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=_pt(PX_NOTE),
        color=NOTE_COLOR,
    )


def _span(values) -> str:
    """The numeric range the y axis is showing, as words.

    A zero-based axis is the repo's rule and it is the right rule -- but it has
    a cost this module hit on its first render against real sweep output: when
    every frontier sits near 39 s, all three are drawn as one hairline at the
    top of a mostly empty panel, and the picture reads as "identical" when the
    truth is "within 0.6 s of each other". Truncating the axis to spread them
    out is the dishonest fix; stating the range in words is the honest one, and
    it is information the picture cannot carry at any scale.
    """
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return f"all frontiers at p99 {low:.3g} s"
    return f"p99 spans {low:.3g}–{high:.3g} s"


def _tidy(axis, xlabel: str, ylabel: str, facecolor: str) -> None:
    axis.set_facecolor(facecolor)
    axis.set_xlabel(xlabel, fontsize=_pt(PX_AXIS_LABEL))
    axis.set_ylabel(ylabel, fontsize=_pt(PX_AXIS_LABEL))
    axis.tick_params(labelsize=_pt(PX_TICK))
    # Few ticks, because a tick label at the legibility floor is wide: the
    # default locator packs enough of them to overlap into a grey smear.
    axis.xaxis.set_major_locator(MaxNLocator(nbins=4))
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5))
    # Both frontier axes are ratio-scale quantities with a real zero. Letting
    # matplotlib pick a floor above zero exaggerates every difference drawn on
    # them, which is the entire comparison.
    axis.set_ylim(bottom=0)
    axis.set_xlim(left=0)


def _finish(fig, path, return_figure):
    fig.savefig(path, dpi=100)
    if return_figure:
        return fig
    plt.close(fig)
    return Path(path)


def convergence(frontiers_a, frontiers_c, swept, path, return_figure=False):
    """Figure 1. Left panel measured, right panel modeled, boundary on the chart."""
    if not frontiers_a or not frontiers_c:
        raise ValueError(
            "no frontiers for arm A and/or arm C; an empty arm draws a blank "
            "panel beside a full one, which reads as 'this arm showed nothing' "
            "rather than 'this arm was never run'"
        )
    only_a = sorted(set(frontiers_a) - set(frontiers_c))
    only_c = sorted(set(frontiers_c) - set(frontiers_a))
    if only_a or only_c:
        raise ValueError(
            f"arm A and arm C were swept over different signals "
            f"(only in A: {only_a}, only in C: {only_c}); the measured panel "
            "would draw both arms as though they were compared on the same "
            "signals, with the missing one invisible rather than reported"
        )
    if not swept:
        raise ValueError(
            "swept is empty; the modeled panel would render as an empty axes, "
            "which reads as 'the lag sweep found no effect' rather than 'the "
            "lag sweep was not run'"
        )

    fig, (left, right) = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    # Explicit margins, not `tight_layout`: the banners, the notes and the
    # shared legend all live outside the axes, and `tight_layout` shrinks the
    # axes to nothing trying to account for them.
    fig.subplots_adjust(left=0.095, right=0.985, top=0.815, bottom=0.365, wspace=0.30)

    signals = _ordered(frontiers_a)
    n_a = sum(len(v) for v in frontiers_a.values())
    n_c = sum(len(v) for v in frontiers_c.values())

    for arm, data in (("A", frontiers_a), ("C", frontiers_c)):
        for signal in signals:
            front = pareto_frontier(data[signal])
            left.plot(
                [p.cost for p in front],
                [p.p99 for p in front],
                ARM_STYLE[arm],
                marker="o",
                markersize=5,
                linewidth=2,
                color=SIGNAL_COLOR.get(signal, UNKNOWN_SIGNAL_COLOR),
                label=f"{SIGNAL_LABEL.get(signal, signal)} {arm}",
            )
    _tidy(left, "cost (replica-seconds)", "p99 request latency (s)", MEASURED_BG)
    _banner(left, "MEASURED", "artifact 1's two lag arms", MEASURED_BANNER)
    measured_p99 = [p.p99 for data in (frontiers_a, frontiers_c) for v in data.values() for p in v]
    # Two lines, not one: the panel is half the canvas and the guards caught
    # the single-line version spilling past it and into the modeled panel's own
    # note.
    _note(left, f"n={n_a + n_c} policy points ({n_a} A, {n_c} C)\n{_span(measured_p99)}")

    lags = sorted(swept)
    right.plot(
        lags, [swept[k] for k in lags], "o-", markersize=5, linewidth=2, color=MODELED_BANNER
    )
    _tidy(right, "cold-start lag (s)", "inter-signal gap (s)", MODELED_BG)
    # "NOT MEASURED" rather than "MODELED" as the banner word: at a glance
    # MEASURED and MODELED differ by two letters and read as the same word, so
    # the strip that is supposed to make the boundary unmissable would be the
    # least legible part of it. "modeled" is still stated, in the subtitle.
    _banner(right, "NOT MEASURED", "modeled: lag swept, invented", MODELED_BANNER)
    _note(right, f"n={len(lags)} modeled lag values")

    # Proxy handles, because the measured panel draws one line per
    # (signal, arm) and a legend with an entry for each is both wider than the
    # panel and redundant: colour carries the signal, line style carries the
    # arm, so they are shown as two independent keys instead of their product.
    handles = [
        Line2D([], [], color=SIGNAL_COLOR.get(s, UNKNOWN_SIGNAL_COLOR), linewidth=3,
               label=SIGNAL_LABEL.get(s, s))
        for s in signals
    ] + [
        Line2D([], [], color="#333333", linewidth=2, linestyle=ARM_STYLE[a], label=ARM_LABEL[a])
        for a in ("A", "C")
    ]
    # Anchored under the MEASURED panel, not centred on the whole figure: every
    # key in it describes that panel. Centred, it would sit under the modeled
    # panel too and invite the single navy line there to be read as one of the
    # three signals.
    # Two columns, not three: at the legibility floor three keys in a row are
    # wider than the panel they sit under and the first one runs off the canvas.
    # Rows are cheap here -- figure HEIGHT does not enter the phone-legibility
    # relation at all, so vertical space is the one dimension that is free.
    for anchor_y, subset in (
        (0.070, handles[: len(signals)]),
        (0.010, handles[len(signals) :]),
    ):
        fig.legend(
            handles=subset,
            loc="lower center",
            bbox_to_anchor=(LEFT_PANEL_CENTRE, anchor_y),
            ncol=2,
            fontsize=_pt(PX_LEGEND),
            frameon=False,
        )

    # The boundary as structure, not only as colour: a rule down the middle of
    # the canvas, so the two halves stay distinguishable if one is cropped out
    # or the figure is printed in greyscale.
    fig.add_artist(
        Line2D(
            [0.5, 0.5], [0.20, 0.96], transform=fig.transFigure,
            color="#8a8a8a", linewidth=1.2, linestyle=(0, (4, 4)),
        )
    )
    return _finish(fig, path, return_figure)


def frontiers(by_signal, path, return_figure=False, context=""):
    """Figure 2. All three signals, or it refuses to draw.

    `context` is appended to the N statement. Optional, but a reader who only
    looks at figures cannot tell which lag arm or spike shape a bare frontier
    chart came from, and this figure has no other place to say so.
    """
    missing = [s for s in SIGNAL_ORDER if s not in by_signal]
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; refusing to publish a chart "
            "that appears to compare three signals while showing fewer"
        )

    fig, axis = plt.subplots(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    fig.subplots_adjust(left=0.095, right=0.985, top=0.955, bottom=0.245)

    total = 0
    drawn_p99: list[float] = []
    for signal in SIGNAL_ORDER:
        front = pareto_frontier(by_signal[signal])
        total += len(front)
        drawn_p99 += [p.p99 for p in front]
        axis.plot(
            [p.cost for p in front],
            [p.p99 for p in front],
            "o-",
            markersize=5,
            linewidth=2,
            color=SIGNAL_COLOR[signal],
            label=SIGNAL_LABEL[signal],
        )
    _tidy(axis, "cost (replica-seconds)", "p99 request latency (s)", "#ffffff")
    # Below the axes, not on top of the frontiers: the cheap-and-slow end of a
    # Pareto frontier is the upper left and the expensive-and-fast end the lower
    # right, so an in-axes legend covers one or the other whatever corner it
    # picks.
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.125),
        ncol=3,
        fontsize=_pt(PX_LEGEND),
        frameon=False,
    )
    note = f"n={total} frontier points across {len(SIGNAL_ORDER)} signals"
    if context:
        note = f"{note} — {context}"
    _note(axis, f"{note} · {_span(drawn_p99)}", y=-0.245)
    return _finish(fig, path, return_figure)
