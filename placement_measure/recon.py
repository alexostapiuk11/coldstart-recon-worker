"""Artifact 4's reconnaissance probes. Capture-only: nothing here is a result.

Each probe answers one question the amendment leaves to reconnaissance, and
returns raw readings; `placement_measure.recon_report` turns the saved outputs
into answers. One probe per job, so a probe that hangs or dies loses only its
own question.

| probe         | question (amendment section)                                        |
|---------------|---------------------------------------------------------------------|
| `stage`       | put every pinned checkpoint on the network volume before any timing |
| `coresidency` | do two engines fit at the split, with how much KV each (§3 go/no-go)|
| `swaps`       | compile reuse per target, page-cache eviction, memory release (§3, §5)|
| `early_start` | does an engine start while the previous one's memory is held (§5)   |
| `sleep`       | does sleep mode work, and what does a sleep-based swap cost (§6)    |
| `help`        | does the pinned image accept every flag artifact 4 passes           |

Considered and not probed: vLLM 0.27.1's development weight-update endpoints
(`/update_weights` and the weight-transfer engine under
vllm/entrypoints/serve/dev/rlhf). They load weights pushed by a training peer
over a transfer engine, not a checkpoint from disk, so they are not a serving
swap.

`healthy` in every probe's output means the probe ran to its end, which is the
field `RunPodSubmitter` treats as success. An engine that failed to start is
an answer here -- for `coresidency` it is the go/no-go's "no" -- not a failed
job, and the per-engine `healthy` fields carry it.
"""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV, SwapDeps, measure_swap

__all__ = ["PROBES", "ReconDeps", "run_probe"]

TEARDOWN_RESERVE_S = 120.0
# A swap needs two engine starts and a release wait; one is not started with
# less than this left, because a job the platform kills returns nothing. Once a
# swap has run in this job, the bar rises to SWAP_BUDGET_MARGIN times the
# longest one so far: a fixed floor alone admitted a swap that overran when the
# engines started slower than the floor assumed.
MIN_SWAP_BUDGET_S = 400.0
SWAP_BUDGET_MARGIN = 1.25
SMOKE = {"prompt": "Hello", "max_tokens": 4}
DEV_ENV = {"VLLM_SERVER_DEV_MODE": "1"}
SERVE_FLAGS = ("--enable-sleep-mode", "--gpu-memory-utilization", "--max-num-seqs",
               "--max-model-len", "--no-enable-prefix-caching", "--revision")
BENCH_FLAGS = ("--random-input-len", "--random-output-len", "--random-range-ratio",
               "--random-prefix-len", "--max-concurrency", "--ignore-eos")


@dataclass
class ReconDeps:
    served: Callable | None = None
    read_memory: Callable | None = None
    swap_deps: SwapDeps | None = None
    snapshot_download: Callable | None = None
    post: Callable = requests.post
    get: Callable = requests.get
    run_command: Callable = subprocess.run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: ReconDeps) -> ReconDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.read_memory is None:
        from placement_measure.gpu_memory import read_memory

        d.read_memory = read_memory
    if d.swap_deps is None:
        d.swap_deps = SwapDeps(served=d.served, read_memory=d.read_memory, clock=d.clock)
    if d.snapshot_download is None:
        from huggingface_hub import snapshot_download

        d.snapshot_download = snapshot_download
    return d


def _timed(d: ReconDeps, fn: Callable) -> dict:
    t0 = d.clock()
    try:
        r = fn()
        body = r.text[:500]
        return {"status": r.status_code, "seconds": d.clock() - t0, "body": body, "error": None}
    except Exception as e:  # noqa: BLE001 -- an endpoint that is absent is the answer
        return {"status": None, "seconds": d.clock() - t0, "body": None, "error": repr(e)[:300]}


def _smoke(d: ReconDeps, server, model: str) -> dict:
    return _timed(d, lambda: d.post(f"{server.base_url}/v1/completions",
                                    json={"model": model, **SMOKE}, timeout=60))


def _engine(spec: EngineSpec, server) -> dict:
    lines = list(server.log_lines)
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "served_cmd": list(server.cmd),
            "facts": engine_facts(lines), **log_tail(lines)}


def probe_stage(p: dict, d: ReconDeps, deadline: float) -> dict:
    staged = []
    for m in p["models"]:
        t0 = d.clock()
        try:
            path = d.snapshot_download(repo_id=m["model"], revision=m["revision"])
            staged.append({**m, "path": str(path), "seconds": d.clock() - t0, "error": None})
        except Exception as e:  # noqa: BLE001 -- one missing checkpoint must not hide the rest
            staged.append({**m, "path": None, "seconds": d.clock() - t0, "error": repr(e)[:300]})
        if d.clock() >= deadline:
            break
    return {"staged": staged, "complete": len(staged) == len(p["models"])
            and all(s["error"] is None for s in staged)}


def probe_coresidency(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    idle = d.read_memory()
    with (
        d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=8000) as ea,
        d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=8001) as eb,
    ):
        both = d.read_memory()
        smoke = {
            "a": _smoke(d, ea, a.model) if ea.healthy else None,
            "b": _smoke(d, eb, b.model) if eb.healthy else None,
        }
        eb.stop()
        ea.stop()
    return {"idle_memory": idle, "both_memory": both, "smoke": smoke,
            "engines": {"a": _engine(a, ea), "b": _engine(b, eb)}}


def probe_swaps(p: dict, d: ReconDeps, deadline: float) -> dict:
    results, skipped = [], []
    longest = 0.0
    for s in p["swaps"]:
        if deadline - d.clock() < max(MIN_SWAP_BUDGET_S, SWAP_BUDGET_MARGIN * longest):
            skipped.append(s)
            continue
        started = d.clock()
        results.append(measure_swap(
            EngineSpec.from_dict(s["a"]), EngineSpec.from_dict(s["b"]), cold=bool(s["cold"]),
            hf_home=p["hf_home"], release_tolerance_mib=p["release_tolerance_mib"],
            release_timeout_s=p["release_timeout_s"], deps=d.swap_deps,
        ))
        longest = max(longest, d.clock() - started)
    return {"swaps": results, "skipped_for_budget": skipped}


def probe_early_start(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=8000) as ea:
        first = _engine(a, ea)
        teardown_s = ea.stop()
    at_start = d.read_memory()
    with d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=8000) as eb:
        second = _engine(b, eb)
        eb.stop()
    return {"a": first, "teardown_s": teardown_s, "memory_when_b_started": at_start, "b": second}


def probe_sleep(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    env = {**ENGINE_ENV, **DEV_ENV}
    steps: dict = {}
    with d.served(a.model, args=a.serve_args(), env=env, port=8000) as ea:
        steps["a"] = _engine(a, ea)
        if ea.healthy:
            steps["memory_a_awake"] = d.read_memory()
            steps["sleep_a"] = _timed(d, lambda: d.post(f"{ea.base_url}/sleep?level=1", timeout=300))
            steps["is_sleeping_a"] = _timed(d, lambda: d.get(f"{ea.base_url}/is_sleeping", timeout=10))
            steps["memory_a_asleep"] = d.read_memory()
            with d.served(b.model, args=b.serve_args(), env=env, port=8001) as eb:
                steps["b"] = _engine(b, eb)
                if eb.healthy:
                    steps["memory_b_awake_a_asleep"] = d.read_memory()
                    steps["sleep_b"] = _timed(d, lambda: d.post(f"{eb.base_url}/sleep?level=1", timeout=300))
                    steps["wake_a"] = _timed(d, lambda: d.post(f"{ea.base_url}/wake_up", timeout=300))
                    steps["smoke_a_after_wake"] = _smoke(d, ea, a.model)
                    steps["memory_a_awake_b_asleep"] = d.read_memory()
                eb.stop()
            ea.stop()
    return steps


def probe_help(p: dict, d: ReconDeps, deadline: float) -> dict:
    out = {}
    for name, cmd, flags in (
        ("serve", ["vllm", "serve", "--help=all"], SERVE_FLAGS),
        ("bench", ["vllm", "bench", "serve", "--help=all"], BENCH_FLAGS),
    ):
        try:
            proc = d.run_command(cmd, capture_output=True, text=True, check=False, timeout=60)
            text = proc.stdout or ""
            out[name] = {"returncode": proc.returncode,
                         "missing": [f for f in flags if f not in text], "error": None}
        except Exception as e:  # noqa: BLE001 -- a missing tool is the answer
            out[name] = {"returncode": None, "missing": list(flags), "error": repr(e)[:300]}
    return out


PROBES = {
    "stage": probe_stage,
    "coresidency": probe_coresidency,
    "swaps": probe_swaps,
    "early_start": probe_early_start,
    "sleep": probe_sleep,
    "help": probe_help,
}


def run_probe(payload: dict, deps: ReconDeps | None = None) -> dict:
    name = payload["probe"]
    if name not in PROBES:
        raise ValueError(f"unknown probe {name!r}; known: {sorted(PROBES)}")
    d = _resolve(deps or ReconDeps())
    t0 = d.clock()
    deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
    result = PROBES[name](payload, d, deadline)
    return {"healthy": True, "probe": name, "label": payload.get("label"),
            "elapsed_s": d.clock() - t0, "result": result}
