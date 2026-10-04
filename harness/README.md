# harness

The artifact-agnostic half of the measurement stack. Artifact 1
(`coldstart/`) is its first consumer; artifacts 2–5 are the reason it exists.

## The one rule

**`harness/` never imports `coldstart/`.** `tests/test_harness_boundary.py`
enforces it. When a module here needs something artifact-specific — a record
type, a pin set, a grouping key, a publishability preset — it takes it as a
parameter. That is why `JsonlStore` takes a record class, `build_schedule`
speaks conditions and blocks, `failure_rate_by_group` requires a key, and
`assert_endpoint_matches` requires a pin set.

## What is here

| Module | What it gives an artifact |
|---|---|
| `stats.py` | Medians, percentiles, ECDF, bootstrap CIs, bootstrap on a difference of contrasts, paired within-host units. Every "intervals shown" constraint in the portfolio runs through this. |
| `publish.py` | `partition()` — the gate between stored rows and any figure or stats call — plus failure-rate and discard tables from disjoint row populations. |
| `figure_guards.py` | Empty-input refusal, missing-field errors that name the row, refusal to silently drop a series, and the phone-legibility floor every spec requires. |
| `store.py` | Append-only JSONL with a truncated-line diagnostic. Pass your own record type. |
| `scheduler.py` | Interleaved, randomized-within-block schedules, so a condition is never confounded with time-varying platform state. |
| `recorder.py` | Clock B: monotonic stage marks relative to `t0`, wall clock never used for arithmetic. |
| `failures.py` | Platform and engine failure strings → a closed `FailureClass` taxonomy. |
| `vllm_logs.py` | Engine log → startup sub-phases, KV blocks, engine info, and which phases the version merges. |
| `submit.py` | The submitter interface (`SubmitOutcome`), an in-process stub for artifact 1's `submit(arm, run_id)`, and `PayloadStubSubmitter` for workers that take a whole payload. |
| `runpod/` | Endpoint preflight, job lifecycle extraction, a retrying HTTP client, and `submit_payload` for any JSON job input. |
| `campaign.py` | The campaign loop (`run_campaign`): schedule → submit → record → store, never retried, with the resume drift guard. The artifact passes its own `submit` and `build_record`. Artifact 1's `coldstart/driver.py` still carries its own copy of the loop; it has not moved onto this one yet. |
| `serve.py` | `served(model, *, args, env, port=8000, health_timeout=900.0)`: `vllm serve` in its own process group, health-waited, yielded healthy or not, with an idempotent `stop() -> float`. |
| `bench.py` | `run_bench(...)`: one `vllm bench serve` run, warm-ups and ready check pinned off, its saved JSON returned unaltered. |
| `gpu_util.py` | `nvidia-smi` `utilization.gpu` sampled every 0.5 s on a thread while a run is in flight; median as a fraction, raw samples kept. |
| `service_sweep.py` | The single-engine service-curve sweep's local side: interleaved schedule, job payload, `SweepRun` record, and the reduction to plain `(concurrency, latency_s, throughput_tps, gpu_util)` tuples with min–max intervals. |
| `sweep_worker.py` | One sweep run inside the worker: exact-prompt probe with a recorded random fallback, one warm-up wave, the measured run, the compact summary. |

## What is deliberately NOT here

Cold-start stage taxonomy, `RunRecord`, the clock-A/clock-B residual, the
`REQUIRED_FOR_*` presets, artifact 1's economics, and its four figures. Those are
in `coldstart/`. See
`docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md` for the full
decision log.

## Where the shared tooling is used

`worker/sweep_handler.py` runs one sweep job inside the image, selected by the
template's `dockerStartCmd`; `scripts/run_service_sweep.py` drives a sweep
from a laptop and keeps its pin set (pins never live here); artifact 2 turns
the curve into its `ServiceCurve` in `scripts/a2_service_curve.py`.

## Still not here

Exact-timestamp trace replay through `vllm bench serve` is unverified and out
of scope. The discrete-event simulators live with their artifacts:
`autoscale/` for artifact 2, and artifact 4's own package for its placement
simulator. Nothing here imports `autoscale` either:
`tests/test_shared_tooling_boundary.py` checks it in a fresh interpreter.
