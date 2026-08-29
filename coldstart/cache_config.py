from dataclasses import dataclass

# Shared, pre-staged locations on the network volume — deliberately *not* namespaced by
# run: the entire point of "warm" is that a later run finds what an earlier run put here.
VOLUME_ROOT = "/runpod-volume"
VOLUME_HF_HOME = f"{VOLUME_ROOT}/hf"
VOLUME_VLLM_CACHE_ROOT = f"{VOLUME_ROOT}/vllm-cache"

# Cold locations. These must never be shared between runs (see CacheConfig.env below) —
# unlike the volume paths above, "cold" only holds if a reused serverless worker cannot
# find another run's leftovers here.
COLD_HF_ROOT = "/tmp/hf-cold"
COLD_VLLM_CACHE_ROOT = "/tmp/vllm-cache-cold"


@dataclass(frozen=True)
class CacheConfig:
    """The single interface that differs between arms — see spec 6.3.

    Cache configuration is a single interface with three implementations, and it is the
    only thing that differs between arms. Same image digest, same entrypoint, same
    engine flags — one swapped object. If arm behavior diverges anywhere else in this
    codebase, the single-variable claim is false and the experiment is compromised.
    `tests/test_arm_isolation.py` checks that structurally rather than hoping it holds.
    """

    arm: str
    weights_source: str  # "hub" | "volume"
    compile_cache_warm: bool

    def env(self, run_id: str) -> dict[str, str]:
        """Every arm sets the same variable names. Only values differ.

        A cold path is namespaced by `run_id` so that a serverless worker reused across
        runs can never silently serve one run's downloaded weights or compiled
        artifacts to another run's cold arm (spec risk table: "Compile cache leaking
        into a cold arm"). Per-run engine-output verification, done downstream, is a
        detector for this; making the path unique is the preventative.

        `run_id` is a required input, not generated here: this module must stay free of
        its own randomness so the emitted config is reproducible from a stored
        `RunRecord.run_id` (coldstart/schema.py) after the fact.
        """
        if not run_id:
            raise ValueError(f"run_id must be a non-empty string, got {run_id!r}")
        if "/" in run_id:
            raise ValueError(f"run_id must not contain '/': {run_id!r}")

        hf_home = VOLUME_HF_HOME if self.weights_source == "volume" else f"{COLD_HF_ROOT}/{run_id}"
        cache_root = (
            VOLUME_VLLM_CACHE_ROOT
            if self.compile_cache_warm
            else f"{COLD_VLLM_CACHE_ROOT}/{run_id}"
        )
        return {"HF_HOME": hf_home, "VLLM_CACHE_ROOT": cache_root}


# Arm C is settled. The reconnaissance run (spec 5, 6.8) asked whether the pinned vLLM
# version compiles at startup at all — if it did not, arm C would collapse into arm B and
# the experiment would revert to two arms. It does: the captures show `torch.compile took
# 38.96 s in total` against a 53.73 s engine init (fixtures/README.md, Q3). H3 and arm C
# are retained, and docs/experiment.md pre-registers them on that basis.
CACHE_CONFIGS = {
    "A": CacheConfig("A", weights_source="hub", compile_cache_warm=False),
    "B": CacheConfig("B", weights_source="volume", compile_cache_warm=False),
    "C": CacheConfig("C", weights_source="volume", compile_cache_warm=True),
}


def resolve(arm: str) -> CacheConfig:
    try:
        return CACHE_CONFIGS[arm]
    except KeyError:
        raise ValueError(f"unknown arm {arm!r}; known: {sorted(CACHE_CONFIGS)}") from None
