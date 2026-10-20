# Dedicate, swap or share: placing twenty small models on GPUs, and a simulator that missed its own test: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: LLM serving on a GPU (P1), How these experiments earn trust (P2).

## Why it exists

**Question:** Twenty small models on rented RTX 4090s: dedicate a GPU to each, swap models through a shared pool, or co-locate two per GPU? Which is cheapest as popularity skew and arrival timing change? The answer comes from a simulator that failed its pre-registered validation gate (P2: gate).

**Requirements that drove everything:**

- Size every strategy by the same rule: hot models pinned the same way, then the smallest fleet that meets the SLO. *Why:* If only some strategies may give a hot model extra GPUs, the rule, not the measurement, decides the high-skew result (scope amendment §7).
- Hold the latency target for every popularity decile of models, not only for all requests together. *Why:* Popular models send most requests, so an aggregate p99 (P2: percentiles) can pass while some tenants fail (design §8).
- Sweep popularity skew at two arrival regimes that give each model the same long-run share. *Why:* Swapping with LRU follows whether a model's requests come together in time, not how often they come; skew alone misses that (design §7).
- Measure on the GPU what a swap, a co-located neighbour and a memory split cost; simulate only traffic, fleet dynamics and queueing. *Why:* Only the hardware can answer them; interference "cannot be reasoned to" (design, module 2).
- Fix the rules before the data is analysed, and record any later change as a dated amendment (P2: amendment); trust the simulator only if it reproduces a real replay, and publish a miss. *Why:* Fleet numbers are a model's; only a test fixed in advance separates a finding from model error (a failed gate is a result (P2: failed)).
- State the result as a decision rule in GPUs and monthly dollars, with every conversion assumption published. *Why:* The portfolio requires money too, and readers must be able to substitute their own rate.

## Need to know first

- **Zipf skew, and hot models**: The k-th most popular of 20 models gets a share proportional to 1 / k to the power s. At **s = 2.0** the hottest model carries 62.7% of requests (1 divided by 1.596, the sum of 1 / k² over the 20 models). Total load: one GPU's measured throughput, 8.89 requests per second. A model above 0.7 of a GPU is **hot** and gets pinned GPUs in every strategy. Spread arrivals never reach that: even at s = 2.0 the hottest model needs 0.627 of a GPU, so no model is hot there.
- **Spread and bursty arrivals**: Same long-run share per model, different timing. **Spread**: random (Poisson) arrivals, each labelled independently. **Bursty**: each model is ON in bursts of about 120 s, a fifth of the time. In a burst its load is five times its average, so the bursty hot-model rule uses that ON-period load.
- **A swap, and the LRU pool**: Stop one vLLM (P1: vllm) engine, wait for its memory to free, start the next model's engine until it answers health: median **37.8 s** over 16 warm swaps, compile cache (P1: compile) hit. The swap strategy's pool evicts the **least recently used** model. Sleep mode (5.0 s) was measured, never simulated.
- **Co-location and the KV split**: Two vLLM 0.27.1 engines on one card, 45% of its memory each. The KV cache (P1: kvcache) falls from **168,464** tokens alone to **55,104** (pinned): room for 82 full-length requests of 2,048 tokens, against 26 (26 to 28 were seen running). It shrinks 3.1 times while the memory share shrinks 2.0 times. About 2.6 times is a fixed cost: roughly 3.6 GiB sits outside the KV cache (the weights (P1: weights) among it) at either budget, so it comes off the smaller budget first; an unpinned split engine that hit the compile cache held 64,976 tokens. The other 1.18 is the pin: both engines were held to the compiled engine's 55,104, about 1 GiB of KV less each, so that two engines' CUDA-graph capture fit on the card.
- **The SLO, per popularity decile**: **SLO: p99 at most 75.6 s**, twice the median swap. A **decile** is 2 of the 20 models by popularity. Its p99 is taken in each simulated run, then the median over 30 runs. A fleet size passes only if all ten deciles meet the SLO.
- **The validation gate, as used here**: Three tenants on **one GPU**, a 900 s bursty trace of 1,562 requests with real swaps, replayed **three times**. Per 30 s bin, the simulator's median latency must fall inside the three repeats' band. Pass: at least 10 judged bins, at most half missing, swap count within the real range ±1. Co-location gets only two **held-out** interference cells.

## How it works

One reference point: bursty arrivals, Zipf s = 1.0, 20 models, one GPU of load. Dedicate's and co-locate's counts are arithmetic; swap's 10 and the SLO checks are simulated, by a simulator that failed its gate.

| Step | What happens | Pinned hot GPUs | Tail models | Dedicate GPUs | Swap GPUs | Co-locate GPUs |
|---|---|---|---|---|---|---|
| 1 | Twenty models share one GPU's worth of load (8.89 req/s, one GPU's measured saturation), Zipf s = 1.0. Bursty: each model is ON about a fifth of the time, at five times its average load. No GPU is placed yet. (Decision: Two arrival regimes with the same per-model shares) | not yet | 20 | not yet | not yet | not yet |
| 2 | The hot rule: the top model has 0.278 of the traffic, so 1.39 GPU of load while ON. Over 0.7, so it gets ceil(1.39 / 0.7) = ceil(1.985) = 2 pinned GPUs, in every strategy (derived). (Decision: One sizing rule for every strategy, judged per decile) | **2** | **19** | not yet | not yet | not yet |
| 3 | Model 2 has 0.139 of the traffic, 0.695 GPU while ON: 0.005 under 0.7, so not hot. A 0.69 threshold would pin 5 GPUs, not 2 (derived): the rule sets this edge, not the data. The other 18 models are lower still. (Decision: One sizing rule for every strategy, judged per decile) | 2 | 19 | not yet | not yet | not yet |
| 4 | Dedicate: the pinned GPUs plus one GPU per tail model, 2 + 19 = 21 (derived). One placement, never searched. (Decision: One sizing rule for every strategy, judged per decile) | 2 | 19 | **21 (fixed)** | not yet | not yet |
| 5 | Swap: the pinned GPUs plus a shared LRU pool grown from 1 to 19 GPUs, so 3 to 21 in all. Sizing takes the first count where all ten popularity deciles meet the 75.6 s p99 SLO. (Decision: One sizing rule for every strategy, judged per decile) | 2 | 19 | 21 (fixed) | **search 3 to 21** | not yet |
| 6 | At 9 GPUs the two hottest deciles sit at 87.7 and 77.2 s, over the SLO. At 10 (a pool of 8) the worst decile is 56.8 s. So the first count to pass is 10 (simulated, median of 30 runs). (Decision: One sizing rule for every strategy, judged per decile) | 2 | 19 | 21 (fixed) | **10 (first to pass)** | not yet |
| 7 | Co-locate: pinned GPUs plus the 19 tail models paired, 9 pairs and 1 single, so 12. Un-pairing adds GPUs up to 21. The first count tried, 12, already passed (worst decile 6.1 s, simulated): the pairing floor. (Decision: One sizing rule for every strategy, judged per decile) | 2 | 19 | 21 (fixed) | 10 (first to pass) | **12 (floor, passed)** |
| 8 | Both searches end at 21, so dedicate can tie but never win. Load used: 1/21 = 4.8%, 1/10 = 10%, 1/12 = 8.3% (derived). Models held set dedicate's and co-locate's counts; swap's comes from swap delay. | 2 | 19 | **21 (4.8% used)** | **10 (10%)** | **12 (8.3%)** |

Bold cells changed in that step.

**Takeaway:** Dedicate's 21 and co-locate's 12 follow from the hot rule and pairing; the simulator only showed the pairing floor passes the SLO (12 here; all 11 evaluable points). Only swap's 10 was searched. All unvalidated.

## System views (C4)

### Who and what the study touches (context)

One RunPod endpoint rents one RTX 4090 at a time; checkpoints come from a network volume. Artifact 1 is a reference line; artifact 5 reads this study's unvalidated cost per tenant.

- **Author**: designs, runs, publishes the miss
- **Placement study**: simulator, gate, three measured primitives
- **Reader**: platform engineers and managers
- **Network volume**: Qwen3 checkpoints, read offline
- **RunPod serverless**: one RTX 4090, EU-RO-1
- **Artifact 5**: reads cost per tenant per month
- **Artifact 1 stages**: 8B cold-start medians, a reference
- Author → Placement study: designs, runs
- Placement study → Reader: draft post + data
- Placement study → RunPod serverless: 248 paid jobs
- RunPod serverless → Network volume: loads weights
- Placement study → Artifact 5: cost_per_tenant.json
- Artifact 1 stages → Placement study: reference bar

### The runnable parts (container)

The laptop submits one job at a time; the worker runs a cell, swap, sleep switch or replay. After the stores everything is laptop CPU: the simulator, then one analysis file for figures, cost file and post.

- **Campaign driver**: laptop: committed design to jobs
- **RunPod endpoint**: 0 to 1 worker, pinned settings
- **Measure handler**: cell, swap, sleep or replay job
- **vLLM engines**: one, two co-resident, or swapped
- **data/a4 stores**: cells, swaps, sleep, replays (JSONL)
- **Placement simulator**: CPU only, measured inputs
- **Analysis**: analysis.json: sizes, verdict, money
- **Figures + post draft**: numbers rendered, never retyped
- Campaign driver → RunPod endpoint: one job at a time
- RunPod endpoint → Measure handler: starts
- Measure handler → vLLM engines: starts, loads, times
- Campaign driver → data/a4 stores: appends a record
- data/a4 stores → Placement simulator: curve, surface, swaps
- Placement simulator → Analysis: sized fleets
- data/a4 stores → Analysis: replays for the gate
- Analysis → Figures + post draft: one file

### Inside the simulator (placement/) (component)

Every fleet size of every strategy runs the same 30 traces (common random numbers), so strategies differ only in placement. Sizing then picks, per strategy, the smallest fleet whose every decile meets the SLO.

- **Traffic generator**: Zipf labels; spread or bursty
- **Placement families**: hot rule, then fleets by GPU count
- **Measured inputs**: solo curve, pair surface, 16 swaps
- **Grid-point evaluation**: every fleet, 30 runs, same traces
- **Event loop**: route by residency, LRU swap, drain-out
- **Per-decile p99**: withheld below the sample floor
- **Crossover + money**: cheapest per skew; monthly dollars
- **Sizing**: smallest fleet meeting SLO per decile
- Traffic generator → Grid-point evaluation: one trace per run
- Placement families → Grid-point evaluation: fleets, smallest first
- Grid-point evaluation → Event loop: a fleet and a trace
- Measured inputs → Event loop: service and swap times
- Event loop → Per-decile p99: latencies
- Per-decile p99 → Sizing: decile p99s
- Sizing → Crossover + money: GPUs per strategy

### One swap inside the simulator, in order (dynamic)

The gate replayed this path on one GPU, where the victim is trivial: LRU choice across GPUs was only unit-tested. The swap is a fixed stall of the GPU; nothing models what a swap costs the requests around it, the term the diagnosis says is missing.

- **1 Request for model x**: x is on no GPU; it waits in its queue
- **2 Pick the LRU victim**: the pool GPU used longest ago
- **3 Victim drains**: admits nothing; in-flight finish
- **4 Swap starts**: GPU stalls a drawn time, median 37.8 s
- **5 Two queues wait**: model x, and the evicted model
- **6 Swap done**: x resident; its queue is dispatched
- **7 Service time**: solo curve at dispatch, then frozen
- **8 Latency recorded**: arrival to done; every request served
- 1 Request for model x → 2 Pick the LRU victim: no swap pending
- 2 Pick the LRU victim → 3 Victim drains: victim chosen
- 3 Victim drains → 4 Swap starts: last one done
- 4 Swap starts → 5 Two queues wait: meanwhile
- 5 Two queues wait → 6 Swap done: stall ends
- 6 Swap done → 7 Service time: dispatch
- 7 Service time → 8 Latency recorded: done

## Core decisions

### A new fleet simulator, fed three measured primitives

**Problem:** The question is about fleets of 10 to 25 GPUs and 20 models; the August design planned to extend artifact 2's simulator.

**Options considered:**

- Extend artifact 2's simulator with a model dimension (the August design)
- Assume co-located models each get half the throughput
- A new loop with GPU identity: route by residency, swap by LRU, serve every request; swap, interference and KV split measured

**Chosen:** A new loop with GPU identity: route by residency, swap by LRU, serve every request; swap, interference and KV split measured

**Why:** Artifact 2's loop has no replica identity, and placement is exactly which GPU holds which model; changing it would also change artifact 2's code mid-experiment. The half-the-throughput guess is "almost certainly wrong in both directions" (design), so it was measured. Every request is served, because dropping unfinished ones would drop the cold-tail requests stuck behind swaps.

**Cost:** A new loop to build. Service time is frozen at dispatch, capacity is the top measured concurrency, and neighbour load between 0 and 16 is interpolated, not measured.

### One sizing rule for every strategy, judged per decile

**Problem:** At equal GPU counts the strategies cost the same, so each needs its own fleet size, by a rule that cannot decide the result by itself.

**Options considered:**

- Compare the strategies at one fixed number of GPUs
- Let only some strategies replicate hot models
- Size on the aggregate p99 of all requests
- In the bursty regime, let every strategy search up to a common cap
- One hot-model rule for all three; the smallest fleet whose every decile meets the SLO; bursty sizing on ON-period load

**Chosen:** One hot-model rule for all three; the smallest fleet whose every decile meets the SLO; bursty sizing on ON-period load

**Why:** Hot models get pinned GPUs in every strategy, so strategies differ only in how the rest are placed. The aggregate p99 is mostly popular models' requests, so it passes fleets that fail the hottest tenants (swap 9 GPUs, not 10; see How it works). On average load, a placeholder sweep left every bursty strategy dominated; the owner chose ON-period load.

**Cost:** Swap needs one GPU more at the reference point. Swap and co-locate search only up to dedicate's size, where their layouts become dedicate's, so dedicating can at best tie. Bursty s = 0.6 is not evaluable: a decile had too few requests for a p99.

### Two arrival regimes with the same per-model shares

**Problem:** Skew says how often each model is asked for, not whether its requests come together. Swapping by LRU depends on the second.

**Options considered:**

- Sweep Zipf skew alone
- At each skew, a spread regime (independent arrivals) and a bursty one (ON about a fifth of the time, 120 s bursts), with identical long-run shares

**Chosen:** At each skew, a spread regime (independent arrivals) and a bursty one (ON about a fifth of the time, 120 s bursts), with identical long-run shares

**Why:** Both generators take the same shares, so only clustering in time differs; skew alone "would earn the correct objection that the analysis ignores locality" (design §7). The simulator put the boundary between the regimes, with no crossover along skew in either.

**Cost:** Only two regimes were built, so the data cannot say where between them the winner changes. The gate's trace used a third shape (180 s bursts at duty 0.25).

### A small model, picked by a go/no-go, with KV that binds

**Problem:** Two of artifact 1's 8B models (about 16 GB each) do not fit a 24 GB card, and at the earlier short request the KV cache never fills.

**Options considered:**

- Artifact 1's Qwen3-8B
- A different card for the co-location arm
- Keep the inherited short request
- Qwen3-4B, falling back to Qwen3-1.7B, by a go/no-go fixed before reconnaissance; a request long enough that the split's KV binds

**Chosen:** Qwen3-4B, falling back to Qwen3-1.7B, by a go/no-go fixed before reconnaissance; a request long enough that the split's KV binds

**Why:** A different card would confound strategy with hardware. Pass: both engines healthy at 45% of memory, each with at least 16,384 KV tokens. The 4B pair left 9,456 and 9,520; the 1.7B pair passed. The shape rule chose 1,792 input and 256 output tokens: a split engine has room for 26 full-length requests, a lone one for 82.

**Cost:** A small-model result (3.8 GiB of weights); swap and co-location costs scale with size. Two warm engines did not fit at 45% each, so their KV was pinned to 55,104 tokens by a signed amendment.

### Load and SLO from a ranking-blind screen

**Problem:** On placeholder inputs both regimes came out degenerate: the 4 s SLO was shorter than one swap. Load and SLO decide whether the strategies can differ at all.

**Options considered:**

- Keep the placeholder design point (four GPUs of load, a 4 s SLO)
- A screen over 3 loads × 3 SLO multiples of the swap median that scores how many strategies each grid point tells apart, never which is cheaper

**Chosen:** A screen over 3 loads × 3 SLO multiples of the swap median that scores how many strategies each grid point tells apart, never which is cheaper

**Why:** A count of distinct fleet sizes cannot favour a strategy. Ties went to the earlier candidate: one GPU of load and twice the swap median, 75.6 s with the measured swaps. The screen's data was committed before the values it set.

**Cost:** Twice a swap absorbs a swap, which favours swapping: at the reference point the simulated swap fleet delivers about 45 s p99, the others 4 to 5 s. The measured sweep ran at this one SLO, and the screen ran on placeholder engines. At twice a swap even the simulated spread swap pool at s = 1.0, which never finds a model resident (hit rate 0.0), meets the SLO: its worst decile is 74.3 s against 75.6.

### Hold the simulator to a one-GPU replay; publish the miss

**Problem:** Fleet numbers mean something only if the simulator reproduces a real system; the design scaled artifact 2's gate down to one GPU.

**Options considered:**

- Draw each predicted swap from the measured distribution
- After the failure, re-validate with the swap time calibrated
- Three real replays of one 900 s bursty trace; predict with the median measured swap; publish whatever the verdict

**Chosen:** Three real replays of one 900 s bursty trace; predict with the median measured swap; publish whatever the verdict

**Why:** A model cannot be held tighter than three real repeats' spread, and a fixed swap time keeps the prediction deterministic. It failed: 10 of 13 judged bins outside, always too slow. Recalibrating would not rescue it: charged each repeat's own swaps, 12 of 13 still miss, the other way.

**Cost:** No fleet size is validated: the gate tested one GPU, three tenants and swapping only, at a burst shape and load the sweep did not use; co-location had two held-out cells, one missed. The diagnosis is exploratory.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Size every strategy by the same rule: hot models pinned the same way, then the smallest fleet that meets the SLO.
  - `sizing` One sizing rule for every strategy, judged per decile: Same hot-model rule and SLO search for all three.
  - `screen` Load and SLO from a ranking-blind screen: One SLO and one load apply to all three strategies.
- R2: Hold the latency target for every popularity decile of models, not only for all requests together.
  - `sizing` One sizing rule for every strategy, judged per decile: All ten deciles must meet the SLO.
- R3: Sweep popularity skew at two arrival regimes that give each model the same long-run share.
  - `regimes` Two arrival regimes with the same per-model shares: Same shares, different clustering.
- R4: Measure on the GPU what a swap, a co-located neighbour and a memory split cost; simulate only traffic, fleet dynamics and queueing.
  - `newsim` A new fleet simulator, fed three measured primitives: The three primitives enter as measurements.
  - `model` A small model, picked by a go/no-go, with KV that binds: All three strategies fit one card class.
- R5: Fix the rules before the data is analysed, and record any later change as a dated amendment (P2: amendment); trust the simulator only if it reproduces a real replay, and publish a miss.
  - `model` A small model, picked by a go/no-go, with KV that binds: Criterion and fallback committed before reconnaissance.
  - `screen` Load and SLO from a ranking-blind screen: Rule fixed before reconnaissance, output before measuring.
  - `gate` Hold the simulator to a one-GPU replay; publish the miss: Rule fixed before the replays; the failed verdict stands.
- R6: State the result as a decision rule in GPUs and monthly dollars, with every conversion assumption published.
  - `sizing` One sizing rule for every strategy, judged per decile: A sized fleet is a GPU count, priced at a published rate.

**Decisions and the concepts they use:**

- `newsim` A new fleet simulator, fed three measured primitives uses A swap, and the LRU pool: A swap is a stall drawn from 16 measured swaps.
- `newsim` A new fleet simulator, fed three measured primitives uses Co-location and the KV split: Co-located latency comes from the measured surface.
- `sizing` One sizing rule for every strategy, judged per decile uses The SLO, per popularity decile: The SLO is applied decile by decile.
- `sizing` One sizing rule for every strategy, judged per decile uses Zipf skew, and hot models: Skew decides which models are hot.
- `regimes` Two arrival regimes with the same per-model shares uses Spread and bursty arrivals: The two regimes differ only in timing.
- `regimes` Two arrival regimes with the same per-model shares uses Zipf skew, and hot models: Both regimes are swept over the same six skews.
- `model` A small model, picked by a go/no-go, with KV that binds uses Co-location and the KV split: The shape makes the split's KV ceiling bind.
- `screen` Load and SLO from a ranking-blind screen uses The SLO, per popularity decile: The SLO is a multiple of the swap median.
- `screen` Load and SLO from a ranking-blind screen uses A swap, and the LRU pool: The swap median sets the SLO's seconds.
- `gate` Hold the simulator to a one-GPU replay; publish the miss uses The validation gate, as used here: Three repeats, 30 s bins, at most half missing.
- `gate` Hold the simulator to a one-GPU replay; publish the miss uses A swap, and the LRU pool: Each swap was charged the 37.8 s median.

**Results and the decisions they support:**

- UNVALIDATED: GPUs each strategy needs, by skew and regime → `sizing` One sizing rule for every strategy, judged per decile, `regimes` Two arrival regimes with the same per-model shares
- UNVALIDATED: sizing on the aggregate p99 hides the hottest tenants → `sizing` One sizing rule for every strategy, judged per decile
- Measured: a busy neighbour roughly doubles latency at every load → `newsim` A new fleet simulator, fed three measured primitives, `model` A small model, picked by a go/no-go, with KV that binds
- Measured: where a 37.8 s swap goes → `newsim` A new fleet simulator, fed three measured primitives
- The gate: the simulator against three real replays → `gate` Hold the simulator to a one-GPU replay; publish the miss
- EXPLORATORY, SIMULATED: how much interference co-locating can absorb → `newsim` A new fleet simulator, fed three measured primitives

## Implementation flow

11 steps in 6 phases, 5 milestones.

Milestones: 4. Pre-register step 1, then step 2's rules (2026-10-04); 6. Screen load and SLO; fix step 2's values (2026-10-05); 8. Cells, swaps, sleep; two amendments, re-runs (2026-10-05 to 10-06); 9. Replay three times; the gate fails (2026-10-06); 11. Figures, spend, draft post; sensitivity run (2026-10-07).

### Phase 1 of 6: Design (2 steps)

1. **Frame three strategies, two regimes, one gate**: Dedicate, swap with LRU, or co-locate; Zipf skew at two arrival regimes; three measured primitives; a one-GPU replay gate. Approved, not funded.
   - Output: the design spec and its definition of done
   - When: 2026-08-18
   - Decision: `regimes` Two arrival regimes with the same per-model shares
   - Evidence: 2a44aa0ead (design spec)
2. **Reconcile with the code; plan three stages**: Scope amendment: a new simulator, one sizing rule, Qwen3-4B with a 1.7B fallback. Then plans 1 to 3, a timeline, and §14: bursty sizing on ON-period load.
   - Output: scope amendment, three plans, the §14 decision
   - When: 2026-10-03 to 10-04
   - Decision: `newsim` A new fleet simulator, fed three measured primitives
   - Evidence: ffad6449c4 (scope amendment, plan 1); 0fa8786b50 (plans 2, 3, timeline, §14)

### Phase 2 of 6: Build with no GPU (2 steps)

3. **Build simulator, worker jobs and analysis offline**: Traffic, placement families, event loop, sizing; swap, cell and replay jobs; screen, gate, analysis, figures. The sweep refuses placeholder inputs unless told.
   - Output: placement/ and placement_measure/, run end to end on placeholders
   - When: 2026-10-04
   - Decision: `sizing` One sizing rule for every strategy, judged per decile
   - Evidence: a338f3d232 (simulator); d7ac7fda0d (per-decile sizing); 5681fde3c9 (replay driver); 291c7a0cac (validation gate); dab943ca6e (one analysis script)
4. **Pre-register step 1, then step 2's rules** [MILESTONE]: Step 1 (models, memory split, go/no-go) landed among the first code commits, before reconnaissance; step 2's rules that evening.
   - Output: docs/experiment-a4.md: step 1 and step 2's rules
   - When: 2026-10-04
   - Decision: `model` A small model, picked by a go/no-go, with KV that binds
   - Evidence: c356e4b609 (step 1, before reconnaissance); 39e88f9753 (step 2 rules)

### Phase 3 of 6: Reconnaissance (2 steps)

5. **Reconnaissance: 4B fails, 1.7B passes**: Two 4B engines left 9,456 and 9,520 KV tokens of 16,384 needed; the 1.7B pair passed, a pre-registered branch. Eviction missed its threshold, so swaps are warm only.
   - Output: docs/recon-a4.md: Qwen3-1.7B, warm swaps, sleep mode works
   - When: 2026-10-04 to 10-05
   - Decision: `model` A small model, picked by a go/no-go, with KV that binds
   - Evidence: dcd528cb99 (jobs rebuilt for the fallback); c60602db50 (captures and record)
6. **Screen load and SLO; fix step 2's values** [MILESTONE]: On placeholder engines and recon's swaps, the screen chose one GPU of load and twice the swap median. Values committed before the first measurement run.
   - Output: data/a4/screen.json; step 2 values: 1,792 + 256 tokens, grids, the gate
   - When: 2026-10-05
   - Decision: `screen` Load and SLO from a ranking-blind screen
   - Evidence: d16ff5edb1 (screen); b17c8aca20 (step 2 values)

### Phase 4 of 6: Measure (2 steps)

7. **Pin the pair's KV after the first cells fail**: Two engines that both hit the compile cache ran out of memory. KV pinned to the registered 55,104 tokens; a probe confirmed it; the owner signed.
   - Output: amendment 2026-10-05 and kvpin-probe.jsonl
   - When: 2026-10-05
   - Decision: `model` A small model, picked by a go/no-go, with KV that binds
   - Evidence: 8e8b3ac7de (drafted); 4ccbbadc3c (signed after the probe)
8. **Cells, swaps, sleep; two amendments, re-runs** [MILESTONE]: After the cell runs, before their analysis: a saturated neighbour counts and its ramp wait may lengthen. 44 re-runs; first tries of two designs lost to a zero balance.
   - Output: every cell, held-out and solo included, with 3+ valid repeats; 16 swaps, 8 sleep switches
   - When: 2026-10-05 to 10-06
   - Decision: `newsim` A new fleet simulator, fed three measured primitives
   - Evidence: b8b74ac0b1 (validity and ramp amendments); 4778350b74 (cells, swaps, sleep stored); 2389defca2 (failed for want of credit); f5efb1c632 (every cell 3+ valid)

### Phase 5 of 6: Validate (2 steps)

9. **Replay three times; the gate fails** [MILESTONE]: Three real replays on one pod: 10 of 13 judged bins outside the band, the prediction always slower. Swaps: 11 predicted, 10 real.
   - Output: replay.jsonl; a failed verdict
   - When: 2026-10-06
   - Decision: `gate` Hold the simulator to a one-GPU replay; publish the miss
   - Evidence: 8e40c92a28 (validation trace); e3ab099c8d (three replays)
10. **Diagnose the miss; keep the verdict**: Exploratory: a 30% faster curve does not close it; replay swaps took about 25 s, not 37.8; at their own swap time 12 of 13 still miss.
   - Output: the swap-cost finding; analysis.json keeps the failed verdict
   - When: 2026-10-07
   - Decision: `gate` Hold the simulator to a one-GPU replay; publish the miss
   - Evidence: 300c689eac (diagnosis, exploratory); 21c8962516 (analysis: gate failed, one cell missed)

### Phase 6 of 6: Write up (1 step)

11. **Figures, spend, draft post; sensitivity run** [MILESTONE]: Figures, billing-API spend and the draft post; after review, an exploratory interference sensitivity run. Unpublished: it waits on artifact 2's post.
   - Output: post-a4.md (draft), spend-a4.md, dod-a4.md, the sensitivity finding
   - When: 2026-10-07
   - Decision: `gate` Hold the simulator to a one-GPU replay; publish the miss
   - Evidence: 4f61a48675 (figures); 9251b059ae (final billing read); d8c44702aa (post draft); 6ca0f654ef (review edits, sensitivity finding)

## Results as meaning

### UNVALIDATED: GPUs each strategy needs, by skew and regime

- Axis: Simulated by a model that failed its gate. Swap's point is the smallest pool whose every popularity decile meets the 75.6 s p99 SLO, over 30 runs. Dedicate's is fixed by the hot-model rule (pinned GPUs plus one per other model). Co-locate's is its pairing floor (pinned GPUs plus half the rest, paired), where the SLO held at every evaluable point.
- Read it as: In each regime one strategy is cheapest at every evaluable skew: co-locate when spread, swap when bursty. Dedicating, which can at best tie by construction, needs about twice the cheapest. Spread swap's peak at s = 1.25 was not diagnosed.
- How it is computed: Reference point, bursty s = 1.0: 21, 10, 12 GPUs. One GPU-month = $1.1095 × 730 h = $809.935; 21 × 809.935 / 20 tenants = $850.43; dedicate costs $8,909.28 a month more than swap.
- Axes: x is Zipf skew s; y is GPUs to meet the SLO in every decile (GPUs)
- spread: dedicate: 0.6: 20, 0.8: 20, 1.0: 20, 1.25: 20, 1.5: 20, 2.0: 20
- spread: swap: 0.6: 13, 0.8: 13, 1.0: 13, 1.25: 18, 1.5: 17, 2.0: 15
- spread: co-locate: 0.6: 10, 0.8: 10, 1.0: 10, 1.25: 10, 1.5: 10, 2.0: 10
- bursty: dedicate: 0.8: 21, 1.0: 21, 1.25: 23, 1.5: 24, 2.0: 25
- bursty: swap: 0.8: 9, 1.0: 10, 1.25: 12, 1.5: 13, 2.0: 13
- bursty: co-locate: 0.8: 12, 1.0: 12, 1.25: 14, 1.5: 15, 2.0: 16
- Reference: reference point; the gate's skew at x = 1.0
- Note: SIMULATED, FAILED VALIDATION. Bursty s = 0.6 is not evaluable: some decile had too few requests for a p99 in some run.
- So: see decisions `sizing`, `regimes`

### UNVALIDATED: sizing on the aggregate p99 hides the hottest tenants

- Axis: Simulated. Swap's p99 per decile at 9 GPUs (what an aggregate-p99 rule picks) and at 10 (the per-decile rule).
- Read it as: At 9 GPUs deciles 1 and 2 breach (87.7 and 77.2 s); the coldest does not. The design expected the cold tail to suffer; the post does not explain why the hottest do.
- How it is computed: A decile is 2 of 20 models: each run's p99, then the median over 30 runs.
- Axes: x is popularity decile (1 = hottest two models); y is p99, median of 30 runs (s)
- swap, 9 GPUs: sized on the aggregate p99: 1: 87.7, 2: 77.2, 3: 61.7, 4: 54.8, 5: 51.4, 6: 58.0, 7: 52.9, 8: 51.1, 9: 54.2, 10: 55.6
- swap, 10 GPUs: sized per decile: 1: 44.6, 2: 56.8, 3: 46.5, 4: 43.8, 5: 44.0, 6: 39.9, 7: 40.1, 8: 39.7, 9: 41.7, 10: 46.5
- Reference: SLO 75.6 s at y = 75.6 s
- Note: SIMULATED, FAILED VALIDATION. Swap at the reference point, bursty s = 1.0.
- So: see decision `sizing`

### Measured: a busy neighbour roughly doubles latency at every load

- Axis: Measured on RunPod: median latency of 1,792 + 256-token requests, 3 or more runs per point. Split: two engines at 45% of memory, KV pinned to 55,104 tokens.
- Read it as: A busy neighbour makes a model 2.0 to 2.4 times slower at every load, even one request; 32 and 64 match because the neighbour sits at its ceiling. An idle neighbour costs nothing up to 32; at 64 the split engine is slower even alone (8.63 against 7.66 s), probably queueing behind its ceiling of 26.
- How it is computed: Own 1: 2.95 / 1.27 = 2.3. KV: 168,464 / 2,048 = 82 alone, 55,104 / 2,048 = 26 split; 168,464 / 55,104 = 3.1 = 2.6 (168,464 / 64,976, fixed cost) × 1.18 (64,976 / 55,104, the pin).
- Axes: x is own requests in flight (log scale); y is median latency per request (s)
- alone, full memory: 1: 1.27, 2: 1.5, 4: 1.68, 8: 2.06, 16: 2.83, 32: 4.35, 64: 7.66, 128: 14.39
- split, neighbour idle: 1: 1.27, 2: 1.5, 4: 1.68, 8: 2.06, 16: 2.83, 32: 4.3, 64: 8.63
- split, neighbour at 16: 1: 2.95, 2: 3.16, 4: 3.43, 8: 4.51, 16: 6.13, 32: 8.99, 64: 18.0
- split, neighbour at 64: 1: 3.02, 2: 3.27, 4: 3.56, 8: 4.68, 16: 6.36, 32: 9.33, 64: 18.68
- held out: measured (points): 24: 8.07, 48: 16.54
- held out: surface's prediction (points): 24: 7.85, 48: 13.77
- Reference: KV ceiling, split at x = 26
- Reference: KV ceiling, alone at x = 82
- Note: Held-out cells: own 24 with neighbour 48 (passed), own 48 with neighbour 24 (missed, above the split ceiling of 26). A cell passes if the prediction is inside its repeats' range or within 10% of their median.
- So: see decisions `newsim`, `model`

### Measured: where a 37.8 s swap goes

- Axis: Median seconds per stage. Swap: 16 warm swaps of Qwen3-1.7B. Cold start: artifact 1's arm C cold start (P1: coldstart) (Qwen3-8B), a reference, not a baseline.
- Read it as: A swap skips platform scheduling and compiling (a cache hit) but re-pays process start, imports and the health check: 27.8 of 37.8 s. Artifact 1's launch segment is not a weight download: 16.7 of its 21.3 s is server start-up before the model-loading line (arm C medians), which a swap also pays.
- How it is computed: Stage medians: 0.8 + 0.04 + 27.8 + 2.2 + 6.8 + 0.3 = 37.94 s, not the 37.8 s median swap (medians do not add). Cold start: 4.8 + 21.3 + 8.6 + 4.1 + 0.3 = 39.1 s.
- Swap, 1.7B: Teardown 0.8, Memory release 0.04, Process start, imports, health 27.8, Weight load 2.2, Engine init, rest 6.8, torch.compile (cache hit) 0.3 (s)
- Cold start, 8B (A1): Platform (not in a swap) 4.8, Launch to model loaded 21.3, Engine init (S4) 8.6, Health check (S5) 4.1, First request 0.3 (s)
- Drawn as one segment, Teardown + release: Teardown + Memory release
- Drawn as one segment, Weights, init, compile: Weight load + Engine init, rest + torch.compile (cache hit)
- Drawn as one segment, Init, health, first request: Engine init (S4) + Health check (S5) + First request
- So: see decision `newsim`

### The gate: the simulator against three real replays

- Axis: One GPU, three tenants, a 900 s bursty trace with real swaps. Predicted: the simulator, every swap at 37.8 s. Real: three repeats on one pod.
- Read it as: All ten misses sit above the band: the simulator predicted the engine slower, by up to 67.8 s. Three late bins agree. The swap count agreed (11 against 10); the latency did not.
- How it is computed: Pass needs at least 10 judged bins and at most half missing: 10 / 13 = 0.77. Largest miss, bin 180 to 210 s: 166.1 − 98.3 = 67.8 s.
- Axes: x is start of 30 s bin, scheduled arrival (s); y is median latency in the bin (s)
- simulator's prediction (points): 0.0: 31, 30.0: 10, 60.0: 70, 90.0: 67, 120.0: 121, 150.0: 135, 180.0: 166, 330.0: 54, 360.0: 36, 690.0: 34, 720.0: 23, 750.0: 13, 780.0: 7
- real: fastest of 3 repeats (points): 0.0: 20, 30.0: 2, 60.0: 44, 90.0: 55, 120.0: 67, 150.0: 85, 180.0: 90, 330.0: 27, 360.0: 5, 690.0: 28, 720.0: 20, 750.0: 13, 780.0: 4
- real: slowest of 3 repeats (points): 0.0: 24, 30.0: 2, 60.0: 53, 90.0: 65, 120.0: 80, 150.0: 89, 180.0: 98, 330.0: 28, 360.0: 6, 690.0: 31, 720.0: 23, 750.0: 16, 780.0: 8
- Note: Judged bins only, rounded to whole seconds; 16 bins had too few requests to judge. The band is fastest to slowest of the three real repeats.
- So: see decision `gate`

### EXPLORATORY, SIMULATED: how much interference co-locating can absorb

- Axis: Simulated, exploratory. At 1, any busy neighbour costs what a neighbour at 16 costs (the worst reading of the unmeasured range); then that latency times 4 or 8.
- Read it as: At 1 the fleets match the registered surface, so the unmeasured range does not matter at this SLO. Bursty co-locate loses to swap at 4 times; spread survives 4 times by one GPU and loses at 8.
- How it is computed: Bursty co-locate 12 → 20 GPUs at 4 times (swap stays 10); spread 10 → 12 at 4 times and 16 at 8 times (swap 13).
- Axes: x is busy-neighbour latency, times the measured (step surface); y is GPUs to meet the SLO (GPUs)
- spread: dedicate: 1: 20, 4: 20, 8: 20
- spread: swap: 1: 13, 4: 13, 8: 13
- spread: co-locate: 1: 10, 4: 12, 8: 16
- bursty: dedicate: 1: 21, 4: 21, 8: 21
- bursty: swap: 1: 10, 4: 10, 8: 10
- bursty: co-locate: 1: 12, 4: 20, 8: 21
- Note: EXPLORATORY: one skew (s = 1.0), 6 runs, one SLO, after the analysis. The multipliers are not measurements.
- So: see decision `newsim`

## Interview card

**30-second pitch:** I asked how to place twenty small LLMs on rented GPUs: give each its own GPU, swap models in and out of a shared pool, or pair them on one card. I measured what the hardware charges for a swap and for a busy neighbour, and fed that into a fleet simulator. Its answer: how traffic arrives picks the winner, not how skewed it is. Pair models when requests are spread out, swap when they come in bursts; dedicating, which by construction can at best tie, never won. But the simulator failed its own pre-registered test, 10 of 13 bins, so I publish the GPU counts as unvalidated.

**2-minute version:** For 20 small models on RTX 4090s I compared dedicating a GPU each, swapping through a shared LRU pool, and co-locating two per GPU, across Zipf skew and two arrival patterns with the same per-model shares, spread and bursty. On the GPU I measured a swap (median 37.8 s, mostly process start), a busy neighbour (2.0 to 2.4 times slower) and the memory split (KV cache 168,464 down to 55,104 tokens). A new simulator sized each strategy to the smallest fleet where every popularity decile meets a 75.6 s p99; aggregate sizing would have let the hottest tenants breach. Simulated result: co-locate when spread, swap when bursty, dedicating about twice the cheapest. But my pre-registered gate, three real replays on one GPU, failed: 10 of 13 bins outside the band. An exploratory diagnosis found the simulator charged 37.8 s per swap where the replay pod took about 25 s, and even at that 12 of 13 still missed; the likely gap is a term for what a swap costs nearby requests, unmeasured. So the ordering is wide and the counts are unvalidated. The paid runs cost $25.23.

**Hard follow-ups:**

- Q: Why trust a simulator that failed its gate?
  A: For GPU counts, I don't: the gate failed at its one point (one GPU, three tenants, swapping only), the fleets are 10 to 25 GPUs, and co-location had two held-out cells, one missed. The ordering is wide, about twice, but I did not test whether the model's error leaves it unchanged. The measured swap, slowdown and KV split stand.
- Q: Why is dedicating never cheapest?
  A: Partly by construction: swap and co-locate search only up to dedicate's size, where their layouts become dedicate's, so dedicating can at best tie (scope amendment §7; the post does not say this). Only swap's count came from the SLO search (see How it works). The simulated margin is the point: co-locate's 3 to 6 s latency met the 75.6 s SLO at half of dedicate's 20 GPUs.
- Q: What would change the winner?
  A: Arrival timing (only two regimes built); the SLO (twice a swap favours swapping, and the sweep ran at one SLO); interference (exploratory: four times the busy-neighbour latency loses co-location the bursty regime, eight the spread one); model size (a 1.7B result).
- Q: Why did the gate fail?
  A: Exploratory, after the verdict. A host up to 30% faster does not close it. The gate charged 37.8 s per swap; replay swaps took about 25 s. Charged that, the simulator is too fast and 12 of 13 bins still miss: probably it lacks a term for what a swap costs nearby requests, which I did not measure.
- Q: You switched models and changed rules mid-campaign. Isn't that moving the goalposts?
  A: The 1.7B switch was a branch committed before reconnaissance. The KV pin came after the first co-located runs crashed, before any valid co-located data, confirmed by a probe and signed; the validity and ramp amendments came after the cell runs, before their analysis. All dated in git; the re-runs cost 7.45 unplanned GPU-hours.
- Q: What would you do next?
  A: Measure what a swap costs the requests around it, on one pod with the replay's own requests: the likely missing term. A recalibrated re-run would not pass. Co-location needs its own replay.

**Limits (what I must not claim):** Every GPU count, dollar figure and the decision rule are from a simulator that failed its gate (10 of 13 bins), at one GPU, three tenants and swapping only, with a burst shape and load the sweep did not use; co-location had two held-out cells, one missed, and no replay; LRU victim choice across GPUs was only unit-tested. Whether the model's error leaves the ordering unchanged was not tested. Qwen3-1.7B, not the registered 4B; one size and request shape; LRU only; one GPU class and datacenter; warm swaps only; swap time varies about 50% by pod; one SLO, twice a swap, which favours swapping; two arrival regimes. Sleep mode measured, never simulated. The diagnosis and the interference sensitivity are exploratory. The post is an unpublished draft.

## Recall questions

- Q: Why can the strategies not be compared at the same number of GPUs?
  A: At equal counts they cost the same by construction. Each is sized to its smallest fleet meeting the SLO, and cost follows from that count.
- Q: Spread and bursty traffic give each model the same share. What differs, and what does it change?
  A: Timing. In a burst one swap-in serves many requests; scattered, a model is loaded, evicted and loaded again (design module 4). Simulated: swap cheapest when bursty, co-locate when spread.
- Q: At the reference point, what does sizing on the aggregate p99 get wrong?
  A: In the simulator it picks 9 GPUs for swap, and the two hottest deciles breach the SLO; per-decile sizing needs 10 (numbers in How it works). R2.
- Q: Which cold-start stages does a swap skip, and what does it still pay?
  A: It skips platform scheduling and compiling (a cache hit). It re-pays process start, imports and the health check, 27.8 of 37.8 s.
- Q: Splitting memory halves each engine's share. Why does its KV cache shrink 3.1 times?
  A: About 2.6 times is a fixed cost, roughly 3.6 GiB outside the KV cache at either budget, which comes off the smaller budget first. The other 1.18 is the pin to the compiled engine's 55,104 tokens, which lets two graph captures fit: 168,464 to 55,104 tokens, 82 to 26 requests.
- Q: A busy neighbour makes a model about twice as slow. Why does co-locating still halve the simulated spread fleet?
  A: SLO headroom, not low load: 3 to 6 s against 75.6 s. In the exploratory run it held at the worst reading of the unmeasured range.
- Q: Why can dedicating at best tie under this sizing rule?
  A: Swap and co-locate search only up to dedicate's size, where their layouts become dedicate's and serve identically, so dedicating can tie but never win. The simulated margin is the point.
- Q: The gate charged 37.8 s per swap; the replay pod's swaps took about 25 s. Why does charging 25 s not rescue the gate?
  A: Then it predicts faster than real and 12 of 13 bins still miss: no fixed swap cost matches. The exploratory diagnosis blames a missing term for a swap's effect on nearby requests, unmeasured.
- Q: What did the gate test, and what did it never test?
  A: One GPU, three tenants, swapping, 180 s bursts at 0.3 of a GPU. Never co-location (two held-out cells), never a multi-GPU fleet or LRU victim choice across GPUs, never the swept 120 s bursts.
- Q: Which requirement breaks if the GPU counts are presented as findings, and what may be said instead?
  A: R5. The ordering may be called wide but unvalidated; the measured primitives stand.

Sources: see the page

## Interview mode (paste this to an AI chat)

You are my interview coach. The brief above is the only ground truth about my project;
do not add facts it does not contain, and say "the brief does not say" when asked.

Settings (I may change these at any time):
- AUDIENCE: hiring manager | senior peer | skeptic
  (hiring manager: impact, ownership, trade-offs, what I would do differently;
   senior peer: technical depth on the decisions; skeptic: pushes on every hand-wave)
- DEPTH: pitch (30 s answer) | standard (2 to 5 minutes of follow-ups) | deep (three
  levels of "why")
- MODE: ask (you interview me) | quiz (recall questions, one at a time) | grade (I paste
  an answer, you grade it against the brief)

Default: AUDIENCE = hiring manager, DEPTH = standard, MODE = ask.

Rules:
1. One question at a time. Wait for my answer.
2. Do not reveal the brief's answers before I have answered.
3. After each answer, say what was solid, what was missing, and which stated limit I
   should have admitted. Keep it to five lines.
4. Never let me claim more than the brief supports. If I overstate, ask me to cut it
   back, and quote the limit.
5. I am a software engineer, not a researcher: reward clear reasoning about decisions
   and trade-offs over memorised numbers. A number is only useful to me as evidence for
   an answer.
6. Start now with my current settings and the first question.
