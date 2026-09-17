"""Render artifact 2's figures.

Against the PLACEHOLDER service curve until plan 2's hardware sweep runs --
the output is a draft for inspecting LAYOUT, not a result. Every number on
these axes is derived from invented service-curve points, which is why the
sweep has to be opted into with `allow_unmeasured=True` and why the script
says so on stdout before it draws anything.

The sweep behind these figures is ~25 minutes of CPU (30 repetitions of every
threshold combination, for each of seven lag distributions), so its output is
cached to JSON and re-used: iterating on a figure's layout must not cost half
an hour per look, or the looking does not happen. `--refresh` re-runs it.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags
from autoscale.figures import SIGNAL_ORDER, convergence, frontiers
from autoscale.frontier import (
    PolicyPoint,
    gap_interval,
    h3_verdict,
    pareto_frontier,
)
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.sweep import SweepConfig, run_sweep

SEED = 17
UNTIL = 400.0
SWEPT_LAGS = (20.0, 40.0, 60.0, 80.0, 120.0)
BASELINE_FRACTION_OF_SATURATION = 0.70  # docs/experiment-a2.md, amended 2026-09-17
ADDITIONAL_REPLICAS_AT_PEAK = 0.25  # docs/experiment-a2.md, amended 2026-09-17
RAMP_SECONDS = 95.0  # docs/experiment-a2.md, "Traffic model": R = D / 2
# 2000 draws is enough for 95% percentile endpoints (the 50th and 1950th
# order statistics) without the bootstrap dominating a sweep that is
# already minutes of CPU.
GAP_BOOTSTRAP_ITERATIONS = 2000


def _saturation_rps(curve) -> float:
    """Requests per second one replica sustains at its best operating point.

    The pre-registration fixes the traffic model as a RULE, not as two numbers:
    baseline is 40% of measured saturation and `k` is sized to require three
    additional replicas at the measured service rate, with "the two absolute
    rates computed from the service curve and committed before any policy sweep
    runs". So they are derived here from whichever curve is in hand rather than
    written as literals -- literals fixed against one curve silently stop
    implementing the rule the moment the curve is replaced, which is precisely
    what plan 2 is going to do. The plan's own draft of this script hardcoded
    `baseline_rate=2.0, k=4.0`, roughly a sixth of what the rule gives against
    the placeholder curve; at that load one replica absorbs the whole spike and
    queue depth never crosses even its lowest threshold, so its entire frontier
    was discarded as `no_scaling_action`.

    Continuous batching makes throughput non-monotonic in concurrency once the
    latency knee is passed, so this is a max over the measured points rather
    than the value at the highest one.
    """
    return max(c / curve.latency_at(c) for c, _, _, _ in curve.points if c > 0)


def _preregistered_shape(curve, kind: str, ramp: float) -> SpikeShape:
    saturation = _saturation_rps(curve)
    baseline = BASELINE_FRACTION_OF_SATURATION * saturation
    peak = baseline + ADDITIONAL_REPLICAS_AT_PEAK * saturation
    return SpikeShape(
        kind=kind, baseline_rate=baseline, k=peak / baseline, ramp=ramp, sustain=190.0
    )


def _report_discards(label: str, discards: list[str]) -> None:
    """`run_sweep` returns `"{signal}:{reason}"` entries so the count can be
    published per signal, as the pre-registration requires. Splitting here is
    what keeps that promise instead of printing a bare total."""
    if not discards:
        print(f"{label}: 0 discards")
        return
    per_signal: Counter[tuple[str, str]] = Counter()
    for entry in discards:
        signal, _, reason = entry.partition(":")
        per_signal[(signal, reason)] += 1
    detail = ", ".join(f"{s}/{r}={n}" for (s, r), n in sorted(per_signal.items()))
    print(f"{label}: {len(discards)} discards ({detail})")


def _by_signal(points):
    return {s: [p for p in points if p.signal == s] for s in {p.signal for p in points}}


def _sweep(label: str, shape: SpikeShape, lags: LagDistribution, arm: str):
    points, discards = run_sweep(
        SweepConfig(
            shape=shape, lags=lags, curve=SERVICE_CURVE_PLACEHOLDER, arm=arm, until=UNTIL
        ),
        seed=SEED,
        allow_unmeasured=True,  # placeholder curve; layout draft, not a result
    )
    print(f"{label}: {len(points)} policy points over signals {sorted(_by_signal(points))}")
    _report_discards(label, discards)
    return points


def _run_everything(store: str):
    """Every sweep the two figures need, as plain data ready to cache."""
    shape = _preregistered_shape(SERVICE_CURVE_PLACEHOLDER, kind="step", ramp=0.0)
    print(
        f"step spike: baseline={shape.baseline_rate:.1f} rps, k={shape.k:.1f} "
        f"(peak {shape.baseline_rate * shape.k:.1f} rps), sustain={shape.sustain:g}s"
    )
    lags = load_measured_lags(store)

    sources: dict[str, list[PolicyPoint]] = {}
    for arm in ("A", "C"):
        sources[f"arm {arm}"] = _sweep(f"arm {arm}", shape, lags[arm], arm)

    swept: dict[float, dict] = {}
    for lag in SWEPT_LAGS:
        label = f"modeled lag {lag:g}s"
        points = _sweep(label, shape, LagDistribution(samples=[lag]), f"synthetic-{lag}")
        sources[label] = points
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(points).items()}
        # `iso_cost_budget`, not `min(cost) * 2`: the latter was written here,
        # pre-registered nowhere, and left every frontier fully affordable, so
        # the "iso-cost slice" constrained nothing. Any signal whose frontier
        # cannot reach the budget makes the gap undefined rather than smaller --
        # `gap_at_iso_cost` says so and raises.
        swept[lag] = gap_interval(
            per_signal, iterations=GAP_BOOTSTRAP_ITERATIONS, seed=SEED
        )
        print(
            f"{label}: gap={swept[lag]['point']:.4f}s "
            f"[{swept[lag]['lo']:.4f}, {swept[lag]['hi']:.4f}] "
            f"at budget {swept[lag]['budget']:.1f}"
        )

    # H3 is evaluated under BOTH shapes or not at all -- the pre-registration
    # fixes that, because H4 already predicts the ramp's margins shrink, so a
    # ramp-only halving is both the easier outcome and the less interesting
    # one. Until this existed the script swept only the step, and `h3_verdict`
    # was reachable from tests and from nowhere else: running the artifact
    # could not evaluate its own headline hypothesis.
    ramp_shape = _preregistered_shape(SERVICE_CURVE_PLACEHOLDER, kind="ramp", ramp=RAMP_SECONDS)
    print(
        f"ramp spike: baseline={ramp_shape.baseline_rate:.1f} rps, k={ramp_shape.k:.1f}, "
        f"ramp={ramp_shape.ramp:g}s, sustain={ramp_shape.sustain:g}s"
    )
    for arm in ("A", "C"):
        sources[f"ramp arm {arm}"] = _sweep(
            f"ramp arm {arm}", ramp_shape, lags[arm], f"ramp-{arm}"
        )

    gaps: dict[str, dict] = {}
    for label in ("arm A", "arm C", "ramp arm A", "ramp arm C"):
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(sources[label]).items()}
        got = gap_interval(per_signal, iterations=GAP_BOOTSTRAP_ITERATIONS, seed=SEED)
        gaps[label] = got
        reps = {s: f[0].n for s, f in sorted(per_signal.items())}
        print(
            f"{label}: gap={got['point']:.4f}s [{got['lo']:.4f}, {got['hi']:.4f}] "
            f"at budget {got['budget']:.1f} replica-seconds (repetitions {reps})"
        )

    verdict = h3_verdict(
        step_gap_a=gaps["arm A"]["point"],
        step_gap_c=gaps["arm C"]["point"],
        ramp_gap_a=gaps["ramp arm A"]["point"],
        ramp_gap_c=gaps["ramp arm C"]["point"],
        step_gap_a_interval=(gaps["arm A"]["lo"], gaps["arm A"]["hi"]),
        ramp_gap_a_interval=(gaps["ramp arm A"]["lo"], gaps["ramp arm A"]["hi"]),
    )
    print(
        f"\nH3: holds={verdict.holds} partial={verdict.partial} "
        f"evaluable={verdict.evaluable}\n  {verdict.detail}"
    )
    # The verdict is computed from POINT gaps and every one of them has an
    # interval printed above. A halving that is inside the noise is not a
    # halving; the intervals are what a reader checks that against, and they
    # stay printed rather than being folded into the boolean, because a
    # three-state verdict with an interval quietly absorbed into it is a
    # four-state verdict nobody declared.
    return sources, swept, gaps


def _dump(path: Path, sources, swept, gaps) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": {
                    label: [
                        [
                            list(p.cost_samples), list(p.p99_samples), p.signal,
                            p.scale_up_at, p.scale_down_at,
                        ]
                        for p in points
                    ]
                    for label, points in sources.items()
                },
                "swept": {str(k): v for k, v in swept.items()},
                "gaps": gaps,
            },
            indent=1,
        )
    )


def _load(path: Path):
    raw = json.loads(path.read_text())
    sources = {
        label: [
            PolicyPoint(
                cost_samples=tuple(c), p99_samples=tuple(p), signal=s,
                scale_up_at=u, scale_down_at=d,
            )
            for c, p, s, u, d in rows
        ]
        for label, rows in raw["sources"].items()
    }
    return sources, {float(k): v for k, v in raw["swept"].items()}, raw.get("gaps", {})


def _first_complete(sources) -> str | None:
    """The first sweep that produced a frontier for all three signals.

    Preferring a measured arm and falling back to a modeled lag is not a silent
    substitution: the label this returns is printed ON the frontier figure, so a
    reader can see which sweep it came from without reading the script.
    """
    for label, points in sources.items():
        if all(s in _by_signal(points) for s in SIGNAL_ORDER):
            return label
    return None


def main() -> None:
    # The sweep is minutes of CPU with nothing to show for it. Python
    # block-buffers stdout as soon as it is redirected to a file, so without
    # this the progress lines all arrive at the end and a working run is
    # indistinguishable from a hung one.
    sys.stdout.reconfigure(line_buffering=True)

    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/a2-figures-draft")
    ap.add_argument("--refresh", action="store_true", help="re-run the sweep, ignoring the cache")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not SERVICE_CURVE_PLACEHOLDER.measured:
        print(
            "WARNING: rendering against the PLACEHOLDER service curve. "
            "These figures are a layout draft, not a result."
        )

    cache = out / "sweep-cache.json"
    if cache.exists() and not args.refresh:
        print(f"reusing the cached sweep at {cache} (--refresh to re-run it)")
        sources, swept, gaps = _load(cache)
    else:
        sources, swept, gaps = _run_everything(args.store)
        _dump(cache, sources, swept, gaps)
        print(f"cached the sweep to {cache}")

    # Figure 2 first: it needs one sweep with all three signals, which is a
    # weaker precondition than figure 1's, so a run that cannot draw the
    # headline still leaves something to look at.
    blocked = []
    complete = _first_complete(sources)
    if complete is None:
        blocked.append(
            "frontier figure: no sweep produced a frontier for all three signals. "
            + "; ".join(
                f"{label} has {sorted(_by_signal(points))}" for label, points in sources.items()
            )
        )
    else:
        print(frontiers(_by_signal(sources[complete]), out / "frontiers.png", context=complete))

    arm_a, arm_c = _by_signal(sources["arm A"]), _by_signal(sources["arm C"])
    try:
        print(
            convergence(
                arm_a,
                arm_c,
                swept,
                out / "convergence.png",
                curve_measured=SERVICE_CURVE_PLACEHOLDER.measured,
            )
        )
    except ValueError as exc:
        blocked.append(f"convergence figure: {exc}")

    if blocked:
        why = (
            "These are the figures' own guards refusing to draw a chart that "
            "would read as a comparison it is not. Against the PLACEHOLDER "
            "service curve the slow arm's replicas are killed by LIFO "
            "scale-down before they serve, so whole signals are excluded by "
            "the pre-registered `replica_never_served` rule and the arms end "
            "up compared over different signal sets. Re-run with --refresh "
            "once plan 2's measured service curve lands; if signals are still "
            "missing then, the spike window or the exclusion rules -- not this "
            "script -- are what need revisiting."
        )
        raise SystemExit("\n\n".join(["", *blocked, why]))


if __name__ == "__main__":
    main()
