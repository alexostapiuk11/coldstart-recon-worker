# How Many Adapters Fit on a GPU — Harness Amendment

**Date:** 2026-09-26
**Status:** Approved 2026-09-26, after two review rounds. All six decisions in §0 signed off by the
author on 2026-09-26.
**Artifact:** 5 of 5
**Amends:** [2026-08-17 multi-LoRA serving design](2026-08-17-multi-lora-serving-design.md)
**Depends on:** [Artifact 4](2026-08-17-multi-model-serving-economics-design.md) and its
[scope amendment](2026-09-26-multi-model-serving-economics-scope.md) (hard), the
[harness extraction](../plans/2026-09-03-harness-extraction.md) (hard, new)

The August design was written before any harness existed, so it describes several components as if
artifact 5 would build them. Artifacts 1 and 2 have since built most of them. This amendment maps
every component the August design needs onto what exists, and narrows artifact 5's build scope to
what is genuinely new.

Mapping the components against vLLM's source also showed that four parts of the August design
cannot produce a supportable result as written. §3 corrects them, and §4 defines the quantities the
August design left undefined, so a plan can be written without inventing them.

**The August document stands unedited as the record of what was decided before the harness
existed.** Where the two conflict, this one governs. Everything this document does not mention is
unchanged.

A further revision is expected after artifact 4 publishes, the way artifact 2's final design
absorbed artifact 1's numbers. This amendment fixes nothing that depends on artifact 4's results.

### How each claim below was checked

| Label | Meaning |
|---|---|
| **repo** | Read in this repository on 2026-09-26 |
| **vLLM 0.27.1** | Read in the source of vLLM v0.27.1, the version artifact 1's image carries, on 2026-09-26. Source, not runtime: §6 confirms each on the image digest artifact 4 pins |
| **vLLM main** | Read on vLLM's `main` branch only. Weaker than the above |
| **estimate** | Arithmetic or judgement, not measured |

---

## 0. Decisions signed off

Each is caller-observable, changes a published claim, or changes another artifact's plan. **All six
were approved by the author on 2026-09-26.**

1. **The headline claim is reframed (§3b, §3c).** The August claim "dominated by batch
   heterogeneity, not by memory" cannot be tested as written. At the inherited request shape memory
   cannot move latency or throughput, and part of what the August design calls memory is kernel
   overhead. The claim becomes a three-way decomposition: heterogeneity cost, registered-slot cost,
   and memory reported as a capacity ceiling.
2. **Harness changes that touch artifact 1's code (§5).** Approved as two: a required condition key
   on the paired bootstrap, and the campaign-loop lift with `coldstart/driver.run_campaign` migrated
   onto it. **Revised during planning, 2026-09-26: the key change is dropped as unnecessary.**
   `bootstrap_median_ci` over per-instance differences is the same computation as the paired
   bootstrap, verified to return identical intervals on the same seed. So only the campaign-loop
   lift touches artifact 1's code, and it goes through the parity gate.
3. **Endorsing artifact 4's proposal for a shared in-container tooling plan (§2).** Artifact 4's scope
   amendment, §13 item 4, proposes one standalone harness plan for the in-container load-generation
   core, the `vllm serve` lifecycle and the single-engine sweep. **Update, 2026-09-26:** the author
   accepted artifact 4's amendment. Under it, `vllm bench serve` run in-container is the shared load
   path, artifact 4 owns the lifecycle lift, and the campaign loop is lifted with a record-builder
   callback. Artifact 5 consumes all three and builds none of them.
4. **GPU-free work may start before artifact 4 finishes (§6).** This relaxes the portfolio's
   "strictly sequential" rule for code only. No paid run happens before artifact 4's pins exist.
5. **Proposed pre-registration values (§4).** These are k = 1, round-robin assignment, 24 instances
   per point, and the constructions for the knee, the equivalence gate and tenants per GPU. The
   numbers still in brackets are fixed in `docs/experiment-a5.md` after reconnaissance and before
   any paid run.
6. **A published figure changes (§7).** Artifact 4's swap cost moves from figure 1, where its units
   do not match, to figure 4, the cost chart.

---

## 1. Harness state on 2026-09-26

**repo.** The tag `artifact-1-published` exists. The harness extraction has completed Tasks 1–3:
the capability inventory, the parity gate (`scripts/parity_check.sh`), and an empty `harness/`
package with its import-direction guard (`tests/test_harness_boundary.py`). **Tasks 4–13 have not
started.** Every reusable module below still lives in `coldstart/`, so "reuse" means reuse once the
named extraction task has moved it.

Artifact 2 has a working simulator and statistical layer in `autoscale/`. Its measurement half is
blocked at reconnaissance: `docs/recon-a2.md` records Q1 and Q2 unanswered. **No concurrent load
generator, no service-curve sweep and no validation gate exist as code.** The extraction plan's
harness README, which names a shared load generator as missing, is text inside its Task 13, not yet
a file.

### Update, 2026-10-04: the harness has landed

The paragraphs above record the state this amendment was approved against, and stay as written.
**repo**, as of `main` on 2026-10-04:

- **Harness extraction Tasks 4–13 are complete** (merged at `39c20b3`). The modules this section's
  component map lists under "harness home after extraction" now live there, with the four approved
  signature changes. Artifact 1's own code stays in `coldstart/`.
- **The shared in-container tooling has landed** (`ca9afbc`). `harness/serve.py` provides
  `served(...)`, and `harness/bench.py` provides `run_bench(...)`, with the interface agreed in §2.
  `run_bench` pins `--num-warmups 0`, `--ready-check-timeout-sec 0`, `--save-result` and
  `--save-detailed` itself, and refuses those flags in `dataset_args`.
- **Two of artifact 5's harness changes landed with it, verbatim from its plan 1:** the campaign
  loop, with `coldstart/driver.run_campaign` migrated onto it, and `submit_payload`. The same work
  added `harness.submit.PayloadStubSubmitter`, which artifact 5's stub worker now runs through instead
  of a second stub submitter. **The generic multi-sample bootstrap did not land** and stays in artifact
  5's plan 1.

Facts from artifact 2's first paid runs on this image that bear on artifact 5:

- `vllm bench serve --help` prints no flags in vLLM 0.27.1; only `--help=all` lists them.
  Reconnaissance must read the help text that way, or R4 would report every bench flag missing.
- `pandas` is not in the image, so vLLM's `custom` dataset fails. Artifact 5 uses `random`, as
  planned.
- The engine's `non-default args:` log line states `max_num_seqs`, a direct reading for R5.
- On Qwen3-8B, engine startup measured 84.5 s cold and 30.6 s warm, and teardown 0.5 s. The first
  job on a new endpoint waited 743 s for the image pull. These are a starting point for R8 and the
  budget, not a substitute for them.

---

## 2. Component map

### Reused, no new code

| Capability the August design needs | Existing component (**repo**) | Harness home after extraction |
|---|---|---|
| TTFT percentiles, sample floors, bootstrap intervals | `coldstart/analysis/stats.py` | `harness/stats.py` (Task 4). The paired bootstrap needs one change, below |
| Append-only record storage | `coldstart/store.py` | `harness/store.py`, record class injected (Task 8) |
| Randomized order of sweep points and phases | `coldstart/scheduler.py` | `harness/scheduler.py`, `build_schedule(conditions, blocks, seed)` (Task 9) |
| Publishability gate; failure rates per condition | `coldstart/analysis/pipeline.py` | `harness/publish.py`, `failure_rate_by_group(rows, key)` (Task 10) |
| **KV capacity at each sweep point** | `coldstart/vllm_logs.py` reads `GPU KV cache size: N tokens` | `harness/vllm_logs.py` (Task 5). See §3d for the compile-cache confound this reading carries |
| Framework version per run | Same parser | Same |
| Engine and platform failure classification | `FailureClass` in `coldstart/checks.py` | `harness/failures.py` (Task 7) |
| Server-start timing | `coldstart/recorder.py` | `harness/recorder.py` (Task 6) |
| RunPod submission, lifecycle extraction, endpoint preflight | `coldstart/runpod_*.py`, `coldstart/preflight.py` | `harness/runpod/` (Task 12). Artifact 5 supplies its own pin set |
| In-process submitter stub | `StubSubmitter` in `coldstart/submitter.py` | `harness/submit.py` (Task 12) |
| Figure constraints: N stated, empty input refused, no dropped series, phone legibility | Guards in `coldstart/analysis/figures.py` | `harness/figure_guards.py` (Task 11) |
| Pinned vLLM image, CI build, digest pinning | `worker/Dockerfile`, `.github/workflows/build-worker.yml` | Stays. Artifact 5 adds its handler and a `COPY multilora` line |
| Published figures re-derive from committed data | `tests/test_published_figures.py`, `scripts/parity_check.sh` | Pattern reused with artifact 5's figure list |
| Pre-publish gate, including the employer-boundary check | Artifact 1 spec §8 | A checklist. Nothing to build |

**KV capacity is the largest reduction.** It is a line vLLM prints at every startup, and the parser
already reads it.

### Reused with a change

- **The paired bootstrap, reused without a change.** `bootstrap_paired_median_diff` reads each unit's
  conditions from `row["arm"]`. **repo.** But the computation it performs is a median-interval
  bootstrap over one difference per unit, and `bootstrap_median_ci` over per-instance differences
  returns identical intervals on the same seed (verified 2026-09-26). Artifact 5 computes one
  difference per instance and calls `bootstrap_median_ci`. Artifact 1's statistics are untouched.
- **Two additive harness functions, no caller changes.** A generic multi-sample bootstrap in
  `harness/stats.py`, for the difference in differences of §3b and the knee's ratio in §4. A
  `submit_payload` method on the RunPod submitter, because `submit(arm, run_id)` hard-codes artifact
  1's payload.
- **The image boundary test.** `tests/test_harness_boundary.py` hard-codes
  `FIRST_PARTY = {"coldstart", "harness", "worker", "recon"}`, so a missing `COPY multilora` would
  pass. **repo.** Artifact 5 adds `multilora` to that set. The CI paths filter check then covers it.
- **The reconnaissance capture script, not reused.** `recon/capture.py` writes to fixed paths that existing tests parse, and always sends the payload `{"recon": True}`. **repo.** Revised during planning, 2026-09-26: rather than give artifact 1's script new options, artifact 5 writes its own capture script over the harness's `submit_payload`. That reuses the retrying transport the harness already has, and leaves artifact 1's script exactly as it was.

### The load path

**vLLM 0.27.1.** `vllm bench serve` ships in the image. It supports `--lora-modules` with
`--lora-assignment random|round-robin`, `--max-concurrency`, `--ignore-eos`, and `--save-detailed`,
which requires `--save-result`.

**Decision, updated 2026-09-26 after artifact 4's amendment was accepted:** `vllm bench serve`, run
in-container, is the shared load path, wrapped by the standalone harness tooling plan. Artifact 5
consumes that wrapper and does not build one. Artifact 5's five requirements on it are a
per-request model name from a given list, round-robin assignment, fixed concurrency, ignore-EOS, and
the tool's raw per-request `ttfts`, `output_lens` and `errors` returned unaltered, with the phase
duration and the tool's `completed` and `failed` counts.

Artifact 5 stores those raw arrays and applies §3f's rules itself, so the shared wrapper needs no
artifact 5 logic. Sign-off is item 3 of §0.

**Interface agreed with artifact 4's session, 2026-09-26.** The shared tooling plan provides
`harness.serve.served(model, *, args, env, port=8000, health_timeout=900.0)`, a context manager
yielding `.base_url`, `.log_lines` and `.healthy`, and `harness.bench.run_bench(base_url, *, model,
lora_modules, lora_assignment, max_concurrency, num_prompts, dataset_args, ignore_eos, seed,
result_dir)`, returning the tool's saved JSON unaltered. Artifact 5 calls both only from
`multilora/serving.py`. Artifact 4's results arrive at `data/a4/cost_per_tenant.json`, as a grid of
rows with a pre-registered `reference` row; artifact 5's cost table reads that row.

### Lifted into the harness by whichever plan reaches it first

Artifact 4's scope amendment agrees with both lifts and the same ownership rule (its §1d and §11).

- **The `vllm serve` lifecycle.** **repo.** It exists in `worker/probe.py` and in
  `worker/recon_handler.py`. `probe.run_probe` is one function that starts the server, runs artifact
  1's warm-up trio and terminates. It has no point where other load could run, and it imports
  `coldstart.analysis.metrics`. The lift is a harness context manager that starts the server, yields
  the running server and its log lines, and terminates on exit. It belongs to the shared tooling plan
  endorsed above. `worker/probe.py` stays as artifact 1's frozen measured path, reproducible at the
  `artifact-1-published` tag, and is not migrated.
- **The campaign loop.** **repo.** Schedule, submit, record and store with a resume guard is
  `coldstart/driver.run_campaign`, which the extraction left in `coldstart/` because "nothing needs
  it yet". Artifacts 4 and 5 both need it now. The lift takes a record-builder callback. **Unlike the
  probe, `run_campaign` migrates onto it**, because it is orchestration rather than the measured path,
  and `tests/test_driver.py`, `tests/test_end_to_end.py` and the parity gate cover it. If the
  migration does not pass all three, it is reverted and the duplicate is recorded.

### Genuinely new

| Component | Why nothing existing covers it |
|---|---|
| Synthetic adapter writer | PEFT-format directories at the fixed rank and target modules, seeded random weights at a fixed initialisation scale, generated in the container at job start with a checksum recorded |
| Real-adapter acquisition | The equivalence gate needs public adapters for the exact base revision. Their ids and revisions are pinned in `docs/experiment-a5.md` |
| Artifact 5 worker handler | Runs one instance's full phase sequence (§4) through the lifted lifecycle |
| Active-adapter sampler | Polls `/metrics` during load (§3a) |
| Cache configuration | Artifact 1's volume env mapping is in `coldstart/cache_config.py`, which artifact 5 does not import. A few lines |
| Compile-cache priming script | One cold start per `max_loras` value before the campaign (§3d). Artifact 1's `scripts/prime_compile_cache.py` is the pattern, not an import |
| GPU-free stub | Emits fake load-generator output and startup logs. Artifact 1's stubs replay its own logs and stay in `coldstart/` |
| Record class, pin set, runner script | The shape of one instance's result, and the script a reader runs |
| Analysis | Per-instance estimands, the paired decomposition, the knee, the equivalence test |
| Cost per tenant and the three-way table | Consumes artifact 4's committed output for the dedicated and swapped columns |
| The four figures and a published-figures test | The charts are new. The guards are not |
| `docs/experiment-a5.md` | The pre-registration, committed before the first paid run. Artifact 4 creates `experiment-a4.md` the same way |

### Deliberately not reused

- **Artifact 1's explainer pipeline.** The August design asks for a post, not an explainer.
- **Artifact 1's economics module.** It stays in `coldstart/`. Artifact 4's scope amendment defines
  its own assumptions record with the GPU hourly rate. **Artifact 5 takes the rate from artifact 4's
  committed assumptions**, so all three columns of the cost table share one rate. Artifact 1's
  published rate is labelled illustrative and is not used.
- **Artifact 2's interval-band drawing**, which is written around artifact 2's frontiers.

---

## 3. Design corrections

### 3a. "Registered" means a GPU slot

**vLLM 0.27.1:**

- `max_loras` is documented as "Max number of LoRAs in a single batch" and is also the number of GPU
  slots. Weight buffers are allocated per slot, sized to `max_lora_rank`, whether or not an adapter
  occupies the slot.
- `max_cpu_loras` is the number held in CPU memory. It defaults to `max_loras` and must be at least
  that large. Adapters beyond `max_loras` are copied into a slot on demand, which is the
  resident-versus-swapped mode the August design places out of scope.

**Consequences.**

1. **At each sweep point, `max_loras = max_cpu_loras = N`,** and `max_lora_rank` equals the fixed
   adapter rank. A larger `max_lora_rank` would allocate and compute over rank that is never used.
2. **The August evidence for its distinction is withdrawn.** It argued that a separate in-batch cap
   shows the cost lives in the distinction. In vLLM the cap and the resident count are one knob. The
   registered/active distinction is still real, and the regimes still separate it.
3. **Tenants per GPU becomes a lower bound.** vLLM's intended multi-tenant mode holds many more
   adapters on the CPU than in slots. This design measures only the all-resident case, so the
   adapter column of the cost table is labelled a lower bound on tenants per GPU.
4. **The manipulation check changes form.** **vLLM 0.27.1:** the closest observable is the gauge
   `vllm:lora_requests_info`. Its `running_lora_adapters` label lists the scheduler's running set as
   a comma-joined string, and each update is stamped with the current time. The Prometheus client
   keeps every label combination it has seen, so the sampler reads the series with the newest
   timestamp, at a pre-registered interval. It is published as a sample of scheduler state, not a
   count per batch.
5. **That gauge has a cost that differs by regime.** **vLLM 0.27.1:** it creates a new label series
   on every stats record, whether or not anyone scrapes. The concentrated regime produces a handful
   of combinations. The spread regime produces a new one almost every step, so the registry and the
   `/metrics` payload grow inside the API-server process being measured. That overhead does **not**
   cancel in the subtraction. It lands in the heterogeneity cost, and series left by a spread phase
   persist into the next phase. It is vLLM's default behaviour, so it is also what a deployment pays.
   **Handling:** the per-instance phase order is randomized, so carry-over is spread across both
   regimes. Its size is bounded by control instances at N = 64 started with `--disable-log-stats`,
   which disables the gauge (§4). The post reports it as a default-configuration cost, separate from
   the kernel.

### 3b. The concentrated regime also pays a kernel cost that grows with N

**vLLM 0.27.1.** With the default `specialize_active_lora = False`, one dimension of the LoRA
kernels' launch grid is `max_loras + 1`, whatever the number of adapters actually in the batch.
Slices for empty slots exit early but are still launched. At N = 64, a concentrated batch that uses
one adapter launches 65 slices per LoRA operation, against 2 at N = 1.

**A second N-dependent path:** with tuned kernel configurations, tile choice is keyed on `max_loras`.
`VLLM_TUNED_CONFIG_FOLDER` is pinned unset in the endpoint environment so that path stays closed.

So the concentrated regime's change with N is **not memory alone**. It is memory plus a
slot-proportional kernel overhead. The August subtraction attributes all of it to memory.

**Correction.** The concentrated-regime effect is named the **registered-slot cost**. The post never
calls it memory.

**Diagnostic.** `specialize_active_lora = True` captures graphs for powers of two up to
`max_loras`, so a concentrated batch launches one or two slices at every N. The concentrated regime
is re-run with it at N ∈ {1, 16, 64}. The flag also changes which graphs are dispatched, so the two
settings differ even at N = 1. The slot-proportional overhead is therefore a difference in
differences, computed from unpaired instances:

> [concentrated, default (N) − concentrated, default (1)] − [concentrated, specialized (N) −
> concentrated, specialized (1)]

What remains of the registered-slot cost is named **other slot-count cost**, such as host-side LoRA
bookkeeping, and is expected near zero. It is not memory: §3c shows memory cannot move latency at
this shape.

**vLLM 0.27.1:** the flag defaults to off, depends on `cudagraph_specialize_lora`, which defaults to
on, and is not in the compile-cache hash, so the per-N priming covers it. Graphs are not cached, so
startup captures up to eight extra sets at N = 64. R9 measures that cost. The diagnostic is the first
thing cut if budget binds; the post then reports the registered-slot cost unsplit.

The earlier draft of this amendment described the flag backwards: it removes a registered-side
cost, not a heterogeneity cost.

### 3c. At the inherited request shape, memory cannot move latency or throughput

**estimate**, from Qwen3-4B's configuration: KV is 144 KiB per token. One rank-16 adapter over all
seven linear projections is about 63 MiB, so 64 slots take about 3.9 GiB, roughly 28,000 tokens of
KV. A request at the inherited shape is about 30 tokens, so 64 concurrent requests need about 2,000.
**KV never binds, at any N.** A memory effect on TTFT or throughput at fixed concurrency is therefore
zero by construction. The slot figures assume r = 16. Slot memory scales with r: at r = 64, 64 slots
would need about 15.8 GiB, which does not fit beside 7.5 GiB of weights, so r and the top of the
sweep are fixed together after R2. That is the same class of problem as artifact 2's degenerate regime
(`docs/findings-a2-degenerate-regime.md`).

**Correction.** Memory is reported as what it actually changes: **capacity**. At each N, KV tokens are
converted to the maximum concurrent requests supportable, at the inherited shape and at a
pre-registered production context length. That feeds tenants per GPU directly. The post states that
at this request shape memory does not bind, and why.

**The claim becomes:** at fixed concurrency, the throughput and TTFT change with N decomposes into a
heterogeneity cost and a registered-slot cost. Memory's effect is a capacity ceiling, reported
separately. Whether heterogeneity dominates is still the question, now asked of quantities that can
answer it. Sign-off is item 1 of §0.

### 3d. The compile cache is keyed on `max_loras`

**vLLM 0.27.1.** The LoRA configuration hash includes `max_loras`, `max_lora_rank` and the target
modules. The engine configuration hash includes that hash, and the torch.compile cache directory is
keyed on it. **Each of the seven N values compiles separately.**

**Why it matters.** **repo:** `fixtures/README.md` records a cold compile inflating peak activation
from 0.19 to 1.18 GiB and cutting KV capacity from 43,040 to 35,792 tokens. That is about the size of
the whole slot-buffer effect at N = 16. An instance that compiled cold would put a spurious step into
the KV figure.

**Correction.**

- Before the campaign, the priming script starts the server once per N value against the network
  volume, the way artifact 1 primed arm C. Priming runs go to a separate store and are never data.
- Every instance is classified warm or cold **from its own startup log**, not from the cache
  directory. **repo:** artifact 1's handler checks only that `torch_compile_cache/` exists, and its
  docstring says that cannot tell this configuration's cache from another's. With seven per-N hash
  directories under one root, it would read warm for every N after the first priming run.
- **The rule** reuses artifact 1's priming criterion from `docs/experiment.md`: an instance is warm
  if the parser's `S4b`, the `torch.compile took … s in total` line, is under one second. The log's
  "Using cache directory" path, which carries the hash, is recorded as well.
- An instance classified cold is excluded, as artifact 1's arm-state gate excludes a mislabelled
  arm.

**Restart cost is not known yet.** The earlier draft cited artifact 1's warm-cache cold start, a p50
of 39.4 s. That was end-to-end serverless time for Qwen3-8B without LoRA, platform included, and it
does not transfer. §6 measures the in-container restart for the actual configuration.

### 3e. Offered concurrency and assignment together cap the spread regime

A batch cannot hold more distinct adapters than there are requests in flight, so at concurrency C
the spread regime reaches at most C active adapters.

**Random assignment reaches fewer.** **estimate:** the expected distinct adapters among C requests
drawn uniformly from N is N(1 − (1 − 1/N)^C).

| N | C | Expected distinct, random | Round-robin |
|---|---|---|---|
| 64 | 64 | 40.6 | 64 |
| 32 | 64 | 27.8 | 32 |
| 64 | 256 | 62.9 | 64 |

**Correction.** Assignment is **round-robin**, which keeps roughly min(N, C) distinct adapters in
flight. Offered concurrency C is at least the top of the sweep. If reconnaissance shows `max_num_seqs`
cannot support that, the top of the sweep is lowered to C and the post says why. Points above C
would still measure the registered-slot cost, but not further heterogeneity.

### 3f. Reading `vllm bench serve` output

**vLLM 0.27.1:**

- `--save-detailed` saves per-request `ttfts`, `itls`, `start_times`, `output_lens` and `errors`.
- It saves no per-request end-to-end latency and no per-request adapter id.
- A failed request stays in `ttfts` with the value 0.0.

**Rules.**

- A request is a failure, removed before any statistic and counted, if its `errors` entry is
  non-empty, **or** its TTFT is 0.0, **or** its output length is 0. **vLLM 0.27.1:** some failure
  paths record an empty error string, and no per-request success flag is saved. The per-phase failure
  count is cross-checked against the tool's own `completed` and `failed` counts, and a mismatch fails
  the phase.
- Throughput is the sum of successful `output_lens` divided by the phase duration the tool reports.
- The tool's summary means and standard deviations are never used. Artifact 1's rule is that a mean
  is never published for right-skewed data.
- The tool's built-in warm-up and ready-check requests target the base model, not the adapters. Both
  default to off in 0.27.1 and are pinned off explicitly with `--num-warmups 0` and
  `--ready-check-timeout-sec 0`. The handler warms the
  adapters itself (§4) and has already waited on `/health` through the lifecycle.

### 3g. Output length and carry-over between phases

- **Output length.** Random weights and different real adapters generate different text. Under the
  inherited `max_tokens = 16` without `--ignore-eos`, outputs can stop early, and lengths differ by
  regime and by adapter set. That would confound both the heterogeneity cost and the equivalence
  gate. **Every phase runs with `--ignore-eos`**, and `output_lens` is recorded and checked.
- **Prefix cache.** An identical prompt creates one prefix-cache entry per adapter, so a spread phase
  after a concentrated one would pay cold prefixes the other did not. **Prefix caching is disabled**,
  and an untimed warm-up touches every registered adapter before the first timed phase.
- **Client contention.** The load client runs in the same container as the server. The container's
  vCPU count is recorded per instance.

---

## 4. Measurement protocol

This section defines everything the August design left for a plan-writer to invent. Values in
brackets are fixed in `docs/experiment-a5.md` after reconnaissance, before any paid run.

### One instance

One server start at one N, with `max_loras = max_cpu_loras = N`, `max_lora_rank = r`, prefix caching
off, and the compile cache primed.

1. Record the startup log: KV tokens, version, `S4b`, the cache directory path.
2. Untimed warm-up: every registered adapter receives [w] requests.
3. Four timed phases, two concentrated and two spread, in an order the scheduler randomizes per
   instance. Each phase uses round-robin assignment, concurrency C, ignore-EOS, and at least
   max(80, 10 × C) requests. 80 is the p95 sample floor.
4. The active-adapter sampler runs throughout every phase.
5. Terminate, and record every serve argument.

**Concentrated** lists k = 1 adapter; **spread** lists all N. At N = 1 the two regimes coincide, so
the heterogeneity cost is zero there by construction, and that is stated rather than measured.

**What varies, and at what level.**

| Level | Varies |
|---|---|
| Per phase | The adapter list the load generator assigns from |
| Per job | `max_loras`, `max_cpu_loras`, the registered adapter set, and for the diagnostic and control instances `specialize_active_lora` and `--disable-log-stats` |
| Fixed in the endpoint environment | Model, revision, `max_lora_rank`, target modules, `max_model_len`, prefix caching off, `gpu_memory_utilization`, `VLLM_TUNED_CONFIG_FOLDER` unset |

This follows artifact 1's rule that anything not under study is fixed in the environment rather than
passed per job (**repo**, `worker/handler.py`).

### Blocks, jobs and instance counts

- **Instances per condition: 24.** The bootstrap floor (`MIN_BOOTSTRAP_SAMPLES`) is 20, and the four
  extra absorb cold-compile exclusions and failed instances. If a condition still falls below 20,
  top-up instances are scheduled before any analysis, and the post discloses them.
- **Conditions:** the seven sweep points; the gate; the diagnostic at N ∈ {1, 16, 64}; and the
  control at N = 64 with `--disable-log-stats` (§3a).
- A block is one pass over the sweep's seven N values in scheduler-randomized order.
- A job runs consecutive instances from the schedule, as many as fit inside the endpoint's 1800 s
  execution timeout (**repo**, `docs/runbook.md`).
- `host_id` is recorded per instance. Comparisons across N are between instances and unpaired. If
  every instance lands on one host, as all of artifact 1's runs did, that is stated as circumstance,
  not design.

### Estimands

- **Within an instance, per regime:** TTFT p50 and p95 over the successful requests of both of that
  regime's phases, and throughput as total successful output tokens over total phase duration.
- **Heterogeneity cost at N:** spread minus concentrated, paired within each instance. The interval is
  the paired bootstrap over instances.
- **Registered-slot cost at N:** concentrated at N minus concentrated at N = 1. The interval is an
  unpaired bootstrap over instances.
- **Slot-proportional overhead:** the difference in differences of §3b.
- **Gauge overhead:** the heterogeneity cost at N = 64 with default stats minus with
  `--disable-log-stats`, unpaired.
- **Memory:** KV tokens at N, converted to maximum concurrency (§3c).
- Every reported point is a median across instances, with the instance count stated.

### The knee

The August design requires a knee threshold stated in advance but defines neither the curve nor the
rule.

- **Curve:** spread-regime throughput T(N).
- **Marginal cost of a doubling:** m(N) = 1 − T(N) / T(N/2), a ratio, so it does not depend on
  absolute throughput.
- **Knee:** the smallest N whose point estimate m(N) exceeds the threshold τ. It is reported as the
  interval (N/2, N], because the sweep resolves only doublings. If no point exceeds τ, the knee is
  reported as above 64.
- **Why the point estimate and not a significance rule:** requiring the interval to clear τ would
  miss a real but noisy drop and push the knee, and so tenants per GPU, upward. The point-estimate
  rule errs toward fewer tenants.
- **Resolution, reported alongside:** for each doubling, whether the unpaired bootstrap lower bound
  of m(N) also exceeds τ. Six doublings are examined. Resolution is descriptive, so no multiplicity
  correction is applied, and the post says so.
- τ is set in `docs/experiment-a5.md`.

### Tenants per GPU

The August design converts adapters to tenants without a rule. This is the rule, and each input is
pre-registered.

- **By slots:** N/2 at the knee, the last point below τ. It is a lower bound (§3a).
- **By throughput:** at that N, measured request throughput divided by one tenant's peak request
  rate. The peak rate is requests per tenant per month, divided by the seconds in a month, times a
  peak-to-average factor. It holds only if TTFT p95 at concurrency C meets the SLO. If it does not,
  the point is reported as infeasible at C.
- **By memory:** the KV concurrency ceiling. At the inherited shape it exceeds `max_num_seqs` at
  every N, so it does not bind. The post states that.
- **Tenants per GPU** is the smallest of the three. That value feeds cost per tenant per month.

### The equivalence gate

The August design derives the tolerance "same construction as artifact 2's validation". **repo:**
that construction is a trajectory band from three repeats (artifact 2's final design, §10). It does
not map onto a scalar comparison, and it exists only as prose. The construction here replaces it.

- **Configuration:** G real public adapters and G synthetic adapters, at the same `max_lora_rank`
  and target-module set, so 2G slots are registered. Concurrency is the sweep's C. **vLLM 0.27.1:**
  the kernel runs at the buffer rank, so matched means the same buffers, and each real adapter's
  rank is at most r.
- **Instances:** 24. Each runs four spread phases: two over the real set, two over the synthetic
  set, in randomized order.
- **Statistic:** per instance, the relative difference (synthetic − real) / real, each side
  aggregated over its two phases. This is computed for TTFT p50 and for throughput.
- **Margin δ = τ / 2.** A synthetic bias smaller than half the knee threshold cannot move the knee
  by itself. That ties the margin to what the post reports. The earlier draft took δ from per-instance
  spread, which is on the wrong scale for a median's interval and would have made the gate nearly
  impossible to fail.
- **Pass:** the 90% bootstrap interval of the median statistic lies inside ±δ for both metrics. That
  is a two one-sided test at the 5% level.
- **Resolution check:** the same statistic for the first real phase against the second must also have
  its 90% interval inside ±δ. It uses single phases, which are noisier than the gate's two-phase
  aggregates, so the check is conservative. If it fails, the gate cannot resolve δ, and it is
  reported as **inconclusive**, not passed.
- **Fail or inconclusive:** the August fallback applies unchanged.

---

## 5. Build scope

**Shared changes, each built once in the harness.**

| Change | Where | Built by |
|---|---|---|
| The campaign loop with a record-builder callback; `run_campaign` migrated onto it, through the parity gate | `harness/campaign.py`, `coldstart/driver.py` | **Landed 2026-10-04** with the shared tooling, verbatim from artifact 5's plan 1 |
| A generic multi-sample bootstrap | `harness/stats.py` | Artifact 5, additive |
| `submit_payload` on the RunPod submitter, and a payload stub | `harness/runpod/submitter.py`, `harness/submit.py` | **Landed 2026-10-04** with the shared tooling |
| The `vllm serve` lifecycle and the in-container `vllm bench serve` wrapper | `harness/serve.py`, `harness/bench.py` | **Landed 2026-10-04**, the standalone harness tooling plan |
| `multilora` added to `FIRST_PARTY` | `tests/test_harness_boundary.py` | Artifact 5 |
| Nothing: `recon/capture.py` stays unchanged. Revised during planning, 2026-09-26: artifact 5's own capture script submits through `submit_payload`, reusing the harness's retrying transport | `scripts/a5_recon_capture.py` | Artifact 5 |

**Artifact 5 builds, in `multilora/`:** the synthetic adapter writer, real-adapter acquisition, the
worker handler with its sampler, the cache configuration, the priming script, the GPU-free stub, the
record class, pin set and runner, the analysis, the cost table, the four figures with their test, a
reconnaissance handler, and `docs/experiment-a5.md`. It applies §3f's output rules to the raw arrays
the shared wrapper returns.

**Artifact 5 does not build:** statistics, storage, scheduling, the publishability gate, the
engine-log parser, the failure taxonomy, the stage recorder, the RunPod client or preflight, the
image build, the figure guards, the serve lifecycle, or a load generator.

**Package boundary.** `multilora/` imports `harness/` and never `coldstart/` or `autoscale/`. A test
enforces it by parsing imports, the way `tests/test_autoscale_boundary.py` does.

---

## 6. Sequencing and reconnaissance

### Prerequisites

1. **Harness extraction Tasks 4–12 complete**, with the parity gate passing after each. **Met
   2026-10-04.**
2. **Artifact 4 fixes the base model, GPU class and vLLM image.** Artifact 4's scope amendment finds
   that Qwen3 has no 3B checkpoint and proposes Qwen3-4B on the same 24 GB card, with Qwen3-1.7B as
   the fallback. The estimates in §3c assume Qwen3-4B.
3. **The shared changes in §5**, each by whichever plan reaches it first. Paid measurement needs the
   lifecycle and a load path; GPU-free work needs neither. **Met 2026-10-04**, except the generic
   bootstrap, which artifact 5's plan 1 adds.

After step 1, GPU-free work may start before steps 2 and 3 finish: the adapter writer, the record
class, the analysis and the figures, all against the stub. No paid run happens before step 2. That
relaxation needs sign-off, item 4 of §0.

### Reconnaissance

A capture-only run on the image digest artifact 4 pins. The August questions are labelled R1–R3.
Most answers are already known from vLLM 0.27.1 source, so reconnaissance **confirms on the image**
rather than discovers.

| # | Question | Known from 0.27.1 source | Why it matters |
|---|---|---|---|
| R1 | The in-batch cap | It is `max_loras` (§3a) | The sweep sets it per point |
| R2 | The ceiling on registered count at one rank | No | Sets the top of the sweep |
| R3 | Synthetic adapters load and serve | No | August's go/no-go |
| R4 | The load path works with LoRA: the shared generator if it has landed, otherwise `vllm bench serve` behaving as §3f describes | The tool's flags, yes | The load path |
| R5 | `max_num_seqs` allows C at the top of the sweep | No | §3e |
| R6 | The startup log still prints KV tokens with LoRA enabled, after slot buffers are allocated | Buffers are allocated at model load, before profiling | KV capacity for free |
| R7 | The LoRA gauge is exported, and how fast its series grow under the spread regime | Exported, yes; growth, no | §3a |
| R8 | In-container restart time with a primed cache, per N | Separate compile per N is known (§3d); the time is not | Budget |
| R9 | `specialize_active_lora` present, and what the diagnostic costs at startup | Present, default off | §3b |
| R10 | At least G public adapters exist for the chosen architecture, at rank ≤ r, targeting a subset of the fixed modules. Adapters trained on any checkpoint with the identical architecture and shapes qualify, such as a Base or Instruct variant, because serving cost depends on shape (§4) | No | The equivalence gate |

R4 and R6 decide scope, not viability. A "no" moves work back into artifact 5's build list.

### Budget

**estimate.**

| Condition | Instances |
|---|---|
| Sweep, 7 points × 24 | 168 |
| Equivalence gate | 24 |
| Diagnostic, 3 points × 24 | 72 |
| Gauge control at N = 64 | 24 |
| Priming, one per N | 7 |
| **Total** | **295** |

- **Duration:** at 3–5 minutes per instance, roughly 15–25 GPU-hours.
- **Cost:** about $15–25 at artifact 1's illustrative $1.0/h. The August estimate was $10–20, so the
  upper end exceeds it. The rate artifact 4 records replaces the illustrative one.

R8 turns this estimate into a computation before the pre-registration is committed. If it does not
fit, cuts come in this order: the gauge control, the diagnostic, then sweep resolution. The second
regime is never cut, as the August design requires. Without the control and the diagnostic, the
post reports the registered-slot cost unsplit and the gauge overhead unbounded, and says so.

---

## 7. August text this amendment supersedes

- §2's claim and §6's "heterogeneity cost" definition: reframed by §3b and §3c.
- §2's argument that a separate in-batch cap is evidence: withdrawn by §3a.
- §4 "Recorded per run: in-batch adapter cap": the cap equals N by construction. "Distinct adapters
  observed per batch" becomes the gauge sample of §3a.
- §5's tolerance "same construction as artifact 2's validation": replaced by §4's gate.
- §9 threat 1 and §10's limit "in-batch cap bounding the spread regime": replaced by the concurrency
  cap of §3e.
- §11's budget: replaced by §6's estimate, pending R8.
- §12b module 2, "rank changes compute": in vLLM, compute runs at `max_lora_rank`. Rank still
  changes buffer size and compute, but through the configured maximum, not the adapter.
- §10 figure 1 draws artifact 4's swap cost, in seconds, as a reference line on a TTFT and
  throughput chart. The units do not match. **The reference line moves to figure 4**, the cost
  chart, where both are in money. This is an August issue. Sign-off is item 6 of §0.

---

## 8. Definition of done — additions

Added to the August list. Nothing is removed from it.

- The six sign-offs in §0 recorded.
- Harness extraction Tasks 4–12 and §5's harness changes complete. No module in `multilora/` imports
  `coldstart/` or `autoscale/`, enforced by a test.
- `docs/experiment-a5.md` committed before the first paid run. It fixes C, G, r, the target
  modules, [w], the scrape interval, τ and so δ, the production context length, the real adapter ids
  and revisions, the SLO, requests per tenant per month, and the peak-to-average factor.
- The compile cache primed per N; every instance classified warm or cold from its startup log;
  cold instances excluded; every condition at 20 or more instances after exclusions.
- Every instance run as §4 describes, with ignore-EOS, prefix caching off, round-robin assignment,
  and `VLLM_TUNED_CONFIG_FOLDER` unset.
- The gauge overhead reported from the control, or declared unbounded if the control was cut.
- None of `vllm bench serve`'s summary statistics in the post, and failures removed by §3f's rule
  before any statistic.
- The concentrated-regime effect published as the registered-slot cost, never as memory. Memory
  published as a capacity ceiling, with the statement that it does not bind at this request shape.
- The adapter column of the cost table labelled a lower bound on tenants per GPU.
- R1–R10 answered, with their captures committed under `fixtures/a5/`.

---

## 9. Risks — additions

| Risk | Handling |
|---|---|
| Harness extraction slips | Artifact 5 waits. Building against `coldstart/` first is the rework this amendment removes |
| The shared tooling plan slips | Artifact 5's paid work waits for it. Its GPU-free work does not. Artifact 5 does not build a second lifecycle or wrapper |
| The gauge overhead is large | A finding about vLLM's default metrics under multi-adapter load. The heterogeneity cost is then reported both with and without it |
| No public adapters exist for the base revision (R10) | The gate cannot run as designed. The post reports the mechanism argument without the empirical check, and says so. That is weaker than the August design and needs a decision at the time |
| The slot-proportional overhead dominates the concentrated regime | A finding about the default kernel configuration, publishable as such, with the diagnostic as evidence |
| Restart time makes the budget exceed $20 | The cut order in §6: the gauge control, the diagnostic, then sweep resolution, never the second regime |
