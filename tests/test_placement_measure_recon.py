import subprocess

import pytest
from a4_fakes import Clock, FakeEngines, memory_script

from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.swap import SwapDeps

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


class Resp:
    def __init__(self, status=200, text="{}"):
        self.status_code, self.text = status, text


def _deps(clock, engines, readings=(500, 9000, 500), posted=None, snapshot=None, run_command=None):
    run = memory_script(list(readings))
    posted = posted if posted is not None else []

    def post(url, **kw):
        posted.append(url)
        return Resp()

    return ReconDeps(
        served=engines.served,
        read_memory=lambda: read_memory(run=run),
        swap_deps=SwapDeps(
            served=engines.served, read_memory=lambda: read_memory(run=run),
            wait_for_release=lambda target, timeout_s: wait_for_release(
                target, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
            make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock),
        snapshot_download=snapshot or (lambda repo_id, revision: f"/vol/{repo_id}@{revision}"),
        post=post, get=lambda url, **kw: Resp(text='{"is_sleeping": true}'),
        run_command=run_command or (lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")),
        clock=clock,
    )


def test_an_unknown_probe_is_refused():
    with pytest.raises(ValueError, match="unknown probe"):
        run_probe({"probe": "guess", "job_budget_s": 1800})


def test_stage_records_every_checkpoint_and_whether_all_landed():
    clock = Clock()

    def snapshot(repo_id, revision):
        if repo_id.endswith("Base"):
            raise OSError("401")
        return "/vol/x"

    out = run_probe({"probe": "stage", "job_budget_s": 1800,
                     "models": [{"model": A.model, "revision": "ra"},
                                {"model": B.model, "revision": "rb"}]},
                    _deps(clock, FakeEngines(clock), snapshot=snapshot))
    staged = out["result"]["staged"]
    assert out["healthy"] and [s["error"] is None for s in staged] == [True, False]
    assert not out["result"]["complete"]


def test_coresidency_reports_both_engines_kv_and_memory():
    clock = Clock()
    engines = FakeEngines(clock)
    out = run_probe({"probe": "coresidency", "job_budget_s": 1800,
                     "a": A.to_dict(), "b": B.to_dict()}, _deps(clock, engines))
    r = out["result"]
    assert r["engines"]["a"]["facts"]["kv_capacity_tokens"] == 35792
    assert r["engines"]["b"]["healthy"]
    assert [s.base_url[-4:] for s in engines.started] == ["8000", "8001"]
    assert r["both_memory"]["used_mib"] == 9000


def test_coresidency_with_a_failed_engine_is_an_answer_not_a_failed_job():
    clock = Clock()
    out = run_probe({"probe": "coresidency", "job_budget_s": 1800, "a": A.to_dict(),
                     "b": B.to_dict()}, _deps(clock, FakeEngines(clock, healthy={B.model: False})))
    assert out["healthy"] and not out["result"]["engines"]["b"]["healthy"]
    assert out["result"]["smoke"]["b"] is None


def test_swaps_stop_starting_new_swaps_when_the_budget_runs_low():
    clock = Clock()
    engines = FakeEngines(clock, startup_s={A.model: 300.0, B.model: 300.0})
    swap = {"a": A.to_dict(), "b": B.to_dict(), "cold": False}
    out = run_probe({"probe": "swaps", "job_budget_s": 1200, "hf_home": "/vol/hf",
                     "release_tolerance_mib": 256, "release_timeout_s": 60,
                     "swaps": [swap, swap, swap]},
                    _deps(clock, engines, readings=(500, 500)))
    r = out["result"]
    assert len(r["swaps"]) == 1 and len(r["skipped_for_budget"]) == 2


def test_early_start_starts_the_successor_without_waiting_for_release():
    clock = Clock()
    engines = FakeEngines(clock)
    out = run_probe({"probe": "early_start", "job_budget_s": 1800, "a": A.to_dict(),
                     "b": B.to_dict()}, _deps(clock, engines, readings=(9000,)))
    assert out["result"]["memory_when_b_started"]["used_mib"] == 9000
    assert out["result"]["b"]["healthy"]


def test_sleep_runs_the_sleep_wake_sequence_in_dev_mode():
    clock = Clock()
    engines = FakeEngines(clock)
    posted = []
    sleepy = EngineSpec(A.model, "ra", 0.8, 2048, 256, extra_args=("--enable-sleep-mode",))
    out = run_probe({"probe": "sleep", "job_budget_s": 1800, "a": sleepy.to_dict(),
                     "b": EngineSpec(B.model, "rb", 0.8, 2048, 256,
                                     extra_args=("--enable-sleep-mode",)).to_dict()},
                    _deps(clock, engines, posted=posted))
    r = out["result"]
    assert [u.rsplit("/", 1)[1] for u in posted] == [
        "sleep?level=1", "sleep?level=1", "wake_up", "completions"]
    assert r["sleep_a"]["status"] == 200 and r["is_sleeping_a"]["body"] == '{"is_sleeping": true}'
    assert "--enable-sleep-mode" in engines.started[0].cmd


def test_help_lists_the_flags_the_image_does_not_know():
    clock = Clock()

    def run_command(cmd, **kw):
        text = "--max-concurrency --ignore-eos" if cmd[1] == "bench" else "--revision --max-num-seqs"
        return subprocess.CompletedProcess(cmd, 0, text, "")

    out = run_probe({"probe": "help", "job_budget_s": 1800},
                    _deps(clock, FakeEngines(clock), run_command=run_command))
    assert "--enable-sleep-mode" in out["result"]["serve"]["missing"]
    assert "--random-input-len" in out["result"]["bench"]["missing"]
