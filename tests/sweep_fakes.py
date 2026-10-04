"""Fakes for the sweep handler: an engine, a bench and a GPU sampler that
follow a known timing model, so a test can check the sweep recovers exactly
what was put in. Not a test module (no `test_` prefix); test files import it
by name, which works because pytest puts tests/ on sys.path for them."""

import contextlib
import subprocess
from collections import Counter

from harness.bench import BenchError

PROMPT_TOKENS = 13
OUTPUT_LEN = 16
NON_DEFAULT_LINE = (
    "(APIServer pid=130) INFO 10-04 12:00:00 [api_utils.py:273] non-default args: "
    "{'model_tag': 'Qwen/Qwen3-8B', 'model': 'Qwen/Qwen3-8B', 'max_model_len': 8192, "
    "'max_num_seqs': 256}"
)
KV_LINE = "(EngineCore pid=340) INFO 10-04 12:00:40 [kv_cache_utils.py:2235] GPU KV cache size: 35,792 tokens"


def model_latency(level: int, repeat: int = 0) -> float:
    return 0.30 + 0.01 * level + 0.002 * repeat


def model_ttft(level: int) -> float:
    return 0.05 + 0.001 * level


def model_util(level: int) -> float:
    return min(1.0, 0.15 * level**0.5)


def bench_json(
    n: int, *, level: int, repeat: int = 0, input_len: int = PROMPT_TOKENS, n_failed: int = 0
) -> dict:
    """The tool's saved JSON for `n` requests, the first `n_failed` of which
    failed the way a timed-out request does: an error text, TTFT 0, no output."""
    latency, ttft = model_latency(level, repeat), model_ttft(level)
    itl = (latency - ttft) / (OUTPUT_LEN - 1)
    bad = [i < n_failed for i in range(n)]
    return {
        "duration": n / level * latency,
        "completed": n - n_failed,
        "failed": n_failed,
        "num_prompts": n,
        "max_concurrency": level,
        "output_throughput": OUTPUT_LEN * level / latency,
        "median_e2el_ms": latency * 1000,
        "input_lens": [input_len] * n,
        "output_lens": [0 if b else OUTPUT_LEN for b in bad],
        "ttfts": [0.0 if b else ttft for b in bad],
        "itls": [[] if b else [itl] * (OUTPUT_LEN - 1) for b in bad],
        "start_times": [0.0] * n,
        "generated_texts": ["x"] * n,
        "errors": ["Connection timeout" if b else "" for b in bad],
    }


class FakeServer:
    def __init__(self, model, args, healthy, log_lines=None):
        self.base_url = "http://127.0.0.1:8000"
        self.cmd = ["vllm", "serve", model, "--port", "8000", *args]
        self.healthy = healthy
        self.log_lines = (
            list(log_lines)
            if log_lines is not None
            else ["INFO fake engine starting", NON_DEFAULT_LINE, KV_LINE]
        )
        self.stops = 0

    def stop(self) -> float:
        self.stops += 1
        return 1.5


class FakeSampler:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def summary(self):
        util = model_util(self.engine.last_level)
        sample = {"t_s": 0.0, "raw": str(round(util * 100)), "util_pct": util * 100}
        # t0 and the request times (bench_json's start_times are 0.0) share a zero,
        # so the one sample falls inside the measured span
        return {"gpu_util": util, "t0_monotonic": 0.0, "t_exit_s": 10.0,
                "thread_stopped": True, "interval_s": 0.5, "n_samples": 1, "n_valid": 1,
                "samples": [sample]}


class FakeEngine:
    """One fake `vllm serve` plus `vllm bench serve`, shared across jobs.

    `measured[level]` counts measured runs per level, so each repeat of a
    level gets its own latency from `model_latency(level, repeat)`.
    `failed_requests` makes that many of each measured run's requests fail.
    """

    def __init__(
        self, *, healthy=True, probe_ok=True, fail_measured_at=None, log_lines=None,
        failed_requests=0,
    ):
        self.failed_requests = failed_requests
        self.healthy = healthy
        self.log_lines = log_lines
        self.probe_ok = probe_ok
        self.fail_measured_at = fail_measured_at
        self.served_calls = []
        self.bench_calls = []
        self.measured = Counter()
        self.last_level = 1
        self.servers = []
        self.commands = []

    @contextlib.contextmanager
    def served(self, model, *, args, env):
        self.served_calls.append({"model": model, "args": list(args), "env": dict(env)})
        server = FakeServer(model, args, self.healthy, self.log_lines)
        self.servers.append(server)
        try:
            yield server
        finally:
            server.stop()

    def run_bench(self, base_url, **kw):
        self.bench_calls.append(kw)
        name = kw["result_dir"].name
        if name == "prompt-probe":
            if not self.probe_ok:
                raise BenchError("vllm bench serve exited 1; ModuleNotFoundError: pandas")
            return bench_json(1, level=1)
        level = kw["max_concurrency"]
        self.last_level = level
        if name != "measured":
            return bench_json(kw["num_prompts"], level=level)
        repeat = self.measured[level]
        self.measured[level] += 1
        if self.fail_measured_at == (level, repeat):
            raise BenchError("vllm bench serve exited 1; this run has no result")
        return bench_json(
            kw["num_prompts"], level=level, repeat=repeat, n_failed=self.failed_requests
        )

    def sampler(self):
        return FakeSampler(self)

    def deps(self, deps_cls):
        return deps_cls(
            served=self.served,
            run_bench=self.run_bench,
            sampler_factory=self.sampler,
            count_tokens=lambda base_url, model, prompt: PROMPT_TOKENS,
            host_info=lambda: {"host_id": "fake-container"},
            run_command=self.run_command,
        )

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        is_help = cmd[:3] == ["vllm", "bench", "serve"]
        stdout = "--max-concurrency --save-detailed" if is_help else "42"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")
