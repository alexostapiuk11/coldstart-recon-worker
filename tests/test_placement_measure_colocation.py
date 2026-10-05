"""One co-location cell, against fake engines, bench and samplers."""

import contextlib
import threading

import pytest
from a4_fakes import Clock, FakeEngines

from harness.bench import BenchError
from placement_measure.colocation import CellDeps, CellSpec, measure_cell, stoppable_run
from placement_measure.engine import EngineSpec

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


def _cell(neighbour, **over):
    return CellSpec(**{"own": 8, "neighbour": neighbour, "input_len": 1024, "output_len": 256,
                       "num_prompts": 160, "warmup_prompts": 8, "neighbour_prompts": 100_000,
                       "seed": 7, **over})


class FakeSampler:
    def __init__(self, base_url, values):
        self.base_url = base_url
        self.samples = [{"t_s": i * 0.5, "running": v, "error": None} for i, v in enumerate(values)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def values(self):
        return [s["running"] for s in self.samples]


def _deps(clock, *, neighbour_finishes=False, reached=True, healthy=None, run_one=None):
    engines = FakeEngines(clock, healthy=healthy)
    calls = {"run_one": [], "bench": []}

    def fake_run_one(base_url, **kw):
        calls["run_one"].append((base_url, kw))
        if neighbour_finishes:
            # The fake neighbour returns at once; a measured run lasts far
            # longer than the microseconds its thread needs to finish.
            threading.Event().wait(0.2)
        return {"latency_s": 0.8, "plan": kw["plan"].to_dict(), "level": kw["level"]}

    def fake_bench(base_url, **kw):
        calls["bench"].append((base_url, kw))
        stop_run = kw["run"]
        if neighbour_finishes:
            return {"completed": 1}
        # Block like a long tool run until the cell stops it, then fail the way
        # a terminated tool does.
        stop_run.stop.wait(5)
        raise BenchError("vllm bench serve exited -15")

    def fake_stoppable(stop):
        run = lambda *a, **k: None
        run.stop = stop
        return run

    deps = CellDeps(
        served=engines.served, run_one=run_one or fake_run_one, run_bench=fake_bench,
        sampler_factory=lambda: contextlib.nullcontext(),
        running_sampler=lambda base_url: FakeSampler(base_url, [8, 8, 7, 8]),
        wait_running=lambda base_url, at_least, timeout_s: {"reached": reached, "seconds": 2.0},
        stoppable=fake_stoppable, clock=clock,
    )
    return deps, engines, calls


def test_a_solo_cell_runs_one_engine_at_its_own_concurrency():
    deps, engines, calls = _deps(Clock())
    out = measure_cell(A, None, _cell(None), deps=deps)
    assert out["healthy"] and out["run"]["level"] == 8
    assert [s.base_url for s in engines.started] == ["http://127.0.0.1:8000"]
    plan = calls["run_one"][0][1]["plan"]
    assert plan.path == "random-fixed-length"
    assert "--random-input-len" in plan.dataset_args and "1024" in plan.dataset_args


def test_an_idle_neighbour_cell_starts_both_engines_and_loads_neither():
    deps, engines, calls = _deps(Clock())
    out = measure_cell(A, B, _cell(0), deps=deps)
    assert [s.base_url.rsplit(":", 1)[1] for s in engines.started] == ["8000", "8001"]
    assert out["neighbour_load"] == {"level": 0}
    assert calls["bench"] == []


def test_a_loaded_cell_holds_the_neighbour_through_the_measured_run():
    deps, _, calls = _deps(Clock())
    out = measure_cell(A, B, _cell(8), deps=deps)
    load = out["neighbour_load"]
    assert out["run"]["latency_s"] == 0.8
    assert calls["bench"][0][0] == "http://127.0.0.1:8001"
    assert calls["bench"][0][1]["max_concurrency"] == 8
    assert load["ended"] == "stopped" and not load["ended_before_measured_run"]
    assert load["median_running"] == 8 and load["min_running"] == 7


def test_a_neighbour_that_finished_early_is_flagged():
    deps, _, _ = _deps(Clock(), neighbour_finishes=True)
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert out["neighbour_load"]["ended"] == "finished"
    assert out["neighbour_load"]["ended_before_measured_run"]


def test_a_neighbour_that_never_ramped_is_recorded():
    deps, _, _ = _deps(Clock(), reached=False)
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert out["neighbour_load"]["ramp"]["reached"] is False


def test_an_unhealthy_neighbour_fails_the_cell_before_any_load():
    deps, _, calls = _deps(Clock(), healthy={B.model: False})
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert not out["healthy"] and calls["run_one"] == [] and calls["bench"] == []


def test_a_failed_measurement_is_data_and_the_engines_are_stopped():
    def broken(base_url, **kw):
        raise BenchError("exited 1")

    deps, engines, _ = _deps(Clock(), run_one=broken)
    out = measure_cell(A, B, _cell(0), deps=deps)
    assert out["healthy"] and out["run"] is None and "BenchError" in out["run_error"]
    assert all(s.stops >= 1 for s in engines.started)


def test_stoppable_run_ends_a_long_tool_when_asked(tmp_path):
    stop = threading.Event()
    run = stoppable_run(stop)
    threading.Timer(0.3, stop.set).start()
    proc = run(["sleep", "30"], capture_output=True, text=True, check=False)
    assert proc.returncode != 0


def test_stoppable_run_returns_a_finished_tools_output():
    run = stoppable_run(threading.Event())
    proc = run(["echo", "hi"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0 and proc.stdout.strip() == "hi"


def test_a_cell_spec_refuses_impossible_loads():
    with pytest.raises(ValueError):
        _cell(-1)
    with pytest.raises(ValueError):
        CellSpec(own=0, neighbour=None, input_len=1, output_len=1, num_prompts=1,
                 warmup_prompts=0, neighbour_prompts=0, seed=1)
