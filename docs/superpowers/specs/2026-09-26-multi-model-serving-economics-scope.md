# Dedicate, Swap, or Share — Scope Amendment

**Date:** 2026-09-26
**Status:** Approved 2026-09-26. The owner accepted all twelve recommendations in §13.
**Artifact:** 4 of 5
**Amends:** [2026-08-17 multi-model serving economics design](2026-08-17-multi-model-serving-economics-design.md)
**Depends on:** [Artifact 1](2026-08-17-cold-start-decomposition-design.md), **complete and tagged**
(`artifact-1-published`); [Artifact 2 final design](2026-09-04-autoscaling-signal-comparison-final.md),
**in progress** — §2 names which parts of it this artifact actually needs.
**Coordinates with:** [Artifact 5 harness amendment](2026-09-26-multi-lora-serving-harness-amendment.md),
written in parallel — see §11.

The August design was written before any harness existed. It describes reuse in general terms
("artifact 2's simulator already models a fleet", "same gate structure as artifact 2") against code
that had not been written. Much of that code now exists, some of it does not, and some of what
exists does not fit. This amendment reconciles the design with the repository as it stands on
2026-09-26, so that no implementation plan re-builds a component that is already built, and no plan
assumes a component fits when it does not.

**The August document stands unedited as the record of what was decided before the harness
existed**, following the convention artifact 2's final design set. Where the two conflict, this one
governs. Everything it does not mention is unchanged: the claim, the three strategies, the two
traffic axes, the metrics, the four figures, the post structure, and the learning guide except
where §5 corrects it.

### How each claim is labelled

| Label | Meaning |
|---|---|
| **repo** | Checked by reading the named file in this repository |
| **HF** | Checked against the Hugging Face model API or the checkpoint's `config.json`, 2026-09-26 |
| **estimate** | Arithmetic from stated inputs. Not measured |
| **unverified** | Plausible, not checked. Assigned to reconnaissance or to the implementation plan |

This amendment went through two review rounds against the code and the governing documents. The
first found claimed reuse that does not fit, an undefined cost axis, and several factual errors.
The second found a sizing rule that decided the high-skew result by construction, a zero-width
crossover interval, and cross-document errors. This version incorporates both rounds.

---

## 1. Inventory: what exists, and what artifact 4 does with it

### 1a. Reused as-is — not in artifact 4's build scope

| Component | Lives in today | Artifact 4 uses it for |
|---|---|---|
| Discrete-event queue with deterministic tiebreak | `autoscale/events.py` **repo** — imports nothing first-party | The spine of the placement simulator |
| Service-curve type: linear interpolation, `measured` flag, finite and range guards | `autoscale/service.py` **repo** — imports nothing first-party | The **solo** curve and the **solo-at-split** curve. Not the co-located case, which depends on two loads (§1e, §7) |
| Percentiles, medians, bootstrap intervals, sample floors | `coldstart/analysis/stats.py`, moving to `harness/stats.py` in extraction task 4 **repo** | Every interval and every p99. **Never a third copy** |
| Paired bootstrap on per-repetition differences | `bootstrap_paired_median_diff`, `coldstart/analysis/stats.py:399` **repo**, same move | Every strategy-versus-strategy difference, paired by repetition (§8) |
| Engine-log parser: S4 sub-phase durations, `GPU KV cache size: N tokens` | `coldstart/vllm_logs.py`, moving to `harness/` in task 5 **repo** | Reading KV capacity at the split, and reading compile time `S4b` per swap-in (§5) |
| Stage recorder | `coldstart/recorder.py`, moving in task 6 **repo** | Clock-B stage marks for every swap |
| RunPod transport with 409/5xx retry, submitter, lifecycle extraction, endpoint preflight | `coldstart/runpod_*.py`, `coldstart/preflight.py`, moving in task 12 **repo** | Every paid run |
| Interleaved randomized schedule | `coldstart/scheduler.py`, generalized in task 9 **repo** | Interleaving the interference grid's conditions so platform drift cannot confound them |
| Pinned worker image, its CI build, and the test that every imported package is COPYed | `worker/Dockerfile`, `.github/workflows/build-worker.yml`, `tests/test_harness_boundary.py` **repo** | Artifact 4 adds handler files to the same image |
| Phone-legibility floor and figure input guards | `MIN_PHONE_TEXT_PX`, `phone_pt`, `_validate_rows`, `_required_field` in `coldstart/analysis/figures.py`, moving in task 11 **repo** | All four figures |

### 1b. Pattern reused, new code written

| Component | Why the code does not fit as-is | What artifact 4 writes |
|---|---|---|
| Common random numbers per repetition, pairing on repetition identity | `autoscale/sweep.py` `_derive_seed` and `frontier.PolicyPoint.rep_indices` are keyed to thresholds and signals **repo** | The same discipline: every strategy replays the identical trace within a repetition, and pairing is on repetition id, not position |
| Published-figure drift test and byte-level parity gate | `tests/test_published_figures.py` and `scripts/parity_check.sh` hardcode artifact 1's figure names, store and render script **repo** | Their own copies pointed at artifact 4's figures and committed data |
| Reconnaissance capture script | `recon/capture.py` writes to `fixtures/vllm_logs/startup_{i}.log`, one log per job **repo**. Run unchanged, it would overwrite artifact 1's committed fixtures, which the parser tests depend on | An output-directory argument and one log per engine. A small change, but not "as-is" |
| Pre-registration and dated amendments | `docs/experiment.md`, `docs/experiment-a2.md` **repo** | `docs/experiment-a4.md`, its own file. The August DoD's "pre-registration extended" is replaced (§12) |
| Business framing | `Assumptions` in `coldstart/analysis/economics.py` requires, beside the GPU hourly rate, four artifact-1 fields with no meaning here: scale-ups per day, steady-state tokens per second and context length must be positive, volume cost non-negative **repo**. The extraction inventory keeps the module in `coldstart/` **repo** | Its own assumptions record: GPU hourly rate, fleet size, request volume, SLO tail. `SECONDS_PER_HOUR` and `DAYS_PER_MONTH` are defined locally and pinned equal to artifact 1's by a test (§7, boundary) |
| Cold-start stage taxonomy | `coldstart/analysis/metrics.derive` computes `T_total` from the platform's submit and result timestamps (clock A) **repo**. A swap happens inside one job and has no per-swap platform clock | The stage **definitions** and the `S2`/`S3`/`S4` bracket arithmetic from clock B |

### 1c. Not used — and the August spec implied they would be

| Component | Why not |
|---|---|
| **The simulation loop**, `autoscale/sim.py` | **The largest correction.** August §6 has artifact 2's simulator "gaining" a model dimension and a placement policy. The loop has no replica identity: load is spread as `ceil(in_flight / serving_replicas)` under a stated even-balancing simplification, and fleet state is a count **repo**. Placement is exactly the question of *which* GPU holds *which* model. Retrofitting it would also change artifact 2's code under artifact 2's still-running experiment. Artifact 4 writes its own loop (§7) |
| Controller, signals, threshold sweep, Pareto frontier | Artifact 4's fleet is a fixed size per run. Nothing autoscales |
| Spike-shaped arrivals, `autoscale/arrivals.py` | Coupled to `SpikeShape`, with no model labels and no locality **repo** |
| `LagDistribution`, `autoscale/coldstart_ecdf.py` | The class is generic, but its module imports `coldstart` at load time, so any importer pulls `coldstart` in transitively **repo**. Drawing from an empirical sample is `rng.choice` over a validated list. Artifact 4's resampler lives in its own coldstart-free module rather than importing a boundary violation |
| Cache-arm configuration, `coldstart/cache_config.py`, and the handler's compile-cache directory check | The arms are artifact 1's. The directory check cannot tell whether a cache came from a different model, by its own docstring (`worker/handler.py`) **repo**. Artifact 4 reads compile time `S4b` instead (§5) |
| `worker/probe.py` called directly | It is artifact 1's measured path, not a general engine driver: `PORT = 8000` is hardcoded, so two co-resident engines collide; it sends a fixed prompt as ten sequential requests; and it always tears its engine down before returning **repo**. Artifact 4 uses the shared `vllm serve` lifecycle instead (§1d, §11) |

### 1d. Shared tooling — built once, outside artifact 4

All five components below were missing when this amendment was written. By 2026-10-04 all five had landed on `main`: the harness extraction merged at `39c20b3`, the shared in-container tooling at `ca9afbc`, and artifact 2's band arithmetic at `8c3b4c7` **repo**. The rows now say what each is, and how artifact 4 uses it.

| Component | What landed | How artifact 4 uses it |
|---|---|---|
| **Concurrent load generator** | `harness/bench.py` `run_bench`, a wrapper around `vllm bench serve` that returns the tool's saved JSON unaltered **repo**. pandas is not in the image, so the tool's custom dataset fails; the random dataset works (artifact 2's pilot, 2026-10-04) | Load for every curve and grid cell, through the random dataset at a fixed input and output length (plan 2, Task 7). The tool cannot replay a recorded trace's exact timestamps, so the replay driver is artifact 4's own (§1e item 7, plan 3) |
| **`vllm serve` lifecycle** | `harness/serve.py` `served(model, *, args, env, port, health_timeout)`, yielding a `Server` with `.stop() -> float` **repo**. `.stop()` measures until the engine's parent process exits, not until GPU memory is free, by its own docstring | Two engines on two ports for co-location, and timed teardown inside the context for swaps. Memory release is measured separately by polling `memory.used` (plan 2, Tasks 3 and 6) |
| **Campaign loop** | `harness/campaign.py` `run_campaign(schedule, submit, build_record, store, ...)` **repo**. Artifact 1's driver now runs on it | Every paid campaign (plan 2, Task 15) |
| **Service-curve sweep** | `harness/service_sweep.py`, `harness/sweep_worker.py`, `worker/sweep_handler.py`, `scripts/run_service_sweep.py` **repo**. The handler always sends artifact 1's 12-token prompt, or random prompts of that length | Artifact 4's request shape is its own (§4), so it does not use the sweep handler. It reuses the sweep's measured-run function `run_one`, its prompt plan and its failure rule inside its own co-location cell, so a solo and a co-located latency are the same kind of number (plan 2, Task 7) |
| **Trace-replay comparison** | `autoscale/validation_band.py`: `trajectory`, `band` and `compare`, with no import path to `coldstart` and no pre-registered values **repo** | Validation's band and verdict (plan 3). The check that every real repeat replayed one schedule stays artifact 4's own, since artifact 2 keeps its version in `autoscale/validation.py` **repo** |

### 1e. Genuinely new — artifact 4's build scope

1. **Multi-model traffic generator.** Zipf model labels; a spread regime (Poisson) and a bursty regime (§7).
2. **Placement simulator loop** on the shared event queue, with the semantics in §7.
3. **Co-located service model.** Latency as a function of a model's own load *and* its neighbour's, measured on a grid and interpolated in two dimensions. `ServiceCurve` is one-dimensional **repo**, so this is new.
4. **Two-engine co-location harness.** Two `vllm serve` processes on distinct ports with memory fractions, driven by two load streams at a controlled split. Built on the shared lifecycle and load generator.
5. **Swap measurement handler.** Model A resident, teardown, model B healthy, in one container. Times teardown until A's GPU memory is released, not only until process exit, and records `S4b` and page-cache state per swap-in (§5).
6. **Reconnaissance handler variant.** Co-residency at the split, one swap, and the sleep-mode probe (§6).
7. **In-container replay driver** for validation: a replayed three-model trace against real engines, with real swaps, at exact timestamps, and the check that all real repeats replayed one schedule. The band and verdict arithmetic come from `autoscale/validation_band.py` (§1d).
8. **Record classes and the pin set**: model revisions, image digest, memory fractions, `--max-model-len`, request shape.
9. **Analysis**: fleet sizing per strategy, per-decile p99 with the drain-out rule, crossover estimator with a paired interval (§7, §8).
10. **Money view** on artifact 4's own assumptions record.
11. **Four figures** and their drift test.
12. **`docs/experiment-a4.md`.**
13. **Import-boundary test** for `placement/` (§7).

---

## 2. Prerequisites and sequencing

The August definition of done requires "Artifacts 1 and 2 complete; stage taxonomy, KV capacity,
service curve, and simulator available." Read literally it is both too strong and too weak.

**Why wait for the extraction at all.** Not because reuse is impossible today:
`autoscale/events.py` and `autoscale/service.py` import nothing first-party and can be imported now
**repo**. The reason is rework. Code written against `coldstart.analysis.stats` today is rewritten
when the extraction moves it, and artifact 5's amendment gives the same reason **repo**.

**Proposed gates**, split so the GPU-free half is not held up by the measurement half:

| Work | May start when |
|---|---|
| GPU-free: traffic generator, placement simulator, co-located service model, analysis, all against synthetic inputs | Extraction **task 4** (stats) has landed |
| GPU-free: figures, against synthetic inputs | Extraction **task 11** (figure guards) has landed |
| Measurement: recon, curves, interference grid, swaps, validation | Extraction **tasks 5–12** have landed, and the four shared components in §1d exist |
| Publication | After artifact 2's post. The portfolio's sequence is unchanged |

**Two things this depends on that are not artifact 4's to decide.**

- **Part of the shared tooling is blocked on artifact 2's reconnaissance.** Artifact 2's plan 2a,
  committed today as 2979152 and not yet executed, builds the replay arithmetic without waiting **repo**. It defers the
  load driver and the service-curve sweep driver to a plan 2b, because how artifact 2 pins platform
  capacity is its recon Q1 **repo**, and artifact 2's recon record rates Q1 and Q2 "NOT YET
  DECIDABLE" **repo**. Artifact 4's measurements do not have that dependency: they run inside one
  container on one GPU, with no platform scaling. So the fix is to split the tooling. An in-container
  load generator, `vllm serve` lifecycle and single-engine sweep go into `harness/` as their own
  plan, needing no recon answers. Artifact 2's plan 2b still owns everything platform-specific:
  capacity pinning, and a load driver that sends traffic through the platform across pinned
  replicas, which its open-loop gate requires **repo** (artifact 2 final §10) and an in-container
  driver cannot do. What moves out of plan 2b is the engine-side sweep and the load-generation core
  it would otherwise write. That changes artifact 2's planning, so it is a decision (§13, item 4).
- **The extraction has two sign-offs pending inside it.** Its inventory requires confirmation of
  four signature changes before task 8, and the explainer author's confirmation before task 4
  **repo**. The `artifact-1-published` tag it requires exists **repo**.

---

## 3. The model class — "~3B-class from artifact 1's family" does not exist

Artifact 1 ran `Qwen/Qwen3-8B` **repo**. **Qwen3 has no 3B dense checkpoint** **HF**.

| Checkpoint | Parameters | Layers / KV heads / head dim | `rope_theta` | `max_position_embeddings` | bf16 weights |
|---|---|---|---|---|---|
| `Qwen/Qwen3-4B` | 4,022,468,096 | 36 / 8 / 128 | 1,000,000 | 40,960 | 7.49 GiB |
| `Qwen/Qwen3-4B-Base` | 4,022,468,096 | 36 / 8 / 128 | 1,000,000 | 32,768 | 7.49 GiB |
| `Qwen/Qwen3-4B-Instruct-2507` | 4,022,468,096 | 36 / 8 / 128 | 5,000,000 | 262,144 | 7.49 GiB |
| `Qwen/Qwen3-4B-Thinking-2507` | 4,022,468,096 | 36 / 8 / 128 | 5,000,000 | 262,144 | 7.49 GiB |
| `Qwen/Qwen3-1.7B` | 2,031,739,904 | — | — | — | 3.78 GiB |

Parameters, architecture and configs **HF**; bf16 sizes **estimate** (parameters × 2 bytes).

**Proposed:** Qwen3-4B as the model class, Qwen3-1.7B as the fallback if the go/no-go fails.
Qwen3-4B is also proposed as artifact 5's base (§11).

**Memory, and why the split cuts KV several-fold rather than in half.**

- Artifact 1's engine reported a 21.64 GiB budget at `gpu_memory_utilization` 0.92 on the same card
  **repo**. Two 4B models take 14.98 GiB of it, leaving about 6.7 GiB for both engines' activation
  peaks, CUDA graphs and KV **estimate**.
- KV costs 144 KiB per token for this architecture (36 layers × 8 KV heads × 128 × K and V × 2 bytes)
  **estimate**. The same figure reproduces artifact 1's 8B reading, 4.92 GiB for 35,792 tokens **repo**.
- That gives roughly 90k tokens solo and roughly 13–20k per engine at an even split **estimate**.
  The split costs each model most of its cache, which is what makes August §5.3 worth measuring —
  provided the request shape lets KV bind at all (§4).

**Go/no-go pass criterion, stated in tokens so it can be fixed before recon.** Proposed: both
engines reach `/health` at the split with the pre-registered `--max-model-len`, and each engine's
logged KV capacity is at least 8 × T_max tokens, where T_max is a fixed per-request token ceiling,
proposed at 2,048. That is 16,384 tokens per engine, inside the 13–20k estimate above, so the check
can genuinely fail. The request shape itself is chosen later, at or below T_max (§4). August §5.0
names the check but not the threshold.

**The pre-registration is committed in two dated steps**, because recon is itself a paid run and the
request shape depends on what recon reports:

1. **Before the recon run:** model candidates and pins, T_max, `--max-model-len`, the memory split,
   and this go/no-go criterion.
2. **Before the first measurement run:** everything else §12 lists, including the request shape.

**The checkpoints are not fully homogeneous.** Shapes match, but `rope_theta` and maximum length
differ across pairs **HF**. Whether `rope_theta` enters vLLM's compiled graph, and so decides
whether two checkpoints share a `torch.compile` cache entry, is **unverified**. It matters: a
compile costs `S4b` 19.0 s and a cache hit 0.33 s in artifact 1's published medians **repo**. So:

- `--max-model-len` is pinned explicitly for every engine, independent of each checkpoint's maximum.
- Recon measures `S4b` per swap-in target, and the swap distribution is recorded per target pair.
- The validation set is chosen after recon: config-matched checkpoints if per-target swap costs
  differ, any three if they do not.
- Output length is fixed per request (`ignore_eos` with a fixed `max_tokens`), because base,
  instruct and thinking checkpoints stop at very different points and would otherwise make service
  time depend on which model was asked.

---

## 4. Request shape — at the inherited shape, KV never binds

Artifacts 1 and 2 use a short fixed prompt with `max_tokens` 16 **repo**. At that shape the KV cache
admits about 1,190 concurrent requests, far above vLLM's default `max_num_seqs` of 256, per artifact
2's recon record **repo**. At 13–20k tokens per engine after the split **estimate**, the same shape
would still admit several hundred. The split would not bind, August §5.3 would measure nothing, and
the required explanation "why a shrunken KV budget hurts more than proportionally" could not be
shown.

**Proposed:** artifact 4 pre-registers its own request shape, long enough that the split engine's KV
binds below `max_num_seqs`. The exact prompt and output lengths are chosen from the solo and split
KV capacities recon reports, at or below T_max (§3), and fixed in the second pre-registration step,
before any curve is measured.

**Cost of the choice:** artifact 4's service curves are not comparable with artifact 2's. That loss
is small, because the model class already differs and artifact 4 re-measures its curves anyway. It
is stated in the post.

---

## 5. Swap measurement conditions

Refines August §5.1. The baseline mechanism stays process-level: tear down, bring up, container warm.

- **Weight source is a design variable, pinned.** It is the largest swap-cost lever: artifact 1's
  median `T_weights` was 45.8 s when downloading (arm A) and 30.4 s from the network volume (arm B)
  **repo**. Proposed: weights on the network volume, the realistic source for a previously seen
  model on this platform.
- **Compile state moves weight time too.** Arm C loaded weights 8.85 s [8.37, 9.66] faster than arm
  B, paired within all 100 triples, on arms that differ only in compile-cache configuration **repo**
  (artifact 1's post). The post rules out host placement, position in the triple and the preceding
  arm, and leaves two candidate mechanisms: compile work attributed to loading, or CPU contention from
  compile workers **repo**. So a swap-in's `T_weights` depends on whether it compiles, and swap
  durations are recorded with their compile state rather than pooled.
- **The page cache would bias validation toward swap.** Three 4B models, about 22.5 GiB, likely stay
  in host page cache; twenty, about 150 GiB, likely do not **estimate**. Swaps measured on a three-model
  validation would then be faster than swaps in the simulated twenty-model fleet. Page-cache state
  is recorded per swap. Recon establishes whether the cache can be dropped inside the container
  **unverified**. If it can, swaps are measured cold and warm, the simulator draws from the cold
  distribution, and validation drops the cache between swaps. If it cannot, this is a stated limit.
- **Compile state is read, not inferred.** `S4b` per swap-in says whether compilation happened **repo**
  (parser). Compile state moves three things: `S4b`, `T_weights` (above), and KV capacity, where
  artifact 1 published 35,792 tokens without a warm compile cache and 43,040 with one **repo**. The
  KV-split measurement fixes compile state explicitly.
- **Teardown is timed to memory release.** Today the probe marks `S7` and then terminates its engine,
  so teardown is untimed **repo**. The new handler times from teardown start until A's GPU memory is
  free. Whether vLLM's memory profiling misbehaves if another process frees memory while it profiles
  is **unverified**. Recon checks it, and B starts only after A's memory is released.
- **A process-level swap re-pays interpreter startup.** The probe marks `S1` at its own start, so
  artifact 1 published `S1` as zero on every arm, and the `vllm serve` subprocess's own Python and
  import time lands inside `S2` **repo**. So a process-level swap skips `T_platform` and container start,
  and it does **not** skip interpreter startup. August §1 ("not platform provisioning or interpreter
  startup") and learning-guide Module 1 are corrected accordingly.
- **Figure 4 separates taxonomy from magnitude.** Artifact 1's medians are for the 8B model. Figure 4
  shows the 4B swap's own measured stages, with each stage marked paid or skipped per the taxonomy.
  Artifact 1's 8B magnitudes appear only as a labelled reference, never as the thing a 4B swap is
  subtracted from.

---

## 6. Sleep mode — named candidate, and how it enters the model

Refines August §5.0. The August spec says to measure a second arm "if the pinned version offers a
cheaper in-process path" without naming one.

**Named candidate:** vLLM's sleep mode. At its lighter level it moves weights to host memory and
restores them on wake. Whether it exists in vLLM 0.27.1, whether it applies to switching *between*
checkpoints or only to suspending one, and what GPU memory a sleeping engine keeps are all
**unverified**. Recon answers them.

If a cheap path exists and is not measured, every crossover is biased toward dedicate. If it is
measured, the §7 simulator cannot represent it as written: it has no host-memory tier, no limit on
how many sleeping models fit in host RAM, and no allowance for GPU memory a sleeping engine keeps.

**Proposed:** a sleep-mode arm is measured and reported. It is simulated only if recon measures all
three of those quantities; otherwise the post states that the crossover is for process-level swap
and gives the sleep-mode swap cost beside it.

---

## 7. The simulator, restated

Replaces August §6. A new loop in artifact 4's own package, proposed name `placement/`.

**Offered load and fleet sizing.** The August design never says how many GPUs each strategy gets,
which leaves the cost axis undefined: at equal M, cost is identical by construction. Proposed rule:

- **Offered load** is a fixed total rate, pre-registered as a multiple of one GPU's measured
  saturation — the same rule-relative-to-measurement style artifact 2 uses **repo**.
- **One replication rule, applied identically to all three strategies.** A model whose share of
  offered load exceeds a pre-registered fraction of one GPU's capacity is *hot*. Each hot model gets
  enough pinned, solo, non-evictable GPUs to carry its load, in every strategy. The strategies differ
  only in how the remaining *tail* models are placed: one GPU each (dedicate), LRU over a shared
  pool (swap), or paired (co-locate). At Zipf s = 2.0 over 20 models the hottest model carries 62.7%
  of traffic **estimate**, so hot models are not an edge case.
  - *Why one rule for all three.* If only some strategies may replicate, the others become
    infeasible at high skew by construction, and the sizing rule, not the measurement, decides the
    result exactly where the August design expects swap to win. Pinning hot models in every
    strategy is also how multi-model platforms are commonly run, a claim that is **unverified** here
    and stated as a design choice.
- **Each strategy is sized to the smallest M that meets a pre-registered SLO**: median-across-
  repetitions p99 at or below a target for every popularity decile. Dedicate's M is fixed by
  construction, one GPU per tail model plus the hot models' pinned GPUs. Swap and co-locate search M
  upward from the hot GPUs, bounded above by dedicate's M. For swap, each added GPU enlarges the
  shared pool by one. For co-locate, M starts at every tail model paired, and each added GPU un-pairs
  the busiest remaining pair onto two solo GPUs. Both families therefore reach dedicate exactly at
  dedicate's M, which is why that is the bound.
- **Sizing happens once per grid point**, over all repetitions, not per repetition. Cost is that M
  times the measured window; warm-up and drain-out time are not charged, because both are artefacts
  of a finite simulation.
- **Co-locate pairing** is fixed among tail models: the busiest tail model with the least busy, the
  second busiest with the second least busy, and so on. This does not balance pair loads — at s = 1.0, the pair (1, 20) carries about 29% of traffic and
  (10, 11) about 5% **estimate**. It keeps each busier model's neighbour quiet, so interference is
  smallest where load is largest. Hot models are pinned solo and are never paired.
- **Dominated is a result.** A strategy that cannot meet the SLO below dedicate's M at some skew is
  reported as dominated there. Swap thrashing at low skew is expected to show up this way.

**Residency and routing.**

- Each pinned GPU holds one hot model. Each tail GPU holds one resident model under dedicate and
  swap, two under co-locate.
- A request goes to a GPU holding its model, least in-flight first. This replaces artifact 2's
  even-balancing simplification for this loop only, because here it is the mechanism under study.
- Initial residency is the M most popular models. The first W seconds of every run are discarded as
  warm-up, with W pre-registered.

**Swap-LRU semantics.**

- Under swap, a tail model is resident on at most one GPU of the shared pool. Hot models sit on
  their pinned GPUs and never enter the pool.
- A request for a non-resident model with no swap already pending for it triggers one swap. The
  victim is the resident model with the oldest last-request time, across the pool's GPUs.
- The victim's GPU stops admitting requests, drains its in-flight requests, and is then unavailable
  for a duration drawn from the measured swap distribution for that target.
- Requests for the evicted model queue until it is resident again. Requests for the incoming model
  queue until its swap completes.
- A swap may begin while every GPU is busy; the drain rule covers it.

**Service time.** Solo and solo-at-split curves use `ServiceCurve` **repo**. Co-located requests use the
two-dimensional model (§1e, item 3). Artifact 2's "service time frozen at dispatch" simplification
is inherited and stated **repo**. It matters more here, because a neighbour's load can change
mid-request. The interference curve is the check on it (August §9).

**Binary residency.** Artifact 2's binary replica model rests on artifact 1's measurement that vLLM
finishes warmup before answering `/health` **repo**. A process-level swap runs the same engine path, so
the justification carries over. An in-process swap path does not inherit it and gets its own
warm-up check.

**Drain-out, not censoring.** `SimResult.latencies` in artifact 2 excludes requests unfinished at the
window's end **repo**. Here those are exactly the cold-tail requests stuck behind swaps, so excluding
them would flatter swap. Every request that arrives inside the window is served to completion: after
the window closes, no new arrivals are generated and the simulation runs until the queue drains.

**Traffic generator.**

- **Spread:** Poisson arrivals, each labelled with a model drawn from Zipf, p(k) ∝ k^−s for
  k = 1…N.
- **Bursty:** each model's arrivals follow an on/off process whose long-run rate equals its Zipf
  share, so the frequency distribution is identical to the spread regime and only temporal locality
  differs. Mean burst length is pre-registered.

**Import boundary.** Exactly one module in `placement/` may import `coldstart`, directly or
transitively. It is the adapter that reads artifact 1's stage medians for figure 4, and nothing else
imports it at module level. The test checks this transitively, importing each other module in a
fresh subprocess and asserting `coldstart` never entered `sys.modules`. A direct-import check would
pass while `coldstart` arrives through `autoscale.coldstart_ecdf` or `autoscale.sim` **repo**. A
subprocess is needed because pytest shares `sys.modules` across the session, and other test files
import `coldstart` **repo**, so an in-process check would depend on test order.

The two calendar constants, `SECONDS_PER_HOUR` and `DAYS_PER_MONTH`, are defined in `placement/`'s
money module. A test pins them equal to `coldstart.analysis.economics`'s values, the same
conformance pattern artifact 2 uses for its statistics copy **repo**. Tests are outside the boundary.

**Validation coverage.** One GPU with one resident model exercises swap timing and queueing, not LRU
victim choice across GPUs. Victim choice is covered by unit tests with hand-computed scenarios, the
way artifact 2 covers its controller arithmetic **repo**. The post says so.

---

## 8. Statistics: the per-decile floor, and the crossover interval

Not anticipated in August §8.

**The floor.** The shared statistics refuse a p99 from fewer than 500 samples **repo**. For N = 20,
Zipf p(k) ∝ k^−s, and the coldest decile being models 19 and 20:

| Zipf s | Coldest decile's share | Requests per run, expected count 500 | Requests per run, all 30 runs ≥ 500 with 95% probability |
|---|---|---|---|
| 0.6 | 5.25% | 9,530 | about 10,830 |
| 1.0 | 2.85% | 17,528 | about 19,950 |
| 1.5 | 1.07% | 46,672 | about 53,180 |
| 2.0 | 0.33% | 151,436 | about 172,630 |

All **estimate**. The expected-count column is break-even: about half of runs miss the floor there.
The last column sizes each run so it clears the floor with probability 1 − 0.05/30 ≈ 99.83%, so that
all 30 clear together at least 95% of the time. It uses a normal approximation to the binomial.
Sizing each run to clear only 95% of the time would leave all 30 clearing together about 21% of the
time (0.95^30), and the all-or-nothing rule below would then withhold most grid points.

- **Bursty traffic is overdispersed**, so the formula understates what it needs. Run length at each
  grid point is set by a pilot on a separate seed range. The pilot must show every decile clearing
  the floor in at least 1 − 0.05/R of repetitions, where R is the pre-registered repetition count.
- **All or nothing per grid point.** A decile's p99 at a grid point is published only if it clears
  the floor in every repetition, and there are at least 20 repetitions **repo** (the bootstrap floor).
  Otherwise that decile is withheld at that grid point. Withholding repetition by repetition would
  keep the runs that happened to send more traffic to the cold tail, which is a selection bias.
- **The estimand matches artifact 2's:** p99 per repetition, then the median across repetitions,
  with a bootstrap interval over repetitions **repo**.
- **Hardware validation is not affected** at the decile level. It compares timelines for three models.

**The crossover estimator.** Sizing is once per grid point (§7), so a strategy's cost at a grid
point is a single number, not a per-repetition sample. A paired difference of per-repetition costs
would therefore have zero width. The uncertainty lives in the sizing, and the estimator puts it
there. Per locality regime:

1. **Point estimate.** At each skew grid point, size each strategy (§7) and take the cheapest one
   that is not dominated. The crossover is the skew at which that choice changes, reported as the
   pair of adjacent grid points it lies between. Cost is integer M, so interpolating between grid
   points would invent precision the sizing does not have. A tie in M is reported as a tie.
2. **Interval.** Resample repetitions with replacement, using the same resampled repetition ids for
   every strategy, so the pairing through common traces survives. Re-size every strategy and
   re-locate the crossover inside each draw, so uncertainty propagates through sizing and location
   together. This is the approach artifact 2's gap interval takes through frontier selection **repo**.
3. **Draws that do not locate a single crossover are counted, not dropped.** The share of draws
   with no crossover in the swept range, and with more than one, is published beside the interval.
4. **Grid points where any decile is withheld** make sizing undefined there. They are reported as
   not evaluable and excluded from location. The pilot rule above exists to make this rare.

**Per-decile p99 comparisons between strategies** at a common M, the fairness figure's content, use
`bootstrap_paired_median_diff` **repo**. It currently pairs by artifact 1's arm labels; it needs the
grouping key artifact 5's amendment also proposes **repo**, as part of the extraction's task 4 move.

---

## 9. Budget, sequence and repository corrections

- **Stale in August §11:** "artifacts 1–3 consume roughly $120–195". The sequence became 1, 2, 4, 5, 3
  when artifact 5 was added, and artifact 3 uses no GPU **repo**.
- **Stale in August §12:** "decision deferred to post-artifact-3". It follows artifact 2.
- **Stale in August §10:** the pre-publish gate is "same as artifacts 1–3". It is the gate artifacts 1
  and 2 use.
- **The funding decision still cannot be made.** Artifact 1's spend was never recorded: its post
  publishes 6.14 measured GPU-hours and states that no invoice was read **repo**. Artifact 2's final
  design requires reading it before artifact 2 spends **repo**. The decision covers artifacts 4 and 5
  together, per the portfolio contract **repo**.
- **The $30–45 estimate is incomplete.** It has no line for reconnaissance (co-residency, one swap,
  the sleep-mode probe), for the solo 4B curve, or for a sleep-mode arm. It needs re-estimating
  before the funding decision. Reuse cuts engineering hours, not GPU time.
- **The August cut order saves nothing first.** It cuts skew-sweep resolution first, but the skew
  sweep is simulated and costs $0. Proposed paid cut order: interference-grid resolution first, then
  validation repeats down to three, then the sleep-mode arm.
- **Repository.** The portfolio contract gives each artifact its own repo, with artifacts 1 and 2 as
  the stated exception **repo**. The August design already says artifact 4 links "the shared repo".
  The exception extends to artifacts 4 and 5, and the contract should say so.

---

## 10. Risks — additions to August §12

| Risk | Handling |
|---|---|
| August's "verified in the local loop before any paid run" cannot hold: GPU memory cannot be checked locally | Replaced by the recon go/no-go with a numeric pass criterion (§3) |
| Page cache makes validation swaps faster than fleet swaps | Page-cache state recorded per swap; cold distribution drives the simulator; validation drops the cache, or the limit is stated (§5) |
| Checkpoints differ in `rope_theta`, so swap cost may depend on the target | `S4b` measured per target; validation set chosen after recon (§3) |
| The inherited request shape makes the KV split invisible | Artifact 4's own shape, chosen from recon's KV readings (§4) |
| `coldstart` imported transitively through artifact 2's resampler | Own resampler; transitive boundary test (§1c, §7) |
| The shared tooling waits on artifact 2's recon | Build it as its own harness plan (§2, §13 item 4) |
| A cheaper swap path exists but cannot be simulated | Measured and reported; simulated only if its tier is measured (§6) |
| Cold-tail requests censored at the window's end | Drain-out (§7) |
| A sizing rule that lets only some strategies replicate decides the high-skew result by construction | One replication rule for all three strategies (§7) |
| The paired cost difference has zero width once sizing is per grid point | Interval from resampling repetitions through sizing and location (§8) |
| Replay arithmetic planned inside `autoscale/` imports `coldstart` transitively | Resolved: plan 2a now builds it in the coldstart-free `autoscale/validation_band.py` (§1d) |

---

## 11. Coordination with artifact 5

Artifact 5 hard-depends on artifact 4 for its base model, GPU class, image and swap-cost reference
line **repo**. Its parallel amendment already assumes Qwen3-4B, citing this amendment **repo**. The
August LoRA design still says "~3B-class"; under the convention that August designs stay unedited,
that is superseded by artifact 5's amendment, not corrected in place.

- **Base checkpoint:** proposed Qwen3-4B, the direct 4B sibling of artifact 1's Qwen3-8B.
- **Reference line:** the process-level swap arm, because it is the one the simulator uses. A
  sleep-mode arm, if measured, is reported to artifact 5 as a second line.
- **Funding:** one decision covers artifacts 4 and 5 together, per the portfolio contract **repo**.

Artifact 5's amendment makes three proposals that bear on artifact 4 **repo**. This amendment's
position on each:

- **Artifact 4 owns the `vllm serve` lifecycle lift.** Accepted. Artifact 4 reaches it first, and
  `worker/probe.py` stays frozen as artifact 1's measured path.
- **The campaign loop is lifted with a record-builder callback.** Accepted. Artifact 4's paid runs
  need exactly that loop (§1d).
- **`vllm bench serve` as the shared load path.** Accepted for curves and the interference grid.
  Validation's exact-timestamp replay is the open question, which is **unverified**, and artifact 4
  builds its replay driver only if `vllm bench serve` cannot do it (§1d).

Artifact 5's amendment also expects artifact 2 to build the service-curve sweep in the harness. If
§13 item 4 is accepted, that expectation changes to the standalone harness plan, and artifact 5's
document should be updated to match.

**Interfaces agreed with artifact 5's session on 2026-09-26.** Artifact 5 codes against these through one adapter module, so a later rename touches one file:

- `harness/serve.py` `served(model, *, args, env, port=8000, health_timeout=900.0)`: a context manager yielding `.base_url`, `.log_lines` and `.healthy`. At artifact 4's request it also has an idempotent `.stop() -> float`, so a swap handler can time teardown inside the context, and `port` is per call, so two engines can run at once.
- `harness/bench.py` `run_bench(...)`: runs `vllm bench serve` and returns its saved JSON unaltered.
- `data/a4/cost_per_tenant.json`, written by artifact 4's plan 3: `gpu_hourly_rate`, `n_models`, a `reference` grid point fixed in the second pre-registration step, and one row per (regime, s) with dedicated, swapped (process-level arm) and optional sleep-mode cost per tenant per month, null where dominated or not evaluable. Per-tenant cost depends on skew and regime, so a flat set of keys could not name the grid point it came from. Artifact 5 refuses the file if the reference matches zero or several rows, or if `gpu_hourly_rate` differs from its own pre-registered rate.

**Different import boundaries, deliberately.** Artifact 5 bans importing `autoscale/` **repo**.
Artifact 4 imports two of its coldstart-free modules, `events` and `service`, because artifact 4 is a
simulator reusing a simulator's primitives and artifact 5 is pure measurement.

---

## 12. Definition of done — deltas only

Every August item not listed here stands.

- **Replaces** "Artifacts 1 and 2 complete; stage taxonomy, KV capacity, service curve, and simulator
  available" with: the gates in §2 met for each kind of work, and **the post published after
  artifact 2's post**.
- **Replaces** "Pre-registration extended with artifact 4's hypotheses" with: `docs/experiment-a4.md`
  committed in the two dated steps of §3. Before the recon run: model candidates and pins, T_max,
  `--max-model-len`, the memory split, and the go/no-go criterion. Before the first measurement run:
  N, the Zipf grid, both locality regimes' parameters, the offered load, the SLO, the hot-model
  threshold, the sizing and pairing rules, the request shape, the warm-up window, the repetition
  count, the pilot rule for run length, and the tolerance construction.
- **Adds:** model set and revisions recorded, with the go/no-go outcome and, if it fails, the fallback's.
- **Adds:** for every swap, teardown timed to memory release, `S4b`, page-cache state, and target pair recorded.
- **Adds:** a test that no function name defined in `placement/`, public or private, also exists in
  `harness.stats`, `harness.figure_guards` or `autoscale.stats`, with an explicit allow-list for any
  deliberate local helper and the reason beside it. This replaces the unmeasurable "does not
  re-implement".
- **Adds:** the transitive import-boundary test passes (§7).
- **Adds:** this artifact's own spend recorded when it completes.

---

## 13. Decisions — all twelve accepted by the owner, 2026-09-26

Each was put to the owner as a recommendation and accepted as written. Decision 12's request went to artifact 2's session the same day and was accepted: plan 2a now builds the band arithmetic in a coldstart-free module (§1d).

1. **Model class.** Qwen3-4B, fallback Qwen3-1.7B, and Qwen3-4B as artifact 5's base.
2. **Amendment rather than in-place edit.** Chosen to follow artifact 2's precedent. The cost is that
   a reader landing on the August file, including through artifact 5's link, does not see this one.
   A one-line forward pointer in the August header would fix that, and would break the "unedited"
   convention artifact 2's August file still keeps.
3. **Split gates (§2).** Simulator and analysis after extraction task 4; figures after task 11;
   measurement after tasks 5–12 and the shared tooling; publication after artifact 2.
4. **In-container tooling as its own harness plan (§1d, §2).** The load-generation core, the
   `vllm serve` lifecycle and the single-engine sweep are built without waiting for artifact 2's
   recon. Artifact 2's plan 2b keeps capacity pinning and the platform-routed load driver its
   open-loop gate needs. Recommended, because it unblocks artifacts 4 and 5 and removes the
   engine-side work from plan 2b. It changes plan 2b's scope, so it needs your agreement for
   artifact 2 as well.
5. **The simulator is new, not extended (§1c, §7).** This makes the largest engineering item explicit.
6. **Fleet sizing (§7).** One replication rule for all three strategies: hot models on pinned solo
   GPUs; the strategies differ on the tail. Each strategy sized once per grid point to the smallest M
   meeting a per-decile SLO, bounded by dedicate's M. Hot-with-cold pairing among tail models, to
   keep busy models' neighbours quiet.
7. **Artifact 4's own request shape (§4).** Accepts that its curves are not comparable with artifact 2's.
8. **Weight source and page cache (§5).** Network volume; cold-cache distribution drives the simulator.
9. **Sleep mode (§6).** Measured and reported; simulated only if its host-memory tier is measured.
10. **Paid cut order (§9).** Interference-grid resolution, then validation repeats, then the sleep-mode arm.
11. **Artifact 5's three proposals (§11).** Artifact 4 owns the lifecycle lift; the campaign loop is
    lifted with a record-builder callback; `vllm bench serve` is the shared load path, with a replay
    driver only if it cannot replay exact timestamps.
12. **Ask artifact 2's plan 2a to split its replay arithmetic (§1d).** Put the band and verdict
    arithmetic in a module that does not import `autoscale.sim`, before plan 2a's Task 8 is executed.
    If declined, the arithmetic is artifact 4 build scope.

---

## 14. Found while writing plan 1 — decided by the owner, 2026-10-04

**Decision:** in the bursty regime, the hot-model rule and dedicate's fleet size are set on ON-period load (average ÷ duty); the spread regime keeps the average. Still one rule for all three strategies. Plan 3, Task 1 implements it. A screen run on example inputs on 2026-10-04 confirmed the effect: in the bursty regime swap sized 7–11 GPUs below dedicate instead of every strategy coming out dominated.

Plan 1's code ran a full sweep on placeholder inputs on 2026-09-26. Both regimes came out degenerate, and the causes are design properties, not simulator bugs:

- **The placeholder design point.** In the spread regime, 20 models share four GPUs' worth of load, so every model is requested every few seconds, and a swap pool even one GPU short of holding every tail model thrashes. The placeholder SLO of 4 s is also shorter than one swap. Swap then sizes to dedicate's M at every skew. This is a parameter choice, and plan 3's ranking-blind regime screen addresses it, as artifact 2's regime probe did.
- **A gap in §7's sizing rules.** The hot-model rule and dedicate's fixed M use a model's average load. Under bursty traffic a model's ON-period load is its average divided by duty, five times at duty 0.2. So in the bursty regime even dedicate misses a p99 SLO, and every strategy is reported dominated. Two fixes are possible. One sizes on ON-period load in the bursty regime. The other lets every family, dedicate included, search M upward to a common cap, which changes what "dominated" means. The owner chose the first on 2026-10-04 (above). Plan 1's code implements §7 as written; plan 3's Task 1 adds the ON-period factor.

---

## 15. Implementation timeline — moved, 2026-10-04

The timeline, with phase status, dependencies, owner decisions, calendar and the GPU budget, is its own document: [the artifact 4 implementation timeline](../plans/2026-10-04-artifact-4-implementation-timeline.md). Its GPU budget, about 11–16 GPU-hours and $12–18 at the repository's illustrative rate, replaces §9's "$30–45, incomplete" as the working estimate; §9 stays as the record of the earlier one.
