"""`data/a4/cost_per_tenant.json`: artifact 4's per-tenant costs for artifact 5.

The format was agreed with artifact 5's session on 2026-09-26 (amendment §11):
`gpu_hourly_rate`, `n_models`, a `reference` grid point fixed in the second
pre-registration step, and one row per (regime, s) with the dedicated, swapped
(process-level arm) and sleep-mode cost per tenant per month, null where a
strategy is dominated or the point is not evaluable. Sleep mode is never
simulated here (amendment §6), so its column is always null.

Artifact 5 refuses the file if the reference matches zero or several rows, if
the reference row has no dedicated or no swapped cost, or if the rate differs
from its own. `build` refuses the first two itself, so a file artifact 5 would
refuse is never written; the rate is artifact 5's to check, since it reads
artifact 4's committed rate (its plan 2).

`model` names the checkpoint every cost in the file was measured on, with its pinned
revision. It is an addition to the agreed format: no existing key or value changed.
"""

from placement_measure.prereg import CANDIDATES

__all__ = ["build"]


def _cost(point: dict, strategy: str) -> float | None:
    if not point["evaluable"]:
        return None
    view = point["strategies"][strategy]
    return None if view is None else view["cost_per_tenant_month"]


def build(analysis: dict) -> dict:
    rows = []
    for regime, r in analysis["regimes"].items():
        for p in r["points"]:
            rows.append({
                "regime": regime, "s": p["s"],
                "dedicated_cost_per_tenant_month": _cost(p, "dedicate"),
                "swapped_cost_per_tenant_month": _cost(p, "swap"),
                "sleep_mode_cost_per_tenant_month": None,
            })
    ref = analysis["reference"]
    matches = [row for row in rows if row["regime"] == ref["regime"] and row["s"] == ref["s"]]
    if len(matches) != 1:
        raise ValueError(f"the reference {ref} matches {len(matches)} rows, not 1")
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        if matches[0][key] is None:
            raise ValueError(
                f"the reference row has no {key.split('_')[0]} cost (dominated or not "
                "evaluable); artifact 5 would refuse the file. This is a finding for the "
                "owner, not a gap to fill"
            )
    model = analysis["inputs"]["model"]
    if model not in CANDIDATES:
        raise ValueError(f"{model!r} is not a registered checkpoint, so it has no pinned revision "
                         "to name in the file")
    return {
        "gpu_hourly_rate": analysis["rate"]["gpu_hourly_rate"],
        "rate_provenance": analysis["rate"]["provenance"],
        "n_models": analysis["design"]["n_models"],
        "reference": dict(ref),
        "rows": rows,
        "source": "artifact 4, data/a4/analysis.json; process-level swap arm",
        # Added 2026-10-07 at artifact 5's request: its figure sets an adapter bar on a
        # different model beside these bars, and the file is what says which model these are.
        "model": {"id": model, "revision": CANDIDATES[model]},
    }
