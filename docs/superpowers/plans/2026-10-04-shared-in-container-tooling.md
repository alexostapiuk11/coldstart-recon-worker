# Shared In-Container Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, with no GPU and no spend, the shared tooling artifacts 2, 4 and 5 run inside the worker image: a `vllm serve` lifecycle (`harness/serve.py`), a `vllm bench serve` wrapper (`harness/bench.py`), an nvidia-smi utilisation sampler (`harness/gpu_util.py`), the campaign loop lifted out of artifact 1 (`harness/campaign.py`), payload submission (`submit_payload`), and the single-engine service-curve sweep from schedule to artifact 2's `ServiceCurve`. Then move artifact 1's driver onto the lifted loop.

**Architecture:** Everything shared lives in `harness/`, imports neither `coldstart` nor `autoscale`, and a fresh-interpreter test proves it. The sweep is split by machine: `harness/service_sweep.py` is the local side (interleaved schedule, job payload, `SweepRun` record, reduction to plain tuples), `harness/sweep_worker.py` is one run inside the container (prompt path, warm-up, measured bench run, compact summary), and `worker/sweep_handler.py` is the RunPod glue around `harness.serve`. `scripts/run_service_sweep.py` drives a sweep through `harness.campaign.run_campaign` and `RunPodSubmitter.submit_payload` and owns the sweep's pin set; `scripts/a2_service_curve.py` turns the tuples into artifact 2's `ServiceCurve`. No pixels change, so the UI rules do not apply. The plan replaces existing code (the campaign loop in `coldstart/driver.py`, `RunPodSubmitter.submit`), so it carries an inventory, a keep/drop log, a baseline, and deletes the old loop last, gated on byte parity.

**Tech Stack:** Python 3.13, pytest, ruff 0.16, `requests`, the stdlib `subprocess`/`threading`/`http.server` (for the fake engine). No new dependencies. vLLM is not installed locally: every engine and bench call is faked.

---

## Why this plan exists, and what it deliberately leaves out

Artifacts 2, 4 and 5 all need to start an engine, put concurrent load on it, and record what it did. Scope decision 4 (`docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md` §1d) made that one shared plan rather than three copies. The interfaces were agreed with artifact 4's and artifact 5's sessions on 2026-09-26 and are coded against already: `served(model, *, args, env, port=8000, health_timeout=900.0)` and `run_bench(base_url, *, model, lora_modules, lora_assignment, max_concurrency, num_prompts, dataset_args, ignore_eos, seed, result_dir)`. Artifact 5's plan 2 refuses to start unless those parameter names exist (its Prerequisites block). This plan builds them to that contract, adds the service-curve sweep, and adopts artifact 5's campaign-loop lift and `submit_payload` verbatim, as the owner decided on 2026-10-04.

**Non-goals.**

- **The paid run.** Task 15 writes the checklist. Running it rents a GPU, and that is the owner's decision, not a plan step.
- **Artifact 4's swap handler and two-engine harness, artifact 5's instance runner.** They call `served` and `run_bench`; they are their own plans.
- **Exact-timestamp trace replay through `vllm bench serve`.** Unverified, and artifact 2's plan 2b's concern.
- **Choosing artifact 2's concurrency levels.** The sweep takes them as an argument. Which levels to buy is the owner's call at paid-run time (Task 15's checklist names the inputs).
- **Editing `worker/probe.py`.** It stays frozen; `served` lifts its lifecycle and leaves it alone.

## Owner decisions this plan implements (2026-10-04, binding)

1. **Adopt artifact 5's lift.** Plan 1 Task 3 (`harness/campaign.py`, lines 321–613 of `docs/superpowers/plans/2026-09-26-artifact-5-plan-1-gpu-free-core.md`) and Task 4 (`submit_payload`, lines 614–761) are copied here verbatim, code and tests. `coldstart/driver.run_campaign` becomes a thin wrapper, gated on parity. Tasks 2, 3 and 14.
2. **Three repeats per level, interleaved across levels.** Per run, the median end-to-end request latency; per level, the median of the three run medians with min–max as the interval. Tasks 9 and 11.
3. **GPU utilisation from nvidia-smi.** `utilization.gpu` every 0.5 s on a background thread during each bench run; per run, the median as a fraction; raw samples kept. Task 7.
4. **Artifact 1's exact prompt** through bench's custom dataset; a GPU-free test pins the flags and the dataset file; the first paid run verifies the engine received it; if bench cannot send it, fall back to the random dataset at the same token length and record which path was used. Tasks 8 and 15.

## Rules this plan operates under

- **Several workstreams share this checkout.** Never `git add -A` or `git add .`; every commit step names its files. Never run `ruff --fix` over the whole repository; run it on the files the task touched. `git status` will show other sessions' untracked plans and specs: leave them alone.
- **`PYTHONDONTWRITEBYTECODE=1`** on every pytest and script invocation. `.pyc` invalidation keys on mtime-seconds plus size, and a stale cache can make moved code look like it still works.
- **Test counts are relative.** The suite grows under other workstreams. "Passes" means pytest exits 0. A count that *drops* between two runs means a test file stopped being collected: stop and investigate. Counts quoted for a single new test file are that file's own tests.
- **Every error message names what went wrong and the consequence of it passing silently. Every docstring says why, and names the alternative it rejected.** This repository's house style; reviewers hold new code to it.
- **ruff gotchas in this repository's configuration.** `pyproject.toml` sets no `select`, and ruff 0.16.3's default set here is broad (list it with `.venv/bin/python -m ruff check --show-settings harness/store.py`):
  - **PLC0414** is on, so the `import X as X` re-export idiom fails; re-export with a named `noqa: F401` instead.
  - **RUF100** flags any `noqa` that suppresses nothing, including a `noqa` for a rule that is not enabled (`E402`, `PT012`, `E501` are all off). Add a `noqa` only after ruff has reported the rule.
  - **TRY004** fires on `raise ValueError` directly under a bare `isinstance` check; it does not fire under a compound condition (`if isinstance(x, bool) or x < 1:`). So `# noqa: TRY004` is needed in the first shape and is an RUF100 error in the second. Run ruff and add it only if reported.
  - **RUF007** wants `itertools.pairwise` instead of `zip(xs, xs[1:])`.
  - Also live: **PYI034** (`__enter__` should return `typing.Self`), **PLR0402** (`import a.b as b` → `from a import b`), **SIM117** (nested `with` → one `with`), **BLE001** (a blind `except Exception` needs a `noqa: BLE001` with a reason), **PLW1510** (`subprocess.run` needs an explicit `check=`).
- **Never edit** `docs/experiment.md`, `docs/experiment-a2.md`, another session's specs or plans (the scope, the amendment, artifact 4's and 5's plans), or the published `data/` and `docs/figures/`. Contradictions found in those files go in this plan's open items, not into them.
- **`worker/probe.py` stays frozen.** It is artifact 1's measured path, excerpted by the explainer (`coldstart/explainer/excerpts.py`) and reproducible at the `artifact-1-published` tag.
- **`harness/` never imports `coldstart` or `autoscale`.** `tests/test_harness_boundary.py` checks the first statically; Task 13 adds a static check for the second and fresh-interpreter `sys.modules` checks for both.

## Cross-plan coupling

- **Artifact 5 plan 1** (untracked, another session's). Its Task 3's ownership rule: *if `harness/campaign.py` already exists, run Step 1's test against it; if it passes, skip; if it fails, reconcile.* This plan creates the file verbatim, so artifact 5's six tests pass against it and its Task 3 becomes a no-op. Its Task 4 likewise. Tell artifact 5's session when Tasks 2 and 3 land.
- **Artifact 5's `multilora/serving.py`** calls `served(model, args=args, env=env)` and reads `.healthy`, `.log_lines`, `.base_url`; it calls `run_bench` with all nine keywords and reads `duration`, `completed`, `failed`, `ttfts`, `output_lens`, `errors` from the result. Tasks 5 and 6 test those exact shapes; Task 6 verified those six keys exist in vLLM 0.27.1's saved JSON.
- **Artifact 4** uses `.stop() -> float` to time teardown inside the context and `port` per call to run two engines. Task 5 defines what the float measures (see its docstring) and refuses a port that already answers.
- **Artifact 2** consumes the curve through `scripts/a2_service_curve.py` (Task 12). `autoscale/service.py` is not modified.

## Verified against vLLM 0.27.1, and what is not

Read from the tag's source on 2026-10-04 (`git` tag `v0.27.1` of `vllm-project/vllm`):

| Fact the code relies on | Where verified |
|---|---|
| `vllm bench serve` flags: `--base-url`, `--model`, `--max-concurrency`, `--num-warmups` (default 0), `--ready-check-timeout-sec` (default 0), `--save-result`, `--save-detailed`, `--result-dir`, `--result-filename`, `--ignore-eos`, `--lora-modules` (nargs `+`), `--lora-assignment` (`random`/`round-robin`), `--percentile-metrics` (accepts `ttft,tpot,itl,e2el`), `--disable-tqdm` | [`vllm/benchmarks/serve.py` `add_cli_args`](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/serve.py) |
| `--seed`, `--num-prompts`, `--dataset-name` (incl. `custom`, `random`), `--dataset-path`, `--skip-chat-template`, `--custom-output-len`, `--random-input-len`, `--random-output-len`, `--random-range-ratio`, `--random-prefix-len` | [`vllm/benchmarks/datasets/datasets.py` `add_dataset_parser`, `add_random_dataset_base_args`](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/datasets/datasets.py) |
| The custom dataset reads a JSONL `prompt` column through **pandas** (a `PlaceholderModule` if pandas is absent), applies the chat template unless `--skip-chat-template`, and oversamples a short file to `--num-prompts` with fresh request ids | same file, `CustomDataset`, `BenchmarkDataset.maybe_oversample_requests` |
| Saved JSON keys: `duration`, `completed`, `failed`, `total_input_tokens`, `total_output_tokens`, `request_throughput`, `output_throughput`, `num_prompts`, `max_concurrency`, plus `median_<m>_ms`/`p99_<m>_ms` for each selected percentile metric; with `--save-detailed`, per request: `input_lens`, `output_lens`, `ttfts`, `itls`, `start_times`, `generated_texts`, `errors`. Without `--save-detailed` those seven are deleted before saving | `serve.py` `benchmark` (result dict) and `main_async` (`if not args.save_detailed`) |
| No per-request end-to-end latency is saved. For the completions endpoint the tool's own `latency` is the last chunk's time minus the start time, i.e. exactly `ttft + sum(itl)`; `input_lens` holds the **engine's** `usage.prompt_tokens`, overwriting the client's count | [`vllm/benchmarks/lib/endpoint_request_func.py` `async_request_openai_completions`](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/lib/endpoint_request_func.py) |
| The bench client loads its tokenizer with `get_tokenizer(model_id)` and no revision | `serve.py` `main_async` |
| `max_num_seqs` defaults to 256 in the API-server context on GPUs under 70 GiB (an RTX 4090), and the default is logged only at DEBUG: `Defaulting max_num_seqs to %d for %s usage context.` Explicit engine args are logged at INFO in the `non-default args:` line (format confirmed in `fixtures/vllm_logs/startup_0.log` line 7) | [`vllm/engine/arg_utils.py`](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/engine/arg_utils.py) `get_batch_defaults`, `_set_default_max_num_seqs_and_batched_tokens_args` |
| `/tokenize` takes `{"model", "prompt"}`, returns `count` and `tokens`, `add_special_tokens` defaults to True (as for a completion) | [`vllm/entrypoints/serve/tokenize/protocol.py`](https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/entrypoints/serve/tokenize/protocol.py) |
| `AsyncEngineArgs.enable_log_requests` exists (CLI `--enable-log-requests` by the field-to-flag convention) | `arg_utils.py` |

**UNVERIFIED — each is checked on the first paid run by Task 15's checklist, mostly through the `--diagnostics` jobs Task 10 builds:**

1. Whether the pinned image has **pandas** (the custom dataset needs it). If not, the exact-prompt probe fails and every run takes the recorded random fallback.
2. That `vllm bench serve --help` in the pinned image lists every flag `harness/bench.py` and `harness/sweep_worker.py` pass (the source says yes; the image is what runs).
3. That the image's saved JSON carries the keys listed above (read one `raw_bench`).
4. That the reconstructed latency agrees with the tool's `median_e2el_ms` (recorded per run as `bench_median_e2el_s`).
5. Whether the bench client can load the tokenizer inside the container (it resolves `Qwen/Qwen3-8B` with no revision, so it may reach the Hugging Face hub).
6. Artifact 1's prompt's token count, and whether it reaches a 16-token KV block (if it does, prefix caching serves part of every exact-prompt request from cache, and the exact and fallback paths are different workloads).
7. Whether `--enable-log-requests` makes the engine log the prompt text at INFO (`diagnostics.prompt_in_log`). If not, the engine-side evidence is `input_lens` equal to `/tokenize`'s count.
8. That the `non-default args:` line carries `'max_num_seqs': 256` when `--max-num-seqs 256` is passed.
9. What nvidia-smi prints for `--query-gpu=utilization.gpu --format=csv,noheader,nounits --id=0` in the container.
10. Whether vLLM's child processes exit on the parent's SIGTERM (handled regardless: `served` signals the process group).
11. That RunPod's REST `GET /endpoints/{id}` returns an `executionTimeoutMs` key (the sweep pins it; `--preflight-only` shows it for free).
12. RunPod's maximum job-output size (ordinary jobs return a few KB; a diagnostic job returns the raw bench JSON, tens of KB).
13. RunPod's per-second price for an RTX 4090 serverless worker on the day (for the cost estimate).

## Design decisions this plan makes that the digest did not settle

| Decision | Choice | Why |
|---|---|---|
| Job granularity under the 1800 s execution timeout | **One RunPod job per (level, repeat)** | Startup p95 86 s cold-compile, 55 s warm (artifact 1, `data/analysis.json`); a measured run is ~20 waves × latency(level), 6–42 s on the placeholder curve; a job is ~3 minutes, a 10× margin. Per level would put a level's three repeats back to back on one engine (decision 2 forbids) and hide engine-to-engine variation in the interval. |
| Latency statistic | Per request `ttft + sum(itls)` over successful requests under amendment §3f's failure rule (non-empty error, TTFT 0.0, or output 0), cross-checked against the tool's `completed`/`failed`; per run the median | The saved JSON has no per-request e2e latency; the reconstruction equals the tool's own `latency` by construction; artifact 5 applies the same rule, so the two artifacts' latencies mean the same thing. The tool's `median_e2el_ms` is requested with `--percentile-metrics` and stored only as a cross-check. |
| Throughput | Sum of successful `output_lens` / tool `duration` (output tokens per second) | Amendment §3f's definition; equals the tool's `output_throughput`. |
| Sweep module split | `harness/service_sweep.py` (local) + `harness/sweep_worker.py` (in-container) | The two halves run on different machines and change for different reasons; each file stays focused. |
| `run_bench` extras | Keyword `extra_args=()`, `timeout=None`, `run=subprocess.run`; also pins `--disable-tqdm` and `--result-filename bench.json`; refuses any flag it owns in `dataset_args`/`extra_args`; refuses a `result_dir` already holding `bench.json`; `lora_assignment` defaults to `None` (no flag) | Subset-checked signatures allow extra keywords; argparse keeps the last of two values silently; a stale file would be read as this run's result. |
| `served` extras | `executable`, `term_grace`, `health_ok`, `clock`, `sleep` keywords for tests; `Server.cmd`, `.returncode`, `.drain_completed`; refuses a port that already answers; an unhealthy engine is stopped *before* it is yielded | Tests need the seams; artifact 4 runs two engines and a shared port would make the health check lie; stopping first makes `.log_lines` complete. |
| `.stop()` float | Seconds from the call until the `vllm serve` parent exits (SIGTERM to the group, `term_grace`, SIGKILL); excludes GPU memory release and the drain join; repeated calls return the first value | Artifact 4 times memory release itself; folding a poll in would hard-code one artifact's definition of "torn down". |
| Prompt path | Decided per job by a one-request probe; "exact" only if the engine's `input_lens == [/tokenize count]`; fallback at the `/tokenize` length; the reducer refuses a store mixing paths | Each job is a fresh engine; the local machine cannot run the image's tool; a mixed curve is two measurements. |
| Warm-up | One wave (`warmup_prompts = level`) at the run's concurrency, discarded, on a different seed | First-wave effects are small but not zero; a different seed keeps random-fallback warm-up prompts out of the prefix cache. |
| Requests per run | `max(100, 20 × level)` | Bounds each run at ~20 × latency(level) seconds whatever the level; ≥100 requests feed every median. |
| Output length | 16 tokens with `--ignore-eos` | Artifact 1's `max_tokens`; the placeholder curve's throughput column assumes 16; ignoring EOS makes every request exactly 16 tokens. |
| `healthy` semantics | The sweep handler returns `healthy: True` whenever the engine answered `/health`; a failed measurement is `run: None` + `run_error`, stored as a failed run | `RunPodSubmitter` treats a falsy `healthy` as "health check timed out", which would mislabel a bench failure. |
| Reducer refusals | No ok run; duplicate (level, repeat); mixed prompt paths; mixed serve commands; mixed GPU-utilisation methods (windowed, whole-call, or unrecorded); a missing utilisation; fewer than `min_repeats` (default 3) ok runs at a level; a requested level absent; under two levels | Each is a condition under which the output would not be one replica's curve. `--min-repeats` lets the operator accept two, on the record. |
| `SweepRun` record | Lives in `harness/service_sweep.py` | It is the sweep's, not an artifact's; artifacts 2 and 4 store the same shape. |
| Pin set | In `scripts/run_service_sweep.py`: GPU type, network volume, `executionTimeoutMs`, and a `templateId` passed on the command line; FlashBoot and `workersMin` deliberately unpinned | The template is provisioned when the paid run is prepared; the worker budgets against 1800 s; the sweep measures nothing about startup. |
| `max_num_seqs` | Parsed in the worker from `non-default args:` (INFO) or the DEBUG default line; the artifact-2 run passes `--serve-args "--max-num-seqs 256"` so the INFO line records it; `scripts/a2_service_curve.py` refuses a curve without exactly one value | DEBUG logging could perturb the timing being measured; 256 is the verified default on this card, so the pin changes nothing but makes the value observed. **Accepted 2026-10-04** (owner delegated the call to the controller). |
| Stub vs measured | The curve JSON records `source` ("runpod"/"stub"); the a2 adapter sets `measured` from it | A stub curve must never reach a figure labelled measured. |
| In-container verification | `--diagnostics` jobs return `vllm bench serve --help`, nvidia-smi's raw output, whether pandas imports, whether the prompt was logged, and the raw bench JSON | There is no shell on a serverless worker; this is how the UNVERIFIED items get checked without a pod. |
| Shared test fakes | `tests/sweep_fakes.py`, a non-test module imported by name | Three test files need the same fake engine; `tests/conftest.py` is avoided because artifact 5's plan creates one. |
| Migration placement | Task 14, after everything else; the old loop is kept as `_legacy_run_campaign` for one step, compared byte-for-byte, then deleted as the task's last step | Deletion last, gated on parity, per this repository's replacement rules. |
| Drift-guard wording | Adopt `harness.campaign`'s messages ("has condition 'C' ... assigns it 'A'") rather than re-raising artifact 1's "has arm" text | No test asserts the old wording; `tests/test_driver.py` asserts `run_index 0`, `'C'`, `'A'` and `beyond`, all still present; wrapping would duplicate the guard's text. Operator-visible: **accepted 2026-10-04** (owner delegated the call to the controller). |

---

## File Structure

| File | Responsibility |
|---|---|
| `harness/campaign.py` | **Create (Task 2), verbatim from artifact 5 plan 1 Task 3.** Schedule → submit → record → store, never retried, resume drift guard. |
| `harness/runpod/submitter.py` | **Modify (Task 3), verbatim from artifact 5 plan 1 Task 4.** `submit_payload(payload)`; `submit(arm, run_id)` delegates to it. |
| `harness/submit.py` | **Modify (Task 4).** `UNHEALTHY_ERROR` and `PayloadStubSubmitter`, the GPU-free twin of `submit_payload`. |
| `harness/serve.py` | **Create (Task 5).** `served(...)`, `Server`: the `vllm serve` lifecycle. |
| `harness/bench.py` | **Create (Task 6).** `run_bench(...)`, `bench_command(...)`, `BenchError`. |
| `harness/gpu_util.py` | **Create (Task 7).** `GpuUtilSampler`. |
| `harness/sweep_worker.py` | **Create (Task 8).** In-container sweep run: prompt path, warm-up, measured run, summary, `max_num_seqs_from_log`. |
| `harness/service_sweep.py` | **Create (Task 9).** Local sweep side: levels, schedule, payload, `SweepRun`, `build_sweep_record`, `reduce_curve`. |
| `worker/sweep_handler.py` | **Create (Task 10).** RunPod handler for one (level, repeat). |
| `worker/Dockerfile` | **Modify (Task 10).** `COPY worker/sweep_handler.py`. |
| `scripts/run_service_sweep.py` | **Create (Task 11).** Local driver and the sweep pin set. |
| `scripts/a2_service_curve.py` | **Create (Task 12).** Tuples → artifact 2's `ServiceCurve`, with `max_num_seqs`. |
| `harness/README.md` | **Modify (Task 13).** The new modules move from "Not yet here" to the table. |
| `coldstart/driver.py` | **Modify (Task 14).** `run_campaign` becomes a thin wrapper; the old loop is deleted last. |
| `tests/test_harness_campaign.py`, `tests/test_harness_submit_payload.py` | Tasks 2–3, verbatim from artifact 5. |
| `tests/test_payload_stub_submitter.py`, `tests/test_harness_serve.py`, `tests/test_harness_bench.py`, `tests/test_harness_gpu_util.py`, `tests/test_harness_sweep_worker.py`, `tests/test_harness_service_sweep.py`, `tests/test_sweep_handler.py`, `tests/test_run_service_sweep.py`, `tests/test_a2_service_curve.py`, `tests/test_shared_tooling_boundary.py` | Tests, per task. |
| `tests/sweep_fakes.py` | **Create (Task 10).** Fake engine, bench and sampler with a known timing model. Not collected (no `test_` prefix). |
| `tests/test_harness_boundary.py` | **Modify (Task 10).** Every `worker/*.py` is COPYed. |
| `build/shared-tooling-baseline/` | **Create (Task 1), gitignored, local only.** The "before" baseline. |

---

## Task 1: Inventory the campaign loop and capture the "before" baseline

Tasks 3 and 14 replace existing code: `RunPodSubmitter.submit` and the loop in `coldstart/driver.run_campaign`. This repository's rules require an inventory built **by reading the code**, a keep/drop decision for every capability, and a baseline to compare against, before anything is changed. The inventory below was built from `coldstart/driver.py` and `harness/runpod/submitter.py` at commit `39c20b3`; this task re-verifies it against the tree you are on and records the baseline. It changes no tracked file.

**Files:**
- Create (gitignored, local only): `build/shared-tooling-baseline/driver_baseline.py`, `build/shared-tooling-baseline/before/`, `build/shared-tooling-baseline/notes.txt`

- [ ] **Step 1: Confirm the starting point**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
git log --oneline -1
ls harness/campaign.py harness/serve.py harness/bench.py harness/gpu_util.py harness/service_sweep.py 2>&1
grep -n "def submit_payload" harness/runpod/submitter.py
```

Expected: HEAD at or after `39c20b3`; every `ls` line says `No such file or directory`; the `grep` prints nothing. If `harness/campaign.py` exists, artifact 4's or 5's plan reached it first: run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_campaign.py -q` (artifact 5's six tests). If they pass, skip Task 2's Steps 1–4 and keep its file; if they fail, stop and reconcile the two interfaces before going on. Apply the same rule to `submit_payload` and Task 3. If `harness/serve.py` or `harness/bench.py` exists, stop: another plan built them, and this one must be reconciled with it first.

- [ ] **Step 2: Re-verify every row of the inventory against the code**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
grep -n "def _new_run_id\|uuid.uuid4\|def _record_from\|def run_campaign\|build_schedule(\|if resume\|falls beyond\|has arm\|done.add\|in done\|_new_run_id()\|submitter.submit(\|triple_index\|store.append\|on_run(\|return store" coldstart/driver.py
grep -n "def submit\|_UnhealthyRun\|except Exception\|clock_A\|start({" harness/runpod/submitter.py
grep -rn "run_campaign\|_record_from\|_new_run_id" scripts tests harness --include='*.py' | grep -v "^tests/test_harness_campaign.py"
```

Expected: every line number cited in the tables below appears in the first command's output, within a line or two; the third command lists `harness/runpod/submitter.py` (row 15), `scripts/prime_compile_cache.py`, `scripts/run_window.py`, `tests/test_driver.py` and `tests/test_end_to_end.py` (row 4), plus two non-callers: a comment in `tests/test_metrics.py` and `tests/test_stubs.py`'s unrelated local helper `_record_from_stub`. **If the output shows a capability the tables do not list, add a row (with a decision) before continuing** — an unlisted capability is exactly the failure this task exists to prevent.

**A. `coldstart/driver.run_campaign` and its helpers — keep/drop log**

| # | Capability (read from the code) | Lines at `39c20b3` | Decision |
|---|---|---|---|
| 1 | Run id generated **before** submit, uuid4 hex (no `/`, so `CacheConfig.env` accepts it) | 11–22, 221 | **Preserved.** Wrapper passes `make_run_id=_new_run_id`; `harness.campaign` calls it before `submit`. |
| 2 | Failure path of `_record_from`: diagnostics' log lines parsed, `failed_engine` built, status `failed` with `classify_failure` | 26–62 | **Preserved unchanged** in `coldstart/driver.py` as the `build_record` callback. |
| 3 | OK path of `_record_from`: `arm_state_unverifiable` flag, engine fields incl. raw `log_lines`, `host` copied, `config`, status `ok` | 64–157 | **Preserved unchanged** (same callback). |
| 4 | Signature `run_campaign(submitter, store, arms, triples, seed, on_run=None, resume=False)` | 160 | **Preserved exactly.** Callers: `scripts/run_window.py:185`, `scripts/prime_compile_cache.py:66`, `tests/test_driver.py`, `tests/test_end_to_end.py`. |
| 5 | The whole docstring, including the "store holds only this campaign" caveat | 161–191 | **Preserved verbatim**; the caveat is repeated in `harness/campaign.py`'s module docstring. |
| 6 | Schedule rebuilt from `build_schedule(conditions=arms, blocks=triples, seed=seed)` | 192 | **Preserved** in the wrapper. |
| 7 | `resume` off by default | 160, 183–184 | **Preserved** (`harness.campaign` default `False`; wrapper passes it through). |
| 8 | Resume reads the whole store once and validates every record **before any job is submitted** | 194–217 | **Preserved** (`check_resume` runs before the loop). |
| 9 | Drift guard: stored `run_index` beyond the rebuilt schedule raises `ValueError` | 198–206 | **Preserved; wording changes.** New text keeps `run_index N` and `beyond`; drops "for the given arms/triples/seed" and "(e.g. fewer triples)". |
| 10 | Drift guard: stored arm differs from the schedule's raises `ValueError` | 207–216 | **Preserved; wording changes** from "has arm 'C' … assigns it arm 'A'" to "has condition 'C' … assigns it 'A'". Both name the index and both values. **Accepted 2026-10-04** (owner delegated the call to the controller) — the text an operator sees on a refused resume changes. |
| 11 | Completed indices skipped | 217–220 | **Preserved.** |
| 12 | One `submitter.submit(arm=..., run_id=...)` per scheduled run, keyword call, never retried; any exception propagates (an interrupted window keeps what it stored) | 222 | **Preserved** in the wrapper's `submit` closure (keyword call kept, so `StubSubmitter` and `RunPodSubmitter` are unchanged); `harness.campaign` has no `try`. |
| 13 | `record.host["triple_index"] = scheduled.block_index` after the record is built | 224 | **Preserved** in the wrapper's `build_record` callback. |
| 14 | Each record appended as it lands; `on_run(record)` after the append; returns `store` | 225–228 | **Preserved** (same order in `harness.campaign`). |
| 15 | `harness/runpod/submitter.py:3` docstring names `driver._record_from` | — | **Preserved**; still true. |

**Intentionally dropped:** nothing.

**B. `RunPodSubmitter.submit(arm, run_id)` — keep/drop log (Task 3)**

| Capability | Decision |
|---|---|
| Payload is exactly `{"arm": arm, "run_id": run_id}` | **Preserved** — `submit` builds it and calls `submit_payload`; artifact 5's test `test_artifact_ones_submit_is_now_the_two_field_payload` pins it. |
| Clock A stamped on both paths | **Preserved** in `submit_payload`. |
| Unhealthy engine → `_UnhealthyRun` → error text + output as `diagnostics` | **Preserved.** |
| Any other exception → error string, `payload=None` (failures are data) | **Preserved.** |
| `KeyboardInterrupt` escapes | **Preserved** (`except Exception` does not catch it); `tests/test_runpod_submitter.py::test_keyboard_interrupt_still_escapes` pins it. |

**C. `worker/probe.py`'s lifecycle — lifted into `harness/serve.py`; the probe itself is untouched**

| Probe behaviour | In `served` |
|---|---|
| Port 8000 (line 26) | Kept as the default; `port` is per call. |
| Health poll 0.25 s, 2 s request timeout (64–73) | Kept. |
| Health budget 900 s (106) | Kept as `health_timeout`'s default. |
| `Popen`, stdout+stderr merged, `text=True`, `bufsize=1` (133–140) | Kept, plus `start_new_session=True`. |
| Env overrides merged into a copy of `os.environ` (129–131) | Kept. |
| Daemon drain thread (142–157) | Kept. |
| terminate → wait 30 s → kill; join drain 15 s (161–167, 187–194) | Kept, by process group, plus a final SIGKILL sweep of the group. |
| `drain_completed` flag (204) | Kept as `Server.drain_completed`. |
| `served_cmd` recorded (170, 199) | Kept as `Server.cmd`. |
| Clock-B stage marks S1–S7, the warm-up trio, `derived` | **Not lifted:** artifact 1's measurement, not lifecycle. The probe keeps them. |
| (Not in the probe) early exit when the process dies | **Added.** |

- [ ] **Step 3: Record the test baseline**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
mkdir -p build/shared-tooling-baseline
{
  echo "HEAD: $(git rev-parse --short HEAD)"
  echo "collected: $(PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --collect-only -o addopts='' -q | tail -1)"
  echo "driver+e2e: $(PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts='' -q tests/test_driver.py tests/test_end_to_end.py | tail -1)"
  echo "submitter: $(PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts='' -q tests/test_runpod_submitter.py tests/test_submitter.py tests/test_harness_boundary.py | tail -1)"
  echo "signature: $(PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c 'import inspect; from coldstart.driver import run_campaign; print(inspect.signature(run_campaign))')"
} | tee build/shared-tooling-baseline/notes.txt
```

Expected (at `39c20b3` when this plan was written; your collected count may be higher because other workstreams add tests):

```
HEAD: 39c20b3
collected: 1227 tests collected in 0.67s
driver+e2e: 29 passed in 0.72s
submitter: 25 passed in 0.14s
signature: (submitter, store, arms, triples, seed, on_run=None, resume=False)
```

- [ ] **Step 4: Run the parity gate and record it**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
./scripts/parity_check.sh 2>&1 | tail -8 | tee -a build/shared-tooling-baseline/notes.txt
```

Expected, ending:

```
analysis.json: identical
== figures: every published pixel ==
waterfall.png: identical
warmup.png: identical
ecdf.png: identical
per_host.png: identical

PARITY OK
```

Anything else: stop. The baseline has to be green before anything can be compared against it.

- [ ] **Step 5: Write the driver baseline script**

Create `build/shared-tooling-baseline/driver_baseline.py`:

```python
"""Artifact 1's campaign loop on fixed inputs: the stored bytes, the on_run
sequence, and both resume-guard messages. Deterministic: run ids come from a
counter and every clock is the stub's virtual clock, so two runs of the same
code produce byte-identical output.

Usage: driver_baseline.py OUTDIR [legacy]. `legacy` runs
`coldstart.driver._legacy_run_campaign`, which exists only between Task 14's
Steps 3 and 8, so old and new loops can be compared in one tree."""

import itertools
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.getcwd())

from coldstart import driver
from coldstart.schema import RunRecord
from coldstart.stubs.stub_endpoint import StubEndpoint, VirtualClock
from harness.store import JsonlStore
from harness.submit import StubSubmitter

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
counter = itertools.count()
driver._new_run_id = lambda: f"run{next(counter):04d}"
if len(sys.argv) > 2 and sys.argv[2] == "legacy":
    driver.run_campaign = driver._legacy_run_campaign


def campaign(store, seed, triples, resume=False, on_run=None):
    clock = VirtualClock()
    driver.run_campaign(
        StubSubmitter(StubEndpoint(seed=7, clock=clock), clock=clock),
        store, ["A", "B", "C"], triples, seed, on_run=on_run, resume=resume,
    )


with tempfile.TemporaryDirectory() as tmp:
    store = JsonlStore(Path(tmp) / "c.jsonl", RunRecord)
    seen = []
    campaign(store, 31, 4, on_run=lambda r: seen.append((r.run_index, r.arm, r.host["triple_index"])))
    (out / "campaign.jsonl").write_bytes(store.path.read_bytes())
    (out / "on_run.txt").write_text(repr(seen) + "\n")
    messages = []
    for seed, triples in ((99, 4), (31, 2)):
        try:
            campaign(store, seed, triples, resume=True)
        except ValueError as e:
            messages.append(str(e))
    (out / "drift_messages.txt").write_text("\n".join(messages) + "\n")
    # Resume after an interrupted window continues the same interleaving.
    store2 = JsonlStore(Path(tmp) / "r.jsonl", RunRecord)
    clock = VirtualClock()
    ep = StubEndpoint(seed=7, clock=clock)

    class StopAt5:
        def run(self, arm, run_id):
            if len(store2.read_all()) == 5:
                raise KeyboardInterrupt
            return ep.run(arm=arm, run_id=run_id)

    try:
        driver.run_campaign(StubSubmitter(StopAt5(), clock=clock), store2, ["A", "B", "C"], 4, 31)
    except KeyboardInterrupt:
        pass
    driver.run_campaign(StubSubmitter(ep, clock=clock), store2, ["A", "B", "C"], 4, 31, resume=True)
    (out / "resumed.jsonl").write_bytes(store2.path.read_bytes())
print(f"baseline written to {out}")
```

- [ ] **Step 6: Capture the "before" behaviour and check it is deterministic**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python build/shared-tooling-baseline/driver_baseline.py build/shared-tooling-baseline/before
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python build/shared-tooling-baseline/driver_baseline.py build/shared-tooling-baseline/before2
for f in campaign.jsonl on_run.txt resumed.jsonl drift_messages.txt; do
  cmp -s build/shared-tooling-baseline/before/$f build/shared-tooling-baseline/before2/$f && echo "$f: deterministic" || echo "$f: NOT DETERMINISTIC"
done
cat build/shared-tooling-baseline/before/on_run.txt
cat build/shared-tooling-baseline/before/drift_messages.txt
```

Expected: four `deterministic` lines; `on_run.txt` is

```
[(0, 'C', 0), (1, 'B', 0), (2, 'A', 0), (3, 'C', 1), (4, 'B', 1), (5, 'A', 1), (6, 'B', 2), (7, 'C', 2), (8, 'A', 2), (9, 'B', 3), (10, 'C', 3), (11, 'A', 3)]
```

and `drift_messages.txt` holds exactly the two messages `tests/test_driver.py` asserts on (`test_resume_rejects_a_drifted_seed` checks `"run_index 0"`, `"C"`, `"A"`; `test_resume_rejects_a_shrunk_schedule` checks `"run_index"`, `"beyond"`):

```
resume: stored run_index 0 has arm 'C' on disk, but the rebuilt schedule assigns it arm 'A'. This means resume was called with different arms/triples/seed than produced the stored data, which would splice two different interleavings together -- resume must use the exact arms/triples/seed of the original window.
resume: stored run_index 6 falls beyond the rebuilt schedule, which only covers 0..5 for the given arms/triples/seed. This means resume was called with different schedule parameters (e.g. fewer triples) than produced the stored data -- resume must use the exact arms/triples/seed of the original window.
```

`campaign.jsonl` and `resumed.jsonl` are about 254 KB each. Nothing to commit: `build/` is gitignored, and this task changed no tracked file.

---

## Task 2: Lift the campaign loop into the harness (artifact 5 plan 1 Task 3, verbatim)

Artifacts 4 and 5 both need artifact 1's schedule, submit, record and store loop with its resume guard. It is lifted with the submit and record steps passed in as callables. **The code and tests below are copied verbatim from `docs/superpowers/plans/2026-09-26-artifact-5-plan-1-gpu-free-core.md` Task 3 (lines 321–613), as the owner decided on 2026-10-04.** That task's Steps 5–7 — migrating `coldstart/driver.py` and the parity gate — are Task 14 here, so the old loop is deleted last, after everything else is in.

**Ownership rule (artifact 5's, kept):** if `harness/campaign.py` already exists, do not rewrite it. Run Step 1's test against it. If it passes, skip to Step 5. If it fails, stop and reconcile the two interfaces before continuing.

**Files:**
- Create: `harness/campaign.py`, `tests/test_harness_campaign.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_harness_campaign.py`:

```python
from dataclasses import asdict, dataclass

import pytest

from harness.campaign import run_campaign
from harness.scheduler import build_schedule
from harness.store import JsonlStore
from harness.submit import SubmitOutcome


@dataclass
class Row:
    run_index: int
    condition: str
    run_id: str
    ok: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Row":
        return cls(**d)


class Recorder:
    def __init__(self, fail_at: int | None = None):
        self.calls: list[tuple[int, str]] = []
        self.fail_at = fail_at

    def submit(self, scheduled, run_id):
        self.calls.append((scheduled.run_index, scheduled.condition))
        if scheduled.run_index == self.fail_at:
            raise KeyboardInterrupt  # an operator stopping the window mid-run
        return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload={}, error=None)


def _build(scheduled, run_id, outcome):
    return Row(scheduled.run_index, scheduled.condition, run_id, outcome.error is None)


def _run(store, schedule, submitter, **kw):
    return run_campaign(
        schedule,
        submitter.submit,
        _build,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        **kw,
    )


def test_one_record_per_scheduled_run_in_schedule_order(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x", "y"], blocks=3, seed=4)
    _run(store, schedule, Recorder())
    rows = store.read_all()
    assert [r.run_index for r in rows] == list(range(6))
    assert [r.condition for r in rows] == [s.condition for s in schedule]


def test_run_ids_are_generated_by_the_caller_supplied_factory(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    ids = iter(["id0", "id1"])
    _run(store, build_schedule(["x"], blocks=2, seed=1), Recorder(), make_run_id=lambda: next(ids))
    assert [r.run_id for r in store.read_all()] == ["id0", "id1"]


def test_resume_skips_what_is_stored_and_keeps_the_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x", "y", "z"], blocks=3, seed=9)
    with pytest.raises(KeyboardInterrupt):
        _run(store, schedule, Recorder(fail_at=4))
    second = Recorder()
    _run(store, schedule, second, resume=True)
    assert [i for i, _ in second.calls] == list(range(4, 9))
    assert [r.run_index for r in store.read_all()] == list(range(9))


def test_resume_refuses_a_drifted_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    _run(store, build_schedule(["x", "y", "z"], blocks=3, seed=9), Recorder())
    drifted = build_schedule(["x", "y", "z"], blocks=3, seed=10)
    first_stored = store.read_all()[0]
    assert drifted[0].condition != first_stored.condition, "pick seeds whose first slot differs"
    with pytest.raises(ValueError) as e:
        _run(store, drifted, Recorder(), resume=True)
    msg = str(e.value)
    assert "run_index 0" in msg
    assert repr(first_stored.condition) in msg
    assert repr(drifted[0].condition) in msg


def test_resume_refuses_a_shrunk_schedule(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    _run(store, build_schedule(["x", "y"], blocks=3, seed=2), Recorder())
    with pytest.raises(ValueError, match="beyond"):
        _run(store, build_schedule(["x", "y"], blocks=1, seed=2), Recorder(), resume=True)


def test_resume_is_off_by_default(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl", Row)
    schedule = build_schedule(["x"], blocks=2, seed=1)
    _run(store, schedule, Recorder())
    again = Recorder()
    _run(store, schedule, again)
    assert len(again.calls) == 2
    assert len(store.read_all()) == 4
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_campaign.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.campaign'`.

- [ ] **Step 3: Create `harness/campaign.py`**

```python
"""The campaign loop every measurement artifact shares: schedule -> submit ->
record -> store, with a resume guard.

Lifted from artifact 1's `coldstart/driver.run_campaign`. What an artifact
submits and what record it builds are its own business, so both arrive as
callables; what is worth sharing is the discipline around them:

- One record per scheduled run, appended as it lands. Never retried in place:
  a retry would hide a failure the failure-rate table has to count.
- `resume=True` skips runs already in the store, keyed by `run_index`, and
  first checks that every stored record agrees with the rebuilt schedule. A
  resumed window called with a drifted seed or block count would otherwise
  splice two interleavings into one store -- the confound interleaving exists
  to prevent -- and nothing downstream could tell.

The drift guard assumes the store holds only this campaign's records. Give
each campaign its own store file.
"""

import uuid
from collections.abc import Callable, Iterable


def new_run_id() -> str:
    """Generated before the job is submitted: artifacts namespace per-run
    paths by it, so it must exist before the worker runs. A uuid4 hex string
    contains no "/"."""
    return uuid.uuid4().hex


def check_resume(
    schedule: list,
    stored: Iterable,
    index_of: Callable[[object], int],
    condition_of: Callable[[object], str],
) -> set[int]:
    """Return the run indices already done, refusing a store that disagrees
    with `schedule`."""
    expected = {s.run_index: s.condition for s in schedule}
    done: set[int] = set()
    for record in stored:
        index = index_of(record)
        want = expected.get(index)
        if want is None:
            raise ValueError(
                f"resume: stored run_index {index} falls beyond the rebuilt "
                f"schedule, which only covers 0..{len(schedule) - 1}. Resume "
                "was called with different schedule parameters than produced "
                "the stored data -- it must use the exact ones of the original "
                "window."
            )
        have = condition_of(record)
        if have != want:
            raise ValueError(
                f"resume: stored run_index {index} has condition {have!r} on "
                f"disk, but the rebuilt schedule assigns it {want!r}. Resume "
                "was called with different schedule parameters than produced "
                "the stored data, which would splice two interleavings together "
                "-- it must use the exact ones of the original window."
            )
        done.add(index)
    return done


def run_campaign(
    schedule: list,
    submit: Callable,
    build_record: Callable,
    store,
    *,
    index_of: Callable[[object], int],
    condition_of: Callable[[object], str],
    make_run_id: Callable[[], str] = new_run_id,
    on_run: Callable | None = None,
    resume: bool = False,
):
    """Run every scheduled item not already stored.

    `submit(scheduled, run_id)` returns a `harness.submit.SubmitOutcome`.
    `build_record(scheduled, run_id, outcome)` returns the artifact's record,
    which `store.append` persists. `index_of` and `condition_of` read a stored
    record's run index and condition for the resume guard.

    `resume` is off by default: silently skipping runs an operator asked for is
    a worse failure than repeating them.
    """
    done = check_resume(schedule, store.read_all(), index_of, condition_of) if resume else set()
    for scheduled in schedule:
        if scheduled.run_index in done:
            continue
        run_id = make_run_id()
        outcome = submit(scheduled, run_id)
        record = build_record(scheduled, run_id, outcome)
        store.append(record)
        if on_run:
            on_run(record)
    return store
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_campaign.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/campaign.py tests/test_harness_campaign.py
git add harness/campaign.py tests/test_harness_campaign.py
git commit -m "feat: lift the campaign loop into the harness, artifact 5's code verbatim"
```

Expected from ruff: `All checks passed!`

---

## Task 3: Submit an arbitrary payload to RunPod (artifact 5 plan 1 Task 4, verbatim)

`RunPodSubmitter.submit(arm, run_id)` builds artifact 1's two-field payload. Artifact 5's worker needs a whole instance specification, and the sweep worker needs a level and a repeat. This adds `submit_payload`, and `submit` becomes a one-line call to it with the same payload as before. It is additive. **Code and tests verbatim from artifact 5 plan 1 Task 4 (lines 614–761).** Task 1's log B lists what `submit` did and where each behaviour now lives.

**Ownership rule:** if `grep -n "def submit_payload" harness/runpod/submitter.py` already prints a line, run Step 1's test against it and skip to Step 4 if it passes.

**Files:**
- Modify: `harness/runpod/submitter.py` (the `submit` method, lines 166–182 at `39c20b3`)
- Create: `tests/test_harness_submit_payload.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_harness_submit_payload.py`:

```python
import copy

from harness.runpod.submitter import RunPodSubmitter

COMPLETED = {
    "id": "job-7",
    "status": "COMPLETED",
    "delayTime": 1200,
    "executionTime": 90000,
    "workerId": "worker-xyz",
    "output": {"healthy": True, "host": {"host_id": "container-1"}, "phases": []},
}


class FakeTransport:
    def __init__(self, status):
        self._status = status
        self.started = []

    def start(self, payload):
        self.started.append(payload)
        return self._status["id"]

    def status(self, job_id):
        return self._status


def _submitter(status):
    transport = FakeTransport(status)
    clock = iter([10.0, 25.0])
    sub = RunPodSubmitter(transport, clock=lambda: next(clock), sleep=lambda s: None)
    return sub, transport


def test_the_payload_is_sent_verbatim():
    sub, transport = _submitter(COMPLETED)
    payload = {"run_id": "r1", "condition": "sweep-N16", "n_slots": 16, "phases": []}
    sub.submit_payload(payload)
    assert transport.started == [payload]


def test_a_completed_job_returns_the_output_with_platform_identity_attached():
    sub, _ = _submitter(COMPLETED)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.error is None
    assert outcome.clock_A == {"t_submit": 10.0, "t_result": 25.0}
    assert outcome.payload["host"]["host_id"] == "worker-xyz"
    assert outcome.payload["host"]["container_host_id"] == "container-1"
    assert outcome.payload["host"]["job_id"] == "job-7"
    assert "clock_C" in outcome.payload


def test_an_unhealthy_engine_keeps_its_output_as_diagnostics():
    status = copy.deepcopy(COMPLETED)
    status["output"]["healthy"] = False
    status["output"]["log_lines"] = ["CUDA out of memory"]
    sub, _ = _submitter(status)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.payload is None
    assert "health check timed out" in outcome.error
    assert outcome.diagnostics["log_lines"] == ["CUDA out of memory"]


def test_a_failed_job_is_data_not_an_exception():
    status = {"id": "job-8", "status": "FAILED", "error": "worker exited"}
    sub, _ = _submitter(status)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.payload is None
    assert "FAILED" in outcome.error


def test_artifact_ones_submit_is_now_the_two_field_payload():
    sub, transport = _submitter(COMPLETED)
    sub.submit(arm="B", run_id="run-9")
    assert transport.started == [{"arm": "B", "run_id": "run-9"}]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_submit_payload.py -v`
Expected: FAIL with `AttributeError: 'RunPodSubmitter' object has no attribute 'submit_payload'`.

- [ ] **Step 3: Replace `submit` in `harness/runpod/submitter.py`**

Replace the whole existing `submit` method of `RunPodSubmitter` with these two methods:

```python
    def submit(self, arm: str, run_id: str) -> SubmitOutcome:
        """Artifact 1's job: its payload is exactly an arm and a run id."""
        return self.submit_payload({"arm": arm, "run_id": run_id})

    def submit_payload(self, payload: dict) -> SubmitOutcome:
        """Run one job whose input is `payload`, verbatim.

        `submit(arm, run_id)` builds artifact 1's two-field payload. Another
        artifact's worker needs a different input -- artifact 5's carries a
        whole instance specification -- and everything around the payload is
        the same: clock A stamped on both paths, the job awaited to a terminal
        state, an unhealthy engine's output kept as diagnostics, and failures
        returned as data rather than raised.
        """
        t_submit = self._clock()
        try:
            job_id = self._transport.start(payload)
            result = self._payload_from(self._await_terminal(job_id))
            error, diagnostics = None, None
        except _UnhealthyRun as e:
            result, error, diagnostics = None, str(e), e.output
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            result, error, diagnostics = None, str(e), None
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=result,
            error=error,
            diagnostics=diagnostics,
        )
```

- [ ] **Step 4: Run the new tests and artifact 1's submitter tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_submit_payload.py tests/test_runpod_submitter.py -q`
Expected: all pass (21 at `39c20b3`: 5 new plus artifact 1's 16). The last new test pins that artifact 1's payload is unchanged.

- [ ] **Step 5: Run the parity gate, then commit**

Run: `./scripts/parity_check.sh`. Expected: last line `PARITY OK`.

```bash
git add harness/runpod/submitter.py tests/test_harness_submit_payload.py
git commit -m "feat: submit_payload, so a worker can take more than artifact 1's arm and run id"
```

---

## Task 4: A payload stub submitter for GPU-free tests

Every GPU-free test of a payload-taking worker needs a stand-in for `submit_payload`. `StubSubmitter` cannot be it: its interface is `submit(arm, run_id)`. Artifact 5's stand-in lives in its own package; the sweep needs one in the harness. The important property is that it fails where the real submitter fails: a falsy `healthy` is a failure, and a payload that would not serialise fails here rather than on the first paid job.

**Files:**
- Modify: `harness/submit.py` (add `import json`; append `UNHEALTHY_ERROR` and `PayloadStubSubmitter`)
- Create: `tests/test_payload_stub_submitter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_payload_stub_submitter.py`:

```python
"""The payload stub is what every GPU-free test of a payload-taking worker
runs through, so it must fail in the same places the real submitter does."""

from pathlib import Path

import pytest

from harness.failures import FailureClass, classify_failure
from harness.runpod.submitter import RunPodSubmitter
from harness.submit import UNHEALTHY_ERROR, PayloadStubSubmitter


def _clock():
    ticks = iter([1.0, 4.0])
    return lambda: next(ticks)


def test_a_healthy_output_is_the_payload_and_clock_a_brackets_it():
    seen = []

    def worker(payload):
        seen.append(payload)
        return {"healthy": True, "echo": payload["x"]}

    outcome = PayloadStubSubmitter(worker, clock=_clock()).submit_payload({"x": 7})
    assert seen == [{"x": 7}]
    assert outcome.error is None
    assert outcome.payload == {"healthy": True, "echo": 7}
    assert outcome.clock_A == {"t_submit": 1.0, "t_result": 4.0}


def test_an_unhealthy_output_is_a_failure_with_the_output_kept():
    output = {"healthy": False, "log_lines": ["CUDA out of memory"]}
    outcome = PayloadStubSubmitter(lambda p: output, clock=_clock()).submit_payload({})
    assert outcome.payload is None
    assert outcome.error == UNHEALTHY_ERROR
    assert outcome.diagnostics == output
    assert classify_failure(outcome.error) is FailureClass.HEALTH_TIMEOUT


def test_an_output_without_healthy_counts_as_unhealthy():
    outcome = PayloadStubSubmitter(lambda p: {"run": {}}, clock=_clock()).submit_payload({})
    assert outcome.error == UNHEALTHY_ERROR


def test_a_worker_exception_is_data_not_a_raise():
    def worker(payload):
        raise RuntimeError("engine exploded")

    outcome = PayloadStubSubmitter(worker, clock=_clock()).submit_payload({})
    assert outcome.payload is None
    assert outcome.error == "engine exploded"
    assert outcome.clock_A == {"t_submit": 1.0, "t_result": 4.0}


def test_a_payload_the_real_transport_could_not_send_fails_here():
    outcome = PayloadStubSubmitter(lambda p: {"healthy": True}, clock=_clock()).submit_payload(
        {"path": Path("/tmp/x")}
    )
    assert outcome.payload is None
    assert "not JSON serializable" in outcome.error


def test_the_payload_arrives_as_json_would_deliver_it():
    seen = []
    PayloadStubSubmitter(lambda p: seen.append(p) or {"healthy": True}).submit_payload(
        {"levels": (1, 2)}
    )
    assert seen == [{"levels": [1, 2]}]


def test_keyboard_interrupt_still_escapes():
    def worker(payload):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        PayloadStubSubmitter(worker).submit_payload({})


def test_the_unhealthy_text_matches_the_real_submitters():
    class Transport:
        def start(self, payload):
            return "job-1"

        def status(self, job_id):
            return {"id": job_id, "status": "COMPLETED", "output": {"healthy": False}}

    real = RunPodSubmitter(Transport(), sleep=lambda s: None).submit_payload({})
    assert real.error == UNHEALTHY_ERROR
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_payload_stub_submitter.py -v`
Expected: FAIL with `ImportError: cannot import name 'UNHEALTHY_ERROR' from 'harness.submit'`.

- [ ] **Step 3: Replace the whole of `harness/submit.py` with**

(The first 59 lines — `SubmitOutcome` and `StubSubmitter` — are unchanged apart from the added `import json`.)

```python
"""Clock A. Stamps submit and result around a job, and captures failures as data."""

import json
import time
from dataclasses import dataclass


@dataclass
class SubmitOutcome:
    clock_A: dict
    payload: dict | None
    error: str | None
    # What the worker returned on a run that failed but still reported
    # something. `payload` stays None for a failure so nothing downstream can
    # mistake it for a usable run; this carries the engine output that explains
    # WHY it failed. A health-timeout run is the case that matters: the probe
    # returns its log lines with healthy=False, and without this they are
    # dropped -- discarding the evidence for exactly the runs that need it.
    diagnostics: dict | None = None


class StubSubmitter:
    """Clock A against the in-process stub. Same interface as the real submitter.

    `t_result` is stamped after the endpoint returns, which for a
    request/response worker is after all ten warmup requests (S7) complete --
    not at first token of request 1 (S6), the spec's `T_total` boundary
    (spec 7). `t_result - t_submit` is therefore NOT `T_total` and must not be
    treated as such downstream: `metrics.derive()` recovers `T_total` by
    subtracting the clock-B warmup tail (`S7_warmup_done - S6_first_token`)
    from this raw span. See B1.
    """

    def __init__(self, endpoint, clock=time.monotonic):
        self._endpoint = endpoint
        self._clock = clock

    def submit(self, arm: str, run_id: str) -> SubmitOutcome:
        """Run one job. `run_id` is supplied by the caller, never generated here.

        The arm's cache paths are namespaced by `run_id` (`CacheConfig.env`), so
        the id the endpoint runs under has to be the id the stored record
        carries. Generating one here -- or taking the platform's job id after
        the fact -- would leave the paths a run actually used unreconstructible
        from `RunRecord.run_id`.
        """
        t_submit = self._clock()
        try:
            payload = self._endpoint.run(arm=arm, run_id=run_id)
            error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            payload, error = None, str(e)
        # Stamped on both paths: a failed run still consumed wall-clock time and
        # still counts in the failure-rate table.
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=payload,
            error=error,
        )


# The text harness.runpod.submitter raises for a completed job whose engine
# never became healthy, phrased to match harness.failures' HEALTH_TIMEOUT
# needle. Repeated here rather than imported: the RunPod submitter imports this
# module, so importing back would be a cycle. tests/test_payload_stub_submitter.py
# pins that the two stay identical.
UNHEALTHY_ERROR = "health check timed out: probe reported unhealthy"


class PayloadStubSubmitter:
    """`submit_payload(payload)` against an in-process worker function.

    The GPU-free twin of `RunPodSubmitter.submit_payload`, for workers whose
    input is more than artifact 1's arm and run id. `StubSubmitter` cannot
    stand in for that: its interface is `submit(arm, run_id)`.

    It copies the real submitter's one decision about a worker's output: a job
    that completes with an output whose `healthy` is falsy is a FAILURE, with
    the output kept as diagnostics. A stub that accepted any output would let a
    GPU-free test pass a handler that forgets to return `healthy: True` -- and
    the real submitter would then record every paid run as failed.

    The payload and the output both round-trip through JSON, because the real
    transport serialises both. A payload that only works in-process (a tuple
    that comes back a list, a Path that does not serialise at all) fails here,
    as data, instead of on the first paid job.

    Not reproduced: clock C and the platform's worker id, which only the
    platform knows. Records built from this stub carry neither.
    """

    def __init__(self, worker, clock=time.monotonic):
        self._worker = worker
        self._clock = clock

    def submit_payload(self, payload: dict) -> SubmitOutcome:
        t_submit = self._clock()
        try:
            output = json.loads(json.dumps(self._worker(json.loads(json.dumps(payload)))))
            if output.get("healthy"):
                result, error, diagnostics = output, None, None
            else:
                result, error, diagnostics = None, UNHEALTHY_ERROR, output
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            result, error, diagnostics = None, str(e), None
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=result,
            error=error,
            diagnostics=diagnostics,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_payload_stub_submitter.py tests/test_submitter.py tests/test_driver.py -q`
Expected: all pass (8 new).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/submit.py tests/test_payload_stub_submitter.py
git add harness/submit.py tests/test_payload_stub_submitter.py
git commit -m "feat: a payload stub submitter that fails where the real one does"
```

---

## Task 5: The `vllm serve` lifecycle

`served` is the interface artifacts 4 and 5 code against: `served(model, *, args, env, port=8000, health_timeout=900.0)`, a context manager yielding `.base_url`, `.log_lines`, `.healthy` and an idempotent `.stop() -> float`. Its behaviour is lifted from `worker/probe.py` (Task 1's table C), which is not touched.

The tests cannot use vLLM — it is not installed here. Each test writes a fake `vllm` executable into `tmp_path` and puts it first on `PATH`. The fake is a short Python script: it prints startup lines in the engine's wording (including the KV-cache line artifact 5 looks for), serves `/health` with `http.server` on the port it was given, and misbehaves on request through `FAKE_VLLM_MODE` (never healthy, exit 3, ignore SIGTERM, spawn a child). Because the misbehaviour is switched on through `env`, the same tests prove the override semantics.

**Files:**
- Create: `harness/serve.py`, `tests/test_harness_serve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_serve.py`:

```python
"""The `vllm serve` lifecycle, proven against a fake engine.

vLLM is not installed locally, and these tests must not need it. A fake
`vllm` executable is written into tmp_path and put first on PATH: it prints
startup lines in the engine's own wording, serves `/health` on the port it was
given, and misbehaves on request (never healthy, exits early, ignores SIGTERM,
spawns a child) so each failure path runs against a real process.
"""

import inspect
import os
import signal
import socket
import subprocess
import sys
import time

import pytest
import requests

from harness.serve import served

KV_LINE = "INFO GPU KV cache size: 43,040 tokens"

FAKE_VLLM = r'''
import http.server
import os
import signal
import subprocess
import sys
import time

argv = sys.argv[1:]
assert argv[0] == "serve", argv
port = int(argv[argv.index("--port") + 1])
mode = os.environ.get("FAKE_VLLM_MODE", "healthy")
print("ARGV " + " ".join(argv), flush=True)
for key in filter(None, os.environ.get("FAKE_VLLM_ECHO", "").split(",")):
    print(f"ENV {key}={os.environ.get(key)}", flush=True)
print("INFO fake engine starting", flush=True)
print("INFO GPU KV cache size: 43,040 tokens", flush=True)
print("INFO torch.compile took 0.30 s in total", flush=True)
if mode == "exit":
    sys.exit(3)
if mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_VLLM_CHILD_PID"], "w") as f:
        f.write(str(child.pid))
if mode == "never_healthy":
    time.sleep(600)
    sys.exit(0)


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", port), Health).serve_forever()
'''


@pytest.fixture(autouse=True)
def fake_vllm(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "vllm"
    exe.write_text(f"#!{sys.executable}\n{FAKE_VLLM}")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return exe


@pytest.fixture
def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def test_the_signature_is_the_one_artifacts_4_and_5_code_against():
    params = inspect.signature(served).parameters
    assert {"model", "args", "env", "port", "health_timeout"} <= set(params)
    assert params["port"].default == 8000
    assert params["health_timeout"].default == 900.0
    assert params["args"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["env"].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_healthy_engine_yields_its_url_and_its_startup_log(port):
    with served("m", args=["--revision", "r1"], env={}, port=port, health_timeout=30) as server:
        assert server.healthy is True
        assert server.base_url == f"http://127.0.0.1:{port}"
        assert requests.get(f"{server.base_url}/health", timeout=2).status_code == 200
        assert server.cmd == ["vllm", "serve", "m", "--port", str(port), "--revision", "r1"]
    assert f"ARGV serve m --port {port} --revision r1" in server.log_lines
    assert KV_LINE in server.log_lines
    assert server.drain_completed


@pytest.mark.parametrize("bad", [["--port", "9000"], ["--port=9000"]])
def test_a_port_in_args_is_refused_because_served_adds_its_own(bad, port):
    with pytest.raises(ValueError, match="passes --port itself"), served(
        "m", args=bad, env={}, port=port
    ):
        pass


def test_env_is_merged_over_the_parent_environment_and_never_applied_to_it(port, monkeypatch):
    monkeypatch.setenv("FROM_PARENT", "parent")
    monkeypatch.delenv("OVERRIDE", raising=False)
    env = {"FAKE_VLLM_ECHO": "FROM_PARENT,OVERRIDE", "OVERRIDE": "mine"}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
    assert "ENV FROM_PARENT=parent" in server.log_lines
    assert "ENV OVERRIDE=mine" in server.log_lines
    assert "OVERRIDE" not in os.environ


def test_an_engine_that_never_answers_is_yielded_unhealthy_with_its_log(port):
    env = {"FAKE_VLLM_MODE": "never_healthy"}
    with served("m", args=[], env=env, port=port, health_timeout=1.0) as server:
        assert server.healthy is False
        assert server.returncode is not None, "an unhealthy engine is stopped before the yield"
        assert KV_LINE in server.log_lines


def test_the_wait_ends_as_soon_as_the_engine_exits(port):
    started = time.monotonic()
    with served("m", args=[], env={"FAKE_VLLM_MODE": "exit"}, port=port, health_timeout=60) as s:
        assert s.healthy is False
        assert s.returncode == 3
        assert KV_LINE in s.log_lines
    assert time.monotonic() - started < 10, "waited out the health budget on a dead process"


def test_stop_is_idempotent_and_returns_the_teardown_seconds(port):
    with served("m", args=[], env={}, port=port, health_timeout=30) as server:
        first = server.stop()
        assert server.returncode is not None
        assert first >= 0.0
        assert server.stop() == first
    assert server.stop() == first


def test_the_whole_process_group_is_killed(port, tmp_path):
    pid_file = tmp_path / "child.pid"
    env = {"FAKE_VLLM_MODE": "child", "FAKE_VLLM_CHILD_PID": str(pid_file)}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
        child = int(pid_file.read_text())
        assert _alive(child)
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child), "a child of the engine outlived teardown and would hold the GPU"


def test_an_engine_that_ignores_sigterm_is_killed_after_the_grace_period(port):
    env = {"FAKE_VLLM_MODE": "stubborn"}
    with served("m", args=[], env=env, port=port, health_timeout=30, term_grace=0.5) as server:
        assert server.healthy
        took = server.stop()
    assert 0.5 <= took < 10
    assert server.returncode == -signal.SIGKILL


def test_an_exception_in_the_block_still_stops_the_engine(port):
    with (
        pytest.raises(RuntimeError, match="caller failed"),
        served("m", args=[], env={}, port=port, health_timeout=30) as server,
    ):
        assert server.healthy
        raise RuntimeError("caller failed")
    assert server.returncode is not None


def test_a_port_that_already_answers_is_refused_before_spawning(port):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen()
        with pytest.raises(RuntimeError, match="already answering"), served(
            "m", args=[], env={}, port=port
        ):
            pass
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_serve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.serve'`.

- [ ] **Step 3: Create `harness/serve.py`**

```python
"""Start `vllm serve` on a port, wait for health, tear it down on request.

Lifted from `worker/probe.py`'s lifecycle. The probe itself stays frozen: it
is artifact 1's measured path, excerpted by the explainer and reproducible at
the `artifact-1-published` tag. What is shared is the lifecycle, not artifact
1's warm-up trio. The probe is one function that starts, measures and stops,
so another artifact has no point at which to run its own load; `served` yields
the running engine and the caller measures whatever it measures inside the
`with` block.

Kept from the probe: port 8000 by default, a 0.25 s health poll with a 2 s
request timeout, a 900 s health budget, stdout and stderr merged and
line-buffered, the environment overrides merged into a copy of the parent's
environment (never applied to `os.environ`), a daemon thread draining the log,
and terminate -> wait 30 s -> kill on teardown.

Changed from the probe, on purpose:

- The engine runs in its own session and is signalled by process group.
  Whether vLLM's worker processes exit when the API-server parent receives
  SIGTERM is unverified. A surviving engine core would keep the GPU's memory
  into the next job on a reused serverless worker, and that job would start
  its engine on a card that is already partly full.
- The health wait stops as soon as the process exits. The probe polls a dead
  process for the whole 900 s, paying fifteen minutes of GPU time to learn
  what the exit code already said.
- An unhealthy engine is stopped and then YIELDED with `healthy=False` and its
  log lines; it does not raise. Those lines are the only evidence of why the
  engine never came up. Raising would make every caller rebuild the capture,
  and artifact 5's instance runner already reads them off the yielded object.
- A port that something already answers on is refused before spawning. The
  health check would otherwise talk to whatever owns the port and report
  someone else's engine as this one.
"""

import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager

import requests

HEALTH_POLL_SECONDS = 0.25
HEALTH_REQUEST_TIMEOUT_SECONDS = 2.0
TERM_GRACE_SECONDS = 30.0
DRAIN_JOIN_SECONDS = 15.0


def _health_ok(url: str) -> bool:
    try:
        return requests.get(url, timeout=HEALTH_REQUEST_TIMEOUT_SECONDS).status_code == 200
    except requests.RequestException:
        return False


def _refuse_port_in_args(args: Sequence[str]) -> None:
    for arg in args:
        if arg == "--port" or arg.startswith("--port="):
            raise ValueError(
                f"args contains {arg!r}, but served() passes --port itself from its "
                "`port` argument; two --port flags leave the engine on whichever one "
                "argparse keeps, while the health check and base_url use the other"
            )


def _refuse_busy_port(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return
    raise RuntimeError(
        f"something is already answering on 127.0.0.1:{port}; the health check "
        "would talk to it and report another process's engine as this one. Stop "
        "it, or pass a different port"
    )


class Server:
    """A started engine, healthy or not, as `served` yields it.

    `log_lines` grows while the engine runs; read it after `stop()` (or after
    the `with` block) for the complete log. `cmd` is the exact argument list
    that was executed, including the `--port` that `served` added.
    """

    def __init__(self, proc, *, cmd, base_url, term_grace, clock):
        self.cmd = cmd
        self.base_url = base_url
        self.healthy = False
        self.log_lines: list[str] = []
        self._proc = proc
        self._term_grace = term_grace
        self._clock = clock
        self._teardown_s: float | None = None
        self._drain = threading.Thread(target=self._drain_stdout, daemon=True)
        self._drain.start()

    def _drain_stdout(self) -> None:
        for line in self._proc.stdout:
            self.log_lines.append(line.rstrip("\n"))

    @property
    def returncode(self) -> int | None:
        """None while the engine runs; its exit status once it has exited."""
        return self._proc.poll()

    @property
    def drain_completed(self) -> bool:
        """False if the log reader was still running when `stop()` gave up
        waiting for it, in which case `log_lines` may be missing its tail."""
        return not self._drain.is_alive()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self._proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            # The group is already gone. macOS reports a group holding only
            # zombies as EPERM rather than ESRCH; either way nothing is left
            # to signal.
            pass

    def stop(self) -> float:
        """Stop the engine and return how long that took, in seconds.

        The float measures from this call until the `vllm serve` parent
        process has exited: SIGTERM to the whole process group, up to
        `term_grace` seconds of waiting, then SIGKILL to the group if the
        parent is still alive. After the parent exits, the group is swept with
        SIGKILL so no straggling child keeps the GPU.

        It does NOT measure GPU memory release. The driver frees a process's
        memory shortly after the process dies, and how shortly is exactly what
        artifact 4's swap handler measures by polling the device after this
        returns. Folding a poll in here would hard-code one artifact's
        definition of "torn down" into everyone's.

        Idempotent: a second call signals nothing and returns the first call's
        value, so a caller can time teardown inside the `with` block and the
        block's own exit does no harm. An engine that had already exited
        returns roughly 0.0.
        """
        if self._teardown_s is not None:
            return self._teardown_s
        t0 = self._clock()
        if self._proc.poll() is None:
            self._signal_group(signal.SIGTERM)
            try:
                self._proc.wait(timeout=self._term_grace)
            except subprocess.TimeoutExpired:
                self._signal_group(signal.SIGKILL)
                self._proc.wait()
        self._teardown_s = self._clock() - t0
        self._signal_group(signal.SIGKILL)
        # stdout reaches EOF only once every writer is gone; join so the
        # drain thread finishes appending before anyone reads log_lines.
        self._drain.join(timeout=DRAIN_JOIN_SECONDS)
        return self._teardown_s


def _wait_healthy(server: Server, timeout: float, health_ok, clock, sleep) -> bool:
    url = f"{server.base_url}/health"
    deadline = clock() + timeout
    while clock() < deadline:
        if server.returncode is not None:
            return False
        if health_ok(url):
            return True
        sleep(HEALTH_POLL_SECONDS)
    return False


@contextmanager
def served(
    model: str,
    *,
    args: Sequence[str],
    env: Mapping[str, str] | None,
    port: int = 8000,
    health_timeout: float = 900.0,
    executable: str = "vllm",
    term_grace: float = TERM_GRACE_SECONDS,
    health_ok: Callable[[str], bool] = _health_ok,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Server]:
    """Run `vllm serve model --port port *args` for the duration of the block.

    `env` is a dict of OVERRIDES, merged over a copy of `os.environ` for the
    engine process only. A full replacement environment was rejected: every
    caller would have to remember PATH, CUDA and HF variables, and the one that
    forgot would fail on a paid GPU. `os.environ` itself is never touched,
    because a serverless worker is reused across jobs and a mutated environment
    would carry one job's paths into the next.

    Yields a `Server`. Check `.healthy` before sending load: an engine that
    never answered `/health` within `health_timeout`, or exited first, is
    already stopped when it is yielded, so `.log_lines` is complete.

    The engine is always stopped on exit, including when the block raises.
    `executable`, `term_grace`, `health_ok`, `clock` and `sleep` exist for
    tests; production callers pass none of them.
    """
    args = list(args)
    _refuse_port_in_args(args)
    _refuse_busy_port(port)
    merged = os.environ.copy()
    merged.update(env or {})
    cmd = [executable, "serve", model, "--port", str(port), *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=merged,
        start_new_session=True,
    )
    server = Server(
        proc, cmd=cmd, base_url=f"http://127.0.0.1:{port}", term_grace=term_grace, clock=clock
    )
    try:
        server.healthy = _wait_healthy(server, health_timeout, health_ok, clock, sleep)
        if not server.healthy:
            server.stop()
        yield server
    finally:
        server.stop()
```

- [ ] **Step 4: Run the tests to verify they pass — three times**

```bash
for i in 1 2 3; do PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_serve.py -q -o addopts="" | tail -1; done
```

Expected: `12 passed` three times, each in about 4 s. These tests start real processes; a test that passes once and fails once is a race and must be fixed, not retried.

- [ ] **Step 5: Prove two of the tests can fail**

A test of process behaviour that cannot fail proves nothing. Break each feature, watch its test fail, and restore:

```bash
cp harness/serve.py build/serve.py.bak
sed -i '' 's/os.killpg(self._proc.pid, sig)/os.kill(self._proc.pid, sig)/' harness/serve.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_serve.py -q -o addopts="" -k process_group | tail -1
cp build/serve.py.bak harness/serve.py
python3 - <<'PY'
from pathlib import Path
p = Path("harness/serve.py")
p.write_text(p.read_text().replace("        if server.returncode is not None:\n            return False\n", "", 1))
PY
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_serve.py -q -o addopts="" -k "exits" | tail -1
cp build/serve.py.bak harness/serve.py && cmp harness/serve.py build/serve.py.bak && echo restored
```

Expected: `1 failed, 11 deselected` for the first (the engine's child outlives teardown), `1 failed, 11 deselected` for the second after about 60 s (it waits out the health budget on a dead process), then `restored`. If either mutation still passes, the test is not testing the feature: fix the test before going on.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/serve.py tests/test_harness_serve.py
git add harness/serve.py tests/test_harness_serve.py
git commit -m "feat: harness.serve -- the vllm serve lifecycle, killed by process group"
```

---

## Task 6: The `vllm bench serve` wrapper

`run_bench` builds one `vllm bench serve` command, pins what amendment §3f requires, creates `result_dir`, and returns the saved JSON unaltered. Every flag and saved key it relies on was read from vLLM v0.27.1's source (see "Verified against vLLM 0.27.1" above; the module docstring cites the same files). Whether the pinned image's tool accepts them is UNVERIFIED items 2–3, checked on the first paid run.

**Files:**
- Create: `harness/bench.py`, `tests/test_harness_bench.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_bench.py`:

```python
"""`run_bench` builds one `vllm bench serve` command and returns the tool's
saved JSON untouched. The subprocess is faked: vLLM is not installed locally.
The fake writes the result file where the command says the tool would."""

import inspect
import json
import subprocess
from pathlib import Path

import pytest

from harness.bench import RESULT_FILENAME, BenchError, bench_command, run_bench

URL = "http://127.0.0.1:8000"
SAVED = {
    "duration": 12.5,
    "completed": 2,
    "failed": 0,
    "ttfts": [0.1, 0.2],
    "itls": [[0.01], [0.02]],
    "output_lens": [2, 2],
    "errors": ["", ""],
    "a_key_from_a_future_version": {"nested": [1, 2]},
}


class FakeRun:
    def __init__(self, saved=None, returncode=0, stdout="", stderr="", write=True):
        self.saved = SAVED if saved is None else saved
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.write = write
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        if self.write:
            out = Path(cmd[cmd.index("--result-dir") + 1])
            assert out.is_dir(), "run_bench must create result_dir before the tool runs"
            name = cmd[cmd.index("--result-filename") + 1]
            (out / name).write_text(json.dumps(self.saved))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _call(tmp_path, run, **kw):
    args = {
        "model": "Qwen/Qwen3-8B",
        "max_concurrency": 4,
        "num_prompts": 100,
        "dataset_args": ["--dataset-name", "random", "--random-input-len", "13"],
        "ignore_eos": True,
        "seed": 7,
        "result_dir": tmp_path / "does" / "not" / "exist",
        "run": run,
    }
    args.update(kw)
    return run_bench(URL, **args)


def _has(cmd, *seq):
    n = len(seq)
    return any(tuple(cmd[i : i + n]) == seq for i in range(len(cmd) - n + 1))


def test_the_signature_is_the_one_artifacts_4_and_5_code_against():
    params = inspect.signature(run_bench).parameters
    assert {
        "model", "lora_modules", "lora_assignment", "max_concurrency", "num_prompts",
        "dataset_args", "ignore_eos", "seed", "result_dir",
    } <= set(params)
    assert params["lora_modules"].default == ()
    assert params["lora_assignment"].default is None


def test_the_command_starts_with_the_engine_url_and_model(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert run.cmd[:7] == ["vllm", "bench", "serve", "--base-url", URL, "--model", "Qwen/Qwen3-8B"]
    assert _has(run.cmd, "--max-concurrency", "4")
    assert _has(run.cmd, "--num-prompts", "100")
    assert _has(run.cmd, "--seed", "7")


def test_warmups_ready_check_and_saving_are_pinned_on_every_run(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert _has(run.cmd, "--num-warmups", "0")
    assert _has(run.cmd, "--ready-check-timeout-sec", "0")
    assert "--save-result" in run.cmd
    assert "--save-detailed" in run.cmd
    assert _has(run.cmd, "--result-filename", RESULT_FILENAME)


def test_the_result_dir_is_created_and_the_saved_json_comes_back_unaltered(tmp_path):
    out = _call(tmp_path, FakeRun())
    assert out == SAVED
    assert (tmp_path / "does" / "not" / "exist" / RESULT_FILENAME).is_file()


def test_a_sweep_without_lora_sends_no_lora_flags(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert "--lora-modules" not in run.cmd
    assert "--lora-assignment" not in run.cmd


def test_lora_names_and_assignment_reach_the_tool(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, lora_modules=["a00", "a01"], lora_assignment="round-robin")
    assert _has(run.cmd, "--lora-modules", "a00", "a01")
    assert _has(run.cmd, "--lora-assignment", "round-robin")


def test_an_assignment_without_adapters_is_refused(tmp_path):
    with pytest.raises(ValueError, match="base model"):
        _call(tmp_path, FakeRun(), lora_assignment="round-robin")


@pytest.mark.parametrize("ignore_eos", [True, False])
def test_ignore_eos_is_a_flag_only_when_asked_for(tmp_path, ignore_eos):
    run = FakeRun()
    _call(tmp_path, run, ignore_eos=ignore_eos)
    assert ("--ignore-eos" in run.cmd) is ignore_eos


def test_dataset_and_extra_args_pass_through_in_order(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, extra_args=["--percentile-metrics", "ttft,tpot,itl,e2el"])
    assert _has(run.cmd, "--dataset-name", "random", "--random-input-len", "13")
    assert run.cmd[-2:] == ["--percentile-metrics", "ttft,tpot,itl,e2el"]


@pytest.mark.parametrize(
    ("where", "bad"),
    [("dataset_args", ["--save-result"]), ("extra_args", ["--max-concurrency=8"])],
)
def test_a_flag_run_bench_owns_is_refused_wherever_it_appears(tmp_path, where, bad):
    with pytest.raises(ValueError, match="sets itself"):
        _call(tmp_path, FakeRun(), **{where: bad})


def test_a_failed_tool_raises_with_its_exit_code_and_last_output(tmp_path):
    run = FakeRun(returncode=1, stderr="Traceback\nValueError: no pandas", write=False)
    with pytest.raises(BenchError, match="exited 1") as e:
        _call(tmp_path, run)
    assert "no pandas" in str(e.value)


def test_a_tool_that_writes_nothing_raises(tmp_path):
    with pytest.raises(BenchError, match="wrote no"):
        _call(tmp_path, FakeRun(write=False))


def test_a_stale_result_file_is_refused(tmp_path):
    out = tmp_path / "r"
    out.mkdir()
    (out / RESULT_FILENAME).write_text("{}")
    with pytest.raises(ValueError, match="stale"):
        _call(tmp_path, FakeRun(), result_dir=out)


def test_a_timeout_raises_bench_error(tmp_path):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output="partial progress")

    with pytest.raises(BenchError, match="within 3 s") as e:
        _call(tmp_path, run, timeout=3)
    assert "partial progress" in str(e.value)


def test_the_subprocess_is_run_without_check_and_with_output_captured(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, timeout=60)
    assert run.kwargs == {"capture_output": True, "text": True, "check": False, "timeout": 60}


@pytest.mark.parametrize(("c", "n"), [(0, 10), (4, 0)])
def test_zero_concurrency_or_prompts_is_refused(c, n, tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        bench_command(
            URL, model="m", lora_modules=(), lora_assignment=None, max_concurrency=c,
            num_prompts=n, dataset_args=[], ignore_eos=True, seed=0, result_dir=tmp_path,
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_bench.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.bench'`.

- [ ] **Step 3: Create `harness/bench.py`**

```python
"""Run `vllm bench serve` against a running engine; return its saved JSON unaltered.

Why the engine's own benchmark client rather than a load generator written
here: it is what the field quotes, it ships in the pinned image, and it
already handles streaming, concurrency limits, LoRA assignment and
per-request timing. A home-grown client would be one more thing to validate
before any number it produced could be trusted.

Why unaltered: consumers apply their own rules to the raw per-request arrays.
Artifact 5 applies amendment §3f's failure rule; the service sweep applies the
same rule. A wrapper that filtered or summarised would make every consumer
inherit its choices without seeing them. The tool's own summary fields are
passed through untouched; whether to use any of them is the caller's call.

Pinned on every run, whatever the caller asks (amendment §3f):

- `--num-warmups 0` and `--ready-check-timeout-sec 0`. The tool's warm-up and
  ready-check requests target the base model, not the adapters, and the
  caller has already waited on `/health` through `harness.serve`. Both
  default to 0 in vLLM 0.27.1; pinning them keeps a version bump from
  silently adding unmeasured requests.
- `--save-result` and `--save-detailed`. Without the first nothing is written;
  without the second the tool deletes `input_lens`, `output_lens`, `ttfts`,
  `itls`, `start_times`, `generated_texts` and `errors` before saving.
- `--result-filename bench.json`, so the file read back is the file this call
  wrote, and `--disable-tqdm`, so the captured stderr holds errors rather than
  progress bars.

Verified against vLLM v0.27.1's source on 2026-10-04:
https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/serve.py
(`add_cli_args`, `benchmark`, `main_async`) and
https://github.com/vllm-project/vllm/blob/v0.27.1/vllm/benchmarks/datasets/datasets.py
(`add_dataset_parser`).
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

RESULT_FILENAME = "bench.json"
_PINNED = (
    "--num-warmups", "0",
    "--ready-check-timeout-sec", "0",
    "--save-result",
    "--save-detailed",
    "--disable-tqdm",
)
# Flags this module sets from its own arguments or pins. A caller passing one
# of them through dataset_args or extra_args would produce a command with two
# values for one flag, and argparse silently keeps the last.
_MANAGED = frozenset({
    "--append-result",
    "--base-url",
    "--disable-tqdm",
    "--ignore-eos",
    "--lora-assignment",
    "--lora-modules",
    "--max-concurrency",
    "--model",
    "--num-prompts",
    "--num-warmups",
    "--ready-check-timeout-sec",
    "--result-dir",
    "--result-filename",
    "--save-detailed",
    "--save-result",
    "--seed",
})
_TAIL_LINES = 40


class BenchError(RuntimeError):
    """`vllm bench serve` produced no result for this run."""


def _refuse_managed(args: Sequence[str], where: str) -> None:
    for arg in args:
        flag = arg.split("=", 1)[0]
        if flag in _MANAGED:
            raise ValueError(
                f"{where} contains {arg!r}, which run_bench sets itself; argparse "
                "keeps the last of two values silently, so the run would not be "
                "the one its arguments describe"
            )


def bench_command(
    base_url: str,
    *,
    model: str,
    lora_modules: Sequence[str],
    lora_assignment: str | None,
    max_concurrency: int,
    num_prompts: int,
    dataset_args: Sequence[str],
    ignore_eos: bool,
    seed: int,
    result_dir,
    extra_args: Sequence[str] = (),
) -> list[str]:
    """The exact argument list `run_bench` executes. Public so a GPU-free test
    can pin it and an operator can print it."""
    if max_concurrency < 1 or num_prompts < 1:
        raise ValueError(
            f"max_concurrency={max_concurrency!r} and num_prompts={num_prompts!r} must "
            "both be at least 1; the tool reads 0 concurrency as unlimited, which "
            "would measure a different load than the one recorded"
        )
    if lora_assignment is not None and not lora_modules:
        raise ValueError(
            f"lora_assignment={lora_assignment!r} with no lora_modules; the tool "
            "would ignore the assignment and send every request to the base model"
        )
    _refuse_managed(dataset_args, "dataset_args")
    _refuse_managed(extra_args, "extra_args")
    cmd = [
        "vllm", "bench", "serve",
        "--base-url", base_url,
        "--model", model,
        "--max-concurrency", str(max_concurrency),
        "--num-prompts", str(num_prompts),
        "--seed", str(seed),
        *dataset_args,
    ]
    if lora_modules:
        cmd += ["--lora-modules", *lora_modules]
    if lora_assignment is not None:
        cmd += ["--lora-assignment", lora_assignment]
    if ignore_eos:
        cmd.append("--ignore-eos")
    cmd += [*_PINNED, "--result-dir", str(result_dir), "--result-filename", RESULT_FILENAME]
    cmd += list(extra_args)
    return cmd


def _tail(text: str | None) -> str:
    return "\n".join((text or "").splitlines()[-_TAIL_LINES:])


def run_bench(
    base_url: str,
    *,
    model: str,
    lora_modules: Sequence[str] = (),
    lora_assignment: str | None = None,
    max_concurrency: int,
    num_prompts: int,
    dataset_args: Sequence[str],
    ignore_eos: bool,
    seed: int,
    result_dir,
    extra_args: Sequence[str] = (),
    timeout: float | None = None,
    run: Callable = subprocess.run,
) -> dict:
    """Run one benchmark and return the JSON the tool saved, unaltered.

    `lora_modules` and `lora_assignment` default to "no LoRA", so a
    single-model sweep passes neither; with them omitted the command carries
    no LoRA flags at all. `extra_args` carries tool flags that are not dataset
    flags (the sweep asks for `--percentile-metrics`), kept apart from
    `dataset_args` so neither name lies about what it holds.

    `result_dir` is created if missing, and must not already hold a
    `bench.json`: a stale file would be read back as this run's result if the
    tool exited 0 without writing. Raises `BenchError` when the tool exits
    non-zero, times out, or writes nothing, with the tail of its output --
    there is no result to return, and returning an empty dict would let a
    caller compute statistics from nothing.

    `timeout` bounds the tool's wall time; `run` exists for tests.
    """
    out_dir = Path(result_dir)
    result_path = out_dir / RESULT_FILENAME
    cmd = bench_command(
        base_url,
        model=model,
        lora_modules=lora_modules,
        lora_assignment=lora_assignment,
        max_concurrency=max_concurrency,
        num_prompts=num_prompts,
        dataset_args=dataset_args,
        ignore_eos=ignore_eos,
        seed=seed,
        result_dir=out_dir,
        extra_args=extra_args,
    )
    if result_path.exists():
        raise ValueError(
            f"{result_path} already exists; if the tool then exited 0 without "
            "writing, that stale file would be returned as this run's result"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        partial = e.stdout if isinstance(e.stdout, str) else None
        raise BenchError(
            f"vllm bench serve did not finish within {timeout} s and was killed; "
            f"this run has no result. Last output:\n{_tail(partial)}"
        ) from e
    if proc.returncode != 0:
        raise BenchError(
            f"vllm bench serve exited {proc.returncode}; this run has no result. "
            f"Last output:\n{_tail(proc.stderr) or _tail(proc.stdout)}"
        )
    if not result_path.exists():
        raise BenchError(
            f"vllm bench serve exited 0 but wrote no {result_path}; without the saved "
            f"JSON this run has no result. Last output:\n{_tail(proc.stdout)}"
        )
    with result_path.open() as f:
        return json.load(f)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_bench.py -q`
Expected: 19 passed.

- [ ] **Step 5: Confirm artifact 5's prerequisite check now passes for `run_bench`**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import inspect
from harness.bench import run_bench
b = inspect.signature(run_bench).parameters
assert {'model', 'lora_modules', 'lora_assignment', 'max_concurrency', 'num_prompts',
        'dataset_args', 'ignore_eos', 'seed', 'result_dir'} <= set(b), b
print('run_bench has the agreed interface')
"
```

Expected: `run_bench has the agreed interface`.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/bench.py tests/test_harness_bench.py
git add harness/bench.py tests/test_harness_bench.py
git commit -m "feat: harness.bench -- one vllm bench serve run, saved JSON returned unaltered"
```

---

## Task 7: The nvidia-smi utilisation sampler

Owner decision 3. The command runner is injectable; the tests fake it, because there is no GPU here. The sampler never raises on a bad reading: an unreadable GPU becomes a sample with an error, and an all-unreadable run reports `None`, which Task 9's reducer refuses rather than inventing a value.

**Files:**
- Create: `harness/gpu_util.py`, `tests/test_harness_gpu_util.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_gpu_util.py`:

```python
"""The nvidia-smi sampler, with the command runner faked: no GPU here."""

import subprocess
import threading
import time

import pytest

from harness.gpu_util import QUERY, GpuUtilSampler


class FakeSmi:
    def __init__(self, outputs, returncode=0):
        self.outputs = list(outputs)
        self.returncode = returncode
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, cmd, **kwargs):
        with self.lock:
            self.calls.append((cmd, kwargs))
            out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        return subprocess.CompletedProcess(cmd, self.returncode, out, "boom")


def _clock(values):
    it = iter(values)
    return lambda: next(it)


def test_the_query_is_utilization_gpu_for_one_gpu_without_units():
    smi = FakeSmi(["37\n"])
    sampler = GpuUtilSampler(run=smi, gpu_index=0)
    sampler.sample_once()
    cmd, kwargs = smi.calls[0]
    assert cmd == [*QUERY, "--id=0"]
    assert "--query-gpu=utilization.gpu" in cmd
    assert "--format=csv,noheader,nounits" in cmd
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 5.0


def test_samples_keep_the_raw_text_and_the_time_since_start():
    sampler = GpuUtilSampler(run=FakeSmi(["37\n"]), clock=_clock([100.0, 100.5]))
    assert sampler.sample_once() == {"t_s": 0.5, "raw": "37", "util_pct": 37.0}


def test_the_run_summary_is_the_median_as_a_fraction():
    sampler = GpuUtilSampler(run=FakeSmi(["10", "90", "50"]))
    for _ in range(3):
        sampler.sample_once()
    assert sampler.median_fraction() == pytest.approx(0.5)


@pytest.mark.parametrize("raw", ["[N/A]", "137", "40\n41"])
def test_an_unreadable_sample_is_kept_but_never_counted(raw):
    sampler = GpuUtilSampler(run=FakeSmi([raw, "80"]))
    bad = sampler.sample_once()
    sampler.sample_once()
    assert bad["util_pct"] is None
    assert "error" in bad
    assert sampler.median_fraction() == pytest.approx(0.8)
    assert sampler.summary()["n_valid"] == 1
    assert sampler.summary()["n_samples"] == 2


def test_a_failing_nvidia_smi_is_a_sample_with_an_error_not_a_raise():
    def run(cmd, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    sampler = GpuUtilSampler(run=run)
    sample = sampler.sample_once()
    assert sample["util_pct"] is None
    assert "FileNotFoundError" in sample["error"]
    assert sampler.median_fraction() is None


def test_a_nonzero_exit_is_recorded_with_its_stderr():
    sampler = GpuUtilSampler(run=FakeSmi(["50"], returncode=9))
    assert sampler.sample_once()["error"] == "exit 9: boom"


def test_the_thread_samples_from_entry_and_stops_at_exit():
    smi = FakeSmi(["42"])
    with GpuUtilSampler(interval=0.01, run=smi) as sampler:
        time.sleep(0.2)
    calls_at_exit = len(smi.calls)
    time.sleep(0.1)
    assert calls_at_exit >= 2
    assert len(smi.calls) == calls_at_exit, "sampling continued after the run ended"
    assert sampler.summary()["gpu_util"] == pytest.approx(0.42)
    assert len(sampler.summary()["samples"]) == calls_at_exit


def test_a_run_shorter_than_one_interval_still_gets_a_sample():
    with GpuUtilSampler(interval=60.0, run=FakeSmi(["70"])) as sampler:
        pass
    assert sampler.summary()["n_valid"] == 1
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_gpu_util.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.gpu_util'`.

- [ ] **Step 3: Create `harness/gpu_util.py`**

```python
"""GPU utilisation, sampled from nvidia-smi while a bench run is in flight.

Owner decision 3 (2026-10-04): `utilization.gpu` every 0.5 s in a background
thread for the duration of each run; per run, the median as a fraction 0-1;
the raw samples kept with the run.

Why nvidia-smi: it is already in the image (worker/handler.py reads the GPU
name with it) and needs no new dependency. NVML bindings (pynvml) were
rejected as a new package in an image whose pip state artifact 1 pinned, and
vLLM's `/metrics` exports KV-cache usage, which is a memory fraction, not
compute. `utilization.gpu` is the share of the sample period in which at
least one kernel ran. It saturates well before throughput does -- the
censoring artifact 2's H2 is about -- so it is reported as read and never
rescaled.

Why the median: one run's samples include the ramp at its start and the
drain at its end. The median is the steady middle; a mean would be pulled by
the edges, and artifact 1's rule is that a mean is never published for skewed
data.
"""

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Self

from harness.stats import median

QUERY = ("nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits")
DEFAULT_INTERVAL_S = 0.5
QUERY_TIMEOUT_S = 5.0


def _parse_percent(raw: str) -> tuple[float | None, str | None]:
    lines = raw.splitlines()
    if len(lines) != 1:
        return None, f"expected one line for one GPU, got {len(lines)}"
    try:
        value = float(lines[0])
    except ValueError:
        return None, f"not a number: {lines[0]!r}"
    if not 0.0 <= value <= 100.0:
        return None, f"outside 0-100: {value!r}"
    return value, None


class GpuUtilSampler:
    """Samples one GPU's utilisation on a background thread while in a `with`.

    The first sample is taken as the block is entered, so even a run shorter
    than one interval gets a reading. A query that fails, times out or prints
    something unparseable becomes a sample with `util_pct` None and an
    `error`, kept with the raw text: an unreadable GPU must never be the
    reason a measured run is thrown away, and a gap must never be filled with
    an invented number.
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL_S,
        *,
        gpu_index: int = 0,
        run: Callable = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.interval = interval
        self.samples: list[dict] = []
        self._cmd = [*QUERY, f"--id={gpu_index}"]
        self._run = run
        self._clock = clock
        self._t0 = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def command(self) -> list[str]:
        return list(self._cmd)

    def sample_once(self) -> dict:
        t = self._clock() - self._t0
        try:
            proc = self._run(
                self._cmd, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_S
            )
            raw = (proc.stdout or "").strip()
            if proc.returncode == 0:
                util, error = _parse_percent(raw)
            else:
                util, error = None, f"exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        except Exception as e:  # noqa: BLE001 -- see the class docstring
            raw, util, error = "", None, repr(e)[:200]
        sample = {"t_s": t, "raw": raw, "util_pct": util}
        if error is not None:
            sample["error"] = error
        self.samples.append(sample)
        return sample

    def _loop(self) -> None:
        while True:
            self.sample_once()
            if self._stop.wait(self.interval):
                return

    def __enter__(self) -> Self:
        self._t0 = self._clock()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + QUERY_TIMEOUT_S + 1.0)

    def median_fraction(self) -> float | None:
        """Median of the readable samples, as a fraction; None if there are none."""
        values = [s["util_pct"] for s in self.samples if s["util_pct"] is not None]
        if not values:
            return None
        return median(values) / 100.0

    def summary(self) -> dict:
        return {
            "gpu_util": self.median_fraction(),
            "interval_s": self.interval,
            "n_samples": len(self.samples),
            "n_valid": sum(1 for s in self.samples if s["util_pct"] is not None),
            "samples": list(self.samples),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_gpu_util.py -q`
Expected: 10 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/gpu_util.py tests/test_harness_gpu_util.py
git add harness/gpu_util.py tests/test_harness_gpu_util.py
git commit -m "feat: harness.gpu_util -- nvidia-smi utilisation sampled during a bench run"
```

---

## Task 8: One sweep run inside the worker

Everything between "the engine is healthy" and "here is the run's summary". Four pieces, each decided above:

- **The prompt path** (owner decision 4). `choose_prompt_path` writes artifact 1's prompt to a one-line JSONL file, sends it once through bench's custom dataset, and keeps the exact path only if the engine's own prompt-token count for that request equals `/tokenize`'s count. Otherwise it falls back to random prompts of the same length and keeps the reason. The test pins the file's bytes and both flag lists exactly.
- **The failure rule and the latency.** `successful_requests` applies amendment §3f's rule and reconstructs each request's end-to-end latency as `ttft + sum(itls)`, which equals the tool's own per-request `latency` for the completions endpoint (verified table above). The tool's counts are a cross-check.
- **The summary.** Compact: no per-request arrays. The tool's scalar fields ride along; its `median_e2el_ms` is kept as a cross-check, never used.
- **`max_num_seqs`**, read from the engine log, never assumed (`docs/recon-a2.md` Q3).

**Files:**
- Create: `harness/sweep_worker.py`, `tests/test_harness_sweep_worker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_sweep_worker.py`:

```python
"""One sweep run inside the worker, with the bench and the sampler faked."""

import json

import pytest

from harness.bench import BenchError
from harness.sweep_worker import (
    E2EL_PERCENTILES,
    PROMPT_EXACT,
    PROMPT_RANDOM_FALLBACK,
    WARMUP_SEED_OFFSET,
    PromptPlan,
    choose_prompt_path,
    exact_dataset_args,
    max_num_seqs_from_log,
    random_dataset_args,
    run_one,
    run_summary,
    successful_requests,
    write_exact_prompt_dataset,
)

PROMPT = "Explain what a key-value cache does, in two sentences."
URL = "http://127.0.0.1:8000"


def raw_result(n=4, *, ttft=0.1, itl=0.02, out=16, duration=2.0, **over):
    raw = {
        "duration": duration,
        "completed": n,
        "failed": 0,
        "num_prompts": n,
        "max_concurrency": 2,
        "output_throughput": n * out / duration,
        "input_lens": [13] * n,
        "ttfts": [ttft] * n,
        "itls": [[itl] * (out - 1)] * n,
        "output_lens": [out] * n,
        "errors": [""] * n,
        "generated_texts": ["x"] * n,
        "start_times": [0.0] * n,
        "median_e2el_ms": (ttft + itl * (out - 1)) * 1000,
    }
    raw.update(over)
    return raw


class FakeBench:
    def __init__(self, results=None, fail=None):
        self.calls = []
        self.results = results or {}
        self.fail = fail or {}

    def __call__(self, base_url, **kw):
        self.calls.append(kw)
        name = kw["result_dir"].name
        if name in self.fail:
            raise BenchError(self.fail[name])
        return self.results.get(name, raw_result())


class FakeSampler:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        self.log.append("enter")
        return self

    def __exit__(self, *exc):
        self.log.append("exit")

    def summary(self):
        return {"gpu_util": 0.6, "n_samples": 3, "n_valid": 3, "interval_s": 0.5, "samples": []}


PLAN = PromptPlan(PROMPT_EXACT, ("--dataset-name", "custom"), 13)


def test_the_exact_prompt_file_is_pinned_byte_for_byte(tmp_path):
    path = write_exact_prompt_dataset(PROMPT, tmp_path)
    assert path.read_bytes() == (
        b'{"prompt": "Explain what a key-value cache does, in two sentences."}\n'
    )


def test_the_exact_prompt_flags_are_pinned():
    assert exact_dataset_args("/w/prompt.jsonl", output_len=16) == [
        "--dataset-name", "custom",
        "--dataset-path", "/w/prompt.jsonl",
        "--custom-output-len", "16",
        "--skip-chat-template",
    ]


def test_the_fallback_flags_are_pinned():
    assert random_dataset_args(input_len=13, output_len=16) == [
        "--dataset-name", "random",
        "--random-input-len", "13",
        "--random-output-len", "16",
        "--random-range-ratio", "0",
        "--random-prefix-len", "0",
    ]


def test_a_probe_the_engine_received_at_the_right_length_keeps_the_exact_path(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1)})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_EXACT
    assert plan.prompt_tokens == 13
    assert list(plan.dataset_args) == exact_dataset_args(tmp_path / "prompt.jsonl", output_len=16)
    probe = bench.calls[0]
    assert (probe["num_prompts"], probe["max_concurrency"]) == (1, 1)


def test_a_failing_probe_falls_back_to_random_at_the_same_length(tmp_path):
    bench = FakeBench(fail={"prompt-probe": "exited 1: pandas is not installed"})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK
    assert list(plan.dataset_args) == random_dataset_args(input_len=13, output_len=16)
    assert "pandas" in plan.probe_error


def test_a_probe_whose_prompt_arrived_at_another_length_falls_back(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1, input_lens=[27])})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK
    assert "[27]" in plan.probe_error


def test_the_failure_rule_drops_errors_zero_ttfts_and_empty_outputs():
    raw = raw_result(5)
    raw["errors"][1] = "boom"
    raw["ttfts"] = [0.1, 0.1, 0.0, 0.1, 0.1]
    raw["output_lens"] = [16, 16, 16, 0, 16]
    raw.update(completed=2, failed=3)
    ok = successful_requests(raw)
    assert ok["n_failed"] == 3
    assert ok["e2e_s"] == pytest.approx([0.1 + 0.02 * 15] * 2)


def test_a_disagreement_with_the_tools_own_counts_is_refused():
    raw = raw_result(4)
    raw["errors"][0] = "boom"
    with pytest.raises(ValueError, match="miscounting"):
        successful_requests(raw)


def test_a_result_saved_without_detail_is_refused():
    raw = raw_result(2)
    del raw["itls"]
    with pytest.raises(ValueError, match="save-detailed"):
        successful_requests(raw)


def test_the_summary_is_compact_and_carries_the_three_curve_values():
    plan = PromptPlan(PROMPT_EXACT, ("--dataset-name", "custom"), 13)
    gpu = {"gpu_util": 0.6, "samples": [{"t_s": 0.0, "raw": "60", "util_pct": 60.0}]}
    s = run_summary(raw_result(4, ttft=0.1, itl=0.02, out=16, duration=2.0), gpu=gpu, plan=plan,
                    warmup=None)
    assert s["latency_s"] == pytest.approx(0.1 + 0.02 * 15)
    assert s["ttft_median_s"] == pytest.approx(0.1)
    assert s["throughput_tps"] == pytest.approx(4 * 16 / 2.0)
    assert s["gpu_util"] == 0.6
    assert s["prompt_path"] == PROMPT_EXACT
    assert s["bench_median_e2el_s"] == pytest.approx(s["latency_s"])
    assert s["input_lens_unique"] == [13]
    assert "ttfts" not in s and "ttfts" not in s["bench_scalars"]
    assert s["bench_scalars"]["output_throughput"] == pytest.approx(32.0)
    json.dumps(s)


def test_a_run_where_nothing_succeeded_is_refused():
    raw = raw_result(3)
    raw["ttfts"] = [0.0] * 3
    raw.update(completed=0, failed=3)
    with pytest.raises(ValueError, match="no request succeeded"):
        run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None)


def test_error_samples_are_deduplicated_and_capped_at_three():
    raw = raw_result(6)
    raw["errors"] = ["", "e1", "e1", "e2", "e3", "e4"]
    raw["ttfts"][1:] = [0.0] * 5
    raw.update(completed=1, failed=5)
    s = run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None)
    assert s["error_samples"] == ["e1", "e2", "e3"]


def test_one_run_warms_up_then_measures_with_the_sampler_around_the_measurement_only(tmp_path):
    log = []
    bench = FakeBench()

    def recording_bench(base_url, **kw):
        log.append(kw["result_dir"].name)
        return bench(base_url, **kw)

    s = run_one(
        URL, model="m", level=8, num_prompts=160, warmup_prompts=8, plan=PLAN, seed=11,
        workdir=tmp_path, run_bench=recording_bench, sampler_factory=lambda: FakeSampler(log),
    )
    assert log == ["warmup", "enter", "measured", "exit"]
    warm, measured = bench.calls
    assert warm["max_concurrency"] == measured["max_concurrency"] == 8
    assert (warm["num_prompts"], measured["num_prompts"]) == (8, 160)
    assert warm["seed"] == 11 + WARMUP_SEED_OFFSET and measured["seed"] == 11
    assert measured["extra_args"] == list(E2EL_PERCENTILES)
    assert "extra_args" not in warm
    assert measured["ignore_eos"] is True
    assert s["warmup"] == {"num_prompts": 8, "completed": 4, "failed": 0}
    assert s["gpu_util"] == 0.6


def test_the_raw_bench_json_is_kept_only_when_asked_for(tmp_path):
    bench = FakeBench()
    kw = {"model": "m", "level": 2, "num_prompts": 100, "warmup_prompts": 0, "plan": PLAN,
          "seed": 1, "run_bench": bench, "sampler_factory": lambda: FakeSampler([])}
    assert "raw_bench" not in run_one(URL, workdir=tmp_path / "a", **kw)
    kept = run_one(URL, workdir=tmp_path / "b", keep_raw=True, **kw)
    assert kept["raw_bench"] == raw_result()


def test_no_warmup_when_none_is_asked_for(tmp_path):
    bench = FakeBench()
    s = run_one(
        URL, model="m", level=2, num_prompts=100, warmup_prompts=0, plan=PLAN, seed=1,
        workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
    )
    assert len(bench.calls) == 1
    assert s["warmup"] is None


def test_a_spent_budget_refuses_to_start_a_bench_run(tmp_path):
    bench = FakeBench()
    with pytest.raises(BenchError, match="budget is spent"):
        run_one(
            URL, model="m", level=2, num_prompts=100, warmup_prompts=2, plan=PLAN, seed=1,
            workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
            deadline=10.0, clock=lambda: 11.0,
        )
    assert bench.calls == []


NON_DEFAULT = (
    "(APIServer pid=130) INFO 08-28 23:28:00 [api_utils.py:273] non-default args: "
    "{'model_tag': 'Qwen/Qwen3-8B', 'model': 'Qwen/Qwen3-8B', 'max_model_len': 8192, "
    "'max_num_seqs': 256}"
)
DEFAULTED = "DEBUG 10-04 [arg_utils.py:2797] Defaulting max_num_seqs to 256 for openai-api-server"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([NON_DEFAULT], (256, "non-default-args")),
        ([DEFAULTED], (256, "debug-default")),
        ([DEFAULTED.replace("256", "128"), NON_DEFAULT], (256, "non-default-args")),
        (["INFO GPU KV cache size: 35,792 tokens"], (None, None)),
    ],
)
def test_max_num_seqs_is_read_from_the_log_and_never_assumed(lines, expected):
    assert max_num_seqs_from_log(lines) == expected
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_sweep_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.sweep_worker'`.

- [ ] **Step 3: Create `harness/sweep_worker.py`**

```python
"""One run of the service-curve sweep, inside the worker.

Everything between "the engine is healthy" and "here is the run's summary":
decide how artifact 1's prompt reaches the engine, warm the engine for one
wave, run one measured `vllm bench serve` at the level's concurrency with the
GPU sampler running, and reduce the tool's saved JSON to a compact summary.
The engine lifecycle (`harness.serve`) and the job plumbing
(`worker/sweep_handler.py`) are not here, so this file can be tested with a
fake bench and a fake sampler and nothing else.

Split from `harness/service_sweep.py`, which holds the local side (schedule,
payload, record, reduction), because the two halves run on different
machines and change for different reasons.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from harness.bench import BenchError
from harness.stats import median

PROMPT_EXACT = "exact"
PROMPT_RANDOM_FALLBACK = "random-fallback"
DATASET_FILENAME = "prompt.jsonl"
# Asks the tool to also report its own end-to-end latency percentiles. Not
# used for the curve -- see run_summary -- only recorded beside it, so the
# first paid run can confirm the reconstruction agrees with the tool.
E2EL_PERCENTILES = ("--percentile-metrics", "ttft,tpot,itl,e2el")
# Warm-up requests draw from a different seed than the measured run, so a
# random-fallback warm-up cannot leave the measured prompts in the prefix cache.
WARMUP_SEED_OFFSET = 500_000
_ERROR_SAMPLES = 3
_ERROR_CHARS = 300
_PER_REQUEST = ("ttfts", "itls", "output_lens", "errors")


def write_exact_prompt_dataset(prompt: str, directory) -> Path:
    """One JSONL line holding the prompt, in the custom dataset's format.

    One line rather than `num_prompts` copies: vLLM 0.27.1's custom dataset
    oversamples a short file up to `--num-prompts` with fresh request ids
    (`BenchmarkDataset.maybe_oversample_requests`), so every request carries
    the same text either way, and the file stays the same for every level.
    """
    path = Path(directory) / DATASET_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"prompt": prompt}) + "\n")
    return path


def exact_dataset_args(dataset_path, *, output_len: int) -> list[str]:
    """Bench flags that send the dataset file's prompt verbatim.

    `--skip-chat-template` because artifact 1's probe posts the raw prompt to
    `/v1/completions`; the custom dataset would otherwise wrap it in the
    model's chat template and send a different, longer prompt.
    """
    return [
        "--dataset-name", "custom",
        "--dataset-path", str(dataset_path),
        "--custom-output-len", str(output_len),
        "--skip-chat-template",
    ]


def random_dataset_args(*, input_len: int, output_len: int) -> list[str]:
    """Random prompts of exactly `input_len` tokens: range ratio 0, no prefix."""
    return [
        "--dataset-name", "random",
        "--random-input-len", str(input_len),
        "--random-output-len", str(output_len),
        "--random-range-ratio", "0",
        "--random-prefix-len", "0",
    ]


@dataclass(frozen=True)
class PromptPlan:
    """How this run's requests are built, and why.

    `path` is PROMPT_EXACT or PROMPT_RANDOM_FALLBACK and is stored with every
    run (owner decision 4): a curve measured on random prompts of the right
    length is a different measurement from one on the exact prompt, and a
    reader has to be able to tell which one they are looking at.
    """

    path: str
    dataset_args: tuple[str, ...]
    prompt_tokens: int
    probe_error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dataset_args"] = list(self.dataset_args)
        return d


def choose_prompt_path(
    base_url: str,
    *,
    model: str,
    prompt: str,
    output_len: int,
    workdir,
    run_bench: Callable,
    count_tokens: Callable[[str], int],
) -> PromptPlan:
    """Try the exact prompt once; fall back to random prompts of its length.

    The probe is one request at concurrency 1. It passes only if the tool
    completed it AND the engine's own prompt-token count for it (the tool
    copies `usage.prompt_tokens` into `input_lens`) equals the server's
    `/tokenize` count of the prompt -- so "exact" means the engine received a
    prompt of exactly that length, not merely that the tool ran. Anything else
    -- the tool failing (a missing `pandas`, which the custom dataset needs, is
    the expected cause), or a length mismatch -- falls back to the random
    dataset at the `/tokenize` length, with the reason kept.

    Decided per job, because each job is a fresh engine and nothing carries
    between jobs. Deciding once on the local machine was rejected: it cannot
    run the pinned image's tool. `service_sweep.reduce_curve` refuses a store
    whose runs took different paths, so a campaign cannot mix them silently.
    """
    workdir = Path(workdir)
    tokens = count_tokens(prompt)
    exact_args = exact_dataset_args(
        write_exact_prompt_dataset(prompt, workdir), output_len=output_len
    )
    try:
        raw = run_bench(
            base_url,
            model=model,
            max_concurrency=1,
            num_prompts=1,
            dataset_args=exact_args,
            ignore_eos=True,
            seed=0,
            result_dir=workdir / "prompt-probe",
        )
    except BenchError as e:
        error = str(e)[-2000:]
    else:
        lens = raw.get("input_lens")
        if raw.get("completed") == 1 and lens == [tokens]:
            return PromptPlan(PROMPT_EXACT, tuple(exact_args), tokens)
        error = (
            f"probe completed={raw.get('completed')!r} with input_lens={lens!r}; "
            f"expected 1 completed request of {tokens} prompt tokens"
        )
    return PromptPlan(
        PROMPT_RANDOM_FALLBACK,
        tuple(random_dataset_args(input_len=tokens, output_len=output_len)),
        tokens,
        error,
    )


def successful_requests(raw: dict) -> dict:
    """Apply amendment §3f's failure rule to the tool's per-request arrays.

    A request failed if its `errors` entry is non-empty, OR its TTFT is 0.0,
    OR its output length is 0: in vLLM 0.27.1 some failure paths leave the
    error string empty and no success flag is saved. The result is then
    cross-checked against the tool's own `completed` and `failed` counts.

    End-to-end latency per request is reconstructed as `ttft + sum(itls)`.
    `--save-detailed` saves no per-request end-to-end latency, and for the
    completions endpoint the tool's own `latency` is the last chunk's time
    minus the start time, which is exactly the first chunk's time plus every
    gap after it (`async_request_openai_completions` in
    vllm/benchmarks/lib/endpoint_request_func.py, v0.27.1).
    """
    missing = [k for k in ("duration", "completed", "failed", *_PER_REQUEST) if k not in raw]
    if missing:
        raise ValueError(
            f"bench result lacks {missing}; without --save-detailed's per-request "
            "arrays no latency can be computed, and the run would be stored with none"
        )
    lengths = {k: len(raw[k]) for k in _PER_REQUEST}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            f"per-request arrays differ in length {lengths}; pairing them by index "
            "would attribute one request's timing to another"
        )
    e2e, ttft, out = [], [], []
    failed = 0
    for err, t, itl, n in zip(
        raw["errors"], raw["ttfts"], raw["itls"], raw["output_lens"], strict=True
    ):
        if err or t == 0.0 or n == 0:
            failed += 1
            continue
        e2e.append(t + sum(itl))
        ttft.append(t)
        out.append(n)
    if len(e2e) != raw["completed"] or failed != raw["failed"]:
        raise ValueError(
            f"the failure rule finds {len(e2e)} successful and {failed} failed requests, "
            f"but the tool counted completed={raw['completed']} failed={raw['failed']}; "
            "one of them is miscounting, and a latency from the wrong population "
            "would be stored as this level's"
        )
    return {"e2e_s": e2e, "ttft_s": ttft, "output_lens": out, "n_failed": failed}


def run_summary(raw: dict, *, gpu: dict, plan: PromptPlan, warmup: dict | None) -> dict:
    """The compact per-run summary the worker returns: no per-request arrays.

    `latency_s` is the median end-to-end latency of the successful requests,
    reconstructed per request (see `successful_requests`). The tool's own
    `median_e2el_ms` is recorded as `bench_median_e2el_s` and not used:
    artifact 5's rule is to compute statistics from the raw arrays under one
    failure rule, and the sweep keeps the same rule so the two artifacts'
    latencies mean the same thing.

    `throughput_tps` is output tokens per second: successful output lengths
    summed over the tool's measured duration.
    """
    ok = successful_requests(raw)
    if not ok["e2e_s"]:
        raise ValueError(
            f"no request succeeded ({raw['failed']} failed); this run has no latency, "
            "and storing it as ok would put a point on the curve that was never measured"
        )
    if not raw["duration"] > 0:
        raise ValueError(
            f"bench duration is {raw['duration']!r}; throughput would divide by it"
        )
    bench_e2el = raw.get("median_e2el_ms")
    errors = [e for e in raw["errors"] if e]
    return {
        "latency_s": median(ok["e2e_s"]),
        "ttft_median_s": median(ok["ttft_s"]),
        "throughput_tps": sum(ok["output_lens"]) / raw["duration"],
        "gpu_util": gpu["gpu_util"],
        "prompt_path": plan.path,
        "bench_median_e2el_s": None if bench_e2el is None else bench_e2el / 1000.0,
        "completed": raw["completed"],
        "failed": raw["failed"],
        "duration_s": raw["duration"],
        "input_lens_unique": sorted(set(raw.get("input_lens") or [])),
        "error_samples": list(dict.fromkeys(e[:_ERROR_CHARS] for e in errors))[:_ERROR_SAMPLES],
        "bench_scalars": {k: v for k, v in raw.items() if not isinstance(v, (list, dict))},
        "gpu": gpu,
        "prompt": plan.to_dict(),
        "warmup": warmup,
    }


def _remaining(deadline: float | None, clock: Callable[[], float]) -> float | None:
    if deadline is None:
        return None
    left = deadline - clock()
    if left <= 0:
        raise BenchError(
            "the job's time budget is spent; another bench run would be killed by "
            "the platform's execution timeout, and the job would return nothing"
        )
    return left


def run_one(
    base_url: str,
    *,
    model: str,
    level: int,
    num_prompts: int,
    warmup_prompts: int,
    plan: PromptPlan,
    seed: int,
    workdir,
    run_bench: Callable,
    sampler_factory: Callable,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    keep_raw: bool = False,
) -> dict:
    """Warm up, then one measured run at concurrency `level`.

    The warm-up is `warmup_prompts` requests at the same concurrency, results
    discarded but their counts kept. vLLM captures CUDA graphs at startup, so
    the first wave's extra cost is small, but it is not zero, and a sweep
    point's median should not carry it. The GPU sampler runs around the
    measured run only, so the warm-up never reaches the utilisation median.

    `keep_raw` adds the tool's saved JSON, unaltered, as `raw_bench`. Only the
    first paid run's diagnostic jobs ask for it, to check the saved keys
    against what this module reads; every other job stays compact.
    """
    workdir = Path(workdir)
    common = {
        "model": model,
        "max_concurrency": level,
        "dataset_args": list(plan.dataset_args),
        "ignore_eos": True,
    }
    warmup = None
    if warmup_prompts:
        warm = run_bench(
            base_url,
            **common,
            num_prompts=warmup_prompts,
            seed=seed + WARMUP_SEED_OFFSET,
            result_dir=workdir / "warmup",
            timeout=_remaining(deadline, clock),
        )
        warmup = {
            "num_prompts": warmup_prompts,
            "completed": warm.get("completed"),
            "failed": warm.get("failed"),
        }
    with sampler_factory() as sampler:
        raw = run_bench(
            base_url,
            **common,
            num_prompts=num_prompts,
            seed=seed,
            result_dir=workdir / "measured",
            extra_args=list(E2EL_PERCENTILES),
            timeout=_remaining(deadline, clock),
        )
    summary = run_summary(raw, gpu=sampler.summary(), plan=plan, warmup=warmup)
    if keep_raw:
        summary["raw_bench"] = raw
    return summary


# vLLM logs its explicitly-set engine arguments at INFO ("non-default args:
# {...}", fixtures/vllm_logs/startup_0.log line 7) and the max_num_seqs it
# defaulted to only at DEBUG ("Defaulting max_num_seqs to %d for %s usage
# context.", vllm/engine/arg_utils.py, v0.27.1). docs/recon-a2.md records that
# the value is absent from the captured log; the sweep must record it.
_MAX_NUM_SEQS_SET = re.compile(r"non-default args: .*'max_num_seqs': (?P<n>\d+)")
_MAX_NUM_SEQS_DEFAULTED = re.compile(r"Defaulting max_num_seqs to (?P<n>\d+)")


def max_num_seqs_from_log(lines: Sequence[str]) -> tuple[int | None, str | None]:
    """The engine's max_num_seqs and where it was read, or (None, None).

    An explicitly passed value wins over a logged default. Absence is
    returned as None, never as vLLM's documented default: the default depends
    on the GPU's memory and the usage context, and reporting a value the log
    did not show is the assumption recon-a2 says the sweep must not inherit.
    """
    for pattern, source in (
        (_MAX_NUM_SEQS_SET, "non-default-args"),
        (_MAX_NUM_SEQS_DEFAULTED, "debug-default"),
    ):
        for line in lines:
            m = pattern.search(line)
            if m:
                return int(m.group("n")), source
    return None, None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_sweep_worker.py -q`
Expected: 20 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/sweep_worker.py tests/test_harness_sweep_worker.py
git add harness/sweep_worker.py tests/test_harness_sweep_worker.py
git commit -m "feat: one service-sweep run in the worker -- exact prompt or recorded fallback"
```

---

## Task 9: The sweep's local side — schedule, payload, record, curve

`harness/service_sweep.py` is what the local driver needs. The schedule is `harness.scheduler.build_schedule` over conditions `c<level>` with `blocks=repeats`: every level once per block, shuffled within the block by the seed, which is owner decision 2 exactly. `build_sweep_record` is the `build_record` callback for `harness.campaign.run_campaign`. `reduce_curve` turns stored runs into one row per level — median of the run medians, min–max interval — and refuses, with a reason, every store that would not give one replica's curve. It emits plain tuples and never imports `autoscale`.

**Files:**
- Create: `harness/service_sweep.py`, `tests/test_harness_service_sweep.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_service_sweep.py`:

```python
"""The sweep's local side: schedule, payload, record, and the curve reduction."""

import json

import pytest

from harness.scheduler import ScheduledRun
from harness.service_sweep import (
    STATISTIC,
    SweepRun,
    build_sweep_record,
    condition_for,
    job_payload,
    level_of,
    num_prompts_for,
    reduce_curve,
    sweep_schedule,
    validate_levels,
)
from harness.submit import UNHEALTHY_ERROR, SubmitOutcome

CLOCK_A = {"t_submit": 0.0, "t_result": 9.0}


def test_conditions_round_trip_and_reject_anything_else():
    assert condition_for(16) == "c16"
    assert level_of("c16") == 16
    with pytest.raises(ValueError, match="not a sweep level"):
        level_of("A")


@pytest.mark.parametrize(
    ("levels", "match"),
    [([1], "at least two"), ([2, 1], "ascending"), ([1, 1, 2], "ascending"),
     ([0, 4], "positive integer"), ([1, True], "positive integer"), ([1, 2.5], "positive")],
)
def test_bad_levels_are_refused_before_anything_is_spent(levels, match):
    with pytest.raises(ValueError, match=match):
        validate_levels(levels)


def test_three_repeats_per_level_interleaved_by_seed():
    levels = [1, 2, 4, 8, 16, 32, 64]
    schedule = sweep_schedule(levels, seed=20261004)
    assert len(schedule) == 3 * len(levels)
    for block in range(3):
        in_block = [s for s in schedule if s.block_index == block]
        assert sorted(level_of(s.condition) for s in in_block) == levels
    for level in levels:
        idx = [s.run_index for s in schedule if s.condition == condition_for(level)]
        assert idx != list(range(idx[0], idx[0] + 3)), f"all repeats of {level} back to back"
    assert sweep_schedule(levels, seed=20261004) == schedule
    assert sweep_schedule(levels, seed=1) != schedule


def test_prompts_scale_with_the_level_above_a_floor():
    assert num_prompts_for(1) == 100
    assert num_prompts_for(8) == 160
    assert num_prompts_for(64) == 1280
    assert num_prompts_for(4, waves=10, minimum=5) == 40


def test_the_job_payload_carries_one_level_and_repeat():
    p = job_payload(
        ScheduledRun(5, 1, "c8"), "rid", serve_args=["--max-num-seqs", "256"],
        output_len=16, job_budget_s=1800, seed=100,
    )
    assert p == {
        "run_id": "rid", "run_index": 5, "level": 8, "repeat": 1,
        "serve_args": ["--max-num-seqs", "256"], "num_prompts": 160, "warmup_prompts": 8,
        "output_len": 16, "job_budget_s": 1800, "seed": 105, "diagnostics": False,
    }
    json.dumps(p)


def _summary(latency=0.5, util=0.4, path="exact"):
    return {
        "latency_s": latency, "ttft_median_s": 0.05, "throughput_tps": 32.0,
        "gpu_util": util, "prompt_path": path, "completed": 100, "failed": 0,
    }


def _ok_output(run_id="rid", level=8, run=None, **over):
    out = {
        "healthy": True, "run_id": run_id, "level": level, "repeat": 0,
        "run": _summary() if run is None else run, "run_error": None,
        "served_cmd": ["vllm", "serve", "m", "--port", "8000"],
        "engine": {"max_num_seqs": 256, "kv_capacity_tokens": 35792},
        "log_lines": ["INFO GPU KV cache size: 35,792 tokens"],
        "host": {"host_id": "w1"}, "clock_C": {"delay_ms": 10},
    }
    out.update(over)
    return out


def test_an_ok_job_becomes_an_ok_record_with_the_curve_fields_on_top():
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(), error=None),
    )
    assert (rec.outcome, rec.level, rec.repeat, rec.run_index) == ("ok", 8, 1, 5)
    assert (rec.latency_s, rec.throughput_tps, rec.gpu_util) == (0.5, 32.0, 0.4)
    assert rec.prompt_path == "exact"
    assert rec.engine["max_num_seqs"] == 256
    assert rec.engine["log_lines"] == ["INFO GPU KV cache size: 35,792 tokens"]
    assert rec.clock_C == {"delay_ms": 10}
    assert SweepRun.from_dict(json.loads(json.dumps(rec.to_dict()))) == rec


def test_diagnostics_are_carried_into_the_record_when_the_worker_sends_them():
    out = _ok_output(diagnostics={"pandas_importable": False})
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.diagnostics == {"pandas_importable": False}


def test_an_unhealthy_engine_is_a_failed_record_that_keeps_its_log():
    diag = {"healthy": False, "log_lines": ["CUDA out of memory"], "served_cmd": ["vllm"]}
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c1"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=None, error=UNHEALTHY_ERROR, diagnostics=diag),
    )
    assert rec.outcome == "failed"
    assert rec.status["failure_class"] == "health_timeout"
    assert rec.engine["log_lines"] == ["CUDA out of memory"]
    assert rec.latency_s is None


def test_a_failed_measurement_on_a_healthy_engine_is_a_failed_record():
    out = _ok_output(level=1, run=None)
    out["run"] = None
    out["run_error"] = "BenchError: vllm bench serve exited 1"
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c1"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.outcome == "failed"
    assert "exited 1" in rec.status["failure_detail"]
    assert rec.engine["log_lines"]


def test_an_answer_for_another_run_is_refused():
    with pytest.raises(ValueError, match="another run"):
        build_sweep_record(
            ScheduledRun(0, 0, "c8"), "rid",
            SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(run_id="other"), error=None),
        )


def _rec(level, repeat, *, latency=0.5, tps=32.0, util=0.4, path="exact", outcome="ok",
         cmd=("vllm", "serve", "m"), mns=256):
    ok = outcome == "ok"
    return SweepRun(
        run_id=f"r{level}-{repeat}", run_index=0, condition=condition_for(level), level=level,
        repeat=repeat, outcome=outcome,
        latency_s=latency if ok else None, ttft_median_s=0.05 if ok else None,
        throughput_tps=tps if ok else None, gpu_util=util if ok else None,
        prompt_path=path if ok else None, served_cmd=list(cmd),
        engine={"max_num_seqs": mns, "kv_capacity_tokens": 35792},
    )


def _three(level, latencies, **kw):
    return [_rec(level, i, latency=lat, **kw) for i, lat in enumerate(latencies)]


def test_each_level_is_the_median_of_its_run_medians_with_the_min_max_interval():
    records = _three(1, [0.31, 0.30, 0.35], util=0.2) + _three(4, [0.40, 0.38, 0.39], util=0.6)
    red = reduce_curve(records)
    assert red.points == [(1, 0.31, 32.0, 0.2), (4, 0.39, 32.0, 0.6)]
    assert red.levels[0]["latency_s_range"] == [0.30, 0.35]
    assert red.levels[1]["n_runs"] == 3
    doc = red.to_dict()
    assert doc["statistic"] == STATISTIC
    assert doc["points"] == [[1, 0.31, 32.0, 0.2], [4, 0.39, 32.0, 0.6]]
    assert doc["engine"]["max_num_seqs"] == [256]
    json.dumps(doc)


def test_failed_runs_are_counted_and_left_out_of_the_statistics():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3) + [_rec(2, 3, outcome="failed")]
    red = reduce_curve(records)
    assert red.levels[1]["n_failed"] == 1
    assert red.levels[1]["n_runs"] == 3


def test_a_level_short_of_its_repeats_is_refused_unless_the_caller_lowers_the_bar():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 2)
    with pytest.raises(ValueError, match="level 2 has 2 successful runs"):
        reduce_curve(records)
    assert reduce_curve(records, min_repeats=2).levels[1]["n_runs"] == 2


def test_mixed_prompt_paths_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, path="random-fallback")
    with pytest.raises(ValueError, match="prompt paths"):
        reduce_curve(records)


def test_mixed_serve_commands_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, cmd=("vllm", "serve", "other"))
    with pytest.raises(ValueError, match="serve commands"):
        reduce_curve(records)


def test_a_missing_utilisation_is_refused_rather_than_invented():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3)
    records[0].gpu_util = None
    with pytest.raises(ValueError, match="utilisation"):
        reduce_curve(records)


def test_two_campaigns_in_one_store_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3) + [_rec(1, 0)]
    with pytest.raises(ValueError, match="more than one campaign"):
        reduce_curve(records)


def test_a_requested_level_with_no_runs_is_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3)
    with pytest.raises(ValueError, match=r"levels \[4\]"):
        reduce_curve(records, expected_levels=[1, 2, 4])


def test_a_single_level_or_an_empty_store_is_refused():
    with pytest.raises(ValueError, match="no successful run"):
        reduce_curve([])
    with pytest.raises(ValueError, match="at least two"):
        reduce_curve(_three(1, [0.3] * 3))


def test_engine_facts_report_every_distinct_value_including_absence():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, mns=None)
    assert reduce_curve(records).engine["max_num_seqs"] == [256, None]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_service_sweep.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'harness.service_sweep'`.

- [ ] **Step 3: Create `harness/service_sweep.py`**

```python
"""The single-engine service-curve sweep, local side.

One replica at a fixed serve configuration, concurrency swept. Per level the
sweep reports end-to-end request latency, throughput in output tokens per
second, GPU utilisation and TTFT. Artifact 2's simulator uses the latency as
each request's service time and caps a replica at the highest level measured;
artifact 4 needs the same curve per engine at a memory split. So the levels
and the serve arguments are the caller's, never fixed here.

This module holds what the local driver needs: the schedule, the job payload,
the stored record, and the reduction to a curve. What runs inside the worker
is `harness/sweep_worker.py`.

The reduction emits PLAIN TUPLES `(concurrency, latency_s, throughput_tps,
gpu_util)`, never `autoscale.service.ServiceCurve`. Artifact 5's package bans
`autoscale`, and the harness must not pull one artifact's types into another;
artifact 2 adapts the tuples on its own side (`scripts/a2_service_curve.py`).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from harness.failures import classify_failure
from harness.scheduler import ScheduledRun, build_schedule
from harness.stats import median

SCHEMA_VERSION = 1
# Owner decision 2 (2026-10-04): three repeats per level, interleaved.
DEFAULT_REPEATS = 3
# Each measured run is about this many waves of `level` concurrent requests,
# so its duration is about DEFAULT_WAVES x latency(level) whatever the level,
# and never fewer than DEFAULT_MIN_PROMPTS requests feed one run's median.
DEFAULT_WAVES = 20
DEFAULT_MIN_PROMPTS = 100
STATISTIC = (
    "per run: the median, over successful requests, of ttft + sum(itls) "
    "(end-to-end request latency); per level: the median of the run medians, "
    "with min..max of the run medians as the interval"
)
_CURVE_FIELDS = ("latency_s", "throughput_tps", "gpu_util", "ttft_median_s")


def condition_for(level: int) -> str:
    return f"c{level}"


def level_of(condition: str) -> int:
    if not condition.startswith("c") or not condition[1:].isdigit():
        raise ValueError(
            f"condition {condition!r} is not a sweep level like 'c16'; a record "
            "under it cannot be placed on the curve"
        )
    return int(condition[1:])


def validate_levels(levels: Sequence[int]) -> list[int]:
    """At least two distinct positive integers, ascending.

    Ascending and distinct because `ServiceCurve` refuses anything else, and
    discovering that after a paid sweep is the expensive way. At least two
    because one point cannot be interpolated.
    """
    out = list(levels)
    for level in out:
        if isinstance(level, bool) or not isinstance(level, int) or level < 1:
            # ValueError, not TypeError, so a caller catches one type for
            # every bad level.
            raise ValueError(
                f"level {level!r} is not a positive integer; bench's "
                "--max-concurrency takes an integer and reads 0 as unlimited"
            )
    if len(out) < 2:
        raise ValueError(f"levels {out!r}: a curve needs at least two points")
    if out != sorted(set(out)):
        raise ValueError(
            f"levels {out!r} must be strictly ascending; the curve requires "
            "distinct, ascending concurrency"
        )
    return out


def sweep_schedule(levels: Sequence[int], *, repeats: int = DEFAULT_REPEATS, seed: int):
    """Every level once per block, shuffled within each block by `seed`.

    `harness.scheduler.build_schedule` is exactly owner decision 2: repeats
    interleaved across levels, never all repeats of one level back to back,
    so a level is never confounded with a stretch of platform conditions.
    `block_index` is the repeat.
    """
    if repeats < 1:
        raise ValueError(f"repeats={repeats!r}; a sweep with no repeats measures nothing")
    conditions = [condition_for(level) for level in validate_levels(levels)]
    return build_schedule(conditions=conditions, blocks=repeats, seed=seed)


def num_prompts_for(level: int, *, waves: int = DEFAULT_WAVES, minimum: int = DEFAULT_MIN_PROMPTS):
    return max(minimum, waves * level)


def job_payload(
    scheduled: ScheduledRun,
    run_id: str,
    *,
    serve_args: Sequence[str],
    output_len: int,
    job_budget_s: float,
    seed: int,
    waves: int = DEFAULT_WAVES,
    min_prompts: int = DEFAULT_MIN_PROMPTS,
    diagnostics: bool = False,
) -> dict:
    """The worker's input for one (level, repeat).

    `seed + run_index` gives every run its own bench seed, so random-fallback
    prompts differ between runs. `warmup_prompts` is one wave at the level.
    `diagnostics` asks the worker for the in-container checks the first paid
    run needs (worker/sweep_handler.py `collect_diagnostics`).
    """
    level = level_of(scheduled.condition)
    return {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "level": level,
        "repeat": scheduled.block_index,
        "serve_args": list(serve_args),
        "num_prompts": num_prompts_for(level, waves=waves, minimum=min_prompts),
        "warmup_prompts": level,
        "output_len": output_len,
        "job_budget_s": job_budget_s,
        "seed": seed + scheduled.run_index,
        "diagnostics": diagnostics,
    }


@dataclass
class SweepRun:
    """One stored sweep run. Failed runs are stored too: failures are data.

    The four curve fields are top-level and None on a failed run, so the
    reducer never digs into `summary`. `summary` is the worker's compact
    summary as returned (no per-request arrays); `engine` holds parsed engine
    facts plus the raw engine log, so a parser fix can be re-applied later.
    """

    run_id: str
    run_index: int
    condition: str
    level: int
    repeat: int
    outcome: str
    latency_s: float | None = None
    ttft_median_s: float | None = None
    throughput_tps: float | None = None
    gpu_util: float | None = None
    prompt_path: str | None = None
    served_cmd: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    host: dict = field(default_factory=dict)
    clock_A: dict = field(default_factory=dict)
    clock_C: dict = field(default_factory=dict)
    status: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SweepRun":
        return cls(**d)


def _failed_status(detail: str) -> dict:
    return {"failure_class": classify_failure(detail).value, "failure_detail": detail}


def _engine_of(output: dict) -> dict:
    return {**(output.get("engine") or {}), "log_lines": list(output.get("log_lines") or [])}


def build_sweep_record(scheduled: ScheduledRun, run_id: str, outcome) -> SweepRun:
    """The `build_record` callback for `harness.campaign.run_campaign`.

    Three outcomes. The job failed or the engine never became healthy: stored
    failed, the worker's output (log lines, served command) kept from
    `diagnostics`. The engine was healthy but the measurement failed: the
    worker returns `healthy: True` -- that field means the engine answered
    `/health`, which is all `RunPodSubmitter` checks -- with `run: None` and a
    `run_error`; stored failed with that error. Otherwise stored ok.
    """
    level = level_of(scheduled.condition)
    base = {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "condition": scheduled.condition,
        "level": level,
        "repeat": scheduled.block_index,
        "clock_A": dict(outcome.clock_A),
    }
    if outcome.error is not None:
        diag = outcome.diagnostics or {}
        return SweepRun(
            **base,
            outcome="failed",
            served_cmd=list(diag.get("served_cmd") or []),
            engine=_engine_of(diag),
            host=dict(diag.get("host") or {}),
            status=_failed_status(outcome.error),
            diagnostics=dict(diag.get("diagnostics") or {}),
        )
    out = outcome.payload
    if out.get("run_id") != run_id or out.get("level") != level:
        raise ValueError(
            f"the worker answered for run_id={out.get('run_id')!r} level="
            f"{out.get('level')!r}, but this job was run_id={run_id!r} level={level}; "
            "storing it would put another run's numbers under this one"
        )
    common = {
        "served_cmd": list(out.get("served_cmd") or []),
        "engine": _engine_of(out),
        "host": dict(out.get("host") or {}),
        "clock_C": dict(out.get("clock_C") or {}),
        "diagnostics": dict(out.get("diagnostics") or {}),
    }
    run = out.get("run")
    if not run:
        detail = out.get("run_error") or "worker returned neither a run nor a run_error"
        return SweepRun(**base, outcome="failed", **common, status=_failed_status(detail))
    return SweepRun(
        **base,
        outcome="ok",
        latency_s=run["latency_s"],
        ttft_median_s=run["ttft_median_s"],
        throughput_tps=run["throughput_tps"],
        gpu_util=run["gpu_util"],
        prompt_path=run["prompt_path"],
        summary=run,
        **common,
        status={"failure_class": None, "failure_detail": None},
    )


def _distinct(values) -> list:
    values = list(values)
    present = sorted({v for v in values if v is not None})
    return present + ([None] if None in values else [])


@dataclass(frozen=True)
class CurveReduction:
    """Per-level rows, ascending by concurrency, and what they were measured with."""

    levels: tuple
    prompt_path: str
    served_cmd: tuple
    engine: dict

    @property
    def points(self) -> list[tuple[int, float, float, float]]:
        """`(concurrency, latency_s, throughput_tps, gpu_util)` per level."""
        return [
            (row["concurrency"], row["latency_s"], row["throughput_tps"], row["gpu_util"])
            for row in self.levels
        ]

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "statistic": STATISTIC,
            "points": [list(p) for p in self.points],
            "levels": [dict(row) for row in self.levels],
            "prompt_path": self.prompt_path,
            "served_cmd": list(self.served_cmd),
            "engine": dict(self.engine),
        }


def reduce_curve(
    records,
    *,
    min_repeats: int = DEFAULT_REPEATS,
    expected_levels: Sequence[int] | None = None,
) -> CurveReduction:
    """Stored runs -> one row per level: median of the run medians, min..max.

    Refuses, rather than reduces around, every condition under which the
    result would not be one replica's curve: no successful run; two
    successful runs at one (level, repeat), which means two campaigns share a
    store; runs that took different prompt paths or ran different serve
    commands; a run with no GPU utilisation (the curve has no honest value to
    put there); a level with fewer than `min_repeats` successful runs; a
    requested level absent from the store; fewer than two levels.
    """
    records = list(records)
    ok = [r for r in records if r.outcome == "ok"]
    if not ok:
        raise ValueError("the store holds no successful run; there is no curve to reduce")
    seen: set[tuple[int, int]] = set()
    for r in ok:
        if (r.level, r.repeat) in seen:
            raise ValueError(
                f"two successful runs at level {r.level} repeat {r.repeat}; the store "
                "holds more than one campaign, and pooling them would mix engines this "
                "reduction cannot tell apart. Give each campaign its own store"
            )
        seen.add((r.level, r.repeat))
    paths = sorted({str(r.prompt_path) for r in ok})
    if len(paths) != 1:
        raise ValueError(
            f"successful runs took prompt paths {paths}; points measured on the exact "
            "prompt and on random prompts are different measurements and cannot share "
            "one curve"
        )
    commands = {tuple(r.served_cmd) for r in ok}
    if len(commands) != 1:
        raise ValueError(
            f"successful runs used {len(commands)} different serve commands; a curve "
            "from differently configured engines is not one replica's curve"
        )
    no_util = [r.run_id for r in ok if r.gpu_util is None]
    if no_util:
        raise ValueError(
            f"runs {no_util} have no GPU utilisation reading; the curve's utilisation "
            "column would need an invented value. Check nvidia-smi in the image"
        )
    present = sorted({r.level for r in records})
    if expected_levels is not None:
        absent = sorted(set(expected_levels) - set(present))
        if absent:
            raise ValueError(
                f"levels {absent} were requested but have no stored run; the campaign "
                "did not finish. Resume it before reducing"
            )
    failed = Counter(r.level for r in records if r.outcome != "ok")
    rows = []
    for level in present:
        runs = sorted((r for r in ok if r.level == level), key=lambda r: r.repeat)
        if len(runs) < min_repeats:
            raise ValueError(
                f"level {level} has {len(runs)} successful runs, fewer than "
                f"min_repeats={min_repeats}; its median and min-max interval would rest "
                "on fewer repeats than registered. Re-run the level in a new campaign, "
                "or pass a lower min_repeats and report it"
            )
        row = {
            "concurrency": level,
            "n_runs": len(runs),
            "n_failed": failed[level],
            "run_ids": [r.run_id for r in runs],
        }
        for name in _CURVE_FIELDS:
            values = [getattr(r, name) for r in runs]
            row[name] = median(values)
            row[f"{name}_range"] = [min(values), max(values)]
        rows.append(row)
    if len(rows) < 2:
        raise ValueError(f"only level {present} is present; a curve needs at least two")
    engine = {
        key: _distinct(r.engine.get(key) for r in ok)
        for key in ("max_num_seqs", "max_num_seqs_source", "kv_capacity_tokens", "vllm_version")
    }
    return CurveReduction(
        levels=tuple(rows),
        prompt_path=paths[0],
        served_cmd=next(iter(commands)),
        engine=engine,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_service_sweep.py -q`
Expected: 25 passed.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check harness/service_sweep.py tests/test_harness_service_sweep.py
git add harness/service_sweep.py tests/test_harness_service_sweep.py
git commit -m "feat: service-curve sweep schedule, record and reduction to plain tuples"
```

---

## Task 10: The sweep's RunPod handler, and its own COPY line

`worker/sweep_handler.py` runs one (level, repeat) inside the image: start the engine with `harness.serve.served`, choose the prompt path, warm up one wave, run one measured bench with the GPU sampler running, stop the engine, return a compact summary. It is selected by the template's `dockerStartCmd` (`python3 -u /opt/sweep_handler.py`); the image's default CMD stays artifact 1's handler.

**Job granularity: one job per (level, repeat).** The endpoint's execution timeout is 1800 s (`docs/runbook.md`). Artifact 1 measured this engine's startup at p95 86 s with weights on the volume and a cold compile cache (arm B), 55 s warm (arm C) (`data/analysis.json`). A measured run is ~20 waves of latency(level) — 6 to 42 s on the placeholder curve — with at least 100 requests; warm-up is one wave; teardown is at most the 30 s grace. A job is therefore about 2–3 minutes against a 30-minute limit, a 10× margin for a measured curve slower than the placeholder. One job per level would also fit, but its three repeats would run back to back on one engine (owner decision 2 forbids it) and the interval would never see engine-to-engine variation. The handler still budgets: it keeps 120 s back for teardown and upload, bounds every bench run by what remains, and reports a spent budget as a `run_error` rather than letting the platform kill the job with nothing returned.

**Two contracts the tests pin.** `healthy` is `True` whenever the engine answered `/health`, because that is the field `RunPodSubmitter` treats as success; a failed measurement is `run: None` plus `run_error`. And a payload with `diagnostics: true` additionally returns the in-container answers Task 15's checklist needs — `vllm bench serve --help`, nvidia-smi's raw output, whether pandas imports, whether the engine logged the prompt — plus the raw bench JSON. Ordinary jobs return none of that.

The existing Dockerfile guard checks only package COPY lines, so a new `worker/*.py` without its own COPY line passes every test and fails on the paid run. Step 5 adds a guard for that first, and watches it fail.

The handler, the driver (Task 11) and the artifact-2 adapter (Task 12) share one fake engine with a known timing model. It lives in `tests/sweep_fakes.py`, a helper module without the `test_` prefix, imported by name (pytest puts `tests/` on `sys.path` for test modules in this repository's default import mode). `tests/conftest.py` is deliberately not used: artifact 5's plan creates one.

**Files:**
- Create: `worker/sweep_handler.py`, `tests/sweep_fakes.py`, `tests/test_sweep_handler.py`
- Modify: `worker/Dockerfile:32-37`, `tests/test_harness_boundary.py` (append one test)

- [ ] **Step 1: Write the fakes and the failing tests**

Create `tests/sweep_fakes.py`:

```python
"""Fakes for the sweep handler: an engine, a bench and a GPU sampler that
follow a known timing model, so a test can check the sweep recovers exactly
what was put in. Not a test module (no `test_` prefix); test files import it
by name, which works because pytest puts tests/ on sys.path for them."""

import contextlib
import subprocess
from collections import Counter

from harness.bench import BenchError

PROMPT_TOKENS = 13
OUTPUT_LEN = 16
NON_DEFAULT_LINE = (
    "(APIServer pid=130) INFO 10-04 12:00:00 [api_utils.py:273] non-default args: "
    "{'model_tag': 'Qwen/Qwen3-8B', 'model': 'Qwen/Qwen3-8B', 'max_model_len': 8192, "
    "'max_num_seqs': 256}"
)
KV_LINE = "(EngineCore pid=340) INFO 10-04 12:00:40 [kv_cache_utils.py:2235] GPU KV cache size: 35,792 tokens"


def model_latency(level: int, repeat: int = 0) -> float:
    return 0.30 + 0.01 * level + 0.002 * repeat


def model_ttft(level: int) -> float:
    return 0.05 + 0.001 * level


def model_util(level: int) -> float:
    return min(1.0, 0.15 * level**0.5)


def bench_json(n: int, *, level: int, repeat: int = 0, input_len: int = PROMPT_TOKENS) -> dict:
    latency, ttft = model_latency(level, repeat), model_ttft(level)
    itl = (latency - ttft) / (OUTPUT_LEN - 1)
    return {
        "duration": n / level * latency,
        "completed": n,
        "failed": 0,
        "num_prompts": n,
        "max_concurrency": level,
        "output_throughput": OUTPUT_LEN * level / latency,
        "median_e2el_ms": latency * 1000,
        "input_lens": [input_len] * n,
        "output_lens": [OUTPUT_LEN] * n,
        "ttfts": [ttft] * n,
        "itls": [[itl] * (OUTPUT_LEN - 1)] * n,
        "start_times": [0.0] * n,
        "generated_texts": ["x"] * n,
        "errors": [""] * n,
    }


class FakeServer:
    def __init__(self, model, args, healthy):
        self.base_url = "http://127.0.0.1:8000"
        self.cmd = ["vllm", "serve", model, "--port", "8000", *args]
        self.healthy = healthy
        self.log_lines = ["INFO fake engine starting", NON_DEFAULT_LINE, KV_LINE]
        self.stops = 0

    def stop(self) -> float:
        self.stops += 1
        return 1.5


class FakeSampler:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def summary(self):
        util = model_util(self.engine.last_level)
        sample = {"t_s": 0.0, "raw": str(round(util * 100)), "util_pct": util * 100}
        return {"gpu_util": util, "interval_s": 0.5, "n_samples": 1, "n_valid": 1,
                "samples": [sample]}


class FakeEngine:
    """One fake `vllm serve` plus `vllm bench serve`, shared across jobs.

    `measured[level]` counts measured runs per level, so each repeat of a
    level gets its own latency from `model_latency(level, repeat)`.
    """

    def __init__(self, *, healthy=True, probe_ok=True, fail_measured_at=None):
        self.healthy = healthy
        self.probe_ok = probe_ok
        self.fail_measured_at = fail_measured_at
        self.served_calls = []
        self.bench_calls = []
        self.measured = Counter()
        self.last_level = 1
        self.servers = []
        self.commands = []

    @contextlib.contextmanager
    def served(self, model, *, args, env):
        self.served_calls.append({"model": model, "args": list(args), "env": dict(env)})
        server = FakeServer(model, args, self.healthy)
        self.servers.append(server)
        try:
            yield server
        finally:
            server.stop()

    def run_bench(self, base_url, **kw):
        self.bench_calls.append(kw)
        name = kw["result_dir"].name
        if name == "prompt-probe":
            if not self.probe_ok:
                raise BenchError("vllm bench serve exited 1; ModuleNotFoundError: pandas")
            return bench_json(1, level=1)
        level = kw["max_concurrency"]
        self.last_level = level
        if name != "measured":
            return bench_json(kw["num_prompts"], level=level)
        repeat = self.measured[level]
        self.measured[level] += 1
        if self.fail_measured_at == (level, repeat):
            raise BenchError("vllm bench serve exited 1; this run has no result")
        return bench_json(kw["num_prompts"], level=level, repeat=repeat)

    def sampler(self):
        return FakeSampler(self)

    def deps(self, deps_cls):
        return deps_cls(
            served=self.served,
            run_bench=self.run_bench,
            sampler_factory=self.sampler,
            count_tokens=lambda base_url, model, prompt: PROMPT_TOKENS,
            host_info=lambda: {"host_id": "fake-container"},
            run_command=self.run_command,
        )

    def run_command(self, cmd, **kwargs):
        self.commands.append(cmd)
        is_help = cmd[:3] == ["vllm", "bench", "serve"]
        stdout = "--max-concurrency --save-detailed" if is_help else "42"
        return subprocess.CompletedProcess(cmd, 0, stdout, "")
```

Create `tests/test_sweep_handler.py`:

```python
"""The sweep's RunPod handler, driven against a fake engine and bench."""

import json
import sys
from pathlib import Path

import pytest
from sweep_fakes import PROMPT_TOKENS, FakeEngine, model_latency, model_util

from harness.scheduler import ScheduledRun
from harness.service_sweep import build_sweep_record, job_payload
from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import sweep_handler


@pytest.fixture(autouse=True)
def endpoint_env(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.setenv("MODEL_REVISION", "b968826d9c46dd6066d109eabc6255188de91218")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")


def _payload(level=8, repeat=0, run_id="rid", **over):
    p = job_payload(
        ScheduledRun(run_index=3, block_index=repeat, condition=f"c{level}"), run_id,
        serve_args=["--max-num-seqs", "256"], output_len=16, job_budget_s=1800, seed=100,
    )
    p.update(over)
    return p


def _run(engine, payload):
    return sweep_handler.handler({"input": payload}, deps=engine.deps(sweep_handler.Deps))


def test_the_prompt_is_artifact_ones_byte_for_byte():
    import probe

    assert sweep_handler.A1_PROMPT == probe.PROMPT


def test_a_healthy_run_returns_a_compact_summary_and_the_engine_facts():
    engine = FakeEngine()
    out = _run(engine, _payload(level=8))
    assert out["healthy"] is True
    assert out["run_error"] is None
    assert (out["run_id"], out["level"], out["repeat"]) == ("rid", 8, 0)
    assert out["run"]["latency_s"] == pytest.approx(model_latency(8))
    assert out["run"]["gpu_util"] == pytest.approx(model_util(8))
    assert out["run"]["prompt_path"] == "exact"
    assert out["run"]["input_lens_unique"] == [PROMPT_TOKENS]
    assert out["engine"]["max_num_seqs"] == 256
    assert out["engine"]["max_num_seqs_source"] == "non-default-args"
    assert out["engine"]["kv_capacity_tokens"] == 35792
    assert out["teardown_s"] == 1.5
    text = json.dumps(out)
    assert '"ttfts"' not in text and '"itls"' not in text, "per-request arrays leaked"
    assert len(text) < 20_000


def test_serve_args_are_the_endpoints_fixed_flags_then_the_jobs():
    engine = FakeEngine()
    _run(engine, _payload())
    assert engine.served_calls == [{
        "model": "Qwen/Qwen3-8B",
        "args": ["--revision", "b968826d9c46dd6066d109eabc6255188de91218",
                 "--max-model-len", "8192", "--max-num-seqs", "256"],
        "env": {},
    }]


def test_a_job_may_not_override_a_flag_the_endpoint_owns():
    with pytest.raises(ValueError, match="endpoint environment owns"):
        _run(FakeEngine(), _payload(serve_args=["--max-model-len=4096"]))


def test_the_bench_sequence_is_probe_warmup_then_one_measured_run():
    engine = FakeEngine()
    _run(engine, _payload(level=8))
    names = [c["result_dir"].name for c in engine.bench_calls]
    assert names == ["prompt-probe", "warmup", "measured"]
    measured = engine.bench_calls[-1]
    assert (measured["max_concurrency"], measured["num_prompts"]) == (8, 160)
    assert measured["timeout"] is not None, "the measured run must be bounded by the job budget"


def test_an_unhealthy_engine_returns_its_log_and_runs_no_load():
    engine = FakeEngine(healthy=False)
    out = _run(engine, _payload())
    assert out["healthy"] is False
    assert any("KV cache size" in line for line in out["log_lines"])
    assert engine.bench_calls == []


def test_a_failed_measurement_still_returns_the_log_and_stops_the_engine():
    engine = FakeEngine(fail_measured_at=(8, 0))
    out = _run(engine, _payload(level=8))
    assert out["healthy"] is True
    assert out["run"] is None
    assert out["run_error"].startswith("BenchError")
    assert out["log_lines"]
    assert engine.servers[0].stops >= 1


def test_a_probe_that_cannot_send_the_prompt_falls_back_and_says_so():
    out = _run(FakeEngine(probe_ok=False), _payload())
    assert out["run"]["prompt_path"] == "random-fallback"
    assert "pandas" in out["run"]["prompt"]["probe_error"]


def test_a_budget_spent_on_startup_is_a_run_error_not_a_platform_kill():
    out = _run(FakeEngine(), _payload(job_budget_s=60))
    assert out["run"] is None
    assert "budget is spent" in out["run_error"]


def test_the_output_becomes_an_ok_record_through_the_stub_submitter():
    engine = FakeEngine()
    payload = _payload(level=4)
    outcome = PayloadStubSubmitter(lambda p: _run(engine, p)).submit_payload(payload)
    rec = build_sweep_record(ScheduledRun(3, 0, "c4"), "rid", outcome)
    assert rec.outcome == "ok"
    assert rec.latency_s == pytest.approx(model_latency(4))
    assert rec.engine["max_num_seqs"] == 256


def test_an_unhealthy_output_becomes_a_health_timeout_record():
    engine = FakeEngine(healthy=False)
    outcome = PayloadStubSubmitter(lambda p: _run(engine, p)).submit_payload(_payload(level=4))
    rec = build_sweep_record(ScheduledRun(3, 0, "c4"), "rid", outcome)
    assert rec.outcome == "failed"
    assert rec.status["failure_class"] == "health_timeout"
    assert rec.engine["log_lines"]


def test_an_ordinary_job_runs_no_diagnostics_and_keeps_no_raw_json():
    engine = FakeEngine()
    out = _run(engine, _payload())
    assert "diagnostics" not in out
    assert "raw_bench" not in out["run"]
    assert engine.commands == []


def test_a_diagnostic_job_answers_the_first_paid_runs_questions():
    engine = FakeEngine()
    out = _run(engine, _payload(diagnostics=True))
    diag = out["diagnostics"]
    assert diag["bench_help"]["cmd"] == ["vllm", "bench", "serve", "--help"]
    assert "--save-detailed" in diag["bench_help"]["stdout"]
    assert diag["nvidia_smi"]["stdout"] == "42"
    assert isinstance(diag["pandas_importable"], bool)
    assert diag["prompt_in_log"] is False
    assert out["run"]["raw_bench"]["ttfts"], "the diagnostic job keeps the saved JSON"


def test_an_unhealthy_diagnostic_job_still_reports_the_tools_help():
    out = _run(FakeEngine(healthy=False), _payload(diagnostics=True))
    assert out["healthy"] is False
    assert out["diagnostics"]["bench_help"]["returncode"] == 0


def test_model_id_is_required(monkeypatch):
    monkeypatch.delenv("MODEL_ID")
    with pytest.raises(KeyError):
        _run(FakeEngine(), _payload())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_sweep_handler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sweep_handler'`.

- [ ] **Step 3: Create `worker/sweep_handler.py`**

```python
"""RunPod handler for one (level, repeat) of the service-curve sweep.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/sweep_handler.py`. The image's default CMD stays artifact 1's
measurement handler.

One job is one scheduled run: start the engine, decide how artifact 1's prompt
reaches it, warm up one wave, run one measured `vllm bench serve` at the
level's concurrency with the GPU sampler running, stop the engine, and return
a compact summary. Telemetry rides the result channel, as artifact 1's handler
does, so no run is lost to log retrieval.

Why one job per (level, repeat), not one per level. The endpoint's execution
timeout is 1800 s (docs/runbook.md). Artifact 1 measured this engine's startup
at a p95 of 86 s with weights on the network volume and a cold compile cache
(arm B, data/analysis.json), and 55 s warm (arm C). A measured run lasts about
DEFAULT_WAVES = 20 waves of latency(level): 20 x 0.3-2.1 s, 6-42 s, on the
placeholder curve, with at least 100 requests. So a job is about three minutes
against a 30-minute limit, with room for a measured curve ten times slower
than the placeholder. A job per level would fit too, but its three repeats
would run back to back on one engine, which owner decision 2 forbids, and its
interval would never see engine-to-engine variation. A single job for the
whole sweep was rejected for the same reason, and because one failure would
lose every point.

Returns `healthy: True` whenever the engine answered `/health`, because that
is the field `RunPodSubmitter` treats as success. A measurement that then
failed comes back as `run: None` with a `run_error`, and
`harness.service_sweep.build_sweep_record` stores it as a failed run.
"""

import importlib.util
import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from harness.sweep_worker import choose_prompt_path, max_num_seqs_from_log, run_one
from harness.vllm_logs import parse_engine_log

# Artifact 1's prompt, byte for byte (worker/probe.py PROMPT). Copied, not
# imported: probe.py imports coldstart.analysis.metrics, and the sweep must
# not drag artifact 1's package into its path. tests/test_sweep_handler.py
# pins the two equal.
A1_PROMPT = "Explain what a key-value cache does, in two sentences."
# Seconds kept back from the job budget for teardown and the result upload.
TEARDOWN_RESERVE_S = 120.0
_HELP_CHARS = 200_000
# Read from the endpoint environment, as worker/handler.py does, so they
# cannot differ between jobs of one campaign. Duplicated from handler.py
# rather than imported for the same reason as A1_PROMPT.
_FIXED_SERVE_ENV = (
    ("MODEL_REVISION", "--revision"),
    ("MAX_MODEL_LEN", "--max-model-len"),
)


def fixed_serve_args() -> list[str]:
    args: list[str] = []
    for var, flag in _FIXED_SERVE_ENV:
        value = os.environ.get(var)
        if value:
            args += [flag, value]
    return args


def serve_args_for(payload_args) -> list[str]:
    owned = {flag for _, flag in _FIXED_SERVE_ENV}
    clash = [a for a in payload_args if a.split("=", 1)[0] in owned]
    if clash:
        raise ValueError(
            f"serve_args {clash} set flags the endpoint environment owns; a per-job "
            "value would let one campaign's runs measure different engines"
        )
    return [*fixed_serve_args(), *payload_args]


def count_tokens(base_url: str, model: str, prompt: str) -> int:
    """The engine's own token count for the prompt, from vLLM's `/tokenize`.

    The server's count rather than a local tokenizer's: the bench client
    tokenizes with the model's tokenizer at its default revision, the engine
    with the pinned one, and only the engine's count is the prompt it serves.
    """
    r = requests.post(
        f"{base_url}/tokenize", json={"model": model, "prompt": prompt}, timeout=30
    )
    r.raise_for_status()
    return len(r.json()["tokens"])


def host_info() -> dict:
    return {"host_id": socket.gethostname(), "runpod_pod_id": os.environ.get("RUNPOD_POD_ID")}


def _engine_facts(lines) -> dict:
    parsed = parse_engine_log("\n".join(lines))
    max_num_seqs, source = max_num_seqs_from_log(lines)
    return {
        **parsed.engine_info,
        "s4_subphases": parsed.phases,
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
    }


def collect_diagnostics(run_command: Callable, log_lines) -> dict:
    """In-container checks the first paid run needs, asked for per job.

    Each answers an item this repository could not verify without the image:
    whether the tool accepts every flag `harness.bench` passes (its help
    text), whether `pandas` -- which the custom dataset needs -- is installed,
    what nvidia-smi prints for the sampler's query, and whether the engine
    logged artifact 1's prompt text (only if the job's serve args turned
    request logging on). Never part of an ordinary job: the help text alone
    is tens of kilobytes.
    """

    def capture(cmd):
        try:
            proc = run_command(cmd, capture_output=True, text=True, check=False, timeout=120)
        except Exception as e:  # noqa: BLE001 -- a diagnostic never fails the job
            return {"cmd": cmd, "error": repr(e)}
        return {
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-_HELP_CHARS:],
            "stderr": (proc.stderr or "")[-2000:],
        }

    return {
        "bench_help": capture(["vllm", "bench", "serve", "--help"]),
        "nvidia_smi": capture(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits",
             "--id=0"]
        ),
        "pandas_importable": importlib.util.find_spec("pandas") is not None,
        "prompt_in_log": any(A1_PROMPT in line for line in log_lines),
    }


@dataclass
class Deps:
    """The handler's effects, injectable so tests run it without an engine.

    None means "the real one", resolved lazily so importing this module never
    needs vLLM, the runpod SDK, or a GPU.
    """

    served: Callable | None = None
    run_bench: Callable | None = None
    sampler_factory: Callable | None = None
    count_tokens: Callable[[str, str, str], int] = count_tokens
    host_info: Callable[[], dict] = host_info
    run_command: Callable = subprocess.run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(deps: Deps) -> Deps:
    if deps.served is None:
        from harness.serve import served

        deps.served = served
    if deps.run_bench is None:
        from harness.bench import run_bench

        deps.run_bench = run_bench
    if deps.sampler_factory is None:
        from harness.gpu_util import GpuUtilSampler

        deps.sampler_factory = GpuUtilSampler
    return deps


def handler(job, deps: Deps | None = None) -> dict:
    d = _resolve(deps or Deps())
    t0 = d.clock()
    p = job.get("input") or {}
    # Required and never defaulted: a run that cannot say which level it
    # measured is a mislabelled point, not a slightly worse one.
    run_id, level = p["run_id"], int(p["level"])
    model = os.environ["MODEL_ID"]
    args = serve_args_for(p["serve_args"])
    common = {"run_id": run_id, "level": level, "repeat": p["repeat"], "host": d.host_info()}
    want_diagnostics = bool(p.get("diagnostics"))
    deadline = t0 + float(p["job_budget_s"]) - TEARDOWN_RESERVE_S
    with d.served(model, args=args, env={}) as server, tempfile.TemporaryDirectory() as tmp:
        startup_s = d.clock() - t0
        if not server.healthy:
            out = {
                "healthy": False,
                "log_lines": list(server.log_lines),
                "served_cmd": list(server.cmd),
                "startup_s": startup_s,
                **common,
            }
            if want_diagnostics:
                out["diagnostics"] = collect_diagnostics(d.run_command, out["log_lines"])
            return out
        try:
            plan = choose_prompt_path(
                server.base_url,
                model=model,
                prompt=A1_PROMPT,
                output_len=p["output_len"],
                workdir=tmp,
                run_bench=d.run_bench,
                count_tokens=lambda prompt: d.count_tokens(server.base_url, model, prompt),
            )
            run = run_one(
                server.base_url,
                model=model,
                level=level,
                num_prompts=p["num_prompts"],
                warmup_prompts=p["warmup_prompts"],
                plan=plan,
                seed=p["seed"],
                workdir=tmp,
                run_bench=d.run_bench,
                sampler_factory=d.sampler_factory,
                deadline=deadline,
                clock=d.clock,
                keep_raw=want_diagnostics,
            )
            run_error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6); the
            # engine's log and teardown below must survive a failed measurement.
            run, run_error = None, f"{type(e).__name__}: {e}"
        teardown_s = server.stop()
    lines = list(server.log_lines)
    out = {
        "healthy": True,
        "run": run,
        "run_error": run_error,
        "served_cmd": list(server.cmd),
        "engine": _engine_facts(lines),
        "log_lines": lines,
        "startup_s": startup_s,
        "teardown_s": teardown_s,
        **common,
    }
    if want_diagnostics:
        out["diagnostics"] = collect_diagnostics(d.run_command, lines)
    return out


def main():
    # Imported here so tests can import the handler without the runpod SDK,
    # and so importing it never starts a server.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_sweep_handler.py -q`
Expected: 15 passed.

- [ ] **Step 5: Append the worker-module COPY guard to `tests/test_harness_boundary.py`**

Append at the end of the file, after two blank lines (it already imports `re` and defines `REPO`):

```python
def test_dockerfile_copies_every_worker_module():
    """The package check above cannot see worker/*.py: those are copied file by
    file and run as scripts, not imported as a package. A new handler without
    its own COPY line passes every other guard and fails on the paid GPU run,
    when the template's dockerStartCmd names a file the image does not hold."""
    dockerfile = (REPO / "worker" / "Dockerfile").read_text()
    pairs = re.findall(r"^COPY\s+worker/(\w+\.py)\s+/opt/(\w+\.py)\s*$", dockerfile, re.MULTILINE)
    copied = {src for src, dst in pairs if src == dst}
    modules = sorted(p.name for p in (REPO / "worker").glob("*.py"))
    missing = [m for m in modules if m not in copied]
    assert modules, "worker/ has no modules, so this test checks nothing"
    assert missing == [], (
        f"worker/Dockerfile does not COPY {missing} to /opt under the same name; a "
        "template whose dockerStartCmd runs one of them fails on a paid GPU run"
    )
```

- [ ] **Step 6: Run it to verify it fails on the new handler**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_boundary.py -q -o addopts=""`
Expected: `1 failed, 4 passed`, the failure naming `sweep_handler.py` ("Left contains one more item: 'sweep_handler.py'").

- [ ] **Step 7: Add the COPY line to `worker/Dockerfile`**

Replace:

```dockerfile
COPY worker/handler.py /opt/handler.py

ENTRYPOINT []
# The measurement handler. recon_handler.py stays in the image; select it by
# overriding dockerStartCmd on the template when another capture is needed.
CMD ["python3", "-u", "/opt/handler.py"]
```

with:

```dockerfile
COPY worker/handler.py /opt/handler.py
# The service-curve sweep's handler (harness/service_sweep.py). Imports only
# harness/, never coldstart/.
COPY worker/sweep_handler.py /opt/sweep_handler.py

ENTRYPOINT []
# The measurement handler. recon_handler.py and sweep_handler.py stay in the
# image; select one by overriding dockerStartCmd on the template, e.g.
# `python3 -u /opt/sweep_handler.py` for the service-curve sweep.
CMD ["python3", "-u", "/opt/handler.py"]
```

`harness/` is already COPYed (line 29) and already in `build-worker.yml`'s paths filter, so no other image change is needed; the existing package guard confirms it in Step 8.

- [ ] **Step 8: Run the boundary and handler tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_boundary.py tests/test_sweep_handler.py -q -o addopts=""`
Expected: `20 passed`.

- [ ] **Step 9: Lint and commit**

```bash
.venv/bin/python -m ruff check worker/sweep_handler.py tests/sweep_fakes.py tests/test_sweep_handler.py tests/test_harness_boundary.py
git add worker/sweep_handler.py worker/Dockerfile tests/sweep_fakes.py tests/test_sweep_handler.py tests/test_harness_boundary.py
git commit -m "feat: the service-sweep RunPod handler, with its own COPY line and a guard for the next one"
```

When this commit is pushed (the owner's call, not a plan step), CI rebuilds the worker image (`worker/**` is in the paths filter); the digest it reports is what Task 15's checklist pins the sweep template to.

---

## Task 11: The local sweep driver, end to end with no network

`scripts/run_service_sweep.py` preflights the endpoint against the sweep's pin set, builds the schedule, runs `harness.campaign.run_campaign` with `RunPodSubmitter.submit_payload`, stores every run through `harness.store.JsonlStore` as a `SweepRun`, reduces the store to the curve, and writes it as JSON. The pin set lives here, never in `harness/`, because a pin set is one experiment's boundary.

The tests drive the whole chain — driver, campaign loop, store, `PayloadStubSubmitter`, the real `sweep_handler.handler`, the reducer — against Task 10's fake engine, with `requests.get`/`post` replaced by functions that fail the test if called. The fake's latency is a known function of level and repeat, so the test checks that the curve recovers exactly the median repeat and the min–max interval that were put in.

**Files:**
- Create: `scripts/run_service_sweep.py`, `tests/test_run_service_sweep.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_run_service_sweep.py`:

```python
"""The sweep end to end with no network: the local driver, the harness
campaign loop and store, the payload stub submitter, the real sweep handler,
and a fake engine whose timing model the curve must recover."""

import json
import sys
from pathlib import Path

import pytest
import requests
from sweep_fakes import FakeEngine, model_latency, model_util

from harness.runpod.preflight import PreflightError
from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_service_sweep as rss
import sweep_handler

LEVELS = [1, 2, 4, 8]


@pytest.fixture(autouse=True)
def no_network_and_an_endpoint_env(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the stub sweep touched the network")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.setenv("MODEL_REVISION", "b968826d9c46dd6066d109eabc6255188de91218")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")


def _submitter(engine, payloads=None):
    def worker(payload):
        if payloads is not None:
            payloads.append(payload)
        return sweep_handler.handler({"input": payload}, deps=engine.deps(sweep_handler.Deps))

    return PayloadStubSubmitter(worker).submit_payload


def _sweep(tmp_path, engine, **kw):
    args = {
        "submit_payload": _submitter(engine),
        "store_path": tmp_path / "sweep.jsonl",
        "out_path": tmp_path / "curve.json",
        "levels": LEVELS,
        "seed": 20261004,
        "source": "stub",
        "serve_args": ["--max-num-seqs", "256"],
    }
    args.update(kw)
    return rss.run_sweep(**args)


def test_the_curve_recovers_the_timing_model_with_three_interleaved_repeats(tmp_path):
    payloads = []
    engine = FakeEngine()
    doc = _sweep(tmp_path, engine, submit_payload=_submitter(engine, payloads))
    assert [p[0] for p in doc["points"]] == LEVELS
    for (c, latency, tps, util), row in zip(doc["points"], doc["levels"], strict=True):
        assert latency == pytest.approx(model_latency(c, repeat=1)), "median of three repeats"
        assert row["latency_s_range"] == pytest.approx(
            [model_latency(c, 0), model_latency(c, 2)]
        )
        assert tps == pytest.approx(16 * c / model_latency(c, 1))
        assert util == pytest.approx(model_util(c))
        assert row["n_runs"] == 3
    assert doc["source"] == "stub"
    assert doc["prompt_path"] == "exact"
    assert doc["engine"]["max_num_seqs"] == [256]
    assert len(payloads) == 3 * len(LEVELS)
    assert [p["num_prompts"] for p in payloads if p["level"] == 8] == [160] * 3
    on_disk = json.loads((tmp_path / "curve.json").read_text())
    assert on_disk["points"] == doc["points"]


def test_every_run_is_stored_in_schedule_order(tmp_path):
    _sweep(tmp_path, FakeEngine())
    rows = [json.loads(line) for line in (tmp_path / "sweep.jsonl").read_text().splitlines()]
    assert [r["run_index"] for r in rows] == list(range(12))
    assert all(r["outcome"] == "ok" for r in rows)
    levels_in_order = [r["level"] for r in rows]
    assert levels_in_order != sorted(levels_in_order), "repeats were not interleaved"


def test_an_interrupted_campaign_resumes_where_it_stopped(tmp_path):
    engine = FakeEngine()
    calls = []
    real = _submitter(engine)

    def flaky(payload):
        calls.append(payload["run_index"])
        if payload["run_index"] == 5 and calls.count(5) == 1:
            raise KeyboardInterrupt
        return real(payload)

    with pytest.raises(KeyboardInterrupt):
        _sweep(tmp_path, engine, submit_payload=flaky)
    doc = _sweep(tmp_path, engine, submit_payload=flaky, resume=True)
    assert calls == list(range(12))[:6] + list(range(5, 12))
    assert len(doc["points"]) == len(LEVELS)


def test_a_failed_run_is_stored_and_its_level_refused_until_the_bar_is_lowered(tmp_path):
    engine = FakeEngine(fail_measured_at=(4, 1))
    with pytest.raises(ValueError, match="level 4 has 2 successful runs"):
        _sweep(tmp_path, engine)
    rows = [json.loads(line) for line in (tmp_path / "sweep.jsonl").read_text().splitlines()]
    assert sum(r["outcome"] == "failed" for r in rows) == 1
    doc = rss.reduce_store(tmp_path / "sweep.jsonl", tmp_path / "curve.json", min_repeats=2,
                           meta={"source": "stub", "levels_requested": LEVELS})
    row4 = next(r for r in doc["levels"] if r["concurrency"] == 4)
    assert (row4["n_runs"], row4["n_failed"]) == (2, 1)


def test_a_diagnostic_pilot_stores_the_in_container_answers(tmp_path):
    doc = _sweep(tmp_path, FakeEngine(), levels=[1, 8], repeats=1, min_repeats=1,
                 diagnostics=True)
    rows = [json.loads(line) for line in (tmp_path / "sweep.jsonl").read_text().splitlines()]
    assert all("--save-detailed" in r["diagnostics"]["bench_help"]["stdout"] for r in rows)
    assert all(r["summary"]["raw_bench"]["itls"] for r in rows)
    assert [p[0] for p in doc["points"]] == [1, 8]


def test_the_pin_set_lives_in_the_script_and_requires_a_template():
    pins = rss.sweep_pins("tmpl-123")
    assert pins["templateId"] == "tmpl-123"
    assert pins["executionTimeoutMs"] == rss.EXECUTION_TIMEOUT_S * 1000
    assert pins["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090"]
    with pytest.raises(ValueError, match="template id is required"):
        rss.sweep_pins("")


def test_preflight_only_spends_nothing(monkeypatch, capsys):
    monkeypatch.setenv("RUNPOD_API_KEY", "k")
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: rss.sweep_pins("tmpl"))
    monkeypatch.setattr(rss, "RunPodSubmitter", None)
    rss.main(["--preflight-only", "--template-id", "tmpl"])
    assert "matches the sweep pin set" in capsys.readouterr().out


def test_a_drifted_endpoint_is_refused_before_any_job(monkeypatch):
    monkeypatch.setenv("RUNPOD_API_KEY", "k")
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    drifted = {**rss.sweep_pins("tmpl"), "executionTimeoutMs": 600000}
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: drifted)
    with pytest.raises(PreflightError, match="executionTimeoutMs"):
        rss.main(["--template-id", "tmpl", "--levels", "1,2", "--seed", "1",
                  "--store", "s.jsonl", "--out", "c.json"])


def test_missing_credentials_refuse_to_start(monkeypatch):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="RUNPOD_API_KEY"):
        rss.main(["--preflight-only", "--template-id", "tmpl"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_run_service_sweep.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'run_service_sweep'`.

- [ ] **Step 3: Create `scripts/run_service_sweep.py`**

```python
"""Run the single-engine service-curve sweep on a RunPod endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/run_service_sweep.py --preflight-only --template-id <id>
    .venv/bin/python scripts/run_service_sweep.py --template-id <id> \\
        --levels 1,2,4,8,16,32,64 --seed 20261004 --serve-args "--max-num-seqs 256" \\
        --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json
    .venv/bin/python scripts/run_service_sweep.py --reduce-only --levels 1,2,4,8,16,32,64 \\
        --min-repeats 2 --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json

Reads RUNPOD_API_KEY and RUNPOD_SWEEP_ENDPOINT_ID from the environment. The
endpoint's template must run `python3 -u /opt/sweep_handler.py`.

Refuses to spend unless the endpoint matches the sweep pin set below. Every
(level, repeat) is one job, stored as it lands; `--resume` continues an
interrupted campaign with the same --levels/--repeats/--seed. The curve is
written as plain tuples plus per-level intervals; artifact 2 turns it into a
`ServiceCurve` with scripts/a2_service_curve.py.

`--store` and `--out` have no defaults. Artifacts 2 and 4 both run this
script, and a shared default path would let one artifact's campaign resume
into the other's store, which the resume guard would accept whenever the
level lists happened to agree.
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.campaign import run_campaign
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from harness.service_sweep import (
    DEFAULT_MIN_PROMPTS,
    DEFAULT_REPEATS,
    DEFAULT_WAVES,
    SweepRun,
    build_sweep_record,
    job_payload,
    reduce_curve,
    sweep_schedule,
)
from harness.store import JsonlStore

# The endpoint's executionTimeoutMs, in seconds. The worker budgets each job
# against it (worker/sweep_handler.py), so it is pinned below as well: a
# larger platform limit would be harmless, a smaller one would kill jobs the
# worker believes it has time for, and they would return nothing.
EXECUTION_TIMEOUT_S = 1800
OUTPUT_LEN = 16  # artifact 1's max_tokens (worker/probe.py MAX_TOKENS)

# The sweep's boundary. Same GPU class and network volume as artifact 1
# (coldstart/pins.py), because artifact 2 inherits artifact 1's engine; the
# template is the sweep's own (dockerStartCmd overridden) and is passed in,
# since it is provisioned when the paid run is prepared. FlashBoot and
# workersMin are deliberately NOT pinned: they change startup, and the sweep
# measures nothing about startup.
SWEEP_PINNED_BASE = {
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "executionTimeoutMs": EXECUTION_TIMEOUT_S * 1000,
}


def sweep_pins(template_id: str) -> dict:
    if not template_id:
        raise ValueError(
            "a template id is required; without it the preflight would accept an "
            "endpoint running any image and any start command"
        )
    return {**SWEEP_PINNED_BASE, "templateId": template_id}


def run_sweep(
    *,
    submit_payload,
    store_path,
    out_path,
    levels,
    seed: int,
    source: str,
    repeats: int = DEFAULT_REPEATS,
    serve_args=(),
    waves: int = DEFAULT_WAVES,
    min_prompts: int = DEFAULT_MIN_PROMPTS,
    output_len: int = OUTPUT_LEN,
    min_repeats: int = DEFAULT_REPEATS,
    resume: bool = False,
    diagnostics: bool = False,
    on_run=None,
) -> dict:
    """Schedule -> one job per (level, repeat) -> JSONL -> curve JSON.

    `submit_payload` is `RunPodSubmitter.submit_payload` for a paid run and
    `PayloadStubSubmitter.submit_payload` in tests. `source` ("runpod" or
    "stub") is written into the curve so a stub curve can never be mistaken
    for a measured one downstream.
    """
    schedule = sweep_schedule(levels, repeats=repeats, seed=seed)
    store = JsonlStore(store_path, SweepRun)

    def submit(scheduled, run_id):
        return submit_payload(
            job_payload(
                scheduled,
                run_id,
                serve_args=serve_args,
                output_len=output_len,
                job_budget_s=EXECUTION_TIMEOUT_S,
                seed=seed,
                waves=waves,
                min_prompts=min_prompts,
                diagnostics=diagnostics,
            )
        )

    run_campaign(
        schedule,
        submit,
        build_sweep_record,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        on_run=on_run,
        resume=resume,
    )
    meta = {
        "source": source,
        "levels_requested": list(levels),
        "repeats": repeats,
        "seed": seed,
        "serve_args": list(serve_args),
        "output_len": output_len,
        "waves": waves,
        "min_prompts": min_prompts,
    }
    return reduce_store(store_path, out_path, min_repeats=min_repeats, meta=meta)


def reduce_store(store_path, out_path, *, min_repeats: int, meta: dict) -> dict:
    records = JsonlStore(store_path, SweepRun).read_all()
    reduction = reduce_curve(
        records, min_repeats=min_repeats, expected_levels=meta.get("levels_requested")
    )
    doc = {**reduction.to_dict(), **meta, "min_repeats": min_repeats, "store": str(store_path)}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return doc


def _levels(text: str) -> list[int]:
    return [int(part) for part in text.split(",") if part.strip()]


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set; refusing to start (see this script's docstring)")
    return value


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--template-id")
    ap.add_argument("--levels", type=_levels)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--serve-args", default="", help="extra `vllm serve` flags, one string")
    ap.add_argument("--waves", type=int, default=DEFAULT_WAVES)
    ap.add_argument("--min-prompts", type=int, default=DEFAULT_MIN_PROMPTS)
    ap.add_argument("--min-repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--store")
    ap.add_argument("--out")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--diagnostics", action="store_true",
                    help="first paid run only: in-container checks and the raw bench JSON")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--reduce-only", action="store_true")
    args = ap.parse_args(argv)

    if args.reduce_only:
        if not (args.store and args.out):
            ap.error("--reduce-only needs --store and --out")
        meta = {"source": "runpod"}
        if args.levels:
            meta["levels_requested"] = args.levels
        reduce_store(args.store, args.out, min_repeats=args.min_repeats, meta=meta)
        print(f"[reduce] wrote {args.out}", flush=True)
        return

    key, endpoint_id = _require("RUNPOD_API_KEY"), _require("RUNPOD_SWEEP_ENDPOINT_ID")
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key), sweep_pins(args.template_id))
    print(f"[preflight] endpoint {endpoint_id} matches the sweep pin set", flush=True)
    if args.preflight_only:
        return
    missing = [f for f in ("levels", "seed", "store", "out") if getattr(args, f) is None]
    if missing:
        ap.error(f"a paid run needs --{', --'.join(missing)}")

    def progress(record):
        detail = record.status.get("failure_class") or ""
        print(
            f"[run {record.run_index:>3}] c={record.level:<4} repeat={record.repeat} "
            f"{record.outcome:<6} {detail}",
            flush=True,
        )

    doc = run_sweep(
        submit_payload=RunPodSubmitter(HttpTransport(endpoint_id, key)).submit_payload,
        store_path=args.store,
        out_path=args.out,
        levels=args.levels,
        seed=args.seed,
        source="runpod",
        repeats=args.repeats,
        serve_args=shlex.split(args.serve_args),
        waves=args.waves,
        min_prompts=args.min_prompts,
        min_repeats=args.min_repeats,
        resume=args.resume,
        diagnostics=args.diagnostics,
        on_run=progress,
    )
    print(f"[done] {len(doc['points'])} levels; curve={args.out}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_run_service_sweep.py -q`
Expected: 9 passed.

- [ ] **Step 5: Check the command line refuses to spend without credentials**

```bash
env -u RUNPOD_API_KEY PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --preflight-only --template-id x; echo "exit=$?"
```

Expected: `RUNPOD_API_KEY is not set; refusing to start (see this script's docstring)` and `exit=1`. No request is made.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/python -m ruff check scripts/run_service_sweep.py tests/test_run_service_sweep.py
git add scripts/run_service_sweep.py tests/test_run_service_sweep.py
git commit -m "feat: run_service_sweep -- preflight, one job per level and repeat, curve JSON"
```

---

## Task 12: Artifact 2's adapter — tuples to a measured `ServiceCurve`

The harness emits tuples; artifact 2 adapts them on its own side. `scripts/a2_service_curve.py` builds a `ServiceCurve` (whose constructor re-validates every point), sets `measured` only when the sweep's `source` is `"runpod"`, and records `max_num_seqs`, which `docs/recon-a2.md` (Q3, "the pilot sweep should record it") requires. It refuses a curve that does not carry exactly one `max_num_seqs`, and it flags a top level above that limit, because the curve's top level becomes the simulator's per-replica admission cap (`autoscale/sim.py`).

**Files:**
- Create: `scripts/a2_service_curve.py`, `tests/test_a2_service_curve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_a2_service_curve.py`:

```python
"""Artifact 2's adapter from the sweep's tuples to a `ServiceCurve`."""

import json
import sys
from pathlib import Path

import pytest
import requests
from sweep_fakes import FakeEngine, model_latency

from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

import a2_service_curve as a2
import run_service_sweep as rss
import sweep_handler


def _doc(source="runpod", max_num_seqs=(256,), top=64):
    return {
        "source": source,
        "points": [[1, 0.31, 51.6, 0.15], [top, 0.95, 1077.9, 0.99]],
        "levels": [{"concurrency": 1}, {"concurrency": top}],
        "statistic": "per run: ...",
        "prompt_path": "exact",
        "served_cmd": ["vllm", "serve", "m", "--port", "8000", "--max-num-seqs", "256"],
        "engine": {"max_num_seqs": list(max_num_seqs), "max_num_seqs_source": ["non-default-args"]},
    }


def test_a_measured_sweep_becomes_a_measured_curve_with_its_cap_recorded():
    curve, meta = a2.build_service_curve(_doc())
    assert curve.measured is True
    assert curve.points == ((1, 0.31, 51.6, 0.15), (64, 0.95, 1077.9, 0.99))
    assert meta["max_num_seqs"] == 256
    assert meta["max_num_seqs_source"] == "non-default-args"
    assert meta["top_level_above_max_num_seqs"] is False


def test_a_top_level_above_the_engines_limit_is_flagged():
    _, meta = a2.build_service_curve(_doc(top=512))
    assert meta["top_level_above_max_num_seqs"] is True


def test_a_stub_sweep_converts_but_is_never_measured():
    curve, meta = a2.build_service_curve(_doc(source="stub"))
    assert curve.measured is False
    assert meta["measured"] is False


@pytest.mark.parametrize("values", [(), (None,), (256, 512)])
def test_max_num_seqs_must_be_exactly_one_recorded_value(values):
    with pytest.raises(ValueError, match="max_num_seqs"):
        a2.build_service_curve(_doc(max_num_seqs=values))


def test_service_curve_validation_still_applies():
    doc = _doc()
    doc["points"][1][3] = 1.2
    with pytest.raises(ValueError, match="outside"):
        a2.build_service_curve(doc)


def test_the_written_file_loads_back_as_the_same_curve(tmp_path):
    (tmp_path / "sweep.json").write_text(json.dumps(_doc()))
    a2.main(["--curve", str(tmp_path / "sweep.json"), "--out", str(tmp_path / "a2.json")])
    curve = a2.load_service_curve(tmp_path / "a2.json")
    assert curve == a2.build_service_curve(_doc())[0]


def test_end_to_end_from_the_stub_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "post", None)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.delenv("MODEL_REVISION", raising=False)
    monkeypatch.delenv("MAX_MODEL_LEN", raising=False)
    engine = FakeEngine()
    submit = PayloadStubSubmitter(
        lambda p: sweep_handler.handler({"input": p}, deps=engine.deps(sweep_handler.Deps))
    ).submit_payload
    doc = rss.run_sweep(
        submit_payload=submit, store_path=tmp_path / "s.jsonl", out_path=tmp_path / "c.json",
        levels=[1, 4, 16], seed=7, source="stub", serve_args=["--max-num-seqs", "256"],
    )
    curve, meta = a2.build_service_curve(doc)
    assert curve.measured is False
    assert curve.latency_at(4) == pytest.approx(model_latency(4, 1))
    assert meta["max_num_seqs"] == 256
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_service_curve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'a2_service_curve'`.

- [ ] **Step 3: Create `scripts/a2_service_curve.py`**

```python
"""Artifact 2's side of the service-curve sweep: tuples in, `ServiceCurve` out.

    .venv/bin/python scripts/a2_service_curve.py \\
        --curve data/a2/service-sweep-curve.json --out data/a2/service-curve.json

The harness reduction emits plain tuples so that no artifact's types leak into
another's (artifact 5 bans `autoscale`). This adapter is where artifact 2
takes them: it builds a `ServiceCurve`, which re-validates every point, and it
records `max_num_seqs`, which docs/recon-a2.md requires the pilot sweep to
record rather than assume -- the curve's top level becomes the simulator's
per-replica admission cap, and whether that cap is the engine's own limit or
something below it changes what the cap means.

`measured` is True only for a curve whose `source` is "runpod". A stub curve
still converts, so the GPU-free tests exercise this path, but as
`measured=False`, the flag artifact 2's figures already print as NOT MEASURED.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.service import ServiceCurve


def max_num_seqs_of(curve_doc: dict) -> tuple[int, str]:
    """The one max_num_seqs every successful run reported, and where it was read."""
    engine = curve_doc.get("engine") or {}
    values = engine.get("max_num_seqs") or []
    sources = engine.get("max_num_seqs_source") or []
    if len(values) != 1 or values[0] is None:
        raise ValueError(
            f"the sweep's runs reported max_num_seqs {values!r}, not exactly one value; "
            "docs/recon-a2.md requires it recorded, and the curve's top level cannot "
            "be read as a per-replica cap without it. Pass --max-num-seqs explicitly "
            "in the sweep's --serve-args so the engine logs it"
        )
    return values[0], sources[0] if len(sources) == 1 else "mixed"


def build_service_curve(curve_doc: dict) -> tuple[ServiceCurve, dict]:
    max_num_seqs, source = max_num_seqs_of(curve_doc)
    curve = ServiceCurve(
        points=[tuple(p) for p in curve_doc["points"]],
        measured=curve_doc.get("source") == "runpod",
    )
    meta = {
        "measured": curve.measured,
        "points": [list(p) for p in curve.points],
        "levels": curve_doc["levels"],
        "statistic": curve_doc["statistic"],
        "prompt_path": curve_doc["prompt_path"],
        "served_cmd": curve_doc["served_cmd"],
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
        "top_level_above_max_num_seqs": curve.max_measured_concurrency > max_num_seqs,
        "sweep_source": curve_doc.get("source"),
    }
    return curve, meta


def load_service_curve(path) -> ServiceCurve:
    doc = json.loads(Path(path).read_text())
    return ServiceCurve(points=[tuple(p) for p in doc["points"]], measured=doc["measured"])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--curve", required=True, help="run_service_sweep.py's --out file")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    curve, meta = build_service_curve(json.loads(Path(args.curve).read_text()))
    meta["source_curve"] = args.curve
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    label = "MEASURED" if curve.measured else "NOT MEASURED (stub)"
    print(f"[a2] {len(curve.points)} points, max_num_seqs={meta['max_num_seqs']}, {label}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, and artifact 2's existing boundary test**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_service_curve.py tests/test_autoscale_boundary.py tests/test_service.py -q`
Expected: all pass (9 new). `autoscale/service.py` is not modified.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check scripts/a2_service_curve.py tests/test_a2_service_curve.py
git add scripts/a2_service_curve.py tests/test_a2_service_curve.py
git commit -m "feat: artifact 2's adapter from sweep tuples to a ServiceCurve, max_num_seqs recorded"
```

---

## Task 13: Import boundaries, and the harness README

`tests/test_harness_boundary.py` parses direct imports, so it cannot see a module that imports something which imports `coldstart`. These tests import each shared module in a fresh interpreter and inspect `sys.modules`, the pattern plan 2a uses for `autoscale/validation_band.py`, for both `coldstart` and `autoscale`. A static check that no harness file imports `autoscale` sits beside them, and the sweep handler gets the same fresh-interpreter check, since it must run in the image without artifact 1's package.

**Files:**
- Create: `tests/test_shared_tooling_boundary.py`
- Modify: `harness/README.md` (the table, and the "Not yet here" section)

- [ ] **Step 1: Write the tests**

Create `tests/test_shared_tooling_boundary.py`:

```python
"""The shared in-container tooling loads no artifact's package.

`tests/test_harness_boundary.py` parses direct imports. That misses a module
that imports something which imports coldstart, so this file imports each new
module in a fresh interpreter and inspects `sys.modules` afterwards, the
pattern plan 2a uses for `autoscale/validation_band.py`. `autoscale` is banned
as well as `coldstart`: artifact 5's package refuses to load `autoscale`, and
it imports these modules.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BANNED = ("coldstart", "autoscale")
SHARED = [
    "harness.serve",
    "harness.bench",
    "harness.gpu_util",
    "harness.campaign",
    "harness.submit",
    "harness.runpod.submitter",
    "harness.service_sweep",
    "harness.sweep_worker",
]


def _loaded_after_import(module: str, extra_path: str | None = None) -> list[str]:
    prelude = f"sys.path.insert(0, {extra_path!r}); " if extra_path else ""
    code = (
        f"import importlib, json, sys; {prelude}importlib.import_module({module!r}); "
        "print(json.dumps(sorted(sys.modules)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return json.loads(out.stdout)


@pytest.mark.parametrize("module", SHARED)
def test_importing_a_shared_module_loads_no_artifact_package(module):
    banned = [m for m in _loaded_after_import(module) if m.split(".")[0] in BANNED]
    assert banned == [], (
        f"importing {module} loads {banned}; artifacts 4 and 5 import this module, "
        "and artifact 5 refuses to load autoscale, so the shared tooling would stop "
        "being shareable"
    )


def test_the_sweep_handler_runs_without_artifact_one():
    banned = [
        m
        for m in _loaded_after_import("sweep_handler", str(REPO / "worker"))
        if m.split(".")[0] in BANNED
    ]
    assert banned == [], (
        f"worker/sweep_handler.py loads {banned}; the sweep would then depend on "
        "artifact 1's package being importable in the image"
    )


def test_no_harness_module_imports_autoscale():
    offenders = []
    for path in sorted((REPO / "harness").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "autoscale" for n in names):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        f"{offenders} import autoscale; the harness serves artifacts that ban it. "
        "Emit plain values and let artifact 2 adapt them"
    )
```

- [ ] **Step 2: Run them; they should pass, so prove they can fail**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_shared_tooling_boundary.py -q -o addopts=""
cp harness/service_sweep.py build/service_sweep.py.bak
sed -i '' 's/^from harness.stats import median$/from harness.stats import median\nimport autoscale.service  # noqa: F401/' harness/service_sweep.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_shared_tooling_boundary.py -q -o addopts="" | tail -1
cp build/service_sweep.py.bak harness/service_sweep.py && cmp harness/service_sweep.py build/service_sweep.py.bak && echo restored
```

Expected: `10 passed`; then `2 failed, 8 passed` (the fresh-interpreter test for `harness.service_sweep` and the static check); then `restored`. A boundary test that has never failed is not known to work.

- [ ] **Step 3: Update `harness/README.md`**

In the "What is here" table, replace the `submit.py` and `runpod/` rows:

```markdown
| `submit.py` | The submitter interface (`SubmitOutcome`) and an in-process stub for the GPU-free loop. |
| `runpod/` | Endpoint preflight, job lifecycle extraction, and a retrying HTTP client. |
```

with:

```markdown
| `submit.py` | The submitter interface (`SubmitOutcome`), an in-process stub for artifact 1's `submit(arm, run_id)`, and `PayloadStubSubmitter` for workers that take a whole payload. |
| `runpod/` | Endpoint preflight, job lifecycle extraction, a retrying HTTP client, and `submit_payload` for any JSON job input. |
| `campaign.py` | The campaign loop: schedule → submit → record → store, never retried, with the resume drift guard. The artifact passes its own `submit` and `build_record`. |
| `serve.py` | `served(model, *, args, env, port=8000, health_timeout=900.0)`: `vllm serve` in its own process group, health-waited, yielded healthy or not, with an idempotent `stop() -> float`. |
| `bench.py` | `run_bench(...)`: one `vllm bench serve` run, warm-ups and ready check pinned off, its saved JSON returned unaltered. |
| `gpu_util.py` | `nvidia-smi` `utilization.gpu` sampled every 0.5 s on a thread while a run is in flight; median as a fraction, raw samples kept. |
| `service_sweep.py` | The single-engine service-curve sweep's local side: interleaved schedule, job payload, `SweepRun` record, and the reduction to plain `(concurrency, latency_s, throughput_tps, gpu_util)` tuples with min–max intervals. |
| `sweep_worker.py` | One sweep run inside the worker: exact-prompt probe with a recorded random fallback, one warm-up wave, the measured run, the compact summary. |
```

Then replace the whole `## Not yet here` section (from that heading to the end of the file) with:

```markdown
## Where the shared tooling is used

`worker/sweep_handler.py` runs one sweep job inside the image, selected by the
template's `dockerStartCmd`; `scripts/run_service_sweep.py` drives a sweep
from a laptop and keeps its pin set (pins never live here); artifact 2 turns
the curve into its `ServiceCurve` in `scripts/a2_service_curve.py`.

## Still not here

Exact-timestamp trace replay through `vllm bench serve` is unverified and out
of scope. The discrete-event simulators live with their artifacts:
`autoscale/` for artifact 2, and artifact 4's own package for its placement
simulator. Nothing here imports `autoscale` either:
`tests/test_shared_tooling_boundary.py` checks it in a fresh interpreter.
```

- [ ] **Step 4: Run the boundary tests and lint, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_shared_tooling_boundary.py tests/test_harness_boundary.py -q -o addopts=""
.venv/bin/python -m ruff check tests/test_shared_tooling_boundary.py
git add tests/test_shared_tooling_boundary.py harness/README.md
git commit -m "test: the shared tooling loads neither coldstart nor autoscale; README lists it"
```

Expected: `15 passed`; `All checks passed!`

---

## Task 14: Move artifact 1's driver onto the lifted loop; delete the old loop last

Artifact 5 plan 1 Task 3 Steps 5–7, with the code verbatim, run here — after every other task — so that deleting the old loop is the last code change in the plan, and only after it is proven byte-identical. The old loop is kept as `_legacy_run_campaign` for exactly one comparison, then deleted as this task's last step.

What changes and what does not is Task 1's log A: every row is Preserved; the two drift-guard messages change wording (rows 9–10), and no test asserts the old wording. **If the parity gates in Steps 4–6 fail and cannot be fixed, revert this task's edit to `coldstart/driver.py` (`git checkout coldstart/driver.py`) and record in `harness/campaign.py`'s module docstring that `coldstart/driver.py` keeps a duplicate loop.** That is the amendment's stated fallback (artifact 5 plan 1 Task 3 Step 7). Then stop and tell the owner.

**Files:**
- Modify: `coldstart/driver.py` (imports, lines 3–8; `run_campaign`'s body, lines 192–228 at `39c20b3`)

- [ ] **Step 1: Confirm the baseline from Task 1 is present**

```bash
ls build/shared-tooling-baseline/before/
```

Expected: `campaign.jsonl  drift_messages.txt  on_run.txt  resumed.jsonl`. If it is missing (a fresh clone, a cleaned `build/`), check out the commit Task 1 ran on into a temporary worktree and re-run Task 1 Steps 5–6 there; never capture a "before" from code that already changed.

- [ ] **Step 2: Add the harness import**

In `coldstart/driver.py`, add this import among the other `harness` imports (between `from coldstart.schema import RunRecord` and `from harness.failures import classify_failure`):

```python
from harness.campaign import run_campaign as harness_run_campaign
```

- [ ] **Step 3: Keep the old loop under a new name, and give `run_campaign` the new body**

First, append this function at the end of `coldstart/driver.py`, after two blank lines. Its body is the current body of `run_campaign`, lines 192–228, unchanged:

```python
def _legacy_run_campaign(submitter, store, arms, triples, seed, on_run=None, resume=False):
    """The loop as it was before the migration onto harness.campaign.

    Kept for exactly one comparison: Task 14 Step 5 runs it beside the new
    run_campaign and compares their stored bytes. Deleted in Step 8.
    """
    schedule = build_schedule(conditions=arms, blocks=triples, seed=seed)
    done: set[int] = set()
    if resume:
        arm_by_index = {s.run_index: s.condition for s in schedule}
        for r in store.read_all():
            expected_arm = arm_by_index.get(r.run_index)
            if expected_arm is None:
                raise ValueError(
                    f"resume: stored run_index {r.run_index} falls beyond the "
                    f"rebuilt schedule, which only covers 0..{len(schedule) - 1} "
                    f"for the given arms/triples/seed. This means resume was "
                    f"called with different schedule parameters (e.g. fewer "
                    f"triples) than produced the stored data -- resume must use "
                    f"the exact arms/triples/seed of the original window."
                )
            if r.arm != expected_arm:
                raise ValueError(
                    f"resume: stored run_index {r.run_index} has arm "
                    f"{r.arm!r} on disk, but the rebuilt schedule assigns it "
                    f"arm {expected_arm!r}. This means resume was called with "
                    f"different arms/triples/seed than produced the stored "
                    f"data, which would splice two different interleavings "
                    f"together -- resume must use the exact arms/triples/seed "
                    f"of the original window."
                )
            done.add(r.run_index)
    for scheduled in schedule:
        if scheduled.run_index in done:
            continue
        run_id = _new_run_id()
        outcome = submitter.submit(arm=scheduled.condition, run_id=run_id)
        record = _record_from(scheduled, run_id, outcome)
        record.host["triple_index"] = scheduled.block_index
        store.append(record)
        if on_run:
            on_run(record)
    return store
```

Then keep `run_campaign`'s signature, `(submitter, store, arms, triples, seed, on_run=None, resume=False)`, and its docstring exactly as they are, and replace everything in its body after the docstring with (artifact 5's code, verbatim):

```python
    schedule = build_schedule(conditions=arms, blocks=triples, seed=seed)

    def submit(scheduled, run_id):
        return submitter.submit(arm=scheduled.condition, run_id=run_id)

    def build_record(scheduled, run_id, outcome):
        record = _record_from(scheduled, run_id, outcome)
        record.host["triple_index"] = scheduled.block_index
        return record

    return harness_run_campaign(
        schedule,
        submit,
        build_record,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.arm,
        make_run_id=_new_run_id,
        on_run=on_run,
        resume=resume,
    )
```

The new body keeps the old body's two artifact-1 calls — `submitter.submit(arm=scheduled.condition, ...)` and `record.host["triple_index"] = scheduled.block_index` — moved into `submit` and `build_record`. `make_run_id=_new_run_id` is resolved when `run_campaign` is called, so a test or the baseline script that replaces `driver._new_run_id` still controls the ids.

- [ ] **Step 4: Run artifact 1's driver, end-to-end and campaign tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_driver.py tests/test_end_to_end.py tests/test_harness_campaign.py -q -o addopts=""`
Expected: `35 passed` at `39c20b3` (Task 1's 29 plus artifact 5's 6). `test_resume_rejects_a_drifted_seed` and `test_resume_rejects_a_shrunk_schedule` pass on the new wording, because they assert `"run_index 0"`, `"C"`, `"A"`, `"run_index"` and `"beyond"`, which both wordings contain. This is the deliberate handling of the "arm" → "condition" change: the assertions are not edited.

- [ ] **Step 5: Compare old and new loops byte for byte against the baseline**

```bash
rm -rf build/shared-tooling-baseline/new build/shared-tooling-baseline/legacy
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python build/shared-tooling-baseline/driver_baseline.py build/shared-tooling-baseline/new
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python build/shared-tooling-baseline/driver_baseline.py build/shared-tooling-baseline/legacy legacy
for f in campaign.jsonl on_run.txt resumed.jsonl drift_messages.txt; do
  for v in legacy new; do
    cmp -s build/shared-tooling-baseline/before/$f build/shared-tooling-baseline/$v/$f && echo "$v $f: identical" || echo "$v $f: DIFFERS"
  done
done
cat build/shared-tooling-baseline/new/drift_messages.txt
```

Expected:

```
legacy campaign.jsonl: identical
new campaign.jsonl: identical
legacy on_run.txt: identical
new on_run.txt: identical
legacy resumed.jsonl: identical
new resumed.jsonl: identical
legacy drift_messages.txt: identical
new drift_messages.txt: DIFFERS
resume: stored run_index 0 has condition 'C' on disk, but the rebuilt schedule assigns it 'A'. Resume was called with different schedule parameters than produced the stored data, which would splice two interleavings together -- it must use the exact ones of the original window.
resume: stored run_index 6 falls beyond the rebuilt schedule, which only covers 0..5. Resume was called with different schedule parameters than produced the stored data -- it must use the exact ones of the original window.
```

The stored records (every byte of 12 records), the `on_run` sequence including `triple_index`, and an interrupted-then-resumed window are identical; only the two messages differ, exactly as Task 1's rows 9–10 decided. Any other `DIFFERS` is a parity failure: stop.

- [ ] **Step 6: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: last line `PARITY OK`. This runs the whole suite and ruff too.

- [ ] **Step 7: Confirm the callers still import and run**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
import run_window, prime_compile_cache
print('callers import: run_window, prime_compile_cache')
"
```

Expected: `callers import: run_window, prime_compile_cache`. (Both call `run_campaign` with keywords Task 1's row 4 lists; the signature is unchanged.)

- [ ] **Step 8: Delete the old loop — the last change in this plan**

Delete the whole `_legacy_run_campaign` function from the end of `coldstart/driver.py` (its `def` line through its final `return store`), and nothing else. Then re-run every gate on the tree without it:

```bash
grep -n "_legacy_run_campaign\|done: set\[int\]\|arm_by_index" coldstart/driver.py; echo "grep exit=$?"
rm -rf build/shared-tooling-baseline/final
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python build/shared-tooling-baseline/driver_baseline.py build/shared-tooling-baseline/final
for f in campaign.jsonl on_run.txt resumed.jsonl; do
  cmp -s build/shared-tooling-baseline/before/$f build/shared-tooling-baseline/final/$f && echo "$f: identical" || echo "$f: DIFFERS"
done
cmp -s build/shared-tooling-baseline/new/drift_messages.txt build/shared-tooling-baseline/final/drift_messages.txt && echo "drift_messages.txt: as Step 5"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_driver.py tests/test_end_to_end.py tests/test_harness_campaign.py -q -o addopts=""
./scripts/parity_check.sh 2>&1 | tail -1
```

Expected: the `grep` prints nothing and `grep exit=1`; three `identical` lines; `drift_messages.txt: as Step 5`; `35 passed`; `PARITY OK`.

- [ ] **Step 9: Commit**

```bash
git add coldstart/driver.py
git commit -m "refactor: artifact 1's driver calls the harness campaign loop; the old loop is gone"
```

---

## Task 15: Full verification, the parity audit, and the paid-run checklist

Nothing in this task changes code. It proves the plan's end state and writes down — here, in this plan — what the owner checks before and during the first paid run. **The paid run itself is not a step of this plan.**

**Files:** none modified.

- [ ] **Step 1: The full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: exit 0. Then `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --collect-only -o addopts="" -q | tail -1` must show at least Task 1's count plus 149 (this plan adds 149 tests: 6 + 5 + 8 + 12 + 19 + 10 + 20 + 25 + 15 + 1 + 9 + 9 + 10). Fewer means a file stopped being collected: stop.

- [ ] **Step 2: Lint**

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 3: The parity gate**

Run: `./scripts/parity_check.sh`
Expected: last line `PARITY OK`.

- [ ] **Step 4: The parity audit — every Preserved capability, exercised**

Every row of Task 1's logs A and B is exercised by a test that ran green in Step 1, or by Task 14's byte comparison:

| Task 1 row | Exercised by |
|---|---|
| A1 run id before submit; A12 one keyword `submit` per run | Task 14 Step 5 (`on_run.txt`, `campaign.jsonl` identical with counter ids); `tests/test_harness_campaign.py::test_run_ids_are_generated_by_the_caller_supplied_factory`; `tests/test_driver.py` cache-path tests (`resolve(record.arm).env(record.run_id)`) |
| A2–A3 `_record_from`, both paths | `tests/test_driver.py::test_a_failed_run_keeps_the_evidence_of_why_it_failed`, `::test_records_keep_the_raw_engine_log`, the `arm_state_unverifiable` tests; Task 14 Step 5 bytes |
| A4 signature; A5 docstring | Task 14 Step 7; `git diff 39c20b3 -- coldstart/driver.py` shows the docstring untouched |
| A6 schedule; A11 skip done; A14 append/on_run/return | Task 14 Step 5 (`resumed.jsonl` identical after an interrupt); `tests/test_harness_campaign.py::test_resume_skips_what_is_stored_and_keeps_the_schedule` |
| A7 resume off by default | `tests/test_driver.py::test_resume_is_off_by_default`; `tests/test_harness_campaign.py::test_resume_is_off_by_default` |
| A8–A10 drift guards, before any job | `tests/test_driver.py::test_resume_rejects_a_drifted_seed`, `::test_resume_rejects_a_shrunk_schedule`; Task 14 Step 5 messages |
| A13 `triple_index` | Task 14 Step 5 `on_run.txt` carries it per record |
| B (all) `submit` payload, clock A, unhealthy diagnostics, failures as data, `KeyboardInterrupt` escapes | `tests/test_harness_submit_payload.py`; `tests/test_runpod_submitter.py` (16 tests) |

Confirm with `git diff 39c20b3 --stat -- coldstart/ scripts/run_window.py scripts/prime_compile_cache.py`: only `coldstart/driver.py` changed.

- [ ] **Step 5: The tree holds only what this plan meant to add**

```bash
git status --porcelain
git log --oneline 39c20b3..HEAD
```

Expected: `git status` shows only files other sessions own (the untracked artifact 5 plans and amendment, if still untracked); `git log` shows this plan's 13 commits (Tasks 2–14). Nothing under `data/` or `docs/figures/` changed: `git diff 39c20b3 --stat -- data docs/figures` prints nothing.

- [ ] **Step 6: Tell the sessions that depend on this**

Artifact 5's session: `harness/campaign.py` and `submit_payload` are in, verbatim from its plan 1 Tasks 3–4; its prerequisite check for `served`/`run_bench` passes. Artifact 4's session: `served(...).stop()` returns seconds until the parent exits, not until memory is released (Task 5's docstring); `port` is per call and a busy port is refused.

### Paid-run checklist (for the owner; not a plan step)

**A. Image.** Push this plan's commits (the owner's call). CI (`build-worker.yml`) rebuilds the worker image because `worker/**` and `harness/**` changed, and its summary prints `ghcr.io/<repo>@sha256:...`. Pin the template to that digest, never a tag. The image's base, vLLM 0.27.1, is unchanged.

**B. Template (new; artifact 1's `mzadx4qugv` stays as it is).**
- Image: the digest from A.
- `dockerStartCmd`: `python3 -u /opt/sweep_handler.py`. On the default command every job fails with `KeyError: 'arm'` (artifact 1's handler), as recon/README.md warns for recon jobs.
- Environment: `MODEL_ID=Qwen/Qwen3-8B`, `MODEL_REVISION=b968826d9c46dd6066d109eabc6255188de91218`, `MAX_MODEL_LEN=8192` — artifact 1's values (the revision is in `fixtures/vllm_logs/startup_0.log`'s `non-default args:` line); copy them from artifact 1's template rather than retyping.
- Container disk as artifact 1's template; network volume `9c7ut2slrd` (weights under `HF_HOME=/runpod-volume/hf`).

**C. Endpoint (new; artifact 1's `ka5mryakkxumew` keeps matching its records).** GPU `NVIDIA GeForce RTX 4090`; `workersMin` 0; `workersMax` 1 (the cost ceiling; the driver submits one job at a time anyway); `idleTimeout` 5 s; `executionTimeoutMs` 1800000; the template from B. FlashBoot does not affect the sweep's measurement and is not pinned.

**D. Free preflight.**

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_SWEEP_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --preflight-only --template-id <template id>
```

Expected: `[preflight] endpoint <id> matches the sweep pin set`. If it reports `executionTimeoutMs: absent from the endpoint` (UNVERIFIED item 11), print the keys with `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import os; from harness.runpod.preflight import fetch_endpoint; print(sorted(fetch_endpoint(os.environ['RUNPOD_SWEEP_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY'])))"`, rename the key in `SWEEP_PINNED_BASE` and in `tests/test_run_service_sweep.py`, run the tests, commit, and preflight again. Never delete the pin to get past it.

**E. Cost estimate.** Jobs = levels × 3 (plus the pilot's 2). Per job ≈ startup (p95 86 s, artifact 1 arm B) + probe and `/tokenize` (~5 s) + one warm-up wave (latency) + the measured run (`max(100, 20c)/c × latency`) + teardown (≤ 30 s). Price = total seconds × RunPod's per-second rate for a 4090 serverless worker on the day (UNVERIFIED item 13), plus queue time for a cold image pull on the first job (once observed at 1898 s, `harness/runpod/submitter.py`). On the placeholder curve:

```bash
RATE_PER_S=<rate from RunPod's pricing page> PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import os
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as C
from harness.service_sweep import num_prompts_for
levels = [1, 2, 4, 8, 16, 32, 64]
repeats = 3
STARTUP_S, TEARDOWN_S, OVERHEAD_S = 86.0, 30.0, 5.0
per_level = {}
for c in levels:
    lat = C.latency_at(c)
    per_level[c] = STARTUP_S + OVERHEAD_S + lat + num_prompts_for(c) / c * lat + TEARDOWN_S
total_s = repeats * sum(per_level.values())
print({c: round(s, 1) for c, s in per_level.items()})
print(f"{len(levels) * repeats} jobs, {total_s / 60:.1f} GPU-minutes on the placeholder curve")
rate = float(os.environ["RATE_PER_S"])
print(f"about ${total_s * rate:.2f} at ${rate}/s, plus any cold image pull on the first job")
PY
```

Output on the placeholder curve: `21 jobs, 49.2 GPU-minutes`; at an illustrative `$0.00031/s` that is about `$0.92`. Re-run it with the levels actually chosen, and again after the pilot with its measured startup and latency.

**F. The diagnostic pilot: two jobs that answer the UNVERIFIED items.**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --template-id <template id> \
  --levels 1,8 --repeats 1 --min-repeats 1 --seed 20261004 --diagnostics \
  --serve-args "--max-num-seqs 256 --enable-log-requests" \
  --store build/sweep-pilot.jsonl --out build/sweep-pilot-curve.json
```

`--enable-log-requests` is for the pilot only (it adds log volume during measurement); the campaign does not pass it. Then read every answer:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json

FLAGS = [
    "--base-url", "--model", "--max-concurrency", "--num-prompts", "--seed", "--dataset-name",
    "--dataset-path", "--custom-output-len", "--skip-chat-template", "--random-input-len",
    "--random-output-len", "--random-range-ratio", "--random-prefix-len", "--ignore-eos",
    "--num-warmups", "--ready-check-timeout-sec", "--save-result", "--save-detailed",
    "--disable-tqdm", "--result-dir", "--result-filename", "--percentile-metrics",
    "--lora-modules", "--lora-assignment",
]
KEYS = ["duration", "completed", "failed", "ttfts", "itls", "output_lens", "errors",
        "input_lens", "median_e2el_ms", "output_throughput", "num_prompts", "max_concurrency"]
rows = [json.loads(line) for line in open("build/sweep-pilot.jsonl")]
for r in rows:
    print(f"--- run {r['run_index']} c={r['level']} {r['outcome']} {r['status'].get('failure_detail') or ''}")
    d = r.get("diagnostics") or {}
    help_text = (d.get("bench_help") or {}).get("stdout", "")
    print("  bench --help missing flags:", [f for f in FLAGS if f not in help_text])
    print("  pandas importable:", d.get("pandas_importable"), "| prompt in log:", d.get("prompt_in_log"))
    print("  nvidia-smi raw:", repr((d.get("nvidia_smi") or {}).get("stdout", "")[:40]))
    print("  engine:", {k: r["engine"].get(k) for k in ("max_num_seqs", "max_num_seqs_source",
                                                       "kv_capacity_tokens", "vllm_version")})
    if r["outcome"] != "ok":
        continue
    s = r["summary"]
    print("  saved JSON missing keys:", [k for k in KEYS if k not in s["raw_bench"]])
    print("  prompt:", s["prompt_path"], "tokens", s["prompt"]["prompt_tokens"],
          "engine input_lens", s["input_lens_unique"], "| probe_error:", s["prompt"]["probe_error"])
    gap_ms = (s["latency_s"] - s["bench_median_e2el_s"]) * 1000
    print(f"  latency {s['latency_s']:.4f} s vs tool median_e2el {s['bench_median_e2el_s']:.4f} s"
          f" (gap {gap_ms:+.2f} ms)")
    print("  gpu samples valid:", s["gpu"]["n_valid"], "of", s["gpu"]["n_samples"],
          "median", s["gpu_util"])
    print("  wall: clock_A", round(r["clock_A"]["t_result"] - r["clock_A"]["t_submit"], 1), "s;",
          "clock_C", r["clock_C"])
PY
```

| UNVERIFIED item | Look at | If it is not as assumed |
|---|---|---|
| 1 pandas in the image | `pandas importable`; `prompt:` path and `probe_error` | Fallback is automatic and recorded. Whether to accept it or add pandas to the image (which changes artifact 1's image too) is the owner's call — decide before the campaign; never mix paths (the reducer refuses). |
| 2 bench flags | `bench --help missing flags` must be `[]` | Fix the flag in `harness/bench.py` or `harness/sweep_worker.py` and their pinned tests before spending more. |
| 3 saved JSON keys | `saved JSON missing keys` must be `[]` | Same. |
| 4 reconstruction | `gap` within ±1 ms | Investigate before the campaign; the curve's latency column depends on it. |
| 5 tokenizer in the container | both runs `ok`; a failure detail mentioning the Hugging Face hub or a tokenizer | Pass `--tokenizer <local snapshot path>` through `extra_args` (a code change, with a test). |
| 6 prompt length vs a 16-token block | `tokens` and `engine input_lens` equal, and below 16 | At 16 or more, prefix caching serves the first block from cache on the exact path: record it as a limitation, or decide on `--no-enable-prefix-caching` in `--serve-args` (a configuration change from artifact 1, the owner's call). |
| 7 prompt logged | `prompt in log` | If False, the engine-side evidence is `input_lens == tokens` (the engine's own `usage.prompt_tokens`). |
| 8 `max_num_seqs` recorded | `engine: max_num_seqs 256, non-default-args` | If `None`, the line's format differs: fix `harness/sweep_worker.py`'s regex against a real log line from the record's `engine.log_lines`, with a test. |
| 9 nvidia-smi output | `nvidia-smi raw` an integer string; `gpu samples valid` > 0 | Fix `harness/gpu_util.py`'s parser with a test using the real output. |
| 10 child processes | (nothing to read) | Handled by group kill regardless. |
| 12 output size | both jobs completed | If a diagnostic job failed on size, re-run the pilot without `--diagnostics` for the checks that do not need the raw JSON. |
| — wall time | `clock_A`, `clock_C`, and the record's `summary.duration_s` | Feed into E. |

**G. The campaign.** Levels are the owner's decision (`docs/recon-a2.md` Q3: KV does not bind near 256; `max_num_seqs` 256 does; the top level becomes the simulator's per-replica cap). Fix the seed once and never change it between windows.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --template-id <template id> \
  --levels <ascending, comma-separated> --seed 20261004 --serve-args "--max-num-seqs 256" \
  --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json
# interrupted? the same command plus --resume
```

A level with a failed run fails the reduction with `level N has 2 successful runs`; the store keeps everything. Either re-run that level as its own new campaign and store, or accept two with `--reduce-only --levels ... --min-repeats 2` and say so where the curve is reported.

**H. Artifact 2's curve.**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_service_curve.py \
  --curve data/a2/service-sweep-curve.json --out data/a2/service-curve.json
```

Expected: `[a2] N points, max_num_seqs=256, MEASURED`. Wiring the measured curve into artifact 2's simulator and figures is artifact 2's plan 2b, not this plan.

---

## Open items found while writing this plan (not fixed here; other sessions' files)

- `docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md` lines 88–89 say plan 2a was not executed; it has been.
- `docs/superpowers/specs/2026-09-26-multi-lora-serving-harness-amendment.md` §1 (about lines 74–77) says harness extraction Tasks 4–13 have not started; they merged at `39c20b3`.
- The scope and amendment describe `served` and `run_bench` without saying what `.stop()`'s float measures or that `run_bench` takes extra keywords; this plan defines both (design-decisions table) and the owning sessions may want to record them.
- `autoscale/service.py`'s docstring says refusing to publish from an unmeasured curve is "enforced at the sweep boundary (not written yet)". Task 12 makes `measured` follow the sweep's `source`; the refusal itself belongs to artifact 2's figure code.

---

## Self-review

**Spec coverage.** Inventory and baseline: Task 1 (log A from the code, PARITY OK, collected count, both drift messages verbatim). `served` with merged env, `--port` added and duplicates refused, unhealthy yielded, early exit, own session and group kill, idempotent `stop()` with its float documented, drain thread: Task 5, tested against a fake `vllm` on `PATH` for healthy, never-healthy, early exit, port refusal, env merge, idempotent stop, group kill, SIGTERM-ignoring escalation, busy port, and exceptions in the block. `run_bench` with defaults for LoRA, the four pinned flags, `result_dir` created, JSON unaltered, verified against v0.27.1 with citations and an in-container check: Task 6 and Task 15 F. GPU sampler: Task 7. `harness/campaign.py` verbatim: Task 2. Driver migration with deletion last and the wording change handled: Task 14. `submit_payload` verbatim and a payload stub: Tasks 3–4. The sweep — caller-supplied levels, three interleaved repeats, a seeded order, one bench run per run with the sampler, per-run record with level, repeat, latency (computation stated), throughput, utilisation, TTFT, prompt path; a reducer to plain tuples with min–max; no `autoscale`: Tasks 8–9. Exact prompt with recorded fallback, flags and file pinned: Task 8. Handler within 1800 s, granularity justified, `healthy: True`, compact output, own COPY line and a guard: Task 10. Driver with preflight and pin set outside `harness/`, schedule, campaign, store, reduction, JSON: Task 11. Artifact-2 adapter with `max_num_seqs`: Task 12. Fresh-interpreter boundaries and the README: Task 13. Final suite, ruff, parity, paid-run checklist: Task 15.

**Placeholder scan.** No "TBD", "TODO", "similar to", or prose-only code steps. Values the plan cannot know are explicit runtime inputs, never placeholders in code: the template id (a required argument, refused when empty), the levels (an argument), RunPod's price (an environment variable for the estimate).

**Type consistency.** `served(model, *, args, env, port, health_timeout, ...)` → `Server` with `base_url`, `log_lines`, `healthy`, `cmd`, `returncode`, `drain_completed`, `stop()`; used so by `worker/sweep_handler.py` and `tests/sweep_fakes.FakeServer`. `run_bench(base_url, *, ..., extra_args, timeout, run)` → `dict`; called so by `sweep_worker.choose_prompt_path`/`run_one` and the fakes. `GpuUtilSampler.summary()` keys `gpu_util`, `samples`, `n_valid`, `n_samples`, `interval_s`, matched by `FakeSampler`. `PromptPlan(path, dataset_args, prompt_tokens, probe_error)`. `run_summary` keys `latency_s`, `ttft_median_s`, `throughput_tps`, `gpu_util`, `prompt_path` read by `build_sweep_record`. `job_payload` keys read by `handler`: `run_id`, `level`, `repeat`, `serve_args`, `num_prompts`, `warmup_prompts`, `output_len`, `job_budget_s`, `seed`, `diagnostics`. `CurveReduction.to_dict()` keys `points`, `levels`, `prompt_path`, `served_cmd`, `engine`, `statistic` read by `scripts/a2_service_curve.py`. `run_campaign(schedule, submit, build_record, store, *, index_of, condition_of, make_run_id, on_run, resume)` called so by Task 11 and Task 14.

**UI verification audit.** No task changes pixels.

**Parity audit.** First task inventories by reading the code (Task 1, with a re-verification grep and a rule to add rows). Every capability has a decision; none is dropped; the one operator-visible change (drift-guard wording) is flagged for owner acknowledgement. The baseline is captured before any change (Task 1 Steps 3–6: PARITY OK, counts, signature, stored bytes, messages). Deletion of the old loop is the last step of the last code task (Task 14 Step 8), gated on byte identity of stored records and on PARITY OK with old and new side by side (Steps 4–6), and re-verified after the deletion. Task 15 Step 4 maps each preserved capability to the test or comparison that exercised it.

**How this plan was checked.** Every code block was run on 2026-10-04 in a copy of the repository at `39c20b3` (outside the working tree): the 149 new tests passed, each new test file also passed on its own, `ruff check .` passed with the repository's configuration, the full suite passed apart from `test_git_tracks_every_published_figure`, which needs a git checkout the copy did not have, and the parity script's analysis and figure comparisons printed `PARITY OK` after the driver migration. The mutation checks in Tasks 5 and 13 were run and failed as described. Task 1's baseline script was run before and after the migration, with and without `legacy`, and produced exactly the comparisons Task 14 Step 5 expects.
