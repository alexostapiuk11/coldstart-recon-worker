# Artifact 5 — reconnaissance record (amendment §6)

Captured 2026-10-05 (UTC) on image
`ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:39e967e984962d5c355616b6ce27fa309a0895df41c61652c857a9b43a001b7a`
(commit 096298c) for the final set and the 0.85 set, endpoint `hwtia288shbztb`
(template `pckotb2yze`, RTX 4090, network volume `9c7ut2slrd` in EU-RO-1),
model `Qwen/Qwen3-4B` at `1cfa9a7208912126459214e8b04321603b3df60c`, vLLM
0.27.1. Captures: `fixtures/a5/`. Answers computed by
`scripts/a5_recon_report.py` into `fixtures/a5/recon_report.json`.

What the files hold, and where each fact comes from:

- `fixtures/a5/lora-*.json` (top level): the final set, nine probes at
  `gpu_memory_utilization` 0.80. This is the set `recon_report.json` is computed
  from (the script reads only the top level). Engine log timestamps run
  10-05 05:47:23 to 10-05 05:59:50, all on pod `vek8wg1x5n1n2r`.
- `fixtures/a5/budget-085/`: the same nine probes at 0.85, kept as evidence.
  Log timestamps 10-05 04:44:44 to 10-05 05:40:24, on two pods
  (`xxl7l9mmxv3t55` for the N1 pair and N64-first, `b4vz30ffiba1t8` for the rest).
- `fixtures/a5/oom-attempt-1/`: the first two N1 probes at vLLM's default 0.92.
  Log timestamps 10-05 04:09:37 to 10-05 04:12:01, pod `rs5tgu0t3plzvl`.
- `fixtures/a5/help.json`: `vllm serve --help` and `vllm bench serve --help`.
  It carries no engine log and no wall-clock timestamp; its `clock_A.t_submit`
  (212225.3) is 401.0 s before oom-attempt-1's first submit (212626.4) on the
  same controller clock.
- `help.json` and `oom-attempt-1/` were captured on the earlier image
  `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:25fb8c399c5b95a2f63391ebf98d78d6432663fe92f32ac5fdf45e677a5097cb`
  (commit b81ffdc, same vLLM base). The image digests, endpoint, template and
  volume IDs are not stored in the captures; they come from the run notes and
  commit d1084d5's message. The vLLM version comes from the engine log banner
  (`version 0.27.1`) in every capture that has a log; the model revision comes
  from the engine's config line and the served command.
- Timestamps: the engine log lines carry `MM-DD HH:MM:SS` with no year and no
  zone. They are read as UTC: the capture files' modification times (local
  time, UTC−7) agree with them to the minute, and the year comes from the
  commits.

## Answers and the rules applied

The rules are Task 5 Step 3's table (amendment §6), fixed before the data.

| # | Answer | Source key | Rule applied |
|---|---|---|---|
| R1 | `true`: `--max-loras` is in `vllm serve --help` | `R1_in_batch_cap_is_max_loras` | Stops only if false. Not triggered: the in-batch cap is `--max-loras`, so §3a holds |
| R2 | `64` | `R2_highest_healthy_slots` | Applies only below 64. Not triggered: the sweep's top stays 64 |
| R3 | `true`: every registered adapter in every healthy probe answered HTTP 200 (1, 1, 16, 16, 64, 64, 64, 8 adapters) | `R3_every_adapter_answered`, `probes.*.completions_ok` | Stops only if false. Not triggered: synthetic adapters serve (August §4's go) |
| R4 | bench flags missing `[]`; engine flags missing `[]`; phase arrays complete `true` | `R4_bench_flags_missing`, `R4_engine_flags_missing`, `R4_phase_arrays_complete` | Stops (or, for `--specialize-active-lora` alone, cuts the diagnostic) only if a list is non-empty or the arrays are incomplete. Not triggered |
| R5 | `64` distinct adapters running at the top point | `R5_max_distinct_running_at_top` | Applies only below the top point. 64 equals the top point, so C = 64 keeps every adapter in flight; the top stays 64 |
| R6 | `true`: every healthy probe's log reports KV capacity with LoRA enabled | `R6_kv_reported_with_lora`, `probes.*.kv_capacity_tokens` | Stops only if false. Not triggered: KV capacity is read from the log, no new measurement |
| R7 | `true`: the running-adapters gauge is exported (by every healthy probe except `lora-N64-no-stats`, which disables log stats) | `R7_gauge_exported`, `probes.*.gauge_exported` | Cuts the gauge control only if false. Not triggered: the gauge control stays, subject to Task 6's budget |
| R8 | startup seconds per point, first and restart: see "R8: startup times" below | `probes.*.startup_s`, `probes.*.compile_state` | Feeds Task 6's budget. The 0.80 set has no cold starts, so cold times come from `budget-085/` |
| R9 | `true`: `--specialize-active-lora` is in `vllm serve --help` | `R9_specialize_flag_present` | Cuts the diagnostic only if false. Not triggered by the rule. The diagnostic is cut anyway, for a reason the table does not cover: see "The diagnostic is cut" |
| R10 | 4 selected of 261 seen, rule `strict-v2`; the gate probe served all 4 real and 4 synthetic adapters | `real_adapter_candidates.json` (`seen`, `selected`, `rejected`, `rule`, `enough`), `lora-gate-real.json` | Already applied in Task 2. `enough` is `true`. See "R10: the real adapters" below |
| Request shape | 13 prompt tokens + 16 output = 29 tokens | `request_shape_prompt_tokens` = `[13]` | Stops only if more than one value. One value: it fixes `--random-input-len 13` |

### R8: startup times

`startup_s` from `probes.*.startup_s` (0.80, in `recon_report.json`) and from the
same field in `budget-085/` captures. `compile_state` is `engine_facts`'s
reading of the log: `torch.compile took … s in total` under 1 s reads warm.

| Point (slots) | 0.80 `-first` | 0.80 `-restart` | 0.85 `-first` (cold) | what the 0.85 `-first` log shows | 0.85 `-restart` |
|---|---|---|---|---|---|
| 1 | 55.46 s, warm | 39.90 s, warm | 93.12 s, reads cold | `torch.compile took 1.77 s`; the log says `Directly load AOT compilation` from artifact `d12c0718…`, which oom-attempt-1's N1-first compiled and saved. Not a fresh compile | 62.65 s, warm |
| 16 | 44.66 s, warm | 38.40 s, warm | 117.91 s, cold | `torch.compile took 46.68 s`; fresh compile (`saved AOT compiled function`, artifact `3aa8b8ac…`) | 47.41 s, warm |
| 64 | 48.43 s, warm | 47.93 s, warm | 215.35 s, cold | `torch.compile took 83.24 s`; fresh compile (artifact `9835de36…`) | 44.65 s, warm |
| 8 (`lora-gate-real`) | 37.14 s, warm (only probe) | none | 104.33 s, cold | `torch.compile took 52.86 s`; fresh compile (artifact `f627f65c…`) | none |

Other 0.80 probes at 64 slots: `lora-N64-no-stats` 56.71 s (warm),
`lora-N64-specialize` 65.23 s until the health check gave up (warm, unhealthy).

Why the 0.80 set has no cold starts: every 0.80 probe's log shows
`Directly load AOT compilation` from the compile cache on the network volume,
which the 0.92 and 0.85 runs had already filled. The AOT artifact hash for a
slot count is the same at every budget (`d12c0718…` for N1 at 0.92, 0.85 and
0.80; `9835de36…` for N64 at 0.85 and 0.80), so the cache key did not change
with the budget. That compile *cost* does not depend on the memory budget is an
expectation, not a measurement: no point was compiled cold at two budgets.

Gaps in R8, stated plainly:

- N1 has no fresh-compile startup that reached health. The only fresh N1
  compile is oom-attempt-1's N1-first (`torch.compile took 39.66 s`), and that
  instance ran out of memory. The 0.85 N1-first reads cold by the 1 s rule but
  loaded a cached compile; its extra time is elsewhere (its log shows
  `Model loading took 7.63 GiB and 18.138512 seconds`, against 2.76 to 14.18 s
  in every other capture).
- Points 2, 4 and 32 were never probed, cold or warm.
- At 0.85 the N64 `-first` and `-restart` ran on different pods
  (`xxl7l9mmxv3t55`, `b4vz30ffiba1t8`), so that pair is not a same-host restart.

### R10: the real adapters

From `fixtures/a5/real_adapter_candidates.json`: `seen` holds 261 Hub adapters
for `Qwen/Qwen3-4B`; rule `strict-v2` (`multilora/adapters.py`,
`real_adapter_qualifies`) keeps a plain LoRA with rank exactly 16, exactly the
seven modules (`q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`),
`task_type` `CAUSAL_LM`, no `modules_to_save`, no DoRA or rsLoRA, no rank or
alpha patterns, no `lora_bias`, `fan_in_fan_out` off, `bias` `none`, and
`base_model_name_or_path` equal to `Qwen/Qwen3-4B`.

254 were rejected, 7 qualified, and the first 4 by repo id were selected
(`count` 4). The 3 that qualified but were not needed:
`predictive-maintenance/qwen3-4b-failuresensoriq-lora`, `shmarymane/sin-ia`,
`ziadrone/airesupdated-v6`.

Rejections by first failing check (from the `rejected` dict; reasons grouped by
their leading words):

| Reason | Count | Detail |
|---|---|---|
| rank is not 16 | 160 | rank 32: 74, rank 64: 38, rank 8: 30, rank 128: 17, rank 1: 1 |
| `base_model_name_or_path` is not `Qwen/Qwen3-4B` | 60 | `Qwen/Qwen3-4B-Base` 25, `Qwen/Qwen3-4B-Instruct-2507` 23, `base/Qwen/Qwen3-4B-Instruct-2507/` 5, seven others 1 each |
| `task_type` is not `CAUSAL_LM` | 18 | `SEQ_CLS` 13, `None` 4, `FEATURE_EXTRACTION` 1 |
| does not target all seven modules | 11 | missing the three MLP modules 7, missing five 3, missing `gate_proj` 1 |
| targets modules outside the seven | 3 | `dense_4h_to_h`/`dense_h_to_4h` 2, `gate_up_proj` 1 |
| `modules_to_save` not empty | 1 | `['lm_head']` |
| `use_rslora` on | 1 | |
| **Total** | **254** | 160 + 60 + 18 + 11 + 3 + 1 + 1 |

Selected (repo, revision):

| Repo | Revision |
|---|---|
| `AIsakawaii/task_b_method2_qwen4b` | `8ba6625bbb5f5a8770109f003ae55fcaef4fb117` |
| `davemaxuellkr/KIRD-project_QLoRa-Qwen3-4B_en-ko` | `f7eb9b54171b1212347ebb0e3bb26008d81e92db` |
| `hanghang1024/Qwen3-4b-Qlora-Fin` | `47d3fc76a0d748497e726134ee5092e68bb0cacf` |
| `jacobcd52/qwen3_4b_hacker` | `89cb5e72a31c2f2ce53e9c4f9aee9ee38b7c26e2` |

The gate probe `lora-gate-real` (0.80) registered these four as `r00`–`r03`
plus four synthetic adapters `s00`–`s03` (8 slots). All 8 answered HTTP 200
(`completion_status`), and its phase completed 640 of 640 requests with 0
failed. The 0.85 gate probe did the same (8 of 8 HTTP 200, 640 of 640).

## Decisions carried into the pre-registration

- Sweep: `(1, 2, 4, 8, 16, 32, 64)`. R2 = 64 and R5 = 64 leave the top at 64.
- Concurrency: 64 (R5: all 64 adapters were seen running at C = 64).
- `gpu_memory_utilization` 0.80, fixed in the endpoint environment as
  `A5_GPU_MEMORY_UTILIZATION` and passed explicitly by the worker (commit
  096298c). See "The memory budget".
- `include_diagnostic = False`: `lora-N64-specialize` ran out of memory in
  CUDA-graph capture at 0.85 and at 0.80, and the owner decided on 2026-10-05
  to cut the diagnostic rather than lower the budget further or give it its own
  budget. Hypothesis H4 is deleted in the pre-registration. See "The diagnostic
  is cut".
- `include_control = True`, subject to the budget rule in Task 6 (R7 true).
- Request shape: 13 prompt tokens + 16 output = 29 tokens; bench dataset args
  `--dataset-name random --random-input-len 13 --random-output-len 16`. The
  capture runs used a provisional `--random-input-len 14` (every capture's
  `payload.dataset_args`); 13 is the measured value.
- Real adapters: the four in the R10 table, at those revisions.
- Task 6's budget must take cold startup times from `budget-085/`, not from the
  `-first` probes of the top-level set, because those read warm. (As written,
  Task 6 Step 4's script takes `cold` from the `-first` probes in
  `recon_report.json`, which are the warm 0.80 ones.) N1's cold time there is
  not a fresh compile, and points 2, 4 and 32 have no observation (R8 gaps).

## The memory budget

**(a) vLLM's default, 0.92: out of memory.** The first two N1 probes
(`oom-attempt-1/`, no `--gpu-memory-utilization` in the served command) failed
the health check.

- `lora-N1-first` (cold compile, `torch.compile took 39.66 s`): the engine
  logged `Free memory on device (22.64/23.52 GiB) on startup. Desired GPU memory
  utilization is (0.92, 21.64 GiB). Actual usage is 7.97 GiB for consumed memory
  (weights + non-torch), 0.8 GiB for peak activation, and 1.28 GiB for CUDAGraph
  memory.` with `Current kv cache memory in use is 12.86 GiB`. It then died in
  the sampler warm-up (`warmup_kernels` → `flashinfer_sample`):
  `Tried to allocate 150.00 MiB. GPU 0 has a total capacity of 23.52 GiB of which
  146.44 MiB is free`, `this process has 22.87 GiB memory in use`, plus
  `Process 51 has 500.00 MiB memory in use`.
- `lora-N1-restart` (warm, `torch.compile took 0.36 s`): `Available KV cache
  memory: 13.56 GiB` (98,752 tokens). It died **during CUDA-graph capture**, not
  in the sampler: the FULL capture bar reached 45/70, then
  `torch.AcceleratorError: CUDA error: out of memory` at
  `gpu_worker.py` line 717. It logged no `Free memory on device` line.

How the budget is spent (derived from the N1-first line): consumed 7.97 +
activation 0.8 + KV 12.86 = 21.63 GiB, which is the 21.64 GiB budget (to
rounding). The 1.28 GiB of CUDA-graph memory comes on top: 21.63 + 1.28 =
22.91 GiB, against 23.52 GiB total, with 500 MiB held by another process:
23.52 − 22.91 − 0.49 = 0.12 GiB left, the order of the 146.44 MiB free at the
failure. So the engine sizes KV to the budget and the graph memory is outside
that sizing. Every healthy capture logs `Graph capturing finished … took
1.28 GiB`.

**(b) 0.85: eight healthy, one failed.** The worker was changed to require
`A5_GPU_MEMORY_UTILIZATION` from the endpoint environment and pass
`--gpu-memory-utilization` (commit 096298c). All nine probes ran at 0.85
(`budget-085/`, served command `--gpu-memory-utilization 0.85`): eight healthy,
`lora-N64-specialize` failed.

**(c) 0.80: eight healthy, one failed.** Because N64-specialize failed at 0.85,
the budget was lowered to 0.80 for the whole experiment and all nine probes
re-ran (top level, served command `--gpu-memory-utilization 0.8`): eight
healthy, `lora-N64-specialize` failed again.

The plain N64 restart at 0.80 (`lora-N64-restart`) logged:
`Free memory on device (22.64/23.52 GiB) on startup. Desired GPU memory
utilization is (0.8, 18.81 GiB). Actual usage is 12.78 GiB for consumed memory
(weights + non-torch), 0.15 GiB for peak activation, and 1.28 GiB for CUDAGraph
memory`, with `Available KV cache memory: 5.89 GiB`. Derived: 12.78 + 0.15 +
5.89 = 18.82 GiB (the 18.81 GiB budget, to rounding); with graphs, 18.82 + 1.28
= 20.10 GiB, leaving 23.52 − 20.10 = 3.42 GiB of the device unclaimed by this
engine.

## The diagnostic is cut

`lora-N64-specialize` (64 slots, `--specialize-active-lora`) ran out of memory
during CUDA-graph capture at both budgets. Its torch.compile was the plain N64
artifact (`Directly load AOT compilation` from `9835de36…`, the same as the
plain N64 probes); what differed was the number of graphs.

| Probe | PIECEWISE graphs | FULL graphs | Where it died | Memory at the OOM |
|---|---|---|---|---|
| plain N64 (all healthy N64 probes, both budgets) | 102/102 | 70/70 | healthy | n/a |
| N64-specialize, 0.85 (10-05 05:36:28) | bar reached 319/459 | not started | PIECEWISE capture, in `flash_attn_varlen_func` | tried 2.00 MiB; 448.00 KiB free; this process 23.02 GiB in use, 19.81 GiB allocated by PyTorch; another process 500.00 MiB |
| N64-specialize, 0.80 (10-05 05:56:34) | 459/459 | 0/315 | at the start of FULL capture | tried 20.00 MiB; 4.44 MiB free; this process 23.01 GiB in use, 18.67 GiB allocated by PyTorch; another process 500.00 MiB |

Derived: 459 / 102 = 4.5 and 315 / 70 = 4.5, so specialization asked for 4.5
times as many graphs of each kind. The 0.85 run had more KV allocated (7.06 GiB
against 5.89 GiB at 0.80, same 12.49 GiB model load) and died earlier in the
capture.

Task 5's rule table does not cover this outcome: R9 is `true` (the flag exists),
and no row covers a flag that exists but whose instance cannot start. The owner
decided on 2026-10-05 to cut the diagnostic rather than lower the budget further
or give the diagnostic its own budget. So `include_diagnostic = False`, and
hypothesis H4 is deleted in the pre-registration.

What was not measured: no `--specialize-active-lora` instance became healthy at
any point, so there is no specialize result at all; N1 and N16 specialize were
never probed. That the failure comes from graph count scaling with
specialization is an inference from the capture progress bars and the OOM lines,
not a separate measurement; no specialize run logged a
`Graph capturing finished … took … GiB` line, so its graph memory is unknown.

## Observed memory and capacity

All values are parsed from each capture's `log_lines`:
`Model loading took X GiB`, `Available KV cache memory: X GiB`,
`GPU KV cache size: N tokens`, and
`Maximum concurrency for 8,192 tokens per request: Nx`.

At 0.80 (budget 18.81 GiB). Every probe of a slot count logged the same four
values, warm or "first":

| Slots | Probes | Model loading took | Available KV cache memory | KV cache tokens | Max concurrency (8,192 tokens/request) |
|---|---|---|---|---|---|
| 1 | N1-first, N1-restart | 7.63 GiB | 10.74 GiB | 78,208 | 9.55x |
| 8 | gate-real | 8.17 GiB | 10.2 GiB | 74,288 | 9.07x |
| 16 | N16-first, N16-restart | 8.78 GiB | 9.61 GiB | 69,968 | 8.54x |
| 64 | N64-first, -restart, -no-stats, -specialize | 12.49 GiB | 5.89 GiB | 42,864 | 5.23x |

At 0.85 (budget 19.99 GiB), where cold and warm instances differ:

| Slots | Probe (compile) | Model loading took | Peak activation | Available KV cache memory | KV cache tokens | Max concurrency |
|---|---|---|---|---|---|---|
| 1 | N1-first (cached compile, reads cold) | 7.63 GiB | 0.15 GiB | 11.95 GiB | 86,976 | 10.62x |
| 1 | N1-restart (warm) | 7.63 GiB | 0.15 GiB | 11.92 GiB | 86,768 | 10.59x |
| 8 | gate-real (cold) | 8.17 GiB | 0.83 GiB | 10.64 GiB | 77,488 | 9.46x |
| 16 | N16-first (cold) | 8.78 GiB | 0.87 GiB | 10.01 GiB | 72,912 | 8.90x |
| 16 | N16-restart (warm) | 8.78 GiB | 0.15 GiB | 10.79 GiB | 78,544 | 9.59x |
| 64 | N64-first (cold) | 12.49 GiB | 1.09 GiB | 6.07 GiB | 44,224 | 5.40x |
| 64 | N64-restart, -no-stats, -specialize (warm) | 12.49 GiB | 0.15 GiB | 7.06 GiB | 51,440 | 6.28x |

(Peak activation is from each capture's `Free memory on device` line; the
specialize probe logged none, so its row's 0.15 GiB is the restart's.)

Derived:

| Quantity | Value | How derived |
|---|---|---|
| Per-slot weight/LoRA-buffer cost | 0.0771 GiB (79.0 MiB) per slot | (N64 load − N1 load) / 63 = (12.49 − 7.63) / 63. Cross-checks: (8.78 − 7.63) / 15 = 0.0767 (N16); (8.17 − 7.63) / 7 = 0.0771 (gate) |
| KV tokens lost per slot at 0.80 | 561.0 tokens | (78,208 − 42,864) / 63 |
| Cold vs warm KV at 0.85, N64 | 7,216 tokens fewer cold (14.0 %) | 51,440 − 44,224; 7,216 / 51,440 |
| Cold vs warm KV at 0.85, N16 | 5,632 tokens fewer cold (7.2 %) | 78,544 − 72,912; 5,632 / 78,544 |
| Where the cold difference comes from | the profiling run's peak activation | 19.99 − 12.83 − 1.09 = 6.07 GiB (N64 cold) against 19.99 − 12.78 − 0.15 = 7.06 GiB (N64 warm) |

That the load increase per slot is the LoRA buffers is an inference (the model
weights are the same at every point). The 0.85 N64 cold/warm pair also ran on
different pods. Campaign instances are expected to start warm, because the
campaign primes the compile cache once per N before it starts (amendment §3d;
the volume's cache now holds compiles for 1, 8, 16 and 64 slots only), so their
KV capacity should be the warm value; the 0.80 set, all warm, is the one that
matches. This is an expectation, not an observation. The amendment also says
`--specialize-active-lora` is not in the compile-cache hash; the two specialize
captures agree (they loaded the plain N64 artifact).

KV is not the binding limit at the campaign's shape: at C = 64 the N64-restart
engine logged `Running: 64 reqs … GPU KV cache usage: 4.7%`. Derived check,
assuming vLLM's default 16-token KV block: 29 tokens take 2 blocks = 32 tokens,
and 64 × 32 = 2,048 of 42,864 tokens is 4.8 %.

## Performance seen during reconnaissance

These are single-phase reconnaissance observations: one phase of 640 requests at
concurrency 64, `regime` `spread`, with the provisional
`--random-input-len 14`. They are not the campaign and are not results. TTFT
percentiles are computed from each phase's `ttfts` array (all 640 entries, no
errors), linear interpolation, in milliseconds. "Running" is the most distinct
adapters the gauge showed in one sample (`gauge_samples`).

At 0.80 (the final set):

| Probe | Completed | Failed | Phase duration | TTFT p50 | TTFT p95 | Running (max) |
|---|---|---|---|---|---|---|
| lora-N1-first | 640 | 0 | 3.030 s | 79.9 ms | 118.1 ms | 1 |
| lora-N1-restart | 640 | 0 | 2.980 s | 64.9 ms | 116.6 ms | 1 |
| lora-N16-first | 640 | 0 | 3.523 s | 65.6 ms | 156.5 ms | 16 |
| lora-N16-restart | 640 | 0 | 3.488 s | 72.2 ms | 153.6 ms | 16 |
| lora-N64-first | 640 | 0 | 5.777 s | 108.6 ms | 172.6 ms | 64 |
| lora-N64-restart | 640 | 0 | 5.608 s | 92.4 ms | 175.5 ms | 64 |
| lora-N64-no-stats | 640 | 0 | 5.772 s | 117.8 ms | 168.2 ms | no gauge |
| lora-gate-real | 640 | 0 | 3.197 s | 59.0 ms | 125.4 ms | 8 |

At 0.85 (`budget-085/`):

| Probe | Completed | Failed | Phase duration | TTFT p50 | TTFT p95 | Running (max) |
|---|---|---|---|---|---|---|
| lora-N1-first | 640 | 0 | 3.617 s | 121.1 ms | 253.5 ms | 1 |
| lora-N1-restart | 640 | 0 | 3.808 s | 154.0 ms | 232.5 ms | 1 |
| lora-N16-first | 640 | 0 | 3.558 s | 71.1 ms | 137.3 ms | 16 |
| lora-N16-restart | 640 | 0 | 3.579 s | 76.2 ms | 115.4 ms | 16 |
| lora-N64-first | 640 | 0 | 6.238 s | 130.8 ms | 260.3 ms | 64 |
| lora-N64-restart | 640 | 0 | 5.754 s | 104.3 ms | 151.6 ms | 64 |
| lora-N64-no-stats | 640 | 0 | 5.701 s | 104.3 ms | 131.3 ms | no gauge |
| lora-gate-real | 640 | 0 | 3.235 s | 73.9 ms | 104.1 ms | 8 |

Every request in every phase produced 16 output tokens (`output_lens`).

## Cost and time

From each capture's `payload.clock_C` (RunPod's `executionTime`/`delayTime`,
present only on successful jobs) and `clock_A` (the controller's monotonic
clock, submit to result).

| Set | Successful jobs | Sum of `execution_ms` | Sum of `delay_ms` | Failed jobs (controller time each) | Wall time |
|---|---|---|---|---|---|
| 0.80 (top level) | 8 | 668,270 ms (11.14 min) | 89,382 ms | 1: N64-specialize, 72.7 s | 856.5 s (14.3 min), one contiguous run: first `t_submit` 218409.4 to last `t_result` 219265.9 |
| 0.85 (`budget-085/`) | 8 | 1,083,888 ms (18.06 min) | 411,988 ms | 1: N64-specialize, 57.4 s | 3,697.6 s (61.6 min) from first submit to last result, but not contiguous: the jobs themselves sum to 1,581.7 s (26.4 min), with gaps at about 04:48–05:06 and 05:10–05:30 UTC |
| 0.92 (`oom-attempt-1/`) | 0 | none | none | 2: N1-first 124.7 s, N1-restart 41.8 s | 166.5 s |
| `help.json` | 1 | 37,811 ms (0.63 min) | 11,684 ms | 0 | 53.0 s |

All successful jobs together: 668,270 + 1,083,888 + 37,811 = 1,789,969 ms
(29.83 min) of `execution_ms`. The four failed jobs carry no `execution_ms`;
their controller-side durations sum to 296.6 s. The record does not say what
ran in the 0.85 set's gaps; any job that was not captured is not counted here.

No dollar figure is given. The hourly rate is not in the record (unverified;
read it off the RunPod console), nor is whether RunPod bills `delay_ms` (worker
boot and queue) or the failed jobs' time.
