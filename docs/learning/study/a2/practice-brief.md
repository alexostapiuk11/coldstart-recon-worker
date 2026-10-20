# Practice: reading the autoscaling loop: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: An autoscaling simulator that failed its own test. About 35 minutes.

## Objectives

- Draw the simulated autoscaling loop in two minutes and mark which parts were measured and which are code.
- Derive each signal's blind spot on this engine: utilisation from 1.7% of capacity, queue depth below 100%, in flight near 66 at baseline.
- Predict a policy's replica-seconds from its launch times, and a step spike's p99 from the cold start, to within about a tenth.
- Explain the validation gate: the 1/4 per-bin miss rate, the pass rule, both failures and the near-saturation amplification.
- Contrast this one-step controller with a proportional autoscaler and say which findings would not transfer.
- State the limits without overclaiming: unvalidated simulator, untested overload, one host curve, load-balancer findings dated 2026-10-05.

## Check yourself first

### Check 1

Q: One replica serves 128 requests at once and each takes 0.606 s. How many requests per second does it complete, and which law gives it?
KEY: 128 / 0.606 = 211.2 req/s, by Little's Law (in flight = arrival rate × time each request spends). The measured completions at 128 in flight are a little lower, 204.4 req/s.
If missed, review: Little's Law

### Check 2

Q: A new replica is launched at t = 0. What happens before it serves its first request, and how long does that take with and without caches here?
KEY: Platform queue, container start, weights load, compile and warm-up. The median lag is 81.07 s with nothing cached (arm A) and 39.37 s with weights on a network volume and a warm compile cache (arm C).
If missed, review: Cold start (P1: coldstart)

### Check 3

Q: You fixed a pass rule, the model failed it, you made one disclosed change, and it failed the other way. What may you publish?
KEY: The failure and every miss; the model's own numbers only labelled unvalidated. A third fix would be tuning until it agrees, which the pre-registration forbids.
If missed, review: A failed gate is a result (P2: failed)

## Estimation drills

### Estimate 1: What does a policy cost before you run it?

Problem: A 400 s window starts with one replica already running. The controller evaluates every 5 s, acts at most once per 30 s cooldown, adds or removes one replica, and caps at 12; a replica is billed from launch. Traffic starts at t = 0, so the first evaluation that sees work is t = 5 s. Find the cost of (a) utilisation, (b) in flight with up 16 on arm C, (c) queue depth, up 4 and down 1, on arm C.

KEY steps:

1. Utilisation reads 1.0 whenever a replica is busy, so it launches at 5, 35, ..., 305 s: 11 launches, then the cap of 12.
2. A launch at t is billed 400 − t seconds: 395, 365, ..., 95. Their sum is 11 × 395 − 30 × (0 + 1 + ... + 10) = 4,345 − 1,650 = 2,695.
3. Add the first replica's 400: 3,095. The cold start never enters, so every utilisation policy costs 3,095.
4. In flight, up 16: the signal reads 128 per serving replica at 5 s and 35 s, so it launches at 5, 35, ..., 155 s (6 launches), then stops. Billed 395 + 365 + 335 + 305 + 275 + 245 = 1,920, plus 400 is 2,320, the sweep's median for up 16 with down 1, 2 or 4.
5. Queue depth, up 4 and down 1: replica 2 runs 5 to 95 s (90), replica 3 runs 35 to 65 s (30), replica 4 runs 125 to 215 s (90), replica 5 runs 155 to 185 s (30): 240, plus 400 is 640.

KEY answer: (a) 3,095, (b) 2,320, (c) 640 replica-seconds. A threshold controller's cost is how many cooldown periods its signal stays past a threshold, which is set by what the signal can see, not by the exact threshold.

### Estimate 2: What step p99 does a 1.2× overload produce, whatever the signal?

Problem: One replica completes 211.2 req/s and arrivals jump to 253.4 req/s, a ratio ρ of 1.2. The first extra replica serves at D = 5 s plus the cold start. Treat the queue as a fluid FIFO queue with a service time of about 0.6 s. Estimate the worst wait for arm C (39.4 s cold start) and arm A (81.1 s), and say what removes it.

KEY steps:

1. A request arriving at t < D finds (λ − μ)t ahead of it, served at μ, so it waits (ρ − 1)t, unless the second replica arrives first.
2. The worst request is the one whose wait ends exactly at D: (ρ − 1)t = D − t, so t = D/ρ. Its wait is D − D/ρ = D(1 − 1/ρ). After D two replicas drain at 2μ, so later arrivals wait less.
3. Add the service time: W_max = D(1 − 1/ρ) + 0.6.
4. Arm C: D = 44.4 s. 44.4 / 6 = 7.4, plus 0.6 is 8.0 s. The simulated medians for in flight and utilisation are 7.20 to 7.73 s: the formula runs 3% to 11% high, since a p99 sits below the maximum.
5. Arm A: D = 86.1 s. 86.1 / 6 = 14.3, plus 0.6 is 14.9 s, against 14.44 to 15.52 s simulated for all three signals.
6. Queue depth's second episode on arm C lasts 69 s (95 s to about 164 s): 69 / 6 + 0.6 = 12.1 s, against 11.15 to 12.03 s simulated.
7. To remove it you need N × μ ≥ λ before the spike: 2 replicas here. No signal can buy that after the spike starts.

KEY answer: About 8.0 s on arm C and 14.9 s on arm A, whatever the signal: W_max ≈ D(1 − 1/ρ) + 0.6. A shorter cold start nearly halves it; only warm headroom, N × μ ≥ λ, removes it.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 12

Q: At the 0.70× baseline of 147.8 req/s, about how many requests are in flight on one replica, and how do you know without running anything?
KEY: About 66. Little's Law: in flight = rate × latency, roughly 147.8 req/s × 0.44 s. The measured curve completes only 139.5 req/s at 64 in flight, so the baseline sits just above 64. A 2 to 16 in-flight grid is therefore crossed by 45.5 req/s (about a fifth of capacity) and fires at baseline.
RED FLAG: "About 16, the top of the grid", or a guess from GPU memory.

### Drill 2 of 12

Q: Why does nvidia-smi utilisation read 1.0 with a single request in flight?
KEY: As NVIDIA defines the counter (check the docs for your driver), it is the share of the sample period in which any kernel was running, not how much of the GPU the kernels use. One request's decode steps keep a kernel running almost continuously (my explanation, not separately measured), so it reads 1.0 from 3.5 req/s, 1.7% of 204.4. Whether a graded counter such as SM activity helps here was not measured.
RED FLAG: "One request really uses the whole GPU", or "it is a sampling bug".

### Drill 3 of 12

Q: What does queue depth read at 90% load on this engine, and what does that do to a scale-down threshold of 0 or 1?
KEY: About zero in the fluid picture: requests wait only once all 128 slots are running, so a queue appears past 204.4 req/s (bursty arrivals queue a little earlier). A down threshold of 0 to 1 therefore fires whenever capacity is merely enough, and removes the replica that made it enough. That is the simulated thrash in the walkthrough.
RED FLAG: "Queue depth is proportional to load."

### Drill 4 of 12

Q: Why can a per-serving-replica signal not fall while a new replica is starting, and why does that cost money?
KEY: The signal divides by serving replicas. A starting replica is billed from launch but not counted, so per-replica load stays high and the controller adds one more per cooldown until enough have arrived to pull the signal under its threshold. That is why utilisation, always 1.0, climbs to the 12-replica cap.
RED FLAG: "Starting replicas add capacity at once, so it settles quickly."

### Drill 5 of 12

Q: All 19 queue-depth policies cost 640 replica-seconds on arm C. Why?
KEY: The queue reads 0 or hundreds (196 to 2,546 in the replayed run, otherwise 0), so nearly every up threshold from 1 to 16 and down threshold from 0 to 1 makes the same moves: UP at 5 and 35 s, DOWN at 65 and 95, UP at 125 and 155, DOWN at 185 and 215. 410 of 570 replayed runs make exactly those eight; the rest add a launch. Cost is launch-time arithmetic: 400 + 240 = 640.
RED FLAG: "The thresholds were well chosen", or "the simulator is broken".

### Drill 6 of 12

Q: Estimate in-flight's and utilisation's step p99 on arm C without the simulator.
KEY: The first extra replica serves at D = 5 s + 39.4 s = 44.4 s. At 1.2× overload the worst wait is about D(1 − 1/1.2) + 0.6 = 8.0 s; the simulated medians are 7.20 to 7.73 s, since a p99 sits below the maximum. Arm A: D = 86.1 s gives 14.9 s against 14.44 to 15.52 s. The dead time sets it, not the signal.
RED FLAG: "The p99 comes from the service curve, about 0.6 s."

### Drill 7 of 12

Q: On the step, the simulated gap grew from arm A to arm C, against H3. Explain it without saying faster cold starts make the signal matter more.
KEY: On arm C the first new replica serves at about 44 s and the backlog clears, so queue depth scales down twice with the spike still on and pays a second cold start: a 69 s single-replica overload, p99 about 12 s. On arm A the replayed run has two or more replicas serving by its first scale-down, and all three signals sit between 14.44 and 15.52 s (gap 0.082 s). A rerun with scale-down off came close to the others (exploratory, not committed).
RED FLAG: "A faster cold start makes the signal matter more", stated as a finding.

### Drill 8 of 12

Q: Would Kubernetes' HPA have produced this thrash?
KEY: I did not test it. A proportional autoscaler computes a desired count from the signal and typically has separate scale-up and scale-down timing, with a long scale-down window by default (check your version). This simulator removes one replica per action under one shared 30 s cooldown, a modelling choice, so its frontiers describe this controller, not any real autoscaler.
RED FLAG: "HPA has a cooldown too, so it is the same."

### Drill 9 of 12

Q: Why does the gate judge the arrivals the engine received rather than the send schedule, and what did that cost?
KEY: RunPod's load balancer held requests and released them in bursts, so judged by send time its stalls would count as simulator misses. The cost: the prediction can no longer be written before the run, and the bursts, up to 512 requests at the engine with at most 128 running, become model input in a regime the curve never measured.
RED FLAG: "To make the model pass."

### Drill 10 of 12

Q: Attempt one missed by 14% in the median but by up to 89% in some bins. Reconcile the two.
KEY: Near saturation, waiting time depends on arrival rate minus capacity, a small difference of two large numbers. The replay peaked at 0.98× of measured throughput and the load balancer's bursts pushed the engine past its 128 cap, so a modest speed difference can turn a backlog the simulator predicts into none. Consistent with the data, not isolated: the quiet bins missed by 14%, which host speed explains only in part.
RED FLAG: "The −89% bins are outliers", or "host speed explains everything".

### Drill 11 of 12

Q: Is the miss rule fair to a perfect model? Quantify it.
KEY: Per bin, three unbiased repeats land on one side with probability 2 × (1/2)³ = 1/4, the same as the prediction falling outside the three runs' min–max. The pass rule needs 10 judged bins and at most half missing. For independent bins a perfect model fails about 2% at 10 bins and under 0.1% at 30; a model outside the spread in 3 bins of 4 fails 92% and 99.7%. Correlated bins and host effects raise the false fail to about 2.5% and near 5% (the pre-registration's simulation).
RED FLAG: "A good model should hit every bin."

### Drill 12 of 12

Q: What would you measure to answer the original question for real?
KEY: A closed-loop run on real replicas with a real autoscaler replaying recorded spikes; the load balancer's scaler value set to the engine's cap and its routing measured; host speed recorded per replica; validation in the overload regime the sweep uses; an asymmetric scale-down; and p99 with replica-seconds over many spikes. The simulator then drops out of the claim.
RED FLAG: "Run the simulator with more repetitions."

## Design scenario

Prompt: You run Qwen3-8B on vLLM on Kubernetes, on RTX 4090-class nodes. A new pod takes 40 to 80 s to start serving. Traffic is diurnal with unannounced bursts of up to 30% that last a few minutes. The SLO is p99 under 3 s at minimum cost. Design the autoscaling: what you scale on, how you set it, how you know it works.

KEY outline:

1. Measure one replica first: a concurrency sweep for latency, throughput and the memory ceiling, on your own request shapes. The toy shape here (13-token prompts, 16 output tokens) gives 204.4 req/s per replica; yours will differ a lot.
2. Size headroom from the dead time, not from the signal. A burst of ρ times a fleet's capacity builds a backlog for about the cold start D, with worst wait about D(1 − 1/ρ), if one new replica restores capacity (else add a cooldown per extra launch).
3. For ρ = 1.3 that is 0.23 D, about 15 s at D = 65 s, far over a 3 s SLO. So keep warm capacity of at least 1.3× typical load, or cut D (weights on fast storage, compile caches).
4. Scale up on requests in flight per replica, with a target taken from your own curve at the concurrency whose latency still meets the SLO with room for a burst. Never on nvidia-smi utilisation: it read 1.0 from one request.
5. Use waiting requests only as a fast overload trigger. It reads 0 until a replica is full, so it cannot ask for capacity early, and it must not drive scale-down.
6. Scale down slowly and asymmetrically: a window longer than a burst plus a cold start, never on an empty queue alone. This simulator removed the newest replica first, even one still starting, and paid a second cold start.
7. Mechanics: your platform's autoscaler fed by the engine's running and waiting request counts (check metric names and defaults for your versions); minimum replicas from the headroom rule; check the load balancer's per-worker cap and routing (RunPod's default capped two workers at 17.1 req/s).
8. Validate closed loop: replay recorded bursts against a staging fleet with the real autoscaler and record p99, replica-seconds, scale events and the host of each pod. Trust an offline simulator only after it passes a pre-registered gate, in the overload regime too.

KEY pitfalls:

- Quoting a simulated gap or signal ranking as a finding: the simulator failed its gate twice.
- Scaling on nvidia-smi utilisation, which read 1.0 from one request.
- Symmetric scale-down on an empty queue: the simulated queue-depth policy gave capacity back mid-spike and paid a second cold start.
- Sizing from one host's curve: the other hosts measured ran 7 to 18% faster than the curve's host under load.
- Copying the toy numbers (204.4 req/s, 13-token prompts) into production sizing.

## Lab

Cost: runs on your machine
Goal: See the control loop act, derive its costs from launch times, and test whether queue depth's simulated disadvantage on arm C comes from its scale-down.
Note: CPU only, under a second per spike on a laptop: no GPU, no paid API call, no network.

Setup:

- The repo on branch study-pilot. Run Python as .venv/bin/python, never uv run, which re-syncs .venv.
- Committed inputs only: data/a2/service-curve.json and data/campaign.jsonl.
- Write a script outside the repo (repo root on sys.path) that loads the measured curve with autoscale.measured_curve.select_curve, artifact 1's lags with autoscale.coldstart_ecdf.load_measured_lags, and the step spike with autoscale.traffic.spike_shape.
- It builds arrivals with autoscale.arrivals.arrival_times and the sweep's seed, random.Random(autoscale.sweep._derive_seed(17, up, down, 0)), over 400 s.
- It calls autoscale.sim.run_with_policy with Controller(up, down, 30.0, 12), evaluate_every 5.0 and lags['C'] (or 'A'), and wraps Controller.decide to log time, signal value and decision.

Steps:

1. Trace utilisation (up 0.9, down 0.05), in flight (up 16, down 4) and queue depth (up 4, down 1) on arm C, repetition 0. Write down each action and the signal that caused it.
2. Before reading the results, predict each run's replica_seconds from launch times (estimation problem 1).
3. Predict each run's p99 with the fluid formula (estimation problem 2), then compare.
4. Re-run queue depth on arm A. Explain why no mid-spike scale-down happens there.
5. Re-run queue depth on arm C for six repetitions with scale-down unreachable (down threshold −0.5, which a non-negative queue never reaches). Note cost and p99.
6. Stretch: change the cooldown to 10 s and to 60 s, still symmetric. Predict, then observe, the effect on queue depth's thrash and on utilisation's cost (with a 10 s cooldown its 11th launch is at 105 s).

Record:

- replica_seconds of each run
- percentiles()['p99'] of each run
- UP and DOWN actions: time, signal value, replicas
- Predicted against simulated cost and p99

KEY expected result: Repetition 0 on arm C, replayed from committed code and seeds: utilisation 3,095 replica-seconds with p99 8.2 s; in flight (up 16, down 4) 2,320 with 7.99 s; queue depth (up 4, down 1) 640 with 11.73 s. On arm A queue depth costs 880 with p99 14.8 s and its first scale-down comes after more than one replica serves. With scale-down off, expect a higher cost and a p99 close to the other signals' (the unit's exploratory rerun, not committed).
KEY what it shows: Cost is launch-time arithmetic; p99 is set by dead time; queue depth's simulated disadvantage on arm C is tied to its scale-down rule; and the simulator models this controller, not any real autoscaler.

## Calculator

Spike survival: worst wait from the dead time Fluid FIFO queue; assumes one launch restores capacity. 253.4 req/s is the sweep's spike, 211.2 req/s is 128 / 0.606 s, 0.606 s and 39.37 s are measured; the 5 s check and one warm replica are settings. Defaults give about 8.0 s; set the cold start to 81.07 s for about 14.9 s.

Inputs (default, range):

- Arrival rate in the spike: 253.4 req/s (range 50 to 600)
- One replica completes: 211.2 req/s (range 100 to 400)
- Service time at saturation: 0.606 s (range 0.2 to 1.5)
- Cold start: 39.37 s (range 10 to 150)
- First check after the spike: 5 s (range 1 to 30)
- Warm replicas at spike start: 1 (range 1 to 6)

Outputs at the defaults:

- First relief arrives at = 44.4 s  [ev + cold]
- Overload ratio = 1.20  [lam / (n0 * mu)]
- Worst wait = 8.0 s  [max(0, (ev + cold) * (1 - n0 * mu / lam)) + svc]
- Replicas that remove the overload = 2  [ceil(lam / mu)]
- Launches beyond the first needed = 0  [max(0, ceil(lam / mu) - n0 - 1)]

## Recall cards

- [littles-law] One replica: 128 in flight, 0.606 s each. Saturation? -> KEY: 128 / 0.606 = 211.2 req/s, the simulator's capacity. Measured completions at 128 in flight: 204.4 req/s.
- [littles-law] In flight per replica at the 147.8 req/s baseline? -> KEY: About 66: Little's Law on the measured curve. 64 in flight delivers 139.5 req/s, so the baseline sits just above 64.
- [batching] Latency and throughput from 1 to 128 in flight? -> KEY: Latency about 2.1× (0.284 to 0.606 s); throughput about 58× (3.5 to 204.4 req/s).
- [signals] What does nvidia-smi utilisation read here, and from where? -> KEY: 1.0 from one request in flight (1.7% of 204.4 req/s), 0 only when idle: every utilisation threshold (0.50 to 0.95) is crossed at once.
- [signals] Queue depth at 90% load on one replica? -> KEY: About 0 in the fluid picture: requests wait only once 128 are running. Bursty arrivals can queue a little earlier.
- [signals] Which signal is graded across the range, and what was wrong with its grid? -> KEY: In flight. Its 2 to 16 grid is crossed by 45.5 req/s while the baseline sits near 66.
- [control-loop] The simulated controller in one line? -> KEY: Checks every 5 s; one replica per action; one 30 s cooldown for both directions; 1 to 12 replicas; the newest replica is removed first; starting replicas are not counted in the signal.
- [control-loop] Why can a signal not fall during a cold start? -> KEY: It divides by serving replicas. A starting replica is billed but not counted, so per-replica load stays high.
- [cost] Derive utilisation's 3,095 replica-seconds. -> KEY: 400 for replica 1, plus 11 launches at 5, 35, ..., 305 s: 400 + 11 × 395 − 30 × 55 = 3,095.
- [cost] Why did every queue-depth policy cost 640 on arm C? -> KEY: Its queue reads 0 or hundreds, so thresholds barely matter: UP 5, UP 35, DOWN 65, DOWN 95, UP 125, UP 155, DOWN 185, DOWN 215 (one replayed policy).
- [dead-time] Worst wait in a step overload ρ with first relief at D? -> KEY: About D(1 − 1/ρ) plus the service time. For ρ = 1.2 and D = 44.4 s: about 8.0 s.
- [dead-time] Simulated step p99, arm C against arm A (in flight, utilisation)? -> KEY: About 7.20 to 7.73 s against 14.44 to 15.52 s: roughly a sixth of (5 s plus the cold start), plus 0.6 s.
- [thrash] What produced the simulated 3.96 s gap on arm C? -> KEY: Queue depth spends 640 against 2,320 to 3,095, and its scale-down on an empty queue mid-spike forces a second cold start. A rerun with scale-down off came close (exploratory, not committed).
- [bridge] How does this controller differ from a proportional autoscaler? -> KEY: It adds or removes exactly one replica per action under one cooldown for both directions; a proportional one computes a desired count and often times scale-down separately (check your autoscaler's defaults). The frontiers describe this controller only.
- [gate] The miss rule, and a perfect model's chance of a miss per bin? -> KEY: A bin misses when all three repeats sit on one side of the prediction (outside their min–max) by more than 1 ms: at most 2 × (1/2)³ = 1/4.
- [gate] The pass rule, and the false-fail rate at 10 independent bins? -> KEY: At least 10 judged bins, at most half missing: about 2% (2.5% with queue correlation, near 5% with host effects, simulated).
- [gate] Results of attempts one and two? -> KEY: 34 of 37 bins missed, the engine 14% faster than predicted; calibrated, 37 of 37 missed, the engine 13% slower.
- [near-saturation] Why can a modest host difference show as −89% in some bins? -> KEY: Near saturation, waiting depends on arrival rate minus capacity. The replay ran at 0.98× of measured throughput with bursts above it. Consistent with the data, not isolated.
- [runpod] RunPod's load balancer at its default scaler value 4 (2026-10-05)? -> KEY: It capped each worker near 4 in flight: 17.1 req/s delivered by two workers, $36.02 against $2.05 per million requests, 18× dearer.
- [limits] Three things you must not claim. -> KEY: Any signal ranking (unvalidated simulator); behaviour in overload (gate at 0.95×, sweep at 1.20×); that RunPod's load balancer still behaves this way (probes of 2026-10-05).
- [capacity] Replicas for 1,000 req/s at 204.4 per replica? -> KEY: 1,000 / 204.4 = 4.9, so 5 with no headroom; 6.8, so 7, at the 147.8 req/s baseline; plus warm capacity for the cold start.
- [draw-it] [draw] Draw the autoscaling loop with its dead time; shade what was measured. -> KEY: Traffic, serving replicas, signal, controller, cold start, back to the replicas. Shade the latency curve and the cold starts; hang the gate off the replicas box.
- [draw-it] [draw] Sketch the three signals against load, 0 to 253.4 req/s, with their grids. -> KEY: Utilisation: 1.0 from the first point. In flight: 1 to 128, grid 2 to 16 at the bottom. Queue: 0 until 204.4, then rising.
- [draw-it] [draw] Draw the queue-depth thrash on arm C as a timeline. -> KEY: UP at 5 and 35 s; replica 2 serves at 44 s; DOWN at 65 and 95 s on an empty queue; the backlog rebuilds; UP at 125 and 155; the first serves near 164 s; DOWN at 185 and 215.

## Review schedule

- Day 1, after the study: Draw the loop and the three-signal chart from memory, give the 2-minute explanation aloud, and do estimation problem 1 for utilisation.
- Day 3: Cards 1 to 12, estimation problem 2 for arm A (14.9 s, within 10%), drills 1 to 6.
- Day 7: Cards 13 to 24, drills 7 to 12, lab steps 1 to 5. Say why the arm C gap is tied to scale-down and why a proportional autoscaler would differ.
- Day 21: The design scenario aloud in ten minutes, then the 30-second pitch with no overclaim and the limits stated unprompted.

## Assumed numbers

Not from the study page's sources:

- 1.3: The scenario's burst size, +30% over typical load: an assumption chosen for the exercise, not a measurement.
- 65: A cold start of about 60 s plus the 5 s check, for the scenario: an assumption inside the 40 to 80 s range given in the prompt.
- 0.23: 1 − 1/1.3 = 0.2308, worked from the assumed burst size.
- 15: 0.23 × 65 = 14.95 s, worked from the two assumed numbers above.
- 0.44: worked out, Latency between 0.439 s at 64 in flight and 0.606 s at 128 (data/a2/service-curve.json), interpolated near 66 in flight: about 0.443 s.
- 8.0: worked out, 44.4 x (1 - 1/1.2) + 0.6 = 7.4 + 0.6 = 8.0 s; with D = 44.37 and rho = 1.1998 it is 7.995 s.
- 14.3: worked out, 86.1 / 6 = 14.35 s.
- 7.4: worked out, 44.4 / 6 = 7.4 s.
- 12.1: worked out, 69 / 6 + 0.6 = 11.5 + 0.6 = 12.1 s.
- 105: worked out, A 10 s cooldown from the first evaluation: 5 + 10 x 10 = 105 s.
- 8.2: worked out, Read-only replay of autoscale.sim.run_with_policy for utilization (up 0.9, down 0.05), arm C step, repetition 0, seed autoscale.sweep._derive_seed(17, 0.9, 0.05, 0): p99 8.2 s, cost 3,095. A replay, not a measurement.
- 7.99: worked out, Same replay for in_flight_concurrency (up 16, down 4): p99 7.987 s, cost 2,320.
- 14.8: worked out, Same replay for queue_depth (up 4, down 1) on arm A: p99 14.799 s, cost 880.
- 1,920: worked out, 395 + 365 + 335 + 305 + 275 + 245 = 1,920.
- 86.1: worked out, 5 + 81.07 = 86.07 s: the first evaluation plus arm A's median cold start.
- 14.9: worked out, 86.07 x (1 - 1/1.2) + 0.606 = 14.33 + 0.61 = 14.94 s (with the sweep's rho 253.4 / 211.2 = 1.1998 the result is the same to one decimal).
- 305: worked out, The 11th launch of a fleet that scales up at every chance: 5 + 10 x 30 = 305 s.
- 365: worked out, 400 - 35: the billed seconds of a launch at 35 s.
- 275: worked out, 400 - 125: the billed seconds of a launch at 125 s.
- 245: worked out, 400 - 155: the billed seconds of a launch at 155 s.
- 12.03: worked out, data/a2/frontier-sweep.json sources['arm C'], queue_depth up 2 down 0: the median of its 30 p99 samples, 12.03 s, the highest of the 19 queue-depth medians (lowest 11.15).
- 4,345: worked out, 11 x 395.
- 1,650: worked out, 30 x (0 + 1 + ... + 10) = 30 x 55.
- 2,695: worked out, 4,345 - 1,650.

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
