"""The four public-post figures: waterfall decomposition, warmup curve, ECDF,
and per-host medians.

These charts are the artifact for most readers — more people will look at
the waterfall than will read the method section — so every aggregate drawn
here goes through ``coldstart.analysis.stats.median``, the same function
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
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from coldstart.analysis.stats import ecdf, median

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


def _validate_rows(rows) -> list[dict]:
    """Fail loudly on the one input domain every figure shares: nothing to
    plot. A copy is returned so callers get a stable list even if `rows`
    was a generator (none of the figures consume `rows` more than once, but
    this keeps that assumption from becoming load-bearing by accident)."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")
    return rows


def _by_arm(rows) -> dict[str, list[dict]]:
    """Split rows by arm, requiring all of ARMS to be represented. Silently
    skipping a missing arm (the plan's `if not rs: continue`) would drop
    that arm's whole series from the chart with no indication anything was
    wrong — a figure that quietly compares two arms instead of three is a
    misleading chart, not a smaller one."""
    rows = _validate_rows(rows)
    by = {a: [r for r in rows if r["arm"] == a] for a in ARMS}
    missing = [a for a in ARMS if not by[a]]
    if missing:
        raise ValueError(
            f"no rows for arm(s) {missing}; refusing to silently drop "
            f"{'an arm' if len(missing) == 1 else 'arms'} from the chart"
        )
    return by


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
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(11, 5.5))
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
        platform = median([r["t_platform"] for r in rs])
        process = median([r["t_process"] for r in rs])

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

            _draw(i, platform, "T_platform (not attributable)", RESIDUAL_COLOR)
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
                unattributed_label = "unattributed within S4"
                if merged_subs:
                    unattributed_label += f" (includes merged: {', '.join(merged_subs)})"
                _draw(i, unattributed, unattributed_label, "#d9c8a9")
                s5 = _median_present(rs, "t_s5")
                if s5 is not None:
                    _draw(i, s5, "S5 ready (health poll)", "#5aa9c2")
            else:
                # No mark delineates S4 today (Task 11, the probe that
                # emits S4_start/S4_end, is not built yet). S5_ready -
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
                    "S4 + S5 (merged — S4_start/S4_end not yet measured)",
                    "#b8b0c8",
                    hatch="//",
                )

            if s6 is not None:
                _draw(i, s6, "S6 cold TTFT", "#4f6d7a")
        else:
            _draw(i, platform, "T_platform (not attributable)", RESIDUAL_COLOR)
            _draw(i, process, "S2 to ready (phases merged by engine)", "#7f8fa6")

    ax.set_yticks(ys, labels, fontsize=11)
    ax.set_xlabel("seconds (median)", fontsize=12)
    ax.tick_params(axis="x", labelsize=11)
    ax.set_xlim(left=0)
    # Placed outside the axes (to the right) rather than in a corner: with
    # every stage now individually labelled there can be a dozen legend
    # entries, more than any in-plot corner has room for without covering a
    # bar. `bbox_inches="tight"` on save (below) expands the saved canvas to
    # include it rather than clipping it off. Font sizes here are larger
    # than the other three figures' legends (fontsize=8) specifically
    # because this chart is wider in absolute pixels now that it carries up
    # to a dozen entries -- what determines legibility once a reader
    # displays the PNG at a fixed width (e.g. a phone screen) is
    # `font_pt / figure_width_in`, not the font's absolute point size, so a
    # wider chart needs correspondingly larger fonts to hold the same
    # rendered size after downscaling. `labelspacing`/`handlelength` are
    # trimmed so the wider font doesn't blow the legend column out further.
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        fontsize=10,
        borderaxespad=0.0,
        labelspacing=0.4,
        handlelength=1.5,
        handletextpad=0.5,
    )
    ax.set_title("Cold start decomposition", fontsize=15)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return Path(out_path)


def warmup_curve(rows, out_path) -> Path:
    by = _by_arm(rows)
    all_rows = [r for rs in by.values() for r in rs]

    lengths = {len(r["warmup"]) for r in all_rows}
    if len(lengths) != 1:
        raise ValueError(
            f"warmup lists have mismatched lengths across rows: {sorted(lengths)}; "
            "every row must report the same number of warmup requests"
        )
    (n_req,) = lengths
    if n_req == 0:
        raise ValueError("warmup lists are empty")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        med = [median([r["warmup"][i]["end_to_end"] for r in rs]) for i in range(n_req)]
        (line,) = ax.plot(
            range(1, n_req + 1), med, marker="o", label=f"{ARM_LABEL[arm]} (n={len(rs)})"
        )

        # Steady state is per-arm, not pooled across all three arms. Each
        # arm converges to its own plateau -- a band computed by pooling
        # every arm's rows together would sit near the middle arm's
        # plateau and be flatly wrong for the other two (e.g. the slowest
        # arm would look like it never reaches "steady state" and the
        # fastest arm would look like it beats steady state from request 2
        # on). Drawn from all of *that arm's* rows, not just its first row
        # (same one-outlier-row concern as before, now scoped per arm), in
        # that arm's own line color so the band is unambiguously "this
        # curve's" rather than a third, disconnected element.
        steady = median([r["warmup"][k]["end_to_end"] for r in rs for k in (-3, -2, -1)])
        ax.axhspan(
            steady * 0.9,
            steady * 1.1,
            color=line.get_color(),
            alpha=0.15,
            label=f"{ARM_LABEL[arm]} steady-state band (±10%)",
        )

    ax.set_xlabel("request index")
    ax.set_ylabel("end-to-end latency (s)")
    ax.set_ylim(bottom=0)
    ax.set_title("Ready is not fast")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def ecdf_plot(rows, out_path) -> Path:
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        xs, ys = ecdf([r["t_total"] for r in rs])
        ax.step(xs, ys, where="post", label=f"{ARM_LABEL[arm]} (n={len(rs)})")
    ax.set_xlabel("T_total (s)")
    ax.set_ylabel("fraction of runs ≤ x")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1)
    ax.set_title("Distribution, not a mean")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def per_host_medians(rows, out_path) -> Path:
    rows = _validate_rows(rows)
    hosts = sorted({r["host_id"] for r in rows})
    fig, ax = plt.subplots(figsize=(8, 4.5))
    meds = [median([r["t_total"] for r in rows if r["host_id"] == h]) for h in hosts]
    counts = [sum(1 for r in rows if r["host_id"] == h) for h in hosts]
    ax.bar(range(len(hosts)), meds)
    ax.set_xticks(range(len(hosts)), [f"{h}\n(n={c})" for h, c in zip(hosts, counts, strict=True)])
    ax.set_ylabel("median T_total (s)")
    ax.set_ylim(bottom=0)
    ax.set_title("Host heterogeneity")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)
