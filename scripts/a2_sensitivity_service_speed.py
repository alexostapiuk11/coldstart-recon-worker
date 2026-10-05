"""EXPLORATORY: does H3's answer survive the service-speed error the validation found?

Not pre-registered, and run after both validation attempts failed: the first
found the simulator predicting the engine about 12% too slow, the second, after
host calibration, about 12% too fast (docs/findings-a2-validation-host-speed.md,
data/a2/validation-*/verdict.json). Its output is reported as a sensitivity
check on an unvalidated simulator, never as a validated result.

What changes is the ENGINE only. The traffic -- the spike's absolute rates --
stays the committed curve's (`traffic.spike_shape` of the committed curve), and
each sweep's service curve is the committed curve with every latency multiplied
by a factor: 0.88 (the engine 12% faster) and 1.12 (12% slower). Rejected:
rendering the figures against a scaled curve file, which would rescale the
traffic with it -- the spike is defined relative to the curve's saturation --
and keep the overload at exactly 1.2x, hiding the very effect under test.

Everything else is the headline's: the four sweeps (arm A and C, step and
ramp), seed 17, 30 repetitions, the grids, the gap's bootstrap interval and
`h3_verdict`. Sweeps run four at a time and are checkpointed per factor.
Free: CPU only.
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import a2_render_figures as render

from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.frontier import gap_interval, h3_verdict, pareto_frontier
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.sweep import SweepConfig, run_sweep
from autoscale.traffic import spike_shape
from autoscale.validation import host_scaled_curve

FACTORS = (0.88, 1.12)
HEADLINE = (("arm A", "A", "step", "A"), ("arm C", "C", "step", "C"),
            ("ramp arm A", "A", "ramp", "ramp-A"), ("ramp arm C", "C", "ramp", "ramp-C"))


def configs(committed, factor: float):
    """(tag, shape, service curve, arm, label) per headline sweep: the shape from the
    COMMITTED curve, the service from the scaled one."""
    service = host_scaled_curve(committed, (factor, factor))
    return [(tag, spike_shape(committed, kind=kind), service, arm, label)
            for tag, arm, kind, label in HEADLINE]


def run_task(task):
    factor, _tag, kind, arm, label, curve_path, store = task
    committed, _ = select_curve(curve_path, placeholder=False)
    shape = spike_shape(committed, kind=kind)
    service = host_scaled_curve(committed, (factor, factor))
    lags = load_measured_lags(store)[arm]
    return run_sweep(SweepConfig(shape=shape, lags=lags, curve=service, arm=label,
                                 until=render.UNTIL), seed=render.SEED)


def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--curve", default=str(DEFAULT_PATH))
    ap.add_argument("--out", default="build/a2-sensitivity-service-speed")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print("EXPLORATORY sensitivity check: traffic from the committed curve, engine latency "
          f"x{FACTORS}. Not pre-registered; an unvalidated simulator.")

    checkpoints = {f: render.SweepCheckpoint(
        out / f"x{f:g}.json",
        {**render.sweep_identity(args.curve, args.store), "service_factor": f})
        for f in FACTORS}
    tasks = {}
    for f in FACTORS:
        for tag, arm, kind, label in HEADLINE:
            if checkpoints[f].get(tag) is None:
                tasks[(f, tag)] = (f, tag, kind, arm, label, args.curve, args.store)
    if tasks:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_task, t): key for key, t in tasks.items()}
            for fut in as_completed(futures):
                f, tag = futures[fut]
                points, discards = fut.result()
                checkpoints[f].put(tag, points, discards)
                print(f"  x{f:g} {tag}: {len(points)} policy points, {len(discards)} discards")

    results = {}
    for f in FACTORS:
        gaps = {}
        for tag, *_ in HEADLINE:
            points, discards = checkpoints[f].get(tag)
            per_signal = {s: pareto_frontier(ps) for s, ps in render._by_signal(points).items()}
            try:
                gaps[tag] = gap_interval(per_signal, iterations=render.GAP_BOOTSTRAP_ITERATIONS,
                                         seed=render.SEED)
            except ValueError as exc:
                gaps[tag] = {"refused": exc.args[0].split(";")[0]}
            g = gaps[tag]
            frontier = {s: [(round(p.cost), round(p.p99, 3), p.n) for p in fr]
                        for s, fr in sorted(per_signal.items())}
            gaps[tag]["frontiers"] = frontier
            gaps[tag]["discards"] = len(discards)
            line = (f"gap={g['point']:.4f}s [{g['lo']:.4f}, {g['hi']:.4f}]"
                    if "point" in g else f"REFUSED ({g['refused']})")
            print(f"x{f:g} {tag}: {line}; {len(discards)} discards; frontiers {frontier}")
        verdict = None
        if all("point" in gaps[t] for t, *_ in HEADLINE):
            v = h3_verdict(
                step_gap_a=gaps["arm A"]["point"], step_gap_c=gaps["arm C"]["point"],
                ramp_gap_a=gaps["ramp arm A"]["point"], ramp_gap_c=gaps["ramp arm C"]["point"],
                step_gap_a_interval=(gaps["arm A"]["lo"], gaps["arm A"]["hi"]),
                ramp_gap_a_interval=(gaps["ramp arm A"]["lo"], gaps["ramp arm A"]["hi"]))
            verdict = {"holds": v.holds, "partial": v.partial, "evaluable": v.evaluable,
                       "detail": v.detail}
            print(f"x{f:g} H3: holds={v.holds} partial={v.partial} evaluable={v.evaluable}: "
                  f"{v.detail}")
        results[f"{f:g}"] = {"gaps": gaps, "h3": verdict}
    (out / "results.json").write_text(json.dumps(results, indent=1))
    print(f"wrote {out / 'results.json'}")


if __name__ == "__main__":
    main()
