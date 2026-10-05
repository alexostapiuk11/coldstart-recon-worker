"""Reconnaissance: capture what the pinned engine actually does (amendment §6).

Measures nothing that is published. Two probe kinds run in the worker:

- `help`: the engine's and the benchmark client's own help text, which settles
  whether the flags `multilora.serving` uses exist (R4, R9).
- `lora`: one instance through `multilora.instance.run_instance`, with one
  spread phase over every adapter, plus a single completion per adapter and one
  idle scrape of `/metrics` (R2, R3, R5-R8).

`recon_payloads` is the fixed probe list the capture script submits. Its first
three sweep points run twice, so the first compiles and the second shows what a
warm restart costs.
"""

import subprocess

# Artifact 1's request, the inherited shape (August §3): this prompt, 16 output
# tokens. The lora probe asks the engine's own tokenizer how many tokens the
# prompt is, which fixes `--random-input-len` in the pre-registration.
A1_PROMPT = "Explain what a key-value cache does, in two sentences."
A1_OUTPUT_TOKENS = 16

from multilora.conditions import SPREAD, gate_synthetic_name, real_name, synthetic_name
from multilora.instance import run_instance

RECON_POINTS = (1, 16, 64)


def _capture(cmd: list[str]) -> dict:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        return {"cmd": cmd, "returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}
    except Exception as e:  # noqa: BLE001 -- a missing subcommand is itself the answer
        return {"cmd": cmd, "returncode": None, "stdout": "", "stderr": str(e)}


def help_probe(run_cmd=_capture) -> dict:
    return {
        "healthy": True,
        "serve_help": run_cmd(["vllm", "serve", "--help=all"]),
        # `--help=all`, not `--help`: vLLM 0.27.1's `vllm bench serve --help`
        # prints no flags at all (shared tooling report, 2026-10-04), which
        # would read as every bench flag missing and stop reconnaissance.
        "bench_help": run_cmd(["vllm", "bench", "serve", "--help=all"]),
    }


def lora_probe(payload: dict, *, deps, post_status, post_json, **instance_kw) -> dict:
    def after_ready(server):
        statuses = {
            name: post_status(
                f"{server.base_url}/v1/completions",
                {"model": name, "prompt": "Hello", "max_tokens": 4},
            )
            for name in payload["registered"]
        }
        tokenized = post_json(
            f"{server.base_url}/tokenize", {"model": instance_kw["model"], "prompt": A1_PROMPT}
        )
        return {
            "completion_status": statuses,
            "metrics_idle": deps.http_get(f"{server.base_url}/metrics"),
            "a1_prompt_tokens": tokenized.get("count"),
        }

    return run_instance(payload, deps=deps, after_ready=after_ready, **instance_kw)


def run_probe(
    payload: dict, *, deps, post_status, post_json=None, run_cmd=_capture, **instance_kw
) -> dict:
    if payload["probe"] == "help":
        return help_probe(run_cmd)
    if payload["probe"] == "lora":
        return lora_probe(
            payload, deps=deps, post_status=post_status, post_json=post_json, **instance_kw
        )
    raise ValueError(f"unknown probe {payload['probe']!r}")


def _lora_payload(label, registered, *, concurrency, dataset_args, adapter_seed,
                  specialize=False, disable_log_stats=False, real_adapters=()) -> dict:
    return {
        "probe": "lora",
        "label": label,
        "run_index": 0,
        "condition": "recon",
        "n_slots": len(registered),
        "registered": list(registered),
        "specialize_active_lora": specialize,
        "disable_log_stats": disable_log_stats,
        "phases": [{"phase_index": 0, "regime": SPREAD, "adapters": list(registered)}],
        "concurrency": concurrency,
        "requests_per_phase": max(80, 10 * concurrency),
        "warmup_requests_per_adapter": 1,
        "scrape_interval_s": 1.0,
        "adapter_seed": adapter_seed,
        "dataset_args": list(dataset_args),
        "real_adapters": list(real_adapters),
    }


def recon_payloads(*, concurrency: int, dataset_args, adapter_seed: int, real_candidates=()) -> list[dict]:
    """The fixed probe list. `real_candidates` is [(repo, revision), ...] from
    scripts/a5_find_real_adapters.py; when given, one probe serves them beside
    as many synthetic adapters, which is the gate's configuration (R10)."""
    kw = {"concurrency": concurrency, "dataset_args": dataset_args, "adapter_seed": adapter_seed}
    out = [{"probe": "help", "label": "help"}]
    for n in RECON_POINTS:
        names = [synthetic_name(i) for i in range(n)]
        out.append(_lora_payload(f"lora-N{n}-first", names, **kw))
        out.append(_lora_payload(f"lora-N{n}-restart", names, **kw))
    top = [synthetic_name(i) for i in range(RECON_POINTS[-1])]
    out.append(_lora_payload("lora-N64-specialize", top, specialize=True, **kw))
    out.append(_lora_payload("lora-N64-no-stats", top, disable_log_stats=True, **kw))
    if real_candidates:
        g = len(real_candidates)
        real = [
            {"name": real_name(i), "repo": repo, "revision": rev}
            for i, (repo, rev) in enumerate(real_candidates)
        ]
        names = [r["name"] for r in real] + [gate_synthetic_name(i) for i in range(g)]
        out.append(_lora_payload("lora-gate-real", names, real_adapters=real, **kw))
    return out
