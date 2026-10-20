# Which tool-calling failures tool presentation moves: chat brief

## How to use this brief

Paste this whole file into an AI chat, then paste the prompt at the end (it is already the last section). Ask clarifying questions about anything below. About 45 minutes to study.

Read first: How these experiments earn trust (P2).

## Why it exists

**Question:** **No data yet: no campaign has run, and no result is shown. This page shows the question, the instrument, the predictions and the controls only.** Hold one model fixed and change only how its tools are presented: 2 to 4 tools or 20 with look-alikes, terse or rich descriptions, loose or strict schemas. Which kind of failure moves: a call that is not valid, a call nobody asked for, a missing call, the wrong tool, or the wrong arguments? And what does each presentation cost per successful call? 49 candidate scenarios in seven public or synthetic domains, graded by rule with no LLM judge. The sources disagree in one place (see the known contradiction); this page follows the amendment that governs.

**Requirements that drove everything:**

- Every scenario is rendered in all eight cells (tool count × description richness × schema strictness), and the renderings differ only in the factor being manipulated. *Why:* Otherwise a difference cannot be pinned on presentation. It is the same single-variable discipline the other artifacts apply to their arms.
- Every response is graded by an ordered procedure into exactly one of six categories, against each tool's single canonical schema, with a versioned normalizer. No LLM judge. *Why:* A judge adds its own variance to the quantity under study, and a harness that answers differently twice cannot be adopted. Each category points at a different fix.
- Rates are averaged per scenario, intervals resample whole scenarios, and the number of repetitions is sized from the pilot's intra-scenario correlation. *Why:* Reruns of a scenario the model finds confusing fail for the same reason each time. Treating calls as independent makes intervals far too narrow and manufactures significance.
- After an injected tool error, measure whether the model repeats the failing call unchanged, with the error message either actionable or opaque. *Why:* Repeating a failing call verbatim turns one error into a token-burning loop; an actionable message should prevent it. It is a mechanism-level prediction that gets tested, not asserted.
- Hypotheses, band, grading and floors are committed before the pilot; the scenario count, repetitions, included scenarios and approved spend before any campaign call. No paid call runs without a stated call count and cost. *Why:* N depends on what the pilot measures, git timestamps must show the order, and the portfolio's spend rule is made mechanical by a guard.
- Every scenario, tool and schema is public (a BFCL seed) or authored in neutral domains; nothing derives from the author's employer. A scan of the data files fails the tests unless the author has signed off each hit. *Why:* The author's confidentiality boundary. The scan cannot read intent, so a pre-publish check by the author remains.

## Need to know first

- **Six categories, and the first rule that applies wins**: The model executes nothing: it emits a structured request (a tool, JSON arguments) and the harness decides what to do with it, so every failure is a property of that request and needs no judgment about meaning. Provider errors, refusals and truncations are excluded first and counted per cell. Then: `MALFORMED` (not a valid call to a tool that was shown: unparseable, a tool not in context, a required key missing, a wrong JSON type), `SPURIOUS` (a call where none was expected), `MISSING` (no call where one was), `WRONG_TOOL`, `WRONG_PARAMS` (a wrong value, enum or pattern miss, or an unknown key), `CORRECT`. The category depends on what was rendered: a call to `get_current_weather` is `MALFORMED` in a cell that shows two other tools and `WRONG_TOOL` in the 20-tool cell that shows it. Think of it as: The model is a client sending an RPC, the harness a gateway validating it: parse, then schema, then routing, then business rules. The order is part of the contract, as a 400 is decided before a 404.
- **The eight cells**: Three factors, two levels each: tool count, description richness, schema strictness; the table under Results shows the levels. Baseline: low, terse, loose. Think of it as: A configuration matrix in which each axis changes one thing and the system prompt is one fixed text in every cell, like a deploy matrix that differs only in the flag under test.
- **Strictness is schema content, and every call is graded against one canonical schema**: Each tool has one canonical schema, its strict form, and every call in every cell is graded against it, whatever the model was shown. A loose schema is charged for constraints it never showed: that is the measurement of what loose costs, not a bug. Provider strict mode (constrained decoding) stays off in all eight cells; decision D2 gives the reason. Think of it as: Contract testing: a consumer's request is validated against the provider's real contract, not the subset the docs showed. And a type system that makes invalid states unrepresentable versus documentation plus a validator at the edge: this study asks whether the model reads the documentation.
- **The unit of independent variation is the scenario**: N reruns of one scenario carry between one and N scenarios' worth of information, set by the intra-scenario correlation ρ. S scenarios × N repetitions have effective size S·N / (1 + (N − 1)ρ), which approaches S/ρ however many repetitions are added. Intervals resample whole scenarios; Wilson intervals are used only within one scenario. Think of it as: A flaky test failing 20 times in CI is one bug with 20 symptoms. A dashboard counting failures counts symptoms; the bootstrap over scenarios counts bugs.
- **Main effects, interactions and the scale**: A main effect is the high-level rate minus the low-level rate, averaged over the other two factors, in percentage points. An interaction is one factor's effect at the other's high level minus its effect at the low level: the difference, as the code computes it, not that difference halved. Say which convention you mean. The scale is fixed in advance because an interaction on the percentage-point scale can vanish on a ratio scale. Think of it as: An ablation table where you ask not only whether a component helps, but whether it helps more on a large cluster than on a small one.
- **The baseline band, and what it selects**: Every candidate runs 10 times at the baseline cell and is included if its correct rate falls in a band, proposed as 0.10 to 0.90 and frozen at step 1. It picks where the instrument has resolution: scenarios a model always passes could hide a real effect. Every candidate and decision is published, and excluded ones stay in the repository. One reading the sources do not state: a rate strictly between 0 and 1 means the reruns disagreed, so the band also selects for flipping; how many candidates survive is what the pilot measures. Think of it as: Sizing a load test: choose a load at which the system sometimes fails, because a load at which nothing ever fails cannot show which change helps.
- **Recovery, and the identical retry**: A mock service rejects a call as the scenario says (an invalid parameter, a contradicting result, a timeout or a malformed payload) in one of two formats: actionable (names the parameter, says what to do) or opaque (`Error: invalid request.`). Up to three attempts follow. Identical retry: the first action after the error repeats the failing call unchanged. For a rejection that is a loop; for a timeout it is the right move, so H4 counts the persistent kinds only. A conversation ends as `recovered`, `gave_up` (stopped calling, no success claim; includes asking the user), `hallucinated_success` (stopped calling, a success-shaped message with no disclosed failure: a pattern proxy with known misses), or `budget_exhausted` (rejected at the third attempt, neither of the other two). Think of it as: HTTP semantics: a 400 with a field error must not be retried unchanged, a 504 may be if the call is idempotent. An agent retrying a non-idempotent call after a timeout meets the duplicate-payment problem of artifact 6.
- **Cost per successful call, and the retry walk**: All spend, failed attempts included, divided by correct calls. A retry policy of up to three attempts is costed by walking each scenario's recorded reruns in order, not with c / (1 − f), which assumes each retry is an independent draw and understates the cost when a failing scenario fails again (see the retry walk). Think of it as: Capacity planning for retries: independent failures make retries cheap, but a poison message that fails every time makes every retry pure cost.
- **Known contradiction in the sources: the August learning guide against the amendment**: The August design's learning guide (§9b) and its definition of done (§10) predate the amendment that governs the design. Module 4 works an example of 20 scenarios × 20 repetitions = 400 observations; the amendment sets at least 24 scenarios and N from the pilot's ρ. Module 5 and §10 present Wilson intervals for reported proportions; the amendment allows Wilson only within one scenario. Module 6 teaches temperature-0 nondeterminism as the headline (August H5); amendment §12 revises it and adds a module on clustering, citing near-deterministic reruns. The amendment says it governs, and its supersession list (§11) replaces §5's Wilson-on-cell-rates and the ~20-scenario count, but does not name §9b's modules 4 and 5 or §10's Wilson item (§12 does revise Module 6). **This page follows the amendment.** Think of it as: A runbook that predates an incident-driven change to the design: where the two disagree, the later, approved document is the one to follow, and the stale one is a known trap.

## How it works

A prediction (H4), not a result: no model has produced it. It follows the committed code on `weather-forecast-lisbon`, baseline cell, opaque format; each state is what `recovery.converse` would record.

| Step | What happens | Model's latest turn | Grader, first call | Mock service reply | identical_retry | Conversation record |
|---|---|---|---|---|---|---|
| 1 | The user asks for Lisbon's weather over the next three days. The cell shows two tools, terse and loose: `get_forecast` and `get_air_quality`. The scenario has an `invalid_parameter` rule on `location`. | waiting for the first turn | not graded yet | no call yet | undecided | not injected yet |
| 2 | The model calls `get_forecast` with location "Lisbon" and days 3 (illustrative). Turn 0 is graded as a single-turn answer first: a shown tool, every required key, an acceptable value. (Decision: Grade by rule, against one canonical schema) | **get_forecast(Lisbon, days 3)** | **CORRECT (a bare city is allowed)** | no call yet | undecided | not injected yet |
| 3 | The mock service has its own rule: only "city, country" is accepted. This call matches no accepted recovery call, so it is rejected and the conversation counts as injected. The failing call's key is kept. (Decision: Keep the recovery sub-design, with a floor rule and at least 20 scenarios) | get_forecast(Lisbon, days 3) | CORRECT (a bare city is allowed) | **rejected: "Error: invalid request."** | undecided | **injected: yes** |
| 4 | The harness appends the model's raw output and the error, marked as an error, and asks again. The opaque text names no parameter and says nothing about what to change. | **asked again, up to 3 attempts** | CORRECT (a bare city is allowed) | rejected: "Error: invalid request." | undecided | injected: yes |
| 5 | H4's bet: the model repeats the call unchanged. The harness compares the normalized call with the failing one and records identical_retry, decided on this first action after the error only. (Decision: Keep the recovery sub-design, with a floor rule and at least 20 scenarios) | **get_forecast(Lisbon, days 3) again** | CORRECT (a bare city is allowed) | **rejected again, same text** | **true: same call as the failing one** | injected: yes |
| 6 | The model stops calling and answers in text. The text discloses a failure, so the code does not count it as a claim of success: the conversation ends as a give-up, not a hallucinated success. | **text: failure disclosed** | CORRECT (a bare city is allowed) | **no call, no reply** | true: same call as the failing one | **gave_up: yes; recovered: no** |

Bold cells changed in that step.

**Takeaway:** Single-turn CORRECT, conversation failed: two separate measures. In the actionable arm the error names `location` and an example; H4 predicts fewer identical retries there. Not observed.

## System views (C4)

### Who and what the experiment touches (context)

A deterministic harness, `toolcall/`, with no GPU. It reuses the portfolio's `harness/` loop and stores and imports nothing from another artifact; a test enforces that. The pre-registration is not yet committed, no model API has been called for data, and no result store exists.

- **Author**: writes scenarios, runs, decides
- **Prior art**: Guo 2026, Noise Floor Audit, BFCL
- **Pre-registration**: step 1 not yet committed
- **Shared harness/**: campaign loop, stores, statistics
- **toolcall harness**: 49 candidates × 8 cells; a rule-based grader
- **Reader**: agent engineers; their own tools
- **Model APIs**: OpenAI, Anthropic; no data calls yet
- **BFCL seed**: 14 entries, Apache 2.0, pinned commit
- **Result stores**: JSONL records; none yet
- Author → toolcall harness: authors, runs
- Prior art → toolcall harness: gap it fills
- Pre-registration → toolcall harness: fixes the rules
- toolcall harness → Reader: diagnostic on their tools
- toolcall harness → Model APIs: paid calls
- BFCL seed → toolcall harness: seeds 14 scenarios
- Shared harness/ → toolcall harness: loop, stores, stats
- toolcall harness → Result stores: writes

### The parts of the harness (container)

Plain-data scenarios feed a renderer that makes eight request bodies per scenario. The runner schedules the calls behind a spend guard that writes each call's worst case to a ledger before the call. A recovery conversation is a separate multi-turn loop. Everything after the grader is pure functions over stored records.

- **Scenario + tool files**: 49 scenarios, 7 domain libraries
- **Renderer**: one scenario into 8 request bodies
- **Runner + spend guard**: schedule; approval; ledger
- **Provider clients**: OpenAI Responses, Anthropic Messages
- **Spend ledger**: reserve before, settle after
- **Recovery loop**: mock service, 2 error formats
- **Grader**: normalizer v1; canonical schema
- **Figures + numbers**: four figures; a numbers block
- **Analysis**: contrasts, bootstrap, H1 to H5, cost
- **Call records**: request, response, grade; JSONL
- Scenario + tool files → Renderer: tools, scenario
- Renderer → Runner + spend guard: 8 bodies
- Runner + spend guard → Provider clients: post
- Runner + spend guard → Spend ledger: reserve, settle
- Runner + spend guard → Recovery loop: recovery cells
- Provider clients → Grader: parsed call
- Recovery loop → Grader: first call
- Grader → Call records: graded record
- Call records → Analysis: per-scenario rates
- Analysis → Figures + numbers: one JSON file

### Inside the grader: the ordered rules (component)

One response, one category, the first rule that applies. A provider-side outcome is excluded before any rate. The same normalizer and canonical schema serve every cell, and a tool that was not rendered fails the structure check.

- **0. Provider side**: error, refusal, cap hit: excluded, counted
- **1. Structure**: invalid call to a shown tool: MALFORMED
- **2. Call, none expected**: any valid call: SPURIOUS
- **3. No call made**: answered without it: MISSING
- **Normalizer v1**: rules R1 to R10; canonical schema
- **5. Arguments**: match no acceptable call: WRONG_PARAMS
- **4. Tool**: not an acceptable tool: WRONG_TOOL
- **Grade record**: category, detail, flags, rules version
- **CORRECT**: every check passed
- 0. Provider side → 1. Structure: not excluded
- 1. Structure → 2. Call, none expected: a valid call
- 2. Call, none expected → 3. No call made: or no call at all
- 3. No call made → 4. Tool: a call was made
- 4. Tool → 5. Arguments: acceptable tool
- 5. Arguments → CORRECT: values match
- CORRECT → Grade record: recorded
- Normalizer v1 → 1. Structure: conformance
- Normalizer v1 → 5. Arguments: value matching

### One recovery conversation, opaque error (predicted, not observed) (dynamic)

The conversation from How it works, on `weather-forecast-lisbon`, baseline cell. The ordering is what `recovery.converse` and the mock service do in code; the model's replies are what H4 predicts, not something any model has done.

- **Harness**: recovery.converse
- **Model**: baseline cell
- **Mock service**: invalid_parameter, opaque

1. Harness -> Model: user message + 2 rendered tools (Lisbon, next three days)
2. Model -> Harness: get_forecast("Lisbon", days=3) [reply]
3. Harness -> Mock service: attempt 0
4. Mock service -> Harness: Error: invalid request. (opaque: names no parameter) [fault]
5. Note over Harness: injected = true; failing call key kept
6. Harness -> Model: tool result, is_error = true
7. Model -> Harness: get_forecast("Lisbon", days=3) [reply] [identical retry]
8. Harness -> Mock service: attempt 1
9. Mock service -> Harness: Error: invalid request. [fault]
10. Harness -> Model: tool result, is_error = true
11. Model -> Harness: text: could not retrieve the forecast [reply]
12. Note over Harness: recovered false; gave_up true (the text discloses failure)

## Core decisions

### Vary the presentation, hold the model fixed, cross the factors

**Problem:** Benchmarks vary the model and hold the prompt fixed. The question an engineer faces every time a tool is added is how to present the tools. The plausible finding is an interaction: rich descriptions matter little with three tools and a great deal with twenty look-alikes.

**Options considered:**

- Rank models on tool calling, as the leaderboards do
- Change one factor at a time
- A 2×2×2 factorial over tool count, description richness and schema strictness, one model carrying it

**Chosen:** A 2×2×2 factorial over tool count, description richness and schema strictness, one model carrying it

**Why:** Changing one factor at a time reports two bland main effects and misses the interaction, which is the plausible finding. Holding the model fixed answers a decision made on every new tool, not once. The amendment also found single factors already studied, and no published work that crosses the factors, uses plausible look-alikes or breaks effects down by failure category (moderate confidence).

**Cost:** Eight cells per scenario, and a second and third model only on the best and worst cells. H1 is a replication of Guo et al. under a stricter design, not a first. The novelty claim reaches only as far as that search did.

### Strictness is schema content; constrained decoding stays off

**Problem:** Read literally, the August strict arm would let a provider's strict mode do the work, making the malformed category nearly impossible by construction. That would test the API, not the model.

**Options considered:**

- A reading of the August strict arm that lets provider strict mode do the work (amendment §4a)
- Schema content in all eight cells, plus one exploratory slice with strict mode on

**Chosen:** Schema content in all eight cells, plus one exploratory slice with strict mode on

**Why:** The question is whether the model reads the schema, not whether the decoder enforces it. High strictness renders enums, patterns and a full required list; low strictness renders loose types. The slice answers the practitioner's question, "if I turn strict mode on, which failures are left?", and is labelled exploratory in those words.

**Cost:** The slice's schemas differ from the factorial's: OpenAI's strict mode rewrites optional parameters into unions with null. The provider guarantees come from documentation the amendment read, not re-checked here. "Strict" in this study never means a vendor flag.

### Grade by rule, against one canonical schema

**Problem:** A grader needs a fixed standard. An LLM judge superimposes its own variance on the model's, and grading against whatever schema was rendered would let the instrument create the failures it measures.

**Options considered:**

- An LLM judge
- Ordered rules, checking conformance against the schema the model was shown
- Ordered rules, checking every call against one canonical strict schema per tool

**Chosen:** Ordered rules, checking every call against one canonical strict schema per tool

**Why:** A judge's variance would contaminate the quantity under study, and a harness that answers differently twice is not something anyone builds on. Grading against the rendered schema would give the strict arm more ways to be `MALFORMED`, so strictness would look like it causes the failures it constrains. Structure is checked first, then value, so one wrong value is scored alike in every cell.

**Cost:** Only scenarios whose correct calls can be listed in advance qualify, so it measures structurally checkable calls, a subset of agent correctness. A loose cell can be marked wrong for a constraint it never showed, by design. The normalizer silently sets results, so its rules are versioned and a change is breaking. A "check first" call is graded `WRONG_TOOL`, because grading is single-turn.

### The scenario is the unit; scenarios and repetitions are sized together

**Problem:** Reruns of a scenario are correlated, so the count of calls overstates the information. The August design had scenarios shrink before repetitions and used Wilson intervals on proportions, both resting on rerun variance being the headline.

**Options considered:**

- About 20 scenarios with many repetitions, scenarios shrinking first, Wilson intervals on cell proportions (August)
- N from the pilot's ρ with a floor of 5, at least 24 scenarios, a bootstrap over scenarios, Wilson only within one scenario (amendment)

**Chosen:** N from the pilot's ρ with a floor of 5, at least 24 scenarios, a bootstrap over scenarios, Wilson only within one scenario (amendment)

**Why:** With near-deterministic reruns an extra repetition adds almost nothing to a cell rate's interval; the information is in the scenarios. A Wilson interval over all S·N calls treats them as independent, the error the clustering exists to prevent. If the budget binds, N drops to its floor before S drops.

**Cost:** Authoring time, not money, limits S. The 95% of the S/ρ limit used to size N is `TARGET_FRACTION` in `toolcall/budget.py`, not the amendment. With 10 pilot repetitions and the band, the realised ρ is at most about 0.61, so N is at least 13. The premise (near-deterministic reruns) is the Noise Floor Audit's, read by the amendment on abstracts and not checked here.

### Keep the recovery sub-design, with a floor rule and at least 20 scenarios

**Problem:** Whether an actionable error stops the model repeating a failing call is a clean mechanism-level prediction. But prior work reports that identical repeats are rare, so H4 may have nothing to measure, and the bootstrap needs enough scenarios to give a verdict.

**Options considered:**

- H4 unconditional, as the August design had it
- H4 with a pre-registered floor: if the opaque arm's identical-retry rate is under 5%, report it as not testable
- Eight recovery scenarios, the amendment's first plan

**Chosen:** H4 with a pre-registered floor: if the opaque arm's identical-retry rate is under 5%, report it as not testable; and at least 20 recovery scenarios

**Why:** The floor keeps a floor effect from reading as support or as refutation; Gumaan and Kraishan are the reason it exists. Eight scenarios could never yield a verdict, because the harness refuses a bootstrap over fewer than 20. Recovery scenarios are call scenarios with a recovery block added, so the extra authoring is small.

**Cost:** The estimate for recovery rose from about $5.43 to at most about $14. H4 may end as not testable. `hallucinated_success` is a regex proxy with known misses. A wrong first call can never recover under a transient error, so recovery is also reported given a correct first call.

### Pre-register in two dated steps, behind a spend guard

**Problem:** N depends on what the pilot measures, so not everything can be committed before the pilot. But every rule that does not depend on the pilot should be written down before it, and a paid run needs a hard rule.

**Options considered:**

- One step: everything committed before the pilot, as the August design said
- Two dated steps: rules before the pilot; the scenario count, repetitions, included list and approved spend after it and before any campaign call

**Chosen:** Two dated steps: rules before the pilot; the scenario count, repetitions, included list and approved spend after it and before any campaign call

**Why:** The pilot is itself a paid run and N depends on it; artifact 4 did the same. Post-hoc changes are numbered, dated amendments, never edits. The values are to be held as code, with a test that fails if the document and the code disagree (the record exists; the values file comes with step 1). The spend guard refuses to start without an approved amount that covers the estimate plus headroom, and reserves each call's worst case in a ledger before the call.

**Cost:** Step 1 is not yet committed: until it is, the hypotheses exist only in the approved amendment and are not frozen. Plan 1's review changed four statistical details before any registration was committed (amendment §14 items 8 to 11). The guard's per-call bound is conservative, so metered spend over-counts failures; billed against metered spend is reconciled before publication.

## Relationships

**Requirements and the decisions that meet them:**

- R1: Every scenario is rendered in all eight cells (tool count × description richness × schema strictness), and the renderings differ only in the factor being manipulated.
  - `factorial` Vary the presentation, hold the model fixed, cross the factors: Eight renderings of one scenario differ only in the manipulated factor.
  - `content` Strictness is schema content; constrained decoding stays off: Only the schema content differs between the strictness levels; decoding is the same in every cell.
- R2: Every response is graded by an ordered procedure into exactly one of six categories, against each tool's single canonical schema, with a versioned normalizer. No LLM judge.
  - `grader` Grade by rule, against one canonical schema: Rules and one canonical schema give the same answer twice and score a value alike in every cell.
- R3: Rates are averaged per scenario, intervals resample whole scenarios, and the number of repetitions is sized from the pilot's intra-scenario correlation.
  - `unit` The scenario is the unit; scenarios and repetitions are sized together: Rates average per scenario, intervals resample scenarios, and N comes from the measured ρ.
- R4: After an injected tool error, measure whether the model repeats the failing call unchanged, with the error message either actionable or opaque.
  - `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios: The conversation, the two message formats and the floor rule are the measurement.
- R5: Hypotheses, band, grading and floors are committed before the pilot; the scenario count, repetitions, included scenarios and approved spend before any campaign call. No paid call runs without a stated call count and cost.
  - `rules` Pre-register in two dated steps, behind a spend guard: Each step is committed before the data it governs, and the guard refuses a paid phase without a covering approval.
- R6: Every scenario, tool and schema is public (a BFCL seed) or authored in neutral domains; nothing derives from the author's employer. A scan of the data files fails the tests unless the author has signed off each hit.
  - No decision: A constraint on every decision, enforced by a data-file scan and the author's sign-offs (amendment §6), not the outcome of a choice among options.

**Decisions and the concepts they use:**

- `factorial` Vary the presentation, hold the model fixed, cross the factors uses The eight cells: The eight cells are this decision in table form.
- `factorial` Vary the presentation, hold the model fixed, cross the factors uses Main effects, interactions and the scale: The interaction between richness and count is the finding the design looks for.
- `content` Strictness is schema content; constrained decoding stays off uses Strictness is schema content, and every call is graded against one canonical schema: Strictness as content, with decoding off, is this decision.
- `content` Strictness is schema content; constrained decoding stays off uses The eight cells: Strictness is the third axis of the eight cells.
- `grader` Grade by rule, against one canonical schema uses Six categories, and the first rule that applies wins: The ordered rules are the taxonomy, each category a property of the emitted call.
- `grader` Grade by rule, against one canonical schema uses Strictness is schema content, and every call is graded against one canonical schema: The canonical schema is the standard.
- `unit` The scenario is the unit; scenarios and repetitions are sized together uses The unit of independent variation is the scenario: The effective-size argument is this decision.
- `unit` The scenario is the unit; scenarios and repetitions are sized together uses Cost per successful call, and the retry walk: The same argument applies to money: a retry walk over recorded reruns, not the independent formula.
- `unit` The scenario is the unit; scenarios and repetitions are sized together uses Known contradiction in the sources: the August learning guide against the amendment: This decision reverses what the August guide teaches in modules 4 and 5.
- `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios uses Recovery, and the identical retry: The mock service and the identical retry are this decision.
- `rules` Pre-register in two dated steps, behind a spend guard uses The baseline band, and what it selects: The selection rule is a step-1 value; its survival rate is what the pilot measures.

**Results and the decisions they support:**

- What the suite is made of (an instrument fact, not a result) → `grader` Grade by rule, against one canonical schema, `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios
- Factors, low and high → `factorial` Vary the presentation, hold the model fixed, cross the factors
- The grader on hand-labelled boundary cases (a control, not a result) → `grader` Grade by rule, against one canonical schema
- Hypotheses H1 to H5 as the approved amendment words them (not yet frozen; results pending) → `factorial` Vary the presentation, hold the model fixed, cross the factors, `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios, `rules` Pre-register in two dated steps, behind a spend guard
- Same 80 failures in 400 calls, two splits across scenarios (constructed, not data) → `unit` The scenario is the unit; scenarios and repetitions are sized together
- Repetitions stop paying → no decision: Worked arithmetic for D4.
- Retry walk, illustrative → no decision: Worked arithmetic for D4.

## Implementation flow

12 steps in 4 phases, 5 milestones.

Milestones: 1. August design: factorial, six categories, no LLM judge (2026-08-17 to 08-19 (−07:00)); 2. Amendment: re-check against prior art and the house process (2026-10-08 17:27 (−07:00)); 4. The grader, with hand-labelled cases (2026-10-09 16:12 (−07:00)); 6. Statistics: contrasts, bootstrap, cost, H1 to H5 (2026-10-09 (−07:00)); 8. Merge: the offline core on main (2026-10-10 14:27 (−07:00)).

### Phase 1 of 4: Design (2 steps)

1. **August design: factorial, six categories, no LLM judge** [MILESTONE]: The question set as the engineer's own variable, how tools are presented, with the model held fixed; five hypotheses; a learning guide (§9b) added two days later.
   - Output: an approved design spec with H1 to H5 and a §9b learning guide
   - When: 2026-08-17 to 08-19 (−07:00)
   - Decision: `factorial` Vary the presentation, hold the model fixed, cross the factors
   - Evidence: 33c16c1 (design spec); a5d1a49 (learning guide §9b added)
2. **Amendment: re-check against prior art and the house process** [MILESTONE]: Two of three headline claims had prior art, current Claude models refuse a temperature parameter, and strict modes make one category impossible by construction. Twelve decisions signed off in chat the same day; three plans written.
   - Output: an approved amendment that governs where it conflicts, and three plans
   - When: 2026-10-08 17:27 (−07:00)
   - Decision: `content` Strictness is schema content; constrained decoding stays off
   - Evidence: 7849925 (amendment approved); 01bfd12 (the three plans)

### Phase 2 of 4: Build offline (6 steps)

3. **Package, data model, eight renderings**: Tools, normalizer v1 and scenarios as validated plain data; a renderer tested to change only the manipulated factor; tests that the package imports no other artifact.
   - Output: toolcall/: tools, scenarios, normalizer v1, 8 renderings
   - When: 2026-10-09 (−07:00)
   - Decision: `content` Strictness is schema content; constrained decoding stays off
   - Evidence: 3b380c8 (package and boundary tests); 3f00794 (tools, normalizer, scenarios); d85826e (the eight cells)
4. **The grader, with hand-labelled cases** [MILESTONE]: The ordered procedure, canonical-schema conformance, and a hand-labelled case for every category and every precedence boundary. Review then fixed pathological arguments and provider error states.
   - Output: grader.py and 21 hand-labelled cases, all passing offline
   - When: 2026-10-09 16:12 (−07:00)
   - Decision: `grader` Grade by rule, against one canonical schema
   - Evidence: b77b366 (grader, hand-labelled cases); ce9b618 (provider errors are API_ERROR); 4844e16 (pathological arguments; rule R10)
5. **Spend guard, mock service, recovery loop, stub**: Pinned prices, a guard that reserves each call's worst case before the call, mock replies in two formats, call and recovery records, every paid phase behind one runner, and a stub model with planted effects so the analysis can be tested for recovering what was put in.
   - Output: recovery.converse, a spend ledger, a stub marked NOT DATA
   - When: 2026-10-09 (−07:00)
   - Decision: `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios
   - Evidence: 261f61d (prices, guard, mock tools, recovery); 7284b53 (records, campaign, stub); cc5c731 (one runner for every paid phase)
6. **Statistics: contrasts, bootstrap, cost, H1 to H5** [MILESTONE]: Wilson intervals, 2³ contrasts, a bootstrap over scenarios, Holm; cost per success from recorded order, the ICC and the rule for N; the five tests. Review changed four statistical details before anything was registered.
   - Output: effects, costs, budget, hypotheses; amendment §14 items 8 to 11
   - When: 2026-10-09 (−07:00)
   - Decision: `unit` The scenario is the unit; scenarios and repetitions are sized together
   - Evidence: 1193733 (Wilson, contrasts, bootstrap, Holm); a2f177a (cost per success, ICC, N rule); 7e1d95a (H1 to H5 and the analysis); dd49557 (amendment §14 items 8 to 11)
7. **The scenario suite and the BFCL seed**: Domain libraries and scenarios authored in batches, each reviewed by the author; 14 BFCL entries at a pinned commit under Apache 2.0; six recovery blocks added so H4 keeps 20 scenarios after the band.
   - Output: 49 candidates (35 authored, 14 BFCL); 38 with recovery, 31 persistent
   - When: 2026-10-09 to 10-10 (−07:00)
   - Decision: `recovery` Keep the recovery sub-design, with a floor rule and at least 20 scenarios
   - Evidence: 8f997f3 (BFCL provenance; §14 item 1 signed off); 0e8632d (first worked domains and data tests); 3816801 (six persistent recovery blocks)
8. **Merge: the offline core on main** [MILESTONE]: Plan 1 ran task by task with a spec review and a code-quality review each; the deviations log records every approved change. Plan 1 spends nothing. No campaign data and no spend record are committed.
   - Output: main holds toolcall/, the suite and the three plans; no results
   - When: 2026-10-10 14:27 (−07:00)
   - Evidence: 88d11a2 (merge of artifact-3-plan-1); 1151a9b (deviations log)

### Phase 3 of 4: Pilot (pending) (2 steps)

9. **Smoke check: one call per pinned model**: Confirm each pinned snapshot accepts the registered settings (temperature 0 with reasoning off, for the primary) and record what the provider actually answers. Needs the author's explicit yes with a call count and cost.
   - Output: not yet: a recorded real answer per provider
   - When: pending
10. **Pre-registration step 1, then the pilot**: Step 1 fixes H1 to H5 with their estimands, the band, the baseline cell, floors, models, seed and the floor rule. The pilot runs every candidate 10 times at the baseline cell, and 10 candidates in all eight cells 5 times. Pilot data is never campaign data.
   - Output: not yet: docs/experiment-a3.md step 1; a pilot store
   - When: pending
   - Decision: `rules` Pre-register in two dated steps, behind a spend guard

### Phase 4 of 4: Campaign (pending) (2 steps)

11. **Step 2, then the campaign**: Step 2 fixes the included scenarios, S, N, the measured cost per call and the approved spend before any campaign call. Then the factorial, recovery, the cross-model slices and the exploratory strict-mode slice, each behind a stated yes.
   - Output: not yet: the step-2 commit and the campaign stores
   - When: pending
12. **Analysis, figures and post**: One analysis file; four figures and the post's numbers generated from it; the post publishes after the posts of artifacts 2 and 4.
   - Output: not yet: analysis.json, four figures, the post
   - When: pending

## Results as meaning

### What the suite is made of (an instrument fact, not a result)

- Axis: Candidate scenarios per domain, split by the failure mode each was written to provoke (its `target_failure_mode`). Read from the committed data files.
- Read it as: Every failure mode is targeted, and `units` has no tool-choice or no-call scenario. 14 of the 49 start from BFCL entries, all from its simple Python category, so all six no-call scenarios are authored. 38 carry a recovery block, 31 of them with persistent error kinds.
- How it is computed: Counts of toolcall/data/scenarios/*.json by domain and target_failure_mode: 49 = 35 authored + 14 BFCL (BFCL-SOURCE.md); 38 recovery, 31 persistent (deviations log).
- calendar: MALFORMED 1, SPURIOUS 1, MISSING 1, WRONG_TOOL 2, WRONG_PARAMS 2 (scenarios)
- files: MALFORMED 2, SPURIOUS 1, MISSING 1, WRONG_TOOL 1, WRONG_PARAMS 1 (scenarios)
- library: MALFORMED 2, SPURIOUS 1, MISSING 1, WRONG_TOOL 2 (scenarios)
- retail_orders: MALFORMED 2, SPURIOUS 1, MISSING 1, WRONG_TOOL 2, WRONG_PARAMS 1 (scenarios)
- travel: MALFORMED 1, SPURIOUS 1, MISSING 1, WRONG_TOOL 1, WRONG_PARAMS 3 (scenarios)
- units: MISSING 4, WRONG_PARAMS 3 (scenarios)
- weather: MALFORMED 1, SPURIOUS 1, MISSING 2, WRONG_TOOL 3, WRONG_PARAMS 2 (scenarios)
- So: see decisions `grader`, `recovery`

### Factors, low and high

- Axis: What the model is shown at each level.
- Read it as: Richness and strictness overlap: rich text can state in words what a strict schema states in structure.

| factor | Low | High |
|---|---|---|
| Tool count | the scenario's own 2 to 4 tools [defined] | 20: those, look-alikes, filler [defined] (4 to 6 look-alikes; 4 or 5 in the current suite) |
| Richness | terse one-liners [defined] | rich: constraints and examples [defined] |
| Strictness | bare types; first required key only [defined] | enums, patterns, every required key [defined] (and additionalProperties: false) |

- So: see decision `factorial`

### The grader on hand-labelled boundary cases (a control, not a result)

- Axis: One row per hand-labelled case, mostly precedence boundaries; the first rule that applies wins.
- Read it as: Each boundary resolves as the ordered procedure says: structure beats value, a wrong tool beats wrong params, provider outcomes come first. It shows the instrument can place a response, not how often any model errs.
- How it is computed: tests/test_toolcall_grader.py: 21 labelled cases covering all six categories and two exclusions; `pytest -k toolcall` 2026-10-19: 1104 passed.

| hand-labelled cases | Response | Graded as | Why |
|---|---|---|---|
| Hallucinated tool (name not in context) | search_flights_v2 (not shown) [case] | MALFORMED [tested, passes] | a tool not shown is structural [case] |
| Required key missing (a call, one key omitted) | destination left out [case] | MALFORMED [tested, passes] | structure before value [case] |
| Wrong JSON type ("2" for an integer) | passengers: "2" [case] | MALFORMED [tested, passes] | R4: a number as a string [case] |
| Enum outside the set (a value error) | cabin: "first" [case] | WRONG_PARAMS [tested, passes] | value, not structure [case] |
| Pattern miss (a value error) | origin: "New York" [case] | WRONG_PARAMS [tested, passes] | value, not structure [case] |
| Call, none expected (a well-formed call) | search_flights on small talk [case] | SPURIOUS [tested, passes] | any valid call [case] |
| Right-looking args (a different, shown tool) | search_trains, same args [case] | WRONG_TOOL [tested, passes] | tool before params [case] |
| Call written in text (no call block) | search_flights(...) as text [case] | MISSING [tested, passes] | text is not a call [case] |
| Unknown key (not in the schema) | seat: "aisle" [case] | WRONG_PARAMS [tested, passes] | R7: key not in schema [case] |
| Unparseable args (JSON cut off) | {"origin": "JFK", [case] | MALFORMED [tested, passes] | must parse as an object [case] |
| Broken, none needed (small talk, bad JSON) | airport_info, arguments not JSON [case] | MALFORMED [tested, passes] | structure beats intent [case] |
| Look-alike, 20 tools (a shown confusable) | flight_prices, shown among 20 [case] | WRONG_TOOL [tested, passes] | shown, so a valid call [case] |

- Note: From the grader's tests, a synthetic flight suite, run offline: no model called. A control of the grader, not a statement about any model.
- So: see decision `grader`

### Hypotheses H1 to H5 as the approved amendment words them (not yet frozen; results pending)

- Axis: One row per hypothesis. Tone is what the prediction expects; no model has been run.
- Read it as: Each row is a bet with its losing condition written first; H4 may not be testable.
- How it is computed: Holm over the five at 0.05: thresholds 0.01, 0.0125, 0.0167, 0.025, 0.05 (0.05 / 5, / 4, / 3, / 2, / 1); over four if H4 is not testable.

| hypothesis | Predicted | Not supported if | Result |
|---|---|---|---|
| H1 richness × count (interaction on failure rate) | negative: rich helps more at 20 [prediction, fewer failures] (replication of Guo et al.; failure = share not CORRECT) | Holm does not reject it [wording] | pending [pending] |
| H2 strictness (MALFORMED+WRONG_PARAMS) | negative; WRONG_TOOL within ±δ₂ [prediction, fewer failures] (equivalence: 90% interval inside ±δ₂, proposed 2 pp) | either part fails [wording] | pending [pending] |
| H3 count → WRONG_TOOL (main effect, 3-part test) | positive, above the others [prediction, more failures] (larger than \|richness\| and \|strictness\| on WRONG_TOOL) | any of 3 one-sided p too big [wording] | pending [pending] |
| H4 error format (opaque − actionable) | positive: more identical retries [prediction, may be untestable] (persistent kinds, injected, paired in cells; floor: opaque under 5%) | Holm does not reject; or not testable [wording] | pending [pending] |
| H5 count vs reruns (\|count\| − \|A/A contrast\|) | positive, and count effect ≠ 0 [prediction] (A/A: odd against even repetitions of identical cells) | either part's p too big [wording] | pending [pending] |

- Note: Wording from amendment §2, tests from §4f and §14 item 8; H3's three-part magnitude test and the failure definition are in `toolcall/hypotheses.py`. Frozen only when pre-registration step 1 is committed; it is not. One-sided cluster-bootstrap p-values, 10,000 draws, Holm at 0.05.
- So: see decisions `factorial`, `recovery`, `rules`

### Same 80 failures in 400 calls, two splits across scenarios (constructed, not data)

- Axis: Constructed to show the arithmetic: 20 scenarios × 20 repetitions, 80 failures in both datasets. Spread: 0 to 7 failures per scenario. Concentrated: four scenarios fail every repetition and sixteen never fail. 95% intervals. Formula rows: the same cell at three correlations ρ.
- Read it as: The pooled rate is 20% in both and the Wilson interval on 400 calls is identical, because it sees only 80 and 400. Resampling scenarios leaves the spread dataset near ±4 points and widens the concentrated one to 5 to 40: its effective size is about 20 scenarios, not about 400 calls. The formula rows widen the same way: effective size 400, 32.3, 22.1.
- How it is computed: toolcall.effects: wilson(80, 400) = 0.164 to 0.242; cluster_bootstrap (10,000 draws, seed 1): 0.16 to 0.24 and 0.05 to 0.40. Formula rows are a normal approximation, not the bootstrap: 20% ± 1.96 × 0.0200 × √(1 + 19ρ).
- Wilson over all 400 calls (both datasets): 20 % of calls failing (interval 16.4 to 24.2)
- Scenario bootstrap: failures spread: 20 % of calls failing (interval 16 to 24)
- Scenario bootstrap: failures concentrated: 20 % of calls failing (interval 5 to 40)
- Formula, ρ = 0 (design effect 1): 20 % of calls failing (interval 16.1 to 23.9)
- Formula, ρ = 0.6 (design effect 12.4): 20 % of calls failing (interval 6.2 to 33.8)
- Formula, ρ = 0.9 (design effect 18.1): 20 % of calls failing (interval 3.3 to 36.7)
- So: see decision `unit`

### Repetitions stop paying

- Axis: N / (1 + (N − 1)ρ). Dots: the N the sizing rule picks. Floor 5 (amendment §4d); cap 20 is the N the cost table assumes, neither frozen.
- Read it as: Each curve flattens at its limit 1/ρ; at ρ = 0.9 the twentieth repetition adds almost nothing. The band caps the baseline ρ near 0.61; 0.9 is an extreme.
- Axes: x is repetitions per scenario, N; y is effective size per scenario
- ρ = 0.3, limit 3.33: 1: 1.0, 2: 1.54, 3: 1.88, 4: 2.11, 5: 2.27, 6: 2.4, 8: 2.58, 10: 2.7, 13: 2.83, 16: 2.91, 20: 2.99
- ρ = 0.6, limit 1.67: 1: 1.0, 2: 1.25, 3: 1.36, 4: 1.43, 5: 1.47, 6: 1.5, 8: 1.54, 10: 1.56, 13: 1.59, 16: 1.6, 20: 1.61
- ρ = 0.9, limit 1.11: 1: 1.0, 2: 1.05, 3: 1.07, 4: 1.08, 5: 1.09, 6: 1.09, 8: 1.1, 10: 1.1, 13: 1.1, 16: 1.1, 20: 1.1
- N the rule picks (points): 5: 1.09, 13: 1.59, 20: 2.99

### Retry walk, illustrative

- Axis: Assumed failure rate f = 0.3, up to three attempts; not a measurement.
- Read it as: In this extreme case, where 30% of scenarios always fail, the formula understates the right bar by 37.5%; that figure holds only here. If a failing scenario fails again, retries cost more than the formula says.
- How it is computed: Left: 1 + 0.3 + 0.09 = 1.39 calls per group, 97.3% of groups succeed, 1.39 / 0.973 = 1.43. Right: 0.7 × 1 + 0.3 × 3 = 1.6 calls, 70% succeed, 1.6 / 0.7 = 2.29.
- Independent failures, c / (1 − f): 1.43 calls per success
- 30% of scenarios always fail: 2.29 calls per success

## Interview card

**30-second pitch:** I'm testing whether the way you present tools to an LLM changes which failures you get, holding the model fixed: two to four tools or twenty with look-alikes, terse or rich descriptions, loose or strict schemas. A rule-based grader, not an LLM judge, puts every response into one of six categories, and the intervals resample scenarios rather than calls, because a scenario that confuses the model does so on every rerun. The harness, a 49-scenario suite and the grader's tests are built and merged; the predictions are in an approved design but not yet frozen in a pre-registration, and no campaign has run, so I can give you the design and the bets, not results.

**2-minute version:** Tool-calling benchmarks rank models with the prompt held fixed. I asked the question an engineer faces every time they add a tool: holding the model fixed, does how I present my tools change which failures I get? Each scenario is a plain data file: a user message, the two to four tools it needs, four to six look-alike tools written for it, and the exact calls that count as correct. A renderer produces eight versions: few tools or twenty, terse or rich descriptions, loose or strict schemas. It is a factorial because the plausible finding is an interaction: rich descriptions should matter more with twenty look-alikes than with three tools. The grader puts each response into one of six categories by ordered rules, always against one canonical strict schema, so a loose schema's cost shows up instead of being forgiven. Provider strict mode stays off in all eight cells, because constrained decoding would make malformed calls nearly impossible by construction and I would be testing the decoder. The statistics follow from one idea: reruns of a confusing scenario are correlated, so I average per scenario, bootstrap over scenarios, and size the repetitions from the pilot's correlation. I also convert everything to cost per successful call, walking the recorded reruns rather than using the textbook retry formula. What exists is the offline core, a 49-scenario suite, and tests against a stub; what does not is any model result. The five hypotheses are worded in an approved design and get frozen in a committed pre-registration before the pilot runs.

**Hard follow-ups:**

- Q: Tool-calling benchmarks already exist. What is new here?
  A: They vary the model and hold the prompt fixed; this holds the model fixed and varies the presentation. The literature has since covered single factors and rerun noise: the amendment names Guo et al. as the closest work to H1, so H1 is framed as a replication under a stricter design, and the Noise Floor Audit as the closest to H5, pointing the other way. What the search found no one publishing, at moderate confidence, is a balanced factorial with plausible look-alikes, broken down by failure category and converted to cost per successful call. I claim that only as far as that search went, and none of it has produced a result yet.
- Q: 400 calls in a cell: why is the interval not based on 400?
  A: Reruns of one scenario are correlated, so the effective size is S·N / (1 + (N − 1)ρ), between S and S·N. Take two constructed datasets with the same 80 failures in 400 calls. If the failures are spread over the scenarios the interval is near ±4 points; if four scenarios fail every time and sixteen never do, resampling scenarios gives 5 to 40, while a Wilson interval on 400 calls gives the same narrow answer for both. So I resample whole scenarios and use Wilson only within one scenario.
- Q: You grade a loose-schema call against a schema the model never saw. Isn't that unfair?
  A: It is the measurement: what a loose schema costs is exactly the constraints the model was not told. Grading against the rendered schema would give the strict arm more ways to fail, so strictness would look like it causes the failures it constrains, a confound the instrument would create. The README says so, and rich descriptions can state a constraint in words, which is part of the richness-by-strictness interaction.
- Q: Provider strict mode is on and the malformed rate is zero. What have you learned about the model?
  A: Almost nothing about its structural ability, because constrained decoding guarantees a conforming call except on a refusal, a truncation or enum capitalisation (the vendors' claim as the amendment read it, not re-checked here). What remains informative is the wrong tool, value-level wrong parameters, missing calls and spurious calls. That is why strict mode is off in the eight cells and run as one labelled exploratory slice.
- Q: The amendment expects near-deterministic reruns, yet your band wants scenarios with a 10 to 90% baseline pass rate. How can both hold?
  A: The sources do not resolve it; this is a reading, not a finding. A rate strictly between 0 and 1 over 10 reruns means those reruns disagreed, so the band selects for flipping. The amendment lists few survivors as a risk and answers it by authoring more candidates before step 2, and does not widen the band after the pilot. If reruns barely flip, authoring more may not help, and I would say so. The pilot's survival rate is the measurement, so this is pending. The deviations log notes one consequence already: the band caps the realised ρ near 0.61, so N is at least 13.
- Q: Why not cost a retry policy as c / (1 − f)?
  A: That formula assumes each retry is an independent draw. With near-deterministic reruns a scenario that fails tends to fail again, so it understates what retries cost; in an illustrative calculation with f = 0.3 and a cap of 3, 1.43 calls per success becomes 2.29 if the failing 30% of scenarios always fail. The study walks each scenario's recorded reruns in order. It is the scenario-as-unit argument expressed in money.

**Limits (what I must not claim):** No results exist: no hypothesis has an outcome and no cost per successful call has been measured. The hypotheses are worded in the approved amendment and are frozen only when pre-registration step 1 is committed; it has not been, and no pilot or campaign records are committed. When results exist they will hold for the pinned model snapshots on their run dates, each at the provider's most deterministic available setting (which may be the provider default, recorded as a deviation), for structurally checkable single-call scenarios in seven public or synthetic domains, one call per turn, and a suite chosen by a baseline band. A "check first" call is graded `WRONG_TOOL` because grading is single-turn; `hallucinated_success` is a regex proxy with known misses; the high-count filler is partly cross-domain. The prior-work table is cited from abstracts the amendment's author read and is not re-read here. The sources contradict each other in one place (the August learning guide against the amendment) and this page follows the amendment. A later revision of the pilot plan is uncommitted and is not used here.

## Recall questions

- Q: A model emits `get_current_weather` in a cell that shows only `get_forecast` and `get_air_quality`. Which category? And if the cell shows 20 tools including it?
  A: `MALFORMED`: a tool that was not shown is structural. In the 20-tool cell the same call is `WRONG_TOOL` (a confusable). The category depends on what was rendered, by design.
- Q: The user only says thanks, so no call is expected, and the model calls a shown tool with a required argument missing. Category?
  A: `MALFORMED`. Structure is checked before `SPURIOUS`, so the ordered rules decide it, not the intent.
- Q: Why is a loose-cell call graded against the strict schema?
  A: That is the measurement of what a loose schema costs. Grading against the rendered schema would give the strict arm more ways to fail and make strictness look harmful, a confound the instrument would create.
- Q: Which three outcomes are excluded before any rate is computed?
  A: `API_ERROR`, `REFUSED` and `TRUNCATED`. Each is counted per cell, and a cell where they together exceed 2% of its calls is flagged.
- Q: Why is provider strict mode off in all eight cells?
  A: It would make `MALFORMED` nearly impossible by construction and test the decoder, not the model. One labelled exploratory slice turns it on.
- Q: What is the effective sample size, and what does it approach?
  A: S·N / (1 + (N − 1)ρ), approaching S/ρ as N grows. At high ρ another repetition buys almost nothing, so the information is in the scenarios.
- Q: At ρ = 0.9 and 30 scenarios, what does going from 5 to 40 repetitions buy?
  A: Almost nothing: effective size rises from 32.6 to 33.2 (the amendment's example). Spend on scenarios, not reruns. The band caps the pilot's ρ near 0.61, so the rule for N lands at 13 or more.
- Q: Where are Wilson intervals used in this design?
  A: Only within one scenario, where the repetitions are the unit. Cell rates and effects use a bootstrap that resamples whole scenarios.
- Q: How is an interaction computed here, and what should you say about the convention?
  A: One factor's effect at the other's high level minus its effect at the low level, on the percentage-point scale. Say that it is the difference and not halved, and that the scale was fixed before the data.
- Q: Why does H4 count only the persistent error kinds?
  A: After a rejection an identical retry is a loop, but after a timeout it is the right move if the call is idempotent. Counting both would blur the pathology H4 tests.
- Q: What is H4's floor rule?
  A: If the opaque arm's identical-retry rate has a point estimate under 5%, H4 is reported as not testable at this rate. It counts neither as support nor as refutation, and Holm runs over the other four.
- Q: A conversation ends with the model stopping and saying it could not retrieve the forecast. How is it recorded?
  A: As `gave_up` (step 6 of How it works). A success-shaped message that discloses nothing would be `hallucinated_success`, by a regex proxy with known misses.
- Q: Which sources contradict each other here, and which do you follow?
  A: The August design's learning guide (modules 4 to 6) and definition of done teach 20 × 20 observations, Wilson intervals for proportions and temperature-0 variance as the headline. The 2026-10-08 amendment governs where they conflict, so scenarios and N are sized together, Wilson is within one scenario, and that H5 is withdrawn.

Sources: see the page

## Interview mode (paste this to an AI chat)

You are my interview coach. The brief above is the only ground truth about my project;
do not add facts it does not contain, and say "the brief does not say" when asked.

Settings (I may change these at any time):
- AUDIENCE: hiring manager | senior peer | skeptic
  (hiring manager: impact, ownership, trade-offs, what I would do differently;
   senior peer: technical depth on the decisions; skeptic: pushes on every hand-wave)
- DEPTH: pitch (30 s answer) | standard (2 to 5 minutes of follow-ups) | deep (three
  levels of "why")
- MODE: ask (you interview me) | quiz (recall questions, one at a time) | grade (I paste
  an answer, you grade it against the brief)

Default: AUDIENCE = hiring manager, DEPTH = standard, MODE = ask.

Rules:
1. One question at a time. Wait for my answer.
2. Do not reveal the brief's answers before I have answered.
3. After each answer, say what was solid, what was missing, and which stated limit I
   should have admitted. Keep it to five lines.
4. Never let me claim more than the brief supports. If I overstate, ask me to cut it
   back, and quote the limit.
5. I am a software engineer, not a researcher: reward clear reasoning about decisions
   and trade-offs over memorised numbers. A number is only useful to me as evidence for
   an answer.
6. Start now with my current settings and the first question.
