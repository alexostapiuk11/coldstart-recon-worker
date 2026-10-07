"""Everything the post reports, assembled from the two stores.

One JSON-able dict, written by `scripts/a5_analyse.py` to
`data/a5/analysis.json`. Every number in the post and every figure reads from
it, so a published number can always be traced back to the records.
"""

import copy
from dataclasses import asdict

from harness.publish import discard_table, failure_rate_by_group
from harness.stats import MIN_BOOTSTRAP_SAMPLES, median
from multilora.conditions import SPREAD, SWEEP, condition_name
from multilora.economics import tenants_per_gpu, three_way_table
from multilora.estimands import instance_rows, point_at, rows_for, sweep_estimands
from multilora.gate import verdict
from multilora.knee import knee


def gate_verdict(gate_records, prereg, iterations=10000, seed=0) -> dict:
    """The gate alone. `scripts/a5_run.py --which campaign` refuses to start
    unless this says pass (August §8: nothing else runs until the gate passes
    or its failure is characterized)."""
    rows = instance_rows(gate_records, prereg)
    if len(rows.publishable) < MIN_BOOTSTRAP_SAMPLES:
        return {
            "verdict": "insufficient",
            "n": len(rows.publishable),
            "delta": prereg.equivalence_margin,
            "reason": f"{len(rows.publishable)} publishable gate instances; the bootstrap "
            f"needs {MIN_BOOTSTRAP_SAMPLES}",
        }
    return verdict(rows.publishable, prereg.equivalence_margin, iterations, seed)


# The fields of artifact 4's `validation` that travel with its costs, copied
# as given: nothing derived, nothing renamed.
A4_VALIDATION_FIELDS = {
    "latency": ("compared", "agreeing"),
    "held_out_cells": ("passed", "total"),
    "swaps": ("predicted", "real", "agree"),
}


def a4_context(a4: dict | None) -> dict | None:
    """Artifact 4's model class and validation outcome, when its cost file
    carries them (from its d7cf0c3 on). A file without either key -- the
    older shape -- gives None; a file with only one of them is refused rather
    than half-described."""
    if a4 is None:
        return None
    present = [k for k in ("model", "validation") if k in a4]
    if not present:
        return None
    if len(present) == 1:
        raise ValueError(
            f"artifact 4's cost file has {present[0]!r} without the other of 'model' and "
            "'validation'; the two travel together"
        )
    validation = a4["validation"]
    return copy.deepcopy({
        "model": a4["model"],
        "validation": {
            "outcome": validation["outcome"],
            **{
                part: {field: validation[part][field] for field in fields}
                for part, fields in A4_VALIDATION_FIELDS.items()
            },
            "note": validation["note"],
        },
    })


def analyse(records, gate_records, prereg, a4: dict | None = None, iterations=10000, seed=0) -> dict:
    campaign = instance_rows(records, prereg)
    gate = instance_rows(gate_records, prereg)
    all_rows = campaign.publishable + campaign.discarded + campaign.failed
    gate_rows = gate.publishable + gate.discarded + gate.failed
    out = {
        "prereg": asdict(prereg),
        "failures": failure_rate_by_group(all_rows + gate_rows, "condition"),
        "discards": discard_table(campaign.discarded + gate.discarded, "condition"),
        "gate": gate_verdict(gate_records, prereg, iterations, seed),
    }
    sweep = sweep_estimands(campaign.publishable, prereg, iterations, seed)
    out["sweep"] = sweep
    throughput = {
        n: [r[SPREAD]["throughput_tps"] for r in rows_for(campaign.publishable, condition_name(SWEEP, n))]
        for n in prereg.sweep
    }
    k = knee(throughput, prereg.knee_threshold, iterations, seed)
    out["knee"] = k
    at = k["slots_below_knee"]
    spread_at = point_at(sweep, at)["median"][SPREAD]
    rate_rows = rows_for(campaign.publishable, condition_name(SWEEP, at))
    tenants = tenants_per_gpu(
        slots_below_knee=at,
        request_rate=median([r[SPREAD]["request_rate"] for r in rate_rows]),
        ttft_p95=spread_at["ttft_p95"],
        max_concurrency=point_at(sweep, at)["memory"]["max_concurrency_context"],
        prereg=prereg,
    )
    out["tenants"] = tenants
    if a4 is not None and tenants["feasible"]:
        out["cost_table"] = three_way_table(tenants["tenants"], prereg, a4)
    context = a4_context(a4)
    if context is not None:
        out["a4_context"] = context
    return out
