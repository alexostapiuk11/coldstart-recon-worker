# Interview-oriented learning resources for artifacts 1, 2, 4, 5, 6, 7

Date: 2026-10-18. Status: draft for the owner's review.

## Goal

The owner is an SDE preparing to explain these six projects in interviews and
hiring-manager conversations. Most interviews will be ordinary project deep dives and
behavioural rounds; these projects come up some of the time, not always. The owner needs
**intuition for the logic, not recall of numbers**: what problem drove each artifact, how
the system is shaped, which decisions defined it, and why the answer follows from the
data. Numbers appear only as the evidence that derives an answer.

The existing material (`docs/learning/plan.md`, the explainer pages) is built for
defending results module by module, at about 2 to 2.5 hours per artifact, and the owner
finds it too text-heavy to remember. This work replaces it as the *study path*; the old
plans and pages stay as reference and are not deleted.

## Scope

In: artifacts 1 (cold start), 2 (autoscaling signal), 4 (dedicate/swap/share),
5 (multi-LoRA capacity), 6 (duplicate-payment defenses), 7 (matching-engine tail), plus two
shared prerequisite pages.

Out: artifact 3 (no results yet). Artifact 6 results (the campaign is unread by
pre-registration rule; its page covers requirements, architecture, decisions and flow, and
says "results pending"). Any change to the posts, data or code.

## Deliverables

Per unit, two files under `docs/learning/study/<unit>/`:

- `page.html`: the visual study page, published as a private Artifact; the URL is
  recorded in `docs/learning/plan.md`.
- `brief.md`: the chat brief, the same facts in compact markdown, pasteable into any AI
  chat, ending in the interview-mode prompt.

Units: `p1-llm-serving`, `p2-trusting-experiments`, `a1`, `a2`, `a4`, `a5`, `a6`, `a7`.

Artifacts 6 and 7 live in other repos (`~/projects/ledger-faults`,
`~/projects/matching-engine-tail`); their sources are read from there, their study files
are written here so all study material sits in one place.

## Shared prerequisites

| Unit | Used by | Covers |
|---|---|---|
| P1 LLM serving on a GPU | 1, 2, 4, 5 | weights vs KV cache, GPU memory as the ceiling, what vLLM does, continuous batching, cold start, serverless GPUs |
| P2 How these experiments earn trust | all six | percentiles and tail latency, pre-registration, spread vs interval, validation gates and amendments, why a failed gate is a result |

Single-artifact concepts get a short "need to know" section inside that artifact's page:
Little's Law and the load balancer (2), Zipf skew (4), LoRA adapters (5), Kafka, outbox
and idempotency (6), the JVM, Disruptor ring and `fsync` (7). P1 and P2 are about 20
minutes each.

## Page template (about 45 minutes per artifact)

Order, about 5 minutes per section, then recall:

1. **Why it exists.** One-sentence question; the initial requirements that drove
   everything, as a short list.
2. **System views, C4 style.** Context (who and what it touches), containers (the
   deployable or runnable parts), components (inside the one container that matters), and
   one dynamic view tracing a single run, request or message. No code level. Diagrams are
   inline SVG, one idea each, labelled in plain words.
3. **Core decisions (4 to 6).** One card each: the problem, the options considered, what was
   chosen, why, and what it cost. The decision list is the page's spine; later sections
   point back to it.
4. **Implementation flow.** From experiment design to the published claim, as a phased
   timeline with milestones (see "Implementation flow" below).
5. **Results as meaning.** Each chart carries "this axis means", "read it as", and "so the
   decision was". Numbers are shown only where they derive the answer.
6. **Interview card.** 30-second pitch, 2-minute version, and the likely hard follow-ups
   with a short answer each, plus an honest "limits" line (what the artifact cannot claim).
7. **Recall check.** Questions with answers hidden until revealed, aimed at the "why" and
   at the decisions, not at numbers.

Design rules from the owner's complaints: short blocks instead of paragraphs; one diagram
or interaction per idea; every chart annotated; no section that is only text.

### Implementation flow (required for every artifact unit)

The flow says how the implementation was actually done, step by step, so the owner can
narrate it in order. Each artifact unit's `flow` has:

- **Phases:** 5 to 12 steps grouped into at least two consecutive phases (for example
  design, build, measure, analyse and publish), shown in the order written.
- **Steps with outputs:** every step has a short label, a short detail and an `output`,
  one line naming what concretely existed after it (for example "a frozen
  pre-registration"); a step tied to a decision names it, and the page links the two.
- **Milestones:** 2 to 6 steps are milestones, each with a date (`when`) and git evidence
  (`evidence`: the commit, and its repo when that is not this one).
- **Derived, not remembered:** steps, dates and commits come from the repo's git history
  and plans (`git log`, the plan and spec documents), not from memory.
- **Verified:** the schema enforces the rules above, and the per-unit evidence test checks
  that every cited commit exists in its repo.

## Interview mode

Lives at the end of each `brief.md` as a prompt to paste into an AI chat, and is also
summarised on the page. Settings the owner can change in the paste:

- **Audience:** hiring manager (impact, ownership, trade-offs, what I would do differently),
  senior peer (technical depth on the decisions), or skeptic (pushes on every hand-wave).
- **Depth:** pitch (30 s), standard (2 to 5 min of follow-ups), deep (10 min, 3 levels of
  "why").
- **Mode:** ask me, or quiz me on recall, or grade my answer against the brief.
- **Rules built in:** one question at a time; do not reveal the brief's answers unprompted;
  after each answer, say what was solid, what was missing, and what the stated limits
  require me to admit; never let me claim more than the artifact supports.

## Sourcing and accuracy rules

The owner has twice caught unverified claims in earlier work, so:

- Every fact on a page and in a brief comes from the artifact's post, pre-registration,
  results document or code, read in this session. Each unit ends with a "Sources" list of
  file and section.
- Where a claim is the author's interpretation rather than a measured result, the page
  says so. Where a source is missing or the post is a draft (6, parts of 2 and 4), the page
  says so rather than filling the gap.
- Each page is checked against the source by a second pass (a reviewer agent) before it is
  published.

## Verification (the owner's standing rule for UI work)

Each page is opened in a browser at desktop and phone width, screenshots are inspected, and
interactive elements (reveal-answer, any toggles) are clicked. `verifying-visual-output`
applies; DOM presence alone is not evidence. Skills `artifact-design`, `artifact-diagramming`
and `dataviz` are loaded before writing pages.

## Build order (approach A: pilot, then fan out)

1. Pilot: **P1** and **A1**. A1 depends on P1 and has the most existing material.
2. Owner review of the pilot's format: density, diagram level, interview mode. Template
   changes are made here, once.
3. Fan out: P2 and A2, A4, A5, A6, A7 from the approved template, in parallel where
   independent. A6 and A7 read their sources from the other repos.
4. Record URLs in `docs/learning/plan.md` and a pointer in `docs/learning/progress.md`
   (`progress.md` stays the owner's record; the new units add no verdicts).

## Risks

- **Format miss.** Mitigated by the pilot gate.
- **Reduction drops a true caveat.** Mitigated by the Limits line in every interview card
  and the reviewer pass. A simplified result must not claim more than the post does (e.g.
  artifacts 2 and 4 failed their validation gates; their conclusions are stated as
  unvalidated).
- **Artifact 6 pages go stale** once its results exist; its page carries a "results
  pending" marker and the brief says how to extend it.
- **Working tree.** `docs/learning/plan.md`, `progress.md` and an artifact 3 plan are
  modified by other sessions; the pilot does not touch them until step 4, and only edits
  plan.md after checking its state.
