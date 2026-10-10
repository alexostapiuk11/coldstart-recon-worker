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


def _pt(px: float) -> float:
    return phone_pt(px, WIDTH_IN)


def _style(ax) -> None:
    ax.tick_params(labelsize=_pt(PX_TEXT))
    ax.xaxis.label.set_size(_pt(PX_TEXT))
    ax.yaxis.label.set_size(_pt(PX_TEXT))
    ax.grid(alpha=0.3, axis="x" if ax.get_ylabel() == "" else "y")


def _n_line(analysis: dict) -> str:
    return f"{analysis['S']} scenarios × {analysis['N']} repetitions per cell"


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
    correct_edge = [1 - f["point"] for f in fail]
    ax.errorbar(correct_edge, cells,
                xerr=[[f["hi"] - f["point"] for f in fail], [f["point"] - f["lo"] for f in fail]],
                fmt="none", ecolor="black", capsize=3, lw=1.2)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Share of graded calls")
    ax.set_ylabel("tool count – description – schema")
    ax.invert_yaxis()
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.suptitle(
        f"Failure modes by formulation\n{_n_line(analysis)}\n"
        "whisker: 95% interval on the failure rate",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def interaction(analysis: dict, out_path):
    """Figure 2: H1. Failure rate at low and high tool count, terse vs rich,
    averaged over schema strictness, with 95% intervals."""
    m = analysis["marginal_count_richness"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 6.0))
    xs = [0, 1]
    for richness in ("terse", "rich"):
        pts = [m[f"{count}-{richness}"] for count in ("low", "high")]
        ax.errorbar(xs, [p["point"] for p in pts],
                    yerr=[[p["point"] - p["lo"] for p in pts], [p["hi"] - p["point"] for p in pts]],
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
        f"interaction {h1['point']:+.3f} (95% interval {h1['lo']:+.3f} to {h1['hi']:+.3f}), "
        f"H1 {h1['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def flakiness(analysis: dict, out_path):
    """Figure 3: how often repetitions of one scenario in one cell disagree."""
    f = analysis["flakiness"]
    dist = f["distinct_categories_per_unit"]
    keys = sorted(dist, key=int)
    validate_rows(keys)
    shares = [dist[k] / f["units"] for k in keys]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    ax.bar([f"{k} outcome{'s' if k != '1' else ''}" for k in keys], shares, color="#2f6fd0")
    ax.set_ylim(0, 1)
    ax.set_ylabel("Share of (scenario, cell) units")
    ax.set_xlabel("Distinct categories among one unit's repetitions")
    _style(ax)
    e = f["ever_flip"]
    fig.suptitle(
        f"Rerun disagreement at the most deterministic setting\n"
        f"{f['units']} (scenario, cell) units, {analysis['N']} repetitions each\n"
        f"ever-flip fraction {e['point']:.3f} (95% interval {e['lo']:.3f} to {e['hi']:.3f})",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def identical_retry(analysis: dict, out_path):
    """Figure 4: H4. Identical-retry rate after an error, by message format,
    over persistent error kinds, with the pre-registered floor drawn."""
    rec = analysis["recovery"]
    fmts = [f for f in ("actionable", "opaque") if f in rec]
    validate_rows(fmts)
    cis = [rec[f]["identical_retry_persistent"] for f in fmts]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.0))
    for x, (fmt, ci) in enumerate(zip(fmts, cis)):
        point = ci["point"] if ci else rec[fmt]["identical_retry"]
        ax.bar(x, point, color=FORMAT_COLOR[fmt], width=0.6)
        if ci:
            ax.errorbar(x, point, yerr=[[point - ci["lo"]], [ci["hi"] - point]],
                        fmt="none", ecolor="black", capsize=5, lw=1.2)
    h4 = analysis["hypotheses"]["H4"]
    ax.axhline(h4["floor"], color="#888888", ls="--", lw=1.2, label="pre-registered floor")
    ax.set_xticks(range(len(fmts)), [f"{f} error" for f in fmts])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Identical-retry rate")
    _style(ax)
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper left")
    n = h4["n_scenarios"]
    fig.suptitle(
        f"Repeating the failing call unchanged\n"
        f"{n} scenarios, persistent error kinds · H4 {h4['verdict']}",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


FIGURES = {
    "taxonomy": taxonomy,
    "interaction": interaction,
    "flakiness": flakiness,
    "identical_retry": identical_retry,
}
