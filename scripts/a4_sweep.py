"""Run artifact 4's sweep: size every strategy at every grid point, locate the crossover.

Against PLACEHOLDER inputs until the measurement plan replaces them. The output
is then a check that the machinery works, not a result, which is why the script
refuses unmeasured inputs unless run with --allow-unmeasured and says so on
stdout before anything runs.

The evaluations are cached to JSON under a name derived from every input, so
re-printing a summary does not re-run the sweep, and a changed input can never
silently reuse a stale cache. `--refresh` re-runs it anyway.
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.traffic import saturation_rps
from placement.crossover import estimate_crossover
from placement.design import Design
from placement.evaluate import Scenario, dump_evaluations, load_evaluations
from placement.grid import evaluate_grid, grid
from placement.money import Assumptions, monthly_difference
from placement.resample import EmpiricalDistribution
from placement.sim import Engines
from placement.sizing import sized_fleet

CROSSOVER_ITERATIONS = 2000
# Bumped whenever an evaluation gains a field, so a cache written by older code
# is never read back with the new fields silently empty.
CACHE_VERSION = 2


def _require_measured(design: Design, engines: Engines, swap_time: EmpiricalDistribution, allow: bool) -> None:
    unmeasured = [
        name
        for name, ok in (
            ("solo curve", engines.solo.measured),
            ("co-located surface", engines.colocated.measured),
            ("swap times", swap_time.measured),
            ("design", design.preregistered),
        )
        if not ok
    ]
    if not unmeasured:
        return
    if not allow:
        raise SystemExit(
            f"refusing to sweep: {', '.join(unmeasured)} are placeholders. Their "
            "output is indistinguishable from a result in every format. Pass "
            "--allow-unmeasured to check the machinery against them."
        )
    print(f"WARNING: {', '.join(unmeasured)} are placeholders. This is not a result.")


def _cache_key(design, engines, swap_time) -> str:
    material = json.dumps(
        [CACHE_VERSION, asdict(design), asdict(engines.solo), asdict(engines.colocated),
         asdict(swap_time)],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def scenario_for(design: Design, engines: Engines) -> Scenario:
    return Scenario(
        n_models=design.n_models, offered_gpus=design.offered_gpus,
        saturation_rps=saturation_rps(engines.solo), hot_fraction=design.hot_fraction,
        warmup=design.warmup, mean_burst=design.mean_burst, duty=design.duty,
    )


def evaluations_for(design: Design, engines: Engines, swap_time: EmpiricalDistribution,
                    out: Path, workers: int, refresh: bool = False) -> list:
    """The grid's evaluations, from the cache when every input matches.
    `scripts/a4_analyse.py` reads the sweep through here, so the analysis and
    the summary are computed from the same evaluations."""
    out.mkdir(parents=True, exist_ok=True)
    scenario = scenario_for(design, engines)
    cache = out / f"evaluations-{_cache_key(design, engines, swap_time)}.json"
    if cache.exists() and not refresh:
        print(f"reusing {cache} (--refresh to re-run)")
        return load_evaluations(cache)
    evaluations = evaluate_grid(
        grid(design, scenario), scenario, engines, swap_time, design.repetitions,
        design.seed, design.slo_seconds, workers,
    )
    dump_evaluations(cache, evaluations)
    print(f"cached {len(evaluations)} grid points to {cache}")
    return evaluations


def run(
    design: Design,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    rate: Assumptions,
    out: Path,
    workers: int,
    allow_unmeasured: bool,
    refresh: bool = False,
) -> dict:
    _require_measured(design, engines, swap_time, allow_unmeasured)
    evaluations = evaluations_for(design, engines, swap_time, out, workers, refresh)

    everything = list(range(design.repetitions))
    summary: dict = {"design": asdict(design), "rate": asdict(rate), "regimes": {}}
    for regime in design.regimes:
        chosen = sorted((e for e in evaluations if e.point.regime == regime), key=lambda e: e.point.s)
        rows = []
        print(f"\n{regime}: s, window (s), M dedicate / swap / colocate, cheapest, extrapolated")
        for e in chosen:
            sized = sized_fleet(e, everything, design.slo_seconds)
            extrapolated = sum(sum(c.extrapolated) for cs in e.outcomes.values() for c in cs)
            row = {
                "s": e.point.s,
                "window": e.point.until - design.warmup,
                "sized": sized,
                "extrapolated_dispatches": extrapolated,
            }
            rows.append(row)
            cells = "not evaluable" if sized is None else " / ".join(
                "dominated" if sized[k] is None else str(sized[k]) for k in ("dedicate", "swap", "colocate")
            )
            print(f"  {e.point.s:<4} {row['window']:>8.0f}  {cells}  {extrapolated}")
        crossover = estimate_crossover(
            chosen, design.slo_seconds, iterations=CROSSOVER_ITERATIONS, seed=design.seed
        )
        skews = [e.point.s for e in chosen]
        located = [(skews[i], skews[j]) for i, j in crossover.point]
        interval = None if crossover.interval is None else tuple(skews[i] for i in crossover.interval)
        print(
            f"  crossover between s = {located or 'none in range'}; interval on its lower "
            f"grid point {interval}; draws: none {crossover.no_crossing}, one "
            f"{crossover.one_crossing}, several {crossover.many_crossings} of {crossover.iterations}"
        )
        for row in rows:
            sized = row["sized"]
            if sized and sized["dedicate"] is not None:
                cheaper = [m for m in sized.values() if m is not None]
                row["dedicate_over_cheapest_per_month"] = monthly_difference(
                    sized["dedicate"], min(cheaper), rate
                )
        summary["regimes"][regime] = {
            "rows": rows,
            "crossover": {
                "between": located,
                "interval_lower_point": interval,
                "no_crossing": crossover.no_crossing,
                "one_crossing": crossover.one_crossing,
                "many_crossings": crossover.many_crossings,
                "iterations": crossover.iterations,
            },
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a4-sweep")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--allow-unmeasured", action="store_true")
    args = ap.parse_args()
    from placement.placeholders import (
        PLACEHOLDER_DESIGN,
        PLACEHOLDER_ENGINES,
        PLACEHOLDER_RATE,
        PLACEHOLDER_SWAP_TIME,
    )

    run(
        PLACEHOLDER_DESIGN, PLACEHOLDER_ENGINES, PLACEHOLDER_SWAP_TIME, PLACEHOLDER_RATE,
        Path(args.out), args.workers, args.allow_unmeasured, args.refresh,
    )


if __name__ == "__main__":
    main()
