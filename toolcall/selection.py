"""The pilot's two outputs: which candidates are included, and rho (amendment §5).

Selection uses the baseline cell only, against a band fixed at pre-registration
step 1 (August §4's rule). Every candidate is listed with its rate and its
decision, and excluded candidates stay in the repository, flagged.
"""

from collections import defaultdict

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall.budget import Line, icc, reps_for, table, total
from toolcall.effects import wilson
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED
from toolcall.guard import bound_held
from toolcall.providers import ModelSettings


def baseline_table(pilot_records, scenarios, prereg) -> list[dict]:
    """One row per candidate. A record outside the baseline cell, naming an
    unknown scenario, or repeating a (scenario, block) is refused. A candidate
    with fewer graded repetitions than `prereg.min_graded_per_cell` is excluded
    (the pre-registered rule), whatever its rate."""
    known = {s.id for s in scenarios}
    by: dict = defaultdict(list)
    dropped: dict = defaultdict(int)
    seen: set = set()
    for r in pilot_records:
        if r.cell != prereg.baseline_cell:
            raise ValueError(f"run {r.run_index} is in {r.cell}, not the baseline cell")
        if r.scenario_id not in known:
            raise ValueError(
                f"run {r.run_index} names scenario {r.scenario_id!r}, not among the candidates")
        key = (r.scenario_id, r.block_index)
        if key in seen:
            raise ValueError(
                f"scenario {r.scenario_id!r} block {r.block_index} appears twice "
                f"(run {r.run_index}): a repeated record would count one repetition twice")
        seen.add(key)
        if r.grade["category"] in EXCLUDED:
            dropped[r.scenario_id] += 1
        else:
            by[r.scenario_id].append(r.grade["category"] == "CORRECT")
    lo, hi = prereg.band
    out = []
    for s in sorted(scenarios, key=lambda s: s.id):
        reps = by.get(s.id, [])
        excluded = dropped.get(s.id, 0)
        if not reps:
            out.append({"scenario": s.id, "n": 0, "correct": 0, "rate": None,
                        "excluded": excluded, "include": False,
                        "reason": "no graded pilot repetitions"})
            continue
        k = sum(reps)
        rate = k / len(reps)
        w_lo, w_hi = wilson(k, len(reps))
        if len(reps) < prereg.min_graded_per_cell:
            include, reason = False, "too few graded repetitions"
        else:
            include = lo <= rate <= hi
            reason = "inside the band" if include else (
                "at or near ceiling" if rate > hi else "at or near floor")
        out.append({"scenario": s.id, "n": len(reps), "correct": k, "rate": rate,
                    "wilson_lo": w_lo, "wilson_hi": w_hi, "excluded": excluded,
                    "include": include, "reason": reason, "target": s.target_failure_mode})
    return out


def rho(pilot_records, included: set[str]) -> float:
    """The pilot's intra-scenario correlation over the included scenarios.

    Caveat: rho is estimated on the same repetitions that selected the
    scenarios. Selecting on the band bounds each scenario's rate away from 0 and
    1, so within-scenario variance cannot be near zero and rho is biased low.
    N then comes out larger than the true rho would give: conservative for
    power and costlier, and the cap bounds it. No correction is applied."""
    by: dict = defaultdict(list)
    for r in pilot_records:
        if r.scenario_id in included and r.grade["category"] not in EXCLUDED:
            by[r.scenario_id].append(int(r.grade["category"] == "CORRECT"))
    return icc(list(by.values()))


def table_markdown(rows: list[dict]) -> str:
    lines = ["| scenario | target | correct / n | rate | Wilson 95% | excluded | decision |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["rate"] is None:
            lines.append(
                f"| `{r['scenario']}` | | 0 / 0 | | | {r['excluded']} | exclude: {r['reason']} |")
            continue
        lines.append(
            f"| `{r['scenario']}` | {r['target']} | {r['correct']} / {r['n']} | "
            f"{r['rate']:.2f} | {r['wilson_lo']:.2f}–{r['wilson_hi']:.2f} | {r['excluded']} | "
            f"{'include' if r['include'] else 'exclude'}: {r['reason']} |")
    return "\n".join(lines)


def _usd_per_call(records, what: str) -> float:
    priced = [r.cost_usd for r in records if r.cost_usd is not None]
    if not priced:
        raise ValueError(f"no priced calls among the pilot records for {what}")
    return sum(priced) / len(priced)


def _dearest_cell_usd(records, what: str) -> float:
    """The highest per-cell mean cost among `records`, grouped by `cell`."""
    by_cell: dict = defaultdict(list)
    for r in records:
        by_cell[r.cell].append(r)
    if not by_cell:
        raise ValueError(f"no pilot records for {what}")
    means = []
    for cell, recs in by_cell.items():
        if any(r.cost_usd is not None for r in recs):
            means.append(_usd_per_call(recs, f"{what}, cell {cell}"))
    if not means:
        raise ValueError(f"no priced calls among the pilot records for {what}")
    return max(means)


def _guard_misses(pilot: dict) -> list:
    """Run indexes of every pilot call or recovery turn whose measured input
    tokens exceeded the spend guard's pre-call bound."""
    singles = pilot["baseline"] + pilot["cells"] + [r for v in pilot["slice"].values() for r in v]
    misses = [r.run_index for r in singles if r.usage and not bound_held(
        ModelSettings(**r.settings), r.request, r.usage)]
    for rec in pilot["recovery"]:
        settings = ModelSettings(**rec.settings)
        misses += [rec.run_index for t in rec.turns if "parsed" in t and not bound_held(
            settings, t["request"], t["parsed"]["usage"])]
    return misses


def step2_proposal(pilot: dict, scenarios, prereg) -> dict:
    """Everything step 2 fixes, computed from the pilot's stores (amendment §5).

    The recovery and slice phases use the same N as the campaign: the same
    rho argument applies to their repetitions. That N inherits `rho`'s caveat:
    rho is estimated on the repetitions that selected the scenarios, which
    biases it low and N high (conservative for power, costlier; the cap bounds
    it).

    `pilot` holds the four pilot stores' records: "baseline", "cells" (all
    eight cells), "slice" ({model: records}) and "recovery" (conversations).
    Cost per call is measured, not assumed: per cell from "cells", per slice
    model from "slice", per conversation from "recovery". The best cell is not
    known at step 2, so everything that will run in it is priced at the dearest
    cell: the exploratory line at the dearest cell's cost, each slice model at
    its own dearest cell's mean, and the recovery conversation (pilot recovery
    runs in the baseline cell) scaled by dearest-cell cost over baseline-cell
    cost. The guard's input bound is checked on every pilot call and every
    recovery turn. The budget table's total covers plan 3's phases only: the
    pilot is already spent."""
    rows = baseline_table(pilot["baseline"], scenarios, prereg)
    included = tuple(r["scenario"] for r in rows if r["include"])
    misses = _guard_misses(pilot)
    if misses:
        raise ValueError(f"the spend guard's input bound failed on {len(misses)} pilot calls; "
                         "lower toolcall.guard.CHARS_PER_TOKEN_BOUND (fewer characters per "
                         "token makes the input bound larger) before any campaign spend")
    if len(included) < prereg.s_floor:
        return {"candidates": len(rows), "included": included,
                "selection_table": table_markdown(rows), "enough_scenarios": False}
    by_id = {s.id: s for s in scenarios}
    r = rho(pilot["baseline"], set(included))
    n = reps_for(r, prereg.n_floor, prereg.n_cap)
    cell_cost = {c.name: _usd_per_call([x for x in pilot["cells"] if x.cell == c.name],
                                       f"cell {c.name}")
                 for c in CELLS}
    per_cell = sum(cell_cost.values()) / len(cell_cost)
    dearest = max(cell_cost.values())
    baseline_cost = cell_cost[prereg.baseline_cell]
    if baseline_cost <= 0:
        raise ValueError(f"the baseline cell {prereg.baseline_cell} has a zero measured cost; "
                         "the recovery conversation cannot be scaled to the dearest cell")
    if not pilot["recovery"]:
        raise ValueError("the pilot's recovery store is empty: a recovery conversation "
                         "cannot be priced")
    rec_conv_baseline = sum(x.cost_usd for x in pilot["recovery"]) / len(pilot["recovery"])
    rec_conv = rec_conv_baseline * dearest / baseline_cost
    n_rec = sum(1 for i in included if by_id[i].recovery)
    s = len(included)
    lines = [
        Line(f"campaign: 8 cells x {s} scenarios x {n}", 8 * s * n, per_cell),
        Line(f"recovery: 2 cells x 2 formats x {n_rec} scenarios x {n}",
             2 * 2 * n_rec * n, rec_conv),
        Line(f"exploratory: 1 cell x {s} x {n}", s * n, dearest),
    ]
    for model, recs in sorted(pilot["slice"].items()):
        lines.append(Line(f"slice {model}: 2 cells x {s} x {n}", 2 * s * n,
                          _dearest_cell_usd(recs, f"slice model {model}")))
    return {
        "candidates": len(rows), "included": included, "rho": r, "reps": n,
        "recovery_scenarios": n_rec, "recovery_reps": n, "slice_reps": n,
        "usd_per_call_by_cell": cell_cost,
        "usd_per_recovery_conversation_baseline": rec_conv_baseline,
        "usd_per_recovery_conversation": rec_conv, "estimate_usd": total(lines),
        "budget_table": table(
            lines, total_label="total, plan 3's phases only (the pilot is sunk)"),
        "selection_table": table_markdown(rows),
        "enough_scenarios": True,
        "enough_recovery_scenarios": n_rec >= MIN_BOOTSTRAP_SAMPLES,
    }
