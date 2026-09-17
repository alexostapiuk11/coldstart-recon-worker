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

0. **Pin the sample first.** The module uses the gated, repeat-host **n = 99**
   set — the one the ECDF plots and the post reports — not the raw n = 100 that
   still contains the 2,266.6 s first-touch run. The interval is therefore
   `[80.91, 85.88]`. Saying why is free, and shows beat 12's gate doing something
   in a tutorial whose act 2 asks "was that decided before you looked?"
1. **Refute with his own data.** Arm A's interval `[80.91, 85.88]` spans 82–85s
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
   money, and they set the interval's width. 10,000 resamples take well under a
   second on a laptop and are free (measure at build time — do not pin a
   literal, it is machine-dependent), and they change nothing past a point. Only the expensive
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

**Grounding contract.** Every number on this page is policed by an explicit key
list and a test; a free-running tutor reintroduces exactly the drift that guards
against. So: the tutor is invoked with the current section's rendered text
**plus the resolved numbers block for that section**, and is instructed to
refuse any figure not in that block and say it is refusing. **Placement is
per-card and per-chart, never a single global button** — a footer widget cannot
answer "what does *this paragraph* mean", which is the entire request.


### Modules

| # | module | page sections | min | checkpoint |
|---|---|---|---|---|
| 0 | diagnostic | — | done | done — see Calibration |
| 1 | one run's journey | Part I spine, beats 1–12 | 12 | narrate a run end to end, naming which clock is running |
| 2 | **spread vs interval** | ECDF + resample frames | 20 | predict the controlled test: same clusters, different split — what happens to the interval? |
| 3 | GPU memory, weights, and the ceiling | zone 4 intro | 8 | finish the consequence chain unaided |
| 4 | vLLM's four steps; the KV dividend | zone 4 section | 15 | explain why memory profiling needs a real forward pass |
| 5 | the six components | the six deep cards | 18 | for any card, state the failure it prevents |
| 6 | three arms; the difference of contrasts | act 3 + the shortcut panels | 12 | judge a claim from two intervals, and say what's missing |
| 7 | what could *not* be concluded | act 4 | 8 | name a limit the artifact states about itself |
| 8 | **teach it back** | the closing card | 30+ | draft the LinkedIn version; Claude plays an audience member who doesn't know the material |

**Statistics moved from position 5 to position 2.** The diagnostic called it the
highest-value module in the plan, and the earlier ordering put it behind four
modules covering material the learner measures as comfortable or better. It
needs only "runs have different durations", which beat 12 and the ECDF supply.
Teaching the comfortable material first and the large gap last inverts the
priority the diagnostic established.

**~2 hours total, and that number is a control.** Without it there is no way to
notice the plan has grown too long until someone is already bored by it — which
was the stated priority. If a module overruns its budget in practice, cut it;
the Risks section's "cut cards, do not add prose" only works once something
exists to cut, and a minutes column works before that.

Checkpoints require **production, not recognition** — answers in the reader's
own words, never multiple choice. Recognising an explanation and being able to
give one are different skills, and only the second is the stated goal.

Module 8 is the real assessment. The author's end goal is to teach this to
others, and preparing to teach is the most reliable way to discover what is not
actually understood — as module 5 demonstrated within this very session.

### Progress state

`docs/learning/progress.md`. One record per module, written by Claude at each
checkpoint:

```
module: 5
attempted: 2026-09-17
verdict: solid | fuzzy | not_attempted
what_the_answer_missed: <the specific gap, in the learner's own words where possible>
correction_issued: <what was shown, and whether it worked>
```

**Pass criterion**, uniform across modules: the learner states the idea in their
own words without the material in front of them, and the statement survives one
follow-up question. **On a fail, do not repeat the same explanation** — that is
what failed with the interval, twice. Branch to a different representation
(shrink the example, make it concrete, or find a case that breaks the wrong
model), and record which representation worked, because that is the finding
worth keeping.

Module 0 is already a completed record: verdict fuzzy, missed that an interval
ranges over *medians* rather than runs, corrected by the five-step sequence
above. Updated by Claude at each checkpoint, readable by the author, and the
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
| A | your laptop | `runpod_submitter.py` | submit → result, including all queueing |
| B | inside the container | `recorder.py`, `probe.py` | the engine's own startup, phase by phase |
| C | the platform (read on the laptop by `runpod_api.py`) | RunPod itself | its own view of the job lifecycle — as durations, never timestamps |

`checks.py` reconciles them. `T_platform = T_total − T_process` is a number
just clocks A and B: `checks.compute_residual(t_total, t_process)` takes nothing
else. Clock C is the only thing that can say how much of that residual was
queueing versus bring-up — and it reports *durations, not timestamps*, so even
that split is partial and `runpod_api` refuses to invent the rest.
`DEFAULT_RTT_FLOOR = 0.05` catches the case where A
and B disagree by less than a network round trip, which would mean the clocks
are lying. This machinery is what lets the post say "Failures: 0, Discards: 0"
and mean it.

**The S-stage vocabulary.** `S1…S7` are *this project's* names, not vLLM's —
vLLM prints prose and `vllm_logs.PATTERNS` and `probe`'s two regexes map it onto
the S-names. Saying vLLM shares the vocabulary would erase the instrumentation
trick described four lines later. It is the shared language between the probe
that marks the boundaries and the analysis that turns marks into a waterfall. `vllm_logs.PATTERNS` keys on `S4b`/`S4c`/`S4e`;
`MERGED = ["S4a", "S4d"]` is why the post has an "unattributed" row. Without
this vocabulary the waterfall chart is unreadable.

## Part I — one run's journey

The spine is a single run animated end to end through the apparatus. Each beat
lights its zone on the map and states which clock is running. The six deep cards
hang off this path as optional depth, not as the only way in.

| # | beat | components | clock |
|---|---|---|---|
| 1 | the schedule says run 147 is arm B | `scheduler.py`, `cache_config.py` | — |

*Beat 1's "run 147 is arm B" is true for the committed seed but is a data-dependent literal: it goes on the anti-drift key list, or a reseed silently falsifies the spine's opening line.*

| 2 | preflight refuses, or allows | `preflight.py` | — |
| 3 | the job is stamped and sent | `submitter.py`, `runpod_submitter.py` | **A** starts |
| 4 | RunPod queues it, rents a GPU, boots the image | platform, network volume | **C** |
| 5 | the container prepares arm B's cache state — and snapshots it *before* running | `handler.py`, `cache_config.py` | — |
| 6 | the probe starts `vllm serve` and begins watching stdout | `probe.py`, `recorder.py` | **B** starts |
| 7 | vLLM does its four things; its own log lines become marks | vLLM, `vllm_logs.py` | **B** |
| 8 | ten requests go in; the engine is timed warm | `probe.py` | **B** |
| 9 | the result returns on the result channel, not the log channel | `handler.py` | — |
| 10 | nothing is judged yet — the row goes down raw, valid or not | `driver.py` | — |
| 11 | one self-describing row is appended | `store.py`, `schema.py` | — |
| 12 | offline, no GPU: reconcile the three clocks → gate → derive → intervals → chart | `checks.py`, `runpod_api.py`, `analysis/*` | A·B·C |

### Zone 4 — vLLM, as a section rather than an aside

vLLM is the only component that is someone else's software and the only one
under test, so it gets a full section, skeletoned on the S-stages.

- **What an inference server is for**, in plain language, at the same depth as
  the KV bullet below — this reader does not know what one is, and "vLLM" stays
  a word until it becomes a thing. Required content, all of it already concrete
  in this repo: it replaces a loop calling `model.generate()`; it is an **HTTP
  server** that this repo starts as a **subprocess** (`vllm serve`, `probe.py`)
  listening on **port 8000**, which the probe polls at **`/health`** to know it
  is up and sends the ten warmup requests to at **`/v1/completions`**; it holds
  **one copy of the weights** and multiplexes many users' requests over it,
  which is what continuous batching means and why act 4 needs it; the KV cache
  is per-conversation scratch space, which is why it caps concurrency. Plus one
  "what vLLM is not" line: not a model, not a trainer.
- **Why each startup step costs real time**: loading weights into GPU memory,
  compiling the model, sizing the KV cache, capturing CUDA graphs.
- **The payoff — the KV capacity dividend.** vLLM cannot know how much memory is
  free for a KV cache except by running the model once and looking at what's
  left. On a cold arm the compiler's working set is still resident during that
  pass, so the engine permanently sizes a cache **16.8% smaller** — equivalently, a
  warm compile cache leaves **20.3% more** KV cache — 4 concurrent
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
| 2 · RunPod (clock C) | queue, GPU allocation, network volume | serverless means nothing runs until a request arrives |
| 3 · the container (clock B) | `handler`, `probe`, `recorder` | the stopwatch must live next to the thing it times |
| 4 · vLLM | weight load, compile, KV sizing, graph capture | someone else's software — the thing under test |
| 5 · the record | `schema`, `store`, `campaign.jsonl` | one self-describing JSON object per run, appendable so 300 runs can be resumed |
| 6 · offline, no GPU | `pipeline`, `metrics`, `checks`, `runpod_api`, `vllm_logs`, `stats`, `figures`, `economics`, `scripts/analyse.py`, `scripts/render_figures.py`, `analysis.json` | every published number is re-derived here — and this is where the three clocks are reconciled, not at run time |
| 7 · the test rig | `stubs/`, `fixtures/` | the campaign runs GPU-free against a fake endpoint, and every log parser is pinned against captured real output — the reason any of this was testable without spending money |

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
| `cache_config.py` | the experiment's one independent variable, expressed as an env dict with `run_id`-namespaced paths. The card must credit the merge correctly: `probe.run_probe` does `os.environ.copy()` then `update(env_overrides)`, which is what stops one run's cache leaking into the next on a reused worker |
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
| 3 · Compared to what? | Compared to what, and where's the interval? | three lanes, one box differs | decomposition + **the shortcut that got lucky** |
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
| **the shortcut that got lucky** | `analysis.json` + constructed | two panels, see below |
| bootstrap resample | `campaign.jsonl` | ~10 frames of resampling, showing what an interval *means* without deriving one |
| KV dividend | `analysis.json` | 35,792 vs 43,040 tokens → 4 vs 5 concurrent requests |
| NOT ANSWERABLE | `campaign.jsonl` | act 4's payoff |
| warmup | `campaign.jsonl` | "ready is already fast" — the pre-registered expectation that was wrong |

### The shortcut that got lucky — act 3's payoff, specified

An earlier draft called this the "overlap trap" and claimed a reader could not
get the difference by eyeballing the two contrasts. **That was false on this
data, and the chart would have taught the opposite of its lesson.** Subtracting
the endpoints naively gives `[-20.337, -5.501]`; the true difference interval is
`[-20.298, -5.537]` — the shortcut lands within 0.04 s. The two intervals also do
not overlap at all (20.47 < 25.97), so there was no overlap and no trap.

Two panels, and the second does the work:

**Panel 1 — the real campaign.** A→B `[10.67, 20.47]`, B→C `[25.97, 31.01]`, the
true difference `[-20.30, -5.54]`, and the naive subtraction drawn beside it,
landing almost on top of it. Caption: *the shortcut worked here.*

**Panel 2 — the same arithmetic, badly wrong.** A case where the two estimates
share a source of error, so the difference is known far more precisely than
either part and naive subtraction produces a wildly too-wide interval. This
artifact supplies it directly: the within-host paired contrast exists *because*
pairing cancels host effects, which is that correlation made concrete. Caption:
*same arithmetic, same confidence, wrong.*

The lesson is then the honest one, and stronger than the original claim:
**nothing visible in the two intervals tells you which case you are in.** That is
why the difference is computed rather than derived.

### Standing rule for every "this is the trap" example

Run the naive method a learner would actually try, against the real numbers,
**before** the example ships. Keep it only if the naive method visibly fails.

This spec wrote step 4 of the statistics sequence precisely because an example
that accidentally confirms the wrong model is worse than no example — and then
built act 3's payoff on that exact mistake. The rule exists because the
principle was already known and still not applied.

## Anti-drift requirements

A tutorial about measurement discipline that silently disagrees with its own
dataset is self-refuting.

1. **Numbers.** The build script renders numbers from an **explicit key list**.
   Keys present in `analysis.json` are read from it; everything else
   (per-phase medians, the paired B→C contrast, the first-touch run) is computed
   from `campaign.jsonl` through `pipeline.partition()`
   and `stats`. A test asserts each key on the list resolves and matches.
   *Not* "every number matches `analysis.json`" — that was unsatisfiable, since
   `analysis.json` carries only `paired_A_to_B_t_weights` and no per-phase rows.
2. **Code excerpts.** Anchored by `# explainer:<slug>` sentinel comments added to
   the source files, with the excerpt spanning to a closing sentinel. Anchors
   are sentinels rather than line ranges or function names because the
   harness-extraction plan rewrites import paths and will move this code.
   Excerpts carry their comments — in `handler.py` the comment *is* the lesson.
   A test fails when a sentinel disappears.
3. **Charts.** Regenerated via matplotlib's **SVG backend** from
   `coldstart/analysis/figures.py` rather than a second renderer. Four already
   exist and are reused as-is: `ecdf_plot`, `waterfall`, `warmup_curve`, and
   `per_host_medians` (whose single-host branch already renders "NOT
   ANSWERABLE"). **Three must be written**, and they live in `figures.py` so the
   sentinel and phone-floor machinery covers them: `shortcut_panels`,
   `resample_frames`, `kv_dividend`. Each routes every font size through
   `phone_pt` and every aggregate through `stats.median`, as the existing four
   do. `figures.py` pins `matplotlib.use("Agg")` at import and `dpi=150` at each
   `savefig`; SVG comes from the output extension.
4. **A prerequisite, not an assumption.** Module 5's headline number — arm A's
   `[80.91, 85.88]` — is a bootstrap CI on a *single sample's* median, and
   `stats.py` exposes no such function (only the two- and three-sample contrast
   forms). `stats.bootstrap_median_ci(values, iterations=10000, seed=0,
   alpha=0.05)` must be added first, reusing `_quantile` and honouring
   `MIN_BOOTSTRAP_SAMPLES`, so the most important module's numbers pass the same
   guard as every other number on the page.
5. **No line counts in cards** — they drift on every edit and no guard covers
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
  per Part I beat, plus 4 for Part II's acts. Each state changes at most one
  zone plus at most one clock badge — beats 3 and 6 light a zone *and* start a
  clock, so "exactly one thing" was already contradicted by the beat table.
- **Phone**: below 768px the spine moves above the prose and pins at reduced
  height; the map carries ~28 boxes, so the phone view shows zone-level
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

**~28 boxes on one diagram.** Phone legibility is the named risk; zone-level
collapse is the control.
