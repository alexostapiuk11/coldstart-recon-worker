# Artifact 1 — Pre-registration

Committed before the first paid measurement run. The git timestamp on this file
is the evidence that the hypotheses below were fixed in advance.

## Configuration held fixed

Endpoint ka5mryakkxumew, EU-RO-1, NVIDIA GeForce RTX 4090 (24 GB), network
volume 9c7ut2slrd, template mzadx4qugv, image
ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:d41f67dd59981558244582d814a195d89e5c810d1cc72e1141f1a00a100983e9,
vLLM 0.27.1, Qwen/Qwen3-8B revision b968826d9c46dd6066d109eabc6255188de91218,
--max-model-len 8192, gpu_memory_utilization at the 0.9 default, FlashBoot off,
workersMin 0, workersMax 1.

`--max-model-len 8192` is not a default. Qwen3-8B's native 40960 context needs
more KV cache than a 24 GB card has left after 15.27 GiB of weights, and the
engine refuses to start. 8192 fits with headroom and keeps supported
concurrency non-degenerate at roughly four sequences.

Any change to a value above ends the experiment rather than continuing across
the boundary.

The image digest above has been re-pinned twice, both times before any
measurement that this campaign publishes.

The first re-pin: the vendored `coldstart/` package was found not to trigger an
image rebuild in CI, so the endpoint was serving an image 20+ commits stale,
predating the pre-probe compile-cache observation the arm-state exclusion rule
depends on. No data had been collected under it.

The second re-pin, and the campaign restart it forced: a first window of 27 runs
showed arm A failing 40% while arm B failed 0%. The cause was arm A's per-run
cold `HF_HOME` never being removed -- ~15.3 GiB of weights per run against a
60 GB container disk, so the fourth arm A run on any given worker died with
"No space left on device" before the engine started, resetting whenever the
worker recycled. That attrition falls on one arm, so it would have biased the
primary A->B contrast through survivorship rather than appearing as noise. The
worker now frees each run's cold directories after the run, and also empties
the cold roots BEFORE each run -- the first fix was insufficient on its own,
because a worker can inherit a disk already filled by runs from an earlier
image that had no cleanup, which end-cleanup cannot remove.

Those 27 runs are retained at `data/discarded-window-0.jsonl` and are excluded
from every published number. They are kept because they are the evidence for
that defect, not because they are data. This is the boundary rule in this
document applied to itself: the pinned image changed, so the campaign restarts
rather than splicing results across the change.

## Arms

Cache configuration is the only thing that differs between arms
(`coldstart/cache_config.py`).

| Arm | Weights | Compile cache |
|---|---|---|
| A | hub, per-run cold path | cold, per-run path |
| B | network volume | cold, per-run path |
| C | network volume | warm, on the volume |

**Arm C requires a primed volume, and priming is not a measured run.** A warm
compile cache has to be created before arm C can measure one. Before the
campaign opens, arm C is run twice against the volume and both runs are written
to a separate store (`data/priming.jsonl`), never to `data/campaign.jsonl`. The
first compiles cold and writes the cache; the second must report
`compile_cache_observed = true` with an `S4b` under one second, which is the
check that the volume is genuinely warm.

Priming runs are excluded from every published number. They are recorded and
committed so a reader can see they happened and what they cost, not because they
are data. Without this step arm C's early runs would compile cold and its later
runs would not, making the arm a mixture whose effect grows with run index --
which would look like a real trend.

## Hypotheses

**H1 (decomposition).** Weight handling is the dominant directly-measured stage
— more than half of `T_process` — in the fully uncached arm.

**H2 (weight caching).** Pre-staging weights on a network volume materially
reduces weight-handling time relative to fetching from the hub.

**H3 (compile caching).** Engine compilation on a cold artifact cache is a
non-trivial term in `S4`, and warming that cache materially reduces engine-init
time. Confirmed measurable by the reconnaissance run: this vLLM version
compiles at startup, `torch.compile took 38.96 s in total` against a 53.73 s
engine init.

**H4 (tail).** The spread between median and p95 total cold start is driven
substantially by host heterogeneity rather than by variance within any single
stage.

**H4 may not be answerable on this provider, and that is recorded before any
data.** Host placement is RunPod's to decide, not ours. The driver submits
serially, so only one job is ever in flight and no endpoint setting changes
this; `idleTimeout` is already at its 5 s minimum, so workers do terminate
between runs, and RunPod still re-allocates the same physical machine because
it has the image cached. Across 27 runs of a discarded first window we observed
**2 distinct hosts, one of them serving 23 runs**.

The commitment: publish the distinct host count and the per-host run
distribution alongside H4, whatever they turn out to be, and state plainly that
H4 is under-powered if the campaign lands on a handful of machines. No
post-hoc reframing, and no quiet omission of the host count if it is
embarrassing.

Note this cuts the other way for the secondary analysis: the same concentration
makes within-host triples plentiful, so the paired contrast should be well
supplied even when H4 is not. That asymmetry is a fact about renting elastic
capacity, and it is worth reporting as one.

**H5 (compile cache buys KV capacity).** A cold compile inflates the engine's
measured peak activation, reducing the KV cache budget. Arm C therefore shows
higher `kv_capacity_tokens` than arm B under otherwise identical configuration.

H5 is new in this pre-registration and is stated as a hypothesis, not a result.
It comes from the reconnaissance captures, where peak activation was 1.18 GiB
on a cold compile and 0.19 GiB on a warm one with every other memory term
identical, and KV capacity was 35,792 versus 43,040 tokens. That is n=1 per
condition and confounded by worker reuse, which is exactly why it is being
predicted in advance rather than reported from those captures.

The relative ranking of H2 and H3 is the most interesting result available.

## Analysis plan

Every derived row comes from `coldstart.analysis.metrics.derive`. Rows are
partitioned by `coldstart.analysis.pipeline.partition` before any figure or
statistic sees them; consistency is a requirement of every preset.

**Sampling: windows, and what the spacing actually was.** The design calls for
at least three windows on separate days, because fleet conditions on rented
elastic capacity vary by time and day and a single-session campaign would
confound the arm effect with that session's conditions — a confound that cannot
be detected afterwards from the stored records.

What actually happened is published rather than implied. Window 1's 100 runs all
fell on 2026-09-02 UTC. Window 2 was started a few hours later, after the UTC
day boundary but within the same working session, so it satisfies "a different
day" by calendar and only partially by intent. Every run carries `t0_wall`, so
the true spacing between windows is recoverable from the published records, and
the post states it. A reader who thinks two windows hours apart sample one set
of fleet conditions is entitled to discount the fleet-drift mitigation
accordingly; that judgement is theirs to make with the timestamps in hand, not
ours to obscure by reporting only a window count.

Interleaving within each window is unaffected — it protects against drift inside
a window regardless of when the window ran.

Primary comparison unit: `t_weights` for A→B, `t_compile` for B→C.
Reported for each contrast: median difference with a 95% bootstrap percentile
interval (`bootstrap_median_diff`, 10,000 iterations).
**The interval on the difference of the two contrasts
(`bootstrap_contrast_difference`) is reported before any ranking claim is
made, and it is computed on `t_total` across all three arms** -- not on the
two mechanism units above. `bootstrap_contrast_difference` computes
`(median(A) - median(B)) - (median(B) - median(C))`, using B in both halves, so
it requires one shared unit; subtracting a `t_weights` contrast from a
`t_compile` one would difference two different quantities. `t_total` is the
honest common unit for the ranking claim, which asks which cache buys back more
cold start.

Secondary, supporting only: within-host triples
(`bootstrap_paired_median_diff`), reported with wider intervals and never as
the headline.

Distributions are reported as p50/p90/p95 and a full ECDF. **No p99** — at
~100 runs per arm that is one or two observations.

**Two things window 1 established that change how results must be reported,
recorded here before the remaining windows run.**

*The warmup curve is flat, and that is the finding.* Request 1 is 7.7% slower
than steady state — inside the ±10% tolerance — so `T_fast` is request 1 and
"ready is not fast" does not hold at this configuration. The engine's own log
explains it: vLLM runs a profiling forward pass and captures 86 CUDA graph
shapes *before* answering `/health`, then serves. The warmup cost is real and
large, but it is paid inside `S4` where the waterfall already shows it, not
served to users afterwards. Figure 2 will report this rather than an assumed
penalty. A side diagnostic, run on a separate template and never on the pinned
campaign image, asks whether longer generations change it; its results are
supporting context, not pre-registered data.

*First-touch runs must be separated before any distribution is published.* The
campaign's first run carried `t_platform` of 2174 s — a cold image pull — which
is 17.8x the next slowest run and makes a pooled ECDF unreadable. The threats
table already required a first-touch versus repeat-host flag reported
separately; it is derived from the store (a run is first-touch when it is the
first on its `host_id`) rather than recorded by the worker, so it applies
retroactively to every run already collected.

## Exclusion rules, fixed in advance

- A run whose clocks fail `check_consistency` is discarded, reason recorded.
- A run whose observed compile-cache state does not match its arm's expected
  state is discarded, reason recorded.
- A failed run is counted in the failure-rate table, never in the discard
  table, and never substitutes for a missing arm in a within-host triple.
- Failure rate and discard rate are published per arm.
- No run is retried in place.

## Stopping rule

Stop at 100 runs per arm, or when the intervals on **both** contrasts are tight
enough to distinguish a large effect from no effect — whichever comes first.
Both must qualify.

## Headline selection rule

Rank candidate findings by how far they transfer to a reader on different
infrastructure, and lead with the most transferable. Committed now so the
headline cannot be chosen by which result cost the most effort.
