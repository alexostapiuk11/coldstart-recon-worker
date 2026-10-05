"""Amendment §4's estimands, from stored records to intervals.

Every record passes through `harness.publish.partition` first, so a failed
instance, a cold-compiled instance and a phase whose counts disagree with the
failure rule are each counted and excluded rather than silently averaged in.

Paired quantities -- the heterogeneity cost -- are one difference per
instance, bootstrapped with `bootstrap_median_ci`. That is the same
computation as the harness's paired bootstrap, without its artifact-1 field
names (amendment §2). Quantities across instances are unpaired.
"""

from harness.publish import PartitionResult, partition
from harness.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    bootstrap_function_of_medians,
    bootstrap_median_ci,
    bootstrap_median_diff,
    median,
)
from multilora.conditions import (
    CONCENTRATED,
    CONTROL,
    DIAGNOSTIC,
    GATE,
    REAL,
    SPREAD,
    SWEEP,
    SYNTHETIC,
    condition_name,
    parse_condition,
)
from multilora.phase import PhaseCountMismatch, check_counts, phase_summaries, regime_summary
from multilora.prereg import Preregistration

METRICS = ("throughput_tps", "ttft_p50", "ttft_p95")
REQUIRED = ("compile_warm", "counts_ok", "kv_capacity_tokens")


def instance_rows(records, prereg: Preregistration) -> PartitionResult:
    rows = []
    for rec in records:
        cond = parse_condition(rec.condition, prereg)
        row = {
            "ok": rec.outcome == "ok",
            "run_index": rec.run_index,
            "condition": rec.condition,
            "kind": cond.kind,
            "n_slots": cond.n_slots,
            "host_id": rec.host.get("host_id"),
            "failure_class": rec.failure_class,
        }
        if rec.outcome == "ok":
            row["compile_state"] = rec.engine.get("compile_state")
            row["compile_warm"] = True if row["compile_state"] == "warm" else None
            row["kv_capacity_tokens"] = rec.engine.get("kv_capacity_tokens")
            try:
                for phase in rec.phases:
                    check_counts(phase)
                row["counts_ok"] = True
            except PhaseCountMismatch as e:
                row["counts_ok"] = None
                row["count_mismatch"] = str(e)
            if row["counts_ok"]:
                regimes = (REAL, SYNTHETIC) if cond.kind == GATE else (CONCENTRATED, SPREAD)
                for regime in regimes:
                    row[regime] = regime_summary(rec, regime)
                if cond.kind == GATE:
                    row["real_phases"] = phase_summaries(rec, REAL)
        rows.append(row)
    return partition(rows, required=REQUIRED)


def rows_for(rows: list[dict], condition: str) -> list[dict]:
    return [r for r in rows if r["condition"] == condition]


def _values(rows, regime: str, metric: str) -> list[float]:
    return [r[regime][metric] for r in rows]


def heterogeneity_cost(rows, metric: str, iterations=10000, seed=0) -> dict:
    """Spread minus concentrated, paired within each instance."""
    deltas = [r[SPREAD][metric] - r[CONCENTRATED][metric] for r in rows]
    return {**bootstrap_median_ci(deltas, iterations=iterations, seed=seed), "n": len(deltas)}


def registered_slot_cost(rows_n, rows_1, metric: str, iterations=10000, seed=0) -> dict:
    """Concentrated at N minus concentrated at one slot, unpaired."""
    res = bootstrap_median_diff(
        _values(rows_n, CONCENTRATED, metric),
        _values(rows_1, CONCENTRATED, metric),
        iterations=iterations,
        seed=seed,
    )
    return {**res, "n": [len(rows_n), len(rows_1)]}


def slot_overhead(default_n, default_1, special_n, special_1, metric, iterations=10000, seed=0) -> dict:
    """Amendment §3b's difference in differences, concentrated regime, unpaired:
    [default(N) - default(1)] - [specialized(N) - specialized(1)]."""
    groups = [
        _values(g, CONCENTRATED, metric) for g in (default_n, default_1, special_n, special_1)
    ]
    res = bootstrap_function_of_medians(
        groups, lambda m: (m[0] - m[1]) - (m[2] - m[3]), iterations=iterations, seed=seed
    )
    return {**res, "n": [len(g) for g in groups]}


def gauge_overhead(sweep_rows, control_rows, metric, iterations=10000, seed=0) -> dict:
    """Heterogeneity cost with default stats minus with `--disable-log-stats`,
    at the control point, unpaired (amendment §3a)."""
    def deltas(rows):
        return [r[SPREAD][metric] - r[CONCENTRATED][metric] for r in rows]

    res = bootstrap_median_diff(
        deltas(sweep_rows), deltas(control_rows), iterations=iterations, seed=seed
    )
    return {**res, "n": [len(sweep_rows), len(control_rows)]}


def memory_ceiling(rows, prereg: Preregistration) -> dict:
    """KV tokens at a sweep point, as maximum concurrency at the inherited
    request shape and at the production context length (amendment §3c)."""
    per_instance = [r["kv_capacity_tokens"] for r in rows]
    kv = median(per_instance)
    return {
        "kv_tokens": kv,
        "kv_by_instance": per_instance,
        "max_concurrency_request_shape": int(kv // prereg.request_tokens),
        "max_concurrency_context": int(kv // prereg.context_length_tokens),
        "n": len(rows),
    }


def sweep_estimands(publishable, prereg: Preregistration, iterations=10000, seed=0) -> dict:
    """Every per-point estimand the post reports. JSON-shaped: points are a
    list carrying their own slot count, so a round trip through
    `data/a5/analysis.json` cannot turn keys into strings."""
    at_one = rows_for(publishable, condition_name(SWEEP, 1))
    points = []
    for n in prereg.sweep:
        rows = rows_for(publishable, condition_name(SWEEP, n))
        point = {
            "n_slots": n,
            "n": len(rows),
            "memory": memory_ceiling(rows, prereg),
            "median": {
                regime: {m: median(_values(rows, regime, m)) for m in METRICS}
                for regime in (CONCENTRATED, SPREAD)
            },
            "interval": {
                regime: {
                    m: bootstrap_median_ci(_values(rows, regime, m), iterations=iterations, seed=seed)
                    for m in METRICS
                }
                for regime in (CONCENTRATED, SPREAD)
            },
        }
        if n == 1:
            point["heterogeneity"] = {"by_construction": 0.0}
            point["registered_slot"] = {"by_construction": 0.0}
        else:
            point["heterogeneity"] = {
                m: heterogeneity_cost(rows, m, iterations, seed) for m in METRICS
            }
            point["registered_slot"] = {
                m: registered_slot_cost(rows, at_one, m, iterations, seed) for m in METRICS
            }
        points.append(point)
    out = {"points": points}
    if prereg.include_diagnostic:
        d1 = rows_for(publishable, condition_name(DIAGNOSTIC, 1))
        out["slot_overhead"] = [
            {
                "n_slots": n,
                **{
                    m: slot_overhead(
                        rows_for(publishable, condition_name(SWEEP, n)), at_one,
                        rows_for(publishable, condition_name(DIAGNOSTIC, n)), d1,
                        m, iterations, seed,
                    )
                    for m in METRICS
                },
            }
            for n in prereg.diagnostic_points
            if n != 1
        ]
    if prereg.include_control:
        n = prereg.control_point
        out["gauge_overhead"] = {
            "n_slots": n,
            **{
                m: gauge_overhead(
                    rows_for(publishable, condition_name(SWEEP, n)),
                    rows_for(publishable, condition_name(CONTROL, n)),
                    m, iterations, seed,
                )
                for m in METRICS
            },
        }
    return out


def point_at(sweep: dict, n_slots: int) -> dict:
    return next(p for p in sweep["points"] if p["n_slots"] == n_slots)


def publishable_counts(records, prereg: Preregistration) -> dict[str, dict]:
    """Per condition: stored, failed, discarded and publishable instances, and
    whether publishable meets the bootstrap floor. Checked before analysis."""
    parts = instance_rows(records, prereg)
    out: dict[str, dict] = {}
    for bucket, rows in (("publishable", parts.publishable), ("discarded", parts.discarded),
                         ("failed", parts.failed)):
        for r in rows:
            entry = out.setdefault(r["condition"], {"publishable": 0, "discarded": 0, "failed": 0})
            entry[bucket] += 1
    for entry in out.values():
        entry["meets_floor"] = entry["publishable"] >= MIN_BOOTSTRAP_SAMPLES
    return out
