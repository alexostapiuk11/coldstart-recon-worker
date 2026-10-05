# Regime search on the measured curve: pass criteria, stated before the search

**Date:** 2026-10-04
**Status:** criteria fixed; the search has not run. This file is committed before
`scripts/a2_regime_search.py` runs any candidate, so the commit history shows the
criteria came first. Results are added below the line at the end, never above it.

## Why there is a search

The first full policy sweep on the measured curve (`data/a2/service-curve.json`)
was refused at the H3 gap. The figures' guard requires every frontier point to
keep at least 20 of 30 repetitions, and on arm A's step all three `queue_depth`
frontier points kept 3 or 4.

`scripts/a2_discard_diagnostic.py` traced it to the traffic model:
- the pre-registered spike peaks at 0.95 of one replica's capacity (200.6 of
  211.2 req/s; about 115 in flight against a cap of 128);
- so a queue forms only in brief bursts (median run: at or above the
  scale-up threshold in about 5% of evaluations);
- `queue_depth` scales up on a burst, and the newest replica is removed before
  it serves (scale-downs at least equal scale-ups in all 430 discarded runs);
- the 0.70 / 0.25 regime was chosen on the placeholder curve (2026-09-17
  amendment) and does not carry over to the measured one.

**What we have already seen.** The diagnostic printed per-policy p99s on arm A's
step under the current regime: `queue_depth` about 0.72 s on its few kept runs,
`in_flight_concurrency` about 0.66 s, `utilization` 0.674 s. That was seen
before these criteria were written, and the amendment that follows must say so.

## What may change

Only the two traffic knobs in `autoscale/traffic.py`:
- `BASELINE_FRACTION_OF_SATURATION` (b), now 0.70
- `ADDITIONAL_REPLICAS_AT_PEAK` (a), now 0.25

Everything else stays fixed:
- the measured curve;
- sustain 190 s, ramp 95 s, window 400 s;
- the threshold grids;
- cooldown 30 s, evaluation every 5 s, cap 12 replicas;
- the exclusion rules;
- 30 repetitions, sweep seed 17;
- the bootstrap floor of 20;
- both measured arms (A and C) and both shapes (step and ramp).

## The candidates, in order of preference

The same b × a grid the placeholder probe searched (`scripts/a2_regime_probe.py`
stage 1), so the search space is not chosen now. Order: keep b at the signed
0.70 if any a works, smallest a first; otherwise the next b down.

| b | a, in order |
|---|---|
| 0.70 | 0.25 (current; the control), 0.5, 1, 2, 3 |
| 0.40 | 0.25, 0.5, 1, 2, 3 |
| 0.20 | 0.25, 0.5, 1, 2, 3 |
| 0.10 | 0.25, 0.5, 1, 2, 3 |

**Selection rule:** the first candidate in this order that passes is the one
proposed. The search stops there; later candidates cannot change the choice.
No candidate is chosen, ranked or dropped on any gap value or on which signal
does better.

## Pass criteria

A candidate passes only if both hold, in **each** of the four headline sweeps
(arm A step, arm C step, arm A ramp, arm C ramp). Each sweep is the full
pre-registered sweep (all three signals, 30 repetitions, seed 17):

- **P1, the headline gap is computable.** `autoscale.frontier.gap_interval` (2000
  iterations, seed 17, exactly as `scripts/a2_render_figures.py` calls it)
  completes without refusing. In practice that means:
  - every signal has a frontier;
  - every frontier point kept at least 20 of 30 repetitions;
  - every frontier reaches the iso-cost budget, in the observed data and in
    every bootstrap draw.

  The search records only whether it completed and, if not, the refusal. It does
  not record or print the gap or its interval.
- **P2, the policies are not degenerate.** Across all policies in the sweep,
  there are at least 2 distinct median p99 values at 1 ms resolution. This is
  the 2026-09-17 degeneracy (all 55 identical), stated as a floor.

The utilisation sensitivity arm (`utilization_throughput`) is not a criterion.
Its gap is reported after sign-off, as the 2026-10-04 amendment requires.

## How it runs (staging cannot change the outcome)

1. **Screen** each candidate on arm A's step with `queue_depth` alone, at full
   repetitions. `queue_depth`'s frontier depends only on its own points, and the
   sweep's seeds do not involve the signal, so these are exactly the points the
   full sweep would give. A frontier point below 20 repetitions fails P1 for
   that candidate, so it is not swept further.
2. **Verify** a candidate that clears the screen with the four full sweeps,
   checked against P1 and P2.
3. Stop at the first candidate that passes.

Every candidate tried is recorded, with the stage and the reason it failed.

## If nothing passes

`queue_depth` is reported as unusable on this engine across the whole searched
traffic family, with this search as the evidence. H3 is then proposed as a
comparison of the two remaining signals, in an amendment for the owner's
sign-off. The exclusion rules are not touched either way.

## What a passing candidate does NOT settle

- **The validation operating point.** `autoscale.validation_schedule` scales
  the same spike shape. A larger a can push the peak past two pinned
  replicas' capacity, and `build_schedule` then refuses (predicted unfinished
  work). The validation replicas, rates and LB probe ladder are re-derived
  afterwards and may need their own amendment, with new paid-run costs.
- **Adoption.** A passing candidate goes into a written amendment to
  `docs/experiment-a2.md` for the owner's sign-off, disclosing this search and
  the p99s already seen. The full figure sweep re-runs only after that.

---

## Results

(Appended after the search runs.)
