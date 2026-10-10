"""The pilot's two outputs: which candidates are included, and rho (amendment §5).

Selection uses the baseline cell only, against a band fixed at pre-registration
step 1 (August §4's rule). Every candidate is listed with its rate and its
decision, and excluded candidates stay in the repository, flagged.
"""

from collections import defaultdict

from toolcall.budget import Line, icc, reps_for, table, total
from toolcall.effects import wilson
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED
from toolcall.guard import bound_held
from toolcall.providers import ModelSettings


def baseline_table(pilot_records, scenarios, prereg) -> list[dict]:
    by: dict = defaultdict(list)
    for r in pilot_records:
        if r.cell != prereg.baseline_cell:
            raise ValueError(f"run {r.run_index} is in {r.cell}, not the baseline cell")
        if r.grade["category"] not in EXCLUDED:
            by[r.scenario_id].append(r.grade["category"] == "CORRECT")
    lo, hi = prereg.band
    out = []
    for s in sorted(scenarios, key=lambda s: s.id):
        reps = by.get(s.id, [])
        if not reps:
            out.append({"scenario": s.id, "n": 0, "correct": 0, "rate": None,
                        "include": False, "reason": "no graded pilot repetitions"})
            continue
        k = sum(reps)
        rate = k / len(reps)
        w_lo, w_hi = wilson(k, len(reps))
        include = lo <= rate <= hi
        reason = "inside the band" if include else (
            "at or near ceiling" if rate > hi else "at or near floor")
        out.append({"scenario": s.id, "n": len(reps), "correct": k, "rate": rate,
                    "wilson_lo": w_lo, "wilson_hi": w_hi, "include": include,
                    "reason": reason, "target": s.target_failure_mode})
    return out


def rho(pilot_records, included: set[str]) -> float:
    by: dict = defaultdict(list)
    for r in pilot_records:
        if r.scenario_id in included and r.grade["category"] not in EXCLUDED:
            by[r.scenario_id].append(int(r.grade["category"] == "CORRECT"))
    return icc(list(by.values()))


def table_markdown(rows: list[dict]) -> str:
    lines = ["| scenario | target | correct / n | rate | Wilson 95% | decision |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        if r["rate"] is None:
            lines.append(f"| `{r['scenario']}` | | 0 / 0 | | | exclude: {r['reason']} |")
            continue
        lines.append(
            f"| `{r['scenario']}` | {r['target']} | {r['correct']} / {r['n']} | "
            f"{r['rate']:.2f} | {r['wilson_lo']:.2f}–{r['wilson_hi']:.2f} | "
            f"{'include' if r['include'] else 'exclude'}: {r['reason']} |")
    return "\n".join(lines)


def _usd_per_call(records) -> float:
    priced = [r.cost_usd for r in records if r.cost_usd is not None]
    if not priced:
        raise ValueError("no priced calls in this pilot store")
    return sum(priced) / len(priced)


def step2_proposal(pilot: dict, scenarios, prereg) -> dict:
    """Everything step 2 fixes, computed from the pilot's stores (amendment §5).

    The recovery and slice phases use the same N as the campaign: the same
    rho argument applies to their repetitions.

    `pilot` holds the four pilot stores' records: "baseline", "cells" (all
    eight cells), "slice" ({model: records}) and "recovery" (conversations).
    Cost per call is measured, not assumed: per cell from "cells", per slice
    model from "slice", per conversation from "recovery". The exploratory slice
    is priced at the dearest cell, since the best cell is not known yet."""
    rows = baseline_table(pilot["baseline"], scenarios, prereg)
    included = tuple(r["scenario"] for r in rows if r["include"])
    singles = pilot["baseline"] + pilot["cells"] + [r for v in pilot["slice"].values() for r in v]
    misses = [r.run_index for r in singles if r.usage and not bound_held(
        ModelSettings(**r.settings), r.request, r.usage)]
    if misses:
        raise ValueError(f"the spend guard's input bound failed on {len(misses)} pilot calls; "
                         "raise toolcall.guard.CHARS_PER_TOKEN_BOUND's margin before any "
                         "campaign spend")
    if len(included) < prereg.s_floor:
        return {"candidates": len(rows), "included": included,
                "selection_table": table_markdown(rows), "enough_scenarios": False}
    by_id = {s.id: s for s in scenarios}
    r = rho(pilot["baseline"], set(included))
    n = reps_for(r, prereg.n_floor, prereg.n_cap)
    cell_cost = {c.name: _usd_per_call([x for x in pilot["cells"] if x.cell == c.name])
                 for c in CELLS}
    per_cell = sum(cell_cost.values()) / len(cell_cost)
    rec_conv = sum(x.cost_usd for x in pilot["recovery"]) / len(pilot["recovery"])
    n_rec = sum(1 for i in included if by_id[i].recovery)
    s = len(included)
    lines = [
        Line(f"campaign: 8 cells x {s} scenarios x {n}", 8 * s * n, per_cell),
        Line(f"recovery: 2 cells x 2 formats x {n_rec} scenarios x {n}",
             2 * 2 * n_rec * n, rec_conv),
        Line(f"exploratory: 1 cell x {s} x {n}", s * n, max(cell_cost.values())),
    ]
    for model, recs in sorted(pilot["slice"].items()):
        lines.append(Line(f"slice {model}: 2 cells x {s} x {n}", 2 * s * n,
                          _usd_per_call(recs)))
    return {
        "candidates": len(rows), "included": included, "rho": r, "reps": n,
        "recovery_scenarios": n_rec, "recovery_reps": n, "slice_reps": n,
        "usd_per_call_by_cell": cell_cost,
        "usd_per_recovery_conversation": rec_conv, "estimate_usd": total(lines),
        "budget_table": table(lines), "selection_table": table_markdown(rows),
        "enough_scenarios": True,
        "enough_recovery_scenarios": n_rec >= 20,
    }
