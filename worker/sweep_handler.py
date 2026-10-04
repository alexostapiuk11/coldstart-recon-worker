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
import sys
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
# Longest one diagnostic capture may run. A capture started before the job's
# deadline still runs on past it, so the cap, not the deadline, bounds how much
# of TEARDOWN_RESERVE_S a diagnostic job can spend. The first version gave each
# capture 120 s: three of them, after a 30 s stop grace and a 15 s log join,
# could outlast the reserve and cost the whole job's result (the platform kills
# the job and returns nothing). None of the three commands should take more
# than a few seconds; a 30 s cap says "hung" and records the timeout.
DIAGNOSTIC_CAPTURE_TIMEOUT_S = 30.0
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
    """The endpoint's fixed flags, then the job's, refusing a job flag that clashes.

    A flag is compared with `_` read as `-`, because vLLM's argument parser
    treats `--max_model_len` and `--max-model-len` as the same flag: a check on
    the dashed spelling alone let the underscore one through, and the engine
    then ran with a per-job value the endpoint is meant to own.
    """
    owned = {flag for _, flag in _FIXED_SERVE_ENV}
    clash = [a for a in payload_args if a.split("=", 1)[0].replace("_", "-") in owned]
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


def _drain_state(server) -> dict:
    """Whether the engine log is whole, as the log reader reports it.

    `drain_completed` False means `log_lines` may be missing its tail (the
    reader failed, or `stop()` gave up waiting for it), which a reader of the
    stored log cannot tell from a log that simply ends. `drain_error` is the
    exception's `repr`, a string, so the output stays JSON.
    """
    error = server.drain_error
    return {
        "drain_completed": bool(server.drain_completed),
        "drain_error": None if error is None else repr(error),
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


def collect_diagnostics(
    run_command: Callable,
    log_lines,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """In-container checks the first paid run needs, asked for per job.

    Each answers an item this repository could not verify without the image:
    whether the tool accepts every flag `harness.bench` passes (its help
    text), whether `pandas` -- which the custom dataset needs -- is installed,
    what nvidia-smi prints for the sampler's query, whether the engine
    logged artifact 1's prompt text (vLLM 0.27.1 logs prompt text only at
    DEBUG, so False is the expected answer and `input_lens` is the evidence),
    and whether another process on this machine reads
    the same monotonic clock (`clocks`: the GPU-utilisation window compares
    the sampler's `time.monotonic` with the bench tool's `time.perf_counter`
    request times; on Linux both are CLOCK_MONOTONIC, which is not checked
    until a diagnostic job runs on the image). Never part of an ordinary job:
    the help text alone is tens of kilobytes.

    The bench help is `--help=all`: in vLLM 0.27.1 a plain `--help` prints the
    usage line and a summary of the option groups, not the flags
    (`FlexibleArgumentParser.format_help`, vllm/utils/argparse_utils.py), so
    "the flag is missing from the help" would be true of every flag.

    These run after the engine is stopped, inside the seconds the job keeps
    back for teardown and the upload. Each capture is capped at
    DIAGNOSTIC_CAPTURE_TIMEOUT_S, and once `clock()` reaches `deadline` (the
    job's own, `TEARDOWN_RESERVE_S` before its end) the remaining captures are
    not run and say so under `skipped`. Running them anyway was rejected: a
    job the platform kills returns nothing, and that loses the measurement
    along with the checks. `deadline=None` never skips.
    """

    def capture(cmd):
        if deadline is not None and clock() >= deadline:
            return {
                "cmd": cmd,
                "skipped": "the job deadline had passed before this check could start; "
                "running it would have risked the job's result",
            }
        try:
            proc = run_command(
                cmd, capture_output=True, text=True, check=False,
                timeout=DIAGNOSTIC_CAPTURE_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001 -- a diagnostic never fails the job
            return {"cmd": cmd, "error": repr(e)}
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-_HELP_CHARS:],
            "stderr": (proc.stderr or "")[-2000:],
        }

    # A child process stamps its own perf_counter between two reads of this
    # process's monotonic: if the child's value lies between them, the two
    # processes (and the two clocks) share an epoch. The run's own check still
    # applies per run; this says why it would fail.
    child_cmd = [sys.executable, "-c", "import time; print(time.perf_counter())"]
    before = time.monotonic()
    child = capture(child_cmd)
    after = time.monotonic()
    try:
        child_value = float(child.get("stdout", "").strip())
    except ValueError:
        child_value = None
    clocks = {
        "monotonic": vars(time.get_clock_info("monotonic")),
        "perf_counter": vars(time.get_clock_info("perf_counter")),
        "child_cmd": child_cmd,
        "monotonic_before_child": before,
        "child_perf_counter": child_value,
        "monotonic_after_child": after,
        "child_perf_counter_between": (
            None if child_value is None else before <= child_value <= after
        ),
    }
    if "skipped" in child:
        clocks["skipped"] = child["skipped"]
    return {
        "clocks": clocks,
        "bench_help": capture(["vllm", "bench", "serve", "--help=all"]),
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
            # `served` stopped this engine before yielding it, so `startup_s`
            # here is the health wait PLUS that stop (harness/serve.py); the
            # second `stop()` returns the first one's seconds and signals nothing,
            # so `startup_s - teardown_s` is the wait alone.
            teardown_s = server.stop()
            lines = list(server.log_lines)
            out = {
                "healthy": False,
                # The facts a diagnosis needs (vllm_version, max_num_seqs, ...) are
                # exactly what a run that never became healthy would otherwise lose,
                # read from the whole log before the cap.
                "engine": _engine_facts(lines),
                **capped_log(lines),
                "served_cmd": list(server.cmd),
                "startup_s": startup_s,
                "teardown_s": teardown_s,
                **_drain_state(server),
                **common,
            }
            if want_diagnostics:
                out["diagnostics"] = collect_diagnostics(
                    d.run_command, lines, deadline=deadline, clock=d.clock
                )
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
                deadline=deadline,
                clock=d.clock,
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
        **_drain_state(server),
        **common,
    }
    if want_diagnostics:
        out["diagnostics"] = collect_diagnostics(
            d.run_command, lines, deadline=deadline, clock=d.clock
        )
    return out


def main():
    # Imported here so tests can import the handler without the runpod SDK,
    # and so importing it never starts a server.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
