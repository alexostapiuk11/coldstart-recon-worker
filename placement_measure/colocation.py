"""One cell of the co-location grid: a measured load on engine A while engine B,
resident on the same card, carries a held background load.

The cell's output is A's latency at its own concurrency `own` with its
neighbour at concurrency `neighbour` -- one point of the two-load surface
`placement.colocated.ColocatedSurface` interpolates (amendment §1e item 3).
Three kinds of cell, all on the same code:

- `neighbour is None`: A alone at full memory. The solo curve.
- `neighbour == 0`: A at the split, B resident and idle. The solo-at-split
  curve, the surface's first column.
- `neighbour > 0`: A at the split under B's load.

The measured run is `harness.sweep_worker.run_one`, the service sweep's own:
one warm-up, then one `vllm bench serve` at `own`, summarised under the shared
failure rule, so a co-located latency and a solo one mean the same thing. Its
prompts are random at a fixed length (`random_dataset_args`), because artifact
4's request shape is its own (amendment §4) and the image cannot run the
custom dataset (pandas is absent, artifact 2's pilot, 2026-10-04).

Why the neighbour's load is checked rather than assumed. The neighbour runs
its own bench client on a thread, sized to outlast the measured run and
stopped as soon as the measured run ends. Before the measured run starts, the
cell waits until B reports at least `neighbour` requests running; during it,
`vllm:num_requests_running` on B is sampled. A neighbour that finished early,
or never reached its load, leaves the cell flagged in its own output rather
than silently measured against a lighter neighbour.

Engines start one after the other (A, then B). vLLM sizes its KV cache from a
profiling pass, and two engines profiling at once would each see the other's
allocations as they happen; whether that changes the result is UNVERIFIED,
and serial startup removes the question.
"""

import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness.bench import BenchError
from harness.stats import median
from harness.sweep_worker import PromptPlan, random_dataset_args
from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV

__all__ = ["PROMPT_PATH", "CellDeps", "CellSpec", "measure_cell", "stoppable_run"]

PORT_MEASURED = 8000
PORT_NEIGHBOUR = 8001
PROMPT_PATH = "random-fixed-length"
NEIGHBOUR_SEED_OFFSET = 700_000
STOP_POLL_S = 0.5


@dataclass(frozen=True)
class CellSpec:
    own: int
    neighbour: int | None
    input_len: int
    output_len: int
    num_prompts: int
    warmup_prompts: int
    neighbour_prompts: int
    seed: int
    ramp_timeout_s: float = 60.0

    def __post_init__(self) -> None:
        if type(self.own) is not int or self.own < 1:
            raise ValueError(f"own concurrency must be a positive int, got {self.own!r}")
        if self.neighbour is not None and (type(self.neighbour) is not int or self.neighbour < 0):
            raise ValueError(
                f"neighbour must be None (solo) or an int >= 0, got {self.neighbour!r}"
            )
        if self.neighbour and self.neighbour_prompts < 1:
            raise ValueError("a loaded neighbour needs neighbour_prompts to send")


def stoppable_run(stop: threading.Event, popen: Callable = subprocess.Popen) -> Callable:
    """A `subprocess.run` stand-in for `harness.bench.run_bench` that ends the
    tool early when `stop` is set.

    `run_bench` has no way to cancel a run, and the neighbour's load must end
    when the measured run does, or the job pays for minutes of load nobody
    reads. Output goes to temporary files rather than pipes, so a chatty tool
    cannot fill a pipe nobody reads and block. A stopped run exits non-zero,
    and `run_bench` raises `BenchError`, which the neighbour thread expects.
    """

    def run(cmd, *, capture_output, text, check, timeout=None):
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            proc = popen(cmd, stdout=out, stderr=err, text=True)
            deadline = None if timeout is None else time.monotonic() + timeout
            while proc.poll() is None:
                if stop.wait(STOP_POLL_S) or (deadline is not None and time.monotonic() > deadline):
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            out.seek(0)
            err.seek(0)
            return subprocess.CompletedProcess(cmd, proc.returncode, out.read(), err.read())

    return run


@dataclass
class CellDeps:
    served: Callable | None = None
    run_one: Callable | None = None
    run_bench: Callable | None = None
    sampler_factory: Callable | None = None
    running_sampler: Callable | None = None
    wait_running: Callable | None = None
    stoppable: Callable = stoppable_run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: CellDeps) -> CellDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.run_one is None:
        from harness.sweep_worker import run_one

        d.run_one = run_one
    if d.run_bench is None:
        from harness.bench import run_bench

        d.run_bench = run_bench
    if d.sampler_factory is None:
        from harness.gpu_util import GpuUtilSampler

        d.sampler_factory = GpuUtilSampler
    if d.running_sampler is None or d.wait_running is None:
        from placement_measure import metrics

        d.running_sampler = d.running_sampler or metrics.RunningSampler
        d.wait_running = d.wait_running or metrics.wait_running
    return d


def _engine(spec: EngineSpec, server) -> dict:
    lines = list(server.log_lines)
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "served_cmd": list(server.cmd),
            "facts": engine_facts(lines), **log_tail(lines)}


def _plan(cell: CellSpec) -> PromptPlan:
    return PromptPlan(
        path=PROMPT_PATH,
        dataset_args=tuple(random_dataset_args(input_len=cell.input_len, output_len=cell.output_len)),
        prompt_tokens=cell.input_len,
    )


def _measure(d: CellDeps, server, spec: EngineSpec, cell: CellSpec, workdir, deadline) -> dict:
    return d.run_one(
        server.base_url, model=spec.model, level=cell.own, num_prompts=cell.num_prompts,
        warmup_prompts=cell.warmup_prompts, plan=_plan(cell), seed=cell.seed, workdir=workdir,
        run_bench=d.run_bench, sampler_factory=d.sampler_factory, deadline=deadline, clock=d.clock,
    )


def _loaded(d: CellDeps, ea, eb, a: EngineSpec, b: EngineSpec, cell: CellSpec, workdir, deadline):
    stop = threading.Event()
    finished = threading.Event()
    state: dict = {}

    def load() -> None:
        try:
            d.run_bench(
                eb.base_url, model=b.model, max_concurrency=cell.neighbour,
                num_prompts=cell.neighbour_prompts, dataset_args=list(_plan(cell).dataset_args),
                ignore_eos=True, seed=cell.seed + NEIGHBOUR_SEED_OFFSET,
                result_dir=Path(workdir) / "neighbour", run=d.stoppable(stop),
            )
            state["ended"] = "finished"
        except BenchError as e:
            state["ended"] = "stopped" if stop.is_set() else f"error: {e}"[:400]
        finally:
            finished.set()

    thread = threading.Thread(target=load, daemon=True)
    thread.start()
    try:
        ramp = d.wait_running(eb.base_url, at_least=cell.neighbour, timeout_s=cell.ramp_timeout_s)
        with d.running_sampler(eb.base_url) as sampler:
            run = _measure(d, ea, a, cell, workdir, deadline)
        # Read before `stop` is set: a neighbour that ended by then ran out of
        # prompts during the measured run, so part of that run was measured
        # against a lighter neighbour than the cell is labelled with.
        ended_early = finished.is_set()
    finally:
        stop.set()
        thread.join(timeout=30)
    values = sampler.values()
    return run, {
        "level": cell.neighbour,
        "ramp": ramp,
        "samples": sampler.samples,
        "median_running": median(values) if values else None,
        "min_running": min(values) if values else None,
        "ended": state.get("ended"),
        "ended_before_measured_run": ended_early,
    }


def measure_cell(
    a: EngineSpec,
    b: EngineSpec | None,
    cell: CellSpec,
    *,
    deadline: float | None = None,
    deps: CellDeps | None = None,
) -> dict:
    d = _resolve(deps or CellDeps())
    common = {"cell": asdict(cell)}
    with tempfile.TemporaryDirectory() as tmp:
        if cell.neighbour is None:
            with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT_MEASURED) as ea:
                engines = {"measured": _engine(a, ea), "neighbour": None}
                if not ea.healthy:
                    return {**common, "healthy": False, "engines": engines, "run": None,
                            "run_error": None, "neighbour_load": None}
                try:
                    run, run_error = _measure(d, ea, a, cell, os.path.join(tmp, "m"), deadline), None
                except Exception as e:  # noqa: BLE001 -- failures are data; the log must survive
                    run, run_error = None, f"{type(e).__name__}: {e}"
                ea.stop()
            return {**common, "healthy": True, "engines": engines, "run": run,
                    "run_error": run_error, "neighbour_load": None}
        if b is None:
            raise ValueError("a co-located cell needs the neighbour's engine spec")
        with (
            d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT_MEASURED) as ea,
            d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=PORT_NEIGHBOUR) as eb,
        ):
            engines = {"measured": _engine(a, ea), "neighbour": _engine(b, eb)}
            if not (ea.healthy and eb.healthy):
                return {**common, "healthy": False, "engines": engines, "run": None,
                        "run_error": None, "neighbour_load": None}
            try:
                if cell.neighbour == 0:
                    run = _measure(d, ea, a, cell, os.path.join(tmp, "m"), deadline)
                    neighbour_load = {"level": 0}
                else:
                    run, neighbour_load = _loaded(d, ea, eb, a, b, cell, tmp, deadline)
                run_error = None
            except Exception as e:  # noqa: BLE001 -- failures are data; the logs must survive
                run, neighbour_load, run_error = None, None, f"{type(e).__name__}: {e}"
            eb.stop()
            ea.stop()
        engines = {"measured": _engine(a, ea), "neighbour": _engine(b, eb)}
    return {**common, "healthy": True, "engines": engines, "run": run, "run_error": run_error,
            "neighbour_load": neighbour_load}
