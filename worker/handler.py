"""RunPod serverless handler. Returns the stage bundle as the job result.

Telemetry rides the result channel rather than the log channel, so no run is
lost to log-retrieval failure -- see spec 6.1.
"""

import os
import socket
import subprocess

from probe import run_probe

from coldstart import cache_config
from coldstart.cache_config import resolve
from coldstart.recorder import StageRecorder

# Serve arguments held fixed across arms (spec "Held fixed"). They are read from
# the endpoint environment rather than the job input: a per-job override would
# make them a second thing that can differ between arms, and the single-variable
# claim allows exactly one -- the cache configuration.
_FIXED_SERVE_ENV = (
    ("MODEL_REVISION", "--revision"),
    ("MAX_MODEL_LEN", "--max-model-len"),
)


def _serve_args() -> list[str]:
    """Flags appended to `vllm serve`, omitting any that are unset.

    An unset value yields no flag at all rather than an empty string, which
    `vllm serve` would reject or, worse, interpret.
    """
    args: list[str] = []
    for var, flag in _FIXED_SERVE_ENV:
        value = os.environ.get(var)
        if value:
            args += [flag, value]
    return args


def _prepare_cache_dirs(env_overrides: dict) -> None:
    """Create the run's cache directories, refusing to fabricate the volume.

    A cold path is per-run and will not exist on a reused worker, so it is
    created. A volume path is different: if the network volume is not mounted,
    creating it would silently put the directory on container disk, and arms B
    and C would run cold while reporting themselves warm -- an invalid
    experiment that still produces plausible numbers. That fails loudly instead.
    """
    root = cache_config.VOLUME_ROOT
    for path in env_overrides.values():
        on_volume = path == root or path.startswith(root + "/")
        if on_volume and not os.path.isdir(root):
            raise RuntimeError(
                    f"{path!r} is on the network volume but {root!r} is not mounted; "
                    "creating it would put the cache on container disk and make this "
                    "arm silently cold"
                )
        os.makedirs(path, exist_ok=True)


def _gpu_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        ).stdout.strip()
        name, driver = (p.strip() for p in out.split(",")[:2])
    except Exception:  # noqa: BLE001 - nvidia-smi absence, timeout and malformed
        # output are all equally "we could not read the GPU", and host metadata
        # must never be the reason a measured run is thrown away.
        name, driver = "unknown", "unknown"
    return {
        "gpu_model": name,
        "driver_version": driver,
        # In-container identity. The platform's own worker identity arrives
        # separately on clock C (`runpod_api.extract_worker_id`); the driver
        # reconciles the two, since only the latter is stable across the
        # container restarts that a reused serverless worker performs.
        "host_id": socket.gethostname(),
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
    }


def handler(job):
    payload = job.get("input") or {}
    # Both are required and neither is defaulted. A run that cannot say which
    # arm it belongs to is not a slightly worse data point, it is a mislabelled
    # one, and a default would silently attribute it to whichever arm was
    # chosen here.
    arm = payload["arm"]
    run_id = payload["run_id"]

    config = resolve(arm)
    env_overrides = config.env(run_id)

    _prepare_cache_dirs(env_overrides)

    model = os.environ["MODEL_ID"]
    result = run_probe(
        StageRecorder(),
        model,
        extra_args=_serve_args(),
        env_overrides=env_overrides,
    )

    result["run_id"] = run_id
    result["arm"] = arm
    result["host"] = _gpu_info()
    # What the arm actually resolved to, carried with the run so the analysis
    # can verify the arm from the record instead of trusting the label.
    result["cache_config"] = {
        "arm": config.arm,
        "weights_source": config.weights_source,
        "compile_cache_warm": config.compile_cache_warm,
        "env": dict(env_overrides),
    }
    result["compile_cache_observed"] = os.path.isdir(
        os.path.join(env_overrides["VLLM_CACHE_ROOT"], "torch_compile_cache")
    )
    return result


def main():
    # Imported here, not at module scope, so the handler stays importable for
    # tests on a machine without the runpod SDK -- and so importing it never
    # starts a server as a side effect.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
