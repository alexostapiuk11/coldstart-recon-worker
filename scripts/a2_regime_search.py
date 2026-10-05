"""The measured-curve regime search, run exactly as docs/regime-search-a2-measured.md states.

That document fixes the candidates, their order, the pass criteria and the
selection rule, and was committed before this script ran anything. This
script is its executable form; tests/test_a2_regime_search.py pins the two
together, so the code cannot quietly search a different space or apply a
different test from the one the document promised.

Two stages, neither able to change the outcome:
1. SCREEN every candidate on arm A's step with `queue_depth` alone. Its
   frontier depends only on its own points, and the sweep's seeds do not
   involve the signal, so these are the full sweep's `queue_depth` points. A
   frontier point below the bootstrap floor fails P1 there. The screens run in
   parallel because the order only matters for the selection, which happens
   afterwards.
2. VERIFY candidates that clear the screen, IN PREFERENCE ORDER, with the
   four headline sweeps against P1 and P2, and stop at the first that passes.

P1 runs `gap_interval` exactly as the figure script does and keeps only
whether it refused: the search never records or prints a gap, so the choice
cannot be steered by one. Rejected: re-using `a2_regime_probe.py`'s stage 2,
whose survival count (a policy with ONE kept run survives) passes the very
regime the headline was refused in, and whose candidate list was picked from
the placeholder curve.

Every finished sweep is checkpointed per candidate under --out, so an
interrupted search resumes. Free: CPU only, no network. Hours, not minutes.
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
from autoscale.frontier import gap_interval, pareto_frontier
from autoscale.measured_curve import DEFAULT_PATH, select_curve
from autoscale.signals import SIGNALS
from autoscale.stats import MIN_BOOTSTRAP_SAMPLES
from autoscale.sweep import SweepConfig, run_sweep
from autoscale.traffic import saturation_rps, spike_shape

# docs/regime-search-a2-measured.md, "The candidates, in order of preference".
CANDIDATES: tuple[tuple[float, float], ...] = tuple(
    (b, a) for b in (0.70, 0.40, 0.20, 0.10) for a in (0.25, 0.5, 1.0, 2.0, 3.0)
)
# The four headline sweeps: (tag, arm, kind, the arm label `run_sweep` gets).
SWEEPS = (
    ("arm A step", "A", "step", "A"),
    ("arm C step", "C", "step", "C"),
    ("arm A ramp", "A", "ramp", "ramp-A"),
    ("arm C ramp", "C", "ramp", "ramp-C"),
)
SCREEN_SIGNAL = "queue_depth"
P2_RESOLUTION_S = 0.001
P2_MIN_DISTINCT = 2


def _by_signal(points):
    out: dict[str, list] = {}
    for p in points:
        out.setdefault(p.signal, []).append(p)
    return out


def screen_failure(points) -> str | None:
    """Why the screen sweep fails P1, or None if it does not."""
    mine = [p for p in points if p.signal == SCREEN_SIGNAL]
    if not mine:
        return f"no {SCREEN_SIGNAL} policy kept a single run, so it has no frontier"
    thin = [p for p in pareto_frontier(mine) if p.n < MIN_BOOTSTRAP_SAMPLES]
    if thin:
        return (f"{len(thin)} {SCREEN_SIGNAL} frontier points below {MIN_BOOTSTRAP_SAMPLES} "
                f"repetitions (fewest {min(p.n for p in thin)})")
    return None


def p1_failure(points) -> str | None:
    """Why `gap_interval` refuses this sweep, or None if it completes.

    The gap it returns is discarded here, unread, on purpose: see the module
    docstring.
    """
    per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(points).items()}
    try:
        gap_interval(per_signal, iterations=render.GAP_BOOTSTRAP_ITERATIONS, seed=render.SEED)
    except ValueError as exc:
        return exc.args[0].split(";")[0]
    return None


def p2_distinct(points) -> int:
    """Distinct median p99s across every policy in the sweep, at 1 ms."""
    return len({round(p.p99 / P2_RESOLUTION_S) for p in points})


def candidate_tag(b: float, a: float) -> str:
    return f"b{b:.2f}-a{a:g}"


def run_task(task):
    """One sweep in a worker process. Module-level so it pickles."""
    b, a, arm, kind, arm_label, signals, curve_path, store = task
    curve, _ = select_curve(curve_path, placeholder=False)
    shape = spike_shape(curve, kind, baseline_fraction=b, additional_replicas=a)
    lags = load_measured_lags(store)[arm]
    return run_sweep(
        SweepConfig(shape=shape, lags=lags, curve=curve, arm=arm_label, until=render.UNTIL),
        seed=render.SEED, signals=signals,
    )


def _identity(curve_path, store, b, a) -> dict:
    return {**render.sweep_identity(str(curve_path), store),
            "baseline_fraction": b, "additional_replicas": a}


def _pool_map(tasks: dict, workers: int, checkpoint_for, runner):
    """Run `tasks` ({(candidate, tag): task}) on a pool, checkpointing each
    result in the main process as it lands. Already-checkpointed ones are
    read back instead of re-run."""
    results = {}
    todo = {}
    for key, task in tasks.items():
        cached = checkpoint_for(key[0]).get(key[1])
        if cached is not None:
            results[key] = cached[0]
        else:
            todo[key] = task
    if not todo:
        return results
    if workers <= 1:
        for key, task in todo.items():
            points, discards = runner(task)
            checkpoint_for(key[0]).put(key[1], points, discards)
            results[key] = points
            print(f"  {candidate_tag(*key[0])} {key[1]}: done")
        return results
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(runner, task): key for key, task in todo.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            points, discards = fut.result()
            checkpoint_for(key[0]).put(key[1], points, discards)
            results[key] = points
            print(f"  {candidate_tag(*key[0])} {key[1]}: done")
    return results


def search(curve_path, store: str, out: Path, *, workers: int = 4, runner=run_task,
           candidates=CANDIDATES) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    checkpoints: dict = {}

    def checkpoint_for(cand):
        if cand not in checkpoints:
            checkpoints[cand] = render.SweepCheckpoint(
                out / f"{candidate_tag(*cand)}.json", _identity(curve_path, store, *cand))
        return checkpoints[cand]

    curve, _ = select_curve(curve_path, placeholder=False)
    sat = saturation_rps(curve)
    screen_tag = f"screen arm A step {SCREEN_SIGNAL}"
    print(f"stage 1: screening {len(candidates)} candidates ({SCREEN_SIGNAL}, arm A step)")
    screens = _pool_map(
        {(c, screen_tag): (*c, "A", "step", "A", (SCREEN_SIGNAL,), curve_path, store)
         for c in candidates},
        workers, checkpoint_for, runner)

    records = []
    for b, a in candidates:
        shape = spike_shape(curve, "step", baseline_fraction=b, additional_replicas=a)
        rec = {"baseline_fraction": b, "additional_replicas": a,
               "peak_over_saturation": shape.baseline_rate * shape.k / sat}
        failed = screen_failure(screens[((b, a), screen_tag)])
        if failed:
            records.append({**rec, "stage": "screen", "passed": False,
                            "failures": {"arm A step": failed}})
            print(f"{candidate_tag(b, a)}: fails the screen ({failed})")
            continue
        print(f"{candidate_tag(b, a)}: clears the screen; stage 2, four full sweeps")
        rest = tuple(s for s in sorted(SIGNALS) if s != SCREEN_SIGNAL)
        tasks = {}
        for tag, arm, kind, label in SWEEPS:
            signals = rest if tag == "arm A step" else None
            key_tag = "arm A step, other signals" if tag == "arm A step" else tag
            tasks[((b, a), key_tag)] = (b, a, arm, kind, label, signals, curve_path, store)
        got = _pool_map(tasks, workers, checkpoint_for, runner)
        sweeps = {
            tag: (screens[((b, a), screen_tag)] + got[((b, a), "arm A step, other signals")]
                  if tag == "arm A step" else got[((b, a), tag)])
            for tag, *_ in SWEEPS
        }
        failures, distinct = {}, {}
        for tag, points in sweeps.items():
            distinct[tag] = p2_distinct(points)
            why = p1_failure(points)
            if why:
                failures[tag] = f"P1: {why}"
            elif distinct[tag] < P2_MIN_DISTINCT:
                failures[tag] = f"P2: {distinct[tag]} distinct median p99 at 1 ms"
        passed = not failures
        records.append({**rec, "stage": "verify", "passed": passed, "failures": failures,
                        "p2_distinct": distinct})
        print(f"{candidate_tag(b, a)}: {'PASSES' if passed else 'fails'} "
              f"{failures or ''} distinct p99s {distinct}")
        (out / "results.json").write_text(json.dumps(records, indent=1))
        if passed:
            break
    (out / "results.json").write_text(json.dumps(records, indent=1))
    return records


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--curve", default=str(DEFAULT_PATH))
    ap.add_argument("--out", default="build/a2-regime-search")
    ap.add_argument("--workers", type=int, default=4)
    return ap.parse_args(argv)


def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    records = search(args.curve, args.store, Path(args.out), workers=args.workers)
    chosen = next((r for r in records if r["passed"]), None)
    print()
    if chosen is None:
        print("NO candidate passes. Per docs/regime-search-a2-measured.md, queue_depth is "
              "reported as unusable across the searched traffic family.")
    else:
        print(f"first passing candidate in preference order: b={chosen['baseline_fraction']}, "
              f"a={chosen['additional_replicas']} (peak {chosen['peak_over_saturation']:.2f} x "
              "one replica's saturation). Proposed in an amendment for the owner's sign-off.")
    print(f"wrote {Path(args.out) / 'results.json'}")


if __name__ == "__main__":
    main()
