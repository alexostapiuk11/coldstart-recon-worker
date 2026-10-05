import contextlib
import json

import pytest

from harness.scheduler import ScheduledRun
from harness.submit import SubmitOutcome
from multilora import serving
from multilora.campaign import job_payload
from multilora.instance import Deps, run_instance, synthetic_seed
from multilora.records import build_record

TINY = {
    "hidden_size": 8, "num_attention_heads": 2, "num_key_value_heads": 1,
    "head_dim": 4, "intermediate_size": 16, "num_hidden_layers": 2,
}
MODULES = ("q_proj", "v_proj")
KV_LINE = "GPU KV cache size: 50,000 tokens"
WARM = "torch.compile took 0.31 s in total"


class FakeServer:
    def __init__(self, healthy=True):
        self.base_url = "http://127.0.0.1:8000"
        self.log_lines = [WARM, KV_LINE]
        self.healthy = healthy


def fake_served(calls, healthy=True):
    @contextlib.contextmanager
    def served(model, *, args, env):
        calls.append({"model": model, "args": args, "env": env})
        yield FakeServer(healthy)

    return served


def fake_bench(calls):
    def run_bench(base_url, **kw):
        calls.append(kw)
        n = kw["num_prompts"]
        return {
            "duration": n * 0.01, "completed": n, "failed": 0,
            "ttfts": [0.05] * n, "output_lens": [16] * n, "errors": [""] * n,
        }

    return run_bench


def _deps(served_calls, bench_calls, healthy=True, downloads=None):
    def download(repo, revision, dest):
        (downloads if downloads is not None else []).append((repo, revision, dest))
        from multilora.adapters import write_synthetic_adapter

        write_synthetic_adapter(dest, config=TINY, base_model="m", rank=2,
                                target_modules=MODULES, seed=99)

    metrics = 'vllm:lora_requests_info{running_lora_adapters="a00",waiting_lora_adapters=""} 1.0\n'
    return Deps(
        model_config=lambda model, revision: TINY,
        download_adapter=download,
        http_get=lambda url: metrics,
        host_info=lambda: {"host_id": "container", "vcpus": 8},
        served=fake_served(served_calls, healthy),
        run_bench=fake_bench(bench_calls),
    )


@pytest.fixture(autouse=True)
def adapter_root(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "ADAPTER_ROOT", str(tmp_path / "adapters"))


def _run(payload, deps):
    return run_instance(
        payload, model="Qwen/Qwen3-4B", revision="rev", max_model_len=8192, rank=2,
        target_modules=MODULES, env={"HF_HOME": "/h"}, deps=deps, gpu_memory_utilization=0.85,
    )


def test_an_instance_warms_every_adapter_then_runs_the_phases_in_order(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N4"), "run-1", prereg)
    served_calls, bench_calls = [], []
    out = _run(payload, _deps(served_calls, bench_calls))
    assert out["healthy"] is True
    warm = bench_calls[0]
    assert warm["lora_modules"] == ["a00", "a01", "a02", "a03"]
    assert warm["num_prompts"] == prereg.warmup_requests_per_adapter * 4
    timed = bench_calls[1:]
    assert [c["lora_modules"] for c in timed] == [p["adapters"] for p in payload["phases"]]
    assert all(c["num_prompts"] == prereg.requests_per_phase for c in timed)
    assert all(c["lora_assignment"] == "round-robin" and c["ignore_eos"] for c in timed)
    assert [p["phase_index"] for p in out["phases"]] == [0, 1, 2, 3]
    args = served_calls[0]["args"]
    assert args[args.index("--max-loras") + 1] == "4"


def test_the_memory_budget_reaches_the_engine_and_the_recorded_command(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N2"), "run-1", prereg)
    served_calls = []
    out = _run(payload, _deps(served_calls, []))
    cmd = out["served_cmd"]
    assert cmd.count("--gpu-memory-utilization") == 1
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.85"
    assert cmd[3:] == served_calls[0]["args"]


def test_an_instance_without_a_memory_budget_is_refused(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N2"), "run-1", prereg)
    with pytest.raises(TypeError, match="gpu_memory_utilization"):
        run_instance(
            payload, model="Qwen/Qwen3-4B", revision="rev", max_model_len=8192, rank=2,
            target_modules=MODULES, env={}, deps=_deps([], []),
        )


def test_the_output_becomes_a_well_formed_record(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N2"), "run-1", prereg)
    out = _run(payload, _deps([], []))
    rec = build_record(
        ScheduledRun(3, 0, "sweep-N2"), "run-1",
        SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=out, error=None),
    )
    assert rec.engine["kv_capacity_tokens"] == 50_000
    assert rec.engine["compile_state"] == "warm"
    assert set(rec.adapters) == {"a00", "a01"}
    assert len(rec.phases) == 4
    json.dumps(rec.to_dict())


def test_an_unhealthy_engine_returns_its_log_and_runs_no_load(prereg):
    payload = job_payload(ScheduledRun(0, 0, "sweep-N1"), "run-1", prereg)
    bench_calls = []
    out = _run(payload, _deps([], bench_calls, healthy=False))
    assert out["healthy"] is False
    assert KV_LINE in out["log_lines"]
    assert bench_calls == []


def test_synthetic_adapters_are_reused_when_parameters_match(prereg, tmp_path):
    payload = job_payload(ScheduledRun(0, 0, "sweep-N2"), "run-1", prereg)
    first = _run(payload, _deps([], []))["adapters"]
    marker = tmp_path / "adapters" / "a00" / "adapter_model.safetensors"
    mtime = marker.stat().st_mtime_ns
    second = _run(payload, _deps([], []))["adapters"]
    assert first == second
    assert marker.stat().st_mtime_ns == mtime, "an identical adapter was rewritten"


def test_gate_instances_download_real_adapters_at_their_pinned_revision(prereg):
    payload = job_payload(ScheduledRun(0, 0, "gate"), "run-g", prereg)
    downloads = []
    out = _run(payload, _deps([], [], downloads=downloads))
    assert [(repo, rev) for repo, rev, _ in downloads] == list(prereg.real_adapters)
    assert set(out["adapters"]) == {f"r{i:02d}" for i in range(4)} | {f"s{i:02d}" for i in range(4)}


def test_sweep_and_gate_synthetic_seeds_never_collide():
    assert synthetic_seed(1, "a00") != synthetic_seed(1, "s00")
    assert len({synthetic_seed(1, f"a{i:02d}") for i in range(64)}) == 64
