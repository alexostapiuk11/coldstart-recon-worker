# Learning plan — the cold-start artifact

**The material:** https://claude.ai/code/artifact/40e49d9f-dbe5-453e-b753-0572b19d2486


Nine modules, about two hours total. The material is the explainer; this file is
the path through it and the record of what counts as understanding.

**The pass criterion, uniform across modules:** state the idea in your own words
without the material in front of you, and have the statement survive one
follow-up question. Recognising an explanation and being able to give one are
different skills, and only the second is the goal here.

**On a failed checkpoint, the same explanation does not get repeated.** That is
what failed twice in module 0. Branch to a different representation — shrink the
example, make it concrete, or find a case that breaks the wrong model — and
record which representation worked. That record is the useful artifact.

## Where to ask

| | ask it here | because |
|---|---|---|
| "what does KV cache mean again?", "say that differently", "another example" | the page's own tutor, if built | instant, always there, needs no session — but it has no memory between questions |
| "I still don't get *why*", checkpoints, the teach-back critique | Claude, in session | reads the actual source, and carries your history across sessions |

## The modules

| # | module | page sections | min | checkpoint |
|---|---|---|---|---|
| 0 | diagnostic | — | done | see `progress.md` |
| 1 | one run's journey | Part I spine, beats 1–12 | 12 | narrate a run end to end, naming which clock is running |
| 2 | **spread vs interval** | the interlude: ECDF + resample frames | 20 | predict the controlled test: same clusters, different split — what happens to the interval? |
| 3 | GPU memory, weights, and the ceiling | zone 4 intro | 8 | finish the consequence chain unaided |
| 4 | vLLM's four steps; the KV dividend | zone 4 section | 15 | explain why memory profiling needs a real forward pass |
| 5 | the six components | the six cards | 18 | for any card, state the failure it prevents |
| 6 | three arms; the difference of contrasts | act 3 + the shortcut panels | 12 | judge a claim from two intervals, and say what is missing |
| 7 | what could *not* be concluded | act 4 | 8 | name a limit the artifact states about itself |
| 8 | **teach it back** | the closing card | 30+ | draft the LinkedIn version; Claude plays someone who does not know the material and pushes on every hand-wave |

**Statistics sits at position 2, not 5.** The diagnostic found it the largest
gap, and an earlier ordering had it behind four modules of material already
comfortable. It needs only "runs have different durations," which beat 12 and the
ECDF supply.

**The two-hour total is a control, not an estimate.** Without it there is no way
to notice the plan has grown too long until someone is already bored by it —
which was the stated priority. If a module overruns, cut it.

## Why module 8 is the assessment

The goal is to teach this to other people. Preparing to teach is the most
reliable way to discover what is not actually understood — which is exactly what
happened during module 0, in both directions: it found the interval
misconception, and it caught a claim in the teaching material that the data
contradicted.

---

# Learning plan — artifact 2, the autoscaling signal

**The material:** the post, [`docs/post-a2.md`](../post-a2.md), and its five
figures; the concepts behind it are in the design spec's learning guide
(`docs/superpowers/specs/2026-08-17-autoscaling-signal-comparison-design.md`,
§13b). The pass criterion and the rule on failed checkpoints are the same as
above: state it unaided, survive one follow-up, and on a miss change the
representation, not the volume.

**The material, as a page:** a private interactive page,
<https://claude.ai/artifact/Lt9oqDvw3SFoJgGBQxBKPR>, covers modules 1 to 6, each
with a widget on the committed data and its checkpoint shown unanswered. Its
source is `explainer_a2/`, built by `scripts/build_explainer_a2.py`; the
checkpoint text on the page is read from the table below, so editing a
checkpoint here means rebuilding and republishing the page. Modules 0, 7 and 8
need no page and happen in session.

**Adapted to what the artifact found, not what it set out to find.** §13b was
written before the build and teaches the simulator's answer as if it would be
trusted. The simulator failed its validation twice, so the weight moves to what
was measured: the service curve, the load balancer, host speed and the gate
itself. Two of §13b's modules are merged into others, integrated excess is
dropped because the published metric is p99, and the load balancer, which
§13b does not mention, gets its own module.

## The modules

| # | module | material | min | checkpoint |
|---|---|---|---|---|
| 0 | diagnostic | — | 10 | answer §13b's self-checks 1, 2, 3, 7 and 8 cold; record what is solid and what is not |
| 1 | continuous batching and the service curve | the post's "The service curve" and its figure; §13b modules 1–2 | 12 | from the figure, say why latency rises gently from 1 to 128 in flight while throughput bends, and what stopped the curve at 128 |
| 2 | **Little's Law, checked on real data** | the load-balancer section, finding 1; §13b module 3 | 15 | probe 1 at 50 req/s offered: two workers held 2.62 and 2.65 requests on average and delivered 17.10 req/s. Compute each request's time in the engine and compare it with the measured server p50 (0.310 s). Then say why a cap of 4 per worker does not deliver 8 ÷ 0.31 ≈ 26 req/s, and what would have to be measured to know |
| 3 | why GPU utilisation is blind | the service curve's bottom panel; §13b module 4 | 10 | say why it reads 1.0 from one request upward, predict what an autoscaler driven by it does, and connect that to why the iso-cost budget stopped constraining the other two signals |
| 4 | dead time and cooldowns | the simulator figure; §13b modules 5–6 | 10 | §13b's self-checks 5 and 6; then predict, before looking, whether a faster cold start should make the signal choice matter more or less, and say why the simulator's answer to that is not evidence |
| 5 | frontiers, dominance and the iso-cost slice | the post's "(a)" and "(b)"; §13b modules 7–8 | 15 | §13b's self-check 7; then explain how 19 policies with the same fleet produce a spread of p99s, and why that spread decides what can and cannot be ranked |
| 6 | **the validation gate, and why it failed** | the post's attempts one and two, the `attempts` and `host_speed` figures; §13b module 9 | 20 | §13b's self-check 8; then explain how one host-speed factor can make every bin miss on the same side, and propose the test that would settle why the calibration over-corrected |
| 7 | what could not be concluded | the post's Limits | 8 | §13b's self-check 10 against what was actually validated (one replica, below capacity); name a limit the post states about itself |
| 8 | **teach it back** | the whole post | 30+ | draft the LinkedIn version; Claude plays someone who does not know the material and pushes on every hand-wave |

About two hours, held to the same control as above: if a module overruns, cut it.

**The gate sits at position 6, after the concepts it uses.** It needs Little's
Law (module 2) to read the in-flight counts and the frontier (module 5) to see
what was at stake, and it is the part of the artifact most worth teaching:
a pre-registered test that the author's own model failed, twice.

**Module 2's last question is open on purpose.** Nothing in the repository
explains why the workers averaged about 2.6 in flight under a cap of 4, so
the checkpoint is to say what measurement would answer it, not to know the
answer.

---

# Learning plan — artifact 5, how many LoRA adapters fit on one GPU

**The material:** the post, [`docs/post-a5.md`](../post-a5.md), and its four
figures (`docs/figures/a5/`, each with a phone-width variant); the concepts
behind it are in the design spec's
learning guide (`docs/superpowers/specs/2026-08-17-multi-lora-serving-design.md`,
§12b), and the pre-registration and its three amendments are in
[`docs/experiment-a5.md`](../experiment-a5.md). The pass criterion and the rule
on failed checkpoints are the same as above: state it unaided, survive one
follow-up, and on a miss change the representation, not the volume.

**Adapted to what the artifact found, not what it set out to find.** §12b was
written before the build and expects the curve to be flat to some count and then
rise. The measured curve does not wait: spread-regime throughput loses 10.7% by
8 to 16 adapters, and the pre-registered knee is there. Four of its answers
change:

- **Self-check 6, "the equivalence check fails, what do you do?",** had two
  outcomes. The run produced a third, *inconclusive*, twice, and the answer
  became an amendment. The gate gets a module of its own.
- **Self-check 8, "flat to 32 then sharp",** is a prediction the data
  contradicts. Use it as the diagnostic: the recorded answer is what was
  predicted, and the module that follows checks it against the main chart.
- **Self-check 9, "combine with artifact 4's answer",** inherits a simulator
  that failed its own validation. The post's cost bars are not like-for-like.
- **Rank (self-checks 2 and 7)** is fixed at 16 and never varied. §12b's
  modules 1–2 are merged into one.

## The modules

| # | module | material | min | checkpoint |
|---|---|---|---|---|
| 0 | diagnostic | — | 10 | answer §12b's self-checks 1, 3, 4, 5 and 8 cold; record what is solid and what is not. Self-check 8 is written down as a prediction, to be checked in module 2 |
| 1 | what an adapter is, and what rank sets | the post's "Synthetic adapters" argument paragraph; §12b modules 1–2 | 10 | say why an adapter is megabytes beside a gigabytes model, why serving cost depends on shapes and not on values, and what that licenses (serving cost of any rank-16 adapter on this base) and does not license (quality, other ranks) |
| 2 | **registered is not active** | "Registered is not active"; the main chart; §12b modules 3–4 | 15 | before looking at the chart, predict at 64 slots whether the concentrated line and the spread line are close, which is lower, and by roughly what fraction. Then say which line's slope is the registered-slot cost and which gap is the heterogeneity cost, and why `max_loras` being both the slot count and the in-batch cap forces the regimes to separate them by traffic |
| 3 | **spread vs interval, then the knee** | the main chart's bars; "Headline"; the decomposition table | 15 | open by checking the artifact 1 fix held: the post says the bars show where the median would land on a re-run and not where one start lands. State that without the post, then say why pairing within a start lets the heterogeneity cost cancel start-to-start variation but the registered-slot cost cannot. Then read the knee: 10.7% [9.2%, 11.5%] from 8 to 16 straddles 10%, so is the knee at 8 resolved, and what happens to the dollars if it is really 16 |
| 4 | Little's law and the three bounds | "Tenants per GPU" and "Memory is a capacity question" | 12 | from 64 in flight, about 204 requests a second, one tenant's peak of 0.114 requests a second and 9 requests of KV room at 8,192 tokens, reproduce the 0.31 s, the 0.036 requests in system per tenant and the 250. Then say why KV capacity cannot move TTFT at 29-token requests and still sets a tenant bound. Last, recompute how many requests the 42,864-token cache holds at 64 slots, counting in 16-token blocks, and check it against the 4.7% usage the engine logged with 64 running (see the note below) |
| 5 | **the equivalence gate, and the amendments** | "Synthetic adapters, and how I know they are valid here"; `docs/experiment-a5.md` Amendments 1 and 3; §12b module 6 | 25 | state the rule (the statistic, the ±5% margin as half the knee threshold, 90% intervals, the resolution check) and why it has three verdicts. Then from the 88-start result, TTFT p50 −1.16% [−2.54%, +0.75%] with a resolution check of +2.24% [−0.11%, +5.81%], give the verdict and why. Then say what separates Amendment 3 from a forking path, what the reader should still discount, and why the stop-on-repeated-failure guard exists |
| 6 | the cost bars, and what cannot be concluded | "Adapters versus swapping models" and "Limits" | 12 | §12b's self-check 9 against what was validated: say which of the three bars rest on a failed simulator, which way each is known to err (neither, for the swapped bar), why the model sizes differ, and why the adapter bar is an upper bound. Name three limits the post states about itself |
| 7 | **teach it back** | the whole post | 30+ | draft the LinkedIn version; Claude plays someone who does not know the material and pushes on every hand-wave |

About two hours, held to the same control as above: if a module overruns, cut it.

**The statistics return in modules 3 and 5, not in a module of their own.**
Artifact 1's diagnostic found intervals the largest gap, and artifact 2's
modules that lean on them have no recorded attempt. Module 3 opens by testing
the fix before it builds on it, and module 5 is the first place in the
portfolio where an interval's *failure to settle a question* is the content:
the resolution check is a 90% interval compared against a margin.

**Module 4's last question is a check on a slip that was fixed.** The post first
said 1,478 requests, dividing by 29 tokens and ignoring block rounding; it now
says 1,339 (42,864 ÷ 32). The 4.7% the engine logged agrees with the blocks:
64 × 32 = 2,048 of 42,864 tokens. The conclusion never moved: either figure is
more than twenty times the 64 requests in flight.

**Module 5 is the part most worth teaching.** A rule fixed before the data,
whose own check could not resolve its margin, and an extension decided after
seeing the interim verdict, with the order of events kept in git. A teach-back
that gets this right shows the difference between a result and the process that
made it trustworthy.

---

# Learning plan — artifact 4, dedicate, swap or share

**The material:** a private explainer page,
https://claude.ai/artifact/XpK5JB3U8jYgoUsVsP6eQy (source:
[`explainer/a4/page.template.html`](../../explainer/a4/page.template.html), built
into `page.html` by `scripts/a4_build_explainer.py` from the committed data),
which covers modules 1 to 7 with a prediction or an interactive in most and the
checkpoint at the end of each; modules 0 and 8 happen in the session and are not
on the page. Modules 2, 4 and 5 ask for a prediction before they show the chart,
and 4 and 5 check the answers recorded in module 0. Behind it: the post,
[`docs/post-a4.md`](../post-a4.md), and its four
figures (`docs/figures/a4/`, each with a phone-width variant); the concepts
behind it are in the design spec's learning guide
(`docs/superpowers/specs/2026-08-17-multi-model-serving-economics-design.md`,
§12b); the pre-registration and its amendments are in
[`docs/experiment-a4.md`](../experiment-a4.md), the validation failure's
diagnosis in
[`docs/findings-a4-validation-swap-cost.md`](../findings-a4-validation-swap-cost.md),
and the interference sensitivity in
[`docs/findings-a4-interference-sensitivity.md`](../findings-a4-interference-sensitivity.md).
The pass criterion and the rule on failed checkpoints are the same as above:
state it unaided, survive one follow-up, and on a miss change the
representation, not the volume.

**Adapted to what the artifact found, not what it set out to find.** §12b was
written before the build and teaches a crossover along the skew axis whose
simulator would be trusted. The simulator failed its validation and the
crossover is between the regimes. Four of its answers change:

- **Self-check 6, "aggregate p99 is fine, why a problem?",** expects the cold
  tenants to suffer. At the reference point the opposite happened: the two
  hottest deciles breach at 9 GPUs and the coldest does not. Use it as a
  diagnostic prediction, recorded before the deciles figure is shown.
- **Self-check 8, "the crossover moves between bursty and spread",** is a
  prediction the data answers differently: no crossover along skew in either
  regime; the winner changes between the regimes (co-locate when spread, swap
  when bursty). Record the answer given before the crossover figure is shown.
- **Self-check 5, thrashing "at the low-skew end",** is not what the sweep
  shows. In the spread regime at s = 1.0 swapping has a hit rate of 0 and about
  1,095 swaps an hour, and its fleet is not monotone in skew (13, 13, 13, 18,
  17, 15). The post says it did not diagnose why.
- **Self-check 9, "cut cost 40%, bottom decile outside SLO",** is the
  aggregate-rule view: 9 GPUs instead of 10 at the reference point, cheaper and
  wrong. §12b's modules 3–5 are merged into one because the sweep's two regimes
  carry them together.

## The modules

| # | module | material | min | checkpoint |
|---|---|---|---|---|
| 0 | diagnostic | — | 10 | answer §12b's self-checks 1, 3, 4, 5, 6 and 8 cold; record what is solid and what is not. Self-checks 6 and 8 are written down as predictions, to be checked in modules 4 and 5 |
| 1 | **a swap is a cold start minus the expensive parts** | "A swap" and its stage table, the swap-stages figure; §12b module 1 | 12 | from the table say which stages a swap pays (27.8 s of 37.8 s is process start, imports and health) and which it skips, and why a 1.7B swap is about as long as artifact 1's 8B cold start. Then say why the 8B bar is a reference and not a baseline, and what sleep mode's 5.0 s avoids and what the post says it cannot price |
| 2 | **sharing a GPU: interference and the KV split** | "Co-location" and "The KV split", the interference figure; §12b module 2 | 15 | before looking, predict whether a busy neighbour's cost grows with the model's own load. Then from the figure: latency about 2.2 times at every own concurrency, even one request about 2.3 times. Reproduce 168,464 ÷ 55,104 ≈ 3.1 against 0.92 ÷ 0.45 ≈ 2.0, and the ceilings of 82 and 26 requests, and say why the memory share and the cache shrink by different factors. Say what the post did and did not measure about the mechanism |
| 3 | Zipf, locality and the two regimes | "The crossover" and "Method"; §12b modules 3–5 | 15 | explain Zipf skew to someone who has not seen it; say why spread and bursty arrivals with the same long-run rate per model behave differently for swapping; read the spread column of the crossover figure and say what a hit rate of 0 and 1,095 swaps an hour mean. Say why LRU is held fixed rather than compared |
| 4 | **averages hide tenants** | "Why the naive answer is wrong", the deciles figure; §12b module 6, self-checks 6 and 9 | 12 | check the prediction recorded in module 0 against the figure. Then say why sizing the swap fleet on the aggregate p99 gives 9 GPUs, which deciles breach, and why that answers self-check 9: is a fleet that is cheaper and outside the SLO for a tenth of the models cheaper |
| 5 | **the decision rule, and what carries it** | the lead, "The crossover", "Where the boundary moves"; the sensitivity finding; §12b module 7, self-check 8 | 18 | check the prediction recorded in module 0. State the rule, and why there is no crossover along skew. Then say what the 75.6 s SLO does to the answer (it favours swapping, and co-located latency of 3 to 6 s leaves wide room) and use the sensitivity table: at what multiple of the measured penalty co-locating stops winning, in which regime first, and why that run is exploratory. Say why dedicating needs 21 to 25 GPUs for twenty models |
| 6 | **the validation gate, and why it failed** | "The validation, and its failure", the validation findings, `docs/experiment-a4.md` "The validation gate" and the amendments; artifact 2's module 6 for the shape | 25 | state the gate (three repeats, a band widened by 0.001 s, at most half the bins may miss, swap count within one) and its verdict, 10 of 13 bins. Then explain how a swap charge of 37.8 s against about 25 s makes every miss fall on the same side, why charging each repeat its own swap time still fails but with the sign flipped, and what the gate did not cover (co-location). Last, propose the measurement that would say how much of the failure is the host and how much the model, and say why a calibrated re-run would not rescue the result |
| 7 | what could not be concluded | "Limits" and the amendments | 8 | name three limits the post states about itself, and say which one makes the others matter most (the failed validation). Say what separates an amendment made before the data it governs from a forking path, using the git order of events |
| 8 | **teach it back** | the whole post | 30+ | draft the LinkedIn version; Claude plays someone who does not know the material and pushes on every hand-wave |

About two hours, held to the same control as above: if a module overruns, cut it.

**Module 6 is the part most worth teaching, as module 5 is for artifact 5.**
A rule fixed before the data, and the author's own model failing it: the
teach-back that gets it right shows that a published failure with a diagnosis
is a result. If artifact 2's module 6 has been run, open this one by asking
what differs: that gate failed on host speed; this one failed mostly on the
swap charge, and the part that remains is a term the model does not have.

**Module 5 is where the post's wording changed most during review.** The
sensitivity result replaced an explanation the author had given without testing
it ("per-model load is low"). A good checkpoint answer says what carries the
result and does not repeat the replaced explanation.
