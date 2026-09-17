# Finding — artifact 2's pre-registered traffic model makes the signal comparison degenerate

**Date:** 2026-09-17
**Status:** open. Blocks H1, H2 and H3 from being evaluable. Not fixed by plan 2's
measured service curve.

## The finding, in one sentence

Under the pre-registered traffic model, **every policy in the threshold grid
delivers exactly the same p99 latency** — so the inter-signal gap that H3 is
built on is zero by construction, and the ~0.44 s the draft reported was noise.

## The evidence

### 1. One arrival trace, all 55 policies, one p99

`scripts/a2_gap_noise_floor.py`'s companion check: fix a single arrival trace,
run every `(signal, scale_up_at, scale_down_at)` combination in the
pre-registered grid against it.

```
one trace: 24769 arrivals
55/55 policies kept
DISTINCT p99 values:  1  ->  [85.173819876]
DISTINCT cost values: 8
  in_flight_concurrency: 1 distinct p99
  queue_depth:           1 distinct p99
  utilization:           1 distinct p99
```

All three signals, every threshold pair, **identical p99 to nine decimal
places**. The policies differ only in what they spend.

### 2. The measured gap is noise around that zero

Ten independent master seeds, arm A, step shape, 30 repetitions each
(`scripts/a2_gap_noise_floor.py`):

| statistic | value |
|---|---|
| mean gap | **0.314 s** |
| sd across seeds | 0.247 s |
| range | 0.039 – 0.864 s |
| sem | 0.078 s |

The spread is comparable to the quantity. A single sweep's gap is a draw from
this distribution, not a measurement of anything — and the draft's 0.44 s sits
comfortably inside it.

Note the ordering is unstable too: across the ten seeds each of the three
signals takes a turn being "worst". In three of the ten, `queue_depth` and
`in_flight_concurrency` return **byte-identical** p99 (they share an arrival
trace after the seed-pairing fix), and the entire remaining gap is
`utilization` — which is still scored on a different trace, because its
threshold grid shares no `(up, down)` pair with the other two.

### 3. The mechanism

```
saturation/replica = 33.7 rps
baseline = 13.5 rps   peak = 114.5 rps
peak needs 3.4 replicas; cap is 12
arm A lag p50 = 81.1 s, spike sustain = 190 s
```

Every policy scales up **8 or 9 times**:

```
(scale_up, scale_down) -> policies
  (8, 0):  6   utilization
  (8, 4):  3   in_flight_concurrency
  (8, 6): 34   all three
  (9, 0):  4   utilization
  (9, 4):  2   in_flight_concurrency
  (9, 5):  6   in_flight_concurrency, utilization
```

The peak is 3.4× one replica's capacity, so **every signal is past every
threshold in its own grid from the first evaluation onward and stays there**.
A saturated signal carries no information, and three saturated signals carry
the same none.

**The replica cap is not the binding constraint.** Net fleet growth is 2 to 9
replicas plus the initial one, against a ceiling of 12 — so the cap is never
reached, and raising it changes nothing. Measured directly at
`max_replicas` ∈ {12, 24, 64}: identical scale-up counts, identical fleet
growth, and still exactly **one** distinct p99 across all 55 policies at every
ceiling. (An earlier draft of this finding asserted the policies "hit the
12-replica ceiling". They do not; the probe in the next section disproved it.)

The real mechanism is the cold start. The 81 s lag means no added capacity
arrives for the first 81 s of a 190 s spike, so the backlog that sets the p99
is already built before any policy's decisions can matter — and the request at
the 99th percentile is one queued during that window, whose wait is fixed by
the lag alone. Whether the fleet later reaches 3 replicas or 10 changes how
fast the *rest* of the queue drains, not the tail. The p99 is set by the lag
and the arrival trace; the policy has no purchase on it.

The differences that survive are all in scale-**down**, which moves cost (8
distinct values) and not latency.

## Why a measured service curve will not fix this

The traffic model is pre-registered as a *rule*, not as absolute rates:
baseline is 40% of measured saturation and `k` is sized to require three
additional replicas *at the measured service rate*. Both scale with whatever
curve is in hand. So replacing the placeholder with plan 2's measured curve
changes the absolute rps and leaves the **ratio** — peak at 3.4× one replica's
saturation — exactly where it is. The 81.1 s lag and the 190 s sustain are
measured and fixed already.

The degeneracy is a property of that ratio against that lag, not of the
placeholder's invented latency points.

## What this does and does not invalidate

- **H1** (in-flight concurrency dominates) — not evaluable. No signal dominates
  on p99 because p99 does not vary.
- **H2** (utilization is worst, by censoring) — not evaluable for the same
  reason. Ironically the *mechanism* H2 predicts is real and present: every
  signal is censored, not just utilization.
- **H3** (the gap halves between arms) — not evaluable. `h3_verdict`'s
  `evaluable=False` guard fires only on an **exact** zero arm-A gap, and noise
  around a true zero is not exactly zero — so the guard would let a spurious
  verdict through. That is a defect in the guard, surfaced by this finding.
- **H4** (ranking stable across shapes) — not evaluable; there is no stable
  ranking to be stable.
- The simulator itself is **not** implicated. It is doing exactly what it was
  asked to: replaying a load no policy can serve.

## A regime where the comparison IS defined

`scripts/a2_regime_probe.py` sweeps the two traffic-model knobs and the replica
cap, and asks one deliberately ranking-blind question per configuration: how
many *distinct* p99 values do the 55 policies produce on a single fixed trace?
The metric cannot be read as "signal X is better", so searching for a large
spread cannot smuggle in a preferred winner — it can only locate a regime where
the signals are distinguishable from one another at all.

**10 of 40 configurations separate the policies. Every one of them has
`peak / saturation` between 0.35 and 1.20. Every configuration at
`peak / saturation ≥ 1.4` gives a spread of exactly zero.**

The candidates that keep all 55 policies (lower loads lose policies to the
pre-registered exclusion rules):

| baseline | additional replicas | peak/sat | distinct p99 | p99 spread | p99 floor |
|---|---|---|---|---|---|
| 70% | 0.25 | 0.95 | 2 | 6.04 s | 3.23 s |
| **40%** | **0.5** | **0.90** | **5** | **3.37 s** | **1.60 s** |
| 10% | 1 | 1.10 | 3 | 1.87 s | 15.98 s |
| 20% | 1 | 1.20 | 2 | 1.35 s | 21.69 s |
| 70% | 0.5 | 1.20 | 2 | 1.27 s | 21.40 s |

The replica cap is irrelevant throughout: 12 and 24 give byte-identical results
in all 40 rows.

The mechanism is exactly the theory. Separation needs the spike to carry the
fleet from comfortably-under capacity to *roughly at* capacity, so that a
threshold is sometimes crossed and sometimes not. Push the peak past ~1.4×
saturation and every signal is pinned high for the whole spike; three pinned
signals are one signal.

**The 40% / 0.5 row is the strongest candidate**, and notably it keeps the
pre-registered baseline fraction untouched — only `k` moves, from 3 additional
replicas to 0.5. It resolves the 55 policies into 5 distinct p99 values rather
than 2, which is what a Pareto frontier needs to have shape, and its 3.37 s
spread sits on a 1.60 s floor: a *relative* effect of over 200%, against the
6.04 s spread on a 3.23 s floor that the widest-spread row offers with only two
buckets.

## The candidate regime, measured at full strength

The table above is one trace per configuration. Running the full diagnostic at
the 40% / 0.5 candidate — 10 master seeds × 30 repetitions, both arms — gives:

```bash
.venv/bin/python scripts/a2_gap_noise_floor.py --seeds 10 --reps 30 \
  --baseline-fraction 0.40 --additional-replicas 0.5
```

| | arm A (lag p50 81.1 s) | arm C (lag p50 39.4 s) |
|---|---|---|
| queue depth | 2.8023 ± 0.0611 | 2.7032 ± 0.0449 |
| in-flight concurrency | **1.1195 ± 0.0096** | 0.9672 ± 0.0081 |
| GPU utilization | 1.1408 ± 0.0104 | **0.9575 ± 0.0079** |
| **iso-cost gap** | **1.6957 ± 0.0639** | **1.7549 ± 0.0492** |

(± is the standard error across master seeds; p99 in seconds.)

The gap is now **26× its own standard error**, against the pre-registered
regime's 0.314 ± 0.078 around a true zero. The ranking is identical in all 20
runs. The comparison is defined here.

**And it refutes all three testable hypotheses.**

- **H1** (in-flight concurrency dominates) — **not supported.** In-flight and
  utilization are a tie: paired difference +0.0213 ± 0.0172 on arm A and
  −0.0098 ± 0.0110 on arm C, both inside 2 sem, and *the sign flips between
  arms*. What dominates is neither: both beat queue depth by ~1.7 s.
- **H2** (utilization is the worst of the three, by censoring) — **refuted.**
  Utilization is tied for *best*. Queue depth is worst, by 1.66 ± 0.07 s on
  arm A and 1.75 ± 0.05 s on arm C.
- **H3** (the gap at least halves from arm A to arm C) — **refuted.** Halving
  would need arm C ≤ 0.848. Measured: 1.755. The paired change is
  **+0.0592 ± 0.0614** — the gap does not shrink, it does not move at all.
- **H4** (ranking stable across shapes, margins shrink on the ramp) — untested;
  needs the ramp sweep from the statistical-layer plan.

### Why choosing this regime is not result-shopping

Selecting an operating point after seeing that it produces an effect is a real
researcher-degrees-of-freedom hazard, and it deserves a direct answer rather
than a disclaimer. Three things make this defensible, and the third is the
strongest:

1. The selection metric was **ranking-blind**: `distinct_p99`, a count of how
   many different values the 55 policies produce. Nothing in it can express a
   preference for a signal.
2. The search was over the **full grid**, run once, and is committed — not a
   sequence of tries stopped when one looked good.
3. **It refuted every hypothesis the artifact pre-registered.** A regime chosen
   to produce a result would produce the *predicted* result. This one says the
   headline is wrong, the mechanism in H2 is backwards, and the winner is a tie
   between two signals rather than the one predicted.

All of it against the **placeholder service curve**. These are not results;
they are a demonstration that the machinery can now produce results. Plan 2's
measured curve is what would make them real, and it could move every number
here.

## Candidate fixes (none chosen — this needs a decision)

Each changes a pre-registered quantity and so requires a dated amendment
disclosing this search.

1. **Lower the peak** — `k` sized to require ~0.5 additional replicas instead
   of 3, keeping baseline at 40% of saturation. Supported by the probe above,
   and the smallest edit to the pre-registration that produces an evaluable
   experiment. **Recommended.**
2. ~~Raise the replica ceiling~~ — **disproven.** The cap never binds; 12, 24
   and 64 give identical results.
3. **Widen the threshold grids upward** so some thresholds sit above the peak
   signal value. Keeps the traffic model; changes what "spans its own range"
   means, which the pre-registration argued for at length. Untested.
4. **Report the degeneracy as the result.** "Under a spike this far above
   capacity, the autoscaling signal is irrelevant to tail latency and matters
   only for cost" is a defensible and genuinely useful finding — and the cost
   axis *does* separate the signals (8 distinct costs on one trace). It is not
   the artifact that was pre-registered, and the probe shows a nearby regime
   where the pre-registered question does have an answer.

## How to reproduce

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py --seeds 10 --reps 30
```

Roughly 40 minutes of CPU. `--seeds 2 --reps 3` reproduces the shape of the
result in under a minute.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_regime_probe.py
```

Roughly 3 minutes. Prints the table above and names the widest-separating
configuration.
