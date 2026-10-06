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
from matplotlib.ticker import FixedLocator, FuncFormatter

from autoscale.figures import (
    CURVE_COLOR,
    FIG_HEIGHT_IN,
    FIG_WIDTH_IN,
    MEASURED_BANNER,
    MEASURED_BG,
    PX_LEGEND,
    _figure_banner,
    _finish,
    _note,
    _pt,
    _tidy,
)

__all__ = ["validation_attempts"]

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
        values = [y for repeat in attempt["residuals"] for _, y in repeat if y is not None]
        drawn[key] = values
        below = sum(v < 0 for v in values)
        above = sum(v > 0 for v in values)
        every = max(below, above) == len(values)
        side, count = ("below", below) if below >= above else ("above", above)
        axis.text(0.5, 0.97 if side == "below" else 0.03,
                  f"median residual {statistics.median(values):+.3f} s\n".replace("-", "−")
                  + (f"all {count}" if every else f"{count} of {len(values)}")
                  + f" bins {side} zero",
                  transform=axis.transAxes, ha="center", va="top" if side == "below" else "bottom",
                  fontsize=_pt(PX_LEGEND), color=CURVE_COLOR)
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
    _note(axes[0], f"n={compared} judged bins per attempt, 3 repeats each; bin counts are per repeat\n"
                   "residual = real − predicted p50 per 10 s bin, binned by engine arrival\n"
                   "y axis: symmetric log, linear within ±0.01 s; ticks in seconds",
          y=-0.20)
    _figure_banner(fig, left, right, "MEASURED", "1 replica, 3 repeats per attempt",
                   MEASURED_BANNER)
    return _finish(fig, path, return_figure)
