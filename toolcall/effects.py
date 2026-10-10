"""Rates, effects and their intervals, clustered on scenario (amendment §4f).

- A per-scenario rate is the share of one scenario's graded repetitions, in
  one cell, that land in a set of categories. Wilson intervals are used for
  these, and only these, because there the repetitions are the unit.
- A cell rate averages per-scenario rates, each scenario weighted equally.
- Effects are risk differences in percentage points, the 2^3 contrasts:
  a main effect is the high level minus the low, averaged over the other two
  factors; a two-way interaction is a factor's effect at the other factor's
  high level minus its effect at the low level.
- Every interval is a paired percentile bootstrap over scenarios: each draw
  resamples whole scenarios, so a scenario that fails for one reason in every
  repetition counts once, not N times. That is the August design's
  unit-of-variation correction.

`harness/stats.py` is medians-only by design. These estimators are new, so
they live here; the percentile endpoints, the iteration checks and the
bootstrap floor are the harness's own, imported, not copied.
"""

import math
import random
from collections import defaultdict

from harness.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    _check_iterations_and_alpha,
    _percentile_interval,
)
from toolcall.formulation import CELLS
from toolcall.grader import CATEGORIES, EXCLUDED

FACTORS = ("count", "richness", "strictness")
# Level words per factor: the second word is the high (+1) level.
LEVELS = {"count": ("low", "high"), "richness": ("terse", "rich"),
          "strictness": ("loose", "strict")}


def _graded_reps(outcomes, sid, cell_name):
    """The one missing-cell rule: a scenario with no graded repetitions in a
    cell is an error, never silently averaged over the cells it does have."""
    reps = outcomes.get(sid, {}).get(cell_name, [])
    if not reps:
        raise ValueError(f"scenario {sid} has no graded repetitions in {cell_name}")
    return reps


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"wilson needs 0 <= k <= n and n > 0, got k={k}, n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # Floating error would leave 5.55e-17 / 0.9999999999999999 at the extremes.
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return lo, hi


def graded_outcomes(records) -> dict[str, dict[str, list[tuple[int, str]]]]:
    """{scenario: {cell: [(block_index, category), ...]}}, excluded outcomes
    removed. A repeated (scenario, cell, block_index) is refused: it would
    count one repetition twice."""
    out: dict = defaultdict(lambda: defaultdict(list))
    seen = set()
    for r in records:
        key = (r.scenario_id, r.cell, r.block_index)
        if key in seen:
            raise ValueError(
                f"duplicate record for scenario {r.scenario_id}, cell {r.cell}, "
                f"block {r.block_index} (run {r.run_index})"
            )
        seen.add(key)
        cat = r.grade["category"]
        if cat in EXCLUDED:
            continue
        if cat not in CATEGORIES:
            raise ValueError(f"unknown category {cat!r} in run {r.run_index}")
        out[r.scenario_id][r.cell].append((r.block_index, cat))
    return {s: dict(c) for s, c in out.items()}


def rate_rows(outcomes, categories, cells=CELLS, scenarios=None) -> list[dict[str, float]]:
    """One row per scenario: {cell name: rate of `categories`}. Every scenario
    must have graded repetitions in every cell, or the contrast is undefined."""
    cats = set(categories)
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        row = {}
        for cell in cells:
            reps = _graded_reps(outcomes, sid, cell.name)
            row[cell.name] = sum(c in cats for _, c in reps) / len(reps)
        rows.append(row)
    return rows


def weights(estimand: str) -> dict[str, float]:
    """Cell weights for `main:<factor>`, `interaction:<f>:<g>`, or
    `at:<f>:<g>:<low|high>` (the effect of f with g held at one level)."""
    parts = estimand.split(":")
    kind = parts[0]
    if kind == "main" and len(parts) == 2 and parts[1] in FACTORS:
        def weight(s):
            return s[parts[1]] / 4
    elif (kind == "interaction" and len(parts) == 3 and parts[1] in FACTORS
          and parts[2] in FACTORS and parts[1] != parts[2]):
        def weight(s):
            return s[parts[1]] * s[parts[2]] / 2
    elif (kind == "at" and len(parts) == 4 and parts[1] in FACTORS and parts[2] in FACTORS
          and parts[1] != parts[2] and parts[3] in LEVELS[parts[2]]):
        level = 1 if parts[3] == LEVELS[parts[2]][1] else -1

        def weight(s):
            return s[parts[1]] / 2 if s[parts[2]] == level else 0.0
    else:
        raise ValueError(f"unknown or malformed estimand {estimand!r}")
    return {cell.name: weight(cell.signs) for cell in CELLS}


def contrast(row: dict[str, float], estimand: str) -> float:
    return sum(wt * row[cell] for cell, wt in weights(estimand).items())


def cluster_bootstrap(units: list, statistic, iterations: int = 10000, seed: int = 0,
                      alpha: float = 0.05) -> dict:
    """Percentile interval on `statistic(units)`, resampling whole units
    (scenarios) with replacement. Also returns one-sided bootstrap p-values,
    the share of draws at or beyond zero on each side, add-one smoothed.
    `p_le_0` (mass at or below zero) is the p-value for a claim that the
    effect is positive; `p_ge_0` is the p-value for a claim that it is
    negative. Draws exactly at zero count on both sides, which is
    conservative."""
    _check_iterations_and_alpha(iterations, alpha)
    if len(units) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{len(units)} scenarios; a bootstrap over scenarios needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (harness.stats.MIN_BOOTSTRAP_SAMPLES)"
        )
    rng = random.Random(seed)
    n = len(units)
    draws = [statistic([units[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations)]
    lo, hi = _percentile_interval(draws, alpha)
    return {
        "point": statistic(units),
        "lo": lo,
        "hi": hi,
        "p_le_0": (sum(d <= 0 for d in draws) + 1) / (iterations + 1),
        "p_ge_0": (sum(d >= 0 for d in draws) + 1) / (iterations + 1),
        "n_scenarios": n,
        "iterations": iterations,
        "alpha": alpha,
    }


def average(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs)


def effect(rows, estimand: str, **kw) -> dict:
    return cluster_bootstrap(rows, lambda rs: average(contrast(r, estimand) for r in rs), **kw)


def cell_rates(rows, **kw) -> dict[str, dict]:
    return {
        cell.name: cluster_bootstrap(rows, lambda rs, c=cell.name: average(r[c] for r in rs),
                                     **kw)
        for cell in CELLS
    }


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Holm's step-down procedure: reject in order of p until the first
    p > alpha / (m - rank); nothing after it is rejected."""
    order = sorted(pvalues, key=lambda k: pvalues[k])
    m = len(order)
    out = {k: False for k in pvalues}
    for rank, key in enumerate(order):
        if pvalues[key] > alpha / (m - rank):
            break
        out[key] = True
    return out


def ever_flip_rows(outcomes, scenarios=None, min_reps: int = 1) -> list[float]:
    """Per scenario: the share of its cells whose graded repetitions do not all
    land in one category. The Noise Floor Audit's measure (amendment §4f).

    A cell with a single graded repetition cannot flip, so counting it as "did
    not flip" would pull the fraction down for no reason. `min_reps` keeps only
    the (scenario, cell) units with at least that many graded repetitions in
    the denominator; a scenario with no such unit has no row."""
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        flips = []
        for cell in CELLS:
            reps = _graded_reps(outcomes, sid, cell.name)
            if len(reps) >= min_reps:
                flips.append(len({c for _, c in reps}) > 1)
        if flips:
            rows.append(sum(flips) / len(flips))
    return rows


def half_rows(outcomes, categories, scenarios=None) -> list[dict[str, float]]:
    """Per scenario and cell: the rate among even-numbered repetitions minus
    the rate among odd-numbered ones. The A/A contrast H5 compares against."""
    cats = set(categories)
    rows = []
    for sid in sorted(scenarios if scenarios is not None else outcomes):
        row = {}
        for cell in CELLS:
            reps = _graded_reps(outcomes, sid, cell.name)
            even = [c for b, c in reps if b % 2 == 0]
            odd = [c for b, c in reps if b % 2 == 1]
            if not even or not odd:
                raise ValueError(f"{sid} {cell.name}: the A/A contrast needs both halves")
            row[cell.name] = (sum(c in cats for c in even) / len(even)
                              - sum(c in cats for c in odd) / len(odd))
        rows.append(row)
    return rows


def per_scenario_wilson(outcomes, categories, cell: str) -> list[dict]:
    cats = set(categories)
    out = []
    for sid in sorted(outcomes):
        reps = _graded_reps(outcomes, sid, cell)
        k = sum(c in cats for _, c in reps)
        lo, hi = wilson(k, len(reps))
        out.append({"scenario": sid, "k": k, "n": len(reps), "rate": k / len(reps),
                    "lo": lo, "hi": hi})
    return out
