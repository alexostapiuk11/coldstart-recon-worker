# Cold Start Explainer — Design

A scrolling explainer that teaches the artifact-1 system and the measurement
method behind it, built as a published Artifact.

## Why this exists

`docs/post.md` is the artifact's result. It assumes the reader already knows
what HBM, a KV cache, CUDA graph capture and `torch.compile` are. This document
specifies a different thing: the explainer that gets someone to the point where
the post is readable.

## Two audiences, in order

**Now — the author.** Wants to understand the system he commissioned: which
components exist, what each is responsible for, what vLLM is, how it was
instrumented. Depth is welcome; this reader will click into code.

**Later — a professional audience (LinkedIn).** Wants a transferable skill, not
facts about vLLM. The durable value is *how to judge a performance claim*.

These are not served by two documents. They are served by one page with two
parts, where Part I is complete on its own and Part II reuses its diagram.

## Learning objectives

Part I — the reader can name every component of the measurement apparatus, say
what each is responsible for, explain what vLLM does during a cold start, and
describe how it was measured without being modified.

Part II — the reader can look at any performance claim and ask the four
questions in the closing card.

## Structure

### Part I — the architecture tour

Explorable, not narrated. A map of six zones; clicking a component opens its
card.

| zone | contains | the idea it carries |
|---|---|---|
| 1 · your laptop | scheduler, preflight, driver, submitter, recorder | the experiment is orchestrated from outside the thing being measured |
| 2 · RunPod | queue, GPU allocation, network volume | serverless means nothing is running until a request arrives |
| 3 · inside the container | handler, probe, log reader, warmup requests | the stopwatch has to live next to the thing it times |
| 4 · vLLM | weight load, compile, KV sizing, graph capture | someone else's software — the thing under test |
| 5 · the record | schema, `campaign.jsonl` | one self-describing JSON object per run |
| 6 · offline | pipeline, metrics, stats, figures | every published number is re-derived here, with no GPU |

**Zone 4 gets a sub-tour.** What an inference server is, in plain language. Why
each of its four startup steps costs real time. And the instrumentation point:
vLLM was never modified — the phase boundaries come from log lines it already
prints (`Model loading took`, `init engine (profile, create kv cache, warmup
model) took`). Reading a black box's own output is the transferable trick.

### The component card contract

Every card answers the same four questions, in this order:

1. **What it is** — one sentence, plus file and line count.
2. **Its one job** — a single responsibility, stated as a responsibility.
3. **Why it exists — the failure it prevents** — the concrete disaster averted.
4. **Hands off to** — the next component.

Then a **collapsed** code excerpt, extracted from source at build time, with a
callout naming the line worth looking at.

Field 3 is the one that makes a component memorable. A box in a diagram is
forgettable; a defence against a specific disaster is not.

### Six deep cards

Not twenty. Twenty equal-weight cards is a reference manual, which is the
failure mode this explainer is defined against. Selected for having a lesson
that outlives this repo:

| component | the lesson |
|---|---|
| `preflight.py` | a safety check that can't do its job must fail, not shrug — it refuses an empty pin set rather than passing everything |
| `worker/probe.py` | instrument a black box by reading what it already says about itself |
| `worker/handler.py` | a correctness bug that looks like a simplification: the cache check must run *before* the probe, because a cold compile creates the directory as a side effect of finishing. Moving it later still returns *a* boolean — while discarding two thirds of a paid campaign and silently missing the leak it exists to catch |
| `analysis/pipeline.py` | an explicit gate between stored rows and consumers beats scattered validity checks |
| `analysis/stats.py` | what a bootstrap interval actually means, and the sample floors that withhold a number rather than publish a thin one |
| `stubs/` | the whole campaign runs GPU-free against a fake endpoint — the reason any of this was testable without spending money |

Remaining components get one line on the map.

### Part II — the method narrative

Four acts, reusing the Part I map as a scroll-driven spine. Each installs one
question and ends with a one-line real-world claim the reader judges.

| act | question installed | spine state | payoff |
|---|---|---|---|
| 1 · "81 seconds" is not a finding | How many runs? What was the spread? | one lane, n=1 | distribution chart |
| 2 · Decided before, or after? | Was that decided before you looked? | a gate ahead of the data | the artifact's own admitted post-hoc rule |
| 3 · Compared to what? | Compared to what, and where's the interval? | three lanes, one box differs | the 81-second decomposition |
| 4 · What could you *not* conclude? | What did this fail to show? | one machine, H4 struck out | the NOT ANSWERABLE figure |

Act 2 must include the artifact's own violation: `docs/post.md` states that the
rule separating one result was written after seeing the data. Teaching
pre-registration with an experiment that caught itself is more convincing than
teaching it with a clean example, and it is the beat most likely to be
remembered.

Act 3 must state the difference-of-contrasts point: to claim one cache beats the
other you need the interval on *the difference*, not two separate intervals
eyeballed for overlap. This is the most common error the explainer can
inoculate against.

### Closing

The four questions as a screenshot-sized card. That card is the LinkedIn post;
the explainer is what it links to.

## Data-driven content

Three charts, all generated from committed data — never hand-drawn, never
retyped:

| chart | source | shows |
|---|---|---|
| spread | `data/campaign.jsonl` | one run tells you nothing; 100 runs have a shape |
| decomposition | `data/campaign.jsonl` | where the 81 seconds goes, per arm |
| intervals | `data/analysis.json` | the two contrasts and the interval on their difference |

Every inline number in the prose is rendered from `data/analysis.json` (for anything with an interval) or `data/campaign.jsonl` (for counts and medians) — never typed into the page by hand.

## Anti-drift requirements

A tutorial about measurement discipline that silently disagrees with its own
dataset is self-refuting. Three guards:

1. **Numbers** — a test asserts every number rendered into the explainer matches
   `data/analysis.json`.
2. **Code excerpts** — extracted from source files at build time by anchor. A
   test fails when an anchor no longer appears in its file. The
   harness-extraction plan rewrites import paths across every module, so
   hand-pasted snippets would go wrong the day it runs, and go wrong silently.
3. **Charts** — regenerated from `campaign.jsonl`; no committed chart that
   cannot be re-derived.

## Build and tooling

- **Output**: a published Artifact — a private page with a shareable link.
- **Self-contained**: a strict CSP blocks external hosts, which rules out
  scrollytelling libraries. Scroll choreography is `IntersectionObserver`,
  roughly forty lines.
- **Diagrams**: hand-authored inline SVG. They animate layer by layer; a
  matplotlib PNG cannot light up one box.
- **Charts**: authored as inline SVG generated by a build script from the
  committed data, so they inherit the page's theme and can be highlighted.
- **Build script**: reads `campaign.jsonl` and `analysis.json`, extracts code
  excerpts by anchor, emits the page.
- **Theme**: must render correctly in light and dark.
- **Phone**: the artifact's own figures regressed on phones twice. Text in
  generated SVG follows the same floor `coldstart/analysis/figures.py` enforces.

## Out of scope

Each of these is a place the explainer could turn boring or expensive, and none
serves either learning objective:

- A present/deck mode. The page converts to a carousel by hand later if wanted.
- An interactive parameter playground.
- Deriving the bootstrap from scratch — what an interval *means* is in scope;
  how to implement one is not.
- A full tour of HBM, CUDA graph internals, or continuous batching beyond what
  Part I's zone-4 sub-tour needs.
- Any second page. One artifact, two parts.

## Risks

**"Spot a bad benchmark" is a skill, and exposition does not install skills.**
Mitigated by the per-act judgement exercise. If those land flat in review, Part
II needs rework, not more prose.

**Part I could bloat into the reference manual it is defined against.** The
six-card limit is the control. Adding a seventh requires dropping one.

**The explainer duplicates prose already in `docs/post.md`.** Accepted: the post
is the result, the explainer is the teaching. They share data and code, not
sentences.
