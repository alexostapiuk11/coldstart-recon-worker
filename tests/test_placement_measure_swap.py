"""A process-level swap, against fake engines, memory and cache.

A's engine takes 40 s of fake time to start, B's 25 s; `stop()` returns
0.5 s; memory reads 9000 MiB twice then falls to idle. So the swap is
teardown 0.5 + release (two 0.25 s polls) + B's 25 s.
"""

import pytest
from a4_fakes import Clock, FakeEngines, memory_script

from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.swap import SwapDeps, measure_swap

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.92, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.92, 2048, 256)


def _deps(engines, clock, readings, cache_calls):
    run = memory_script(readings)
    return SwapDeps(
        served=engines.served,
        read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda target, timeout_s: wait_for_release(
            target, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: cache_calls.append(paths) or {"requested": True, "files": paths},
        weight_files=lambda hf_home, model, revision: [f"{hf_home}/{model}@{revision}"],
        clock=clock,
    )


def _swap(cold=False, healthy=None, readings=(500, 9000, 9000, 500)):
    clock = Clock()
    engines = FakeEngines(clock, startup_s={A.model: 40.0, B.model: 25.0}, healthy=healthy,
                          compile_s={B.model: 0.33})
    cache_calls = []
    out = measure_swap(A, B, cold=cold, hf_home="/vol/hf", release_tolerance_mib=256,
                       release_timeout_s=60, deps=_deps(engines, clock, list(readings), cache_calls))
    return out, engines, cache_calls


def test_the_swap_is_teardown_plus_release_plus_bring_up():
    out, engines, _ = _swap()
    assert out["healthy"]
    assert out["teardown_s"] == 0.5
    assert out["release"]["released"] and out["release"]["seconds"] == pytest.approx(0.5)
    assert out["b"]["startup_s"] == pytest.approx(25.0)
    assert out["swap_s"] == pytest.approx(0.5 + 0.5 + 25.0)
    assert [s.model for s in engines.started] == [A.model, B.model]


def test_the_release_target_is_the_idle_reading_plus_the_tolerance():
    out, _, _ = _swap()
    assert out["baseline_memory"]["used_mib"] == 500
    assert out["release"]["target_used_mib"] == 756


def test_the_incoming_models_compile_state_is_read_from_its_log():
    out, _, _ = _swap()
    assert out["b"]["facts"]["s4b_s"] == 0.33
    assert out["a"]["facts"]["s4b_s"] == 19.0


def test_a_cold_swap_evicts_the_incoming_models_weights_and_records_it():
    out, _, calls = _swap(cold=True)
    assert calls == [[f"/vol/hf/{B.model}@rb"]]
    assert out["cache"]["requested"]
    warm, _, none = _swap(cold=False)
    assert none == [] and warm["cache"] == {"requested": False}


def test_an_unhealthy_incoming_engine_is_a_failed_swap_with_its_log():
    out, _, _ = _swap(healthy={B.model: False})
    assert not out["healthy"] and out["swap_s"] is None
    assert "never answered" in out["failure"]
    assert out["b"]["log_tail"]


def test_an_unhealthy_outgoing_engine_never_starts_the_successor():
    out, engines, _ = _swap(healthy={A.model: False})
    assert not out["healthy"]
    assert [s.model for s in engines.started] == [A.model]


def test_memory_that_is_never_released_leaves_no_swap_time():
    out, _, _ = _swap(readings=(500, 9000))
    assert not out["release"]["released"]
    assert out["swap_s"] is None and "not released" in out["failure"]
