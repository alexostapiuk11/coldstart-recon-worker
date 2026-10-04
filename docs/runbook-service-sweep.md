# Runbook: the service-curve sweep's paid run

For the owner; not a plan step. Do not run any of this without the owner's say-so.

Every command and field name below was checked against the repository when this
was tracked (HEAD `c0e7c65` plus the commit that adds this file). The pilot reader in F,
`scripts/read_sweep_pilot.py`, is tested against a stub pilot store written by
`run_sweep` with the shared fakes (`tests/test_read_sweep_pilot.py`), so its output on
a real run will differ in values, not in shape. "UNVERIFIED item N" below is the numbering
of the list in `docs/superpowers/plans/2026-10-04-shared-in-container-tooling.md`.

**Owner/controller decisions this checklist carries out (all 2026-10-04):** three interleaved repeats per
level, median of the run medians, min–max as the interval; nvidia-smi sampler; artifact 1's exact prompt with
a recorded fallback; `--max-num-seqs 256` pinned; prefix caching off; any failed request is a run error.

**A. Image.** Push the plan's commits (the owner's call). CI (`build-worker.yml`) rebuilds the worker image
because `worker/**` and `harness/**` changed; its summary prints `ghcr.io/<repo>@sha256:...`. Pin the template
to that digest, never a tag. The base image, vLLM 0.27.1, is unchanged. The Dockerfile COPYs `worker/sweep_handler.py`
to `/opt/sweep_handler.py` (and `harness` as a directory); `tests/test_harness_boundary.py` fails if a `worker/*.py`
lacks its COPY.

**B. Template (new; artifact 1's `mzadx4qugv` stays as it is).**
- Image: the digest from A.
- `dockerStartCmd`: `python3 -u /opt/sweep_handler.py`. On the default command every job fails with
  `KeyError: 'arm'` (artifact 1's handler), as recon/README.md warns for recon jobs.
- Environment: `MODEL_ID=Qwen/Qwen3-8B`, `MODEL_REVISION=b968826d9c46dd6066d109eabc6255188de91218`,
  `MAX_MODEL_LEN=8192` — artifact 1's values; copy them from artifact 1's template rather than retyping.
  The handler reads `MODEL_ID` with no default (a missing one is a `KeyError`), and refuses `--revision` /
  `--max-model-len` in `--serve-args` because the environment owns them.
- Container disk as artifact 1's template; network volume `9c7ut2slrd` (weights under `HF_HOME=/runpod-volume/hf`).

**C. Endpoint (new; artifact 1's `ka5mryakkxumew` keeps matching its records).** GPU `NVIDIA GeForce RTX 4090`;
`workersMin` 0; `workersMax` 1 (the cost ceiling; the driver submits one job at a time anyway); `idleTimeout` 5 s;
`executionTimeoutMs` 1800000; the template from B. FlashBoot does not affect the sweep's measurement and is not pinned.

**D. Free preflight.** (The owner runs this; it is one GET and no job.)

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_SWEEP_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --preflight-only --template-id <template id>
```

Expected: `[preflight] endpoint <id> matches the sweep pin set`. If it reports `executionTimeoutMs: absent from the
endpoint` (UNVERIFIED item 11), print the keys with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import os; from harness.runpod.preflight import fetch_endpoint; print(sorted(fetch_endpoint(os.environ['RUNPOD_SWEEP_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY'])))"`,
rename the key in `SWEEP_PINNED_BASE` (`scripts/run_service_sweep.py`) and in `tests/test_run_service_sweep.py`, run the
tests, commit, and preflight again. Never delete the pin to get past it.

The preflight checks four things only: the GPU type, the network volume, `executionTimeoutMs` and
the template (`SWEEP_PINNED_BASE` plus the template id). `workersMin`, `workersMax` and `idleTimeout`
from C are not read back by it; set them by hand and look at them in the console.

**E. Cost estimate.** Jobs = levels x 3 (plus the pilot's 2). Per job = startup (p95 86 s, artifact 1 arm B, `data/analysis.json`) +
probe and `/tokenize` (~5 s) + one warm-up wave (latency) + the measured run (`max(100, 20c)/c x latency`) +
teardown (<= 30 s). Price = total seconds x RunPod's per-second rate for a 4090 serverless worker on the day
(UNVERIFIED item 13), plus queue time for a cold image pull on the first job (once observed at 1898 s,
`harness/runpod/submitter.py`). The script below was re-run at `c0e7c65`; it prints
`21 jobs, 49.2 GPU-minutes on the placeholder curve` and, at an illustrative `$0.00031/s`, `about $0.92`.

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

Re-run it with the levels actually chosen, and again after the pilot with its measured startup and latency.
It does not include a failed run's cost: a run with any failed request is a run error (below), is stored as
failed, and the level then needs a re-run (G), which is more jobs.

**F. The diagnostic pilot: two jobs that answer the UNVERIFIED items.**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --template-id <template id> \
  --levels 1,8 --repeats 1 --min-repeats 1 --seed 20261004 --diagnostics \
  --serve-args "--max-num-seqs 256 --enable-log-requests" \
  --store build/sweep-pilot.jsonl --out build/sweep-pilot-curve.json
```

The script appends `--no-enable-prefix-caching` to every job's serve args itself (prefix caching is pinned off;
the recorded `served_cmd` shows it). It does not choose `--max-num-seqs`: the command line above does, and a paid
run refuses to start without an explicit `--max-num-seqs N` in `--serve-args` (before any request is made),
because the engine logs its default only at DEBUG, so the curve could not record the binding concurrency limit,
and `scripts/a2_service_curve.py` would refuse it after the sweep was paid for. `--unrecorded-max-num-seqs` runs
without the pin anyway and prints that consequence; do not use it for a campaign whose curve artifact 2 will read.
`--preflight-only` and `--reduce-only` are not checked. `--enable-log-requests`
is for the pilot only (it adds a log line per request); the campaign does not pass it. If the pilot's store holds a
failed run, the reduction at the end of the command fails after the store is written; the store is what you read.

Then read every answer with the reader, which prints one block per stored run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/read_sweep_pilot.py build/sweep-pilot.jsonl
```

Per run it prints: the bench flags missing from the image's `--help`; whether pandas imports and the prompt reached
the engine log; nvidia-smi's raw output; the clock check; whether the serve command carries both pins and the engine's
`non-default args:` line shows prefix caching off; the engine facts (`max_num_seqs` and where it was read, KV
capacity, vLLM version) and the log cap; the saved-JSON keys that are missing; the prompt path, token count and the
engine's own input lengths; completed and failed requests with error samples; the reconstructed latency against the
tool's median; the GPU figure with its method and sample counts; and the wall-clock figures. A failed run prints its
failure detail and the engine facts only. The reader reports and never gates: each answer has a different remedy.

| UNVERIFIED item | Look at | If it is not as assumed |
|---|---|---|
| 1 pandas in the image | `pandas importable`; `prompt:` path and `probe_error` | Fallback is automatic and recorded. Whether to accept it or add pandas to the image (which changes artifact 1's image too) is the owner's call — decide before the campaign; never mix paths (the reducer refuses). |
| 2 bench flags | `bench --help missing flags` must be `[]` | Fix the flag in `harness/bench.py` or `harness/sweep_worker.py` and their pinned tests before spending more. A missing `--backend`/`--endpoint` means the pin itself is wrong for the image. |
| 3 saved JSON keys | `saved JSON missing keys` must be `[]` | Same. A missing `start_times` does not fail a run but turns the GPU figure into the whole-call median (see "GPU utilisation" below). |
| 4 reconstruction | `gap` within +-1 ms | Investigate before the campaign; the curve's latency column depends on it. |
| 5 tokenizer in the container | both runs `ok`; a failure detail mentioning the Hugging Face hub or a tokenizer | Pass `--tokenizer <local snapshot path>` through `extra_args` (a code change, with a test). |
| 6 prompt length vs a 16-token block | `tokens` and `engine input_lens` equal | Now low-stakes: prefix caching is pinned off, so the exact and fallback paths measure the same workload whatever the length. Record the token count. Still check the `non-default args` line below, because it is the proof that the pin reached the engine. |
| 6b prefix caching off reached the engine (new) | `serve cmd pins` both True; `non-default args line has prefix caching off: True`; the job did not fail to start | A job that never became healthy, with an argparse error naming `--no-enable-prefix-caching` in its log, means the flag spelling differs in the image: stop, fix `PREFIX_CACHING_OFF` in `scripts/run_service_sweep.py` and its tests. If the engine started but the line shows no `enable_prefix_caching`, the log format differs: read the `engine.log_lines` head and decide with the owner. |
| 7 prompt logged | `prompt in log` (computed over the whole engine log, before the 400/400 head/tail cap) | If False, the engine-side evidence is `input_lens == tokens` (the engine's own `usage.prompt_tokens`). |
| 8 `max_num_seqs` recorded | `engine: max_num_seqs 256, non-default-args` | If `None`, the line's format differs: fix `harness/sweep_worker.py`'s regex against a real line from `engine.log_lines` (the head holds startup), with a test. |
| 9 nvidia-smi output | `nvidia-smi raw` an integer string; `gpu samples valid` > 0 | Fix `harness/gpu_util.py`'s parser with a test using the real output. |
| 9b clock alignment (new) | `clocks: child_perf_counter_between` must be `True`; and the run's `gpu: ... windowed: True` | `False` means the sampler's `time.monotonic` and the tool's `time.perf_counter` do not share an epoch in the container: windowing will refuse and every run falls back to the whole-call median (`windowed: False`, a `window note`). Do not run the campaign on that figure without the owner's decision; the whole-call median includes the tool's idle startup and teardown. `None` means the child's output did not parse (read `diagnostics.clocks.child_cmd`). |
| 10 child processes | (nothing to read) | Handled by group kill regardless. |
| 12 output size | both jobs completed | If a diagnostic job failed on size, re-run the pilot without `--diagnostics` for the checks that do not need the raw JSON. The log is already capped at 400 head + 400 tail lines of at most 2000 chars; `log: N lines, truncated: ...` shows whether the cap cut anything. |
| — failed requests (new) | `requests: ... failed 0`; an `outcome` of `failed` with a detail beginning `N of M requests failed (at most 0 allowed)` | Any failed request is a run error, stored as a failed run with no latency. Read `error samples` (first three distinct, 300 chars). Do not lower the bar to get past it; fix the cause (a timeout at the top level is the likely one, and it is the level that becomes the admission cap). |
| — wall time | `clock_C` (`execution_ms`, `delay_ms`, from the platform), `clock_A` (submit to result, queue delay included, so not a run time) and `summary.duration_s` (the measured run only) | Feed `execution_ms` into E, not `clock_A`: a cold image pull once put 1898 s of queue delay in front of 140 s of execution (`harness/runpod/submitter.py`). `clock_C` is absent on a failed run. |

**GPU utilisation: how to read the figure.** `summary.gpu_util` (and the record's top-level `gpu_util`, which is what the
curve uses) is the median of the nvidia-smi samples taken between the earliest successful request's start and the
latest one's end, from the tool's `start_times` plus each request's latency, compared on the monotonic clock. Beside it:
`gpu_util_whole_call` (the median over every sample, idle startup and teardown included), `gpu_util_windowed`
(True when the window was used), `gpu_util_n_in_span` / `gpu_util_n_outside_span` (readable samples), `gpu_util_span_s`.
When windowing is unavailable the figure is the whole-call median, `gpu_util_windowed` is False and
`gpu_util_window_note` says why. A windowed run with no sample inside the span stores `gpu_util: None`, and the
reducer then refuses the store ("have no GPU utilisation reading"). Samples are 0.5 s apart and a run is about 20 waves of latency(level), 6-42 s on the placeholder curve, so a run has
roughly 12-80 samples in its span; treat the in-span count as the figure's sample size.
A sample within its own `query_s` of the span's edge can fall on either side of the true boundary. For the campaign,
check that every run says `windowed: True`. The reducer refuses a store whose successful runs disagree on
`gpu_util_windowed` (some windowed, some whole-call, or an older record that never said), with "the curve's
utilisation column would mix two measurements", because that would be two statistics under one label. The same
refusal applies to `--reduce-only`, which calls the same reducer. A pilot whose two runs differ therefore stores
both and then fails its reduction; read the store.

**G. The campaign.** Levels are the owner's decision (`docs/recon-a2.md` Q3: KV does not bind near 256;
`max_num_seqs` 256 does; the top level becomes the simulator's per-replica cap). Fix the seed once and never
change it between windows.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_service_sweep.py --template-id <template id> \
  --levels <ascending, comma-separated> --seed 20261004 --serve-args "--max-num-seqs 256" \
  --store data/a2/service-sweep.jsonl --out data/a2/service-sweep-curve.json
# interrupted? the same command plus --resume
```

The `--max-num-seqs` pin is required: without it (or `--unrecorded-max-num-seqs`) the command refuses before the
preflight. Do not pass `--diagnostics` or `--enable-log-requests`. Prefix caching stays off (the script adds the flag). Passing
`--serve-args=--enable-prefix-caching` (with the `=`) keeps it on and the script prints a warning; that is a different
experiment from artifact 5's and not what this checklist runs.

A level with a failed run (including one with a single failed request) fails the reduction with
`level N has 2 successful runs`; the store keeps everything, failed runs included, with the engine log head and tail,
`log_lines_total`, `log_truncated` and `log_head_lines`. Either re-run that level as its own new campaign and store, or
accept two with `--reduce-only --levels ... --min-repeats 2` and say so where the curve is reported.

`--reduce-only` labels the curve with the `source` its stored runs carry (`runpod` for a paid run). A store whose runs
carry none needs `--source {runpod,stub}`; a `--source` that contradicts the runs, or a store mixing sources, is
refused.

**H. Artifact 2's curve.**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_service_curve.py \
  --curve data/a2/service-sweep-curve.json --out data/a2/service-curve.json
```

Expected first line: `[a2] N points, max_num_seqs=256, MEASURED`. It then prints, per level, `c / median latency`
against the bench tool's own `request_throughput` and their ratio (Little's law). That is disclosure, not a gate: a
ratio above 1 means the median latency sits below the mean latency and saturation computed from the curve overstates
what the engine sustained. A level whose throughput is not stored prints `unavailable`. The output JSON also carries
per-level min..max intervals (`intervals`) for figure 4. It prints a WARNING if the top level is above `max_num_seqs`.
Wiring the measured curve into artifact 2's simulator and figures is artifact 2's plan 2b, not this plan.

**Things the owner should know before spending**
1. `--max-num-seqs 256` must be in `--serve-args`; the script now refuses a paid run without it (see F), so the
   failure that used to come after the money was spent comes before it. `--unrecorded-max-num-seqs` is the
   deliberate way past it, and the resulting curve cannot go through `scripts/a2_service_curve.py`.
2. A campaign whose runs mix windowed and whole-call GPU figures is refused at the reduction, after the runs are
   paid for and stored. Check the pilot's `windowed: True` (F, row 9b) before the campaign. The store keeps every
   run, but there is no way to reduce a subset of it; the fix is a re-run of the runs that differ, as a new campaign.
3. The drift-guard wording changed ("has condition 'C' on disk, but the rebuilt schedule assigns it 'A'", and the
   shrunk-schedule message no longer says "for the given arms/triples/seed" or suggests "fewer triples"). Accepted
   2026-10-04; nothing but the two messages differs from the pre-lift driver's output.
