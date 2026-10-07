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

## Amendment 1 — a larger equivalence gate (2026-10-05)

This amendment is post-hoc. It was written after the first equivalence gate
returned its verdict, and in response to that verdict. The post will say so.
Nothing above this section has been edited: the text and the table above remain
the record of what was pre-registered before the first measured run.

### What happened

The first gate ran 24 instances under the rule above. One instance (run index 5)
read its compile cache cold and was excluded, which left 23 usable instances.
Its records are kept as the pilot, at `data/a5/gate-pilot.jsonl` (commit
4b31c3f has them at their original path, `data/a5/gate.jsonl`). The verdict was
inconclusive:

- Throughput: median relative difference (synthetic minus real, over real)
  -0.8%, 90% bootstrap interval [-2.2%, +0.3%], inside ±5%, and resolved: the
  real-versus-real resolution check gave -0.6% [-2.4%, +1.1%].
- TTFT p50: median +2.9%, 90% interval [-2.7%, +10.7%], not inside ±5%, and
  unresolved: the real-versus-real resolution check gave +8.9% [-6.4%, +11.7%].

Because the TTFT resolution check failed, the rule reads inconclusive, not
fail.

### What the pilot's records show

Recomputed from `data/a5/gate-pilot.jsonl`, the 23 usable instances only:

- No drift with phase position. The median single-phase TTFT p50 by position
  in the instance is 112.9 ms, 113.6 ms, 112.6 ms and 112.8 ms for positions
  0 to 3 (23 phases each).
- Real and synthetic phases are within a few milliseconds of each other: the
  median single-phase TTFT p50 is 111.4 ms over the 46 real phases and
  114.8 ms over the 46 synthetic phases.
- Single-phase TTFT p50 varies by roughly ±10-15% between phases of one
  instance. The real-versus-real relative difference (second real phase
  against the first, per instance) has quartiles -8.2%, +8.9% and +16.2%, and
  ranges from -33.6% to +30.9%.

The pilot shows noise, not evidence of bias. At 23 usable instances the gate
cannot establish equivalence on TTFT p50 within ±5%. It does not show that
synthetic and real adapters differ. The real-versus-real median of +8.9% is far
from the zero expected of two phases of the same adapter set; with the
position medians flat, it is read here as noise, but if it recurs the larger
gate will read inconclusive too.

### What changes

Only the gate's size. The gate runs 144 instances instead of 24
(`gate_instances` 144) in a fresh store, `data/a5/gate.jsonl`. Everything else
about the gate is unchanged: the configuration held fixed above, the 4 real and
4 synthetic adapters, four spread phases per instance (two over the real set,
two over the synthetic set, in randomized order), the statistic, the margin
δ = τ/2 = 0.05, the 90% bootstrap interval, the resolution check and the
verdict rule.

The fresh gate's instances 0 to 23 repeat the pilot's phase orders and request
seeds. The design is indexed by run index: each instance's phase order comes
from `phase_plan` with the run index, and the bench request seeds are derived
from the run index inside the worker. The gate is a single condition, so a
schedule seed orders nothing. Nothing is pooled, so this does not matter
statistically: the new gate's instances 0 to 23 are new measurements of the
same design, not reuses of the pilot's records.

The pilot is not pooled with the new gate. The verdict is computed from the new
gate's records alone. The post reports the pilot as a pilot, with its numbers.
The pilot was renamed to `data/a5/gate-pilot.jsonl` so that a resumed run of the
gate, which matches stored records by run index and condition, can never pick
up the pilot's records as its own. The campaign and the analysis read only
`data/a5/gate.jsonl`.

### Sizing

The pilot's TTFT interval half-width was 6.70%, and its real-versus-real
resolution interval half-width about 9.0%, at 23 usable instances. If both
shrink with the square root of the count, then at about 139 usable instances
(144 less the expected cold-compile exclusions; the pilot lost 1 in 24) they
would be about 2.7% and 3.7%. An earlier sizing of 72 instances considered only
the TTFT interval and left out the resolution check. That check needs roughly
75 usable instances before its half-width falls below 5% even if it is centred
on zero, so 144 was chosen.

These are estimates, not guarantees. A pass needs the TTFT interval's median
plus its half-width inside ±5%. If the true bias stays near the pilot's +2.9%,
an interval of about 2.7% still crosses +5%; the true bias must be below about
2.3% for a pass. The larger gate may still be inconclusive or fail. A fail
would be a finding (synthetic adapters slower in TTFT p50 by a few percent),
not an error.

### What happens next

The campaign runs only if the new gate passes. If the new gate is inconclusive
or fails, the August fallback applies as §4 of the design amendment says
("Fail or inconclusive: the August fallback applies unchanged"). The gate is
not run a third time under this amendment.

### Cost

The pilot's instances took 156 to 202 s of wall time each when warm (median
161 s, mean 174 s including the 357 s cold-compile instance; the whole pilot
took 1.16 hours). At about 174 s each, 144 instances take about 7 hours, or
about $7 to $8 at the illustrative $1.00 to $1.11 per GPU-hour. These are
estimates.

### Budget, revised

The budget bullet above (3.87 GPU-hours for 216 instances) used a 24-instance
gate and a per-instance model of about 52 to 75 s (53 s for the gate's 8
slots), built from reconnaissance's setup, warm-startup and per-request
timings. The pilot measured about 174 s per instance from submission to result,
roughly three times the model. Recomputed from the measured time:

- New gate: 144 × 174.4 s = 6.98 hours.
- Campaign: 192 instances (the seven sweep points and the gauge control, 24
  each) × the same 174.4 s = 9.30 hours. No campaign instance has been
  measured; this assumes they take as long as a gate instance.
- Already spent: the priming runs took 33 minutes of wall time (0.55 hours) and
  the pilot 1.16 hours, from the `clock_A` fields of `data/a5/priming.jsonl`
  and `data/a5/gate-pilot.jsonl`.
- Total: about 18.0 hours, so about $18.0 at $1.00 per GPU-hour and about $20.0
  at $1.11.

The total approaches the $20 cap: at the upper rate it reaches it. The design
amendment's §6 cut order (the gauge control first) remains the rule if the
campaign estimate exceeds the cap, and that decision is the owner's.

### Decision

Chosen by the owner in chat on 2026-10-05, among a larger gate in a fresh
store, the August fallback, or changing the decision rule. The size was chosen
between 72, 108 and 144 instances after the sizing was corrected to include the
resolution check.

### Parameters as amended

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
| `gate_instances` | `144` |
| `equivalence_margin` (derived) | `0.05` |
| `requests_per_phase` (derived) | `640` |

## Amendment 2 — the GPU hourly rate, a base-model disclosure and an endpoint constraint (2026-10-05)

This amendment was written while the larger gate of Amendment 1 was running. It
records three decisions the owner made in chat on 2026-10-05. None of its three
parts changes what is measured, or how the gate or the campaign is analysed.
Nothing above this section has been edited: the text and the tables above remain
the record of what was pre-registered and of Amendment 1.

### The GPU hourly rate

`gpu_hourly_rate` changes from $1.00 per GPU-hour (illustrative, carried over
from artifact 1) to $1.1095 per GPU-hour, artifact 4's registered rate. "Rules
fixed now" said that if artifact 4 fixed a different rate before publication,
that would be an amendment to this document, not a silent change; this is that
amendment.

The rate is `GPU_HOURLY_RATE = 1.1095` in artifact 4's `placement/registered.py`
(commit b17c8ac), and its provenance there reads:

> derived from RunPod's billing API for endpoint nnypnh9drkq5ux (GET
> /v1/billing/endpoints: $0.2443519 for 792.879 s billed, $0.000308 per
> second), read 2026-10-05

Arithmetic check: $0.2443519 / 792.879 s = $0.000308 per second, and × 3600 =
$1.1095 per hour. It is one billing sample from another endpoint
(`nnypnh9drkq5ux`, artifact 4's), so it is an estimate of the platform's price
for this GPU class, not a quoted price, and it stays a stated assumption in the
post. Artifact 4's reconnaissance record (`docs/recon-a4.md`, section 1, on
`main`, not on this branch) later read the same billing record in full, $0.4988
for 1,623.2 s billed, an implied $1.106 per hour, and kept $1.1095 as
registered; the 0.3% difference does not matter here either. Commit b17c8ac is
on the remote: `git branch -r --contains b17c8ac` lists `origin/main` (as of
the local repository's last fetch).

The rate affects only the economics: the cost per tenant, the three-way table
with artifact 4 and the budget estimate. It never enters a measurement. The
economics must use one rate across both artifacts, and
`multilora/economics.py` refuses a three-way table whose artifact 4 rate
differs from this pre-registration's.

Amendment 1's "Budget, revised" total at the new rate: 6.98 + 9.30 + 0.55 +
1.16 = 17.99 GPU-hours, and 17.99 × $1.1095 = $19.96. That is just under the $20
cap, with no margin to speak of ($0.04). The design amendment's §6 cut order
(the gauge control first) remains the rule if the campaign estimate exceeds the
cap, and that decision is the owner's. `scripts/a5_budget.py`, which uses
reconnaissance's per-instance timing model that Amendment 1 found to be roughly
three times too low, now prints 5.64 GPU-hours and $6.25 for the gate of 144
and the campaign; the measured-time total above is the one compared with the
cap.

### The base model

Artifact 5's base model stays `Qwen/Qwen3-4B` at
`1cfa9a7208912126459214e8b04321603b3df60c` (the owner's decision). The
configuration held fixed above does not change.

Artifact 4's reconnaissance changed its own model class to `Qwen/Qwen3-1.7B` at
`70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`. Its primary pair (Qwen3-4B and
Qwen3-4B-Base, two engines at 0.45 of GPU memory each) failed its
pre-registered go/no-go on 2026-10-05, with KV capacities of 9,456 and 9,520
tokens against the 16,384 required, while the fallback pair (Qwen3-1.7B twice)
passed with 55,104 and 64,976 tokens (`docs/recon-a4.md`, section 2, on `main`).
That record also says artifact 5's base model changes with artifact 4's class
(section 8); the owner decided otherwise, which is why this is disclosed here.
The design amendment's prerequisite 2 ("Artifact 4 fixes the base model, GPU
class and vLLM image") is met for the GPU class and the vLLM image, but not for
the base model.

Consequence for the post: "Adapters versus swapping models" sets artifact 5's
adapter-serving results on Qwen3-4B against artifact 4's model-swap costs
measured on Qwen3-1.7B. The post must say plainly that the two sides use
different model sizes, and must not present the comparison as like-for-like.
Artifact 4's reference point is expected to be `{"regime": "bursty", "s": 1.0}`.

`docs/experiment-a4.md`, step 1, says Qwen3-4B "is also artifact 5's base
model". For artifact 4, that sentence is superseded by its own fallback
decision; for artifact 5 it still holds.

### An endpoint constraint

At 19:28:40 UTC on 2026-10-05, `allowedCudaVersions` was set to `["13.0"]` on
the measurement endpoint `2ilkjkm9ob4qvo`. That was immediately after the gate
record with run index 28 landed (19:28:39 UTC), while the larger gate was
running; at 19:34 UTC it had 31 of 144 records, all `ok`.

Why: artifact 4 reported that the vLLM 0.27.1 base image needs a host driver
that supports CUDA 13.0, and that one host failed with CUDA `Error 804` (forward
compatibility attempted on unsupported hardware), so its endpoint was restricted
the same way (`docs/recon-a4.md`, sections 1 and 9). Ours had no restriction.

`allowedCudaVersions` is not one of the five pinned fields (`flashboot`,
`gpuTypeIds`, `networkVolumeId`, `templateId`, `workersMin`). The controller
re-read the endpoint after the update: all five pinned fields, and
`workersMax`, `idleTimeout`, `executionTimeoutMs`, `gpuCount`, `scalerType` and
`scalerValue`, were unchanged, and the live preflight against
`multilora/pins.py` is expected to still match.

The hosts in the stores so far (read while the gate was running, at 31
records):

| Store | Records | `host_id` | `driver_version` | `failure_class` |
|---|---|---|---|---|
| `data/a5/priming.jsonl` | 14 | `py4ehqx9v51fj4` | `595.91.07` | none in 14 |
| `data/a5/gate-pilot.jsonl` | 24 | `py4ehqx9v51fj4` | `595.91.07` | none in 24 |
| `data/a5/gate.jsonl`, run index 0 to 28 (before) | 29 | `vw53rwt15gpiab` | `580.178.04` | none in 29 |
| `data/a5/gate.jsonl`, run index 29 and 30 (after) | 2 | `vw53rwt15gpiab` | `580.178.04` | none in 2 |

Every record's outcome is `ok` and its `failure_class` is empty, and no record
contains a CUDA error. Each store ran on one host; the pilot and the larger gate
ran on different hosts with different drivers. Records with run index 28 or
below ran before the constraint and the rest after it. The host is not
randomized: it is whatever the platform assigns, before and after the
constraint, and the records name it. The pilot is not pooled with the larger
gate (Amendment 1), so the host change between them does not enter the
verdict. The post's Method names the constraint.

### Parameters as amended (2)

The earlier tables stay as the record. This is the table the code now runs on:

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
| `gpu_hourly_rate` | `1.1095` |
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
| `gate_instances` | `144` |
| `equivalence_margin` (derived) | `0.05` |
| `requests_per_phase` (derived) | `640` |

## Amendment 3 — replacing the instances a host fault cost the larger gate (2026-10-05)

This amendment is post-hoc. It was written after the larger gate (Amendment 1)
had finished and its result had been seen, and in response to that result. The
post will say so. Nothing above this section has been edited.

### What happened

The larger gate ran its 144 scheduled instances into `data/a5/gate.jsonl`
(commit e46e4b2). Recomputed from that store:

- Run indices 0 to 91, 92 records, all `ok`, all on host `vw53rwt15gpiab`,
  driver `580.178.04`. Four of them (run indices 0, 21, 47 and 91) read their
  compile cache cold and are excluded by the exclusion rule, which leaves 88
  usable instances.
- Run indices 92 to 143, all 52, failed with `failure_class` `health_timeout`.
  All 52 ran on one pod, `3dwlukmn7oc80p` (host `af4bf9285b23`, driver
  `570.195.03`). In every one of them the engine log has CUDA `Error 804:
  forward compatibility was attempted on non supported HW`, and the engine
  died before it served a request. Each took about 21 s from submission to
  result (median 21.2 s; the first, run index 92, 114.5 s).

`allowedCudaVersions` `["13.0"]` was in force for all 52 (set at 19:28:40 UTC,
after run index 28; Amendment 2). A constraint was set, and the scheduler still
placed the work on a host with driver `570.195.03`. No explanation beyond that
is claimed here. The runner had no stop on repeated failures, so it kept
submitting until the schedule was exhausted. The bad worker exited at 22:41:02
UTC, after the run had ended.

The verdict on the 88 usable instances is **inconclusive**:

- TTFT p50: median relative difference (synthetic minus real, over real)
  -1.16%, 90% bootstrap interval [-2.54%, +0.75%], inside ±5%. Resolution
  check (second real phase against the first): +2.24% [-0.11%, +5.81%], not
  inside ±5%, so TTFT is unresolved.
- Throughput: +0.22% [-0.35%, +0.54%], inside ±5%, and resolved: the
  resolution check gave -0.31% [-0.97%, +0.21%].

Because the TTFT resolution check failed, the rule reads inconclusive, not
fail. This interim verdict was seen before this amendment was written.

### What the failures are, and what they are not

They are an infrastructure fault: one pod, whose driver could not run the
image, failing before any request was served. They are not related to
adapters: no phase ran, so neither real nor synthetic adapters were ever
exercised. The gate is a single condition, and every instance carries both of
its regimes, so the loss removes no condition or regime selectively; it only
shortens the gate. The 52 records are failures and are reported as such:
counted in the failure table, kept in `data/a5/gate.jsonl`, never deleted.

### What changes

Only `gate_instances`, from 144 to 196. It counts scheduled instances, not
usable ones.

- Runs 0 to 143 are unchanged and stay in `data/a5/gate.jsonl`, the 52 failed
  ones included.
- Runs 144 to 195, exactly 52, are the replacements. They run with `--resume`
  into the same store. The extended schedule's first 144 entries are the stored
  ones, so resume skips them and appends only the new run indices
  (`tests/test_multilora_gate_extension.py`). Their phase orders are fresh,
  drawn from their own run indices by `phase_plan`.
- Nothing else about the gate changes: the configuration held fixed above, the
  4 real and 4 synthetic adapters, the statistic, the margin δ = 0.05, the 90%
  bootstrap interval, the resolution check and the verdict rule.

### The rule for the replacements

Exactly these 52 attempts are made. Any failures among them are recorded,
counted and not replaced again, and no further instances are added under this
amendment. The verdict is computed from all usable records in
`data/a5/gate.jsonl`: the 88 usable instances above plus the usable
replacements.

The 88-instance verdict was seen before this extension was decided. This is a
data-dependent extension toward the sample size Amendment 1 fixed in advance
(144 scheduled, about 139 usable expected). It is justified only because the
loss was a host fault that ran no measurement, not a property of anything
measured. The post reports the interim 88-instance verdict alongside the final
one.

### What to expect

If no further faults occur, and the replacements are excluded for cold compiles
at the larger gate's rate (4 in 92), about 135 to 138 instances will be usable
(88 + 52 × 88/92 ≈ 137.7).

The TTFT resolution check's interval had a half-width of about 3.0% at 88
usable instances ((5.81 + 0.11) / 2 = 2.96%). Scaled by √(88/135), that is
about 2.4%; with the median at +2.2%, the upper bound would be about 4.6%,
inside 5% but with little room. The interval is not symmetric, though: its
upper end was 3.56 points above the median at 88, and that arm scaled the same
way gives about 2.9 points, an upper bound of about 5.1%, just outside. These
are estimates. A pass is not guaranteed; the gate may again read inconclusive,
and then the August fallback applies, as Amendment 1 says.

### The guard

`scripts/a5_run.py` now stops a run after `--max-consecutive-failures`
(default 3) failed instances in a row, with exit code 3
(`multilora.cli.ConsecutiveFailureGuard`, `stop_after_consecutive_failures`).
Each record is appended to the store before the check runs, so a stop keeps
every record. It prints the run-index range of the failing streak, its failure
class, and the host and driver of the last failing record.

The operating rule: after a stop, wait at least 30 s so an idle bad worker
exits, then run again with `--resume`. A stop leaves at most 3 failed records
per incident. They are among the 52 attempts, count as attempts, and are not
replaced.

### Cost

From the larger gate's own records (`clock_A`, submission to result), an `ok`
instance took 166.4 s on average (2.77 minutes), so 52 replacements take about
52 × 166.4 s = 2.40 hours, about $2.67 at $1.1095 per GPU-hour. This is an
estimate.

### Budget, revised again

Amendment 2's total was about 17.99 GPU-hours, $19.96. Recomputed from the
records now available, all times submission to result from `clock_A`:

- Spent: priming 0.55 hours, the pilot 1.16 hours, and the larger gate 4.61
  hours (all 144 records: 92 `ok` instances 4.25 hours, 52 failed ones 0.36
  hours). Together 6.32 hours.
- Planned replacements: 52 × 166.4 s = 2.40 hours.
- Campaign: 192 instances × 166.4 s (the larger gate's mean over its `ok`
  records, in place of the pilot's 174.4 s) = 8.88 hours. No campaign instance
  has been measured; this assumes they take as long as a gate instance.
- Total: about 17.60 GPU-hours, about $19.53 at $1.1095, under the $20 cap by
  about $0.47.

These are wall times, not billed times: an idle worker kept alive after its
last job (the bad worker until 22:41:02 UTC) and any start-up the platform
bills are not in `clock_A`. The billing record is the authority on spend and
was not read for this amendment. The design amendment's §6 cut order (the
gauge control first) remains the rule if the campaign estimate exceeds the cap,
and that decision is the owner's.

### Decision

Chosen by the owner in chat on 2026-10-05, among replacing the failed
instances (chosen), applying the August fallback, or changing the decision
rule.

### Parameters as amended (3)

The earlier tables stay as the record. This is the table the code now runs on:

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
| `gpu_hourly_rate` | `1.1095` |
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
| `gate_instances` | `196` |
| `equivalence_margin` (derived) | `0.05` |
| `requests_per_phase` (derived) | `640` |

## Actual spend (read 2026-10-07)

This section is an appended record. It was written after the campaign had
finished and the billing record had been read. No value above it was changed.

The billing record is RunPod's billing API (`GET /v1/billing/endpoints`,
grouped by `endpointId`, daily buckets), read on 2026-10-07 for the period
starting 2026-10-04. The table gives the returned `amount` (USD) and
`timeBilledMs`, with billed hours as `timeBilledMs / 3.6e6`.

| date (UTC) | endpoint | USD | billed hours |
|---|---|---|---|
| 2026-10-05 | measurement `2ilkjkm9ob4qvo` (artifact5-measure) | 8.05 | 7.26 |
| 2026-10-06 | measurement `2ilkjkm9ob4qvo` (artifact5-measure) | 0.44 | 0.39 |
| 2026-10-07 | measurement `2ilkjkm9ob4qvo` (artifact5-measure) | 5.31 | 4.79 |
| 2026-10-05 | reconnaissance `hwtia288shbztb` (artifact5-recon) | 0.68 | 0.61 |

The exact returned values were: 8.04911638086196 USD and 26140290 ms
(2026-10-05), 0.4363682254916057 USD and 1421296 ms (2026-10-06),
5.312057421775535 USD and 17253097 ms (2026-10-07) for the measurement
endpoint, and 0.6816014961805195 USD and 2212514 ms (2026-10-05) for the
reconnaissance endpoint. A Python computation from those values printed:

| quantity | USD | billed hours | implied rate (USD per hour) | difference from $1.1095 |
|---|---|---|---|---|
| measurement endpoint, total | 13.80 | 12.45 | 1.1084 | -0.10% |
| reconnaissance endpoint, total | 0.68 | 0.61 | 1.1090 | -0.04% |
| grand total | 14.48 | 13.06 | 1.1084 | -0.10% |

The implied rate is total USD divided by billed hours. The registered rate is
$1.1095 per GPU-hour (Amendment 2). Unrounded: measurement 13.7975 USD over
12.4485 h, reconnaissance 0.6816 USD over 0.6146 h, grand total 14.4791 USD
over 13.0631 h. The per-day implied rates ran from 1.1053 to 1.1090.

What the figures say:

1. The grand total, $14.48, is under the $20 cap by about $5.52 ($5.5209
   unrounded).
2. It is also below the Amendment 2 estimate of about $19.96 (17.99
   GPU-hours), and below Amendment 3's revised estimate of about $19.53
   (17.60 GPU-hours), by about $5.48 and $5.05. The main reason is the campaign
   instance time. Computed from `data/a5/campaign.jsonl`, `clock_A`
   (`t_result - t_submit`) over the 191 `ok` records (of 192), an instance took
   a mean of 108.0 s of wall time (median 104.1 s). The estimates assumed 166 s
   per instance, taken from the gate (Amendment 3 used 166.4 s). The campaign
   estimate was 192 x 166.4 s = 8.88 hours, and the campaign instances took
   about 65% of that time each.
3. The figures do not include network-volume storage, which is billed
   separately and was not read, or any spend on other endpoints or other
   artifacts. They cover only the two endpoints named above.
4. The billing buckets are per endpoint per UTC day, so the spend cannot be
   split exactly between priming, the pilot gate, the larger gate, the
   replacements and the campaign. As a rough allocation by UTC day, 2026-10-05
   and 2026-10-06 correspond to everything up to the end of the gate
   replacements (the reconnaissance endpoint's spend was also billed on
   2026-10-05), which is $8.49 on the measurement endpoint, and 2026-10-07 is
   the campaign, $5.31. The campaign ran 06:50 to 12:36 UTC on 2026-10-07, and
   to the best of the record nothing else ran on the measurement endpoint that
   day. The records in `data/a5/campaign.jsonl` carry no wall-clock UTC
   timestamps (`clock_A` is a monotonic clock), so the run window and that
   claim could not be checked from the data store.
5. The billed hours (13.06 h in total) are lower than the sum of wall-clock
   times in Amendment 3's budget arithmetic (17.60 h) because billing counts
   active worker time, not queue or controller wait, and `clock_A` runs from
   submission to result.
