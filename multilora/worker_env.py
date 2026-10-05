"""What the worker reads from the endpoint's environment (amendment §4).

Anything not under study is fixed in the endpoint environment rather than
passed per job, as artifact 1's handler does: a per-job override would be a
second thing that can differ between conditions. Missing values fail loudly
at job start, before any GPU time is spent on a misconfigured engine.
"""

import math
import os

VOLUME_ROOT = "/runpod-volume"
# Artifact 5's own compile-cache root. Separate from artifact 1's
# /runpod-volume/vllm-cache so the two artifacts' caches never mix.
VOLUME_ENV = {
    "HF_HOME": f"{VOLUME_ROOT}/hf",
    "VLLM_CACHE_ROOT": f"{VOLUME_ROOT}/a5/vllm-cache",
}
REQUIRED = (
    "MODEL_ID",
    "MODEL_REVISION",
    "MAX_MODEL_LEN",
    "A5_MAX_LORA_RANK",
    "A5_TARGET_MODULES",
    "A5_GPU_MEMORY_UTILIZATION",
)


def _memory_budget(raw: str) -> float:
    """The engine's GPU memory fraction, in (0, 1]. Fixed in the endpoint
    environment because vLLM's own default overshoots on this card with LoRA
    enabled (see `multilora.serving.serve_args`)."""
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not (math.isfinite(value) and 0 < value <= 1):
        raise RuntimeError(f"A5_GPU_MEMORY_UTILIZATION={raw!r} must be a number in (0, 1]")
    return value


def instance_kwargs(environ=None) -> dict:
    environ = os.environ if environ is None else environ
    missing = [k for k in REQUIRED if not environ.get(k)]
    if missing:
        raise RuntimeError(f"endpoint environment lacks {missing}")
    if environ.get("VLLM_TUNED_CONFIG_FOLDER"):
        raise RuntimeError(
            "VLLM_TUNED_CONFIG_FOLDER is set; tuned kernel configs key tile choice on "
            "max_loras, a second slot-dependent cost (amendment §3b). Unset it."
        )
    return {
        "model": environ["MODEL_ID"],
        "revision": environ["MODEL_REVISION"],
        "max_model_len": int(environ["MAX_MODEL_LEN"]),
        "rank": int(environ["A5_MAX_LORA_RANK"]),
        "target_modules": tuple(environ["A5_TARGET_MODULES"].split(",")),
        "gpu_memory_utilization": _memory_budget(environ["A5_GPU_MEMORY_UTILIZATION"]),
    }


def volume_env(isdir=os.path.isdir, makedirs=os.makedirs) -> dict:
    """Engine cache paths on the network volume, refusing to fabricate it.
    Creating a missing mount point would put the caches on container disk and
    make every instance compile cold while looking warm to nothing -- artifact
    1's handler refuses for the same reason."""
    if not isdir(VOLUME_ROOT):
        raise RuntimeError(f"{VOLUME_ROOT} is not mounted")
    for path in VOLUME_ENV.values():
        makedirs(path, exist_ok=True)
    return dict(VOLUME_ENV)
