import pytest

from coldstart.cache_config import CACHE_CONFIGS, resolve


def test_three_arms_exist():
    assert sorted(CACHE_CONFIGS) == ["A", "B", "C"]


def test_arm_a_is_fully_cold():
    c = resolve("A")
    assert c.arm == "A"
    assert c.weights_source == "hub"
    assert c.compile_cache_warm is False


def test_arm_b_caches_weights_only():
    c = resolve("B")
    assert c.arm == "B"
    assert c.weights_source == "volume"
    assert c.compile_cache_warm is False


def test_arm_c_caches_both():
    c = resolve("C")
    assert c.arm == "C"
    assert c.weights_source == "volume"
    assert c.compile_cache_warm is True


def test_env_variable_names_are_identical_across_arms():
    """Every arm must expose the same variable *names* — spec 6.3: same image, same
    entrypoint, same flags, one swapped object. Only the values may differ."""
    envs = {arm: set(resolve(arm).env("run-fixed").keys()) for arm in CACHE_CONFIGS}
    assert envs["A"] == envs["B"] == envs["C"] == {"HF_HOME", "VLLM_CACHE_ROOT"}


def test_arm_a_env_values():
    """Arm A: everything cold, everything namespaced under this run's id.

    A constant-dict env() (the single most damaging possible bug in this file — it would
    make every arm identical) fails this because the values below are arm-specific
    literals, not derived from CACHE_CONFIGS or from each other.
    """
    assert resolve("A").env("run-123") == {
        "HF_HOME": "/tmp/hf-cold/run-123",
        "VLLM_CACHE_ROOT": "/tmp/vllm-cache-cold/run-123",
    }


def test_arm_b_env_values():
    """Arm B: weights pinned to the shared volume, compile cache still cold-and-unique."""
    assert resolve("B").env("run-123") == {
        "HF_HOME": "/runpod-volume/hf",
        "VLLM_CACHE_ROOT": "/tmp/vllm-cache-cold/run-123",
    }


def test_arm_c_env_values():
    """Arm C: both caches pinned to the shared, pre-warmed volume paths."""
    assert resolve("C").env("run-123") == {
        "HF_HOME": "/runpod-volume/hf",
        "VLLM_CACHE_ROOT": "/runpod-volume/vllm-cache",
    }


def test_arm_a_does_not_point_at_the_volume():
    """Guards against the arm-A-pointing-at-the-volume mutation directly: neither of
    arm A's paths may be the shared volume, no matter what arm B/C produce."""
    env = resolve("A").env("run-123")
    assert "/runpod-volume" not in env["HF_HOME"]
    assert "/runpod-volume" not in env["VLLM_CACHE_ROOT"]


def test_cold_paths_are_unique_per_run():
    """The defect this file exists to prevent: a reused serverless worker must never be
    able to serve one run's leftover cache to another run's cold arm (spec risk table,
    "Compile cache leaking into a cold arm"). Cold paths must vary with run_id.
    """
    env1 = resolve("A").env("run-1")
    env2 = resolve("A").env("run-2")
    assert env1["HF_HOME"] != env2["HF_HOME"]
    assert env1["VLLM_CACHE_ROOT"] != env2["VLLM_CACHE_ROOT"]

    b1 = resolve("B").env("run-1")
    b2 = resolve("B").env("run-2")
    assert b1["VLLM_CACHE_ROOT"] != b2["VLLM_CACHE_ROOT"]


def test_warm_paths_are_stable_across_runs():
    """The flip side of uniqueness: a *warm* (pre-staged) path must be the same path on
    every run, or the whole point of pre-staging — that a later run finds what an
    earlier run put there — is defeated."""
    assert resolve("B").env("run-1")["HF_HOME"] == resolve("B").env("run-2")["HF_HOME"]
    assert (
        resolve("C").env("run-1")["VLLM_CACHE_ROOT"] == resolve("C").env("run-2")["VLLM_CACHE_ROOT"]
    )


def test_run_id_is_required_input_not_generated():
    """This module must not manufacture its own randomness — the emitted config has to
    be reproducible from a stored run record (the run_id already written to RunRecord)."""
    with pytest.raises(TypeError):
        resolve("A").env()


@pytest.mark.parametrize("bad_run_id", ["", "a/b", "../escape"])
def test_env_rejects_malformed_run_id(bad_run_id):
    with pytest.raises(ValueError, match="run_id"):
        resolve("A").env(bad_run_id)


def test_unknown_arm_is_a_named_error():
    """Every other module in this codebase fails loudly with a message naming what was
    valid (see coldstart/analysis/stats.py's `unknown percentile` errors) — this must
    match, not raise a bare KeyError."""
    with pytest.raises(ValueError, match=r"unknown arm 'Z'.*'A', 'B', 'C'"):
        resolve("Z")
