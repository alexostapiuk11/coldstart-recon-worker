import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import handler as handler_mod

from coldstart import cache_config

RUN_ID = "run-0007"


@pytest.fixture
def captured(monkeypatch):
    """Replaces the probe, recording exactly what the handler asked it to run."""
    seen = {}

    def _fake_run_probe(recorder, model, health_timeout=900.0, extra_args=(), env_overrides=None):
        seen["model"] = model
        seen["extra_args"] = list(extra_args)
        seen["env_overrides"] = dict(env_overrides or {})
        return {"healthy": True, "warmup": [], "clock_B": {"marks": []}, "log_lines": []}

    monkeypatch.setattr(handler_mod, "run_probe", _fake_run_probe)
    # Directory creation is exercised on its own below; these tests are about
    # which arm resolves to which paths.
    monkeypatch.setattr(handler_mod, "_prepare_cache_dirs", lambda env: None)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.delenv("MODEL_REVISION", raising=False)
    monkeypatch.delenv("MAX_MODEL_LEN", raising=False)
    return seen


def _job(arm="A", run_id=RUN_ID):
    return {"input": {"arm": arm, "run_id": run_id}}


# --- the arm is applied, not merely observed --------------------------------


def test_arm_a_gets_cold_weights_and_cold_compile_cache(captured):
    handler_mod.handler(_job(arm="A"))
    env = captured["env_overrides"]
    assert env["HF_HOME"] == f"{cache_config.COLD_HF_ROOT}/{RUN_ID}"
    assert env["VLLM_CACHE_ROOT"] == f"{cache_config.COLD_VLLM_CACHE_ROOT}/{RUN_ID}"


def test_arm_b_gets_volume_weights_but_still_a_cold_compile_cache(captured):
    handler_mod.handler(_job(arm="B"))
    env = captured["env_overrides"]
    assert env["HF_HOME"] == cache_config.VOLUME_HF_HOME
    assert env["VLLM_CACHE_ROOT"] == f"{cache_config.COLD_VLLM_CACHE_ROOT}/{RUN_ID}"


def test_arm_c_gets_the_warm_compile_cache_on_the_volume(captured):
    handler_mod.handler(_job(arm="C"))
    env = captured["env_overrides"]
    assert env["HF_HOME"] == cache_config.VOLUME_HF_HOME
    assert env["VLLM_CACHE_ROOT"] == cache_config.VOLUME_VLLM_CACHE_ROOT


def test_cold_paths_are_namespaced_per_run(captured):
    """Two runs of the same cold arm must not share a directory, or a reused
    worker serves run N-1's compiled artifacts to run N."""
    handler_mod.handler(_job(arm="A", run_id="run-1"))
    first = captured["env_overrides"]["VLLM_CACHE_ROOT"]
    handler_mod.handler(_job(arm="A", run_id="run-2"))
    second = captured["env_overrides"]["VLLM_CACHE_ROOT"]
    assert first != second


def test_every_arm_differs_only_in_cache_configuration(captured):
    """The single-variable claim: same model, same serve args across arms."""
    per_arm = {}
    for arm in ("A", "B", "C"):
        handler_mod.handler(_job(arm=arm))
        per_arm[arm] = (captured["model"], tuple(captured["extra_args"]))
    assert len(set(per_arm.values())) == 1


# --- the run must be labelled, never defaulted ------------------------------


def test_missing_arm_is_an_error(captured):
    with pytest.raises(KeyError):
        handler_mod.handler({"input": {"run_id": RUN_ID}})


def test_missing_run_id_is_an_error(captured):
    with pytest.raises(KeyError):
        handler_mod.handler({"input": {"arm": "A"}})


def test_unknown_arm_is_an_error(captured):
    with pytest.raises(ValueError):
        handler_mod.handler(_job(arm="Z"))


def test_empty_input_is_an_error(captured):
    with pytest.raises(KeyError):
        handler_mod.handler({})


# --- serve arguments --------------------------------------------------------


def test_revision_and_max_model_len_are_passed_through(captured, monkeypatch):
    monkeypatch.setenv("MODEL_REVISION", "b968826d")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")
    handler_mod.handler(_job())
    assert captured["extra_args"] == [
        "--revision",
        "b968826d",
        "--max-model-len",
        "8192",
    ]


def test_absent_serve_args_are_omitted_not_empty_strings(captured):
    handler_mod.handler(_job())
    assert captured["extra_args"] == []


# --- provenance carried on the result ---------------------------------------


def test_result_records_the_resolved_arm(captured):
    result = handler_mod.handler(_job(arm="C"))
    cfg = result["cache_config"]
    assert cfg["arm"] == "C"
    assert cfg["weights_source"] == "volume"
    assert cfg["compile_cache_warm"] is True
    assert cfg["env"]["VLLM_CACHE_ROOT"] == cache_config.VOLUME_VLLM_CACHE_ROOT


def test_result_carries_run_id_and_host(captured):
    result = handler_mod.handler(_job())
    assert result["run_id"] == RUN_ID
    assert "host_id" in result["host"]


# --- cache directories: created when cold, never fabricated on the volume ----


def test_cold_directories_are_created(tmp_path):
    cold = tmp_path / "hf-cold" / "run-1"
    handler_mod._prepare_cache_dirs({"HF_HOME": str(cold)})
    assert cold.is_dir()


def test_unmounted_volume_is_an_error_not_a_silently_cold_arm(tmp_path, monkeypatch):
    """The failure this prevents produces plausible numbers, not a crash:
    arms B and C would run cold while reporting themselves warm."""
    monkeypatch.setattr(cache_config, "VOLUME_ROOT", str(tmp_path / "not-mounted"))
    with pytest.raises(RuntimeError, match="not mounted"):
        handler_mod._prepare_cache_dirs(
            {"HF_HOME": str(tmp_path / "not-mounted" / "hf")}
        )


def test_mounted_volume_directory_is_created(tmp_path, monkeypatch):
    root = tmp_path / "mounted"
    root.mkdir()
    monkeypatch.setattr(cache_config, "VOLUME_ROOT", str(root))
    handler_mod._prepare_cache_dirs({"HF_HOME": str(root / "hf")})
    assert (root / "hf").is_dir()
