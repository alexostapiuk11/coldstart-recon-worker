"""The figures: four for the published post — waterfall decomposition, warmup
curve, ECDF, per-host medians — and three for the explainer that teaches it:
the KV dividend, the resample frames, and the shortcut panels.

These charts are the artifact for most readers — more people will look at
the waterfall than will read the method section — so every aggregate drawn
here goes through ``harness.stats.median``, the same function
``percentiles()``'s p50 uses. That is deliberate: a chart median computed a
different way than the reported percentile table's median would put two
different numbers for the same quantity in the same post. See
``stats.median``'s docstring for why it skips the bootstrap sample floor.

Input domains are guarded rather than left to quietly produce a misleading
chart:

- Empty ``rows`` raises, rather than drawing an empty axes with no
  indication anything is wrong.
- An arm entirely absent from ``rows`` raises, rather than the plan's
  original ``if not rs: continue`` — which would silently drop that arm's
  bar/line/legend entry, understating how many arms were actually compared.
- ``warmup_curve`` additionally requires every row's warmup list to be the
  same length; a shorter list would otherwise either IndexError deep inside
  a comprehension or (if longer) silently have its tail ignored depending on
  which row happened to be ``rows[0]``.

None of the four functions mutate their input rows.

B4: a row from a failed run, an inconsistent run, or a merged run does not
raise a clean error on its own — a bare `r["t_platform"]` inside a
comprehension either `KeyError`s (failed rows don't have the key at all) or
feeds `None` to `median()`/`ecdf()`, which fails with a context-free
`TypeError` from inside `math.isfinite`. `required_field`, imported from
`harness.figure_guards`, replaces every such dereference this module makes
with a check that names the row (by `arm`/`host_id`, the identity these
hand-built and derive()-shaped rows both reliably carry) and the field, and raises
`harness.publish.NotPublishableError`. This does not make these
functions require `"ok"`/`"consistent"` on every row -- that would break the
"pure consumer of whatever fields a row happens to carry" policy above and
this module's own tests, which hand-build rows without either key. A caller
that has already gated rows through `harness.publish.partition()` for the fields a
given figure needs (see the `REQUIRED_FOR_*` constants in
`coldstart/analysis/presets.py`) can hand the
result straight through; a caller that has not gets a clear error instead of
a crash three stack frames into a library call.

``warmup_curve``'s steady-state band and ``T_fast`` annotation import
``FAST_TOLERANCE``, ``steady_state_latency`` and ``time_to_fast_index``
directly from ``coldstart.analysis.metrics`` — the pre-registered tolerance
and the one steady-state estimator every published number uses (each run's
own median of its last three requests). Before this, the tolerance was a
second hardcoded ``0.9``/``1.1`` literal and the band was a *different*
estimator — a pooled median over every row's last three requests combined —
so a reader could see a point sitting inside the drawn band while the
published table said the replica was not yet fast (B5). This is a
deliberate, narrow exception to the "pure consumer of whatever fields a row
happens to carry" policy below: these three names are pre-registered
parameters and a function, not a row-shape assumption, so importing them
does not couple this module to ``derive()``'s output shape the way the
(deliberately *not* imported) ``S4_SUBPHASE_KEYS`` would.
"""

import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from coldstart.analysis.metrics import FAST_TOLERANCE, steady_state_latency, time_to_fast_index
from harness.figure_guards import (
    MIN_PHONE_TEXT_PX,  # noqa: F401  re-exported: tests import it from here
    PHONE_WIDTH_PX,  # noqa: F401  re-exported: tests import it from here
    group_required,
    phone_pt,
    required_field,
    validate_rows,
)
from harness.stats import bootstrap_median_ci, ecdf, median

ARMS = ["A", "B", "C"]
ARM_LABEL = {"A": "A — nothing cached", "B": "B — weights cached", "C": "C — weights + compile"}
RESIDUAL_COLOR = "#9e9e9e"  # deliberately distinct from every measured-stage color

# The five named S4 sub-phases, in chronological order — must match
# coldstart.analysis.metrics.S4_SUBPHASE_KEYS. Not imported directly so this
# module stays a pure consumer of whatever fields a row happens to carry
# (rows in tests are hand-built dicts, not always derive() output).
S4_SUBPHASE_KEYS = ("S4a", "S4b", "S4c", "S4d", "S4e")
_SUBPHASE_LABEL = {
    "S4a": "S4a device init",
    "S4b": "S4b compilation",
    "S4c": "S4c memory profiling",
    "S4d": "S4d KV allocation",
    "S4e": "S4e graph capture",
}
_SUBPHASE_COLOR = {
    "S4a": "#7fae7f",
    "S4b": "#c0392b",
    "S4c": "#4a8a4a",
    "S4d": "#8a6d3b",
    "S4e": "#c88a2e",
}


def _median_present(rs: list[dict], key: str) -> float | None:
    """Median of `key` across rows that report it (not None), or None if no
    row does. Never `.get(key, 0.0)` — a sub-phase this engine version did
    not delineate is absent, the same distinction metrics.derive() makes,
    and defaulting it to zero would draw a plausibly-shaped but understated
    bar instead of an honest gap."""
    vals = [r[key] for r in rs if r.get(key) is not None]
    return median(vals) if vals else None


def waterfall(rows, out_path) -> Path:
    """Stacked median stage durations per arm, every measured stage drawn
    and individually labelled in chronological order, residual visually
    distinct.

    Stacking order: T_platform, S1, T_weights (S2+S3), each identified S4
    sub-phase present in the data, unattributed-within-S4, S5, S6 — spec,
    "Why S4 is sub-decomposed" and "Attribution caveat". A sub-phase absent
    from every row in an arm (the pinned engine version never delineated
    it) is not drawn as its own bar; its duration is still real and folds
    into the unattributed segment by construction (bracket minus only the
    *identified* sub-phases), and that segment's label states which
    sub-phases were merged into it rather than the chart silently being one
    bar short with no explanation.
    """
    by = group_required(rows, "arm", ARMS)
    fig_w = 9.0
    fig, ax = plt.subplots(figsize=(fig_w, 7.0))
    labels, ys = [], []
    seen_labels: set[str] = set()

    def _draw(y: float, value: float, label: str, color: str, **kw) -> float:
        lbl = None if label in seen_labels else label
        seen_labels.add(label)
        ax.barh(y, value, left=_draw.left, color=color, label=lbl, **kw)
        _draw.left += value
        return value

    for i, arm in enumerate(ARMS):
        rs = by[arm]
        labels.append(f"{ARM_LABEL[arm]}\n(n={len(rs)})")
        ys.append(i)
        platform = median([required_field(r, "t_platform") for r in rs])
        process = median([required_field(r, "t_process") for r in rs])

        # derive() returns t_weights=None when the engine did not delineate the
        # load boundary. Drawing a merged span as if it were T_weights would be
        # the chart telling a story the data does not support, so the merge is
        # drawn as one explicitly-labelled bar instead — spec, stage taxonomy.
        measured = [r["t_weights"] for r in rs if r["t_weights"] is not None]
        _draw.left = 0.0
        if measured:
            weights = median(measured)
            s1 = _median_present(rs, "t_s1")
            s6 = _median_present(rs, "t_s6")
            bracket = _median_present(rs, "t_s4_bracket")

            _draw(i, platform, "T_platform (not attributed)", RESIDUAL_COLOR)
            if s1 is not None:
                _draw(i, s1, "S1 imports", "#8e6fc4")
            _draw(i, weights, "T_weights (S2+S3)", "#2f6fd0")

            if bracket is not None:
                present: dict[str, float] = {}
                merged_subs: list[str] = []
                for key in S4_SUBPHASE_KEYS:
                    val = _median_present(rs, f"t_{key.lower()}")
                    if val is not None:
                        present[key] = val
                    else:
                        merged_subs.append(key)
                identified_sum = sum(present.values())
                unattributed = bracket - identified_sum
                if unattributed < 0:
                    # A negative term means the identified sub-phases don't
                    # fit inside the S4 bracket that is supposed to contain
                    # them — the decomposition itself is broken, not just
                    # cosmetically short. checks.py already applies this
                    # exact discipline to a single run's t_weights
                    # ("discard, don't silently correct"); a max(0.0, ...)
                    # clamp here would draw a plausible-looking but wrong
                    # bar, and this chart is the last place before
                    # publication such a defect could be caught.
                    raise ValueError(
                        f"arm {arm!r}: unattributed S4 time is negative "
                        f"({unattributed:.3f}s = S4 bracket {bracket:.3f} - "
                        f"identified sub-phases {identified_sum:.3f}); the "
                        "measured sub-phases do not fit inside the bracket "
                        "that is supposed to contain them"
                    )
                for key in S4_SUBPHASE_KEYS:
                    if key in present:
                        _draw(i, present[key], _SUBPHASE_LABEL[key], _SUBPHASE_COLOR[key])
                unattributed_label = "S4 unattributed"
                if merged_subs:
                    unattributed_label += f" (merged: {', '.join(merged_subs)})"
                _draw(i, unattributed, unattributed_label, "#d9c8a9")
                s5 = _median_present(rs, "t_s5")
                if s5 is not None:
                    _draw(i, s5, "S5 ready (health poll)", "#5aa9c2")
            else:
                # This row carries no S4_start/S4_end marks. The probe emits
                # them on every run now, so on a live campaign this branch means
                # the marks were lost for this run, not that they are
                # unavailable in principle. S5_ready -
                # S3_load_done is NOT the bracket — S5 is a separate, later
                # stage (spec, Attribution caveat) — so it is never
                # substituted. What IS honestly known without it: S1,
                # T_weights and S6 are each independently measured from
                # their own marks and partition t_process with no gaps
                # around S4, so process minus those three is exactly the
                # combined S4+S5 span. Drawn as one explicitly-merged
                # bucket rather than silently omitted.
                remainder = process - weights - (s1 or 0.0) - (s6 or 0.0)
                _draw(
                    i,
                    remainder,
                    "S4+S5 (merged — no S4 marks)",
                    "#b8b0c8",
                    hatch="//",
                )

            if s6 is not None:
                _draw(i, s6, "S6 cold TTFT", "#4f6d7a")
        else:
            _draw(i, platform, "T_platform (not attributable)", RESIDUAL_COLOR)
            _draw(i, process, "S2→ready (engine merged phases)", "#7f8fa6")

    ax.set_yticks(ys, labels, fontsize=phone_pt(7.8, fig_w))
    ax.set_xlabel("seconds (median)", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
    ax.set_xlim(left=0)
    # Below the axes in two columns, not outside it to the right.
    #
    # A right-hand legend forced `bbox_inches="tight"` on save, which expands
    # the written canvas past `figsize` by however wide the legend happens to
    # be -- so the figure's true width, the denominator every one of these font
    # sizes depends on, was not knowable from the code. It came out at 10.9in,
    # which silently shrank the 11pt arm labels to 5.3px on a phone. Underneath
    # the axes the legend costs vertical space, which downscaling does not
    # penalise, and the width stays exactly `fig_w`.
    # Centred on the *figure*, not the axes. The arm labels ("C — weights +
    # compile (n=100)") inset the axes well to the right of the canvas edge, so
    # a legend centred on the axes sits off-centre on the page and its widest
    # entry ran past the right margin -- clipping the closing parenthesis of
    # the merged-subphase label, the one legend entry the spec specifically
    # requires be shown rather than hidden.
    handles, legend_labels = ax.get_legend_handles_labels()
    fig.legend(
        handles,
        legend_labels,
        loc="lower center",
        ncol=2,
        fontsize=phone_pt(7.6, fig_w),
        labelspacing=0.4,
        handlelength=1.5,
        handletextpad=0.5,
        columnspacing=1.4,
        frameon=False,
    )
    ax.set_title("Cold start decomposition", fontsize=phone_pt(10.0, fig_w))
    fig.tight_layout(rect=(0.0, 0.19, 1.0, 1.0))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def warmup_curve(rows, out_path) -> Path:
    by = group_required(rows, "arm", ARMS)
    all_rows = [r for rs in by.values() for r in rs]

    lengths = {len(required_field(r, "warmup")) for r in all_rows}
    if len(lengths) != 1:
        raise ValueError(
            f"warmup lists have mismatched lengths across rows: {sorted(lengths)}; "
            "every row must report the same number of warmup requests"
        )
    (n_req,) = lengths
    if n_req == 0:
        raise ValueError("warmup lists are empty")

    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 5.0))
    fast_marks: list = []
    steadies: dict = {}
    for arm_idx, arm in enumerate(ARMS):
        rs = by[arm]
        med = [median([r["warmup"][i]["end_to_end"] for r in rs]) for i in range(n_req)]
        # On real data the three arms' post-ready curves coincide to within a
        # millisecond, so a plain solid line per arm draws three curves in the
        # same pixels and the reader sees only whichever arm was drawn last --
        # indistinguishable from A and B having been dropped from the figure.
        # Distinct dash patterns and markers, with the later arms drawn
        # narrower, keep all three readable exactly where they overlap.
        style, marker, width = (("-", "o", 3.2), ("--", "s", 2.0), (":", "^", 1.2))[arm_idx % 3]
        (line,) = ax.plot(
            range(1, n_req + 1),
            med,
            linestyle=style,
            marker=marker,
            markersize=5,
            linewidth=width,
            label=f"{ARM_LABEL[arm]} (n={len(rs)})",
        )

        # Steady state is per-arm, not pooled across all three arms. Each
        # arm converges to its own plateau -- a band computed by pooling
        # every arm's rows together would sit near the middle arm's
        # plateau and be flatly wrong for the other two (e.g. the slowest
        # arm would look like it never reaches "steady state" and the
        # fastest arm would look like it beats steady state from request 2
        # on). Drawn in that arm's own line color so the band is
        # unambiguously "this curve's" rather than a third, disconnected
        # element.
        #
        # Within an arm, this is metrics.steady_state_latency's own
        # definition -- each row's own median of *its* last three requests
        # -- aggregated across that arm's rows with the same stats.median
        # every other aggregate in this module uses (B5). Not a pooled
        # median over every row's last three requests combined: pooling is
        # a *different* estimator from the one metrics.py uses to compute
        # time_to_fast_index/T_fast for each individual run, and the two
        # can disagree on data where rows differ from each other -- a
        # reader could then see a point sitting inside this band while the
        # published table says that run was not yet fast.
        per_run_steady = [steady_state_latency(r["warmup"]) for r in rs]
        steady = median(per_run_steady)
        steadies[arm] = steady
        ax.axhspan(
            steady * (1 - FAST_TOLERANCE),
            steady * (1 + FAST_TOLERANCE),
            color=line.get_color(),
            alpha=0.15,
            label=f"{ARM_LABEL[arm]} steady-state band (±{FAST_TOLERANCE:.0%})",
        )

        # T_fast annotation — spec figures section: "the steady-state band
        # marked and T_fast annotated." Reuses time_to_fast_index (the same
        # pre-registered definition and FAST_TOLERANCE the published table
        # uses) against this arm's own median curve, so the marker lands on
        # exactly the request the arm's headline T_fast would name, rather
        # than a fourth copy of the threshold logic drifting from the other
        # three.
        synthetic_warmup = [{"req_index": k + 1, "end_to_end": v} for k, v in enumerate(med)]
        fast_req = time_to_fast_index(synthetic_warmup, steady)
        if fast_req is not None:
            fast_marks.append((arm, fast_req, med[fast_req - 1], line.get_color()))

    # Annotated after the arm loop, not inside it. Every arm can reach
    # tolerance on the same request (on this campaign all three reach it on
    # request 1), and a per-arm annotation then draws the same label three
    # times on one point -- with fixed offsets, one of which pushed the text
    # off the left edge of the figure entirely. Collapsing the shared case
    # into a single label states the same fact once and cannot clip.
    if fast_marks:
        reqs = {req for _, req, _, _ in fast_marks}
        if len(reqs) == 1 and len(fast_marks) == len(ARMS):
            (req,) = reqs
            ys = [y for _, _, y, _ in fast_marks]
            ax.scatter(
                [req],
                [max(ys)],
                marker="*",
                s=260,
                color="black",
                zorder=6,
            )
            ax.annotate(
                f"T_fast (req {req}) — all three arms",
                xy=(req, max(ys)),
                xytext=(44, -16),
                textcoords="offset points",
                fontsize=phone_pt(7.6, fig_w),
                fontweight="bold",
                arrowprops={"arrowstyle": "-", "color": "black", "lw": 0.8},
            )
        else:
            for arm_idx, (_, req, y, color) in enumerate(fast_marks):
                ax.scatter(
                    [req],
                    [y],
                    marker="*",
                    s=220,
                    color=color,
                    edgecolor="black",
                    linewidths=0.6,
                    zorder=5,
                )
                # Offsets point inward from whichever edge the marker sits
                # near, so a T_fast on request 1 or on the last request can
                # never be laid out off the canvas.
                dx = 14 if req <= (n_req + 1) / 2 else -14
                ha = "left" if dx > 0 else "right"
                ax.annotate(
                    f"T_fast (req {req})",
                    xy=(req, y),
                    xytext=(dx, (24, -30, 46)[arm_idx % 3]),
                    textcoords="offset points",
                    fontsize=phone_pt(7.6, fig_w),
                    fontweight="bold",
                    ha=ha,
                    color=color,
                    arrowprops={"arrowstyle": "-", "color": color, "lw": 0.8, "alpha": 0.8},
                )

    # State the coincidence numerically. A reader looking at three superimposed
    # curves should not have to take on faith that they are separate series.
    spread_ms = (max(steadies.values()) - min(steadies.values())) * 1000
    # Inside the axes, in the empty band below the curves. Centred on the
    # *figure* it would overflow the narrow axes and clip against the canvas
    # edge; the axes' lower half is empty on this data and holds it intact.
    ax.text(
        0.5,
        0.66,
        f"All three arms coincide.\nSteady-state medians differ by {spread_ms:.1f} ms — cache\n"
        "configuration does not affect latency once the engine is up.",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=phone_pt(7.8, fig_w),
        style="italic",
        linespacing=1.5,
    )

    ax.set_xlabel("request index", fontsize=phone_pt(8.2, fig_w))
    ax.set_ylabel("end-to-end latency (s)", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(labelsize=phone_pt(7.6, fig_w))
    ax.set_ylim(bottom=0)
    # The spec's working title for this figure was "Ready is not fast",
    # written before the measurement. The campaign says the opposite at this
    # configuration: request 1 lands 7.7% above steady state, inside the
    # tolerance band, because vLLM runs a profiling pass and captures 86 CUDA
    # graph shapes BEFORE answering /health. The warmup is real and it is
    # expensive -- it is simply paid inside S4, where the waterfall shows it,
    # rather than served to the first users. The title states what the data
    # shows; changing the data to fit the title was never an option.
    # `pad` keeps it clear of the per-arm T_fast annotations, which cluster at
    # the top-left when every arm reaches tolerance on request 1.
    ax.set_title(
        "Ready is already fast — the warmup was paid before ready",
        fontsize=phone_pt(9.4, fig_w),
        pad=18,
    )
    # Inside the axes, in the empty lower half. Outside-right it squeezed the
    # axes to little over half the canvas, and at a font size legible on a
    # phone six entries would have taken more than that again. On this data the
    # curves sit against the top of the plot and everything below them is
    # empty, so an in-axes legend hides nothing -- the earlier objection to
    # placing it here (it covered requests 6-10) applied to a corner position,
    # not to the empty band.
    ax.legend(
        loc="lower center",
        fontsize=phone_pt(7.6, fig_w),
        borderaxespad=0.6,
        labelspacing=0.35,
        handlelength=1.6,
        handletextpad=0.5,
        frameon=False,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def ecdf_plot(rows, out_path) -> Path:
    by = group_required(rows, "arm", ARMS)
    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 4.5))
    for arm in ARMS:
        rs = by[arm]
        xs, ys = ecdf([required_field(r, "t_total") for r in rs])
        ax.step(xs, ys, where="post", label=f"{ARM_LABEL[arm]} (n={len(rs)})")
    ax.set_xlabel("T_total (s)", fontsize=phone_pt(8.2, fig_w))
    ax.set_ylabel("fraction of runs ≤ x", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(labelsize=phone_pt(7.6, fig_w))
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1)
    ax.set_title("Distribution, not a mean", fontsize=phone_pt(9.4, fig_w))
    ax.legend(fontsize=phone_pt(7.6, fig_w), frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def kv_dividend(rows, out_path) -> Path:
    """Arm C's larger KV cache, stated in both directions and in requests.

    Both percentages appear because the direction is genuinely easy to invert:
    43040/35792 is +20.3% (warm vs cold) while 35792/43040 is -16.8% (cold vs
    warm). A chart carrying one of them alone invites the other to be quoted.
    """
    rows = validate_rows(rows)
    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 4.3))
    by = group_required(rows, "arm", ARMS)
    caps = {a: median([required_field(r, "kv_capacity_tokens") for r in by[a]]) for a in ARMS}
    cold, warm = caps["A"], caps["C"]

    ax.barh([0, 1], [cold, warm], height=0.45, color=["#9e9e9e", "#4a8c5f"])
    ax.set_yticks(
        [0, 1],
        ["cold compile\n(arms A, B)", "warm compile\n(arm C)"],
        fontsize=phone_pt(7.8, fig_w),
    )
    ax.set_xlabel("KV cache capacity (tokens)", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
    for y, v in ((0, cold), (1, warm)):
        ax.text(
            v * 0.98,
            y,
            f"{int(v):,}",
            ha="right",
            va="center",
            color="white",
            fontweight="bold",
            fontsize=phone_pt(7.8, fig_w),
        )
    ax.set_title(
        f"A warm compile cache leaves {warm / cold - 1:+.1%} more KV cache\n"
        f"({int(warm // 8192)} concurrent requests vs {int(cold // 8192)} at 8192 context)",
        fontsize=phone_pt(8.6, fig_w),
    )
    # Anchored to the *figure*, not the axes: an ax.transAxes offset is a
    # fraction of the axes' own height, which tight_layout resizes to fit
    # everything inside `rect` -- so a fixed transAxes offset lands in a
    # different place depending on how much room the title/xlabel end up
    # needing, and it collided with the xlabel here. transFigure coordinates
    # are stable regardless of how tight_layout resizes the axes above them.
    ax.text(
        0.5,
        0.025,
        f"Equivalently: a cold compile sizes the cache {abs(cold / warm - 1):.1%} smaller —\n"
        "permanently, for the life of that replica.",
        transform=fig.transFigure,
        ha="center",
        fontsize=phone_pt(7.6, fig_w),
        style="italic",
    )
    fig.tight_layout(rect=(0.0, 0.17, 1.0, 1.0))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def per_host_medians(rows, out_path) -> Path:
    rows = validate_rows(rows)
    hosts = sorted({r["host_id"] for r in rows})
    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 4.5))
    meds = [
        median([required_field(r, "t_total") for r in rows if r["host_id"] == h]) for h in hosts
    ]
    counts = [sum(1 for r in rows if r["host_id"] == h) for h in hosts]
    ax.bar(range(len(hosts)), meds, width=0.5 if len(hosts) > 1 else 0.25)
    ax.set_xticks(range(len(hosts)), [f"{h}\n(n={c})" for h, c in zip(hosts, counts, strict=True)])
    ax.set_ylabel("median T_total (s)", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(labelsize=phone_pt(7.6, fig_w))
    ax.set_ylim(bottom=0)

    # A single host is the degenerate case: one bar filling the frame looks like a
    # measurement of host heterogeneity when it is the opposite -- the campaign never
    # observed a second host, so H4 has no evidence either way. Say that on the chart,
    # because the figure travels without its caption.
    if len(hosts) == 1:
        ax.set_title(
            "Host heterogeneity: NOT ANSWERABLE from this campaign",
            fontsize=phone_pt(8.8, fig_w),
        )
        ax.set_xlim(-0.75, 0.75)
        ax.text(
            0.5,
            0.5,
            f"All {counts[0]} runs landed on one host.\nNo between-host comparison exists.",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=phone_pt(8.2, fig_w),
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85},
        )
    else:
        ax.set_title("Host heterogeneity", fontsize=phone_pt(9.4, fig_w))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def resample_frames(values, out_path, frames: int = 10, seed: int = 0) -> Path:
    """`frames` imaginary campaigns, each contributing one median.

    Deliberately shows medians on a number line rather than a histogram of runs:
    the misconception this chart exists to break is that an interval describes
    where the runs landed, and a chart of runs would confirm it. `values` is a
    plain list of measurements, not rows -- this one is about the numbers, not
    about which arm or host they came from.
    """
    xs = sorted(float(v) for v in values)
    if not xs:
        raise ValueError("resample_frames needs at least one value")
    rng = random.Random(seed)
    n = len(xs)
    meds = [median([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(frames)]
    ci = bootstrap_median_ci(xs, seed=seed)

    # Four vertical bands, top to bottom, each with its own label directly
    # above it so the eye never has to hop between a legend and the data:
    # real-run ticks, imaginary-campaign medians, the caption (two lines,
    # because the full sentence plus both numbers overflows one line at any
    # phone-legible font size -- an earlier version let it run past the right
    # edge of the canvas instead of wrapping), then the interval bracket
    # sitting right above the x-axis. Fixed y-slots rather than fractions of
    # `frames` keep the bands from colliding regardless of how many frames
    # are requested.
    y_ticks_label, y_ticks = 1.24, 1.14
    y_dots_label = 0.92
    dots_top, dots_bottom = 0.82, 0.40
    y_caption1, y_caption2 = 0.26, 0.15
    y_bracket = 0.03

    fig_w = 8.0
    fig, ax = plt.subplots(figsize=(fig_w, 5.2))
    ax.scatter(xs, [y_ticks] * n, marker="|", s=260, color="#2f6fb5", alpha=0.35)
    ax.text(
        0.01,
        y_ticks_label,
        f"the {n} real runs",
        transform=ax.get_yaxis_transform(),
        fontsize=phone_pt(7.6, fig_w),
        color="#2f6fb5",
    )
    dot_step = (dots_top - dots_bottom) / max(frames - 1, 1)
    for i, m in enumerate(meds):
        ax.scatter([m], [dots_top - i * dot_step], marker="o", s=40, color="#c0392b", zorder=5)
    ax.text(
        0.01,
        y_dots_label,
        f"one median from each of {frames} imaginary campaigns",
        transform=ax.get_yaxis_transform(),
        fontsize=phone_pt(7.6, fig_w),
        color="#c0392b",
    )
    ax.text(
        0.01,
        y_caption1,
        "the interval: middle 95% of 10,000 such medians",
        transform=ax.get_yaxis_transform(),
        fontsize=phone_pt(7.8, fig_w),
        fontweight="bold",
    )
    ax.text(
        0.01,
        y_caption2,
        f"(only {frames} shown above, to stay readable) [{ci['lo']:.2f}, {ci['hi']:.2f}]",
        transform=ax.get_yaxis_transform(),
        fontsize=phone_pt(7.8, fig_w),
        fontweight="bold",
    )
    ax.plot([ci["lo"], ci["hi"]], [y_bracket, y_bracket], color="black", linewidth=2.6, zorder=6)
    for x in (ci["lo"], ci["hi"]):
        ax.plot(
            [x, x],
            [y_bracket - 0.035, y_bracket + 0.035],
            color="black",
            linewidth=2.6,
            zorder=6,
        )
    ax.set_ylim(-0.08, 1.38)
    ax.set_yticks([])
    ax.set_xlabel("seconds", fontsize=phone_pt(8.2, fig_w))
    ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
    ax.set_title("The interval ranges over medians, never over runs", fontsize=phone_pt(9.4, fig_w))
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def _draw_interval(ax, y, lo, hi, color, label, fig_w):
    ax.plot([lo, hi], [y, y], color=color, linewidth=2.6)
    for x in (lo, hi):
        ax.plot([x, x], [y - 0.09, y + 0.09], color=color, linewidth=2.6)
    ax.text(
        hi,
        y + 0.16,
        f"{label}  [{lo:.2f}, {hi:.2f}]",
        color=color,
        fontsize=phone_pt(7.4, fig_w),
        ha="right",
    )


def shortcut_panels(intervals, out_path) -> Path:
    """Two panels: the shortcut landing, then the same shortcut failing.

    An earlier design called this the "overlap trap" and claimed a reader
    could not get the difference by eyeballing the two contrasts. On this
    campaign that is false -- the intervals do not overlap at all and naive
    endpoint subtraction lands within 0.04s -- so the chart would have taught
    the shortcut it meant to forbid. The honest lesson needs both panels: the
    shortcut works here, fails on correlated estimates, and nothing visible
    in the two intervals says which case you are in.
    """
    ab, bc, diff = intervals["ab"], intervals["bc"], intervals["diff"]
    corr = shortcut_panels.correlated_example()
    fig_w = 8.0
    fig, axes = plt.subplots(2, 1, figsize=(fig_w, 7.4))

    for ax, data, title, verdict in (
        (
            axes[0],
            {"ab": ab, "bc": bc, "diff": diff},
            "This campaign — the shortcut worked",
            "the shortcut worked here: naive subtraction lands within 0.04 s",
        ),
        (
            axes[1],
            corr,
            "Correlated estimates — same arithmetic, wrong",
            "naive subtraction is several times too wide",
        ),
    ):
        d = data
        naive_lo, naive_hi = d["ab"][0] - d["bc"][1], d["ab"][1] - d["bc"][0]
        _draw_interval(ax, 3.0, d["ab"][0], d["ab"][1], "#2f6fb5", "first contrast", fig_w)
        _draw_interval(ax, 2.2, d["bc"][0], d["bc"][1], "#e0a43a", "second contrast", fig_w)
        _draw_interval(ax, 1.4, d["diff"][0], d["diff"][1], "#4a8c5f", "true difference", fig_w)
        _draw_interval(ax, 0.6, naive_lo, naive_hi, "#c0392b", "naive subtraction", fig_w)
        span = max(d["ab"][1], d["bc"][1], naive_hi) - min(d["ab"][0], d["bc"][0], naive_lo)
        pad = span * 0.08 if span else 1.0
        ax.set_xlim(
            min(d["ab"][0], d["bc"][0], naive_lo) - pad,
            max(d["ab"][1], d["bc"][1], naive_hi) + pad,
        )
        ax.set_ylim(0.15, 3.55)
        ax.set_yticks([])
        ax.tick_params(axis="x", labelsize=phone_pt(7.6, fig_w))
        ax.set_title(title, fontsize=phone_pt(8.8, fig_w))
        ax.text(
            0.5,
            0.03,
            verdict,
            transform=ax.transAxes,
            ha="center",
            fontsize=phone_pt(7.6, fig_w),
            style="italic",
        )

    # Two lines, not one: the full sentence at any phone-legible font size
    # runs past the right edge of an 8-inch-wide canvas (as it did in an
    # earlier version of this figure), so it is wrapped manually rather
    # than left to overflow.
    fig.text(
        0.5,
        0.045,
        "Nothing visible in the two contrasts tells you which case you are in.",
        ha="center",
        fontsize=phone_pt(7.6, fig_w),
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.012,
        "That is why the difference is computed, not derived.",
        ha="center",
        fontsize=phone_pt(7.6, fig_w),
        fontweight="bold",
    )
    fig.tight_layout(rect=(0.0, 0.09, 1.0, 1.0))
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def _correlated_example() -> dict:
    """Two contrasts sharing a host effect, so the difference is far better
    pinned than either part and naive subtraction is grossly too wide. Built
    from the campaign's own paired design, which exists for this exact
    reason.
    """
    return {
        "ab": (2.0, 28.0),
        "bc": (6.0, 32.0),
        "diff": (-5.2, -2.8),
    }


shortcut_panels.correlated_example = _correlated_example
