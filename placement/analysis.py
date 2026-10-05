"""Every published number about the sweep, from its evaluations.

August §8's metrics, the amendment's sizing and crossover (§7, §8), and the
money view, as plain JSON-ready dicts. `scripts/a4_analyse.py` writes them to
`data/a4/analysis.json`; the figures, the cost file and the post read that
file and recompute nothing, as artifact 1's figures read `data/analysis.json`.

Per grid point and strategy, at the fleet each strategy is sized to:

- cost: monthly, per tenant, and per million output tokens at the offered load;
- aggregate p99, the median across repetitions with a bootstrap interval;
- per-decile p99 and SLO breach, medians across repetitions;
- hit rate (requests whose model was resident on arrival) and swaps per hour.

Two views carry the post's fairness argument (August §8, "Averages hide
tenants"). `aggregate_rule` sizes every strategy on the aggregate p99 instead
of the per-decile one, and reports what the coldest decile gets at that
cheaper fleet. `fairness` compares swap and co-locate decile by decile at a
common fleet size, paired by repetition, with `harness.stats`'s paired
bootstrap (amendment §8).
"""

from collections.abc import Sequence

from harness.stats import bootstrap_median_ci, bootstrap_paired_median_diff, median
from placement.crossover import cheapest, estimate_crossover
from placement.design import Design
from placement.evaluate import ConfigOutcome, PointEvaluation
from placement.fleet import STRATEGIES
from placement.money import HOURS_PER_MONTH, SECONDS_PER_HOUR, Assumptions, monthly_cost
from placement.sizing import sized_fleet
from placement.traffic import DECILES

__all__ = ["analyse", "fairness", "point_view", "size_by_aggregate"]

BOOTSTRAP_ITERATIONS = 10_000
CROSSOVER_ITERATIONS = 2000
COLDEST = DECILES - 1


def size_by_aggregate(outcomes: Sequence[ConfigOutcome], reps: Sequence[int], slo: float) -> int | None:
    """The smallest M whose median-across-repetitions AGGREGATE p99 meets the
    SLO: what a fleet dashboard would size to. None if none does."""
    for outcome in outcomes:
        values = [outcome.aggregate_p99s[r] for r in reps]
        if any(v is None for v in values):
            raise ValueError(f"{outcome.strategy} at M={outcome.m} has a repetition under the "
                             "aggregate p99 floor; it cannot be sized on the aggregate")
        if median(values) <= slo:
            return outcome.m
    return None


def _at(outcomes: Sequence[ConfigOutcome], m: int) -> ConfigOutcome:
    for outcome in outcomes:
        if outcome.m == m:
            return outcome
    raise ValueError(f"no configuration at M={m}")


def _median_or_none(values):
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _strategy_view(c: ConfigOutcome, reps, *, warmup: float, until: float, n_models: int,
                   tokens_per_month: float, rate: Assumptions, seed: int) -> dict:
    aggregate = [c.aggregate_p99s[r] for r in reps]
    ci = bootstrap_median_ci(aggregate, iterations=BOOTSTRAP_ITERATIONS, seed=seed)
    cost = monthly_cost(c.m, rate)
    return {
        "m": c.m,
        "monthly_cost": cost,
        "cost_per_tenant_month": cost / n_models,
        "cost_per_million_tokens": cost / tokens_per_month * 1e6,
        "aggregate_p99": {"point": median(aggregate), "lo": ci["lo"], "hi": ci["hi"]},
        "decile_p99": [median([c.decile_p99s[r][d] for r in reps]) for d in range(DECILES)],
        "decile_breach": ([_median_or_none([c.decile_breach[r][d] for r in reps])
                           for d in range(DECILES)] if c.decile_breach else None),
        "hit_rate": sum(c.hits[r] for r in reps) / sum(c.requests[r] for r in reps),
        # Swaps begun inside the measured window, over its length: warm-up
        # and drain-out swaps are artefacts of a finite run (amendment §7).
        "swaps_per_hour": median([c.window_swaps[r] / (until - warmup) * SECONDS_PER_HOUR
                                  for r in reps]),
        "extrapolated_dispatches": sum(c.extrapolated[r] for r in reps),
    }


def point_view(e: PointEvaluation, design: Design, *, total_rate: float, output_len: int,
               rate: Assumptions) -> dict:
    reps = list(range(e.repetitions))
    base = {"regime": e.point.regime, "s": e.point.s, "window_s": e.point.until - design.warmup}
    sized = sized_fleet(e, reps, design.slo_seconds)
    if sized is None:
        return {**base, "evaluable": False}
    tokens_per_month = total_rate * output_len * HOURS_PER_MONTH * SECONDS_PER_HOUR
    views = {}
    for i, strategy in enumerate(STRATEGIES):
        m = sized[strategy]
        views[strategy] = None if m is None else _strategy_view(
            _at(e.outcomes[strategy], m), reps, warmup=design.warmup, until=e.point.until,
            n_models=design.n_models,
            tokens_per_month=tokens_per_month, rate=rate, seed=design.seed + i)
    aggregate_rule = {}
    for strategy in STRATEGIES:
        m = size_by_aggregate(e.outcomes[strategy], reps, design.slo_seconds)
        if m is None:
            aggregate_rule[strategy] = None
            continue
        c = _at(e.outcomes[strategy], m)
        breach = ([c.decile_breach[r][COLDEST] for r in reps] if c.decile_breach else [])
        deciles = [median([c.decile_p99s[r][d] for r in reps]) for d in range(DECILES)]
        aggregate_rule[strategy] = {
            "m": m,
            "decile_p99": deciles,
            "coldest_decile_p99": deciles[COLDEST],
            "coldest_decile_breach": _median_or_none(breach),
        }
    best = sorted(cheapest(sized))
    feasible = [m for m in sized.values() if m is not None]
    return {
        **base, "evaluable": True, "sized": sized, "cheapest": best, "strategies": views,
        "aggregate_rule": aggregate_rule,
        "dedicate_over_cheapest_per_month": (
            None if sized["dedicate"] is None or not feasible
            else monthly_cost(sized["dedicate"], rate) - monthly_cost(min(feasible), rate)),
    }


def fairness(e: PointEvaluation, sized: dict, *, a: str = "swap", b: str = "colocate",
             seed: int = 0) -> dict | None:
    """Per-decile p99 of `a` minus `b` at a common fleet size, paired by
    repetition. The common size is the larger of the two sized fleets, which
    both families contain because both reach dedicate's M. None when either
    strategy is dominated."""
    if sized.get(a) is None or sized.get(b) is None:
        return None
    m = max(sized[a], sized[b])
    ca, cb = _at(e.outcomes[a], m), _at(e.outcomes[b], m)
    reps = range(e.repetitions)
    deciles = []
    for d in range(DECILES):
        units = [[{"arm": a, "p99": ca.decile_p99s[r][d]}, {"arm": b, "p99": cb.decile_p99s[r][d]}]
                 for r in reps]
        deciles.append(bootstrap_paired_median_diff(units, a, b, value="p99",
                                                    iterations=BOOTSTRAP_ITERATIONS, seed=seed + d))
    return {"m": m, "a": a, "b": b, "deciles": deciles}


def _segments(points: list[dict]) -> tuple[list[dict], list[dict]]:
    """The decision rule: runs of adjacent grid points with the same cheapest
    set, as skew ranges, and the points no run may claim.

    A point that is not evaluable, or where no strategy meets the SLO, ends a
    run and is listed as a gap. The crossover estimator skips such points too
    (`placement.crossover.crossings` locates only points with a cheapest set),
    but a rule stated as "s = 0.6-1.0: co-locate" must not cover a point in
    the middle that said nothing."""
    segments: list[dict] = []
    gaps: list[dict] = []
    current: dict | None = None
    for p in points:
        if not p["evaluable"] or not p["cheapest"]:
            gaps.append({"s": p["s"], "reason": "not evaluable" if not p["evaluable"]
                         else "no strategy meets the SLO"})
            current = None
            continue
        if current is not None and current["cheapest"] == p["cheapest"]:
            current["to_s"] = p["s"]
        else:
            current = {"from_s": p["s"], "to_s": p["s"], "cheapest": p["cheapest"]}
            segments.append(current)
    return segments, gaps


def analyse(evaluations: Sequence[PointEvaluation], design: Design, *, total_rate: float,
            output_len: int, rate: Assumptions, reference: dict) -> dict:
    regimes = {}
    for regime in design.regimes:
        chosen = sorted((e for e in evaluations if e.point.regime == regime),
                        key=lambda e: e.point.s)
        points = [point_view(e, design, total_rate=total_rate, output_len=output_len, rate=rate)
                  for e in chosen]
        estimate = estimate_crossover(chosen, design.slo_seconds,
                                      iterations=CROSSOVER_ITERATIONS, seed=design.seed)
        skews = [e.point.s for e in chosen]
        segments, gaps = _segments(points)
        regimes[regime] = {
            "points": points,
            "decision_rule": segments,
            "gaps": gaps,
            "crossover": {
                "between": [[skews[i], skews[j]] for i, j in estimate.point],
                "interval_lower_point": (None if estimate.interval is None
                                         else [skews[i] for i in estimate.interval]),
                "no_crossing": estimate.no_crossing, "one_crossing": estimate.one_crossing,
                "many_crossings": estimate.many_crossings, "iterations": estimate.iterations,
            },
        }
    ref = [e for e in evaluations
           if e.point.regime == reference["regime"] and e.point.s == reference["s"]]
    if len(ref) != 1:
        raise ValueError(f"the reference point {reference} matches {len(ref)} grid points, not 1")
    ref_sized = sized_fleet(ref[0], list(range(ref[0].repetitions)), design.slo_seconds)
    return {
        "design": {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(design).items()},
        "rate": {"gpu_hourly_rate": rate.gpu_hourly_rate, "provenance": rate.provenance},
        "total_rate_rps": total_rate,
        "output_len": output_len,
        "reference": dict(reference),
        "regimes": regimes,
        "fairness": None if ref_sized is None else fairness(ref[0], ref_sized, seed=design.seed),
    }
