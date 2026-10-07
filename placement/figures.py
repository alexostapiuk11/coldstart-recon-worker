"""Artifact 4's four body figures, drawn from `data/a4/analysis.json` alone.

August §10's four, under the constraints every artifact's figures share:
intervals shown, N stated, no truncated axes, legible on a phone, and looked at
by a human before anything is called done (`harness.figure_guards`).

1. `crossover`: the fleet each strategy is sized to, and its aggregate p99,
   against skew, one column per locality regime. The crossover interval is
   shaded and the validated operating point is marked (August §9).
2. `deciles`: p99 by popularity decile at the reference skew, each strategy at
   its own sized fleet, beside swap sized on the aggregate p99 instead.
3. `interference`: the measured co-location surface as one curve per
   neighbour load, the solo curve, both KV ceilings, and the held-out cells.
4. `swap_stages`: the 4B swap's measured stages, each marked paid or skipped
   under artifact 1's taxonomy, with artifact 1's 8B cold start as a labelled
   reference (amendment §5).

The text budget is artifact 2's: at the phone floor a figure holds about 90
characters across, whatever its width, so labels are terse, figures grow
tall rather than wide, and margins are set explicitly.

Refusals rather than best-effort drawing: a regime, strategy or stage missing
from the analysis raises instead of drawing a chart that compares fewer things
than it appears to.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from harness.figure_guards import phone_pt
from placement.fleet import STRATEGIES

__all__ = ["FIGURES", "crossover", "deciles", "interference", "swap_stages"]

STRATEGY_COLOR = {"dedicate": "#4f6d7a", "swap": "#c0392b", "colocate": "#2f6fd0"}
STRATEGY_MARKER = {"dedicate": "s", "swap": "o", "colocate": "^"}
REGIME_TITLE = {"spread": "spread arrivals", "bursty": "bursty arrivals"}
NOTE_COLOR = "#3f3f3f"
FIG_WIDTH_IN = 7.0
PX_TITLE = 9.0
PX_LABEL = 8.2
PX_TICK = 7.8
PX_NOTE = 7.8


def _pt(px: float, width: float = FIG_WIDTH_IN) -> float:
    return phone_pt(px, width)


def _require(mapping: dict, keys, what: str) -> None:
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise ValueError(f"the analysis has no {what} {missing}; refusing to draw a chart that "
                         "silently compares fewer of them")


def _save(fig, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    return path


def _style(ax, width: float = FIG_WIDTH_IN) -> None:
    ax.tick_params(labelsize=_pt(PX_TICK, width))
    ax.grid(alpha=0.25, linewidth=0.6)


def _finish(fig, path, return_figure: bool):
    out = _save(fig, path)
    if return_figure:
        return fig
    plt.close(fig)
    return out


def crossover(analysis: dict, path, *, return_figure: bool = False):
    regimes = analysis["regimes"]
    order = [r for r in ("spread", "bursty") if r in regimes]
    _require(regimes, analysis["design"]["regimes"], "regime")
    slo = analysis["design"]["slo_seconds"]
    reps = analysis["design"]["repetitions"]
    fig, axes = plt.subplots(2, len(order), figsize=(FIG_WIDTH_IN, 8.6), sharex=True,
                             squeeze=False)
    for col, regime in enumerate(order):
        r = regimes[regime]
        top, bottom = axes[0][col], axes[1][col]
        points = r["points"]
        skews = [p["s"] for p in points]
        top_m = 0
        bottom_hi = 0.0
        for strategy in STRATEGIES:
            xs, ms, lats, los, his = [], [], [], [], []
            for p in points:
                if not p["evaluable"] or p["strategies"].get(strategy) is None:
                    continue
                v = p["strategies"][strategy]
                xs.append(p["s"])
                ms.append(v["m"])
                ap = v["aggregate_p99"]
                lats.append(ap["point"])
                los.append(ap["point"] - ap["lo"])
                his.append(ap["hi"] - ap["point"])
            top_m = max([top_m, *ms])
            bottom_hi = max([bottom_hi, *(m + h for m, h in zip(lats, his))])
            style = {"color": STRATEGY_COLOR[strategy], "marker": STRATEGY_MARKER[strategy],
                     "markersize": 5, "linewidth": 1.4}
            top.plot(xs, ms, label=strategy, **style)
            bottom.errorbar(xs, lats, yerr=[los, his], capsize=2, **style)
        for p in points:
            if not p["evaluable"]:
                # Anchored on the inside, at the frame's own edge: centred on the first
                # or last skew it would straddle the frame and run over the tick
                # labels, and started at the skew it would run into the validated line.
                if p["s"] == skews[0]:
                    where = {"xy": (0.02, 0.02), "xycoords": "axes fraction", "ha": "left"}
                elif p["s"] == skews[-1]:
                    where = {"xy": (0.98, 0.02), "xycoords": "axes fraction", "ha": "right"}
                else:
                    where = {"xy": (p["s"], 0), "xytext": (0, 4), "textcoords": "offset points",
                             "ha": "center"}
                top.annotate("not\nevaluable", va="bottom", fontsize=_pt(PX_NOTE),
                             color=NOTE_COLOR, **where)
                continue
            dominated = [s for s in STRATEGIES if p["strategies"].get(s) is None]
            for k, strategy in enumerate(dominated):
                top.plot(p["s"], top_m * 1.08 + k * top_m * 0.05, marker="x", linestyle="none",
                         color=STRATEGY_COLOR[strategy], markersize=6)
        c = r["crossover"]
        if c["interval_lower_point"]:
            lo, hi = c["interval_lower_point"]
            right = skews[min(skews.index(hi) + 1, len(skews) - 1)]
            top.axvspan(lo, right, color="#f2d7a6", alpha=0.45, linewidth=0)
        for a, b in c["between"]:
            top.axvline((a + b) / 2, color="#a0522d", linewidth=1.0, linestyle="--")
        bottom.axhline(slo, color="#555555", linewidth=1.0, linestyle=":")
        validated = analysis.get("validation", {}).get("point")
        slo_right = bool(validated and validated["regime"] == regime
                         and validated["s"] < (skews[0] + skews[-1]) / 2)
        bottom.annotate(f"SLO {slo:.0f} s", (skews[-1] if slo_right else skews[0], slo),
                        xytext=(-2 if slo_right else 2, 3), textcoords="offset points",
                        ha="right" if slo_right else "left", fontsize=_pt(PX_NOTE),
                        color=NOTE_COLOR)
        top.set_title(REGIME_TITLE[regime], fontsize=_pt(PX_TITLE))
        top.set_ylim(0, top_m * 1.25 + 1)
        if validated and validated["regime"] == regime:
            for ax in (top, bottom):
                ax.axvline(validated["s"], color="#2f6b34", linewidth=1.2, linestyle="-.")
            top.annotate("validated\npoint", (validated["s"], top_m * 1.25 + 1), xytext=(3, -4),
                         textcoords="offset points", va="top", fontsize=_pt(PX_NOTE),
                         color="#2f6b34")
        top.yaxis.set_major_locator(MaxNLocator(integer=True))
        bottom.set_ylim(0, max(slo, bottom_hi) * 1.15)
        bottom.set_xlabel("Zipf skew s", fontsize=_pt(PX_LABEL))
        for ax in (top, bottom):
            _style(ax)
    axes[0][0].set_ylabel("GPUs to meet SLO", fontsize=_pt(PX_LABEL))
    axes[1][0].set_ylabel("aggregate p99 (s)", fontsize=_pt(PX_LABEL))
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False,
               fontsize=_pt(PX_LABEL), bbox_to_anchor=(0.5, 0.045))
    fig.text(0.5, 0.012, f"x = dominated; shaded = crossover 95% interval; n={reps} runs per point",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.95, bottom=0.15, hspace=0.12, wspace=0.22)
    return _finish(fig, path, return_figure)


def deciles(analysis: dict, path, *, return_figure: bool = False):
    ref = analysis["reference"]
    slo = analysis["design"]["slo_seconds"]
    regimes = analysis["regimes"]
    _require(regimes, analysis["design"]["regimes"], "regime")
    order = [r for r in ("spread", "bursty") if r in regimes]
    fig, axes = plt.subplots(len(order), 1, figsize=(FIG_WIDTH_IN, 8.0), sharex=True,
                             squeeze=False)
    xs = list(range(1, 11))
    for row, regime in enumerate(order):
        ax = axes[row][0]
        point = next((p for p in regimes[regime]["points"] if p["s"] == ref["s"]), None)
        if point is None:
            raise ValueError(f"{regime} has no grid point at s = {ref['s']}")
        ax.set_title(f"{REGIME_TITLE[regime]}, s = {ref['s']}", fontsize=_pt(PX_TITLE))
        if not point["evaluable"]:
            # Said on the panel, not raised: one regime that is not evaluable
            # at the reference must not stop every other figure from rendering.
            ax.text(0.5, 0.5, "not evaluable here:\na decile missed the p99 floor",
                    transform=ax.transAxes, ha="center", va="center", fontsize=_pt(PX_LABEL),
                    color=NOTE_COLOR)
            ax.set_yticks([])
            _style(ax)
            continue
        for strategy in STRATEGIES:
            v = point["strategies"].get(strategy)
            if v is None:
                continue
            ax.plot(xs, v["decile_p99"], color=STRATEGY_COLOR[strategy],
                    marker=STRATEGY_MARKER[strategy], markersize=5, linewidth=1.4,
                    label=f"{strategy}, {v['m']} GPUs")
        agg = point["aggregate_rule"].get("swap")
        sized = point["strategies"].get("swap")
        if agg is not None and (sized is None or agg["m"] < sized["m"]):
            ax.plot(xs, agg["decile_p99"], color=STRATEGY_COLOR["swap"], linestyle="--",
                    marker="o", markerfacecolor="white", markersize=5, linewidth=1.2,
                    label=f"swap sized on aggregate, {agg['m']} GPUs")
        ax.axhline(slo, color="#555555", linewidth=1.0, linestyle=":")
        # Headroom above the highest curve and the SLO line, so the note has room
        # inside the frame; at the right end because the aggregate-sized curve is
        # highest at the left.
        top_y = max([slo, *(max(line.get_ydata()) for line in ax.lines if len(line.get_xdata()) >= 3)])
        ax.set_ylim(0, top_y * 1.14)
        ax.annotate(f"SLO {slo:.0f} s", (xs[-1], slo), xytext=(-2, 3), textcoords="offset points",
                    ha="right", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
        ax.set_ylabel("p99 (s)", fontsize=_pt(PX_LABEL))
        # Two columns in the empty band between the dedicate/colocate curves near
        # zero and the swap curves, not on any curve.
        ax.legend(fontsize=_pt(PX_NOTE), frameon=False, loc="center", ncol=2,
                  bbox_to_anchor=(0.5, 0.30))
        _style(ax)
    axes[-1][0].set_xticks(xs, ["1\nhottest", *map(str, range(2, 10)), "10\ncoldest"])
    axes[-1][0].set_xlabel("popularity decile", fontsize=_pt(PX_LABEL))
    reps = analysis["design"]["repetitions"]
    fig.text(0.5, 0.012, f"median of {reps} runs' p99 per decile", ha="center",
             fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.95, bottom=0.13, hspace=0.22)
    return _finish(fig, path, return_figure)


def interference(analysis: dict, path, *, return_figure: bool = False):
    inputs = analysis["inputs"]
    surface = inputs["surface"]
    cells = inputs["cells"]
    kv = inputs["kv"]
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 6.4))
    shades = ["#9ecae1", "#4292c6", "#2171b5", "#08306b"]
    if len(surface["neighbour"]) > len(shades):
        raise ValueError("more neighbour levels than the figure has shades for")
    n_min = math.inf
    for j, neighbour in enumerate(surface["neighbour"]):
        own = surface["own"]
        lo, hi, mid = [], [], []
        for o in own:
            cell = cells.get(f"pair:o{o}:n{neighbour}")
            if cell is None or cell["n"] == 0:
                raise ValueError(f"the surface has cell ({o}, {neighbour}) but no summary for it")
            n_min = min(n_min, cell["n"])
            mid.append(cell["median"])
            lo.append(cell["median"] - cell["lo"])
            hi.append(cell["hi"] - cell["median"])
        label = "split, neighbour idle" if neighbour == 0 else f"split, neighbour at {neighbour}"
        ax.errorbar(own, mid, yerr=[lo, hi], color=shades[j], marker="o", markersize=4,
                    linewidth=1.4, capsize=2, label=label)
    solo = inputs["solo_curve"]
    ax.plot([p[0] for p in solo], [p[1] for p in solo], color="#222222", linewidth=1.6,
            marker="s", markersize=4, label="solo, full memory")
    for check in analysis.get("held_out", []):
        ax.plot(check["own"], check["median"], marker="D", markerfacecolor="white",
                markeredgecolor="#a0522d", linestyle="none", markersize=7)
        ax.plot(check["own"], check["predicted"], marker="x", color="#a0522d", markersize=7,
                linestyle="none")
    ax.plot([], [], marker="D", markerfacecolor="white", markeredgecolor="#a0522d",
            linestyle="none", label="held out: measured, x = predicted")
    for ceiling, text in ((kv["split_ceiling"], "KV full, split"),
                          (kv["solo_ceiling"], "KV full, solo")):
        if ceiling is None:
            continue
        ax.axvline(ceiling, color="#777777", linestyle=":", linewidth=1.0)
        ax.annotate(text, (ceiling, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -4),
                    textcoords="offset points", rotation=90, va="top", ha="left",
                    fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    ax.set_xscale("log", base=2)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("own concurrency (requests in flight)", fontsize=_pt(PX_LABEL))
    ax.set_ylabel("latency per request (s)", fontsize=_pt(PX_LABEL))
    ax.legend(fontsize=_pt(PX_NOTE), frameon=False, loc="upper left")
    _style(ax)
    shape = inputs["request_shape"]
    fig.text(0.5, 0.012, f"{shape['input_len']}+{shape['output_len']} tokens; median and "
             f"range of n>={n_min} runs per point", ha="center", fontsize=_pt(PX_NOTE),
             color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.97, bottom=0.14)
    return _finish(fig, path, return_figure)


# (key, legend label, colour, hatched). Hatched marks a stage the other bar
# does not have: teardown and release are paid only by a swap; the platform's
# scheduling and container start, and the first token, are not in a swap. The
# two bars' stages are each artifact's own: artifact 1's T_weights includes
# the process start and imports, which a swap's log puts in its first bar.
SWAP_SEGMENTS = (
    ("teardown_s", "teardown (swap only)", "#8c6d31", True),
    ("release_s", "memory release (swap only)", "#bd9e39", True),
    ("process_and_health_s", "process start, imports, health", "#8e6fc4", False),
    ("weights_s", "weight load", "#2f6fd0", False),
    ("compile_s", "torch.compile (S4b)", "#d95f02", False),
    ("engine_init_rest_s", "engine init, rest", "#e6ab02", False),
)
REFERENCE_SEGMENTS = (
    ("t_platform", "T_platform (not in a swap)", "#9e9e9e", True),
    ("t_weights", "T_weights (S2+S3)", "#9ecae1", False),
    ("t_s4_bracket", "S4 engine init", "#fdd57e", False),
    ("t_s5", "S5 health", "#c7b8e8", False),
    ("t_s6", "S6 first token (not in a swap)", "#4f6d7a", True),
)
IN_BAR_MIN_S = 3.0


def swap_stages(analysis: dict, path, *, return_figure: bool = False):
    stages = analysis["inputs"]["stages"]
    ref = analysis["inputs"]["a1_reference"]
    _require(stages["stages"], [k for k, *_ in SWAP_SEGMENTS], "swap stage")
    _require(ref["stages"], [k for k, *_ in REFERENCE_SEGMENTS], "reference stage")
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 6.4))
    model = analysis["inputs"]["model"].split("/")[-1]
    state = "cold cache" if stages["cold"] else "warm cache"
    rows = (
        (1.0, f"{model} swap\n{state}, n={stages['n']}", stages["stages"], SWAP_SEGMENTS),
        (0.0, f"Qwen3-8B cold\nstart, n={ref['n']}\n(artifact 1)", ref["stages"],
         REFERENCE_SEGMENTS),
    )
    totals = []
    for y, _, values, segments in rows:
        left = 0.0
        for key, label, color, hatched in segments:
            width = values[key]
            ax.barh(y, width, left=left, color=color, edgecolor="white",
                    hatch="///" if hatched else None, height=0.55, label=label)
            if width >= IN_BAR_MIN_S:
                ax.text(left + width / 2, y, f"{width:.1f}", ha="center", va="center",
                        fontsize=_pt(PX_NOTE), color="#111111")
            left += width
        ax.text(left + 0.4, y, f"Σ {left:.1f} s", va="center", fontsize=_pt(PX_LABEL))
        totals.append(left)
    ax.set_yticks([1.0, 0.0], [rows[0][1], rows[1][1]], fontsize=_pt(PX_TICK))
    ax.set_xlim(0, max(totals) * 1.18)
    ax.set_ylim(-0.5, 1.5)
    ax.set_xlabel("seconds (median)", fontsize=_pt(PX_LABEL))
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.16), ncol=2, frameon=False,
              fontsize=_pt(PX_NOTE))
    # A bar's end is the sum of its stages' medians, which is not the median of
    # the totals; the median swap, the number the SLO is a multiple of, is
    # stated beside it so the two are never read as one.
    fig.text(0.5, 0.055, f"Σ: sum of stage medians. Median swap: {stages['stages']['swap_s']:.1f} s",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.text(0.5, 0.012, "hatched: in one bar only. The 8B bar is a reference, not a baseline",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.27, right=0.97, top=0.97, bottom=0.40)
    return _finish(fig, path, return_figure)


FIGURES = {"crossover": crossover, "deciles": deciles, "interference": interference,
           "swap_stages": swap_stages}
