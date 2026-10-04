"""The single-engine service-curve sweep, local side.

One replica at a fixed serve configuration, concurrency swept. Per level the
sweep reports end-to-end request latency, throughput in output tokens per
second, GPU utilisation and TTFT. Artifact 2's simulator uses the latency as
each request's service time and caps a replica at the highest level measured;
artifact 4 needs the same curve per engine at a memory split. So the levels
and the serve arguments are the caller's, never fixed here.

This module holds what the local driver needs: the schedule, the job payload,
the stored record, and the reduction to a curve. What runs inside the worker
is `harness/sweep_worker.py`.

The reduction emits PLAIN TUPLES `(concurrency, latency_s, throughput_tps,
gpu_util)`, never `autoscale.service.ServiceCurve`. Artifact 5's package bans
`autoscale`, and the harness must not pull one artifact's types into another;
artifact 2 adapts the tuples on its own side (`scripts/a2_service_curve.py`).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from harness.failures import classify_failure
from harness.scheduler import ScheduledRun, build_schedule
from harness.stats import median

SCHEMA_VERSION = 1
# Owner decision 2 (2026-10-04): three repeats per level, interleaved.
DEFAULT_REPEATS = 3
# Each measured run is about this many waves of `level` concurrent requests,
# so its duration is about DEFAULT_WAVES x latency(level) whatever the level,
# and never fewer than DEFAULT_MIN_PROMPTS requests feed one run's median.
DEFAULT_WAVES = 20
DEFAULT_MIN_PROMPTS = 100
STATISTIC = (
    "per run: the median, over successful requests, of ttft + sum(itls) "
    "(end-to-end request latency); per level: the median of the run medians, "
    "with min..max of the run medians as the interval"
)
_CURVE_FIELDS = ("latency_s", "throughput_tps", "gpu_util", "ttft_median_s")


def condition_for(level: int) -> str:
    return f"c{level}"


def level_of(condition: str) -> int:
    if not condition.startswith("c") or not condition[1:].isdigit():
        raise ValueError(
            f"condition {condition!r} is not a sweep level like 'c16'; a record "
            "under it cannot be placed on the curve"
        )
    return int(condition[1:])


def validate_levels(levels: Sequence[int]) -> list[int]:
    """At least two distinct positive integers, ascending.

    Ascending and distinct because `ServiceCurve` refuses anything else, and
    discovering that after a paid sweep is the expensive way. At least two
    because one point cannot be interpolated.
    """
    out = list(levels)
    for level in out:
        if isinstance(level, bool) or not isinstance(level, int) or level < 1:
            # ValueError, not TypeError, so a caller catches one type for
            # every bad level.
            raise ValueError(
                f"level {level!r} is not a positive integer; bench's "
                "--max-concurrency takes an integer and reads 0 as unlimited"
            )
    if len(out) < 2:
        raise ValueError(f"levels {out!r}: a curve needs at least two points")
    if out != sorted(set(out)):
        raise ValueError(
            f"levels {out!r} must be strictly ascending; the curve requires "
            "distinct, ascending concurrency"
        )
    return out


def sweep_schedule(levels: Sequence[int], *, repeats: int = DEFAULT_REPEATS, seed: int):
    """Every level once per block, shuffled within each block by `seed`.

    `harness.scheduler.build_schedule` is exactly owner decision 2: repeats
    interleaved across levels, never all repeats of one level back to back,
    so a level is never confounded with a stretch of platform conditions.
    `block_index` is the repeat.
    """
    if repeats < 1:
        raise ValueError(f"repeats={repeats!r}; a sweep with no repeats measures nothing")
    conditions = [condition_for(level) for level in validate_levels(levels)]
    return build_schedule(conditions=conditions, blocks=repeats, seed=seed)


def num_prompts_for(level: int, *, waves: int = DEFAULT_WAVES, minimum: int = DEFAULT_MIN_PROMPTS):
    return max(minimum, waves * level)


def job_payload(
    scheduled: ScheduledRun,
    run_id: str,
    *,
    serve_args: Sequence[str],
    output_len: int,
    job_budget_s: float,
    seed: int,
    waves: int = DEFAULT_WAVES,
    min_prompts: int = DEFAULT_MIN_PROMPTS,
    diagnostics: bool = False,
) -> dict:
    """The worker's input for one (level, repeat).

    `seed + run_index` gives every run its own bench seed, so random-fallback
    prompts differ between runs. `warmup_prompts` is one wave at the level.
    `diagnostics` asks the worker for the in-container checks the first paid
    run needs (worker/sweep_handler.py `collect_diagnostics`).
    """
    level = level_of(scheduled.condition)
    return {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "level": level,
        "repeat": scheduled.block_index,
        "serve_args": list(serve_args),
        "num_prompts": num_prompts_for(level, waves=waves, minimum=min_prompts),
        "warmup_prompts": level,
        "output_len": output_len,
        "job_budget_s": job_budget_s,
        "seed": seed + scheduled.run_index,
        "diagnostics": diagnostics,
    }


@dataclass
class SweepRun:
    """One stored sweep run. Failed runs are stored too: failures are data.

    The four curve fields are top-level and None on a failed run, so the
    reducer never digs into `summary`. `summary` is the worker's compact
    summary as returned (no per-request arrays); `engine` holds parsed engine
    facts plus the raw engine log, so a parser fix can be re-applied later.
    """

    run_id: str
    run_index: int
    condition: str
    level: int
    repeat: int
    outcome: str
    latency_s: float | None = None
    ttft_median_s: float | None = None
    throughput_tps: float | None = None
    gpu_util: float | None = None
    prompt_path: str | None = None
    served_cmd: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    host: dict = field(default_factory=dict)
    clock_A: dict = field(default_factory=dict)
    clock_C: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    startup_s: float | None = None
    teardown_s: float | None = None
    drain_completed: bool | None = None
    drain_error: str | None = None
    # "runpod" or "stub", as the driver that ran the campaign named it; None on
    # a store written before this field existed. A record carries its own
    # source so a later `--reduce-only` can refuse to label a stub curve as
    # measured instead of trusting a flag typed at the time.
    source: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SweepRun":
        return cls(**d)


def _failed_status(detail: str) -> dict:
    return {"failure_class": classify_failure(detail).value, "failure_detail": detail}


# What the handler reports about its own log cap (worker/sweep_handler.py
# `capped_log`). Stored beside `log_lines` so a reader of a record can tell an
# 800-line head-and-tail from a whole log.
_LOG_CAP_KEYS = ("log_lines_total", "log_truncated", "log_head_lines")


def _engine_of(output: dict) -> dict:
    """The engine facts plus the (capped) log and what the cap did to it.

    A handler output without the cap fields (an older handler) stores them as
    None, not as `False` / `len(log_lines)`: those would claim the log was
    complete, which nothing in that output says. The alternative of leaving
    the keys out was rejected so every record has the same shape and "unknown"
    is distinguishable from "forgot to store".
    """
    return {
        **(output.get("engine") or {}),
        "log_lines": list(output.get("log_lines") or []),
        **{key: output.get(key) for key in _LOG_CAP_KEYS},
    }


# What the handler reports about its own timing and its log reader; stored on
# the record as top-level fields (see SweepRun).
_TIMING_KEYS = ("startup_s", "teardown_s", "drain_completed", "drain_error")


def _timing_of(output: dict) -> dict:
    return {key: output.get(key) for key in _TIMING_KEYS}


def build_sweep_record(
    scheduled: ScheduledRun, run_id: str, outcome, *, source: str | None = None
) -> SweepRun:
    """The `build_record` callback for `harness.campaign.run_campaign`.

    Three outcomes. The job failed or the engine never became healthy: stored
    failed, the worker's output (log lines, served command) kept from
    `diagnostics`. The engine was healthy but the measurement failed: the
    worker returns `healthy: True` -- that field means the engine answered
    `/health`, which is all `RunPodSubmitter` checks -- with `run: None` and a
    `run_error`; stored failed with that error. Otherwise stored ok.

    `source` ("runpod" / "stub") goes on every record, failed ones too, so a
    store can say where it came from without a flag that someone must remember
    to repeat at reduction time.
    """
    level = level_of(scheduled.condition)
    base = {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "condition": scheduled.condition,
        "level": level,
        "repeat": scheduled.block_index,
        "clock_A": dict(outcome.clock_A),
        "source": source,
    }
    if outcome.error is not None:
        diag = outcome.diagnostics or {}
        return SweepRun(
            **base,
            outcome="failed",
            served_cmd=list(diag.get("served_cmd") or []),
            engine=_engine_of(diag),
            **_timing_of(diag),
            host=dict(diag.get("host") or {}),
            status=_failed_status(outcome.error),
            diagnostics=dict(diag.get("diagnostics") or {}),
        )
    out = outcome.payload
    if (
        out.get("run_id") != run_id
        or out.get("level") != level
        or out.get("repeat") != scheduled.block_index
    ):
        raise ValueError(
            f"the worker answered for run_id={out.get('run_id')!r} level="
            f"{out.get('level')!r} repeat={out.get('repeat')!r}, but this job was "
            f"run_id={run_id!r} level={level} repeat={scheduled.block_index}; storing it "
            "would put another run's numbers under this one"
        )
    common = {
        "served_cmd": list(out.get("served_cmd") or []),
        "engine": _engine_of(out),
        "host": dict(out.get("host") or {}),
        "clock_C": dict(out.get("clock_C") or {}),
        "diagnostics": dict(out.get("diagnostics") or {}),
        **_timing_of(out),
    }
    run = out.get("run")
    if not run:
        detail = out.get("run_error") or "worker returned neither a run nor a run_error"
        return SweepRun(**base, outcome="failed", **common, status=_failed_status(detail))
    return SweepRun(
        **base,
        outcome="ok",
        latency_s=run["latency_s"],
        ttft_median_s=run["ttft_median_s"],
        throughput_tps=run["throughput_tps"],
        gpu_util=run["gpu_util"],
        prompt_path=run["prompt_path"],
        summary=run,
        **common,
        status={"failure_class": None, "failure_detail": None},
    )


def _distinct(values) -> list:
    values = list(values)
    present = sorted({v for v in values if v is not None})
    return present + ([None] if None in values else [])


@dataclass(frozen=True)
class CurveReduction:
    """Per-level rows, ascending by concurrency, and what they were measured with."""

    levels: tuple
    prompt_path: str
    served_cmd: tuple
    engine: dict
    # "windowed", "whole-call" or "unrecorded": how the utilisation column was
    # measured, the one value every successful run agreed on (a store that
    # disagrees is refused). Carried so a reader of the curve file, and
    # artifact 2's adapter, can say which statistic the column is.
    gpu_util_method: str

    @property
    def points(self) -> list[tuple[int, float, float, float]]:
        """`(concurrency, latency_s, throughput_tps, gpu_util)` per level."""
        return [
            (row["concurrency"], row["latency_s"], row["throughput_tps"], row["gpu_util"])
            for row in self.levels
        ]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "statistic": STATISTIC,
            "points": [list(p) for p in self.points],
            "levels": [dict(row) for row in self.levels],
            "prompt_path": self.prompt_path,
            "served_cmd": list(self.served_cmd),
            "engine": dict(self.engine),
            "gpu_util_method": self.gpu_util_method,
        }


def _median_request_throughput(runs) -> float | None:
    """The median of the level's runs' bench `request_throughput`, or None.

    From each run's `summary.bench_scalars`, written by the worker from the
    tool's saved JSON. None when ANY run lacks it: a median over the runs that
    kept it would describe a different set of runs than the level's latency,
    which is what artifact 2's Little's-law comparison sets it against. Not
    validated here (a zero or non-finite value is reported by the comparison,
    not dropped); not a curve column and has no interval.
    """
    values = [((r.summary.get("bench_scalars") or {}).get("request_throughput")) for r in runs]
    return None if None in values else median(values)


def reduce_curve(
    records,
    *,
    min_repeats: int = DEFAULT_REPEATS,
    expected_levels: Sequence[int] | None = None,
) -> CurveReduction:
    """Stored runs -> one row per level: median of the run medians, min..max.

    Refuses, rather than reduces around, every condition under which the
    result would not be one replica's curve: no successful run; two
    successful runs at one (level, repeat), which means two campaigns share a
    store; runs that took different prompt paths or ran different serve
    commands; runs whose GPU utilisation was measured by different methods (a
    windowed median for some, the whole-call median for others, or a record
    that never said which); a run with no GPU utilisation (the curve has no
    honest value to put there); a level with fewer than `min_repeats` successful runs; a
    requested level absent from the store; fewer than two levels.
    """
    records = list(records)
    ok = [r for r in records if r.outcome == "ok"]
    if not ok:
        raise ValueError("the store holds no successful run; there is no curve to reduce")
    seen: set[tuple[int, int]] = set()
    for r in ok:
        if (r.level, r.repeat) in seen:
            raise ValueError(
                f"two successful runs at level {r.level} repeat {r.repeat}; the store "
                "holds more than one campaign, and pooling them would mix engines this "
                "reduction cannot tell apart. Give each campaign its own store"
            )
        seen.add((r.level, r.repeat))
    paths = sorted({str(r.prompt_path) for r in ok})
    if len(paths) != 1:
        raise ValueError(
            f"successful runs took prompt paths {paths}; points measured on the exact "
            "prompt and on random prompts are different measurements and cannot share "
            "one curve"
        )
    commands = {tuple(r.served_cmd) for r in ok}
    if len(commands) != 1:
        raise ValueError(
            f"successful runs used {len(commands)} different serve commands; a curve "
            "from differently configured engines is not one replica's curve"
        )
    # `gpu_util_windowed` is True when the figure is the median over the
    # measured span, False when it fell back to the whole-call median (idle
    # startup and teardown included), and absent on a record written before the
    # field existed. Absent is "unknown", a third value, not a guess at either:
    # an older run could have been either, so it cannot be pooled with a known
    # one. Pooling was rejected over refusing because the median of the two
    # kinds is a number that belongs to neither statistic.
    method_names = {
        r.summary.get("gpu_util_windowed"): "unrecorded"
        if r.summary.get("gpu_util_windowed") is None
        else ("windowed" if r.summary["gpu_util_windowed"] else "whole-call")
        for r in ok
    }
    if len(method_names) > 1:
        raise ValueError(
            f"successful runs measured GPU utilisation by different methods "
            f"{sorted(method_names.values())}; the curve's utilisation column would mix "
            "two measurements (a median over the measured span and a median that includes "
            "idle startup and teardown) under one label. No reduction can leave out the "
            "differing runs, and a single level cannot be re-run alone (the sweep needs "
            "at least two levels and the reducer reads one store): re-run the whole "
            "campaign into a new store so every run used one method. That costs the "
            "whole campaign again"
        )
    (gpu_util_method,) = method_names.values()
    no_util = [r.run_id for r in ok if r.gpu_util is None]
    if no_util:
        raise ValueError(
            f"runs {no_util} have no GPU utilisation reading; the curve's utilisation "
            "column would need an invented value. Check nvidia-smi in the image"
        )
    present = sorted({r.level for r in records})
    if expected_levels is not None:
        absent = sorted(set(expected_levels) - set(present))
        if absent:
            raise ValueError(
                f"levels {absent} were requested but have no stored run; the campaign "
                "did not finish. Resume it before reducing"
            )
    failed = Counter(r.level for r in records if r.outcome != "ok")
    rows = []
    for level in present:
        runs = sorted((r for r in ok if r.level == level), key=lambda r: r.repeat)
        if len(runs) < min_repeats:
            raise ValueError(
                f"level {level} has {len(runs)} successful runs, fewer than "
                f"min_repeats={min_repeats}; its median and min-max interval would rest "
                "on fewer repeats than registered. A single level cannot be re-run "
                "alone (the sweep needs at least two levels and the reducer reads one "
                "store), so either re-run the whole campaign into a new store, which "
                "costs the whole campaign again, or reduce with a lower bar (for "
                "example `--min-repeats 2`) and disclose the reduced repeat count "
                "wherever the curve is reported"
            )
        row = {
            "concurrency": level,
            "n_runs": len(runs),
            "n_failed": failed[level],
            "run_ids": [r.run_id for r in runs],
        }
        for name in _CURVE_FIELDS:
            values = [getattr(r, name) for r in runs]
            row[name] = median(values)
            row[f"{name}_range"] = [min(values), max(values)]
        row["request_throughput"] = _median_request_throughput(runs)
        rows.append(row)
    if len(rows) < 2:
        raise ValueError(f"only level {present} is present; a curve needs at least two")
    engine = {
        key: _distinct(r.engine.get(key) for r in ok)
        for key in ("max_num_seqs", "max_num_seqs_source", "kv_capacity_tokens", "vllm_version")
    }
    return CurveReduction(
        levels=tuple(rows),
        prompt_path=paths[0],
        served_cmd=next(iter(commands)),
        engine=engine,
        gpu_util_method=gpu_util_method,
    )
