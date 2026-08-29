"""Derive every published number from the stored JSONL.

    .venv/bin/python scripts/analyse.py --store data/campaign.jsonl
    .venv/bin/python scripts/analyse.py --store data/campaign.jsonl --summary-only
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_COMPILE,
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
    PartitionResult,
    discard_table,
    failure_rate_by_arm,
    partition,
)
from coldstart.analysis.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    MIN_SAMPLES,
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_median_diff,
    median,
    percentiles,
    within_host_triples,
)
from coldstart.store import JsonlStore

ITERATIONS = 10_000

# A distribution asks percentiles() for p50/p90/p95 (its default `want`), so
# it needs whichever of those floors is hardest to clear -- p95's -- not just
# p50's. Importing MIN_SAMPLES rather than hardcoding 80 means this can never
# silently drift from the floor percentiles() itself enforces.
DIST_FLOOR = max(MIN_SAMPLES[name] for name in ("p50", "p90", "p95"))

# A per-arm KV-capacity figure is a median, so it earns the same "measurement,
# not observation" floor percentiles' own p50 uses (see stats.py's module
# docstring) -- median() itself deliberately skips this floor because it also
# serves as a plotting aggregate (per its docstring), but a headline published
# figure is not a plotting aggregate.
KV_CAPACITY_FLOOR = MIN_SAMPLES["p50"]


def _withheld(reason: str) -> dict:
    """Uniform envelope for a metric that could not be published. Every
    consumer (a human reading the JSON, or tests/test_reproducibility.py)
    checks the same `withheld` boolean instead of an isinstance check against
    a bare string -- see `_published` for the success half of the envelope."""
    return {"withheld": True, "reason": reason}


def _published(fields: dict) -> dict:
    """Uniform envelope for a metric that was computed. `fields` is whatever
    that metric's own real output looks like (point/lo/hi for a bootstrap
    interval, p50/p90/p95 for a distribution, point for a plain median) --
    the `withheld: False` key is the one thing every published metric in this
    file shares, so a consumer never needs to know which shape it is looking
    at before checking whether it was withheld at all."""
    return {"withheld": False, **fields}


def _floor_or_withhold(compute, counts: dict[str, int], floor: int) -> dict:
    """The one guard every per-arm distribution, every contrast, the paired
    bootstrap, and kv_capacity_median route through.

    `counts` maps a human-readable label (an arm name, or "within-host
    triples") to how many publishable, non-None samples back that
    computation. Zero is just the n=0 case of the same floor a thin-but-
    nonzero sample already fails -- not a separate condition, and not
    something `compute` (a raising bootstrap/percentile call) is ever asked
    to handle itself. Every label short of `floor` is named in the reason,
    not just the first, so an operator sees every empty or thin arm in one
    message instead of debugging them one crash at a time.
    """
    short = {label: n for label, n in counts.items() if n < floor}
    if short:
        parts = [f"{label} has {n} publishable rows" for label, n in short.items()]
        return _withheld(f"{', '.join(parts)} (needs >= {floor})")
    return _published(compute())


def _full_analysis(rows: list[dict], total_part: PartitionResult) -> dict:
    """Every metric beyond the always-safe summary block: distributions,
    KV-capacity medians, the six contrasts, and the paired analysis.

    Isolated from `main()` so the risky section can be wrapped in one
    try/except there -- an exception raised in here must never cost the
    caller `failure_rate_by_arm`/`discard_table`, which is exactly the
    diagnostic an operator reaches for when a campaign looks broken.
    """
    out: dict = {}
    pub = total_part.publishable

    out["distributions"] = {}
    for arm in ("A", "B", "C"):
        arm_rows = [r["t_total"] for r in pub if r["arm"] == arm]
        out["distributions"][arm] = _floor_or_withhold(
            lambda arm_rows=arm_rows: percentiles(arm_rows),
            {f"arm {arm}": len(arm_rows)},
            DIST_FLOOR,
        )

    # H5: does a warm compile cache buy KV capacity? Routed through the shared
    # median every other aggregate uses, not a hand-rolled index. `is not
    # None` filters the "neither reported nor block-derivable" branch of
    # metrics.derive() out of the sample before it ever reaches median().
    out["kv_capacity_median"] = {}
    for arm in ("A", "B", "C"):
        arm_tokens = [
            r["kv_capacity_tokens"]
            for r in pub
            if r["arm"] == arm and r["kv_capacity_tokens"] is not None
        ]
        out["kv_capacity_median"][arm] = _floor_or_withhold(
            lambda arm_tokens=arm_tokens: {"point": median(arm_tokens)},
            {f"arm {arm}": len(arm_tokens)},
            KV_CAPACITY_FLOOR,
        )

    # t_compile has its own nullity condition (an undelineated S4b),
    # independent of T_total consistency -- REQUIRED_FOR_T_COMPILE gates it
    # exactly the way REQUIRED_FOR_T_WEIGHTS gates t_weights below, so a
    # merged-S4b row's None can never reach a bootstrap unfiltered.
    weights_pub = partition(rows, required=REQUIRED_FOR_T_WEIGHTS).publishable
    compile_pub = partition(rows, required=REQUIRED_FOR_T_COMPILE).publishable
    by_w = {a: [r["t_weights"] for r in weights_pub if r["arm"] == a] for a in "ABC"}
    by_c = {a: [r["t_compile"] for r in compile_pub if r["arm"] == a] for a in "ABC"}

    # Mechanism contrasts, each in the unit that explains it.
    out["contrast_A_to_B_t_weights"] = _floor_or_withhold(
        lambda: bootstrap_median_diff(by_w["A"], by_w["B"], iterations=ITERATIONS, seed=1),
        {"arm A": len(by_w["A"]), "arm B": len(by_w["B"])},
        MIN_BOOTSTRAP_SAMPLES,
    )
    out["contrast_B_to_C_t_compile"] = _floor_or_withhold(
        lambda: bootstrap_median_diff(by_c["B"], by_c["C"], iterations=ITERATIONS, seed=2),
        {"arm B": len(by_c["B"]), "arm C": len(by_c["C"])},
        MIN_BOOTSTRAP_SAMPLES,
    )

    # The ranking claim, in one unit across all three arms. It has to be a
    # single metric: bootstrap_contrast_difference computes
    # (median(a) - median(b)) - (median(b) - median(c)) and uses b twice, so
    # feeding it t_weights for A/B and t_compile for C would subtract two
    # different quantities and produce a number that means nothing. t_total is
    # the honest common unit -- "which cache buys more cold start back".
    by_t = {a: [r["t_total"] for r in pub if r["arm"] == a] for a in "ABC"}
    out["contrast_A_to_B_t_total"] = _floor_or_withhold(
        lambda: bootstrap_median_diff(by_t["A"], by_t["B"], iterations=ITERATIONS, seed=5),
        {"arm A": len(by_t["A"]), "arm B": len(by_t["B"])},
        MIN_BOOTSTRAP_SAMPLES,
    )
    out["contrast_B_to_C_t_total"] = _floor_or_withhold(
        lambda: bootstrap_median_diff(by_t["B"], by_t["C"], iterations=ITERATIONS, seed=6),
        {"arm B": len(by_t["B"]), "arm C": len(by_t["C"])},
        MIN_BOOTSTRAP_SAMPLES,
    )
    # Reported before any ranking claim is made -- spec 7.
    out["difference_of_contrasts_t_total"] = _floor_or_withhold(
        lambda: bootstrap_contrast_difference(
            by_t["A"], by_t["B"], by_t["C"], iterations=ITERATIONS, seed=3
        ),
        {"arm A": len(by_t["A"]), "arm B": len(by_t["B"]), "arm C": len(by_t["C"])},
        MIN_BOOTSTRAP_SAMPLES,
    )

    triples = within_host_triples(rows)
    out["within_host_triples"] = len(triples)
    out["paired_A_to_B_t_weights"] = _floor_or_withhold(
        lambda: bootstrap_paired_median_diff(
            triples, "A", "B", "t_weights", iterations=ITERATIONS, seed=4
        ),
        {"within-host triples": len(triples)},
        MIN_BOOTSTRAP_SAMPLES,
    )

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    out: dict = {"n_records": len(rows)}

    # Always-safe: no bootstrap, no percentile floor, nothing here can raise
    # on thin or empty data. This is exactly what an operator reaches for
    # first when a campaign looks broken, so it must survive even if
    # everything below it doesn't.
    out["failure_rate_by_arm"] = failure_rate_by_arm(rows)
    total_part = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    out["discard_table"] = discard_table(total_part.discarded)
    out["counts"] = {
        "publishable_t_total": len(total_part.publishable),
        "discarded": len(total_part.discarded),
        "failed": len(total_part.failed),
    }

    if args.summary_only:
        print(json.dumps(out, indent=2, default=str))
        return

    try:
        out.update(_full_analysis(rows, total_part))
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment below
        # A crash here must not cost the caller the summary block above --
        # that is exactly the diagnostic an operator needs at the moment
        # something has gone wrong enough to raise. Print what was safely
        # computed plus the error, then exit non-zero so a script or CI
        # check still sees failure.
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out, indent=2, default=str))
        sys.exit(1)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
