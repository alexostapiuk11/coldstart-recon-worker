# Where a vLLM cold start goes: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: LLM serving on a GPU (P1).

## Why it exists

**Question:** Where does a cold vLLM (P1: vllm) start on a rented GPU spend its time, and which empty cache is worth warming more: the weights or the compiled GPU code (P1: compile)? One also bought serving memory (KV cache (P1: kvcache)).

**Requirements that drove everything:**

- Split one cold start (P1: coldstart) into named phases, and label time that cannot be attributed instead of hiding it. *Why:* The caches act on different phases (weights (P1: weights) on loading, compile (P1: compile) on engine start), so one "startup" bar would hide half the experiment.
- Any two set-ups compared differ only in cache configuration: same image, entrypoint and engine flags. *Why:* Otherwise a difference cannot be pinned on a cache.
- Report each arm's spread as percentiles, and give every comparison its own interval. *Why:* Cold starts are skewed with a heavy tail, so a mean describes no real run. "Cache X matters more" needs its own interval, not two point estimates side by side.
- Commit the hypotheses, which runs get thrown out, when to stop and how the headline is chosen, before the first paid measurement run. *Why:* Git timestamps then show the rules came before the data, and the headline cannot be picked by which result cost the most effort.
- Run on paid GPUs only code already tested offline, and let anyone re-derive every number on a laptop. *Why:* The whole budget was $200, and debugging on live GPUs eats it. A number a reader cannot re-derive must be taken on trust.

## Need to know first

- **Arms A, B and C**: Three cache set-ups. **A**: weights from the model hub, compile cache (P1: compile) cold. **B**: weights from a network volume, compile cache cold. **C**: weights from the volume, compile cache warm.
- **Triples**: One run of each arm, in an order shuffled from a seed. 100 triples make the 300 runs, so a busy hour on the rented GPUs falls on all three arms.
- **Contrast, and difference of contrasts**: A **contrast** is the difference of two arms' medians, with a 95% bootstrap interval (resample the runs 10,000 times, keep the middle 95%): A minus B is the weight cache's saving, B minus C the compile cache's. Their **difference**, (A minus B) minus (B minus C), ranks the caches only if its interval excludes zero; negative favours the compile cache.
- **Two clocks and the platform residual**: **Clock A** (laptop) brackets the whole job; total cold start (P1: coldstart) is its span minus the worker-clock warmup after the first request. **Clock B** (worker) starts just before `vllm serve` is launched. **Platform time** = total minus clock B time, the one allowed cross-clock subtraction: queue, container start, handler set-up, teardown, polling lag.
- **Percentiles and the ECDF**: **p90** is the time 90% of runs finish within; p50 is the median. An **ECDF** plots every run (seconds across, share finished up), so the tail stays visible.
- **The five hypotheses**: **H1**: weight handling is over half of worker-clock time through the first request in arm A. **H2**: volume weights cut it materially. **H3**: compiling is a non-trivial part of engine start, and a warm cache cuts it. **H4**: host differences drive how far p95 sits above the median. **H5**: a warm compile cache leaves more KV cache (P1: kvcache).
- **Pre-registration**: Hypotheses, contrasts, which runs to throw out, when to stop and how to pick the headline, committed in `docs/experiment.md` before any paid measurement run, four days before the published campaign's first run; later additions are dated in git.

## System views (C4)

### Who and what the study touches (context)

RunPod serverless rents the GPU, one job at a time. Weights come from the model hub (arm A) or from a network volume mounted into the worker (arms B and C). Output: a post plus the raw data.

- **Author**: designs, runs and publishes
- **Cold-start study**: 300 measured cold starts, 3 cache set-ups
- **Reader**: inference-platform engineers and managers
- **Network volume**: staged weights and warm compile cache
- **RunPod serverless**: one RTX 4090 job at a time, EU-RO-1
- **Model hub**: Qwen3-8B at a pinned revision
- Author → Cold-start study: designs, runs
- Cold-start study → Reader: post + raw data
- Cold-start study → RunPod serverless: rents GPU jobs
- RunPod serverless → Network volume: arms B, C read
- RunPod serverless → Model hub: arm A downloads

### The runnable parts (container)

The laptop schedules, submits and stores; the worker image runs vLLM on the rented GPU and returns its measurements in the job result. Analysis runs on the laptop only.

- **Driver + scheduler**: laptop: seeded triples, submit, clock A
- **RunPod endpoint**: queues the job, boots a worker
- **JSONL store**: append-only, one line per run
- **Worker image**: handler + probe running vllm serve, clock B
- **Model hub**: weights for arm A
- **Analysis + figures**: laptop only: partition, bootstrap, charts
- **Network volume**: weights for B and C, compile cache for C
- Driver + scheduler → RunPod endpoint: job in, result out
- RunPod endpoint → Worker image: starts container
- Worker image → Model hub: arm A download
- Worker image → Network volume: arms B, C
- Driver + scheduler → JSONL store: appends a record
- JSONL store → Analysis + figures: reads rows

### Inside one run: the worker opened up (component)

Solid boxes run in the worker: the handler sets two cache paths and checks the cache directories; the probe launches `vllm serve`, stamps phase marks on clock B and returns the raw log. Dashed boxes are outside the worker code; the parser and run record are built later on the laptop.

- **Handler**: reads arm and run id from the job
- **Cache config**: arm to two paths: weights, compile cache
- **Cache-dir checks**: empty cold dirs, refuse missing volume, snapshot
- **Stage recorder**: phase marks on clock B
- **Probe**: starts vllm serve, sends ten requests
- **vLLM server process**: prints its own startup phases
- **Result bundle**: marks, raw log, warmup, cache state
- **Log parser (laptop)**: log lines to compile, profiling, capture
- **Run record (laptop)**: one self-describing JSON line
- Handler → Cache config: arm, run id
- Cache config → Cache-dir checks: paths
- Cache-dir checks → Probe: then start
- Probe → vLLM server process: reads stdout
- Probe → Stage recorder: phase marks
- Stage recorder → Result bundle: clock B marks
- Probe → Result bundle: raw log
- Handler → Result bundle: cache state
- Result bundle → Log parser (laptop): log lines
- Log parser (laptop) → Run record (laptop): sub-phases

### One run, in order (dynamic)

Clock A (laptop) runs from step 2; clock B (worker) starts between steps 4 and 5. The caches act in the highlighted steps 5 and 6; the compile cache also shortened step 5 by about 9 s, unexplained. Platform time is everything clock A sees outside clock B.

- **1 Schedule picks arm**: next slot in a seeded, shuffled triple
- **2 Driver submits**: new run id; clock A starts
- **3 Platform boots**: queue, find a 4090, start container
- **4 Handler sets cache**: two paths, snapshot compile cache
- **5 Launch, load weights**: the weight cache acts here: hub or volume
- **6 Engine compiles**: the compile cache acts here; then profile, capture
- **7 Ten requests**: first request, then the latency curve
- **8 Result returned**: bundle rides the job result, not logs
- **9 Record built**: laptop parses the log, builds the record
- **10 Appended**: one line in the store, never retried
- 1 Schedule picks arm → 2 Driver submits: arm
- 2 Driver submits → 3 Platform boots: arm, run id
- 3 Platform boots → 4 Handler sets cache: process starts
- 4 Handler sets cache → 5 Launch, load weights: clock B starts
- 5 Launch, load weights → 6 Engine compiles: model loaded
- 6 Engine compiles → 7 Ten requests: health OK
- 7 Ten requests → 8 Result returned: bundle
- 8 Result returned → 9 Record built: payload
- 9 Record built → 10 Appended: record

## Core decisions

### Three arms, one variable

**Problem:** Two caches start empty: the weights and the compiled code. To rank them, each comparison must change one thing only.

**Options considered:**

- Two arms: hub vs volume weights
- Add a baked-image arm, weights inside the container image
- Add the fourth cell: weights cold, compile cache warm
- One variable, cache configuration, at three levels: A, B, C

**Chosen:** One variable, cache configuration, at three levels: A, B, C

**Why:** A to B isolates the weight cache. B to C isolates the compile cache with weight handling held constant. The configuration is one frozen object that sets two paths, so the single-variable claim is true by structure. A baked image only moves the bytes into the image pull, inside the platform residual the harness cannot split, so it would flatter the weight time unseen. Nobody warms a compile cache while re-downloading weights, so the fourth cell answers no question.

**Cost:** A warm arm needs a primed volume, and a test has to check that the arms differ nowhere else.

### Measure from outside the engine

**Problem:** vLLM's interesting phases are internal, and part of every cold start (queue, container start, image pull) happens before our code exists.

**Options considered:**

- Time startup through vLLM's Python engine API
- One clock, and give all the time to the stages you can see
- Run the real `vllm serve`, bracket it with a worker clock, split phases from its log, and get platform time by subtraction

**Chosen:** Run the real `vllm serve`, bracket it with a worker clock, split phases from its log, and get platform time by subtraction

**Why:** The Python API would measure a startup path nobody deploys. With one clock you cannot detect that it is lying; the implemented check compares the laptop and worker clocks and discards a run whose total leaves no room for a network round trip.

**Cost:** Platform time is one residual holding teardown and polling lag as well as queueing. RunPod's queue and execution durations (clock C) are recorded but not used to split it. Two engine sub-phases (device init and KV allocation) are not delineated by this vLLM build, so they sit merged in an unattributed row. The log patterns are tied to vLLM 0.27.1.

### Interleave the arms in random triples

**Problem:** Conditions on rented GPUs change over hours and days. Run the arms in blocks and a busy evening gets labelled as an arm effect.

**Options considered:**

- Blocks: all of A, then all of B, then all of C
- Interleaved triples: one run of each arm per triple, order shuffled from a seed

**Chosen:** Interleaved triples: one run of each arm per triple, order shuffled from a seed

**Why:** Blocking confounds the cache with time-of-day conditions, and on rented GPUs that confound can be large enough to make or erase the whole effect. The design calls interleaving its most important validity decision. Triples also allow a paired, same-host check as supporting evidence.

**Cost:** A resumed campaign must rebuild the exact schedule, so the harness refuses a resume whose stored arms disagree with the seed. The windows ended up hours apart rather than on separate days, so drift between windows is only partly covered; the post says so.

### Check each arm's cache state

**Problem:** A warm cache leaking into a cold arm, or a cold compile inside arm C, would still produce plausible numbers. The configuration alone does not show what was on disk.

**Options considered:**

- Trust the configuration
- Let arm C's first campaign runs warm the cache
- Prime arm C outside the campaign, isolate cold paths per run, and check the compile-cache state on every run

**Chosen:** Prime arm C outside the campaign, isolate cold paths per run, and check the compile-cache state on every run

**Why:** Without priming, arm C's early runs compile cold and later ones do not: a mixture whose effect grows with run index, which looks like a real trend. So two priming runs go to a separate store, and the second must show the cache present and compile under one second. Cold paths are named by run id so a reused worker cannot hand one run's files to another. The cache state is checked before the engine starts, since a cold compile creates the directory as it finishes; a run whose state disagrees with its arm is discarded.

**Cost:** Priming runs cost GPU time and are excluded from every number. Moving the check to after the engine run would look harmless but quietly discard about two thirds of a paid campaign, so the code carries a do-not-move warning.

### Rank the caches by the difference's interval

**Problem:** Which cache buys more? Two effects, each with its own interval, do not answer that.

**Options considered:**

- Compare the two point estimates
- Subtract the weight-time contrast from the compile-time contrast
- Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Chosen:** Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Why:** "Compile cache mattered more" is only a finding if the gap between the two effects excludes zero. The difference needs one shared unit, so it is computed on total cold start; subtracting weight time from compile time would difference two different quantities. The headline rule, lead with what transfers furthest to other infrastructure, was committed before data.

**Cost:** Total time is noisier than the mechanism units, so the interval is wide: −10.39 s, 95% [−20.30, −5.54]. The pre-registration requires it reported before any ranking claim.

### Report the shape, and what it cannot answer

**Problem:** Cold starts have a heavy right tail, and 100 runs per arm cannot support every summary.

**Options considered:**

- Means and standard deviations
- Publish p99 as well
- Drop the host hypothesis (H4) quietly once every run lands on one host
- p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Chosen:** p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Why:** A mean is pulled by the tail. At 100 runs a p99 is one or two observations, not an estimate. Before the published campaign began (a discarded window had already shown runs piling onto one host), the pre-registration committed to publishing the host count whatever it was. The same single host made every triple host-complete, so the paired check is fully supplied.

**Cost:** The far tail stays unresolved: the post can say that B's largest repeat-host runs were longer than A's, but not why. The question of whether host placement drives the tail is lost.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Split one cold start (P1: coldstart) into named phases, and label time that cannot be attributed instead of hiding it.
  - `clocks` Measure from outside the engine: Engine phases come from vLLM's own log; what it cannot split goes in a labelled unattributed row and a named platform residual, so nothing is hidden.
- R2: Any two set-ups compared differ only in cache configuration: same image, entrypoint and engine flags.
  - `arms` Three arms, one variable: One frozen configuration sets both cache paths, so each arm differs from the next in exactly one thing.
  - `interleave` Interleave the arms in random triples: In blocks, the time of day changes along with the arm, so a busy evening would pose as an arm effect.
  - `state` Check each arm's cache state: A leaked warm cache, or a cold compile in arm C, would make the arms differ in more than their configured cache, and the configuration alone does not show what was on disk.
- R3: Report each arm's spread as percentiles, and give every comparison its own interval.
  - `rank` Rank the caches by the difference's interval: Two savings side by side do not rank the caches; only an interval on their difference can.
  - `shape` Report the shape, and what it cannot answer: A mean is pulled by the tail, so percentiles and the full ECDF describe real runs instead.
- R4: Commit the hypotheses, which runs get thrown out, when to stop and how the headline is chosen, before the first paid measurement run.
  - `rank` Rank the caches by the difference's interval: Leading with what transfers furthest, a rule committed before data, stops the headline being picked afterwards.
  - `shape` Report the shape, and what it cannot answer: H4 was fixed in advance, so it is reported as unanswerable instead of quietly dropped.
- R5: Run on paid GPUs only code already tested offline, and let anyone re-derive every number on a laptop.
  - No decision: It is met by process: in the flow, "Build against the captures; prove it end to end" tests the code on recorded logs and a free fake engine before any campaign run, and "Analyse from the committed store" re-derives every number with no GPU.

**Decisions and the concepts they use:**

- `arms` Three arms, one variable uses Arms A, B and C: Three arms give each cache its own one-step comparison: A to B for weights, B to C for compile.
- `arms` Three arms, one variable uses Contrast, and difference of contrasts: Each adjacent pair of arms yields one contrast, so each cache's saving is measured on its own.
- `clocks` Measure from outside the engine uses Two clocks and the platform residual: Two clocks let platform time be found by subtraction, and let a run whose clocks disagree be caught.
- `interleave` Interleave the arms in random triples uses Triples: Each triple puts all three arms in the same stretch of time, so drift lands on every arm alike.
- `state` Check each arm's cache state uses Arms A, B and C: Each arm has an expected cache state, so a run whose observed state disagrees can be caught and discarded.
- `rank` Rank the caches by the difference's interval uses Contrast, and difference of contrasts: The ranking is the difference of the two contrasts.
- `rank` Rank the caches by the difference's interval uses Pre-registration: The pre-registration requires the difference's interval before any ranking claim, so the claim never appears without it.
- `shape` Report the shape, and what it cannot answer uses Percentiles and the ECDF: p50 to p95 hold up at 100 runs per arm; a p99 would be one or two runs.
- `shape` Report the shape, and what it cannot answer uses The five hypotheses: H4 asked whether host placement drives the tail, and one host cannot answer it.

**Results and the decisions they support:**

- Where each arm's median cold start goes → `arms` Three arms, one variable, `clocks` Measure from outside the engine
- How spread out the runs are → `shape` Report the shape, and what it cannot answer
- The two effects, each measured on its own → `arms` Three arms, one variable
- Which cache bought more: the interval on the difference → `rank` Rank the caches by the difference's interval
- KV cache left for serving, by arm → `arms` Three arms, one variable

## Implementation flow

10 steps in 5 phases, 5 milestones.

Milestones: 4. Build against the captures; prove it end to end (2026-08-28); 5. Pre-register the rules (2026-08-28); 7. Discard the first window and restart (2026-08-31); 8. Run 100 interleaved triples (2026-09-02 to 09-04 UTC); 10. Write up, gate and date the post (2026-09-03 to 09-17).

### Phase 1 of 5: Design (1 step)

1. **Specify one variable at three levels**: Three arms differing only in cache configuration, named phases and two clocks; then a task-by-task harness plan.
   - Output: the design spec and the harness plan, before any code
   - When: 2026-08-17 to 08-19
   - Decision: `arms` Three arms, one variable
   - Evidence: c778863484 (design spec); ddcce86605 (harness plan)

### Phase 2 of 5: Build and prove offline (3 steps)

2. **Build the harness core with no GPU**: Recorder, store, seeded scheduler, clock checks, statistics and figures, tested on a laptop. A cross-module review found five blocking defects, all fixed.
   - Output: a laptop-tested core with a gate deciding which rows are publishable
   - When: 2026-08-19 to 08-20
   - Evidence: 23de7208dc (triple scheduler); bcbca83168 (five defects recorded); 2293b17181 (publishability gate)
3. **Capture three real cold starts**: The one paid step before the pre-registration: engine logs and API responses saved verbatim. vLLM compiles at startup, so arm C stays.
   - Output: fixtures/: three engine logs and three platform status payloads
   - When: 2026-08-28
   - Evidence: 5e10909133
4. **Build against the captures; prove it end to end** [MILESTONE]: Log parser, platform clock, a probe around `vllm serve` and a free stub replaying the real logs; a synthetic campaign through it recovers the known effects.
   - Output: tests/test_end_to_end.py: the whole pipeline runs with no GPU
   - When: 2026-08-28
   - Decision: `clocks` Measure from outside the engine
   - Evidence: 55e44e2154 (log parser); 5c8d29ae22 (probe); 3ed2379328 (end-to-end validation)

### Phase 3 of 5: Prepare the paid run (2 steps)

5. **Pre-register the rules** [MILESTONE]: Hypotheses, contrasts, and the exclusion, stopping and headline rules, committed before any priming or campaign run; the captures shaped it.
   - Output: docs/experiment.md, changed afterwards only by dated amendments
   - When: 2026-08-28
   - Decision: `rank` Rank the caches by the difference's interval
   - Evidence: 95dd30726b
6. **Guard the arms, prime arm C, smoke-test**: A run whose compile cache, read before the engine starts, contradicts its arm is discarded. Two priming runs and a smoke triple, never counted, exposed two defects that were fixed first.
   - Output: data/priming.jsonl and data/smoke.jsonl, outside the campaign store
   - When: 2026-08-28 to 08-29
   - Decision: `state` Check each arm's cache state
   - Evidence: b60122abf7 (arm-state discard); ea58eb9651 (state read before the engine); bee70f6d91 (poll budget; priming runs); 7ee1f08f2d (engine log kept; smoke runs)

### Phase 4 of 5: Measure (2 steps)

7. **Discard the first window and restart** [MILESTONE]: Arm A lost 3 of its 9 runs to a full worker disk. The fix changed the pinned image, so the 27-run window was discarded whole, not spliced.
   - Output: data/discarded-window-0.jsonl, kept as evidence; a re-pinned image
   - When: 2026-08-31
   - Evidence: 740e1eafaf (cleanup fix; window stored); 7d2313ffad (re-pin; restart recorded); 4d7b4017a0 (restart's first run failed too; purge at start)
8. **Run 100 interleaved triples** [MILESTONE]: Seeded triples, one job in flight, one JSON line per run, no retries. Three windows hours apart, all on one host.
   - Output: data/campaign.jsonl: 300 runs, 100 per arm, no failures, no discards
   - When: 2026-09-02 to 09-04 UTC
   - Decision: `interleave` Interleave the arms in random triples
   - Evidence: 68ece63079 (window 1); e2ffd6b2dd (window 2); 83ec68fb36 (complete)

### Phase 5 of 5: Analyse and publish (2 steps)

9. **Analyse from the committed store**: The gate partitions rows before any statistic; seeded bootstrap intervals follow. A first-touch rule, added after window one, keeps one image-pull run out of the ECDF.
   - Output: data/analysis.json (a re-run reproduces it byte for byte) and the four figures
   - When: 2026-09-02 to 09-03
   - Decision: `shape` Report the shape, and what it cannot answer
   - Evidence: b82c59243b (first-touch rule, post hoc); 46df9b9e02 (economics); 94ba821567 (figures)
10. **Write up, gate and date the post** [MILESTONE]: The headline follows the pre-registered rule; the pre-publish gate caught two wrong claims. Every number re-derives with no GPU.
   - Output: docs/post.md with byline, permanent slug and date
   - When: 2026-09-03 to 09-17
   - Evidence: fe773ec78f (post written); bc10b41bed (date corrected to 2026-09-17)

## Results as meaning

### Where each arm's median cold start goes

- Axis: Median seconds per phase, 100 runs per arm. A: nothing cached; B: weights cached; C: both cached. Compile is drawn last, out of time order (it follows model loading). Unattributed engine start: two sub-phases the log does not split. Other fixed steps: memory profiling (P1: vllm), graph capture (P1: compile), the ready check (engine up until health answers, mostly API-server start-up), the first request, start to finish.
- Read it as: The launch segment runs from starting `vllm serve` to its "Model loading took" line, so it holds process start-up too; vLLM's own loading time is 17.40, 4.57, 4.54 s. Dashed box on C: B's compile time.
- How it is computed: Each segment is one phase's median over 100 runs; Other fixed steps adds four such medians (A: 8.82 s), so it is not itself a median, and bars miss the median totals (81.12, 65.43, 39.37 s).
- A: Platform (by subtraction) 4.37, Server launch to model loaded 45.83, Memory profiling 0.09, Graph capture 4.0, Unattributed engine start 4.46, Ready check 4.43, First request 0.3, Compile 19.01 (s)
- B: Platform (by subtraction) 4.07, Server launch to model loaded 30.35, Memory profiling 0.11, Graph capture 4.0, Unattributed engine start 4.38, Ready check 4.57, First request 0.3, Compile 18.79 (s)
- C: Platform (by subtraction) 4.83, Server launch to model loaded 21.34, Memory profiling 0.17, Graph capture 4.0, Unattributed engine start 3.83, Ready check 4.1, First request 0.3, Compile 0.33 (s)
- Drawn as one segment, Other fixed steps: Memory profiling + Graph capture + Ready check + First request
- On bar C, a dashed outline shows where Compile sat in B (18.79 s)
- Changed A → B: Weight cache only: launch to model loaded falls 45.83 → 30.35 s; compile stays near 19 s.
- Changed B → C: Compile cache only: compile falls 18.79 → 0.33 s. Launch to model loaded also falls, 30.35 → 21.34 s, unexplained.
- So: see decisions `arms`, `clocks`

### How spread out the runs are

- Axis: Seconds of total cold start per arm: p50 (median), p90, p95.
- Read it as: The arm order holds at every percentile shown, but among repeat-host runs B's largest is longer than A's: the far tail does not follow the median. No p99: at 100 runs it would be one or two runs.
- How it is computed: Percentiles use all 300 publishable runs, among them arm A's 2266.6 s run on a host's first image pull (far past p95); each hollow marker is that arm's largest repeat-host run (A: 99 runs, B: 100).
- A: p50 81.1, p90 96.3, p95 96.4 (s); largest 111.6 s
- B: p50 65.4, p90 85.9, p95 86.4 (s); largest 148.2 s
- C: p50 39.4, p90 54.8, p95 54.9 (s)
- Note: Hollow circle: the arm's largest repeat-host run; the post gives it for A and B only.
- So: see decision `shape`

### The two effects, each measured on its own

- Axis: Seconds of total cold start each cache saves (median difference), with a 95% bootstrap interval.
- Read it as: Both clear zero, but side by side they do not rank the caches; the next chart does. Only 18.46 s of the compile cache's 26.07 s is compilation; the other 7.6 s roughly matches the unexplained launch-segment gap (8.85 s).
- How it is computed: A − B and B − C use unrounded medians, so 15.68 and 26.07 s, not the 15.69 and 26.06 the rounded medians (81.12, 65.43, 39.37) give.
- Weight cache, A − B: 15.68 s (interval 10.67 to 20.47)
- Compile cache, B − C: 26.07 s (interval 25.97 to 31.01)
- So: see decision `arms`

### Which cache bought more: the interval on the difference

- Axis: Weight-cache saving minus compile-cache saving: seconds of total cold start, 95% bootstrap interval.
- Read it as: The whole interval, −20.30 to −5.54 s, lies left of zero, which licenses the ranking.
- How it is computed: 15.68 − 26.07 = −10.39 s, on unrounded medians; the interval comes from 10,000 resamples of the runs.
- (A − B) − (B − C), total cold start: -10.39 s (interval -20.3 to -5.54)
- So: see decision `rank`

### KV cache left for serving, by arm

- Axis: KV cache tokens vLLM allocated at startup, same card and flags in every arm.
- Read it as: C keeps 20.3 % more KV cache: one more full-length (8192-token) request served at once, 5 instead of 4. On a cold arm the compiler's working set is resident while vLLM measures free memory, so the cache is sized smaller for the replica's life. Pre-registered as H5.
- How it is computed: 43,040 / 8,192 = 5.25 and 35,792 / 8,192 = 4.37 full-length requests; the code keeps whole requests (rounds down), so 5 against 4. 43,040 / 35,792 = 1.203, so 20.3 % more.
- A: 35792 tokens
- B: 35792 tokens
- C: 43040 tokens
- So: see decision `arms`

## Interview card

**30-second pitch:** I measured where the time goes when a vLLM server starts cold on a rented GPU, and which of two caches is worth warming: the model weights or the engine's compiled code. I ran three set-ups differing in one thing only, interleaved, a hundred times each, and split every start into phases. The compile cache saved about 10 seconds more per cold start than the weight cache, 95% interval 5.5 to 20 seconds more, and it left about 20% more KV cache for serving.

**2-minute version:** Everyone talks about caching the weights. But vLLM also compiles parts of the model at startup and caches that on disk, a cache few notice unless they have operated the engine. I set up three arms that differ only in cache configuration: nothing cached, weights on a network volume, and weights plus a warm compile cache. I ran them as shuffled triples so platform drift could not pose as an arm effect, and I committed my hypotheses and rules before the first paid measurement run. I timed the real `vllm serve` with one clock in the worker and one on my laptop, so platform start-up is a named residual, not hidden. The answer: warming the compile cache saved about 10 seconds more per cold start than caching the weights, and the interval on that difference never crossed zero. It also left about a fifth more KV cache, because profiling no longer ran next to the compiler's memory. What it cannot tell you is anything about other hardware, or whether host placement drives the tail: every run landed on one machine, and I reported that rather than dropping the question.

**Hard follow-ups:**

- Q: Why three arms and not two, or four?
  A: Two arms (hub vs volume) only test the weight cache: the fallback had this vLLM not compiled at startup; it does. A to B isolates weights, B to C compile with weights fixed. The fourth cell, weights cold but compile warm, has no operational meaning. A baked-image arm would only move the bytes into the image pull, which I cannot observe.
- Q: Why pre-register a one-person experiment?
  A: The git timestamp is the only evidence that the hypotheses and the headline rule came before the data: they were committed four days before the published campaign's first run. Later amendments are dated, among them the rule separating a host's first image pull, written about half an hour after window one showed a 2174 s platform time. None changed a hypothesis or a contrast.
- Q: What surprised you?
  A: Two things. C reached "model loaded" 8.85 s sooner than B, on arms that differ only in compile cache, while vLLM's own model-loading time is the same in B and C (4.57 vs 4.54 s): not host, not position in the triple, and this campaign does not explain it. And "ready is not fast" was wrong here: vLLM (P1: vllm) does its warmup before answering health, so the first request is already near steady state.
- Q: What would you do differently?
  A: The host question failed: a serially-submitting driver kept landing on the one machine that had the image cached. The windows were hours apart, not separate days. And the first window was thrown out because arm A's per-run weights (P1: weights) filled the worker disk (A failed 3 of its 9 runs, B none), which would have biased the contrast; the worker now empties cold directories before and after each run.
- Q: What does this not tell you?
  A: The seconds for any other GPU, model, engine version, region or provider. Anything about many serverless (P1: serverless) replicas starting at once and contending for the same volume; every run was one replica alone. Anything past p95. And whether host placement drives the tail.
- Q: So should everyone warm the compile cache?
  A: It is the better buy and the more fragile one. A compile cache (P1: compile) costs nothing to store, but any change to engine version, model, hardware or flags invalidates it, so every upgrade pays the cold compile again unless warming is built into the deploy. The weight cache is a volume you rent every month whether you scale or not.

**Limits (what I must not claim):** One provider, GPU model, model, engine version, region and host: the seconds do not transfer; the mechanisms do. H4 (does host placement drive the tail?) is unanswerable: all 300 runs landed on one host. Single replica, no contention. No percentile past p95. The first-touch rule that keeps the 2266.6 s run out of the ECDF (it stays in the medians) was written after seeing the data and is disclosed as post hoc. Why C reaches "model loaded" 8.85 s sooner than B is not settled.

## Recall questions

- Q: B and C differ only in the compile cache. Which chart segment should change, and which other one changed?
  A: Only compile should move, and it does: 18.79 to 0.33 s. The launch segment also shrank, 30.35 to 21.34 s, though vLLM's own loading time is the same in B and C (4.57 vs 4.54 s). The campaign does not explain it.
- Q: On the one-run view, where does clock B start, and what lands in platform time?
  A: Between steps 4 and 5: the probe starts clock B just before launching `vllm serve`. Platform time is everything the laptop clock sees outside it: queueing, finding a GPU, starting the container and handler set-up before; teardown and the driver's 5 s polling after.
- Q: Why is arm C primed outside the campaign?
  A: Otherwise its early runs compile cold and its later runs do not, making the arm a mixture whose effect grows with run index and looks like a trend.
- Q: Why is the compile cache checked before the engine starts, not after?
  A: A cold compile creates the cache directory as it finishes. Checked afterwards, every healthy cold run would look warm and be discarded, and a cold compile inside arm C would pass as warm.
- Q: How is a contrast obtained, and why does the ranking need a third number?
  A: Subtract the medians of two arms that differ in one cache, with a bootstrap interval. Which cache saves more is a claim about the difference of the two contrasts, so it needs its own interval, on one shared unit: total cold start.
- Q: If the difference's interval had run from −20 to +3 s, what could you claim?
  A: Not the ranking: no difference, or a slightly larger weight-cache saving, would still fit, and the design makes the ranking a finding only if the interval excludes zero. Each cache's own saving, with its interval, could still be reported.
- Q: Which requirement breaks if the arms run in blocks, and what protects it?
  A: R2, one change per comparison: in blocks, time-of-day platform conditions change along with the cache. Interleaved triples protect it, with one frozen cache configuration and the per-run check of each arm's compile-cache state.
- Q: Why is a failed run never retried in place?
  A: A retry quietly replaces slow or unlucky runs with faster ones and makes the distribution look better than it is. Failures are their own rows and are counted per arm.
- Q: Why does the warm compile cache leave more KV cache?
  A: vLLM sizes the KV cache from free memory measured during a profiling pass. On a cold arm the compiler's working set is resident during that pass, so less memory looks free, and the smaller cache stays for the replica's life.

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
