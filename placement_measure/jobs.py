"""One measurement job, chosen by `kind`: a swap, a co-location cell, or a
sleep-mode switch.

The worker handler (`worker/a4_measure_handler.py`) is a thin shell around
`measure_job`, so everything here runs in tests with injected effects. Every
output carries the payload's `run_id` and the host, because the local record
must name the run it came from and the host a run landed on, as artifact 1's
and the service sweep's records do.
"""

import os
import socket
import time
from collections.abc import Callable

from placement_measure.colocation import CellDeps, CellSpec, measure_cell
from placement_measure.engine import EngineSpec
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.swap import SwapDeps, measure_swap

__all__ = ["KINDS", "measure_job", "sleep_switch"]

KINDS = ("swap", "cell", "sleep")
TEARDOWN_RESERVE_S = 120.0
SLEEP_STEPS = ("sleep_a", "sleep_b", "wake_a", "smoke_a_after_wake")


def sleep_switch(steps: dict) -> dict:
    """The sleep probe's steps, reduced to one switch.

    The switch from serving B back to serving A costs B's sleep plus A's wake.
    It counts only if every step answered 200, including a completion from A
    after waking: a wake that returns before A can serve is not a switch.
    """
    statuses = {k: (steps.get(k) or {}).get("status") for k in SLEEP_STEPS}
    engines_up = all((steps.get(k) or {}).get("healthy") for k in ("a", "b"))
    ok = engines_up and all(s == 200 for s in statuses.values())
    return {
        "healthy": engines_up,
        "statuses": statuses,
        "switch_s": steps["sleep_b"]["seconds"] + steps["wake_a"]["seconds"] if ok else None,
        "first_request_after_wake_s": (steps.get("smoke_a_after_wake") or {}).get("seconds"),
        "memory_a_asleep_mib": (steps.get("memory_a_asleep") or {}).get("used_mib"),
        "failure": None if ok else (
            "an engine never answered /health" if not engines_up
            else f"a sleep-mode step did not answer 200: {statuses}"),
    }


def host_info() -> dict:
    return {"host_id": socket.gethostname(), "runpod_pod_id": os.environ.get("RUNPOD_POD_ID")}


def measure_job(
    payload: dict,
    *,
    swap_deps: SwapDeps | None = None,
    cell_deps: CellDeps | None = None,
    recon_deps: ReconDeps | None = None,
    host: Callable[[], dict] = host_info,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    kind = payload["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; known: {KINDS}")
    # Required and never defaulted: a run that cannot say which run it was is
    # a mislabelled point, not a slightly worse one.
    common = {"run_id": payload["run_id"], "kind": kind, "host": host()}
    t0 = clock()
    if kind == "swap":
        out = measure_swap(
            EngineSpec.from_dict(payload["a"]), EngineSpec.from_dict(payload["b"]),
            cold=bool(payload["cold"]), hf_home=payload["hf_home"],
            release_tolerance_mib=payload["release_tolerance_mib"],
            release_timeout_s=payload["release_timeout_s"], deps=swap_deps,
        )
    elif kind == "sleep":
        probe = run_probe({"probe": "sleep", "job_budget_s": payload["job_budget_s"],
                           "a": payload["a"], "b": payload["b"]}, recon_deps)
        out = {**sleep_switch(probe["result"]), "steps": probe["result"]}
    else:
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
        b = payload.get("b")
        out = measure_cell(
            EngineSpec.from_dict(payload["a"]), None if b is None else EngineSpec.from_dict(b),
            CellSpec(**payload["cell"]), deadline=deadline, deps=cell_deps,
        )
    return {**out, **common, "elapsed_s": clock() - t0}
