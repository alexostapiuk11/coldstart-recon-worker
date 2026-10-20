# How many LoRA adapters actually fit on one GPU: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: LLM serving on a GPU (P1), How these experiments earn trust (P2).

## Why it exists

**Question:** When one GPU serves many customers' fine-tunes as LoRA adapters on one shared base model, what does each added adapter cost: holding it on the GPU, or serving it in the same batch (P1: batching) as the others? How many tenants does that leave per GPU, at what price? Measured on Qwen3-4B, one RTX 4090, vLLM (P1: vllm) 0.27.1.

**Requirements that drove everything:**

- Split what adapters cost into what registering them costs and what serving many of them in one batch costs, inside the same server start. *Why:* Most benchmarking conflates adapters loaded with adapters active together. The design's prior was that mixing adapters in a batch costs more than loading them, and only a split can test it.
- Sweep with synthetic adapters only after a pre-registered check shows they serve like real ones. *Why:* The sweep needs 64 adapters of one shape for one base model; of 261 public adapters for Qwen3-4B, 7 qualified. Without a check, "those aren't real adapters" stays open.
- Fix the knee threshold, the gate's margin and verdict rule, the SLO and the tenant assumptions before the first measured run; later changes are dated amendments (P2: amendment). *Why:* Otherwise the knee, and the tenants per GPU it sets, could be tuned after the data.
- Convert the knee into tenants per GPU and cost per tenant per month, beside artifact 4's cost of dedicated and swapped whole models, with every assumption published. *Why:* That three-way number is what a team building a per-customer fine-tune product needs; the design calls it the strongest business number in the portfolio.
- Hold image, model, GPU, rank, target modules, request shape and memory budget fixed; prime the compile cache (P1: compile) per slot count and exclude any start that compiled cold. *Why:* In artifact 1 a cold compile cut KV cache (P1: kvcache) capacity by about as much as 16 slots' buffers take here, so one cold start would fake a memory step.
- Report medians across server starts with bootstrap intervals (P2: interval), never means, and re-derive every published number from committed data with no GPU. *Why:* Latency is right-skewed, so a mean describes no real start; a number a reader cannot re-derive must be taken on trust.

## Need to know first

- **LoRA adapter and its rank**: A fine-tune leaves each base matrix W frozen and adds a low-rank detour: `y = W·x + (α/r)·B·(A·x)`, A shaped r × in, B shaped out × r. **Rank** r is 16 here: 33,030,144 numbers across seven projections in 36 layers (the repo's Qwen3-4B shapes), 63 MiB at 2 bytes, against 7.63 GiB for the loaded model at 1 slot. Each slot's buffers took 79 MiB (measured; the extra 16 is unexplained). vLLM computes every adapter at the slot's buffer rank, so the work is set by shape, not by the numbers inside.
- **Registered versus active, and the slot cap**: **Registered**: loaded into one of `max_loras` GPU slots, each a buffer preallocated at `max_lora_rank` that takes GPU memory (P1: hbm) used or not. **Active**: the distinct adapters among requests batched together right now. In vLLM 0.27.1 `max_loras` is also the cap on distinct adapters per batch, so the two are one knob. `max_cpu_loras` is a host-memory tier behind the slots; here it equals N, so nothing swaps.
- **Shared versus mixed batch**: Each decode step reads the base weights once for all requests in the batch, so batching is nearly free throughput until compute or KV runs out (general GPU behaviour, not measured here). Each distinct adapter is not shared: it needs its own small multiply over only its requests (63 MiB of weights at rank 16, 3.9 GiB for 64). Consistent with the data, not measured; vLLM 0.27.1 source, may differ.
- **Heterogeneity cost and registered-slot cost**: **Concentrated** regime: all load on one adapter. **Spread**: round-robin over all N. **Heterogeneity cost** at N = spread minus concentrated, in the same start (median of paired gaps; −1,290 at 64 slots). **Registered-slot cost** = concentrated at N minus concentrated at 1 slot, across starts: what slots cost with one adapter carrying all the load (−450 at 64).
- **The knee**: Loss per doubling: m(N) = 1 − T(N) / T(N/2), with T the spread regime's throughput. The **knee** is the first N whose point estimate exceeds τ = 10%, fixed in advance, so it lies between N/2 and N (the sweep only doubles). Slots below it set the slot bound on tenants.
- **Little's law, as used here**: **Requests in the system = arrival rate × time each spends there.** At 8 slots, 64 in flight and about 204 completed a second means about 0.31 s each. One tenant at peak, 0.114 requests a second, keeps about 0.036 requests in the system; KV room for 9 long (8,192-token) requests then fits 250 tenants. A real long request would stay longer than 0.31 s, so that bound is generous.
- **Equivalence gate: pass, fail, inconclusive**: Per start: (synthetic − real) / real for TTFT p50 and throughput. **Pass**: the median's 90% interval lies inside ±5% for both. **Resolution check**: the second real phase against the first must also fit ±5%; if not, the gate cannot resolve its own margin and the verdict is **inconclusive**, not pass. Resolved but not inside: **fail**.

## How it works

Numbers from several server starts on one RTX 4090 (each slot count is its own start). Watch what moves when slots are only held, and what moves when they are all in the batch.

| Step | What happens | GPU slots held | Adapters in the batch | LoRA slices (0.27.1) | KV tokens: room/used | Throughput, tokens/s | In flight ÷ adapters |
|---|---|---|---|---|---|---|---|
| 1 | One slot, one adapter, 64 requests in flight: the baseline. Every adapter here sits resident in a GPU slot; none is swapped in from CPU memory (`max_cpu_loras` = `max_loras` = N). | 1 | 1 | 2 (1 working) | 78,208 / ~2,048 | 3,577 | 64 |
| 2 | Register 64 slots but keep sending all traffic to one adapter. Buffers eat KV room, yet 64 requests use only ~2,048 tokens of it. The kernels launch 65 slices (vLLM 0.27.1 source, may differ). (Decision: Memory as capacity; name the slot cost) | **64** | 1 | **65 (1 working)** | **42,864 / ~2,048** | **3,127** | 64 |
| 3 | Now spread: each request uses its own adapter, so 64 small multiplications, not one larger (why; consistent with the data, not measured). Mixing costs about 1,290. (Decision: Separate the counts by traffic) | 64 | **64** | **65 (64 working)** | 42,864 / ~2,048 | **1,835** | **1** |
| 4 | Back to the sweep, spread regime, every registered adapter active. At 8 slots the loss against 4 slots is 5.3%, under the 10% threshold. | **8** | **8** | **9 (8 working)** | **74,288 / ~2,048** | **3,260** | **8** |
| 5 | At 16 slots the loss against 8 is 1 − 2,911 / 3,260 = 10.7%: the first doubling past 10%. Its interval, 9.2% to 11.5%, does not clear 10%, so the crossing is unresolved; the knee rule uses the point estimate. (Decision: A knee rule erring toward fewer tenants) | **16** | **16** | **17 (16 working)** | **69,968 / ~2,048** | **2,911** | **4** |
| 6 | The knee lies between 8 and 16, so the bound is 8. A floor: 8 adapters active in one batch at 64 in flight, all resident; CPU swapping not measured. Not a customer count. | **8** | **8** | **9 (8 working)** | **74,288 / ~2,048** | **3,260** | **8** |

Bold cells changed in that step.

**Takeaway:** Holding 64 slots costs 450 tokens/s; mixing 64 adapters in one batch costs about 1,290, 2.87 times more. Splitting the batch by adapter fits that cost, but only its size was measured, not its breakdown.

## System views (C4)

### Who and what the study touches (context)

RunPod rents the GPU one server start at a time; artifact 4's committed cost file supplies the dedicated and swapped costs; output is a post and the raw data.

- **Author**: designs, runs, publishes
- **LoRA capacity study**: 1 to 64 adapters on one base model
- **Reader**: teams pricing per-customer fine-tunes
- **Artifact 4 cost file**: dedicated, swapped: simulated, unvalidated
- **RunPod serverless**: one RTX 4090 job at a time
- **Hugging Face Hub**: Qwen3-4B and 4 real adapters, pinned
- **Network volume**: model and compile caches
- Author → LoRA capacity study: designs, runs
- LoRA capacity study → Reader: post + raw data
- Artifact 4 cost file → LoRA capacity study: cost rows
- LoRA capacity study → RunPod serverless: one start per job
- RunPod serverless → Hugging Face Hub: downloads
- RunPod serverless → Network volume: caches

### The runnable parts (container)

The laptop runner runs the gate first, refuses the campaign until it passes, submits one job per server start and appends each result to a store. Analysis runs on the laptop only.

- **Laptop runner**: gate first; campaign only after a pass
- **RunPod endpoint**: pinned; later CUDA 13.0 hosts only
- **Worker container**: a5_handler: one server start per job
- **vllm serve + bench**: server and load generator together
- **data/a5 stores**: priming, gate pilot, gate, campaign
- **Analysis + figures**: analysis.json, four figures, post table
- **Artifact 4 cost file**: dedicated and swapped rows
- Laptop runner → RunPod endpoint: job in, result out
- RunPod endpoint → Worker container: starts
- Worker container → vllm serve + bench: runs
- Laptop runner → data/a5 stores: appends a record
- data/a5 stores → Analysis + figures: reads
- Artifact 4 cost file → Analysis + figures: cost rows

### Inside the equivalence gate (component)

Every gate start registers the same 8 adapters and runs four spread phases. Two numbers per start feed the verdict: synthetic against real, and the second real phase against the first. Only a pass lets the runner start the sweep. The failure-streak stop was added by Amendment 3.

- **Gate schedule**: 196 scheduled; phase order from run index
- **8-slot server start**: 4 real (r00-r03), 4 synthetic (s00-s03)
- **Four spread phases**: 2 over real, 2 over synthetic, shuffled
- **Failure, cold rules**: bad requests out; cold compiles excluded
- **Failure-streak stop**: 3 failed starts in a row: stop
- **Resolution check**: 2nd real phase vs 1st, per start
- **Per-start statistic**: (synthetic - real) / real, TTFT and tokens/s
- **90% bootstrap**: interval of the median across starts
- **Verdict**: inside ±5%? resolved? pass, fail, inconclusive
- **Campaign guard**: the sweep runs only after a pass
- Gate schedule → 8-slot server start: run index
- 8-slot server start → Four spread phases: healthy
- 8-slot server start → Failure-streak stop: failed
- Four spread phases → Failure, cold rules: per-request arrays
- Failure, cold rules → Per-start statistic: usable start
- Failure, cold rules → Resolution check: real phases
- Per-start statistic → 90% bootstrap: one per start
- Resolution check → 90% bootstrap
- 90% bootstrap → Verdict: two intervals
- Verdict → Campaign guard: pass

### One sweep server start, in order (dynamic)

Steps 1 and 8 run on the laptop, 2 to 7 in the rented container. The regimes differ only in step 6: which adapters the load generator lists. KV capacity and the warm/cold reading come from the startup log, parsed in step 8; KV is never measured under load.

- **1 Runner picks a start**: slot count N, run index, phase order
- **2 Write adapters**: N synthetic, seeded: rank 16, 7 projections
- **3 Start vllm serve**: N slots, all resident; memory budget 0.80
- **4 Keep startup log**: KV tokens, compile time: parsed later
- **5 Untimed warm-up**: 2 requests to every adapter
- **6 Four timed phases**: 2 one-adapter, 2 spread, order shuffled
- **7 Result returned**: raw per-request arrays, gauge, host
- **8 Record appended**: log parsed; one line; failures kept
- 1 Runner picks a start → 2 Write adapters: job
- 2 Write adapters → 3 Start vllm serve: N adapters
- 3 Start vllm serve → 4 Keep startup log: healthy
- 4 Keep startup log → 5 Untimed warm-up: ready
- 5 Untimed warm-up → 6 Four timed phases: every slot touched
- 6 Four timed phases → 7 Result returned: 640 requests each
- 7 Result returned → 8 Record appended: payload

## Core decisions

### Separate the counts by traffic

**Problem:** In vLLM 0.27.1 one setting, `max_loras`, is both the number of GPU slots and the cap on distinct adapters per batch, so configuration cannot hold registered fixed while active changes.

**Options considered:**

- Sweep registered adapters only, conflating the two counts as most benchmarking does
- Hold extra adapters in CPU memory and swap them into slots
- Assign requests to adapters at random
- Run both regimes in every start: one adapter, then all N round-robin, in a shuffled order

**Chosen:** Run both regimes in every start: one adapter, then all N round-robin, in a shuffled order

**Why:** Same slots, memory and start; only how many adapters the batch mixes differs, so start-to-start variation cancels out of spread minus concentrated. Swapping is the mode the design put out of scope. Random assignment of 64 requests over 64 adapters reaches about 40.6 distinct on average; round-robin keeps up to min(N, 64) in flight.

**Cost:** The registered-slot cost compares different starts, against 1 slot. The check that the regimes differed reads vLLM's running-adapters gauge once a second: a sample of scheduler state, not a count per batch. By vLLM 0.27.1's source the gauge may add cost to the spread regime; 24 control starts with it off put gauge-on minus gauge-off at +17 tokens/s [−19, +57]: no cost detected. Its bound is in the mixing-versus-holding result.

### Memory as capacity; name the slot cost

**Problem:** The design claimed the cost was "dominated by batch heterogeneity, not by memory". Reading vLLM's source showed two flaws: at 29-token requests the KV cache can never fill, and the one-adapter regime also pays a kernel cost that grows with slots.

**Options considered:**

- Call the one-adapter regime's slowdown memory, as the August design did
- Also split the slot cost with a `--specialize-active-lora` diagnostic at 1, 16 and 64 slots (planned; cut when it ran out of memory)
- Three parts: heterogeneity cost, registered-slot cost, and memory as a capacity ceiling

**Chosen:** Three parts: heterogeneity cost, registered-slot cost, and memory as a capacity ceiling

**Why:** 64 requests (29 tokens each, in two 16-token blocks) need about 2,048 tokens of KV, far under what is left at 64 slots (see How it works), so memory never delays the scheduler. The LoRA kernels launch `max_loras + 1` slices whatever the batch holds (vLLM 0.27.1 source, may differ in other versions), so the one-adapter slope is the registered-slot cost, never KV capacity. Memory becomes tenants instead, through Little's law.

**Cost:** The diagnostic ran out of GPU memory during CUDA-graph capture at 64 slots, at budgets 0.85 and 0.80: it asked for 4.5 times as many graphs. It was cut before the first measured run and H4 withdrawn, so −450 tokens/s stays unsplit between the launch grid, host-side bookkeeping or anything else that scales with slots.

### License synthetic adapters by a gate

**Problem:** Public adapters for Qwen3-4B vary in rank, modules and base; the sweep needs 64 of one shape. Weight values should not change serving cost, but saying so invites "those aren't real adapters".

**Options considered:**

- Public adapters only, at whatever count qualifies (the design's fallback)
- Assert that weight values cannot matter, with no check
- Artifact 2's tolerance band from three repeats
- A margin taken from per-start spread
- 4 real vs 4 synthetic in one 8-slot server: the median difference's 90% interval inside ±5%, plus a real-vs-real resolution check

**Chosen:** 4 real vs 4 synthetic in one 8-slot server: the median difference's 90% interval inside ±5%, plus a real-vs-real resolution check

**Why:** Cost is set by shape: vLLM computes at the buffer rank, and a dense multiply does the same work for any values. Ignore-EOS (always 16 output tokens) and prefix caching off close the one known path from weights to cost, what the model generates. The margin is half the knee threshold, so a passing bias cannot move the knee by itself. Artifact 2's band does not fit one number, and a per-start margin would have made the gate nearly impossible to fail.

**Cost:** The gate tested one point, 8 slots; the other sweep points rest on the shape argument. It licenses serving cost at rank 16, these seven modules and this base model, nothing about output quality or other ranks. Single-phase TTFT turned out to vary ±10–15% within a start, so the resolution check needed far more starts than planned.

### Inconclusive twice: enlarge, then replace, both disclosed

**Problem:** The 24-start pilot was inconclusive: phase-to-phase TTFT noise left the resolution check wider than ±5%. The larger rerun lost 52 starts to one bad host and was inconclusive again, by 0.81 points.

**Options considered:**

- Apply the design's fallback: public adapters only, a smaller sweep
- Change the decision rule
- A larger gate of 72 or 108 starts
- 144 starts in a fresh store (Amendment 1), then replace exactly the 52 lost starts (Amendment 3)

**Chosen:** 144 starts in a fresh store (Amendment 1), then replace exactly the 52 lost starts (Amendment 3)

**Why:** The pilot showed noise and no evidence of bias: no drift by phase position, real and synthetic phases a few milliseconds apart. Scaling the pilot's interval widths by the square root of the count, 144 scheduled starts (about 139 usable) were estimated to narrow the resolution check enough, with no guarantee; an earlier 72-start sizing had left that check out. The 52 losses died before serving a request (CUDA Error 804, driver 570.195.03), so replacing them restores the size Amendment 1 fixed rather than choosing a new one.

**Cost:** Both amendments were written after a verdict, in response to it. Amendment 1 had said an inconclusive larger gate meant the August fallback, with no third run under it; Amendment 3 extended the second run instead, decided after seeing the 88-start result. The final TTFT resolution check passes by 0.05 points and sits above zero: the second real phase's TTFT p50 ran about 2% higher than the first's, an order effect not investigated.

### A knee rule erring toward fewer tenants

**Problem:** "How many adapters fit" has no answer until a rule says what counts as capacity, and the design named a threshold but neither the curve nor the rule.

**Options considered:**

- August's knee: a stated threshold, with the curve and rule undefined
- Require a doubling's interval to clear the threshold
- First doubling whose point estimate loses over 10% of spread throughput; tenants = the smallest of three bounds

**Chosen:** First doubling whose point estimate loses over 10% of spread throughput; tenants = the smallest of three bounds

**Why:** A loss per doubling is a ratio, so it does not depend on absolute throughput. Requiring the interval to clear 10% would miss a real but noisy drop and push the knee, and tenants, upward; the point-estimate rule errs toward fewer. Tenants = min(slots below the knee, measured throughput ÷ one tenant's peak rate, KV ceiling through Little's law), each input fixed in advance.

**Cost:** The first crossing, 10.7%, is unresolved (see How it works). If that is noise, the slot bound is 16 and cost per tenant halves. And 8 is a lower bound in any case: only the all-resident case was measured.

### Price adapters beside whole models, labelled

**Problem:** The business answer compares cost per tenant three ways, and the August design made a shared base model with artifact 4 a hard dependency. But artifact 4's costs come from its simulator, and it moved to Qwen3-1.7B after its Qwen3-4B pair failed a memory check.

**Options considered:**

- Publish without artifact 4's costs (the plan stops instead)
- Move this artifact to Qwen3-1.7B to match artifact 4
- Keep Qwen3-4B; three bars at one rate, labelled not like-for-like and resting on a failed simulator

**Chosen:** Keep Qwen3-4B; three bars at one rate, labelled not like-for-like and resting on a failed simulator

**Why:** One shared rate, $1.1095 per GPU-hour (Amendment 2), and code that refuses a table at another rate. What the comparison can carry is the shape of the choice: swapping pays per switch, resident adapters pay per co-active adapter.

**Cost:** The bars share a unit and a rate and nothing else measured: different model sizes, output lengths and traffic. Artifact 4's simulator failed its gate at exactly this point (10 of 13 bins missed), so the swapped bar's error direction is unknown and the dedicated bar was not tested by that gate; the adapter bar, set beside them, inherits that.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Split what adapters cost into what registering them costs and what serving many of them in one batch costs, inside the same server start.
  - `regimes` Separate the counts by traffic: Their gap is the cost of mixing; the concentrated slope is the cost of slots.
  - `memory` Memory as capacity; name the slot cost: Each part is named for its cause, so kernel overhead is not called memory.
- R2: Sweep with synthetic adapters only after a pre-registered check shows they serve like real ones.
  - `gate` License synthetic adapters by a gate: Synthetic adapters are used only once real ones serve within ±5% of them.
  - `amend` Inconclusive twice: enlarge, then replace, both disclosed: The gate finally could resolve ±5%, so synthetic adapters were not waved through.
- R3: Fix the knee threshold, the gate's margin and verdict rule, the SLO and the tenant assumptions before the first measured run; later changes are dated amendments (P2: amendment).
  - `gate` License synthetic adapters by a gate: Margin, interval and verdict rule were pre-registered; the runner refuses the campaign until the gate passes.
  - `amend` Inconclusive twice: enlarge, then replace, both disclosed: Each change is an appended amendment; the margin and rule never moved.
  - `knee` A knee rule erring toward fewer tenants: The curve, rule and τ were committed before the first measured run.
- R4: Convert the knee into tenants per GPU and cost per tenant per month, beside artifact 4's cost of dedicated and swapped whole models, with every assumption published.
  - `knee` A knee rule erring toward fewer tenants: The slot bound sets tenants per GPU, so the price.
  - `cost` Price adapters beside whole models, labelled: Tenants become dollars beside whole-model alternatives, assumptions stated.
- R5: Hold image, model, GPU, rank, target modules, request shape and memory budget fixed; prime the compile cache (P1: compile) per slot count and exclude any start that compiled cold.
  - `regimes` Separate the counts by traffic: Both regimes share one start's slots, memory and compile state.
- R6: Report medians across server starts with bootstrap intervals (P2: interval), never means, and re-derive every published number from committed data with no GPU.
  - No decision: Met by process: "Analyse, price, publish" re-runs the analysis byte-identically from data/a5 and artifact 4's committed cost file, with no GPU.

**Decisions and the concepts they use:**

- `regimes` Separate the counts by traffic uses Registered versus active, and the slot cap: One knob sets slots and the in-batch cap, so traffic has to split them.
- `regimes` Separate the counts by traffic uses Heterogeneity cost and registered-slot cost: The two regimes yield the two subtractions.
- `regimes` Separate the counts by traffic uses Shared versus mixed batch: Spread traffic is the mixed case.
- `memory` Memory as capacity; name the slot cost uses Heterogeneity cost and registered-slot cost: The concentrated slope is a kernel cost, not memory.
- `memory` Memory as capacity; name the slot cost uses Little's law, as used here: KV capacity bounds tenants through Little's law.
- `gate` License synthetic adapters by a gate uses LoRA adapter and its rank: Rank and modules set the work, so random weights can stand in.
- `gate` License synthetic adapters by a gate uses Equivalence gate: pass, fail, inconclusive: The resolution check makes "no difference found" mean something.
- `amend` Inconclusive twice: enlarge, then replace, both disclosed uses Equivalence gate: pass, fail, inconclusive: Both misses were resolution checks outside ±5%, not synthetic-vs-real differences.
- `knee` A knee rule erring toward fewer tenants uses The knee: The rule is the knee's definition.
- `knee` A knee rule erring toward fewer tenants uses Little's law, as used here: Little's law gives the memory bound on tenants.
- `cost` Price adapters beside whole models, labelled uses The knee: The adapter bar is the GPU's monthly cost over the knee's slot bound.

**Results and the decisions they support:**

- Throughput by adapters added: one active, or all → `regimes` Separate the counts by traffic
- The knee: throughput lost per doubling of active adapters → `knee` A knee rule erring toward fewer tenants
- Mixing versus holding, at 64 adapters → `regimes` Separate the counts by traffic, `memory` Memory as capacity; name the slot cost
- The equivalence gate, three times: could it resolve 5%? → `gate` License synthetic adapters by a gate, `amend` Inconclusive twice: enlarge, then replace, both disclosed
- Where the card's 23.52 GiB goes → `memory` Memory as capacity; name the slot cost
- KV capacity falls with slots, never binds → `memory` Memory as capacity; name the slot cost, `knee` A knee rule erring toward fewer tenants
- UNVALIDATED NEIGHBOURS: cost per tenant per month → `cost` Price adapters beside whole models, labelled

## Implementation flow

10 steps in 5 phases, 5 milestones.

Milestones: 4. Pre-register the rules (2026-10-05 00:29 (−07:00)); 5. Prime the caches; 24-start gate: inconclusive (2026-10-05); 8. Amendment 3: replace exactly 52; the gate passes (2026-10-05); 9. Run the 192-start campaign (2026-10-06 to 10-07 (−07:00)); 10. Analyse, price, publish (2026-10-07).

### Phase 1 of 5: Design (1 step)

1. **Ask the question, then correct it against vLLM's source**: August: a sweep, two regimes, a gate, a knee. The harness amendment (signed 09-26, committed 10-04): registered means a GPU slot, memory cannot move latency at this shape, and the knee and gate get exact rules.
   - Output: the design spec, the harness amendment and three plans
   - When: 2026-08-18 to 10-04
   - Decision: `memory` Memory as capacity; name the slot cost
   - Evidence: 6af0e1df94 (design spec); 4f8b7e8288 (harness amendment and plans)

### Phase 2 of 5: Build offline (1 step)

2. **Build the GPU-free core**: Phase orders per start, seeded synthetic adapters, the knee and gate rules, estimands and figures, run end to end against a stub worker.
   - Output: multilora/: tested with no GPU, never importing artifact 1 or 2
   - When: 2026-10-04
   - Decision: `regimes` Separate the counts by traffic
   - Evidence: f63a28c3ab (per-start phase order); 53553313534e (synthetic adapters); a7e57f2080 (knee and gate rules); c456873a63 (stub end to end)

### Phase 3 of 5: Reconnoitre and pre-register (2 steps)

3. **Find real adapters; capture the engine**: 7 of 261 Hub adapters qualified. Paid captures: vLLM's default memory budget ran out of memory; at 0.85 and then 0.80 the diagnostic did too, so it was cut and 0.80 kept.
   - Output: docs/recon-a5.md and fixtures/a5/: budget 0.80, sweep top 64, diagnostic cut
   - When: 2026-10-04 to 10-05
   - Decision: `memory` Memory as capacity; name the slot cost
   - Evidence: 1fe2de4855 (strict real-adapter rule); 096298c8df (memory budget fixed); 89f8b7fb65 (captures); 6b034ee179 (answers and rules applied)
4. **Pre-register the rules** [MILESTONE]: After the reconnaissance captures, before priming and the gate: hypotheses, τ = 10%, the gate's margin, SLO and tenant assumptions, a $1.00 placeholder rate; H4 withdrawn.
   - Output: docs/experiment-a5.md, changed afterwards only by appended amendments
   - When: 2026-10-05 00:29 (−07:00)
   - Decision: `knee` A knee rule erring toward fewer tenants
   - Evidence: 93789512a8

### Phase 4 of 5: Equivalence gate (4 steps)

5. **Prime the caches; 24-start gate: inconclusive** [MILESTONE]: One cold compile excluded, 23 usable. TTFT resolution check +8.9% [−6.4%, +11.7%], outside ±5%; throughput passed.
   - Output: the pilot, kept as data/a5/gate-pilot.jsonl and never pooled
   - When: 2026-10-05
   - Decision: `gate` License synthetic adapters by a gate
   - Evidence: 476b2df2fe (priming runs); 4b31c3f702 (pilot gate)
6. **Amendments 1 and 2: a larger gate; rate and model**: Amendment 1 (post-hoc): 144 starts in a fresh store, nothing else changed. Amendment 2, mid-run: artifact 4's $1.1095 rate, the base-model mismatch, the CUDA 13.0 host restriction.
   - Output: gate_instances 144; gpu_hourly_rate 1.1095
   - When: 2026-10-05
   - Decision: `amend` Inconclusive twice: enlarge, then replace, both disclosed
   - Evidence: e1c91253a8 (pilot set aside); 0d312ef868 (Amendment 1); 1dfacd4aa4 (Amendment 2)
7. **The larger gate: 52 lost to a host; inconclusive**: Runs 92 to 143 hit one pod whose driver could not run the image. 88 usable: TTFT inside ±5%, but its resolution check +2.24% [−0.11%, +5.81%].
   - Output: data/a5/gate.jsonl: 92 ok, 52 failed, all kept
   - When: 2026-10-05
   - Decision: `amend` Inconclusive twice: enlarge, then replace, both disclosed
   - Evidence: e46e4b2bd6
8. **Amendment 3: replace exactly 52; the gate passes** [MILESTONE]: Post-hoc, after the 88-start verdict. A stop after 3 failures in a row; 3 replacements failed on the same driver and were not replaced again.
   - Output: 196 scheduled, 55 failed, 4 cold, 137 usable: pass
   - When: 2026-10-05
   - Decision: `amend` Inconclusive twice: enlarge, then replace, both disclosed
   - Evidence: 4c0839ea1f (Amendment 3 and the guard); 278447e1e4 (pass)

### Phase 5 of 5: Measure and publish (2 steps)

9. **Run the 192-start campaign** [MILESTONE]: Seven slot counts plus the gauge control, 24 starts each, in randomized blocks. One start failed client-side and was not retried; no cold compiles, no top-up.
   - Output: data/a5/campaign.jsonl: 191 ok, all on one host
   - When: 2026-10-06 to 10-07 (−07:00)
   - Decision: `regimes` Separate the counts by traffic
   - Evidence: e270ee61ed
10. **Analyse, price, publish** [MILESTONE]: Analysis from the two stores and artifact 4's file, then figures and the post; artifact 4's failed validation added to the cost bars; a KV count corrected that night.
   - Output: data/a5/analysis.json (re-runs byte-identical), four figures, docs/post-a5.md
   - When: 2026-10-07
   - Decision: `cost` Price adapters beside whole models, labelled
   - Evidence: 90a4f60b8e (analysis); d82f356fb1 (post); abb6a69e1b (artifact 4's validation carried); 820e1808ba (1,339, not 1,478)

## Results as meaning

### Throughput by adapters added: one active, or all

- Axis: Measured: Qwen3-4B on one RTX 4090, 64 requests in flight, 13 prompt and 16 output tokens. Each point is a median over server starts; both lines come from the same starts.
- Read it as: The gap between the lines at each N is the heterogeneity cost; the top line's own fall is the registered-slot cost. Spread TTFT p95 rose from 108 to 141 ms, far inside the 1 s SLO: all 64 served.
- How it is computed: Concentrated 3,577 → 3,127 tokens/s (−450, 12.6%); spread 3,568 → 1,835, about half. Every point is a median of per-start throughput: successful output tokens over total phase time.
- Axes: x is adapters registered (GPU slots) (log scale); y is output throughput (tokens/s)
- concentrated: one adapter active: 1: 3577 (3555 to 3598), 2: 3573 (3559 to 3590), 4: 3543 (3518 to 3583), 8: 3535 (3510 to 3548), 16: 3469 (3453 to 3492), 32: 3320 (3308 to 3353), 64: 3127 (3100 to 3140)
- spread: all registered active: 1: 3568 (3554 to 3582), 2: 3529 (3509 to 3556), 4: 3443 (3413 to 3480), 8: 3260 (3233 to 3282), 16: 2911 (2889 to 2948), 32: 2422 (2411 to 2431), 64: 1835 (1824 to 1844)
- Note: Whiskers: 95% bootstrap interval of the median across 23 or 24 starts, a plausible range for the true median. Single starts scatter more widely than the whiskers.
- So: see decision `regimes`

### The knee: throughput lost per doubling of active adapters

- Axis: Measured: loss per doubling, 1 − T(N) / T(N/2), with T the spread regime's median throughput.
- Read it as: The first point above the line is 16, so the knee lies between 8 and 16 (see How it works).
- How it is computed: At 16: 1 − 2,911 / 3,260 = 10.7%. Rounded to one decimal, the 2-slot whisker's low end is 0.0 (0.03%).
- Axes: x is adapters registered and active (N) (log scale); y is spread throughput lost vs N/2 (%)
- loss per doubling, m(N) (points): 2: 1.1 (0.0 to 2.0), 4: 2.4 (1.2 to 3.8), 8: 5.3 (4.3 to 6.6), 16: 10.7 (9.2 to 11.5), 32: 16.8 (16.1 to 17.9), 64: 24.2 (23.7 to 24.8)
- Reference: threshold τ, fixed in advance at y = 10 %
- Note: Whiskers: 95% bootstrap interval of the ratio of medians. A crossing is resolved when the whole whisker clears the line: at 32 and 64, not at 16.
- So: see decision `knee`

### Mixing versus holding, at 64 adapters

- Axis: Measured, 95% bootstrap intervals of the median. Heterogeneity: paired within each of 24 starts. Registered-slot: concentrated at 64 slots against at 1 slot, across starts. Gauge: the heterogeneity cost with the gauge on minus 24 control starts with stats logging off.
- Read it as: The two costs' intervals are far apart, so H2 holds: the batch's mix costs more than the slots. The gauge's interval straddles zero; a gauge cost would show as negative, so at most about 19 tokens/s (the post quotes the symmetric bound, 57), against the 1,290.
- How it is computed: 1,290 / 450 = 2.87, the post's 2.9. The slot cost is unsplit: the diagnostic that would separate the launch grid ran out of memory.
- Heterogeneity: spread vs one adapter: -1290 tokens/s (interval -1309 to -1274)
- Registered-slot: 64 slots vs 1: -450 tokens/s (interval -486 to -425)
- Gauge: on minus off: 17 tokens/s (interval -19 to 57)
- So: see decisions `regimes`, `memory`

### The equivalence gate, three times: could it resolve 5%?

- Axis: Measured: TTFT p50 relative difference per start, median across usable starts, with the 90% bootstrap interval the rule requires. Synthetic vs real, and real vs real (the resolution check), as in the verdicts concept. 23: the pilot; 88: the 144-start rerun after 52 host failures; 137: after Amendment 3.
- Read it as: The top row is not data: it is the margin. A pass needs both intervals of a run inside it. Synthetic vs real is inside from 88 on. Real vs real reaches +11.7% at 23 and +5.81% at 88 (inconclusive both times), then +4.95% at 137: a pass by 0.05 points, sitting above zero. Throughput passed all three runs.
- How it is computed: 196 scheduled − 55 failed − 4 cold compiles = 137 usable. Margin = τ / 2 = 0.05. Final resolution check: 5 − 4.95 = 0.05 points to spare.
- Reference: the ±5% margin: 0 % (interval -5 to 5)
- 23 starts: synthetic vs real: 2.9 % (interval -2.7 to 10.7)
- 23 starts: real vs real: 8.9 % (interval -6.4 to 11.7)
- 88 starts: synthetic vs real: -1.16 % (interval -2.54 to 0.75)
- 88 starts: real vs real: 2.24 % (interval -0.11 to 5.81)
- 137 starts: synthetic vs real: -0.48 % (interval -1.87 to 0.95)
- 137 starts: real vs real: 2.29 % (interval 0.99 to 4.95)
- So: see decisions `gate`, `amend`

### Where the card's 23.52 GiB goes

- Axis: Measured from the startup log (docs/recon-a5.md), budget 0.80 of 23.52 GiB; 'derived' segments are subtractions.
- Read it as: Each slot's 79 MiB comes out of the KV cache. CUDA graphs (1.28 GiB) sit outside the budget, which fits the 0.92 default running out of memory.
- How it is computed: KV = 18.81 − 7.55 − 0.44 − N × 0.0771. Left over = 23.52 − 18.81 − 1.28 = 3.43.
- 1 slot: Base weights (derived) 7.55, Adapter slots 0.08, Runtime + activation (derived) 0.44, KV cache 10.74, CUDA graphs (outside budget) 1.28, Left over (derived) 3.43 (GiB)
- 8 slots: Base weights (derived) 7.55, Adapter slots 0.62, Runtime + activation (derived) 0.44, KV cache 10.2, CUDA graphs (outside budget) 1.28, Left over (derived) 3.43 (GiB)
- 64 slots: Base weights (derived) 7.55, Adapter slots 4.94, Runtime + activation (derived) 0.44, KV cache 5.89, CUDA graphs (outside budget) 1.28, Left over (derived) 3.42 (GiB)
- So: see decision `memory`

### KV capacity falls with slots, never binds

- Axis: Measured: the KV cache size vLLM logs at startup, budget 0.80 of the 24 GB card.
- Read it as: About 45% of the cache goes by 64 slots, yet it still holds 1,339 of these short requests against the 64 in flight: memory cannot slow this load. At an 8,192-token context it holds 9 at 8 slots, which gives the memory bound. The fall is a straight line, about 561 tokens per slot (79 MiB), not an accelerating cliff.
- How it is computed: 42,864 / 32 (two 16-token blocks per 29-token request) = 1,339; analysis.json's own field still divides by 29 (1,478). Memory bound = unfloored throughput bound × 9 / 64 = 1,784.6 × 9 / 64 = 250.96, rounded down: 250.
- Axes: x is adapters registered (GPU slots); y is KV cache capacity (tokens)
- KV cache at startup: 1: 78208, 2: 77744, 4: 76496, 8: 74288, 16: 69968, 32: 60448, 64: 42864
- Reference: 64 requests in flight use about this at y = 2048 tokens
- Note: Every start at a point reported the same value, so there is no interval.
- So: see decisions `memory`, `knee`

### UNVALIDATED NEIGHBOURS: cost per tenant per month

- Axis: All at $1.1095 per GPU-hour. Dedicated and swapped: artifact 4's simulator, Qwen3-1.7B, bursty regime, s = 1.0, which failed its validation (10 of 13 bins missed). Adapter: this artifact's measurement, Qwen3-4B.
- Read it as: Not like-for-like: different model sizes, output lengths and traffic. The adapter bar is an upper bound because tenants are a lower bound; the swapped bar's error direction is unknown; the dedicated bar was not tested by artifact 4's gate.
- How it is computed: $1.1095 × 730 h / 8 tenants = $101.24. If the 8-to-16 crossing were noise: 16 tenants, half that.
- dedicated (artifact 4 simulator): 850.43 USD a month
- swapped (artifact 4 simulator): 404.97 USD a month
- adapter, upper bound (8-tenant floor): 101.24 USD a month
- So: see decision `cost`

## Interview card

**30-second pitch:** I measured how many customers' LoRA fine-tunes one GPU can serve on a shared base model, and found the cost is mostly how many share a batch, not how many you load. I split the two by running every server start with the load on one adapter and spread over all of them; at the top of the sweep, mixing cost about three times what holding the adapters did. By a knee rule fixed in advance, past about 8 adapters active in the same batch each doubling costs over a tenth of throughput. That makes 8 a floor on tenants per GPU with every adapter resident, not a capacity claim: real counts depend on how often customers overlap, which I didn't measure. Synthetic adapters were licensed by a pre-registered gate that needed two disclosed extensions before it could pass.

**2-minute version:** Products that give each customer a fine-tune serve them as LoRA adapters on one base model, and people ask how many adapters fit. That mixes two costs: adapters held in GPU slots, and adapters active in the same batch. In vLLM one setting sets both, so I separated them by traffic: every server start ran its load on a single adapter and round-robin over all registered ones, two phases each in shuffled order, so the gap is paired inside the start. I swept 1 to 64 adapters on Qwen3-4B on one RTX 4090, 24 scheduled starts per point. The adapters were synthetic, which I only used after a pre-registered equivalence gate against 4 real ones. That gate came back inconclusive twice, once from phase-to-phase noise and once after a bad host killed 52 starts, and I extended it through two post-hoc amendments, disclosed as such, until it passed. At 64 adapters, mixing cost 1,290 tokens a second against 450 for holding the slots. KV capacity fell 45% but never bound at this request shape. By the knee rule's point estimates, each doubling past 8 adapters active in the same batch costs over a tenth of throughput, though the first crossing is unresolved. That makes 8 a floor on tenants per GPU with every adapter resident, at about $101 a month each as an upper bound; how many customers share a batch in real traffic, I didn't measure. The comparison with whole-model serving leans on artifact 4's simulator, which failed its validation, so I don't present those bars as findings.

**Hard follow-ups:**

- Q: Why synthetic adapters, and what does that license?
  A: There are not 64 public rank-16 adapters on the seven projections for Qwen3-4B: 7 of 261 qualified. Serving cost is set by shape: vLLM computes at the buffer rank, and a dense multiply does the same work for any values. The one known path from values to cost, what the model generates, is closed by ignore-EOS and prefix caching off. The gate then checked it at 8 slots. It licenses serving cost at this rank, these modules, this base; nothing about quality or other ranks.
- Q: Wasn't Amendment 3 a forking path?
  A: It was data-dependent, and the post says so: I decided it after seeing the 88-start verdict. What bounds it: only the count changed, by exactly the 52 starts a host fault killed before any phase ran, back toward the size Amendment 1 had fixed; the 3 replacements that failed again were counted, not replaced; the margin and rule never moved. What it does not undo: Amendment 1 had said an inconclusive larger gate meant the August fallback, Amendment 1 was post-hoc too, and the final resolution check passes by only 0.05 points.
- Q: Why don't the cost bars count as a finding?
  A: Dedicated and swapped come from artifact 4's simulator, which failed its pre-registered validation at exactly this operating point: 10 of 13 bins outside the band of three real repeats, 1 of 2 held-out cells passed. Its swap cost fits no single value, so the swapped bar's error direction is unknown; dedicated was never tested by the gate. The bars also cross model sizes, Qwen3-1.7B against 4B. Only the adapter bar rests on a measurement, and it is an upper bound.
- Q: Can I say one GPU serves 8 customers?
  A: Not as a capacity claim, and the post says so next to the headline. The 8 counts adapters active in the same batch at 64 in flight, all resident, so it is a floor on tenants; real counts depend on how often customers overlap, which wasn't measured. Even as a floor it is not firm: the first crossing, 10.7%, is unresolved (see How it works). If that is noise the bound is 16 and the cost per tenant halves; the rule was registered to err toward fewer. And only all-resident adapters were run, while vLLM can hold more in CPU memory and swap them into slots.
- Q: If memory isn't the cost, why does KV capacity fall 45%?
  A: Each slot's weight buffers take memory the KV cache would use (see How it works). But 64 requests of 29 tokens use about 2,048 (two 16-token blocks each); the scheduler never waits for KV. Memory matters as capacity: at an 8,192-token context the cache holds 9 requests at 8 slots, a bound of 250 tenants, and for long contexts it would bind before throughput. That bound is generous: it uses the 29-token requests' time in system.
- Q: What would you do differently?
  A: Build the failure-streak stop before the first paid run: without it, one bad host consumed 52 gate starts. Size the gate for its resolution check, not only its main interval: an earlier 72-start sizing left the check out, and the pilot's 24 could not resolve ±5% through phase-to-phase TTFT noise. Then the sequels the post names: rank as a variable, and resident versus swapped adapters, which turns the lower bound on tenants into a measurement.

**Limits (what I must not claim):** **Do not say "8 customers per GPU".** The 8 counts adapters active in the same batch at 64 in flight with every adapter resident: a floor on tenants, not a capacity claim. One base model (Qwen3-4B), one RTX 4090, rank 16 on seven projections, one short request shape (13 prompt + 16 output tokens at 64 in flight), vLLM 0.27.1, whose source the launch-grid and gauge explanations were read from (this repo's reading, not re-checked elsewhere; other versions may differ): the numbers do not transfer, and the knee elsewhere is unmeasured. All adapters resident in GPU slots, so tenants are a lower bound and the adapter cost an upper bound. The registered-slot cost is unsplit (the diagnostic ran out of memory; H4 withdrawn). The gate tested one point (8 slots), was extended twice after its result was seen, and its TTFT resolution check passes by 0.05 points with an uninvestigated order effect. The knee's first crossing is unresolved. The regime check samples the scheduler once a second. All 191 campaign starts ran on one host, so host-to-host variation is not in the intervals. 55 gate starts and 1 campaign start failed and 4 gate starts were excluded as cold, all counted. The dedicated and swapped costs come from artifact 4's simulator, which failed validation, on a smaller model; the rate is one billing sample.

## Recall questions

- Q: In vLLM 0.27.1, what two things does `max_loras` set, and why does that force two traffic regimes?
  A: The number of GPU slots and the cap on distinct adapters per batch. With `max_cpu_loras` = `max_loras` = N, configuration cannot change the active count while holding the registered count, so traffic does: one adapter or all N, in the same start.
- Q: Why does a batch spanning 64 adapters cost more than one sharing an adapter?
  A: If the kernels split the batch by adapter (vLLM 0.27.1 source, not measured here), that is 64 sets of weights read per projection per step instead of one, and 64 small multiplications instead of one larger (see How it works).
- Q: Why does the one-adapter regime slow down too as slots grow, and why is that not memory?
  A: The LoRA kernels launch `max_loras + 1` slices whatever the batch holds; empty slots' slices exit early but are launched (counts in How it works; vLLM 0.27.1 source, may differ). KV never binds at 29-token requests. How much the launch grid explains is unmeasured: the diagnostic was cut.
- Q: Why is the heterogeneity cost paired within a start, and the registered-slot cost not?
  A: Both regimes run in every start, so spread minus concentrated is a difference inside one server start and start-to-start variation cancels. The slot cost compares concentrated at N with concentrated at 1 slot, which are different starts.
- Q: The gate's real-vs-real check fits inside ±5% but synthetic vs real does not. What is the verdict, and what happens?
  A: Fail: the gate can resolve ±5%, yet could not show synthetic within ±5% of real. The design calls that a publishable finding, and its fallback applies: public adapters only, at the count that qualifies, with a smaller sweep.
- Q: Why can random weights stand in for trained adapters, and which two settings close the remaining gap?
  A: The work is set by shape (rank at the buffer rank, the seven projections), and a dense multiply costs the same for any values. Ignore-EOS fixes every output at 16 tokens, so weights cannot change how much is generated, and prefix caching is off, so no adapter's prompt is served from a cache another missed.
- Q: Had the knee rule required the interval to clear 10%, where would the knee be, and why was that rule rejected?
  A: Between 16 and 32, so 16 tenants: the 32 crossing is resolved, the 16 one is not. Rejected because it misses a real but noisy drop and pushes the knee, and tenants, upward; the point-estimate rule errs toward fewer.
- Q: How does Little's law turn KV capacity into a bound on tenants?
  A: Requests in the system = rate × time. 64 in flight at about 204 completed a second is about 0.31 s each; a tenant at peak (0.114 a second) keeps about 0.036 in the system; room for 9 long requests at 8 slots ÷ 0.036 = 250 tenants.
- Q: Which requirement does each gate amendment protect, and what do the amendments cost the claim?
  A: R2: synthetic adapters are licensed only by a gate that can resolve ±5%. R3: each change is appended and dated, margin and rule unchanged. Cost: both were decided after a verdict, so they are data-dependent and disclosed as post-hoc.

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
