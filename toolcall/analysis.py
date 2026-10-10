"""Everything the post reports, as one JSON-shaped dict.

The figures and the post's numbers block read this and nothing else, so a
number in the post is a number in `data/a3/analysis.json`, and tests fail if
either drifts from a fresh run of this function.

One analysable scenario set. Before any estimate, the included scenarios are
cut to those with at least `prereg.min_graded_per_cell` graded repetitions
(not API_ERROR, REFUSED or TRUNCATED) in every cell. The rest are dropped and
listed in `dropped_scenarios` with their graded counts, so a reader can see
what was lost and why. The set is passed explicitly to every estimate, the
hypotheses and the costs: `S`, the effects, the hypotheses and the cost table
are all about the same scenarios. H5 may drop a few more (an empty A/A half),
disclosed in `h5_dropped_scenarios`.

`analysable_below_s_floor` is true when fewer scenarios survive the floor than
the pre-registered `s_floor`. The estimates still run (while S reaches the
bootstrap floor), but the post must disclose that the pre-registered scenario
count was not met.
"""

from collections import Counter, defaultdict

from harness.stats import MIN_BOOTSTRAP_SAMPLES
from toolcall import NORMALIZER_VERSION, SCHEMA_VERSION
from toolcall.costs import break_even, cost_per_success
from toolcall.effects import (
    average,
    cell_rates,
    cluster_bootstrap,
    effect,
    ever_flip_rows,
    graded_outcomes,
    rate_rows,
)
from toolcall.formulation import CELLS, parse_cell
from toolcall.grader import CATEGORIES, EXCLUDED, FAILURES
from toolcall.hypotheses import bootstrap_params, evaluate
from toolcall.normalize import RULES
from toolcall.scenarios import PERSISTENT_KINDS

ESTIMANDS = (
    "main:count", "main:richness", "main:strictness",
    "interaction:richness:count", "interaction:strictness:count",
    "interaction:strictness:richness",
    "at:richness:count:low", "at:richness:count:high",
)


def analysable_scenarios(records, included, prereg) -> tuple[list[str], list[dict]]:
    """The scenarios every estimate is about, and the ones dropped.

    `included`: ids pre-registered (or all scenario ids). Kept: at least
    `prereg.min_graded_per_cell` graded repetitions in every cell. Dropped ones
    carry the graded count per cell, so the reason can be checked."""
    graded = graded_outcomes(records)
    floor = prereg.min_graded_per_cell
    keep, dropped = [], []
    for sid in sorted(included):
        by_cell = {cell.name: len(graded.get(sid, {}).get(cell.name, [])) for cell in CELLS}
        if min(by_cell.values()) >= floor:
            keep.append(sid)
        else:
            short = sorted(c for c, n in by_cell.items() if n < floor)
            dropped.append({
                "scenario": sid,
                "reason": f"fewer than {floor} graded repetitions in {len(short)} "
                          f"cell(s): {', '.join(short)}",
                "graded_by_cell": by_cell,
            })
    return keep, dropped


def counts_by_cell(records) -> dict:
    out: dict = {}
    for cell in CELLS:
        rs = [r for r in records if r.cell == cell.name]
        c = Counter(r.grade["category"] for r in rs)
        out[cell.name] = {
            **{k: c.get(k, 0) for k in CATEGORIES + EXCLUDED},
            "calls": len(rs),
            "multiple_calls": sum(r.grade["multiple_calls"] for r in rs),
            "text_looks_like_call": sum(r.grade["text_looks_like_call"] for r in rs),
            "empty_response": sum(r.grade["empty_response"] for r in rs),
            "unmetered": sum(r.unmetered for r in rs),
            "excluded_share": (sum(c.get(k, 0) for k in EXCLUDED) / len(rs)) if rs else None,
        }
    return out


def ranked_cells(records, prereg, scenarios=None) -> dict:
    """Best and worst cells by failure-rate point estimate: the pre-registered
    rule that picks the recovery, slice and exploratory cells (amendment §4e).
    Over `scenarios`, the analysable set (default: every scenario in `records`)."""
    rows = rate_rows(graded_outcomes(records), FAILURES, scenarios=scenarios)
    points = {c.name: average(r[c.name] for r in rows) for c in CELLS}
    order = sorted(points, key=lambda k: (points[k], k))
    return {"best": order[0], "worst": order[-1], "failure_rate": points}


def _two_cell(records, cells: tuple[str, str], scenarios, prereg) -> dict:
    outcomes = graded_outcomes(records)
    formulations = [parse_cell(c) for c in cells]
    rows = rate_rows(outcomes, FAILURES, cells=formulations, scenarios=scenarios)
    kw = bootstrap_params(prereg)
    out = {c: cluster_bootstrap(rows, lambda rs, c=c: average(r[c] for r in rs), **kw)
           for c in cells}
    out["difference"] = cluster_bootstrap(
        rows, lambda rs: average(r[cells[1]] - r[cells[0]] for r in rs), **kw)
    out["cells"] = list(cells)
    return out


def _slice(records, cells: tuple[str, str], analysable, prereg) -> dict:
    """One slice model on the two slice cells. The scenarios are the analysable
    set intersected with those this model has at least `min_graded_per_cell`
    graded repetitions for in both cells; the others are disclosed. If fewer
    than the bootstrap floor remain the slice is reported as not estimable, with
    the reason, rather than raising and losing the whole analysis."""
    keep = set(analysable)
    records = [r for r in records if r.scenario_id in keep]
    graded = graded_outcomes(records)
    floor = prereg.min_graded_per_cell
    eligible, dropped = [], []
    for sid in analysable:
        by_cell = {c: len(graded.get(sid, {}).get(c, [])) for c in cells}
        if min(by_cell.values()) >= floor:
            eligible.append(sid)
        else:
            dropped.append({"scenario": sid, "graded_by_cell": by_cell})
    if len(eligible) < MIN_BOOTSTRAP_SAMPLES:
        return {"estimable": False, "cells": list(cells), "dropped_scenarios": dropped,
                "reason": f"{len(eligible)} scenarios with at least {floor} graded repetitions "
                          f"in both cells; the bootstrap floor is {MIN_BOOTSTRAP_SAMPLES}"}
    return {"estimable": True, "dropped_scenarios": dropped,
            **_two_cell(records, cells, eligible, prereg)}


def _exploratory(records, best: str, analysable):
    """Constrained-decoding calls, which are only comparable in the best cell:
    any record from another cell is an error. Counted over the analysable set."""
    if not records:
        return None
    wrong = sorted({r.cell for r in records if r.cell != best})
    if wrong:
        raise ValueError(f"exploratory calls must all be in the best cell {best}; got {wrong}")
    return {"cell": best,
            "counts": Counter(r.grade["category"] for r in records
                              if r.scenario_id in analysable)}


def _marginal(failure_rows, prereg) -> dict:
    """Failure rate at each (count, richness) pair, averaged over strictness:
    the four points of the interaction figure, each with its interval."""
    out = {}
    for count in ("low", "high"):
        for richness in ("terse", "rich"):
            cells = [f"{count}-{richness}-{s}" for s in ("loose", "strict")]
            out[f"{count}-{richness}"] = cluster_bootstrap(
                failure_rows,
                lambda rs, cs=cells: average(average(r[c] for c in cs) for r in rs),
                **bootstrap_params(prereg))
    return out


def _identical_retry_ci(records, fmt, prereg):
    """Per-scenario identical-retry rates over persistent kinds, bootstrapped
    over scenarios; None when too few scenarios for the bootstrap floor."""
    by: dict = defaultdict(list)
    for r in records:
        if (r.fmt == fmt and r.injected and not r.excluded
                and r.error_kind in PERSISTENT_KINDS and r.identical_retry is not None):
            by[r.scenario_id].append(bool(r.identical_retry))
    units = [sum(v) / len(v) for _, v in sorted(by.items())]
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        return None
    return cluster_bootstrap(units, average, **bootstrap_params(prereg))


def _recovery(records, prereg) -> dict:
    by_fmt: dict = defaultdict(list)
    for r in records:
        by_fmt[r.fmt].append(r)
    out = {}
    for fmt, rs in sorted(by_fmt.items()):
        injected = [r for r in rs if r.injected and not r.excluded]
        n = len(injected)
        out[fmt] = {
            "conversations": len(rs),
            "injected": n,
            "not_injected": sum(not r.injected and not r.excluded for r in rs),
            "excluded": Counter(r.excluded for r in rs if r.excluded),
            "identical_retry": (sum(bool(r.identical_retry) for r in injected) / n) if n else None,
            "recovered": (sum(r.recovered for r in injected) / n) if n else None,
            "gave_up": (sum(r.gave_up for r in injected) / n) if n else None,
            "hallucinated_success": (sum(r.hallucinated_success for r in injected) / n)
            if n else None,
            "turns_to_recovery": Counter(r.turns_to_recovery for r in injected if r.recovered),
            "identical_retry_persistent": _identical_retry_ci(rs, fmt, prereg),
        }
    return out


def _sensitivity(records, scenarios, prereg) -> dict:
    """Exploratory. The failure-rate effects again, with API_ERROR, REFUSED and
    TRUNCATED counted as failures instead of dropped, on the analysable set.
    The main analysis drops them as ungradable; this shows how far the effects
    move if they were really failures. Not pre-registered as a test."""
    out: dict = defaultdict(lambda: defaultdict(list))
    for r in records:  # duplicates were already refused by graded_outcomes
        out[r.scenario_id][r.cell].append((r.block_index, r.grade["category"]))
    rows = rate_rows(out, FAILURES + EXCLUDED, scenarios=scenarios)
    kw = bootstrap_params(prereg)
    return {
        "label": "exploratory: not pre-registered, not part of the hypothesis family",
        "target": "failure rate, API_ERROR + REFUSED + TRUNCATED counted as failures",
        "effects": {e: effect(rows, e, **kw) for e in ESTIMANDS},
    }


def analyse(records, recovery_records, scenarios, prereg, *, slices=None,
            exploratory=None, spend=None) -> dict:
    """`records`: the primary model's campaign calls. `slices`: {model: calls}
    in the two slice cells. `exploratory`: constrained-decoding calls in the
    best cell, or None if the slice was cut.

    `counts` covers every call of the included scenarios, dropped ones too: the
    calls were made and paid for, and a scenario dropped for too many API
    errors would otherwise vanish from the excluded counts that explain it.
    Everything else is about the analysable scenarios only."""
    included = set(prereg.included) if prereg.included else {s.id for s in scenarios}
    records = [r for r in records if r.scenario_id in included]
    analysable, dropped = analysable_scenarios(records, included, prereg)
    keep = set(analysable)
    counts = counts_by_cell(records)
    records = [r for r in records if r.scenario_id in keep]
    recovery_records = [r for r in recovery_records if r.scenario_id in keep]
    outcomes = graded_outcomes(records)
    kw = bootstrap_params(prereg)
    failure_rows = rate_rows(outcomes, FAILURES, scenarios=analysable)
    rates = {"failure": cell_rates(failure_rows, **kw)}
    for cat in FAILURES:
        rates[cat] = cell_rates(rate_rows(outcomes, (cat,), scenarios=analysable), **kw)
    effects = {
        target: {e: effect(rate_rows(outcomes, cats, scenarios=analysable), e, **kw)
                 for e in ESTIMANDS}
        for target, cats in (("failure", FAILURES), ("WRONG_TOOL", ("WRONG_TOOL",)),
                             ("MALFORMED+WRONG_PARAMS", ("MALFORMED", "WRONG_PARAMS")))
    }
    # Only units with two or more graded repetitions can flip; every analysable
    # unit has at least `min_graded_per_cell`, which may be 1, so count them.
    flips = ever_flip_rows(outcomes, scenarios=analysable, min_reps=2)
    distinct = Counter(len({c for _, c in reps}) for s in analysable
                       for reps in outcomes[s].values())
    informative = sum(len(reps) >= 2 for s in analysable for reps in outcomes[s].values())
    wrong_kind = Counter(r.grade.get("wrong_tool_kind") for r in records
                         if r.grade["category"] == "WRONG_TOOL")
    costs = cost_per_success(records, prereg.retry_cap, **kw, scenarios=analysable)
    ranks = ranked_cells(records, prereg, analysable)
    out = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_rules": [list(r) for r in RULES],
        "model": prereg.primary.model,
        "settings": prereg.primary.to_dict(),
        "S": len(analysable),
        "analysable_below_s_floor": len(analysable) < prereg.s_floor,
        "N": prereg.reps,
        "retry_cap": prereg.retry_cap,
        "recovery_reps": prereg.recovery_reps,
        "slice_reps": prereg.slice_reps,
        "baseline_cell": prereg.baseline_cell,
        "min_graded_per_cell": prereg.min_graded_per_cell,
        "dropped_scenarios": dropped,
        "counts": counts,
        "cell_rates": rates,
        "marginal_count_richness": _marginal(failure_rows, prereg),
        "effects": effects,
        "sensitivity_exclusions_as_failures": _sensitivity(records, analysable, prereg),
        "hypotheses": evaluate(outcomes, recovery_records, prereg, scenarios=analysable),
        "flakiness": {
            "ever_flip": cluster_bootstrap(flips, average, **kw),
            "units_with_two_or_more": informative,
            "distinct_categories_per_unit": {str(k): v for k, v in sorted(distinct.items())},
            "units": sum(distinct.values()),
        },
        "wrong_tool_kind": {str(k): v for k, v in sorted(wrong_kind.items())},
        "ranked_cells": ranks,
        "recovery": _recovery(recovery_records, prereg),
        "cost": costs,
        "break_even": break_even(costs),
        "slice": {model: _slice(rs, (ranks["best"], ranks["worst"]), analysable, prereg)
                  for model, rs in sorted((slices or {}).items())},
        "exploratory_constrained": _exploratory(exploratory, ranks["best"], keep),
        "spend": spend,
    }
    h5 = out["hypotheses"]["H5"]
    out["h5_dropped_scenarios"] = list(h5["dropped_scenarios"])
    return _plain(out)


def _plain(x):
    """Counters and tuples to JSON types, so the dict round-trips byte-for-byte."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    return x
