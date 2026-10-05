"""Measure H3's iso-cost gap against its own noise floor.

The question is not "what is the gap" but "is the gap larger than the noise it
is made of". The sweep's own repetitions cannot answer that: they are averaged
into each policy's estimate, so the gap that comes out the far end has no
uncertainty attached to it. This runs the whole step sweep at K independent
MASTER seeds instead, giving K independent estimates of one quantity. If their
spread is comparable to the gap itself, a single sweep's number is a draw, not
a measurement.

Result, 2026-09-17, arm A, step, PLACEHOLDER service curve, 10 master seeds x
30 repetitions:

    gap = 0.314 s, sd 0.247, range 0.039 to 0.864

The draft reported 0.44 s, which sits inside that range. And the true gap under
this curve is exactly ZERO: on one fixed arrival trace all 55 policies in the
grid deliver an identical p99 to nine decimal places (85.173819876 s) while
producing 8 distinct costs. The whole of the measured 0.314 s is therefore
traffic noise around a true zero.

See docs/findings-a2-degenerate-regime.md for why the true gap is zero -- it is
not a property of the placeholder curve, and a measured curve will not fix it.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from a2_render_figures import UNTIL, _by_signal

import autoscale.sweep as sweep_mod
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.frontier import pareto_frontier
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.sweep import SweepConfig, run_sweep
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,
    BASELINE_FRACTION_OF_SATURATION,
    spike_shape,
)

# Coprime-ish stride so the master seeds are not near neighbours; the seeds
# themselves are arbitrary but FIXED, so this script reproduces.
SEED_BASE = 1000
SEED_STRIDE = 7919


def _p99_at(frontier, cost):
    """The best p99 at or below `cost`, or None if nothing is affordable.

    Returns None rather than raising, unlike `frontier._p99_at_cost`: this is a
    diagnostic sweeping many seeds, and one seed whose frontier cannot reach
    the budget is a data point about that seed, not a reason to abandon the
    other nine.
    """
    affordable = [p for p in frontier if p.cost <= cost]
    return min(p.p99 for p in affordable) if affordable else None


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--reps", type=int, default=30)
    ap.add_argument("--arm", default="A")
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/a2-gap-noise-floor.json")
    # Candidate regimes from scripts/a2_regime_probe.py. Defaulting to the
    # pre-registered values means the no-flag invocation measures what the
    # artifact currently claims; passing them measures a candidate BEFORE the
    # pre-registration is amended to adopt it, which is the order that keeps
    # the amendment a disclosure rather than a result-driven edit.
    ap.add_argument("--baseline-fraction", type=float, default=None)
    ap.add_argument("--additional-replicas", type=float, default=None)
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--curve", default=None,
                       help=f"the measured curve (default {DEFAULT_PATH})")
    which.add_argument("--placeholder", action="store_true",
                       help="run against the invented placeholder curve")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    curve, _ = select_curve(
        None if args.placeholder else (args.curve or DEFAULT_PATH),
        placeholder=args.placeholder,
    )

    # Reaching into the module rather than passing a parameter: REPETITIONS is
    # pre-registered at 30 and `run_sweep` rightly takes no override. Lowering
    # it here is a diagnostic convenience and must stay visible as one.
    if args.reps != sweep_mod.REPETITIONS:
        print(f"NOTE: repetitions lowered to {args.reps} from the pre-registered 30")
    sweep_mod.REPETITIONS = args.reps

    if args.baseline_fraction is not None or args.additional_replicas is not None:
        fraction = (
            args.baseline_fraction
            if args.baseline_fraction is not None
            else BASELINE_FRACTION_OF_SATURATION
        )
        additional = (
            args.additional_replicas
            if args.additional_replicas is not None
            else ADDITIONAL_REPLICAS_AT_PEAK
        )
        shape = spike_shape(
            curve,
            "step",
            baseline_fraction=fraction,
            additional_replicas=additional,
        )
        print(
            f"NOT the pre-registered traffic model: baseline={fraction:.0%} of "
            f"saturation, {additional} additional replicas at peak "
            f"(peak/saturation={fraction + additional:.2f})"
        )
    else:
        shape = spike_shape(curve, "step")

    lags = load_measured_lags(args.store)[args.arm]
    print(
        f"arm {args.arm}: {args.seeds} master seeds x {args.reps} reps, "
        f"baseline={shape.baseline_rate:.1f} rps k={shape.k:.1f} "
        + ("-- PLACEHOLDER service curve" if not curve.measured else "-- measured service curve")
    )

    rows = []
    for i in range(args.seeds):
        seed = SEED_BASE + SEED_STRIDE * i
        points, discards = run_sweep(
            SweepConfig(
                shape=shape,
                lags=lags,
                curve=curve,
                arm=args.arm,
                until=UNTIL,
            ),
            seed=seed,
            allow_unmeasured=not curve.measured,
        )
        frontiers = {s: pareto_frontier(ps) for s, ps in _by_signal(points).items()}
        budget = min(p.cost for p in points) * 2
        per_signal = {s: _p99_at(f, budget) for s, f in frontiers.items()}
        scored = {s: v for s, v in per_signal.items() if v is not None}
        gap = (max(scored.values()) - min(scored.values())) if len(scored) > 1 else None
        rows.append(
            {
                "seed": seed,
                "budget": budget,
                "per_signal": per_signal,
                "gap": gap,
                "n_signals": len(scored),
                "discards": len(discards),
            }
        )
        shown = {k: (round(v, 4) if v is not None else None) for k, v in per_signal.items()}
        print(f"  seed={seed} gap={gap!r} per_signal={shown}")

    gaps = [r["gap"] for r in rows if r["gap"] is not None]
    summary: dict[str, float] = {"n": len(gaps)}
    if len(gaps) > 1:
        summary |= {
            "mean": statistics.fmean(gaps),
            "min": min(gaps),
            "max": max(gaps),
            "stdev": statistics.stdev(gaps),
        }
        summary["sem"] = summary["stdev"] / len(gaps) ** 0.5
    print("\nSUMMARY", json.dumps(summary, indent=1))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
