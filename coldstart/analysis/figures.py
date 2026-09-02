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

B4: a row from a failed run, an inconsistent run, or a merged run does not
raise a clean error on its own — a bare `r["t_platform"]` inside a
comprehension either `KeyError`s (failed rows don't have the key at all) or
feeds `None` to `median()`/`ecdf()`, which fails with a context-free
`TypeError` from inside `math.isfinite`. `_required_field` below replaces
every such dereference this module makes with a check that names the row
(by `arm`/`host_id`, the identity these hand-built and derive()-shaped rows
both reliably carry) and the field, and raises
`coldstart.analysis.pipeline.NotPublishableError`. This does not make these
functions require `"ok"`/`"consistent"` on every row -- that would break the
"pure consumer of whatever fields a row happens to carry" policy above and
this module's own tests, which hand-build rows without either key. A caller
that has already gated rows through `pipeline.partition()` for the fields a
given figure needs (see the `REQUIRED_FOR_*` constants there) can hand the
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

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from coldstart.analysis.metrics import FAST_TOLERANCE, steady_state_latency, time_to_fast_index
from coldstart.analysis.pipeline import NotPublishableError
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


def _row_identity(row: dict) -> str:
    return f"arm={row.get('arm')!r} host_id={row.get('host_id')!r}"


def _required_field(row: dict, key: str):
    """B4: raise `NotPublishableError`, naming the row and `key`, in place of
    the bare `KeyError` (key absent -- a failed run's short row) or
    `TypeError` (key present but `None` -- an inconsistent or merged run)
    that dereferencing `row[key]` directly would produce deep inside
    `median()`/`ecdf()`. See the module docstring."""
    if key not in row:
        raise NotPublishableError(
            f"row ({_row_identity(row)}) has no {key!r} field -- route rows "
            "through coldstart.analysis.pipeline.partition() with that field "
            "in `required` before calling this figure"
        )
    val = row[key]
    if val is None:
        raise NotPublishableError(
            f"row ({_row_identity(row)}) has {key!r} = None -- not publishable "
            "for this figure; route rows through "
            "coldstart.analysis.pipeline.partition() with that field in "
            "`required` first"
        )
    return val


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
        platform = median([_required_field(r, "t_platform") for r in rs])
        process = median([_required_field(r, "t_process") for r in rs])

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
                    "S4 + S5 (merged — S4 bracket marks absent)",
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

    lengths = {len(_required_field(r, "warmup")) for r in all_rows}
    if len(lengths) != 1:
        raise ValueError(
            f"warmup lists have mismatched lengths across rows: {sorted(lengths)}; "
            "every row must report the same number of warmup requests"
        )
    (n_req,) = lengths
    if n_req == 0:
        raise ValueError("warmup lists are empty")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm_idx, arm in enumerate(ARMS):
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
            fast_y = med[fast_req - 1]
            ax.scatter(
                [fast_req],
                [fast_y],
                marker="*",
                s=220,
                color=line.get_color(),
                edgecolor="black",
                linewidths=0.6,
                zorder=5,
            )
            # Three arms can land T_fast at the same request index with
            # close steady-state values (e.g. the cached arms B and C), so a
            # small alternating up/down offset is not enough separation on
            # its own -- these three (dx, dy) offsets, one per arm position,
            # spread the labels both horizontally and vertically so they
            # cannot stack on each other regardless of how close the
            # underlying curves are.
            offset_x, offset_y = ((14, 20), (-92, 2), (14, -42))[arm_idx % 3]
            ax.annotate(
                f"T_fast (req {fast_req})",
                xy=(fast_req, fast_y),
                xytext=(offset_x, offset_y),
                textcoords="offset points",
                fontsize=9,
                fontweight="bold",
                color=line.get_color(),
                arrowprops={"arrowstyle": "-", "color": line.get_color(), "lw": 0.8, "alpha": 0.8},
            )

    ax.set_xlabel("request index")
    ax.set_ylabel("end-to-end latency (s)")
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
    ax.set_title("Ready is already fast — the warmup was paid before ready", pad=24)
    # Outside the axes, as the waterfall's is. On real data the curve is
    # nearly flat and sits high, so an in-axes legend covered requests 6-10
    # entirely -- the data was present and simply hidden behind the box.
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        fontsize=8,
        borderaxespad=0.0,
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def ecdf_plot(rows, out_path) -> Path:
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        xs, ys = ecdf([_required_field(r, "t_total") for r in rs])
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
    meds = [
        median([_required_field(r, "t_total") for r in rows if r["host_id"] == h]) for h in hosts
    ]
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
