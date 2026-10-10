"""The four figures (August §8), drawn from the analysis dict only.

Same constraints as every artifact: N stated, no truncated value axes,
intervals shown, legible on a phone. Text sizes go through
`harness.figure_guards.phone_pt`, and tests/test_toolcall_figures.py checks
every text artist clears the phone floor.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from harness.figure_guards import phone_pt, validate_rows
from toolcall.formulation import CELLS
from toolcall.grader import CATEGORIES

PX_TITLE = 10.0
PX_TEXT = 8.4
WIDTH_IN = 8.0

CATEGORY_COLOR = {
    "CORRECT": "#d9d9d9",
    "MALFORMED": "#7a3e9d",
    "SPURIOUS": "#c88a2e",
    "MISSING": "#4a8a4a",
    "WRONG_TOOL": "#c04a4a",
    "WRONG_PARAMS": "#2f6fd0",
}
RICHNESS_COLOR = {"terse": "#c04a4a", "rich": "#2f6fd0"}
FORMAT_COLOR = {"actionable": "#2f6fd0", "opaque": "#c04a4a"}


# matplotlib stamps its version into a PNG's Software chunk; dropping it keeps a
# render byte-identical across matplotlib upgrades.
_NO_METADATA = {"Software": None}

# Every key the figures read, as dotted paths, so a renderer can refuse an
# analysis that predates one before it draws anything.
REQUIRED_PATHS = (
    "S", "N", "recovery_reps", "cell_rates.failure", "marginal_count_richness",
    "hypotheses.H1", "hypotheses.H4", "flakiness.distinct_categories_per_unit",
    "flakiness.units", "flakiness.ever_flip", "recovery",
)


def missing_paths(analysis: dict) -> list[str]:
    missing = []
    for path in REQUIRED_PATHS:
        node = analysis
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                missing.append(path)
                break
            node = node[part]
    return missing


def _pt(px: float) -> float:
    return phone_pt(px, WIDTH_IN)


def _style(ax, grid_axis: str = "y") -> None:
    ax.tick_params(labelsize=_pt(PX_TEXT))
    ax.xaxis.label.set_size(_pt(PX_TEXT))
    ax.yaxis.label.set_size(_pt(PX_TEXT))
    ax.grid(alpha=0.3, axis=grid_axis)


def _err(points, los, his) -> list[list[float]]:
    """errorbar's [[below], [above]] extents. A percentile bootstrap interval
    need not contain its point estimate, and errorbar refuses a negative
    extent, so a point outside [lo, hi] gets a zero-length arm on that side."""
    return [[max(0.0, p - lo) for p, lo in zip(points, los, strict=True)],
            [max(0.0, hi - p) for p, hi in zip(points, his, strict=True)]]


def _pct(interval: dict) -> str:
    """'95%' from the interval's own alpha, so the label cannot disagree with it."""
    return f"{round(100 * (1 - interval['alpha']))}%"


def _n_line(analysis: dict) -> str:
    # N is the scheduled repetitions: API errors can leave fewer graded ones.
    return f"{analysis['S']} scenarios × up to {analysis['N']} repetitions per cell"


def taxonomy(analysis: dict, out_path):
    """Figure 1: which failure mode moves, cell by cell. Bars are cell rates
    of each category; the whisker is the failure rate's 95% interval."""
    rates = analysis["cell_rates"]
    cells = [c.name for c in CELLS]
    validate_rows(cells)
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 7.0))
    left = [0.0] * len(cells)
    for cat in ("CORRECT",) + tuple(c for c in CATEGORIES if c != "CORRECT"):
        if cat == "CORRECT":
            widths = [1 - rates["failure"][c]["point"] for c in cells]
        else:
            widths = [rates[cat][c]["point"] for c in cells]
        ax.barh(cells, widths, left=left, color=CATEGORY_COLOR[cat], label=cat.lower())
        left = [lo + w for lo, w in zip(left, widths)]
    fail = [rates["failure"][c] for c in cells]
    # The whisker sits at x = 1 - failure, so the interval flips: [1 - hi, 1 - lo].
    correct_edge = [1 - f["point"] for f in fail]
    ax.errorbar(correct_edge, cells,
                xerr=_err(correct_edge, [1 - f["hi"] for f in fail], [1 - f["lo"] for f in fail]),
                fmt="none", ecolor="black", capsize=3, lw=1.2)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of graded calls")
    ax.set_ylabel("tool count – description – schema")
    ax.invert_yaxis()
    _style(ax, grid_axis="x")
    ax.legend(fontsize=_pt(PX_TEXT), ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.suptitle(
        f"Failure modes by formulation\n{_n_line(analysis)}\n"
        f"whisker: {_pct(fail[0])} interval on the failure rate",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, metadata=_NO_METADATA)
    return fig


def interaction(analysis: dict, out_path):
    """Figure 2: H1. Failure rate at low and high tool count, terse vs rich,
    averaged over schema strictness, with intervals."""
    m = analysis["marginal_count_richness"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 6.0))
    xs = [0, 1]
    # Terse and rich share each tick; a small offset keeps overlapping markers
    # and whiskers both visible.
    for richness, shift in (("terse", -0.03), ("rich", 0.03)):
        pts = [m[f"{count}-{richness}"] for count in ("low", "high")]
        ax.errorbar([x + shift for x in xs], [p["point"] for p in pts],
                    yerr=_err([p["point"] for p in pts], [p["lo"] for p in pts],
                              [p["hi"] for p in pts]),
                    color=RICHNESS_COLOR[richness], marker="o", capsize=4, lw=2,
                    label=f"{richness} descriptions")
    h1 = analysis["hypotheses"]["H1"]
    ax.set_xticks(xs, ["low (2–4 tools)", "high (20 tools)"])
    ax.set_xlim(-0.3, 1.3)
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Failure rate")
    ax.set_xlabel("Tool count")
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper left")
    fig.suptitle(
        f"Description richness by tool count\n{_n_line(analysis)}\n"
        f"interaction {100 * h1['point']:+.1f} pp ({_pct(h1)} interval "
        f"{100 * h1['lo']:+.1f} to {100 * h1['hi']:+.1f} pp), H1 {h1['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, metadata=_NO_METADATA)
    return fig


def flakiness(analysis: dict, out_path):
    """Figure 3: how often repetitions of one scenario in one cell disagree."""
    f = analysis["flakiness"]
    dist = f["distinct_categories_per_unit"]
    validate_rows(dist)
    # Keys are strings (the analysis dict is JSON-shaped). Every count from 1 to
    # the largest is drawn, so a count nobody hit is an empty bar, not a gap.
    counts = range(1, max(int(k) for k in dist) + 1)
    shares = [dist.get(str(k), 0) / f["units"] for k in counts]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    bars = ax.bar([f"{k} outcome{'s' if k != 1 else ''}" for k in counts], shares,
                  color="#2f6fd0")
    # A bar can be too short to see; its unit count tells a reader zero from small.
    ax.bar_label(bars, labels=[f"n={dist.get(str(k), 0)}" for k in counts], padding=2,
                 fontsize=_pt(PX_TEXT))
    # Headroom above 1.0 keeps the label of a bar near 1.0 inside the frame; the
    # ticks stop at 1.0, the largest possible share.
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("Share of (scenario, cell) units")
    ax.set_xlabel("Distinct categories among one unit's repetitions")
    _style(ax)
    e = f["ever_flip"]
    fig.suptitle(
        f"Rerun disagreement at the most deterministic setting\n"
        f"{f['units']} (scenario, cell) units, up to {analysis['N']} repetitions each\n"
        f"ever-flip fraction {e['point']:.3f} ({_pct(e)} interval {e['lo']:.3f} to {e['hi']:.3f})",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, metadata=_NO_METADATA)
    return fig


def identical_retry(analysis: dict, out_path):
    """Figure 4: H4. Identical-retry rate after an error, by message format,
    over persistent error kinds, with the pre-registered floor drawn."""
    rec = analysis["recovery"]
    fmts = [f for f in ("actionable", "opaque") if f in rec]
    validate_rows(fmts)
    cis = [rec[f]["identical_retry_persistent"] for f in fmts]
    for fmt, ci in zip(fmts, cis):
        if ci is None:
            raise ValueError(f"no persistent-kind identical-retry interval for {fmt}")
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    for x, (fmt, ci) in enumerate(zip(fmts, cis)):
        ax.bar(x, ci["point"], color=FORMAT_COLOR[fmt], width=0.6)
        ax.errorbar([x], [ci["point"]], yerr=_err([ci["point"]], [ci["lo"]], [ci["hi"]]),
                    fmt="none", ecolor="black", capsize=5, lw=1.2)
    h4 = analysis["hypotheses"]["H4"]
    ax.axhline(h4["floor"], color="#888888", ls="--", lw=1.2, label="pre-registered floor")
    ax.set_xticks(range(len(fmts)),
                  [f"{f} error\n{ci['n_scenarios']} scenarios" for f, ci in zip(fmts, cis)])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Identical-retry rate")
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper left")
    fig.suptitle(
        f"Repeating the failing call unchanged\n"
        f"persistent error kinds · up to {analysis['recovery_reps']} conversations\n"
        f"per scenario and format · whisker: {_pct(cis[0])} interval\n"
        f"H4 pairs {h4['n_scenarios']} scenarios · H4 {h4['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, metadata=_NO_METADATA)
    return fig


FIGURES = {
    "taxonomy": taxonomy,
    "interaction": interaction,
    "flakiness": flakiness,
    "identical_retry": identical_retry,
}
