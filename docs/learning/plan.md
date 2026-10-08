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
| 4 | Little's law and the three bounds | "Tenants per GPU" and "Memory is a capacity question" | 12 | from 64 in flight, about 204 requests a second, one tenant's peak of 0.114 requests a second and 9 requests of KV room at 8,192 tokens, reproduce the 0.31 s, the 0.036 requests in system per tenant and the 250. Then say why KV capacity cannot move TTFT at 29-token requests and still sets a tenant bound. Last, the post says 42,864 tokens hold 1,478 requests in the same paragraph that counts 2,048 tokens for 64 requests in 16-token blocks: recompute and say which it is (see the note below) |
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

**Module 4's last question is a real discrepancy, not a trap.** It was found
while writing this plan. The conclusion does not move: either figure is more
than twenty times the 64 requests in flight. The post's published text is not
edited; a correction would be appended as a dated note.

**Module 5 is the part most worth teaching.** A rule fixed before the data,
whose own check could not resolve its margin, and an extension decided after
seeing the interim verdict, with the order of events kept in git. A teach-back
that gets this right shows the difference between a result and the process that
made it trustworthy.
