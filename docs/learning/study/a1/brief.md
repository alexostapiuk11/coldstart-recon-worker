# Where a vLLM cold start goes: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

## Why it exists

**Question:** When a vLLM server starts cold on a rented GPU, where does the time go? And which of its two empty caches is worth warming more: the model weights, or the engine's compiled code?

**Requirements that drove everything:**

- Split one cold start into named phases, and label what cannot be attributed instead of hiding it.. *Why:* The two caches act on different phases: weights on loading, compile on engine start. One "startup" bar would hide half the experiment. And many published cold-start numbers quietly give all the time to stages the author could see; a named bucket for "time I cannot attribute, and why" is more credible.
- Change exactly one thing between the set-ups being compared.. *Why:* Otherwise a difference cannot be pinned on a cache. Same image, entrypoint and engine flags for every arm; only the cache configuration differs.
- Report the distribution and its uncertainty, not an average.. *Why:* Cold starts are skewed with a heavy tail, so a mean describes no real run. A claim like "cache X matters more" needs its own interval, not two point estimates side by side.
- Fix the hypotheses, exclusion rules, stopping rule and headline rule before the first paid measurement run.. *Why:* The git timestamps then show the rules came before the data, later amendments are dated and labelled, and the headline cannot be picked by which result cost the most effort.
- Run only proven code on paid GPUs, and let anyone re-derive every number on a laptop.. *Why:* The whole budget was $200, and debugging on live GPUs is what eats it. A number a reader cannot re-derive from the committed data is one they have to take on trust.

## Need to know first

- **Arms A, B and C**: Three cache set-ups. **A**: weights downloaded from the model hub, compile cache cold. **B**: weights read from a network volume, compile cache cold. **C**: weights from the volume, compile cache warm. A to B buys the weight cache; B to C buys the compile cache. For what weights, the compile step and a serverless cold start are, see P1, LLM serving on a GPU.
- **Contrast, and difference of contrasts**: A **contrast** is the difference between two arms' medians: A minus B is what the weight cache saves, B minus C is what the compile cache saves. The **difference of contrasts** is (A minus B) minus (B minus C). Negative means the compile cache saved more. It gets its own bootstrap interval, because a ranking is only a finding if that interval excludes zero.
- **Pre-registration**: Writing the hypotheses, analysis plan, exclusion rules, stopping rule and headline rule into a committed file before the first paid measurement run, so the git history shows they came first. Here: `docs/experiment.md`, committed four days before the first run.

## System views (C4)

### Who and what the study touches (context)

The study rents GPUs from RunPod serverless, one job at a time. Weights come either from the model hub (arm A) or from a network volume RunPod mounts into the worker (arms B and C). The output is a post plus the raw data, for engineers and managers on inference-platform teams.

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

The laptop side schedules, submits and stores; the worker image runs vLLM on the rented GPU and sends its measurements back as the job result. Analysis never touches the platform: it reads the stored lines on a laptop.

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

### Inside one run: where the phases come from (component)

The log parser and the run record live on the laptop; everything else runs inside the worker. The stage recorder stamps phase boundaries on one monotonic clock, and the raw vLLM log goes back with the result. On the laptop the driver parses the log into engine sub-phases and builds the record. Sub-phases the log does not delineate are stored as merged, not guessed.

- **Handler**: reads arm and run id from the job
- **Cache config**: arm to two paths: weights, compile cache
- **Cache-dir checks**: empty cold dirs, refuse missing volume, snapshot
- **Result bundle**: marks, log lines, warmup, cache state
- **Stage recorder**: monotonic marks, clock B
- **Probe**: starts vllm serve, sends ten requests
- **Log parser (laptop)**: log lines to compile, profiling, capture
- **Run record**: one self-describing JSON line
- **vLLM server process**: prints its own startup phases
- Handler → Cache config: arm, run id
- Cache config → Cache-dir checks: paths
- Cache-dir checks → Probe: then start
- Probe → vLLM server process: reads stdout
- Probe → Stage recorder: marks S1 to S7
- Stage recorder → Result bundle: clock B marks
- Handler → Result bundle: host, cache state
- Result bundle → Log parser (laptop): log lines
- Log parser (laptop) → Run record: sub-phases

### One run, in order (dynamic)

Follow the step numbers. Clock A (laptop) brackets the whole job; clock B (worker) starts when the probe starts. Platform time is total minus clock B time, so besides the queue it holds handler set-up, teardown and the driver's 5 s polling. A failed run is still stored as a row and never retried.

- **1 Schedule picks arm**: next slot in a seeded, shuffled triple
- **2 Driver submits**: new run id, job input, clock A starts
- **3 Platform boots**: queue, find a 4090, start container
- **6 Ten requests**: first token, then time to fast
- **5 vLLM starts**: load weights, compile, profile, capture
- **4 Handler sets cache**: two paths, snapshot compile cache
- **7 Result returned**: bundle rides the job result, not logs
- **8 Record built**: parse log, build the run record
- **9 Appended**: one line in the store, never retried
- 1 Schedule picks arm → 2 Driver submits: arm
- 2 Driver submits → 3 Platform boots: arm, run id
- 3 Platform boots → 4 Handler sets cache: process starts
- 4 Handler sets cache → 5 vLLM starts: vllm serve
- 5 vLLM starts → 6 Ten requests: health OK
- 6 Ten requests → 7 Result returned: bundle
- 7 Result returned → 8 Record built: payload
- 8 Record built → 9 Appended: record

## Core decisions

### Three arms, one variable

**Problem:** A cold vLLM replica starts with two empty caches: the weights and the engine's compiled code. To say which matters more, each comparison must change one thing only.

**Options considered:**

- Two arms, hub weights vs volume weights (the fallback if this vLLM did not compile at startup)
- Add a baked-image arm, with the weights inside the container image
- Add the fourth cell: weights cold, compile cache warm
- One variable, cache configuration, at three levels: A, B, C

**Chosen:** One variable, cache configuration, at three levels: A, B, C

**Why:** A to B isolates the weight cache. B to C isolates the compile cache with weight handling held constant. The configuration is one frozen object that sets two paths, so the single-variable claim is true by structure. A baked image does not remove the bytes; it moves them into the image pull, which happens before any measuring code runs, so it would flatter the number for a reason the harness cannot see. Nobody warms a compile cache while re-downloading weights, so the fourth cell answers no question.

**Cost:** Arm C exists only because the reconnaissance run showed this vLLM compiles at startup. A warm arm needs a primed volume, and a test has to check that the arms differ nowhere else.

### Measure from outside the engine

**Problem:** The interesting phases are inside vLLM's startup, and part of every cold start (queue, container start, image pull) happens before any code of ours exists.

**Options considered:**

- Time startup through vLLM's Python engine API
- One clock, and give all the time to the stages you can see
- Run the real `vllm serve` as a subprocess, bracket it with a monotonic clock, split phases from its log, and get platform time by subtraction

**Chosen:** Run the real `vllm serve` as a subprocess, bracket it with a monotonic clock, split phases from its log, and get platform time by subtraction

**Why:** The Python API would measure a startup path nobody deploys. With one clock you cannot detect that it is lying. The design names three; the implemented check compares the driver and worker clocks and discards a run whose in-process time exceeds its total. The platform residual is the one named cross-clock subtraction; total time to first token is itself the job's laptop-clock span minus the worker-clock warmup tail.

**Cost:** Platform time is one residual, and it holds teardown and polling lag as well as queueing. RunPod's queue and execution durations are recorded but not used to split it. Two engine sub-phases (S4a, S4d) are not delineated by this vLLM build, so they sit merged in an unattributed row. The log patterns are tied to vLLM 0.27.1.

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

**Problem:** The headline question is which cache buys more. Two effects, each with its own interval, do not answer it.

**Options considered:**

- Compare the two point estimates
- Subtract the weight-time contrast from the compile-time contrast
- Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Chosen:** Bootstrap the difference of contrasts on total cold start, and pick the headline by a rule fixed in advance

**Why:** "Compile cache mattered more" is only a finding if the gap between the two effects excludes zero. The difference needs one shared unit, so it is computed on total cold start; subtracting weight time from compile time would difference two different quantities. The headline rule, lead with what transfers furthest to other infrastructure, was committed before data.

**Cost:** Total time is noisier than the mechanism units, so the interval is wide: −10.39 s, 95% [−20.30, −5.54]. The pre-registration forbids making the ranking claim anywhere without it.

### Report the shape, and what it cannot answer

**Problem:** Cold starts are right-skewed with a heavy tail, and about 100 runs per arm cannot support every summary.

**Options considered:**

- Means and standard deviations
- Publish p99 as well
- Drop the host hypothesis (H4) quietly once every run lands on one host
- p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Chosen:** p50, p90, p95 and a full ECDF, no p99, and H4 reported as unanswerable

**Why:** A mean is pulled by the tail. At 100 runs a p99 is one or two observations, not an estimate. Before the published campaign began (a discarded window had already shown runs piling onto one host), the pre-registration committed to publishing the host count whatever it was. The same single host made every triple host-complete, so the paired check is fully supplied.

**Cost:** The far tail stays unresolved: the post can say that B's largest runs were longer than A's, but not why. The question of whether host placement drives the tail is lost.

## Implementation flow

1. **Capture, then build offline**: A cheap reconnaissance run saves real vLLM logs and RunPod responses as fixtures. Parser, clocks, store and analysis are built and tested against them and a free stub. A disk-fill defect still cost one paid 27-run window, which was discarded.
2. **Pre-register**: Hypotheses H1 to H5, both contrasts, exclusion rules, stopping rule and headline rule go into `docs/experiment.md`, committed before the first paid measurement run.
3. **Prime arm C**: Two arm C runs warm the compile cache on the volume. They go to a separate store and never count.
4. **Run interleaved triples**: 100 seeded triples, 300 runs, one job in flight. Every pinned setting is fixed; any change ends the experiment instead of continuing across it.
5. **Store, never retry**: One JSON line per run, appended as it lands. A failure is its own row and counts in the failure table; nothing is retried in place.
6. **Partition, then analyse**: A gate sorts rows into publishable, discarded and failed before any statistic sees them. Then seeded bootstrap intervals (10,000 iterations) on medians and contrasts.
7. **Publish what re-derives**: Figures and the post come from the committed store. A re-run reproduces the analysis file byte for byte, with no GPU.

## Results as meaning

### Where each arm's median cold start goes

- Axis: Seconds, median per phase, 100 runs per arm. Each segment is its own median, so the segments do not add up to the arm's median total (81.12, 65.43 and 39.37 s). Imports are not shown: their mark is taken before vLLM is launched, so import time sits inside the launch segment.
- Read it as: The launch segment (the post calls it T_weights) runs from starting `vllm serve` to vLLM's "Model loading took" line, so it holds process start-up as well as weights. vLLM's own loading time is 17.40 s in A, and 4.57 and 4.54 s in B and C. The compile segment almost vanishes in C (19.01 to 0.33 s). Graph capture is a flat 4.00 s everywhere: it depends on the shapes captured, not on what was cached.
- A: nothing cached: Platform (by subtraction) 4.37, Server launch to model loaded 45.83, Compile 19.01, Memory profiling 0.09, Graph capture 4.0, Unattributed engine start 4.46, Ready check 4.43, First token 0.3 (s)
- B: weights cached: Platform (by subtraction) 4.07, Server launch to model loaded 30.35, Compile 18.79, Memory profiling 0.11, Graph capture 4.0, Unattributed engine start 4.38, Ready check 4.57, First token 0.3 (s)
- C: weights + compile: Platform (by subtraction) 4.83, Server launch to model loaded 21.34, Compile 0.33, Memory profiling 0.17, Graph capture 4.0, Unattributed engine start 3.83, Ready check 4.1, First token 0.3 (s)
- So: see decision `arms`

### Which cache bought more total cold start

- Axis: Median seconds of total cold start saved by each cache: the two contrasts on the same unit.
- Read it as: The compile cache saves about 10 s more per cold start. The difference of contrasts is −10.39 s, 95% bootstrap [−20.30, −5.54]: the interval never crosses zero, which is what licenses the ranking. Of the compile cache's 26.07 s, only 18.46 s is compilation. C also reaches "model loaded" 8.85 s sooner than B (paired): that gap opens before loading begins, and this campaign does not explain it.
- Weight cache (A to B): 15.68 s
- Compile cache (B to C): 26.07 s
- So: see decision `rank`

### KV cache left for serving, by arm

- Axis: KV cache tokens vLLM allocated at startup, same card and flags in every arm.
- Read it as: This is memory the compile cache gives back: 20.3 % more KV cache in C, one more concurrent request at 8192 context (5 instead of 4). On a cold arm the compiler's working set is still resident when vLLM measures free memory, so it sizes the cache smaller, and that loss lasts for the replica's whole life. Pre-registered as H5 before the campaign.
- A: 35792 tokens
- B: 35792 tokens
- C: 43040 tokens

## Interview card

**30-second pitch:** I measured where the time goes when a vLLM server starts cold on a rented GPU, and which of two caches is worth warming: the model weights or the engine's compiled code. I ran three set-ups that differ in one thing only, interleaved, about a hundred times each, and split every start into phases. The compile cache bought more than the weight cache, and it also left more memory for serving.

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

**Limits (what I must not claim):** One provider, one GPU model, one model, one engine version, one region, one host. The seconds do not transfer; the mechanisms do. H4 (does host placement drive the tail?) is unanswerable: all 300 runs landed on one host. Single replica, no contention. No percentile past p95; beyond it only single runs are shown. The first-touch rule that keeps the 2266.6 s run out of the ECDF (it stays in the medians) was written after seeing the data, and is disclosed as post hoc. Why C reaches "model loaded" 8.85 s sooner than B is not settled.

## Recall questions

- Q: Why are there three arms and not four?
  A: The fourth cell, weights cold with compile warm, has no operational meaning, so measuring it fills a table without answering a question. A baked-image arm was also excluded: it moves the weight bytes into the image pull, which is inside the platform residual the harness cannot see.
- Q: Why are the arms interleaved instead of run in blocks?
  A: Blocks would confound the cache with time-varying fleet conditions; a busy evening would be measured and labelled as an arm.
- Q: Why is arm C primed outside the campaign?
  A: Otherwise its early runs compile cold and its later runs do not, making the arm a mixture whose effect grows with run index and looks like a trend.
- Q: Why does the handler check the compile cache before the engine starts, not after?
  A: A cold compile creates the cache directory as it finishes. Checked afterwards, every healthy cold run would look warm and be discarded, and a real leak would pass unseen.
- Q: Why is the difference of contrasts computed on total cold start?
  A: It subtracts one contrast from the other, so both must be in one unit. Weight time minus compile time would difference two different quantities.
- Q: Why can platform time only be obtained by subtraction?
  A: Queueing, finding a machine, creating the container and pulling the image all happen before any measuring code exists. So it is total time on the laptop clock minus time on the worker clock. That residual also holds handler set-up, teardown and the driver's 5 s polling; RunPod's own queue delay was only about 0.13 s.
- Q: Why is a failed run never retried in place?
  A: A retry quietly replaces slow or unlucky runs with faster ones and makes the distribution look better than it is. Failures are their own rows and are counted per arm.
- Q: Why does the warm compile cache leave more KV cache?
  A: vLLM sizes the KV cache from free memory measured during a profiling pass. On a cold arm the compiler's working set is resident during that pass, so less memory looks free, and the smaller cache stays for the replica's life.

## Sources

- `docs/post.md`: ## Headline ranking, by the pre-registered rule
- `docs/post.md`: ## The decomposition
- `docs/post.md`: ## The distribution, not the mean
- `docs/post.md`: ## The two contrasts, and the interval on their difference
- `docs/post.md`: ### The part the compile cache saves that isn't compilation
- `docs/post.md`: ## KV capacity — the second dividend
- `docs/post.md`: ## Ready is already fast
- `docs/post.md`: ### Break-even, and why the two caches are not the same shape
- `docs/post.md`: ## Host heterogeneity: not answerable
- `docs/post.md`: ## Scope
- `docs/post.md`: ## Reproducing this
- `docs/experiment.md`: ## Configuration held fixed
- `docs/experiment.md`: ## Arms
- `docs/experiment.md`: ## Hypotheses
- `docs/experiment.md`: ## Analysis plan
- `docs/experiment.md`: ## Exclusion rules, fixed in advance
- `docs/experiment.md`: ## Stopping decision, recorded
- `docs/experiment.md`: ## Headline selection rule
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ## 1. Context and goal
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Resource envelope
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Variables
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Deliberate exclusion — the baked-image arm
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Sample plan
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### 6.1 Approach
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### 6.3 Two decisions worth calling out
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### 6.5 Clock discipline
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### 6.6 Failure handling
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### 6.8 Reconnaissance run — discovery before measurement
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Statistical treatment
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ### Known limitation, stated not solved — cold-start contention
- `docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md`: ## 9b. Learning guide
- `harness/README.md`: ## What is here
- `coldstart/cache_config.py`: class CacheConfig
- `coldstart/driver.py`: def _record_from
- `coldstart/schema.py`: class RunRecord
- `worker/handler.py`: Snapshot the cache state BEFORE run_probe(), not after.
- `worker/handler.py`: def _purge_cold_roots
- `worker/probe.py`: def run_probe
- `harness/campaign.py`: def check_resume
- `harness/scheduler.py`: def build_schedule
- `harness/recorder.py`: class StageRecorder
- `harness/vllm_logs.py`: MERGED: list[str] = ["S4a", "S4d"]
- `harness/stats.py`: def bootstrap_contrast_difference
- `coldstart/checks.py`: def check_consistency
- `coldstart/analysis/metrics.py`: t_total = t_total_job - warmup_tail
- `harness/runpod/submitter.py`: poll_interval: float = 5.0

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
