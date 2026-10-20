# Practice: where a vLLM cold start goes: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: Where a vLLM cold start goes. About 35 minutes.

## Objectives

- Draw one cold start as a time-ordered bar, naming what each cache shrinks and which block cannot be placed in order.
- Compute KV cache tokens from the card, utilisation, weights, profiling peak and bytes per token, then the requests held at a length.
- Explain why a warm cache directory gave 0.99 GiB more KV cache, and say what the log shows and what it does not.
- Tell clock A from clock B, name what sets clock A's resolution, and say what platform time holds.
- Justify three arms and the interval on the difference of contrasts, and say what claim an interval crossing zero allows.
- State three limits of the result and one platform design that warms the cache directory on deploy.

## Check yourself first

### Check 1

Q: An 8B-parameter model in 16-bit weights: roughly how much GPU memory do the weights take, and what else has to fit?
KEY: About 16 GB (this unit's log: 15.27 GiB). Also the KV cache and the working memory the engine measures at its profiling peak.
If missed, review: GPU memory (VRAM) (P1: hbm)

### Check 2

Q: A bootstrap interval on a median: what is resampled, and can the interval reach a value no run took?
KEY: The runs, with replacement; each resample gives a median. Yes: a median can fall between two runs, so the interval can span a gap in the data.
If missed, review: Spread versus interval (P2: interval)

### Check 3

Q: Why interleave arms in shuffled triples instead of running them in blocks?
KEY: Slow drift, such as a busy hour on the rented GPUs, then lands on all three arms instead of posing as an arm effect.
If missed, review: Paired, interleaved runs (P2: pairing)

## Estimation drills

### Estimate 1: KV cache capacity on the 24 GB card

Problem: From the log: the card reports 23.52 GiB, vLLM plans with 0.92 of it, weights plus non-torch memory use 15.54 GiB, and the profiling peak is 1.18 GiB (cold) or 0.19 GiB (warm). Assume Qwen3-8B keeps 2-byte K and V for 36 layers, 8 KV heads, head dim 128. How many tokens fit, and how many 8,192-token requests?

KEY steps:

1. Budget: 0.92 × 23.52 = 21.64 GiB.
2. KV memory: 21.64 − 15.54 − 1.18 = 4.92 GiB cold; 21.64 − 15.54 − 0.19 = 5.91 GiB warm.
3. Bytes per token: 2 (K and V) × 36 × 8 × 128 × 2 bytes = 147,456 B = 144 KiB (the shape is assumed).
4. Tokens: 4.92 GiB / 144 KiB ≈ 35,826 against the log's 35,792, which is 2,237 blocks of 16 (block size assumed); 5.91 GiB gives ≈ 43,031 against 43,040. Rounding in the logged GiB explains the gap.
5. Gain: 0.99 GiB / 144 KiB ≈ 7,209 tokens against the observed 7,248. One GiB of profiling peak costs about 7,282 tokens.
6. Requests: 35,792 / 8,192 = 4.37 → 4 and 43,040 / 8,192 = 5.25 → 5; at 2,048 tokens, 17 against 21.

KEY answer: Close to the logged 35,792 and 43,040 tokens: 20.3% more warm, 4 against 5 whole 8,192-token requests, 17 against 21 at 2,048.

### Estimate 2: Does the weight cache pay for itself?

Problem: Use the post's illustrative prices (assumptions, not measured): $1.00 per GPU-hour, $3.50 a month for the volume, 24 scale-ups a day. The weight cache saves 15.60 s per scale-up. At how many scale-ups a day does it break even?

KEY steps:

1. Saving per scale-up: 15.60 s × $1.00 / 3,600 s ≈ $0.00433.
2. Volume per day: $3.50 / 30.42 days ≈ $0.115.
3. Break-even: 0.115 / 0.00433 ≈ 26.6 scale-ups a day.
4. At 24 a day the saving is 24 × 0.00433 ≈ $0.104 a day against $0.115: a small loss, a marginal call.
5. The compile cache stores for free (26.13 s saved per scale-up, break-even 0.16 a day), but each version change pays a cold compile again.

KEY answer: About 26.6 scale-ups a day, so 24 a day does not quite pay. Every dollar figure rescales with your own prices.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 11

Q: Why three arms, and not two or four?
KEY: A to B changes only the weight cache and B to C only the compile cache, so each saving gets its own one-step comparison. Two arms would test only weights; that was the fallback had this vLLM not compiled at startup, and it does. The fourth cell (weights cold, compile warm) has no operational meaning. A baked-image arm only moves the bytes into the image pull, inside the unsplit platform residual.
RED FLAG: "More arms is always better", or proposing the baked image without saying its bytes move into a time the study cannot observe.

### Drill 2 of 11

Q: What is in platform time, and what is not?
KEY: Platform time is total cold start minus the worker clock's time: container and handler start, teardown and up to one 5 s poll of lag. It is the one allowed cross-clock subtraction, a residual rather than a measured phase. RunPod's own queue delay was about 0.13 s (median), so it is not queueing.
RED FLAG: "Platform time is the queue." Or treating it as a measured phase.

### Drill 3 of 11

Q: H1 says weight handling is over half of worker-clock time. Does weight loading dominate a cold start?
KEY: H1 holds by its pre-registered definition: weight handling is a median 0.58 of worker-clock time in arm A, above half in all 100 runs. But that phase runs from launching vllm serve to the "Model loading took" line, so it is mostly server start-up (28.19 s median) beside vLLM's own load (17.40 s of 79.09 s, about 22%). "Weights dominate" claims more than the data shows.
RED FLAG: "Yes, weights dominate cold start", read straight off the 0.58.

### Drill 4 of 11

Q: What is clock A's resolution, and what does it do to your intervals?
KEY: The laptop learns a job has finished only at a status poll, every 5 s. Clock A's spans repeat on a grid of about 5.175 s (289 of the 299 repeat-host runs lie within 0.25 s of it), so totals move in steps: arm A has runs at 80.92 to 81.16 s and at 85.72 to 85.89 s, none between. That is part of why the interval on the difference is wide. On the worker clock the same difference is −12.16 s [−15.54, −10.74], an exploratory check, not the pre-registered result.
RED FLAG: "The cloud is noisy." Or swapping in the narrower worker-clock interval after seeing it.

### Drill 5 of 11

Q: Why is the compile cache's interval, 25.97 to 31.01 s around 26.07 s, lopsided?
KEY: B's runs ranked 41 to 56 lie at 65.35 to 65.80 s and rank 57 is 70.29 s, while C's median is steady near 39.4 s. A resample that draws few of B's low runs, about one in ten, lifts B's median into the 70 s cluster: 70.4 − 39.4 = 31.0, the interval's top. The low runs are packed, so the bottom sits only 0.10 s under the estimate. The interval shows where the median can jump, given the gaps in the data.
RED FLAG: "The bootstrap is broken", or reaching for a t-test because the interval is asymmetric.

### Drill 6 of 11

Q: Why does a warm compile cache leave more KV cache? Show the arithmetic, and say what is measured.
KEY: vLLM plans with 0.92 of the card: 0.92 × 23.52 = 21.64 GiB. The KV cache gets what is left after weights and non-torch memory (15.54 GiB) and the profiling pass's peak: 21.64 − 15.54 − 1.18 = 4.92 GiB after a cold compile, 21.64 − 15.54 − 0.19 = 5.91 GiB after a warm one, 35,792 against 43,040 tokens. It is sized once, so it is fixed for the replica's life. The log shows the drop in peak, not its cause; H5 registered the compiler's memory still being resident during profiling.
RED FLAG: "The compiler leaks memory", or "it frees up after compile, so it does not matter", or stating the cause as measured.

### Drill 7 of 11

Q: Is "one more concurrent request" the right way to state the KV gain?
KEY: Not as the headline. 43,040 against 35,792 tokens is 20.3% more (7,248 tokens). Whole requests held depend on length: at 8,192 tokens, 4.37 → 4 against 5.25 → 5; at 2,048 tokens, 17.48 → 17 against 21.02 → 21. Report tokens, and give concurrency only for a stated length.
RED FLAG: "25% more users" (5 against 4), or quoting concurrency without the request length.

### Drill 8 of 11

Q: Arm C reaches "model loaded" 8.85 s sooner than B, with only the compile cache changed. What do you check?
KEY: vLLM's own load time is the same (4.57 vs 4.54 s). The engine log's timestamps put the gap before the engine core starts: the API server's step from the arguments line to architecture resolution takes about 10 s in B and 1 s in C. Arm C warms the whole vLLM cache directory, not only compiled code; a cached model-inspection result is the working guess, not confirmed. A next step would be to warm only part of the directory and watch that gap.
RED FLAG: "Noise", or "it is the compile", or "unknown" with no next step.

### Drill 9 of 11

Q: The volume load took 4.57 s for about 16 GB. Is that the volume's throughput?
KEY: It would be about 3.6 GB/s, high for network storage. All 300 runs landed on one host, and the first arm B run after a 19.8 h gap spent 17.45 s in vLLM's load, so a warm host cache is one possible reading, unverified. Treat 4.57 s as a warm-host figure until it is measured on fresh hosts.
RED FLAG: Quoting 4.57 s as the volume's throughput for any host.

### Drill 10 of 11

Q: Which cache do you build into a platform, and how do you justify it?
KEY: Warm the compile cache in the deploy pipeline. It costs nothing to store, but a change of engine version, model, hardware or flags invalidates it, so otherwise the first scale-up after every upgrade pays the cold compile again (18.5 s here). The weight cache is a volume billed continuously: at the post's illustrative prices it breaks even at 26.6 scale-ups a day. Say which numbers are assumptions.
RED FLAG: "Cache everything on a shared volume" with no invalidation story, or quoting the break-even as a measured result.

### Drill 11 of 11

Q: What does the study not tell you about a hundred replicas scaling at once?
KEY: Nothing: every run was one replica alone, so contention on the volume, registry pulls and many hosts starting together were not tested. The one first-touch run, an image pull on a host that had never seen it, took 2266.6 s, far above every cache effect (15 to 26 s). If scale-up can reach new hosts, image distribution may dominate; that is one observation, not a headline.
RED FLAG: Extrapolating this study's seconds to fleet behaviour.

## Design scenario

Prompt: You run a serverless inference platform. Customers deploy 7B to 14B open-weight models on 24 GB GPUs. Product wants the first token of a scale-from-zero replica within 30 s at p95, and engine upgrades ship every two weeks. Design the cold-start path, and say what you would measure.

KEY outline:

1. Decompose before optimising: a worker clock around the engine with log-line timestamps, and a platform clock finer than a 5 s poll. Budget platform, start-up, weight load, compile, profiling, capture, ready and first token.
2. Compile and engine caches as build artifacts: in CI, start the engine once per engine version, model revision, GPU model and flag set, and publish the cache directory versioned. Check the key at start and alert on a miss. Here a warm directory was worth about 26 s a start and 20.3% more KV cache.
3. Weights: a volume or node-local copy beat the hub here (vLLM's load 17.40 s against 4.57 s), but 4.57 s may be a warm-host figure. Measure first reads on fresh hosts before promising it, and weigh the volume's fixed cost against scale-up frequency.
4. Image distribution: the one first-touch run took 2266.6 s, far above every cache effect. Pre-pull on node join and keep the image warm; this study has one observation, not a rate.
5. Capture and readiness: graph capture is a flat 4 s here, and skipping it (--enforce-eager) saves that per start but costs on every token after, so it suits only short-lived replicas. Gate traffic on /health, and check per engine version that warm-up finishes before it answers (true for 0.27.1 here).
6. Capacity: report KV tokens per replica as an indicator. A cold compile cost 20.3% of it for the replica's life here.
7. Measure: p50 and p95 time to first token from zero, split by host warmth; cache-key miss rate after each upgrade; KV tokens per replica; and contention when many replicas start together, which this study did not test.
8. Trade-offs: the cache matrix grows with GPU models, versions and flags, so build only what the fleet runs. A warm pool costs idle GPU-hours; compare it with the break-even arithmetic.

KEY pitfalls:

- Quoting this study's seconds for other GPUs, models, engine versions or providers: the seconds do not transfer, the mechanisms do.
- Promising the weight-cache speed-up from warm-host numbers: all 300 runs used one host.
- A compile cache with no key check, so a routine upgrade turns it cold in silence.
- Reporting a p99 or a mean from a hundred starts per set-up.
- Treating a first-touch image pull as a normal start, or ignoring it.

## Lab

Cost: no cost
Goal: See the poll grid, the log localisation, the memory line and the exact re-derivation on your own laptop.
Note: An optional paid extension (warming only part of the vLLM cache directory on one rented GPU) would test the cause of the head start; it is not part of this lab and is untested.

Setup:

- A checkout of the repo with the committed data/campaign.jsonl. Use .venv/bin/python and never uv run.
- No GPU, no network and no paid call.

Steps:

1. Run .venv/bin/python scripts/analyse.py --store data/campaign.jsonl > /tmp/a1_analysis.json, then cmp /tmp/a1_analysis.json data/analysis.json. Expect no output: the file reproduces byte for byte.
2. Run .venv/bin/python scripts/weights_phase_check.py --store data/campaign.jsonl. Expect start-up before load of 28.19, 25.28 and 16.67 s beside vLLM-reported loads of 17.40, 4.57 and 4.54 s.
3. Take each run's clock A span (t_total_job from coldstart.analysis.metrics.derive) and fold it modulo trial periods around 5 s. The period with the tightest bunching is about 5.175 s.
4. Plot an ECDF of t_total per arm over the repeat-host runs (drop the one first-touch run). Expect stairs about 5 s apart.
5. Call harness.stats.bootstrap_contrast_difference(a, b, c, seed=3) on t_process, then on t_total. Expect about −12.16 [−15.54, −10.74] and −10.39 [−20.30, −5.54].
6. For each run's engine log lines, take the timestamps of the non-default args line and the Resolved architecture line, and print the median gap per arm. Expect 10, 10 and 1 s.
7. Read the Desired GPU memory utilization and Actual usage log lines, and recompute KV memory and tokens with the calculator on this page.

Record:

- Byte identity of the analysis file
- Fitted poll period, and how many of the 299 spans lie within 0.25 s of it (expect 289)
- Interval widths on the worker clock and the laptop clock
- Median engine-log gaps per arm
- KV memory and tokens against the logged 4.92 and 5.91 GiB, 35,792 and 43,040 tokens

KEY expected result: Everything reproduces from the committed store: identical analysis file, the three start-up figures, a poll grid near 5.175 s, a worker-clock interval about a third as wide as the laptop-clock one, a 10 s, 10 s and 1 s architecture gap, and KV numbers within rounding of the log.
KEY what it shows: The clock's resolution sets interval width, the engine log holds more than the summary, and the memory arithmetic closes within rounding.

## Calculator

KV cache capacity Defaults are arm B's logged values (cold compile); set the peak to 0.19 for arm C. Card, utilisation, fixed memory and peak come from the engine log. Bytes per token and request length are assumptions, listed below.

Inputs (default, range):

- Card memory: 23.52 GiB (range 8 to 80)
- Utilisation fraction: 0.92 (range 0.5 to 0.98)
- Weights + non-torch: 15.54 GiB (range 4 to 70)
- Profiling peak: 1.18 GiB (range 0 to 6)
- KV bytes per token: 144 KiB (range 16 to 1024)
- Request length: 8192 tokens (range 256 to 32768)

Outputs at the defaults:

- KV cache memory = 4.92 GiB  [card * util - fixed - peak]
- Tokens that fit = 35,814  [max(0, floor((card * util - fixed - peak) * 1048576 / kib))]
- Whole requests held = 4  [max(0, floor(floor((card * util - fixed - peak) * 1048576 / kib) / req))]
- Tokens per GiB of peak = 7,282  [1048576 / kib]

## Recall cards

- [phases] List one cold start's phases in clock order. -> KEY: Platform, start-up before load, weight load, compile, profiling, unattributed engine start (device initialisation and KV allocation, not split by the log), graph capture, ready check, first request.
- [phases] Median start-up before load and vLLM-reported load, per arm? -> KEY: A: 28.19 s and 17.40 s. B: 25.28 s and 4.57 s. C: 16.67 s and 4.54 s.
- [caches] What did the weight cache (A to B) shrink? -> KEY: vLLM's load, 17.40 → 4.57 s. Start-up before load barely moved, 28.19 → 25.28 s, and compile stayed near 19 s.
- [caches] What did the warm cache directory (B to C) shrink? -> KEY: Compile, 18.79 → 0.33 s, and start-up before load, 25.28 → 16.67 s. vLLM's load did not change.
- [caches] Where in the engine log is arm C's start-up head start? -> KEY: Between the arguments line and architecture resolution, in the API server before the engine core: median 10 s in A and B, 1 s in C. The cause is unconfirmed.
- [memory] Write the KV budget with this run's numbers. -> KEY: KV = 0.92 × 23.52 − 15.54 − peak: 4.92 GiB at a 1.18 GiB peak, 5.91 GiB at 0.19.
- [memory] KV bytes per token for Qwen3-8B (assumed shape)? -> KEY: 2 × 36 × 8 × 128 × 2 = 147,456 B = 144 KiB, matching the log's 35,792 tokens in 4.92 GiB within rounding.
- [memory] Why does the smaller KV cache from a cold compile last? -> KEY: It is sized once, from the profiling pass's peak, and not resized, so it is fixed for the replica's life.
- [memory] Whole 8,192-token requests held, cold against warm? And at 2,048 tokens? -> KEY: 4 against 5 (4.37 and 5.25); 17 against 21 (17.48 and 21.02).
- [clocks] Where does clock B start and stop? -> KEY: From just before vllm serve is launched to the end of the first request. Requests 2 to 10 are the warm-up tail, subtracted from clock A's span.
- [clocks] What sets clock A's resolution? -> KEY: The 5 s status poll: spans repeat on a grid of about 5.175 s, 289 of 299 within 0.25 s of it.
- [clocks] What is platform time, and what is it not? -> KEY: Total minus clock B time: container and handler start, teardown, up to one poll of lag. Not queueing: RunPod's queue delay was about 0.13 s.
- [stats] The headline difference and its interval? -> KEY: −10.39 s, 95% [−20.30, −5.54] on total cold start: the compile cache saves more.
- [stats] The same difference on the worker clock? -> KEY: −12.16 s [−15.54, −10.74]: exploratory, with no poll lag and platform time left out.
- [stats] Why is B − C's interval, 25.97 to 31.01 around 26.07, lopsided? -> KEY: B's runs ranked 41 to 56 sit at 65.35 to 65.80 s and rank 57 is 70.29 s: a resample can lift B's median into the 70 s cluster, but not far below.
- [stats] If the difference's interval ran from −20 to +3 s, what could you claim? -> KEY: Each cache's own saving, but not the ranking, which needs an interval that excludes zero.
- [design] Why prime arm C outside the campaign? -> KEY: Otherwise its early runs compile cold and later ones do not: a mixture that looks like a trend.
- [design] Why check the cache state before the engine starts? -> KEY: A cold compile creates the directory as it finishes, so checked afterwards every cold run would look warm.
- [design] What was fixed before the campaign, and what was added after? -> KEY: Before: hypotheses, contrasts, exclusion and stopping rules, the headline rule. After, as dated amendments: the first-touch rule (post hoc) and the H4 scoping.
- [limits] Three things this study cannot tell you. -> KEY: Other GPUs, models, engine versions or providers; contention with many replicas at once; whether host placement drives the tail (all runs on one host).
- [ops] What invalidates a compile cache, and what is the platform fix? -> KEY: A change of engine version, model, hardware or flags. Warm it in the deploy pipeline, keyed per combination.
- [draw it: phases] [draw] Draw it: the time-ordered bar for arms B and C, naming which block each cache shrinks. -> KEY: Left to right: platform, start-up before load, weight load, compile, profiling, unattributed, capture to first request. The weight cache shrinks the load block; the warm cache directory shrinks compile and start-up.
- [draw it: clocks] [draw] Draw it: one run as a sequence with both clocks, the 0.25 s health poll and the 5 s status poll. -> KEY: Driver, RunPod, handler, probe, vllm serve. Clock A from the submit to the poll that sees the result; clock B from just before the launch to the first reply; requests 2 to 10 subtracted from clock A's span.
- [draw it: memory] [draw] Draw it: the memory budget for the cold and the warm arm, with its four numbers. -> KEY: A 21.64 GiB budget: 15.54 for weights and non-torch, a peak of 1.18 or 0.19, and 4.92 or 5.91 left for the KV cache.

## Review schedule

- Day 1: Draw the last three cards from memory and check them against the page. Do the first estimation without notes.
- Day 3: Cards 1 to 12 out loud, then drills 1 to 5, then the 2-minute answer in the interview card.
- Day 7: Cards 13 to 21 and the second estimation; drills 6 to 11 with the brief's interview mode.
- Day 21: The design scenario, whiteboarded in 20 minutes; redraw the three draw cards; run the lab if not done.

## Assumed numbers

Not from the study page's sources:

- 36 layers, 8 KV heads, head dim 128: Qwen3-8B's published shape, with 2-byte K and V, not read in this repo. It reproduces the log: 4.92 GiB over 35,792 tokens is about 144 KiB per token.
- 16-token blocks: vLLM's block size, assumed; the log prints tokens, not blocks. Both token counts are multiples of 16.
- $1.00 an hour, $3.50 a month, 24 a day: The post's illustrative GPU price, volume price and scale-up frequency. The study measured seconds, not invoices.
- 2,048 tokens: An assumed average request length for the second concurrency case; 8,192 is the pinned context length.
- 147,456: worked out, 2 (K and V) x 36 layers x 8 KV heads x 128 head dim x 2 bytes, from the assumed shape.
- 144: worked out, 147,456 B / 1,024 = 144 KiB per token.
- 35,826: worked out, 4.92 GiB x 2^30 B / 147,456 B per token = 35,826.2.
- 43,031: worked out, 5.91 GiB x 2^30 B / 147,456 B per token = 43,031.5.
- 7,209: worked out, 0.99 GiB x 2^30 B / 147,456 B per token = 7,208.97.
- 7,282: worked out, 2^30 B / 147,456 B per token = 7,281.8: tokens one GiB of profiling peak costs.
- 2,237: worked out, 35,792 / 16 = 2,237 blocks, exact.
- 17.48: worked out, 35,792 / 2,048 = 17.477.
- 21.02: worked out, 43,040 / 2,048 = 21.016.
- 16.4: worked out, 15.27 GiB x 1.0737 GB per GiB = 16.40 GB.
- 3.6: worked out, 16.40 GB / 4.57 s = 3.59 GB/s.
- 3,600: worked out, Seconds in an hour.
- 0.00433: worked out, 15.60 s x $1.00 per hour / 3,600 s = $0.004333 per scale-up.
- 30.42: worked out, 365 / 12 days in an average month.
- 0.115: worked out, $3.50 / 30.42 days = $0.1151 per day.
- 0.104: worked out, 24 x $0.004333 = $0.104 per day.

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
