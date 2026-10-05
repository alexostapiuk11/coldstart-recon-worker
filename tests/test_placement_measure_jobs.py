"""The measurement job, end to end through the harness's JSON-round-tripping
stub submitter, and the two handlers."""

import sys
from pathlib import Path

import pytest
from a4_fakes import Clock, FakeEngines, memory_script
from test_placement_measure_colocation import _cell
from test_placement_measure_colocation import _deps as cell_deps

from harness.submit import PayloadStubSubmitter
from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.jobs import measure_job
from placement_measure.swap import SwapDeps

ROOT = Path(__file__).resolve().parents[1]
A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


def _swap_deps(clock, healthy=None):
    run = memory_script([500, 9000, 500])
    return SwapDeps(
        served=FakeEngines(clock, healthy=healthy).served, read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda t, timeout_s: wait_for_release(
            t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock)


def _swap_payload(**over):
    return {"kind": "swap", "run_id": "r1", "a": A.to_dict(), "b": B.to_dict(), "cold": True,
            "hf_home": "/vol/hf", "release_tolerance_mib": 256, "release_timeout_s": 60,
            "job_budget_s": 1800, **over}


def _host():
    return {"host_id": "h1", "runpod_pod_id": None}


def test_a_swap_job_survives_the_json_round_trip_and_reads_as_success():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(p, swap_deps=_swap_deps(clock), host=_host,
                                                     clock=clock))
    outcome = sub.submit_payload(_swap_payload())
    assert outcome.error is None
    assert outcome.payload["run_id"] == "r1" and outcome.payload["swap_s"] > 0


def test_a_failed_swap_reaches_the_submitter_as_a_failure_with_diagnostics():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(
        p, swap_deps=_swap_deps(clock, healthy={B.model: False}), host=_host, clock=clock))
    outcome = sub.submit_payload(_swap_payload())
    assert outcome.payload is None and outcome.diagnostics["b"]["log_tail"]


def test_a_cell_job_survives_the_json_round_trip():
    clock = Clock()
    deps, _, _ = cell_deps(clock)
    payload = {"kind": "cell", "run_id": "r2", "a": A.to_dict(), "b": B.to_dict(),
               "cell": vars(_cell(8)), "job_budget_s": 1800}
    sub = PayloadStubSubmitter(lambda p: measure_job(p, cell_deps=deps, host=_host, clock=clock))
    outcome = sub.submit_payload(payload)
    assert outcome.error is None and outcome.payload["neighbour_load"]["level"] == 8


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown kind"):
        measure_job({"kind": "guess", "run_id": "x"})


def test_the_handlers_import_without_the_runpod_sdk():
    sys.path.insert(0, str(ROOT / "worker"))
    import a4_measure_handler
    import a4_recon_handler

    assert callable(a4_measure_handler.handler) and callable(a4_recon_handler.handler)
