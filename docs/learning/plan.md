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
