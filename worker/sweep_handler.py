"""RunPod handler for one (level, repeat) of the service-curve sweep.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/sweep_handler.py`. The image's default CMD stays artifact 1's
measurement handler.

One job is one scheduled run: start the engine, decide how artifact 1's prompt
reaches it, warm up one wave, run one measured `vllm bench serve` at the
level's concurrency with the GPU sampler running, stop the engine, and return
a compact summary. Telemetry rides the result channel, as artifact 1's handler
does, so no run is lost to log retrieval.

Why one job per (level, repeat), not one per level. The endpoint's execution
timeout is 1800 s (docs/runbook.md). Artifact 1 measured this engine's startup
at a p95 of 86 s with weights on the network volume and a cold compile cache
(arm B, data/analysis.json), and 55 s warm (arm C). A measured run lasts about
DEFAULT_WAVES = 20 waves of latency(level): 20 x 0.3-2.1 s, 6-42 s, on the
placeholder curve, with at least 100 requests. So a job is about three minutes
against a 30-minute limit, with room for a measured curve ten times slower
than the placeholder. A job per level would fit too, but its three repeats
would run back to back on one engine, which owner decision 2 forbids, and its
interval would never see engine-to-engine variation. A single job for the
whole sweep was rejected for the same reason, and because one failure would
lose every point.

Returns `healthy: True` whenever the engine answered `/health`, because that
is the field `RunPodSubmitter` treats as success. A measurement that then
failed comes back as `run: None` with a `run_error`, and
`harness.service_sweep.build_sweep_record` stores it as a failed run.
"""

import importlib.util
import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from harness.sweep_worker import choose_prompt_path, max_num_seqs_from_log, run_one
from harness.vllm_logs import parse_engine_log

# Artifact 1's prompt, byte for byte (worker/probe.py PROMPT). Copied, not
# imported: probe.py imports coldstart.analysis.metrics, and the sweep must
# not drag artifact 1's package into its path. tests/test_sweep_handler.py
# pins the two equal.
A1_PROMPT = "Explain what a key-value cache does, in two sentences."
# Seconds kept back from the job budget for teardown and the result upload.
TEARDOWN_RESERVE_S = 120.0
_HELP_CHARS = 200_000
# What comes back of the engine's log, and why it is a head and a tail rather
# than the whole of it. RunPod's maximum job-output size is UNVERIFIED (plan
# item 12), and `--enable-log-requests` (which a diagnostic job may pass) logs
# a line per request: a run of 100+ requests plus the engine's own startup can
# reach several MB, and an over-size output would cost the whole job's result,
# not just the log. The head holds startup (about 135 lines in the three
# captured logs, fixtures/vllm_logs/): the engine arguments and the KV-cache
# line. The tail holds the last thing the engine said, which is where a crash
# or a shutdown shows. Everything the sweep READS from the log is extracted
# from the full log before this cap (`_engine_facts`, `collect_diagnostics`),
# so nothing downstream depends on a line that the cap can drop; the lines
# returned are evidence for a human, and `log_lines_total` / `log_truncated`
# say when they are partial. Rejected: shipping everything, and compressing it
# (a job output limit counts bytes on the wire, and the log is the one field
# nobody parses). 400 + 400 is ~3x the startup log on each side.
LOG_HEAD_LINES = 400
LOG_TAIL_LINES = 400
# A request log line can hold the whole prompt; a line count alone would not
# bound the bytes. Applied to the lines that survive the head/tail cut.
LOG_LINE_CHARS = 2000
# Read from the endpoint environment, as worker/handler.py does, so they
# cannot differ between jobs of one campaign. Duplicated from handler.py
# rather than imported for the same reason as A1_PROMPT.
_FIXED_SERVE_ENV = (
    ("MODEL_REVISION", "--revision"),
    ("MAX_MODEL_LEN", "--max-model-len"),
)


def fixed_serve_args() -> list[str]:
    args: list[str] = []
    for var, flag in _FIXED_SERVE_ENV:
        value = os.environ.get(var)
        if value:
            args += [flag, value]
    return args


def serve_args_for(payload_args) -> list[str]:
    owned = {flag for _, flag in _FIXED_SERVE_ENV}
    clash = [a for a in payload_args if a.split("=", 1)[0] in owned]
    if clash:
        raise ValueError(
            f"serve_args {clash} set flags the endpoint environment owns; a per-job "
            "value would let one campaign's runs measure different engines"
        )
    return [*fixed_serve_args(), *payload_args]


def count_tokens(base_url: str, model: str, prompt: str) -> int:
    """The engine's own token count for the prompt, from vLLM's `/tokenize`.

    The server's count rather than a local tokenizer's: the bench client
    tokenizes with the model's tokenizer at its default revision, the engine
    with the pinned one, and only the engine's count is the prompt it serves.
    """
    r = requests.post(
        f"{base_url}/tokenize", json={"model": model, "prompt": prompt}, timeout=30
    )
    r.raise_for_status()
    return len(r.json()["tokens"])


def host_info() -> dict:
    return {"host_id": socket.gethostname(), "runpod_pod_id": os.environ.get("RUNPOD_POD_ID")}


def _engine_facts(lines) -> dict:
    parsed = parse_engine_log("\n".join(lines))
    max_num_seqs, source = max_num_seqs_from_log(lines)
    return {
        **parsed.engine_info,
        "s4_subphases": parsed.phases,
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
    }


def capped_log(lines) -> dict:
    """The log fields of the job output: head, tail, the true count, a flag.

    `log_head_lines` is where the head ends in `log_lines`, so a reader can
    tell the gap from the seam. When the whole log fits, nothing is dropped
    and `log_truncated` is False. See LOG_HEAD_LINES for why it is capped.
    """
    total = len(lines)
    if total <= LOG_HEAD_LINES + LOG_TAIL_LINES:
        kept, head = list(lines), total
    else:
        kept, head = list(lines[:LOG_HEAD_LINES]) + list(lines[-LOG_TAIL_LINES:]), LOG_HEAD_LINES
    kept = [
        line if len(line) <= LOG_LINE_CHARS
        else f"{line[:LOG_LINE_CHARS]}...[{len(line) - LOG_LINE_CHARS} more chars cut]"
        for line in kept
    ]
    return {
        "log_lines": kept,
        "log_lines_total": total,
        "log_head_lines": head,
        "log_truncated": total > LOG_HEAD_LINES + LOG_TAIL_LINES,
    }


def collect_diagnostics(run_command: Callable, log_lines) -> dict:
    """In-container checks the first paid run needs, asked for per job.

    Each answers an item this repository could not verify without the image:
    whether the tool accepts every flag `harness.bench` passes (its help
    text), whether `pandas` -- which the custom dataset needs -- is installed,
    what nvidia-smi prints for the sampler's query, and whether the engine
    logged artifact 1's prompt text (only if the job's serve args turned
    request logging on). Never part of an ordinary job: the help text alone
    is tens of kilobytes.
    """

    def capture(cmd):
        try:
            proc = run_command(cmd, capture_output=True, text=True, check=False, timeout=120)
        except Exception as e:  # noqa: BLE001 -- a diagnostic never fails the job
            return {"cmd": cmd, "error": repr(e)}
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-_HELP_CHARS:],
            "stderr": (proc.stderr or "")[-2000:],
        }

    return {
        "bench_help": capture(["vllm", "bench", "serve", "--help"]),
        "nvidia_smi": capture(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits",
             "--id=0"]
        ),
        "pandas_importable": importlib.util.find_spec("pandas") is not None,
        "prompt_in_log": any(A1_PROMPT in line for line in log_lines),
    }


@dataclass
class Deps:
    """The handler's effects, injectable so tests run it without an engine.

    None means "the real one", resolved lazily so importing this module never
    needs vLLM, the runpod SDK, or a GPU.
    """

    served: Callable | None = None
    run_bench: Callable | None = None
    sampler_factory: Callable | None = None
    count_tokens: Callable[[str, str, str], int] = count_tokens
    host_info: Callable[[], dict] = host_info
    run_command: Callable = subprocess.run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(deps: Deps) -> Deps:
    if deps.served is None:
        from harness.serve import served

        deps.served = served
    if deps.run_bench is None:
        from harness.bench import run_bench

        deps.run_bench = run_bench
    if deps.sampler_factory is None:
        from harness.gpu_util import GpuUtilSampler

        deps.sampler_factory = GpuUtilSampler
    return deps


def handler(job, deps: Deps | None = None) -> dict:
    d = _resolve(deps or Deps())
    t0 = d.clock()
    p = job.get("input") or {}
    # Required and never defaulted: a run that cannot say which level it
    # measured is a mislabelled point, not a slightly worse one.
    run_id, level = p["run_id"], int(p["level"])
    model = os.environ["MODEL_ID"]
    args = serve_args_for(p["serve_args"])
    common = {"run_id": run_id, "level": level, "repeat": p["repeat"], "host": d.host_info()}
    want_diagnostics = bool(p.get("diagnostics"))
    deadline = t0 + float(p["job_budget_s"]) - TEARDOWN_RESERVE_S
    with d.served(model, args=args, env={}) as server, tempfile.TemporaryDirectory() as tmp:
        startup_s = d.clock() - t0
        if not server.healthy:
            lines = list(server.log_lines)
            out = {
                "healthy": False,
                **capped_log(lines),
                "served_cmd": list(server.cmd),
                "startup_s": startup_s,
                **common,
            }
            if want_diagnostics:
                out["diagnostics"] = collect_diagnostics(d.run_command, lines)
            return out
        try:
            plan = choose_prompt_path(
                server.base_url,
                model=model,
                prompt=A1_PROMPT,
                output_len=p["output_len"],
                workdir=tmp,
                run_bench=d.run_bench,
                count_tokens=lambda prompt: d.count_tokens(server.base_url, model, prompt),
            )
            run = run_one(
                server.base_url,
                model=model,
                level=level,
                num_prompts=p["num_prompts"],
                warmup_prompts=p["warmup_prompts"],
                plan=plan,
                seed=p["seed"],
                workdir=tmp,
                run_bench=d.run_bench,
                sampler_factory=d.sampler_factory,
                deadline=deadline,
                clock=d.clock,
                keep_raw=want_diagnostics,
            )
            run_error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6); the
            # engine's log and teardown below must survive a failed measurement.
            run, run_error = None, f"{type(e).__name__}: {e}"
        teardown_s = server.stop()
    lines = list(server.log_lines)
    out = {
        "healthy": True,
        "run": run,
        "run_error": run_error,
        "served_cmd": list(server.cmd),
        "engine": _engine_facts(lines),
        **capped_log(lines),
        "startup_s": startup_s,
        "teardown_s": teardown_s,
        **common,
    }
    if want_diagnostics:
        out["diagnostics"] = collect_diagnostics(d.run_command, lines)
    return out


def main():
    # Imported here so tests can import the handler without the runpod SDK,
    # and so importing it never starts a server.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
