import contextlib

import pytest

from multilora import serving
from multilora.instance import Deps
from multilora.recon import RECON_POINTS, recon_payloads, run_probe
from multilora.recon_report import report

TINY = {
    "hidden_size": 8, "num_attention_heads": 2, "num_key_value_heads": 1,
    "head_dim": 4, "intermediate_size": 16, "num_hidden_layers": 2,
}
HELP = " ".join(serving.ENGINE_FLAGS + serving.BENCH_FLAGS)
GAUGE = 'vllm:lora_requests_info{running_lora_adapters="a00,a01",waiting_lora_adapters=""} 1.0\n'


@pytest.fixture(autouse=True)
def adapter_root(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "ADAPTER_ROOT", str(tmp_path / "adapters"))


def _deps():
    class Server:
        def __init__(self):
            self.base_url = "http://x"
            self.log_lines = ["torch.compile took 0.30 s in total", "GPU KV cache size: 40,000 tokens"]
            self.healthy = True

    @contextlib.contextmanager
    def served(model, *, args, env):
        yield Server()

    def run_bench(base_url, **kw):
        n = kw["num_prompts"]
        return {"duration": n * 0.02, "completed": n, "failed": 0,
                "ttfts": [0.1] * n, "output_lens": [16] * n, "errors": [""] * n}

    return Deps(model_config=lambda m, r: TINY, download_adapter=lambda *a: None,
                http_get=lambda url: GAUGE, host_info=dict, served=served, run_bench=run_bench)


KW = {"model": "m", "revision": "r", "max_model_len": 8192, "rank": 2,
      "target_modules": ("q_proj",), "env": {}, "gpu_memory_utilization": 0.85}


def test_the_probe_list_covers_each_point_twice_and_the_two_switches():
    payloads = recon_payloads(concurrency=64, dataset_args=["--x"], adapter_seed=1)
    labels = [p["label"] for p in payloads]
    assert labels[0] == "help"
    for n in RECON_POINTS:
        assert f"lora-N{n}-first" in labels and f"lora-N{n}-restart" in labels
    assert "lora-N64-specialize" in labels and "lora-N64-no-stats" in labels
    assert "lora-gate-real" not in labels


def test_real_candidates_add_a_gate_shaped_probe():
    payloads = recon_payloads(concurrency=64, dataset_args=["--x"], adapter_seed=1,
                              real_candidates=[("org/a", "r1"), ("org/b", "r2")])
    gate = payloads[-1]
    assert gate["label"] == "lora-gate-real"
    assert gate["registered"] == ["r00", "r01", "s00", "s01"]
    assert gate["real_adapters"][1] == {"name": "r01", "repo": "org/b", "revision": "r2"}


def test_a_lora_probe_answers_every_adapter_and_scrapes_the_gauge():
    payload = recon_payloads(concurrency=4, dataset_args=["--x"], adapter_seed=1)[3]
    out = run_probe(payload, deps=_deps(), post_status=lambda url, body: 200,
                    post_json=lambda url, body: {"count": 13}, **KW)
    assert set(out["completion_status"]) == set(payload["registered"])
    assert out["a1_prompt_tokens"] == 13
    assert "lora_requests_info" in out["metrics_idle"]
    assert len(out["phases"]) == 1 and out["phases"][0]["regime"] == "spread"
    cmd = out["served_cmd"]
    assert cmd[cmd.index("--gpu-memory-utilization") + 1] == "0.85"


def test_the_help_probe_records_failures_as_answers():
    def run_cmd(cmd):
        return {"cmd": cmd, "returncode": 2, "stdout": "", "stderr": "no such command"}

    out = run_probe({"probe": "help"}, deps=None, post_status=None, run_cmd=run_cmd)
    assert out["bench_help"]["returncode"] == 2


def test_the_report_turns_captures_into_answers():
    payloads = recon_payloads(concurrency=4, dataset_args=["--x"], adapter_seed=1)
    help_out = {"healthy": True,
                "serve_help": {"stdout": HELP, "stderr": ""},
                "bench_help": {"stdout": HELP, "stderr": ""}}
    captures = [{"label": "help", "payload": payloads[0],
                 "outcome": {"payload": help_out, "error": None, "diagnostics": None}}]
    for p in payloads[1:3]:
        out = run_probe(p, deps=_deps(), post_status=lambda url, body: 200,
                        post_json=lambda url, body: {"count": 13}, **KW)
        captures.append({"label": p["label"], "payload": p,
                         "outcome": {"payload": out, "error": None, "diagnostics": None}})
    answers = report(captures)
    assert answers["R4_bench_flags_missing"] == []
    assert answers["R4_engine_flags_missing"] == []
    assert answers["R2_highest_healthy_slots"] == 1
    assert answers["R3_every_adapter_answered"] is True
    assert answers["R6_kv_reported_with_lora"] is True
    assert answers["R7_gauge_exported"] is True
    assert answers["R9_specialize_flag_present"] is True
    assert answers["probes"]["lora-N1-first"]["phase_seconds_per_request"] == pytest.approx(0.02)
    assert answers["request_shape_prompt_tokens"] == [13]


def test_both_help_probes_ask_for_every_flag():
    """vLLM 0.27.1's `vllm bench serve --help` prints no flags; only `--help=all`
    lists them (shared tooling report, 2026-10-04). A plain `--help` would read
    as every bench flag missing, and plan 2's R4 rule would stop for nothing."""
    seen = []

    def run_cmd(cmd):
        seen.append(cmd)
        return {"cmd": cmd, "returncode": 0, "stdout": "", "stderr": ""}

    run_probe({"probe": "help"}, deps=None, post_status=None, run_cmd=run_cmd)
    assert [c[-1] for c in seen] == ["--help=all", "--help=all"]
