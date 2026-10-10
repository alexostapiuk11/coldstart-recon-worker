# Artifact 3, plan 1: deviations log

Plan 1 (`2026-10-08-artifact-3-plan-1-offline-core.md`) was executed task by task with
subagents, from 2026-10-09 to 2026-10-10. Each task had a spec review and a code-quality
review, and each data batch had an adversarial review plus the author's confidentiality
review. Those reviews changed the plan's code in many places. This file is the running log of
every approved change, written as the work went.

How to read it:

- **Plan 1's code blocks are history.** Where this log and the plan disagree, the code on
  `main` and this log are right. Plan 1's text was not rewritten.
- **Lines starting "For plan 2", "For plan 3", "For Task N" or "For the post"** are
  obligations on later work. Plans 2 and 3 are revised against the real code at plan 2's
  kickoff, using these lines.
- **Author decisions** are marked as such and dated. The amendment's §14 records the ones that
  change the design.
- Commit hashes refer to the `artifact-3-plan-1` branch.

---

# Deviations from plan 1's text, approved in review (fold into the plan at the end)

- Task 1 (31f2b86): tests/test_toolcall_boundary.py — probe prints JSON read with json.loads (no eval); test_the_harness_never_loads_toolcall imports every harness module in a fresh subprocess instead of grepping for the word.
- Task 2 (plan text only): Step 2's expected error names `toolcall.scenarios`, not `toolcall.stub_suite` (tests/a3_examples.py imports scenarios first).
- Task 2 (4ef0310), code: one definition of a valid value (call_matches requires conformance + empty value_violations; new rule R9; R2 "never override R9"); strip_nulls keeps nulls on unknown keys; huge-int safety; recursive call_key; fullmatch names; ParamSpec checks required bool, enum strings unique after casefold, bad regex → ValueError; scenario literals/one_of/examples checked against canonical enum/pattern; one_of non-empty list; no key in both args and may_include; duplicate tool/confusable names refused; recovery validation (claim pattern compiles, recovery tools in low set, param exists, results are dicts, invalid_parameter injectable vs acceptable_calls[0]); +31 tests (43 → 74 in the three files).
- Open, non-blocking (from Task 2 re-review): injectability check looks at acceptable_calls[0] only; None literal on numeric param raises TypeError not ValueError; ECMA-vs-Python regex dialect unchecked.
- Task 3 (follow-up commit): high-count filler drawn per scenario with a seeded shuffle (domain first, then others) instead of alphabetical; new tests: only-the-manipulated-factor-differs over all scenarios and cells, under-20 error, dedupe, cross-process order stability.
- For Task 4 (from Task 3 review): openai_strict_parameters must add null to an optional param's enum when it makes the type nullable (OpenAI strict mode), with a test.
- For Task 19 authoring rules (from Task 3 review, narrowed): terse descriptions must not list a parameter's allowed enum values or its pattern. Rich descriptions may, by design (August §5: rich = constraints and examples), which makes "constraints in prose vs in schema" part of the richness x strictness interaction, stated in the post.
- Task 4 (837a25e): openai_strict_parameters appends null to nullable enums.
- Task 4 (review-fix commit): model_dump(exclude_none=True); finish "error" for unknown terminal states and missing usage; ModelSettings enforces §3 (OpenAI needs reasoning_effort; Anthropic needs thinking and no temperature); consecutive Anthropic tool results merged into one user message; more parser/builder tests.
- For Task 5: grader maps finish "error" to API_ERROR (with a test).
- For Task 6: recovery loop answers every call_id of a multi-call response (extra calls get a fixed "not executed: one call per turn" tool result); finish "error" excludes the conversation as API_ERROR.
- For plan 2 Task 2: smoke check does a real two-turn round trip per provider (call, tool result, second call), proving echoed raw output is accepted.
- Process incident: a reviewer's `git checkout <sha>` left HEAD detached; d10efeb was committed detached; fixed by fast-forwarding artifact-3-plan-1 to d10efeb. Reviewers now forbidden to move HEAD; implementers check the branch before committing.
- For Task 13: tests/test_toolcall_runner.py FakeSDK must use `model_dump=lambda **kw: resp` (Client.post now passes exclude_none=True).
- Task 5 (ce9b618): finish "error" → API_ERROR. Review-fix commit: parse_arguments catches ValueError/RecursionError; Grade.empty_response flag; word-boundary text-call heuristic; normalizer R10 (duplicate keys last-wins); precedence/R5/multi-call/round-trip tests.
- For the post (Task 5 review): a confusable called in a low cell is MALFORMED (not rendered), WRONG_TOOL in a high cell; say so. Empty answers in no-call scenarios count CORRECT but are flagged; report the count.
- Task 6 (1be9562): recovery answers every call; finish "error" excluded. Review-fix commit (real-money): SpendGuardError (fatal guard-internal failures); finite checks on approved/estimate; input bound + 500-token overhead, priced at max(input, cache_write); failed post charged bound x (1 + SDK_MAX_RETRIES=2) as unmetered; usage-less or unparseable response charged the bound; SDK clients built with max_retries=2 explicitly; recovery keeps request body on failure; injectability check covers all PERSISTENT_KINDS; tests/test_toolcall_guard.py.
- For Task 13 (runner): on --resume, seed each phase's SpendGuard with the metered cost already in that phase's store, so the approved amount caps the whole phase across resumes, not each invocation.
- For the post (Task 6 review): gave_up is the residual "stopped calling without recovering or claiming success" (includes asking the user); identical_retry's denominator is injected, non-excluded conversations of persistent kinds; hallucinated_success is a pattern-based proxy.
- Task 6 follow-up: an unparseable response in converse → API_ERROR exclusion (not a crash).
- For Task 7: tests/test_toolcall_campaign.py's check_estimate test must match the new message ("finite positive amount") instead of "no spend approved"; and single_turn's build() must catch a parse failure (anything but SpendCapReached) and record API_ERROR with the response kept, not crash the campaign. The spend-guard campaign test must still hold (guard stops before the cap) under the new bound×3 semantics.
- For Task 13: runner tests — the approval-refusal regex must match the new message; the SDK metering test's $5 approval is too small under bound×3+overhead for 660 calls (guard stops at 305): raise the approval (e.g. 20.0) and keep the assertion spent <= approved; model_dump lambda must accept **kw.
- For the spend record (plan 3): failed posts are charged bound×3 even if never billed, so the metered total is an upper bound on failures; billed-vs-metered reconciliation must gate publication.
- Task 7 (cf94339): check_estimate test message; single_turn unparseable → API_ERROR. Review-fix commit: recovery pin check + RecoveryRecord.returned_models; CallRecord.unmetered (usage/cost None when usage missing) and RecoveryRecord.unmetered_turns; SystematicFailure after 10 consecutive API_ERRORs; resume refuses a store with different model/settings/phase; CallRecord.request_sha256 of the bytes sent; stub strictness detection works under constrained decoding; re-grade-from-record test.
- Known limit (documented): a SpendCapReached mid-conversation discards that conversation's paid turns; resume redoes it.
- Task 7 follow-up (ca0fe21): request_sha256 over json.dumps(request, sort_keys=True), checkable from the stored record; stub blind-spot comment.
- Task 8 (review-fix commit): exact Wilson endpoints; validated estimand names; one missing-cell check across rate/flip/half/wilson helpers; duplicate (scenario, cell, block) records refused; p-value docstring; contrast/Holm/calibration tests.
- For plan 2 step-1 pre-registration rules (from Task 8 review): (a) exclusions (API_ERROR/REFUSED/TRUNCATED) — report per-cell counts beside every effect, and pre-register a sensitivity analysis counting exclusions as failures; (b) pre-register a minimum graded count per (scenario, cell), e.g. ≥ 2, and what happens below it (scenario dropped from that hypothesis, disclosed); (c) report the ever-flip fraction only over units with ≥ 2 graded repetitions; (d) H5: an empty even/odd half → that scenario is dropped from H5, disclosed.
- Task 9 (plan text only): Step 2's expected error names toolcall.budget (the test imports budget first). Follow-up b203f11: costs._units refuses a graded record with cost None.
- Task 9 (review-fix commit): paid REFUSED/TRUNCATED calls counted in spend with zero wins (excluded_by_category, excluded_usd per cell); costs reuse effects' duplicate/missing-cell guards; retry_cap validated vs repetitions, calls_used_retry reported; p-values dropped from cost entries; geometric == single documented; break_even gets a paired cluster-bootstrap cost_difference_retry with verdict pays/does not pay/undetermined, required rate clamped with achievable flag; icc raises when every group has size 1, all-identical documented as rho 1.
- For plan 2 prereg doc: record TARGET_FRACTION 0.95 as a pre-registered constant of the N rule, and that with ~24-30 pilot scenarios the cap usually binds at low rho.
- For Task 11 (analysis): pick the analysable scenario set once (every cell has >= the pre-registered minimum graded reps), disclose dropped ones, and pass it explicitly to effects (rate_rows' scenarios=) and to cost_per_success (add a scenarios= keyword) — today a fully excluded scenario is silently dropped by effects but raises in costs.
- Task 10 (9909ab1): Preregistration.min_graded_per_cell = 2. Review-fix commit: strict validation (bool-free ints, int seeds, finite approved_usd, ModelSettings types, constrained False, non-empty distinct slice models, models priced, tuple band/included, iterations >= 100, alpha in (0, 0.5], step-2 reps <= n_cap, step 2 all-or-none); selection prices slice and recovery at the dearest cell, checks the guard bound on every pilot call including recovery turns, refuses unknown/duplicate pilot records, shows excluded counts, applies min_graded_per_cell; rho's selection bias documented (conservative).
- For plan 2 prereg doc: state that rho is estimated on the selecting repetitions (biased low, so N is conservative).
- For Task 13 (cont.): test_step_two_is_computed_from_the_pilot must look for the new budget total label ('**total, plan 3' or just '**total') instead of the literal '**total**'.
- For plan 2/3 text (Task 10 re-review): with 10 pilot reps and band selection, realised rho <= ~0.61, so N >= 13; don't describe N as 5-10. Budget at N = 13-20.
- Task 11 (2ea1dc0): analysable scenario set by min_graded_per_cell (dropped_scenarios disclosed), passed to every effects/costs/hypotheses/slice/recovery computation; cost_per_success(scenarios=); H5 drops empty-half scenarios (h5_dropped_scenarios) and zips one list, testable False below the bootstrap floor; ever-flip over units with >= 2 graded reps (units_with_two_or_more); exploratory sensitivity_exclusions_as_failures; per-cell empty_response and unmetered counts; shared bootstrap_params. Next commit: min_graded_per_cell default 3 and >= retry_cap; analysable_below_s_floor flag.
- Task 12 (d96a2e5). Review-fix commit 53fccbe:
  - _err clamps errorbar arms, so a point outside its percentile interval cannot crash;
  - identical_retry requires the persistent-kind interval (no fallback to the all-kinds rate) and labels each bar's N, with "H4 pairs N scenarios" in the title;
  - explicit grid_axis; dense flakiness categories; ±0.03 offsets on the interaction plot;
  - interval % from alpha; H1 shown in pp;
  - "up to N repetitions";
  - autouse plt.close in tests; +13 tests.
- For Task 15 (render script): close each figure after saving (the FIGURES functions return live figures).
- For the post (Task 12 review):
  - the flakiness title's "most deterministic setting" is fixed wording; justify it from the settings or reword;
  - the H4 figure's bars are per-format persistent rates, while the floor gate uses H4's paired opaque_rate, so the two can differ slightly.
- Task 13 (dispatch): the approval check compares estimate + guard headroom (largest call's worst bound) against the approval, because the guard refuses a call whose bound×3 could cross the cap; one SpendGuard per phase, shared by its jobs (no `remaining or job_est`); resume seeds the guard with the phase's stored spend.
- Task 13: cc5c731 (runner with follow-ups 1-9), 2916e1e (review fixes), e49d784.
  - Spend safety:
    - SpendLedger root/<phase>.spend.jsonl: reserve worst case before every post, settle after; unsettled = worst case; torn tail repaired; dir fsynced on create.
    - resume seed = max(ledger, stored_spend_usd).
    - Approval must cover estimate + guard headroom; the recovery headroom comes from a synthetic final-turn body.
  - Store discipline:
    - a non-empty store/ledger without resume is refused;
    - the STUB marker keeps stub rehearsals and paid roots apart;
    - all job stores are preflighted.
  - Recovery planning: calls planned at TURN_BUDGET+1 attempts, priced with history; prereg.turn_budget must equal recovery.TURN_BUDGET.
  - Estimate and API: estimate adds INPUT_OVERHEAD_TOKENS; `sdks` is a dict keyed by provider (plan 2/3 scripts must pass sdks=, not sdk=).
- For plan 2/3 scripts: stub rehearsal and paid runs need different roots (STUB marker refuses otherwise); paid scripts pass --resume explicitly to continue a phase; the ledger file is part of the spend record (billed-vs-metered gate reads it).
- Task 14 (8d0f574): plan files verbatim; a3_diagnose paid path uses runner.plan_cost (estimate + headroom), a SpendLedger and reuse refusal; +4 script tests. Review fixes: the confidentiality scan reads keys and identifiers and pins each sign-off to a sha256; numbers, diagnose and the BFCL importer were hardened (42a9946, 8192c37).
- For Task 16: toolcall/data/confidentiality_signoff.json uses the new sign-off format (sha256 of the file bytes + reviewed hits + ISO date + note); the plan's literal JSON must be regenerated with the hash helper.
- Task 15 commits:
  - defda9f: scripts with main(argv); stub demo refuses a non-empty --out.
  - 9642e70: analyse emits recovery_reps/slice_reps; identical-retry title states repetitions; flakiness bars show n=.
  - d057a17:
    - stub analysis carries NOT_DATA; numbers_block refuses it; renderer refuses it without --allow-stub;
    - REQUIRED_PATHS pre-check;
    - savefig metadata Software=None, byte-identity tested;
    - flakiness ylim 1.1, ticks capped at 1.0;
    - demo validates before mkdir;
    - stub announce "stub: no spend".
- For plan 3: --allow-stub renders carry no on-image NOT DATA mark, so the published-figures step must render only from a non-stub analysis (renderer refusal covers this) and never copy from build/a3-stub*.
- Task 14 follow-up 8192c37: sign-off helper prints root-relative keys (--root, default toolcall/data); policy ?numbers?; replace_block refuses multi-marker blocks; a3_diagnose model allowlist from PRICES.
- Task 16 (0e8632d): plan data verbatim; added the terse-rule test. Review fixes (C1 claim-shape pattern, C2 injection must not depend on richness, I1 no-call message gives its referent, I4 rich text names no tool, M1 afternoon time, data tests a-f).
- FOR THE AUTHOR at Task 19 (decisions):
  - I3: the high-count filler is partly cross-domain (calendar 10/20 same-domain, weather 12/20), unless domains grow toward 20 tools. Decide: grow domains, or state it in the prereg. Also seed the filler on a stable list so adding tools doesn't reshuffle high sets (the suite freezes at prereg anyway).
  - I2: Lisbon's WRONG_TOOL lure in the terse cells is thin. Consider a phrasing where daily and hourly both fit, and check it in the pilot.
  - Authoring rules to add:
    - a SPURIOUS scenario's tempting call must be fully specifiable from the message;
    - the success_claim_pattern matches claim shape, not scripted values;
    - the recovery expected value appears in no description;
    - rich descriptions refer to other tools by function, not by name.
  - Post notes:
    - list_events as a legitimate "check first" step is graded WRONG_TOOL (single-turn grading);
    - units.rich lists the enum, so strictness adds nothing for units in rich cells (M5);
    - Anthropic regex support for the time pattern is unverified.
- Task 16 fixes, in commits 6ff4c1a, 4bca6ba and the claim-pattern commit:
  - recovery values appear in no description in the library;
  - claim-shape pattern requiring "I have" before the verb, with the residual misses documented in the test;
  - the no-call referent, tool-name-free rich text, 14:15, attendees [];
  - data tests a-f.
- For plan 2 pilot/prereg (Task 16 re-review):
  - record the injection rate per recovery cell (RecoveryRecord.injected) and pre-register a floor, rather than assuming injection is cell-independent. The rich location text says "add the country when ambiguous", which may lead cautious models to the expected value;
  - hallucinated_success is a regex proxy with known misses (listed in tests/test_toolcall_data.py); the post says so.
- Task 19, weather batch review:
  - For plan 2/3 analysis: report recovery rates also conditioned on first_grade == CORRECT, as a sensitivity. With a transient error kind (timeout, malformed_payload), a WRONG_PARAMS first call can never recover, which depresses `recovered` in the cells where the trap fires (e.g. bfcl-simple_python_186).
  - For the post: 188's MISSING cell is expected to be nearly empty (a weak label kept by the author's choice, pending); 185's hourly tool is wrong only by a range stated in the rich text.
- Author decisions, weather batch (2026-10-09): keep 188 as MISSING, with the post saying its MISSING cell is expected to be nearly empty, and add a strong authored MISSING scenario later (weather climate-normals, e.g. "how much rain does Lisbon usually get in November?"); keep 186's timeout recovery and report recovery rates also conditioned on a correct first call (plan 2/3 analysis).
- 35bef1f: recovery.claims_success — hallucinated_success requires a claim-shaped final message that does NOT disclose failure or uncertainty (DISCLOSES_FAILURE); a disclosed failure is a give-up. The data-test leak check now reads list values. For the post/prereg: define hallucinated_success this way; the filter is blunt (a real claim containing "error"/"none" counts as give-up).
- Author decision 2026-10-10: BFCL seeds keep BFCL's original parameters (names, types, required, defaults, ground-truth values); no manufactured enums or required-ness. Travel 36/85/86 reverted accordingly.
- a3f600b: DISCLOSES_FAILURE broadened (rejected/refused/invalid/timed out/unavailable; any verb after can't/couldn't/unable to, minus idioms; first-person hedges incl. 'I think', 'I believe', estimate/guess count as disclosure by design). Post: a fabrication wrapped in 'I think' reads as a give-up.
- 0ff21f2: flat 'estimated' claims count as claims; 'haven't got <access>' discloses; analysis _recovery adds recovered_given_correct_first and n_correct_first (exploratory sensitivity). Plan 2 prereg: name it as the sensitivity for recovery.
- 3fa06a1: contradicting_result is not injected when the first call already meets the recovery requirement (mirrors invalid_parameter), removing an identical-retry false recovery (188, portland, files-share-photos); DISCLOSES_FAILURE adds haven't/hasn't + -ed/been and don't/doesn't know.
- Author decisions 2026-10-10 (units batch): rename calendar convert_time -> convert_clock_time so BFCL 378's message stays verbatim (touches approved calendar-singapore-nine's visible tool name); neutral wording for the daily-rate currency tool. 365 drops its timeout recovery (convert_mass enum path could never recover in loose cells).
- Task 20 (2026-10-10): 3916 passed, ruff clean, PARITY OK, no shared diff. NOTE: amendment §14 item 3 says openai/anthropic are added to pyproject.toml, but plan 1 did not add them (SDKs load lazily in Client.post). Plan 2's smoke task must add them (a shared-file change needing the author's yes) or document installing them separately.
