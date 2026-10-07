# Finding (exploratory): the validation gate's miss is mostly the swap cost, which varies by pod, and a fixed swap cost cannot close it

**Date:** 2026-10-07
**Status:** exploratory, run after the gate's verdict was known. It explains the
verdict; it does not change or replace it. `data/a4/analysis.json` keeps the
verdict as the registered gate produced it. Reproduce with
`PYTHONPATH=. .venv/bin/python scripts/a4_diagnose_validation.py`; the output is
`data/a4/exploratory/validation-diagnosis.json`.

## The verdict it explains

The gate **failed**: 10 of 13 judged bins missed, the largest by 67.8 s, and every
miss on the same side. The simulator predicted the latency higher than the engine's:
in the busy bins by a factor of 1.1 to 2.0, and by 4.5 and 6.9 in two bins just after
a burst. The swap count agreed: predicted 11, real 10 in all three repeats.

## The two hypotheses tried

**1. Host speed (the curve's pod against the replays' pod).** The solo curve was
measured almost entirely on one pod (`2vobcb310fgy1k`; the valid solo runs came from
two pods, and 133 of the 139 valid cell runs are from that one);
the three replays ran on another (`7db5ue5kw9yfjf`). The curve was sped up uniformly
and the gate's prediction re-run:

| curve speed | bins agreeing of 13 | largest miss |
|---|---|---|
| 1.00 (as gated) | 3 | 67.8 s |
| 1.05 | 2 | 64.5 s |
| 1.10 | 0 | 61.6 s |
| 1.20 | 1 | 54.9 s |
| 1.30 | 1 | 50.5 s |

A uniform speed difference of up to 30% does not close the miss. It is not the
explanation, and nothing here measured the two pods' relative speed directly.

**2. The swap time charged per swap.** The gate charges 37.8 s, the median of the
swap campaign (run on `2vobcb310fgy1k`). The swaps inside the replays took
**25.5, 23.8 and 25.0 s** (medians of ten each; range 22 to 28 s), on the replay pod.
Swap time also differs elsewhere in this experiment: 29 to 35 s on the
reconnaissance pod. So swap cost varies by pod, by about 50% across the pods seen.
Re-running the prediction with other charges:

| swap charged | bins agreeing of 13 | largest miss | swaps predicted (real 10) |
|---|---|---|---|
| 38 s (as gated) | 2 | 69.2 s | 11 |
| 33 s | 4 | 37.7 s | 10 |
| 30 s | 2 | 19.7 s | 10 |
| 28 s | 6 | 7.7 s | 10 |
| 26 s | 4 | 9.3 s | 10 |
| 25 s | 2 | 10.4 s | 10 |
| 24 s | 1 | 11.3 s | 10 |
| 22 s | 1 | 20.1 s | 10 |

At the 37.8 s the gate charged, a swap cost 12 s more than it cost on the replay pod,
ten times over, in a regime where the bursts offer about 1.2 times what one GPU can
serve, so the error piles up as queue delay. That is most of the miss, and it makes
the predicted swap count too high by one.

## What it does not explain

Charging each repeat its own median real swap time and holding each repeat to its
own prediction (artifact 2's per-repeat construction) **still fails**: 12 of 13
judged bins miss, the largest by 10.4 s. And the direction has flipped. With the
swap cost the repeats paid, the simulator predicts the latency **lower** than the
engine's in almost every bin: for example 18.4 s predicted against 19.5 to 24.2 s
real in the first bin, 43.6 against 44.4 to 52.9 s, and 10.6 against 20.5 to 23.0 s
late in the trace. The numbers per bin are in the output file.

So no single fixed swap cost matches the real system. About 38 s over-predicts and
about 25 s under-predicts, and between them (28 s gets 6 of 13 bins) it still falls
short of a gate whose band is three nearly identical repeats widened by 0.001 s.
The simulator charges a swap as a fixed stall of the whole pool. Something in the
real swap costs a request more than the swap's start-to-ready time (for example
requests drained from the old engine, or the first requests on a fresh engine being
slower), and the model has no term for it. This was not measured here.

## For the results

- **The verdict stands.** The registered gate failed, and the failure is a real
  model-against-reality gap, not only a host artefact.
- **Swap cost is pod-dependent by about 50%** on this RTX 4090 pool. The simulator
  takes one swap distribution from one pod. Every decision rule and crossover that
  depends on the swap cost inherits that variance; the post states it beside the
  failed verdict.
- **A calibrated re-validation would not pass,** so it would not rescue the
  frontiers. It could be run, as an amendment, if the owner wants the number: it
  needs no new GPU time, because each replay records its own swaps.
- **What would need measuring to go further:** the real swap's effect on requests in
  flight and just after (the stall the model leaves out), on one pod, with the
  replay's own requests. That needs GPU time and is not part of this finding.
