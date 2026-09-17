# Cold Start Explainer — Design

A scrolling explainer that teaches the artifact-1 system and the measurement
method behind it, built as a published Artifact.

## Why this exists

`docs/post.md` is the artifact's result. It explains its mechanisms well, but it
assumes the reader already knows what HBM and a KV cache are, and it presents
the apparatus as settled rather than teaching it. This document specifies a
different thing: the explainer that gets someone to the point where the post is
readable.

## Two audiences, in order

**Now — the author.** Wants to understand the system he commissioned: which
components exist, what each is responsible for, what vLLM is, how it was
instrumented. Depth is welcome; this reader will click into code.

**Later — a professional audience (LinkedIn).** Wants a transferable skill, not
facts about vLLM. The durable value is *how to judge a performance claim*.

One page, two parts. **Both parts are narrated.** An earlier draft made Part I
an explorable map with no guided path — which handed all the craft to the
second audience while the first got a reference manual with hover text. The
author's words were "initially I want to learn, not others," so Part I gets a
spine of its own, and it comes first.

## Learning objectives

**Part I** — the reader can name every component, say what each is responsible
for, explain what vLLM does during a cold start and why each step costs time,
and describe how the measurement was taken without modifying vLLM.

**Part II** — the reader can look at any performance claim and ask the four
questions in the closing card.

## Calibration — what the diagnostic found

Run 2026-09-17, before any material was written: four self-assessments and
three open probes. It changed the plan in five places, which is the argument for
running it first.

| area | measured level | consequence |
|---|---|---|
| serverless, containers | **comfortable** — explained cold start correctly and unprompted, including warming | **Cut.** Budgeted a section; needs one sentence. |
| GPU memory, weights | **better than self-reported** — named activations and K/Q/V unprompted | Don't re-teach the parts. Teach the *consequence chain* he stopped short of: 24 GB total − 15 GB weights = a hard ceiling on conversation length, fixed at startup. One correction owed: **Q is not cached**, only K and V. |
| intervals | **specific misconception**, see below | Promoted to the highest-value module in the plan. |
| the repo | **unread** — directed the work, didn't read the source | Deep cards are new material. Each needs setup before code appears; dropping the reader into `handler.py` cold is the boring failure. |

### The interval misconception, and the sequence that fixed it

Stated belief: *"the interval shows where the majority of numbers landed —
a bell curve, most values in that range."* This is the most common
misunderstanding of a confidence interval, and it survived a first, abstract
explanation. It was then restated almost unchanged — evidence that defining the
concept does not shift it.

What worked, in order, and therefore what the module must do:

1. **Refute with his own data.** Arm A's interval `[80.92, 85.88]` spans 82–85s
   where *zero* runs landed, and excludes 96s where 9 runs landed. A "where most
   values land" reading cannot survive that chart.
2. **Shrink the example until the mechanism is visible.** Five numbers, not 99.
   Show six imaginary campaigns drawn from a bag, each producing one median.
3. **Name the word that misleads.** "Shuffling" is wrong — reordering never
   moves a median. It is **drawing with replacement**: pull a number, write it
   down, *put it back*, repeat as many times as you have runs.
4. **Break the wrong model with a controlled test.** Same two clusters at 81s
   and 86s; change only the split. 51/48 → interval 5.00s wide. 70/29 → 0.00s
   wide. Identical clusters, identical gap, collapsing interval. The interval was
   never measuring the gap between groups.
5. **Separate evidence from computation.** 99 real runs = 2.34 GPU-hours and real
   money, and they set the interval's width. 10,000 resamples = 0.19s on a
   laptop and free, and they change nothing past a point. Only the expensive
   number carries information.

Step 4 is load-bearing: the arm A example accidentally *confirms* the wrong
model, because its interval happens to run from 81 to 86 and so looks exactly
like the gap between clusters. Any teaching of this concept that uses only arm A
will reinforce the error it means to correct.

## The learning plan and the tutoring loop

The author asked to be taught, not handed a document. Material cannot notice a
misconception; the section above is proof that the misconception was only found
by asking, and only fixed by iterating.

### Two tutors, split by one constraint

The in-page tutor uses the `sample` capability and **has no memory between
calls**. That single fact assigns the work:

| | handles | because |
|---|---|---|
| **in-page tutor** (`sample`) | "what does KV cache mean again?", "say this differently", "another example" | always available, instant, needs no session — but cannot know what was already covered |
| **Claude, in session** | "I still don't get *why*", checkpoint judging, teach-back critique | reads the actual source, and carries history across sessions |

### Modules

| # | module | checkpoint |
|---|---|---|
| 0 | diagnostic | done — see Calibration |
| 1 | GPU memory, weights, and the ceiling | finish the consequence chain unaided |
| 2 | one run's journey | narrate a run end to end, naming which clock is running |
| 3 | vLLM's four steps; the KV dividend | explain why profiling needs a real forward pass |
| 4 | the six components | for any card, state the failure it prevents |
| 5 | **spread vs interval** | the controlled-test prediction: same clusters, different split — what happens? |
| 6 | three arms; the difference of contrasts | judge a claim from two intervals, and say what's missing |
| 7 | what could *not* be concluded | name a limit the artifact states about itself |
| 8 | **teach it back** | draft the LinkedIn version; Claude plays an audience member who doesn't know the material |

Checkpoints require **production, not recognition** — answers in the reader's
own words, never multiple choice. Recognising an explanation and being able to
give one are different skills, and only the second is the stated goal.

Module 8 is the real assessment. The author's end goal is to teach this to
others, and preparing to teach is the most reliable way to discover what is not
actually understood — as module 5 demonstrated within this very session.

### Progress state

`docs/learning/progress.md` — what is solid, what is fuzzy, what was corrected
and when. Updated by Claude at each checkpoint, readable by the author, and the
thing that keeps a later session calibrated instead of re-teaching what already
landed. Re-explaining known material is the specific boredom failure the author
warned against.

## The two organizing ideas

Everything in Part I hangs off these. Neither is optional; without them the map
is a picture of boxes and the reader cannot answer "how was this measured?"

**Three clocks, three machines.** This is *why* zones 1, 2 and 3 are separate
zones rather than a decorative grouping.

| clock | where it runs | who stamps it | what it can see |
|---|---|---|---|
| A | your laptop | `submitter.py` | submit → result, including all queueing |
| B | inside the container | `recorder.py`, `probe.py` | the engine's own startup, phase by phase |
| C | the platform | `runpod_api.py` | RunPod's own view of the job lifecycle |

`checks.py` reconciles them. `T_platform = T_total − T_process` is a number
only because clock C exists; `DEFAULT_RTT_FLOOR = 0.05` catches the case where A
and B disagree by less than a network round trip, which would mean the clocks
are lying. This machinery is what lets the post say "Failures: 0, Discards: 0"
and mean it.

**The S-stage vocabulary.** `S1…S7` is the shared language between the probe
that marks the boundaries, vLLM's own log output, and the analysis that turns
marks into a waterfall. `vllm_logs.PATTERNS` keys on `S4b`/`S4c`/`S4e`;
`MERGED = ["S4a", "S4d"]` is why the post has an "unattributed" row. Without
this vocabulary the waterfall chart is unreadable.

## Part I — one run's journey

The spine is a single run animated end to end through the apparatus. Each beat
lights its zone on the map and states which clock is running. The six deep cards
hang off this path as optional depth, not as the only way in.

| # | beat | components | clock |
|---|---|---|---|
| 1 | the schedule says run 147 is arm B | `scheduler.py`, `cache_config.py` | — |
| 2 | preflight refuses, or allows | `preflight.py` | — |
| 3 | the job is stamped and sent | `submitter.py`, `runpod_submitter.py` | **A** starts |
| 4 | RunPod queues it, rents a GPU, boots the image | platform, network volume | **C** |
| 5 | the container prepares arm B's cache state — and snapshots it *before* running | `handler.py`, `cache_config.py` | — |
| 6 | the probe starts `vllm serve` and begins watching stdout | `probe.py`, `recorder.py` | **B** starts |
| 7 | vLLM does its four things; its own log lines become marks | vLLM, `vllm_logs.py` | **B** |
| 8 | ten requests go in; the engine is timed warm | `probe.py` | **B** |
| 9 | the result returns on the result channel, not the log channel | `handler.py` | — |
| 10 | three clocks are reconciled; the run is consistent or it isn't | `checks.py`, `runpod_api.py` | A·B·C |
| 11 | one self-describing row is appended | `store.py`, `schema.py` | — |
| 12 | offline, with no GPU: gate → derive → intervals → chart | `analysis/*` | — |

### Zone 4 — vLLM, as a section rather than an aside

vLLM is the only component that is someone else's software and the only one
under test, so it gets a full section, skeletoned on the S-stages.

- **What an inference server is for**, in plain language — including continuous
  batching, which is *in* scope here because Part II act 4 depends on it.
- **Why each startup step costs real time**: loading weights into GPU memory,
  compiling the model, sizing the KV cache, capturing CUDA graphs.
- **The payoff — the KV capacity dividend.** vLLM cannot know how much memory is
  free for a KV cache except by running the model once and looking at what's
  left. On a cold arm the compiler's working set is still resident during that
  pass, so the engine permanently sizes a **20.3% smaller cache** — 4 concurrent
  requests instead of 5, for the life of that replica. This is the most vivid
  "how vLLM actually works, and why it mattered here" story the artifact
  contains and it must not be reduced to a bullet.
- **The instrumentation point.** vLLM was never modified. Phase boundaries come
  from lines it already prints — `Model loading took`, `init engine (profile,
  create kv cache, warmup model) took`. Reading a black box's own output is the
  transferable trick.

### The component map

Every component gets a stated responsibility. The six-card limit controls
*depth*, not coverage — a one-line map entry is still a responsibility
sentence, which is what was actually asked for.

| zone | components | the idea it carries |
|---|---|---|
| 1 · your laptop (clock A) | `scheduler`, `cache_config`, `preflight`, `driver`, `submitter`, `runpod_submitter` | the experiment is orchestrated from outside the thing measured |
| 2 · RunPod (clock C) | queue, GPU allocation, network volume, `runpod_api` | serverless means nothing runs until a request arrives |
| 3 · the container (clock B) | `handler`, `probe`, `recorder` | the stopwatch must live next to the thing it times |
| 4 · vLLM | weight load, compile, KV sizing, graph capture | someone else's software — the thing under test |
| 5 · the record | `schema`, `store`, `campaign.jsonl` | one self-describing JSON object per run, appendable so 300 runs can be resumed |
| 6 · offline, no GPU | `pipeline`, `metrics`, `vllm_logs`, `stats`, `figures`, `economics` | every published number is re-derived here |

**Edges carry labels.** The user asked how components *interact*, so an edge
states what travels it: `{arm, run_id}` job input → `vllm serve` subprocess →
stdout lines → `S*` marks → result JSON **on the result channel** → a
`campaign.jsonl` row → a derived row → a chart. Card field 4 highlights its own
edge on the map.

### The component card contract

1. **What it is** — one sentence.
2. **Its one job** — a responsibility, stated as a responsibility.
3. **Why it exists — the failure it prevents** — the concrete disaster averted.
4. **Hands off to** — the next component, highlighted on the map.

Then a **collapsed** code excerpt with a callout naming the line worth reading.
Field 3 is what makes a component memorable: a box in a diagram is forgettable,
a defence against a specific disaster is not.

### Six deep cards

Selected for a lesson that outlives this repo. Verified against source.

| component | the lesson |
|---|---|
| `preflight.py` | a safety check that can't do its job must fail, not shrug — it refuses an empty pin set rather than passing everything |
| `cache_config.py` | the experiment's one independent variable, expressed as an env dict merged into a subprocess copy so it cannot leak between runs on a reused worker |
| `worker/probe.py` | instrument a black box by reading what it already says about itself — including why the adjacent log lines were rejected |
| `worker/handler.py` | a correctness bug that looks like a simplification: the cache snapshot must precede the probe, because a cold compile creates the directory as a side effect of finishing. Moving it later still returns *a* boolean — while discarding ~200 of 300 paid runs *and* silently missing the leak it exists to catch |
| `checks.py` | three clocks on three machines, and what it means when they disagree by less than a round trip |
| `stubs/` | the whole campaign runs GPU-free against a fake endpoint — the reason any of this was testable without spending money |

`pipeline.py` and `stats.py` lose their deep cards to `cache_config` and
`checks`; their content moves into beat 12 and the statistics visuals below.

## Part II — the method narrative

Four acts reusing the Part I map as a scroll-driven spine. Each installs one
question and ends with a one-line real-world claim the reader judges.

| act | question installed | spine state | payoff chart |
|---|---|---|---|
| 1 · "81 seconds" is not a finding | How many runs? What was the spread? | one lane, n=1 | ECDF / spread |
| 2 · Decided before, or after? | Was that decided before you looked? | a gate ahead of the data | — (the admitted post-hoc rule) |
| 3 · Compared to what? | Compared to what, and where's the interval? | three lanes, one box differs | decomposition + **overlap trap** |
| 4 · What could you *not* conclude? | What did this fail to show? | one machine, H4 struck out | **NOT ANSWERABLE** figure |

Act 2 must include the artifact's own violation: `docs/post.md` states that the
rule separating one result was written after seeing the data. Teaching
pre-registration with an experiment that caught itself is more convincing than a
clean example, and it is the beat most likely to be remembered.

### Closing

The four questions as a screenshot-sized card. That card is the LinkedIn post;
the explainer is what it links to.

## Charts

Statistics get **shown**, not described — this was an explicit priority, and the
single most important claim in the artifact is one that cannot be made in prose.

| chart | source | shows |
|---|---|---|
| spread / ECDF | `campaign.jsonl` | one run tells you nothing; 100 runs have a shape |
| decomposition | `campaign.jsonl` | where the 81 seconds goes, per arm |
| **overlap trap** | `analysis.json` | A→B [10.67, 20.47] and B→C [25.97, 31.01] on one axis, then the difference [−20.30, −5.54] beside them — you cannot get the third by eyeballing the first two |
| bootstrap resample | `campaign.jsonl` | ~10 frames of resampling, showing what an interval *means* without deriving one |
| KV dividend | `analysis.json` | 35,792 vs 43,040 tokens → 4 vs 5 concurrent requests |
| NOT ANSWERABLE | `campaign.jsonl` | act 4's payoff |
| warmup | `campaign.jsonl` | "ready is already fast" — the pre-registered expectation that was wrong |

## Anti-drift requirements

A tutorial about measurement discipline that silently disagrees with its own
dataset is self-refuting.

1. **Numbers.** The build script renders numbers from an **explicit key list**.
   Keys present in `analysis.json` are read from it; everything else
   (per-phase medians, the paired B→C contrast, the first-touch run, KV
   concurrency) is computed from `campaign.jsonl` through `pipeline.partition()`
   and `stats`. A test asserts each key on the list resolves and matches.
   *Not* "every number matches `analysis.json`" — that was unsatisfiable, since
   `analysis.json` carries only `paired_A_to_B_t_weights` and no per-phase rows.
2. **Code excerpts.** Anchored by `# explainer:<slug>` sentinel comments added to
   the source files, with the excerpt spanning to a closing sentinel. Anchors
   are sentinels rather than line ranges or function names because the
   harness-extraction plan rewrites import paths and will move this code.
   Excerpts carry their comments — in `handler.py` the comment *is* the lesson.
   A test fails when a sentinel disappears.
3. **Charts.** Regenerated from `campaign.jsonl` via matplotlib's **SVG
   backend**, reusing `coldstart/analysis/figures.py` rather than hand-rolling a
   second renderer. Its phone-legibility floor (`phone_pt`) then applies
   unchanged.
4. **No line counts in cards** — they drift on every edit and no guard covers
   them.

## Jargon contract

"Avoid jargon" is not testable; this is. Exactly these terms may appear, each
with a one-sentence plain-language definition at first use: cold start, HBM, KV
cache, `torch.compile`, CUDA graph capture, continuous batching, bootstrap
interval, percentile/ECDF, contrast, pre-registration. **A term outside this
list may not be used without being defined or replaced.** A build check greps
the rendered page for the definition of each term that appears.

## Build and tooling

- **Output**: a published Artifact — a private page with a shareable link.
- **Self-contained**: a strict CSP blocks external hosts, ruling out
  scrollytelling libraries. Scroll choreography is `IntersectionObserver`.
- **Spine diagram**: hand-authored inline SVG with **12 discrete states**, one
  per Part I beat, plus 4 for Part II's acts. Each state changes exactly one
  thing: a zone lights, an edge animates, a clock badge activates.
- **Phone**: below 768px the spine moves above the prose and pins at reduced
  height; the map carries ~24 boxes, so the phone view shows zone-level
  granularity only, expanding on tap. Text follows `figures.py`'s floor.
- **Theme**: must render correctly in light and dark.

## Out of scope

- A present/deck mode.
- An interactive parameter playground.
- Deriving the bootstrap mathematically — what an interval *means* is in scope
  and now has its own animation; the derivation is not.
- A second page. One artifact, two parts.

## Risks

**Part I is the half that can bore.** It is reference-shaped by nature. Controls:
the journey spine gives it narrative momentum, the six-card limit caps depth,
and every card leads with a disaster rather than a description. If review finds
Part I still drags, cut cards — do not add prose.

**The two audiences pull the page apart.** Part I wants depth, Part II wants
compression. The disclosure pattern is the control: prose complete, code
collapsed. If Part II starts acquiring Part I's detail, the split has failed.

**"Spot a bad benchmark" is a skill, and exposition does not install skills.**
Mitigated by the per-act judgement exercise.

**~24 boxes on one diagram.** Phone legibility is the named risk; zone-level
collapse is the control.
