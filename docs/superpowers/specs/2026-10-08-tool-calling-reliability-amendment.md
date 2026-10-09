# How Tool Presentation Changes Failure Modes — Amendment

**Date:** 2026-10-08
**Status:** Approved 2026-10-08. All twelve decisions in §0 were signed off by the author in chat
on 2026-10-08, and the document as a whole was approved the same day.
**Artifact:** 3 of 5, now built next, after artifacts 2 and 4 publish
**Amends:** [2026-08-17 tool-calling reliability design](2026-08-17-tool-calling-reliability-harness-design.md)
**Depends on:** the harness (`harness/`, landed 2026-10-04) for storage, scheduling, the campaign
loop, the publishability gate and the figure guards. No GPU, no RunPod.

The August design was written before artifacts 1, 2, 4 and 5 had settled how this repository
pre-registers, amends, records spend and publishes. Since then, three things have changed. Two of
its three headline claims now have prior art. The current cheap Claude models refuse a temperature
parameter. And provider strict modes make one of its six failure categories impossible by
construction. This amendment re-checks the design against all three and against the house process.
It defines the quantities the August design left undefined, so a plan can be written without
inventing them.

**The August document stands unedited as the record of what was decided on 2026-08-17.** Where the
two conflict, this one governs. Everything this document does not mention is unchanged.

### How each claim below was checked

| Label | Meaning |
|---|---|
| **repo** | Read in this repository on 2026-10-08, at `de0cbc8` |
| **docs** | Read on the provider's official documentation page on 2026-10-08 |
| **paper** | Read on the paper's arXiv abstract page on 2026-10-08. The abstract, not the full text, unless stated |
| **secondary** | Reported by a research pass on 2026-10-08 and not re-read. Weaker than the above; each is re-checked before anything depends on it |
| **estimate** | Arithmetic or judgement, not measured |

---

## 0. Decisions signed off

Each changes a published claim, the design, or the budget. **All twelve were approved by the
author in chat on 2026-10-08.**

1. **The artifact is repositioned as a replication and extension (§2).** The lead becomes the
   failure-category breakdown of presentation effects and the cost per successful call, which has no
   published equivalent. H1 becomes an explicit replication of Guo et al. (2026). H5 becomes a test of
   presentation effects against the rerun noise floor, not a claim that reruns vary a lot.
2. **Primary model: `gpt-5.4-mini-2026-03-17`** with reasoning `none` (§3).
3. **Cross-model slice: `claude-sonnet-5-5`** with thinking `between_tools`, and
   **`gpt-5.4-nano-2026-03-17`** (§3).
4. **Schema strictness manipulates schema content only (§4a).** Provider constrained decoding is
   off in all eight cells and is run as one exploratory slice. Calls are graded against one canonical
   schema per tool (§4b).
5. **The high tool-count level is 20 tools, including 4–6 plausible confusables (§4c).**
6. **Scenario count S and repetitions N are chosen together from the pilot's intra-scenario
   correlation (§4d),** with floors N ≥ 5 and S ≥ 24. This reverses the August rule that scenarios
   shrink before repetitions.
7. **The recovery sub-design is kept, with a pre-registered floor rule (§4e).**
8. **Sources: a BFCL seed plus authored scenarios in neutral domains, with a confidentiality guard
   test (§6).**
9. **Statistics: a paired cluster bootstrap over scenarios on the risk-difference scale, Wilson
   intervals only within one scenario, and Holm's correction across the five hypotheses (§4f).**
10. **Clients: the official `openai` and `anthropic` SDKs behind one interface, called synchronously
    through the harness campaign loop. No Batch API (§7).**
11. **Permanent slug: `/experiments/tool-presentation-failure-modes` (§10).**
12. **The local-model smoke test becomes an optional, owner-run, zero-cost step (§9).**
    Hand-labelled cases for all six categories, including genuinely malformed calls, are required
    instead.

---

## 1. What changed since 2026-08-17

- **Sequence.** The author now targets lead agentic-engineer and ML-engineer roles at NYC fintech and
  big tech. Artifact 3 is the only agents and evals piece in a portfolio that is otherwise all LLM
  serving (artifacts 1, 2, 4, 5). It moves from "sequenced last and optional" to next. GPU-free and
  API code may start now. **The post publishes after the posts of artifacts 2 and 4**, the same
  ordering artifact 4's definition-of-done record applies to itself (**repo**, `docs/dod-a4.md` item 2).
- **Timebox.** About 3–4 weeks of part-time work, alongside interview prep. The binding constraint
  is scenario-authoring time, not money (§8).
- **Budget.** The $40–60 target stands. The August framing, "against $65–120 remaining after
  artifacts 1 and 2", is replaced by §8's figure recomputed from the spend records.
- **Confidentiality.** The author builds an agent platform at their current employer. Every
  scenario, tool, schema and datum here is public or synthetic. Nothing derives from the employer's
  code, designs, tool schemas or domains. Scenarios resembling insurance or claims workflows are
  excluded, and a test enforces it (§6).

---

## 2. Prior art, and the repositioned claim

### What is now published

The August design's prior-art argument was that existing benchmarks vary the model and hold the
prompt fixed. That is still true of the leaderboards. It is no longer true of the literature.

| Work | What it holds fixed and varies | Bearing on this design | Check |
|---|---|---|---|
| BFCL V4 format-sensitivity study (Berkeley, 2025-07-17) | Models fixed; 26 prompt-format variants (return format, doc format, tags, prompt style), prompt-mode models only | Varies format, not tool count, descriptions or strictness. No interactions, no repetitions | secondary |
| Guo, Dong, Gao, Das, *Learning to Rewrite Tool Descriptions for Reliable LLM-Agent Tool Use*, arXiv 2602.20426 (v1 2026-02-23, v2 2026-04-29) | Agent fixed; descriptions rewritten by a learned method; 0–150+ candidate tools added | **The closest work to H1.** Rewritten descriptions reduce accuracy degradation as the catalog grows ("reducing accuracy degradation by 29.23%"). Not a factorial; distractors mostly random; no strictness factor; no failure-category breakdown | paper |
| Chen et al., *Noise Floor Audit for Agent Benchmarks*, arXiv 2608.22331 (2026-08-23) | BFCL at temperature 0 on native tool-calling endpoints, reruns and semantics-preserving prompt perturbations | **The closest work to H5, and it points the other way.** Ever-flip fractions of 0.7%, 2.0% and 2.7% across three endpoints; prompt perturbations 11–58× noisier than reruns | paper |
| Gumaan, *Feedback That Backfires*, arXiv 2608.23651 (2026-08-24) | Models of 135M–1.7B; error feedback in the transcript | **The closest work to H4.** The failed call's presence in the transcript drives repetition; the error's wording contributes little. Frontier scale untested | paper |
| Kraishan, *Loud Failures, Quiet Failures*, arXiv 2610.10062 (2026-10-07) | Six models, 1,920 trials, explicit vs silent tool faults | "Identical repeats remained rare." A floor effect on H4 is likely | paper |
| τ-bench (2024), τ²-bench (2025), τ³ in the `tau2-bench` repository (v1.0.1, 2026-07) | Models vary; domains and tasks fixed | pass^k already makes repeated-trial consistency standard. Nothing varies tool presentation | secondary |
| LongFuncEval (2505.10570), RAG-MCP (2505.03275), *How Many Tools Should an LLM Agent See?* (2605.24660), *MCP Tool Descriptions Are Smelly!* (2602.14878), *The Constraint Tax* (2605.26128) | Single-factor studies of catalog size, description quality or schema constraints | Each covers one factor. None crosses factors or breaks effects down by failure category | secondary |
| Anthropic, *Writing effective tools for agents* (2025-09-11); OpenAI function-calling guide | Vendor advice | States most of the planned findings as advice (fewer tools, better descriptions, strict types, actionable errors), backed by internal evals with no published variance | secondary |

**What nobody has published, as far as this search found (moderate confidence):**

- a balanced factorial over tool count, description richness and schema strictness with a formal
  interaction test;
- with plausible confusables rather than random distractors;
- broken down into the six failure categories, so each factor's effect is attributed to the failure
  it moves;
- converted into cost per successful call and a token break-even.

### The repositioned claim

> Holding the model fixed, how tools are presented moves *which* failures happen, and the moves are
> attributable: tool count and confusables drive wrong-tool choices, schema content drives malformed
> and wrong-parameter calls, and description richness pays for its tokens only above a tool count
> this artifact measures. Reruns at the provider's most deterministic setting move results far less
> than presentation does.

The August through-line is unchanged and gets sharper. Point estimates hide the thing you care
about. And the unit of independent variation is the scenario, not the call. With near-deterministic
reruns, that is no longer a subtlety: N repetitions of one scenario carry close to one scenario's
worth of information (§4d).

**The related-work section names every row of the table above**, early in the post, as the August
design already requires. H1 is presented as a replication of Guo et al. under a stricter design.

### Hypotheses, as amended

These replace the August H1–H5. Their wording and estimands are frozen at step 1 of the
pre-registration (§5). Every estimand is defined in §4f.

- **H1 (replication).** The reduction in failure rate from rich descriptions is larger at high tool
  count than at low: the description-by-count interaction on failure rate is negative.
- **H2.** Schema strictness reduces the combined `MALFORMED` + `WRONG_PARAMS` rate, and its effect on
  `WRONG_TOOL` lies within ±δ₂ (an equivalence test, δ₂ fixed at step 1; proposed 2 percentage points).
- **H3.** Tool count's main effect on `WRONG_TOOL` is positive, and larger than both description
  richness's and strictness's effects on `WRONG_TOOL`.
- **H4 (frontier-scale test of Gumaan 2026).** In recovery scenarios, the identical-retry rate is
  higher after an opaque error message than after an actionable one. Subject to §4e's floor rule.
- **H5 (noise floor).** Tool count's main effect on failure rate exceeds, in magnitude, the same
  contrast computed between two halves of identical repetitions (an A/A contrast).

The August H5, that rerun variance is "large enough to matter operationally", is withdrawn as a
hypothesis. The rerun spread is still measured and published as a descriptive result (the ever-flip
fraction, §4f), because it is a property of the instrument, not a prediction about it.

---

## 3. Models and API settings

### Selection

| Role | Model and pinned id | Price per MTok (in / cached / out) | Check |
|---|---|---|---|
| Primary: full factorial, recovery, pilot | `gpt-5.4-mini-2026-03-17` | $0.75 / $0.075 / $4.50 | docs |
| Slice, smaller model | `gpt-5.4-nano-2026-03-17` | $0.20 / $0.02 / $1.25 | secondary; re-read before plan 2 pins it |
| Slice, frontier model from a different provider | `claude-sonnet-5-5` (dateless ids are pinned snapshots) | $2.00 / $0.20 / $10.00 | docs, and the Claude API reference cached 2026-09-25 |

**Why not a Claude model as primary.** **docs:** Claude Haiku 5.5 was released 2026-10-07 at
$0.10 / $0.50. Like every Claude model from 4.7 on, it returns a 400 on any non-default
`temperature`, `top_p` or `top_k`. Claude Haiku 4.5 still accepts temperature, but is reported as
retiring "not sooner than October 15, 2026" (**secondary**), inside this artifact's window. And
**docs:** Anthropic allows at most 20 strict tools per request, 24 optional parameters and 16
union-typed parameters across all strict schemas. That would bind the factorial's design.

**Why Sonnet 5.5 for the slice.** **docs:** `thinking: {type: "between_tools"}` is Sonnet 5.5's
documented way to turn thinking off, accepted at effort `high` or below. That is the closest match to
the primary's reasoning `none`. Opus 5.5 cannot turn thinking off at all. Forced `tool_choice` (`any`
or `tool`) returns a 400 on Sonnet 5.5. This design uses `auto` everywhere anyway, because `MISSING`
and `SPURIOUS` are only observable under `auto`.

### Settings held fixed, per call

| Setting | Primary and nano | Sonnet 5.5 |
|---|---|---|
| Endpoint | Responses API | Messages API |
| Reasoning / thinking | `reasoning.effort = "none"` | `thinking = {type: "between_tools"}`, effort `high` (its default) |
| Temperature | `0`, if plan 2's one-call check confirms the snapshot accepts it with reasoning `none`; otherwise the provider default, recorded as a deviation | Not settable (400). Provider default, recorded as a deviation |
| Provider strict mode | `strict: false` sent explicitly on every tool. **secondary:** the Responses API enables strict mode by default where it can | `strict` omitted (off) |
| Parallel tool calls | `parallel_tool_calls: false` | `tool_choice: {type: "auto", disable_parallel_tool_use: true}` |
| Tool choice | `auto` | `auto` |
| Tool search / deferred loading | Off. Every rendered tool is in context, or the tool-count factor never reaches the model | Off |
| Output cap | 1,024 tokens | 1,024 tokens |
| System prompt | One fixed text, identical in every cell, naming no tool | Same text |

**The temperature finding is reframed.** The August design pins temperature 0 and calls residual
variance at temperature 0 "itself a publishable result". On the current Claude models no temperature
can be sent. And the Noise Floor Audit has measured temperature-0 tool-calling reruns at the
endpoints it tested. The post states each model's setting as "the provider's most deterministic
available setting". It reports the ever-flip fraction per model as a property of that endpoint on
those dates, and does not generalise it.

**Pinning.** Every record stores the model id the request named and the model id the response
returned. A mismatch fails the record. The price table (`toolcall/prices.py`, plan 2) cites its
source page and read date, as artifact 5's rate did.

---

## 4. Design corrections

### 4a. Schema strictness is schema content, not constrained decoding

**docs:** with Anthropic's `strict: true`, sampling is grammar-constrained, and the input matches the
schema except on a refusal, a `max_tokens` truncation, or an enum value whose capitalisation differs.
OpenAI's strict mode is the same kind of guarantee (**secondary**). Under the August definition,
the strict arm would therefore make `MALFORMED` close to impossible by construction. H2 would test
the API, not the model.

**Correction.**

- **The factor is the schema the model sees.** High strictness renders enums, patterns and a
  disciplined required/optional split. Low strictness renders loose types: free-form strings for what
  are enums or patterns in the canonical schema, and no `required` list beyond the tool's single most
  obvious argument.
- **Constrained decoding is off in all eight cells** (§3's settings table).
- **One exploratory slice** re-runs the best cell with provider strict mode on, on the primary model,
  at the factorial's N. It is labelled exploratory in those words. It answers the practitioner's
  question: "if I turn strict mode on, which failures are left?"
- **Feasibility under the strict-tool caps.** The high-count level is 20 tools (§4c), so the
  exploratory slice fits Anthropic's 20-strict-tool cap if it is ever repeated on Claude. Each
  scenario's rendered strict schemas are checked against the 24-optional and 16-union caps by a test
  in plan 1, so the canonical schemas never depend on a feature one provider rejects.

### 4b. Grading is against one canonical schema

If the grader checked conformance against the *rendered* schema, the strict arm would have more ways
to be `MALFORMED` (an enum the loose arm never declared), and strictness would appear to cause the
failures it constrains. That is a measurement confound created by the instrument. The August design's
single-source discipline, "nothing else differs between them", applies to the grader too.

**Correction.**

- Each abstract tool has one **canonical schema**: its strict form. Every rendering is derived from it,
  and every call in every cell is graded against it.
- **`MALFORMED`** is structural only: no parseable call; arguments that are not a JSON object; a tool
  name that is not in the rendered set; a canonical-required key missing; or a value of the wrong
  JSON type after normalization.
- **Value-level violations become `WRONG_PARAMS`:** an enum value outside the set, a string that fails
  a pattern, or a value outside the acceptable set. A loose-arm call that sends `"NYC"` where the
  canonical enum wants `"JFK"` is a wrong parameter, in every cell alike.
- Enum comparison is case-insensitive, because **docs:** Anthropic does not guarantee enum
  capitalisation even under strict mode. That is normalization rule 1 in v1.
- The normalizer is versioned. Changing it is a breaking change, as August §4 requires. Its version
  is stored in every graded record.

### 4c. Tool-count levels

- **Low:** the 2–4 tools the scenario needs, with no distractors.
- **High:** exactly 20 tools. These are the low set, plus 4–6 **plausible confusables** written for
  that scenario (same domain, overlapping verbs or parameters), plus filler from the domain's tool
  library up to 20.
- Every scenario's confusables are named in its data file, so a `WRONG_TOOL` call can be attributed
  to a confusable or to filler. The post reports that split.
- 20 matches OpenAI's soft guidance of under 20 functions and Anthropic's strict-tool cap
  (**secondary** for the guidance, **docs** for the cap). It tests confusability rather than sheer
  catalog size, which Guo et al. and LongFuncEval already cover. The post says so.

### 4d. Scenarios and repetitions are sized together

The August rule, that scenarios shrink before repetitions, rested on rerun variance being the
headline. With near-deterministic reruns, an extra repetition of the same scenario adds almost
nothing to a cell rate's interval. The information is in the number of scenarios.

**estimate:** for S scenarios, N repetitions and intra-scenario correlation ρ (on the
correct/incorrect indicator, within one cell), the effective sample size is S·N / (1 + (N − 1)ρ). At
ρ = 0.9 and S = 30, going from N = 5 to N = 40 raises it from 32.6 to 33.2.

**Rule.**

- The pilot (§5) measures ρ in the baseline cell.
- Step 2 of the pre-registration fixes S and N to maximise effective sample size under the remaining
  budget. N is at least 5, enough to estimate per-scenario flakiness and the ever-flip fraction. S is
  at least 24 included scenarios, comfortably above the harness's bootstrap floor of 20
  (`MIN_BOOTSTRAP_SAMPLES`, **repo**).
- Target about 30 included scenarios, from about 45 candidates. Authoring time, not money, is what
  limits S.
- If the budget binds, N drops to its floor before S drops. This reversal of the August rule is
  stated in the post.

### 4e. Recovery: the floor rule

- The nested factor is kept: actionable vs opaque error messages, over the August design's four
  error kinds.
- It is run on two formulations: the baseline cell and the best cell from the factorial.
- *Revised during planning: at least 20 recovery scenarios are needed, not 8; see §14 item 1,
  which awaits the author's sign-off.*
- The turn budget is 3 attempts after the injected error.
- **Floor rule, pre-registered:** if the opaque arm's identical-retry rate has a point estimate below
  5%, H4 is reported as "not testable at this rate". It counts neither as support nor as refutation,
  and Holm's correction runs over the other four.
- The post cites Gumaan (2026) and Kraishan (2026) as the reason the floor rule exists.

### 4f. Statistics

The August §5 asks for both Wilson intervals on proportions and bootstrapping over scenarios. Applied
to cell rates, the two conflict. A Wilson interval over all S·N calls in a cell treats them as
independent, which is the error the clustering exists to prevent.

**Rules.**

- **Per-scenario rate:** the share of a scenario's N repetitions in a category, within one cell.
  Wilson intervals are used here and only here, where repetitions are the unit.
- **Cell rate** for a category: the per-scenario rates averaged over included scenarios, each
  scenario weighted equally. A scenario with many easy repetitions cannot dominate.
- **Effects** are on the risk-difference scale, in percentage points, fixed in advance because
  interactions depend on scale. A main effect is the standard 2³ contrast: the rate at the high level
  minus the rate at the low level, averaged over the other two factors. A two-way interaction is the
  factor's effect at the other factor's high level minus its effect at the low level.
- **Intervals** come from a paired percentile bootstrap over scenarios. Every scenario appears in all
  eight cells, so each draw resamples scenarios and recomputes every cell rate from the drawn set.
  10,000 iterations; the seed is fixed at pre-registration.
- **Confirmatory verdicts:** each hypothesis has a one-sided bootstrap p-value, the share of draws on
  the wrong side of zero. H2's equivalence part uses a 90% interval inside ±δ₂. Holm's step-down
  procedure runs across H1–H5 at a familywise 0.05. Everything else is labelled exploratory in those
  words.
- **The A/A contrast (H5):** each cell's repetitions are split by odd and even index. Tool count's
  contrast is then computed between the two halves of identical cells. The interval is bootstrapped
  the same way.
- **Ever-flip fraction:** the share of (scenario, cell) units whose N repetitions do not all land in
  one category. This is the Noise Floor Audit's measure, kept so the two are comparable.
- **Where the new code lives.** `harness/stats.py` is medians-only by design. Its own docstring says
  restricting statistics to medians keeps "a caller cannot smuggle a mean in" (**repo**). These
  proportion estimators therefore live in artifact 3's package, and `harness/` is untouched. A test
  like `tests/test_placement_no_reimplementation.py` checks that artifact 3 redefines no name that
  `harness.stats` or `harness.figure_guards` defines.

**Cost per successful call** is estimated from the data, not from an independence formula. The
August design defines it as total tokens, including failed attempts and retries, divided by
successes. A "retry until success" policy is costed by walking each scenario's repetitions in their
recorded order, up to a cap of 3 attempts. Under the usual geometric formula, cost is c / (1 − f);
that formula assumes retries are independent. With near-deterministic reruns, a failing scenario
fails again, and the geometric formula would understate cost. This is the artifact's
unit-of-variation argument in money. Break-even is the failure-rate reduction at which a richer
formulation's per-call token overhead is repaid. It is computed per pair of cells, from measured
token counts and the pinned prices.

### 4g. Provider-side outcomes are not model failures

Three outcomes are not one of the six categories. Each is counted per cell, excluded before any rate
is computed, and reported:

- `API_ERROR`: the request failed after the SDK's own transport retries.
- `REFUSED`: `stop_reason` or the provider's equivalent reports a refusal.
- `TRUNCATED`: the output cap was reached.

The campaign loop never retries a run in place (**repo**, `harness/campaign.py`), so a failure the
taxonomy cannot see stays visible. A cell where these three together exceed 2% of its calls is
flagged in the post.

A response with more than one call, despite parallel calls being disabled, is graded on its first
call. The count of such responses is reported.

---

## 5. Protocol and pre-registration

**Two dated steps, as artifact 4 did** (**repo**, `docs/experiment-a4.md`). The pilot is itself a
paid run, and N depends on what it measures.

**Step 1, committed before the pilot.** It fixes:

- the five hypotheses with their estimands, directions and δ₂;
- the selection rule and band;
- the baseline formulation;
- normalizer v1 and the grading procedure;
- the repetition and scenario floors;
- the models, settings and price table;
- the bootstrap seed and iteration count;
- the floor rule;
- the confidentiality rule.

Proposed values:

- **Baseline formulation:** low tool count, terse descriptions, loose schema. It is the minimal
  rendering, and a scenario that is not trivial there has room to move in both directions.
- **Band:** a baseline pass rate in [0.10, 0.90] over 10 pilot repetitions.
- **δ₂:** 2 percentage points.

**The pilot.** It is never campaign data, and it goes to its own store, as artifact 5's priming
runs did.

1. Every candidate runs at the baseline formulation, 10 repetitions each. This gives each
   candidate's baseline rate and ρ.
2. Ten candidates run in all eight cells at 5 repetitions. This gives measured cost per call per
   cell.

**Step 2, committed after the pilot and before any campaign call.** It fixes:

- the included scenario list, with every candidate's rate and its include or exclude decision;
- S and N, from §4d's rule;
- the measured cost per call;
- the budget computation and the approved spend.

**Selection.** The August §4 rule stands. Excluded candidates stay in the repository, flagged, and
re-runnable.

**Post-hoc changes** are numbered, dated amendments appended to `docs/experiment-a3.md`, as
artifacts 4 and 5 did. Nothing above an amendment is edited.

**Values as code.** `toolcall/prereg.py` holds the record, `toolcall/prereg_values.py` the values, and
a test fails if the table in `docs/experiment-a3.md` and the values disagree (**repo**, artifact 5's
pattern).

---

## 6. Scenario sources and the confidentiality guard

- **Public seed.**
  - Candidates come from BFCL's non-live single-turn categories: simple, multiple, irrelevance. The
    live categories are user-contributed, so their provenance is less clear.
  - **secondary:** the BFCL README states Apache 2.0 for its data.
  - Plan 1 reads the license file at the commit it copies from. It records that commit and attributes
    each seed scenario to its source id. No file is copied before the license is confirmed.
- **Authored scenarios** come from neutral domains: weather, calendar, travel, retail orders, files,
  units, library.
  - Each targets one failure mode, which is recorded in its data file.
  - Recovery scenarios are authored, because the mock tool layer is this artifact's own.
- **Excluded:** anything resembling insurance or claims workflows, and anything derived from the
  author's employer's code, designs, tool schemas or domains.
- **The guard test.**
  - It scans every scenario and tool-library data file, not code, for a vocabulary list: insurance,
    insurer, policyholder, claim and its inflections in a filing sense, underwriting, premium,
    deductible, adjuster, FNOL, coverage, beneficiary, actuarial.
  - It fails unless the file is listed in `toolcall/scenarios/confidentiality_signoff.json`, with
    the author's sign-off date.
  - Any list entry is reported to the author before commit. The test cannot read intent, so the
    pre-publish gate still includes the August non-negotiable item.

---

## 7. Repository fit

### Reused, no new code (**repo**)

| Need | Existing component |
|---|---|
| Append-only records | `harness.store.JsonlStore(path, record_cls)` |
| Interleaved order of (cell, scenario) runs within each repetition block | `harness.scheduler.build_schedule(conditions, blocks, seed)` |
| Schedule → submit → record → store, never retried, with the resume drift guard | `harness.campaign.run_campaign`. `submit` returns a `harness.submit.SubmitOutcome`; its `clock_A`, `payload` and `error` fields fit one API call |
| Publishable vs discarded vs failed rows | `harness.publish.partition`, `failure_rate_by_group` |
| N stated, empty input refused, no dropped series, phone legibility | `harness.figure_guards` |
| Medians of token counts and latencies, if reported | `harness.stats.bootstrap_median_ci` |
| Published figures re-derive from committed data | The pattern of `tests/test_a5_published_figures.py` |
| Post numbers generated, not typed | The marker-block pattern of `multilora/numbers.py` and `tests/test_a5_post.py` |
| Refuse to publish while a placeholder stands | The pattern of `scripts/a2_prepublish_check.py` |

### Not reused

`harness/runpod/`, `serve.py`, `bench.py`, `vllm_logs.py`, `gpu_util.py`, `service_sweep.py`,
`sweep_worker.py`, `recorder.py`, and `failures.py`. That last one's `FailureClass` covers platform
and engine failures; provider errors are §4g's three classes. No worker image and no Dockerfile
change.

### New: the `toolcall/` package

- scenario and tool-library schemas and loader;
- the formulation renderer;
- the canonical-schema grader and normalizer;
- the failure taxonomy;
- the mock tool layer and recovery loop;
- the provider interface, with OpenAI and Anthropic clients and a fake client;
- the record class and campaign wiring;
- the pre-registration record;
- the price table and cost guard;
- the proportion statistics and effects;
- cost per successful call;
- the analysis;
- the four figures;
- the numbers block;
- a bring-your-own-tools entry point.

**Boundaries.**

- `toolcall/` imports `harness/` and nothing from `coldstart`, `autoscale`, `placement`,
  `placement_measure` or `multilora`. This is checked transitively, in a fresh interpreter per module,
  as `tests/test_placement_boundary.py` does.
- `harness/` gains no import of `toolcall`.
- A no-reimplementation test as in §4f.

**Dependencies, additive to `pyproject.toml`:** `openai`, `anthropic`, and `jsonschema` (canonical
schema validation). *Revised during planning: no `jsonschema`; see §14 item 3.* Tests never import a provider SDK at module level, so the suite runs without
them configured.

**Spend guard.** Every paid script refuses to start without an explicit `--approved-usd` amount.
It also refuses when its own pre-run estimate (calls × measured cost per call) exceeds that amount,
and it stops at the amount if actual usage reaches it. This implements the portfolio rule that no
paid call runs without the author's explicit yes stating the number of calls and the estimated cost.

---

## 8. Budget

**Spent so far, from the spend records** (**repo**):

| Artifact | Spend | Source |
|---|---|---|
| 1 | $37.16 | `docs/spend-a2.md`, "Artifact 1, for the record" |
| 2 | $6.07 | `docs/spend-a2.md` |
| 4 | $25.23 | `docs/spend-a4.md` (billed; owner to confirm against the console) |
| 5 | $14.48 | `docs/experiment-a5.md`, "Actual spend" |
| **Total** | **$82.94** | Compute only; network-volume storage excluded throughout |

Against the original $200 envelope, **$117.06 remains**.

**Artifact 3's estimate.** **estimate**, at the prices in §3. The token assumptions:

- a base prompt of 300 tokens;
- per tool, 30 (terse) or 200 (rich) description tokens, plus 40 (loose) or 120 (strict) schema
  tokens;
- 3 tools at low count, 20 at high, so cell input runs from 510 to 6,700 tokens, about 2,540 on
  average;
- 120 output tokens;
- for Sonnet 5.5, 1.3× tokenizer inflation (**docs**, the Claude 4.7+ tokenizer) and 300 thinking
  tokens.

| Component | Calls | Cost |
|---|---|---|
| Pilot (§5) | 450 baseline + 400 across cells | $1.48 |
| Main factorial, S = 30, N = 20 | 4,800 | $11.75 |
| Recovery, 8 scenarios × 2 formats × 2 cells × N = 20, about 3 turns | about 1,920 | $5.43 |
| Exploratory constrained-decoding slice, best cell (at the high cell's 6,700 input tokens) | 600 | $3.34 |
| Slice: gpt-5.4-nano, 2 cells | 1,200 | $1.05 |
| Slice: Sonnet 5.5, 2 cells | 1,200 | $16.29 |
| **Total** | | **about $39** |
| With 25% contingency | | **about $49** |

This is inside the $40–60 target, and about 42% of what remains in the envelope. S and N are refixed
at step 2 from measured cost per call, so these figures are a starting point, as artifact 5's
budget was.

**Cut order if the step-2 computation exceeds $60:**

1. the exploratory constrained-decoding slice;
2. the Sonnet slice's N, down to the floor;
3. recovery's second formulation;
4. the main factorial's N, down to the floor.

S is cut last. The second level of a factor is never cut.

**Spend record.** `docs/spend-a3.md`, in two parts:

1. **Computed from the data:** each response's `usage`, times the pinned price table.
2. **Read from the provider:** the OpenAI and Anthropic usage or billing pages for the campaign's
   dates, which the owner confirms, as artifact 4's record was confirmed against the console.

A difference above 5% between the two parts is explained in the record.

---

## 9. Process, aligned with artifacts 1, 2, 4 and 5

| August text | Now |
|---|---|
| "Pre-registration committed before the pilot runs" | Two dated steps (§5), and amendments appended, never edited in |
| "Pre-publish gate: same as artifacts 1 and 2" | The checklist, plus `scripts/a3_prepublish_check.py`. It refuses a `PUBLICATION-DATE` or `SPEND-PENDING` placeholder in the post, and `spend` null in the analysis, as artifact 2's script does |
| Numbers in the post | A generated block between `<!-- a3-numbers:start -->` and `<!-- a3-numbers:end -->`, with a drift test, plus a test that every headline number appears verbatim (artifact 4's `test_a4_post.py`) |
| Figures "rendered and visually inspected" | Rendered from `data/a3/analysis.json`; a published-figures test re-derives them; looked at at desktop and 375 px before commit |
| Spend | `docs/spend-a3.md` (§8) |
| Definition of done | A `docs/dod-a3.md` record, checked item by item, as `docs/dod-a4.md` was |
| §9b learning guide | A section of `docs/learning/plan.md` and `docs/learning/progress.md`, as artifacts 4 and 5 have. The §9b self-check is offered before plan 2 |
| Local-model smoke test (DoD) | Optional, owner-run and zero-cost. The author installs a local runner and a small tool-calling model; the grader runs on its output; the DoD item is met only if it ran. Hand-labelled cases for all six categories and every precedence boundary, including genuinely malformed outputs, are required regardless |

---

## 10. Permanent slug

**`/experiments/tool-presentation-failure-modes`.** It names the manipulated variable and the
measured thing, not the headline, so it stays true whichever result leads. The working title is
reworded at publication from the August *How your tool schema changes your failure rate*. "Schema"
undersells two of the three factors, and "rate" is the summary the post argues against.

---

## 11. August text this amendment supersedes

- **§1** "Measuring the residual failure-rate variance at temperature 0 is itself a publishable
  result": superseded by §2 and §3.
- **§1** "Existing benchmarks vary the model and hold the prompt fixed" as the whole differentiation:
  extended by §2's table and the replication framing.
- **§2** "~20 scenarios"; **§2** and **§9** "If budget binds, scenarios shrink before repetitions do":
  replaced by §4d.
- **§4** grading step 1, "conforming to the declared schema": replaced by §4b's canonical schema.
- **§5** factorial row "Schema strictness": clarified by §4a.
- **§5** "Tool count … large set with plausible distractors": fixed at 20 by §4c.
- **§5** temperature: replaced by §3's per-model settings.
- **§5** "Wilson score intervals on proportions" for cell rates: replaced by §4f.
- **§5** H1–H5: replaced by §2's amended hypotheses.
- **§5** "Committed to the repo before the pilot runs": replaced by §5's two steps.
- **§6** "against $65–120 remaining after artifacts 1 and 2": replaced by §8.
- **§6** local-model smoke test as a requirement: made optional by §9.
- **§8** post structure item 3: the related-work section names §2's table.
- **§10** "grader smoke-tested against a small local model's real output": optional, §9.

---

## 12. Definition of done — additions

Added to the August list. Nothing is removed except the item §11 makes optional.

- The twelve sign-offs in §0 recorded, and this amendment approved (both 2026-10-08).
- `toolcall/` imports nothing from another artifact's package, transitively, enforced by a test. It
  redefines nothing `harness.stats` or `harness.figure_guards` defines, enforced by a test.
  `harness/` is unchanged.
- `docs/experiment-a3.md` committed in two dated steps, each before the data it governs.
- Every model setting in §3 recorded per call, with the request body sent; the response's model id
  matched to the pinned id.
- Provider strict mode off in all eight cells, sent explicitly; graded against the canonical schema.
- `API_ERROR`, `REFUSED`, `TRUNCATED` and multi-call counts reported per cell.
- H4 reported as not testable if the floor rule fires.
- Cost per successful call computed from the recorded repetition order, not from the geometric
  formula, with the assumptions published.
- The confidentiality guard test passing, with every sign-off entry reviewed by the author.
- `docs/spend-a3.md` committed, with the owner's provider-console confirmation.
- `scripts/a3_prepublish_check.py` prints `ok`. `docs/dod-a3.md` records every item.
- Published after the posts of artifacts 2 and 4.

### Learning guide — additions to §9b

- **Module 6 is revised:** temperature cannot be set on current Claude models, and the Noise Floor
  Audit found tool-calling reruns at temperature 0 nearly deterministic. The module is now about
  telling rerun noise from presentation effects.
- **Module 9, new: constrained decoding vs schema content.** Why a provider's strict mode makes
  `MALFORMED` impossible by construction, and why this design manipulates the schema instead.
- **Module 10, new: scale and clustering.** Why an interaction depends on the scale it is measured
  on, and why N repetitions of a near-deterministic scenario are worth about one scenario.
- **Self-check additions:**
  - 11. Strict mode is on and `MALFORMED` is zero. What has been learned about the model?
  - 12. ρ is 0.9. What does a 20th repetition buy?

---

## 13. Risks — additions

| Risk | Handling |
|---|---|
| A reviewer cites Guo et al. or the Noise Floor Audit as having done this | §2's table in the post's related-work section, early; H1 framed as a replication; the decomposition and break-even as the contribution |
| The primary snapshot rejects temperature 0 with reasoning `none` | Plan 2's one-call check. If it fails, the provider default is used and recorded, and §3's reframing already covers it |
| A pinned snapshot is retired mid-campaign | Dated snapshots chosen; retirement dates re-read at step 2; the campaign is short (days) |
| ρ is near 1, so effects rest on about 30 clusters | §4d sizes S for it; intervals are reported as they come out |
| Few scenarios survive the band | More candidates are authored before step 2; the band is not widened after the pilot. Widening it would be an amendment, disclosed |
| Opaque-arm identical retries are rare | §4e's floor rule; reported as not testable |
| Scenario authoring overruns the timebox | Recovery scenarios are call scenarios with a recovery block (§14 item 1); S's floor is 24; the BFCL seed supplies part of S |
| A scenario resembles the author's employer's domain | §6's guard test and sign-off list; the pre-publish non-negotiable item |
| Provider prices change between the pilot and the campaign | The price table is re-read at step 2 and at the spend record; the spend record uses billed amounts |

---

## 14. Revised during planning, 2026-10-08

Writing and running plan 1's code in a copy of the repository changed seven details. Each is
listed with its reason. Item 1 changes a number in §4e and §8. **It needs the author's
sign-off and has not had it yet.** The others refine the approved decisions without changing
them.

1. **Recovery needs at least 20 scenarios, not 8.** H4's interval is a bootstrap over
   scenarios, and the harness refuses one over fewer than 20 (`MIN_BOOTSTRAP_SAMPLES`,
   **repo**). Eight scenarios could never yield a verdict.
   - Recovery scenarios are therefore call scenarios with a recovery block added, so the extra
     authoring is small.
   - The suite carries at least 28 of them, 22 with persistent error kinds, so that at least
     20 survive the band.
   - **estimate:** the recovery line in §8 rises from $5.43 to at most about $14 at N = 20, so
     the total with contingency reaches about $60, the top of the target.
   - At the N that §4d's rule picks under a high ρ (5 to 10), it stays near the original
     figure.
   - The cut order in §8 still applies. Recovery's second formulation is third in it.
2. **Recovery and slice repetitions follow §4d's N rule,** the same as the factorial. §8's
   table had assumed N = 20 for both.
3. **No `jsonschema` dependency.** Canonical schemas are restricted to a closed subset:
   - `string`, `integer`, `number` and `boolean`;
   - an `array` of one of those;
   - `enum` or `pattern` on strings.

   `toolcall/normalize.py` checks conformance in about thirty lines. The subset is what every
   provider's strict mode accepts, which §4a needs anyway, and a small checker is easier to
   publish as part of the normalizer than a library's full draft semantics. Only `openai` and
   `anthropic` are added to `pyproject.toml`.
4. **When `invalid_parameter` is injected.** The mock service rejects any call that matches
   no acceptable recovery call. The scenario's user message is written so that the natural
   first call does not match. A first call that already does is accepted, and the conversation
   is counted as "not injected" and excluded from the recovery measures. The other three kinds
   inject on the first call regardless of what it was.
5. **The spend guard uses a per-call upper bound,** not the largest call seen so far.
   - A call larger than any before it could otherwise cross the approved amount. A test caught
     exactly that.
   - The output bound is `max_output_tokens`, which is exact.
   - The input bound counts two characters of request JSON per token. The pilot checks that
     against recorded usage, and the step-2 script refuses to continue if any call broke it.
6. **A pattern value specification carries an `example`** that must match it. The loader
   checks the pair. The stub model and dry runs use the example, so a dry run never needs to
   invent a value.
7. **Constrained decoding on OpenAI rewrites optional parameters.** OpenAI's strict mode needs
   every property in `required`, so optional ones become a union with `null`, in the
   exploratory slice only (`openai_strict_parameters`). The factorial's schemas are untouched.
