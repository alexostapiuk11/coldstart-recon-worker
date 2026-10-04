"""Run `vllm bench serve` against a running engine; return its saved JSON unaltered.

Why the engine's own benchmark client rather than a load generator written
here: it is what the field quotes, it ships in the pinned image, and it
already handles streaming, concurrency limits, LoRA assignment and
per-request timing. A home-grown client would be one more thing to validate
before any number it produced could be trusted.

Why unaltered: consumers apply their own rules to the raw per-request arrays.
Artifact 5 applies amendment §3f's failure rule; the service sweep applies the
same rule. A wrapper that filtered or summarised would make every consumer
inherit its choices without seeing them. The tool's own summary fields are
passed through untouched; whether to use any of them is the caller's call.

Pinned on every run, whatever the caller asks (amendment §3f):

- `--num-warmups 0` and `--ready-check-timeout-sec 0`. The tool's warm-up and
  ready-check requests target the base model, not the adapters, and the
  caller has already waited on `/health` through `harness.serve`. Both
  default to 0 in vLLM 0.27.1; pinning them keeps a version bump from
  silently adding unmeasured requests.
- `--save-result` and `--save-detailed`. Without the first nothing is written;
  without the second the tool deletes `input_lens`, `output_lens`, `ttfts`,
  `itls`, `start_times`, `generated_texts` and `errors` before saving.
- `--result-filename bench.json`, so the file read back is the file this call
  wrote, and `--disable-tqdm`, so the captured stderr holds errors rather than
  progress bars.
- `--backend openai --endpoint /v1/completions`. Both are the tool's defaults
  in 0.27.1 (`add_cli_args`); they are pinned because the sweep rebuilds each
  request's end-to-end latency as `ttft + sum(itls)`, which equals the tool's
  own latency only for the completions request function
  (`async_request_openai_completions`). The chat function stamps its last
  timestamp differently, and a flag slipped in through `extra_args` would
  change what every latency means without any error.

Verified against vLLM v0.27.1's source on 2026-10-04:
https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/serve.py
(`add_cli_args`, `benchmark`, `main_async`) and
https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/datasets/datasets.py
(`add_dataset_parser`).
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

RESULT_FILENAME = "bench.json"
_PINNED = (
    "--num-warmups", "0",
    "--ready-check-timeout-sec", "0",
    "--save-result",
    "--save-detailed",
    "--disable-tqdm",
    "--backend", "openai",
    "--endpoint", "/v1/completions",
)
# Flags this module sets from its own arguments or pins. A caller passing one
# of them through dataset_args or extra_args would produce a command with two
# values for one flag, and argparse silently keeps the last.
_MANAGED = frozenset({
    "--append-result",
    "--backend",
    "--base-url",
    "--disable-tqdm",
    "--endpoint",
    "--ignore-eos",
    "--lora-assignment",
    "--lora-modules",
    "--max-concurrency",
    "--model",
    "--num-prompts",
    "--num-warmups",
    "--ready-check-timeout-sec",
    "--result-dir",
    "--result-filename",
    "--save-detailed",
    "--save-result",
    "--seed",
})
_TAIL_LINES = 40
# A tail is capped in characters as well as lines: one progress line without a
# newline, or a traceback with a very long message, is a single "line" of any
# size, and the whole message rides back in a job result of unverified size.
_TAIL_CHARS = 3000


class BenchError(RuntimeError):
    """`vllm bench serve` produced no result for this run."""


def _refuse_managed(args: Sequence[str], where: str) -> None:
    """Refuse any argument the tool would read as a flag run_bench owns.

    Checked the way the tool parses, not the way the flag is spelled here:
    vLLM's `FlexibleArgumentParser` rewrites `_` to `-` before argparse runs,
    and argparse accepts any unambiguous prefix of a long option, so
    `--max_concurrency 8` and `--max-conc 8` both set `--max-concurrency`. An
    exact-name check would let either through, and the run would then not be
    the one its arguments describe. A prefix is refused whether or not it is
    unambiguous in the real parser: this module cannot see the parser, and no
    flag a sweep needs is spelled as a prefix of one it owns.
    """
    for arg in args:
        if not arg.startswith("--"):
            continue
        flag = arg.split("=", 1)[0].replace("_", "-")
        if flag in _MANAGED or (len(flag) > 2 and any(m.startswith(flag) for m in _MANAGED)):
            raise ValueError(
                f"{where} contains {arg!r}, which run_bench sets itself; argparse "
                "keeps the last of two values silently, so the run would not be "
                "the one its arguments describe"
            )


def bench_command(
    base_url: str,
    *,
    model: str,
    lora_modules: Sequence[str],
    lora_assignment: str | None,
    max_concurrency: int,
    num_prompts: int,
    dataset_args: Sequence[str],
    ignore_eos: bool,
    seed: int,
    result_dir,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """The exact argument list `run_bench` executes. Public so a GPU-free test
    can pin it and an operator can print it."""
    if max_concurrency < 1 or num_prompts < 1:
        raise ValueError(
            f"max_concurrency={max_concurrency!r} and num_prompts={num_prompts!r} must "
            "both be at least 1; the tool reads 0 concurrency as unlimited, which "
            "would measure a different load than the one recorded"
        )
    if lora_assignment is not None and not lora_modules:
        raise ValueError(
            f"lora_assignment={lora_assignment!r} with no lora_modules; the tool "
            "would ignore the assignment and send every request to the base model"
        )
    _refuse_managed(dataset_args, "dataset_args")
    _refuse_managed(extra_args, "extra_args")
    cmd = [
        "vllm", "bench", "serve",
        "--base-url", base_url,
        "--model", model,
        "--max-concurrency", str(max_concurrency),
        "--num-prompts", str(num_prompts),
        "--seed", str(seed),
        *dataset_args,
    ]
    if lora_modules:
        cmd += ["--lora-modules", *lora_modules]
    if lora_assignment is not None:
        cmd += ["--lora-assignment", lora_assignment]
    if ignore_eos:
        cmd.append("--ignore-eos")
    cmd += [*_PINNED, "--result-dir", str(result_dir), "--result-filename", RESULT_FILENAME]
    cmd += list(extra_args)
    return cmd


def _text(data: str | bytes | None) -> str:
    """`TimeoutExpired.stdout`/`.stderr` are bytes even with `text=True`, and
    None when nothing was read; decoding with `replace` so a half-written
    multi-byte character at the kill cannot hide the rest."""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _tail(data: str | bytes | None) -> str:
    text = "\n".join(_text(data).splitlines()[-_TAIL_LINES:])
    return text[-_TAIL_CHARS:]


def _output(stdout, stderr) -> str:
    """The tails of both streams, stderr first: the tool reports errors there,
    and stdout alone (which is what a timeout used to be reduced to) can be
    only the progress it printed before the failure."""
    return f"stderr:\n{_tail(stderr)}\nstdout:\n{_tail(stdout)}"


def _result_note(result_path: Path) -> str:
    """Said whenever a failed call left a result file behind: the file is not
    returned (this call did not finish), but a retry into the same directory
    would be refused as stale, and without this the reader cannot tell why."""
    if not result_path.exists():
        return ""
    return (
        f" A result file exists at {result_path} (written before the failure; it is not "
        "returned, and a retry needs a fresh result_dir or the file removed)."
    )


def run_bench(
    base_url: str,
    *,
    model: str,
    lora_modules: Sequence[str] = (),
    lora_assignment: str | None = None,
    max_concurrency: int,
    num_prompts: int,
    dataset_args: Sequence[str],
    ignore_eos: bool,
    seed: int,
    result_dir,
    extra_args: Sequence[str] = (),
    timeout: float | None = None,
    run: Callable = subprocess.run,
) -> dict:
    """Run one benchmark and return the JSON the tool saved, unaltered.

    `lora_modules` and `lora_assignment` default to "no LoRA", so a
    single-model sweep passes neither; with them omitted the command carries
    no LoRA flags at all. `extra_args` carries tool flags that are not dataset
    flags (the sweep asks for `--percentile-metrics`), kept apart from
    `dataset_args` so neither name lies about what it holds.

    `result_dir` is created if missing, and must not already hold a
    `bench.json`: a stale file would be read back as this run's result if the
    tool exited 0 without writing. Raises `BenchError` when the tool exits
    non-zero, times out, or writes nothing, with the tail of its output --
    there is no result to return, and returning an empty dict would let a
    caller compute statistics from nothing.

    `timeout` bounds the tool's wall time; `run` exists for tests.
    """
    out_dir = Path(result_dir)
    result_path = out_dir / RESULT_FILENAME
    cmd = bench_command(
        base_url,
        model=model,
        lora_modules=lora_modules,
        lora_assignment=lora_assignment,
        max_concurrency=max_concurrency,
        num_prompts=num_prompts,
        dataset_args=dataset_args,
        ignore_eos=ignore_eos,
        seed=seed,
        result_dir=out_dir,
        extra_args=extra_args,
    )
    if result_path.exists():
        raise ValueError(
            f"{result_path} already exists; if the tool then exited 0 without "
            "writing, that stale file would be returned as this run's result"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise BenchError(
            f"vllm bench serve did not finish within {timeout} s and was killed; "
            f"this run has no result.{_result_note(result_path)} "
            f"Last output:\n{_output(e.stdout, e.stderr)}"
        ) from e
    if proc.returncode != 0:
        raise BenchError(
            f"vllm bench serve exited {proc.returncode}; this run has no result."
            f"{_result_note(result_path)} Last output:\n{_output(proc.stdout, proc.stderr)}"
        )
    if not result_path.exists():
        raise BenchError(
            f"vllm bench serve exited 0 but wrote no {result_path}; without the saved "
            f"JSON this run has no result. Last output:\n{_output(proc.stdout, proc.stderr)}"
        )
    try:
        with result_path.open() as f:
            saved = json.load(f)
    except ValueError as e:
        saved = e
    if not isinstance(saved, dict):
        raise BenchError(
            f"{result_path} is not a complete JSON object ({saved!r:.200}); the tool may "
            "have been killed while writing it, and a half-read result would reach the "
            f"caller as if it were a measurement. Last output:\n{_output(proc.stdout, proc.stderr)}"
        )
    return saved
