"""In-container probe. Clock B. Brackets `vllm serve` and drives warmup.

Runs the canonical server path as a subprocess rather than the Python engine API,
because the artifact must measure the startup path people actually deploy --
see spec 6.3.
"""

import os
import re
import subprocess
import threading
import time

import requests

# The warmup trio is pre-registered (spec 7) and lives in the analysis layer.
# Imported, never re-defined: two copies of a pre-registered parameter are two
# copies free to drift, and the one that drifts silently is the one published.
from coldstart.analysis.metrics import (
    FAST_TOLERANCE,
    steady_state_latency,
    time_to_fast_index,
    warmup_penalty,
)

PORT = 8000
WARMUP_REQUESTS = 10
# Generation length for each warmup request. Env-overridable ONLY so a
# side diagnostic can ask whether the flat warmup curve is a property of the
# engine or of our request size -- the campaign leaves it unset and gets 16,
# so the pinned measurement path is unchanged. A diagnostic runs on its own
# template; it never shares the campaign's pinned image.
MAX_TOKENS = int(os.environ.get("WARMUP_MAX_TOKENS") or 16)
PROMPT = "Explain what a key-value cache does, in two sentences."

# Predicates read off the real captures in fixtures/vllm_logs/ (vLLM 0.27.1),
# same discipline as coldstart/vllm_logs.py: message text, never invented.
#
# "Model loading took ..." is the engine reporting the model resident on GPU.
# It is deliberately not "Loading weights took ...", which is the weight loader
# finishing an earlier, different step -- matching that would end T_weights
# before the model is actually on the device.
_LOAD_COMPLETE = re.compile(r"Model loading took\s", re.IGNORECASE)

# The engine's own init summary -- the end of S4. Deliberately not the
# "Starting vLLM server on ..." or "Application startup complete." lines: those
# are S5, and marking S4_end at either would fold all of S5 into S4, the exact
# substitution metrics.derive() refuses to make.
_ENGINE_UP = re.compile(
    r"init engine \(profile, create kv cache, warmup model\) took\s", re.IGNORECASE
)


def _is_load_complete(line: str) -> bool:
    return bool(_LOAD_COMPLETE.search(line))


def _is_engine_up(line: str) -> bool:
    return bool(_ENGINE_UP.search(line))


def _wait_healthy(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.25)
    return False


def _one_request(model: str, now) -> dict:
    """One warmup request. `now()` is the recorder's clock, not time.monotonic.

    `t_dispatch_mono` (B5) is the absolute clock-B instant this request was
    dispatched, and it must share the stage marks' origin: metrics.t_fast_seconds
    subtracts it from the S7_warmup_done mark, which the recorder stores relative
    to t0. A raw time.monotonic() here would be larger by the process uptime and
    make the tail negative on every real run.

    Without this field T_fast is unmeasurable and is never inferred by summing
    end_to_end, which would assume zero gap between sequential requests.
    """
    t_start = now()
    ttft = None
    with requests.post(
        f"http://127.0.0.1:{PORT}/v1/completions",
        json={"model": model, "prompt": PROMPT, "max_tokens": MAX_TOKENS, "stream": True},
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        for chunk in r.iter_lines():
            if chunk and ttft is None:
                ttft = now() - t_start
    return {"t_dispatch_mono": t_start, "ttft": ttft, "end_to_end": now() - t_start}


def run_probe(
    recorder,
    model: str,
    health_timeout: float = 900.0,
    extra_args=(),
    env_overrides: dict | None = None,
) -> dict:
    """Returns the stage bundle. Caller owns the record assembly.

    `extra_args` are appended to `vllm serve` -- the pinned `--revision` and the
    `--max-model-len` held fixed across arms. Both are the caller's to supply:
    this module measures a startup, it does not decide what is being started.

    `env_overrides` is the arm's cache configuration (`CacheConfig.env`). It is
    merged into a copy of the environment for the subprocess only, never applied
    to `os.environ`: a serverless worker is reused across jobs, and mutating the
    process environment would let one run's paths survive into the next run's
    arm -- the leak this configuration exists to prevent.
    """
    recorder.start()
    recorder.mark("S1_imports_done")

    log_lines: list[str] = []
    seen_load = False
    seen_engine_up = False
    recorder.mark("S2_acquisition_start")
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    cmd = ["vllm", "serve", model, "--port", str(PORT), *extra_args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    def drain():
        nonlocal seen_load, seen_engine_up
        for line in proc.stdout:
            log_lines.append(line.rstrip("\n"))
            if not seen_load and _is_load_complete(line):
                seen_load = True
                recorder.mark("S3_load_done")
                # Device init begins the instant weights are resident, so the
                # two marks name the same instant.
                recorder.mark("S4_start")
            if not seen_engine_up and _is_engine_up(line):
                seen_engine_up = True
                recorder.mark("S4_end")

    drain_thread = threading.Thread(target=drain, daemon=True)
    drain_thread.start()

    healthy = _wait_healthy(health_timeout)
    recorder.mark("S5_ready")
    if not healthy:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        drain_thread.join(timeout=15)
        return {
            "healthy": False,
            "served_cmd": cmd,
            "env_applied": dict(env_overrides or {}),
            "log_lines": log_lines,
            "warmup": [],
            "clock_B": recorder.bundle(),
        }

    warmup = []
    for i in range(WARMUP_REQUESTS):
        if i == 0:
            recorder.mark("S6_request1_dispatch")
        result = _one_request(model, recorder.now)
        if i == 0:
            recorder.mark("S6_first_token")
        warmup.append({"req_index": i, **result})
    recorder.mark("S7_warmup_done")

    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    # stdout reaches EOF only once the process is gone; join so the drain
    # thread finishes appending before log_lines is read.
    drain_thread.join(timeout=15)

    steady = steady_state_latency(warmup)
    return {
        "healthy": True,
        "served_cmd": cmd,
        "env_applied": dict(env_overrides or {}),
        "log_lines": log_lines,
        "warmup": warmup,
        "clock_B": recorder.bundle(),
        "drain_completed": not drain_thread.is_alive(),
        "derived": {
            "steady_state_latency": steady,
            "warmup_penalty": warmup_penalty(warmup, steady),
            "time_to_fast_index": time_to_fast_index(warmup, steady),
            # Recorded with the run so the tolerance that produced the index is
            # provable from the stored record rather than assumed.
            "fast_tolerance": FAST_TOLERANCE,
        },
    }
