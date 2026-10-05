"""One process-level swap: engine A serving, torn down, its memory released,
optionally its successor's weights evicted from the page cache, engine B up.

The swap's duration is the sum of the three parts a fleet pays between the
victim draining and the incoming model serving: `teardown_s` (A's process
exiting, from `Server.stop()`), `release.seconds` (the card's memory back at
its idle level), and `b_startup_s` (B from spawn to answering `/health`). The
simulator draws from the distribution of that sum (amendment §5). Draining A's
in-flight requests is the simulator's own business and is not measured here:
A serves nothing in this job.

Engines run with `HF_HUB_OFFLINE=1`. Weights must already be on the network
volume (reconnaissance's `stage` probe puts them there); a download in the
middle of a measured swap would read as a very slow swap and be published as
one.

`healthy` in the result means both engines answered `/health`. That is the
field `RunPodSubmitter` treats as success, so a swap whose B never came up is
stored as failed with this output as its diagnostics.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from placement_measure.engine import EngineSpec, engine_facts, log_tail

__all__ = ["ENGINE_ENV", "SwapDeps", "measure_swap"]

ENGINE_ENV = {"HF_HUB_OFFLINE": "1"}
PORT = 8000


@dataclass
class SwapDeps:
    """The effects, injectable so tests run a swap without an engine or a GPU.
    None means the real one, resolved lazily so importing needs no vLLM."""

    served: Callable | None = None
    read_memory: Callable | None = None
    wait_for_release: Callable | None = None
    make_cold: Callable | None = None
    weight_files: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: SwapDeps) -> SwapDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.read_memory is None or d.wait_for_release is None:
        from placement_measure import gpu_memory

        d.read_memory = d.read_memory or gpu_memory.read_memory
        d.wait_for_release = d.wait_for_release or gpu_memory.wait_for_release
    if d.make_cold is None or d.weight_files is None:
        from placement_measure import pagecache

        d.make_cold = d.make_cold or pagecache.make_cold
        d.weight_files = d.weight_files or pagecache.weight_files
    return d


def _engine_part(spec: EngineSpec, server, startup_s: float) -> dict:
    lines = list(server.log_lines)
    return {
        "spec": spec.to_dict(),
        "healthy": bool(server.healthy),
        "startup_s": startup_s,
        "served_cmd": list(server.cmd),
        "facts": engine_facts(lines),
        **log_tail(lines),
    }


def measure_swap(
    a: EngineSpec,
    b: EngineSpec,
    *,
    cold: bool,
    hf_home: str,
    release_tolerance_mib: float,
    release_timeout_s: float,
    deps: SwapDeps | None = None,
) -> dict:
    d = _resolve(deps or SwapDeps())
    baseline = d.read_memory()
    t0 = d.clock()
    with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT) as sa:
        part_a = _engine_part(a, sa, d.clock() - t0)
        teardown_s = sa.stop()
    out = {"cold": cold, "baseline_memory": baseline, "a": part_a, "teardown_s": teardown_s}
    if not part_a["healthy"]:
        return {**out, "healthy": False, "b": None, "swap_s": None,
                "failure": "engine A never answered /health; there is no swap to time"}
    if baseline["used_mib"] is None:
        return {**out, "healthy": False, "b": None, "swap_s": None,
                "failure": "the idle memory reading failed, so release has no target"}
    release = d.wait_for_release(
        baseline["used_mib"] + release_tolerance_mib, timeout_s=release_timeout_s
    )
    cache = d.make_cold(d.weight_files(hf_home, b.model, b.revision)) if cold else {"requested": False}
    t1 = d.clock()
    with d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=PORT) as sb:
        part_b = _engine_part(b, sb, d.clock() - t1)
        sb.stop()
    ok = part_b["healthy"] and release["released"]
    return {
        **out,
        "healthy": part_b["healthy"],
        "release": release,
        "cache": cache,
        "b": part_b,
        "swap_s": teardown_s + release["seconds"] + part_b["startup_s"] if ok else None,
        "failure": None if ok else (
            "engine B never answered /health" if not part_b["healthy"]
            else "A's memory was not released within the timeout"
        ),
    }
