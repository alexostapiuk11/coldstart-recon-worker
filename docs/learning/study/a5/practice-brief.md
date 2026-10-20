# Practice: how many LoRA adapters fit on one GPU: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: How many LoRA adapters actually fit on one GPU. About 35 minutes.

## Objectives

- Write y = Wx + (α/r)B(Ax), give A and B's shapes for one projection, and size a rank-16 adapter within 10% (about 63 MiB).
- Draw the 24 GB card at 1, 8 and 64 slots and compute the KV tokens left at 64 slots from the budget (5.89 GiB, 42,864 tokens).
- Explain in 60 seconds why a batch spanning 64 adapters costs more than one sharing an adapter, and say which parts are measured.
- Quote the two costs at 64 slots (−1,290 and −450 tokens/s), say which is paired within a start, and why.
- Apply the knee rule to the doubling table, then turn a KV ceiling into a tenant bound with Little's law (250 at 8,192 tokens).
- State what "8 tenants per GPU" does and does not mean, and name what would have to be measured to say more.

## Check yourself first

### Check 1

Q: A 24 GB GPU serves an 8B model in bf16. Roughly how much memory is left for the KV cache, and how does vLLM decide its size?
KEY: The weights take about 16 GB (8B numbers at 2 bytes), so at most about 8 GB is left before runtime memory. vLLM profiles a forward pass and gives what remains of its memory budget to the KV cache.
If missed, review: KV cache (P1: kvcache)

### Check 2

Q: Why does decoding 64 requests together take only a little longer per step than decoding one?
KEY: A decode step reads every weight from GPU memory once, whatever the batch size, so a bigger batch is nearly free throughput until compute or KV memory runs out. That is the batching the adapters then break up.
If missed, review: Continuous batching (P1: batching)

### Check 3

Q: A 90% bootstrap interval for a median difference is [−1.87%, +0.95%] and the margin is ±5%. Is that equivalent, and what else makes "no difference found" trustworthy?
KEY: Yes, it lies inside the margin. You also need evidence the method can resolve ±5%: a real-versus-real check whose interval also fits inside ±5%. Without it the verdict is inconclusive, not a pass.
If missed, review: Validation gate (P2: gate)

## Estimation drills

### Estimate 1: How many adapter slots fit beside one 8,192-token request?

Problem: RTX 4090 (23.52 GiB), Qwen3-4B, memory budget 0.80. The server must hold at least one 8,192-token request in its KV cache. Use the measured 79 MiB per slot at rank 16. How many slots fit at rank 16, and what would rank 64 give if slot memory scales with rank?

KEY steps:

1. Budget = 0.80 × 23.52 = 18.81 GiB (the logged figure).
2. Fixed memory: base weights 7.55 GiB plus runtime and activation 0.44 GiB, both derived, = 7.99 GiB. Left for slots plus KV: 18.81 − 7.99 = 10.82 GiB.
3. One 8,192-token context at 144 KiB a token = 8,192 × 144 / 1,048,576 = 1.125 GiB. Slots may use 10.82 − 1.125 = 9.70 GiB.
4. Rank 16: 9.70 / 0.0771 GiB per slot = 125.8, so 125 slots.
5. Rank 64 (assumption: slot memory scales linearly with rank; the 1.254 overhead factor is measured at rank 16 only): 4 × 79 = 316 MiB = 0.31 GiB per slot, 9.70 / 0.31 = 31 slots. Theory alone (4 × 63 = 252 MiB) gives 39.
6. Sanity check: 64 slots at rank 64 would need about 19.7 GiB (4 × 4.94), more than the 10.82 GiB available; the harness amendment's theory figure is 15.8 GiB. Either way they do not fit.

KEY answer: 125 slots at rank 16 (measured per-slot cost). About 31 at rank 64, an assumption: rank scaling of the overhead was not measured.

### Estimate 2: The memory bound if requests are 2,048 tokens, not 8,192

Problem: At 8 slots the engine logged 74,288 KV tokens; 64 requests were in flight at 203.72 completed requests a second; a tenant peaks at 0.11416 requests a second (100,000 a month, peak three times average). Using the pre-registered formula, what is the memory bound on tenants for a 2,048-token context, and does it change which bound binds?

KEY steps:

1. Requests that fit: 74,288 / 2,048 = 36.27, so 36 (at 8,192 tokens it is 9.07, so 9).
2. Memory bound = fitting requests × request rate / (in flight × one tenant's peak rate) = 36 × 203.72 / (64 × 0.11416).
3. Denominator 64 × 0.11416 = 7.306; numerator 36 × 203.72 = 7,333.9; ratio 1,003.8, floored to 1,003.
4. Compare: throughput bound 1,784, memory bound 1,003 (at 8,192 tokens: 250), slot bound 8. The slot bound still binds.
5. Caveat: 2,048 tokens is a chosen what-if. The 0.31 s time in the system was measured on 29-token requests and a real long request would stay longer, so the bound is generous.

KEY answer: About 1,003 tenants by memory at a 2,048-token context, against 250 at 8,192; the 8-slot bound still binds.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 12

Q: What does rank mean in LoRA, and how big is a rank-16 adapter on Qwen3-4B?
KEY: W stays frozen and the output is y = Wx + (α/r)·B(Ax), with A shaped r × in and B shaped out × r. Rank r is the inner width. Parameters are r × (in + out) per projection: 917,504 a layer and 33,030,144 over seven projections and 36 layers, which is 63 MiB at 2 bytes (computed from the repo's Qwen3-4B shape constants). The measured slot took 79 MiB; the sources do not explain the 16 MiB gap.
RED FLAG: "Rank is the number of layers adapted", "an adapter is a few KB", or quoting 63 MiB as a measurement, or inventing a cause for the 16 MiB.

### Drill 2 of 12

Q: What do `max_loras`, `max_cpu_loras` and `max_lora_rank` set in vLLM 0.27.1, and what were they here?
KEY: `max_loras`: the number of GPU slot buffers (each sized to `max_lora_rank`, allocated used or not) and the cap on distinct adapters per batch. `max_cpu_loras`: adapters held in host memory (at least `max_loras`), copied into a slot on demand. `max_lora_rank`: the width every slot is padded to. Here `max_loras` = `max_cpu_loras` = N (1 to 64) and rank 16, so nothing swaps. This is the harness amendment's reading of 0.27.1; other versions may differ.
RED FLAG: "`max_loras` is the total number of adapters the server can serve."

### Drill 3 of 12

Q: Why does KV capacity fall as slots are added, and is the fall linear?
KEY: vLLM sizes the KV cache from what is left of its memory budget after weights, slot buffers and runtime memory, so each slot's 79 MiB buffer removes about 561 tokens. Measured: 78,208 tokens at 1 slot and 42,864 at 64, 45% fewer; (78,208 − 42,864) / 63 = 561. The fall is a straight line. It only looks like a cliff on a log slot axis.
RED FLAG: "It accelerates past 16 slots."

### Drill 4 of 12

Q: Why can KV capacity not slow this benchmark, even at 64 slots, and when would it?
KEY: A 29-token request takes two 16-token blocks, so 64 in flight use about 2,048 tokens of 42,864 (the engine logged 4.7% KV use); the scheduler never waits for blocks. It would bind with long contexts: at 8,192 tokens the cache holds 9 requests at 8 slots and 5 at 64.
RED FLAG: "Less KV means preemption, so it is part of the slowdown."

### Drill 5 of 12

Q: Why does a batch spanning 64 adapters cost more than one sharing an adapter, and how sure are you?
KEY: Mechanism, consistent with the data and not measured (vLLM 0.27.1 source reading): the base weights are read once for every request, while each distinct adapter needs its own small multiply over only its requests, with its own weights read (about 63 MiB each, 3.9 GiB for 64, in theory). Measured: spread costs 1,290 tokens/s more than concentrated at 64, in the same starts. How that splits between extra bytes, tiny multiplies and launches was not measured.
RED FLAG: "Adapters are swapped in and out" (nothing swaps here), "it is memory", or stating the kernel mechanism as a measurement.

### Drill 6 of 12

Q: Why does the one-adapter regime also slow down, by 450 tokens/s at 64 slots, and why is that not memory?
KEY: By the repo's reading of the 0.27.1 source the LoRA kernels launch `max_loras + 1` slices whatever the batch holds (65 at 64 slots, 2 at 1); empty ones exit early but are still launched. KV never binds at this shape. How much of the 450 that explains is unmeasured: the `--specialize-active-lora` diagnostic ran out of GPU memory in graph capture (4.5 times as many graphs) and was cut, so host-side bookkeeping could also contribute.
RED FLAG: "KV capacity fell 45%, so it is memory", or claiming the launch grid explains the 450.

### Drill 7 of 12

Q: Why run both regimes inside every server start rather than sweeping configurations?
KEY: Slot count and in-batch cap are one knob, so configuration cannot hold registered fixed while active changes; traffic can. Pairing inside a start cancels start-to-start variation (host, compile, allocator), so the heterogeneity interval is tight ([−1,309, −1,274]). The slot cost compares different starts and is wider ([−486, −425]).
RED FLAG: "Set `max_loras` to 1 and register 64 adapters." With a larger `max_cpu_loras` that is the swapped mode, a different experiment.

### Drill 8 of 12

Q: How do you turn a KV ceiling into a tenant bound?
KEY: Little's law: requests in the system = rate × time. At 8 slots 64 in flight at about 204 completed a second means about 0.31 s each. A tenant at peak (0.114 requests a second) keeps about 0.036 in the system. KV room for 9 requests of 8,192 tokens divided by 0.036 gives 250 tenants. It is generous: a real long request stays longer than 0.31 s.
RED FLAG: "KV tokens divided by tokens per request is the tenant count" (forgets time in the system).

### Drill 9 of 12

Q: Is "8 tenants per GPU" the product's capacity?
KEY: No. It is the slot bound: the largest N below the knee, with every adapter resident, 64 requests in flight and one short request shape. It is a floor on tenants. How many customers fit depends on how often they overlap and on swapping adapters from host memory; neither was measured. $101.24 a month is an upper bound on cost per tenant; if the first crossing is noise the bound is 16 and the cost halves.
RED FLAG: "Yes, so a 4090 serves 8 customers at $101 each."

### Drill 10 of 12

Q: Why license synthetic adapters with an equivalence gate, and what does a pass not license?
KEY: Serving cost is set by shape (rank, modules, base), and a dense multiply does the same work for any values. The one known path from values to cost, what the model generates, is closed by ignore-EOS and prefix caching off. The gate checked it at 8 slots with a 90% interval inside ±5% plus a real-versus-real resolution check. A pass licenses nothing about quality, other ranks or other bases.
RED FLAG: "Random weights are fine because LoRA weights do not matter."

### Drill 11 of 12

Q: The 8-to-16 loss is 10.7% with interval [9.2%, 11.5%]. Defend the knee rule.
KEY: The rule was fixed before the data: the first doubling whose point estimate exceeds τ = 10%. Requiring the interval to clear τ would move the knee to 16 to 32 and double tenants on a noisy drop; the point rule errs toward fewer tenants, the cautious side for capacity. Report both: if the crossing is noise the slot bound is 16 and cost per tenant is $50.62.
RED FLAG: "10.7 is above 10, so it is proven."

### Drill 12 of 12

Q: You must serve tenants with ranks from 8 to 64 on 4090s. What breaks first, and what do you measure?
KEY: Slots are padded to `max_lora_rank`, so one rank-64 tenant makes every slot rank-64 and slot memory grows with rank; the amendment estimates 64 slots at rank 64 at about 15.8 GiB, which does not fit beside the weights. Pooling GPUs by rank is one option (my suggestion, untested here). Measure: co-active adapters per step, swap rate and latency if you use host memory, TTFT p95 per tenant, and throughput against active adapters at your real concurrency and request shape. None of this was measured here.
RED FLAG: "Just set `max_loras` to the number of tenants."

## Design scenario

Prompt: You run a fine-tuning product: 2,000 customers, each with a rank-16 LoRA adapter on Qwen3-4B, 100,000 requests a month each, peak three times average, TTFT p95 under 1 s. Design the serving tier on RTX 4090s: how many GPUs, how adapters are placed, and what you measure before you trust the plan.

KEY outline:

1. Demand: 2,000 × 0.114 = 228 requests/s if every customer peaked together (pessimistic). Measured: 203.72 requests/s at 8 adapters in a batch, 64 in flight, 13-token prompts and 16-token outputs. That is a different shape, so re-measure; at least two GPUs on that bound.
2. Co-active adapters in a batch, not registered adapters, drive cost. The knee (8 to 16) was measured with every adapter resident. Route a customer's traffic to a bounded set of GPUs (affinity) so a batch holds few distinct adapters. A design suggestion, not tested here.
3. More customers than slots needs `max_cpu_loras` above `max_loras` and swapping adapters into slots on demand. Not measured: treat swap-in rate and its latency as the main risk until you measure it.
4. Memory: at rank 16, 16 slots take 16 × 79 MiB = 1.2 GiB of KV, small. Long contexts bind earlier through Little's law. Slots are padded to `max_lora_rank`, so keep ranks uniform per server.
5. Failure modes: thrash when co-active customers exceed slots (swap latency lands in TTFT), noisy neighbours (each added co-active adapter slows everyone), cold adapter fetches, a hot customer better served by a dedicated model.
6. Measure first, pre-registered: co-active adapters per step on real traffic; swap rate and p95 swap latency; throughput against active adapters at real concurrency and request shape; TTFT p95 per customer; KV use at real contexts.
7. Cost: GPUs × $1.1095 × 730 hours / customers. State which bound applies and that the whole-model neighbours came from a simulator that failed validation.

KEY pitfalls:

- Quoting 8 tenants per GPU as capacity.
- Reusing 203.72 requests/s for production request lengths.
- Assuming swapping is free: only the all-resident case was measured.
- Mixing ranks on one server, so every slot pays the largest.
- Treating artifact 4's neighbouring bars as findings.

## Lab

Cost: runs on your machine
Goal: Re-derive the published knee, tenants and cost from the raw data with no GPU, then change the rule (τ, context length) and watch the answer move.
Note: No GPU or paid call. A GPU follow-up (about one GPU-hour) could vary concurrency at 64 slots; it is only described here, not run, and its predicted result is untested.

Setup:

- The repo's own environment: .venv/bin/python, never `uv run` (it re-syncs the venv and has broken figure byte tests).
- Inputs already committed: data/a5/campaign.jsonl, data/a5/gate.jsonl, data/a4/cost_per_tenant.json. Write outputs to a scratch folder, not over data/a5.

Steps:

1. .venv/bin/python scripts/a5_analyse.py --require-a4 --out scratch/a5-analysis.json, then cmp scratch/a5-analysis.json data/a5/analysis.json.
2. In a Python session read the campaign store as multilora/analysis.py does and call multilora.knee.knee on the spread throughput per N at tau = 0.08, 0.10 and 0.12.
3. For each tau note the knee interval, the slots below it, and whether the crossing is resolved (the doubling's `resolved` flag); also apply the rule that needs the interval to clear tau.
4. Call multilora.economics.tenants_per_gpu with max_concurrency 36 (a 2,048-token context) instead of 9, and read the three bounds.
5. Plot the seven KV sizes against slots on a linear and a log axis, side by side.

Record:

- Knee interval and slot bound at each tau
- Whether each crossing is resolved, and the first resolved crossing
- Memory bound at 2,048 and at 8,192 tokens
- Cost per tenant at each slot bound

KEY expected result: cmp prints nothing. Tau 0.10: knee 8 to 16, slot bound 8, the 16 crossing unresolved; the interval rule gives 16 to 32. Tau 0.08: knee 8 to 16, and the 16 crossing is resolved. Tau 0.12: knee 16 to 32, slot bound 16, $50.62. At 2,048 tokens the memory bound is 1,003, still above the slot bound. KV is a straight line on linear axes.
KEY what it shows: The headline is a function of a rule fixed in advance; every published number re-derives from committed data; slot memory is linear in slots.

## Calculator

Slot capacity: rank, slots, budget, context Constants: 57,344 = in + out over seven projections, 36 layers, 23.52 GiB card, 144 KiB per KV token. At rank 16, 8 slots it is within 0.1% of the logged 74,288 tokens. Other ranks and the 1.254 factor (measured at rank 16 only) are assumptions. Negative KV means no fit. No throughput is predicted.

Inputs (default, range):

- LoRA rank: 16 (range 8 to 64)
- Slots (max_loras): 8 (range 1 to 128)
- Memory budget (gpu_memory_utilization): 0.8 (range 0.7 to 0.92)
- Context to hold: 8192 tokens (range 1024 to 32768)
- Overhead factor (assumption): 1.254 (range 1 to 1.6)
- Weights + runtime (derived): 7.99 GiB (range 7 to 9)

Outputs at the defaults:

- Numbers per adapter = 33.03 million  [r * 57344 * 36 / 1000000]
- Slot buffer = 79.0 MiB  [r * 57344 * 36 * 2 / 1048576 * calib]
- KV cache left = 10.21 GiB  [u * 23.52 - fixed - n * r * 57344 * 36 * 2 / 1048576 * calib / 1024]
- KV tokens = 74,338  [(u * 23.52 - fixed - n * r * 57344 * 36 * 2 / 1048576 * calib / 1024) * 1048576 / 144]
- Requests of that context that fit = 9  [floor((u * 23.52 - fixed - n * r * 57344 * 36 * 2 / 1048576 * calib / 1024) * 1048576 / 144 / ctx)]
- Most slots that leave room for one = 125  [floor((u * 23.52 - fixed - ctx * 144 / 1048576) / (r * 57344 * 36 * 2 / 1048576 * calib / 1024))]

## Recall cards

- [adapter] LoRA forward pass for one projection? -> KEY: y = W·x + (α/r)·B·(A·x). W is frozen and shared; A is r × in, B is out × r.
- [adapter] Size of a rank-16 adapter on all seven Qwen3-4B projections? -> KEY: 917,504 numbers a layer, 33,030,144 in all: 63 MiB at 2 bytes (computed). The measured slot took 79 MiB; the 16 MiB gap is unexplained.
- [slots] What does max_loras set in vLLM 0.27.1? -> KEY: The number of GPU slot buffers (allocated used or not) and the cap on distinct adapters per batch.
- [slots] What do max_cpu_loras and max_lora_rank add? -> KEY: max_cpu_loras: a host-memory tier of adapters copied into a slot on demand (here equal to N, nothing swaps). max_lora_rank: the width every slot is padded to (16).
- [memory] KV tokens lost per slot, and in MiB? -> KEY: About 561 tokens, 79 MiB; linear in the slot count.
- [memory] KV capacity at 1 slot and at 64 slots? -> KEY: 78,208 and 42,864 tokens, 45% fewer.
- [memory] What sits outside the 0.80 budget, and what happened at the 0.92 default? -> KEY: CUDA graphs, 1.28 GiB, captured after KV is sized. At 0.92 both probes ran out of memory (one in sampler warm-up, one in graph capture).
- [memory] Why can KV not slow this benchmark? -> KEY: 64 requests use about 2,048 tokens of 42,864 (4.8%); the scheduler never waits for blocks.
- [mixed] Why does mixing adapters slow decode? -> KEY: Base weights are read once for all requests; each distinct adapter is its own small multiply with its own weights. Consistent with the data, not measured (0.27.1 source reading).
- [mixed] How much of the 1,290 is extra bytes, and how much tiny multiplies? -> KEY: Not measured. Only the size of the cost was.
- [mixed] Why do idle slots cost throughput? -> KEY: The kernels launch max_loras + 1 slices (65 at 64 slots, 2 at 1) and empty ones still launch (0.27.1 source reading). How much that explains is unmeasured.
- [costs] Heterogeneity cost against registered-slot cost at 64 slots? -> KEY: −1,290 against −450 tokens/s, 2.87 times.
- [costs] Which cost is paired inside a start, and why does it matter? -> KEY: Heterogeneity: both regimes run in every start, so start-to-start variation cancels. The slot cost compares different starts.
- [knee] The knee rule? -> KEY: The first doubling whose point-estimate loss 1 − T(N)/T(N/2) exceeds τ = 10%, fixed in advance.
- [knee] m(16) and is it resolved? -> KEY: 10.7% [9.2%, 11.5%]: unresolved. 32 and 64 are resolved.
- [tenants] The three tenant bounds at 8 slots? -> KEY: 8 by slots, 250 by memory, 1,784 by throughput; slots bind.
- [tenants] Little's-law numbers behind the memory bound? -> KEY: 64 / 203.72 = 0.31 s; 0.114 × 0.31 = 0.036; 9 / 0.036 = 250.
- [tenants] What does "8 tenants" count? -> KEY: Adapters active in one batch at 64 in flight, all resident: a floor, not customers.
- [gate] Gate pass condition? -> KEY: 90% interval of the median (synthetic − real)/real inside ±5% for TTFT p50 and throughput, and the real-versus-real check inside ±5% too.
- [gate] Resolved but outside ±5%, or unresolved: verdicts? -> KEY: Resolved but outside: fail (a finding). Unresolved: inconclusive, never a pass.
- [memory layout] [draw] Draw the 24 GB card at 1, 8 and 64 slots. -> KEY: Stacked bars of 23.52 GiB: weights 7.55 (derived), slots 0.08 / 0.62 / 4.94, runtime 0.44 (derived), KV 10.74 / 10.20 / 5.89, graphs 1.28 outside the budget, left over 3.43.
- [decode step] [draw] Draw one decode step for 64 requests: one adapter against 64 adapters. -> KEY: One shared base multiply for all rows. Adapter multiplies grouped by adapter: 1 working slice with 64 requests, or 64 with 1 each; 65 slices launched. Mechanism hedged: consistent with the data, not measured.
- [throughput] [draw] Sketch the throughput chart: tokens/s against slots. -> KEY: Log slot axis. Concentrated falls gently, 3,577 to 3,127; spread falls from 3,568 to 1,835. The gap is the heterogeneity cost, the top line's fall the slot cost.
- [two dials] [draw] Draw the two-dial model. -> KEY: Slots: KV capacity (a tenant bound by Little's law) and launch grid (the slot cost). Adapters in a batch: heterogeneity cost, then the knee. Tenants = the smallest of three bounds.

## Review schedule

- Day 1 (after study): Cards 1 to 12. Draw the memory layout and the decode step on paper. Give the 60-second explanation aloud.
- Day 3: Cards 13 to 20. Drills 1 to 6 without notes. Redo the slot estimate from a blank page.
- Day 7: Drills 7 to 12 aloud. Redo the 2,048-token estimate. Draw the two-dial model and attach every number.
- Day 21: The design scenario in 20 minutes on a whiteboard, then compare with the outline. Run the lab if not done. All draw cards.

## Assumed numbers

Not from the study page's sources:

- 2,000: Customers in the design scenario: a round number chosen for the exercise.
- 2,048: A shorter context chosen for the what-if estimate and the lab; the measured request shape is 29 tokens.
- 316 MiB, 0.31 GiB: 4 × 79 MiB for rank 64, assuming slot memory scales linearly with rank. The 1.254 factor was measured at rank 16 only.
- 252 MiB, 39 slots: Theory only: 4 × 63 MiB, and 9.70 GiB / 0.246 GiB.
- 19.7 GiB: 64 × 316 MiB for rank 64 at 64 slots, under the same scaling assumption.
- 7.99: worked out, 7.55 + 0.44: base weights plus runtime and activation, both derived in the unit's derived_numbers.
- 10.82: worked out, 18.81 − 7.99.
- 1.125: worked out, 8,192 × 144 / 1,048,576 GiB: one 8,192-token context at 144 KiB a token.
- 9.70: worked out, 10.82 − 1.125 = 9.695.
- 125.8: worked out, 9.695 / 0.0771 = 125.7, floored to 125 slots.
- 1.254: worked out, 79.0 / 63.0: measured slot size over theory, at rank 16 only.
- 36.27: worked out, 74,288 / 2,048 = 36.27; floored to 36.
- 7.306: worked out, 64 × 0.11416.
- 7333.9: worked out, 36 × 203.72 = 7,333.92.
- 1003.8: worked out, 7,333.92 / 7.306 = 1,003.8; economics.py floors the product to 1,003.
- 0.11416: worked out, 100,000 requests a month × 3 / (730 h × 3,600 s) = 0.11416 requests a second.
- 50.62: worked out, 1.1095 × 730 / 16 = 50.62 dollars a month per tenant at 16 tenants.
- 917504: worked out, 16 × 57,344 numbers a layer (in + out summed over the seven projections is 57,344).
- 57344: worked out, 6,656 + 3,584 + 3,584 + 6,656 + 3 × 12,288, from the Qwen3-4B shape constants in the unit's cited plan.
- 1048576: worked out, 1,024 × 1,024 bytes in a MiB; the conversion between MiB, GiB and tokens.
- 125: worked out, floor(125.7): whole slots only.
- 203.72: worked out, median per-start spread request rate at 8 slots, 203.72 requests/s, as in the unit's derived 1784.6 entry.
- 1003: worked out, floor(1,003.8), as multilora/economics.py floors.
- 1.2: worked out, 16 × 79 MiB = 1,264 MiB = 1.23 GiB.
- 228: worked out, 2,000 × 0.114 = 228 requests a second.
- 9.07: worked out, 74,288 / 8,192 = 9.07.
- 4.8: worked out, 2,048 / 42,864 = 4.8%.
- 0.246: worked out, 252 MiB / 1,024 = 0.246 GiB.

## Drill mode (paste this to an AI chat)

You are my drill coach for this practice set. The brief above is the only ground truth. Lines
marked KEY and RED FLAG are for you: never show them before I have answered.

Settings (I may change these at any time):
- SECTION: all (default) | check | estimation | drills | scenario | cards
- PACE: one question at a time

Rules:
1. Ask one question at a time, in the order of the brief unless I pick a section. Start with
   "Check yourself first", then the drills from easy to hard. Wait for my answer.
2. Grade against the KEY: say what I got, what I missed (quote the KEY point), and score me
   0 (miss), 1 (partial) or 2 (solid). Five lines at most.
3. If my answer falls into the RED FLAG, name it ("that is the red-flag answer: ...") and ask
   me to try again before moving on.
4. Do not add facts the brief lacks. If I ask beyond it, say "the brief does not say".
5. Estimation: let me show my steps before you reveal the KEY steps. Accept an answer within a
   factor of 2 if the steps are sound.
6. Scenario: let me talk it through; then check my answer against the KEY outline and pitfalls.
7. Cards: show only the front. For a [draw] card, ask me to describe my sketch in words, then
   compare it with the KEY.
8. Keep a list of everything I scored 0 or 1. Repeat those items later in the session, and at
   the end tell me which to re-test in each slot of "Review schedule".
9. At the end give a score table and the three items to re-test first.
10. Start now with the first question.
