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

Refusals rather than best-effort drawing, in five places:

- `frontiers` refuses a `by_signal` missing any of the three signals. A chart
  that appears to compare three signals while showing two is a misleading
  chart, not a smaller one. This is not hypothetical: against the placeholder
  service curve, queue depth never crosses even its lowest threshold, and this
  guard is what stops that becoming a published two-signal chart.
- `convergence` refuses arms whose signal sets differ. Arm A and arm C are the
  two halves of one comparison; a signal drawn on one arm and absent from the
  other still renders, and reads as though both arms were compared on the same
  signals with the missing one simply overlapping.
- `convergence` also refuses an incomplete signal set that both arms SHARE.
  Agreement is not coverage: two arms that each lost the same signal agree
  perfectly, and the check above passes on them, so this figure drew a
  two-signal "three-signal comparison" without complaint -- the exact input
  `frontiers` below refuses, on the figure that carries the argument.
- `convergence` refuses an empty arm, and refuses an empty sweep. Both draw a
  blank panel that reads as "the model showed nothing" rather than "nothing was
  run".
- `service_curve` (figure 4), through `censoring_onset`, refuses a utilization
  curve that falls back below the censoring threshold after reaching it. The
  figure shades ONE region from the onset to the edge and says every point in
  it is past the threshold; on a curve that dips, part of that region is load
  the utilization policy can still respond to.
"""

from itertools import pairwise
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import MaxNLocator

from autoscale.frontier import pareto_frontier
from autoscale.stats import MIN_BOOTSTRAP_SAMPLES
from autoscale.thresholds import THRESHOLDS

__all__ = [
    "SIGNAL_ORDER",
    "UTILIZATION_CENSOR_AT",
    "censoring_onset",
    "convergence",
    "frontiers",
    "service_curve",
]

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
# Bands are drawn once per render and the sweep behind them is minutes of
# CPU, so 2000 draws costs nothing noticeable here and matches the
# iterations the published gap interval uses.
BAND_ITERATIONS = 2000
BAND_SEED = 0
# Low enough that three overlapping bands stay distinguishable from one
# another and from the lines they belong to.
BAND_ALPHA = 0.18

MEASURED_BG = "#eef7ee"
MODELED_BG = "#e8f1ff"
MEASURED_BANNER = "#2f6b34"
MODELED_BANNER = "#1f4f9e"
NOTE_COLOR = "#3f3f3f"

# The top of utilization's pre-registered scale-up grid. Once utilization
# reaches it, every utilization policy on the grid has already crossed its
# scale-up threshold, so its decision is fixed at "scale up" and further load
# cannot change it. The signal itself keeps rising, from 0.95 towards 1.0;
# what is censored is the DECISION, which no longer depends on that rise.
# H2's censoring mechanism, read off the grid rather than chosen for the chart.
UTILIZATION_CENSOR_AT = max(THRESHOLDS["utilization"][0])
CENSOR_COLOR = "#c0392b"
CURVE_COLOR = "#333333"

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


def _band(axis, front, color, allow_missing_intervals: bool) -> bool:
    """A signal's bootstrap interval, as a band rather than error bars.

    A frontier is a curve, and per-point bars on three overlapping curves are
    unreadable at 375 px -- which spec 7 requires them to be legible at. Drawn
    before the line so the line stays on top of its own band.
    """
    thin = [p for p in front if p.n < MIN_BOOTSTRAP_SAMPLES]
    if thin and allow_missing_intervals:
        # The opt-out, named after `sweep.run_sweep`'s `allow_unmeasured` and
        # there for the same kind of caller: a plumbing check that renders the
        # real code path on a deliberately reduced sweep. It draws NO band at
        # all rather than a partial one, so what comes out is visibly a chart
        # without intervals rather than a chart whose intervals are quietly
        # wrong. The caller is told, so the figure can say so: a signal with no
        # band beside two that have one reads as "this one is certain", which
        # is the opposite of the truth.
        return False
    if thin:
        # Refusing rather than drawing the band without them, and rather than
        # pinching it to zero width at those points. Both alternatives publish
        # a narrower interval than the data supports, which is the flattering
        # direction: a zero-width pinch reads as CERTAINTY about exactly the
        # policy we know least about. A policy with too few surviving
        # repetitions is a finding -- the pre-registered exclusion rules bit it
        # hard -- and belongs in the discard counts the sweep reports, not
        # smoothed into a chart.
        worst = min(p.n for p in thin)
        raise ValueError(
            f"{len(thin)} of {len(front)} points on the {front[0].signal!r} "
            f"frontier have fewer than {MIN_BOOTSTRAP_SAMPLES} surviving "
            f"repetitions (fewest: {worst}), so no bootstrap interval can be "
            "drawn for them. Below that floor the resampled distribution is a "
            "handful of repeated values and the interval comes out "
            "confident-looking and meaningless. Check the per-signal discard "
            "counts: this is the exclusion rules biting, and it is a finding "
            "about that policy rather than a figure to draw around"
        )
    lo, hi = [], []
    for point in front:
        a, b = point.p99_interval(iterations=BAND_ITERATIONS, seed=BAND_SEED)
        lo.append(a)
        hi.append(b)
    costs = [p.cost for p in front]
    if len(front) == 1:
        # `fill_between` over one x-coordinate has zero width and paints
        # NOTHING, so this signal used to arrive as a bare marker beside two
        # banded curves -- which reads as the certain one, the exact misreading
        # the refusal path above exists to prevent, arrived at by a different
        # route. A frontier legitimately collapses to one point whenever every
        # policy of a signal costs the same, which is not a corner case: on the
        # arm-A sweep all 19 queue_depth policies do, and queue_depth is the
        # signal carrying the artifact's headline finding.
        #
        # An error bar rather than a band because there is no curve to band --
        # one operating point has an interval, not an envelope. The module
        # docstring's preference for bands is about three OVERLAPPING curves at
        # 375 px; a lone vertical bar has none of that crowding.
        axis.errorbar(
            costs,
            [p.p99 for p in front],
            yerr=[[front[0].p99 - lo[0]], [hi[0] - front[0].p99]],
            color=color,
            capsize=4,
            elinewidth=2,
            linestyle="none",
            zorder=2,
        )
        return True
    axis.fill_between(costs, lo, hi, color=color, alpha=BAND_ALPHA, linewidth=0)
    return True


def _reps_text(points) -> str:
    """How many repetitions the points were estimated from.

    `n=55 policy points` said how many policies were drawn and never how many
    runs each was estimated from, so a 1-repetition sweep and a 30-repetition
    sweep carried identical annotations. The exclusion rules discard runs, so
    this is a range more often than a single number.
    """
    reps = sorted({p.n for p in points})
    if not reps:
        return "no repetitions"
    if len(reps) == 1:
        return f"{reps[0]} repetitions each"
    return f"{reps[0]}-{reps[-1]} repetitions each"


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


def convergence(frontiers_a, frontiers_c, swept, path, *, curve_measured, return_figure=False):
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
    # Agreement is not coverage. The check above only says the two arms were
    # swept over the SAME signals; two arms that both lost a signal agree
    # perfectly, and this figure -- the one that carries the artifact's argument
    # -- rendered that as a three-signal comparison showing two, while
    # `frontiers` a few lines down has always refused exactly that input.
    missing = [s for s in SIGNAL_ORDER if s not in frontiers_a]
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing} on either arm; both arms "
            "agreeing on an incomplete signal set is not a smaller comparison, "
            "it is a chart that appears to compare three signals while showing "
            "fewer -- and the agreement check above passes on it precisely "
            "because BOTH arms lost the same signal"
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

    unbanded: set[str] = set()
    for arm, data in (("A", frontiers_a), ("C", frontiers_c)):
        for signal in signals:
            front = pareto_frontier(data[signal])
            # Six overlapping bands on one half-width panel would be mud, so
            # only arm A is banded: it is the reference the halving in H3 is
            # measured FROM, and the arms are already distinguished by line
            # style. The note says which.
            if arm == "A" and not _band(
                left, front, SIGNAL_COLOR.get(signal, UNKNOWN_SIGNAL_COLOR), True
            ):
                unbanded.add(SIGNAL_LABEL.get(signal, signal))
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
    _tidy(
        left,
        "cost (replica-seconds)",
        "p99 request latency (s)",
        MEASURED_BG if curve_measured else MODELED_BG,
    )
    # The lag arms ARE measured; the p99 axis they are drawn against is not,
    # unless the service curve behind the sweep was measured too. Stamping
    # MEASURED over a placeholder-derived axis is the precise claim this banner
    # system exists to prevent, made by the banner system.
    #
    # No default on `curve_measured`, deliberately: a default of True publishes
    # an unmeasured curve as measured whenever a caller forgets to pass it,
    # which is the flattering direction, and a default of False silently
    # downgrades a real result. The caller knows which curve it swept.
    if curve_measured:
        _banner(left, "MEASURED", "artifact 1's two lag arms", MEASURED_BANNER)
    else:
        # "LAG MEASURED", not "MEASURED LAG, MODELED LATENCY": the strip is
        # pinned to the panel's width and the panel is half the canvas, so the
        # long form overflowed into the modeled panel and was clipped to
        # "...SURED LAG, MODELED LAT" -- illegible, on the figure whose whole
        # job is to separate measurement from model. Twelve characters, the
        # same length as "NOT MEASURED", which is the width this strip is known
        # to hold. The qualification it drops is carried by the subtitle.
        _banner(
            left,
            "LAG MEASURED",
            "p99 modeled: placeholder curve",
            MODELED_BANNER,
        )
    measured_p99 = [p.p99 for data in (frontiers_a, frontiers_c) for v in data.values() for p in v]
    # Two lines, not one: the panel is half the canvas and the guards caught
    # the single-line version spilling past it and into the modeled panel's own
    # note.
    measured_points = [p for data in (frontiers_a, frontiers_c) for v in data.values() for p in v]
    # Three short lines rather than two longer ones. The panel is half the
    # canvas and its note sits under it; adding the repetition count to the
    # first line pushed that line wide enough to collide with the modeled
    # panel's own note, which the overlap guard caught.
    _note(
        left,
        f"n={n_a + n_c} policy points ({n_a} A, {n_c} C)\n"
        f"{_reps_text(measured_points)}\n"
f"{_span(measured_p99)}",
    )

    lags = sorted(swept)
    # `swept` values may be a bare float (the gap) or a mapping carrying an
    # interval. Both are accepted because the modeled panel is a sensitivity
    # sweep over invented lags and a caller sweeping it cheaply without
    # bootstrapping each point is doing something reasonable -- but a value
    # WITH an interval must never be drawn without it, which is why the band
    # below is keyed on the values themselves rather than on a flag.
    def _point(value):
        return value["point"] if isinstance(value, dict) else value

    if all(isinstance(swept[k], dict) for k in lags):
        right.fill_between(
            lags,
            [swept[k]["lo"] for k in lags],
            [swept[k]["hi"] for k in lags],
            color=MODELED_BANNER,
            alpha=BAND_ALPHA,
            linewidth=0,
        )
    right.plot(
        lags, [_point(swept[k]) for k in lags], "o-", markersize=5, linewidth=2,
        color=MODELED_BANNER,
    )
    _tidy(right, "cold-start lag (s)", "inter-signal gap (s)", MODELED_BG)
    # "NOT MEASURED" rather than "MODELED" as the banner word: at a glance
    # MEASURED and MODELED differ by two letters and read as the same word, so
    # the strip that is supposed to make the boundary unmissable would be the
    # least legible part of it. "modeled" is still stated, in the subtitle.
    _banner(right, "NOT MEASURED", "modeled: lag swept, invented", MODELED_BANNER)
    banded = all(isinstance(swept[k], dict) for k in lags)
    # Both panels' shading is described here rather than once per panel. It
    # belongs on the left too, but the left note is already three lines and a
    # fourth collided with the legend beneath it -- and the vocabulary
    # ("shaded", "95%") is the same for both, so saying it twice earns nothing.
    shading = []
    if banded:
        shading.append("shaded: 95% bootstrap interval")
    if any(p.n >= MIN_BOOTSTRAP_SAMPLES for p in measured_points):
        shading.append("left: arm A only")
    if unbanded:
        # Naming them, not just omitting them. A signal drawn without a band
        # beside two that have one reads as the CERTAIN one, which is exactly
        # backwards -- it is the one whose runs the exclusion rules ate.
        shading.append("no interval (too few reps): " + ", ".join(sorted(unbanded)))
    _note(right, "\n".join([f"n={len(lags)} modeled lag values", *shading]))

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


def frontiers(
    by_signal, path, return_figure=False, context="", allow_missing_intervals=False,
    curve_measured=None,
):
    """Figure 2. All three signals, or it refuses to draw.

    `context` is appended to the N statement. Optional, but a reader who only
    looks at figures cannot tell which lag arm or spike shape a bare frontier
    chart came from, and this figure has no other place to say so.

    `allow_missing_intervals` lets a caller draw without the bootstrap bands
    when the points cannot support them -- a plumbing check on a one-repetition
    sweep, not a publication. Opt-in and named after `run_sweep`'s
    `allow_unmeasured` for the same reason: the default has to be the one that
    refuses, so an under-powered sweep cannot reach a figure by accident.

    `curve_measured` adds which service curve the frontiers ran on to the note;
    a reader who sees only this figure cannot otherwise tell.
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
        _band(axis, front, SIGNAL_COLOR[signal], allow_missing_intervals)
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
    # The curve phrase opens the SECOND line. The first already carries the N
    # statement, the context and the repetition count, and with a long context
    # ("ramp arm A") the phrase pushed it past the canvas. A third line was
    # tried and rejected: it falls below the canvas under this figure's fixed
    # bottom margin. "(invented)" is dropped from the placeholder wording because
    # "PLACEHOLDER" in capitals already says it, and with it the second line
    # was still 21 px wider than the canvas.
    curve_text = ""
    if curve_measured is not None:
        curve_text = "measured curve · " if curve_measured else "PLACEHOLDER curve · "
    all_points = [p for v in by_signal.values() for p in v]
    _note(
        axis,
        f"{note} · {_reps_text(all_points)}\n{curve_text}{_span(drawn_p99)} · "
        "shaded: 95% bootstrap interval",
        y=-0.245,
    )
    return _finish(fig, path, return_figure)


def censoring_onset(curve, threshold: float = UTILIZATION_CENSOR_AT) -> float | None:
    """The lowest concurrency at which utilization reaches `threshold`.

    Linear interpolation between measured points, the same interpolation
    `ServiceCurve` itself uses, so the shaded region begins where the model
    the simulator runs on says it does. None if utilization never reaches the
    threshold in the measured range.

    Refuses a curve that falls back below the threshold after reaching it.
    The figure shades from the onset to the right edge as ONE region, and its
    note says every point in it is at or above the threshold; on a curve that
    dips, part of that region is load the utilization policy can still respond
    to. Shading only the stretches above the threshold was the rejected
    alternative: a band with holes in it is a claim about a non-monotone
    utilization curve, which is a measurement to investigate before it is a
    chart to draw.
    """
    points = [(c, u) for c, _, _, u in curve.points]
    onset = None
    if points[0][1] >= threshold:
        onset, after = float(points[0][0]), 0
    else:
        for i, ((c0, u0), (c1, u1)) in enumerate(pairwise(points)):
            if u0 < threshold <= u1:
                onset, after = c0 + (threshold - u0) / (u1 - u0) * (c1 - c0), i + 1
                break
    if onset is None:
        return None
    dips = [(c, u) for c, u in points[after:] if u < threshold]
    if dips:
        raise ValueError(
            f"utilization reaches {threshold:g} at concurrency {onset:.1f} and then "
            f"falls back below it at {', '.join(f'{c:g} ({u:g})' for c, u in dips)}; "
            "the censored band runs from the onset to the edge, so it would claim "
            "censoring over a range where the utilization policy can still act"
        )
    return onset


def _figure_banner(fig, left: float, right: float, word: str, subtitle: str, color: str) -> None:
    """The measured/modeled strip, in FIGURE coordinates, for a stacked figure.

    `_banner` sizes its strip as a fraction of one panel's height, which suits
    figure 1's tall panels -- `convergence` is its only caller; figure 2 has no
    banner -- and fails on figure 4's three short ones: the strip comes out
    shorter than the word inside it and the subtitle lands on the top panel.
    It is not changed to fit, because that would move figure
    1's pixels; a stacked figure has one header for all its panels, so it is
    drawn once, against the figure, spanning the panels' shared width.
    """
    # `add_artist`, not `fig.patches.append`: appending to the list draws the
    # rectangle without attaching it, so it has no figure to resolve against.
    fig.add_artist(
        Rectangle((left, 0.935), right - left, 0.05, transform=fig.transFigure,
                  facecolor=color, edgecolor="none", zorder=5)
    )
    fig.text((left + right) / 2, 0.96, word, ha="center", va="center",
             fontsize=_pt(PX_BANNER), fontweight="bold", color="white", zorder=6)
    fig.text((left + right) / 2, 0.928, subtitle, ha="center", va="top",
             fontsize=_pt(PX_SUBTITLE), color=color)


def service_curve(curve, path, return_figure=False, measured=None):
    """Figure 4. Latency, throughput and GPU utilization against concurrency,
    with the region where utilization is censored shaded on all three.

    Three stacked panels sharing the concurrency axis rather than one panel
    with three y-axes: the quantities have unrelated units, and a twin-axis
    chart invites reading one curve against another's scale. The shading is on
    every panel because the point of the figure is the COINCIDENCE -- latency
    still climbing while utilization has flattened -- and a reader has to see
    both sides of the boundary in one glance.

    "Censored" means every utilization policy's decision is already fixed at
    scale-up: the signal still rises from 0.95 towards 1.0 inside the band,
    but no threshold on the pre-registered grid sits in that range, so further
    load cannot change what any utilization policy does.

    `measured`, a `MeasuredCurve` for this same curve, adds what only a real
    sweep has: min-max bars per level from its repeats, the idle point drawn
    apart (hollow, dashed: the one point not taken under load), the runs behind
    each point, and the levels the engine could not serve. Without it the
    figure is drawn exactly as before, which is what keeps the placeholder
    draft's pixels unchanged.
    """
    left, right = 0.13, 0.985
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    fig.subplots_adjust(left=left, right=right, top=0.86, bottom=0.20, hspace=0.22)
    if measured is not None and measured.curve is not curve:
        raise ValueError(
            "measured= must carry the same curve being drawn; otherwise the bars and notes "
            "would describe a different measurement than the points they sit on"
        )
    drawn = list(measured.measured_points) if measured is not None else list(curve.points)
    concurrency = [c for c, _, _, _ in drawn]
    # A little past the last point, and the shading runs to the same edge: a
    # band that stopped at the last measured point would read as censoring
    # that ENDS there, and an axis ending exactly on it would clip the marker.
    x_right = max(concurrency) * 1.04
    onset = censoring_onset(curve)
    background = MEASURED_BG if curve.measured else MODELED_BG
    for axis, index, label, key in (
        (axes[0], 1, "latency\n(s)", "latency_s_range"),
        (axes[1], 2, "throughput\n(tok/s)", "throughput_tps_range"),
        (axes[2], 3, "GPU\nutilization", "gpu_util_range"),
    ):
        ys = [p[index] for p in drawn]
        axis.plot(concurrency, ys, "o-", markersize=5, linewidth=2, color=CURVE_COLOR)
        if measured is not None:
            lo = [y - i[key][0] for y, i in zip(ys, measured.intervals, strict=True)]
            hi = [i[key][1] - y for y, i in zip(ys, measured.intervals, strict=True)]
            bars = axis.errorbar(concurrency, ys, yerr=[lo, hi], fmt="none", ecolor=CURVE_COLOR,
                                 elinewidth=1.2, capsize=3)
            # The gid goes on the bar collection itself, not through errorbar's
            # kwargs, which matplotlib copies onto the caps as well.
            for collection in bars.lines[2]:
                collection.set_gid("interval")
            if index in (2, 3):
                idle_y = curve.points[0][index]
                axis.plot([curve.points[0][0], concurrency[0]], [idle_y, ys[0]], linestyle="--",
                          linewidth=1.2, color=CURVE_COLOR)
                # clip_on=False: the idle point sits ON the axes' left edge, and
                # clipped it draws as a half-circle against the spine.
                axis.plot([curve.points[0][0]], [idle_y], "o", markersize=6,
                          markerfacecolor="white", markeredgecolor=CURVE_COLOR, gid="idle",
                          clip_on=False, zorder=4)
        _tidy(axis, "", label, background)
        axis.set_xlim(0, x_right)
        if onset is not None:
            axis.axvspan(onset, x_right, color=CENSOR_COLOR, alpha=BAND_ALPHA,
                         linewidth=0, gid="censored")
    axes[2].set_ylim(0, 1.05)
    axes[2].axhline(UTILIZATION_CENSOR_AT, color=CENSOR_COLOR, linewidth=1, linestyle=":")
    axes[2].set_xlabel("concurrency per replica", fontsize=_pt(PX_AXIS_LABEL))
    if curve.measured:
        subtitle = "one replica, concurrency swept"
        if measured is not None and measured.runs_per_level:
            subtitle = f"{subtitle}, {min(measured.runs_per_level)} runs per level"
        _figure_banner(fig, left, right, "MEASURED", subtitle, MEASURED_BANNER)
    else:
        _figure_banner(fig, left, right, "NOT MEASURED", "placeholder curve: invented points",
                       MODELED_BANNER)
    # Two lines, each short: at the phone floor a note line wider than ~75
    # characters runs past 375 px, and the off-canvas test fails on it.
    if measured is None:
        shading = (
            f"shaded: utilization ≥ {UTILIZATION_CENSOR_AT:g} (from {onset:.1f}), "
            "above every utilization threshold"
            if onset is not None
            else f"utilization ≥ {UTILIZATION_CENSOR_AT:g} never reached in the measured range"
        )
        first = f"n={len(curve.points)} concurrency levels"
    else:
        shading = (
            f"shaded: utilization ≥ {UTILIZATION_CENSOR_AT:g} (from {onset:.2f}), "
            "above every utilization threshold"
            if onset is not None
            else f"utilization ≥ {UTILIZATION_CENSOR_AT:g} never reached in the measured range"
        )
        runs = min(measured.runs_per_level) if measured.runs_per_level else "?"
        first = f"n={len(drawn)} levels × {runs} runs, bars min–max"
        for e in measured.excluded_levels:
            first += f"; {e['concurrency']:g} not servable ({e['n_failed']}/{e['n_runs']} runs)"
    _note(axes[2], f"{first}\n{shading}", y=-0.42)
    return _finish(fig, path, return_figure)
