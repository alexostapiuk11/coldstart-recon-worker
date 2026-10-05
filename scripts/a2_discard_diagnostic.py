"""Why the measured curve's sweep loses its queue-depth runs: per policy, per run.

The first full sweep on the measured curve was refused at the H3 gap: on arm
A's step, 3 of 8 frontier points kept fewer than 20 of 30 repetitions, and the
discard counts were almost all `queue_depth/replica_never_served`. Those
counts are per signal; they cannot say WHICH policies lost runs, whether the
queue ever reached their thresholds, or how late the scale-up came. This
script answers those three, for one sweep, so the owner decides any amendment
from evidence rather than from a total.

It replays the sweep's own loop -- same seed derivation, same traces, same
controller constants, same exclusion order -- with a controller that records
what it was shown. Rejected: an observer hook in `run_sweep`, which would put
a diagnostic seam in the code that produces the published numbers.
tests/test_a2_discard_diagnostic.py pins the replay to `run_sweep` run for
run, so the two cannot drift apart unnoticed.

Free: CPU only, no network. One sweep of all three signals on the measured
curve is roughly 20-30 minutes. It changes nothing and amends nothing.
"""

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale import sweep
from autoscale.arrivals import arrival_times
from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags
from autoscale.controller import Controller, Decision
from autoscale.frontier import PolicyPoint, pareto_frontier
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.service import ServiceCurve
from autoscale.sim import run_with_policy
from autoscale.stats import MIN_BOOTSTRAP_SAMPLES, MIN_SAMPLES
from autoscale.thresholds import SENSITIVITY_THRESHOLDS, THRESHOLDS
from autoscale.traffic import spike_shape

SEED = 17  # scripts/a2_render_figures.py's
UNTIL = 400.0


@dataclass
class RecordingController(Controller):
    """A `Controller` that remembers what it was shown and when it first acted.

    Deciding is untouched: `decide` defers to the parent, so the run is the
    sweep's run. Only finite readings count toward `max_signal`; the counting
    signals read +inf when nothing is serving, which is not a load.
    """

    first_up_at: float | None = field(default=None, repr=False)
    first_cross_at: float | None = field(default=None, repr=False)
    max_signal: float = field(default=0.0, repr=False)
    evaluations: int = field(default=0, repr=False)
    at_or_above_up: int = field(default=0, repr=False)

    def decide(self, signal_value: float, replicas: int, now: float) -> Decision:
        decision = super().decide(signal_value, replicas, now)
        self.evaluations += 1
        if signal_value != float("inf"):
            self.max_signal = max(self.max_signal, signal_value)
        if signal_value >= self.scale_up_at:
            self.at_or_above_up += 1
            if self.first_cross_at is None:
                self.first_cross_at = now
        if decision is Decision.UP and self.first_up_at is None:
            self.first_up_at = now
        return decision


def replay(shape, lags: LagDistribution, curve: ServiceCurve, signals, *, seed=SEED,
           until=UNTIL) -> list[dict]:
    """One row per run, in `run_sweep`'s order, with its outcome and what the
    controller saw. `outcome` is "kept" or the discard reason `run_sweep`
    would record for it."""
    grids = {**THRESHOLDS, **SENSITIVITY_THRESHOLDS}
    rows = []
    for signal in signals:
        up_grid, down_grid = grids[signal]
        for up in up_grid:
            for down in down_grid:
                if down >= up:
                    continue
                for rep in range(sweep.REPETITIONS):
                    rng = random.Random(sweep._derive_seed(seed, up, down, rep))
                    arrivals = arrival_times(shape, until=until, rng=rng)
                    row = {"signal": signal, "up": up, "down": down, "rep": rep}
                    if not arrivals:
                        rows.append({**row, "outcome": "empty_trace"})
                        continue
                    ctl = RecordingController(
                        scale_up_at=up, scale_down_at=down,
                        cooldown=sweep.COOLDOWN_SECONDS, max_replicas=sweep.MAX_REPLICAS,
                    )
                    result = run_with_policy(
                        arrivals=arrivals, signal=signal, controller=ctl, lags=lags,
                        curve=curve, until=until,
                        evaluate_every=sweep.EVALUATE_EVERY_SECONDS, rng=rng,
                    )
                    if result.discard_reason:
                        outcome = result.discard_reason
                    elif len(result.latencies) < MIN_SAMPLES["p99"]:
                        outcome = "insufficient_completions"
                    else:
                        outcome = "kept"
                    rows.append({
                        **row,
                        "outcome": outcome,
                        "cost": result.replica_seconds,
                        "p99": result.percentiles()["p99"] if outcome == "kept" else None,
                        "scale_ups": result.scale_up_events,
                        "scale_downs": result.scale_down_events,
                        "peak_replicas": result.peak_replicas,
                        "peak_serving": result.peak_serving_replicas,
                        "first_up_at": ctl.first_up_at,
                        "first_cross_at": ctl.first_cross_at,
                        "max_signal": ctl.max_signal,
                        "share_at_or_above_up": ctl.at_or_above_up / max(ctl.evaluations, 1),
                    })
    return rows


def policy_points(rows) -> list[PolicyPoint]:
    """The `PolicyPoint`s `run_sweep` would return for these rows."""
    by_policy: dict[tuple, list[dict]] = {}
    for r in rows:
        by_policy.setdefault((r["signal"], r["up"], r["down"]), []).append(r)
    points = []
    for (signal, up, down), runs in by_policy.items():
        kept = [r for r in runs if r["outcome"] == "kept"]
        if kept:
            points.append(PolicyPoint(
                cost_samples=tuple(r["cost"] for r in kept),
                p99_samples=tuple(r["p99"] for r in kept),
                signal=signal, scale_up_at=up, scale_down_at=down,
                rep_indices=tuple(r["rep"] for r in kept),
            ))
    return points


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def summarize(rows) -> list[dict]:
    """Per policy: how many runs survived, why the rest did not, and medians
    of what the controller saw on the runs that scaled."""
    by_policy: dict[tuple, list[dict]] = {}
    for r in rows:
        by_policy.setdefault((r["signal"], r["up"], r["down"]), []).append(r)
    table = []
    for (signal, up, down), runs in by_policy.items():
        outcomes = Counter(r["outcome"] for r in runs)
        scaled = [r for r in runs if r.get("scale_ups")]
        table.append({
            "signal": signal, "up": up, "down": down, "runs": len(runs),
            "kept": outcomes.get("kept", 0),
            "outcomes": dict(sorted(outcomes.items())),
            "median_max_signal": _median([r.get("max_signal") for r in runs]),
            "median_share_at_or_above_up": _median(
                [r.get("share_at_or_above_up") for r in runs]),
            "median_first_up_at": _median([r.get("first_up_at") for r in scaled]),
            "median_peak_serving": _median([r.get("peak_serving") for r in runs]),
        })
    return table


def frontier_report(points) -> list[dict]:
    """Each signal's frontier, with the repetitions behind each point and
    whether it is below the floor `gap_interval` refuses at."""
    out = []
    for signal in sorted({p.signal for p in points}):
        for p in pareto_frontier([q for q in points if q.signal == signal]):
            out.append({"signal": signal, "up": p.scale_up_at, "down": p.scale_down_at,
                        "n": p.n, "cost": p.cost, "p99": p.p99,
                        "below_floor": p.n < MIN_BOOTSTRAP_SAMPLES})
    return out


def littles_law_in_flight(curve: ServiceCurve, rate: float, iterations: int = 200) -> float:
    """Requests in flight on ONE replica at `rate`, by L = rate x latency(L).

    An estimate for the report, not a simulator input: it says whether a single
    replica is expected to fill its slots (and so queue) at that rate. Iterated
    from the curve's cap down, clamped there; if it settles at the cap, the
    replica is saturated and requests queue.
    """
    cap = curve.max_measured_concurrency
    level = cap
    for _ in range(iterations):
        level = min(cap, rate * curve.latency_at(max(level, 1.0)))
    return level


def _fmt(v, spec=".2f"):
    return "-" if v is None else format(v, spec)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--arm", default="A", choices=("A", "C"))
    ap.add_argument("--kind", default="step", choices=("step", "ramp"))
    ap.add_argument("--signals", nargs="+", default=sorted(THRESHOLDS))
    ap.add_argument("--out", default=None,
                    help="JSON report path (default build/a2-diagnostic/arm-<A|C>-<kind>.json)")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--curve", default=None, help=f"the measured curve (default {DEFAULT_PATH})")
    which.add_argument("--placeholder", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    path = None if args.placeholder else (args.curve or DEFAULT_PATH)
    curve, _ = select_curve(path, placeholder=args.placeholder)
    shape = spike_shape(curve, kind=args.kind)
    lags = load_measured_lags(args.store)[args.arm]
    peak = shape.baseline_rate * shape.k

    q = statistics.quantiles(lags.samples, n=10)
    print(f"curve: {'placeholder' if path is None else path}; arm {args.arm}, {args.kind} spike")
    print(f"rates: baseline {shape.baseline_rate:.1f} rps, peak {peak:.1f} rps; "
          f"per-replica cap {curve.max_measured_concurrency:g} in flight")
    for name, rate in (("baseline", shape.baseline_rate), ("peak", peak)):
        print(f"  Little's-law in flight on one replica at {name}: "
              f"{littles_law_in_flight(curve, rate):.1f}")
    print(f"arm {args.arm} cold-start lag: p10 {q[0]:.1f} s, median "
          f"{statistics.median(lags.samples):.1f} s, p90 {q[-1]:.1f} s "
          f"({len(lags.samples)} samples); window {UNTIL:g} s")

    rows = replay(shape, lags, curve, args.signals)
    table = summarize(rows)
    frontier = frontier_report(policy_points(rows))

    print("\nper policy (medians over runs; first UP over runs that scaled):")
    print(f"{'signal':<22} {'up':>5} {'down':>5} {'kept':>5}  {'max sig':>8} "
          f"{'>=up':>6} {'1st UP s':>8} {'serving':>7}  outcomes")
    for t in table:
        print(f"{t['signal']:<22} {t['up']:>5g} {t['down']:>5g} {t['kept']:>2}/{t['runs']:<2}  "
              f"{_fmt(t['median_max_signal']):>8} {_fmt(t['median_share_at_or_above_up']):>6} "
              f"{_fmt(t['median_first_up_at'], '.0f'):>8} "
              f"{_fmt(t['median_peak_serving'], '.0f'):>7}  {t['outcomes']}")
    print(f"\nfrontiers (floor {MIN_BOOTSTRAP_SAMPLES} repetitions):")
    for f in frontier:
        flag = "  BELOW FLOOR" if f["below_floor"] else ""
        print(f"  {f['signal']:<22} up {f['up']:g} down {f['down']:g}: n={f['n']}, "
              f"cost {f['cost']:.0f}, p99 {f['p99']:.3f}s{flag}")

    out = Path(args.out or f"build/a2-diagnostic/arm-{args.arm}-{args.kind}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "curve": "placeholder" if path is None else str(path), "arm": args.arm,
        "kind": args.kind, "seed": SEED, "until": UNTIL,
        "baseline_rps": shape.baseline_rate, "peak_rps": peak,
        "policies": table, "frontier": frontier, "runs": rows,
    }, indent=1))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
