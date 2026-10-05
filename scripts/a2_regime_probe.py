"""Find an operating regime where the autoscaling signal actually matters.

docs/findings-a2-degenerate-regime.md establishes that under the pre-registered
traffic model all 55 policies in the grid deliver an IDENTICAL p99 on any fixed
arrival trace: the peak is 3.4x one replica's saturation, so every signal is
past every threshold in its own grid from the first evaluation onward, and
three saturated signals carry the same zero information. H1, H2 and H3 are
unevaluable there -- not because the effect is small, but because it is exactly
zero by construction.

This probe asks whether a regime exists in which it is NOT zero, before any
pre-registered quantity is amended to reach for one. Amending first and
measuring afterwards would be choosing the traffic model to produce a result,
which is precisely what the pre-registration exists to prevent. Measuring first
and disclosing the search is not: what comes out of this is a statement about
where the comparison is defined at all, and it is made against ONE fixed trace
per configuration with no reference to which signal wins.

The metric is deliberately blind to the ranking: `distinct_p99` counts how many
different p99 values the 55 policies produce, and `p99_spread` is the range.
Neither can be read as "signal X is better", so tuning toward a large spread
cannot smuggle in a preferred winner -- it can only find a regime where the
signals are distinguishable from each other at all.

TWO STAGES, and the second exists because the first misled once already.

Stage 1 (`--stage screen`) is the one-trace screen described above. Its `kept`
column counts policies surviving the pre-registered exclusion rules ON THAT ONE
TRACE, with one fixed lag draw -- and that is NOT how many survive a real
sweep, which draws a fresh trace per repetition. Read as though it were, it
recommended baseline=40%/0.5 additional replicas on a `kept` of 55/55; real
sweeps there give `queue_depth` only 2.7 surviving policies out of 19, so its
"frontier" is three points against nineteen for the other two and part of the
apparent gap is just that mismatch. The screen is a screen: it answers "can
these signals differ at all", and nothing else.

Stage 2 (`--stage verify`) re-runs the separating candidates through `run_sweep`
itself -- real repetitions, fresh traces -- and reports SURVIVING POLICIES PER
SIGNAL alongside the gap. A candidate that starves one signal's grid is
disqualified there no matter how wide its one-trace spread looked.
"""

import argparse
import itertools
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from a2_render_figures import UNTIL

import autoscale.sweep as sweep_mod
from autoscale.arrivals import arrival_times
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.controller import Controller
from autoscale.frontier import pareto_frontier
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.signals import SIGNALS
from autoscale.sim import run_with_policy
from autoscale.sweep import (
    COOLDOWN_SECONDS,
    EVALUATE_EVERY_SECONDS,
    THRESHOLDS,
    SweepConfig,
    run_sweep,
)
from autoscale.traffic import SUSTAIN_SECONDS, saturation_rps, spike_shape

# Set by `main` from --curve / --placeholder. Module-level, not threaded through
# `_probe` and `_verify`, so those keep the signatures this script's header
# documents; the placeholder is only the value before `main` has chosen.
CURVE = SERVICE_CURVE_PLACEHOLDER

TRACE_SEED = 12345  # one fixed trace per configuration, so policies are paired
LAG_SEED = 999

# The pre-registered values, as the origin of the search.
PREREG_BASELINE_FRACTION = 0.40
PREREG_ADDITIONAL_REPLICAS = 3
PREREG_MAX_REPLICAS = 12

# Fixed so stage 2 reproduces; arbitrary otherwise.
VERIFY_SEEDS = (5, 17, 42)


def _probe(baseline_fraction, additional_replicas, max_replicas, lags, sustain):
    """Run every policy in the grid against ONE arrival trace.

    One trace, not 30 repetitions: the question here is whether the policies
    differ from EACH OTHER, which is a paired comparison that needs no
    replication. Averaging over repetitions would only add the traffic noise
    that docs/findings-a2-degenerate-regime.md shows swamping the signal.
    """
    shape = spike_shape(
        CURVE,
        "step",
        sustain=sustain,
        baseline_fraction=baseline_fraction,
        additional_replicas=additional_replicas,
    )
    saturation = saturation_rps(CURVE)
    baseline = shape.baseline_rate
    # Reported, not used to build anything: the probe prints and stores the
    # peak it searched. Recomputing it as baseline x k can differ in the last
    # bit, which would break byte parity for a label.
    peak = baseline + additional_replicas * saturation
    arrivals = arrival_times(shape, until=UNTIL, rng=random.Random(TRACE_SEED))
    if not arrivals:
        return None

    p99s, costs, ups, discards = [], [], [], 0
    for signal in sorted(SIGNALS):
        up_grid, down_grid = THRESHOLDS[signal]
        for up, down in itertools.product(up_grid, down_grid):
            if down >= up:
                continue
            result = run_with_policy(
                arrivals=arrivals,
                signal=signal,
                controller=Controller(
                    scale_up_at=up,
                    scale_down_at=down,
                    cooldown=COOLDOWN_SECONDS,
                    max_replicas=max_replicas,
                ),
                lags=lags,
                curve=CURVE,
                until=UNTIL,
                evaluate_every=EVALUATE_EVERY_SECONDS,
                rng=random.Random(LAG_SEED),
            )
            if result.discard_reason:
                discards += 1
                continue
            p99s.append(result.percentiles()["p99"])
            costs.append(result.replica_seconds)
            ups.append(result.scale_up_events)

    if not p99s:
        return None
    rounded = {round(v, 9) for v in p99s}
    return {
        "baseline_fraction": baseline_fraction,
        "additional_replicas": additional_replicas,
        "max_replicas": max_replicas,
        "sustain": sustain,
        "baseline_rps": baseline,
        "peak_rps": peak,
        "peak_over_saturation": peak / saturation,
        "arrivals": len(arrivals),
        "kept": len(p99s),
        "discarded": discards,
        "distinct_p99": len(rounded),
        "p99_spread": max(p99s) - min(p99s),
        "p99_min": min(p99s),
        "p99_max": max(p99s),
        "cost_spread": max(costs) - min(costs),
        # The cap binds when some policy reached it. A regime where every
        # policy is pinned at the ceiling is degenerate for the same reason a
        # saturated signal is: the controller's decision stopped mattering.
        "hit_cap": sum(1 for u in ups if u >= max_replicas - 1),
    }


def _verify(baseline_fraction, additional_replicas, lags, sustain, reps, seeds):
    """Re-run a candidate through `run_sweep` itself: real repetitions, a fresh
    arrival trace per repetition, the whole exclusion machinery.

    The column that matters here is SURVIVING POLICIES PER SIGNAL. Stage 1's
    `kept` counts what lived through one trace, and a candidate can look like
    it keeps all 55 there while starving a signal's grid across real draws --
    which is exactly what baseline=40%/0.5 did to `queue_depth` (2.7 of 19).
    Comparing a three-point frontier against a nineteen-point one is not the
    comparison this artifact claims to make, however wide the resulting gap.
    """
    shape = spike_shape(
        CURVE,
        "step",
        sustain=sustain,
        baseline_fraction=baseline_fraction,
        additional_replicas=additional_replicas,
    )
    saturation = saturation_rps(CURVE)
    baseline = shape.baseline_rate
    # Reported, not used to build anything: the probe prints and stores the
    # peak it searched. Recomputing it as baseline x k can differ in the last
    # bit, which would break byte parity for a label.
    peak = baseline + additional_replicas * saturation
    sweep_mod.REPETITIONS = reps

    per_signal_counts = {s: [] for s in SIGNALS}
    gaps = []
    for seed in seeds:
        points, _ = run_sweep(
            SweepConfig(shape=shape, lags=lags, curve=CURVE, arm="A", until=UNTIL),
            seed=seed,
            allow_unmeasured=not CURVE.measured,
        )
        by = {}
        for p in points:
            by.setdefault(p.signal, []).append(p)
        for s in SIGNALS:
            per_signal_counts[s].append(len(by.get(s, [])))
        if len(by) == len(SIGNALS):
            frontiers = {s: pareto_frontier(v) for s, v in by.items()}
            budget = max(min(p.cost for p in f) for f in frontiers.values())
            reached = {
                s: min(p.p99 for p in f if p.cost <= budget) for s, f in frontiers.items()
            }
            gaps.append(max(reached.values()) - min(reached.values()))

    return {
        "baseline_fraction": baseline_fraction,
        "additional_replicas": additional_replicas,
        "peak_over_saturation": peak / saturation,
        "policies_per_signal": {
            s: sum(v) / len(v) for s, v in per_signal_counts.items()
        },
        "complete_sweeps": len(gaps),
        "gap": sum(gaps) / len(gaps) if gaps else None,
    }


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--arm", default="A")
    ap.add_argument("--out", default="build/a2-regime-probe.json")
    ap.add_argument(
        "--stage",
        choices=("screen", "verify", "both"),
        default="both",
        help="screen = one trace per configuration; verify = real sweeps of the survivors",
    )
    ap.add_argument("--verify-reps", type=int, default=5)
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--curve", default=None,
                       help=f"the measured curve (default {DEFAULT_PATH})")
    which.add_argument("--placeholder", action="store_true",
                       help="run against the invented placeholder curve")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    global CURVE
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    CURVE, _ = select_curve(
        None if args.placeholder else (args.curve or DEFAULT_PATH),
        placeholder=args.placeholder,
    )

    lags = load_measured_lags(args.store)[args.arm]
    sustain = SUSTAIN_SECONDS  # pre-registered D, held fixed: measured, 2 x p95 arm A
    saturation = saturation_rps(CURVE)
    print(f"arm {args.arm}: saturation/replica={saturation:.1f} rps, sustain={sustain:g}s")
    which_curve = "PLACEHOLDER service curve." if not CURVE.measured else "Measured service curve."
    print(f"{which_curve} One fixed arrival trace per configuration.\n")
    print(
        f"{'base%':>6} {'addl':>5} {'cap':>4} {'peak/sat':>9} {'kept':>5} "
        f"{'distinct':>9} {'p99 spread':>11} {'p99 min':>9} {'cost spread':>12} {'capped':>7}"
    )

    rows = []
    if args.stage in ("screen", "both"):
        for baseline_fraction in (0.10, 0.20, 0.40, 0.70):
            for additional_replicas in (0.25, 0.5, 1, 2, 3):
                for max_replicas in (PREREG_MAX_REPLICAS, 24):
                    row = _probe(
                        baseline_fraction, additional_replicas, max_replicas, lags, sustain
                    )
                    if row is None:
                        continue
                    rows.append(row)
                    print(
                        f"{baseline_fraction:>6.2f} {additional_replicas:>5} {max_replicas:>4} "
                        f"{row['peak_over_saturation']:>9.2f} {row['kept']:>5} "
                        f"{row['distinct_p99']:>9} {row['p99_spread']:>11.4f} "
                        f"{row['p99_min']:>9.2f} {row['cost_spread']:>12.1f} {row['hit_cap']:>7}"
                    )

        usable = [r for r in rows if r["distinct_p99"] > 1]
        print(f"\n{len(usable)}/{len(rows)} configurations separate the policies on p99 at all.")
        if not usable:
            print(
                "NONE. Every configuration probed leaves the 55 policies delivering "
                "one p99, so the degeneracy is not reachable by these three knobs "
                "and the comparison needs a different change -- or the finding IS "
                "the result. See docs/findings-a2-degenerate-regime.md."
            )
        print(
            "\nNOTE: `kept` above is policies surviving ON ONE TRACE. It is NOT how "
            "many survive a real sweep, which draws a fresh trace per repetition. "
            "Stage 2 is what decides a candidate."
        )

    verified = []
    if args.stage in ("verify", "both"):
        print(
            f"\n--- stage 2: real sweeps, {args.verify_reps} repetitions x 3 seeds ---\n"
            f"{'base%':>6} {'addl':>5} {'peak/sat':>9} | "
            + " ".join(f"{s[:12]:>12}" for s in sorted(SIGNALS))
            + f" | {'gap':>7}"
        )
        # The candidates worth the CPU: everything the screen showed separating,
        # plus the pre-registered point as a control.
        candidates = (
            (0.40, 0.5),
            (0.40, 0.75),
            (0.20, 1.0),
            (0.10, 1.0),
            (0.70, 0.25),
            (0.70, 0.5),
            (0.40, 3),  # the pre-registered model, as the degenerate control
        )
        for baseline_fraction, additional_replicas in candidates:
            got = _verify(
                baseline_fraction,
                additional_replicas,
                lags,
                sustain,
                args.verify_reps,
                VERIFY_SEEDS,
            )
            verified.append(got)
            counts = " ".join(
                f"{got['policies_per_signal'][s]:>12.1f}" for s in sorted(SIGNALS)
            )
            gap = f"{got['gap']:>7.3f}" if got["gap"] is not None else f"{'--':>7}"
            print(
                f"{baseline_fraction:>6.2f} {additional_replicas:>5} "
                f"{got['peak_over_saturation']:>9.2f} | {counts} | {gap}"
            )
        print(
            "\nCounts are mean surviving policies per signal, out of 19/17/19 "
            "possible. A candidate that starves a signal's grid is disqualified "
            "however wide its gap: a three-point frontier against a nineteen-point "
            "one is not the comparison this artifact claims to make."
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"screen": rows, "verify": verified}, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
