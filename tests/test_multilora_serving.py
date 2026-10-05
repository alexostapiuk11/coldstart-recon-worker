import pytest

from multilora.serving import (
    ENGINE_FLAGS,
    SPECIALIZE_FLAG,
    run_phase,
    serve,
    serve_args,
)


def _args(**kw):
    base = {
        "revision": "abc123",
        "max_model_len": 8192,
        "n_slots": 2,
        "rank": 16,
        "lora_modules": {"a00": "/tmp/a5-adapters/a00", "a01": "/tmp/a5-adapters/a01"},
        "specialize_active_lora": False,
        "disable_log_stats": False,
        "gpu_memory_utilization": 0.85,
    }
    base.update(kw)
    return serve_args(**base)


def test_every_registered_adapter_gets_its_own_slot():
    args = _args()
    assert args[args.index("--max-loras") + 1] == "2"
    assert args[args.index("--max-cpu-loras") + 1] == "2"
    assert args[args.index("--max-lora-rank") + 1] == "16"
    assert "--no-enable-prefix-caching" in args
    i = args.index("--lora-modules")
    assert args[i + 1 : i + 3] == ["a00=/tmp/a5-adapters/a00", "a01=/tmp/a5-adapters/a01"]


def test_the_per_job_switches_add_their_flags():
    assert SPECIALIZE_FLAG in _args(specialize_active_lora=True)
    assert "--disable-log-stats" in _args(disable_log_stats=True)
    plain = _args()
    assert SPECIALIZE_FLAG not in plain and "--disable-log-stats" not in plain


@pytest.mark.parametrize("value, text", [(0.85, "0.85"), (0.9, "0.9"), (1.0, "1.0"), (1, "1.0")])
def test_the_memory_budget_is_passed_once_as_its_own_argument(value, text):
    args = _args(gpu_memory_utilization=value)
    assert args.count("--gpu-memory-utilization") == 1
    assert args[args.index("--gpu-memory-utilization") + 1] == text
    assert not any(a.startswith("--gpu-memory-utilization=") for a in args)


def test_the_memory_budget_is_required_not_defaulted():
    base = {
        "revision": "abc123", "max_model_len": 8192, "n_slots": 1, "rank": 16,
        "lora_modules": {"a00": "/x"}, "specialize_active_lora": False, "disable_log_stats": False,
    }
    with pytest.raises(TypeError, match="gpu_memory_utilization"):
        serve_args(**base)


def test_the_memory_budget_flag_is_checked_against_the_engines_help():
    assert "--gpu-memory-utilization" in ENGINE_FLAGS


def test_slot_count_must_match_the_adapters_registered():
    with pytest.raises(ValueError, match="1 adapters registered for 2 slots"):
        _args(lora_modules={"a00": "/x"})


def test_serve_passes_through_to_the_harness_lifecycle():
    calls = []

    def fake_served(model, *, args, env):
        calls.append((model, args, env))
        return "ctx"

    assert serve("m", ["--x"], {"HF_HOME": "/h"}, served=fake_served) == "ctx"
    assert calls == [("m", ["--x"], {"HF_HOME": "/h"})]


def test_a_phase_is_round_robin_with_eos_ignored_and_raw_arrays_kept():
    seen = {}

    def fake_run_bench(base_url, **kw):
        seen.update(kw, base_url=base_url)
        return {
            "duration": 12.5, "completed": 3, "failed": 1,
            "ttfts": [0.1, 0.2, 0.0, 0.3], "output_lens": [16, 16, 0, 16],
            "errors": ["", "", "boom", ""], "mean_ttft_ms": 150.0,
        }

    phase = run_phase(
        "http://127.0.0.1:8000", model="m", adapters=("a00", "a01"), concurrency=64,
        num_requests=4, dataset_args=["--dataset-name", "random"], seed=7,
        result_dir="/tmp/r", run_bench=fake_run_bench,
    )
    assert seen["lora_assignment"] == "round-robin"
    assert seen["ignore_eos"] is True
    assert seen["lora_modules"] == ["a00", "a01"]
    assert seen["max_concurrency"] == 64
    assert phase["ttfts"] == [0.1, 0.2, 0.0, 0.3]
    assert phase["duration_s"] == 12.5
    assert "mean_ttft_ms" not in phase, "summary statistics are never carried"
