"""Plan 3's GPU-free rehearsal: from a reconnaissance report to every file the
publication reads, through the scripts the paid steps use, on fake workers.

1. `scripts/a4_step2.py values` writes the registered values and design files.
2. The cell, swap and sleep campaigns run through `scripts/a4_measure.py`'s
   loop, each payload through `placement_measure.jobs.measure_job` on fakes,
   JSON round-tripped by the harness's stub submitter, into their stores.
3. `scripts/a4_step2.py replay` writes the validation trace from those cells.
   The replays themselves are the simulator's latencies on that trace
   (tests/a4_stores.py): the real driver runs in real time, and its own tests
   cover it against the simulator.
4. `scripts/a4_analyse.py` reduces everything; the sweep's evaluations are
   hand-built, because the real sweep is hours of CPU (tests/test_a4_sweep.py
   runs it small).
5. `scripts/a4_cost_file.py` and `scripts/a4_render_figures.py` finish.
"""

import contextlib
import importlib.util
import json
from pathlib import Path

import pytest
from a4_evaluations import rich_sweep
from a4_examples import example_report
from a4_fakes import Clock, FakeEngines, memory_script
from a4_stores import _replays
from test_a4_measure_end_to_end import Sampler
from test_placement_cost_file import _artifact_5_reads
from test_placement_measure_sleep_and_extra_cells import _timed_deps

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from placement.inputs import load_records
from placement.registration import SECTION
from placement_measure.colocation import CellDeps
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.jobs import measure_job
from placement_measure.records import A4Run
from placement_measure.swap import SwapDeps

REPO = Path(__file__).resolve().parents[1]
WARM = {"Qwen/Qwen3-4B": 0.3, "Qwen/Qwen3-4B-Base": 0.3, "Qwen/Qwen3-4B-Instruct-2507": 0.3}
HOST = {"host_id": "h1", "runpod_pod_id": None}


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cell_worker(payload):
    clock = Clock()
    neighbour = payload["cell"]["neighbour"] or 0

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

    deps = CellDeps(served=FakeEngines(clock, compile_s=WARM).served, run_one=run_one,
                    run_bench=bench, sampler_factory=contextlib.nullcontext,
                    running_sampler=Sampler,
                    wait_running=lambda *a, **k: {"reached": True, "seconds": 1.0},
                    stoppable=stoppable, clock=clock)
    return measure_job(payload, cell_deps=deps, host=lambda: HOST, clock=clock)


def _swap_worker(payload):
    clock = Clock()
    run = memory_script([500, 9000, 500])
    deps = SwapDeps(
        served=FakeEngines(clock, compile_s=WARM).served, read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda t, timeout_s: wait_for_release(
            t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock)
    return measure_job(payload, swap_deps=deps, host=lambda: HOST, clock=clock)


def _sleep_worker(payload):
    clock = Clock()
    return measure_job(payload, recon_deps=_timed_deps(clock), host=lambda: HOST, clock=clock)


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    root = tmp_path_factory.mktemp("a4")
    for d in ("fixtures/a4", "data/a4", "docs", "placement"):
        (root / d).mkdir(parents=True)
    (root / "fixtures/a4/recon-report.json").write_text(json.dumps(example_report()))
    (root / "data/a4/screen.json").write_text(
        json.dumps({"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}))
    # Before step 2's values, which the repository's copy has after publication.
    doc = (REPO / "docs/experiment-a4.md").read_text().split(SECTION)[0]
    (root / "docs/experiment-a4.md").write_text(doc)
    step2 = _script("a4_step2")
    reg = step2.write_values(root, 0.69, "test rate, not a quote", "2026-10-14")

    measure = _script("a4_measure")
    for kind, name, worker in (("cell", "cells", _cell_worker), ("swap", "swaps", _swap_worker),
                               ("sleep", "sleep", _sleep_worker)):
        design = measure.load_design(kind, root / "data/a4/designs" / f"{name}.json")
        measure.run_measurement(design, kind, PayloadStubSubmitter(worker).submit_payload,
                                root / "data/a4" / f"{name}.jsonl", source="stub")
    step2.write_replay(root, ["data/a4/cells.jsonl"], ["data/a4/swaps.jsonl"])
    cells = load_records([root / "data/a4/cells.jsonl"])
    swaps = load_records([root / "data/a4/swaps.jsonl"])
    store = JsonlStore(root / "data/a4/replay.jsonl", A4Run)
    for record in _replays(reg, cells, swaps):
        store.append(record)

    analyse = _script("a4_analyse")
    analyse.a4_sweep.evaluations_for = lambda *a, **k: rich_sweep()
    analysis = analyse.analyse_all(reg, analyse.STORES, root=root,
                                   a1_store=REPO / "data/campaign.jsonl",
                                   sweep_out=root / "sweep", workers=1)
    (root / "data/a4/analysis.json").write_text(json.dumps(analysis, indent=1))
    return root, reg, analysis


def test_every_campaign_ran_ok_through_the_real_loop(rehearsal):
    root, reg, _ = rehearsal
    for name in ("cells", "swaps", "sleep"):
        records = load_records([root / "data/a4" / f"{name}.jsonl"])
        assert records and all(r.outcome == "ok" for r in records), name
    cells = load_records([root / "data/a4/cells.jsonl"])
    conditions = {r.condition for r in cells}
    assert set(reg["HELD_OUT"]) <= conditions and f"solo:o{reg['SOLO_LEVELS'][-1]}" in conditions


def test_the_reductions_validation_and_held_out_check_pass(rehearsal):
    _, _, analysis = rehearsal
    assert analysis["validation"]["outcome"] == "passed"
    assert [c["passed"] for c in analysis["held_out"]] == [True, True]
    assert analysis["inputs"]["stages"]["n"] > 0
    assert analysis["inputs"]["sleep_mode"]["n"] == 8


def test_the_cost_file_and_the_figures_are_written(rehearsal, tmp_path):
    root, _, _ = rehearsal
    out = root / "data/a4/cost_per_tenant.json"
    _script("a4_cost_file").main(["--analysis", str(root / "data/a4/analysis.json"),
                                  "--out", str(out)])
    _artifact_5_reads(json.loads(out.read_text()))
    written = _script("a4_render_figures").main(
        ["--analysis", str(root / "data/a4/analysis.json"), "--out", str(tmp_path / "figs")])
    assert len(written) == 8 and all(p.stat().st_size > 10_000 for p in written)
