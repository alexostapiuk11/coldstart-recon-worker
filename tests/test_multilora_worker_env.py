import pytest

from multilora.worker_env import VOLUME_ENV, instance_kwargs, volume_env

ENV = {
    "MODEL_ID": "Qwen/Qwen3-4B",
    "MODEL_REVISION": "abc",
    "MAX_MODEL_LEN": "8192",
    "A5_MAX_LORA_RANK": "16",
    "A5_TARGET_MODULES": "q_proj,k_proj,v_proj",
}


def test_the_fixed_values_come_from_the_environment():
    kw = instance_kwargs(ENV)
    assert kw == {
        "model": "Qwen/Qwen3-4B", "revision": "abc", "max_model_len": 8192, "rank": 16,
        "target_modules": ("q_proj", "k_proj", "v_proj"),
    }


def test_a_missing_value_fails_before_any_gpu_time():
    with pytest.raises(RuntimeError, match="A5_MAX_LORA_RANK"):
        instance_kwargs({k: v for k, v in ENV.items() if k != "A5_MAX_LORA_RANK"})


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
