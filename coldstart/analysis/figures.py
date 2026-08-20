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


def waterfall(rows, out_path) -> Path:
    """Stacked median stage durations per arm, residual visually distinct."""
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    labels, ys = [], []
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
        if measured:
            weights = median(measured)
            sub = {
                k: median([r["s4_subphases"].get(k, 0.0) for r in rs]) for k in ("S4c", "S4e")
            }
            unattributed = max(0.0, process - weights - sum(sub.values()))
            segments = [
                (platform, "T_platform (not attributable)", RESIDUAL_COLOR),
                (weights, "T_weights (S2+S3)", "#2f6fd0"),
                (sub["S4c"], "S4c memory profiling", "#4a8a4a"),
                (sub["S4e"], "S4e graph capture", "#c88a2e"),
                (unattributed, "unattributed within S4", "#d9c8a9"),
            ]
        else:
            segments = [
                (platform, "T_platform (not attributable)", RESIDUAL_COLOR),
                (process, "S2 to ready (phases merged by engine)", "#7f8fa6"),
            ]

        left = 0.0
        for value, label, color in segments:
            ax.barh(i, value, left=left, color=color, label=label if i == 0 else None)
            left += value

    ax.set_yticks(ys, labels)
    ax.set_xlabel("seconds (median)")
    ax.set_xlim(left=0)
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title("Cold start decomposition")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
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
        ax.plot(range(1, n_req + 1), med, marker="o", label=f"{ARM_LABEL[arm]} (n={len(rs)})")

    # Steady state is drawn from every row across every arm, not just
    # `rows[0]` (the plan's original computation): a band anchored to one
    # arbitrary row is one outlier row away from being a misleading anchor
    # for curves compared across all three arms.
    steady = median([r["warmup"][k]["end_to_end"] for r in all_rows for k in (-3, -2, -1)])
    ax.axhspan(steady * 0.9, steady * 1.1, color="#eeeeee", label="steady-state band (±10%)")
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
