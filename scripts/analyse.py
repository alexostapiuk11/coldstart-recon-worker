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
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
    discard_table,
    failure_rate_by_arm,
    partition,
)
from coldstart.analysis.stats import (
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_median_diff,
    median,
    percentiles,
    within_host_triples,
)
from coldstart.store import JsonlStore

ITERATIONS = 10_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    out: dict = {"n_records": len(rows)}

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

    pub = total_part.publishable
    out["distributions"] = {
        arm: percentiles([r["t_total"] for r in pub if r["arm"] == arm])
        for arm in ("A", "B", "C")
    }
    # H5: does a warm compile cache buy KV capacity? Routed through the shared
    # median every other aggregate uses, not a hand-rolled index.
    out["kv_capacity_median"] = {
        arm: median([r["kv_capacity_tokens"] for r in pub if r["arm"] == arm])
        for arm in ("A", "B", "C")
        if any(r["arm"] == arm for r in pub)
    }

    weights_pub = partition(rows, required=REQUIRED_FOR_T_WEIGHTS).publishable
    by_w = {a: [r["t_weights"] for r in weights_pub if r["arm"] == a] for a in "ABC"}
    by_c = {a: [r["t_compile"] for r in pub if r["arm"] == a] for a in "ABC"}

    # Mechanism contrasts, each in the unit that explains it.
    out["contrast_A_to_B_t_weights"] = bootstrap_median_diff(
        by_w["A"], by_w["B"], iterations=ITERATIONS, seed=1
    )
    out["contrast_B_to_C_t_compile"] = bootstrap_median_diff(
        by_c["B"], by_c["C"], iterations=ITERATIONS, seed=2
    )

    # The ranking claim, in one unit across all three arms. It has to be a
    # single metric: bootstrap_contrast_difference computes
    # (median(a) - median(b)) - (median(b) - median(c)) and uses b twice, so
    # feeding it t_weights for A/B and t_compile for C would subtract two
    # different quantities and produce a number that means nothing. t_total is
    # the honest common unit -- "which cache buys more cold start back".
    by_t = {a: [r["t_total"] for r in pub if r["arm"] == a] for a in "ABC"}
    out["contrast_A_to_B_t_total"] = bootstrap_median_diff(
        by_t["A"], by_t["B"], iterations=ITERATIONS, seed=5
    )
    out["contrast_B_to_C_t_total"] = bootstrap_median_diff(
        by_t["B"], by_t["C"], iterations=ITERATIONS, seed=6
    )
    # Reported before any ranking claim is made -- spec 7.
    out["difference_of_contrasts_t_total"] = bootstrap_contrast_difference(
        by_t["A"], by_t["B"], by_t["C"], iterations=ITERATIONS, seed=3
    )

    triples = within_host_triples(rows)
    out["within_host_triples"] = len(triples)
    if len(triples) >= 20:
        out["paired_A_to_B_t_weights"] = bootstrap_paired_median_diff(
            triples, "A", "B", "t_weights", iterations=ITERATIONS, seed=4
        )
    else:
        out["paired_A_to_B_t_weights"] = (
            f"withheld: {len(triples)} triples is below the 20-unit bootstrap floor"
        )

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
