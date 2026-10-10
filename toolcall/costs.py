"""Cost per successful call, and when a richer formulation pays for itself
(August §5, "business framing"; amendment §4f).

Cost per success is total spend, failed attempts included, over the number of
CORRECT calls. Two policies, both computed from recorded calls and their own
usage:

- single attempt: every paid call's cost, divided by the CORRECT ones.
- retry until success, up to `retry_cap` attempts: each scenario's calls in one
  cell, in their recorded order (block index), are cut into consecutive groups
  of `retry_cap`; a group spends until its first CORRECT call, or all of it.

What counts as spend. A graded call (CORRECT or one of the failure categories)
is paid. So are REFUSED and TRUNCATED calls: they are metered, the provider
billed them, and they are failed attempts with no win. They enter the spend and
the retry walk as failures, in recorded order, and are reported per cell in
`excluded_usd` and `excluded_by_category`. API_ERROR calls are the exception:
their cost is None (no usable usage), so they are left out of spend; the spend
record reconciles them. They are counted in `excluded_by_category` only.
`failure_rate_pooled` is over graded calls only, because that is what a rate
means here; REFUSED, TRUNCATED and API_ERROR calls are not in it.

Why the retry walk is computed from data, not from c / (1 - f). The single
attempt cost per success equals c / (1 - f) exactly, by construction: both are
sum(cost) / sum(wins). The informative comparison is the retry walk against it.
That formula assumes a retry is an independent draw. With near-deterministic
reruns a scenario that fails tends to fail again, so the formula understates
what a retry policy costs; the gap is the unit-of-variation argument in dollars.

Cost-side quantities are call-weighted ratios of sums (a scenario with more
paid calls weighs more). Cell rates in `effects.py` weight scenarios equally.
Intervals resample whole scenarios either way.

Guards mirror `effects.py`: a repeated (scenario, cell, block) record, or a
scenario with no graded repetitions in a cell, is a ValueError. `retry_cap`
must fit inside the shortest scenario-cell, so "no complete group" can never
masquerade as "never succeeds".
"""

import math
from collections import defaultdict

from toolcall.effects import _graded_reps, cluster_bootstrap, graded_outcomes
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED

# Excluded categories that were still metered and billed. API_ERROR is the rest.
PAID_EXCLUDED = ("REFUSED", "TRUNCATED")


def _units(records):
    """{scenario: {cell: [(block_index, cost_usd, correct)]}}, sorted by block.

    Graded calls and paid excluded calls (REFUSED, TRUNCATED, as failures) are
    included; API_ERROR calls are not. A paid call with no cost is refused: a
    call that produced no usable usage is always graded API_ERROR."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        category = r.grade["category"]
        if category == "API_ERROR":
            continue
        if r.cost_usd is None:
            raise ValueError(f"run {r.run_index} is graded {category} but "
                             "carries no cost; graded calls are always metered")
        out[r.scenario_id][r.cell].append((r.block_index, r.cost_usd, category == "CORRECT"))
    return {s: {c: sorted(v, key=lambda t: t[0]) for c, v in cells.items()}
            for s, cells in out.items()}


def _single(reps) -> tuple[float, int]:
    return sum(c for _, c, _ in reps), sum(ok for _, _, ok in reps)


def _retry(reps, cap: int) -> tuple[float, int]:
    spent, wins = 0.0, 0
    for start in range(0, len(reps) - cap + 1, cap):
        for _, cost, ok in reps[start:start + cap]:
            spent += cost
            if ok:
                wins += 1
                break
    return spent, wins


def _ratio(pairs) -> float:
    spent = sum(s for s, _ in pairs)
    wins = sum(w for _, w in pairs)
    return spent / wins if wins else float("inf")


def _diff(rich: float, terse: float) -> float:
    """rich - terse, with infinity read as "never succeeds": both infinite is
    no difference, an infinite rich side is dearer, an infinite terse side is
    cheaper."""
    if math.isinf(rich) and math.isinf(terse):
        return 0.0
    if math.isinf(rich):
        return math.inf
    if math.isinf(terse):
        return -math.inf
    return rich - terse


def _finite(x):
    return None if isinstance(x, float) and not math.isfinite(x) else x


def _interval(r: dict) -> dict:
    """A bootstrap result reduced to what a cost needs; an unbounded endpoint
    (some resample had no wins) is None, not infinity."""
    return {k: (_finite(r[k]) if k in ("point", "lo", "hi") else r[k])
            for k in ("point", "lo", "hi", "n_scenarios", "iterations", "alpha")}


def _verdict(r: dict) -> str:
    """Judged on the raw interval: an infinite endpoint still has a sign."""
    if r["hi"] < 0:
        return "pays"
    if r["lo"] > 0:
        return "does not pay"
    return "undetermined"


def cost_per_success(records, retry_cap: int, iterations: int, seed: int,
                     alpha: float = 0.05, *, scenarios=None) -> dict:
    """`scenarios`: the analysable set, as ids. Default: every scenario in the
    records. When given, only those scenarios' records are read, so a scenario
    outside the set cannot reach the spend, the retry walk or the guards, and a
    scenario in the set with no graded repetitions in a cell is refused."""
    records = list(records)
    if scenarios is not None:
        keep = set(scenarios)
        records = [r for r in records if r.scenario_id in keep]
    graded = graded_outcomes(records)  # duplicates and unknown categories refused
    units = _units(records)
    sids = sorted(set(scenarios) if scenarios is not None
                  else {r.scenario_id for r in records})
    for sid in sids:
        for cell in CELLS:
            _graded_reps(graded, sid, cell.name)  # the one missing-cell rule
    shortest = min(len(units[sid][cell.name]) for sid in sids for cell in CELLS)
    if retry_cap < 1 or retry_cap > shortest:
        raise ValueError(f"retry_cap must be between 1 and {shortest}, the fewest "
                         f"repetitions any scenario has in any cell; got {retry_cap}")

    excluded = {cell.name: dict.fromkeys(EXCLUDED, 0) for cell in CELLS}
    excluded_usd = dict.fromkeys(excluded, 0.0)
    for r in records:
        category = r.grade["category"]
        if category in EXCLUDED and r.cell in excluded:
            excluded[r.cell][category] += 1
            if category in PAID_EXCLUDED:
                excluded_usd[r.cell] += r.cost_usd

    out = {}
    paired_inputs = {}
    for cell in CELLS:
        rows = [units[s][cell.name] for s in sids]
        n_graded = sum(len(graded[s][cell.name]) for s in sids)
        spend = sum(c for row in rows for _, c, _ in row)
        wins = sum(ok for row in rows for _, _, ok in row)
        call_cost = spend / n_graded  # spend per graded call, paid excluded calls included
        failure = 1 - wins / n_graded
        single = [_single(row) for row in rows]
        retry = [_retry(row, retry_cap) for row in rows]
        paired_inputs[cell.name] = retry
        entry = {
            "calls": n_graded,
            "calls_used_retry": sum(len(row) // retry_cap * retry_cap for row in rows),
            "usd_per_call": call_cost,
            "failure_rate_pooled": failure,
            # Equals the single-attempt cost per success exactly (both are
            # sum(cost) / sum(wins)); kept as the formula the retry walk is
            # compared against.
            "geometric_usd_per_success": call_cost / (1 - failure) if failure < 1 else None,
            "excluded_by_category": excluded[cell.name],
            "excluded_usd": excluded_usd[cell.name],
        }
        for name, pairs in (("single", single), ("retry", retry)):
            entry[name] = _interval(cluster_bootstrap(
                pairs, _ratio, iterations=iterations, seed=seed, alpha=alpha))
        out[cell.name] = entry

    # Paired: the same resampled scenarios for rich and terse, so what is
    # compared is cost under one draw of the scenario set, not two.
    for cell in CELLS:
        if cell.richness != "terse":
            continue
        rich = f"{cell.count}-rich-{cell.strictness}"
        pairs = list(zip(paired_inputs[cell.name], paired_inputs[rich], strict=True))
        r = cluster_bootstrap(
            pairs, lambda ps: _diff(_ratio([b for _, b in ps]), _ratio([a for a, _ in ps])),
            iterations=iterations, seed=seed, alpha=alpha)
        out[cell.name]["retry_vs_rich"] = {**_interval(r), "verdict": _verdict(r)}
    return out


def break_even(costs: dict) -> list[dict]:
    """For each pair differing only in richness: rich's per-call overhead and,
    under the geometric formula (labelled as such), the failure rate rich must
    reach to cost no more per success than terse. The measured verdict is the
    paired retry-cost difference, rich minus terse, from `cost_per_success`:
    "pays" if its whole interval is below zero, "does not pay" if above,
    otherwise "undetermined"."""
    out = []
    for cell in CELLS:
        if cell.richness != "terse":
            continue
        rich = f"{cell.count}-rich-{cell.strictness}"
        t, r = costs[cell.name], costs[rich]
        paired = t["retry_vs_rich"]
        row = {
            "terse": cell.name, "rich": rich,
            "terse_failure_rate": t["failure_rate_pooled"],
            "rich_failure_rate": r["failure_rate_pooled"],
            "cost_difference_retry": {k: paired[k] for k in ("point", "lo", "hi")},
            "retry_verdict": paired["verdict"],
        }
        if t["usd_per_call"] > 0:
            ratio = r["usd_per_call"] / t["usd_per_call"]
            raw = 1 - ratio * (1 - t["failure_rate_pooled"])
            row.update({
                "overhead_per_call": ratio - 1,
                "required_rich_failure_rate_geometric": max(0.0, raw),
                "achievable_geometric": raw >= 0,
                "pays_geometric": raw >= 0 and r["failure_rate_pooled"] <= raw,
            })
        else:  # a free terse call: no overhead ratio, nothing to break even against
            row.update({
                "overhead_per_call": None,
                "required_rich_failure_rate_geometric": None,
                "achievable_geometric": None,
                "pays_geometric": None,
            })
        out.append(row)
    return out
