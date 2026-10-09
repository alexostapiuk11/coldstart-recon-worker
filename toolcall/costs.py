"""Cost per successful call, and when a richer formulation pays for itself
(August §5, "business framing"; amendment §4f).

Two policies, both computed from recorded calls and their own usage:

- single attempt: every graded call's cost, divided by the CORRECT ones.
- retry until success, up to `retry_cap` attempts: each scenario's repetitions,
  in their recorded order (block index), are cut into consecutive groups of
  `retry_cap`; a group spends until its first CORRECT call, or all of it.

The second is why this is computed from data and not from c / (1 - f): that
formula assumes a retry is an independent draw. With near-deterministic reruns
a scenario that fails tends to fail again, so the formula understates what a
retry policy costs. Both numbers are reported; the gap between them is the
unit-of-variation argument in dollars.

Calls excluded by grade (API_ERROR, REFUSED, TRUNCATED) are left out of both
and reported with the cell's counts.
"""

from collections import defaultdict

from toolcall.effects import cluster_bootstrap
from toolcall.formulation import CELLS
from toolcall.grader import EXCLUDED


def _units(records):
    """{scenario: {cell: [(block_index, cost_usd, correct)]}}, sorted by block."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r.grade["category"] in EXCLUDED:
            continue
        if r.cost_usd is None:
            raise ValueError(f"run {r.run_index} is graded {r.grade['category']} but "
                             "carries no cost; graded calls are always metered")
        out[r.scenario_id][r.cell].append(
            (r.block_index, r.cost_usd, r.grade["category"] == "CORRECT"))
    return {s: {c: sorted(v) for c, v in cells.items()} for s, cells in out.items()}


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


def cost_per_success(records, retry_cap: int, iterations: int, seed: int,
                     alpha: float = 0.05) -> dict:
    units = _units(records)
    sids = sorted(units)
    out = {}
    for cell in CELLS:
        rows = [units[s][cell.name] for s in sids]
        reps = [r for row in rows for r in row]
        n_calls = len(reps)
        call_cost = sum(c for _, c, _ in reps) / n_calls
        failure = 1 - sum(ok for _, _, ok in reps) / n_calls
        entry = {"calls": n_calls, "usd_per_call": call_cost, "failure_rate_pooled": failure,
                 "geometric_usd_per_success": (call_cost / (1 - failure)
                                               if failure < 1 else None)}
        for name, policy in (("single", _single),
                             ("retry", lambda rs: _retry(rs, retry_cap))):
            r = cluster_bootstrap(rows, lambda rs, p=policy: _ratio([p(x) for x in rs]),
                                  iterations=iterations, seed=seed, alpha=alpha)
            entry[name] = {k: (None if isinstance(v, float) and v == float("inf") else v)
                           for k, v in r.items()}
        out[cell.name] = entry
    return out


def break_even(costs: dict) -> list[dict]:
    """For each pair differing only in richness: rich's per-call overhead and,
    under the geometric formula (labelled as such), the failure rate rich must
    reach to cost no more per success than terse."""
    out = []
    for cell in CELLS:
        if cell.richness != "terse":
            continue
        rich = f"{cell.count}-rich-{cell.strictness}"
        t, r = costs[cell.name], costs[rich]
        overhead = r["usd_per_call"] / t["usd_per_call"] - 1
        required = 1 - (r["usd_per_call"] / t["usd_per_call"]) * (1 - t["failure_rate_pooled"])
        out.append({
            "terse": cell.name, "rich": rich,
            "overhead_per_call": overhead,
            "terse_failure_rate": t["failure_rate_pooled"],
            "rich_failure_rate": r["failure_rate_pooled"],
            "required_rich_failure_rate_geometric": required,
            "pays_geometric": r["failure_rate_pooled"] <= required,
            "pays_measured_retry": (
                r["retry"]["point"] is not None and t["retry"]["point"] is not None
                and r["retry"]["point"] <= t["retry"]["point"]
            ),
        })
    return out
