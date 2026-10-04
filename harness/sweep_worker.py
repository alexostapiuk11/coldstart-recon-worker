"""One run of the service-curve sweep, inside the worker.

Everything between "the engine is healthy" and "here is the run's summary":
decide how artifact 1's prompt reaches the engine, warm the engine for one
wave, run one measured `vllm bench serve` at the level's concurrency with the
GPU sampler running, and reduce the tool's saved JSON to a compact summary.
The engine lifecycle (`harness.serve`) and the job plumbing
(`worker/sweep_handler.py`) are not here, so this file can be tested with a
fake bench and a fake sampler and nothing else.

Split from `harness/service_sweep.py`, which holds the local side (schedule,
payload, record, reduction), because the two halves run on different
machines and change for different reasons.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.bench import BenchError
from harness.stats import median

PROMPT_EXACT = "exact"
PROMPT_RANDOM_FALLBACK = "random-fallback"
DATASET_FILENAME = "prompt.jsonl"
# Asks the tool to also report its own end-to-end latency percentiles. Not
# used for the curve -- see run_summary -- only recorded beside it, so the
# first paid run can confirm the reconstruction agrees with the tool.
E2EL_PERCENTILES = ("--percentile-metrics", "ttft,tpot,itl,e2el")
# Warm-up requests draw from a different seed than the measured run, so a
# random-fallback warm-up cannot leave the measured prompts in the prefix cache.
WARMUP_SEED_OFFSET = 500_000
_ERROR_SAMPLES = 3
_ERROR_CHARS = 300
_PER_REQUEST = ("ttfts", "itls", "output_lens", "errors")


def write_exact_prompt_dataset(prompt: str, directory) -> Path:
    """One JSONL line holding the prompt, in the custom dataset's format.

    One line rather than `num_prompts` copies: vLLM 0.27.1's custom dataset
    oversamples a short file up to `--num-prompts` with fresh request ids
    (`BenchmarkDataset.maybe_oversample_requests`), so every request carries
    the same text either way, and the file stays the same for every level.
    """
    path = Path(directory) / DATASET_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prompt": prompt}) + "\n")
    return path


def exact_dataset_args(dataset_path, *, output_len: int) -> list[str]:
    """Bench flags that send the dataset file's prompt verbatim.

    `--skip-chat-template` because artifact 1's probe posts the raw prompt to
    `/v1/completions`; the custom dataset would otherwise wrap it in the
    model's chat template and send a different, longer prompt.
    """
    return [
        "--dataset-name", "custom",
        "--dataset-path", str(dataset_path),
        "--custom-output-len", str(output_len),
        "--skip-chat-template",
    ]


def random_dataset_args(*, input_len: int, output_len: int) -> list[str]:
    """Random prompts of exactly `input_len` tokens: range ratio 0, no prefix."""
    return [
        "--dataset-name", "random",
        "--random-input-len", str(input_len),
        "--random-output-len", str(output_len),
        "--random-range-ratio", "0",
        "--random-prefix-len", "0",
    ]


@dataclass(frozen=True)
class PromptPlan:
    """How this run's requests are built, and why.

    `path` is PROMPT_EXACT or PROMPT_RANDOM_FALLBACK and is stored with every
    run (owner decision 4): a curve measured on random prompts of the right
    length is a different measurement from one on the exact prompt, and a
    reader has to be able to tell which one they are looking at.
    """

    path: str
    dataset_args: tuple[str, ...]
    prompt_tokens: int
    probe_error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dataset_args"] = list(self.dataset_args)
        return d


def choose_prompt_path(
    base_url: str,
    *,
    model: str,
    prompt: str,
    output_len: int,
    workdir,
    run_bench: Callable,
    count_tokens: Callable[[str], int],
) -> PromptPlan:
    """Try the exact prompt once; fall back to random prompts of its length.

    The probe is one request at concurrency 1. It passes only if the tool
    completed it AND the engine's own prompt-token count for it (the tool
    copies `usage.prompt_tokens` into `input_lens`) equals the server's
    `/tokenize` count of the prompt -- so "exact" means the engine received a
    prompt of exactly that length, not merely that the tool ran. Anything else
    -- the tool failing (a missing `pandas`, which the custom dataset needs, is
    the expected cause), or a length mismatch -- falls back to the random
    dataset at the `/tokenize` length, with the reason kept.

    Decided per job, because each job is a fresh engine and nothing carries
    between jobs. Deciding once on the local machine was rejected: it cannot
    run the pinned image's tool. `service_sweep.reduce_curve` refuses a store
    whose runs took different paths, so a campaign cannot mix them silently.
    """
    workdir = Path(workdir)
    tokens = count_tokens(prompt)
    exact_args = exact_dataset_args(
        write_exact_prompt_dataset(prompt, workdir), output_len=output_len
    )
    try:
        raw = run_bench(
            base_url,
            model=model,
            max_concurrency=1,
            num_prompts=1,
            dataset_args=exact_args,
            ignore_eos=True,
            seed=0,
            result_dir=workdir / "prompt-probe",
        )
    except BenchError as e:
        error = str(e)[-2000:]
    else:
        lens = raw.get("input_lens")
        if raw.get("completed") == 1 and lens == [tokens]:
            return PromptPlan(PROMPT_EXACT, tuple(exact_args), tokens)
        error = (
            f"probe completed={raw.get('completed')!r} with input_lens={lens!r}; "
            f"expected 1 completed request of {tokens} prompt tokens"
        )
    return PromptPlan(
        PROMPT_RANDOM_FALLBACK,
        tuple(random_dataset_args(input_len=tokens, output_len=output_len)),
        tokens,
        error,
    )


def successful_requests(raw: dict) -> dict:
    """Apply amendment §3f's failure rule to the tool's per-request arrays.

    A request failed if its `errors` entry is non-empty, OR its TTFT is 0.0,
    OR its output length is 0: in vLLM 0.27.1 some failure paths leave the
    error string empty and no success flag is saved. The result is then
    cross-checked against the tool's own `completed` and `failed` counts.

    End-to-end latency per request is reconstructed as `ttft + sum(itls)`.
    `--save-detailed` saves no per-request end-to-end latency, and for the
    completions endpoint the tool's own `latency` is the last chunk's time
    minus the start time, which is exactly the first chunk's time plus every
    gap after it (`async_request_openai_completions` in
    vllm/benchmarks/lib/endpoint_request_func.py, v0.27.1).
    """
    missing = [k for k in ("duration", "completed", "failed", *_PER_REQUEST) if k not in raw]
    if missing:
        raise ValueError(
            f"bench result lacks {missing}; without --save-detailed's per-request "
            "arrays no latency can be computed, and the run would be stored with none"
        )
    lengths = {k: len(raw[k]) for k in _PER_REQUEST}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            f"per-request arrays differ in length {lengths}; pairing them by index "
            "would attribute one request's timing to another"
        )
    e2e, ttft, out = [], [], []
    failed = 0
    for err, t, itl, n in zip(
        raw["errors"], raw["ttfts"], raw["itls"], raw["output_lens"], strict=True
    ):
        if err or t == 0.0 or n == 0:
            failed += 1
            continue
        e2e.append(t + sum(itl))
        ttft.append(t)
        out.append(n)
    if len(e2e) != raw["completed"] or failed != raw["failed"]:
        raise ValueError(
            f"the failure rule finds {len(e2e)} successful and {failed} failed requests, "
            f"but the tool counted completed={raw['completed']} failed={raw['failed']}; "
            "one of them is miscounting, and a latency from the wrong population "
            "would be stored as this level's"
        )
    return {"e2e_s": e2e, "ttft_s": ttft, "output_lens": out, "n_failed": failed}


def run_summary(raw: dict, *, gpu: dict, plan: PromptPlan, warmup: dict | None) -> dict:
    """The compact per-run summary the worker returns: no per-request arrays.

    `latency_s` is the median end-to-end latency of the successful requests,
    reconstructed per request (see `successful_requests`). The tool's own
    `median_e2el_ms` is recorded as `bench_median_e2el_s` and not used:
    artifact 5's rule is to compute statistics from the raw arrays under one
    failure rule, and the sweep keeps the same rule so the two artifacts'
    latencies mean the same thing.

    `throughput_tps` is output tokens per second: successful output lengths
    summed over the tool's measured duration.
    """
    ok = successful_requests(raw)
    if not ok["e2e_s"]:
        raise ValueError(
            f"no request succeeded ({raw['failed']} failed); this run has no latency, "
            "and storing it as ok would put a point on the curve that was never measured"
        )
    if not raw["duration"] > 0:
        raise ValueError(
            f"bench duration is {raw['duration']!r}; throughput would divide by it"
        )
    bench_e2el = raw.get("median_e2el_ms")
    errors = [e for e in raw["errors"] if e]
    return {
        "latency_s": median(ok["e2e_s"]),
        "ttft_median_s": median(ok["ttft_s"]),
        "throughput_tps": sum(ok["output_lens"]) / raw["duration"],
        "gpu_util": gpu["gpu_util"],
        "prompt_path": plan.path,
        "bench_median_e2el_s": None if bench_e2el is None else bench_e2el / 1000.0,
        "completed": raw["completed"],
        "failed": raw["failed"],
        "duration_s": raw["duration"],
        "input_lens_unique": sorted(set(raw.get("input_lens") or [])),
        "error_samples": list(dict.fromkeys(e[:_ERROR_CHARS] for e in errors))[:_ERROR_SAMPLES],
        "bench_scalars": {k: v for k, v in raw.items() if not isinstance(v, (list, dict))},
        "gpu": gpu,
        "prompt": plan.to_dict(),
        "warmup": warmup,
    }


def _remaining(deadline: float | None, clock: Callable[[], float]) -> float | None:
    if deadline is None:
        return None
    left = deadline - clock()
    if left <= 0:
        raise BenchError(
            "the job's time budget is spent; another bench run would be killed by "
            "the platform's execution timeout, and the job would return nothing"
        )
    return left


def run_one(
    base_url: str,
    *,
    model: str,
    level: int,
    num_prompts: int,
    warmup_prompts: int,
    plan: PromptPlan,
    seed: int,
    workdir,
    run_bench: Callable,
    sampler_factory: Callable,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    keep_raw: bool = False,
) -> dict:
    """Warm up, then one measured run at concurrency `level`.

    The warm-up is `warmup_prompts` requests at the same concurrency, results
    discarded but their counts kept. vLLM captures CUDA graphs at startup, so
    the first wave's extra cost is small, but it is not zero, and a sweep
    point's median should not carry it. The GPU sampler runs around the
    measured run only, so the warm-up never reaches the utilisation median.

    `keep_raw` adds the tool's saved JSON, unaltered, as `raw_bench`. Only the
    first paid run's diagnostic jobs ask for it, to check the saved keys
    against what this module reads; every other job stays compact.
    """
    workdir = Path(workdir)
    common = {
        "model": model,
        "max_concurrency": level,
        "dataset_args": list(plan.dataset_args),
        "ignore_eos": True,
    }
    warmup = None
    if warmup_prompts:
        warm = run_bench(
            base_url,
            **common,
            num_prompts=warmup_prompts,
            seed=seed + WARMUP_SEED_OFFSET,
            result_dir=workdir / "warmup",
            timeout=_remaining(deadline, clock),
        )
        warmup = {
            "num_prompts": warmup_prompts,
            "completed": warm.get("completed"),
            "failed": warm.get("failed"),
        }
    with sampler_factory() as sampler:
        raw = run_bench(
            base_url,
            **common,
            num_prompts=num_prompts,
            seed=seed,
            result_dir=workdir / "measured",
            extra_args=list(E2EL_PERCENTILES),
            timeout=_remaining(deadline, clock),
        )
    summary = run_summary(raw, gpu=sampler.summary(), plan=plan, warmup=warmup)
    if keep_raw:
        summary["raw_bench"] = raw
    return summary


# vLLM logs its explicitly-set engine arguments at INFO ("non-default args:
# {...}", fixtures/vllm_logs/startup_0.log line 7) and the max_num_seqs it
# defaulted to only at DEBUG ("Defaulting max_num_seqs to %d for %s usage
# context.", vllm/engine/arg_utils.py, v0.27.1). docs/recon-a2.md records that
# the value is absent from the captured log; the sweep must record it.
_MAX_NUM_SEQS_SET = re.compile(r"non-default args: .*'max_num_seqs': (?P<n>\d+)")
_MAX_NUM_SEQS_DEFAULTED = re.compile(r"Defaulting max_num_seqs to (?P<n>\d+)")


def max_num_seqs_from_log(lines: Sequence[str]) -> tuple[int | None, str | None]:
    """The engine's max_num_seqs and where it was read, or (None, None).

    An explicitly passed value wins over a logged default. Absence is
    returned as None, never as vLLM's documented default: the default depends
    on the GPU's memory and the usage context, and reporting a value the log
    did not show is the assumption recon-a2 says the sweep must not inherit.
    """
    for pattern, source in (
        (_MAX_NUM_SEQS_SET, "non-default-args"),
        (_MAX_NUM_SEQS_DEFAULTED, "debug-default"),
    ):
        for line in lines:
            m = pattern.search(line)
            if m:
                return int(m.group("n")), source
    return None, None
