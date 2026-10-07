<!--
Permanent slug: /experiments/vllm-multi-lora-capacity
Never changes, per the portfolio contract (artifact 1 spec §3). It names the
question rather than the headline, so the title can still be reworded at
publication without breaking the URL.

The absolute canonical URL is set once the domain is live; until then the slug
is published as a path. If publication slips past the date below, update the
date -- it is the publication date, not the date the draft was finished.
-->

# How many LoRA adapters actually fit on one GPU

**Oleksii Ostapiuk** · 2026-10-07 · `/experiments/vllm-multi-lora-capacity`

I served one base model, Qwen3-4B, on one RTX 4090 with vLLM 0.27.1, registered
between 1 and 64 rank-16 LoRA adapters on it, and scheduled 24 server starts at
each count. Every start carried both kinds of load in turn: all of it on a
single adapter, and all of it spread over every registered adapter. This post
reports what adding adapters cost in throughput, latency and KV capacity on that
configuration, and converts the result into tenants per GPU and dollars. It is a
measurement of this configuration, not of vLLM in general. Every result below
re-derives from committed data on a laptop, with no GPU.

Harness, raw data, analysis and figure code:
[github.com/alexostapiuk11/coldstart-recon-worker](https://github.com/alexostapiuk11/coldstart-recon-worker).
The pre-registration, its three amendments and the spend record:
[`docs/experiment-a5.md`](experiment-a5.md).

The table below is generated from `data/a5/analysis.json` by
`scripts/a5_numbers.py`, and a test fails if it is edited by hand or left stale.

<!-- a5-numbers:start -->
| quantity | value |
|---|---|
| Equivalence gate | pass, n = 137 instances |
| Knee | between 8 and 16 slots |
| Heterogeneity cost at 64 slots, throughput | -1,289.6 tokens/s (95% interval -1,308.8 to -1,273.5 tokens/s) |
| Heterogeneity cost at 64 slots, TTFT p50 | 28.1 ms (95% interval 23.0 to 30.6 ms) |
| Registered-slot cost at 64 slots, throughput | -449.7 tokens/s (95% interval -486.0 to -425.1 tokens/s) |
| Throughput at 1 slot | 3,577 tokens/s |
| Spread throughput at 64 slots | 1,835 tokens/s |
| KV capacity, 1 slot to top | 78,208 to 42,864 tokens |
| Tenants per GPU | 8 (bound by slots; a lower bound) |
| Cost per tenant per month, dedicated | $850.43 |
| Cost per tenant per month, swapped | $404.97 |
| Cost per tenant per month, adapter | $101.24 (an upper bound) |
<!-- a5-numbers:end -->

---

## Headline

The knee is defined on spread-regime throughput, with every registered adapter
active: the fraction of throughput lost each time the adapter count doubles,
against a threshold of 10% per doubling fixed before any measured run. From 8
to 16 adapters the loss is **10.7%, 95% bootstrap interval [9.2%, 11.5%]**. The
point estimate crosses 10%; the interval does not clear it, so this crossing is
not resolved. The next two doublings are: 16.8% [16.1%, 17.9%] from 16 to 32,
and 24.2% [23.7%, 24.8%] from 32 to 64. The registered rule takes the first
point estimate above the threshold, so the knee lies between 8 and 16 adapters.
Brackets in this post are 95% bootstrap intervals of the median across server
starts, except in the equivalence gate, whose rule uses 90%.

> **8 tenants per GPU, at $101.24 per tenant per month.** The 8 is a lower
> bound on tenants, so the $101.24 is an upper bound on cost.

The assumptions behind the dollars, all fixed before measurement except the
rate, which an amendment replaced before the campaign ran:

| assumption | value |
|---|---|
| GPU hourly rate | $1.1095, an estimate from one billing sample (see Limits) |
| hours in a month | 730 |
| requests per tenant per month | 100,000 |
| peak-to-average factor | 3.0 |
| SLO | TTFT p95 at most 1 s |

At 8 adapters the spread regime's TTFT p95 is 115 ms [110, 130], inside the
SLO. Under these assumptions measured throughput alone would allow 1,784
tenants, and KV capacity 250. The slot knee binds first.

Two qualifications belong next to the headline, not under it. First, all 64
adapters fit, in the sense that they served within the SLO: at 64 the spread
regime's TTFT p95 is 141 ms [138, 151]. The 8 is where each further doubling
starts costing more than a tenth of the throughput, which is what the registered
rule counts as capacity. Second, if the unresolved 8-to-16 crossing were noise,
the slot bound would be 16, because the next crossing's lower bound does clear
10%, and the cost per tenant would halve. The rule was registered to err toward
fewer tenants, and here it does.

The decomposition behind the knee: at 64 adapters, spreading the load over all
of them instead of concentrating it on one costs **−1,290 tokens/s [−1,309,
−1,274]**. Having 64 slots registered with the load on one adapter, against one
slot, costs **−450 tokens/s [−486, −425]**. The intervals are far apart, and
the heterogeneity cost is about 2.9 times the registered-slot cost. Registered
slots also cost KV capacity, 78,208 tokens at 1 slot against 42,864 at 64,
identical in every start, but at this request shape that memory cannot move
latency or throughput; the section on memory says why.

---

## The main chart

![Two panels against adapters registered, 1 to 64 GPU slots on a doubling axis. Top: throughput in tokens per second. The concentrated regime, one adapter active, falls from about 3,577 at 1 slot to 3,127 at 64; the spread regime, all registered adapters active, falls from about 3,568 to 1,835; the gap between the two lines is shaded as the heterogeneity cost and widens from 8 slots on. Bottom: TTFT p50 in seconds, spread rising from about 0.063 to 0.101 and concentrated from about 0.062 to 0.073. Points are medians over 23 to 24 server starts, with 95% bootstrap intervals of the median.](figures/a5/throughput_ttft.png)

Blue is the **concentrated** regime: the load generator assigns every request
from a list of one adapter, so one adapter is active whatever is registered.
Red is the **spread** regime: requests go round-robin over all N registered
adapters, so at a concurrency of 64 there are up to min(N, 64) distinct adapters
in flight.

**The shaded gap is the heterogeneity cost.** At each registered count it is
what it costs for the load to be spread across every adapter rather than shared
by one, with the slots, the memory and the server start held fixed. Each start
runs both regimes, two phases each, in a random order drawn per start, so the
gap is a difference within one start and start-to-start variation cancels out
of it. **The blue line's own slope is the registered-slot cost**: what more
registered slots cost when one adapter still carries all the load.

The bars are 95% bootstrap intervals of the median across 23 or 24 starts.
They say where the median would land if this 24-start experiment were re-run.
They do not say where a single start lands: individual starts scatter more
widely than the bars. A narrow bar says the median is pinned down, not that
every start behaves alike.

Read off the analysis: concentrated throughput goes from 3,577 tokens/s [3,555,
3,598] at 1 slot to 3,127 [3,100, 3,140] at 64. Spread goes from 3,568 [3,554,
3,582] to 1,835 [1,824, 1,844], about half. Spread TTFT p50 goes from 63 ms
[61, 69] to 101 ms [98, 104], and p95 from 108 ms [102, 123] to 141 ms [138,
151]. At 64 the heterogeneity cost on TTFT p50 is +28.1 ms [+23.0, +30.6].

The regimes differed as designed. vLLM exposes the scheduler's running set of
adapters as a gauge, which a sampler read once a second through every phase. In
every one of the 167 publishable sweep starts, the largest number of distinct
adapters in a single sample was exactly N during spread phases and exactly 1
during concentrated phases. That gauge is a sample of scheduler state, not a
count per batch.

---

## Registered is not active

In vLLM 0.27.1, one setting, `max_loras`, is two things at once. It is the
number of GPU slots: weight buffers are allocated per slot, sized to
`max_lora_rank`, whether or not an adapter occupies the slot. And it is the cap
on distinct adapters in one batch. A second setting, `max_cpu_loras`, holds
adapters in CPU memory beyond the slots and copies them in on demand. Here every
sweep point sets `max_loras = max_cpu_loras = N`, so every registered adapter is
resident in a GPU slot, and "registered" in this post refers to a slot. That
makes the slot count and the in-batch cap the same knob, so registered and active
cannot be separated by configuration. The two regimes separate them by traffic
instead: same slots, different number of adapters actually in the batch.

**Why a batch that spans many adapters costs more than one that shares an
adapter.** A LoRA adapter adds two small matrices to each of the seven
projections it targets. For a batch that shares one adapter, every row of the
batch is multiplied by the same pair, so the extra work is one pair of
multiplications per projection over the whole batch, and the adapter's weights
are read from GPU memory once per step. For a batch spanning 64 adapters, each
row needs its own adapter's pair: the kernel splits the batch by adapter, reads
64 sets of weights per projection per step instead of one, and does 64 small
multiplications instead of one larger one, at every layer of every decode step.
That is the mechanism as the kernels are organised, and the shaded gap is
consistent with it; this campaign measured the cost's size, not its breakdown
inside the kernel.

**Why the concentrated regime pays too.** In vLLM 0.27.1 with the default
`specialize_active_lora = False`, one dimension of the LoRA kernels' launch grid
is `max_loras + 1`, whatever the batch holds. Slices for empty slots exit early
but are still launched: at 64 slots a concentrated batch launches 65 slices per
LoRA operation, against 2 at 1 slot. So the concentrated regime's change with N
is not memory. I call it the **registered-slot cost**.

| slots | heterogeneity cost (tokens/s) | registered-slot cost (tokens/s) |
|---:|---|---|
| 2 | −43 [−81, −31] | −4 [−36, +21] |
| 4 | −105 [−153, −67] | −34 [−67, +16] |
| 8 | −284 [−312, −235] | −41 [−77, −17] |
| 16 | −574 [−585, −521] | −107 [−135, −76] |
| 32 | −905 [−941, −882] | −257 [−284, −219] |
| 64 | −1,290 [−1,309, −1,274] | −450 [−486, −425] |

Medians with 95% bootstrap intervals. The heterogeneity cost is paired within
each start; the registered-slot cost compares concentrated throughput at N with
concentrated throughput at 1 slot, across starts. At 1 slot both are zero by
construction: the two regimes coincide there, and the registered-slot cost is
measured against 1 slot. Hypothesis H1, a heterogeneity cost below zero at every
point above 1 and growing with slots, holds: every interval in the first column
is below zero, and the costs grow. H2, heterogeneity
cost larger than registered-slot cost at 64, holds.

**What was not measured.** The pre-registration planned a diagnostic to split
the registered-slot cost: re-run the concentrated regime with
`--specialize-active-lora`, which captures CUDA graphs specialized for the
number of active adapters, so a concentrated batch would launch one or two
slices at any N. The difference in differences would have isolated the
launch-grid overhead from any other slot-count cost. At 64 slots that instance
ran out of GPU memory during CUDA-graph capture at both memory budgets tried,
0.85 and 0.80: it asked for 4.5 times as many graphs as the plain 64-slot
configuration. I cut the diagnostic before the first measured run, and its
hypothesis, H4, was withdrawn with it. So the −450 tokens/s is reported
unsplit. I do not know how much of it is the launch grid and how much is
host-side bookkeeping or anything else that scales with slots. I do know it is
not memory.

**The gauge has a cost of its own, and it is small.** The running-adapters
gauge in vLLM 0.27.1 creates a new label series on every stats record, and the
spread regime produces a new combination almost every step, so its overhead
lands in the heterogeneity cost. Control starts at 64 slots with
`--disable-log-stats`, 24 of them, bound it: the heterogeneity cost with the
gauge on minus with it off is +17 tokens/s [−19, +57]. The interval contains
zero; whatever the gauge costs here is too small to separate from noise, and at
most about 57 tokens/s against a heterogeneity cost of 1,290. It is vLLM's
default behaviour, so it is also what a default deployment pays.

---

## Tenants per GPU, and what one costs

Tenants per GPU is the smallest of three bounds, each computed at the last
sweep point below the knee, 8 slots:

| bound | tenants | how |
|---|---:|---|
| slots | **8** | the slot count below the knee; a lower bound, because vLLM can also hold adapters in CPU memory and swap them into slots |
| throughput | 1,784 | measured request throughput divided by one tenant's peak rate, valid only because TTFT p95 meets the SLO |
| memory | 250 | the KV concurrency ceiling at an 8,192-token context, through Little's law (see the section on memory) |

One tenant's peak rate is 100,000 requests a month, divided by the seconds in a
730-hour month, times the peak-to-average factor of 3.0: about 0.114 requests a
second. The slot bound binds by a wide margin: the next smallest, memory, is
about 31 times larger.

**What the knee says to a product that gives each customer a fine-tune.** The
count that sets the price is not how many customers' adapters are registered.
It is how many of them are in the same batch at once. If customers' traffic
overlaps, so that most of a GPU's adapters are active together, then at this
shape every doubling past about 8 co-active adapters costs more than a tenth of
the GPU's throughput, and every customer added makes every other customer's
requests slower. If traffic is concentrated, so that few adapters are active
at any moment, the cost is the registered-slot cost alone, which is under 35% of
the heterogeneity cost at every sweep point. The same 64 adapters cost very
different amounts depending on how their customers' traffic
lines up in time, and that is a property of the customer base, not of the GPU.
It is also why the slot bound sits so far below the throughput bound: the GPU
has the request capacity for far more tenants than the knee lets it hold
efficiently. Spread throughput at 64 adapters, 1,835 tokens/s [1,824, 1,844],
is about 115 requests a second, against about 7.3 a second for 64 tenants at
peak under these assumptions. A product could run past the knee and still meet
the SLO; it would pay for that in throughput per GPU.

![Horizontal bars of cost per tenant per month in US dollars, all at 1.1095 dollars per GPU-hour. Dedicated, 850 dollars, and swapped, 405 dollars, come from artifact 4's simulator of a fleet of Qwen3-1.7B models at its bursty regime with Zipf skew 1.0. Adapter, 101 dollars, is this artifact's Qwen3-4B at 8 tenants per GPU, drawn hatched because it is an upper bound: tenants are a lower bound. A note under the axis gives the GPU rate and the requests per tenant, says the adapter bar is an upper bound, names the model classes (dedicated and swapped from artifact 4's simulator on Qwen3-1.7B, adapter on Qwen3-4B), and says the simulator failed its validation, with 10 of 13 bins missed, so none of its numbers is validated. The two sides use different model sizes, so the bars are not a like-for-like comparison.](figures/a5/cost_per_tenant.png)

| strategy | tenants per GPU | cost per tenant per month | source |
|---|---|---:|---|
| dedicated | artifact 4's sizing | $850.43 | artifact 4's simulator, bursty regime, s = 1.0, Qwen3-1.7B; not validated |
| swapped | artifact 4's sizing | $404.97 | artifact 4's simulator, bursty regime, s = 1.0, Qwen3-1.7B; not validated |
| adapter | 8, a lower bound | $101.24, an upper bound | this artifact, Qwen3-4B |

The adapter cost is the GPU's monthly cost, $1.1095 × 730 hours, divided by 8
tenants. The section on swapping models says why the first two rows and the
third are not like-for-like.

**The first two rows come from a simulator that failed its own test.** Artifact
4's costs come from a simulator fed with measured inputs, and artifact 4
pre-registered a test the simulator had to pass before it was trusted:
reproduce a real one-GPU, three-model replay at its bursty regime, s = 1.0.
That operating point is the reference row used here. The validation outcome is
failed: 10 of 13 judged bins were outside the band of three real repeats (3
agreed), the largest miss was 67.8 s, and 1 of 2 held-out interference cells
passed. The swap count agreed: 11 predicted, 10 real in all three repeats.
Nothing in artifact 4's cost file is validated, at the reference point or
anywhere else. The section on swapping models says what that means for each
bar.

---

## Synthetic adapters, and how I know they are valid here

Every adapter in the sweep is synthetic: weights drawn from a seeded normal
distribution, in the shape of a rank-16 LoRA on the seven projections. There
are not 64 public adapters for this base model in that exact shape: of 261
Hugging Face Hub adapters for `Qwen/Qwen3-4B` that reconnaissance examined, 7
qualified.

**Why the weight values cannot change serving cost.** The work a LoRA adds is
set by shapes, not by values. vLLM runs the kernel at the buffer rank,
`max_lora_rank`, so every adapter in a slot is multiplied as a 16-wide pair of
matrices on the same seven projections, whatever numbers are in it. A dense
matrix multiplication does the same arithmetic and reads the same bytes for any
values. The one path I know of by which weights reach serving cost is what they
make the model generate, and that path is closed here: every phase runs with
ignore-EOS, so every request produces exactly 16 output tokens, and prefix
caching is off, so no adapter's prompt is served from a cache another missed.
What this licenses: random adapters measure the serving cost of any adapter with
this rank, these target modules and this base model. It licenses nothing about
output quality, and nothing about other ranks.

That is an argument. The pre-registration also required an empirical check
before the campaign could start: an equivalence gate, 4 real public adapters
against 4 synthetic ones in the same 8-slot server, each start running two
spread phases over each set in a random order.

![Two panels of relative difference, synthetic minus real adapters over real, in percent. Grey dots are the 137 usable server starts, one each. Red is the median with its 90% bootstrap interval: TTFT p50 from minus 1.87% to plus 0.95%, throughput from minus 0.23% to plus 0.42%. Blue is the real-versus-real resolution check: TTFT p50 from plus 0.99% to plus 4.95%, throughput from minus 0.92% to plus 0.07%. All four intervals sit inside the shaded margin of plus or minus 5%, so the verdict is pass.](figures/a5/equivalence.png)

**The rule.** Per start, the statistic is (synthetic − real) / real, for TTFT
p50 and for throughput. The margin is half the knee threshold, ±5%: a synthetic
bias smaller than that cannot move the knee by itself. The gate passes if the
90% bootstrap interval of the median statistic lies inside ±5% for both
metrics, which is two one-sided tests at the 5% level. A resolution check runs
alongside: the second real phase against the first, the same statistic, must
also fit inside ±5%. If it does not, the gate cannot resolve its own margin,
and the verdict is inconclusive, not pass.

**The verdict, with 137 usable starts, is pass.** TTFT p50: −0.48% [−1.87%,
+0.95%], with the resolution check at +2.29% [+0.99%, +4.95%]. Throughput:
+0.19% [−0.23%, +0.42%], resolution −0.29% [−0.92%, +0.07%]. The TTFT
resolution check passes by 0.05 points. Its interval also sits above zero: the
second phase over the same real adapters ran about 2% slower in TTFT p50 than
the first, which is a drift between single phases rather than a difference
between adapter sets, and it is inside the margin.

**How it got to 137, told in order**, because it did not go as registered:

1. **The pilot, 24 starts, was inconclusive.** One start compiled cold and was
   excluded, leaving 23. Synthetic-versus-real TTFT p50 was +2.9% [−2.7%,
   +10.7%], and the resolution check +8.9% [−6.4%, +11.7%] failed. Throughput
   passed. Single-phase TTFT varied by roughly ±10–15% between phases of one
   start, and 23 starts could not resolve ±5% through that.
2. **Amendment 1, written after that verdict and in response to it, enlarged
   the gate to 144 starts in a fresh store**, with nothing else changed. The
   pilot is kept and not pooled.
3. **The larger gate lost 52 starts to a host fault.** Run indices 92 to 143
   all landed on one pod whose host driver, 570.195.03, could not run the
   image: the engine logged CUDA `Error 804: forward compatibility was
   attempted on non supported HW` and died before serving a request. The
   endpoint had been restricted to hosts supporting CUDA 13.0 part-way through
   the gate, and the restriction did not prevent the placement. I do not know
   why. Of the 92 starts that ran, 4 compiled cold and were excluded.
4. **The 88 usable starts were inconclusive.** TTFT p50 was −1.16% [−2.54%,
   +0.75%], inside the margin, but its resolution check, +2.24% [−0.11%,
   +5.81%], fell just outside. Throughput passed.
5. **Amendment 3 extended the gate by exactly 52 replacements, and I decided
   that after seeing the 88-start verdict.** That is a data-dependent
   extension. Its justification is that the 52 lost starts were a host fault
   that never ran a phase, so the extension restores the sample size Amendment
   1 had fixed in advance rather than choosing a new one. Three of the 52
   replacements failed with the same CUDA error on a host with the same
   driver, after which a stop-on-repeated-failure guard halted the run. Those
   three were counted and not replaced again. The other 49 ran.
6. **Final: 196 scheduled, 55 failed, 4 excluded as cold compiles, 137
   usable.** The verdict above is from those 137.

All 55 failures are in the failure table and kept in `data/a5/gate.jsonl`. The
pilot's numbers and the interim 88-start verdict are in Amendments 1 and 3. The
gate covered one point, 8 slots with 4 adapters of each kind; that synthetic
adapters stand in for real ones at the other points rests on the argument
above, not on a measurement at each point.

---

## Method

**Fixed.** Image `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:39e967e9…`
(vLLM 0.27.1), model `Qwen/Qwen3-4B` at revision
`1cfa9a7208912126459214e8b04321603b3df60c`, one NVIDIA RTX 4090 (24 GB) on
RunPod serverless, `--max-model-len 8192`, `max_lora_rank` 16 on `q_proj,
k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj`, prefix caching off,
`VLLM_TUNED_CONFIG_FOLDER` unset, and `gpu_memory_utilization` 0.80. That last
value is lower than vLLM's default of 0.92 because with LoRA enabled the default
ran out of memory: the engine sizes the KV cache to the budget, and the 1.28 GiB
of CUDA graphs it captures afterwards come on top
([`docs/recon-a5.md`](recon-a5.md)). Part-way through the gate the endpoint
was restricted to hosts whose driver supports CUDA 13.0.

**One start.** One server start at N slots, `max_loras = max_cpu_loras = N`,
compile cache primed. An untimed warm-up sends 2 requests to every registered
adapter. Then four timed phases, two concentrated and two spread, in an order
drawn per start. Each phase sends 640 requests at a concurrency of 64,
round-robin over its adapter list, from vLLM's `random` dataset with 13 prompt
tokens and 16 output tokens, with ignore-EOS. The load generator, `vllm bench
serve`, runs in the same container as the server; I use its per-request arrays
and never its summary statistics. Per start and regime: TTFT p50 and p95 over
the successful requests of both phases, and throughput as successful output
tokens over total phase time.

**The subtraction.** Heterogeneity cost at N: spread minus concentrated, paired
within each start. Registered-slot cost at N: concentrated at N minus
concentrated at 1 slot, across starts. Every reported point is a median across
starts with a 95% bootstrap interval (10,000 resamples, fixed seed); the gate
uses 90% intervals, as its rule requires. Memory is not subtracted: it is read
as KV capacity from each start's startup log.

**Rules, fixed before the data.** A request is a failure if its error entry is
non-empty, its TTFT is zero or its output length is zero, and failures are
removed before any statistic. A start whose compile cache read cold, with
`torch.compile` taking 1 s or more, is excluded. A condition that fell below 20
usable starts would get top-up starts, disclosed here.

**The campaign.** Seven sweep points, 1 to 64 slots by doublings, plus the
gauge control at 64 slots, 24 starts each, 192 in all, in randomized blocks.
191 succeeded. One, at 2 slots, failed on the controlling machine with a
client-side `ConnectionResetError`, was recorded and was not retried, which is
why that point has 23 starts. No campaign start compiled cold, and every
condition stayed at 23 or more, so no top-up ran. All 191 ran on one host,
which was circumstance, not design: the platform assigns hosts. Billed spend for
the whole artifact, reconnaissance, priming, both gates and the campaign, was
$14.48 for 13.06 billed GPU-hours across its two endpoints.

**Pre-registered hypotheses.** H1 and H2 are in the section on registered
slots; both hold. H3, that KV capacity falls with slots and that at this
request shape the KV ceiling exceeds the concurrency at every point, holds; the
section on memory has it. H4 was withdrawn before the first measured run, with
its diagnostic.

The pre-registration in [`docs/experiment-a5.md`](experiment-a5.md) was
committed before the first measured run. Three amendments follow it, each
appended without editing anything above it. Amendments 1 and 3 are post-hoc:
both were written after a gate verdict, in response to it, as told in the
section on synthetic adapters. Amendment 2 replaced the illustrative $1.00
GPU-hour with artifact 4's registered $1.1095, disclosed that the base model
differs from artifact 4's, and recorded the CUDA 13.0 restriction. The git
history is the evidence for the order.

---

## Adapters versus swapping models

Artifact 4 measured the other way to serve many fine-tunes: as whole models,
either one dedicated deployment each or swapped on and off GPUs. Its results
file names the reference point this comparison uses, the bursty regime at Zipf
skew s = 1.0, where its dedicated strategy costs $850.43 per tenant per month
and its swapped strategy $404.97, at the same $1.1095 per GPU-hour.

**Both of those numbers come from artifact 4's simulator, which failed its
pre-registered validation**, at exactly this operating point: bursty, s = 1.0,
three models on one GPU. 10 of 13 judged bins fell outside the band of three
real repeats, the largest miss was 67.8 s, and 1 of 2 held-out interference
cells passed; the swap count agreed, 11 predicted against 10 real in all three
repeats. The failure does not touch the two bars the same way. The swapped bar
depends on the model that failed, since the gate tested exactly the swap path.
At the swap time the simulator charged, the swap campaign's 37.8 s, it
predicted latency higher than the real engine's in every missed bin, always on
the same side; charged instead at the roughly 25 s that the swaps inside the
replays took, on a different pod, it predicted lower in every bin that still
missed. So the validation does not say which way the swapped cost errs.
Artifact 4 says no single fixed swap cost matches the real system, and that it
cannot say how the failure splits between the host and a gap in the model. The
dedicated bar was not tested by that gate, so it is neither validated nor shown
wrong. By artifact 4's pre-registered sizing rule, as I read it, the dedicated
fleet is fixed by construction, one GPU per model plus pinned GPUs for hot
models, sized from measured saturation rather than from the simulated
latencies; the gate did not check that reading. Nothing in the file is
validated, at this point or any other. Artifact 4 says the ordering is wide,
"dedicating costs about twice the cheapest option", and that it did not test
whether the model's error is small enough to leave the ordering unchanged. The
adapter bar is this artifact's own measurement, but placed beside the swapped
bar it inherits that caveat: the comparison between adapters and swapping is
only as firm as the swapped bar.

**This is not a like-for-like comparison, and I do not present it as one.**
Artifact 4's costs come from a simulated fleet of 20 Qwen3-1.7B models with
256-token outputs, under its own traffic model, offered load and SLO. Artifact
5's come from Qwen3-4B with 16-token outputs at a fixed concurrency of 64.
Artifact 4 changed to Qwen3-1.7B because its primary pair, Qwen3-4B and
Qwen3-4B-Base as two co-resident engines, failed its own memory go/no-go, with
KV capacities of 9,456 and 9,520 tokens against the 16,384 it required. I kept
Qwen3-4B for this artifact. The three bars share a unit and a GPU rate and
nothing else that was measured.

What the comparison can carry is the shape of the choice. Swapping pays per
switch, in the time it takes to bring a model onto the GPU. Resident adapters
never switch; they pay per co-active adapter, in throughput. A like-for-like
number needs artifact 4's swap measured on Qwen3-4B, or this sweep run on
Qwen3-1.7B. Neither was run.

---

## Memory is a capacity question

![KV cache capacity in tokens against adapters registered, 1 to 64 slots: 78,208 tokens at 1 slot, 77,744 at 2, 76,496 at 4, 74,288 at 8, 69,968 at 16, 60,448 at 32 and 42,864 at 64. Every server start at a point reported the same value, so the per-instance dots sit on the median line. At 8,192 tokens per request the capacity holds 9 concurrent requests at 1 slot and 5 at 64.](figures/a5/kv_capacity.png)

Each slot's weight buffers take GPU memory that would otherwise hold KV cache.
KV capacity falls from 78,208 tokens at 1 slot to 42,864 at 64, every start at
a point reporting the same value, so there is no interval to draw. That is
about 45% of the KV cache gone, and it is the effect the August design called
memory.

**At this request shape that memory cannot move latency or throughput.** A
request here holds 29 tokens: 13 of prompt, 16 of output. 64 of them in flight
need about 2,048 tokens of KV, in vLLM's 16-token blocks. Even at 64 slots the
cache holds 1,478 such requests at once, against the 64 the load generator
keeps in flight; during reconnaissance the engine at 64 slots logged its KV
usage at 4.7% with 64 requests running. The scheduler never waits for KV, so a
memory effect on TTFT or throughput at fixed concurrency is zero by
construction, and none of the slowdown in the main chart is memory. That is
also why the concentrated regime's change is called the registered-slot cost
and never memory.

Memory matters as **capacity**: how many requests the GPU can hold, which
becomes tenants. Little's law says that, in steady state, the number of
requests in a system equals their arrival rate times the time each spends in
it. At 8 slots the
spread regime kept 64 requests in flight and completed about 204 a second, so
each request's time in system was about 0.31 s. One tenant at peak sends about
0.114 requests a second and so keeps about 0.036 requests in the system. At a
production context of 8,192 tokens per request, the KV cache at 8 slots holds 9
requests, and 9 divided by 0.036 gives the memory bound of 250 tenants. That
is below the throughput bound of 1,784, so for long-context traffic memory would
bind before throughput does. It still sits far above the slot knee of 8. The
bound also carries the time in system measured on 29-token requests; a request
that really used 8,192 tokens would stay longer, and the bound would be lower.

So adapters cost KV capacity, and at long contexts that cost would be the one
to plan around. At this shape it is the less interesting cost: the
heterogeneity cost moves throughput, and memory does not.

---

## Limits

- **One base model, one GPU, one rank, one request shape.** Qwen3-4B, an RTX
  4090, rank 16 on seven projections, 13 prompt and 16 output tokens at a
  concurrency of 64. Every number is a property of that configuration. The
  knee at another rank, another model or with long prompts is unmeasured.
- **A pinned version in a fast-moving area.** vLLM 0.27.1, pinned by image
  digest. The launch-grid behaviour behind the registered-slot cost, and the
  gauge's series growth, are read from that version's source. Multi-adapter
  serving changes often; these claims are dated 2026-10 and scoped to it.
- **The all-resident case only.** Every adapter sat in a GPU slot. vLLM's
  intended multi-tenant mode holds more adapters in CPU memory than in slots
  and swaps them in on demand. That is why tenants per GPU is a lower bound and
  the adapter cost an upper bound, and resident versus swapped is a sequel.
- **The registered-slot cost is unsplit.** The diagnostic that would have
  separated the launch-grid overhead ran out of memory and was cut; H4 was
  withdrawn.
- **The manipulation check is a sample.** The gauge reports the scheduler's
  running set once a second, not the adapters in each batch.
- **One host for the campaign.** All 191 successful campaign starts ran on one
  host. Host-to-host variation is not in the intervals.
- **The rate is an estimate.** $1.1095 per GPU-hour comes from one billing
  sample on artifact 4's endpoint. This artifact's own billing implied $1.1084
  on the measurement endpoint and $1.1090 on the reconnaissance endpoint. The
  $14.48 spend covers those two endpoints and not network-volume storage.
- **Artifact 4's costs come from a simulator that failed its validation.** At
  the bursty, s = 1.0 point used here, 10 of 13 judged bins missed the band of
  three real repeats and 1 of 2 held-out cells passed. The swapped bar depends
  on the failed model, and the validation does not say which way it errs: at
  the 37.8 s swap time the simulator charged, it predicted latency higher than
  real; at the replays' roughly 25 s, lower. The dedicated bar was not tested by
  the gate. Nothing in artifact 4's file is validated, and the adapter
  bar, set beside the swapped bar, inherits that.
- **The cost comparison crosses model sizes.** Artifact 4's reference point was
  measured on Qwen3-1.7B, this artifact on Qwen3-4B.
- **The gate was extended after its result was seen**, twice, and the knee's
  first crossing is not resolved. Both are stated where the claims are.
- **Exclusions and failures.** 4 gate starts were excluded as cold compiles; no
  campaign start was. 55 gate starts and 1 campaign start failed, all counted
  in the committed failure table. No top-up ran.

---

## Reproduce it

The results come from two committed stores and one committed file from
artifact 4. That file, `data/a4/cost_per_tenant.json`, is a byte-identical copy
of the file at artifact 4's commit d7cf0c3, which at the time of writing exists
in artifact 4's local repository and is not on origin. The pilot gate,
reconnaissance and billing figures are recorded, with their sources, in
`docs/experiment-a5.md` and `docs/recon-a5.md`. No GPU is needed for any step
below:

```bash
git clone https://github.com/alexostapiuk11/coldstart-recon-worker
cd coldstart-recon-worker
mkdir -p build
python scripts/a5_analyse.py --require-a4 --out build/a5-analysis.json
cmp build/a5-analysis.json data/a5/analysis.json
```

`scripts/a5_analyse.py` reads `data/a5/campaign.jsonl`, `data/a5/gate.jsonl`
and artifact 4's `data/a4/cost_per_tenant.json`, with the pre-registered values
in `multilora/prereg_values.py`, and writes the analysis. The bootstrap is
seeded, so `cmp` prints nothing: the re-run is byte-identical to the committed
`data/a5/analysis.json`.

```bash
python scripts/a5_render_figures.py --analysis data/a5/analysis.json --out build/a5-figures
python scripts/a5_numbers.py --check
python -m pytest tests/test_a5_post.py tests/test_a5_published_figures.py tests/test_multilora_prereg_values.py
```

`scripts/a5_render_figures.py` reads `data/a5/analysis.json` and draws the four
figures. `scripts/a5_numbers.py --check` reads the same file and this post, and
exits 1 if the generated table above is stale. The tests check the post's table,
figure links and sections against the analysis, re-render the figures and
compare them with `docs/figures/a5/`, and tie the pre-registered values to
`docs/experiment-a5.md` and the reconnaissance captures in `fixtures/a5/`.

---

## Next

- **Rank as a variable.** Slot memory and kernel work both scale with
  `max_lora_rank`. By the design's estimate, at rank 64 the 64 slots would not
  fit beside the weights on this card, so rank and the top of the sweep have to
  move together.
- **Resident versus swapped.** `max_cpu_loras` above `max_loras`, with adapters
  copied into slots on demand: the mode a real multi-tenant deployment would
  run, and the one that turns the lower bound on tenants into a measurement.
- **`specialize_active_lora` as a configuration.** It ran out of memory at 64
  slots on this card at both budgets tried. Whether it removes the
  registered-slot cost where it fits, and what its extra graphs cost, is still
  open.
