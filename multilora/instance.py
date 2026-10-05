"""One server instance, end to end, inside the worker (amendment §4).

1. Make every registered adapter present on local disk: synthetic ones are
   written (or reused when a matching copy already exists on this worker), real
   ones are downloaded at their pinned revision.
2. Start the engine with one slot per adapter.
3. Untimed warm-up: every registered adapter serves `w` requests.
4. The timed phases, in the payload's order, with the gauge sampler running.
5. Return the payload contract documented in `multilora.records`.

Every external effect goes through `Deps`, so tests drive the whole sequence
with fakes and the worker supplies the real ones.
"""

import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from multilora.adapters import adapter_checksum, write_synthetic_adapter
from multilora.sampler import GaugeSampler
from multilora.serving import adapter_path, run_phase, serve, serve_args

_MARKER = "a5_params.json"


@dataclass
class Deps:
    model_config: Callable[[str, str], dict]
    download_adapter: Callable[[str, str, str], None]
    http_get: Callable[[str], str]
    host_info: Callable[[], dict]
    served: Callable | None = None
    run_bench: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def synthetic_seed(adapter_seed: int, name: str) -> int:
    """Deterministic per adapter: the sweep's a00..a63 and the gate's s00..s07
    never share a stream."""
    offset = 0 if name.startswith("a") else 5_000
    return adapter_seed * 10_000 + offset + int(name[1:])


def ensure_synthetic(name: str, *, config: dict, model: str, rank: int, target_modules, seed: int) -> str:
    """Write the adapter unless this worker already holds one written with the
    same parameters; either way return its checksum. A 64-slot instance would
    otherwise rewrite ~4 GB of identical weights on every job."""
    path = adapter_path(name)
    params = {
        "config": config, "model": model, "rank": rank,
        "target_modules": sorted(target_modules), "seed": seed,
    }
    marker = os.path.join(path, _MARKER)
    if os.path.exists(marker):
        with open(marker) as f:
            if json.load(f) == params:
                return adapter_checksum(path)
    checksum = write_synthetic_adapter(
        path, config=config, base_model=model, rank=rank, target_modules=target_modules, seed=seed
    )
    with open(marker, "w") as f:
        json.dump(params, f)
    return checksum


def prepare_adapters(payload: dict, *, model: str, revision: str, rank: int, target_modules, deps: Deps) -> dict:
    config = deps.model_config(model, revision)
    real = {r["name"]: r for r in payload.get("real_adapters", [])}
    checksums = {}
    for name in payload["registered"]:
        if name in real:
            deps.download_adapter(real[name]["repo"], real[name]["revision"], adapter_path(name))
            checksums[name] = adapter_checksum(adapter_path(name))
        else:
            checksums[name] = ensure_synthetic(
                name, config=config, model=model, rank=rank, target_modules=target_modules,
                seed=synthetic_seed(payload["adapter_seed"], name),
            )
    return checksums


def run_instance(
    payload: dict,
    *,
    model: str,
    revision: str,
    max_model_len: int,
    rank: int,
    target_modules,
    env: dict,
    deps: Deps,
    after_ready: Callable | None = None,
) -> dict:
    t0 = deps.clock()
    checksums = prepare_adapters(
        payload, model=model, revision=revision, rank=rank, target_modules=target_modules, deps=deps
    )
    setup_s = deps.clock() - t0
    args = serve_args(
        revision=revision,
        max_model_len=max_model_len,
        n_slots=payload["n_slots"],
        rank=rank,
        lora_modules={name: adapter_path(name) for name in payload["registered"]},
        specialize_active_lora=payload["specialize_active_lora"],
        disable_log_stats=payload["disable_log_stats"],
    )
    common = {
        "served_cmd": ["vllm", "serve", model, *args],
        "host": deps.host_info(),
        "adapters": checksums,
        "setup_s": setup_s,
    }
    t_start = deps.clock()
    with serve(model, args, env, served=deps.served) as server, tempfile.TemporaryDirectory() as tmp:
        startup_s = deps.clock() - t_start
        if not server.healthy:
            return {"healthy": False, "log_lines": list(server.log_lines), "startup_s": startup_s, **common}
        extra = after_ready(server) if after_ready else {}

        def phase(adapters, n, seed, sub):
            return run_phase(
                server.base_url, model=model, adapters=adapters,
                concurrency=payload["concurrency"], num_requests=n,
                dataset_args=payload["dataset_args"], seed=seed,
                result_dir=os.path.join(tmp, sub), run_bench=deps.run_bench,
            )

        warm = phase(
            payload["registered"],
            payload["warmup_requests_per_adapter"] * len(payload["registered"]),
            payload["run_index"], "warmup",
        )
        sampler = GaugeSampler(
            lambda: deps.http_get(f"{server.base_url}/metrics"), payload["scrape_interval_s"]
        )
        phases = []
        with sampler:
            for spec in payload["phases"]:
                sampler.set_phase(spec["phase_index"])
                result = phase(
                    spec["adapters"], payload["requests_per_phase"],
                    payload["run_index"] * 100 + spec["phase_index"], f"phase{spec['phase_index']}",
                )
                sampler.set_phase(None)
                phases.append({**spec, **result})
        return {
            "healthy": True,
            "log_lines": list(server.log_lines),
            "startup_s": startup_s,
            "warmup": {"num_requests": warm["num_requests"], "failed": warm["failed"]},
            "phases": phases,
            "gauge_samples": sampler.samples,
            **common,
            **extra,
        }
