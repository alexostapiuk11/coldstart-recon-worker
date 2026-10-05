"""Artifact 4's validation gate: three models, one GPU, real swaps, one
replayed trace, and the simulator held to the real repeats' spread (August §9).

The band and verdict arithmetic is artifact 2's, shared through the
coldstart-free `autoscale.validation_band`. What is artifact 4's own is here:
the record of one real replay, the check that the repeats replayed one trace,
the simulator's prediction of that trace, and a second test August §9 asks
for, that the simulator reproduces the swap timeline as well as the latency.
Every threshold is pre-registered in `placement.step2`.

Bins are keyed by SCHEDULED arrival, as in artifact 2's gate, so every repeat
and the prediction place the same requests in the same bins and driver jitter
cannot move a request across a boundary. Jitter is bounded instead.

The prediction replays the trace on one GPU that starts holding the first
tenant, as the driver does, with the measured solo curve and every swap at the
median measured swap in the validation's cache state, plus the median
page-cache eviction a cold replay pays and a fleet does not. A fixed swap
time keeps the prediction deterministic: the band is the real system's
spread, and a prediction drawn from a distribution would add the simulator's
own noise to the comparison.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.validation_band import BandBin, Bin, band, compare, trajectory
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.step2 import (
    EDGE_TOLERANCE_S,
    MAX_MISS_FRACTION,
    MAX_SEND_JITTER_S,
    MIN_COMPARED_BINS,
    SWAP_COUNT_SLACK,
    VALIDATION_BIN_S,
    VALIDATION_DRAIN_LIMIT_S,
    VALIDATION_MIN_SWAPS,
    VALIDATION_REPEATS,
    VALIDATION_SEEDS,
    NotDecidable,
    validation_design,
)
from placement_measure.campaigns import ReplayDesign

__all__ = ["ReplayRun", "check_repeats", "predict", "replay_run", "tolerance_band", "validate",
           "validation_trace"]


@dataclass(frozen=True)
class ReplayRun:
    """One real replay. `latencies[i]` is request i's completion minus its
    arrival, None if it never completed; `windowed_latencies` applies the cut
    at `until`, on the same clock as the simulator's trajectory."""

    schedule: tuple[float, ...]
    tenants: tuple[int, ...]
    arrived: tuple[float, ...]
    latencies: tuple[float | None, ...]
    until: float
    swaps: int
    host_id: str

    def windowed_latencies(self) -> tuple[float | None, ...]:
        """None where the request finished after `until`, judged on the
        SCHEDULE's clock (scheduled arrival plus latency), as the prediction
        is. Judged on actual arrival instead, a request finishing within the
        send jitter of the window's end could be censored on one side only,
        and the gate would score an unbounded miss neither system made."""
        return tuple(None if lat is None or t + lat > self.until else lat
                     for t, lat in zip(self.schedule, self.latencies, strict=True))

    def send_jitter(self) -> float:
        return max(a - t for a, t in zip(self.arrived, self.schedule, strict=True))


def replay_run(record) -> ReplayRun:
    """A stored replay record as a `ReplayRun`. Only an ok record qualifies:
    `placement_measure.records` marks a replay failed if a request errored or
    the job budget cut it short."""
    if record.kind != "replay" or record.outcome != "ok":
        raise ValueError(f"run {record.run_id} is not an ok replay ({record.kind}, {record.outcome})")
    out = record.output
    schedule = tuple(float(t) for t, _ in record_schedule(out))
    arrived = out["arrived"]
    if any(a is None for a in arrived):
        raise ValueError(f"replay {record.run_id} left arrivals unhandled; it replayed part of the trace")
    latencies = tuple(None if d is None else d - a for a, d in zip(arrived, out["done"], strict=True))
    return ReplayRun(schedule=schedule, tenants=tuple(m for _, m in record_schedule(out)),
                     arrived=tuple(arrived), latencies=latencies, until=float(out["until"]),
                     swaps=len(out["swaps"]), host_id=(out.get("host") or {}).get("host_id") or "")


def record_schedule(output: dict) -> list[tuple[float, int]]:
    """The trace a replay was given, as the driver echoed it into its output."""
    return [(float(t), int(m)) for t, m in output["schedule"]]


def check_repeats(runs: Sequence[ReplayRun]) -> None:
    if len(runs) != VALIDATION_REPEATS:
        raise ValueError(
            f"{len(runs)} ok replays; the gate needs exactly {VALIDATION_REPEATS}. Fewer is "
            "too little spread, and more widens a min-max band until the model fits"
        )
    first = runs[0]
    for run in runs[1:]:
        if (run.schedule, run.tenants, run.until) != (first.schedule, first.tenants, first.until):
            raise ValueError(
                "the replays differ in trace or window; the band must be the system's spread "
                "on ONE trace, and mixing traces widens it for free"
            )
    for run in runs:
        if run.send_jitter() > MAX_SEND_JITTER_S:
            raise ValueError(
                f"a replay's arrivals lag the schedule by {run.send_jitter():.3f} s, more than "
                f"{MAX_SEND_JITTER_S} s; it replayed a different trace from the one predicted"
            )
    if not all(run.host_id for run in runs):
        raise ValueError("a replay does not name its host; a host-novelty event would then be "
                         "indistinguishable from a simulator bug")


def tolerance_band(runs: Sequence[ReplayRun]) -> list[BandBin]:
    check_repeats(runs)
    return band([trajectory(r.schedule, r.windowed_latencies(), until=r.until,
                            bin_seconds=VALIDATION_BIN_S) for r in runs],
                min_repeats=VALIDATION_REPEATS)


def predict(schedule: Sequence[float], tenants: Sequence[int], until: float, engines: Engines,
            swap_median_s: float) -> tuple[list[Bin], int, float]:
    """The simulator's trajectory of the trace, its swap count, and when its
    last request completes (drain-out included)."""
    if not math.isfinite(swap_median_s) or swap_median_s < 0:
        raise ValueError(f"swap_median_s must be a finite duration, got {swap_median_s!r}")
    n_tenants = max(tenants) + 1
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=tuple(range(n_tenants)))
    result = simulate(list(zip(schedule, tenants, strict=True)), placement, engines,
                      EmpiricalDistribution(samples=(swap_median_s,), measured=True), 0.0,
                      random.Random(0))
    windowed = [None if a + lat > until else lat
                for a, lat in zip(result.arrivals, result.latencies, strict=True)]
    last_done = max(a + lat for a, lat in zip(result.arrivals, result.latencies, strict=True))
    bins = trajectory(result.arrivals, windowed, until=until, bin_seconds=VALIDATION_BIN_S)
    return bins, result.swaps, last_done


def validation_trace(measurement: dict, engines: Engines,
                     swap_s: float) -> tuple[ReplayDesign, list[dict]]:
    """The pre-registered validation trace from the first of VALIDATION_SEEDS
    whose predicted replay is feasible, and the check of every draw tried.

    Feasible: the simulator, given the measured curve and `swap_s` (the
    median swap plus its eviction time, as the replay pays both), drains the
    trace within VALIDATION_DRAIN_LIMIT_S, at least MIN_COMPARED_BINS of its
    bins hold a median, and it swaps at least VALIDATION_MIN_SWAPS times. A
    trace failing the first two would be paid for and then refused, by the
    job budget or by the gate's own minimum; one failing the third would
    not exercise the swaps the gate exists to test. Run before any replay, on
    measured inputs: the choice reads predicted feasibility, never a verdict.
    """
    checks = []
    for seed in VALIDATION_SEEDS:
        design = validation_design(measurement, engines.solo, seed)
        bins, swaps, last_done = predict([t for t, _ in design.trace],
                                         [m for _, m in design.trace], design.until, engines,
                                         swap_s)
        ok_bins = sum(b.status == "ok" for b in bins)
        feasible = (last_done <= VALIDATION_DRAIN_LIMIT_S and ok_bins >= MIN_COMPARED_BINS
                    and swaps >= VALIDATION_MIN_SWAPS)
        checks.append({"seed": seed, "requests": len(design.trace), "predicted_swaps": swaps,
                       "predicted_last_done_s": last_done, "ok_bins": ok_bins,
                       "feasible": feasible})
        if feasible:
            return design, checks
    raise NotDecidable(f"no pre-registered validation draw is feasible: {checks}. The gate "
                       "cannot run as registered; this is the owner's decision")


def validate(records, engines: Engines, swap_median_s: float) -> dict:
    """The gate end to end. `outcome` is "passed" only if the latency verdict
    passed and the swap count agrees; a latency verdict that is not evaluable
    stays "not_evaluable", whatever the swaps say."""
    runs = [replay_run(r) for r in records if r.kind == "replay" and r.outcome == "ok"]
    tolerance = tolerance_band(runs)
    first = runs[0]
    predicted, predicted_swaps, _ = predict(first.schedule, first.tenants, first.until, engines,
                                            swap_median_s)
    verdict = compare(predicted, tolerance, min_compared_bins=MIN_COMPARED_BINS,
                      max_miss_fraction=MAX_MISS_FRACTION,
                      edge_tolerance_seconds=EDGE_TOLERANCE_S)
    real_swaps = [r.swaps for r in runs]
    swaps_agree = min(real_swaps) - SWAP_COUNT_SLACK <= predicted_swaps <= max(real_swaps) + SWAP_COUNT_SLACK
    if verdict.outcome == "not_evaluable":
        outcome = "not_evaluable"
    elif verdict.outcome == "passed" and swaps_agree:
        outcome = "passed"
    else:
        outcome = "failed"
    return {
        "outcome": outcome,
        "latency": {"outcome": verdict.outcome, "detail": verdict.detail,
                    "compared": verdict.compared, "agreeing": verdict.agreeing,
                    "max_miss_seconds": verdict.max_miss_seconds},
        "swaps": {"predicted": predicted_swaps, "real": real_swaps, "agree": swaps_agree},
        "swap_median_s": swap_median_s,
        "hosts": [r.host_id for r in runs],
        "requests": len(first.schedule),
        "bins": [{"start": p.start, "end": p.end, "predicted": p.p50, "lo": b.lo, "hi": b.hi,
                  "verdict": v.verdict}
                 for p, b, v in zip(predicted, tolerance, verdict.bins, strict=True)],
    }
