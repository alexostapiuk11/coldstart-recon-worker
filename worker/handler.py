"""RunPod serverless handler. Returns the stage bundle as the job result.

Telemetry rides the result channel rather than the log channel, so no run is
lost to log-retrieval failure -- see spec 6.1.
"""

import os
import shutil
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


def _compile_cache_present(env_overrides: dict) -> bool:
    """Whether this arm's torch.compile cache directory exists right now.

    Purely a directory check: it cannot tell "a previous run already
    compiled here" apart from "this run's own compile just finished and
    wrote the directory". Callers control which of those two questions gets
    asked by choosing *when* they call this -- see the two call sites in
    handler() below, which ask it at different points for different reasons.

    Also cannot tell "warm because this exact model/config was compiled
    here before" apart from "warm because a *different* model or config was
    compiled here before" -- a volume path carrying a stale cache for
    another model would read True either way. Out of scope while this
    campaign pins one model and one set of engine flags across the whole
    run (spec "Held fixed"), but a real limitation if that ever changes.
    """
    return os.path.isdir(os.path.join(env_overrides["VLLM_CACHE_ROOT"], "torch_compile_cache"))


def _purge_cold_roots() -> None:
    """Empty the cold cache roots before the run starts.

    Clearing this run's own directories afterwards is not enough on its own.
    A serverless worker outlives any single run, and it can inherit a disk
    already full of directories some earlier run left behind -- one that
    crashed before its cleanup, or one from a previous campaign under an
    image that had no cleanup at all. That is not hypothetical: the first run
    of the restarted campaign died with "No space left on device" on a worker
    still holding the previous campaign's arm A weights.

    Purging at the start makes a worker self-healing regardless of what it
    inherited, which end-cleanup alone cannot do. Safe because workersMax is
    1, so no other run on this worker is using these paths.

    Only the cold roots, never the volume: those hold the warm caches arms B
    and C exist to measure.
    """
    for root in (cache_config.COLD_HF_ROOT, cache_config.COLD_VLLM_CACHE_ROOT):
        shutil.rmtree(root, ignore_errors=True)


def _clear_cold_dirs(env_overrides: dict) -> None:
    """Remove this run's per-run cold cache directories.

    They are namespaced by run_id so a reused serverless worker cannot serve
    one run's downloaded weights or compiled artifacts to the next run's cold
    arm. That isolation is only needed WHILE the run is measured; afterwards
    the directory is dead weight.

    Leaving them cost a campaign. Arm A writes ~15.3 GiB of weights per run to
    container disk, the disk is 60 GB, and nothing removed them -- so the
    fourth arm A run on a given worker died with "No space left on device
    (os error 28)" before the engine could start. It presented as a repeating
    three-good-then-fail cycle, resetting whenever the worker recycled, and it
    is worse than a plain failure: the attrition falls on one arm, biasing the
    primary A->B contrast through survivorship rather than showing up as
    noise.

    Volume paths are never touched. They are the warm caches arms B and C
    exist to measure, and deleting one would silently turn a warm arm cold.
    """
    root = cache_config.VOLUME_ROOT
    for path in env_overrides.values():
        if path == root or path.startswith(root + "/"):
            continue
        shutil.rmtree(path, ignore_errors=True)


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

    # Before creating this run's directories, drop anything a previous run
    # left on this worker's disk. See _purge_cold_roots.
    _purge_cold_roots()
    _prepare_cache_dirs(env_overrides)

    # Snapshot the cache state BEFORE run_probe(), not after. The gate this
    # feeds (metrics.derive()'s arm-state check, Task 4b) asks "was this
    # arm's cache warm when the run STARTED" -- but a COLD compile creates
    # `torch_compile_cache/` as a side effect of *finishing*. Fixture
    # evidence from a run known to be a first-ever cache miss
    # (fixtures/vllm_logs/startup_0.log): "Using cache directory: .../
    # torch_compile_cache/.../backbone" followed later by "saved AOT
    # compiled function to .../torch_compile_cache/torch_aot_compile/...",
    # after which fixtures/runpod_api/status_0.json shows the directory
    # present. A plain os.path.isdir() cannot distinguish "found a
    # pre-existing cache" from "just created one by compiling" -- both read
    # True. Reading it after run_probe() returns would therefore report
    # compile_cache_observed=True for every genuinely cold arm A/B run,
    # tripping the arm-state gate on exactly the healthy runs it must not
    # discard, and silently passing the actual leak (a warm cache surviving
    # onto a cold arm) undetected in the other direction.
    #
    # This is the subtlety that gets "simplified" back into a bug later:
    # moving this call to after run_probe() below will look harmless (it
    # still reports *a* boolean) while quietly discarding ~2/3 of a paid
    # campaign. Do not move it.
    compile_cache_observed = _compile_cache_present(env_overrides)

    model = os.environ["MODEL_ID"]
    try:
        result = run_probe(
            StageRecorder(),
            model,
            extra_args=_serve_args(),
            env_overrides=env_overrides,
        )
        result = _finish(result, run_id, arm, config, env_overrides, compile_cache_observed)
    finally:
        # After every observation, never between them: _finish reads the
        # post-run cache state, and clearing first would report False for a
        # cold arm that did compile, destroying the diagnostic. In a finally
        # because a failed run consumed the disk too, and the next run on
        # this worker needs it back -- skipping cleanup on the failure path
        # is how one bad run makes every later arm A run on that worker fail.
        _clear_cold_dirs(env_overrides)
    return result


def _finish(result, run_id, arm, config, env_overrides, compile_cache_observed):
    """Attach the run's provenance and post-run observations."""
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
    # The field metrics.derive()'s arm-state gate consumes -- the pre-probe
    # reading captured above.
    result["compile_cache_observed"] = compile_cache_observed
    # Diagnostic only; never consumed by the gate. A cold arm SHOULD show
    # False before and True after (its own compile just wrote the cache); a
    # cold arm reading False for both means torch.compile never wrote a
    # cache at all, which is itself worth seeing during reconnaissance.
    result["compile_cache_present_after"] = _compile_cache_present(env_overrides)
    return result


def main():
    # Imported here, not at module scope, so the handler stays importable for
    # tests on a machine without the runpod SDK -- and so importing it never
    # starts a server as a side effect.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
