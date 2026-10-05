"""One measurement job: a swap, or a co-location cell, chosen by `kind`.

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
from placement_measure.swap import SwapDeps, measure_swap

__all__ = ["KINDS", "measure_job"]

KINDS = ("swap", "cell")
TEARDOWN_RESERVE_S = 120.0


def host_info() -> dict:
    return {"host_id": socket.gethostname(), "runpod_pod_id": os.environ.get("RUNPOD_POD_ID")}


def measure_job(
    payload: dict,
    *,
    swap_deps: SwapDeps | None = None,
    cell_deps: CellDeps | None = None,
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
    else:
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
        b = payload.get("b")
        out = measure_cell(
            EngineSpec.from_dict(payload["a"]), None if b is None else EngineSpec.from_dict(b),
            CellSpec(**payload["cell"]), deadline=deadline, deps=cell_deps,
        )
    return {**out, **common, "elapsed_s": clock() - t0}
