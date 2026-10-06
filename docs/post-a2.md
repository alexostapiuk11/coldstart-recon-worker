<!--
Permanent slug: /experiments/autoscaling-signal-and-cold-start
Never changes, per the portfolio contract. It names the question the experiment
asked rather than the headline it ended with, so the title can be reworded at
publication without breaking the URL.

The byline date is the publication date. PUBLICATION-DATE is a placeholder: the
pre-publish check, `scripts/a2_prepublish_check.py`, refuses it and the owner sets
the date there. The SPEND-PENDING line under "What it costs" is refused by the
same check until the RunPod console has been read, as is an analysis whose
`spend` is still null.
-->

# An autoscaling simulator that failed its own test

**Oleksii Ostapiuk** · PUBLICATION-DATE · `/experiments/autoscaling-signal-and-cold-start`

I set out to measure which autoscaling signal suits an LLM server whose replicas
take tens of seconds to over a minute to start. The simulator built to answer it
failed its pre-registered validation twice, so the answer is not here. What is here:
the two failures with every miss, a measured difference in speed between rented GPU
hosts of the same model, four things RunPod's load balancer did in my probes, one
missing field in its REST API, and, labelled as unvalidated, what the simulator
would have said.

Harness, raw data, analysis and figure code:
[github.com/alexostapiuk11/coldstart-recon-worker](https://github.com/alexostapiuk11/coldstart-recon-worker)

---

## The question

An autoscaler adds a replica when some signal crosses a threshold. For an LLM
server the usual candidates are queue depth (requests waiting per replica),
in-flight concurrency (requests being served per replica) and GPU utilisation. The
question was which of the three gives the best tradeoff between cost and p99
latency during a traffic spike, and whether the answer depends on how long a new
replica takes to start. Artifact 1 measured cold starts of the same stack under
three cache setups; this uses two. Arm A, nothing cached (weights from the hub, a
cold compile cache), has a median of 81.07 s; arm C, weights on a network volume
plus a warm compile cache, 39.37 s. Both exclude artifact 1's one first-touch run,
an image pull on a new host, as the simulator does. The headline hypothesis, H3,
was that the gap between the best and the worst signal at equal cost at least
halves from arm A to arm C, on both a step spike and a ramp.

**The answer: not answered by measurement.** The comparison needs dozens of
policies run thirty times each through real spikes, so it was to be made in a
simulator, and the simulator was to be trusted only after it reproduced a real
replica's latency under a pre-registered test. It failed that test twice. The
pre-registration says what happens then: the gate's failure is published instead
of the frontiers. This post does that.

---

## What was measured and what was simulated

| | measured on RunPod | simulated |
|---|---|---|
| Cold start | artifact 1's runs: 99 for arm A and 100 for arm C, of its 300 cold starts (`data/campaign.jsonl`) | resampled from those runs |
| Service | one replica of vLLM serving `Qwen/Qwen3-8B` on an RTX 4090: latency, throughput and nvidia-smi GPU utilisation at concurrency 1 to 128, three runs per level | the measured curve, interpolated |
| Fleet | one replica pinned, in the validation runs | up to 12 replicas, added and removed by a policy every 5 s with a 30 s cooldown |
| Traffic | one fixed arrival schedule, replayed open-loop by a driver on my laptop | a step or ramp spike peaking at 1.20× one replica's measured capacity |
| Policies | none | each signal over its own pre-registered threshold grid, 30 repetitions per policy |
| Hosts | speed measured on three RunPod hosts | one host's speed, the curve's |
| Load balancer | five probes of RunPod's load-balancing endpoint | not modelled; load is split evenly |

The simulator fits nothing. Arrivals go in, the measured curve and the measured
cold-start lags turn them into latencies, and a policy's cost is the
replica-seconds it paid for, including replicas still starting when the spike
ended.

---

## The test the simulator had to pass

The pass rule was committed on 2026-10-03, before any real validation run existed,
because a test written after seeing the runs can be bent to fit them. Its core:

- **Three real repeats of one fixed schedule** at pinned capacity. Their spread is
  the tolerance: a model cannot be required to be more reproducible than the system
  it models. Exactly three, because a min–max range only widens as runs are added.
- **Latency p50 per 10 s bin**, judged on server-side latency, the engine's own
  receive-to-response time, which is what the simulator models.
- **A bin misses** when all three repeats land on the same side of their own
  predictions by more than 1 ms (as amended 2026-10-05). A perfect model misses a
  bin with probability 1/4, which is why the rule tolerates misses rather than
  demanding every bin.
- **Pass:** at least 10 judged bins, and no more than half of them missing.
- **A miss's size** is the residual closest to zero among the three repeats: how
  far the repeat nearest its own prediction sits from it. The raw residual of any
  one repeat can be much larger.
- **Two attempts at most.** The design allows one disclosed fix and one
  re-validation after a failure. The amendment that made the fix declared it the
  second and last attempt: if it also failed, the gate's failure would be published
  instead of the frontiers.

Before any verdict, the gate was amended three times on 2026-10-05, each time
because of the load balancer (below): a load-balancer 502 is retried once; the gate
validates one replica instead of two; and each repeat is predicted from the arrival
times the engine actually received rather than the times the driver sent. The last
change means the prediction can no longer be written down before the run. The
prediction for the schedule as sent stays on record in the amendment of 2026-10-05
(second). A fourth amendment that day, after attempt one failed, added the
calibration (below).

**What this gate does not check, even had it passed.** The validation schedule
peaks at 0.95× one replica's capacity; the policy sweep's spike peaks at 1.20×, so
sustained overload like the sweep's, which queue depth reads, was never scheduled.
The load balancer's bursts did push the engine past its `--max-num-seqs` of 128
running requests: reconstructed from each request's engine arrival and server latency,
33%–59% of attempt one's arrivals and 6%–17% of attempt two's took the engine above
128 requests in flight, to as many as 512 in attempt one and 452–503 in attempt two.
That peak, 512, is the endpoint's scaler value, which fits the per-worker cap
described under the load balancer (below). In those stretches the simulator's backlog was off by seconds.
With one replica, the even split of load across replicas is untested; RunPod's load
balancer does not split evenly. And no real autoscaling ran at all (see Limits).

---

## Attempt one: the engine was faster than the curve

![Two panels of residuals, real minus predicted p50 per 10 s bin against engine arrival time. Left, attempt 1: three repeats' lines sit below zero, dipping to several seconds below between about 50 and 200 s. Right, attempt 2: three lines sit just above zero throughout, with a few spikes higher.](figures/a2/attempts.png)

Each line is one repeat's residual per bin. Look at which side of zero the lines
sit: below it in attempt one, above it in attempt two, in almost every bin. The
y axis is logarithmic past ±0.01 s.

The first attempt, judged on the engine's arrival times with the committed curve as
measured, **failed: 34 of 37 judged bins** missed, all on the same side. Across the
judged bins the engine's median latency was **14%** below the simulator's
prediction. The largest miss, measured as the residual closest to zero among the
three repeats, was **2.59 s**. In the bins after the load balancer released held
requests in a burst, the simulator predicted a backlog seconds longer than the
engine's own: raw residuals reached -6.20 s. As the rules allow, one repeat was void
and was run again once: all 64,784 of its successful (HTTP 200) responses lacked a
usable engine-arrival stamp, which the gate judges on.

**The cause, found after the verdict (exploratory).** Two things separated the
validation runs from the curve: the host, and the engine's `--max-num-seqs`, 128 for
validation against 256 for the curve. I re-measured concurrency 32, 64 and 128 on
the curve's own endpoint and image, three runs per level with each setting. All
eighteen runs landed on host `daps3haubwrzbn`; the committed curve was measured on
host `ozhetwnhompob9`.

| concurrency | `--max-num-seqs` 128: latency ÷ the curve's | `--max-num-seqs` 256: latency ÷ the curve's |
|---:|---:|---:|
| 32 | 0.93 (7% lower) | 0.96 (4% lower) |
| 64 | 0.94 (6% lower) | 0.93 (7% lower) |
| 128 | 0.90 (10% lower) | 0.90 (10% lower) |

The setting does not matter: at each level the two columns agree within their own
run-to-run range. The host does, and its lead widens with load. Attempt one's
repeats ran on a third host, `ku80i8usxw3st5`, whose speed was not measured
closed-loop. Its own records give one reading: requests that arrived with 90 to 110
in flight on the engine took a median 0.494 s, against 0.487 s for `daps3haubwrzbn`
at `--max-num-seqs` 128 and 0.533 s for the curve, both interpolated to 100 in
flight. At that load it ran close to `daps3haubwrzbn`'s speed. The simulator models
one host's speed, and RunPod, not the user, decides which host a worker lands on.

![Server-side latency on two RunPod hosts as a ratio to the curve's host, at concurrency 32, 64 and 128. Every point sits below the line at 1.0. daps3haubwrzbn, measured with both engine settings, sits a little below it and lower at 128; sef5s24viyecyr's three calibrated repeats sit lower still at 64 and 128.](figures/a2/host_speed.png)

The horizontal line at 1.0 is the host the curve was measured on; every other host
measured sits below it, broadly further below as load rises. In all,
6 hosts appear in the curve, host re-measurement and validation records, and
3 of them were measured for speed. That is not a distribution of host speeds: it
shows only that hosts of the same GPU model differ by about as much as the gate's
misses.

---

## Attempt two: calibrated, and wrong the other way

The fix, signed before the second attempt ran: before each replay, the driver held
the pinned worker at 64 and then 128 requests outstanding, closed-loop, 60 s
measured at each, and divided the median server latency by the curve's at that
level. The repeat's prediction used the curve scaled by those two ratios. Two
numbers per repeat, measured on traffic the gate never judges; nothing fitted to
the validation trace. All three repeats landed on host `sef5s24viyecyr`, whose
latency, as a ratio to the curve's, measured **0.87 at 64** and
**0.82–0.84 at 128**.

The second and last attempt **failed: 37 of 37 judged bins** missed, this time all
the other way. The engine's latency was **13%** above the calibrated prediction.
The largest miss, measured the same way, was **0.060 s**: small in absolute terms,
but every bin, every repeat, on one side. In one bin a single repeat's raw residual
passed one second. This time no repeat was void.

Why the calibration over-corrected, the evidence does not settle. The two
measurements differ in how load arrived: the calibration kept a fixed number of
requests in flight (closed loop), while the replay sent requests on a schedule (open
loop), through the same load balancer that had released held requests in bursts in
earlier runs. That this difference is the cause is a hypothesis: it was not tested,
and it rests on one host and three repeats.

What the two attempts do show is that the error is about the size of the effect a
host can have. Uncalibrated, the simulator predicted latency too high; calibrated
on the worker it was about to judge, it predicted latency too low by about as much.
A deployment's frontier moves with the host it lands on, and the simulator knows
nothing of the host unless it is told.

Both verdicts, with every bin and every miss's magnitude, are committed:
[`data/a2/validation-engine/verdict.json`](https://github.com/alexostapiuk11/coldstart-recon-worker/blob/main/data/a2/validation-engine/verdict.json)
and
[`data/a2/validation-calibrated/verdict.json`](https://github.com/alexostapiuk11/coldstart-recon-worker/blob/main/data/a2/validation-calibrated/verdict.json).

---

## What RunPod's load balancer does

Measured on 2026-10-05 on RunPod's load-balancing endpoint type, on the endpoints
this project created, with two RTX 4090 workers (probes 1 to 3) or one (probes 4 and
5). These probes were run to find out whether the path could carry the validation
traffic, and the endpoint settings changed between them on purpose; none was
pre-registered. RunPod may change any of this.

![Left: delivered against offered request rate for two workers. At scaler value 4 the line is flat and low at every offered rate; at scaler value 128 it follows the delivered-equals-offered diagonal and bends below it only at the highest rates. Right: probe 3's mean and peak requests in flight per worker by offered rate; worker 1 alone serves the low rates, worker 2 takes load only once worker 1 nears the cap, and both reach the cap at the top rate.](figures/a2/load_balancer.png)

On the left, compare the flat red line with the blue one: the same endpoint type,
two workers each time, scaler value 4 against 128. They were different workers:
probes 1 to 3 ran on 6 workers in all, a new pair each time, and the driver changed
between probes 1 and 2. On the right, see worker 2 stay empty until worker 1 is near
its cap.

**1. The endpoint's scaler value caps the requests in flight per worker.** At
RunPod's default of 4, probe 1 offered 25, 50 and 100 req/s to two workers and the
path delivered 17.1 req/s, the median over its steps, whatever was offered. Every
reconstructed per-worker peak in flight was 4, except one reading of 5, which the
reconstruction can produce by overlapping two neighbouring requests. The engine was
not the bottleneck: its own latency stayed flat while the client's grew, so
requests were waiting inside the load balancer.

| offered (probe 1, scaler value 4) | client p50 | server p50 |
|---:|---:|---:|
| 25 req/s | 3.80 s | 0.311 s |
| 50 req/s | 21.74 s | 0.310 s |
| 100 req/s | 52.00 s | 0.311 s |

The 100 req/s step is incomplete: it had 449 client-side errors, and the driver
stopped when it could not start another thread. With the scaler value at 128, the
same path carried hundreds of requests per second. At 300 req/s offered, probe 2
delivered 277.7 req/s and probe 3 delivered 300.7 req/s; at 450 req/s offered they
delivered 348.1 req/s and 350.4 req/s. RunPod documents the scaler value only as an
autoscaling setting: the divisor in its request-count formula on the
[endpoint settings page](https://docs.runpod.io/serverless/endpoints/endpoint-configurations),
and, in the
[REST API reference](https://docs.runpod.io/api-reference/endpoints/POST/endpoints),
as either that divisor or a queue delay in seconds, default 4. Neither says the
load balancer also caps the requests in flight per worker at that value; these
probes found it (as of 2026-10-05). The validation endpoint's scaler value was 512,
and 512 is the most requests its engine ever held at once (above).

**2. It fills one worker to the cap before routing to the next.** Probe 3's share
of requests sent to worker 1, step by step
from 25 to 450 req/s: 100%, 100%, 100%, 99%, 70%, 51%. Only at 450 req/s
did both workers reach 128 in flight. The simulator splits load evenly, so a
two-replica gate would have compared an even split with fill-first routing and
missed because of the platform's routing, not the model. That is why the gate went
to one replica.

**3. It stalls.** With one worker, the load balancer held requests for seconds and
then released them together. In the three one-replica repeats run before the
engine-arrival amendment, the share of requests that took over 2 s client-side was
21%–35%. That total includes time inside the engine: a released burst leaves a
backlog there, and of the requests over 2 s, most also spent over 1.50 s in the
engine. The part spent outside the engine, client minus server latency over 2 s, is
the smaller share:

| repeat | over 2 s client-side | over 2 s outside the engine | of those over 2 s, over 1.50 s in the engine |
|---|---:|---:|---:|
| 1 | 26% | 16% | 75% |
| 2 | 35% | 19% | 90% |
| 3 | 21% | 10% | 77% |

None of the three carries a verdict; the range covers all three. Under the rules
then in force, repeat 1 was void: 2 requests got 400s, both from the load balancer
with no worker header;
repeats 2 and 3 were refused for send jitter (0.591 s and 0.806 s). The one-worker probes show the same thing as a shortfall that comes and
goes: probe 4 delivered 108.7 req/s at 150 offered and 114.3 req/s at 180, and probe
5 delivered 156.7 req/s at 180 offered but 210.7 req/s at 210. A fixed capacity
limit would not deliver more at a higher offered rate.

**4. It returns 502s that no worker answered.** Probe 2, which did not retry them,
had 13 such 502s, each failing after 0.124–0.284 s. From probe 3 on, the driver
retried a 502 that carried no worker header once, at once. Across probes 3 to 5,
37 first attempts failed this way, in two groups: 17 failed after 0.109–0.399 s,
and 20 failed after 2.50–14.09 s (median of all of them: 2.64 s). A 502 that slow may mean
the request reached a worker before it failed; if so, its retry was served twice.

**One gap in the REST API: its create call cannot make a load-balancing endpoint.**
It has no type field. These endpoints were made through GraphQL `saveEndpoint` with
`type: "LB"`, which RunPod's
[GraphQL reference](https://docs.runpod.io/sdks/graphql/manage-endpoints) documents
(as of 2026-10-05).

What the default costs in dollars is under "What it costs".

---

## What the unvalidated simulator says

**Everything in this section comes from a simulator that failed its validation
twice. It is the simulator's answer, not a measurement.** It is here because the
pre-registration asked a question and a reader may want to know what the model
would have answered, and because some of it, labelled below, does not depend on the
size of the error the gate found.

![Simulated gap between the best and worst signal at the iso-cost budget, arm A against arm C, at three engine speeds, with bootstrap interval bars. Step traffic: every line rises from near zero at arm A to well above it at arm C. Ramp traffic: the x1.00 and x1.12 lines rise, the x0.88 line falls slightly. A red marker at arm C shows half of arm A's x1.00 gap, which H3 needed arm C to reach. The banner reads SIMULATED, FAILED VALIDATION.](figures/a2/simulator_answer.png)

H3 needed each line to fall to half its arm A value or below. On the step every
line rises instead; on the ramp, two rise and the x0.88 line falls slightly. The
x0.88 and x1.12 lines are exploratory and were not pre-registered.

**H3 fails.** The gap between the best and worst signal at the iso-cost budget, from
paired repetitions, x1.00 with its 95% bootstrap interval:

| engine speed | H3 | step, arm A | step, arm C | ramp, arm A | ramp, arm C |
|---|---|---:|---:|---:|---:|
| x0.88 | fails | 0.138 s | 1.38 s | 3.83 s | 3.42 s |
| x1.00 | fails | 0.082 s [0.050–1.06 s] | 3.96 s [3.52–4.56 s] | 8.25 s [7.89–8.60 s] | 10.87 s [10.62–11.05 s] |
| x1.12 | fails | 0.173 s | 1.26 s | 8.71 s | 16.71 s |

The x1.00 row is the committed curve. The x0.88 and x1.12 rows are an exploratory
check run after both validation attempts had failed: every engine latency scaled by
0.88 or 1.12, about the size of the error the gate found in each direction, with the
traffic held fixed. H3's condition fails at all three speeds and on both shapes. On
the step, the gap grows from arm A to arm C at all three speeds, so that direction
does not depend on the calibration error, though its size does. On the ramp, the
direction depends on the engine's speed: the gap grows at x1.00 and x1.12 and
shrinks at x0.88. In the simulator, a faster cold start makes the signal choice
matter more on a step.

**Two things a reader must know before reading any ranking from this.**

**(a) The iso-cost slice does not constrain queue depth or in-flight concurrency.**
The pre-registered budget is the cheapest spend at which every signal has a policy.
Here that is 3,095 replica-seconds, which is utilisation's floor: every utilisation
policy scaled to the replica cap (see the service curve below), so its cheapest
point is the cap. The most expensive frontier point of the other two signals is
2,535 replica-seconds (step, arm A), 2,320 replica-seconds (step, arm C),
2,875 replica-seconds (ramp, arm A) and 2,448 replica-seconds (ramp, arm C), all
under the budget. In no sweep does the slice constrain either of them, so the "gap
at iso-cost" is in fact the spread between each signal's best p99 at any cost.

What each signal reached at the budget, and what it spent:

| sweep | queue depth | in-flight concurrency | GPU utilisation |
|---|---|---|---|
| step, arm A | 14.44 s at 880 replica-seconds | 14.48 s at 2,535 replica-seconds | 14.53 s at 3,095 replica-seconds |
| step, arm C | 11.15 s at 640 replica-seconds | 7.22 s at 2,320 replica-seconds | 7.20 s at 3,095 replica-seconds |
| ramp, arm A | 10.53 s at 895 replica-seconds | 2.30 s at 2,875 replica-seconds | 2.28 s at 3,095 replica-seconds |
| ramp, arm C | 11.43 s at 670 replica-seconds | 0.555 s at 2,448 replica-seconds | 0.554 s at 3,095 replica-seconds |

**(b) This data cannot rank in-flight concurrency against utilisation.** All of
utilisation's policies run the same scale-up schedule at the same cost, yet their
p99s spread widely, because each policy's thresholds seed different arrival traces
and cold-start draws. That spread is a noise floor for any comparison at the cap,
and the margins between utilisation and in-flight sit far inside it (on arm A's
step, in-flight is the worse of the other two signals; in the other three sweeps it
is the better):

| sweep | H2 here | utilisation minus the worse other signal | utilisation minus the better other signal | utilisation's 19 at-cap policies: p99 range (median) |
|---|---|---:|---:|---|
| step, arm A | holds | +43 ms | +82 ms | 14.53–15.52 s (14.73 s) |
| step, arm C | fails | -3,955 ms | -22 ms | 7.20–7.73 s (7.49 s) |
| ramp, arm A | fails | -8,249 ms | -26 ms | 2.28–3.07 s (2.46 s) |
| ramp, arm C | fails | -10,873 ms | -1 ms | 0.554–0.568 s (0.559 s) |

In the one sweep where H2 holds, it holds by +43 ms, inside a spread of about a
second. In the other three it fails by seconds: queue depth's p99 there is worse by
several times that spread, and the gap's bootstrap intervals exclude zero. Queue depth also costs far less: 640–895 replica-seconds
against 2,320–3,095 replica-seconds for the other two.

**H1, H2 and H4 all fail, as defined.** Their operational definitions were written
after the x1.00 frontiers had been seen, and signed by the owner before any verdict
was computed (the analysis note in the pre-registration). They are an analyst's
choices, made with the curves in view; none was pre-registered:

- **H1**, in-flight concurrency dominates on the step (every queue-depth and
  utilisation frontier point weakly dominated by an in-flight point, on both
  arms): H1 fails on both arms.
- **H2**, utilisation is the worst (highest p99 at the budget by more than 1 ms, on
  both arms and both shapes): H2 fails. The pre-registration required a sensitivity
  arm, with utilisation read from throughput instead of nvidia-smi;
  on the sensitivity arm it fails too, so it does not reverse the verdict.
- **H4**, the ranking is stable across shapes and margins shrink on the ramp:
  H4 fails on both counts. On arm A the ranking differs between step and ramp, though
  on arm A's step all three sit within 82 ms, inside the noise above; on arm C it is
  the same on both shapes. The margin condition fails clearly: the ramp's gap is
  larger than the step's on both arms.

The dollar version of the signal choice is under "What it costs", with the same
label.

---

## The service curve

![Three panels against concurrency per replica, from 1 to 128: latency rising gently, throughput rising and bending, and GPU utilisation flat at 1.0 from one request upward, with an open point at 0 for the idle reading. A shaded band covers almost the whole x range in all three panels.](figures/a2/service_curve.png)

The shading marks where nvidia-smi's utilisation reads at or above 0.95, the highest
scale-up threshold in the grid. It starts just below one request in flight, where
the line from the measured idle point at 0 crosses 0.95, and covers every measured
level after that.

This part is measured. On this engine, model and
GPU, nvidia-smi's GPU utilisation reads 1.0 at every measured concurrency from one
request upward. That is above every utilisation scale-up threshold in the
pre-registered grid, the highest of which is 0.95. An autoscaler driven by it sees
a fully busy GPU the moment a replica serves anything, so it scales up at every
chance until it hits its cap: in the simulator, 19 of 19 utilisation policies ran
at the cap in every sweep. Here utilisation says whether a replica is serving, not
how loaded it is.

An idle replica reads 0%, which was measured with the engine idle, outside the
curve's measured span. Concurrency 256 could not be served at all: the engine died
of CUDA out of memory at its first step in every run at that level, so the curve
stops at 128.

---

## What it costs

Converted through assumptions published so you can substitute your own.

| assumption | value | provenance |
|---|---:|---|
| GPU hourly rate, one RTX 4090 worker | $0.74/h | **reported** (RunPod API): the `costPerHr` field of a RunPod worker record, read on 2026-10-05 |
| spikes | 24 per day | **illustrative**: one an hour |

The rate is what RunPod's API reported for that worker, not an invoice. RunPod's
[pricing page](https://www.runpod.io/pricing), read on 2026-10-05, lists $1.10/h for
a serverless 24 GB 4090 PRO worker; $0.74/h is the price the same page gives for an
on-demand RTX 4090 Pod. The dollar figures below are at $0.74/h; at the list price
every one of them is 1.5× higher. Every dollar figure scales linearly with the rate.

**The load balancer's default cap, measured.** Two workers at scaler value 4
delivered 17.1 req/s: **$24.04** per million requests. Two workers at scaler value
128 (a different pair, in probe 3) delivered 300.7 req/s at the 300 req/s step:
**$1.37** per million, 18× less. The throughput is measured; probe 1's last step
was cut short by the driver, and the 128 figure is one step of one probe, not that
endpoint's maximum.
If you run a RunPod load-balancing endpoint, check this setting first.

**The signal choice, from the simulator.**

> UNVALIDATED: simulator failed validation twice; p99s differ by 82 ms

On arm A's step, the three signals' reached p99s are within 82 ms of each other,
inside utilisation's own spread, so at roughly equal p99:

| signal | replica-seconds per spike | per spike at $0.74/h | per day |
|---|---:|---:|---:|
| queue depth | 880 replica-seconds | $0.18 | $4.34 |
| in-flight concurrency | 2,535 replica-seconds | $0.52 | $12.51 |
| GPU utilisation | 3,095 replica-seconds | $0.64 | $15.27 |

This does not carry to the other sweeps: on arm C and on the ramp, queue depth's
lower spend comes with a p99 seconds worse than the other two signals'.

**What this experiment cost.** SPEND-PENDING: the owner reads the RunPod console
before publication.

---

## Limits

- **One provider, one GPU class.** RunPod serverless, RTX 4090, one model
  (`Qwen/Qwen3-8B`, `--max-model-len 8192`) and one engine version (vLLM 0.27.1, as
  the curve's and the host re-measurement's runs record it; the validation records
  do not name it). The images differed: the curve's worker and the load balancer's
  worker were different builds on the same pinned vLLM base image. Artifact 1's
  standing limits carry over to the cold-start lags: one host, one engine version,
  the first-touch run excluded.
- **Few hosts, counted above, and not all of them measured for speed.** Attempt
  one ran on a host measured only in its own records (above); the earlier
  one-replica repeats, which carry no verdict, ran on two others, `dkuulgulj9v97y`
  and `27sbjz78gztw8g`, and attempt one's void repeat on the first of those. A host
  here is the worker id RunPod reports. That is evidence of a spread, not a
  distribution, and says nothing about which host is typical.
- **The load balancer as of 2026-10-05,** on the endpoints this project created, in
  probes that were not pre-registered.
- **The closed-loop confirmatory gate was never built.** The design had a second
  gate: one real run with the GPU-utilisation policy driving actual replica changes,
  which would test the autoscaling loop itself, scale-ups, cold starts arriving
  mid-spike and all. Reconnaissance kept it (`docs/recon-a2.md`: a driven scale-up
  on this platform is a real cold start, the condition the design set for keeping
  it). Plan 2b deferred it to a "plan 2c" that was never written. After the
  open-loop gate failed twice it was dropped without running: a choice made at that
  point; no pre-registered rule required it. So the simulator's control loop has
  never been compared with a real one.
- **The regime under test was outside the gate.** The validation schedule stayed
  below one replica's capacity, though the load balancer's bursts pushed the engine
  past its `--max-num-seqs` of 128 in stretches, to as many as 512 in flight; the
  policy sweep's spike went 20% past capacity and stayed there. The traffic regime
  itself was amended twice, the second time on the measured curve after the first
  sweep was refused, by a rule that records only whether a gap is computable, never
  its value or which signal wins. Both amendments say what had
  been seen before choosing.
- **The even split across replicas** is an assumption of every simulated number,
  and RunPod's load balancer does not split evenly.

---

## Reproducing this

Every number above comes from `data/a2/post-analysis.json`, which one script
reduces from committed files; the design constants (bin width, replica cap, spike
size) come from the pre-registration. All of it is in
[github.com/alexostapiuk11/coldstart-recon-worker](https://github.com/alexostapiuk11/coldstart-recon-worker)
along with the harness, the simulator and the figure code. No GPU required:

```bash
python scripts/a2_post_analysis.py
```

It replays both validation attempts from their records and refuses to write if
either replay does not reproduce its committed verdict. The figures:

```bash
python scripts/a2_render_post_figures.py --phone
```

The calibrated attempt's verdict can be re-judged from its three records. By
default this overwrites the committed `data/a2/validation-calibrated/verdict.json`
and its residual figure in place, so `git diff` afterwards shows whether the
re-judged verdict matches. `--out` names the directory it both reads the records
from and writes into, so to leave the committed files alone, copy the three
`repeat-*.json.gz` records to another directory and pass that:

```bash
python scripts/a2_validate.py --judge
python scripts/a2_validate.py --judge --out build/rejudge   # after copying the records there
```

The two simulation runs take hours on a CPU: the headline frontier sweep, whose
cache is committed as `data/a2/frontier-sweep.json`, and the exploratory
service-speed check:

```bash
python scripts/a2_render_figures.py --out build/a2-figures-k05
python scripts/a2_sensitivity_service_speed.py
```

The data, all under `data/a2/` unless named:

- `data/campaign.jsonl`, artifact 1's cold starts;
- `service-curve.json` and `service-sweep.jsonl`, the measured curve and its runs;
- `validation-engine/` and `validation-calibrated/`, the two attempts' records,
  verdicts and residual figures, including attempt one's void repeat; the verdicts:
  [`validation-engine/verdict.json`](https://github.com/alexostapiuk11/coldstart-recon-worker/blob/main/data/a2/validation-engine/verdict.json),
  [`validation-calibrated/verdict.json`](https://github.com/alexostapiuk11/coldstart-recon-worker/blob/main/data/a2/validation-calibrated/verdict.json);
- `validation/`, the three earlier one-replica repeats, kept as evidence with no
  verdict;
- `lb-probes/probe-1/` to `probe-5/`, every probe request;
- `exploratory/`, the host re-measurement and the service-speed sensitivity;
- `frontier-sweep.json`, the headline sweep; `gpu-rate.json`, the hourly rate;
- `README-evidence.md`, what the load-balancer probe files and the frontier sweep
  are, and the commits that made them.

The pre-registration, `docs/experiment-a2.md`, was first committed on 2026-09-04,
and the validation gate's pass rule on 2026-10-03, before any real validation run.
Two later additions carry no amendment heading, both made on 2026-09-05: the
per-signal threshold grids (`652d7cb`) and the fixed control-loop parameters
(`171b0bb`). Every amendment is listed below by its heading's date:

- **2026-09-05**: the never-served exclusion rule, which as first written discarded
  every run;
- **2026-09-17**: the traffic model, which as registered made every policy deliver
  the same p99 (on the placeholder curve);
- **2026-09-17**: the statistical layer: medians, bootstrap intervals, artifact 1's
  percentile convention, and the iso-cost budget as a rule;
- **2026-10-04**: the measured curve and the validation operating point;
- **2026-10-04 (second)**: the traffic model on the measured curve, chosen by a
  ranking-blind search, and the validation engine's cap of 128;
- **2026-10-05**: one retry of the load balancer's own 502s;
- **2026-10-05 (second)**: one validation replica, because the load balancer fills
  workers in turn;
- **2026-10-05 (third)**: the gate judges the arrivals the engine received;
- **2026-10-05 (fourth)**: a host calibration before each replay, the second and last
  attempt.

And the **Analysis note, 2026-10-05**: H1, H2 and H4 operationalised after the
frontiers were seen. Each amendment states what it changed, why, and what had been
seen when it was made; the git history shows the order.

---

## Next

The question stays open. Answering it needs a simulator that is told its host's
speed and passes a gate, or a closed-loop measurement on real replicas, which
removes the simulator from the claim. Either way it needs the load balancer handled
first: a scaler value set to the engine's own cap, and routing that is measured
rather than assumed even.
