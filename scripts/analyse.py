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


def _missing_arms(samples: dict[str, list], arms: tuple[str, ...]) -> list[str]:
    """Arms in `arms` whose sample list in `samples` is empty."""
    return [a for a in arms if not samples.get(a)]


def _withheld_message(missing: list[str]) -> str:
    """Same 'withheld: <reason>' idiom the paired bootstrap below already
    uses, naming every empty arm so an operator can see which one it was
    rather than a bare crash."""
    names = " and ".join(f"arm {a}" for a in missing)
    verb = "has" if len(missing) == 1 else "have"
    return f"withheld: {names} {verb} no publishable rows"


def _bootstrap_or_withhold(compute, samples: dict[str, list], arms: tuple[str, ...]):
    """Run `compute()` unless any of `arms` has zero rows in `samples`, in
    which case withhold with a message naming the empty arm(s) instead of
    letting the bootstrap raise on an empty sample."""
    missing = _missing_arms(samples, arms)
    if missing:
        return _withheld_message(missing)
    return compute()


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
    out["distributions"] = {}
    for arm in ("A", "B", "C"):
        arm_rows = [r["t_total"] for r in pub if r["arm"] == arm]
        if arm_rows:
            out["distributions"][arm] = percentiles(arm_rows)
        else:
            out["distributions"][arm] = _withheld_message([arm])
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

    # Mechanism contrasts, each in the unit that explains it. An arm with no
    # publishable rows (e.g. a systematic failure or a rate limit that wiped
    # out one arm mid-campaign) must not crash the analysis that exists to
    # explain why a campaign looks wrong -- it is withheld by name instead.
    out["contrast_A_to_B_t_weights"] = _bootstrap_or_withhold(
        lambda: bootstrap_median_diff(by_w["A"], by_w["B"], iterations=ITERATIONS, seed=1),
        by_w,
        ("A", "B"),
    )
    out["contrast_B_to_C_t_compile"] = _bootstrap_or_withhold(
        lambda: bootstrap_median_diff(by_c["B"], by_c["C"], iterations=ITERATIONS, seed=2),
        by_c,
        ("B", "C"),
    )

    # The ranking claim, in one unit across all three arms. It has to be a
    # single metric: bootstrap_contrast_difference computes
    # (median(a) - median(b)) - (median(b) - median(c)) and uses b twice, so
    # feeding it t_weights for A/B and t_compile for C would subtract two
    # different quantities and produce a number that means nothing. t_total is
    # the honest common unit -- "which cache buys more cold start back".
    by_t = {a: [r["t_total"] for r in pub if r["arm"] == a] for a in "ABC"}
    out["contrast_A_to_B_t_total"] = _bootstrap_or_withhold(
        lambda: bootstrap_median_diff(by_t["A"], by_t["B"], iterations=ITERATIONS, seed=5),
        by_t,
        ("A", "B"),
    )
    out["contrast_B_to_C_t_total"] = _bootstrap_or_withhold(
        lambda: bootstrap_median_diff(by_t["B"], by_t["C"], iterations=ITERATIONS, seed=6),
        by_t,
        ("B", "C"),
    )
    # Reported before any ranking claim is made -- spec 7.
    out["difference_of_contrasts_t_total"] = _bootstrap_or_withhold(
        lambda: bootstrap_contrast_difference(
            by_t["A"], by_t["B"], by_t["C"], iterations=ITERATIONS, seed=3
        ),
        by_t,
        ("A", "B", "C"),
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
