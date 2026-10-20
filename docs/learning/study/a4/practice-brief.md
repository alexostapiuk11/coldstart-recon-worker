# Practice: placing twenty models on GPUs: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: Dedicate, swap or share: placing twenty small models on GPUs, and a simulator that missed its own test. About 35 minutes.

## Objectives

- Derive 21, 12 and 10 GPUs at the reference point from the hot rule and pairing, and price them ($850.43 a tenant a month for dedicate).
- Draw one against two vLLM engines on a 24 GB card with GiB labels, and compute each KV ceiling from 114,688 bytes a token.
- Explain with numbers why equal shares give a thrashing spread pool (hit rate 0.00) and a calm bursty one (0.82, pinned included).
- Say which claims are measured, simulated or untested, what the gate covered, and why recalibrating the swap time would not pass it.
- Argue a placement for a new workload from swap time, slowdown, KV ceiling and SLO, and name what you would measure first.

## Check yourself first

### Check 1

Q: What shares a 24 GB card's memory inside one vLLM engine, and which part gets whatever is left?
KEY: Weights, runtime and activation memory, and the KV cache. vLLM gives what remains of the engine's memory budget to the KV cache, so shrinking the budget shrinks the KV cache first.
If missed, review: KV cache (P1: kvcache)

### Check 2

Q: A warm compile cache and a local checkpoint remove which cold-start stages, and which stages remain?
KEY: Platform scheduling, the weight download and compilation go. Process start, imports, the engine's own initialisation and the health check remain: a restart still pays them.
If missed, review: Cold start (P1: coldstart)

### Check 3

Q: A simulator fails its pre-registered validation test. What may you still publish, and how must it be labelled?
KEY: The measured inputs stand. The simulator's outputs are published only as unvalidated, and the failed verdict is itself a result, not something to tune away.
If missed, review: A failed gate is a result (P2: failed)

## Estimation drills

### Estimate 1: Price the reference point from scratch

Problem: Bursty arrivals, s = 1.0, 20 models, one GPU of offered load (8.8946 req/s). Hot threshold 0.7, peak factor 5, and a simulated swap pool of 8 GPUs beside the pinned ones. GPU-hour $1.1095, 730 hours a month, 256 output tokens a request. Derive GPUs, dollars per tenant per month, dollars per million output tokens and load per GPU for the three strategies.

KEY steps:

1. Shares: H = sum of 1/k for k = 1 to 20 = 3.5977, so the top share is 1 / 3.5977 = 0.278 and the second is 0.139.
2. Peak load = share × 1 GPU × 5: 1.39 and 0.695. Only model 1 is hot: ceil(1.39 / 0.7) = ceil(1.985) = 2 pinned GPUs. That leaves 19 tail models.
3. Dedicate = 2 + 19 = 21. Co-locate floor = 2 + ceil(19 / 2) = 2 + 10 = 12 (9 pairs and 1 single). Swap = 2 + the simulated pool of 8 = 10; its search floor would be 3.
4. One GPU-month = 1.1095 × 730 = $809.935.
5. Monthly cost = GPUs × 809.935: $17,008.64, $8,099.35 and $9,719.22. Per tenant (divide by 20): $850.43, $404.97 and $485.96. Dedicate minus swap = 11 × 809.935 = $8,909.29 (8,909.285 exactly; the post prints $8,909.28, rounding down).
6. Output tokens a month = 8.8946 × 256 × 3,600 × 730 = 5,984 million. Dollars per million: 17,008.64 / 5,984 = $2.84; 8,099.35 / 5,984 = $1.35; 9,719.22 / 5,984 = $1.62.
7. Load per GPU = 1 / GPUs: 4.8%, 10% and 8.3%.

KEY answer: 21, 10 and 12 GPUs; $850.43, $404.97 and $485.96 per tenant per month; $2.84, $1.35 and $1.62 per million output tokens; 4.8%, 10% and 8.3% load. Simulated and unvalidated; dollars assume every GPU runs all month.

### Estimate 2: KV ceilings of one engine and of two, from the card

Problem: Card 23.52 GiB, 114,688 bytes of KV per token (Qwen3-1.7B), requests of 2,048 tokens. A lone engine at 0.92 logged 168,464 KV tokens. Find its fixed cost outside the KV cache, predict a split engine's KV at 0.45 and compare with the logged 64,976 (warm) and 55,104 (compiled), then give the three request ceilings.

KEY steps:

1. Per token: 2 (K and V) × 28 layers × 8 KV heads × 128 head dimension × 2 bytes = 114,688 B.
2. Lone budget = 0.92 × 23.52 = 21.64 GiB. Its KV = 168,464 × 114,688 B / 2^30 = 17.99 GiB. Fixed cost outside the KV cache = 21.64 − 17.99 = 3.64 GiB (weights among it).
3. Split budget = 0.45 × 23.52 = 10.58 GiB. Same fixed cost: KV = 10.58 − 3.64 = 6.94 GiB, about 64,970 tokens. The warm engine logged 64,976, so the fixed-cost model is right to within about 10 tokens.
4. The registered 55,104 tokens are 5.89 GiB: the compiled engine's reading, pinned for both (6,319,767,552 bytes, 3,444 blocks of 16 tokens). Each engine gives up about 1.05 GiB against the warm reading.
5. Ratios: budget 0.92 / 0.45 = 2.04; KV 168,464 / 64,976 = 2.6 (the fixed cost); 168,464 / 55,104 = 3.1; the pin 64,976 / 55,104 = 1.18.
6. Ceilings at 2,048 tokens: 168,464 / 2,048 = 82; 64,976 / 2,048 = 31; 55,104 / 2,048 = 26 (26 to 28 were seen running).

KEY answer: Fixed cost about 3.64 GiB; predicted 64,970 warm split tokens (logged 64,976); pinned 55,104; ceilings 82, 31 and 26. A fraction appears to budget one engine rather than partition the card (inferred); the pin is what was tried and it fit.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 12

Q: Why can't you compare dedicate, swap and co-locate at the same number of GPUs?
KEY: At equal counts they cost the same by construction. The variable is the smallest fleet each needs to meet the SLO, found by one shared rule: hot models pinned alike, then the smallest fleet whose every popularity decile meets the 75.6 s p99. Cost follows from that count. Analogy: size each cache tier to its own hit-rate target, not to a shared node count.
RED FLAG: "Compare latency at 12 GPUs each." That lets the fixed count decide the winner.

### Drill 2 of 12

Q: Why is the top model 'hot' in the bursty regime at s = 1.0 but never in the spread regime, even at s = 2.0?
KEY: The rule sizes for peak load: share × 1 GPU × 5 when bursty (a model is ON a fifth of the time), × 1 when spread. At s = 1.0 the top share is 0.278, so 1.39 GPU while ON: over 0.7, ceil(1.39 / 0.7) = ceil(1.985) = 2 pinned GPUs. Spread at s = 2.0 gives the top model 0.627 of a GPU (1 / 1.5962), under 0.7, so none is hot.
RED FLAG: "Hot means a high share." That misses the peak factor, which only the bursty regime has.

### Drill 3 of 12

Q: Why can dedicating at best tie, and what is the finding then?
KEY: Swap's search ends with a pool GPU per tail model and co-locate's with every pair split. Both are dedicate's placement at dedicate's size, so the search stops there and dedicate can tie but never win. 'Never cheapest' is construction plus margin. The simulated margin, about twice the cheapest, is the finding.
RED FLAG: "Dedicating lost because it wastes GPUs." That states the result without the mechanism and hides that part of it is by construction.

### Drill 4 of 12

Q: Co-locate sat exactly at its pairing floor at every evaluable point. What did the simulator add?
KEY: Its counts are arithmetic: pinned GPUs plus half the rest, paired (10 spread; 12, 14, 15, 16 bursty). The simulator only showed that the fully paired fleet meets the 75.6 s SLO, at a p99 of about 2 to 6 s. The uncertainty is whether pairing passes under real interference, not how many GPUs. The exploratory x4 run is where co-locate left its floor.
RED FLAG: Presenting 12 as a fine-grained optimisation result.

### Drill 5 of 12

Q: Halving each engine's memory share cut KV capacity 3.1 times. Walk me through the memory.
KEY: Card 23.52 GiB. A lone engine at 0.92 has 21.64 GiB; its 168,464 KV tokens × 114,688 B are 17.99 GiB, so about 3.64 GiB sits outside the KV cache. A split engine at 0.45 has 10.58 GiB, leaving 6.94 GiB: about 64,970 tokens, and a warm engine logged 64,976. That is 2.6 times. The registered 55,104 is the compiled engine's reading, pinned for both so two warm engines fit: the other 1.18.
RED FLAG: "KV halves because memory halves", or "3.1 times because of the weights" with no numbers.

### Drill 6 of 12

Q: Why did two warm engines at 0.45 each run out of memory when 0.45 + 0.45 leaves room?
KEY: A fraction appears to budget one engine rather than partition the card (inferred; the 1.26 GiB over budget was not itemised). Both engines hit the compile cache, so each took about 64,900 KV tokens. The first held 11.84 GiB against a 10.58 GiB budget, the second 11.16, the worker 0.5: 15 MiB free when the second's graph capture asked for 20 MiB. Pinning KV to 55,104 tokens (6,319,767,552 bytes) gave about 1 GiB back each.
RED FLAG: "The two budgets add to 90%, so it fits." Memory outside the budgets (likely contexts and graphs; not measured) collides.

### Drill 7 of 12

Q: Why does a busy neighbour cost about 2.3 times even with one request in flight, and what would you measure?
KEY: Measured: 2.95 s against 1.27 s at own concurrency 1 with a neighbour at 16, 2.0 to 2.4 times at every load. The mechanism was not measured. Hypothesis only: the engines contend for one GPU's compute and bandwidth, a share of the device that does not depend on your own load; the KV pin keeps their memory apart. Analogy: two pods with no CPU limits on one node. Next: profile both processes at own 1 with neighbour 0, 1 to 15, 16.
RED FLAG: "They compete for KV memory" (KV capacity is pinned and separate; bandwidth is another matter), or stating the contention story as measured.

### Drill 8 of 12

Q: Same per-model shares, yet swap wins when bursty and loses when spread. Show it with numbers.
KEY: Simulated, s = 1.0. Spread, pool 13: hit rate 0.00, 1,094.8 swaps an hour, a swap start every 42.7 s per pool GPU against a 37.8 s median swap. Bursty, pool 8: hit 0.82 over all arrivals, pinned model included (about 0.75 for the pool alone), 96.5 an hour, every 298.5 s. The pool schedules again right after each swap, so a waiting model evicts the LRU serving GPU at once; a 120 s burst spreads one swap over many requests. Analogy: cache thrash.
RED FLAG: "Bursty is lower load." Shares and load are identical by construction; only timing differs.

### Drill 9 of 12

Q: Your SLO is twice the swap time. Defend it, then attack it.
KEY: Defend: a ranking-blind screen chose it before the measurements, counting how many strategies a point tells apart, never which is cheaper; the placeholder 4 s SLO was shorter than one swap. Attack: two swaps of budget absorb a swap, which favours swapping. Even the simulated spread pool at s = 1.0, with hit rate 0.0, met it (worst decile 74.3 s against 75.6). Only one SLO was swept.
RED FLAG: "The SLO was picked to make swap win." It was picked blind, but it does favour swap, and you should say so.

### Drill 10 of 12

Q: Charged 37.8 s per swap the simulator is too slow; charged about 25 s it is too fast. What does that imply?
KEY: No fixed stall fits. Charged 38 s, 2 of 13 bins agree (largest miss 69.2 s; the gate's own run at 37.8 s had 3 of 13 and 67.8 s, so a rounded charge moves a bin); at 28 s, 6; at 25 s, 2 (10.4 s, too fast); each repeat judged on its own swap time still misses 12 of 13. The model has no term for what a swap costs the requests around it (not measured). A calibrated re-run would not pass; measure that cost on one pod.
RED FLAG: "Calibrate the swap time and re-run the gate." That is a forking path, and it still fails.

### Drill 11 of 12

Q: What would a passing gate have bought you here, and what would it still not cover?
KEY: It would cover one GPU, three tenants and swapping only, at 180 s bursts, duty 0.25 and 0.3 of a GPU. It would not cover LRU victim choice across GPUs, fleets of 9 to 25 GPUs, the spread regime, the sweep's 120 s bursts at load 1.0, or co-location, which had two held-out cells and one missed. A credible fleet claim needs a multi-GPU replay per strategy.
RED FLAG: "If the gate passed, the GPU counts are validated."

### Drill 12 of 12

Q: Spread arrivals made the simulated swap pool thrash. Name mitigations a production pool could add, and how you would check them.
KEY: Not tested here: the simulator evicts at once, with no hysteresis. Candidates from cache practice: a minimum residency time before a just-loaded model may be evicted; evict only when a waiter has waited past a threshold; for the cold tail a cheaper switch such as sleep mode (5.0 s, host memory unmeasured). Add the policy to the simulator, compare hit rate and swaps per hour, then replay. Each trades the evicted model's wait against the waiter's.
RED FLAG: Claiming a mitigation works because it sounds standard, or "just add GPUs" without the dollar cost.

## Design scenario

Prompt: You host 50 distinct small models (1 to 4B parameters) for business tenants on 24 GB GPUs. Traffic is office-hours bursty per tenant, total load about 3 GPUs at peak, and the contract SLO is p99 10 s per tenant. Design the placement, and say what you would measure before you commit.

KEY outline:

1. Reframe: 50 models against about 3 GPUs of load is a residency problem. Price each way of keeping models resident (a GPU each, a swap pool, pairs) as this study did, and size every option by one rule, per tenant.
2. The SLO decides first: 10 s is shorter than the 37.8 s process swap measured here (about 25 s on another pod). A pool of process swaps cannot serve a cold request in time; only a switch like sleep mode (5.0 s) could, if 5 s plus service fits, and its host memory is unmeasured.
3. Tiers (a design, not tested here): pin hot tenants by peak load, not average; co-locate pairs only after checking each size's KV ceiling (the 4B pair left 9,456 and 9,520 tokens against a 16,384 floor); keep the cold tail asleep or resident.
4. Interference budget: co-locating won here on headroom, a few seconds against 75.6 s. Against 10 s a 2.0 to 2.4 times slowdown may not fit. That is an inference to measure for the real pairs, including neighbours at 1 to 15.
5. Account per tenant (decile or tenant p99), never the aggregate, which hid the two hottest deciles here.
6. Anti-thrash: the simulated pool evicted at once. Any production policy (minimum residency, wait threshold) must be added to the model and checked, not assumed.
7. Measure first: wake and sleep latency under load, host memory per sleeping model, interference for the real pairs, KV ceilings at the real request shapes, and what a swap or wake costs the requests around it, the term this study lacked.
8. Validate: a pre-registered multi-GPU replay per strategy, then a shadow of production traffic. Publish misses.

KEY pitfalls:

- Copying 'co-locate when spread' without noticing that the SLO is far tighter than 75.6 s.
- Ignoring host memory when proposing sleep mode, which this study never priced.
- Sizing on the aggregate p99, or hot models on average load.
- Presenting a simulated GPU count as a finding after a failed gate.

## Lab

Cost: runs on your machine
Goal: See thrash as a measurable state and see where the sized fleets come from, using the cached sweep and the placement code, with no GPU and no paid call.
Note: CPU only, minutes, read-only. Label every output exploratory and keep it out of data/a4/. A follow-up that needs a GPU (profiling two engines on one card) is not part of this lab and would be a paid run.

Setup:

- Use .venv/bin/python with PYTHONPATH=. and never `uv run`: it re-syncs the venv and has broken byte-compared figure tests.
- Read-only input: build/a4-sweep/evaluations-5f2ab57d0f9f2e86.json (30 repetitions per point). If it is missing, stop: rebuilding it is hours of CPU.
- Write scripts and outputs outside data/a4/, in a scratch folder.

Steps:

1. In a Python session: from placement.evaluate import load_evaluations; ev = load_evaluations(Path(the cache file)). Pick the PointEvaluation whose point.regime is spread, then bursty, with point.s == 1.0.
2. For ev.outcomes['swap'] (one ConfigOutcome per pool size M, ascending) print m, sum(hits) / sum(requests) and the mean of window_swaps per repetition. Plot hit rate against M for both regimes.
3. Re-size with placement.sizing.sized_fleet(ev, list(range(30)), slo) at slo = 75.55 (2 × the 37.78 s median swap) and check it returns the registered 20, 13, 10 (spread) and 21, 10, 12 (bursty).
4. Repeat with slo = 1.0, 1.5 and 3.0 times 37.78 s. Record each strategy's M.
5. Hot rule: from placement.traffic import zipf_shares; from placement.fleet import hot_allocation, family. With shares = zipf_shares(20, 1.0), call hot = hot_allocation(shares, 1.0, 0.7, 5.0), then read len(p.gpus) for each p in family(strategy, shares, hot). Repeat with 0.69.

Record:

- Hit rate and mean swaps per repetition at each pool size, both regimes
- Sized M per strategy at each SLO multiple
- Pinned GPUs and the dedicate and co-locate sizes at hot fraction 0.7 and 0.69

KEY expected result: Predictions to check, not facts. Step 2: spread hit rate near 0 until the pool nears the number of tail models, bursty hit rate from the pinned share (0.28) to 0.82 at M = 10 (pool 8; 0.65 at M = 8). Step 3 reproduces the registered sizes. Step 4: swap's M should rise as the multiple falls and fall as it rises, while co-locate and dedicate stay put. Step 5: pinned GPUs 2 at 0.7 and 5 at 0.69; dedicate 21 then 23, swap's ladder 3 to 21 then 6 to 23, co-locate's 12 to 21 then 14 to 23.
KEY what it shows: Which counts are arithmetic and which come from the SLO search, how fragile swap's win is to the SLO choice, and thrash as a number (hit rate).

## Calculator

Hot rule and fleet sizes Top two models' peak loads: share × 1 GPU × 5 bursty, × 1 spread (s = 1.0 bursty: 1.39 and 0.695; s = 2.0: 3.13 and 0.783). Valid while the third is not hot. A load exactly at the threshold is not hot in the rule (strict >) but is pinned here. Dedicate and floor are arithmetic; swap is simulated.

Inputs (default, range):

- Top model's peak load: 1.39 GPUs (range 0.1 to 4)
- Second model's peak load: 0.695 GPUs (range 0.1 to 1.5)
- Hot threshold: 0.7 GPUs (range 0.5 to 1)
- Models: 20 (range 4 to 40)
- GPU price: 1.1095 $/hour (range 0.5 to 3)
- Hours in a month (assumption): 730 hours (range 500 to 744)

Outputs at the defaults:

- Pinned GPUs = 2  [min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h)]
- Dedicate GPUs = 21  [min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h) + n - (min(1, floor(l1 / h)) + min(1, floor(l2 / h)))]
- Co-locate floor = 12  [min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h) + ceil((n - (min(1, floor(l1 / h)) + min(1, floor(l2 / h)))) / 2)]
- Swap search starts at = 3  [min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h) + 1]
- Dedicate, per tenant = 850.43 $/month  [(min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h) + n - (min(1, floor(l1 / h)) + min(1, floor(l2 / h)))) * rate * hours / n]
- Co-locate floor, per tenant = 485.96 $/month  [(min(1, floor(l1 / h)) * ceil(l1 / h) + min(1, floor(l2 / h)) * ceil(l2 / h) + ceil((n - (min(1, floor(l1 / h)) + min(1, floor(l2 / h)))) / 2)) * rate * hours / n]

## Recall cards

- [core] Total offered load across the 20 models, and each fleet's load per GPU at the reference point? -> KEY: One GPU's worth (8.89 req/s). Dedicate 1 / 21 = 4.8%, swap 1 / 10 = 10%, co-locate 1 / 12 = 8.3% (simulated counts, unvalidated).
- [hot-rule] State the hot rule. -> KEY: Peak load = share × offered GPUs × peak (1 spread, 5 bursty). Hot if above 0.7 of a GPU; a hot model gets ceil(load / 0.7) pinned GPUs, in all three strategies.
- [hot-rule] Why is no model hot in the spread regime? -> KEY: Peak factor 1: the top model is 0.278 of a GPU at s = 1.0 and 0.627 at s = 2.0, both under 0.7.
- [hot-rule] Bursty, s = 1.0: which models are hot and how many GPUs are pinned? -> KEY: Only model 1 (1.39 while ON): ceil(1.985) = 2. Model 2 is at 0.695, 0.005 under 0.7, so it is not hot.
- [ladder] Where do swap's and co-locate's searches start and end? -> KEY: Swap: pinned plus a pool of 1, up to dedicate's size. Co-locate: pinned plus half the rest, paired, up to dedicate's size. Both end at dedicate's placement.
- [ladder] Why can dedicate at best tie? -> KEY: Both other searches end at dedicate's placement at dedicate's size, and sizing never searches past it.
- [ladder] How often did co-locate need more than its pairing floor? -> KEY: Never, at any of the 11 evaluable points (simulated). Its counts are arithmetic.
- [kv] KV bytes per token for Qwen3-1.7B, and how? -> KEY: 2 (K and V) × 28 layers × 8 KV heads × 128 head dimension × 2 bytes = 114,688 B.
- [kv] KV tokens and request ceilings, alone against split (pinned)? -> KEY: 168,464 tokens, 82 requests; 55,104 tokens, 26 requests (2,048 tokens each; 26 to 28 were seen running).
- [kv] What part of the 3.1 times KV shrink is fixed cost, and what part is the pin? -> KEY: The fixed cost (about 3.6 GiB outside the KV cache) gives 2.6 times (168,464 / 64,976). Pinning both engines to the compiled engine's 55,104 gives the other 1.18.
- [kv] Why did two warm engines at 0.45 each fail? -> KEY: The first held 11.84 GiB (budget 10.58), the second 11.16, the worker 0.5. 15 MiB were free when graph capture asked for 20 MiB.
- [interference] Busy-neighbour slowdown range, and the value at own concurrency 1? -> KEY: 2.0 to 2.4 times at every measured load; at own 1, 2.95 / 1.27 = 2.3 times.
- [interference] Why does co-locating still halve the spread fleet? -> KEY: SLO headroom: its latency is about 2 to 6 s against 75.6 s. Exploratory: four times the penalty still wins spread by one GPU (12 against 13) and loses bursty (20 against 10).
- [swap] Swap median, and its biggest stage? -> KEY: 37.8 s. Process start, imports and the health check take 27.8 s (74%); weight load only 2.2 s.
- [swap] Sleep mode: switch time, and why it was never simulated? -> KEY: 5.0 s median over 8 repeats. The host memory a sleeping engine holds was not measured, so it could not be priced. The card read 2,069 MiB asleep against 20,081 MiB awake.
- [lru] Simulated hit rate and swaps an hour, spread against bursty at s = 1.0? -> KEY: Spread (pool 13): 0.00 and 1,094.8. Bursty (pool 8): 0.82 over all arrivals, pinned included (pool alone about 0.75), and 96.5.
- [slo] Why does an SLO of twice a swap favour swapping? -> KEY: A swap fits inside the budget: even a spread pool with hit rate 0.0 met it, worst decile 74.3 s against 75.6 s (simulated).
- [slo] What does sizing on the aggregate p99 pick, and what breaks? -> KEY: Swap at 9 GPUs; deciles 1 and 2 sit at 87.7 and 77.2 s against 75.6 s. Per-decile sizing needs 10.
- [gate] The gate's pass rule? -> KEY: At least 10 judged 30 s bins and at most half missing, band edges widened by 0.001 s; the predicted swap count within the real range, plus or minus 1.
- [gate] Charge 25 s a swap instead of 37.8 s: what happens? -> KEY: The error flips sign (too fast), and 12 of 13 bins still miss when each repeat is judged on its own swaps. No fixed swap cost fits.
- [money] GPU-month, and dedicate's dollars per tenant per month at the reference point? -> KEY: 1.1095 × 730 = $809.935; 21 × 809.935 / 20 = $850.43.
- [draw] [draw] Draw a 24 GB card with one engine at 0.92 and two at 0.45 each: fixed cost, KV, the pin's give-up, and memory outside the budgets. -> KEY: One engine: fixed 3.64 + KV 17.99 + outside 1.88 = 23.52 GiB. Two: 2 × (fixed 3.64 + KV 5.89 + pin give-up 1.05) + outside 2.35 = 23.52 GiB. All subtractions, not measurements.
- [draw] [draw] Draw the three ladders at bursty s = 1.0 and mark where dedicate ties. -> KEY: Dedicate: one point, 21. Swap: 3 to 21, sized 10. Co-locate: 12 to 21, sized 12. Both ranges end at 21, dedicate's placement.
- [draw] [draw] Draw the swap pool's loop: what happens right after a swap finishes? -> KEY: Dispatch the loaded model's queue, then schedule again. If a model still waits with no GPU, evict the least recently used serving GPU now, so a pool with a waiter swaps back to back.

## Review schedule

- Day 1 (after study): Prerequisite check, then redraw the memory layout and the ladders from memory. Cards 1 to 12. Say the 30-second pitch aloud.
- Day 3: Estimation 1 on paper, no notes; target every dollar figure within 1%. Cards 13 to 25 including the draw cards. Drills 1 to 6.
- Day 7: Estimation 2 and the calculator. Run the lab, steps 1 to 3. Drills 7 to 12 aloud, admitting limits.
- Day 21: The design scenario in 20 minutes on a whiteboard, then compare with the outline. All draw cards. Explain what the gate did and did not cover.

## Assumed numbers

Not from the study page's sources:

- 50 models, 3 GPUs, 10 s: The design scenario's parameters: round numbers chosen for the exercise, not from the study.
- 730 hours: Hours in a month, the post's own assumption for dollar figures (every GPU runs all month).
- 1.5962: worked out, Sum of 1 / k^2 for k = 1 to 20 = 1.5962 (computed): the s = 2.0 case of the unit's derived 1.596.
- 3.5977: worked out, H = sum of 1 / k for k = 1 to 20 = 3.5977 (computed; the unit derives 0.278 = 1 / 3.5977).
- 8.8946: worked out, data/a4/analysis.json total_rate_rps = 8.8946 requests a second, one GPU's measured saturation (8.89 in the post).
- 17008.64: worked out, 21 GPUs x $809.935 a GPU-month = $17,008.635 (analysis.json cost 17,008.64 for dedicate).
- 8099.35: worked out, 10 GPUs x $809.935 = $8,099.35 (swap).
- 9719.22: worked out, 12 GPUs x $809.935 = $9,719.22 (co-locate).
- 8909.29: worked out, 11 x $809.935 = $8,909.285 exactly; the post prints $8,909.28, rounding down.
- 5984: worked out, 8.8946 requests a second x 256 output tokens x 3,600 s x 730 h = 5,984.0 million output tokens a month.
- 17.99: worked out, 168,464 tokens x 114,688 B / 2^30 = 17.99 GiB of KV in the lone engine.
- 3.64: worked out, Fixed cost outside the KV cache: 21.64 - 17.99 = 3.64 GiB (the unit derives it as about 3.6).
- 6.94: worked out, Split engine: 10.58 - 3.64 = 6.94 GiB, which is 64,976 tokens x 114,688 B / 2^30 = 6.94 GiB.
- 64970: worked out, (10.584 - 3.6445) GiB x 2^30 / 114,688 B = 64,970 tokens predicted for a warm split engine; logged 64,976.
- 5.89: worked out, 55,104 tokens x 114,688 B / 2^30 = 5.89 GiB (6,319,767,552 bytes).
- 1.88: worked out, Card minus the 0.92 budget: 23.52 - 21.64 = 1.88 GiB outside the budget.
- 2.35: worked out, Card minus two 0.45 budgets: 23.52 - 2 x 10.58 = 2.35 GiB outside both budgets.
- 2.04: worked out, 0.92 / 0.45 = 2.04, the ratio of the two budgets.
- 75.55: worked out, 2 x the median swap 37.775 s = 75.55 s (the unit rounds it to 75.6; analysis.json slo_seconds = 75.5504).
- 37.78: worked out, Median swap 37.775 s (data/a4/analysis.json validation.swap_median_s), the unit's 37.8.
- 1.26: worked out, The first engine's 11.84 GiB less its 10.58 GiB budget = 1.256 GiB, to two decimals.
- 0.75: worked out, (0.8203 - 0.282) / (1 - 0.282) = 0.750: the bursty hit rate with the pinned top model's 0.282 share removed. An estimate, not a stored field.
- 8909.285: worked out, 11 x $809.935 = $8,909.285 exactly (1.1095 x 730 = 809.935); the post prints $8,909.28.

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
