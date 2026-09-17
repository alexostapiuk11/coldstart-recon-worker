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

Every policy scales up **8 or 9 times** and hits the 12-replica ceiling:

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
the same none. Meanwhile the 81 s cold-start lag means the fleet cannot grow
for the first 81 s of a 190 s spike, so a backlog builds that is identical
regardless of which signal ordered the (identically timed) scale-ups. The p99
is set by the lag and the arrival trace; the policy has no purchase on it.

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

## Candidate fixes (none chosen — this needs a decision)

Each changes a pre-registered quantity and so requires a dated amendment.

1. **Lower the peak** so the signals operate below saturation for part of the
   spike. The comparison needs a regime where a threshold is sometimes crossed
   and sometimes not. `k` sized to require 3 additional replicas is the
   pre-registered rule; the problem is that 3 *additional* replicas against a
   40%-of-one-replica baseline is a 8.5× jump.
2. **Raise the replica ceiling** above 12 so the cap stops binding. Cheapest
   change, but it does not address signal saturation — every threshold is still
   crossed immediately.
3. **Widen the threshold grids upward** so some thresholds sit above the peak
   signal value. Keeps the traffic model; changes what "spans its own range"
   means, which the pre-registration argued for at length.
4. **Report the degeneracy as the result.** "Under a spike this far above
   capacity, the autoscaling signal is irrelevant to tail latency and matters
   only for cost" is a defensible and genuinely useful finding — and the cost
   axis *does* separate the signals (8 distinct costs on one trace). It is not
   the artifact that was pre-registered.

## How to reproduce

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py --seeds 10 --reps 30
```

Roughly 40 minutes of CPU. `--seeds 2 --reps 3` reproduces the shape of the
result in under a minute.
