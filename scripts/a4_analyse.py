"""Reduce every measurement store, validate, run the sweep on measured inputs,
and write data/a4/analysis.json. Spends nothing.

    .venv/bin/python scripts/a4_analyse.py [--workers 4] [--refresh] \\
        [--cells data/a4/cells.jsonl ...] [--swaps ...] [--sleep ...] [--replay ...]

Every value the post, the figures and data/a4/cost_per_tenant.json publish
comes from the file this writes. It reads the registered values
(placement/registered.py), the stores, and artifact 1's store for figure 4's
reference. The sweep's evaluations are cached under build/a4-sweep, keyed by
every input, as scripts/a4_sweep.py caches them; the first run is hours of CPU.

Each `--cells` (and the other store flags) may be given more than once: a
top-up campaign has its own store and reduces together with the one it tops up.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import a4_sweep

from autoscale.traffic import saturation_rps
from harness.stats import median, percentiles
from placement.analysis import analyse
from placement.inputs import (
    cell_summary,
    colocated_surface,
    eviction_seconds,
    held_out_check,
    load_records,
    sleep_distribution,
    solo_curve,
    swap_distribution,
)
from placement.money import Assumptions
from placement.sim import Engines
from placement.stages import stage_medians
from placement.step2 import (
    CELL_MIN_VALID,
    HELD_OUT_TOLERANCE,
    REFERENCE,
    VALIDATION_S,
    SweepChoice,
    sweep_design,
)
from placement.validation import validate

REPO = Path(__file__).resolve().parents[1]
STORES = {"cells": ["data/a4/cells.jsonl"], "swaps": ["data/a4/swaps.jsonl"],
          "sleep": ["data/a4/sleep.jsonl"], "replay": ["data/a4/replay.jsonl"]}


def _summary(samples) -> dict:
    samples = sorted(samples)
    p = percentiles(samples, want=("p50", "p90")) if len(samples) >= 50 else {
        "p50": median(samples), "p90": None}
    return {"n": len(samples), "min": samples[0], "max": samples[-1], "p50": p["p50"],
            "p90": p["p90"], "samples": samples}


def registered_values() -> dict:
    from placement import registered

    return {k: getattr(registered, k) for k in dir(registered) if k.isupper()}


def analyse_all(reg: dict, stores: dict[str, list[str]], *, root: Path, a1_store: Path,
                sweep_out: Path, workers: int, refresh: bool = False) -> dict:
    cells = load_records([root / s for s in stores["cells"]])
    swaps = load_records([root / s for s in stores["swaps"]])
    replays = load_records([root / s for s in stores["replay"]])
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=reg["SOLO_LEVELS"], min_repeats=CELL_MIN_VALID, **warm)
    surface = colocated_surface(cells, own_levels=reg["OWN_LEVELS"],
                                neighbour_levels=reg["NEIGHBOUR_LEVELS"],
                                min_repeats=CELL_MIN_VALID, **warm)
    engines = Engines(solo=solo, colocated=surface)
    cold = reg["EVICTION_WORKS"]
    swap_time = swap_distribution(swaps, cold=cold, compiled=False)
    swap_median = median(list(swap_time.samples))
    design = sweep_design(SweepChoice(reg["OFFERED_GPUS"], reg["SLO_SWAP_MULTIPLE"]), swap_median)
    rate = Assumptions(gpu_hourly_rate=reg["GPU_HOURLY_RATE"], provenance=reg["RATE_PROVENANCE"])
    total_rate = design.offered_gpus * saturation_rps(solo)

    evaluations = a4_sweep.evaluations_for(design, engines, swap_time, sweep_out, workers, refresh)
    result = analyse(evaluations, design, total_rate=total_rate, output_len=reg["OUTPUT_LEN"],
                     rate=rate, reference=REFERENCE)

    from placement.a1_reference import stage_medians as a1_stage_medians

    swap_strata = {}
    for state in ((True, False) if cold else (False,)):
        for compiled in (False, True):
            try:
                d = swap_distribution(swaps, cold=state, compiled=compiled)
            except ValueError:
                continue
            swap_strata[f"{'cold' if state else 'warm'}_{'compiled' if compiled else 'hit'}"] = (
                _summary(d.samples))
    sleep = None
    if reg["SLEEP_MEASURED"]:
        sleep = _summary(sleep_distribution(load_records([root / s for s in stores["sleep"]])).samples)
    summary = cell_summary(cells, **warm)
    result["inputs"] = {
        "model": reg["MODEL"],
        "request_shape": {"input_len": reg["INPUT_LEN"], "output_len": reg["OUTPUT_LEN"]},
        "kv": {"split_tokens": reg["KV_SPLIT_TOKENS"], "split_ceiling": reg["SPLIT_CEILING"],
               "solo_tokens": reg["KV_SOLO_TOKENS"], "solo_ceiling": reg["SOLO_CEILING"]},
        "solo_curve": [list(p) for p in solo.points],
        "saturation_rps": saturation_rps(solo),
        # The registered levels, which are the surface's grid: ints, so a
        # reader can name the cell they come from ("pair:o8:n16").
        "surface": {"own": list(reg["OWN_LEVELS"]), "neighbour": list(reg["NEIGHBOUR_LEVELS"]),
                    "latency": [list(row) for row in surface.latency]},
        "cells": summary,
        "swaps": {"simulated": {"cold": cold, "compiled": False, **_summary(swap_time.samples)},
                  "strata": swap_strata},
        "sleep_mode": sleep,
        "stages": stage_medians(swaps, cold=cold),
        "a1_reference": a1_stage_medians(a1_store),
    }
    result["held_out"] = held_out_check(cells, surface, reg["HELD_OUT"],
                                        tolerance=HELD_OUT_TOLERANCE,
                                        min_repeats=CELL_MIN_VALID, **warm)
    replay_swap_s = swap_median + eviction_seconds(swaps, cold=cold)
    try:
        verdict = validate(replays, engines, replay_swap_s)
    except ValueError as e:
        # Too few ok replays, or replays of different traces: the gate could
        # not be run, which is itself the result to publish. Raising here
        # would also withhold the sweep, the cost file and the figures.
        verdict = {"outcome": "refused", "detail": str(e), "swap_median_s": replay_swap_s}
    result["validation"] = {
        **verdict,
        # Where figure 1 marks the validated operating point (August §9).
        "point": {"regime": "bursty", "s": VALIDATION_S, "models": 3, "gpus": 1},
    }
    return result


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in STORES:
        ap.add_argument(f"--{name}", action="append")
    ap.add_argument("--out", default="data/a4/analysis.json")
    ap.add_argument("--sweep-out", default="build/a4-sweep")
    ap.add_argument("--a1-store", default="data/campaign.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    stores = {name: getattr(args, name) or default for name, default in STORES.items()}
    result = analyse_all(registered_values(), stores, root=REPO, a1_store=REPO / args.a1_store,
                         sweep_out=REPO / args.sweep_out, workers=args.workers,
                         refresh=args.refresh)
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {args.out}: validation {result['validation']['outcome']}, held-out "
          f"{[c['passed'] for c in result['held_out']]}")
    for regime, r in result["regimes"].items():
        print(f"  {regime}: decision rule {r['decision_rule']}; crossover {r['crossover']['between']}")
    return result


if __name__ == "__main__":
    main()
