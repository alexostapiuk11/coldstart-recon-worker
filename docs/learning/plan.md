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
