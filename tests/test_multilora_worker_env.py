import pytest

from multilora.worker_env import VOLUME_ENV, instance_kwargs, volume_env

ENV = {
    "MODEL_ID": "Qwen/Qwen3-4B",
    "MODEL_REVISION": "abc",
    "MAX_MODEL_LEN": "8192",
    "A5_MAX_LORA_RANK": "16",
    "A5_TARGET_MODULES": "q_proj,k_proj,v_proj",
    "A5_GPU_MEMORY_UTILIZATION": "0.85",
}


def test_the_fixed_values_come_from_the_environment():
    kw = instance_kwargs(ENV)
    assert kw == {
        "model": "Qwen/Qwen3-4B", "revision": "abc", "max_model_len": 8192, "rank": 16,
        "target_modules": ("q_proj", "k_proj", "v_proj"), "gpu_memory_utilization": 0.85,
    }


def test_a_missing_value_fails_before_any_gpu_time():
    with pytest.raises(RuntimeError, match="A5_MAX_LORA_RANK"):
        instance_kwargs({k: v for k, v in ENV.items() if k != "A5_MAX_LORA_RANK"})


def test_a_missing_memory_budget_fails_before_any_gpu_time():
    """vLLM's 0.92 default OOMed reconnaissance: CUDA-graph memory sits outside
    its KV sizing. The budget is fixed in the endpoint environment (amendment
    §4), so a worker without it must not fall back to the engine's default."""
    with pytest.raises(RuntimeError, match="A5_GPU_MEMORY_UTILIZATION"):
        instance_kwargs({k: v for k, v in ENV.items() if k != "A5_GPU_MEMORY_UTILIZATION"})


@pytest.mark.parametrize("raw", ["abc", "nan", "inf", "-inf", "0", "0.0", "-0.5", "1.5", "1.0000001"])
def test_an_invalid_memory_budget_names_the_variable_and_the_value(raw):
    with pytest.raises(RuntimeError) as e:
        instance_kwargs({**ENV, "A5_GPU_MEMORY_UTILIZATION": raw})
    assert "A5_GPU_MEMORY_UTILIZATION" in str(e.value)
    assert repr(raw) in str(e.value)


def test_an_empty_memory_budget_counts_as_missing():
    with pytest.raises(RuntimeError, match="A5_GPU_MEMORY_UTILIZATION"):
        instance_kwargs({**ENV, "A5_GPU_MEMORY_UTILIZATION": ""})


@pytest.mark.parametrize("raw, value", [("0.85", 0.85), ("1.0", 1.0), ("1", 1.0), ("0.5", 0.5)])
def test_a_valid_memory_budget_is_passed_as_a_float(raw, value):
    kw = instance_kwargs({**ENV, "A5_GPU_MEMORY_UTILIZATION": raw})
    assert kw["gpu_memory_utilization"] == value
    assert type(kw["gpu_memory_utilization"]) is float


def test_tuned_kernel_configs_are_refused():
    with pytest.raises(RuntimeError, match="VLLM_TUNED_CONFIG_FOLDER"):
        instance_kwargs({**ENV, "VLLM_TUNED_CONFIG_FOLDER": "/cfg"})


def test_an_unmounted_volume_is_refused_not_created():
    made = []
    with pytest.raises(RuntimeError, match="not mounted"):
        volume_env(isdir=lambda p: False, makedirs=lambda p, exist_ok: made.append(p))
    assert made == []


def test_a_mounted_volume_gets_artifact_fives_own_cache_root():
    made = []
    env = volume_env(isdir=lambda p: True, makedirs=lambda p, exist_ok: made.append(p))
    assert env == VOLUME_ENV
    assert env["VLLM_CACHE_ROOT"].endswith("/a5/vllm-cache")
    assert sorted(made) == sorted(VOLUME_ENV.values())
