# Finding (exploratory): H3's answer under the service-speed error the validation found

**Date:** 2026-10-05
**Status:** exploratory, not pre-registered. It was run after both validation attempts failed
and after the simulator's own H3 answer was known. It is a sensitivity check on an
**unvalidated** simulator, not a measured result.

## Why

The validation gate failed twice:
- uncalibrated, the simulator predicted the engine about 12% too slow;
- host-calibrated, it predicted the engine about 12% too fast.

See `docs/findings-a2-validation-host-speed.md` and `data/a2/validation-*/verdict.json`.
In this traffic regime the spike peaks at 1.2x one replica's measured capacity, so a 12%
service-speed error changes the overload, and with it the backlog that drives the
comparison. The question is whether the simulator's H3 answer depends on that error.

## Method

`scripts/a2_sensitivity_service_speed.py` (commit 5c50994).
- The traffic is held at the committed curve's absolute rates.
- Every engine latency is multiplied by 0.88 (12% faster) or 1.12 (12% slower).
- The four headline sweeps run per factor: arm A and arm C, step and ramp. They use the
  headline's seed, grids and 30 repetitions, the bootstrap interval, and `h3_verdict`.
- Every sweep kept all 55 policies with 0 discards.

Data: `data/a2/exploratory/sensitivity-service-speed.json`.

## Result

The inter-signal p99 gap at iso-cost, in seconds, with 95% bootstrap intervals:

| engine speed | step, arm A (81 s) | step, arm C (39 s) | ramp, arm A | ramp, arm C | H3 |
|---|---|---|---|---|---|
| x0.88 (12% faster) | 0.139 [0.051, 0.625] | 1.379 [1.185, 1.911] | 3.834 [3.669, 4.302] | 3.417 [3.315, 3.813] | does not hold |
| x1.00 (committed curve) | 0.082 [0.050, 1.061] | 3.955 [3.516, 4.558] | 8.249 [7.894, 8.598] | 10.873 [10.617, 11.052] | does not hold |
| x1.12 (12% slower) | 0.173 [0.078, 1.268] | 1.260 [0.955, 1.584] | 8.714 [8.149, 9.128] | 16.710 [16.505, 17.015] | does not hold |

## What it shows

- **H3's pre-registered bet fails throughout the error band.** At all three speeds and both
  shapes, the gap does not halve when the cold start halves. This conclusion does not depend
  on the 12% calibration error.
- **On the step, the gap grows with a faster cold start at all three speeds**: about 7x to
  48x. The direction is robust. The size is not: the gap at the faster cold start is
  1.3-4.0 s depending on the engine's speed.
- **On the ramp, the direction depends on the engine's speed.** The gap grows at x1.00 and
  x1.12, but shrinks by about 11% at x0.88. So "faster cold starts make the signal matter
  more" holds for the step, and for the ramp only if the engine is not faster than measured.
- **The worst signal is the same throughout.** Queue depth is the worst signal on p99 at
  arm C in every case. In-flight concurrency and GPU utilisation reach about the same p99,
  with utilisation always at the replica cap (the highest cost).

## Limits

This changes the service speed only. It inherits everything else the validation left
untested: the closed-loop autoscaling dynamics, the even split across replicas against
RunPod's fill-first routing, and the load balancer's stalls. It also tests one kind of
error, a uniform scale, not a change in the curve's shape.
