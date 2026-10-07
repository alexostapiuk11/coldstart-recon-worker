"""Artifact 5's four figures, drawn from `data/a5/analysis.json`.

Same constraints as every artifact: N stated on the figure, no truncated
axes, intervals shown, legible at phone width, empty input refused, rendered
and looked at before anything is called done. Sizes are set in rendered
phone pixels through `harness.figure_guards.phone_pt`, so widening a canvas
cannot quietly shrink the text below the floor.

1. Throughput and TTFT against adapters registered, both regimes, the gap
   between them shaded: the heterogeneity cost.
2. KV capacity against adapters registered: the memory effect, as capacity.
3. The equivalence gate: synthetic against real, with the margin.
4. Cost per tenant per month, three strategies. Artifact 4's swap cost is the
   swapped bar here, in money, rather than a line on figure 1 (amendment §7).
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from harness.figure_guards import phone_pt, validate_rows

PX_TITLE = 10.0
PX_TEXT = 8.4
WIDTH_IN = 8.0

COLOR = {"concentrated": "#2f6fd0", "spread": "#c04a4a"}
LABEL = {"concentrated": "concentrated (1 adapter active)", "spread": "spread (all active)"}
STRATEGY_COLOR = {
    "dedicated": "#888888",
    "swapped": "#c88a2e",
    "sleep mode": "#8a6fc8",
    "adapter": "#2f6fd0",
}
GAP_COLOR = "#f2c9c9"
BAND_COLOR = "#dfe9f7"


def _pt(px: float) -> float:
    return phone_pt(px, WIDTH_IN)


def _style(ax) -> None:
    ax.tick_params(labelsize=_pt(PX_TEXT))
    ax.xaxis.label.set_size(_pt(PX_TEXT))
    ax.yaxis.label.set_size(_pt(PX_TEXT))
    ax.grid(alpha=0.3)


def _n_text(points) -> str:
    ns = sorted({p["n"] for p in points})
    return f"n = {ns[0]}" if len(ns) == 1 else f"n = {ns[0]}–{ns[-1]}"


def throughput_and_ttft(analysis: dict, out_path):
    points = validate_rows(analysis["sweep"]["points"])
    xs = [p["n_slots"] for p in points]
    fig, axes = plt.subplots(2, 1, figsize=(WIDTH_IN, 9.0), sharex=True)
    panels = (("throughput_tps", "Throughput (tokens/s)"), ("ttft_p50", "TTFT p50 (s)"))
    for ax, (metric, ylabel) in zip(axes, panels):
        medians = {}
        for regime in ("concentrated", "spread"):
            med = [p["median"][regime][metric] for p in points]
            lo = [p["interval"][regime][metric]["lo"] for p in points]
            hi = [p["interval"][regime][metric]["hi"] for p in points]
            medians[regime] = med
            ax.errorbar(
                xs, med,
                yerr=[[m - low for m, low in zip(med, lo)], [h - m for m, h in zip(med, hi)]],
                color=COLOR[regime], marker="o", capsize=4, lw=2, label=LABEL[regime],
            )
        ax.fill_between(
            xs, medians["concentrated"], medians["spread"],
            color=GAP_COLOR, label="heterogeneity cost",
        )
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        _style(ax)
    axes[0].legend(fontsize=_pt(PX_TEXT), loc="lower left")
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(xs, [str(x) for x in xs])
    axes[1].set_xlabel("Adapters registered (GPU slots)")
    fig.suptitle(
        f"Serving cost as adapters are added · {_n_text(points)} instances per point\n"
        "medians with 95% intervals",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def kv_capacity(analysis: dict, out_path):
    points = validate_rows(analysis["sweep"]["points"])
    context = analysis["prereg"]["context_length_tokens"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.5))
    for i, p in enumerate(points):
        values = p["memory"]["kv_by_instance"]
        ax.scatter([p["n_slots"]] * len(values), values, color="#555555", alpha=0.35, s=14,
                   label="per instance" if i == 0 else None)
    xs = [p["n_slots"] for p in points]
    ax.plot(xs, [p["memory"]["kv_tokens"] for p in points], color="#2f6fd0", marker="o", lw=2,
            label="median")
    ax.set_xscale("log", base=2)
    ax.set_xticks(xs, [str(x) for x in xs])
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Adapters registered (GPU slots)")
    ax.set_ylabel("KV cache capacity (tokens)")
    first, last = points[0]["memory"], points[-1]["memory"]
    ax.text(
        0.02, 0.05,
        f"max concurrent requests at {context:,} tokens: "
        f"{first['max_concurrency_context']} → {last['max_concurrency_context']}",
        transform=ax.transAxes, fontsize=_pt(PX_TEXT),
    )
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper right")
    _style(ax)
    ax.set_title(
        f"KV capacity by slot count · {_n_text(points)} instances per point",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def equivalence(analysis: dict, out_path):
    gate = analysis["gate"]
    if "metrics" not in gate:
        raise ValueError(f"the gate has no verdict to draw: {gate['verdict']}")
    delta = gate["delta"]
    fig, axes = plt.subplots(2, 1, figsize=(WIDTH_IN, 7.5))
    names = {"ttft_p50": "TTFT p50", "throughput_tps": "Throughput"}
    for ax, metric in zip(axes, ("ttft_p50", "throughput_tps")):
        m = gate["metrics"][metric]
        per = validate_rows([{"v": v} for v in m["per_instance"]])
        ax.axvspan(-100 * delta, 100 * delta, color=BAND_COLOR, label=f"margin ±{100 * delta:.1f}%")
        ax.axvline(0, color="#333333", lw=1)
        ax.scatter([100 * r["v"] for r in per], [1.0] * len(per), color="#555555", alpha=0.5, s=16,
                   label="per instance")
        for y, key, label, color in (
            (0.55, "statistic", "synthetic − real, 90% interval", "#c04a4a"),
            (0.2, "resolution", "real − real, 90% interval", "#2f6fd0"),
        ):
            ci = m[key]
            ax.errorbar(100 * ci["point"], y,
                        xerr=[[100 * (ci["point"] - ci["lo"])], [100 * (ci["hi"] - ci["point"])]],
                        color=color, marker="o", capsize=5, lw=2, label=label)
        span = max(2 * delta, *(abs(r["v"]) for r in per)) * 100 * 1.15
        ax.set_xlim(-span, span)
        ax.set_ylim(0, 1.3)
        ax.set_yticks([])
        ax.set_xlabel(f"{names[metric]}: relative difference (%)")
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=_pt(PX_TEXT), loc="lower center", ncol=2)
    fig.suptitle(
        f"Synthetic vs real adapters · verdict: {gate['verdict']} · n = {gate['n']} instances",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig.savefig(out_path, dpi=150)
    return fig


# The base model this artifact served (the post's Method); artifact 4's comes
# from its cost file, through `a4_context`.
ADAPTER_MODEL = "Qwen3-4B"


def a4_bins_missed(context: dict) -> int:
    """Judged latency bins outside the band of real repeats: compared minus
    agreeing. Derived here; artifact 4's file stores only the two counts."""
    latency = context["validation"]["latency"]
    return latency["compared"] - latency["agreeing"]


def a4_note(context: dict) -> str:
    """The lines the cost figure adds under its axis when artifact 4's file
    carries its model class and validation outcome. Written for a failed
    validation; any other outcome needs its own wording, so it is refused."""
    validation = context["validation"]
    if validation["outcome"] != "failed":
        raise ValueError(
            f"artifact 4's validation outcome is {validation['outcome']!r}; the cost "
            "figure's note is written for 'failed' only"
        )
    a4_model = context["model"]["id"].split("/")[-1]
    return (
        f"dedicated and swapped: artifact 4's simulator, {a4_model}; adapter: {ADAPTER_MODEL}\n"
        f"the simulator failed its validation ({a4_bins_missed(context)} of "
        f"{validation['latency']['compared']} bins missed); none of its numbers is validated"
    )


def cost_per_tenant(analysis: dict, out_path):
    rows = validate_rows(analysis["cost_table"])
    prereg = analysis["prereg"]
    context = analysis.get("a4_context")
    extra = "" if context is None else "\n" + a4_note(context)
    # Two more note lines need more room under the axis; without them the
    # canvas is exactly what it was before artifact 4's context existed.
    height, bottom = (4.6, 0.14) if context is None else (5.3, 0.19)
    fig, ax = plt.subplots(figsize=(WIDTH_IN, height))
    labels = [r["strategy"] for r in rows]
    costs = [r["cost"] for r in rows]
    bars = ax.barh(labels, costs, color=[STRATEGY_COLOR[s] for s in labels])
    for bar, row in zip(bars, rows):
        if row.get("upper_bound"):
            bar.set_hatch("//")
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" ${row['cost']:,.0f}",
                va="center", fontsize=_pt(PX_TEXT))
    ax.set_xlim(0, max(costs) * 1.3)
    ax.invert_yaxis()
    ax.set_xlabel("Cost per tenant per month (USD)")
    fig.text(
        0.02, 0.02,
        f"${prereg['gpu_hourly_rate']}/GPU-hour · {prereg['requests_per_tenant_month']:,.0f} "
        "requests/tenant/month\nadapter bar: tenants are a lower bound, so its cost is an upper bound"
        + extra,
        fontsize=_pt(PX_TEXT * 0.9),
    )
    _style(ax)
    ax.set_title(
        f"Cost per tenant per month · adapter: {analysis['tenants']['tenants']} tenants per GPU",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout(rect=(0, bottom, 1, 1))
    fig.savefig(out_path, dpi=150)
    return fig


FIGURES = {
    "throughput_ttft": throughput_and_ttft,
    "kv_capacity": kv_capacity,
    "equivalence": equivalence,
    "cost_per_tenant": cost_per_tenant,
}
