# Finding (exploratory): the validation gate failed on host speed, not on the engine setting

**Date:** 2026-10-05
**Status:** exploratory, run after the gate's verdict was known. It explains the
verdict; it does not change or replace it.

## The verdict it explains

The engine-arrival gate (amendment 2026-10-05, third; `data/a2/validation-engine/`)
**failed**: 34 of 37 judged bins missed, every miss on the same side. The simulator
predicted the engine slower than it was:
- the engine's latency a median 14% below the prediction, over the judged bins;
- by seconds in the queues after the load balancer released bursts.

## The question

Two differences separate the validation runs from the measured curve:
- the host;
- `--max-num-seqs`: 128 for validation (amendment 2026-10-04, second) against 256
  for the curve.

## The measurement

`scripts/run_service_sweep.py` on the curve's own endpoint, template and image.
Levels 32, 64 and 128, three runs each, once with each setting. All 18 runs landed
on one host, `daps3haubwrzbn`. The curve's levels 32-128 were measured on
`ozhetwnhompob9`. Stores: `data/a2/exploratory/maxseqs128.jsonl` and
`maxseqs256.jsonl`.

| level | max-num-seqs 128 | max-num-seqs 256 | committed curve |
|---|---|---|---|
| 32 | 0.351 s (×0.93) | 0.359 s (×0.96) | 0.376 s |
| 64 | 0.411 s (×0.94) | 0.408 s (×0.93) | 0.439 s |
| 128 | 0.546 s (×0.90) | 0.543 s (×0.90) | 0.606 s |

Medians of three runs. The ratio is to the committed curve.

## What it shows

- **The setting does not matter.** At each level the two arms agree within their
  own run-to-run range.
- **The host does.** On `daps3haubwrzbn` the engine has 4-10% lower latency than
  the curve, and the gap widens with load. At level 128 it is about the size of the
  gate's miss.
- **The validation repeats ran on another host,** `ku80i8usxw3st5`, whose speed
  was not measured here. Its own records give one reading: requests that arrived
  with 90 to 110 in flight on the engine took a median 0.494 s, against 0.533 s for
  the curve and 0.487 s for `daps3haubwrzbn` at `--max-num-seqs` 128, both
  interpolated to 100 in flight. That is consistent with a host about as fast as
  `daps3haubwrzbn`.

**For the results:** the simulator's service curve is one host's. Host-to-host
speed on this RTX 4090 pool varies by at least about 10% at high load. The model
carries none of that variance, and the gate failed on it. Every frontier and the
H3 result inherit a curve from a host about 10% slower than at least two others in
the pool. The post states that beside the failed verdict.

Not established: whether `ozhetwnhompob9` is slow or the other two are fast, nor
how wide the spread across the pool is. Three hosts are not a distribution.

Corrected 2026-10-05: the miss was first stated as "about 12% at around 110 in
flight" and the third host's reading as 0.494 s against the curve's 0.559 s; the
post's analysis (`data/a2/post-analysis.json`) gives the median over the judged
bins, 14%, and the 90-110 in-flight reading against references interpolated to
100. "4-10% faster" now reads "4-10% lower latency": the numbers are latency
ratios, not speeds.
