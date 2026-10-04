"""Print what a service-sweep pilot store says about the image's open questions.

    .venv/bin/python scripts/read_sweep_pilot.py build/sweep-pilot.jsonl

The paid-run checklist (docs/runbook-service-sweep.md, section F) runs a two-job
diagnostic pilot with `--diagnostics`, and the answers to its UNVERIFIED items
(docs/superpowers/plans/2026-10-04-shared-in-container-tooling.md) are spread
over a dozen fields of each stored run: whether `vllm bench serve --help=all` lists
every flag the harness passes, which prompt path ran, whether prefix caching
reached the engine, whether the GPU figure was windowed, how the tool's median
agrees with the reconstructed latency. This prints one block per run with each
answer on its own line, so the owner reads them in one place and compares them
with the checklist's table.

It only reports. A gate that exited non-zero on a mismatch was rejected: the
remedy differs per item (a flag fix, an image change, an owner's decision to
accept a fallback), and one pilot with two mismatches should show both, not
stop at the first. A failed run prints its failure detail and the engine facts
that survived, and no more: it has no summary to read.

The flag and key lists below are the ones `harness/bench.py` and
`harness/sweep_worker.py` rely on; when either changes, change them here, or the
check silently stops covering the new one.
"""

import argparse
import json
import sys
from pathlib import Path

# Every flag the harness passes to `vllm bench serve` (harness/bench.py,
# harness/sweep_worker.py), looked for in the image's own `--help`.
FLAGS = [
    "--base-url", "--model", "--max-concurrency", "--num-prompts", "--seed", "--dataset-name",
    "--dataset-path", "--custom-output-len", "--skip-chat-template", "--random-input-len",
    "--random-output-len", "--random-range-ratio", "--random-prefix-len", "--ignore-eos",
    "--num-warmups", "--ready-check-timeout-sec", "--save-result", "--save-detailed",
    "--disable-tqdm", "--backend", "--endpoint", "--result-dir", "--result-filename",
    "--percentile-metrics", "--lora-modules", "--lora-assignment",
]
# The keys of the tool's saved JSON that the summary and the GPU window read.
KEYS = [
    "duration", "completed", "failed", "ttfts", "itls", "output_lens", "errors",
    "input_lens", "start_times", "median_e2el_ms", "request_throughput",
    "output_throughput", "num_prompts", "max_concurrency",
]


def _seconds(value) -> str:
    return "absent" if value is None else f"{value:.1f} s"


def describe(row: dict) -> list[str]:
    """One run's answers, as printable lines."""
    r = row
    e = r["engine"]
    d = r.get("diagnostics") or {}
    out: list[str] = []
    say = out.append
    detail = (r["status"] or {}).get("failure_detail") or ""
    say(f"--- run {r['run_index']} c={r['level']} {r['outcome']} {detail}")
    help_text = (d.get("bench_help") or {}).get("stdout", "")
    say(f"  bench --help missing flags: {[f for f in FLAGS if f not in help_text]}")
    say(f"  pandas importable: {d.get('pandas_importable')} | prompt in log: "
        f"{d.get('prompt_in_log')}")
    say(f"  nvidia-smi raw: {(d.get('nvidia_smi') or {}).get('stdout', '')[:40]!r}")
    say("  clocks: child_perf_counter_between: "
        f"{(d.get('clocks') or {}).get('child_perf_counter_between')}")
    pins = {f: f in r["served_cmd"] for f in ("--max-num-seqs", "--no-enable-prefix-caching")}
    say(f"  serve cmd pins: {pins}")
    nda = next((x for x in e["log_lines"] if "non-default args" in x), None)
    caching_off = nda is not None and "'enable_prefix_caching': False" in nda
    say(f"  non-default args line has prefix caching off: {caching_off}")
    facts = {k: e.get(k) for k in
             ("max_num_seqs", "max_num_seqs_source", "kv_capacity_tokens", "vllm_version")}
    say(f"  engine: {facts}")
    say(f"  log: {e.get('log_lines_total')} lines, truncated: {e.get('log_truncated')}")
    # What the handler measured for this job. The cost estimate (runbook E) takes
    # its startup and teardown from here, not from artifact 1's figures.
    drained = r.get("drain_completed")
    drain_error = r.get("drain_error")
    say(f"  timing: startup {_seconds(r.get('startup_s'))} | teardown "
        f"{_seconds(r.get('teardown_s'))} | log drained: {drained}"
        + (f" ({drain_error})" if drain_error else ""))
    if r["outcome"] != "ok":
        return out
    s = r["summary"]
    # `raw_bench` is only kept for a `--diagnostics` job, and the tool's median is
    # absent when the saved JSON lacked it: either is reported, not a crash that
    # hides the rest of the block.
    median_s = s.get("bench_median_e2el_s")
    raw = s.get("raw_bench")
    say("  saved JSON missing keys: "
        + ("absent (this run had no raw saved JSON; it needs --diagnostics)" if raw is None
           else str([k for k in KEYS if k not in raw])))
    say(f"  prompt: {s['prompt_path']} tokens {s['prompt']['prompt_tokens']} "
        f"engine input_lens {s['input_lens_unique']} | probe_error: {s['prompt']['probe_error']}")
    say(f"  requests: completed {s['completed']} failed {s['failed']} | error samples: "
        f"{s['error_samples']}")
    if median_s is None:
        say(f"  latency {s['latency_s']:.4f} s vs tool median_e2el absent")
    else:
        gap_ms = (s["latency_s"] - median_s) * 1000
        say(f"  latency {s['latency_s']:.4f} s vs tool median_e2el {median_s:.4f} s "
            f"(gap {gap_ms:+.2f} ms)")
    say(f"  gpu: reported {s['gpu_util']} | whole-call {s['gpu_util_whole_call']} | "
        f"windowed: {s['gpu_util_windowed']}")
    if s["gpu_util_windowed"]:
        say(f"       samples in span {s['gpu_util_n_in_span']} outside "
            f"{s['gpu_util_n_outside_span']} | span {round(s['gpu_util_span_s'], 1)} s")
    else:
        say(f"       window note: {s['gpu_util_window_note']}")
    say(f"  gpu samples valid: {s['gpu']['n_valid']} of {s['gpu']['n_samples']}")
    # clock_A spans submit to result, queue delay included; the platform's own
    # delay and execution figures are in clock_C (absent on a failed run).
    submit_to_result = round(r["clock_A"]["t_result"] - r["clock_A"]["t_submit"], 1)
    say(f"  wall: clock_A submit-to-result {submit_to_result} s (includes queue); "
        f"clock_C {r['clock_C']}")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("store", nargs="?", default="build/sweep-pilot.jsonl",
                    help="the pilot's JSONL store (run_service_sweep.py --store)")
    args = ap.parse_args(argv)
    path = Path(args.store)
    if not path.exists():
        sys.exit(f"{path} does not exist; there is no pilot to read. Run the pilot first "
                 "(docs/runbook-service-sweep.md, section F)")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        sys.exit(f"{path} holds no runs; reading it would print nothing and look like a pass")
    for row in rows:
        print("\n".join(describe(row)))


if __name__ == "__main__":
    main()
