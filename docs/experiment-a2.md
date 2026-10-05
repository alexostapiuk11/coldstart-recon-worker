# Artifact 2 — Pre-registration

Committed before the simulator, the sweep, or any result exists. The git
timestamp on this file is the evidence that what follows was fixed in advance.

## Question

For an LLM serving deployment whose scale-up lag is a measured cold-start
distribution, does reducing that lag change how much the choice of autoscaling
signal matters?

## Measured inputs, fixed

- Cold-start lag: artifact 1's empirical ECDF, resampled. Arm A (p50 81.1 s,
  n=99 repeat-host) and arm C (p50 39.4 s, n=100 repeat-host). The single
  first-touch run (arm A, 2266.6 s) is excluded: it measures image
  distribution, not a cold start.
- Lag includes `T_platform` (median 4.07-4.83 s). From the autoscaler's point
  of view the wait is the wait.
- Replicas are binary: absent or serving. Justified by artifact 1's
  measurement that `T_fast` is request 1 and per-arm steady-state medians
  differ by 0.6 ms.

## Traffic model, fixed

- `D` sustain = 2 x p95(arm A) = 192.7 s, rounded to **190 s**. Pinned to arm A
  and held constant across both distributions so the composition comparison
  varies exactly one thing.
- `R` ramp = `D`/2 = **95 s**.
- baseline = **70%** of measured saturation.
- `k` = magnitude requiring **0.5 additional replicas** at the measured
  service rate.

  *Both amended 2026-09-17, from 40% and 3 additional replicas. As
  originally registered they made the experiment unanswerable — see the
  amendment immediately below, which states the old values, the evidence,
  and how the replacements were chosen. `k` amended again 2026-10-04, from
  0.25 to 0.5, on the measured curve — see "Amendment, 2026-10-04 (second)"
  near the end of this document.*

The two absolute rates are computed from the service curve and committed
**before any policy sweep runs**.

### Amendment, 2026-09-17: the traffic model made the experiment unanswerable

**Changed:** baseline **40% → 70%** of measured saturation; `k` from **3 → 0.25**
additional replicas at peak. Peak load moves from 3.40× to **0.95×** one
replica's saturation.

**Why.** As pre-registered, this traffic model makes the experiment
*unanswerable*, and not marginally so: on any fixed arrival trace, all 55
policies in the threshold grid — all three signals, every threshold pair —
deliver an **identical p99 to nine decimal places**, while producing 8 distinct
costs. The inter-signal gap H3 is built on is exactly zero by construction, so
H1, H2, H3 and H4 have no answers to find. The 0.44 s gap an earlier draft
reported was a single draw from a noise distribution measured at
0.314 ± 0.078 across ten master seeds.

The mechanism: `k` sized for 3 additional replicas against a baseline of 40% of
*one* replica's saturation puts the peak at 3.4× that saturation. Every signal
is then past every threshold in its own grid from the first evaluation onward
and stays there for the whole spike, and a saturated signal carries no
information. The measured 81.1 s cold start compounds it — no added capacity
arrives for the first 81 s of a 190 s spike, so the backlog that sets the p99 is
already built before any policy's decisions can take effect.

This is **not** an artefact of the unmeasured placeholder service curve. The
traffic model is a rule scaled to measured saturation, so a measured curve
changes the absolute rates and leaves the ratio — and the degeneracy — exactly
where they are. The replica cap is not implicated either: it never binds, and
`max_replicas` of 12, 24 and 64 give identical results down to the p99.

**How the replacement was chosen.** `scripts/a2_regime_probe.py` runs two
stages. Stage 1 screens a grid of candidates on one fixed trace each, asking a
deliberately **ranking-blind** question: how many *distinct* p99 values do the
55 policies produce? That metric cannot express a preference for any signal, so
it can locate a regime where the signals are distinguishable but cannot select
which one wins. 10 of 40 configurations separate the policies, and every one has
peak/saturation between 0.35 and 1.20; every configuration at ≥ 1.4 gives a
spread of exactly zero.

Stage 2 re-runs the survivors through the real sweep and reports **surviving
policies per signal**. It exists because stage 1 misled once: read as though its
one-trace `kept` count were a real survival rate, it recommended baseline 40% /
0.5 additional replicas, where real sweeps give `queue_depth` only **2.7 of its
19 policies**. A three-point frontier against nineteen-point ones is not the
comparison this artifact claims to make, and part of that candidate's apparent
gap was just the mismatch. **baseline 70% / 0.25 additional replicas** is
adopted instead: every signal keeps its full grid (19/17/19), and the separation
is larger anyway.

**Measured at the adopted regime** (10 master seeds × 30 repetitions, both arms,
placeholder curve):

| | arm A (lag p50 81.1 s) | arm C (lag p50 39.4 s) |
|---|---|---|
| queue depth | 5.9707 ± 0.0440 | 4.2340 ± 0.0383 |
| in-flight concurrency | 2.9758 ± 0.0606 | 1.6807 ± 0.0548 |
| GPU utilization | 3.0284 ± 0.0537 | 1.7094 ± 0.0355 |
| **iso-cost gap** | **3.0681 ± 0.0649** | **2.6094 ± 0.0450** |

The gap is 47× its own standard error, and the ranking is identical in all 20
runs. The comparison is defined here.

**Selecting an operating point after seeing that it produces an effect is a real
researcher-degrees-of-freedom hazard**, and the honest answer is not a
disclaimer but the outcome: this regime **refutes the hypotheses below**. H2's
predicted loser (utilization) is statistically tied for *best*, and the worst
signal by a wide margin is queue depth, which no hypothesis named. H1's
predicted winner is not distinguishable from utilization on either arm. H3's gap
does shrink — significantly, by 0.4587 ± 0.0596, about 15% — but halving would
need arm C at or below 1.534 and it is 2.609. A regime chosen to manufacture a
result would produce the *predicted* result.

Amended while the service curve was still the explicitly-unmeasured placeholder,
under `allow_unmeasured=True`, so no measured result existed to tune it against.
Plan 2's measured curve could move every number above.

Full evidence and reproduction: `docs/findings-a2-degenerate-regime.md`.

## Hypotheses

**H1.** In-flight concurrency dominates the other two on the cost/p99 frontier
for the step spike.

**H2.** GPU utilization is the worst of the three, and the mechanism is
censoring: its frontier degrades most in the high-load region where the signal
has saturated.

**H3 (headline).** The inter-signal frontier gap at iso-cost shrinks by at
least half between the arm-A distribution and the arm-C distribution.

Gap is the p99-damage spread between the best and worst signal at the iso-cost
slice, in seconds. Computed separately for step and ramp, both reported. H3
holds only if the halving occurs under **both** shapes. A halving under one
shape only is published as a partial result, not rounded up to confirmation.

**H4.** The ranking is stable across step and ramp, but margins shrink on the
ramp.

## Fixed control-loop parameters

Not swept, and therefore invisible in every frontier, but they set every
published cost and p99 as surely as the thresholds do. Fixed here rather than
left implicit in the code, so that changing one is a change to the
pre-registration rather than an edit nobody has to justify:

| parameter | value | why this value |
|---|---|---|
| cooldown | 30 s | Without one, a policy fires on every evaluation while the signal stays high and every signal looks identically aggressive. Real autoscalers have one; modelling them without it would idealise away the constraint the comparison is about. |
| evaluation interval | 5 s | The controller sees fleet state this often. Much finer and the cooldown alone governs; much coarser and a 190 s spike gets too few decisions to differentiate signals. |
| max replicas | 12 | A ceiling well above what `k` is sized to require, so the cap does not bind in the normal case and a runaway policy is still bounded. Verified not to bind under either traffic model: `max_replicas` of 12, 24 and 64 give identical scale-up counts, identical fleet growth and identical p99 (2026-09-17). |
| repetitions per configuration | 30 | Fixed before any result is inspected. |

## Threshold grids, per signal

The three signals do not share units, so one numeric grid cannot span all
three:

| signal | unit | range |
|---|---|---|
| queue depth | requests waiting per replica | 0 to unbounded |
| in-flight concurrency | active requests per replica | 0 to the curve's measured maximum |
| GPU utilization | a fraction | 0 to 1 |

Each signal is therefore swept over a grid spanning its own range, fixed here
before any sweep runs:

| signal | scale-up grid | scale-down grid |
|---|---|---|
| queue depth | 1, 2, 4, 8, 16 | 0, 0.25, 0.5, 1 |
| in-flight concurrency | 2, 4, 8, 12, 16 | 0.5, 1, 2, 4 |
| GPU utilization | 0.50, 0.65, 0.80, 0.90, 0.95 | 0.05, 0.15, 0.30, 0.50 |

**This is not the per-signal tuning the design rejects.** That rejection
forbids hand-picking each signal's best operating point after seeing results.
Giving each signal a grid that spans its own range is what makes the frontiers
comparable at all: a single grid of 2 to 16 puts every threshold above
utilization's maximum possible value of 1, so that policy never fires, its
frontier collapses to one "never scale" point, and H2 is confirmed by a units
mismatch rather than by the censoring mechanism this artifact exists to
demonstrate. Verified against the simulator before these grids were fixed:
utilization at a threshold of 2.0 produced 0 scale-ups and a p99 of 89.7 s,
while at 0.5 through 0.95 it produced 4 scale-ups and a p99 of 58.4 s.

## Analysis plan

Frontiers are compared, not points. The headline sentence comes from the
iso-cost slice. Percentiles reported: p50, p90, p95, p99 of request latency
within a spike. p99 is supported here and was not in artifact 1: a spike
generates thousands of requests, where artifact 1 had ~100 runs per arm.

### Amendment, 2026-09-17: the statistical layer

Four changes. None alters a quantity this document fixes; all four alter how a
published number is computed, which is the kind of thing that must not move
silently. Made while the service curve was still the explicitly-unmeasured
placeholder, under `allow_unmeasured=True`, so no measured result existed to
tune them against.

**1. Aggregator: mean → median.** Each policy's published cost and p99 were the
arithmetic MEAN of its 30 per-run values. This document fixes the repetition
count but not the aggregator, so no pre-registered quantity changes — but the
estimator does, and artifact 1's standing rule is that a mean is never published
for right-skewed data. Per-run p99s under a heavy-tailed workload are
right-skewed, and a single catastrophic repetition moves a 30-run mean by a
thirtieth of its own excess. The estimand is unchanged and still per-run: the
p99 a *typical* run of that policy delivers, which is what a median reports.

**2. Intervals on every published quantity.** Percentile-method bootstrap, the
same convention as artifact 1 and pinned equal to it by a conformance test
(`autoscale` cannot import `coldstart`, so the conventions are implemented
twice and that test is what stops them drifting).

The gap's interval resamples repetition *identities* — one shared draw across
every policy, so that wherever two signals both kept repetition r they are
scored on the same arrival trace — and rebuilds the frontiers and re-derives the
budget inside each draw. Propagating uncertainty *through* the frontier
selection is what makes the winner's-curse bias visible: each frontier is a
minimum over 17–19 noisy estimates, so the point gap is biased upward. The
interval inherits that bias; it does not correct it. A correction needs a
held-out selection split and is not attempted.

A policy that lost repetitions to the exclusion rules contributes the drawn ones
it has. That assumes a discarded run is missing for reasons uncorrelated with
the value it would have had, which is **not strictly true**:
`no_scaling_action` fires on the quieter traces, where the policy never crossed
its threshold. The bias runs toward a policy looking better than it is on the
runs it kept, and it is the same bias the point estimate already carries.

**3. Percentile convention and sample floors.** Artifact 2 used nearest-rank
(`sorted[int(q·n)]`) where artifact 1 interpolates between order statistics;
on the same data those disagree by up to a whole order statistic. Artifact 2
also applied no sample floor, so a run that completed a dozen requests reported
its second-worst latency as a "p99" into the same field as one backed by
thousands. Both are now artifact 1's, including `MIN_SAMPLES["p99"] = 500` —
which is what holds this document's own justification for reporting p99 ("a
spike generates thousands of requests") to account.

**4. The iso-cost budget is now a rule.** It was not pre-registered at all, and
was implemented two incompatible ways: `min(cost) × 2` in the render script and
the maximum of the per-signal cheapest points in a test. Against the sweep the
script's version left every frontier fully affordable, so the "inter-signal gap
at iso-cost" was in fact the spread between each signal's *unconstrained* best
— a different quantity under the published name, and the more flattering one,
since it removes the cost axis from a comparison whose premise is a cost/latency
tradeoff.

The budget is now **the cheapest spend at which every compared signal has at
least one policy**: the maximum over signals of that signal's cheapest frontier
point. Derivable from the sweep rather than chosen after seeing it, and it binds
by construction — at exactly this budget the most expensive-floor signal has
precisely one affordable policy. Any lower budget is not a stricter comparison
but an undefined one.

**Effect on the reported numbers** (placeholder curve, both shapes, both arms):

| | arm A | arm C | halving needs |
|---|---|---|---|
| step | 2.7542 [1.4815, 4.1501] | 1.9083 [1.2124, 2.6515] | ≤ 1.3771 — not met |
| ramp | 4.0766 [3.1358, 4.5537] | 1.7870 [1.4784, 2.8918] | ≤ 2.0383 — met |

H3 is therefore **partial**: the gap at least halved under the ramp and not
under the step, which this document requires be published as a partial result
rather than rounded up to confirmation. The step-shape intervals overlap
substantially, so the step arm-A/arm-C difference is not itself resolved at this
sample size; the ramp intervals do not overlap.

## Exclusion rules

A simulation run is discarded if the arrival trace is empty, if **no** replica
launched during the run ever reaches serving, or if the policy produces no
scaling action across the entire spike -- each makes the run uninformative
about the signal rather than an observation about it. Discards are counted and
reported by signal, never silently dropped.

### Amendment, 2026-09-05: the never-served rule was fatally over-broad

As first written this rule discarded a run if **any** replica failed to reach
serving before the window closed. Measured against the simulator before any
result existed: that discarded **100% of runs on both arms**, so the sweep
produced nothing at all.

The error was conceptual, not just arithmetic. In a closed loop with a
realistic cold start, the last replica launched near the end of a spike
essentially never ripens before the window closes -- that is the normal case,
not a degenerate one. And paying for a replica that never serves is precisely
what a slow cold start does to an operator: it is the artifact's subject, not
noise to be excluded. The rule would also have bitten arm A (p50 lag 81.1 s)
harder than arm C (39.4 s), biasing H3 -- the headline -- in the direction of
its own confirmation.

The rule now fires only when the fleet never effectively grew: no launched
replica reached serving at all. A run containing some never-ready replicas is
**kept**, and their cost is billed in `replica_seconds` from launch, because
that cost is a measured finding.

Amended before any sweep was run for results and before the service curve was
measured, so there was no result to tune it against. The only sweeps executed
to this point used the explicitly-unmeasured placeholder curve, under
`allow_unmeasured=True`, to check figure layout.

## Validation gate — pass rule

Fixed 2026-10-03, before any real validation run exists. Implemented in
`autoscale/validation.py` (artifact 2's values) over `autoscale/validation_band.py`
(the arithmetic); changing any value below after the first real run is an amendment.

- **Repeats:** exactly **3** real runs of **one** fixed arrival schedule at pinned
  capacity. Repeats of different schedules are refused, and so is a fourth: the band
  is a min–max range, a range only widens as runs are added, and an open count would
  let the band be grown until the model fits.
- **Trajectory:** latency p50 per **10 s** bin, keyed by *scheduled* arrival time.
  p50 rather than p99 because a 10 s bin holds a few hundred requests and the p99
  floor is 500.
- **Window:** a request whose send time plus latency is strictly later than the end
  of the run window is unfinished — in the real runs exactly as in the simulator.
- **Driver fidelity:** a run whose send times drift more than **0.5 s** from the
  schedule is refused; it replayed a different trace.
- **Band:** per bin, the min and max of the three repeats' p50, widened by **1 ms**
  on each side — taken as the latency clock's resolution — so float residue at an edge is not
  a miss. A miss's magnitude is measured from the unwidened edge.
- **Censoring:** a bin with any unfinished request is censored. A bin censored on
  some repeats and not others is excluded as unstable and reported. Model and reality
  both censored is agreement, but the bin is not *judged*: it says nothing about the
  model's latency, and counting it would let a backlogged tail pass for free. One
  censored and the other not is a **miss of unbounded magnitude**.
- **Sample floor:** a bin with fewer than 20 completed requests — on the repeats, or
  in the prediction — has no p50; it is excluded and reported, never judged.
  Censoring is decided first: a bin censored on one side and thin-but-finished on
  the other is a censoring miss, not excluded.
- **Pass:** at least **10** judged bins are required — fewer is **not evaluable**,
  never a pass — and the run passes if **no more than half** of the judged bins are
  misses.
- **Why a miss rate, not "every bin":** a model that predicts each bin's true median
  exactly still falls outside the min–max of three repeats with probability 1/4 per
  bin, so requiring every bin passes a perfect model 6% of the time at 10 bins and
  0.3% at 20. Under this rule, if bins were independent, a perfect model fails about
  2% of the time at 10 judged bins and under 0.1% at 30, while a model biased beyond
  the system's own spread — outside in about three bins of four — fails 92% and 99.7%
  of the time. Neighbouring bins share queue state, so they are not independent: a
  perfect model fails more often than stated and a biased one less often. In
  simulation (`scripts/a2_validation_gate_power.py`, seeded, over the real
  `compare()` with no band-edge tolerance), queue-level correlation raised the perfect-model failure rate to about
  2.5% at 10–12 judged bins, and a per-run host-speed effect held it near 5% however
  many bins were judged, with power near 80%. The result is published with its number
  of judged bins so a reader can weigh it.
- **Disclosure:** every miss is published with its magnitude, as spec §10 already
  requires.

## Amendment, 2026-10-04: the measured curve and the validation operating point

Made after the service sweep (`data/a2/service-curve.json`) and reconnaissance
(`docs/recon-a2.md`), before any policy sweep has run on the measured curve and
before any real validation run exists. Signed off by the owner on 2026-10-04.

**The measured curve replaces the placeholder.** Concurrency 1–128, three repeats
per level, `max_num_seqs` 256, prefix caching off, random 13-token prompts at 16
output tokens (the exact prompt needs pandas, which the image lacks; recorded per
run). Level 256 is recorded as unservable: the engine died of CUDA out of memory
at its first step in 3 of 3 runs. The per-replica cap is therefore 128.

**An idle point at concurrency 0 reads 0% GPU.** nvidia-smi reads 100% at every
measured level, one request included. Without a point at 0 the curve clamps, an
idle replica reads 100% busy, and no utilisation scale-down threshold can fire.
The 0% is measured: in every successful sweep run, at least 80% of the samples
outside its measured span, with the engine idle, read 0; the rest sit at the
span's edges, next to the warm-up and the prompt probe.

**H2 under a saturating signal.** The headline utilisation signal stays
nvidia-smi's, because it is what GPU-utilisation autoscalers act on, and it
saturates at one request. A **sensitivity arm**, `utilization_throughput`
(throughput at the current per-replica load over the curve's maximum
throughput), is swept with utilisation's grid (up 0.5, 0.65, 0.8, 0.9, 0.95;
down 0.05, 0.15, 0.3, 0.5) and reported beside H2. H2's verdict is stated for
the headline signal; if the sensitivity arm reverses it, the post says so in the
body.

**Absolute rates (spec §8 ordering rule), from `scripts/a2_traffic_rates.py`:**
saturation **211.2 req/s** (128 / 0.606 s); baseline **147.8 req/s** (0.70 ×
saturation); peak **200.6 req/s** (baseline + 0.25 × saturation), for one replica.

**Validation operating point.**
- **2 replicas** pinned (`workersMin = workersMax = 2`; `workersMax` set by the
  owner, `workersMin` by the driver).
- The step shape with its baseline scaled by the replica count: baseline **295.7 req/s**,
  peak **401.3 req/s**, sustain 190 s.
- Window until **400 s**, with a drain **30 s**: no arrival after 370.0 s.
- One schedule, seed **20261004**, 129,876 requests, replayed by all three repeats.
- The gate judges **server-side latency**: the engine's own receive-to-response
  time, stamped by `worker/a2_middleware.py`. That is the quantity the simulator
  models. Client latency is recorded per request and published beside it.
- Before t=0 the driver sends **20 req/s** until every pinned worker has answered
  for 30 s straight, giving up after 900 s; those requests are not part of the run.
- **The simulator's prediction for this schedule:** p50 0.554 s, p99 0.651 s, 0 requests
  unfinished at 400 s.

**Void runs.** A repeat with any non-200 response, a response from a worker
outside the pinned set, or a 200 without the server-latency header is void. It is recorded, not judged, and run
again once. A second void at the same repeat ends the gate as "not evaluable",
with the cause published. A host-novelty event (a pinned worker id never seen in
an earlier repeat) is recorded and disclosed, not voided (spec §10).

**Feasibility probe acceptance (before any validation repeat).** The probe
(`scripts/a2_lb_probe.py`) answers P1–P8 of plan 2b. The repeats may start only
if, at its 450 req/s step:
- every response was 200;
- each pinned worker served at least 35% of requests;
- the maximum send jitter stayed at or below 0.25 s.

Otherwise the owner decides what changes, and this amendment is amended before
any repeat.

## Amendment, 2026-10-04 (second): the traffic model on the measured curve

Made after the first full policy sweep on the measured curve was refused, and
before any of the four headline gaps on the measured curve has been computed.
Signed off by the owner on 2026-10-04.

**Changed:** `k` from **0.25 → 0.5** additional replicas at peak. Baseline stays
at **70%** of measured saturation. Peak load moves from 0.95× to **1.20×** one
replica's saturation. The validation operating point does **not** change (below).

**Why.** On the measured curve the 2026-09-17 regime starves `queue_depth`. The
figure run's guard refused the H3 gap: on arm A's step, all three `queue_depth`
frontier points kept 3 or 4 of 30 repetitions, against the bootstrap floor of
20. `scripts/a2_discard_diagnostic.py` shows the mechanism:
- A peak of 0.95× saturation is about 115 requests in flight on one replica,
  below its cap of 128, so a queue forms only in brief bursts. In the median
  run the queue was at or above the scale-up threshold in about 5% of
  evaluations.
- `queue_depth` scales up on a burst; the burst clears; the next evaluation
  after the 30 s cooldown reads an empty queue. Scale-down then removes the
  newest replica while it is still starting (arm A's median cold start is
  81.1 s). In all 430 discarded runs, scale-downs at least equal scale-ups.

The 2026-09-17 regime was chosen on the placeholder curve, and it did not carry
over. The placeholder probe already showed `queue_depth` starving nearby (40% /
0.5 kept 2.7 of 19 policies).

**How the replacement was chosen.** The pass criteria, candidate order and
selection rule were committed in `docs/regime-search-a2-measured.md` (80ccac2)
before the search code existed. The search, `scripts/a2_regime_search.py`
(63894dd), is pinned to that document by tests.
- **The space:** the placeholder probe's own 4 × 5 grid of baseline and `k`.
  Nothing else could change.
- **The criteria,** required in all four headline sweeps:
  - P1: `gap_interval` completes;
  - P2: at least 2 distinct median p99s at 1 ms.
- **The rule:** the first candidate in a fixed order (keep the baseline at 70%
  if any `k` works, smallest `k` first) is the one proposed.
- **What the search records:** only whether each gap is computable. It never
  records or prints a gap.

Result: a candidate clears exactly when its peak exceeds one replica's
capacity (13 of 20 do). 70% / 0.5 is first in order and passes all four sweeps
(distinct median p99s 46, 53, 53, 30). Full table:
`docs/regime-search-a2-measured.md`.

**What was seen before choosing.** The diagnostic printed per-policy p99s on arm
A's step under the old regime:
- `queue_depth` about 0.72 s, on its few kept runs;
- `in_flight_concurrency` about 0.66 s;
- `utilization` 0.674 s.

The refused figure run also printed the modeled-lag sensitivity gaps under the
old regime: 0.0848 s [0.0727, 0.1042] at a 20 s lag, then 0.0666, 0.0500, 0.0425
and 0.0106 s at 40, 60, 80 and 120 s, the last four without intervals. That is
the explicitly unmeasured synthetic-lag panel. None of the four headline gaps
(arms A and C, step and ramp), their intervals or the H3 verdict has been
computed on the measured curve. The rule above is what chose 0.5, and it cannot
express a preference for any signal.

**Absolute rates (spec §8 ordering rule), from `scripts/a2_traffic_rates.py`,
for the policy sweep and one replica:**
- saturation **211.2 req/s** (unchanged);
- baseline **147.8 req/s** (unchanged);
- peak **253.4 req/s** (baseline + 0.5 × saturation; was 200.6).

Step and ramp share these rates.

**Validation operating point: unchanged, now pinned.** Before this amendment,
the validation schedule followed the sweep's spike automatically. At 0.5, two
pinned replicas would be overloaded: predicted p99 about 39 s, and up to about
16,500 requests outstanding, beyond the driver's in-flight cap of 4,096 and
untested against the platform's load balancer.
- The validation schedule is therefore pinned to the spike the 2026-10-04
  amendment signed: baseline + **0.25** × saturation, scaled to **2
  replicas**. That is baseline 295.7 req/s, peak 401.3 req/s, 129,876
  requests, with the predictions, warm-up, void rules and probe acceptance as
  signed.
- **What this gate does not check.** It validates the simulator's latency curve
  up to saturation. It does not validate the queueing the new spike produces,
  which `queue_depth` now reads. The post says so beside the gate's verdict.

**Validation engine cap: 128.** The simulator admits at most 128 requests per
replica (the curve's top level) and queues the rest. The validation worker
started vLLM with `--max-num-seqs 256`, so above 128 the real engine would run
requests the simulator queues, in a range the curve never measured: level 256
died of CUDA out of memory. Even at the signed point, short bursts exceed 128
per replica.
- `worker/lb_serve.py` now starts the engine with **`--max-num-seqs 128`**.
  Every other flag stays the curve's `served_cmd`.
- The curve itself is unaffected: no measured level exceeded 128, so the
  256 setting never bound during the sweep.
- The worker image is rebuilt before the feasibility probe.

**What re-runs.** The full figure sweep, on the amended traffic, with the same
grids, controller, exclusions, 30 repetitions and seed 17. Nothing else in this
document changes.

## Amendment, 2026-10-05: the load balancer's own 502s

Made after three feasibility probes and before any validation repeat. Signed
off by the owner on 2026-10-05.

**Changed:** a request the load balancer answers **502 without the
`x-a2-worker` header** is retried **once**, at once, by the driver. The retry's
outcome is the request's outcome. Both the void rule and the probe acceptance
read that final outcome:
- A repeat is void if any request's final status is not 200, or on the other
  two signed rules, which are unchanged.
- The probe's "every response was 200" means every request's final status
  is 200.

Nothing else is retried: not a 502 that carries the worker header (it came from
the engine), not any other status, and not a second failure.

**Why.** A 502 without the worker header never produced an engine response,
and the gate is about the engine. In the second probe, 13 of 33,750 requests
were such 502s, in two bursts: 11 in the first 0.3 s of the 450 req/s step, and
2 together 24.5 s into the 300 req/s step. Under the signed void rule, any one
of them voids a repeat. Each repeat steps from 20 req/s of warm-up to
296 req/s at t=0 and to 401 at the spike, so most repeats would likely have
been voided for a platform fault. Two voids end the gate as "not evaluable".
Rejected: retrying until success, which turns the open-loop replay into a
closed loop around a failing path and hides how often it failed.

**What it costs, disclosed:**
- A retried request's client latency includes both attempts.
- Its server latency, the judged quantity, is the retry's own.
- It reaches the engine later than scheduled by the first attempt's duration.
- In the third probe, one first attempt failed after 9.34 s, not instantly. A
  502 that slow may mean the load balancer forwarded the request before
  failing, so the engine may serve a retried request twice. At most 2 of 13,500
  requests here.
- Every retry is marked in the record (`lb_502_retried`, by request index) and
  published with the verdict.

**Evidence** (endpoint `lybvnpnt2m327y`, 2 workers, the signed ladder up to 450
req/s):

| Probe | Endpoint scaler value | At 450 req/s | Verdict |
|---|---|---|---|
| 1 | 4 (RunPod's default) | not reached. The path delivered about 17 req/s at every rate. Server p50 was 0.31 s, but client p50 was 52 s and there were 449 timeouts at 100 req/s. | not evaluable |
| 2 | 128 | 11 of 13,500 were load-balancer 502s, all within 0.3 s of the step starting; split 53/47; jitter 0.08 s | FAIL (non-200) |
| 3 | 128, with this retry | every final status 200; 2 retried; split 49/51; jitter 0.095 s | PASS |

**Operational changes, recorded here because they decide feasibility:**
- The endpoint's scaler value is **128**, the engine's `--max-num-seqs`. With
  RunPod's default of 4, the load balancer kept only a few requests in flight
  per worker. RunPod documents no such limit; it was found by the first two
  probes.
- The probe ladder now also stops on a step whose client p50 exceeds 5 s.
  That only ends the ladder early; it judges nothing.

**What does not change:** the validation operating point, the schedule, the
predictions, the warm-up, the other two void rules, the probe's 35% split and
0.25 s jitter conditions, and the pass rule.

## Amendment, 2026-10-05 (second): one validation replica, because the load balancer fills workers in turn

Made after three feasibility probes and one failed repeat, before any valid
validation record exists. Signed off by the owner on 2026-10-05.

**Changed:**
- The gate validates **1 replica**, not 2.
- The endpoint's scaler value is **512**, above the engine's 128-request cap.
- The probe's ladder is resized to one replica, and its acceptance gains a
  load-balancer check.

The schedule's shape (the step at 0.25 additional replicas), its seed, window,
drain and warm-up, the three void rules, the retry of the load balancer's own
502s, and the pass rule are unchanged.

**Why.** RunPod's load balancer does not split load evenly. It fills one worker
up to the endpoint's scaler value before sending anything to the next.
Reconstructed from the probes' per-request records (scaler value 128):

| Probe 3 step | Worker 1, mean / max in flight | Worker 2, mean / max |
|---|---|---|
| 100 req/s | 37 / 56 | none |
| 200 req/s | 90 / 128 | 1 / 34 |
| 300 req/s | 100 / 128 | 33 / 95 |
| 450 req/s | 85 / 128 | 87 / 128 |

Probe 2 shows the same. The simulator, and so every prediction the gate checks,
splits load evenly across replicas. With 2 replicas the gate would have compared
an even-split prediction against fill-first routing, and missed for a reason
that is the platform's, not the engine model's.

The cap also holds the overflow in the load balancer, outside the measured
server latency. At 450 req/s in probe 3, server latency never exceeded 0.55 s,
but client p99 was 18.9 s. Over a 400 s replay that queue grew until the
driver's thread pool hit the operating system's limit, and repeat 1 died with
no record (the pool is now capped below that limit; it slows down rather than
dies).

With one worker there is nothing to route. A scaler value above the engine's
cap means the load balancer forwards every request at once, and vLLM queues
past its 128 sequences inside the span the middleware measures, which is the
queue the simulator models.

**What this gate no longer checks.** How load is spread across replicas. The
simulator's even split stays an assumption, and the post says so beside the
verdict, with the fill-first routing above as a finding about this platform.

**The operating point, from `scripts/a2_traffic_rates.py`:**
- **1 replica** pinned (`workersMin = workersMax = 1`).
- Baseline **147.8 req/s**, peak **200.6 req/s** (0.95× one replica's
  saturation), sustain 190 s.
- Window until 400 s, drain 30 s, seed 20261004: **64,784 requests**, no
  arrival after 370.0 s.
- The simulator's prediction: p50 0.543 s, p99 0.702 s, 0 unfinished.

**The probe, resized:**
- Ladder: **25, 50, 100, 150, 180, 210 req/s**, 30 s each. The top step covers
  the schedule's busiest 10 s bin (207.4 req/s).
- Acceptance at the top step:
  - every request's final status is 200;
  - the maximum send jitter is at or below 0.25 s;
  - **new: client p99 minus server p99 is at or below 1.0 s**, so requests
    are not waiting in the load balancer. Probe 3's clean steps sat at about
    0.4 s.
- The worker-split condition is dropped: with one worker it is always 100%.

**Cost:** one worker instead of two. About $0.15 for the probe, about $0.55
for three repeats.

## Amendment, 2026-10-05 (third): the gate judges the arrivals the engine received

Made after the first three one-replica repeats, and before any verdict was
computed on them or on anything else. Signed off by the owner on 2026-10-05.

**Why.** All three one-replica repeats were shaped by the load balancer, not by
the engine:

| Repeat | Requests delayed over 2 s client-side | Load-balancer 502s retried | As signed |
|---|---|---|---|
| 1 | 16,868 (26%) | 50 | void: 2 load-balancer 400s at about 9.3 s, no worker header |
| 2 | 22,385 (35%) | 23 | refused: send jitter 0.591 s |
| 3 | 13,620 (21%) | 22 | refused: send jitter 0.806 s |

The load balancer stalls: it holds requests for seconds, then releases them
together. The engine therefore did not receive the schedule the driver sent.
The send-jitter overruns are the driver catching up after such a release.
Judged by scheduled arrival, the gate would score the platform's stalls as
simulator misses. The gate exists to test the simulator's model of the engine,
and the load balancer is not part of that model.

**Changed:**

1. **Engine arrival times are recorded.** `worker/a2_middleware.py` also
   stamps `x-a2-server-received`, the engine's wall-clock time when the request
   reached it.
   - A repeat runs on one worker, so one clock stamps every request.
   - The stamps are put on the run's timeline by subtracting the smallest
     (received − sent) in the run. That aligns the least-delayed request with
     its send time, and every other request arrives at or after its own.
2. **Each repeat is predicted from its own engine arrivals.**
   `run_fixed_capacity` replays the requests in the order and at the times the
   engine received them, at one replica, over the same 400 s window.
   - Real and predicted latencies are binned by that engine arrival time, 10 s
     bins as before.
   - A real request that finishes after the window counts as unfinished, as
     before.
3. **A bin misses when all three repeats land on the same side of their own
   predictions.**
   - For each repeat, the bin's residual is its real p50 minus its predicted
     p50. The bin misses if the three residuals are all above +1 ms or all
     below −1 ms.
   - When the three repeats received identical arrivals, this is exactly the
     signed rule ("the prediction is outside the min-max of the real p50s").
     The signed miss-rate argument holds unchanged: a perfect model misses a
     bin with probability 1/4.
   - Censoring:
     - **Unstable** (excluded, reported): reality backlogged in some repeats
       and not others.
     - **Miss:** reality backlogged in every repeat and the model did not in
       some repeat, or the reverse.
     - **Agree, not judged:** both backlogged in every repeat.
     - **Excluded, reported:** any repeat's bin is thin or empty on either side.
   - The thresholds are unchanged: at least 10 judged bins, and at most half of
     them missing.
4. **Requests that never reached the engine** (a final non-200 without the
   worker header) are left out of both the real and the predicted side, since
   the engine never saw them. They are counted and published.
   - A repeat is **void** if more than **1%** of its requests never reached the
     engine.
   - A request that reached the engine and did not end in 200 still voids, as
     signed.
   - A 200 without the received-time header voids, like one without the
     latency header.
5. **Send jitter is recorded, not judged.** That rule guaranteed the
   prediction replayed the trace the system actually received. Predicting from
   engine arrivals now guarantees that directly. Jitter is published with each
   repeat.
6. **Figure 3** shows, per bin, the three repeats' residuals around zero, and
   marks the misses.

**What does not change:** one replica, the schedule the driver sends (64,784
requests, seed 20261004), the warm-up, the retry of the load balancer's own
502s, the host-novelty disclosure, three repeats with one re-run of a void
repeat, and the pass rule's thresholds.

**What it costs, disclosed:**
- The predictions can no longer be computed before the run. They come from
  each run's observed arrivals.
- The simulator still fits nothing to the run: arrivals go in, latencies come
  out, and no parameter is estimated from the repeats.
- The pre-registered schedule's predictions (p50 0.543 s, p99 0.702 s) stay on
  record, published beside the engine-arrival results.
- Bursts released by load-balancer stalls are now input to the model, so the
  gate tests the service model under burstier traffic than the schedule
  intended.

**The first three one-replica repeats** carry no engine arrival times and
cannot be judged under this rule. They are kept and published as evidence for
it, with no verdict computed.

## Stopping rule

The sweep is exhaustive over the pre-declared threshold grid; there is no
sequential stopping decision to make. Repetitions per configuration are fixed
at 30 before any result is inspected.
