"""A small co-location campaign through the real loop, submitter, dispatcher
and store, reduced to a solo curve and a surface. The fake engines' latency is
1 + 0.1 x own + 0.05 x neighbour, so the reductions must recover it exactly."""

import contextlib
import importlib.util
from pathlib import Path

import pytest
from a4_fakes import Clock, FakeEngines

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from placement.inputs import colocated_surface, solo_curve
from placement_measure.campaigns import CellDesign
from placement_measure.colocation import CellDeps
from placement_measure.jobs import measure_job
from placement_measure.records import A4Run

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("a4_measure", ROOT / "scripts" / "a4_measure.py")
a4_measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a4_measure)

DESIGN = CellDesign(measured_model="Qwen/Qwen3-4B", neighbour_model="Qwen/Qwen3-4B-Base",
                    own_levels=(1, 4), neighbour_levels=(0, 4), solo=True, input_len=512,
                    output_len=64, repeats=2, seed=11)


class Sampler:
    def __init__(self, base_url):
        self.samples = [{"t_s": 0.0, "running": 4.0, "error": None}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def values(self):
        return [4.0]


def _worker(payload):
    neighbour = payload["cell"]["neighbour"] or 0
    clock = Clock()

    def run_one(base_url, **kw):
        return {"latency_s": 1 + 0.1 * kw["level"] + 0.05 * neighbour,
                "throughput_tps": 100.0 * kw["level"], "gpu_util": 1.0}

    def bench(base_url, **kw):
        kw["run"].stop.wait(5)
        from harness.bench import BenchError
        raise BenchError("stopped")

    def stoppable(stop):
        run = lambda *a, **k: None
        run.stop = stop
        return run

    deps = CellDeps(served=FakeEngines(clock).served, run_one=run_one, run_bench=bench,
                    sampler_factory=contextlib.nullcontext, running_sampler=Sampler,
                    wait_running=lambda *a, **k: {"reached": True, "seconds": 1.0},
                    stoppable=stoppable, clock=clock)
    return measure_job(payload, cell_deps=deps, host=lambda: {"host_id": "h"}, clock=clock)


def test_a_cell_campaign_reduces_to_the_latencies_the_engines_produced(tmp_path):
    store = tmp_path / "cells.jsonl"
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(_worker).submit_payload,
                               store, source="stub")
    records = JsonlStore(store, A4Run).read_all()
    assert len(records) == 12 and all(r.outcome == "ok" for r in records)
    surface = colocated_surface(records, own_levels=(1, 4), neighbour_levels=(0, 4), min_repeats=2)
    assert surface.measured
    assert surface.latency_at(4, 4) == pytest.approx(1 + 0.4 + 0.2)
    assert surface.latency_at(1, 0) == pytest.approx(1.1)
    curve = solo_curve(records, levels=(1, 4), min_repeats=2)
    assert curve.latency_at(4) == pytest.approx(1.4) and curve.measured


def test_resume_skips_the_runs_already_stored(tmp_path):
    store = tmp_path / "cells.jsonl"
    calls = []

    def counting(payload):
        calls.append(payload["run_id"])
        return _worker(payload)

    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(counting).submit_payload,
                               store, source="stub")
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(counting).submit_payload,
                               store, source="stub", resume=True)
    assert len(calls) == 12


def test_a_missing_cell_is_refused_not_interpolated(tmp_path):
    store = tmp_path / "cells.jsonl"
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(_worker).submit_payload,
                               store, source="stub")
    records = [r for r in JsonlStore(store, A4Run).read_all() if r.condition != "pair:o4:n4"]
    with pytest.raises(ValueError, match="interpolate"):
        colocated_surface(records, own_levels=(1, 4), neighbour_levels=(0, 4), min_repeats=2)
