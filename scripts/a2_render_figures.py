"""Render artifact 2's figures.

Against the MEASURED service curve (`data/a2/service-curve.json`) by default.
`--placeholder` draws the layout draft against the invented placeholder curve,
as before, and says so on stdout. A sweep cache records which curve it came
from, and a cache from the other curve is refused rather than drawn under the
wrong label.

The sweep behind these figures is minutes of CPU on the placeholder curve and
hours on the measured one (30 repetitions of every threshold combination, for
thirteen sweeps), so its output is cached to JSON and re-used: iterating on a
figure's layout must not cost hours per look, or the looking does not happen.
`--refresh` re-runs it.

Each sweep is also CHECKPOINTED as it finishes (`sweep-checkpoint.json` beside
the cache), and every sweep runs before any gap is computed. The cache alone is
written only after the gaps, and the gaps are where the pre-registered guards
refuse: the first measured run swept for four hours, was refused at the H3 gap,
and kept nothing. A re-run without `--refresh` resumes from the checkpoint, so
a refusal costs seconds to reproduce and a crash costs only the sweep it
interrupted. The checkpoint records what its sweeps depend on (curve, store,
seed, window, grids, controller constants) and is refused if any differ. It
cannot see a change to the simulator's code: after one, use `--refresh`, as
with the cache.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale import sweep as sweep_module
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags
from autoscale.figures import SIGNAL_ORDER, convergence, frontiers, service_curve
from autoscale.frontier import (
    PolicyPoint,
    gap_at_iso_cost,
    gap_interval,
    h3_verdict,
    iso_cost_budget,
    pareto_frontier,
)
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.sweep import SweepConfig, run_sweep
from autoscale.thresholds import SENSITIVITY_THRESHOLDS, THRESHOLDS
from autoscale.traffic import (
    RAMP_SECONDS,  # noqa: F401 -- tests/test_a2_end_to_end.py reads render.RAMP_SECONDS
    spike_shape,
)

SEED = 17
UNTIL = 400.0
SWEPT_LAGS = (20.0, 40.0, 60.0, 80.0, 120.0)
# 2000 draws is enough for 95% percentile endpoints (the 50th and 1950th
# order statistics) without the bootstrap dominating a sweep that is
# already minutes of CPU.
GAP_BOOTSTRAP_ITERATIONS = 2000


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
    """Points grouped by signal, in `SIGNAL_ORDER` and then by name.

    An explicit order, not set order: set order follows the hash seed, which
    parity runs had to pin (`PYTHONHASHSEED=0`) to get stable output (plan 2a
    open item). Signals outside `SIGNAL_ORDER` (the utilisation sensitivity
    arm) come after the three arms.
    """
    present = {p.signal for p in points}
    order = [s for s in SIGNAL_ORDER if s in present] + sorted(present - set(SIGNAL_ORDER))
    return {s: [p for p in points if p.signal == s] for s in order}


def curve_label(path) -> str:
    """How a cache and stdout name the curve: its path, or "placeholder"."""
    return "placeholder" if path is None else str(path)


def check_cache_curve(raw: dict, label: str) -> None:
    """Refuse a sweep cache from another curve, or one that does not say.

    Rejected alternative: treating an untagged cache as a placeholder one. That
    is probably true of every cache that predates plan 2b, but "probably" is
    what a label is for removing; the owner re-runs with --refresh instead.
    """
    got = raw.get("curve")
    if got is None:
        raise SystemExit(
            "the sweep cache does not say which service curve it came from (it predates "
            "plan 2b); re-run with --refresh rather than draw it under a guessed label"
        )
    if got != label:
        raise SystemExit(
            f"the sweep cache came from curve {got!r} but this run is on {label!r}; drawing it "
            "would put one curve's frontiers under the other's banner. Use --refresh or "
            "another --out"
        )


def sweep_identity(label: str, store: str) -> dict:
    """What a checkpointed sweep depends on, as written into the checkpoint.

    Not a hash: a refusal that names WHICH input changed tells the owner
    whether `--refresh` is needed or the wrong `--out` was given, and a digest
    mismatch says neither.
    """
    return {
        "curve": label,
        "store": str(store),
        "seed": SEED,
        "until": UNTIL,
        "repetitions": sweep_module.REPETITIONS,
        "cooldown": sweep_module.COOLDOWN_SECONDS,
        "evaluate_every": sweep_module.EVALUATE_EVERY_SECONDS,
        "max_replicas": sweep_module.MAX_REPLICAS,
        "thresholds": {
            s: [list(up), list(down)]
            for s, (up, down) in sorted({**THRESHOLDS, **SENSITIVITY_THRESHOLDS}.items())
        },
        "swept_lags": list(SWEPT_LAGS),
    }


def _rows(points):
    return [
        [list(p.cost_samples), list(p.p99_samples), p.signal, p.scale_up_at, p.scale_down_at,
         list(p.rep_indices)]
        for p in points
    ]


def _points(rows):
    return [
        PolicyPoint(cost_samples=tuple(c), p99_samples=tuple(p), signal=s, scale_up_at=u,
                    scale_down_at=d, rep_indices=tuple(r))
        for c, p, s, u, d, r in rows
    ]


class SweepCheckpoint:
    """Finished sweeps, written to disk one at a time as they finish.

    `path=None` keeps them in memory only, so `_run_everything` has one code
    path whether or not a caller asked for a file. Each `put` rewrites the
    whole file through a temporary and `os.replace`, so a crash mid-write
    leaves the previous checkpoint, never half of one. Rejected: appending one
    JSON line per sweep, which is cheaper but leaves a torn last line for the
    loader to guess about.
    """

    def __init__(self, path: Path | None, identity: dict):
        self.path = path
        self.identity = identity
        self._sweeps: dict[str, dict] = {}
        if path is not None and path.exists():
            raw = json.loads(path.read_text())
            got = raw.get("identity", {})
            changed = sorted(k for k in {*got, *identity} if got.get(k) != identity.get(k))
            if changed:
                raise SystemExit(
                    f"the sweep checkpoint at {path} was made with different {changed} "
                    f"(checkpoint {[got.get(k) for k in changed]!r}, this run "
                    f"{[identity.get(k) for k in changed]!r}); resuming it would mix sweeps "
                    "from two configurations in one figure. Use --refresh or another --out"
                )
            self._sweeps = raw["sweeps"]

    @property
    def tags(self) -> list[str]:
        return list(self._sweeps)

    def get(self, tag: str):
        got = self._sweeps.get(tag)
        return None if got is None else (_points(got["points"]), list(got["discards"]))

    def put(self, tag: str, points, discards) -> None:
        self._sweeps[tag] = {"points": _rows(points), "discards": list(discards)}
        if self.path is None:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"identity": self.identity, "sweeps": self._sweeps}))
        os.replace(tmp, self.path)


def open_checkpoint(out: Path, identity: dict, *, refresh: bool) -> SweepCheckpoint:
    """The checkpoint in `out`; `--refresh` discards it first."""
    path = out / "sweep-checkpoint.json"
    if refresh and path.exists():
        path.unlink()
        print(f"--refresh: discarded the sweep checkpoint at {path}")
    return SweepCheckpoint(path, identity)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/a2-figures-draft")
    ap.add_argument("--refresh", action="store_true", help="re-run the sweep, ignoring the cache")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--curve", default=None,
                       help=f"the measured curve (default {DEFAULT_PATH})")
    which.add_argument("--placeholder", action="store_true",
                       help="layout draft against the invented placeholder curve")
    return ap.parse_args(argv)


def _sweep(label: str, shape: SpikeShape, lags: LagDistribution, arm: str, curve,
           signals=None, checkpoint: SweepCheckpoint | None = None):
    cached = checkpoint.get(label) if checkpoint is not None else None
    if cached is not None:
        points, discards = cached
        print(f"{label}: from the checkpoint")
    else:
        points, discards = run_sweep(
            SweepConfig(shape=shape, lags=lags, curve=curve, arm=arm, until=UNTIL),
            seed=SEED,
            # Only the placeholder needs the opt-in; a measured curve passes the
            # sweep's own guard.
            allow_unmeasured=not curve.measured,
            signals=signals,
        )
        if checkpoint is not None:
            checkpoint.put(label, points, discards)
    print(f"{label}: {len(points)} policy points over signals {list(_by_signal(points))}")
    _report_discards(label, discards)
    return points


def _run_everything(store: str, curve, checkpoint: SweepCheckpoint | None = None):
    """Every sweep the two figures need, as plain data ready to cache.

    All thirteen sweeps run, and are checkpointed, before any gap is computed:
    the gaps are where the pre-registered guards refuse, and a refusal must
    not cost the sweeps behind it (see the module docstring).
    """
    if checkpoint is None:
        checkpoint = SweepCheckpoint(None, {})
    shape = spike_shape(curve, kind="step")
    print(
        f"step spike: baseline={shape.baseline_rate:.1f} rps, k={shape.k:.1f} "
        f"(peak {shape.baseline_rate * shape.k:.1f} rps), sustain={shape.sustain:g}s"
    )
    # H3 is evaluated under BOTH shapes or not at all -- the pre-registration
    # fixes that, because H4 already predicts the ramp's margins shrink, so a
    # ramp-only halving is both the easier outcome and the less interesting
    # one. Until this existed the script swept only the step, and `h3_verdict`
    # was reachable from tests and from nowhere else: running the artifact
    # could not evaluate its own headline hypothesis.
    ramp_shape = spike_shape(curve, kind="ramp")
    print(
        f"ramp spike: baseline={ramp_shape.baseline_rate:.1f} rps, k={ramp_shape.k:.1f}, "
        f"ramp={ramp_shape.ramp:g}s, sustain={ramp_shape.sustain:g}s"
    )
    lags = load_measured_lags(store)
    if checkpoint.tags:
        print(f"resuming: {len(checkpoint.tags)} sweeps already in {checkpoint.path}")

    sources: dict[str, list[PolicyPoint]] = {}
    for arm in ("A", "C"):
        sources[f"arm {arm}"] = _sweep(f"arm {arm}", shape, lags[arm], arm, curve,
                                       checkpoint=checkpoint)
    for lag in SWEPT_LAGS:
        label = f"modeled lag {lag:g}s"
        sources[label] = _sweep(label, shape, LagDistribution(samples=[lag]),
                                f"synthetic-{lag}", curve, checkpoint=checkpoint)
    for arm in ("A", "C"):
        sources[f"ramp arm {arm}"] = _sweep(
            f"ramp arm {arm}", ramp_shape, lags[arm], f"ramp-{arm}", curve,
            checkpoint=checkpoint,
        )
    # H2's sensitivity arm (amendment 2026-10-04): the same four sweeps with
    # utilisation defined as the throughput fraction, swapped in for the
    # nvidia-smi utilisation signal and nothing else. The sweep seeds on
    # (seed, up, down, rep) and not on the signal, so these traces are the
    # headline's own and the swap changes only what the controller reads.
    sensitivity_runs = (("arm A", shape, "A"), ("arm C", shape, "C"),
                        ("ramp arm A", ramp_shape, "ramp-A"),
                        ("ramp arm C", ramp_shape, "ramp-C"))
    for label, sh, arm in sensitivity_runs:
        tag = f"sensitivity {label}"
        sources[tag] = _sweep(tag, sh, lags[arm[-1]], f"sens-{arm}", curve,
                              signals=("utilization_throughput",), checkpoint=checkpoint)
    if checkpoint.path is not None:
        print(
            f"all {len(sources)} sweeps are checkpointed in {checkpoint.path}; a gap "
            "refused below re-runs from it in seconds (without --refresh)"
        )

    swept: dict[float, dict] = {}
    for lag in SWEPT_LAGS:
        label = f"modeled lag {lag:g}s"
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(sources[label]).items()}
        # `iso_cost_budget`, not `min(cost) * 2`: the latter was written here,
        # pre-registered nowhere, and left every frontier fully affordable, so
        # the "iso-cost slice" constrained nothing. Any signal whose frontier
        # cannot reach the budget makes the gap undefined rather than smaller --
        # `gap_at_iso_cost` says so and raises.
        budget = iso_cost_budget(per_signal)
        try:
            swept[lag] = gap_interval(
                per_signal, iterations=GAP_BOOTSTRAP_ITERATIONS, seed=SEED
            )
            print(
                f"{label}: gap={swept[lag]['point']:.4f}s "
                f"[{swept[lag]['lo']:.4f}, {swept[lag]['hi']:.4f}] at budget "
                f"{budget:.1f} over {swept[lag]['paired_repetitions']} paired repetitions"
            )
        except ValueError as exc:
            # A paired bootstrap draws only from the repetitions EVERY frontier
            # point kept, and the exclusion rules can leave fewer of those than
            # the bootstrap floor. For the four measured gaps that is fatal and
            # stays fatal -- the headline does not get published without an
            # interval. This panel is different in kind: it is the explicitly
            # NOT MEASURED sensitivity sweep over invented lag values, and a
            # point without an interval there is a weaker claim, not a
            # dishonest one. `figures.convergence` draws a bare float without a
            # band and says so in its note, so the degradation is visible on
            # the chart rather than only here.
            swept[lag] = gap_at_iso_cost(per_signal, cost=budget)
            print(
                f"{label}: gap={swept[lag]:.4f}s at budget {budget:.1f} -- "
                f"NO INTERVAL ({exc.args[0].split(';')[0]})"
            )

    gaps: dict[str, dict] = {}
    for label in ("arm A", "arm C", "ramp arm A", "ramp arm C"):
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(sources[label]).items()}
        got = gap_interval(per_signal, iterations=GAP_BOOTSTRAP_ITERATIONS, seed=SEED)
        gaps[label] = got
        reps = {s: f[0].n for s, f in sorted(per_signal.items())}
        print(
            f"{label}: gap={got['point']:.4f}s [{got['lo']:.4f}, {got['hi']:.4f}] "
            f"at budget {got['budget']:.1f} replica-seconds "
            f"({got['paired_repetitions']} paired repetitions; per-signal {reps})"
        )

    # The sensitivity gaps are printed beside the headline gap, never
    # substituted for it. Only the gap computation's refusals (a ValueError
    # from `iso_cost_budget` or `gap_at_iso_cost`, such as an empty or
    # unaffordable frontier) are printed rather than raised, so a sensitivity
    # arm with no gap does not stop the figures being drawn.
    sensitivity_signals = tuple(
        "utilization_throughput" if s == "utilization" else s for s in SIGNAL_ORDER
    )
    for label, _, _ in sensitivity_runs:
        tag = f"sensitivity {label}"
        swapped = [p for p in sources[label] if p.signal != "utilization"] + sources[tag]
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(swapped).items()}
        try:
            budget = iso_cost_budget(per_signal)
            g = gap_at_iso_cost(per_signal, cost=budget, expected=sensitivity_signals)
        except ValueError as exc:
            print(f"{tag}: gap undefined ({exc.args[0].split(';')[0]})")
        else:
            print(
                f"{tag}: gap={g:.4f}s at budget {budget:.1f} replica-seconds with "
                f"utilisation as the throughput fraction (headline gap "
                f"{gaps[label]['point']:.4f}s)"
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


def _dump(path: Path, sources, swept, gaps, label: str) -> None:
    path.write_text(
        json.dumps(
            {
                "curve": label,
                "sources": {label: _rows(points) for label, points in sources.items()},
                "swept": {str(k): v for k, v in swept.items()},
                "gaps": gaps,
            },
            indent=1,
        )
    )


def _load(path: Path):
    raw = json.loads(path.read_text())
    sources = {label: _points(rows) for label, rows in raw["sources"].items()}
    return sources, {float(k): v for k, v in raw["swept"].items()}, raw.get("gaps", {}), raw


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


def main(argv=None) -> None:
    # The sweep is minutes of CPU with nothing to show for it. Python
    # block-buffers stdout as soon as it is redirected to a file, so without
    # this the progress lines all arrive at the end and a working run is
    # indistinguishable from a hung one.
    sys.stdout.reconfigure(line_buffering=True)

    args = parse_args(argv)
    path = None if args.placeholder else (args.curve or DEFAULT_PATH)
    curve, measured = select_curve(path, placeholder=args.placeholder)
    label = curve_label(path)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not curve.measured:
        print(
            "WARNING: rendering against the PLACEHOLDER service curve. "
            "These figures are a layout draft, not a result."
        )
    else:
        print(f"service curve: {label} (measured; idle point added)")
    # Figure 4 needs no sweep -- only the curve -- so it renders first and
    # renders even when a figure guard later refuses to draw the others.
    print(service_curve(curve, out / "service_curve.png", measured=measured))

    cache = out / "sweep-cache.json"
    if cache.exists() and not args.refresh:
        print(f"reusing the cached sweep at {cache} (--refresh to re-run it)")
        sources, swept, gaps, raw = _load(cache)
        check_cache_curve(raw, label)
    else:
        checkpoint = open_checkpoint(out, sweep_identity(label, args.store),
                                     refresh=args.refresh)
        sources, swept, gaps = _run_everything(args.store, curve, checkpoint)
        _dump(cache, sources, swept, gaps, label)
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
        print(frontiers(_by_signal(sources[complete]), out / "frontiers.png", context=complete,
                        curve_measured=curve.measured))

    arm_a, arm_c = _by_signal(sources["arm A"]), _by_signal(sources["arm C"])
    try:
        print(
            convergence(
                arm_a,
                arm_c,
                swept,
                out / "convergence.png",
                curve_measured=curve.measured,
            )
        )
    except ValueError as exc:
        blocked.append(f"convergence figure: {exc}")

    if blocked:
        why = (
            "These are the figures' own guards refusing to draw a chart that "
            "would read as a comparison it is not.\n\n"
            "Under the traffic model in force (the measured service curve and "
            "the 2026-10-04 amendment in docs/experiment-a2.md) all three "
            "signals are expected to survive on both arms and both shapes, so "
            "reaching here means something changed. The likely "
            "causes, in order: a signal whose whole grid was excluded -- read "
            "the per-signal discard counts printed above, since "
            "`no_scaling_action` means its thresholds were never crossed and "
            "`replica_never_served` means the fleet never effectively grew; or "
            "a policy left with fewer surviving repetitions than a bootstrap "
            "interval needs. Either is a finding about that signal, not a "
            "figure to draw around.\n\n"
            "The previous text here blamed LIFO scale-down under the "
            "pre-registered traffic model, which was true of the regime that "
            "model produced and is no longer the regime being swept."
        )
        raise SystemExit("\n\n".join(["", *blocked, why]))


if __name__ == "__main__":
    main()
