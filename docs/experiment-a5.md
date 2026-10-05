# Artifact 5 — Pre-registration

Committed before the first measured run. The git timestamp on this file and on
`multilora/prereg_values.py` is the evidence the values below were fixed in
advance. Design: docs/superpowers/specs/2026-09-26-multi-lora-serving-harness-amendment.md.

## Configuration held fixed

Image `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:39e967e984962d5c355616b6ce27fa309a0895df41c61652c857a9b43a001b7a`
(built from commit 096298c), vLLM `0.27.1` (the engine log banner, `version
0.27.1`, in every capture under `fixtures/a5/` that has a log), model
`Qwen/Qwen3-4B` at `1cfa9a7208912126459214e8b04321603b3df60c`, GPU `NVIDIA
GeForce RTX 4090` (24 GB), `max-model-len` 8192, `max_lora_rank` `16`, target
modules `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`, prefix
caching off, `VLLM_TUNED_CONFIG_FOLDER` unset, FlashBoot off, workersMin 0,
workersMax 1, network volume `9c7ut2slrd` (EU-RO-1). `gpu_memory_utilization`
is `0.80`, fixed in the endpoint environment as `A5_GPU_MEMORY_UTILIZATION`
and passed explicitly by the worker (commit 096298c): with LoRA on this card,
vLLM's default of 0.92 and then 0.85 both ran out of memory, 0.92 for the
plain N1 probes and 0.85 for the 64-slot `--specialize-active-lora` probe
(docs/recon-a5.md, "The memory budget"). The measurement template (plan 3) is
a copy of the reconnaissance template that changes only the start command, to
`python3 -u /opt/a5_handler.py`, so the image, the environment, the container
disk and the network volume are the same as reconnaissance's.
Reconnaissance record: docs/recon-a5.md.

Any change to a value above ends the experiment rather than continuing across
the boundary, as in artifact 1.

## Parameters

| parameter | value |
|---|---|
| `concurrency` | `64` |
| `rank` | `16` |
| `target_modules` | `('q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj')` |
| `gate_adapters` | `4` |
| `warmup_requests_per_adapter` | `2` |
| `scrape_interval_s` | `1.0` |
| `knee_threshold` | `0.1` |
| `request_tokens` | `29` |
| `context_length_tokens` | `8192` |
| `slo_ttft_p95_s` | `1.0` |
| `requests_per_tenant_month` | `100000.0` |
| `peak_to_average` | `3.0` |
| `gpu_hourly_rate` | `1.0` |
| `schedule_seed` | `20261001` |
| `include_diagnostic` | `False` |
| `include_control` | `True` |
| `bench_dataset_args` | `('--dataset-name', 'random', '--random-input-len', '13', '--random-output-len', '16')` |
| `real_adapters` | `(('AIsakawaii/task_b_method2_qwen4b', '8ba6625bbb5f5a8770109f003ae55fcaef4fb117'), ('davemaxuellkr/KIRD-project_QLoRa-Qwen3-4B_en-ko', 'f7eb9b54171b1212347ebb0e3bb26008d81e92db'), ('hanghang1024/Qwen3-4b-Qlora-Fin', '47d3fc76a0d748497e726134ee5092e68bb0cacf'), ('jacobcd52/qwen3_4b_hacker', '89cb5e72a31c2f2ce53e9c4f9aee9ee38b7c26e2'))` |
| `sweep` | `(1, 2, 4, 8, 16, 32, 64)` |
| `concentrated_k` | `1` |
| `instances_per_condition` | `24` |
| `phases_per_regime` | `2` |
| `diagnostic_points` | `(1, 16, 64)` |
| `control_point` | `64` |
| `equivalence_margin` (derived) | `0.05` |
| `requests_per_phase` (derived) | `640` |

## Conditions

Sweep points `(1, 2, 4, 8, 16, 32, 64)`, each at 24 instances. Diagnostic at
`(1, 16, 64)` with `specialize_active_lora` on: cut (`include_diagnostic`
`False`). `lora-N64-specialize` (64 slots, `--specialize-active-lora`) ran out
of memory during CUDA-graph capture at both budgets it was tried at, 0.85 and
0.80, while every plain 64-slot probe started healthy at both
(docs/recon-a5.md, "The diagnostic is cut"). Task 5's rule table did not cover
a flag that exists but whose instance cannot start; the owner decided on
2026-10-05 to cut the diagnostic rather than lower the memory budget for every
condition or give the diagnostic a budget of its own. H4 (slot overhead) is
withdrawn: its diagnostic arm was cut. Gauge control at 64 slots with stats
logging off: included (`include_control` `True`): R7 found the running-adapters
gauge exported, and the budget rule keeps it because the estimate is under the
cap (see "Rules fixed now"). The gate runs first, alone, 24 instances. It
registers the 4 real adapters below plus 4 synthetic ones (8 slots):

| Repo | Revision |
|---|---|
| `AIsakawaii/task_b_method2_qwen4b` | `8ba6625bbb5f5a8770109f003ae55fcaef4fb117` |
| `davemaxuellkr/KIRD-project_QLoRa-Qwen3-4B_en-ko` | `f7eb9b54171b1212347ebb0e3bb26008d81e92db` |
| `hanghang1024/Qwen3-4b-Qlora-Fin` | `47d3fc76a0d748497e726134ee5092e68bb0cacf` |
| `jacobcd52/qwen3_4b_hacker` | `89cb5e72a31c2f2ce53e9c4f9aee9ee38b7c26e2` |

Order within each block is drawn by `harness.scheduler` from `schedule_seed`
`20261001` (the gate's own schedule uses `schedule_seed + 1`,
`multilora/conditions.py`, so it never shares a stream with the campaign's).

## Hypotheses

**H1 (heterogeneity).** Spread minus concentrated throughput is negative at
every sweep point above 1 and grows in magnitude with slots.

**H2 (heterogeneity dominates).** At the top sweep point, the heterogeneity
cost in throughput exceeds the registered-slot cost.

**H3 (memory is capacity, not latency).** KV capacity falls with slots, and at
the inherited request shape the KV concurrency ceiling exceeds C at every
point, so memory does not bind (amendment §3c).

## Rules fixed now

- Failure: amendment §3f's three-way rule; a phase whose counts disagree with
  the tool's is not trusted.
- Exclusion: an instance whose compile cache read cold (S4b ≥ 1 s) is excluded.
- Gate: amendment §4; margin τ/2; inconclusive is not a pass. The campaign
  does not start unless the gate passes.
- Knee: amendment §4's point-estimate rule on spread throughput.
- Tenants per GPU: the smallest of the slot, throughput and memory bounds.
- Every published quantity is a median across instances with a bootstrap
  interval; no mean is published.
- Real adapters: rule `strict-v2` (`multilora/adapters.py`,
  `real_adapter_qualifies`). An adapter qualifies only if it is a plain LoRA
  with rank exactly 16, targets exactly the seven modules above, has
  `task_type` `CAUSAL_LM`, no `modules_to_save`, no DoRA or rsLoRA, no rank or
  alpha patterns, no `lora_bias`, `fan_in_fan_out` off, `bias` `none`, and
  `base_model_name_or_path` equal to `Qwen/Qwen3-4B`. Of 261 Hub adapters
  seen, 7 qualified; the gate uses the first four by repo id, the table in
  "Conditions". `tests/test_multilora_adapters.py` re-derives that selection
  from the committed evidence, `fixtures/a5/real_adapter_candidates.json`.
- Author-signed values, signed off by the owner in chat on 2026-10-05: knee
  threshold τ 0.10 (10% throughput loss per doubling), TTFT SLO 1.0 s (p95),
  100,000 requests per tenant per month, peak-to-average 3.0. The GPU hourly
  rate, $1.00, is an illustrative round number carried over from artifact 1's
  published assumption (docs/post.md); artifact 4 has not committed a rate. If
  artifact 4 fixes a different rate before publication, that is an amendment
  to this document, not a silent change.
- Budget: `scripts/a5_budget.py` estimates 3.87 GPU-hours (about $3.87 at the
  illustrative rate) for 216 instances, 8 conditions (the seven sweep points
  and the gauge control) plus the gate, 24 each, under the $20 cap, so nothing
  is cut by the amendment's cut order. Its cold startup times come from
  `fixtures/a5/budget-085/`, because the final 0.80 set has no cold starts; the
  0.85 N1 cold start itself reused a compile cache, so it is not a fresh
  compile (docs/recon-a5.md, R8).
- Request shape: 13 prompt tokens + 16 output tokens = 29 tokens, the prompt
  length measured by reconnaissance (docs/recon-a5.md,
  `request_shape_prompt_tokens` `[13]`); bench dataset args
  `--random-input-len 13 --random-output-len 16`.
- Cold-compiled instances are excluded by the exclusion rule above. If a
  condition falls below 20 instances, top-up instances are scheduled before any
  analysis, and the post discloses them (amendment §4, "Blocks, jobs and
  instance counts").
