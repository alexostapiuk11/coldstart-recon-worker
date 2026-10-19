# Where a vLLM cold start goes: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

## Why it exists

**Question:** Where does a cold vLLM start on a rented GPU spend its time, and which empty cache is worth warming more: the weights or the compiled code? One of them also turned out to buy serving memory (KV cache).

**Requirements that drove everything:**

- Split one cold start into named phases, and label what cannot be attributed instead of hiding it. *Why:* The caches act on different phases (weights on loading, compile on engine start), so one "startup" bar would hide half the experiment. Naming unattributed time is more credible than hiding it.
- Change exactly one thing between the set-ups being compared. *Why:* Otherwise a difference cannot be pinned on a cache. Same image, entrypoint and engine flags for every arm.
- Report the distribution and its uncertainty, not an average. *Why:* Cold starts are skewed with a heavy tail, so a mean describes no real run. A claim like "cache X matters more" needs its own interval, not two point estimates side by side.
- Fix the hypotheses, exclusion rules, stopping rule and headline rule before the first paid measurement run. *Why:* Git timestamps then show the rules came before the data, and the headline cannot be picked by which result cost the most effort.
- Run only proven code on paid GPUs, and let anyone re-derive every number on a laptop. *Why:* The whole budget was $200, and debugging on live GPUs eats it. A number a reader cannot re-derive must be taken on trust.

## Need to know first

- **Arms A, B and C**: Three cache set-ups. **A**: weights from the model hub, compile cache cold. **B**: weights from a network volume, compile cache cold. **C**: weights from the volume, compile cache warm. Background: P1, LLM serving.
- **Triples**: One run of each arm, in an order shuffled from a seed. 100 triples make the 300 runs, so a busy hour on the fleet falls on all three arms.
- **Contrast, and difference of contrasts**: A **contrast** is the difference of two arms' medians, with a bootstrap interval: A minus B is the weight cache's saving, B minus C the compile cache's. Their **difference**, (A minus B) minus (B minus C), ranks the caches only if its interval excludes zero; negative favours the compile cache.
- **Two clocks and the platform residual**: **Clock A** (laptop) brackets the whole job; total cold start is measured on it. **Clock B** (worker, monotonic) starts just before `vllm serve` is launched. **Platform time** = total minus clock B time, the one allowed cross-clock subtraction: queue, container start, handler set-up, teardown, polling lag. **Clock C**, RunPod's own queue and execution durations, is recorded but not used.
- **Percentiles and the ECDF**: **p90** is the time 90% of runs finish within; p50 is the median. An **ECDF** plots every run (seconds across, share finished up), so the tail stays visible. More in P2.
- **The five hypotheses**: **H1**: weight handling is over half of in-worker time in arm A. **H2**: volume weights cut it materially. **H3**: compiling is a non-trivial part of engine start, and a warm cache cuts it. **H4**: host differences drive the median-to-p95 gap. **H5**: a warm compile cache leaves more KV cache.
- **Pre-registration**: Hypotheses, analysis plan, exclusion rules, stopping rule and headline rule, committed in `docs/experiment.md` four days before the first measurement run, so git shows they came first.

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
- **RunPod endpoint**: queues the job, boots a worker, clock C
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

Solid boxes run in the worker: the handler sets two cache paths and checks the cache directories; the probe launches `vllm serve`, stamps phase marks on clock B and returns the raw log in the result bundle. Dashed boxes are outside the worker code; the parser and run record are built later on the laptop.

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

Clock A (laptop) brackets the job from step 2; clock B (worker) starts between steps 4 and 5. Steps 5 and 6, highlighted, are where the caches act. Platform time is everything clock A sees outside clock B. A failed run is still stored, never retried.

- **1 Schedule picks arm**: next slot in a seeded, shuffled triple
- **2 Driver submits**: new run id; clock A starts
- **3 Platform boots**: queue, find a 4090, start container
- **4 Handler sets cache**: two paths, snapshot compile cache
- **5 Launch, load weights**: the weight cache acts here: hub or volume
- **6 Engine compiles**: the compile cache acts here; then profile, capture
- **7 Ten requests**: first token, then the latency curve
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

**Why:** A to B isolates the weight cache. B to C isolates the compile cache with weight handling held constant. The configuration is one frozen object that sets two paths, so the single-variable claim is true by structure. A baked image does not remove the bytes; it moves them into the image pull, which happens before any measuring code runs, so it would flatter the number for a reason the harness cannot see. Nobody warms a compile cache while re-downloading weights, so the fourth cell answers no question.

**Cost:** Arm C exists only because the reconnaissance run showed this vLLM compiles at startup. A warm arm needs a primed volume, and a test has to check that the arms differ nowhere else.

### Measure from outside the engine

**Problem:** vLLM's interesting phases are internal, and part of every cold start (queue, container start, image pull) happens before our code exists.

**Options considered:**

- Time startup through vLLM's Python engine API
- One clock, and give all the time to the stages you can see
- Run the real `vllm serve`, bracket it with a monotonic clock, split phases from its log, and get platform time by subtraction

**Chosen:** Run the real `vllm serve`, bracket it with a monotonic clock, split phases from its log, and get platform time by subtraction

**Why:** The Python API would measure a startup path nobody deploys. With one clock you cannot detect that it is lying. The design names three; the implemented check compares the driver and worker clocks and discards a run whose in-process time exceeds its total. The platform residual is the one named cross-clock subtraction; total time to first token is itself the job's laptop-clock span minus the worker-clock warmup tail.

**Cost:** Platform time is one residual, and it holds teardown and polling lag as well as queueing. RunPod's queue and execution durations (clock C) are recorded but not used to split it. Two engine sub-phases (device init and KV allocation) are not delineated by this vLLM build, so they sit merged in an unattributed row. The log patterns are tied to vLLM 0.27.1.

### Interleave the arms in random triples

**Problem:** A rented GPU fleet changes over hours and days. Run the arms in blocks and a busy evening gets labelled as an arm effect.

**Options considered:**

- Blocks: all of A, then all of B, then all of C
- Interleaved triples: one run of each arm per triple, order shuffled from a seed

**Chosen:** Interleaved triples: one run of each arm per triple, order shuffled from a seed

**Why:** Blocking confounds the cache with time-of-day fleet conditions, and on a rented fleet that confound can be large enough to make or erase the whole effect. The design calls interleaving its most important validity decision. Triples also allow a paired, same-host check as supporting evidence.

**Cost:** A resumed campaign must rebuild the exact schedule, so the harness refuses a resume whose stored arms disagree with the seed. The windows ended up hours apart rather than on separate days, so drift between windows is only partly covered; the post says so.

### Prove each arm's cache state

**Problem:** A warm cache leaking into a cold arm, or a cold compile inside arm C, would still produce plausible numbers. The configuration alone does not show what was on disk.

**Options considered:**

- Trust the configuration
- Let arm C's first campaign runs warm the cache
- Prime arm C outside the campaign, isolate cold paths per run, and check the cache state on every run

**Chosen:** Prime arm C outside the campaign, isolate cold paths per run, and check the cache state on every run

**Why:** Without priming, arm C's early runs compile cold and later ones do not: a mixture whose effect grows with run index, which looks like a real trend. So two priming runs go to a separate store, and the second must show the cache present and compile under one second. Cold paths are named by run id so a reused worker cannot hand one run's files to another. The handler checks whether the compile cache exists before the engine starts, because a cold compile creates that directory as it finishes; a run whose observed state disagrees with its arm is discarded.

**Cost:** Priming runs cost GPU time and are excluded from every number. Moving the check to after the engine run would look harmless but quietly discard about two thirds of a paid campaign, so the code carries a do-not-move warning.

### Rank the caches by the difference's interval

**Problem:** Which cache buys more? Two effects, each with its own interval, do not answer that.

**Options considered:**

- Compare the two point estimates
- Subtract the weight-time contrast from the compile-time contrast
- Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Chosen:** Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Why:** "Compile cache mattered more" is only a finding if the gap between the two effects excludes zero. The difference needs one shared unit, so it is computed on total cold start; subtracting weight time from compile time would difference two different quantities. The headline rule, lead with what transfers furthest to other infrastructure, was committed before data.

**Cost:** Total time is noisier than the mechanism units, so the interval is wide: −10.39 s, 95% [−20.30, −5.54]. The pre-registration forbids making the ranking claim anywhere without it.

### Report the shape, and what it cannot answer

**Problem:** Cold starts have a heavy right tail, and 100 runs per arm cannot support every summary.

**Options considered:**

- Means and standard deviations
- Publish p99 as well
- Drop the host hypothesis (H4) quietly once every run lands on one host
- p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Chosen:** p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Why:** A mean is pulled by the tail. At 100 runs a p99 is one or two observations, not an estimate. Before the published campaign began (a discarded window had already shown runs piling onto one host), the pre-registration committed to publishing the host count whatever it was. The same single host made every triple host-complete, so the paired check is fully supplied.

**Cost:** The far tail stays unresolved: the post can say that B's largest runs were longer than A's, but not why. The question of whether host placement drives the tail is lost.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Split one cold start into named phases, and label what cannot be attributed instead of hiding it.
  - `clocks` Measure from outside the engine: R1 asks for named phases and a label on what cannot be attributed; this decision splits phases from vLLM's log, names platform time as a residual, and puts the sub-phases the log does not delineate "in an unattributed row".
- R2: Change exactly one thing between the set-ups being compared.
  - `arms` Three arms, one variable: R2 asks to change exactly one thing; here cache configuration is one frozen object that sets two paths, "so the single-variable claim is true by structure".
  - `interleave` Interleave the arms in random triples: R2: otherwise "a difference cannot be pinned on a cache"; in blocks, "a busy evening gets labelled as an arm effect", so a second thing changes with the arm.
  - `state` Prove each arm's cache state: A warm cache leaking into a cold arm, or a cold compile inside arm C, would make the arms differ in more than their configured cache; "the configuration alone does not show what was on disk", so the state is checked on every run.
- R3: Report the distribution and its uncertainty, not an average.
  - `rank` Rank the caches by the difference's interval: R3: "cache X matters more" needs its own interval, "not two point estimates side by side"; the decision rejects "Compare the two point estimates".
  - `shape` Report the shape, and what it cannot answer: R3: "a mean describes no real run"; the decision: "A mean is pulled by the tail", so it reports p50, p90, p95 and a full ECDF.
- R4: Fix the hypotheses, exclusion rules, stopping rule and headline rule before the first paid measurement run.
  - `rank` Rank the caches by the difference's interval: R4 fixes the headline rule in advance; here "the headline rule ... was committed before data".
  - `shape` Report the shape, and what it cannot answer: R4 fixes the hypotheses in advance; so H4 is reported as unanswerable, and the option to drop it "quietly once every run lands on one host" is rejected.
- R5: Run only proven code on paid GPUs, and let anyone re-derive every number on a laptop.
  - No decision: It is met by process: the flow step "Capture, then build offline" tests the code against recorded fixtures and a free stub before paid runs, and "Publish what re-derives" re-derives every figure from the committed store with no GPU.

**Decisions and the concepts they use:**

- `arms` Three arms, one variable uses Arms A, B and C: It chooses the three set-ups A, B and C that the concept defines.
- `arms` Three arms, one variable uses Contrast, and difference of contrasts: "A to B isolates the weight cache. B to C isolates the compile cache": each adjacent pair of arms is one contrast.
- `clocks` Measure from outside the engine uses Two clocks and the platform residual: It uses the driver and worker clocks, and platform time "is the one named cross-clock subtraction".
- `interleave` Interleave the arms in random triples uses Triples: The chosen option is "one run of each arm per triple, order shuffled from a seed".
- `state` Prove each arm's cache state uses Arms A, B and C: Each arm has an expected cache state, and "a run whose observed state disagrees with its arm is discarded".
- `rank` Rank the caches by the difference's interval uses Contrast, and difference of contrasts: The chosen option bootstraps "the difference of contrasts on total cold start".
- `rank` Rank the caches by the difference's interval uses Pre-registration: "The pre-registration forbids making the ranking claim anywhere without" the interval.
- `shape` Report the shape, and what it cannot answer uses Percentiles and the ECDF: The chosen option is "p50, p90, p95 and a full ECDF, no p99".
- `shape` Report the shape, and what it cannot answer uses The five hypotheses: It reports H4, whether host placement drives the tail, as unanswerable.

**Results and the decisions they support:**

- Where each arm's median cold start goes → `arms` Three arms, one variable, `clocks` Measure from outside the engine
- The two effects, each measured on its own → `arms` Three arms, one variable
- Which cache bought more: the interval on the difference → `rank` Rank the caches by the difference's interval
- KV cache left for serving, by arm → `arms` Three arms, one variable

## Implementation flow

1. **Capture, then build offline**: Real vLLM logs and RunPod responses from a cheap reconnaissance run become fixtures; the code is tested on them and a free stub. A disk-fill defect still cost one discarded 27-run window.
2. **Pre-register**: Hypotheses, contrasts and rules are committed in `docs/experiment.md` before the first paid measurement run.
3. **Prime arm C**: Two arm C runs warm the compile cache on the volume; they go to a separate store and never count.
4. **Run interleaved triples**: 100 seeded triples, one job in flight. Any change to a pinned setting ends the experiment.
5. **Store, never retry**: One JSON line per run, appended as it lands. A failure is its own row, never retried.
6. **Partition, then analyse**: A gate sorts rows into publishable, discarded and failed before any statistic; then seeded bootstrap intervals (10,000 iterations).
7. **Publish what re-derives**: Figures and the post come from the committed store; a re-run reproduces the analysis byte for byte, with no GPU.

## Results as meaning

### Where each arm's median cold start goes

- Axis: Median seconds per phase, 100 runs per arm. Each segment is its own median, so bars do not sum to the median totals (81.12, 65.43 and 39.37 s).
- Read it as: The launch segment (the post's `T_weights`) runs from starting `vllm serve` to its "Model loading took" line, so it also holds process start-up. Graph capture is a flat 4.00 s everywhere: it depends on the shapes captured, not on caching.
- A: nothing cached: Platform (by subtraction) 4.37, Launch to model loaded 45.83, Compile 19.01, Memory profiling 0.09, Graph capture 4.0, Unattributed engine start 4.46, Ready check 4.43, First token 0.3 (s)
- B: weights cached: Platform (by subtraction) 4.07, Launch to model loaded 30.35, Compile 18.79, Memory profiling 0.11, Graph capture 4.0, Unattributed engine start 4.38, Ready check 4.57, First token 0.3 (s)
- C: weights + compile: Platform (by subtraction) 4.83, Launch to model loaded 21.34, Compile 0.33, Memory profiling 0.17, Graph capture 4.0, Unattributed engine start 3.83, Ready check 4.1, First token 0.3 (s)
- Changed A → B: Only the weight cache changes. The launch segment falls from 45.83 to 30.35 s (vLLM's own loading time, 17.40 to 4.57 s); compile stays near 19 s.
- Changed B → C: Only the compile cache changes. Compile nearly vanishes, 18.79 to 0.33 s. But the launch segment also shrank, 30.35 to 21.34 s, with vLLM's own loading time unchanged (4.57 vs 4.54 s); this campaign does not explain why.
- So: see decisions `arms`, `clocks`

### The two effects, each measured on its own

- Axis: Median seconds of total cold start each cache saves (the two contrasts).
- Read it as: Side by side these do not rank the caches; the next chart does. Only 18.46 s of the compile cache's 26.07 s is compilation; the rest is the unexplained launch-segment gap above.
- Weight cache (A minus B): 15.68 s
- Compile cache (B minus C): 26.07 s
- So: see decision `arms`

### Which cache bought more: the interval on the difference

- Axis: Weight-cache saving minus compile-cache saving: seconds of total cold start, 95% bootstrap interval.
- Read it as: The whole interval, −20.30 to −5.54 s, lies left of zero: the compile cache saves about 10 s more per cold start. That is what licenses the ranking; the pre-registration forbids the claim without this interval.
- (A − B) − (B − C), total cold start: -10.39 s (interval -20.3 to -5.54)
- So: see decision `rank`

### KV cache left for serving, by arm

- Axis: KV cache tokens vLLM allocated at startup, same card and flags in every arm.
- Read it as: C keeps 20.3 % more KV cache: one more concurrent request at 8192 context (5 instead of 4). On a cold arm the compiler's working set is resident while vLLM measures free memory, so the cache is sized smaller for the replica's life. Pre-registered as H5.
- A: 35792 tokens
- B: 35792 tokens
- C: 43040 tokens
- So: see decision `arms`

## Interview card

**30-second pitch:** I measured where the time goes when a vLLM server starts cold on a rented GPU, and which of two caches is worth warming: the model weights or the engine's compiled code. I ran three set-ups differing in one thing only, interleaved, a hundred times each, and split every start into phases. The compile cache bought more than the weight cache, and it also left more memory for serving.

**2-minute version:** Everyone talks about caching the weights. But vLLM also compiles parts of the model at startup and caches that on disk, and that second cache is almost invisible unless you have operated the engine. So I asked which one matters more. I set up three arms that differ only in cache configuration: nothing cached, weights on a network volume, and weights plus a warm compile cache. I ran them as shuffled triples so platform drift could not pose as an arm effect, and I wrote down the hypotheses, the exclusion rules and how I would pick the headline before the first paid measurement run. The measuring code ran the real `vllm serve` and read its log, with one clock inside the worker and one on my laptop, so everything outside the worker clock, platform start-up included, is a named residual, not hidden. The answer: warming the compile cache saved about 10 seconds more per cold start than caching the weights, and the interval on that difference never crossed zero. It also left about a fifth more KV cache, because profiling no longer ran next to the compiler's memory. What it cannot tell you is anything about other hardware, or whether host placement drives the tail: every run landed on one machine, and I reported that rather than dropping the question.

**Hard follow-ups:**

- Q: Why three arms and not two, or four?
  A: Two arms (hub vs volume) only test the weight cache, and that was the fallback if this vLLM had not compiled at startup; it does. A to B isolates weights, B to C isolates compile with weights held fixed. The fourth cell, weights cold but compile warm, has no operational meaning. A baked-image arm would just move the bytes into the image pull, which I cannot observe.
- Q: Why pre-register a one-person experiment?
  A: Because the git timestamp is the only evidence that the hypotheses and the headline rule came before the data. It was committed four days before the first run. Later amendments are labelled: the first-touch separation rule, written about half an hour after window one showed a 2174 s platform time, with a note on reporting the flat warmup in the same commit; the window-spacing note; and the stopping decision. None changed a hypothesis or a contrast.
- Q: What surprised you?
  A: Two things. C reached "model loaded" 8.85 s sooner than B, on arms that differ only in compile cache. It is not weight loading: vLLM's own loading time is the same in B and C (4.57 vs 4.54 s). The gap opens before loading begins; not host, not position in the triple, and this campaign does not explain it. And "ready is not fast" was wrong here: vLLM does its warmup before answering health, so the first request is already near steady state.
- Q: What would you do differently?
  A: What the record flags. The host question failed: a serially-submitting driver kept landing on the one machine that had the image cached, and no endpoint setting changes that. The windows were hours apart, not separate days. And the first window was thrown out because arm A's per-run weights filled the worker disk, so A failed 40% of its runs against 0% for B, which would have biased the contrast by survivorship; the worker now empties cold directories before and after each run.
- Q: What does this not tell you?
  A: The seconds for any other GPU, model, engine version, region or provider. Anything about many replicas starting at once and contending for the same volume; every run was one replica alone. Anything past p95. And whether host placement drives the tail.
- Q: So should everyone warm the compile cache?
  A: It is the better buy and the more fragile one. It costs nothing to store, but any change to engine version, model, hardware or flags invalidates it, so every upgrade pays the cold compile again unless warming is built into the deploy. The weight cache is a volume you rent every month whether you scale or not.

**Limits (what I must not claim):** One provider, GPU model, model, engine version, region and host: the seconds do not transfer; the mechanisms do. H4 (does host placement drive the tail?) is unanswerable: all 300 runs landed on one host. Single replica, no contention. No percentile past p95. The first-touch rule that keeps the 2266.6 s run out of the ECDF (it stays in the medians) was written after seeing the data and is disclosed as post hoc. Why C reaches "model loaded" 8.85 s sooner than B is not settled.

## Recall questions

- Q: Why are there three arms and not four?
  A: The fourth cell, weights cold with compile warm, has no operational meaning, so measuring it fills a table without answering a question. A baked-image arm was also excluded: it moves the weight bytes into the image pull, which is inside the platform residual the harness cannot see.
- Q: B and C differ only in the compile cache. Which chart segment should change, and which other one changed?
  A: Only the compile segment should move, and it does: 18.79 to 0.33 s. The launch segment also shrank, 30.35 to 21.34 s, although vLLM's own loading time is the same in B and C (4.57 vs 4.54 s). The campaign does not explain it, and it is why only 18.46 s of the compile cache's 26.07 s saving is compilation.
- Q: On the one-run view, where does clock B start, and what lands in platform time?
  A: Between steps 4 and 5: the probe starts clock B just before it launches `vllm serve`. Everything the laptop clock sees outside clock B is platform time: queueing, finding a GPU, starting the container and the handler's set-up before it, and teardown and the driver's 5 s polling after it.
- Q: Why is arm C primed outside the campaign?
  A: Otherwise its early runs compile cold and its later runs do not, making the arm a mixture whose effect grows with run index and looks like a trend.
- Q: Why is the compile cache checked before the engine starts, not after?
  A: A cold compile creates the cache directory as it finishes. Checked afterwards, every healthy cold run would look warm and be discarded, and a real leak would pass unseen.
- Q: How is a contrast obtained, and why does the ranking need a third number?
  A: Subtract the medians of two arms that differ in one cache, with a seeded bootstrap interval: A minus B for the weight cache, B minus C for the compile cache. Which cache saves more is a claim about their difference, (A minus B) minus (B minus C), so it needs its own interval, on one shared unit: total cold start. Weight time minus compile time would difference two different quantities.
- Q: If the difference's interval had run from −20 to +3 s, what could you claim?
  A: Not the ranking. The interval would cross zero, so no difference, or a weight cache that saves slightly more, would still fit the data, and the pre-registration forbids the ranking claim without an interval that excludes zero. Each cache's own saving, with its interval, could still be reported.
- Q: Which requirement breaks if the arms run in blocks, and what protects it?
  A: R2, change exactly one thing. In blocks, time-of-day fleet conditions change along with the cache, so a busy evening is labelled as an arm effect. Interleaved triples protect it, together with one frozen cache configuration (three arms, one variable) and the per-run proof of each arm's cache state.
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
