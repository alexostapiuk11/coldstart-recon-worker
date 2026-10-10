"""Everything the post reports, as one JSON-shaped dict.

The figures and the post's numbers block read this and nothing else, so a
number in the post is a number in `data/a3/analysis.json`, and tests fail if
either drifts from a fresh run of this function.
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
from toolcall.hypotheses import evaluate
from toolcall.normalize import RULES
from toolcall.scenarios import PERSISTENT_KINDS

ESTIMANDS = (
    "main:count", "main:richness", "main:strictness",
    "interaction:richness:count", "interaction:strictness:count",
    "interaction:strictness:richness",
    "at:richness:count:low", "at:richness:count:high",
)


def _kw(prereg) -> dict:
    return {"iterations": prereg.iterations, "seed": prereg.bootstrap_seed,
            "alpha": prereg.alpha}


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
            "excluded_share": (sum(c.get(k, 0) for k in EXCLUDED) / len(rs)) if rs else None,
        }
    return out


def ranked_cells(records, prereg) -> dict:
    """Best and worst cells by failure-rate point estimate: the pre-registered
    rule that picks the recovery, slice and exploratory cells (amendment §4e)."""
    rows = rate_rows(graded_outcomes(records), FAILURES)
    points = {c.name: average(r[c.name] for r in rows) for c in CELLS}
    order = sorted(points, key=lambda k: (points[k], k))
    return {"best": order[0], "worst": order[-1], "failure_rate": points}


def _two_cell(records, cells: tuple[str, str], prereg) -> dict:
    outcomes = graded_outcomes(records)
    formulations = [parse_cell(c) for c in cells]
    rows = rate_rows(outcomes, FAILURES, cells=formulations)
    kw = _kw(prereg)
    out = {c: cluster_bootstrap(rows, lambda rs, c=c: average(r[c] for r in rs), **kw)
           for c in cells}
    out["difference"] = cluster_bootstrap(
        rows, lambda rs: average(r[cells[1]] - r[cells[0]] for r in rs), **kw)
    out["cells"] = list(cells)
    return out


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
                **_kw(prereg))
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
    return cluster_bootstrap(units, average, **_kw(prereg))


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


def analyse(records, recovery_records, scenarios, prereg, *, slices=None,
            exploratory=None, spend=None) -> dict:
    """`records`: the primary model's campaign calls. `slices`: {model: calls}
    in the two slice cells. `exploratory`: constrained-decoding calls in the
    best cell, or None if the slice was cut."""
    included = set(prereg.included) if prereg.included else {s.id for s in scenarios}
    records = [r for r in records if r.scenario_id in included]
    outcomes = graded_outcomes(records)
    kw = _kw(prereg)
    failure_rows = rate_rows(outcomes, FAILURES)
    rates = {"failure": cell_rates(failure_rows, **kw)}
    for cat in FAILURES:
        rates[cat] = cell_rates(rate_rows(outcomes, (cat,)), **kw)
    effects = {
        target: {e: effect(rate_rows(outcomes, cats), e, **kw) for e in ESTIMANDS}
        for target, cats in (("failure", FAILURES), ("WRONG_TOOL", ("WRONG_TOOL",)),
                             ("MALFORMED+WRONG_PARAMS", ("MALFORMED", "WRONG_PARAMS")))
    }
    flips = ever_flip_rows(outcomes)
    distinct = Counter(len({c for _, c in reps}) for cells in outcomes.values()
                       for reps in cells.values())
    wrong_kind = Counter(r.grade.get("wrong_tool_kind") for r in records
                         if r.grade["category"] == "WRONG_TOOL")
    costs = cost_per_success(records, prereg.retry_cap, prereg.iterations,
                             prereg.bootstrap_seed, prereg.alpha)
    ranks = ranked_cells(records, prereg)
    out = {
        "schema_version": SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "normalizer_rules": [list(r) for r in RULES],
        "model": prereg.primary.model,
        "settings": prereg.primary.to_dict(),
        "S": len(outcomes),
        "N": prereg.reps,
        "counts": counts_by_cell(records),
        "cell_rates": rates,
        "marginal_count_richness": _marginal(failure_rows, prereg),
        "effects": effects,
        "hypotheses": evaluate(outcomes, recovery_records, prereg),
        "flakiness": {
            "ever_flip": cluster_bootstrap(flips, average, **kw),
            "distinct_categories_per_unit": {str(k): v for k, v in sorted(distinct.items())},
            "units": sum(distinct.values()),
        },
        "wrong_tool_kind": {str(k): v for k, v in sorted(wrong_kind.items())},
        "ranked_cells": ranks,
        "recovery": _recovery(recovery_records, prereg),
        "cost": costs,
        "break_even": break_even(costs),
        "slice": {model: _two_cell(rs, (ranks["best"], ranks["worst"]), prereg)
                  for model, rs in sorted((slices or {}).items())},
        "exploratory_constrained": (
            {"cell": ranks["best"],
             "counts": Counter(r.grade["category"] for r in exploratory)}
            if exploratory else None),
        "spend": spend,
    }
    return _plain(out)


def _plain(x):
    """Counters and tuples to JSON types, so the dict round-trips byte-for-byte."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_plain(v) for v in x]
    return x
