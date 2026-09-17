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

from a2_render_figures import UNTIL, _saturation_rps

from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.controller import Controller
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as CURVE
from autoscale.signals import SIGNALS
from autoscale.sim import run_with_policy
from autoscale.sweep import COOLDOWN_SECONDS, EVALUATE_EVERY_SECONDS, THRESHOLDS

TRACE_SEED = 12345  # one fixed trace per configuration, so policies are paired
LAG_SEED = 999

# The pre-registered values, as the origin of the search.
PREREG_BASELINE_FRACTION = 0.40
PREREG_ADDITIONAL_REPLICAS = 3
PREREG_MAX_REPLICAS = 12


def _probe(baseline_fraction, additional_replicas, max_replicas, lags, sustain):
    """Run every policy in the grid against ONE arrival trace.

    One trace, not 30 repetitions: the question here is whether the policies
    differ from EACH OTHER, which is a paired comparison that needs no
    replication. Averaging over repetitions would only add the traffic noise
    that docs/findings-a2-degenerate-regime.md shows swamping the signal.
    """
    saturation = _saturation_rps(CURVE)
    baseline = baseline_fraction * saturation
    peak = baseline + additional_replicas * saturation
    shape = SpikeShape(
        kind="step", baseline_rate=baseline, k=peak / baseline, ramp=0.0, sustain=sustain
    )
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


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--arm", default="A")
    ap.add_argument("--out", default="build/a2-regime-probe.json")
    args = ap.parse_args()

    lags = load_measured_lags(args.store)[args.arm]
    sustain = 190.0  # pre-registered D, held fixed: it is measured (2 x p95 arm A)
    saturation = _saturation_rps(CURVE)
    print(f"arm {args.arm}: saturation/replica={saturation:.1f} rps, sustain={sustain:g}s")
    print("PLACEHOLDER service curve. One fixed arrival trace per configuration.\n")
    print(
        f"{'base%':>6} {'addl':>5} {'cap':>4} {'peak/sat':>9} {'kept':>5} "
        f"{'distinct':>9} {'p99 spread':>11} {'p99 min':>9} {'cost spread':>12} {'capped':>7}"
    )

    rows = []
    for baseline_fraction in (0.10, 0.20, 0.40, 0.70):
        for additional_replicas in (0.25, 0.5, 1, 2, 3):
            for max_replicas in (PREREG_MAX_REPLICAS, 24):
                row = _probe(baseline_fraction, additional_replicas, max_replicas, lags, sustain)
                if row is None:
                    continue
                rows.append(row)
                print(
                    f"{baseline_fraction:>6.2f} {additional_replicas:>5} {max_replicas:>4} "
                    f"{row['peak_over_saturation']:>9.2f} {row['kept']:>5} "
                    f"{row['distinct_p99']:>9} {row['p99_spread']:>11.4f} "
                    f"{row['p99_min']:>9.2f} {row['cost_spread']:>12.1f} {row['hit_cap']:>7}"
                )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1))

    usable = [r for r in rows if r["distinct_p99"] > 1 and r["kept"] >= 40]
    print(f"\n{len(usable)}/{len(rows)} configurations separate the policies on p99 at all.")
    if usable:
        best = max(usable, key=lambda r: r["p99_spread"])
        print(
            "widest separation: "
            f"baseline={best['baseline_fraction']:.0%} of saturation, "
            f"additional_replicas={best['additional_replicas']}, "
            f"max_replicas={best['max_replicas']} -> "
            f"{best['distinct_p99']} distinct p99 over {best['kept']} policies, "
            f"spread {best['p99_spread']:.3f}s on a p99 floor of {best['p99_min']:.2f}s"
        )
    else:
        print(
            "NONE. Every configuration probed leaves the 55 policies delivering "
            "one p99, so the degeneracy is not reachable by these three knobs "
            "and the comparison needs a different change -- or the finding IS "
            "the result. See docs/findings-a2-degenerate-regime.md."
        )
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
