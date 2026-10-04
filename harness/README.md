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
| `submit.py` | The submitter interface (`SubmitOutcome`) and an in-process stub for the GPU-free loop. |
| `runpod/` | Endpoint preflight, job lifecycle extraction, and a retrying HTTP client. |

## What is deliberately NOT here

Cold-start stage taxonomy, `RunRecord`, the clock-A/clock-B residual, the
`REQUIRED_FOR_*` presets, artifact 1's economics, and its four figures. Those are
in `coldstart/`. See
`docs/superpowers/plans/2026-09-03-harness-extraction-inventory.md` for the full
decision log.

## Not yet here

No concurrent load generator, no `vllm serve` lifecycle module and no
service-curve sweep exist yet; `worker/probe.py` issues sequential requests
only. Artifacts 2, 4 and 5 all need them. The planned shape is a `serve.py`
(start `vllm serve` on a port, wait for health, tear down on request) and a
`bench.py` (run `vllm bench serve` and return its JSON unaltered), described in
`docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md` §1d.
The campaign loop (`run_campaign`) also still lives in `coldstart/driver.py`,
bound to `RunRecord`. The discrete-event simulators live with their artifacts:
`autoscale/` for artifact 2, and artifact 4's own package for its placement
simulator.
