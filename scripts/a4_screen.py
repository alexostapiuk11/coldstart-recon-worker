"""Run the ranking-blind regime screen and record its choice. Spends nothing.

    .venv/bin/python scripts/a4_screen.py [--report fixtures/a4/recon-report.json] \\
        [--out data/a4/screen.json] [--workers 4]

Reads reconnaissance's report, builds the provisional inputs the screen runs
on (the placeholder engines and reconnaissance's own swap times), and scores
every pre-registered candidate (`placement.screen`). Run it after the
reconnaissance record is committed and before `scripts/a4_step2.py`, which
reads its output. Minutes of CPU; it prints each offered load as it goes.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.traffic import saturation_rps
from harness.stats import median
from placement.evaluate import Scenario
from placement.grid import evaluate_grid, grid
from placement.placeholders import PLACEHOLDER_ENGINES
from placement.resample import EmpiricalDistribution
from placement.screen import run_screen
from placement.step2 import (
    SCREEN_REPETITIONS,
    SCREEN_SEED,
    SweepChoice,
    measurement_design,
    provisional_swap_samples,
    sweep_design,
)


def screen(report: dict, *, workers: int, engines=PLACEHOLDER_ENGINES) -> dict:
    measurement = measurement_design(report)
    samples = provisional_swap_samples(report, measurement)
    swap_time = EmpiricalDistribution(samples=samples, measured=False)
    swap_median = median(list(samples))

    def evaluate(offered: float):
        # The SLO multiple passed here is a placeholder: evaluation does not
        # read the SLO, and `run_screen` scores every multiple afterwards.
        design = sweep_design(SweepChoice(offered, 1.0), swap_median,
                              repetitions=SCREEN_REPETITIONS, seed=SCREEN_SEED,
                              preregistered=False)
        scenario = Scenario(
            n_models=design.n_models, offered_gpus=design.offered_gpus,
            saturation_rps=saturation_rps(engines.solo), hot_fraction=design.hot_fraction,
            warmup=design.warmup, mean_burst=design.mean_burst, duty=design.duty,
        )
        print(f"[screen] offered {offered} GPUs: evaluating {len(design.skews) * 2} points",
              flush=True)
        return evaluate_grid(grid(design, scenario), scenario, engines, swap_time,
                             design.repetitions, design.seed, None, workers)

    result = run_screen(evaluate, swap_median)
    result.pop("choice")
    result["provisional_inputs"] = {
        "engines": "placement.placeholders.PLACEHOLDER_ENGINES (invented; the screen only)",
        "swap_samples": list(samples),
        "simulated_swap": measurement["simulated_swap"],
    }
    return result


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", default="fixtures/a4/recon-report.json")
    ap.add_argument("--out", default="data/a4/screen.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    result = screen(json.loads(Path(args.report).read_text()), workers=args.workers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    for c in result["candidates"]:
        print(f"  offered {c['offered_gpus']}, SLO {c['slo_swap_multiple']} x swap "
              f"({c['slo_seconds']:.0f} s): {c['score']} of {c['evaluable']} evaluable points "
              "separate the strategies")
    print(f"chosen: {result['chosen']}")
    return result


if __name__ == "__main__":
    main()
