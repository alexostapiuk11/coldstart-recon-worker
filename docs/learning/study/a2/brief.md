# An autoscaling simulator that failed its own test: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: LLM serving on a GPU (P1), How these experiments earn trust (P2).

## Why it exists

**Question:** Which autoscaling (P1: serverless) signal, queue depth (requests waiting per replica), requests in flight per replica or GPU utilisation, gives the best cost and p99 trade-off in a traffic spike? Does a faster cold start (P1: coldstart) change the answer? The simulator built to answer it failed its own validation gate (P2: gate) twice.

**Requirements that drove everything:**

- Cold-start lag, latency under load and GPU utilisation come from hardware; only the autoscaler's control loop is simulated. *Why:* The gate then tests exactly the modelled part. Assuming how utilisation maps to load would invent the effect under test.
- Judge each signal by every cost/p99 trade-off its threshold grid reaches, not by one tuning. *Why:* Every policy has thresholds, and whichever set you publish decides the winner.
- Arm A (nothing cached, median 81.07 s) and arm C (fully cached, 39.37 s) differ only in cold-start lag; spike and traffic stay fixed. *Why:* H3 asks whether a faster cold start shrinks the gap between signals; anything else moving with the arm would confound it. (The A1 unit's 81.12 s also counts arm A's one image-pull run.)
- The simulator must reproduce a real replica's latency under a test fixed in advance; if it fails, publish the failure, not the answer. *Why:* Tuning a simulator until it agrees is "fabrication with extra steps" (the design spec); a failed gate is a result (P2: failed).
- Hypotheses, grids, control parameters, the traffic rule and the pass rule are committed before the sweep or validation they govern, except H1, H2 and H4, which were defined after the frontiers were seen; later changes are dated amendments (P2: amendment) saying what had been seen. *Why:* Otherwise the traffic could be tuned until a signal wins, or the tolerance until the model passes.
- Build and test the simulator, sweep and gate arithmetic with no GPU; keep paid runs small and stoppable; re-derive every number on a laptop. *Why:* Most of it was buildable offline. Estimate $35–60; billed $6.07, partly because the closed-loop run never happened.

## Need to know first

- **The control loop**: **A feedback loop with a long dead time.** A signal summarises the serving replicas' load, and every 5 s a controller may add or remove one replica. A new replica is billed at once but serves only after the cold start, so a spike builds a backlog until it arrives.
- **The service curve**: One replica's latency, throughput and GPU utilisation at fixed numbers of requests in flight, 1 to 128, three runs each; 256 ran out of GPU memory. The simulator reads service times from it instead of modelling continuous batching (P1: batching).
- **Little's Law**: **In flight = arrival rate × time each request spends.** At 128 in flight and 0.606 s each, one replica completes 128 / 0.606 = 211.2 req/s: the "saturation" every traffic rate here is a fraction of.
- **Why GPU utilisation is blind here**: nvidia-smi reads 1.0 from one request upward and 0 only when idle, so a utilisation autoscaler adds replicas at every chance up to its cap.
- **Frontier, dominance and the iso-cost slice**: A **policy** is a signal plus its up and down thresholds; over 30 simulated spikes it gives a median cost (**replica-seconds**, billed from each launch) and a median per-run p99. It is **dominated** if another costs no more, has no worse p99 and is better on one; the rest are the **frontier**. The **iso-cost budget** is the cheapest spend at which every signal has a policy; the **gap** is the worst signal's p99 there minus the best's. H3: the gap at least halves from arm A to arm C, on step and ramp.
- **The miss rule**: Per 10 s bin, each real repeat's residual is its p50 minus its own prediction. A bin **misses** when all three residuals sit on one side by more than 1 ms. With no bias each repeat is a coin flip, so a perfect model misses at most 2 × (1/2)³ = 1/4 of bins. **Pass:** at least 10 judged bins, at most half missing.
- **Host speed**: Rented GPUs of one model are not equally fast, and RunPod picks the host. Every other host measured had 4 to 18% lower latency than the curve's, more at high load: about the size of the gate's misses (14% and 13%). A measured cause, not shown to be the whole one.

## How it works

One replayed run: queue depth (up 4, down 1), arm C step spike, repetition 0. Re-run from committed code and seed (the sweep keeps only cost and p99) in a model that failed its gate twice: simulated, not measured.

| Step | What happens | Time (s) | Serving replicas | Starting (billed) | Queue per serving | Controller action |
|---|---|---|---|---|---|---|
| 1 | Spike: 253.4 req/s from t = 0 to 190 s, but one replica completes about 211.2 (Little's Law). Every 5 s the controller reads waiting requests per serving replica: up at 4 or more, down at 1 or less. (Decision: One controller, a grid per signal, frontiers) | 0 | 1 | 0 | 0 | hold: nothing queued yet |
| 2 | t = 5: the queue is 196 per replica, so UP one replica, billed from launch. It serves after a cold start (P1: coldstart) drawn from arm C's runs (median 39.37 s); this draw is 39.4 s. | **5** | 1 | **1** | **196** | **UP: launch replica 2** |
| 3 | t = 10 to 30: the queue grows (374 at t = 10), but one 30 s cooldown after any action, up or down, holds the fleet. At t = 35 it is 1,416 and replica 2 is still starting: UP again, replica 3. | **35** | 1 | **2** | **1,416** | **UP: launch replica 3** |
| 4 | t = 44.4 (5 + 39.4): replica 2 starts serving. Two replicas complete up to 2 × 211.2 = 422.4 req/s against 253.4 arriving, so the backlog drains. | **44.4** | **2** | **1** | **draining** | **none (not an evaluation)** |
| 5 | t = 65: queue 0 (requests wait only once all 128 slots per replica are full), so DOWN. The newest replica goes first: replica 3, still starting, billed for 30 s and never served. | **65** | 2 | **0** | **0** | **DOWN: remove replica 3** |
| 6 | t = 95: queue still 0, cooldown over: DOWN to one replica, with the spike still on at 253.4 req/s. A queue of 0 means enough capacity, and this rule removes the replica that made it enough. | **95** | **1** | 0 | 0 | **DOWN: remove replica 2** |
| 7 | The backlog rebuilds: t = 125, queue 1,274, UP; t = 155, queue 2,546, UP. The first serves at about 164 s, some 69 s after the scale-down: a second cold start under overload. | **155** | 1 | **2** | **2,546** | **UP at 125 and at 155** |
| 8 | t = 185: queue 0, so DOWN removes replica 5, still starting. t = 215, spike over (it ended at 190 s): queue 0, DOWN to one replica. | **215** | 1 | **0** | **0** | **DOWN at 185 and at 215** |
| 9 | Cost: 400 for replica 1 plus 90 + 30 + 90 + 30 = 240 for the four launched: 640 replica-seconds; p99 11.73 s. Of 570 replayed runs, 410 make the same eight moves at the same times. (Decision: One controller, a grid per signal, frontiers) | **400** | 1 | 0 | 0 | **end of window** |

Bold cells changed in that step.

**Takeaway:** In all 570 simulated runs the first scale-down comes before 190 s; the replayed run then pays a second cold start. Median p99 11.15 s against 7.20 s for utilisation. Real autoscalers were not tested.

## System views (C4)

### Who and what the study touches (context)

RunPod is rented two ways, a queue endpoint and a load-balancing endpoint; its billing API gives the spend. Output: a post that leads with the failed test.

- **Author**: designs, runs, publishes the failure
- **Autoscaling study**: simulator, its gate, and RunPod probes
- **Reader**: inference-platform engineers and managers
- **Artifact 1 cold starts**: 99 arm A and 100 arm C runs
- **RunPod queue endpoint**: curve sweep, recon, host re-measure
- **RunPod load balancer**: five probes, validation replays
- Author → Autoscaling study: designs, runs
- Autoscaling study → Reader: post + raw data
- Artifact 1 cold starts → Autoscaling study: lag samples
- Autoscaling study → RunPod queue endpoint: sweep jobs
- Autoscaling study → RunPod load balancer: HTTP load

### The runnable parts (container)

Laptop drivers run every paid step and write committed evidence. The analysis reads only committed files.

- **Laptop drivers**: curve sweep, LB probe, validation replay
- **Sweep worker**: one replica, 1 to 128 in flight
- **LB worker image**: vLLM capped at 128, plus stamping middleware
- **data/a2 evidence**: curve, probe rows, repeats, verdicts
- **Simulator (autoscale)**: CPU only: replays traffic on the curve
- **data/campaign.jsonl**: artifact 1's cold starts
- **Analysis + post**: post-analysis.json, figures, the post
- Laptop drivers → Sweep worker: one job per level and run
- Laptop drivers → LB worker image: open-loop HTTP
- Laptop drivers → data/a2 evidence: writes records
- data/a2 evidence → Simulator (autoscale): curve, arrivals
- data/campaign.jsonl → Simulator (autoscale): lag samples
- Simulator (autoscale) → Analysis + post: verdicts, sweep
- data/a2 evidence → Analysis + post: probe rows

### Inside the gate: a model that must pass (component)

Each repeat is replayed into the fixed-capacity simulator at the times its engine received the requests. Only the engine stamps run on the GPU worker; the rest is laptop code. Nothing is fitted to the trace.

- **Schedule builder**: one step spike, 64,784 requests
- **Open-loop sender**: sends on the clock, whatever the server does
- **Engine stamps**: arrival time and server latency
- **Repeat record**: every request, host id, retries
- **Host calibration**: attempt 2: ratios at 64 and 128
- **Measured curve**: latency by requests in flight
- **Fixed-capacity sim**: this repeat's engine arrivals, one replica
- **10 s bins, p50 each**: real and predicted, by engine arrival
- **Miss-rate verdict**: miss: all 3 repeats on one side
- Schedule builder → Open-loop sender: send times
- Open-loop sender → Engine stamps: through the LB
- Engine stamps → Repeat record: stamped rows
- Repeat record → Host calibration: two ratios
- Host calibration → Measured curve: scales
- Measured curve → Fixed-capacity sim: service time
- Repeat record → Fixed-capacity sim: engine arrivals
- Fixed-capacity sim → 10 s bins, p50 each: predicted
- 10 s bins, p50 each → Miss-rate verdict: residual per repeat

### One calibrated validation repeat, in order (dynamic)

Step 3 is attempt two's fix. The load balancer (step 5) is why the gate judges engine arrivals, not send times.

- **Driver**: laptop
- **Load balancer**: RunPod
- **Engine**: vLLM, 128 running at most
- **Simulator**: laptop

1. Driver -> Load balancer: Pin one worker (workersMin 1; owner set workersMax 1)
2. Driver -> Load balancer: Warm up (20 req/s until 30 s clean)
3. Driver -> Load balancer: Calibrate the host (hold 64, then 128 in flight)
4. Driver -> Load balancer: Replay the schedule (64,784 requests, open loop)
5. Load balancer -> Engine: Holds, then releases bursts
6. Engine -> Driver: Stamps each response (arrival time, server latency) [reply]
7. Driver -> Load balancer: Release, record (workersMin back to 0; one record)
   (gap: above: paid, on RunPod; below: free, laptop)
8. Driver -> Simulator: Predict this repeat (after 3 repeats: its own engine arrivals)
9. Note over Simulator: Bin and compare (p50 per 10 s bin; residual per repeat)
10. Simulator -> Driver: Verdict on three (pass: 10+ judged bins, at most half miss) [reply]

## Core decisions

### Answer in a simulator, held to a gate

**Problem:** The question needs dozens of policies run thirty times each through real spikes: out of budget on rented GPUs.

**Options considered:**

- Run the policies live on real replicas
- A model of vLLM's scheduler in place of the measured curve
- A simulator trusted without a test
- A simulator fed only measured inputs, gated first

**Chosen:** A simulator fed only measured inputs, gated first

**Why:** Modelling the scheduler would replace a measurement with an assumption about what continuous batching (P1: batching) does to latency; the curve measures it, and only the control loop is code. Discrete events need no tick size, and a seed makes runs reproducible.

**Cost:** If the gate fails there is no answer, and it failed twice. The design's second gate, one real closed-loop autoscaling run, was never built.

### One controller, a grid per signal, frontiers

**Problem:** Any published tuning decides the winner, and the signals do not share units: utilisation is a fraction, the others are counts.

**Options considered:**

- Hand-pick each signal's best thresholds
- One shared grid, 2 to 16, for all three
- One controller, a grid per signal in its own units; compare frontiers

**Chosen:** One controller, a grid per signal in its own units; compare frontiers

**Why:** A shared 2 to 16 grid puts every threshold above utilisation's maximum of 1, so it never scales and H2 "wins" by a units mismatch (checked: 0 scale-ups at 2.0). Fixed for every policy: a 30 s cooldown, a 5 s evaluation, a 12-replica cap, 30 repetitions.

**Cost:** Grids were fixed on 2026-09-05 against a placeholder curve that stopped at 64 in flight, and not revisited. On the measured curve each signal's step frontier is one point, and the iso-cost budget, 3,095 replica-seconds, is utilisation's floor: it never constrains the other two.

### Tolerance from reality's own repeatability

**Problem:** How close must the simulator be? The bar has to be fixed before any real run.

**Options considered:**

- A chosen tolerance, say 5%
- Compare against a fresh random draw of the traffic
- Require every bin inside the real runs' band
- Leave the number of repeats open
- Three repeats of the exact trace; at most half the 10 s bins may miss

**Chosen:** Three repeats of the exact trace; at most half the 10 s bins may miss

**Why:** A model cannot be required to be more reproducible than the system it models, so three real repeats set the tolerance, on the exact trace so traffic randomness cannot pose as model error. A perfect model still misses up to a quarter of bins, so "every bin" would often fail it; a model biased beyond the system's own spread misses most bins (the pre-registration's example, three bins in four, fails 92% of the time at 10 bins). Exactly three repeats: a min–max range only widens with more.

**Cost:** Correlated bins make a perfect model fail more often than the stated 2% at 10 bins (2.5% simulated, near 5% with host effects). p50 suited bins of a few hundred requests; the replay's held over a thousand. Two attempts at most.

### Choose the traffic by a ranking-blind rule

**Problem:** As registered, the spike peaked at 3.4× one replica's capacity and all 55 policies gave the same p99 to nine decimals. Later, on the measured curve, the replacement starved queue depth.

**Options considered:**

- Keep the registered traffic and report the tie
- Raise the replica cap
- Widen the threshold grids upward
- Search by a measure that cannot prefer a signal

**Chosen:** Search by a measure that cannot prefer a signal

**Why:** Past every threshold from the first evaluation, every signal says "scale up" at once, and with an 81 s cold start no replica arrives in time, so only cost differs. A bigger cap never binds; wider grids would redefine each signal's range. A count of distinct outcomes cannot pick a winner, and the first re-choice refuted the hypotheses, which a rigged choice would not.

**Cost:** Choosing traffic after seeing data is a real hazard: per-policy p99s had been printed before the second search's criteria were written, as the amendment says. The gate stayed at 0.95× capacity while the sweep moved to 1.20×.

### Validate the engine, not the platform

**Problem:** The replica sits behind RunPod's load balancer, which, the probes found, caps, routes, stalls and drops requests in ways the simulator does not model.

**Options considered:**

- RunPod's queue API (/run) for the replay
- Two pinned replicas, as first signed
- Judge client latency, or bin by send time
- Retry failures until they succeed
- One replica, judged on what its engine received; an unanswered 502 retried once

**Chosen:** One replica, judged on what its engine received; an unanswered 502 retried once

**Why:** The queue API allows 1,000 requests per 10 s, far below the replay's planned peak of about 400 req/s. The load balancer fills one worker before the next, so two replicas would score its routing against the simulator's even split; it holds and releases bursts, so send times would score its stalls as model misses. Retrying until success hides failures.

**Cost:** The prediction can no longer be written before the run, and the bursts become model input: the engine held more than its 128 running cap, up to 512 counting requests queued inside it. Even splitting across replicas stays untested.

### One disclosed fix, then publish the failure

**Problem:** Attempt one failed; an exploratory re-measurement pointed to host speed. What may change without bending the test?

**Options considered:**

- Keep adjusting until it passes
- Fit the curve to the validation runs
- Publish the frontiers with a caveat
- One disclosed fix, declared the last attempt; then publish the failure

**Chosen:** One disclosed fix, declared the last attempt; then publish the failure

**Why:** Tuning until it agrees is what R4 forbids. The fix was two numbers per repeat, latency ratios at 64 and 128 in flight measured on the same worker before its replay, on traffic the gate never judges. It failed the other way by about as much (the engine 14% faster than predicted, then 13% slower).

**Cost:** No measured answer. Why the calibration over-corrected is an untested hypothesis (closed-loop calibration, open-loop bursty replay; one host). H1, H2 and H4 were defined only after the frontiers were seen, and are labelled so.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Cold-start lag, latency under load and GPU utilisation come from hardware; only the autoscaler's control loop is simulated.
  - `simulate` Answer in a simulator, held to a gate: Lags, latency and utilisation are measured; only the control loop is code, and that is what the gate tests.
  - `engine` Validate the engine, not the platform: Server latency is what the curve measured; client latency adds network and load-balancer time.
- R2: Judge each signal by every cost/p99 trade-off its threshold grid reaches, not by one tuning.
  - `frontiers` One controller, a grid per signal, frontiers: Every threshold pair is run, so no single tuning picks the winner.
- R3: Arm A (nothing cached, median 81.07 s) and arm C (fully cached, 39.37 s) differ only in cold-start lag; spike and traffic stay fixed.
  - `traffic` Choose the traffic by a ranking-blind rule: Rates and the 190 s length are the same for both arms, so the arms differ only in lag.
- R4: The simulator must reproduce a real replica's latency under a test fixed in advance; if it fails, publish the failure, not the answer.
  - `simulate` Answer in a simulator, held to a gate: The simulator's answer counts only once it passes a pre-registered test.
  - `tolerance` Tolerance from reality's own repeatability: It is the test the answer must pass: a perfect model passes it, a biased one fails.
  - `engine` Validate the engine, not the platform: The gate stays a test of the engine model, not of a platform the model never described.
  - `onefix` One disclosed fix, then publish the failure: After the second failure the failure was published, not the frontiers.
- R5: Hypotheses, grids, control parameters, the traffic rule and the pass rule are committed before the sweep or validation they govern, except H1, H2 and H4, which were defined after the frontiers were seen; later changes are dated amendments (P2: amendment) saying what had been seen.
  - `tolerance` Tolerance from reality's own repeatability: Committed on 2026-10-03, before any real validation run.
  - `traffic` Choose the traffic by a ranking-blind rule: Each re-choice is a dated amendment; the second search's criteria were committed before its code.
  - `onefix` One disclosed fix, then publish the failure: The fix was a signed amendment, declared the last attempt, before it ran.
- R6: Build and test the simulator, sweep and gate arithmetic with no GPU; keep paid runs small and stoppable; re-derive every number on a laptop.
  - No decision: Met by process: "Build the simulator with no GPU" and "Commit the pass rule" come before any paid run, and one script re-derives every published number from committed files.

**Decisions and the concepts they use:**

- `simulate` Answer in a simulator, held to a gate uses The service curve: The engine enters as this measured curve, not a queueing formula.
- `frontiers` One controller, a grid per signal, frontiers uses Frontier, dominance and the iso-cost slice: Signals are compared frontier against frontier, at the iso-cost budget.
- `frontiers` One controller, a grid per signal, frontiers uses Why GPU utilisation is blind here: Utilisation gets a 0 to 1 grid, yet reads 1.0 above all of it, so its 19 policies ran at the cap.
- `tolerance` Tolerance from reality's own repeatability uses The miss rule: The miss rule is the tolerance: all three repeats on one side is a miss.
- `traffic` Choose the traffic by a ranking-blind rule uses Little's Law: Baseline and peak are fractions of one replica's Little's-law saturation.
- `traffic` Choose the traffic by a ranking-blind rule uses Frontier, dominance and the iso-cost slice: A spike past every threshold gives every policy one p99, so no frontier separates the signals.
- `engine` Validate the engine, not the platform uses The miss rule: Each repeat is held to its own prediction, so bursts that differ per repeat still compare like with like.
- `engine` Validate the engine, not the platform uses The service curve: Capped at 128 running, the curve's top level, the engine queued the rest, as the simulator does.
- `onefix` One disclosed fix, then publish the failure uses Host speed: The fix measured each repeat's host speed, the cause attempt one pointed to.
- `onefix` One disclosed fix, then publish the failure uses The miss rule: Both failures read the same way: all three repeats on one side, almost every bin.

**Results and the decisions they support:**

- The service curve: latency as load rises → `simulate` Answer in a simulator, held to a gate
- Throughput, traffic, and what each signal sees → `traffic` Choose the traffic by a ranking-blind rule
- The test, twice: which side the engine landed on → `tolerance` Tolerance from reality's own repeatability, `onefix` One disclosed fix, then publish the failure
- Host speed: one GPU model, different latency → `onefix` One disclosed fix, then publish the failure
- The load balancer's default cap: offered against delivered → `engine` Validate the engine, not the platform
- UNVALIDATED: what each policy spent and reached (arm C, step) → `frontiers` One controller, a grid per signal, frontiers

## Implementation flow

9 steps in 5 phases, 5 milestones.

Milestones: 1. Specify a gated simulator, then re-base on artifact 1 (2026-08-17 to 09-04); 4. Commit the pass rule before any real run (2026-10-03); 7. Attempt one fails; host speed implicated (2026-10-05); 8. Calibrate the host; attempt two fails (2026-10-05); 9. Publish the failure; label the simulator (2026-10-05 to 10-18).

### Phase 1 of 5: Design (1 step)

1. **Specify a gated simulator, then re-base on artifact 1** [MILESTONE]: The August spec: three signals, two spike shapes, a gate. On 09-04 the final spec took artifact 1's numbers, and the pre-registration followed that night, before simulator code.
   - Output: design spec, final spec and pre-registration, before simulator code
   - When: 2026-08-17 to 09-04
   - Decision: `simulate` Answer in a simulator, held to a gate
   - Evidence: 44841330db (first spec); efe6ab3ae9 (final spec on artifact 1's numbers); d762b29d4c (pre-registration)

### Phase 2 of 5: Build offline (2 steps)

2. **Build the simulator with no GPU**: Lag resampling, event queue, one controller, sweep and frontiers, on a placeholder curve flagged unmeasured. A discard rule that dropped every run was amended before any result.
   - Output: autoscale/: simulator, controller, sweep and frontiers, tested offline
   - When: 2026-09-04 to 09-05
   - Decision: `frontiers` One controller, a grid per signal, frontiers
   - Evidence: 66adb11198 (event queue); 1270f41398 (one controller, swept); 652d7cb409 (grid per signal); 5dfbd806c4 (sweep, frontiers, H3 verdict); 6054dc8c00 (never-served rule amended)
3. **Find the traffic made the question unanswerable**: After a fix (the three signals had been scored on three different traces), all 55 policies gave the same p99. A ranking-blind probe chose new traffic; medians and intervals replaced means.
   - Output: findings-a2-degenerate-regime.md; traffic and statistics amended
   - When: 2026-09-17
   - Decision: `traffic` Choose the traffic by a ranking-blind rule
   - Evidence: b249915cb4 (signals on one trace); 181ef735cf (degeneracy finding); 34ccc2c066 (traffic amended); d61c2095bb (statistical layer)

### Phase 3 of 5: Measure the inputs (2 steps)

4. **Commit the pass rule before any real run** [MILESTONE]: The gate's arithmetic, in a module with no path to artifact 1's code, then the pass rule: three repeats, 10 s bins, at most half missing.
   - Output: validation_band.py and the pass rule in experiment-a2.md
   - When: 2026-10-03
   - Decision: `tolerance` Tolerance from reality's own repeatability
   - Evidence: 8c3b4c7894 (gate arithmetic); 74ba3c8883 (pass rule pre-registered)
5. **Measure the curve; re-choose traffic, criteria first**: The curve, 1 to 128 in flight; recon: pinning holds capacity, a driven scale-up is a real cold start. The old traffic starved queue depth; search criteria were committed, then the search run.
   - Output: service-curve.json; amendments 2026-10-04 and (second): peak 1.20×
   - When: 2026-10-04
   - Decision: `traffic` Choose the traffic by a ranking-blind rule
   - Evidence: 8f664d1645 (measured curve); c3ed1ea7c6 (recon capture); 80ccac2ae9 (search criteria first); 63894dd11d (the search); 29680d3d1a (amendment signed)

### Phase 4 of 5: Validate on RunPod (3 steps)

6. **Probe the load balancer; amend the gate three times**: Probes found a default cap near 17 req/s, fill-first routing, stalls and unanswered 502s. Amendments: retry such a 502 once; one replica; judge engine arrivals.
   - Output: five probes; three amendments; three early repeats kept unjudged
   - When: 2026-10-04 to 10-05 (−07:00)
   - Decision: `engine` Validate the engine, not the platform
   - Evidence: 68c856ce1b (probe built offline); 4bb61d9e0e (502 retry); 2d2d921e07 (one replica); 3a6a3c3f98 (engine arrivals); bfb3cbc6a4 (unjudged repeats kept)
7. **Attempt one fails; host speed implicated** [MILESTONE]: 34 of 37 judged bins missed, the engine faster than predicted. One void repeat (a worker restarted on the old image) was re-run. A re-measurement afterwards ruled out the engine flag and found hosts differ by about the size of the miss. Host speed is a measured cause, not shown to be the whole one: attempt one's own host had about 7% lower latency at ~100 in flight, while the quiet bins missed by 14%.
   - Output: validation-engine/verdict.json: failed; host-speed finding
   - When: 2026-10-05
   - Decision: `onefix` One disclosed fix, then publish the failure
   - Evidence: 3aec1b1ce8 (attempt one, failed); 41f2788b25 (host speed, exploratory)
8. **Calibrate the host; attempt two fails** [MILESTONE]: Signed as the second and last attempt. 37 of 37 bins missed the other way, the engine slower than the calibrated prediction.
   - Output: validation-calibrated/verdict.json: failed, the other way
   - When: 2026-10-05
   - Decision: `onefix` One disclosed fix, then publish the failure
   - Evidence: 4b42b959c4 (calibration amendment); ad3df6321e (attempt two, failed)

### Phase 5 of 5: Publish the failure (1 step)

9. **Publish the failure; label the simulator** [MILESTONE]: An exploratory speed check; H1, H2, H4 defined after the frontiers were seen; one analysis file feeds every number; the post leads with both failures; a probability claim corrected on 10-18.
   - Output: post-a2.md, post-analysis.json, five figures, spend-a2.md
   - When: 2026-10-05 to 10-18
   - Decision: `onefix` One disclosed fix, then publish the failure
   - Evidence: 5c50994c13 (service-speed check); 31bc8bea85 (H1, H2, H4 after the frontiers); 54118f4aba (post written); fd7554a619 (spend from billing API); 270374c1ca (1/4 claim corrected)

## Results as meaning

### The service curve: latency as load rises

- Axis: Measured: one replica of vLLM serving Qwen3-8B on an RTX 4090, median end-to-end latency at each fixed number of requests in flight.
- Read it as: Latency only doubles from 1 to 128 in flight while throughput grows about 58-fold: what continuous batching (P1: batching) buys. The simulator reads every service time from this one host's curve.
- How it is computed: Each point is the median of three runs' medians; 0.606 / 0.284 = 2.1.
- Axes: x is requests in flight on one replica (log scale); y is median latency (s)
- median of 3 runs: 1: 0.284, 2: 0.306 (0.306 to 0.307), 4: 0.308 (0.308 to 0.321), 8: 0.325 (0.324 to 0.325), 16: 0.349, 32: 0.376 (0.375 to 0.38), 64: 0.439 (0.436 to 0.458), 128: 0.606 (0.604 to 0.614)
- Note: Whiskers: lowest and highest of the three runs. At 256 in flight the engine died (out of GPU memory) in 3 of 3 runs, so the curve stops at 128.
- So: see decision `simulate`

### Throughput, traffic, and what each signal sees

- Axis: Measured: throughput and GPU utilisation at each fixed number in flight. Dashed: traffic levels (multiples of the 211.2 req/s saturation). Waiting is arithmetic.
- Read it as: The sweep's spike stayed at 1.20× saturation (253.4 req/s), a regime the gate never tested. GPU utilisation reads 1.0 from the first point, 3.5 req/s or 1.7% of 204.4. In flight rises across the range, but its 2 to 16 grid is crossed by 45.5 req/s while the baseline sits near 66. Queue depth stays 0 until the replica is full.
- How it is computed: Saturation by Little's Law: 128 / 0.606 s = 211.2 req/s (measured at 128: 204.4). Baseline 0.70 × 211.2 = 147.8; peaks add 0.25 or 0.5 × 211.2: 200.6 and 253.4 req/s. 200.6 / 204.4 = 0.98 of measured throughput.
- Axes: x is load on one replica (req/s); y is requests per replica; right y is GPU utilisation ()
- in flight, at its measured load: 3.5: 1, 6.5: 2, 12.9: 4, 24.3: 8, 45.5: 16, 82.6: 32, 139.5: 64, 204.4: 128
- waiting added per second, arithmetic: 0: 0, 204.4: 0, 253.4: 49
- GPU utilisation, measured (points, right axis, ): 0: 0, 3.5: 1, 6.5: 1, 12.9: 1, 24.3: 1, 45.5: 1, 82.6: 1, 139.5: 1, 204.4: 1
- Band: grid 2–16, 2 to 16
- Reference: baseline 0.70× at x = 147.8
- Reference: gate peak 0.95× at x = 200.6
- Reference: sweep peak 1.20× at x = 253.4
- Note: Waiting is arithmetic; bursty arrivals queue a little below 204.4.
- So: see decision `traffic`

### The test, twice: which side the engine landed on

- Axis: Per judged 10 s bin: real p50 ÷ predicted p50 per repeat, median of three, minus 1. Real: measured on RunPod. Predicted: the simulator fed the arrivals that engine received.
- Read it as: Below zero, the engine was faster than predicted. Attempt one is below in every bin, down to −89% after load-balancer bursts; attempt two, calibrated to its host, is 12–16% above in every bin.
- How it is computed: Median over the 37 judged bins: 0.856 (14% below) and 1.127 (13% above); per bin, 0.11 to 0.955 and 1.116 to 1.16. Recomputed from the repeat records.
- Axes: x is engine arrival time, start of each 10 s bin (s); y is real ÷ predicted latency − 1 (%)
- attempt 1, curve as measured: 0: -14, 10: -15, 20: -14, 30: -15, 40: -6, 50: -27, 60: -46, 70: -48, 80: -21, 90: -34, 100: -51, 110: -63, 120: -85, 130: -89, 140: -87, 150: -85, 160: -83, 170: -67, 180: -72, 190: -61, 200: -7, 210: -10, 220: -8, 230: -7, 240: -5, 250: -9, 260: -31, 270: -7, 280: -7, 290: -8, 300: -8, 310: -7, 320: -13, 330: -8, 340: -11, 350: -8, 360: -8
- attempt 2, host-calibrated: 0: 15, 10: 13, 20: 12, 30: 15, 40: 14, 50: 15, 60: 14, 70: 12, 80: 14, 90: 16, 100: 14, 110: 13, 120: 13, 130: 13, 140: 14, 150: 14, 160: 14, 170: 16, 180: 13, 190: 12, 200: 13, 210: 12, 220: 13, 230: 13, 240: 13, 250: 12, 260: 12, 270: 12, 280: 12, 290: 13, 300: 13, 310: 12, 320: 12, 330: 12, 340: 12, 350: 12, 360: 12
- Band: ±1 ms at a 0.5 s p50, -0.2 to 0.2 %
- Reference: prediction at y = 0 %
- Note: Attempt one's bins at 40, 230 and 270 s did not miss.
- So: see decisions `tolerance`, `onefix`

### Host speed: one GPU model, different latency

- Axis: Measured: server latency on each RunPod host relative to the curve's host (ozhetwnhompob9), at high load. Bars: lowest to highest of three runs; ku80i8usxw3st5 has one reading.
- Read it as: At high load every other host measured had 7 to 18% lower latency, the size of the gate's misses; the simulator knows one host. Three hosts show a spread, not a distribution.
- How it is computed: Latency ÷ the curve's: 0.90 at 128 (0.897–0.907); 0.494 / 0.533 = 0.927 at ~100; 0.834 at 128 (0.822–0.841). Percent = (ratio − 1) × 100.
- daps3haubwrzbn, re-measured, 128 in flight: -10.0 % (interval -10.3 to -9.3)
- ku80i8usxw3st5, attempt 1, ~100 in flight: -7.3 % (interval -7.3 to -7.3)
- sef5s24viyecyr, attempt 2, 128 in flight: -16.6 % (interval -17.8 to -15.9)
- So: see decision `onefix`

### The load balancer's default cap: offered against delivered

- Axis: Measured on 2026-10-05: two RTX 4090 workers behind RunPod's load-balancing endpoint, 30 s per offered rate. Exploratory probes, not pre-registered.
- Read it as: At RunPod's default scaler value of 4 the path delivered about 17 req/s whatever was offered, while the engine's p50 stayed at 0.31 s: requests waited in the load balancer, which caps each worker at that many in flight.
- How it is computed: At the billed $1.1085/h ($1.11 rounded) for 2 workers: $36.02 per million at 17.1 req/s, $2.05 at 300.7; 300.7 / 17.1 = 17.6, the post's 18×.
- Axes: x is offered (req/s); y is delivered (req/s)
- delivered = offered (reference): 0: 0, 450: 450
- scaler value 128 (probe 3) (points): 25: 25.1, 50: 50, 100: 100.3, 200: 199.5, 300: 300.7, 450: 350.4
- scaler value 4, default (probe 1) (points): 25: 16.7, 50: 17.1, 100: 17.3
- Note: Probe 1 stopped after 100 req/s: the driver could not start another thread.
- So: see decision `engine`

### UNVALIDATED: what each policy spent and reached (arm C, step)

- Axis: Simulated, not measured, by a model that failed its gate twice. Each dot is one policy (signal and thresholds): its median over 30 simulated step spikes with arm C's cold starts.
- Read it as: Utilisation sat at the cap, 3,095: 400 for replica 1 plus 11 launches, at 5 s and every 30 s to 12 replicas. In flight pays for fewer launches as its threshold rises, from 3,095 at up 2 and 4 to 2,320 at up 16. Queue depth spent 640 in all 19 policies because its signal reads 0 or hundreds, so thresholds rarely change what it does. The budget line constrains no one, so H3's 3.96 s "gap" is queue depth spending 640 against 2,320–3,095. A rerun with scale-down off (exploratory, not committed) brought its p99 close to the others', which suggests the scale-down rule (see How it works) is part of the gap.
- How it is computed: Gap = worst reached p99 − best at the budget: 11.15 − 7.20 = 3.95 s on rounded values (post: 3.96, 95% interval 3.52–4.56). Arm A's step: 0.082 s, so H3's halving fails. Cap cost: 400 + 11 × 395 − 30 × 55 = 3,095.
- Axes: x is replica-seconds per spike (median of 30); y is per-run p99 latency, median of 30 (s)
- queue depth (19): 640: 11.2, 640: 11.3, 640: 11.4 ×2, 640: 11.5 ×7, 640: 11.6 ×3, 640: 11.7 ×2, 640: 11.8, 640: 11.9, 640: 12.0
- in flight (17): 2320: 7.2 ×2, 2320: 7.4, 2422.5: 7.4, 2535: 7.2, 2535: 7.4, 2535: 7.5 ×2, 2535: 7.6, 2540: 7.6, 2550: 7.4, 2555: 7.6, 3095: 7.5 ×2, 3095: 7.6 ×2, 3095: 7.7
- GPU utilisation (19): 3095: 7.2, 3095: 7.3 ×3, 3095: 7.4 ×5, 3095: 7.5 ×5, 3095: 7.6 ×4, 3095: 7.7
- Frontier, best p99 at each cost, any signal (lower-left is better): 640: 11.15, 2320: 7.22, 3095: 7.2
- Reference: iso-cost budget at x = 3095
- Note: SIMULATED, FAILED VALIDATION. The p99 axis starts near 7 s. Each signal's own frontier is one point: its cheapest policy is also its fastest. Pairs whose down threshold is not below the up threshold are skipped (3 of 20 for in flight, 1 for each other signal), hence 17, 19 and 19 policies.
- So: see decision `frontiers`

## Interview card

**30-second pitch:** I tried to find which autoscaling signal, queue depth, requests in flight or GPU utilisation, gives the best cost and tail-latency trade-off for an LLM server whose new replicas take tens of seconds to over a minute to start. Live tests were too expensive, so I built a simulator from measured inputs with a pre-registered test it had to pass. It failed twice: it first predicted latency too high, which I traced partly to host speed, then, calibrated to the host, too low, for a reason I could not settle. So I published the failure, and two measured findings: GPU utilisation reads 100% from one request, and RunPod's load balancer caps each worker at 4 requests in flight by default.

**2-minute version:** A new LLM replica takes a median 39 to 81 seconds to start, so the signal an autoscaler watches has to see trouble early. I compared queue depth, requests in flight and GPU utilisation by their whole cost-versus-p99 frontiers, and asked whether a faster cold start shrinks the difference. Dozens of policies run thirty times each was out of budget on real GPUs, so I built a simulator where every input is measured and only the control loop is code, and committed a pass rule before any real run: replay a real spike three times; a 10-second bin misses if all three runs land on one side of the prediction; more than half missing fails. It failed with the engine 14% faster than predicted. A re-measurement ruled out the engine flag and showed hosts differ by about that much, so host speed is part of the cause. I made one disclosed fix, declared it the last attempt, and it failed 13% the other way. So I published the failure instead of the frontiers. Two findings are measured: nvidia-smi utilisation reads 1.0 from one request, and RunPod's load balancer caps requests per worker at a setting documented only for autoscaling, which made each request 18 times dearer. The paid part cost $6.07.

**Hard follow-ups:**

- Q: So which signal should I use?
  A: Not answered by measurement. Measured: nvidia-smi utilisation reads 1.0 from one request up, so all 19 simulated utilisation policies ran to the cap. The unvalidated simulator puts the three within 82 ms on arm A's step, queue depth spending 880 replica-seconds against 2,535–3,095. Practically, on this stack: don't scale on nvidia-smi utilisation; check the load balancer first.
- Q: Why trust a simulator at all?
  A: By default I didn't. 55 policies × 30 repetitions × 4 sweeps is 6,600 simulated spikes, unaffordable live, so it had to pass a rule committed on 2026-10-03, before any real run. It failed, and that is what I published.
- Q: Wasn't the calibration just moving the goalposts?
  A: One disclosed fix was allowed, and the amendment declared it the last attempt before it ran: two numbers per repeat, from traffic the gate never judges. It failed the other way by about as much, which is the finding: the host moves latency as much as the model's error.
- Q: You changed the traffic twice after seeing data. Isn't that p-hacking?
  A: The registered spike gave every policy one p99: no question to answer. Both re-choices used measures that cannot prefer a signal, and the second search's criteria were committed before its code. I concede that per-policy p99s had been seen (the amendment says so), and the gate never tested the overload the sweep ran in.
- Q: What would a careful reviewer flag in your own write-up?
  A: The gap's interval is called paired, but the code pairs only queue depth with in-flight at shared thresholds; utilisation runs on other traces. H3's wording says "p99-damage spread", the spec's integral over an SLO, but the analysis uses each run's p99 and no SLO exists. And the post omits the request shape (random 13-token prompts, 16 output tokens) and the absent-or-serving replica model.
- Q: How would you autoscale vLLM on Kubernetes, given what you found?
  A: What the data supports: do not scale on nvidia-smi utilisation (measured: 1.0 from one request). Scale up on requests in flight per replica with a target well above the registered 2 to 16, since one replica holds about 66 at the 147.8 req/s baseline. Keep warm capacity for one cold start: a step past what the replicas complete (204.4 req/s each) builds a backlog until the first new one serves, whatever the signal (simulated, unvalidated). Scale down slowly: the simulated queue-depth thrash came from removing a replica as soon as the queue read 0. Not tested: any real autoscaler, so I would check how Kubernetes autoscalers handle scale-down windows in their current docs, and validate closed loop, which I did not.
- Q: Which metric would you scale on in production?
  A: Requests in flight per replica, the one graded signal here: it rises from 1 to 128 across the range, while queue depth is 0 until a replica is full and utilisation is 1.0 from the first request. I would add waiting requests as a fast overload trigger, not as the scale-down signal. Measured: the curve and the utilisation reading. Not measured: where in-flight's threshold should sit, or how a real autoscaler behaves.
- Q: How many replicas for 1,000 req/s?
  A: Capacity first: one replica completes 204.4 req/s at 128 in flight, so 1,000 / 204.4 = 4.9, at least 5 with no headroom. At the 147.8 req/s baseline, near 66 in flight, 1,000 / 147.8 = 6.8, so 7. A burst needs warm capacity for the cold start (39.37 s or 81.07 s), because a replica launched into the burst is not there in time. Caveat: an even split is assumed (RunPod fills one worker first) and the request shape is a toy (13-token prompts, 16 output tokens); measure your own curve.
- Q: What would you do differently?
  A: Measure host speed per run from the start; settle the load balancer before the gate; validate in the sweep's overload; build the closed-loop gate. And revisit the grids: in-flight's tops out at 16, while one replica holds over 64 in flight at baseline alone (139.5 req/s at 64, under the 147.8 baseline). Checked: in replays of in-flight policies from up 2 to up 16 the signal reads 128 per serving replica at the first evaluation, above every threshold in the grid, so all of them scale up at once and the grid only sets where scaling stops. Sweep medians, arm C step: up 2 and 4 reach the cap (3,095), up 8 and 12 stop at 2,535 to 2,555, up 16 at 2,320 to 2,422.5 (simulated).

**Limits (what I must not claim):** No measured answer: every frontier, H1–H4 verdict, gap and per-signal dollar figure is from a simulator that failed validation twice, and H1, H2, H4 were defined after the frontiers were seen. The control loop was never compared with a real autoscaler. The gate tested 0.95× saturation (0.98× of measured throughput), the sweep ran at 1.20×. Even load splitting is assumed; RunPod fills one worker first. One provider, GPU, model, engine version (vLLM 0.27.1) and request shape; replicas absent or serving; 6 hosts seen, 3 timed. Load-balancer findings: five unregistered probes on 2026-10-05.

## Recall questions

- Q: Which requirement breaks if the frontiers are published although the gate failed?
  A: R4, no answer before the model passes: every number would be an unvalidated model's, presented as a finding.
- Q: Why does a perfect model still miss about one bin in four, and how does the pass rule allow for it?
  A: Unbiased, each repeat lands above or below its prediction like a coin, so all three on one side has probability at most 2 × 1/8 = 1/4, less with the 1 ms margin. The rule passes with at least 10 judged bins and at most half missing.
- Q: Attempt one missed with the engine faster, attempt two, calibrated, with it slower. What does the pair let you conclude?
  A: The model's error is about the size of a host's effect (14% against 13%), so a one-host curve cannot predict the hosts RunPod picks. Host speed is a measured cause, not shown to be the whole one, and the pair does not say which way a given host goes.
- Q: Why do two failures mean the answer is not in this study, rather than "try a third fix"?
  A: The calibration was signed as the second and last attempt before it ran; a third fix after two failures is the tuning-until-it-agrees R4 forbids.
- Q: Why does the gate judge the arrivals the engine received, not the driver's send times?
  A: RunPod's load balancer held requests and released bursts, so the engine never received the schedule. Judged by send time, the platform's stalls would count as simulator misses.
- Q: Why is GPU utilisation blind on this engine, and what did it do to its policies?
  A: nvidia-smi reads 1.0 from one request up, above every threshold (highest 0.95), so it scales up at every chance: all 19 policies ran at the 12-replica cap.
- Q: As registered, all 55 policies gave the same p99. Why, and why not just raise the replica cap?
  A: At 3.4× capacity every signal is past every threshold from the first evaluation and no replica arrives within the 81 s cold start, so all act alike. The cap never bound: 12, 24 and 64 gave identical results.
- Q: On arm C the simulated gap is 3.96 s. Why is that not a clean signal effect?
  A: The budget, utilisation's floor (3,095), never constrains the other two, so the gap compares queue depth at 640 replica-seconds with signals spending 2,320–3,095.
- Q: Which requirement does holding the spike fixed across arms protect, and in what unit is the spike set?
  A: R3, vary only the cold start. Its rates are fractions of one replica's Little's-law saturation, 211.2 req/s, and its 190 s length is the same for both arms.

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
