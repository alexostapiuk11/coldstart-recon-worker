# Practice: tool-calling failure modes: practice brief

## How to use this brief

Paste this whole file into an AI chat. The last section is the prompt that makes the chat quiz you; lines marked KEY and RED FLAG are the answers, hidden from you until you have tried. Practice for: Which tool-calling failures tool presentation moves. About 35 minutes.

## Objectives

- Put a response in one of the six categories by the grader's ordered rules, and say how the category changes with what was rendered.
- Compute design effect, effective size and a 95% half-width for given S, N and ρ, and say what one more repetition buys.
- Say in two sentences each why a failed H2 equivalence part is not an effect and why H5 is an intersection-union test.
- Work Holm's thresholds over five and over four tests, and the smallest p-value a bootstrap of B draws can give.
- Work main effects and a count × richness interaction by hand from eight cell rates, and say why the scale is fixed before the data.
- Design a test that separates "the model reads the schema" from "the decoder enforces it", and say what it cannot show.

## Check yourself first

### Check 1

Q: A cell has 400 calls from 20 scenarios and about 20% of them fail. Is its 95% interval about ±4 points, or far wider, and what decides which?
KEY: It depends on how failures cluster within scenarios (the correlation ρ between reruns). About ±4 points only if reruns are independent. The page's constructed example: the same 80 failures give 16% to 24% when spread and 5% to 40% when four scenarios fail every rerun.
If missed, review: The unit of independent variation is the scenario

### Check 2

Q: A service returns a 400 with a field error, and another call times out. Which do you retry unchanged, and what must be true first?
KEY: The timeout, if the call is idempotent; the field error will be rejected the same way every time. This unit's recovery measure counts only the persistent error kinds as an identical-retry loop.
If missed, review: Recovery, and the identical retry

### Check 3

Q: A contract test checks a consumer's request. Against which schema: the subset the docs showed, or the provider's real one?
KEY: The provider's real contract. This study grades every call against one canonical strict schema, however much of it the model was shown, so a loose schema is charged for constraints it never showed.
If missed, review: Strictness is schema content, and every call is graded against one canonical schema

## Estimation drills

### Estimate 1: What is a 20 × 20 cell worth at three correlations?

Problem: A cell has 20 scenarios × 20 repetitions = 400 calls and a pooled failure rate of 20%. Give the design effect, the effective size and the 95% half-width (normal approximation) at ρ = 0, 0.6 and 0.9. Then say how many repetitions the sizing rule picks at ρ = 0.6, with a floor of 5 and a cap of 20.

KEY steps:

1. Independent standard error: √(0.2 × 0.8 / 400) = 0.0200, so the independent half-width is 1.96 × 0.0200 = ±3.9 points.
2. Design effect 1 + (N − 1)ρ = 1 + 19ρ: 1 at ρ = 0, 12.4 at 0.6, 18.1 at 0.9.
3. Effective size 400 / design effect: 400, 32.3 and 22.1.
4. Half-width = 3.9 × √design effect: ±3.9, ±13.8 and ±16.7 points. The same 400 calls give an interval more than four times wider at ρ = 0.9.
5. Sizing rule: the smallest N reaching 95% of the limit S/ρ, so N ≥ 19(1 − ρ)/ρ = 19 × 0.4 / 0.6 = 12.67, rounded up to 13 (inside 5 to 20).

KEY answer: Design effect 1, 12.4, 18.1; effective size 400, 32.3, 22.1; half-width ±3.9, ±13.8, ±16.7 points; N = 13 at ρ = 0.6. Say it as: 400 calls are somewhere between 20 and 400 facts.

### Estimate 2: Contrasts and an interaction from eight illustrative rates

Problem: ILLUSTRATIVE rates, not data or predictions. Failure rate (%) by cell. Low count: terse-loose 30, terse-strict 20, rich-loose 26, rich-strict 16. High count: terse-loose 50, terse-strict 40, rich-loose 34, rich-strict 24. Find the three main effects and the count × richness interaction as the repo defines it, and check it with the code's weights.

KEY steps:

1. Main effect of count = mean(high) − mean(low) = 148 / 4 − 92 / 4 = 37 − 23 = +14 points.
2. Richness: mean(rich) − mean(terse) = 100 / 4 − 140 / 4 = 25 − 35 = −10 points. Strictness: strict 25, loose 35, so also −10.
3. Richness effect at low count = 21 − 25 = −4 points; at high count = 29 − 45 = −16 points.
4. Interaction = effect at high − effect at low = −16 − (−4) = −12 points (the difference, not halved).
5. Check with weights s_count × s_richness / 2 over the eight cells: [(30 + 20 + 34 + 24) − (26 + 16 + 50 + 40)] / 2 = (108 − 132) / 2 = −12.
6. Strictness × count: effect −10 at high count and −10 at low count, so the interaction is 0.
7. Scale: suppose terse 20% falls to rich 10% at low count and 40% to 20% at high count. Risk difference: −20 − (−10) = −10 points of interaction. Ratio: rich halves failures at both counts, so no interaction.

KEY answer: Main effects +14, −10, −10 points; count × richness −12 points (full difference, not halved); strictness × count 0. An interaction on the point scale can vanish on the ratio scale, so the scale is fixed before the data.

## Deep-dive drills

Ordered easy to hard.

### Drill 1 of 12

Q: The model is shown two tools and calls a third that exists in your library but was not shown. Category? And if the cell shows 20 tools including it?
KEY: `MALFORMED`: a tool that was not rendered is a structural failure, and structure is checked first. In the 20-tool cell the same call is `WRONG_TOOL`; the grader records which kind (confusable, filler or low-set tool). The category depends on what was rendered, by design.
RED FLAG: "`WRONG_TOOL`, it is a real tool." The grader asks what the model was shown, not what exists.

### Drill 2 of 12

Q: The user only says thanks, so no call is expected, and the model calls a shown tool with a required argument missing. Category?
KEY: `MALFORMED`. The structure check runs before the no-call check, so a broken call is `MALFORMED` whatever the intent. A well-formed call in the same scenario would be `SPURIOUS`. Order is part of the contract.
RED FLAG: "`SPURIOUS`, it should not have called." That reads intent; the grader applies ordered rules.

### Drill 3 of 12

Q: Why is a loose-schema call graded against the strict schema? Isn't that unfair to the loose arm?
KEY: It is the measurement: what a loose schema costs is exactly the constraints the model was not told. Grading against the rendered schema would give the strict arm more ways to fail, so strictness would look like it causes the failures it constrains, a confound the instrument would create. Rich text can state a constraint in words, which is part of the richness and strictness overlap.
RED FLAG: "We grade against what the model saw, to be fair."

### Drill 4 of 12

Q: Provider strict mode is on and `MALFORMED` is zero. What have you learned about the model's structural ability?
KEY: Very little: constrained decoding makes a conforming call nearly certain by construction, so a zero measures the decoder. The vendors' exceptions as the amendment read them (refusals, truncation, enum capitalisation) were not re-checked here. What stays informative is `WRONG_TOOL`, value-level `WRONG_PARAMS`, `MISSING` and `SPURIOUS`, which is why strict mode is off in the eight cells and run as one labelled exploratory slice.
RED FLAG: "The model is perfectly reliable at formatting."

### Drill 5 of 12

Q: A cell has 20 scenarios × 20 repetitions. Why is its interval not based on 400 observations, and what do you resample?
KEY: Reruns of a scenario are correlated, so the effective size is S·N / (1 + (N − 1)ρ), between S and S·N: at ρ = 0.6 about 32.3, not 400, and the half-width is about ±13.8 points against ±3.9 for independent calls (normal approximation, 20% failure rate). Resample whole scenarios, recomputing every cell rate from the drawn set; Wilson is for one scenario's repetitions only.
RED FLAG: "Wilson on 80 / 400." It sees only 80 and 400 and gives the same narrow answer for the spread and the concentrated dataset.

### Drill 6 of 12

Q: At ρ = 0.9 and S = 30, what does going from 5 to 40 repetitions buy? What does this design's pilot imply for N?
KEY: Almost nothing: effective size rises from 32.6 to 33.2 (amendment §4d), under 2%. The information is in the scenarios, so spend on S. Separately, the band keeps baseline rates between 0.10 and 0.90 over 10 reruns, which caps the realised ρ near 0.61, so the rule for N gives at least 13 (12.15 rounded up).
RED FLAG: "More repetitions always tighten the interval."

### Drill 7 of 12

Q: Holm at 0.05 over five hypotheses with add-one bootstrap p-values. What is the smallest p-value you can get, and why does the pre-registration refuse fewer than 100 draws?
KEY: With B draws the smallest p is 1/(B + 1). Holm's first threshold is 0.05 / 5 = 0.01, so B must be at least 99 for any hypothesis to be rejectable at all; at B = 10,000 the floor is about 0.0001. The thresholds are 0.01, 0.0125, 0.0167, 0.025 and 0.05; over four tests (H4 not testable) they are 0.0125, 0.0167, 0.025 and 0.05. The code's `MIN_ITERATIONS` is 100.
RED FLAG: "Any number of draws is fine, the correction is just a threshold."

### Drill 8 of 12

Q: H2's equivalence part fails. Has strictness been shown to move `WRONG_TOOL`?
KEY: No. Failing to show equivalence is inconclusive, not an effect: the code reports `failed_part = "equivalence"` when Holm rejects the difference part but the 90% interval is not inside ±δ₂ (proposed 2 points). As a rough bound (normal approximation, true effect zero) it passes only if the across-scenario SD of the strictness contrast is under about 6.0 points at S = 24, 6.7 at S = 30.
RED FLAG: "Strictness affects tool choice." Wide intervals are not an effect.

### Drill 9 of 12

Q: Why is H5 an intersection-union test, and what went wrong with the first version?
KEY: H5 compares |count effect| with |A/A contrast|. With near-deterministic reruns the A/A contrast is about zero, so the statistic reduces to |count effect| and the one-sided p-value collapses to about 1/(B + 1) whatever the data say: a simulated null count effect was "supported" 80% of the time (amendment §14 item 8). So H5 also needs a two-sided test that the count effect is not zero, and its p-value is the larger of the two.
RED FLAG: "The A/A contrast is a fine baseline on its own."

### Drill 10 of 12

Q: The amendment expects near-deterministic reruns, yet the band keeps scenarios with a 10% to 90% baseline pass rate. Reconcile them.
KEY: The sources do not reconcile them; this is a reading, not a finding. A rate strictly between 0 and 1 over 10 reruns means the reruns disagreed, so the band also selects for flipping. If reruns barely flip, few candidates may survive and authoring more may not help; the pilot's survival count measures which regime holds, so it is pending. A flip fraction measured on a band-selected set may also not be comparable with the Noise Floor Audit's; that is a reading, not something the sources state.
RED FLAG: "The band just picks medium-difficulty scenarios." It picks scenarios whose reruns disagree.

### Drill 11 of 12

Q: A teammate prices retries as c / (1 − f). In an illustrative case (f = 0.3, up to three attempts) the formula gives 1.43 calls per success. What is wrong with it?
KEY: It assumes each retry is an independent draw. If the 30% of scenarios that fail always fail, a group spends 0.7 × 1 + 0.3 × 3 = 1.6 calls, only 70% of groups succeed, and cost per success is 1.6 / 0.7 = 2.29: the formula understates it by 37.5%. The study walks each scenario's recorded reruns in order, which is the scenario-as-unit argument in money.
RED FLAG: "Retries are geometric, so 1 / (1 − f)."

### Drill 12 of 12

Q: Design a test that separates "the model reads the schema" from "the decoder enforces it", and one that separates "rich descriptions disambiguate" from "rich descriptions restate the enum".
KEY: First: a 2 × 2 of schema content (loose, strict) × constrained decoding (off, on) on the same scenarios. The repo runs strict content with decoding off (the eight cells) and one exploratory slice with decoding on; the other corners are not run, and loose content with decoding on may not be expressible where strict mode needs every property required (the amendment's reading of OpenAI, not re-checked). Second: a richness level whose rich text omits enum values and patterns; the deviations log notes units' rich text lists the enum, so there strictness adds nothing. Label it exploratory.
RED FLAG: "Just compare strict against loose." That mixes content and decoding.

## Design scenario

Prompt: A fictional travel marketplace exposes 60 tools to one booking agent: flight search, fare rules, seat maps, hotel search, itinerary changes, loyalty points and more. Wrong-tool calls and badly formatted dates are the top support complaints. Leadership asks: "Should we turn on provider strict mode and cut the agent to 20 tools?" Design how you would decide and how you would roll it out. Bring nothing from any employer.

KEY outline:

1. Turn the question into failure categories first: grade a sample of traces with a deterministic taxonomy. If most failures are `WRONG_TOOL`, constrained decoding will not fix them; disambiguation and fewer or better-separated tools might.
2. Offline factorial on held-out scenarios: tool count (60 against a routed 20) × schema content × constrained decoding on or off, with deliberate look-alikes (fare rules against fare search). Only calls whose correct form can be listed in advance.
3. The unit is the scenario: size repetitions from a pilot's ρ, average per scenario, bootstrap over scenarios, report per-category rates with intervals and the exclusion rate.
4. Cost per successful call with the real retry policy, walked from recorded reruns, and prompt caching measured rather than assumed. A wrong action (a cancelled booking) is not a retry.
5. Guardrails beyond the prompt: validate against the canonical schema at the boundary; idempotency keys on side-effecting tools so a retry after a timeout cannot act twice; actionable error text (the page predicts, but does not show, that it reduces identical retries).
6. Rollout: shadow-grade the new presentation on live traffic with no side effects, then canary with per-category alerts, pin model versions and re-run the suite on every change.

KEY pitfalls:

- Treating repetitions as independent and reporting a Wilson interval over all calls.
- Grading against the schema the model was shown, so the loose arm is forgiven.
- Turning strict mode on and calling a zero malformed rate a model improvement.
- Claiming results beyond structurally checkable single calls, or quoting a prediction as a finding.

## Lab

Cost: no cost
Goal: See offline that the category depends on the rendering, that the interval depends on how failures split across scenarios, and that correlated failures break the retry formula.
Note: Zero spend: no API key is in the environment and no step makes a model call. The dry run's shares are planted by a stub and say nothing about any model; do not copy them anywhere.

Setup:

- Work in a scratch directory outside the repo. Run every script as `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY PYTHONPATH=<repo> <repo>/.venv/bin/python -B lab.py`, so no key reaches the process.
- Never use `uv run` (it re-syncs the environment) and install nothing. Read `toolcall/README.md`, "How values are compared", first.

Steps:

1. Grade by hand, then by machine. Build the 12 responses of the boundary-cases table with `toolcall.responses.openai_call`, `openai_text` and `toolcall.providers.openai_parse` (`tests/test_toolcall_grader.py` has the calls). Write your predicted category first, then call `toolcall.grader.grade`.
2. Same call, two renderings. Load `toolcall/data/tools` and `toolcall/data/scenarios` (`load_library`, `load_scenarios`). For `weather-forecast-lisbon` grade `get_current_weather` with location Lisbon using `toolcall.formulation.tool_names(scenario, library, "low")`, then `"high"`.
3. Clustering. Build two datasets of 20 scenarios × 20 reruns with 80 failures each: spread (0 to 7 per scenario) and concentrated (4 scenarios fail 20 of 20, 16 fail 0). Call `toolcall.effects.wilson(80, 400)`, `cluster_bootstrap(rates, average, iterations=10000, seed=1)` and `toolcall.budget.icc`.
4. Sweep ρ. For ρ in 0.3, 0.5, 0.61, 0.7 and 0.9 print `toolcall.budget.reps_for(rho, 5, 20)` and `effective_n(30, n, rho)` for n = 5, 13 and 20.
5. Retry walk. In plain Python make 30 scenarios × 21 reruns at an assumed failure rate of 0.3, once independent and once with 9 scenarios that always fail. Cut each scenario into groups of three, spend until the first success, and divide spend by wins.
6. Dry run on the shipped suite (stub, NOT DATA): `scripts/a3_diagnose.py --tools toolcall/data/tools --scenarios toolcall/data/scenarios --dry-run --reps 3 --store <scratch>/dry.jsonl`. Only the fact that it loads, renders and grades matters.

Record:

- Predicted against graded category, for the 12 responses.
- The category of one call in the low and the high rendering.
- Wilson interval, bootstrap interval and ICC for each dataset.
- N the rule picks, and effective size, for each ρ.
- Calls per success and share of groups that succeed, independent and always-fail.

KEY expected result: 1: the table. 2: `MALFORMED` (not in context) in the low cell, `WRONG_TOOL` (confusable) in the high cell. 3: Wilson 0.164 to 0.242 for both; bootstrap about 0.16 to 0.24 spread, 0.05 to 0.40 concentrated; ICC about 0.004 against 1.0. 4: N = 20, 19, 13, 9, 5; effective size at ρ = 0.9 is 32.6 at N = 5, 33.1 at N = 20. 5: about 1.43 calls per success, 97% of groups succeeding, when independent (seed-dependent); 2.29 and 70% when 9 scenarios always fail. 6: 147 graded calls.
KEY what it shows: The category is a function of the rendering plus one canonical schema; the interval is a function of how failures cluster; retry economics follow the clustering. None of it needs a model call.

## Calculator

Design effect and the N rule What-ifs, not measurements: no ρ has been measured. Formulas: the page's effective-size concept (normal approximation for the half-width) and toolcall/budget.py (95% of the limit, floor 5, cap 20).

Inputs (default, range):

- Scenarios, S: 20 (range 2 to 60)
- Repetitions, N: 20 (range 1 to 40)
- Correlation ρ between reruns: 0.6 (range 0.05 to 1)
- Pooled failure rate: 0.2 (range 0.05 to 0.95)

Outputs at the defaults:

- Design effect = 12.4  [1 + (N - 1) * rho]
- Effective size = 32.3  [S * N / (1 + (N - 1) * rho)]
- 95% half-width = 13.8 points  [100 * 1.96 * sqrt(p * (1 - p) / (S * N)) * sqrt(1 + (N - 1) * rho)]
- N the sizing rule picks = 13  [max(5, min(20, ceil(0.95 * (1 - rho) / ((1 - 0.95) * rho))))]

## Recall cards

- [taxonomy] Order the six categories by grader precedence. -> KEY: `MALFORMED`, `SPURIOUS`, `MISSING`, `WRONG_TOOL`, `WRONG_PARAMS`, `CORRECT`. The first rule that applies wins.
- [taxonomy] Which three outcomes are excluded before any rate, and how are they reported? -> KEY: `API_ERROR`, `REFUSED` and `TRUNCATED`: counted per cell and never graded; a cell where they together exceed 2% of its calls is flagged.
- [taxonomy] No call at all where a call was expected. Category? -> KEY: `MISSING`, never `MALFORMED`. A call written as text is graded the same way (flagged, not a call).
- [taxonomy] What does each failure category point at? -> KEY: `MALFORMED`: schema strictness, output format. `SPURIOUS`: description scoping, when not to call. `MISSING`: discoverability, richer descriptions. `WRONG_TOOL`: disambiguation, fewer tools. `WRONG_PARAMS`: typing strictness, parameter naming (toolcall README).
- [taxonomy] Name the three kinds of `WRONG_TOOL` the grader records. -> KEY: confusable (a look-alike written for the scenario), filler (another tool in the 20), and low_set (one of the scenario's own tools that is not acceptable). The amendment names two.
- [canonical] "3" is sent for an integer parameter. Category and rule? -> KEY: `MALFORMED`, rule R4: a number sent as a string is a type error, so structural. 3.0 for an integer is accepted under R3 when it has no fractional part.
- [canonical] An enum value outside the set, or a pattern miss. Category? -> KEY: `WRONG_PARAMS`: value-level, not structural. A key the schema does not define is also `WRONG_PARAMS` (R7).
- [canonical] A null for an optional parameter, and a null for a required one? -> KEY: R5: null for an optional parameter equals omitting it; null for a required one counts as the parameter missing, so `MALFORMED`.
- [cells] What does the high-count cell contain? -> KEY: Exactly 20 tools: the scenario's own 2 to 4, its 4 to 6 look-alikes (4 or 5 in the current suite), and filler from its own domain first, then others.
- [cells] What does a loose schema keep in required? -> KEY: Only the tool's first required parameter; strict renders enums, patterns, every required parameter and additionalProperties: false.
- [cells] Why is provider strict mode off in all eight cells? -> KEY: It would make `MALFORMED` nearly impossible by construction and test the decoder, not the model. One labelled exploratory slice turns it on.
- [cluster] Effective sample size, and what it approaches. -> KEY: S·N / (1 + (N − 1)ρ), approaching S/ρ as N grows. Another repetition buys almost nothing at high ρ, so the information is in the scenarios.
- [cluster] The N rule. -> KEY: The smallest N reaching 95% of S/ρ: N ≥ 19(1 − ρ)/ρ, between a floor of 5 and a cap of 20 (toolcall/budget.py).
- [cluster] Wilson interval for 0 failures in 20 reruns of one scenario? -> KEY: 0% to 16.1% (toolcall.effects.wilson(0, 20)); the normal approximation would give a zero-width interval. Wilson is used only within one scenario.
- [contrasts] A main effect, in words. Is the interaction halved here? -> KEY: High-level rate minus low-level rate, averaged over the other two factors, in points. The interaction is the effect at the other factor's high level minus its effect at the low level: not halved. Say which convention you mean.
- [hypotheses] H4's floor rule. -> KEY: If the opaque arm's identical-retry rate is under 5%, report H4 as not testable at this rate. It counts neither as support nor refutation, and Holm runs over the other four.
- [hypotheses] Holm's thresholds over five tests, and the smallest bootstrap p. -> KEY: 0.01, 0.0125, 0.0167, 0.025, 0.05. With B draws the smallest p is 1/(B + 1), so B must be at least 99 to reject at 0.01.
- [recovery] Why does H4 count only persistent error kinds? -> KEY: After a rejection an identical retry is a loop; after a timeout it is the right move if the call is idempotent. Counting both would blur the pathology.
- [recovery] How does a conversation end when all attempts are used? -> KEY: As `budget_exhausted`: neither `gave_up` nor `hallucinated_success`. `identical_retry` is decided on the first action after the error only.
- [costsuccess] Why not c / (1 − f) for a retry policy? -> KEY: It assumes independent retries. If a failing scenario fails again it understates the cost; the study walks recorded reruns in order.
- [selection] Why can the pilot not report ρ near 0.9? -> KEY: The band keeps baseline rates between 0.10 and 0.90 over 10 reruns, which caps the intra-scenario correlation near 0.61.
- [pipeline] [draw] Draw the pipeline from a scenario file to the verdicts. Mark where calls multiply and where the bootstrap resamples. -> KEY: Scenario → renderer (8 bodies) → model, N reps per cell → provider-side exclusions → grader against the canonical schema → per-scenario rates → cell rates and 2³ contrasts → bootstrap over scenarios → H1 to H5 with Holm. Calls multiply before the grader; the bootstrap resamples whole scenarios.
- [recovery] [draw] Draw one recovery conversation with an opaque error and an identical retry, ending in a give-up. -> KEY: Harness sends the request; the model calls the tool; the mock rejects with an opaque error; the harness marks it injected and keeps the failing call key; the model repeats the call (identical retry); rejected again; the model answers in text that discloses failure: `gave_up`.
- [cluster] [draw] Draw two datasets with the same 80 failures in 400 calls that give very different intervals. -> KEY: Spread: 0 to 7 failures in each of 20 scenarios, interval about 16% to 24%. Concentrated: 4 scenarios fail every rerun, 16 never, interval about 5% to 40%. Wilson on 80 / 400 is the same for both.

## Review schedule

- Day 1: Cards 1 to 12 and drills 1 to 3 aloud. Draw the pipeline from memory. Prerequisite check.
- Day 3: Lab steps 1 to 4. Estimation 1 on paper. Cards 13 to 17. Explain drill 5 aloud in two minutes using the two datasets.
- Day 7: Draw the recovery sequence and the two datasets. Drills 4 and 6 to 8. Estimation 2 by hand, then lab step 5.
- Day 21: The 30-second pitch cold. Drills 9 to 12. Estimation 1 with fresh numbers. The design scenario in 15 minutes. Cards 18 to 24.
- After results: Redraw the pipeline with the real numbers on it, then re-read what the page said was predicted.

## Assumed numbers

Not from the study page's sources:

- S = 20, N = 20, ρ = 0.6, rate 0.2: The calculator's starting what-ifs: the page's constructed 20 × 20 cell with 20% failing, and a ρ near the band's cap. Not measurements.
- 30, 20, 26, 16, 50, 40, 34, 24 (%): ILLUSTRATIVE cell failure rates for estimation 2, invented to show the arithmetic. Not data and not predictions.
- 20 to 10 and 40 to 20 (%): ILLUSTRATIVE terse-to-rich failure rates at low and high count, for the scale example in estimation 2.
- f = 0.3, 9 of 30 scenarios always fail: The page's illustrative retry assumption, reused in the drill and lab step 5. Not a measurement.
- 1.645: The standard normal value for a 90% two-sided interval; used only for the rough H2 equivalence bound in drill 8.
- 12.67: worked out, 19 x (1 - 0.6) / 0.6 = 12.667, the N the sizing rule gives at rho = 0.6 before rounding up to 13.
- 0.0001: worked out, 1 / 10,001 = 0.0000999, the smallest add-one bootstrap p at B = 10,000 draws.
- 6.0: worked out, 0.02 x sqrt(24) / 1.645 = 0.0596: a normal-approximation bound on the strictness contrast's SD, in points, at S = 24.
- 6.7: worked out, 0.02 x sqrt(30) / 1.645 = 0.0666, the same bound at S = 30.
- 16.1: worked out, toolcall.effects.wilson(0, 20) upper end = 0.1611, run offline.
- 33.1: worked out, 30 x 20 / (1 + 19 x 0.9) = 600 / 18.1 = 33.15, effective size at N = 20, rho = 0.9, S = 30.
- 148: worked out, 50 + 40 + 34 + 24: the four illustrative high-count rates (estimation 2).
- 140: worked out, 30 + 20 + 50 + 40: the four illustrative terse-cell rates (estimation 2).
- 108: worked out, 30 + 20 + 34 + 24 (estimation 2, interaction check).
- 132: worked out, 26 + 16 + 50 + 40 (estimation 2, interaction check).
- 0.004: worked out, toolcall.budget.icc on the spread dataset (0 to 7 failures in each of 20 scenarios of 20 reruns), run offline: 0.004.

## Drill mode (paste this to an AI chat)

You are my drill coach for this practice set. The brief above is the only ground truth. Lines
marked KEY and RED FLAG are for you: never show them before I have answered.

Settings (I may change these at any time):
- SECTION: all (default) | check | estimation | drills | scenario | cards
- PACE: one question at a time

Rules:
1. Ask one question at a time, in the order of the brief unless I pick a section. Start with
   "Check yourself first", then the drills from easy to hard. Wait for my answer.
2. Grade against the KEY: say what I got, what I missed (quote the KEY point), and score me
   0 (miss), 1 (partial) or 2 (solid). Five lines at most.
3. If my answer falls into the RED FLAG, name it ("that is the red-flag answer: ...") and ask
   me to try again before moving on.
4. Do not add facts the brief lacks. If I ask beyond it, say "the brief does not say".
5. Estimation: let me show my steps before you reveal the KEY steps. Accept an answer within a
   factor of 2 if the steps are sound.
6. Scenario: let me talk it through; then check my answer against the KEY outline and pitfalls.
7. Cards: show only the front. For a [draw] card, ask me to describe my sketch in words, then
   compare it with the KEY.
8. Keep a list of everything I scored 0 or 1. Repeat those items later in the session, and at
   the end tell me which to re-test in each slot of "Review schedule".
9. At the end give a score table and the three items to re-test first.
10. Start now with the first question.
