"""Fakes for artifact 4's worker side: engines that start on named ports,
nvidia-smi memory readings on a script, and a clock a test advances.

Not a test module; test files import it by name, as they import sweep_fakes.
"""

import contextlib
import subprocess

from sweep_fakes import KV_LINE, NON_DEFAULT_LINE, VERSION_LINE

COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"
# The two lines plan 3's figure 4 splits a swap-in by (placement/stages.py).
LOADING_LINE = ("(EngineCore pid=340) INFO 10-04 12:00:20 [model_runner.py:329] Model loading took "
                "7.49 GiB and 8.0 seconds")
INIT_LINE = ("(EngineCore pid=340) INFO 10-04 12:00:40 [core.py:348] init engine (profile, create "
             "kv cache, warmup model) took {s} s (compilation: {c} s)")


class Clock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeServer:
    def __init__(self, model, args, port, healthy, log_lines):
        self.model = model
        self.base_url = f"http://127.0.0.1:{port}"
        self.cmd = ["vllm", "serve", model, "--port", str(port), *args]
        self.healthy = healthy
        self.log_lines = list(log_lines)
        self.stops = 0

    def stop(self) -> float:
        self.stops += 1
        return 0.5


class FakeEngines:
    """`served` that records every start, takes `startup_s` of fake time per
    engine, and logs a compile time per model."""

    def __init__(self, clock: Clock, *, startup_s=None, healthy=None, compile_s=None):
        self.clock = clock
        self.startup_s = startup_s or {}
        self.healthy = healthy or {}
        self.compile_s = compile_s or {}
        self.started: list[FakeServer] = []

    @contextlib.contextmanager
    def served(self, model, *, args, env, port=8000, health_timeout=900.0):
        assert env.get("HF_HUB_OFFLINE") == "1", "engines must never download mid-measurement"
        self.clock.t += self.startup_s.get(model, 30.0)
        compile_s = self.compile_s.get(model, 19.0)
        lines = [VERSION_LINE, NON_DEFAULT_LINE, KV_LINE, LOADING_LINE,
                 COMPILE_LINE.format(s=compile_s), INIT_LINE.format(s=compile_s + 10.0, c=compile_s)]
        server = FakeServer(model, args, port, self.healthy.get(model, True), lines)
        self.started.append(server)
        try:
            yield server
        finally:
            server.stop()


def memory_script(readings):
    """A `subprocess.run` stand-in answering nvidia-smi with each reading in
    turn (MiB used), then the last one forever. None means the query fails."""
    state = {"i": 0}

    def run(cmd, **kwargs):
        i = min(state["i"], len(readings) - 1)
        state["i"] += 1
        used = readings[i]
        if used is None:
            return subprocess.CompletedProcess(cmd, 9, "", "NVML: not found")
        return subprocess.CompletedProcess(cmd, 0, f"{used}, 24564\n", "")

    return run
