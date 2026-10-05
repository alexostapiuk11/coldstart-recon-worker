"""The only module that calls the shared harness tooling (amendment §2).

`harness.serve.served` starts and stops a `vllm serve` process and
`harness.bench.run_bench` runs `vllm bench serve` against it. Both come from
the standalone harness tooling plan that artifact 4 owns, with the interface
agreed on 2026-09-26. Everything artifact 5 adds on top -- which flags a sweep
point needs, and how a bench result becomes a stored phase -- lives here, so a
change on the harness side touches this one file.

Both harness callables are injectable, so tests run without an engine.
"""

import os

# Written inside the container at job start; never on the network volume.
ADAPTER_ROOT = "/tmp/a5-adapters"
# The CLI spelling of LoRAConfig.specialize_active_lora. Checked against the
# pinned engine's own help text by tests/test_multilora_engine_flags.py, which
# plan 2 adds once reconnaissance has captured that text.
SPECIALIZE_FLAG = "--specialize-active-lora"
ENGINE_FLAGS = (
    "--enable-lora",
    "--max-loras",
    "--max-cpu-loras",
    "--max-lora-rank",
    "--lora-modules",
    "--no-enable-prefix-caching",
    "--disable-log-stats",
    SPECIALIZE_FLAG,
)
BENCH_FLAGS = (
    "--dataset-name",
    "--random-input-len",
    "--random-output-len",
    "--lora-modules",
    "--lora-assignment",
    "--max-concurrency",
    "--ignore-eos",
    "--save-detailed",
    "--num-warmups",
    "--ready-check-timeout-sec",
)


def serve_args(
    *,
    revision: str,
    max_model_len: int,
    n_slots: int,
    rank: int,
    lora_modules: dict[str, str],
    specialize_active_lora: bool,
    disable_log_stats: bool,
) -> list[str]:
    """`vllm serve` flags for one instance (amendment §3a, §3g, §4).

    `max_loras = max_cpu_loras = n_slots`, so every registered adapter is
    resident and the resident-versus-swapped path never runs. Prefix caching is
    off so a phase cannot inherit another phase's cached prefixes."""
    if len(lora_modules) != n_slots:
        raise ValueError(f"{len(lora_modules)} adapters registered for {n_slots} slots")
    args = [
        "--revision", revision,
        "--max-model-len", str(max_model_len),
        "--enable-lora",
        "--max-loras", str(n_slots),
        "--max-cpu-loras", str(n_slots),
        "--max-lora-rank", str(rank),
        "--no-enable-prefix-caching",
        "--lora-modules", *[f"{name}={path}" for name, path in lora_modules.items()],
    ]
    if specialize_active_lora:
        args.append(SPECIALIZE_FLAG)
    if disable_log_stats:
        args.append("--disable-log-stats")
    return args


def adapter_path(name: str) -> str:
    return os.path.join(ADAPTER_ROOT, name)


def _harness_served():
    from harness.serve import served

    return served


def _harness_run_bench():
    from harness.bench import run_bench

    return run_bench


def serve(model: str, args: list[str], env: dict, served=None):
    """A context manager yielding `.base_url`, `.log_lines` and `.healthy`."""
    return (served or _harness_served())(model, args=args, env=env)


def run_phase(
    base_url: str,
    *,
    model: str,
    adapters,
    concurrency: int,
    num_requests: int,
    dataset_args,
    seed: int,
    result_dir,
    run_bench=None,
) -> dict:
    """One phase: round-robin over `adapters` at fixed concurrency, EOS ignored.
    Returns the phase fields `multilora.records` documents, with the tool's
    per-request arrays unaltered."""
    raw = (run_bench or _harness_run_bench())(
        base_url,
        model=model,
        lora_modules=list(adapters),
        lora_assignment="round-robin",
        max_concurrency=concurrency,
        num_prompts=num_requests,
        dataset_args=list(dataset_args),
        ignore_eos=True,
        seed=seed,
        result_dir=result_dir,
    )
    return {
        "concurrency": concurrency,
        "num_requests": num_requests,
        "duration_s": raw["duration"],
        "completed": raw["completed"],
        "failed": raw["failed"],
        "ttfts": raw["ttfts"],
        "output_lens": raw["output_lens"],
        "errors": raw["errors"],
    }
