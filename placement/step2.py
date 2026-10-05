"""Pre-registration step 2, as rules: how reconnaissance's answers become the
measurement design, the simulated design and the validation gate.

Amendment §3 commits the pre-registration in two steps, the second "before the
first measurement run", because the request shape depends on what
reconnaissance reports. This module goes one further. It fixes the RULES
before reconnaissance's answers are read, so that once they are, every value
follows mechanically, and none was chosen by someone who had seen the data
(`docs/experiment-a4.md`, "Step 2"). The values themselves are written to
`placement/registered.py` by `scripts/a4_step2.py`, before the first
measurement run.

A rule that needs an answer reconnaissance did not give raises
`NotDecidable`. That is a stop for the owner, never a default: a guessed
input here would be pre-registered as if it had been measured.

Two thresholds are relative to measurements made later, and are stated as
multiples so they need no value now: the SLO is a multiple of the simulated
swap's median, chosen by the ranking-blind screen (`placement.screen`), and
the validation trace's load is a fraction of the measured solo saturation.
"""

import math
import random
from dataclasses import dataclass

from autoscale.service import ServiceCurve
from autoscale.traffic import saturation_rps
from placement.design import Design
from placement.traffic import bursty_trace, zipf_shares
from placement_measure.campaigns import CellDesign, ReplayDesign, SleepDesign, SwapDesign
from placement_measure.prereg import FALLBACK, MAX_NUM_SEQS, PRIMARY, T_MAX

__all__ = [
    "NotDecidable", "SweepChoice", "measurement_design", "provisional_swap_samples",
    "request_shape", "sweep_design", "validation_design",
]

BASE = "Qwen/Qwen3-4B-Base"
INSTRUCT = "Qwen/Qwen3-4B-Instruct-2507"
# The co-located grid's neighbour. The fallback class has one checkpoint, so
# its two co-resident engines are two copies of it, as in reconnaissance.
NEIGHBOUR = {PRIMARY: BASE, FALLBACK: FALLBACK}
# bf16 weights, amendment §3's table.
WEIGHTS_GIB = {PRIMARY: 7.49, FALLBACK: 3.78}

# --- The request shape (amendment §4) ---
# Fixed output, so service time does not depend on where a checkpoint would
# have stopped (`ignore_eos`, amendment §3).
OUTPUT_LEN = 256
# Total tokens per request, tried shortest first; the last is T_max.
TOTAL_LEN_CANDIDATES = (512, 1024, 1536, 2048)
# The shortest request at which the split engine's KV holds at most this many
# requests at once. That puts the KV ceiling inside a measured grid of a
# handful of points, where its bend can be seen, and well below max_num_seqs.
SPLIT_CEILING_TARGET = 32
# Each grid runs past its KV ceiling by this factor, so the bend is measured
# rather than extrapolated.
LEVEL_HEADROOM = 1.5

# --- The measurement campaigns ---
CELL_REPEATS = 4
# A cell needs this many valid repeats: a run whose measured engine compiled is
# not valid, because compile state moves KV capacity (amendment §5), and the
# first engine on a fresh worker compiles. The fourth repeat absorbs that.
CELL_MIN_VALID = 3
SWAPS_PER_STATE = 16
SLEEP_REPEATS = 8
# Page-cache eviction "works" if every cold swap in reconnaissance had a method
# succeed and the kernel's Cached figure fell by at least this fraction of one
# 4B checkpoint's weights (reconnaissance's cold swaps were 4B).
EVICTION_MIN_FRACTION = 0.5
CELLS_SEED, SWAPS_SEED, SLEEP_SEED = 4101, 4102, 4103

# --- The simulated design (amendment §7, §8, §12) ---
N_MODELS = 20
SKEWS = (0.6, 0.8, 1.0, 1.25, 1.5, 2.0)
REGIMES = ("spread", "bursty")
HOT_FRACTION = 0.7
WARMUP_S = 300.0
MEAN_BURST_S = 120.0
DUTY = 0.2
REPETITIONS = 30
PILOT_TRACES = 1200
SWEEP_SEED = 20261004
# Artifact 5's cost table reads this grid point (amendment §11).
REFERENCE = {"regime": "bursty", "s": 1.0}

# --- The ranking-blind screen (`placement.screen`) ---
# Candidates in preference order; a tie in the screen's score goes to the
# earlier one: offered load first, then the tighter SLO, the one closer to a
# serving target. Offered load is in units of one GPU's saturation, the SLO in
# multiples of the simulated swap's median.
SCREEN_OFFERED_GPUS = (4.0, 2.0, 1.0)
SCREEN_SLO_SWAP_MULTIPLES = (1.0, 2.0, 4.0)
SCREEN_REPETITIONS = 5
SCREEN_SEED = 20261005

# --- The validation gate (August §9) ---
VALIDATION_S = 1.0
VALIDATION_LOAD = 0.3  # of the measured solo saturation
VALIDATION_WINDOW_S = 900.0
VALIDATION_MEAN_BURST_S = 180.0
VALIDATION_DUTY = 0.25
# Draws tried in order; the first whose predicted replay is feasible is used
# (`placement.validation.validation_trace`). One GPU swapping among three
# bursty tenants ping-pongs whenever two are ON at once, so a single draw can
# swap once or a hundred times; a trace whose backlog outlasts the job, or
# that hardly swaps, validates nothing. Chosen on 2026-10-04 by simulating
# draws: with a 4B-like curve and 25-60 s swaps, these parameters gave a
# feasible draw within the first two seeds in every case tried, where a
# 120 s burst at duty 1/3 or a higher load often gave none.
VALIDATION_SEEDS = tuple(range(4104, 4124))
VALIDATION_MIN_SWAPS = 4
VALIDATION_REPEATS = 3
# 30 s, not artifact 2's 10 s: at this load a 10 s bin can hold fewer requests
# than the p50's 20-sample floor, and every bin would be thin.
VALIDATION_BIN_S = 30.0
# Feasible means the predicted last completion is at most this many seconds
# after the replay starts: the job's 1800 s, less its 120 s teardown reserve,
# the driver's 240 s wait for a swap in progress, and 240 s for the first
# engine's start before the replay's clock begins.
VALIDATION_DRAIN_LIMIT_S = 1200.0
MAX_SEND_JITTER_S = 0.5
MIN_COMPARED_BINS = 10
MAX_MISS_FRACTION = 0.5
EDGE_TOLERANCE_S = 0.001
# The predicted swap count must lie within the real repeats' range, widened by
# this many swaps either side.
SWAP_COUNT_SLACK = 1
# The interference check: a held-out cell passes if the surface's prediction
# is inside its repeats' range, or within this fraction of their median.
HELD_OUT_TOLERANCE = 0.10

assert TOTAL_LEN_CANDIDATES[-1] == T_MAX


class NotDecidable(ValueError):
    """Reconnaissance did not answer something a rule needs. Stop: the owner
    decides, and the decision is recorded as an amendment."""


def _answered(entry: dict, what: str) -> dict:
    if not entry.get("answered"):
        raise NotDecidable(f"reconnaissance did not answer {what}; no rule may guess it")
    return entry


def model_class(report: dict) -> str:
    g = report["go_no_go"]
    if _answered(g["primary"], "the primary go/no-go")["passed"]:
        return PRIMARY
    if _answered(g["fallback"], "the fallback go/no-go")["passed"]:
        return FALLBACK
    raise NotDecidable("both model classes failed the go/no-go: the design changes, not the "
                       "measurement (amendment §3)")


def kv_split(report: dict, model: str) -> int:
    key = "primary" if model == PRIMARY else "fallback"
    return min(report["go_no_go"][key]["kv_capacity_tokens"])


def kv_solo(report: dict, model: str) -> int | None:
    """The smallest warm-compile solo reading for `model`, or None when
    reconnaissance has none: its swaps ran only the 4B checkpoints."""
    readings = [r["kv_capacity_tokens"] for r in report["kv_solo"]
                if r["model"] == model and r["compiled"] is False
                and r["kv_capacity_tokens"] is not None]
    return min(readings) if readings else None


def request_shape(kv_split_tokens: int) -> dict:
    for total in TOTAL_LEN_CANDIDATES:
        if kv_split_tokens // total <= SPLIT_CEILING_TARGET:
            break
    ceiling = kv_split_tokens // total
    if ceiling >= MAX_NUM_SEQS:
        raise NotDecidable(
            f"at T_max the split engine still holds {ceiling} requests, at or above "
            f"max_num_seqs {MAX_NUM_SEQS}: KV cannot bind, and amendment §4 cannot be met"
        )
    return {"input_len": total - OUTPUT_LEN, "output_len": OUTPUT_LEN, "split_ceiling": ceiling}


def power_levels(ceiling: int | None) -> tuple[int, ...]:
    """1, 2, 4, ... up to the first level at least `LEVEL_HEADROOM` times the
    ceiling, capped at max_num_seqs. No ceiling means the full range."""
    top = MAX_NUM_SEQS if ceiling is None else min(MAX_NUM_SEQS, LEVEL_HEADROOM * ceiling)
    levels = [1]
    while levels[-1] < top:
        levels.append(levels[-1] * 2)
    return tuple(min(level, MAX_NUM_SEQS) for level in levels)


def held_out_cells(own: tuple[int, ...], neighbour: tuple[int, ...]) -> tuple[str, ...]:
    """Two cells between grid points, never measured into the surface, that
    the surface must predict (August §9's second check)."""
    if len(own) < 4 or len(neighbour) < 3:
        raise NotDecidable(f"the grid {own} x {neighbour} is too small to hold cells out of")
    cells = ((own[-3] * 3 // 2, neighbour[2] * 3 // 2), (own[-2] * 3 // 2, neighbour[1] * 3 // 2))
    return tuple(f"pair:o{o}:n{n}" for o, n in cells)


def compile_shared(report: dict) -> bool:
    rows = report["compile_reuse"]
    if not rows or any(r["b_compiled"] is None for r in rows):
        raise NotDecidable("reconnaissance did not read every swap-in's compile state")
    return not any(r["b_compiled"] for r in rows)


def eviction_works(report: dict) -> bool:
    cold = [r for r in report["cache_eviction"] if r["cold"]]
    if not cold:
        raise NotDecidable("reconnaissance ran no cold swap, so eviction is unanswered")
    need = EVICTION_MIN_FRACTION * WEIGHTS_GIB[PRIMARY] * 1024 * 1024
    return all(any(r["methods_ok"].values()) and r["cached_kib_drop"] is not None
               and r["cached_kib_drop"] >= need for r in cold)


def sleep_works(report: dict) -> bool:
    s = report["sleep_mode"]
    return bool(s.get("answered") and s.get("works"))


def validation_set(model: str, shared: bool) -> tuple[str, str, str]:
    """Three distinct checkpoints if every swap-in reused the compile cache, so
    swap cost does not depend on the target; otherwise three tenants of one
    checkpoint, which are config-matched by construction (amendment §3)."""
    if model == PRIMARY and shared:
        return (PRIMARY, BASE, INSTRUCT)
    return (model, model, model)


def swap_pairs(vset: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    distinct = list(dict.fromkeys(vset))
    if len(distinct) == 1:
        return ((distinct[0], distinct[0]),)
    return tuple((a, b) for a in distinct for b in distinct if a != b)


def measurement_design(report: dict) -> dict:
    """Everything reconnaissance decides, from its report alone."""
    model = model_class(report)
    shape = request_shape(kv_split(report, model))
    total = shape["input_len"] + shape["output_len"]
    solo = kv_solo(report, model)
    solo_ceiling = None if solo is None else solo // total
    own = power_levels(shape["split_ceiling"])
    neighbour = (0, *own[-3:])
    shared, cold_works, sleepy = compile_shared(report), eviction_works(report), sleep_works(report)
    vset = validation_set(model, shared)
    pairs = swap_pairs(vset)
    cells = CellDesign(
        measured_model=model, neighbour_model=NEIGHBOUR[model], own_levels=own,
        neighbour_levels=neighbour, solo=False, input_len=shape["input_len"],
        output_len=shape["output_len"], repeats=CELL_REPEATS, seed=CELLS_SEED,
        extra_cells=tuple(f"solo:o{c}" for c in power_levels(solo_ceiling))
        + held_out_cells(own, neighbour),
    )
    swaps = SwapDesign(pairs=pairs, cold_states=(True, False) if cold_works else (False,),
                       repeats=math.ceil(SWAPS_PER_STATE / len(pairs)), seed=SWAPS_SEED)
    sleep = SleepDesign(a=model, b=NEIGHBOUR[model], repeats=SLEEP_REPEATS,
                        seed=SLEEP_SEED) if sleepy else None
    return {
        "model": model, "shape": shape, "kv_split_tokens": kv_split(report, model),
        "kv_solo_tokens": solo, "solo_ceiling": solo_ceiling,
        "own_levels": own, "neighbour_levels": neighbour,
        "solo_levels": power_levels(solo_ceiling), "held_out": held_out_cells(own, neighbour),
        "compile_shared": shared, "eviction_works": cold_works, "sleep_works": sleepy,
        # The simulator draws swaps from the cold distribution if eviction
        # works, else the warm one, and only swap-ins that reused the compile
        # cache: a fleet's steady state, in which a model has been served on
        # the host before (amendment §5).
        "simulated_swap": {"cold": cold_works, "compiled": False},
        # Sleep mode is measured and reported beside the crossover, never
        # simulated: the simulator would need the host RAM a sleeping model
        # takes, which reconnaissance does not measure (amendment §6).
        "sleep_simulated": False,
        "validation_set": vset, "cells": cells, "swaps": swaps, "sleep": sleep,
    }


def provisional_swap_samples(report: dict, measurement: dict) -> tuple[float, ...]:
    """Reconnaissance's own swap times in the simulated state: the only swap
    measurements that exist when the screen runs, before the swap campaign.

    Cold swaps if eviction works, warm ones otherwise; compile-cache hits only.
    The warm ones include the compile probe's swaps, all of which were warm.
    """
    cold = measurement["simulated_swap"]["cold"]
    rows = [r for r in report["cache_eviction"] if r["cold"] == cold]
    if not cold:
        rows += report["compile_reuse"]
    samples = tuple(r["swap_s"] for r in rows
                    if r["swap_s"] is not None and r["b_compiled"] is False)
    if not samples:
        raise NotDecidable(f"reconnaissance has no {'cold' if cold else 'warm'} swap with a "
                           "compile-cache hit, so the screen has no swap time to draw")
    return samples


@dataclass(frozen=True)
class SweepChoice:
    """The screen's pick: offered load, and the SLO as a swap multiple."""

    offered_gpus: float
    slo_swap_multiple: float


def sweep_design(choice: SweepChoice, swap_median_s: float, *, repetitions: int = REPETITIONS,
                 seed: int = SWEEP_SEED, preregistered: bool = True) -> Design:
    if not math.isfinite(swap_median_s) or swap_median_s <= 0:
        raise ValueError(f"swap_median_s must be finite and positive, got {swap_median_s!r}")
    return Design(
        n_models=N_MODELS, offered_gpus=choice.offered_gpus, hot_fraction=HOT_FRACTION,
        warmup=WARMUP_S, mean_burst=MEAN_BURST_S, duty=DUTY, skews=SKEWS, regimes=REGIMES,
        repetitions=repetitions, slo_seconds=choice.slo_swap_multiple * swap_median_s,
        pilot_traces=PILOT_TRACES, seed=seed, preregistered=preregistered,
    )


def validation_design(measurement: dict, solo_curve: ServiceCurve, seed: int) -> ReplayDesign:
    """The replayed trace: three tenants at Zipf s = VALIDATION_S, bursty, at
    VALIDATION_LOAD of the measured solo saturation, drawn once from `seed`.
    Every repeat replays this one draw. Which of VALIDATION_SEEDS is used is
    decided by `placement.validation.validation_trace`."""
    if seed not in VALIDATION_SEEDS:
        raise ValueError(f"seed {seed!r} is not one of the pre-registered validation seeds")
    shares = zipf_shares(len(measurement["validation_set"]), VALIDATION_S)
    rate = VALIDATION_LOAD * saturation_rps(solo_curve)
    trace = bursty_trace(shares, rate, VALIDATION_WINDOW_S, VALIDATION_MEAN_BURST_S,
                         VALIDATION_DUTY, random.Random(seed))
    shape = measurement["shape"]
    return ReplayDesign(
        tenants=measurement["validation_set"], trace=tuple(trace), until=VALIDATION_WINDOW_S,
        input_len=shape["input_len"], output_len=shape["output_len"],
        max_in_flight=int(solo_curve.max_measured_concurrency),
        cold=measurement["eviction_works"], repeats=VALIDATION_REPEATS, seed=seed,
    )
