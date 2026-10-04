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
)
# Flags this module sets from its own arguments or pins. A caller passing one
# of them through dataset_args or extra_args would produce a command with two
# values for one flag, and argparse silently keeps the last.
_MANAGED = frozenset({
    "--append-result",
    "--base-url",
    "--disable-tqdm",
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


class BenchError(RuntimeError):
    """`vllm bench serve` produced no result for this run."""


def _refuse_managed(args: Sequence[str], where: str) -> None:
    for arg in args:
        flag = arg.split("=", 1)[0]
        if flag in _MANAGED:
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


def _tail(text: str | None) -> str:
    return "\n".join((text or "").splitlines()[-_TAIL_LINES:])


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
        partial = e.stdout if isinstance(e.stdout, str) else None
        raise BenchError(
            f"vllm bench serve did not finish within {timeout} s and was killed; "
            f"this run has no result. Last output:\n{_tail(partial)}"
        ) from e
    if proc.returncode != 0:
        raise BenchError(
            f"vllm bench serve exited {proc.returncode}; this run has no result. "
            f"Last output:\n{_tail(proc.stderr) or _tail(proc.stdout)}"
        )
    if not result_path.exists():
        raise BenchError(
            f"vllm bench serve exited 0 but wrote no {result_path}; without the saved "
            f"JSON this run has no result. Last output:\n{_tail(proc.stdout)}"
        )
    with result_path.open() as f:
        return json.load(f)
