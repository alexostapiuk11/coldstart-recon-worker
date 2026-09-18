# Harness Extraction — Capability Inventory and Decision Log

Built by reading `coldstart/`. Every capability below carries an explicit
decision. A capability in neither column is a planning bug.

**Verified 2026-09-17 against `HEAD`, not against `artifact-1-published`.** The
plan's inventory was written 2026-09-03 and is correct for the code as it stood
at the tag. `coldstart/` has grown since — a whole `explainer/` subpackage and
one new statistics function — and none of it appeared in that table. Those
additions are in their own section below, with decisions. The diff that found
them:

```bash
git grep -h "^def \|^class \|^[A-Z_][A-Z_0-9]* *[:=]" artifact-1-published -- 'coldstart/*.py' 'coldstart/analysis/*.py'
# compared against the same over HEAD
```

## Moved to harness verbatim — behavior unchanged

| Capability | From | To |
|---|---|---|
| `median` (bootstrap-floor-exempt), `percentiles`, `ecdf` | `analysis/stats.py` | `harness/stats.py` |
| `bootstrap_median_diff`, `bootstrap_contrast_difference` | `analysis/stats.py` | `harness/stats.py` |
| `bootstrap_paired_median_diff`, `bootstrap_paired_contrast_difference` | `analysis/stats.py` | `harness/stats.py` |
| **`bootstrap_median_ci`** — see "Added since the plan" | `analysis/stats.py` | `harness/stats.py` |
| `within_host_triples` (paired units within a host) | `analysis/stats.py` | `harness/stats.py` |
| `MIN_SAMPLES`, `MIN_BOOTSTRAP_SAMPLES` sample floors | `analysis/stats.py` | `harness/stats.py` |
| `_quantile`/`_median` percentile convention | `analysis/stats.py` | `harness/stats.py` |
| `parse_engine_log`, `ParsedLog`, phase patterns, merged-phase reporting | `vllm_logs.py` | `harness/vllm_logs.py` |
| `StageRecorder`: `start`/`mark`/`now`/`at`/`duration`/`bundle`, duplicate-mark refusal, wall-clock-never-used-for-arithmetic rule | `recorder.py` | `harness/recorder.py` |
| `FailureClass` (9 members), `_Needle` regex-vs-substring matching, `_SIGNATURES` priority order, `classify_failure` first-match-wins | `checks.py` | `harness/failures.py` |
| `SubmitOutcome` (incl. `diagnostics` for failed-but-reporting runs), `StubSubmitter` | `submitter.py` | `harness/submit.py` |
| `extract_lifecycle`, `residual_splittable`, `extract_worker_id`, `TERMINAL_STATES`, `FIELD_MAP`, `WORKER_ID_FIELD` | `runpod_api.py` | `harness/runpod/api.py` |
| `HttpTransport` (409/5xx retry), `RunPodSubmitter`, `_UnhealthyRun` | `runpod_submitter.py` | `harness/runpod/submitter.py` |
| `fetch_endpoint` (deliberately unretried), `PreflightError`, `REST` | `preflight.py` | `harness/runpod/preflight.py` |
| `partition`, `PartitionResult`, `NotPublishableError`, `_missing_required` (`consistent is True` check), `_exclusion_labels` (closed-category reasons) | `analysis/pipeline.py` | `harness/publish.py` |
| `annotate_first_touch` (first-run-on-host marking, ordered by `run_index`) | `analysis/pipeline.py` | `harness/publish.py` |
| `PHONE_WIDTH_PX`, `MIN_PHONE_TEXT_PX`, `phone_pt` | `analysis/figures.py` | `harness/figure_guards.py` |
| `_validate_rows` (empty-input refusal), `_required_field` (missing/None → `NotPublishableError`), `_row_identity` | `analysis/figures.py` | `harness/figure_guards.py` |
| append-only `JsonlStore.append`, truncated-line diagnostic in `read_all` | `store.py` | `harness/store.py` |
| interleaved-randomized-within-block schedule, seeded RNG order | `scheduler.py` | `harness/scheduler.py` |

## Moved with a deliberate signature change — sign-off required

| Capability | Change | Why |
|---|---|---|
| `JsonlStore(path)` | → `JsonlStore(path, record_cls)` | The store hardcoded `RunRecord`. A second artifact stores a different record shape through the same file discipline. `record_cls` needs only `to_dict()` / `from_dict()`. |
| `build_schedule(arms, triples, seed)` → `ScheduledRun(run_index, triple_index, arm)` | → `build_schedule(conditions, blocks, seed)` → `ScheduledRun(run_index, block_index, condition)` | "Arm" and "triple" are artifact 1's vocabulary. **RNG consumption order is unchanged, so an identical seed yields an identical schedule.** `coldstart/driver.py` maps back, so the stored JSONL is byte-identical. |
| `failure_rate_by_arm(rows)` / `discard_table(rows)` | → `failure_rate_by_group(rows, key)` / `discard_table(rows, key)`, **no default** | Grouping was hardcoded to `row["arm"]`. A default would let artifact 2 group by a column it does not have and silently emit a one-bucket table; requiring the key fails closed. |
| `assert_endpoint_matches(endpoint, pinned=None)` defaulting to module-level `PINNED` | → `assert_endpoint_matches(endpoint, pinned)`, required | `PINNED` is artifact 1's endpoint, not a harness fact. It moves to `coldstart/pins.py`. **This deletes the line an explainer sentinel quotes — see below.** |

**Sign-off:** these four are caller-observable. Confirm before Task 8 begins.

## Stays in coldstart — artifact 1 specific, deliberately not generalized

| Capability | Why it does not move |
|---|---|
| `RunRecord` (clock A/B/C, warmup, arm, engine, host, config, status) | The shape of one cold start. |
| `SCHEMA_VERSION` | Versions artifact 1's record, not the harness. |
| `compute_residual`, `check_consistency`, `_validate_clock_inputs`, `DEFAULT_RTT_FLOOR`, `ConsistencyResult` | Reconciles clock A against clock B for artifact 1's stage taxonomy. |
| `DiscardReason` (5 members, incl. `ARM_STATE_*`) | Outputs of artifact 1's own checks. `harness/publish.py` reads `.value` off whatever enum a row carries. |
| `metrics.derive`, `rows_for_arm`, `ceiling_bound`, `t_fast_seconds`, `_arm_state_mismatch`, every `S4`/`T_fast`/`T_weights` derivation | The cold-start decomposition itself. |
| `economics.py` (foregone tokens, cost per scale-up, break-even) | Artifact 1's business framing. |
| `figures.py` waterfall / warmup / ECDF / per-host, `S4_SUBPHASE_KEYS`, `ARMS`, `ARM_LABEL`, `_by_arm`, `_median_present`, colors | Artifact 1's four charts. |
| `REQUIRED_FOR_*` presets | Name artifact 1's fields. Move to `coldstart/analysis/presets.py`. |
| `cache_config.py` (`CACHE_CONFIGS`, `resolve`, volume/cold roots) | Encodes arms A/B/C's cold/warm directories. |
| `driver.py` (`run_campaign`, `_record_from`, resume drift guard) | Assembles a `RunRecord`. |
| `stubs/` (`StubEndpoint`, `VirtualClock`, `stub_engine`) | Replays artifact 1's captured engine logs. |
| `worker/` (`handler.py`, `probe.py`, `recon_handler.py`) | The artifact 1 measurement worker. |

## Added since the plan was written — decisions made 2026-09-17

Twenty public symbols entered `coldstart/` between `artifact-1-published` and
`HEAD`, none of them in the plan's table. Nothing was removed.

| Capability | File | Decision |
|---|---|---|
| `bootstrap_median_ci` | `analysis/stats.py` | **Moves to `harness/stats.py`.** Generic: an interval on one sample's median, using the same `_quantile`, the same `_percentile_interval` endpoints and the same `MIN_BOOTSTRAP_SAMPLES` floor as every other interval in the module. It is also the function `autoscale/stats.py` re-implements, so the extraction is what lets that duplicate collapse into an import. |
| `explainer/excerpts.py` — `OPEN`, `CLOSE`, `SENTINELS`, `extract` | `coldstart/explainer/` | **Stays, flagged.** The sentinel-extraction machinery is generic; the `SENTINELS` map is artifact-1 paths. Splitting it is the same shape as `preflight.py`'s split, but nothing except the explainer needs it — the plan's YAGNI line is that a name is generalized only when leaving it would make another artifact do the wrong thing. Revisit when a second artifact wants code excerpts. |
| `explainer/jargon.py` — `TERMS`, `undefined_terms`, `_normalize`, `_TYPOGRAPHIC` | `coldstart/explainer/` | **Stays, flagged.** Same reasoning: the "every listed term is defined on the page" check is generic, its term list is not. |
| `explainer/numbers.py` — `KEYS`, `resolve`, `arm_a_ci_n99`, `first_touch_seconds`, `gpu_hours_a_n99`, `hosts_observed`, `_COMPUTED`, `_rows`, `_dig` | `coldstart/explainer/` | **Stays.** Artifact-1 specific by construction — it resolves the explainer's key list against artifact 1's committed campaign data. |
| `resample_frames`, `_correlated_example`, `_draw_interval`, `shortcut_panels`, `kv_dividend` | `analysis/figures.py` | **Stays.** Explainer teaching charts built on artifact 1's data, alongside the four published figures. |

**These decisions are proposals, not sign-off.** `coldstart/explainer/` is another
workstream's active code; its author should confirm before Task 4 moves
anything underneath it.

## The coupling the plan does not know about

`coldstart/explainer/excerpts.py` extracts live code from artifact 1's source by
sentinel comment, against a hardcoded path map:

| slug | file | does the extraction move it? |
|---|---|---|
| `preflight-refuses` | `coldstart/preflight.py` | **YES — and worse than a move** |
| `cache-config-env` | `coldstart/cache_config.py` | no, stays |
| `probe-markers` | `worker/probe.py` | no, stays |
| `handler-snapshot-before` | `worker/handler.py` | no, stays |
| `checks-rtt-floor` | `coldstart/checks.py` | no — it wraps `check_consistency`, which stays; only the failure taxonomy leaves this file |
| `stub-endpoint` | `coldstart/stubs/stub_endpoint.py` | no, stays |

Its docstring anticipates the extraction — *"the harness-extraction plan is about
to rewrite import paths under every one of them. Sentinels make that failure
loud"* — and it is right that a moved file raises `LookupError` rather than
silently emptying the excerpt. But one case is not a path rewrite.

**`preflight-refuses` quotes lines the refactor deletes.** The sentinel wraps:

```python
pinned = PINNED if pinned is None else pinned
if not pinned:
    raise ValueError("pinned configuration is empty; refusing to check nothing")
```

The signature change above makes `pinned` required, so the first of those lines
ceases to exist and the `PINNED` it references moves to `coldstart/pins.py`. The
excerpt's *subject* — "a guard handed nothing to check refuses rather than
passing" — survives in the `if not pinned: raise`, but the code around it does
not. Task 12 must re-place this sentinel and update `SENTINELS` to the new path
in the same commit, and the explainer's build check is what proves it.

## Intentionally dropped

Nothing. This is a move, not a rewrite: every capability above is either
relocated or retained in place.
