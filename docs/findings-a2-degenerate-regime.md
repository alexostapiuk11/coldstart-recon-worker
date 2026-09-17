# Finding — artifact 2's pre-registered traffic model makes the signal comparison degenerate

**Date:** 2026-09-17
**Status:** resolved by amendment. The pre-registered traffic model is replaced
(docs/experiment-a2.md, amended 2026-09-17); this file is the evidence behind
that amendment and the record of how the replacement was chosen. Not fixed by
plan 2's measured service curve — the degeneracy is in the traffic model.

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

## What this invalidates, under the ORIGINAL traffic model

- **H1** (in-flight concurrency dominates) — not evaluable. No signal dominates
  on p99 because p99 does not vary.
- **H2** (utilization is worst, by censoring) — not evaluable for the same
  reason. Ironically the *mechanism* H2 predicts is real and present: every
  signal is censored, not just utilization.
- **H3** (the gap halves between arms) — not evaluable.
- **H4** (ranking stable across shapes) — not evaluable; there is no stable
  ranking to be stable.
- The simulator itself is **not** implicated. It is doing exactly what it was
  asked to: replaying a load no policy can serve.

### A defect this surfaced in `h3_verdict`

`h3_verdict`'s `evaluable=False` guard fires only on an **exact** zero arm-A
gap. Noise around a true zero is not exactly zero — the original model's gap
came out at 0.314 — so the guard walks straight past the case it exists to
catch and returns an ordinary verdict on a quantity that has none. Still open;
scheduled in the statistical-layer plan, where the gap gains an interval that
the guard can test against instead of an equality against 0.0.

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

The separating candidates, as the **one-trace screen** scores them. `kept` here
counts policies surviving on that single trace and is NOT a real survival rate
— the next section shows what happens when these are re-run through real
sweeps, and it changes the answer:

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

On this table alone, 40% / 0.5 looks strongest: 5 distinct p99 values rather
than 2, and a 3.37 s spread on a 1.60 s floor. **That reading is wrong**, and
the next section is what corrects it — a screen answers "can these signals
differ at all", and nothing more.

## The candidate regime, measured at full strength

### First candidate, and why it was rejected

The screen's table is one trace per configuration, and its `kept` column counts
policies that survived the exclusion rules **on that one trace**. Read as a real
survival rate — which it is not, since a real sweep draws a fresh trace per
repetition — it recommended **baseline 40% / 0.5 additional replicas** on a
`kept` of 55/55.

Re-running the candidates through the real sweep shows why that was wrong
(5 repetitions, 3 seeds, arm A; counts are mean surviving policies out of
19 / 17 / 19):

| baseline | additional | peak/sat | queue depth | in-flight | utilization | gap |
|---|---|---|---|---|---|---|
| 40% | 0.5 | 0.90 | **2.7** | 17.0 | 19.0 | 2.143 |
| 40% | 0.75 | 1.15 | 19.0 | 17.0 | 19.0 | 0.634 |
| 20% | 1.0 | 1.20 | 19.0 | 17.0 | 19.0 | 0.925 |
| 10% | 1.0 | 1.10 | 19.0 | 17.0 | 19.0 | 0.956 |
| **70%** | **0.25** | **0.95** | **19.0** | **17.0** | **19.0** | **1.618** |
| 40% | 1.0 | 1.40 | 19.0 | 17.0 | 19.0 | 1.930 |

At 40% / 0.5 queue depth keeps under three of its nineteen policies: the load is
low enough that its lowest threshold (1 request waiting per replica) usually is
never crossed, so almost every run is excluded as `no_scaling_action`. Its
"frontier" is then three points against nineteen, and part of that 2.143 s gap
is just the mismatch — not a comparison this artifact can claim to make.

The 40% / 1.0 row is a different trap: its 1.930 s gap is noise. The one-trace
screen says every policy there produces an *identical* p99 (peak/sat 1.40 is
past the saturation threshold), so the apparent gap is the frontier selecting on
noise — the same winner's-curse effect that produced the original 0.44 s.

`a2_regime_probe.py` now runs both stages, and stage 2 is what decides.

### Adopted: baseline 70% of saturation, k = 0.25 additional replicas

Every signal keeps its full grid, and the separation is the largest of any
candidate that does. At full strength — 10 master seeds × 30 repetitions, both
arms:

| | arm A (lag p50 81.1 s) | arm C (lag p50 39.4 s) |
|---|---|---|
| queue depth | 5.9707 ± 0.0440 | 4.2340 ± 0.0383 |
| in-flight concurrency | **2.9758 ± 0.0606** | **1.6807 ± 0.0548** |
| GPU utilization | 3.0284 ± 0.0537 | 1.7094 ± 0.0355 |
| **iso-cost gap** | **3.0681 ± 0.0649** | **2.6094 ± 0.0450** |

(± is the standard error across master seeds; p99 in seconds.)

The gap is **47× its own standard error**, against the pre-registered regime's
0.314 ± 0.078 around a true zero. The ranking is identical in all 20 runs.

**What it says about the hypotheses.**

- **H1** (in-flight concurrency dominates) — **not supported.** In-flight is
  numerically best on both arms, but not distinguishably: paired against
  utilization it is +0.0527 ± 0.0794 on arm A and +0.0287 ± 0.0575 on arm C,
  both inside 2 sem. The two are a tie.
- **H2** (utilization is the worst of the three, by censoring) — **refuted.**
  Utilization is tied for *best*. The worst signal, by 2.99 ± 0.07 s on arm A
  and 2.55 ± 0.05 s on arm C, is **queue depth** — which no hypothesis named.
- **H3** (the gap at least halves from arm A to arm C) — **refuted, but
  directionally right.** The gap does shrink, significantly: −0.4587 ± 0.0596
  paired, about 15% of the arm-A gap. Halving would need arm C at or below
  1.534; it is 2.609. Faster cold starts *do* narrow the spread between signals,
  by nowhere near half.
- **H4** (ranking stable across shapes, margins shrink on the ramp) — **half
  supported, half contradicted.** See the ramp results below.

### Both shapes, measured (seed 17, 30 repetitions, arm A and arm C)

The ramp sweep the statistical-layer plan added, run on the production path.
p99 in seconds at each sweep's own iso-cost budget:

| sweep | budget | queue depth | in-flight | utilization | ranking, best → worst |
|---|---|---|---|---|---|
| step, arm A | 917.5 | 5.883 | **3.128** | 3.532 | in-flight < utilization < queue depth |
| step, arm C | 725.0 | 4.265 | 2.651 | **2.356** | utilization < in-flight < queue depth |
| ramp, arm A | 912.5 | 5.817 | **1.741** | 1.759 | in-flight < utilization < queue depth |
| ramp, arm C | 772.5 | 3.958 | 2.197 | **2.170** | utilization < in-flight < queue depth |

**H3 under both shapes.** Step: 2.754 → 1.908, where halving needs ≤ 1.377 —
**not halved**. Ramp: 4.077 → 1.787, where halving needs ≤ 2.038 — **halved**.
`h3_verdict` returns `holds=False, partial=True, evaluable=True`: "gap halved
under ramp only; published as a partial result, not as confirmation". That is
the pre-registered treatment of a single-shape halving, applied by the code
rather than by a judgement call after the fact.

**H4, clause by clause.**

- *Ranking stable across shapes* — **supported**, exactly. Each arm's ordering
  is identical on step and ramp, and queue depth is worst in all four sweeps.
  (The top two swap between *arms*, not between shapes, and by margins well
  inside the tie established above.)
- *Margins shrink on the ramp* — **contradicted on arm A**, which is where the
  prediction mattered. The gap does not shrink there; it **grows by 48%**,
  2.754 → 4.077. On arm C it is roughly flat, 1.908 → 1.787. The ramp was
  predicted to be the gentler test that compresses the differences between
  signals; on the slow-cold-start arm it separates them further than the step
  does.

This is also what produces the split H3 verdict: the ramp "halves" largely
because its arm-A gap is so much *larger*, not because its arm-C gap is
smaller. Reading the partial confirmation as evidence that faster cold starts
help more under a ramp would invert the mechanism.

One master seed with bootstrap intervals over its 30 repetitions, not the ten
independent master seeds behind the arm-A/arm-C table above — so the four gaps
carry the wider uncertainty printed by the render script, and the shape
comparison has not been repeated across master seeds.

### Why choosing this regime is not result-shopping

Selecting an operating point after seeing that it produces an effect is a real
researcher-degrees-of-freedom hazard, and it deserves a direct answer rather
than a disclaimer. Three things make this defensible, and the third is the
strongest:

1. The screening metric was **ranking-blind**: `distinct_p99`, a count of how
   many different values the 55 policies produce. Nothing in it can express a
   preference for a signal. The stage-2 tiebreak was *grid completeness* — that
   every signal keeps its policies — which is likewise not a preference for any
   one of them.
2. The search was over the **full grid**, run once, and is committed — not a
   sequence of tries stopped when one looked good.
3. **It refutes the hypotheses the artifact pre-registered.** A regime chosen to
   produce a result would produce the *predicted* result. This one says the
   predicted loser is tied for best, the worst signal is one no hypothesis
   named, and the headline effect is 15% where at least 50% was predicted.

All of it against the **placeholder service curve**. These are not results; they
are a demonstration that the machinery can now produce results. Plan 2's
measured curve is what would make them real, and it could move every number
here.

## The options considered, and the one taken

Each changes a pre-registered quantity, so the choice is disclosed in
`docs/experiment-a2.md`'s 2026-09-17 amendment along with this search.

1. **Lower the peak.** **Taken** — but not at the setting this section
   originally recommended. The first draft of this list proposed `k` at ~0.5
   additional replicas with baseline held at 40% of saturation, on the strength
   of the one-trace screen alone. Stage 2 disqualified it: at 40% / 0.5 queue
   depth survives fewer than 3 of its 19 policies, so its frontier is three
   points against nineteen and part of the gap is that mismatch. The adopted
   setting is **baseline 70% of saturation, `k` = 0.25 additional replicas**,
   the widest-separating candidate that leaves every signal its full grid. See
   "The candidate regime, measured at full strength" above.
2. ~~Raise the replica ceiling~~ — **disproven.** The cap never binds; 12, 24
   and 64 give identical results.
3. **Widen the threshold grids upward** so some thresholds sit above the peak
   signal value. Not taken, and untested: it keeps the traffic model but
   changes what "spans its own range" means, which the pre-registration argued
   for at length. Option 1 reached an evaluable experiment without touching the
   grids, so this stayed unexercised.
4. **Report the degeneracy as the result.** Not taken as the headline, and not
   discarded either: "under a spike this far above capacity the autoscaling
   signal is irrelevant to tail latency and matters only for cost" is true,
   measured, and worth publishing as a secondary finding — the cost axis does
   separate the signals even where p99 does not. It is not the artifact that
   was pre-registered, and option 1 reached a regime where the pre-registered
   question has an answer.

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
