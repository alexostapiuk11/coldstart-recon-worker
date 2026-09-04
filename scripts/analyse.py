"""Derive every published number from the stored JSONL.

.venv/bin/python scripts/analyse.py --store data/campaign.jsonl
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl --summary-only
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.economics import (
    Assumptions,
    break_even_events_per_day,
    cache_is_worth_renting,
    compile_cache_break_even_events_per_day,
    compile_cache_term,
    foregone_tokens,
    gpu_cost_per_scale_up,
    supported_concurrency,
)
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


# The published conversion assumptions (spec 7: "published in each artifact so
# a reader can substitute their own").
#
# Only `assumed_context_length` is measured -- it is the pinned
# `--max-model-len` the campaign actually ran under. The three money rates are
# ILLUSTRATIVE and deliberately round, because this campaign measured seconds
# and tokens, not prices: it never recorded an invoice, and a rate quoted from
# memory would be the one number in the artifact that a reader could not
# re-derive from committed data. A round $1.00/GPU-hour also makes every dollar
# figure below trivially rescalable -- halve the rate, halve the cost.
#
# What is NOT an assumption, and is reported next to every dollar figure, is
# the GPU-seconds each event costs. That is measured, and it is what a reader
# multiplies by their own contract rate.
PUBLISHED_ASSUMPTIONS = Assumptions(
    gpu_hourly_rate=1.00,
    scale_ups_per_day=24.0,
    steady_state_tokens_per_sec=800.0,
    volume_monthly_cost=3.50,
    assumed_context_length=8192,
)
ASSUMPTION_PROVENANCE = {
    "gpu_hourly_rate": "illustrative round number, substitute your own",
    "scale_ups_per_day": "illustrative: one scale-up per hour",
    "steady_state_tokens_per_sec": "illustrative batched decode rate; not measured here",
    "volume_monthly_cost": "illustrative rental for the 50 GB network volume",
    "assumed_context_length": "MEASURED: the pinned --max-model-len",
}
VERSION_CHANGES_PER_MONTH = 2.0


def _economics(out: dict) -> None:
    """Convert the measured seconds into the decision units spec 7 asks for.

    Reads only from `out`, never from the rows -- so every published dollar
    figure is a pure function of numbers already printed above it in the same
    document, and a reader can check the arithmetic by hand without rerunning
    anything. A withheld input (below the sample floor) propagates as a
    withheld output rather than silently pricing a missing median as zero.
    """
    a = PUBLISHED_ASSUMPTIONS
    econ: dict = {
        "assumptions": {
            **{k: getattr(a, k) for k in ASSUMPTION_PROVENANCE},
            "version_changes_per_month": VERSION_CHANGES_PER_MONTH,
        },
        "assumption_provenance": ASSUMPTION_PROVENANCE,
    }

    t_fast = out.get("t_fast_median", {})
    econ["per_scale_up"] = {}
    for arm in ("A", "B", "C"):
        entry = t_fast.get(arm, {})
        if entry.get("withheld"):
            econ["per_scale_up"][arm] = _withheld(entry["reason"])
            continue
        seconds = entry["point"]
        econ["per_scale_up"][arm] = _published(
            {
                "gpu_seconds": seconds,
                "gpu_cost_usd": gpu_cost_per_scale_up(seconds, a),
                "foregone_tokens": foregone_tokens(seconds, a),
            }
        )

    econ["supported_concurrency_at_8192"] = {}
    for arm in ("A", "B", "C"):
        entry = out.get("kv_capacity_median", {}).get(arm, {})
        if entry.get("withheld"):
            econ["supported_concurrency_at_8192"][arm] = _withheld(entry["reason"])
        else:
            econ["supported_concurrency_at_8192"][arm] = _published(
                {"concurrent_requests": supported_concurrency(int(entry["point"]), a)}
            )

    # Weight cache: a continuously rented volume. Compile cache: free to store,
    # but re-warmed from scratch every time the engine version changes -- a
    # lumpy per-version charge, not a monthly rental. Same unit, different
    # shape; that difference is the operational point of the whole comparison.
    a_e, b_e, c_e = (econ["per_scale_up"][k] for k in ("A", "B", "C"))
    if any(e.get("withheld") for e in (a_e, b_e, c_e)):
        econ["break_even"] = _withheld("a per-arm median was withheld")
    else:
        weight_saved = a_e["gpu_seconds"] - b_e["gpu_seconds"]
        compile_saved = b_e["gpu_seconds"] - c_e["gpu_seconds"]
        # One re-warm is one full cold-compile start, which is exactly what
        # arm B pays -- the priming procedure in the pre-registration.
        rewarm_cost = gpu_cost_per_scale_up(b_e["gpu_seconds"], a)
        weight_be = break_even_events_per_day(weight_saved, a)
        compile_be = compile_cache_break_even_events_per_day(
            compile_saved, rewarm_cost, VERSION_CHANGES_PER_MONTH, a
        )
        econ["break_even"] = _published(
            {
                "weight_cache_seconds_saved": weight_saved,
                "weight_cache_events_per_day": weight_be,
                "weight_cache_worth_renting": cache_is_worth_renting(a, weight_be),
                "compile_cache_seconds_saved": compile_saved,
                "compile_cache_rewarm_cost_usd": rewarm_cost,
                "compile_cache_events_per_day": compile_be,
                "compile_cache_worth_renting": cache_is_worth_renting(a, compile_be),
            }
        )

    s4b = out.get("s4b_median", {})
    if not any(s4b.get(k, {}).get("withheld", True) for k in ("B", "C")):
        econ["compile_cache_term_seconds"] = compile_cache_term(
            s4b["B"]["point"], s4b["C"]["point"]
        )

    out["economics"] = econ


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
    triples") to how many publishable, non-None units back that computation
    -- a "unit" is a row for a per-arm sample, a triple for the paired case,
    which is why the message below states a bare count rather than a
    hardcoded noun that would only fit one of the two. Zero is just the n=0
    case of the same floor a thin-but-nonzero sample already fails -- not a
    separate condition, and not something `compute` (a raising
    bootstrap/percentile call) is ever asked to handle itself. Every label
    short of `floor` is named in the reason, not just the first, so an
    operator sees every empty or thin arm in one message instead of
    debugging them one crash at a time.
    """
    short = {label: n for label, n in counts.items() if n < floor}
    if short:
        parts = [f"{label} has {n}" for label, n in short.items()]
        return _withheld(f"{', '.join(parts)} (needs >= {floor})")
    return _published(compute())


def _full_analysis(rows: list[dict], total_part: PartitionResult, out: dict) -> None:
    """Every metric beyond the always-safe summary block: distributions,
    KV-capacity medians, the six contrasts, and the paired analysis.

    Writes directly into the caller's `out` dict, key by key, instead of
    building and returning a separate one -- so if a later statement in here
    raises, every field already computed is still sitting in `out` for
    `main()` to print. Isolated from `main()` only so the risky section can
    be wrapped in one try/except there; an exception raised in here must
    never cost the caller `failure_rate_by_arm`/`discard_table` (already in
    `out` before this is called), nor any of this function's own
    already-computed fields -- both are exactly the diagnostics an operator
    reaches for when a campaign looks broken.
    """
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

    # T_fast, not T_total, is what the economics price: a replica is rented
    # from the moment it starts until it is serving at steady-state latency,
    # and the gap between "ready" and "fast" is rented time too. On this
    # campaign the two are within 0.1s because the warmup is paid before the
    # health check passes (see the warmup figure) -- but that is a measured
    # result of this configuration, not an identity, so the economics read
    # T_fast and would diverge correctly on an engine that served slow first
    # requests.
    out["t_fast_median"] = {}
    for arm in ("A", "B", "C"):
        vals = [
            r["t_fast_seconds"] for r in pub if r["arm"] == arm and r["t_fast_seconds"] is not None
        ]
        out["t_fast_median"] = out["t_fast_median"]
        out["t_fast_median"][arm] = _floor_or_withhold(
            lambda vals=vals: {"point": median(vals)},
            {f"arm {arm}": len(vals)},
            MIN_BOOTSTRAP_SAMPLES,
        )

    # S4b in isolation, so the compile-cache term can be read directly rather
    # than inferred from the B->C contrast (which is measured on t_compile and
    # would agree, but agreement is worth showing rather than asserting).
    out["s4b_median"] = {}
    for arm in ("A", "B", "C"):
        vals = [r["t_s4b"] for r in pub if r["arm"] == arm and r["t_s4b"] is not None]
        out["s4b_median"][arm] = _floor_or_withhold(
            lambda vals=vals: {"point": median(vals)},
            {f"arm {arm}": len(vals)},
            MIN_BOOTSTRAP_SAMPLES,
        )

    # t_compile has its own nullity condition (a run whose parsed engine log
    # has no S4b entry -- the pinned engine normally DOES delineate S4b, so
    # this is not the common case, but it is independent of T_total
    # consistency when it happens) -- REQUIRED_FOR_T_COMPILE gates it exactly
    # the way REQUIRED_FOR_T_WEIGHTS gates t_weights below, so a row without
    # an S4b entry's None can never reach a bootstrap unfiltered.
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

    # The paired contrast pools t_weights per triple (bootstrap_paired_median_diff
    # below, value="t_weights"), so a triple only qualifies if every arm inside
    # it actually has a valid t_weights -- not merely a consistent, complete-
    # looking group of three rows. within_host_triples() itself checks only
    # ok/arm/host_id/triple_index structure (stats.py's `_row_value` docstring
    # warns every caller of exactly this gap), so it is built from weights_pub
    # -- REQUIRED_FOR_T_WEIGHTS's publishable set, the same one `by_w` above
    # already uses -- rather than the raw `rows`. A triple where one arm's
    # t_weights is None (an undelineated S2/S3) or whose row failed
    # consistency then simply has that row absent from weights_pub, so the
    # group no longer covers all three arms and within_host_triples drops it,
    # the same way a failed run's absence already does.
    triples = within_host_triples(weights_pub)
    out["within_host_triples"] = len(triples)
    out["paired_A_to_B_t_weights"] = _floor_or_withhold(
        lambda: bootstrap_paired_median_diff(
            triples, "A", "B", "t_weights", iterations=ITERATIONS, seed=4
        ),
        {"within-host triples": len(triples)},
        MIN_BOOTSTRAP_SAMPLES,
    )

    _economics(out)


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
        _full_analysis(rows, total_part, out)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment below
        # A crash here must not cost the caller the summary block above, nor
        # any field _full_analysis already wrote into `out` before raising --
        # both are exactly the diagnostics an operator needs at the moment
        # something has gone wrong enough to raise. Print what was safely
        # computed plus a short error summary (stdout stays one clean JSON
        # document for tooling), write the real traceback to stderr for a
        # human, then exit non-zero so a script or CI check still sees
        # failure.
        print(traceback.format_exc(), file=sys.stderr)
        out["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(out, indent=2, default=str))
        sys.exit(1)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
