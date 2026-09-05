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
- baseline = **40%** of measured saturation.
- `k` = magnitude requiring **3 additional replicas** at the measured service
  rate.

The two absolute rates are computed from the service curve and committed
**before any policy sweep runs**.

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
| max replicas | 12 | A ceiling well above the 3 additional replicas `k` is sized to require, so the cap does not bind in the normal case and a runaway policy is still bounded. |
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

## Stopping rule

The sweep is exhaustive over the pre-declared threshold grid; there is no
sequential stopping decision to make. Repetitions per configuration are fixed
at 30 before any result is inspected.
