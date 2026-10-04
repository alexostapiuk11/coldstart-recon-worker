# Artifact 2 Plan 2b — the Measured Curve, Pinned Capacity and the Open-Loop Gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the measured service curve under the simulator, the sweep and figure 4. Then build what the primary validation gate (spec §10) needs to run against RunPod: a worker behind a load-balancing endpoint, capacity pinned through `workersMin`, an open-loop driver that replays one exact schedule, and figure 3. Every paid step is the owner's to start.

**Architecture:** Two tracks. (1) **Measured curve, no spend.**
- `autoscale/measured_curve.py` loads `data/a2/service-curve.json` into a `ServiceCurve`, adding a measured idle point (0 load reads 0% GPU).
- A throughput-fraction utilisation signal joins as a sensitivity arm, outside the three headline signals.
- A pre-registration amendment fixes the absolute traffic rates and the validation operating point before any policy sweep runs on the measured curve.
- The render scripts switch to the measured curve, and figure 4 gains per-level intervals.

(2) **Open-loop gate.**
- `worker/lb_serve.py` starts the curve's exact engine behind a RunPod load-balancing endpoint.
- `worker/a2_middleware.py` (raw ASGI, loaded by vLLM's `--middleware`) stamps every response with the worker id and server-side latency.
- `harness/runpod/pinning.py` pins and releases `workersMin`, with a re-read and a deadline.
- `harness/open_loop.py` replays a schedule over HTTP from a thread pool and records send times.
- `autoscale/validation_schedule.py` builds the schedule with a drain tail.
- `scripts/a2_lb_probe.py` is the paid feasibility probe, `scripts/a2_validate.py` runs one pinned repeat or judges three, and figure 3 is `figures.validation_overlay`.

Figures 3 and 4 are matplotlib PNGs. No encapsulation boundary is involved, and no visible figure is removed. Figure 4 changes on purpose: it moves to the measured curve and gains intervals, and Task 1's baseline records what it looked like before.

**Tech Stack:** Python 3.13, pytest, matplotlib, `requests`, ruff, stdlib `asyncio`/`concurrent.futures`/`http.server`. No new dependencies; the worker side runs on the existing vLLM 0.27.1 image.

---

## Why this plan exists, and what it deliberately leaves out

Plan 2a built everything that did not depend on reconnaissance. Recon has now run (`docs/recon-a2.md`, 2026-10-04):
- **Q1 passes:** `workersMin` pins capacity and releases it, acknowledged synchronously.
- **Q2 shows genuine cold starts,** so both gates stand.
- **The curve is measured:** concurrency 1–128, three repeats each, and 256 is recorded as unservable (CUDA out of memory, 3 of 3 runs).

This plan is the part of plan 2a's "carried to plan 2b" list that the open-loop gate needs.

**Non-goals:**

- **The closed-loop confirmatory gate — plan 2c.** It drives real replica changes with the GPU-utilisation policy, and it builds on this plan's worker, pinning and driver. Owner decision 4 below.
- **Running anything paid.** The LB probe (Task 11) and the three validation repeats (Task 12) are built and proven here against fakes and a local HTTP server. Running them is the owner's call; the runbook section at the end is the checklist.
- **Publication.** The published figure copies with their drift guard (spec §11, §16), the post, and recording this artifact's spend belong to the publication plan.
- **The frontiers on the measured curve as a RESULT.** Task 5 makes the render script run on the measured curve, and running its 25-minute sweep is a step. Reading H1–H4 off it is the publication plan's, after the gate.

## Owner decisions this plan implements (2026-10-04, binding)

1. **Utilisation signal: both, with nvidia-smi primary.**
   - Add a measured idle point: 0 load reads 0% GPU. Evidence: every successful sweep run's samples outside the measured span read 0.
   - Keep nvidia-smi as the headline "GPU utilisation". It saturates at one request, and that is what DCGM- or KEDA-style autoscalers see.
   - Add a throughput-fraction signal, `throughput_at(c) / max throughput`, derived from the curve with no GPU spend. It is a disclosed sensitivity arm, so H2 is not won against a straw man.
2. **Load path: a RunPod load-balancing endpoint.** A worker runs a resident vLLM server, and a paid feasibility probe (~$0.50) comes before the validation runs.
3. **`workersMax` is set by the owner by hand.** A dedicated validation endpoint is provisioned with `workersMax = N`. The driver writes only `workersMin`, refuses to start unless `workersMax == N`, and restores `workersMin` 0 with a retry and a re-read.
4. **Split:** 2b is the open loop, 2c the closed loop.

## Verified, and what is not

Verified while writing this plan:
- **vLLM 0.27.1 has `--middleware`.** It takes an import path; a class is added with `app.add_middleware()`. Read from `vllm/entrypoints/openai/cli_args.py` at tag `v0.27.1`.
- **RunPod load-balancing endpoints** ([docs](https://docs.runpod.io/serverless/load-balancing/overview)):
  - requests go to `https://ENDPOINT_ID.api.runpod.ai/<path>`;
  - the worker port comes from `PORT` (default 80), and health from `PORT_HEALTH` plus `HEALTH_CHECK_PATH` (default `/ping`); 200 means healthy, 204 initializing, anything else unhealthy;
  - there is no queue, and requests are dropped when workers are overloaded;
  - the processing timeout is 5.5 min per request, and the payload limit 30 MB;
  - no response header identifies the worker.
- **The queue API's `/run`** allows 1,000 requests per 10 s and 200 concurrent ([docs](https://docs.runpod.io/serverless/workers/concurrent-handler)). The validation peak is ~400 req/s at N=2, which is why decision 2 rejects it.

**UNVERIFIED — the probe (Task 11) answers each before money goes to validation:**

| # | Question | Why it matters |
|---|---|---|
| P1 | Does the LB accept vLLM's `/health` via `HEALTH_CHECK_PATH=/health`, and keep polling while the engine loads, when `/health` refuses connections rather than answering 204? | A worker that is marked unhealthy and never re-polled never serves. |
| P2 | Does `workersMin` pin workers on an LB endpoint as it did on the queue endpoint? | Decision 3. |
| P3 | Does the LB spread requests across the N pinned workers, and how evenly? | The simulator assumes even balancing (`sim.py`). |
| P4 | Does the LB sustain the validation peak (~400 req/s) with zero non-200s? | A run with a failed request is void (Task 4). |
| P5 | Does vLLM 0.27.1 load `a2_middleware.WorkerHeaders`, and do its headers pass through the LB? | Worker attribution and server-side latency. |
| P6 | Client minus server latency at each rate (WAN plus LB). | Why the gate judges server-side latency (Task 4). |
| P7 | Does the LB endpoint accept the network volume `9c7ut2slrd` (weights under `HF_HOME`)? | Without it every cold start downloads 16 GB. |
| P8 | Can a laptop thread-pool driver hold send jitter ≤ 0.5 s at 450 req/s? | `RealRun` refuses a run with more. |

## Rules this plan operates under

- **Several workstreams share this checkout.** Never `git add -A`, `git add .` or `git add -u`; every commit step names its files. Never run `ruff --fix` over the whole repo; run it on the files the task touched.
- **`PYTHONDONTWRITEBYTECODE=1`** on every pytest and script invocation.
- **Test counts are not quoted as absolutes.** "Passes" means `pytest` exits 0; a count that drops between runs is stop-and-investigate.
- **House style.** Every error message names what went wrong **and** the consequence of it passing silently. Every docstring says *why*, including the alternative rejected.
- **Pre-registration.** `docs/experiment-a2.md` is edited only in Task 4, and only after the owner signs off the exact text. Changing a value after the first real validation run is an amendment.
- **Never print the RunPod API key or any token.** Scripts read `RUNPOD_API_KEY` from the environment and never echo it.
- **No paid run inside a task.** Every RunPod call in tests goes through an injected fake session. An autouse fixture makes `requests.get`/`requests.post` raise in every new test module that touches RunPod code.
- **Commit trailer:** end every commit message with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Cross-plan coupling

- **Shared tooling** (`2026-10-04-shared-in-container-tooling.md`, done): `harness/` must import neither `coldstart` nor `autoscale` (`tests/test_shared_tooling_boundary.py`). The new `harness/runpod/pinning.py` and `harness/open_loop.py` obey it; artifacts 4 and 5 may reuse both.
- **Image coverage** (`tests/test_harness_boundary.py`): every `worker/*.py` needs `COPY worker/X.py /opt/X.py`. Task 7 adds two files and their two COPY lines. CI rebuilds the image because `worker/**` changed; the LB template pins the new digest.
- **`autoscale/validation_band.py`** is imported by artifact 4 and must not gain imports. This plan does not touch it.
- **`recon/capture_a2.py`** keeps its own pin/restore code. It imports only the stdlib and `requests` by design, so a reader can rerun it without this repository; `harness/runpod/pinning.py` is a deliberate second copy with the same semantics. Recon is not refactored.

---

## File Structure

| File | Responsibility |
|---|---|
| `autoscale/measured_curve.py` | **Create (Task 2).** Load `data/a2/service-curve.json` into `MeasuredCurve`: a `ServiceCurve` with the idle point, plus intervals, excluded levels and engine facts. Refuses anything not measured or not windowed. |
| `autoscale/signals.py` | **Modify (Task 3).** Add `utilization_throughput` and `SENSITIVITY_SIGNALS` / `ALL_SIGNALS`; `SIGNALS` stays the three headline signals. |
| `autoscale/thresholds.py` | **Modify (Task 3).** Add the sensitivity signal's grid, equal to utilisation's. |
| `autoscale/sim.py` | **Modify (Task 3).** `run_with_policy` resolves the signal in `ALL_SIGNALS`. |
| `autoscale/sweep.py` | **Modify (Task 3).** `run_sweep(..., signals=None)`; the default is the three headline signals. |
| `scripts/a2_traffic_rates.py` | **Create (Task 4).** Print the absolute rates and the validation schedule's facts from the measured curve, for the amendment. |
| `autoscale/validation_schedule.py` | **Create (Task 4).** Validation operating point and the drain-tail schedule. |
| `docs/experiment-a2.md` | **Modify (Task 5, after owner sign-off).** Amendment 2026-10-04: measured curve, idle point, sensitivity signal, absolute rates, validation operating point, latency source, void-run rule, probe acceptance. |
| `tests/test_prereg_a2_plan2b.py` | **Create (Task 5).** Pins the amendment's numbers to the code constants. |
| `scripts/a2_render_figures.py` | **Modify (Tasks 6, 7).** `--curve` (default measured), `--placeholder` for layout drafts, explicit signal order, sensitivity sweep. |
| `scripts/a2_gap_noise_floor.py`, `scripts/a2_regime_probe.py` | **Modify (Task 6).** Same `--curve` / `--placeholder` switch. |
| `autoscale/figures.py` | **Modify (Task 7, Task 13).** Figure 4 intervals, idle point and excluded-level note; figure 2 banner; new `validation_overlay` (figure 3). |
| `worker/a2_middleware.py` | **Create (Task 8).** Raw ASGI middleware adding `x-a2-worker` and `x-a2-server-latency-ms`. |
| `worker/lb_serve.py` | **Create (Task 8).** `exec`s `vllm serve` with the curve's flags plus `--middleware`. |
| `worker/Dockerfile` | **Modify (Task 8).** Two COPY lines. |
| `harness/runpod/pinning.py` | **Create (Task 9).** `WorkerPin`: preflight (`workersMin` 0, `workersMax == N`), pin, release with retry and re-read, signal-safe unwind. |
| `harness/open_loop.py` | **Create (Task 10).** `replay(schedule, send, ...)` plus `http_sender(...)`. |
| `scripts/a2_lb_common.py`, `scripts/a2_lb_probe.py` | **Create (Task 11).** The shared URL, payload, warm-up and summary, and the paid feasibility probe: a rate ladder through the LB, with a summary per step. |
| `scripts/a2_validate.py` | **Create (Task 12, Task 13).** One pinned repeat → `data/a2/validation/repeat-K.json.gz`; `--judge` → verdict and figure 3. |
| `docs/runbook-a2-validation.md` | **Create (Task 14).** Owner's checklist for the probe and the three repeats. |
| Tests | `tests/test_measured_curve.py`, `tests/test_signals.py` / `tests/test_sim_policy.py` / `tests/test_sweep_signals.py`, `tests/test_a2_traffic_rates.py`, `tests/test_a2_figures.py`, `tests/test_a2_middleware.py`, `tests/test_lb_serve.py`, `tests/test_pinning.py`, `tests/test_open_loop.py`, `tests/test_a2_lb_probe.py`, `tests/test_validation_schedule.py`, `tests/test_a2_validate.py`, `tests/test_a2_render_curve_switch.py`. |

---
## Task 1: Inventory what the placeholder curve drives, and capture the "before"

This plan replaces the curve under three scripts and figure 4. Read the code, not this list, and record a keep/drop decision for every capability.

**Files:**
- Create: `docs/superpowers/plans/2026-10-04-artifact-2-plan-2b-inventory.md`
- Create (gitignored): `build/a2-plan2b-baseline/`

- [ ] **Step 1: Find every consumer of the placeholder curve and of figure 4**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
grep -rn "SERVICE_CURVE_PLACEHOLDER\|service_curve(\|censoring_onset\|UTILIZATION_CENSOR_AT" autoscale scripts tests recon harness | grep -v "^tests/.*#"
```

Expected (as of 2026-10-04; investigate anything new):
- production: `scripts/a2_render_figures.py` (import, `_sweep`, `_run_everything` ×2, `main` ×3), `scripts/a2_gap_noise_floor.py` (3 uses) and `scripts/a2_regime_probe.py` (`as CURVE`);
- figure code: `autoscale/figures.py` (`service_curve`, `censoring_onset`, `UTILIZATION_CENSOR_AT`);
- tests: `test_service.py`, `test_validation.py`, `test_a2_figures.py`, `test_sim.py`, `test_a2_end_to_end.py`, `test_sim_policy.py`, `test_frontier.py`, `test_traffic.py` and `test_signals.py`.

- [ ] **Step 2: Read each consumer and write the inventory**

Read `scripts/a2_render_figures.py` (all of it), the `main()` of the two other scripts, and `autoscale/figures.py::service_curve` / `censoring_onset`. Write `docs/superpowers/plans/2026-10-04-artifact-2-plan-2b-inventory.md` with one table row per capability: `| Capability | Where | Decision | How Task N preserves or why dropped |`. It must contain at least these rows, with the decisions shown:

| Capability | Where | Decision |
|---|---|---|
| Render figures 1, 2, 4 against the placeholder for a layout draft | `a2_render_figures.main` | **Preserved** behind `--placeholder` (Task 6) |
| `WARNING: rendering against the PLACEHOLDER service curve` on stdout | `main` | **Preserved** under `--placeholder` |
| `allow_unmeasured=True` passed to `run_sweep` | `_sweep` | **Preserved** only under `--placeholder`; the measured path passes `False` (Task 6) |
| Sweep cache `sweep-cache.json` and `--refresh` | `main`, `_dump`, `_load` | **Preserved**. The cache records which curve it came from, and a cache from the other curve is refused (Task 6) |
| Per-signal discard report | `_report_discards` | **Preserved** |
| H3 verdict printed under both shapes | `_run_everything` | **Preserved** |
| `_by_signal` key order (hash-seed order; parity pins `PYTHONHASHSEED=0`) | `_by_signal` | **Changed on purpose**: an explicit `SIGNAL_ORDER` order (plan 2a open item) |
| Figure 4 from `curve.points` and `curve.measured`, censoring shading, note, banner | `figures.service_curve` | **Preserved** for a bare `ServiceCurve` (byte-identical, checked in Task 6 Step 6 and Task 7 Step 4); intervals, idle point and excluded-level note are added only when a `MeasuredCurve` is passed |
| Figure 2 has no measured/modeled banner | `figures.frontiers` | **Changed on purpose**: its note names which curve it ran on (Task 7; plan 2a open item) |
| `a2_gap_noise_floor.py` / `a2_regime_probe.py` on the placeholder | both `main` | **Preserved** behind `--placeholder`; default becomes the measured curve |
| `RAMP_SECONDS` re-export read by `tests/test_a2_end_to_end.py` | render module | **Preserved** |

Nothing is dropped. If reading the code turns up a capability this list misses, add a row; a capability in neither column is a planning bug.

- [ ] **Step 3: Capture the "before" baseline**

```bash
mkdir -p build/a2-plan2b-baseline
PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 .venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
from autoscale.figures import service_curve
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.traffic import spike_shape, saturation_rps
out = Path("build/a2-plan2b-baseline")
p = service_curve(SERVICE_CURVE_PLACEHOLDER, out / "service_curve_placeholder.png")
facts = {
    "service_curve_placeholder_sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest(),
    "placeholder_saturation_rps": saturation_rps(SERVICE_CURVE_PLACEHOLDER),
    "placeholder_step": spike_shape(SERVICE_CURVE_PLACEHOLDER, "step").__dict__,
}
(out / "facts.json").write_text(json.dumps(facts, indent=1, sort_keys=True))
print(json.dumps(facts, indent=1, sort_keys=True))
PY
for s in a2_render_figures a2_gap_noise_floor a2_regime_probe; do PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/$s.py --help > build/a2-plan2b-baseline/$s.help.txt 2>&1; done
ls build/a2-figures-final/ 2>/dev/null && cp build/a2-figures-final/sweep-cache.json build/a2-plan2b-baseline/placeholder-sweep-cache.json
```

Expected: a sha256 for the placeholder figure 4, saturation `≈ 30.48` req/s (the placeholder's `64/2.10`), three help files, and, if `build/a2-figures-final/` exists, a copy of its placeholder sweep cache. Paste the printed facts into the inventory under "Baseline".

- [ ] **Step 4: Commit the inventory (the baseline stays in `build/`, which is gitignored)**

```bash
git add docs/superpowers/plans/2026-10-04-artifact-2-plan-2b-inventory.md
git commit -m "docs: plan 2b inventory of what the placeholder curve drives, with the before-baseline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Load the measured curve, with its measured idle point

`scripts/a2_service_curve.py::load_service_curve` exists, but `scripts/` is not a package and `autoscale/` must not import it. Nor does it add the idle point. This task puts the loader where the simulator lives.

Why the idle point is a measurement, not an assumption: every successful run in `data/a2/service-sweep.jsonl` sampled nvidia-smi before and after its measured span, while the engine sat idle. Those samples read `0` (for example 33 zeros against 33 out-of-span samples at level 2, and 35 against 34 at level 128). Without the point, `ServiceCurve.utilization_at(0)` clamps to the first point's 1.0, so an idle replica reads 100% busy and no scale-down threshold can ever fire.

**Files:**
- Create: `autoscale/measured_curve.py`
- Test: `tests/test_measured_curve.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The measured service curve as the simulator reads it."""

import json
from pathlib import Path

import pytest

from autoscale.measured_curve import (
    DEFAULT_PATH,
    IDLE_CONCURRENCY,
    MeasuredCurve,
    load_measured_curve,
    select_curve,
)
from autoscale.service import SERVICE_CURVE_PLACEHOLDER

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "data" / "a2" / "service-sweep.jsonl"


def _doc(**over):
    doc = {
        "measured": True,
        "gpu_util_method": "windowed",
        "prompt_path": "random-fallback",
        "max_num_seqs": 256,
        "points": [[1, 0.28, 56.0, 1], [2, 0.31, 104.0, 1], [128, 0.61, 3270.0, 1]],
        "intervals": [
            {"concurrency": 1, "latency_s_range": [0.27, 0.29], "throughput_tps_range": [55, 57],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.02, 0.03]},
            {"concurrency": 2, "latency_s_range": [0.30, 0.32], "throughput_tps_range": [103, 105],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.02, 0.03]},
            {"concurrency": 128, "latency_s_range": [0.60, 0.62], "throughput_tps_range": [3200, 3300],
             "gpu_util_range": [1, 1], "ttft_median_s_range": [0.16, 0.2]},
        ],
        "excluded_levels": [{"concurrency": 256, "reason": "OOM", "n_failed": 3, "n_runs": 3,
                             "run_ids": ["a", "b", "c"], "failure_details": []}],
    }
    doc.update(over)
    return doc


def _write(tmp_path, doc):
    path = tmp_path / "curve.json"
    path.write_text(json.dumps(doc))
    return path


def test_the_idle_point_is_prepended_and_reads_zero(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert isinstance(m, MeasuredCurve)
    assert m.curve.points[0] == (IDLE_CONCURRENCY, 0.28, 0.0, 0.0)
    assert m.curve.utilization_at(0) == 0.0
    assert m.curve.utilization_at(0.5) == pytest.approx(0.5)
    assert m.curve.utilization_at(1) == 1.0


def test_latency_and_cap_are_the_measured_ones(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert m.curve.latency_at(1) == 0.28
    assert m.curve.latency_at(128) == 0.61
    assert m.curve.max_measured_concurrency == 128
    assert m.curve.measured is True


def test_measured_points_exclude_the_idle_point(tmp_path):
    m = load_measured_curve(_write(tmp_path, _doc()))
    assert [p[0] for p in m.measured_points] == [1, 2, 128]
    assert [i["concurrency"] for i in m.intervals] == [1, 2, 128]
    assert m.excluded_levels[0]["concurrency"] == 256
    assert m.max_num_seqs == 256
    assert m.gpu_util_method == "windowed"
    assert m.runs_per_level == ()


def test_runs_per_level_come_from_the_level_rows(tmp_path):
    doc = _doc(levels=[{"n_runs": 3}, {"n_runs": 3}, {"n_runs": 2}])
    assert load_measured_curve(_write(tmp_path, doc)).runs_per_level == (3, 3, 2)
    with pytest.raises(ValueError, match="level rows"):
        load_measured_curve(_write(tmp_path, _doc(levels=[{"n_runs": 3}])))


def test_an_unmeasured_curve_is_refused(tmp_path):
    with pytest.raises(ValueError, match="not measured"):
        load_measured_curve(_write(tmp_path, _doc(measured=False)))


def test_a_curve_that_mixes_or_lacks_the_windowed_method_is_refused(tmp_path):
    with pytest.raises(ValueError, match="windowed"):
        load_measured_curve(_write(tmp_path, _doc(gpu_util_method="whole-call")))


def test_a_curve_already_holding_a_zero_level_is_refused(tmp_path):
    doc = _doc(points=[[0, 0.2, 0.0, 0.0], [1, 0.28, 56.0, 1]])
    doc["intervals"] = doc["intervals"][:2]
    doc["intervals"][0]["concurrency"] = 0
    doc["intervals"][1]["concurrency"] = 1
    with pytest.raises(ValueError, match="idle point"):
        load_measured_curve(_write(tmp_path, doc))


def test_intervals_must_match_the_points_level_for_level(tmp_path):
    doc = _doc()
    doc["intervals"] = doc["intervals"][:2]
    with pytest.raises(ValueError, match="intervals"):
        load_measured_curve(_write(tmp_path, doc))


def test_an_excluded_level_inside_the_measured_range_is_refused(tmp_path):
    doc = _doc()
    doc["excluded_levels"][0]["concurrency"] = 64
    with pytest.raises(ValueError, match="inside the measured range"):
        load_measured_curve(_write(tmp_path, doc))


def test_the_committed_curve_loads():
    m = load_measured_curve(REPO / DEFAULT_PATH)
    assert m.curve.measured
    assert m.curve.max_measured_concurrency == 128
    assert [e["concurrency"] for e in m.excluded_levels] == [256]
    assert m.curve.utilization_at(0) == 0.0
    assert m.runs_per_level == (3,) * 8


def test_the_store_shows_an_idle_gpu_reads_zero():
    """The idle point's evidence: every successful sweep run's samples outside
    its measured span (the engine idle while the bench tool starts and stops)
    read 0. If a future store breaks this, the idle point is no longer a
    measurement and Task 2 has to be revisited, not this test loosened."""
    runs = [json.loads(line) for line in STORE.read_text().splitlines() if line.strip()]
    ok = [r for r in runs if r["outcome"] == "ok"]
    assert ok
    for r in ok:
        samples = [s["util_pct"] for s in r["summary"]["gpu"]["samples"]
                   if s.get("util_pct") is not None]
        zeros = sum(1 for v in samples if v == 0)
        assert zeros >= r["summary"]["gpu_util_n_outside_span"] - 2, r["run_id"]


def test_select_curve_defaults_to_the_measured_one(tmp_path):
    curve, measured = select_curve(_write(tmp_path, _doc()), placeholder=False)
    assert measured is not None and curve is measured.curve


def test_select_curve_placeholder_returns_the_placeholder():
    curve, measured = select_curve(None, placeholder=True)
    assert curve is SERVICE_CURVE_PLACEHOLDER and measured is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_measured_curve.py -q -o addopts=""`
Expected: collection error, `ModuleNotFoundError: No module named 'autoscale.measured_curve'`.

- [ ] **Step 3: Implement `autoscale/measured_curve.py`**

```python
"""The measured service curve, as the simulator, the sweep and figure 4 read it.

`data/a2/service-curve.json` is written by `scripts/a2_service_curve.py` from
the shared service sweep. This module reads it into a `ServiceCurve` and keeps
beside it what the curve alone cannot carry: per-level intervals for figure 4,
the levels the engine could not serve, and the engine facts the post states.

It lives in `autoscale/` rather than reusing `scripts/a2_service_curve.py`'s
loader because `scripts/` is not a package -- every caller would have to edit
`sys.path` -- and because that loader does not add the idle point below.

THE IDLE POINT. The sweep measured concurrency 1 upwards, and nvidia-smi reads
100% at every measured level, one request included. `ServiceCurve` clamps below
its first point, so without a point at 0 an IDLE replica would read 100% busy,
and no utilisation scale-down threshold could ever fire: H2 would be confirmed
by an interpolation artefact. The point added is (0, latency at level 1, 0, 0).
Its utilisation is measured, not assumed: every successful sweep run sampled
nvidia-smi while the engine sat idle, before and after its measured span, and
those samples read 0 (tests/test_measured_curve.py checks the committed store).
Its latency is never read by the simulator, which charges every dispatched
request the load ceil(in_flight / replicas) >= 1; it is set to level 1's so the
curve stays flat there rather than inventing a value. Throughput at 0 load is 0
by definition.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve

__all__ = ["DEFAULT_PATH", "IDLE_CONCURRENCY", "MeasuredCurve", "load_measured_curve",
           "select_curve"]

DEFAULT_PATH = Path("data/a2/service-curve.json")
IDLE_CONCURRENCY = 0.0


@dataclass(frozen=True)
class MeasuredCurve:
    """The curve plus what figure 4 and the post need that it cannot hold."""

    curve: ServiceCurve
    intervals: tuple[dict, ...]
    excluded_levels: tuple[dict, ...]
    max_num_seqs: int
    gpu_util_method: str
    prompt_path: str
    source: str
    runs_per_level: tuple[int, ...] = ()

    @property
    def measured_points(self) -> tuple[tuple[float, float, float, float], ...]:
        """The curve's points without the idle point: what was swept."""
        return tuple(self.curve.points[1:])


def load_measured_curve(path=DEFAULT_PATH) -> MeasuredCurve:
    doc = json.loads(Path(path).read_text())
    if doc.get("measured") is not True:
        raise ValueError(
            f"{path} is not measured (measured={doc.get('measured')!r}); the simulator would "
            "run on invented numbers presented as the engine's. Use select_curve(..., "
            "placeholder=True) for a layout draft instead"
        )
    if doc.get("gpu_util_method") != "windowed":
        raise ValueError(
            f"{path} has gpu_util_method {doc.get('gpu_util_method')!r}, not 'windowed'; the "
            "idle point's 0% is a windowed reading's complement, and a whole-call median "
            "already mixes idle time into every level"
        )
    points = [tuple(float(x) for x in p) for p in doc["points"]]
    if not points or points[0][0] <= IDLE_CONCURRENCY:
        raise ValueError(
            f"{path}'s first level is {points[0][0] if points else None!r}; the idle point "
            "goes at concurrency 0, and a curve that already has a level there (or none) "
            "would get two values for one load"
        )
    intervals = tuple(doc.get("intervals") or ())
    if [i.get("concurrency") for i in intervals] != [p[0] for p in points]:
        raise ValueError(
            f"{path}'s intervals cover levels {[i.get('concurrency') for i in intervals]} but "
            f"its points cover {[p[0] for p in points]}; figure 4 would draw an interval "
            "against the wrong point"
        )
    excluded = tuple(doc.get("excluded_levels") or ())
    top = points[-1][0]
    inside = [e["concurrency"] for e in excluded if e["concurrency"] <= top]
    if inside:
        raise ValueError(
            f"{path} excludes levels {inside}, inside the measured range (top {top:g}); the "
            "simulator interpolates straight across a level the engine could not serve"
        )
    runs = tuple(int(level["n_runs"]) for level in doc.get("levels") or ())
    if runs and len(runs) != len(points):
        raise ValueError(
            f"{path} has {len(runs)} level rows for {len(points)} points; figure 4 states the "
            "runs behind each point and would attach the wrong count"
        )
    idle = (IDLE_CONCURRENCY, points[0][1], 0.0, 0.0)
    return MeasuredCurve(
        curve=ServiceCurve(points=[idle, *points], measured=True),
        intervals=intervals,
        excluded_levels=excluded,
        max_num_seqs=int(doc["max_num_seqs"]),
        gpu_util_method=doc["gpu_util_method"],
        prompt_path=doc.get("prompt_path", "unrecorded"),
        source=str(path),
        runs_per_level=runs,
    )


def select_curve(path, *, placeholder: bool) -> tuple[ServiceCurve, MeasuredCurve | None]:
    """The curve a script runs on: the measured one, or the placeholder on request.

    One switch for every script, so "which curve did this run on" has one
    answer per run. The placeholder is never a fallback for a missing file: a
    missing measured curve is an error, because silently drawing invented
    numbers is the failure the `measured` flag exists to prevent.
    """
    if placeholder:
        return SERVICE_CURVE_PLACEHOLDER, None
    measured = load_measured_curve(path if path is not None else DEFAULT_PATH)
    return measured.curve, measured
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_measured_curve.py -q -o addopts=""`
Expected: all pass. If `test_the_store_shows_an_idle_gpu_reads_zero` fails, STOP and report the failing run ids; the idle point's justification rests on it.

- [ ] **Step 5: Boundary check, full suite, lint**

`autoscale/measured_curve.py` imports only `autoscale.service`, so `tests/test_autoscale_boundary.py` stays green.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
.venv/bin/ruff check autoscale/measured_curve.py tests/test_measured_curve.py
```

Expected: the suite exits 0, and ruff prints `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add autoscale/measured_curve.py tests/test_measured_curve.py
git commit -m "feat: the measured service curve loads into the simulator, with its measured idle point

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The throughput-fraction utilisation signal, as a sensitivity arm

Owner decision 1. `SIGNALS` stays the three headline signals: `run_sweep` iterates it, and figures 1 and 2 are built on `SIGNAL_ORDER`. The new signal sits in `SENSITIVITY_SIGNALS`, and `ALL_SIGNALS` is what `run_with_policy` resolves a name in. `run_sweep` gains `signals=` so the render script can run the sensitivity sweep explicitly.

`utilization_throughput(state, curve) = curve.throughput_at(per_replica) / max(curve throughput)`. It is a fraction in [0, 1] that keeps rising until the knee, unlike nvidia-smi's, so the same threshold grid applies.

**Files:**
- Modify: `autoscale/signals.py`, `autoscale/thresholds.py`, `autoscale/sim.py:476`, `autoscale/sweep.py:144-180`
- Test: `tests/test_signals.py`, `tests/test_sim_policy.py`, create `tests/test_sweep_signals.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_signals.py`:

```python
from autoscale.signals import ALL_SIGNALS, SENSITIVITY_SIGNALS, utilization_throughput
from autoscale.thresholds import THRESHOLDS as _THRESHOLDS


def _tp_curve():
    from autoscale.service import ServiceCurve
    return ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (4, 0.4, 200.0, 1.0)],
                        measured=True)


def test_throughput_fraction_rises_with_load_where_nvidia_smi_is_flat():
    curve = _tp_curve()
    low = utilization_throughput(FleetState(waiting=0, in_flight=1, serving_replicas=1), curve)
    high = utilization_throughput(FleetState(waiting=0, in_flight=4, serving_replicas=1), curve)
    assert low == pytest.approx(0.25)
    assert high == pytest.approx(1.0)
    assert utilization(FleetState(0, 1, 1), curve) == utilization(FleetState(0, 4, 1), curve) == 1.0


def test_throughput_fraction_is_zero_when_idle_and_saturated_with_unserved_work():
    curve = _tp_curve()
    assert utilization_throughput(FleetState(0, 0, 1), curve) == 0.0
    assert utilization_throughput(FleetState(3, 0, 0), curve) == 1.0
    assert utilization_throughput(FleetState(0, 0, 0), curve) == 0.0


def test_the_headline_registry_is_unchanged_and_the_sensitivity_one_is_separate():
    assert sorted(SIGNALS) == ["in_flight_concurrency", "queue_depth", "utilization"]
    assert sorted(SENSITIVITY_SIGNALS) == ["utilization_throughput"]
    assert dict(ALL_SIGNALS) == {**SIGNALS, **SENSITIVITY_SIGNALS}


def test_the_sensitivity_signal_uses_utilizations_grid():
    assert _THRESHOLDS["utilization_throughput"] == _THRESHOLDS["utilization"]
```

(`tests/test_signals.py` already imports `pytest`, `FleetState`, `SIGNALS` and `utilization`; check the file's import block and add only what is missing.)

Append to `tests/test_sim_policy.py`:

```python
def test_run_with_policy_accepts_the_sensitivity_signal():
    import random

    from autoscale.coldstart_ecdf import LagDistribution
    from autoscale.controller import Controller
    from autoscale.service import ServiceCurve
    from autoscale.sim import run_with_policy

    curve = ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (4, 0.4, 200.0, 1.0)],
                         measured=True)
    result = run_with_policy(
        arrivals=[i * 0.05 for i in range(1, 400)],
        signal="utilization_throughput",
        controller=Controller(scale_up_at=0.5, scale_down_at=0.05, cooldown=5.0, max_replicas=3),
        lags=LagDistribution(samples=[1.0]),
        curve=curve,
        until=30.0,
        evaluate_every=1.0,
        rng=random.Random(0),
    )
    assert result.completed > 0
```

Create `tests/test_sweep_signals.py`:

```python
"""run_sweep runs the headline signals by default and any named set on request."""

import pytest

import autoscale.sweep as sweep
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.service import ServiceCurve

CURVE = ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (8, 0.5, 300.0, 1.0)],
                     measured=True)


def _config():
    return sweep.SweepConfig(
        shape=SpikeShape(kind="step", baseline_rate=5.0, k=2.0, ramp=0.0, sustain=20.0),
        lags=LagDistribution(samples=[2.0]), curve=CURVE, arm="test", until=60.0,
    )


@pytest.fixture(autouse=True)
def _few_reps(monkeypatch):
    monkeypatch.setattr(sweep, "REPETITIONS", 1)


def test_default_signals_are_the_headline_three():
    points, discards = sweep.run_sweep(_config(), seed=1)
    seen = {p.signal for p in points} | {d.partition(":")[0] for d in discards}
    assert seen <= {"queue_depth", "in_flight_concurrency", "utilization"}
    assert "utilization_throughput" not in seen


def test_named_signals_are_run_and_nothing_else():
    points, discards = sweep.run_sweep(_config(), seed=1, signals=("utilization_throughput",))
    seen = {p.signal for p in points} | {d.partition(":")[0] for d in discards}
    assert seen == {"utilization_throughput"}


def test_an_unknown_signal_is_refused_before_anything_runs():
    with pytest.raises(KeyError, match="no_such_signal"):
        sweep.run_sweep(_config(), seed=1, signals=("no_such_signal",))
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_signals.py tests/test_sim_policy.py tests/test_sweep_signals.py -q -o addopts=""`
Expected: ImportError for `utilization_throughput`, and `TypeError: run_sweep() got an unexpected keyword argument 'signals'`.

- [ ] **Step 3: Implement**

In `autoscale/signals.py`, change `__all__`, then add after `utilization` and replace the registry block:

```python
__all__ = ["ALL_SIGNALS", "SENSITIVITY_SIGNALS", "SIGNALS", "FleetState", "in_flight_concurrency",
           "queue_depth", "utilization", "utilization_throughput"]
```

```python
def utilization_throughput(state: FleetState, curve: ServiceCurve) -> float:
    """Utilisation as the fraction of the replica's peak throughput in use.

    The sensitivity arm for H2 (owner decision 2026-10-04). nvidia-smi's
    utilisation, which `utilization` reads, saturates at one request in flight
    on this engine, so a policy on it cannot tell a lightly loaded replica from
    a collapsing one. That is what a DCGM-driven autoscaler sees, and it is
    the headline. This signal answers the obvious objection -- "you beat
    utilisation by picking its worst definition" -- with the best definition
    the measured curve supports: throughput at the current per-replica load
    over the curve's maximum throughput, which rises until the knee. Same
    fraction scale, so utilisation's threshold grid applies unchanged.
    Rejected: a fourth headline signal, which would change every figure and
    the pre-registered three-arm comparison.
    """
    if state.serving_replicas == 0:
        return _zero_replica_reading(state, 1.0)
    peak = max(p[2] for p in curve.points)
    if peak <= 0:
        raise ValueError(
            "the curve's maximum throughput is 0; a throughput fraction has no denominator, "
            "and returning 0 would read every load as idle"
        )
    per_replica = state.in_flight / state.serving_replicas
    return min(1.0, curve.throughput_at(per_replica) / peak)


# A read-only view, not a plain dict: this registry is how a sweep names the
# three arms, and a module-level dict could be mutated by any importer --
# silently swapping the function a published arm was actually run with.
# `ServiceCurve` normalises `points` to a tuple for the same reason.
SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {
        "queue_depth": queue_depth,
        "in_flight_concurrency": in_flight_concurrency,
        "utilization": utilization,
    }
)

# Signals run only when named: a sensitivity analysis, not an arm of the
# experiment. Kept out of SIGNALS so `run_sweep`'s default and every figure
# built on the three arms are untouched.
SENSITIVITY_SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {"utilization_throughput": utilization_throughput}
)

ALL_SIGNALS: Mapping[str, Callable[[FleetState, ServiceCurve], float]] = MappingProxyType(
    {**SIGNALS, **SENSITIVITY_SIGNALS}
)
```

In `autoscale/thresholds.py`, add to `THRESHOLDS` after `"utilization"`:

```python
    # Sensitivity arm (owner decision 2026-10-04): the same fraction scale as
    # utilization, so the same grid. A grid of its own would add a second
    # difference between the two utilisation definitions.
    "utilization_throughput": ((0.50, 0.65, 0.80, 0.90, 0.95), (0.05, 0.15, 0.30, 0.50)),
```

In `autoscale/sim.py`, change the import of `SIGNALS` to `ALL_SIGNALS`, and line 476 `signal_fn = SIGNALS[signal]` to `signal_fn = ALL_SIGNALS[signal]`. Grep for any other `SIGNALS` use in `sim.py` (a docstring or error text naming the registry) and update it to say `ALL_SIGNALS`.

In `autoscale/sweep.py`, change the signature and the loop head:

```python
def run_sweep(
    config: SweepConfig, seed: int, allow_unmeasured: bool = False,
    signals: tuple[str, ...] | None = None,
) -> tuple[list[PolicyPoint], list[str]]:
```

Add this paragraph at the end of the docstring:

```
    `signals` names the signals to sweep; the default is the three arms in
    `SIGNALS`. Naming one outside them (the utilisation sensitivity arm) runs
    only what is named, so a sensitivity sweep never changes the arms' output.
    An unknown name is refused before any run, not discovered 25 minutes in.
```

Replace `for signal in sorted(SIGNALS):` with:

```python
    names = tuple(sorted(SIGNALS)) if signals is None else tuple(signals)
    unknown = [s for s in names if s not in ALL_SIGNALS or s not in THRESHOLDS]
    if unknown:
        raise KeyError(
            f"unknown signals {unknown}; known: {sorted(ALL_SIGNALS)}. A typo here would "
            "otherwise surface only when the first policy of that signal runs"
        )
    for signal in names:
```

Also add `ALL_SIGNALS` to `sweep.py`'s import from `autoscale.signals`.

- [ ] **Step 4: Run the tests and the full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_signals.py tests/test_sim_policy.py tests/test_sweep_signals.py -q -o addopts=""
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: both pass. `test_a2_figures.py::test_the_threshold_grid_has_one_home_and_sweep_re_exports_it` stays green, because `sweep.THRESHOLDS is thresholds.THRESHOLDS` still holds.

- [ ] **Step 5: The headline sweep's output is unchanged — prove it**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 .venv/bin/python - <<'PY'
import hashlib, json
import autoscale.sweep as sweep
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as C
from autoscale.traffic import spike_shape
sweep.REPETITIONS = 2
pts, d = sweep.run_sweep(sweep.SweepConfig(spike_shape(C, "step"), LagDistribution([60.0]), C, "x", 400.0),
                         seed=17, allow_unmeasured=True)
print(hashlib.sha256(json.dumps([(p.signal, p.scale_up_at, p.scale_down_at, p.cost_samples, p.p99_samples) for p in pts] + sorted(d)).encode()).hexdigest())
PY
```

Run it once on the commit before this task (`git stash` your changes, run it, `git stash pop`) and once after. Expected: identical hashes. Record both in the commit message body.

- [ ] **Step 6: Lint and commit**

```bash
.venv/bin/ruff check autoscale/signals.py autoscale/thresholds.py autoscale/sim.py autoscale/sweep.py tests/test_signals.py tests/test_sim_policy.py tests/test_sweep_signals.py
git add autoscale/signals.py autoscale/thresholds.py autoscale/sim.py autoscale/sweep.py tests/test_signals.py tests/test_sim_policy.py tests/test_sweep_signals.py
git commit -m "feat: a throughput-fraction utilisation signal as a sensitivity arm, outside the three headline signals

Headline sweep output unchanged: <hash before> == <hash after>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 4: The validation operating point and its schedule, with a drain tail

The spec fixes the gate's rules (`docs/experiment-a2.md`, "Validation gate — pass rule") but not its operating point: replica count, spike, window, or how the schedule ends. This task writes them as code constants and the schedule builder. Task 5 puts the same numbers in the pre-registration for the owner to sign.

**Proposed values (the owner signs them, or changes them, in Task 5):**

| Constant | Value | Why |
|---|---|---|
| `VALIDATION_REPLICAS` | `2` | August design: "a small replica count". Two exercise the load balancer's routing, which the simulator idealises as even balancing; one would not. |
| `VALIDATION_KIND` | `"step"` | The sharper transient: the whole load arrives at t=0. |
| Shape | `traffic.spike_shape(curve, "step")` with `baseline_rate` multiplied by `VALIDATION_REPLICAS` | The pre-registered rates are one replica's (`baseline = 0.70 × saturation`, `peak = baseline + 0.25 × saturation`). Scaling by N keeps the per-replica load equal to the frontiers' regime. Unscaled, two replicas would sit at half load and test nothing about queueing. |
| `VALIDATION_UNTIL` | `400.0` s | The sweep's window (`a2_render_figures.UNTIL`): the spike (190 s) and 210 s of baseline after it. |
| `VALIDATION_DRAIN_SECONDS` | `30.0` s | The schedule's last arrival comes at least 30 s before `until`, so its requests finish inside the window, 50× the top level's 0.61 s latency. Without a drain, the last bins are censored by design (plan 2a's open item). |
| `VALIDATION_SEED` | `20261004` | One fixed schedule; never changed between repeats. |
| `LATENCY_SOURCE` | `"server"` | The gate judges the engine's latency (`x-a2-server-latency-ms`, Task 8), the quantity the simulator models. Client latency adds the WAN and the LB (P6), is recorded for every request, and is published beside it. |
| `WARMUP_RPS`, `WARMUP_MIN_SECONDS`, `WARMUP_MAX_SECONDS` | `20.0`, `30.0`, `900.0` | Before t=0, send light load until all N pinned workers have answered for 30 s straight, then start the schedule. Give up after 15 minutes. |

The builder refuses a schedule that the simulator predicts would leave work unfinished at `until`. Such a schedule would make the final bins censored by design, which is a defect in the schedule, not something to measure.

**Files:**
- Create: `autoscale/validation_schedule.py`, `scripts/a2_traffic_rates.py`
- Test: `tests/test_validation_schedule.py`, `tests/test_a2_traffic_rates.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_validation_schedule.py`:

```python
"""The validation schedule: one replica-scaled step, ending in a drain tail."""

import pytest

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.service import ServiceCurve
from autoscale.traffic import spike_shape
from autoscale.validation import RealRun
from autoscale.validation_schedule import (
    LATENCY_SOURCE,
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    build_schedule,
    schedule_facts,
    validation_shape,
)

CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                     measured=True)


def test_the_constants_are_the_proposed_operating_point():
    assert (VALIDATION_REPLICAS, VALIDATION_KIND, VALIDATION_UNTIL, VALIDATION_DRAIN_SECONDS,
            VALIDATION_SEED, LATENCY_SOURCE) == (2, "step", 400.0, 30.0, 20261004, "server")


def test_the_shape_scales_the_baseline_by_the_replica_count_and_nothing_else():
    one = spike_shape(CURVE, "step")
    two = validation_shape(CURVE, replicas=2, kind="step")
    assert two.baseline_rate == pytest.approx(2 * one.baseline_rate)
    assert (two.k, two.ramp, two.sustain, two.kind) == (one.k, one.ramp, one.sustain, "step")


def test_no_arrival_falls_in_the_drain_tail():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    assert s and max(s) <= 90.0 and min(s) > 0.0
    assert list(s) == sorted(s)


def test_the_same_seed_gives_the_same_schedule():
    a = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    b = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    assert a == b


def test_a_schedule_the_model_cannot_finish_is_refused():
    slow = ServiceCurve(points=[(0, 5.0, 0.0, 0.0), (1, 5.0, 1.0, 1.0), (2, 9.0, 1.5, 1.0)],
                        measured=True)
    with pytest.raises(ValueError, match="unfinished"):
        build_schedule(slow, replicas=1, kind="step", until=60.0, drain=1.0, seed=3)


def test_a_drain_not_shorter_than_the_window_is_refused():
    with pytest.raises(ValueError, match="drain"):
        build_schedule(CURVE, replicas=2, kind="step", until=30.0, drain=30.0, seed=3)


def test_the_schedule_is_a_valid_real_run_schedule():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    RealRun(schedule=s, sent=s, latencies=[0.2] * len(s), replicas=2, until=120.0,
            host_ids=("w1", "w2"))


def test_facts_report_size_rates_and_the_models_prediction():
    s = build_schedule(CURVE, replicas=2, kind="step", until=120.0, drain=30.0, seed=3)
    f = schedule_facts(s, CURVE, replicas=2, until=120.0)
    assert f["requests"] == len(s)
    assert f["last_arrival_s"] == pytest.approx(max(s))
    assert f["predicted_unfinished"] == 0
    assert f["peak_bin_rps"] >= f["mean_rps"] > 0
    assert set(f) >= {"predicted_p50_s", "predicted_p99_s", "bins_with_20_requests"}


def test_the_committed_curve_gives_a_finishable_schedule():
    m = load_measured_curve(DEFAULT_PATH)
    s = build_schedule(m.curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                       until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                       seed=VALIDATION_SEED)
    f = schedule_facts(s, m.curve, replicas=VALIDATION_REPLICAS, until=VALIDATION_UNTIL)
    assert f["predicted_unfinished"] == 0
    assert f["bins_with_20_requests"] >= 30
```

`tests/test_a2_traffic_rates.py`:

```python
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_rates_script_prints_the_numbers_the_amendment_quotes():
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "a2_traffic_rates.py")],
        capture_output=True, text=True, check=True, cwd=REPO,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    ).stdout
    for key in ("saturation_rps", "baseline_rps_one_replica", "peak_rps_one_replica",
                "validation_baseline_rps", "validation_peak_rps", "validation_requests",
                "validation_predicted_p50_s", "validation_last_arrival_s"):
        assert f"{key} " in out, key
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation_schedule.py tests/test_a2_traffic_rates.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'autoscale.validation_schedule'`; the script test fails with a non-zero exit.

- [ ] **Step 3: Implement `autoscale/validation_schedule.py`**

```python
"""The open-loop gate's operating point, and the one schedule its repeats replay.

Spec §10 fixes the gate's rules (`autoscale/validation.py`) but not where it
is run: how many replicas, which spike, how the schedule ends. These constants
are that choice, pre-registered in docs/experiment-a2.md (amendment
2026-10-04) and pinned to it by tests/test_prereg_a2_plan2b.py.

The shape is the frontiers' own step, `traffic.spike_shape`, with the
baseline multiplied by the replica count. The pre-registered rates are ONE
replica's, so unscaled, two pinned replicas would run at half the per-replica
load the frontiers are computed at, and the gate would validate a regime the
results never use. Scaling keeps `k`, the sustain and the ramp unchanged.

The schedule ends in a drain tail: no arrival in the last
`VALIDATION_DRAIN_SECONDS` before `until`, so the final requests finish inside
the window. Without it the last bins are censored on purpose, which costs
judged bins against the 10-bin minimum, or censored on one side only, which is
an unbounded miss the design created rather than the model (plan 2a's
whole-implementation review). The builder also refuses a schedule the
simulator predicts would leave work unfinished at `until`. That checks the
schedule, not the model: a schedule built to censor its own tail cannot test
anything there.
"""

import math
import random

from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.stats import percentiles
from autoscale.traffic import spike_shape

__all__ = [
    "LATENCY_SOURCE", "VALIDATION_DRAIN_SECONDS", "VALIDATION_KIND", "VALIDATION_REPLICAS",
    "VALIDATION_SEED", "VALIDATION_UNTIL", "WARMUP_MAX_SECONDS", "WARMUP_MIN_SECONDS",
    "WARMUP_RPS", "build_schedule", "schedule_facts", "validation_shape",
]

VALIDATION_REPLICAS = 2
VALIDATION_KIND = "step"
VALIDATION_UNTIL = 400.0
VALIDATION_DRAIN_SECONDS = 30.0
VALIDATION_SEED = 20261004
# The gate judges the engine's own latency, stamped by worker/a2_middleware.py:
# it is the quantity the simulator models. Client latency adds the WAN and the
# load balancer, which no part of the model represents; it is recorded per
# request and published beside the verdict, not judged.
LATENCY_SOURCE = "server"
WARMUP_RPS = 20.0
WARMUP_MIN_SECONDS = 30.0
WARMUP_MAX_SECONDS = 900.0


def validation_shape(curve: ServiceCurve, *, replicas: int, kind: str) -> SpikeShape:
    if type(replicas) is not int or replicas < 1:
        raise ValueError(
            f"replicas is {replicas!r}; the pinned fleet is a positive int, and a scaled rate "
            "for a fractional fleet is a load no endpoint can be pinned to"
        )
    one = spike_shape(curve, kind)
    return SpikeShape(kind=one.kind, baseline_rate=one.baseline_rate * replicas, k=one.k,
                      ramp=one.ramp, sustain=one.sustain)


def build_schedule(curve: ServiceCurve, *, replicas: int, kind: str, until: float,
                   drain: float, seed: int) -> tuple[float, ...]:
    if not (math.isfinite(until) and math.isfinite(drain)) or drain <= 0 or drain >= until:
        raise ValueError(
            f"drain {drain!r} with window {until!r}: the drain must be positive and shorter "
            "than the window, or the schedule is empty or has no tail to drain into"
        )
    shape = validation_shape(curve, replicas=replicas, kind=kind)
    arrivals = arrival_times(shape, until - drain, random.Random(seed))
    if not arrivals:
        raise ValueError("the schedule drew no arrivals; a validation run of nothing judges nothing")
    result = run_fixed_capacity(list(arrivals), replicas, curve, until)
    if result.unfinished:
        raise ValueError(
            f"the simulator predicts {result.unfinished} requests unfinished at {until:g} s for "
            f"this schedule; its final bins would be censored by design. Lengthen the drain or "
            "lower the load"
        )
    return tuple(arrivals)


def schedule_facts(schedule, curve: ServiceCurve, *, replicas: int, until: float) -> dict:
    """What the amendment states about the schedule, computed, not typed."""
    result = run_fixed_capacity(list(schedule), replicas, curve, until)
    bins = [0] * math.ceil(until / 10.0)
    for t in schedule:
        bins[min(int(t // 10.0), len(bins) - 1)] += 1
    pct = percentiles(result.latencies, want=("p50", "p99"))
    return {
        "requests": len(schedule),
        "last_arrival_s": max(schedule),
        "mean_rps": len(schedule) / max(schedule),
        "peak_bin_rps": max(bins) / 10.0,
        "bins_with_20_requests": sum(1 for b in bins if b >= 20),
        "predicted_p50_s": pct["p50"],
        "predicted_p99_s": pct["p99"],
        "predicted_unfinished": result.unfinished,
    }
```

- [ ] **Step 4: Implement `scripts/a2_traffic_rates.py`**

```python
"""Print the absolute traffic rates and the validation schedule's facts.

The amendment of 2026-10-04 quotes these numbers. Spec §8's ordering rule
requires the absolute rates to be computed from the service curve and
committed BEFORE any policy sweep runs on it; this script is how they are
computed, so the amendment can be checked by re-running it.
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve  # noqa: E402
from autoscale.traffic import saturation_rps, spike_shape  # noqa: E402
from autoscale.validation_schedule import (  # noqa: E402
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    build_schedule,
    schedule_facts,
    validation_shape,
)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--curve", default=str(REPO / DEFAULT_PATH))
    args = ap.parse_args(argv)
    curve = load_measured_curve(args.curve).curve
    one = spike_shape(curve, VALIDATION_KIND)
    val = validation_shape(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND)
    schedule = build_schedule(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                              until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                              seed=VALIDATION_SEED)
    facts = schedule_facts(schedule, curve, replicas=VALIDATION_REPLICAS, until=VALIDATION_UNTIL)
    rows = {
        "saturation_rps": saturation_rps(curve),
        "baseline_rps_one_replica": one.baseline_rate,
        "peak_rps_one_replica": one.baseline_rate * one.k,
        "k": one.k,
        "validation_replicas": VALIDATION_REPLICAS,
        "validation_baseline_rps": val.baseline_rate,
        "validation_peak_rps": val.baseline_rate * val.k,
        "validation_requests": facts["requests"],
        "validation_last_arrival_s": facts["last_arrival_s"],
        "validation_peak_bin_rps": facts["peak_bin_rps"],
        "validation_bins_with_20_requests": facts["bins_with_20_requests"],
        "validation_predicted_p50_s": facts["predicted_p50_s"],
        "validation_predicted_p99_s": facts["predicted_p99_s"],
        "validation_predicted_unfinished": facts["predicted_unfinished"],
    }
    for key, value in rows.items():
        print(f"{key} {value:.4f}" if isinstance(value, float) else f"{key} {value}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests, then the script**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation_schedule.py tests/test_a2_traffic_rates.py -q -o addopts=""
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_traffic_rates.py | tee build/a2-plan2b-rates.txt
```

Expected: tests pass. The script prints `saturation_rps 211.19…`, `baseline_rps_one_replica 147.83…`, `peak_rps_one_replica 200.63…`, `validation_baseline_rps 295.67…`, `validation_peak_rps 401.27…`, `validation_predicted_unfinished 0`, and a request count near 120,000. Keep the output; Task 5 quotes it.

- [ ] **Step 6: Full suite, lint, commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
.venv/bin/ruff check autoscale/validation_schedule.py scripts/a2_traffic_rates.py tests/test_validation_schedule.py tests/test_a2_traffic_rates.py
git add autoscale/validation_schedule.py scripts/a2_traffic_rates.py tests/test_validation_schedule.py tests/test_a2_traffic_rates.py
git commit -m "validation: the open-loop gate's operating point and its drain-tailed schedule, proposed for pre-registration

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Pre-registration amendment — STOP for the owner's sign-off

Spec §8's ordering rule: the absolute rates are committed **before any policy sweep runs** on the measured curve. This task writes the amendment, shows it to the owner, and commits only on a yes. Task 6's sweep must not run before this commit exists.

**Files:**
- Modify: `docs/experiment-a2.md` (a new `## Amendment, 2026-10-04: the measured curve and the validation operating point` section before `## Stopping rule`)
- Create: `tests/test_prereg_a2_plan2b.py`

- [ ] **Step 1: Write the failing test that pins the amendment to the code**

```python
"""docs/experiment-a2.md's 2026-10-04 amendment states what the code runs."""

import re
from pathlib import Path

from autoscale import validation_schedule as vs
from autoscale.measured_curve import IDLE_CONCURRENCY
from autoscale.thresholds import THRESHOLDS

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a2.md").read_text()
SECTION = DOC.split("## Amendment, 2026-10-04: the measured curve and the validation operating point", 1)


def _section() -> str:
    assert len(SECTION) == 2, "the 2026-10-04 amendment is missing"
    return SECTION[1].split("\n## ", 1)[0]


def test_the_operating_point_matches_the_constants():
    s = _section()
    assert f"**{vs.VALIDATION_REPLICAS} replicas**" in s
    assert f"until **{vs.VALIDATION_UNTIL:g} s**" in s
    assert f"drain **{vs.VALIDATION_DRAIN_SECONDS:g} s**" in s
    assert f"seed **{vs.VALIDATION_SEED}**" in s
    assert "**server-side latency**" in s
    assert f"**{vs.WARMUP_RPS:g} req/s**" in s


def test_the_absolute_rates_are_stated():
    s = _section()
    for label in ("saturation", "baseline", "peak"):
        assert re.search(rf"{label}[^\n]*\*\*\d+\.\d req/s\*\*", s), label


def test_the_idle_point_and_the_sensitivity_signal_are_stated():
    s = _section()
    assert f"concurrency {IDLE_CONCURRENCY:g}" in s and "0%" in s
    assert "`utilization_throughput`" in s
    up, down = THRESHOLDS["utilization_throughput"]
    assert ", ".join(f"{v:g}" for v in up) in s


def test_the_void_run_and_probe_rules_are_stated():
    s = _section()
    assert "void" in s and "non-200" in s
    assert "P1" in s and "P8" in s
```

- [ ] **Step 2: Run it and see it fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_prereg_a2_plan2b.py -q -o addopts=""`
Expected: `AssertionError: the 2026-10-04 amendment is missing`.

- [ ] **Step 3: Draft the amendment (do not commit yet)**

Insert before `## Stopping rule`. Fill each `<…>` from `build/a2-plan2b-rates.txt` (Task 4 Step 5), rounding to one decimal for rates and three for seconds:

```markdown
## Amendment, 2026-10-04: the measured curve and the validation operating point

Made after the service sweep (`data/a2/service-curve.json`) and reconnaissance
(`docs/recon-a2.md`), before any policy sweep has run on the measured curve and
before any real validation run exists. Signed off by the owner on <date>.

**The measured curve replaces the placeholder.** Concurrency 1–128, three repeats
per level, `max_num_seqs` 256, prefix caching off, random 13-token prompts at 16
output tokens (the exact prompt needs pandas, which the image lacks; recorded per
run). Level 256 is recorded as unservable: the engine died of CUDA out of memory
at its first step in 3 of 3 runs. The per-replica cap is therefore 128.

**An idle point at concurrency 0 reads 0% GPU.** nvidia-smi reads 100% at every
measured level, one request included. Without a point at 0 the curve clamps, an
idle replica reads 100% busy, and no utilisation scale-down threshold can fire.
The 0% is measured: every successful sweep run's samples outside its measured
span, with the engine idle, read 0.

**H2 under a saturating signal.** The headline utilisation signal stays
nvidia-smi's, because it is what GPU-utilisation autoscalers act on, and it
saturates at one request. A **sensitivity arm**, `utilization_throughput`
(throughput at the current per-replica load over the curve's maximum
throughput), is swept with utilisation's grid (up 0.5, 0.65, 0.8, 0.9, 0.95;
down 0.05, 0.15, 0.3, 0.5) and reported beside H2. H2's verdict is stated for
the headline signal; if the sensitivity arm reverses it, the post says so in the
body.

**Absolute rates (spec §8 ordering rule), from `scripts/a2_traffic_rates.py`:**
saturation **<sat> req/s** (128 / 0.606 s); baseline **<base> req/s** (0.70 ×
saturation); peak **<peak> req/s** (baseline + 0.25 × saturation), for one replica.

**Validation operating point.**
- **2 replicas** pinned (`workersMin = workersMax = 2`; `workersMax` set by the
  owner, `workersMin` by the driver).
- The step shape with its baseline scaled by the replica count: baseline <vbase>,
  peak <vpeak>, sustain 190 s.
- Window until **400 s**, with a drain **30 s**: no arrival after <last> s.
- One schedule, seed **<seed>**, <n> requests, replayed by all three repeats.
- The gate judges **server-side latency**: the engine's own receive-to-response
  time, stamped by `worker/a2_middleware.py`. That is the quantity the simulator
  models. Client latency is recorded per request and published beside it.
- Before t=0 the driver sends **20 req/s** until every pinned worker has answered
  for 30 s straight, giving up after 900 s; those requests are not part of the run.
- **The simulator's prediction for this schedule:** p50 <p50> s, p99 <p99> s, 0 requests
  unfinished at 400 s.

**Void runs.** A repeat with any non-200 response, or with a response from a
worker outside the pinned set, is void. It is recorded, not judged, and run
again once. A second void at the same repeat ends the gate as "not evaluable",
with the cause published. A host-novelty event (a pinned worker id never seen in
an earlier repeat) is recorded and disclosed, not voided (spec §10).

**Feasibility probe acceptance (before any validation repeat).** The probe
(`scripts/a2_lb_probe.py`) answers P1–P8 of plan 2b. The repeats may start only
if, at its 450 req/s step:
- every response was 200;
- each pinned worker served at least 35% of requests;
- the maximum send jitter stayed at or below 0.25 s.

Otherwise the owner decides what changes, and this amendment is amended before
any repeat.
```

- [ ] **Step 4: STOP. Show the owner the drafted section and the rates output, and ask for sign-off**

Paste the section and `build/a2-plan2b-rates.txt` into the report. Name the decisions the owner is signing:
- 2 replicas, with the step scaled by N;
- server-side latency judged;
- the 30 s drain;
- the void rule;
- the probe thresholds.

Do not commit, and do not start Task 6's sweep, until the owner says yes. If they change a value, change the constant in `autoscale/validation_schedule.py` (and its pinned test in `tests/test_validation_schedule.py`), re-run Task 4 Step 5, and redraft.

- [ ] **Step 5: On sign-off, fill in the date, run the tests, commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_prereg_a2_plan2b.py tests/test_validation_schedule.py -q -o addopts=""
git add docs/experiment-a2.md tests/test_prereg_a2_plan2b.py
git commit -m "prereg: the measured curve, the idle point, the utilisation sensitivity arm, absolute rates and the validation operating point, before any policy sweep on the measured curve

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 6: The scripts run on the measured curve; the placeholder only on request

**Precondition:** Task 5's amendment is committed (`git log --oneline -- docs/experiment-a2.md` shows the `prereg:` commit). Steps 1–6 here are code and may be written before it; Step 7, the sweep, may not.

**Files:**
- Modify: `scripts/a2_render_figures.py`, `scripts/a2_gap_noise_floor.py`, `scripts/a2_regime_probe.py`
- Test: create `tests/test_a2_render_curve_switch.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Which curve the artifact-2 scripts run on, and that a cache cannot cross curves."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_gap_noise_floor as noise  # noqa: E402
import a2_regime_probe as probe  # noqa: E402
import a2_render_figures as render  # noqa: E402
from autoscale.frontier import PolicyPoint  # noqa: E402
from autoscale.service import SERVICE_CURVE_PLACEHOLDER  # noqa: E402


def _pp(signal):
    return PolicyPoint(cost_samples=(1.0,), p99_samples=(1.0,), signal=signal,
                       scale_up_at=1.0, scale_down_at=0.0, rep_indices=(0,))


def test_by_signal_orders_keys_by_signal_order_then_name():
    points = [_pp("utilization"), _pp("utilization_throughput"), _pp("queue_depth"),
              _pp("in_flight_concurrency")]
    assert list(render._by_signal(points)) == [
        "queue_depth", "in_flight_concurrency", "utilization", "utilization_throughput"]


def test_curve_label_names_the_measured_file_or_the_placeholder():
    assert render.curve_label(None) == "placeholder"
    assert render.curve_label(Path("data/a2/service-curve.json")) == "data/a2/service-curve.json"


def test_a_cache_from_the_other_curve_is_refused():
    with pytest.raises(SystemExit, match="placeholder"):
        render.check_cache_curve({"curve": "placeholder"}, "data/a2/service-curve.json")
    with pytest.raises(SystemExit, match="does not say"):
        render.check_cache_curve({}, "data/a2/service-curve.json")
    render.check_cache_curve({"curve": "placeholder"}, "placeholder")


def test_the_sweep_is_unmeasured_only_on_the_placeholder(monkeypatch):
    seen = {}

    def fake_run_sweep(config, seed, allow_unmeasured=False, signals=None):
        seen["allow"], seen["curve"], seen["signals"] = allow_unmeasured, config.curve, signals
        return [], []

    monkeypatch.setattr(render, "run_sweep", fake_run_sweep)
    from autoscale.coldstart_ecdf import LagDistribution
    from autoscale.traffic import spike_shape
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    render._sweep("x", shape, LagDistribution([60.0]), "A", SERVICE_CURVE_PLACEHOLDER)
    assert seen["allow"] is True and seen["curve"] is SERVICE_CURVE_PLACEHOLDER
    assert seen["signals"] is None
    render._sweep("x", shape, LagDistribution([60.0]), "A", SERVICE_CURVE_PLACEHOLDER,
                  signals=("utilization_throughput",))
    assert seen["signals"] == ("utilization_throughput",)


@pytest.mark.parametrize("module", [render, noise, probe])
def test_curve_and_placeholder_flags_are_exclusive(module):
    with pytest.raises(SystemExit):
        module.parse_args(["--placeholder", "--curve", "x.json"])
    assert module.parse_args([]).placeholder is False
    assert module.parse_args(["--placeholder"]).placeholder is True
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_render_curve_switch.py -q -o addopts=""`
Expected: `AttributeError: module 'a2_render_figures' has no attribute 'curve_label'` (and similar for `parse_args`).

- [ ] **Step 3: `scripts/a2_render_figures.py`**

Make these changes. Read the file first; keep every other line as is.

1. Module docstring, first paragraph: replace it with

```
Against the MEASURED service curve (`data/a2/service-curve.json`) by default.
`--placeholder` draws the layout draft against the invented placeholder curve,
as before, and says so on stdout. A sweep cache records which curve it came
from, and a cache from the other curve is refused rather than drawn under the
wrong label.
```

2. Imports: drop `from autoscale.service import SERVICE_CURVE_PLACEHOLDER`, and add `from autoscale.measured_curve import DEFAULT_PATH, select_curve`.

3. Replace `_by_signal`:

```python
def _by_signal(points):
    """Points grouped by signal, in `SIGNAL_ORDER` and then by name.

    An explicit order, not set order: set order follows the hash seed, which
    parity runs had to pin (`PYTHONHASHSEED=0`) to get stable output (plan 2a
    open item). Signals outside `SIGNAL_ORDER` (the utilisation sensitivity
    arm) come after the three arms.
    """
    present = {p.signal for p in points}
    order = [s for s in SIGNAL_ORDER if s in present] + sorted(present - set(SIGNAL_ORDER))
    return {s: [p for p in points if p.signal == s] for s in order}
```

4. Add after `_by_signal`:

```python
def curve_label(path) -> str:
    """How a cache and stdout name the curve: its path, or "placeholder"."""
    return "placeholder" if path is None else str(path)


def check_cache_curve(raw: dict, label: str) -> None:
    got = raw.get("curve")
    if got is None:
        raise SystemExit(
            "the sweep cache does not say which service curve it came from (it predates "
            "plan 2b); re-run with --refresh rather than draw it under a guessed label"
        )
    if got != label:
        raise SystemExit(
            f"the sweep cache came from curve {got!r} but this run is on {label!r}; drawing it "
            "would put one curve's frontiers under the other's banner. Use --refresh or "
            "another --out"
        )


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/a2-figures-draft")
    ap.add_argument("--refresh", action="store_true", help="re-run the sweep, ignoring the cache")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--curve", default=None,
                       help=f"the measured curve (default {DEFAULT_PATH})")
    which.add_argument("--placeholder", action="store_true",
                       help="layout draft against the invented placeholder curve")
    return ap.parse_args(argv)
```

5. `_sweep` takes the curve and the signals:

```python
def _sweep(label: str, shape: SpikeShape, lags: LagDistribution, arm: str, curve,
           signals=None):
    points, discards = run_sweep(
        SweepConfig(shape=shape, lags=lags, curve=curve, arm=arm, until=UNTIL),
        seed=SEED,
        # Only the placeholder needs the opt-in; a measured curve passes the
        # sweep's own guard.
        allow_unmeasured=not curve.measured,
        signals=signals,
    )
    print(f"{label}: {len(points)} policy points over signals {list(_by_signal(points))}")
    _report_discards(label, discards)
    return points
```

6. `_run_everything(store)` becomes `_run_everything(store, curve)`. Replace both `spike_shape(SERVICE_CURVE_PLACEHOLDER, ...)` with `spike_shape(curve, ...)`, and pass `curve` to every `_sweep` call. After the four headline gaps are computed and before `verdict = h3_verdict(...)`, add the sensitivity arm:

```python
    # H2's sensitivity arm (amendment 2026-10-04): the same sweeps with
    # utilisation defined as the throughput fraction. Printed beside the
    # headline, never substituted for it.
    from autoscale.frontier import COMPARED_SIGNALS
    sensitivity_signals = tuple(
        "utilization_throughput" if s == "utilization" else s for s in COMPARED_SIGNALS
    )
    for label, sh, arm in (("arm A", shape, "A"), ("arm C", shape, "C"),
                           ("ramp arm A", ramp_shape, "A"), ("ramp arm C", ramp_shape, "C")):
        tag = f"sensitivity {label}"
        sources[tag] = _sweep(tag, sh, lags[arm], f"sens-{label}", curve,
                              signals=("utilization_throughput",))
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(
            [p for p in sources[label] if p.signal != "utilization"] + sources[tag]).items()}
        try:
            budget = iso_cost_budget(per_signal)
            g = gap_at_iso_cost(per_signal, cost=budget, expected=sensitivity_signals)
            print(f"{tag}: gap={g:.4f}s at budget {budget:.1f} with utilisation as throughput "
                  f"fraction (headline gap {gaps[label]['point']:.4f}s)")
        except ValueError as exc:
            print(f"{tag}: gap undefined ({exc.args[0].split(';')[0]})")
```

Before writing this, check `iso_cost_budget`'s and `gap_at_iso_cost`'s signatures in `autoscale/frontier.py` (lines ~261 and ~335). If `iso_cost_budget` filters to `COMPARED_SIGNALS` internally, pass it a dict whose keys match `sensitivity_signals`, and read its docstring for how; then adjust this block to the real signature, without changing frontier.py.

7. `_dump` writes `"curve": label` at the top level of the JSON (a new parameter `label`). `_load` returns the raw dict too, so `main` can call `check_cache_curve(raw, label)`.

8. `main`:

```python
def main(argv=None) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    args = parse_args(argv)
    path = None if args.placeholder else (args.curve or DEFAULT_PATH)
    curve, measured = select_curve(path, placeholder=args.placeholder)
    label = curve_label(path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not curve.measured:
        print(
            "WARNING: rendering against the PLACEHOLDER service curve. "
            "These figures are a layout draft, not a result."
        )
    else:
        print(f"service curve: {label} (measured; idle point added, cap "
              f"{curve.max_measured_concurrency:g})")
    print(service_curve(curve, out / "service_curve.png", measured=measured))
    ...
```

Keep the rest of `main` as it is, with three changes:
- `_run_everything(args.store)` becomes `_run_everything(args.store, curve)`;
- the cache load calls `check_cache_curve` before using it, and `_dump` passes `label`;
- `curve_measured=SERVICE_CURVE_PLACEHOLDER.measured` becomes `curve_measured=curve.measured`.

`service_curve(..., measured=...)` is added by Task 7. Until Task 7 lands, call `service_curve(curve, out / "service_curve.png")`, and leave a one-line comment that Task 7 adds `measured=`.

- [ ] **Step 4: `scripts/a2_gap_noise_floor.py` and `scripts/a2_regime_probe.py`**

In both scripts:
- Move the `argparse` setup into a `parse_args(argv=None)` function with the same mutually exclusive `--curve` / `--placeholder` group as above (plus each script's own flags, unchanged).
- `main` calls `curve, _ = select_curve(None if args.placeholder else (args.curve or DEFAULT_PATH), placeholder=args.placeholder)`.

In `a2_gap_noise_floor.py`:
- replace every `SERVICE_CURVE_PLACEHOLDER` with `curve`;
- replace `allow_unmeasured=True` with `allow_unmeasured=not curve.measured`;
- make the `"-- PLACEHOLDER service curve"` text conditional: `"-- PLACEHOLDER service curve" if not curve.measured else "-- measured service curve"`.

In `a2_regime_probe.py`:
- change the import to `from autoscale.service import SERVICE_CURVE_PLACEHOLDER` plus `CURVE = SERVICE_CURVE_PLACEHOLDER` at module level;
- in `main`, add `global CURVE` and `CURVE = curve`;
- make each `allow_unmeasured=True` read `allow_unmeasured=not CURVE.measured`;
- make the `"PLACEHOLDER service curve."` line conditional the same way.

Neither script's module docstring states a measured result, so leave both docstrings alone.

- [ ] **Step 5: Run the tests and the full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_render_curve_switch.py tests/test_a2_end_to_end.py -q -o addopts=""
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: pass. `test_a2_end_to_end.py` drives the render module on the placeholder; if it calls `_sweep`/`_run_everything` with the old signatures, update its calls to pass `SERVICE_CURVE_PLACEHOLDER` explicitly. That is a signature change, not a behaviour change; say so in the report.

- [ ] **Step 6: Parity of the placeholder path**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
from autoscale.figures import service_curve
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
p = service_curve(SERVICE_CURVE_PLACEHOLDER, "build/a2-plan2b-baseline/service_curve_placeholder_after.png")
want = json.loads(Path("build/a2-plan2b-baseline/facts.json").read_text())["service_curve_placeholder_sha256"]
got = hashlib.sha256(Path(p).read_bytes()).hexdigest()
print("PLACEHOLDER FIGURE 4 PARITY", "OK" if got == want else f"CHANGED {got} != {want}")
PY
```

Expected: `PLACEHOLDER FIGURE 4 PARITY OK`.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check scripts/a2_render_figures.py scripts/a2_gap_noise_floor.py scripts/a2_regime_probe.py tests/test_a2_render_curve_switch.py tests/test_a2_end_to_end.py
git add scripts/a2_render_figures.py scripts/a2_gap_noise_floor.py scripts/a2_regime_probe.py tests/test_a2_render_curve_switch.py
git add tests/test_a2_end_to_end.py   # only if Step 5 changed it
git commit -m "figures: artifact 2's scripts run on the measured curve by default, the placeholder on request, with the utilisation sensitivity arm

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Run the sweep on the measured curve (CPU only, ~25+ minutes) — only after Task 5's commit**

```bash
git log --oneline -1 -- docs/experiment-a2.md   # must be the prereg: commit
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-measured --refresh 2>&1 | tee build/a2-figures-measured.log
```

Run it in the background, because it takes 25–40 minutes; the sensitivity sweeps add four. Expected:
- the first line names `data/a2/service-curve.json`;
- the per-signal discard counts are printed;
- the four headline gaps and four sensitivity gaps are printed, then `H3: holds=...`.

If a figure guard refuses (`SystemExit` with the "figures' own guards" text), that is a finding about a signal on the measured curve. Report the discard counts verbatim; do not loosen a guard. These numbers are not a published result until the gate passes, so the report quotes them as "measured-curve sweep, unvalidated".

---
## Task 7: Figure 4 on the measured curve, with intervals; figure 2 says which curve it ran on

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. The figure is rendered and looked at, at full size and at 375 px phone width, before this task is done. Tests alone are not completion evidence.

What changes, and only when a `MeasuredCurve` is passed:
- per-level min–max bars on all three panels;
- the idle point drawn hollow and dashed on the utilisation and throughput panels, so it reads as the one point not taken at load;
- a subtitle stating three runs per level;
- a note naming the unservable level;
- the censoring onset printed to two decimals.

It stays at 0.95, because the idle point lifts utilisation from 0 to 1 between concurrency 0 and 1.

A bare `ServiceCurve` (the placeholder) draws byte-identically to today (Task 6 Step 6 checks the hash). Figure 2 gains one phrase in its note, ` · measured curve` or ` · PLACEHOLDER curve (invented)`, only when `curve_measured` is given. That is plan 2a's open item, done as text rather than a banner strip, because figure 2 has no headroom (`top=0.955`) and a strip would move every pixel of it.

**Files:**
- Modify: `autoscale/figures.py` (`service_curve`, `frontiers`)
- Modify: `scripts/a2_render_figures.py` (pass `measured=` and `curve_measured=`)
- Test: `tests/test_a2_figures.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_a2_figures.py`; reuse its `_texts`, `_rendered` and `MIN_PHONE_TEXT_PX` helpers)

```python
from autoscale.measured_curve import DEFAULT_PATH as _MEASURED_PATH
from autoscale.measured_curve import load_measured_curve

REPO_ROOT = Path(__file__).resolve().parents[1]
MEASURED = load_measured_curve(REPO_ROOT / _MEASURED_PATH)


def _draw_measured(tmp_path):
    return service_curve(MEASURED.curve, tmp_path / "m.png", return_figure=True, measured=MEASURED)


def test_measured_figure_4_draws_an_interval_bar_set_on_every_panel(tmp_path):
    fig = _draw_measured(tmp_path)
    bars = [a for a in fig.findobj() if getattr(a, "get_gid", lambda: None)() == "interval"]
    assert len(bars) == 3


def test_measured_figure_4_marks_the_idle_point_apart(tmp_path):
    fig = _draw_measured(tmp_path)
    idle = [a for a in fig.findobj() if getattr(a, "get_gid", lambda: None)() == "idle"]
    assert len(idle) == 2  # utilisation and throughput panels


def test_measured_figure_4_states_runs_levels_and_the_unservable_level(tmp_path):
    text = " ".join(_texts(_draw_measured(tmp_path)))
    assert "n=8 levels × 3 runs" in text
    assert "256 not servable" in text
    assert "from 0.95" in text
    assert "MEASURED" in text and "NOT MEASURED" not in text


def test_measured_figure_4_clears_the_phone_floor_and_stays_on_canvas(tmp_path):
    fig = _draw_measured(tmp_path)
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(match=matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    w, h = fig.canvas.get_width_height()
    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, text


def test_the_interval_bars_change_the_saved_pixels(tmp_path):
    from PIL import Image, ImageChops
    with_bars = service_curve(MEASURED.curve, tmp_path / "a.png", measured=MEASURED)
    without = service_curve(MEASURED.curve, tmp_path / "b.png")
    diff = ImageChops.difference(Image.open(with_bars).convert("RGB"),
                                 Image.open(without).convert("RGB"))
    assert diff.getbbox() is not None


def test_measured_requires_the_matching_curve(tmp_path):
    with pytest.raises(ValueError, match="same curve"):
        service_curve(SERVICE_CURVE_PLACEHOLDER, tmp_path / "x.png", measured=MEASURED)


def test_figure_2_names_its_curve_only_when_told(tmp_path):
    base = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "f.png", return_figure=True)))
    assert "measured curve" not in base and "PLACEHOLDER curve" not in base
    meas = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "g.png", return_figure=True,
                                     curve_measured=True)))
    assert "measured curve" in meas
    ph = " ".join(_texts(frontiers(ALL_THREE, tmp_path / "h.png", return_figure=True,
                                   curve_measured=False)))
    assert "PLACEHOLDER curve (invented)" in ph
```

(Check the file's existing imports for `Path`, `pytest`, `matplotlib`, `service_curve`, `frontiers`, `ALL_THREE` and `SERVICE_CURVE_PLACEHOLDER`, and add only what is missing. `ALL_THREE` must be a `by_signal` dict accepted by `frontiers`; if the fixture has another shape, use the one `_draw("frontiers", "minimal", ...)` uses.)

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -q -o addopts="" -k "measured or names_its_curve or interval_bars"`
Expected: `TypeError: service_curve() got an unexpected keyword argument 'measured'`.

- [ ] **Step 3: Implement**

In `autoscale/figures.py`, change `service_curve`'s signature to `def service_curve(curve, path, return_figure=False, measured=None):`. Replace the docstring's last paragraph ("No interval band yet...") with:

```
    `measured`, a `MeasuredCurve` for this same curve, adds what only a real
    sweep has: min-max bars per level from its repeats, the idle point drawn
    apart (hollow, dashed: the one point not taken under load), the runs behind
    each point, and the levels the engine could not serve. Without it the
    figure is drawn exactly as before, which is what keeps the placeholder
    draft's pixels unchanged.
```

Then in the body, immediately after `fig, axes = plt.subplots(...)` / `subplots_adjust(...)`:

```python
    if measured is not None and measured.curve is not curve:
        raise ValueError(
            "measured= must carry the same curve being drawn; otherwise the bars and notes "
            "would describe a different measurement than the points they sit on"
        )
    drawn = list(measured.measured_points) if measured is not None else list(curve.points)
    concurrency = [c for c, _, _, _ in drawn]
```

Replace the existing `concurrency = [c for c, _, _, _ in curve.points]` line with the block above (so `x_right` uses the measured levels). In the per-panel loop, plot `drawn`, not `curve.points`, and add the bars and idle point:

```python
    for axis, index, label, key in (
        (axes[0], 1, "latency\n(s)", "latency_s_range"),
        (axes[1], 2, "throughput\n(tok/s)", "throughput_tps_range"),
        (axes[2], 3, "GPU\nutilization", "gpu_util_range"),
    ):
        ys = [p[index] for p in drawn]
        axis.plot(concurrency, ys, "o-", markersize=5, linewidth=2, color=CURVE_COLOR)
        if measured is not None:
            lo = [y - i[key][0] for y, i in zip(ys, measured.intervals, strict=True)]
            hi = [i[key][1] - y for y, i in zip(ys, measured.intervals, strict=True)]
            bars = axis.errorbar(concurrency, ys, yerr=[lo, hi], fmt="none", ecolor=CURVE_COLOR,
                                 elinewidth=1.2, capsize=3)
            # The gid goes on the bar collection itself, not through errorbar's
            # kwargs, which matplotlib copies onto the caps as well.
            for collection in bars.lines[2]:
                collection.set_gid("interval")
            if index in (2, 3):
                idle_y = curve.points[0][index]
                axis.plot([curve.points[0][0], concurrency[0]], [idle_y, ys[0]], linestyle="--",
                          linewidth=1.2, color=CURVE_COLOR)
                axis.plot([curve.points[0][0]], [idle_y], "o", markersize=6,
                          markerfacecolor="white", markeredgecolor=CURVE_COLOR, gid="idle")
        _tidy(axis, "", label, background)
        axis.set_xlim(0, x_right)
        if onset is not None:
            axis.axvspan(onset, x_right, color=CENSOR_COLOR, alpha=BAND_ALPHA,
                         linewidth=0, gid="censored")
```

Replace the banner and note block's measured branch:

```python
    if curve.measured:
        subtitle = "one replica, concurrency swept"
        if measured is not None and measured.runs_per_level:
            subtitle = f"{subtitle}, {min(measured.runs_per_level)} runs per level"
        _figure_banner(fig, left, right, "MEASURED", subtitle, MEASURED_BANNER)
    else:
        _figure_banner(fig, left, right, "NOT MEASURED", "placeholder curve: invented points",
                       MODELED_BANNER)
    if measured is None:
        shading = (
            f"shaded: utilization ≥ {UTILIZATION_CENSOR_AT:g} (from {onset:.1f}), "
            "above every utilization threshold"
            if onset is not None
            else f"utilization ≥ {UTILIZATION_CENSOR_AT:g} never reached in the measured range"
        )
        first = f"n={len(curve.points)} concurrency levels"
    else:
        shading = (
            f"shaded: utilization ≥ {UTILIZATION_CENSOR_AT:g} (from {onset:.2f}), "
            "above every utilization threshold"
            if onset is not None
            else f"utilization ≥ {UTILIZATION_CENSOR_AT:g} never reached in the measured range"
        )
        runs = min(measured.runs_per_level) if measured.runs_per_level else "?"
        first = f"n={len(drawn)} levels × {runs} runs, bars min–max"
        for e in measured.excluded_levels:
            first += f"; {e['concurrency']:g} not servable ({e['n_failed']}/{e['n_runs']} runs)"
    _note(axes[2], f"{first}\n{shading}", y=-0.42)
    return _finish(fig, path, return_figure)
```

In `frontiers`, add a `curve_measured=None` keyword after `allow_missing_intervals`, document it in one docstring sentence ("`curve_measured` adds which service curve the frontiers ran on to the note; a reader who sees only this figure cannot otherwise tell"), and before `_note(...)`:

```python
    if curve_measured is not None:
        note = f"{note} · {'measured curve' if curve_measured else 'PLACEHOLDER curve (invented)'}"
```

In `scripts/a2_render_figures.py`, pass `measured=measured` to `service_curve` (removing the Task 6 comment) and `curve_measured=curve.measured` to `frontiers`.

- [ ] **Step 4: Run the figure tests and the placeholder parity**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py tests/test_a2_render_curve_switch.py -q -o addopts=""
```

Then re-run Task 6 Step 6's parity snippet. Expected: tests pass and `PLACEHOLDER FIGURE 4 PARITY OK`. If the note's first line runs off the canvas at phone width (the on-canvas test fails), shorten the wording; do not shrink the font below `PX_NOTE`.

- [ ] **Step 5: Render the measured figure 4 and LOOK at it at both widths**

```bash
mkdir -p build/a2-figure4-measured
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
from autoscale.figures import service_curve
from autoscale.measured_curve import load_measured_curve
m = load_measured_curve()
p = service_curve(m.curve, "build/a2-figure4-measured/service_curve.png", measured=m)
im = Image.open(p); im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save("build/a2-figure4-measured/service_curve-phone.png")
print(p)
PY
```

Open both PNGs with the Read tool and check each of these by eye:
- **MEASURED banner** with "3 runs per level".
- **Error bars** visible on latency and throughput. On utilisation they are degenerate at 1.0, which is correct.
- **Idle point** hollow at (0, 0) on throughput and utilisation, with a dashed segment.
- **Shaded band** from 0.95 across all three panels.
- **Note** names 256 as not servable.
- **No clipped text, and no overlap** between the note and the x-axis label.

At phone width every label must be readable. Describe what you saw in the report; a test pass is not a substitute.

- [ ] **Step 6: Lint, full suite, commit**

```bash
.venv/bin/ruff check autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
git add autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
git commit -m "figures: figure 4 draws the measured curve's per-level intervals, idle point and unservable level; figure 2 names its curve

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 8: The load-balancer worker — the curve's exact engine, stamped per response

A load-balancing endpoint routes HTTP straight to the worker's `PORT`, with no handler in between. The worker is therefore just `vllm serve`, started with the service curve's exact flags plus one addition: `--middleware a2_middleware.WorkerHeaders`.

The middleware is raw ASGI and imports only the stdlib. It adds two response headers:
- `x-a2-worker`: `RUNPOD_POD_ID`, falling back to the container hostname;
- `x-a2-server-latency-ms`: the time from the request reaching the app to its response starting. For a non-streaming completion that is the whole generation.

The RunPod LB documents no worker-identifying header (verified), so without this the driver cannot attribute a request to a replica (spec §10's `host_id`), nor separate engine latency from WAN and LB time (P6).

`lb_serve.py` refuses to diverge from the curve. Its test compares the command it builds against `served_cmd` in `data/a2/service-curve.json`, and the middleware flag is the only allowed difference.

**Template environment (for the runbook, Task 14):**
- `PORT=8000`, `PORT_HEALTH=8000`, `HEALTH_CHECK_PATH=/health`;
- `MODEL_ID`, `MODEL_REVISION`, `MAX_MODEL_LEN` as on the sweep template;
- `dockerStartCmd`: `python3 -u /opt/lb_serve.py`.

**Files:**
- Create: `worker/a2_middleware.py`, `worker/lb_serve.py`
- Modify: `worker/Dockerfile` (two COPY lines after `COPY worker/sweep_handler.py ...`)
- Test: `tests/test_a2_middleware.py`, `tests/test_lb_serve.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_a2_middleware.py`:

```python
"""The ASGI middleware that stamps worker id and server latency on every response."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from a2_middleware import SERVER_LATENCY_HEADER, WORKER_HEADER, WorkerHeaders  # noqa: E402


class Clock:
    def __init__(self, *ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0)


def _run(app, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b"{}"})


def test_http_responses_carry_the_worker_and_the_server_latency():
    mw = WorkerHeaders(_app, clock=Clock(10.0, 10.25), worker_id="pod-abc")
    start = _run(mw, {"type": "http"})[0]
    headers = dict(start["headers"])
    assert headers[WORKER_HEADER] == b"pod-abc"
    assert headers[SERVER_LATENCY_HEADER] == b"250.000"
    assert headers[b"content-type"] == b"application/json"


def test_the_body_passes_through_untouched():
    mw = WorkerHeaders(_app, clock=Clock(0.0, 0.1), worker_id="w")
    assert _run(mw, {"type": "http"})[1] == {"type": "http.response.body", "body": b"{}"}


def test_non_http_scopes_are_passed_through_without_headers():
    seen = []

    async def lifespan_app(scope, receive, send):
        seen.append(scope["type"])

    _run(WorkerHeaders(lifespan_app, worker_id="w"), {"type": "lifespan"})
    assert seen == ["lifespan"]


def test_the_worker_id_falls_back_to_the_pod_then_the_host(monkeypatch):
    monkeypatch.setenv("RUNPOD_POD_ID", "pod-1")
    assert WorkerHeaders(_app).worker_id == "pod-1"
    monkeypatch.delenv("RUNPOD_POD_ID")
    monkeypatch.setenv("HOSTNAME", "host-9")
    assert WorkerHeaders(_app).worker_id == "host-9"


def test_starlette_style_construction_with_app_keyword_works():
    assert WorkerHeaders(app=_app, worker_id="w").app is _app
```

`tests/test_lb_serve.py`:

```python
"""lb_serve starts the service curve's exact engine, plus the middleware and nothing else."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))

import lb_serve  # noqa: E402

CURVE = json.loads((REPO / "data" / "a2" / "service-curve.json").read_text())
ENV = {"MODEL_ID": "Qwen/Qwen3-8B", "MODEL_REVISION": "b968826d9c46dd6066d109eabc6255188de91218",
       "MAX_MODEL_LEN": "8192", "PORT": "8000"}


def test_the_command_is_the_curves_served_cmd_plus_the_middleware():
    assert lb_serve.command(ENV) == [*CURVE["served_cmd"], "--middleware", lb_serve.MIDDLEWARE]


def test_the_port_comes_from_the_platform():
    cmd = lb_serve.command({**ENV, "PORT": "9001"})
    assert cmd[cmd.index("--port") + 1] == "9001"


def test_a_missing_model_is_refused():
    with pytest.raises(KeyError):
        lb_serve.command({k: v for k, v in ENV.items() if k != "MODEL_ID"})


def test_the_dockerfile_copies_both_files():
    text = (REPO / "worker" / "Dockerfile").read_text()
    assert "COPY worker/lb_serve.py /opt/lb_serve.py" in text
    assert "COPY worker/a2_middleware.py /opt/a2_middleware.py" in text


def test_main_execs_vllm_with_the_command(monkeypatch):
    calls = []
    monkeypatch.setattr(lb_serve.os, "execvp", lambda f, a: calls.append((f, a)))
    monkeypatch.setattr(lb_serve.os, "environ", dict(ENV))
    lb_serve.main()
    assert calls == [("vllm", lb_serve.command(ENV))]
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_middleware.py tests/test_lb_serve.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'a2_middleware'` / `'lb_serve'`.

- [ ] **Step 3: Implement `worker/a2_middleware.py`**

```python
"""ASGI middleware that stamps the serving worker and its own latency on responses.

Loaded into vLLM 0.27.1 with `--middleware a2_middleware.WorkerHeaders`
(PYTHONPATH=/opt in the image). vLLM adds a class with `app.add_middleware()`,
which constructs it as `WorkerHeaders(app=...)`.

Why it exists: a RunPod load-balancing endpoint routes requests to workers
and documents no header saying which one served a request. The open-loop
gate needs that per request: spec §10 requires the host of every replica, and
a request served by a worker outside the pinned set voids the run. It also
needs the engine's own latency, which is what the simulator models, separate
from the WAN and load-balancer time a client-side clock adds.

Raw ASGI, stdlib only, rather than Starlette's BaseHTTPMiddleware: that
wrapper buffers streaming responses and has its own cost per request, and the
measurement must add as little as possible to what it measures.
`x-a2-server-latency-ms` runs from the request reaching this layer to the
response starting. For a non-streaming completion, the response starts after
generation finishes, so it is the request's whole time inside the server.
"""

import os
import time

WORKER_HEADER = b"x-a2-worker"
SERVER_LATENCY_HEADER = b"x-a2-server-latency-ms"


class WorkerHeaders:
    def __init__(self, app, *, clock=time.perf_counter, worker_id=None):
        self.app = app
        self._clock = clock
        self.worker_id = (worker_id or os.environ.get("RUNPOD_POD_ID")
                          or os.environ.get("HOSTNAME") or "unknown")
        self._worker = self.worker_id.encode()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        t0 = self._clock()

        async def stamped(message):
            if message.get("type") == "http.response.start":
                ms = (self._clock() - t0) * 1000.0
                headers = [*message.get("headers", []), (WORKER_HEADER, self._worker),
                           (SERVER_LATENCY_HEADER, f"{ms:.3f}".encode())]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, stamped)
```

- [ ] **Step 4: Implement `worker/lb_serve.py`**

```python
"""Start `vllm serve` for artifact 2's load-balancing endpoint.

The engine must be the one the service curve measured, or the gate compares
the simulator against a different system. So the command is the curve's
`served_cmd` (data/a2/service-curve.json; tests/test_lb_serve.py compares
them), with one addition: the middleware that stamps worker id and server
latency (a2_middleware.py). The port comes from the platform's PORT variable;
the endpoint's HEALTH_CHECK_PATH is set to vLLM's own /health.

`exec`, not a subprocess: the platform's signals then reach vLLM directly,
and no Python parent sits between the load balancer and the engine.
"""

import os

MIDDLEWARE = "a2_middleware.WorkerHeaders"
# The service curve's flags (served_cmd), held fixed.
CURVE_FLAGS = ("--max-num-seqs", "256", "--no-enable-prefix-caching")


def command(env) -> list[str]:
    cmd = ["vllm", "serve", env["MODEL_ID"], "--port", env.get("PORT", "8000")]
    if env.get("MODEL_REVISION"):
        cmd += ["--revision", env["MODEL_REVISION"]]
    if env.get("MAX_MODEL_LEN"):
        cmd += ["--max-model-len", env["MAX_MODEL_LEN"]]
    return [*cmd, *CURVE_FLAGS, "--middleware", MIDDLEWARE]


def main() -> None:
    os.execvp("vllm", command(os.environ))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add the Dockerfile COPY lines**

After `COPY worker/sweep_handler.py /opt/sweep_handler.py` in `worker/Dockerfile`:

```dockerfile
COPY worker/lb_serve.py /opt/lb_serve.py
COPY worker/a2_middleware.py /opt/a2_middleware.py
```

- [ ] **Step 6: Run the tests, the boundary tests and the full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_middleware.py tests/test_lb_serve.py tests/test_harness_boundary.py -q -o addopts=""
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: pass. `test_harness_boundary.py` fails if a `worker/*.py` lacks its COPY line.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check worker/a2_middleware.py worker/lb_serve.py tests/test_a2_middleware.py tests/test_lb_serve.py
git add worker/a2_middleware.py worker/lb_serve.py worker/Dockerfile tests/test_a2_middleware.py tests/test_lb_serve.py
git commit -m "worker: a load-balancer worker that runs the service curve's exact engine and stamps worker id and server latency on every response

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Pushing this commit triggers CI's image rebuild (`worker/**` changed). Pushing is the owner's call; the runbook (Task 14) says to pin the LB template to the new digest.

---

## Task 9: Pin and release `workersMin`, with the owner's `workersMax` checked

Owner decision 3. `WorkerPin` never writes `workersMax`, and it refuses to start unless `workersMax == N` (the owner set it) and `workersMin == 0`.

The release has recon's semantics (`recon/capture_a2.py::restore`). The release and its verifying re-read are retried together on 409, 5xx, connection errors and a re-read that does not yet show 0, until a 300 s deadline. Any other 4xx fails at once, with a message telling the operator to release by hand. After the release it checks that `workersMax` is what the preflight saw. As a context manager, it releases on every exit, including `SystemExit` raised from SIGTERM or SIGHUP by `unwind_on_hangup_and_term()`.

**Files:**
- Create: `harness/runpod/pinning.py`
- Test: `tests/test_pinning.py`

- [ ] **Step 1: Write the failing tests**

```python
"""WorkerPin: pin workersMin to N, always release, never touch workersMax."""

import pytest
import requests

from harness.runpod.pinning import PinRefused, ReleaseFailed, WorkerPin

EID = "ep-lb"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("WorkerPin touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


class Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, endpoint=None, post_script=(), get_script=(), ignore_release=False):
        self.endpoint = dict(endpoint or {"id": EID, "workersMin": 0, "workersMax": 2})
        self.post_script = list(post_script)
        self.get_script = list(get_script)
        self.ignore_release = ignore_release
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        assert headers["Authorization"].startswith("Bearer ")
        if self.post_script:
            step = self.post_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is not None:
                return Resp(step, {"error": "scripted"})
        if not (self.ignore_release and json == {"workersMin": 0}):
            self.endpoint.update(json)
        return Resp(200, dict(self.endpoint))

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        if self.get_script:
            step = self.get_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is not None:
                return Resp(step, {"error": "scripted"})
        return Resp(200, dict(self.endpoint))


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _pin(session, clock=None, workers=2):
    clock = clock or Clock()
    return WorkerPin(EID, "key", workers=workers, session=session, clock=clock.clock,
                     sleep=clock.sleep)


def test_preflight_requires_workers_min_zero_and_workers_max_equal_to_n():
    _pin(FakeSession()).preflight()
    with pytest.raises(PinRefused, match="workersMax"):
        _pin(FakeSession({"workersMin": 0, "workersMax": 3})).preflight()
    with pytest.raises(PinRefused, match="workersMin"):
        _pin(FakeSession({"workersMin": 1, "workersMax": 2})).preflight()


def test_the_context_pins_then_releases_and_never_writes_workers_max():
    s = FakeSession()
    with _pin(s):
        assert s.endpoint["workersMin"] == 2
    assert s.endpoint["workersMin"] == 0
    assert all("workersMax" not in (body or {}) for _, _, body in s.calls)


def test_release_runs_when_the_body_raises():
    s = FakeSession()
    with pytest.raises(RuntimeError, match="boom"):
        with _pin(s):
            raise RuntimeError("boom")
    assert s.endpoint["workersMin"] == 0


def test_release_runs_on_system_exit_from_a_signal():
    s = FakeSession()
    with pytest.raises(SystemExit):
        with _pin(s):
            raise SystemExit(143)
    assert s.endpoint["workersMin"] == 0


def test_a_pin_that_fails_after_writing_is_still_released():
    s = FakeSession(get_script=[None, 500, 500, 500, 500, 500])
    with pytest.raises(Exception):
        with _pin(s):
            pass
    assert s.endpoint["workersMin"] == 0


def test_release_retries_through_409s_and_a_lagging_re_read():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [409, 409]
    s.get_script = [None]
    ep = p.release()
    assert ep["workersMin"] == 0


def test_release_gives_up_loudly_at_the_deadline():
    s = FakeSession(ignore_release=True)
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    p.pin()
    with pytest.raises(ReleaseFailed, match="Set it to 0 by hand"):
        p.release()
    assert clock.t <= 300.0 + 30.0


def test_a_refusal_that_retrying_cannot_fix_fails_at_once():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [403]
    with pytest.raises(ReleaseFailed, match="403"):
        p.release()


def test_a_changed_workers_max_is_reported_after_release():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.endpoint["workersMax"] = 5
    with pytest.raises(RuntimeError, match="workersMax is 5"):
        p.release()
    assert s.endpoint["workersMin"] == 0


def test_connection_errors_during_release_are_retried():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [requests.ConnectionError("reset")]
    assert p.release()["workersMin"] == 0
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_pinning.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'harness.runpod.pinning'`.

- [ ] **Step 3: Implement `harness/runpod/pinning.py`**

```python
"""Pin a serverless endpoint's standing workers, and always release them.

Reconnaissance (docs/recon-a2.md) showed `workersMin` pins workers through
`POST /endpoints/{id}/update`, acknowledged synchronously, and that a pinned
worker bills by the second whether or not anything runs on it. This is the
pin a measurement holds for its duration, then releases.

`workersMax` is never written: it is the cost ceiling, set by the person who
provisioned the endpoint. A fixed-capacity run needs `workersMax == N` so the
platform cannot add workers under load, so the preflight requires it and the
release checks it did not change.

The release copies recon/capture_a2.py's semantics; recon keeps its own copy
because it imports nothing from this repository by design. The release and
its verifying re-read are retried together until a deadline, because RunPod
answers 409 for a while after any configuration change and the release
always follows one. "The POST returned 200" is not proof: only a re-read
showing 0 is. A refusal retrying cannot fix fails at once, with the manual
remedy in the message.
"""

import itertools
import signal
import time

import requests

REST = "https://rest.runpod.io/v1"
RELEASE_DEADLINE_SECONDS = 300.0
BACKOFF_CAP_SECONDS = 30.0
PIN_ATTEMPTS = 5


class PinRefused(RuntimeError):
    """The endpoint is not in the state a pinned run needs; nothing was written."""


class ReleaseFailed(RuntimeError):
    """workersMin could not be confirmed back at 0; a worker may still be billing."""


class _Retryable(Exception):
    pass


def _transient(status: int) -> bool:
    return status == 409 or status >= 500


class WorkerPin:
    def __init__(self, endpoint_id: str, api_key: str, *, workers: int, session=requests,
                 clock=time.monotonic, sleep=time.sleep):
        if type(workers) is not int or workers < 1:
            raise ValueError(f"workers is {workers!r}; a pin is a positive int of workers")
        self._id = endpoint_id
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._workers = workers
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._workers_max = None

    @property
    def workers(self) -> int:
        return self._workers

    def _url(self, suffix: str = "") -> str:
        return f"{REST}/endpoints/{self._id}{suffix}"

    def endpoint(self) -> dict:
        r = self._session.get(self._url(), headers=self._headers, timeout=30)
        if not 200 <= r.status_code < 300:
            raise PinRefused(f"GET endpoint {self._id} returned {r.status_code}")
        return r.json()

    def preflight(self) -> dict:
        ep = self.endpoint()
        problems = []
        if ep.get("workersMin") != 0:
            problems.append(
                f"workersMin is {ep.get('workersMin')!r}, not 0: something already holds "
                "workers, and this run would release them when it ends")
        if ep.get("workersMax") != self._workers:
            problems.append(
                f"workersMax is {ep.get('workersMax')!r}, not {self._workers}: a fixed-capacity "
                "run needs the ceiling equal to the pin, or the platform can add workers under "
                "load. workersMax is the owner's to set; this code never writes it")
        if problems:
            raise PinRefused("; ".join(problems))
        self._workers_max = ep["workersMax"]
        return ep

    def pin(self) -> dict:
        for attempt in range(PIN_ATTEMPTS):
            r = self._session.post(self._url("/update"), headers=self._headers,
                                   json={"workersMin": self._workers}, timeout=30)
            if _transient(r.status_code) and attempt < PIN_ATTEMPTS - 1:
                self._sleep(2.0**attempt)
                continue
            if not 200 <= r.status_code < 300:
                raise RuntimeError(f"the pin POST returned {r.status_code}")
            break
        ep = self.endpoint()
        if ep.get("workersMin") != self._workers:
            raise RuntimeError(
                f"the re-read after the pin shows workersMin {ep.get('workersMin')!r}, not "
                f"{self._workers}; the run would measure a fleet it did not pin")
        return ep

    def _release_once(self) -> dict:
        r = self._session.post(self._url("/update"), headers=self._headers,
                               json={"workersMin": 0}, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the release POST returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise ReleaseFailed(self._manual(f"the release POST returned {r.status_code}"))
        r = self._session.get(self._url(), headers=self._headers, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the verifying re-read returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise ReleaseFailed(self._manual(f"the verifying re-read returned {r.status_code}"))
        try:
            ep = r.json()
        except ValueError as e:
            raise _Retryable(f"the verifying re-read was not JSON ({e})") from e
        if not isinstance(ep, dict):
            raise _Retryable(f"the verifying re-read was not an endpoint object: {str(ep)[:80]!r}")
        if ep.get("workersMin") != 0:
            # Possibly propagation lag after an accepted write; POST again.
            raise _Retryable(f"the re-read shows workersMin {ep.get('workersMin')!r}")
        return ep

    def _manual(self, cause: str) -> str:
        return (f"RELEASE FAILED: could not confirm workersMin is 0 on endpoint {self._id} "
                f"(last: {cause}). Set it to 0 by hand now; a pinned worker bills "
                "continuously whether or not anything is running on it")

    def release(self) -> dict:
        deadline = self._clock() + RELEASE_DEADLINE_SECONDS
        for attempt in itertools.count():
            try:
                ep = self._release_once()
                break
            except (_Retryable, requests.RequestException) as e:
                wait = min(2.0**attempt, BACKOFF_CAP_SECONDS)
                if self._clock() + wait > deadline:
                    raise ReleaseFailed(self._manual(str(e))) from e
                self._sleep(wait)
        if self._workers_max is not None and ep.get("workersMax") != self._workers_max:
            raise RuntimeError(
                f"workersMax is {ep.get('workersMax')!r} after the run but was "
                f"{self._workers_max!r} at preflight. workersMin is back to 0, but this code "
                "never writes workersMax, so something else changed the cost ceiling during "
                "the run: treat its evidence as collected under a ceiling nobody checked")
        return ep

    def __enter__(self):
        self.preflight()
        try:
            self.pin()
        except BaseException:
            self.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _exit_on_signal(signum, frame):
    for other in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(other, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def unwind_on_hangup_and_term() -> None:
    """Make SIGTERM and SIGHUP unwind through a `with WorkerPin(...)` release.

    By default both end the process without unwinding, leaving workers pinned
    and billing. Raising SystemExit from a handler turns them into an ordinary
    unwind; the first one ignores any that follow, so a second signal cannot
    cut the bounded release short. `kill -9` cannot be handled: release by hand.
    """
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on_signal)
```

- [ ] **Step 4: Run the tests and the shared-tooling boundary**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_pinning.py tests/test_shared_tooling_boundary.py -q -o addopts=""
```

Expected: pass. `harness/` still loads neither `coldstart` nor `autoscale`.

- [ ] **Step 5: Lint, full suite, commit**

```bash
.venv/bin/ruff check harness/runpod/pinning.py tests/test_pinning.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
git add harness/runpod/pinning.py tests/test_pinning.py
git commit -m "harness: pin a serverless endpoint's workersMin for a run and always release it, never touching workersMax

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 10: The open-loop sender — replay a schedule over HTTP, recording send times

The gate's driver obligations (plan 2a's final report):
- **send times on the schedule's own clock,** with t=0 at the schedule's zero;
- **`until` is the configured window,** not a measured end;
- **raw latencies are kept** even when a request finishes past `until` (windowing is `RealRun.windowed_latencies`'s job).

`replay` dispatches each request at `t0 + scheduled` from one thread. Sends run in a thread pool, and each records its own send time just before the request leaves, so a saturated pool shows up as send jitter instead of hiding. Generic, so it lives in `harness/`; artifacts 4 and 5 may reuse it.

Rejected:
- **asyncio + aiohttp:** a new dependency.
- **`vllm bench serve --request-rate`:** it draws its own Poisson stream and cannot replay a fixed schedule (shared-tooling plan: "exact-timestamp trace replay … unverified").

**Files:**
- Create: `harness/open_loop.py`
- Test: `tests/test_open_loop.py`

- [ ] **Step 1: Write the failing tests**

```python
"""replay(): one schedule, sent on its own clock, every outcome kept."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness.open_loop import Outcome, http_sender, max_jitter, replay


def test_outcomes_come_back_in_schedule_order_with_send_times_near_schedule():
    schedule = [i * 0.01 for i in range(40)]
    outs = replay(schedule, lambda i: (200, {}), max_in_flight=8, start_delay=0.05)
    assert [o.index for o in outs] == list(range(40))
    assert all(isinstance(o, Outcome) and o.status == 200 for o in outs)
    assert max_jitter(outs) < 0.2
    assert all(o.latency is not None and o.latency >= 0 for o in outs)


def test_a_failed_send_is_kept_as_an_error_not_dropped():
    def send(i):
        if i == 2:
            raise ConnectionError("reset by peer")
        return (200, {})

    outs = replay([0.0, 0.01, 0.02, 0.03], send, max_in_flight=2, start_delay=0.01)
    assert len(outs) == 4
    assert outs[2].status is None and outs[2].latency is None
    assert "ConnectionError: reset by peer" in outs[2].error


def test_an_unsorted_schedule_is_refused():
    with pytest.raises(ValueError, match="ascending"):
        replay([0.0, 0.5, 0.2], lambda i: (200, {}))


def test_a_negative_time_is_refused():
    with pytest.raises(ValueError, match="negative"):
        replay([-0.1, 0.0], lambda i: (200, {}))


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("x-a2-worker", "w-local")
        self.send_header("x-a2-server-latency-ms", "12.5")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/completions"
    srv.shutdown()


def test_http_sender_returns_status_and_the_kept_headers(server):
    send = http_sender(server, payload={"x": 1}, headers={"Authorization": "Bearer k"},
                       timeout=5.0, keep_headers=("x-a2-worker", "x-a2-server-latency-ms"))
    status, headers = send(0)
    assert status == 200
    assert headers == {"x-a2-worker": "w-local", "x-a2-server-latency-ms": "12.5"}


def test_replay_through_http_sender_end_to_end(server):
    send = http_sender(server, payload={}, headers={}, timeout=5.0, keep_headers=("x-a2-worker",))
    outs = replay([i * 0.005 for i in range(50)], send, max_in_flight=16, start_delay=0.05)
    assert sum(o.status == 200 for o in outs) == 50
    assert {o.headers["x-a2-worker"] for o in outs} == {"w-local"}
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_open_loop.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'harness.open_loop'`.

- [ ] **Step 3: Implement `harness/open_loop.py`**

```python
"""Open-loop HTTP replay: send each request at its scheduled time, whatever the server does.

Open loop means the schedule, not the server, decides when each request
leaves: a slow response never delays the next send. That is what makes a
real run comparable to the simulator fed the same arrival times; a closed
loop (`vllm bench serve --max-concurrency`) lets the server's speed shape the
arrivals and confounds the two.

One dispatcher thread sleeps until each scheduled time and hands the request
to a pool. Each worker thread stamps `sent` immediately before the request
leaves, so if the pool is exhausted, the delay shows as send jitter, which the
caller checks (`max_jitter`; artifact 2's gate refuses a run above 0.5 s). It
is not hidden inside a latency. Every request yields an `Outcome`: a failure
is an outcome with an error, never a missing row, because a dropped row
would shrink exactly the bins where the server was struggling.

Times are seconds on `clock` relative to t0, the moment the schedule's zero
is placed (`start_delay` after the call, so the pool is up before the first
send).
"""

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

__all__ = ["Outcome", "http_sender", "max_jitter", "replay"]


@dataclass(frozen=True)
class Outcome:
    index: int
    scheduled: float
    sent: float | None
    latency: float | None
    status: int | None
    headers: dict = field(default_factory=dict)
    error: str | None = None


def max_jitter(outcomes: Sequence[Outcome]) -> float:
    return max((abs(o.sent - o.scheduled) for o in outcomes if o.sent is not None), default=0.0)


def replay(schedule: Sequence[float], send: Callable[[int], tuple[int, dict]], *,
           max_in_flight: int = 1024, start_delay: float = 0.5,
           clock=time.monotonic, sleep=time.sleep) -> list[Outcome]:
    times = list(schedule)
    if any(t < 0 for t in times):
        raise ValueError("the schedule has a negative time; t=0 is the schedule's start")
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError(
            "the schedule is not ascending; replay sends in list order, so an out-of-order "
            "entry would be sent late and recorded as jitter the driver caused"
        )
    t0 = clock() + start_delay
    results: list[Outcome | None] = [None] * len(times)

    def one(i: int, scheduled: float) -> None:
        sent = clock() - t0
        try:
            status, headers = send(i)
        except Exception as e:  # noqa: BLE001 -- every failure is data, kept per request
            results[i] = Outcome(i, scheduled, sent, None, None, {}, f"{type(e).__name__}: {e}"[:300])
            return
        results[i] = Outcome(i, scheduled, sent, clock() - t0 - sent, status, dict(headers))

    with ThreadPoolExecutor(max_workers=max_in_flight) as pool:
        for i, scheduled in enumerate(times):
            wait = t0 + scheduled - clock()
            if wait > 0:
                sleep(wait)
            pool.submit(one, i, scheduled)
    return [r for r in results if r is not None]


def http_sender(url: str, *, payload: dict, headers: dict, timeout: float,
                keep_headers: Sequence[str] = (), session_factory=requests.Session):
    """A `send(i)` that POSTs `payload` to `url`, one keep-alive session per thread."""
    local = threading.local()
    keep = tuple(h.lower() for h in keep_headers)

    def send(i: int) -> tuple[int, dict]:
        session = getattr(local, "session", None)
        if session is None:
            session = local.session = session_factory()
        r = session.post(url, json=payload, headers=headers, timeout=timeout)
        got = {k.lower(): v for k, v in r.headers.items()}
        return r.status_code, {h: got[h] for h in keep if h in got}

    return send
```

- [ ] **Step 4: Run the tests, the boundary, lint, full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_open_loop.py tests/test_shared_tooling_boundary.py -q -o addopts=""
.venv/bin/ruff check harness/open_loop.py tests/test_open_loop.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: pass. If `test_outcomes_come_back_in_schedule_order_with_send_times_near_schedule` is flaky on this machine, investigate the dispatcher, not the 0.2 s bound; it is generous for a 0.4 s schedule.

- [ ] **Step 5: Commit**

```bash
git add harness/open_loop.py tests/test_open_loop.py
git commit -m "harness: open-loop HTTP replay that sends on the schedule's clock and keeps every outcome

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: The paid feasibility probe — rate ladder through the load balancer

Owner decision 2: probe before any validation repeat. This task builds `scripts/a2_lb_probe.py` and proves it offline. **Running it is the owner's spend (~$0.50) and follows the runbook (Task 14).**

The probe:
1. pins 2 workers;
2. warms up until both answer;
3. runs a constant-rate ladder: 25, 50, 100, 200, 300 and 450 req/s, 30 s per step;
4. releases;
5. prints, per step: requests, non-200s, errors, each worker's share, client and server p50, their gap, and maximum send jitter;
6. prints the amendment's acceptance verdict at 450 req/s.

The request is the curve's shape: 13 prompt token IDs (`prompt` as a list of ints, so the length is exact without a tokenizer), `max_tokens` 16, `ignore_eos` true, and no sampling parameters, so the server's defaults apply as they did for the sweep's bench requests.

Shared pieces live in `scripts/a2_lb_common.py`, so Task 12 uses the same URL, payload, warm-up and summary:
- `lb_url`
- `payload`
- `sender`
- `constant_rate`
- `warm_up`
- `summarize`

**Files:**
- Create: `scripts/a2_lb_common.py`, `scripts/a2_lb_probe.py`
- Test: `tests/test_a2_lb_probe.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The LB probe and its shared pieces, with no network."""

import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common  # noqa: E402
import a2_lb_probe as probe  # noqa: E402
from harness.open_loop import Outcome  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the probe test touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


def test_the_url_and_payload_match_the_curves_request_shape():
    assert common.lb_url("abc123") == "https://abc123.api.runpod.ai/v1/completions"
    p = common.payload()
    assert len(p["prompt"]) == 13 and all(isinstance(t, int) for t in p["prompt"])
    assert p["max_tokens"] == 16 and p["ignore_eos"] is True
    assert "temperature" not in p and p["model"] == "Qwen/Qwen3-8B"


def test_constant_rate_spaces_requests_evenly():
    s = common.constant_rate(4.0, 2.0)
    assert s == (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75)


def _o(i, status=200, worker="w1", client=0.5, server_ms="300.0", sent=None):
    sent = i * 0.1 if sent is None else sent
    headers = {} if worker is None else {common.WORKER: worker, common.SERVER_LATENCY: server_ms}
    return Outcome(i, i * 0.1, sent, client if status else None, status, headers,
                   None if status else "err")


def test_summarize_counts_shares_latencies_and_jitter():
    outs = [_o(0), _o(1, worker="w2"), _o(2, worker="w2"), _o(3, status=503), _o(4, sent=0.9)]
    s = common.summarize(outs)
    assert s["requests"] == 5 and s["non_200"] == 1
    assert s["worker_share"] == {"w1": 0.5, "w2": 0.5}
    assert s["client_p50_s"] == pytest.approx(0.5)
    assert s["server_p50_s"] == pytest.approx(0.3)
    assert s["client_minus_server_p50_s"] == pytest.approx(0.2)
    assert s["max_jitter_s"] == pytest.approx(0.5)


class FakeReplay:
    """Answers each warm-up chunk from a script of worker ids."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __call__(self, schedule, send, **kw):
        workers = self.chunks.pop(0)
        return [Outcome(i, t, t, 0.3, 200 if w else 503, {common.WORKER: w} if w else {})
                for i, (t, w) in enumerate(zip(schedule, workers * len(schedule)))]


def test_warm_up_returns_once_all_workers_answered_cleanly_long_enough():
    rep = FakeReplay([["w1"], ["w1", "w2"], ["w1", "w2"], ["w1", "w2"], ["w1", "w2"],
                      ["w1", "w2"], ["w1", "w2"], ["w1", "w2"]])
    ids = common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                         max_seconds=600.0, chunk_seconds=5.0, replay_fn=rep)
    assert ids == ["w1", "w2"]


def test_warm_up_refuses_more_workers_than_pinned():
    rep = FakeReplay([["w1", "w2", "w3"]])
    with pytest.raises(RuntimeError, match="3 distinct workers"):
        common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                       max_seconds=600.0, chunk_seconds=5.0, replay_fn=rep)


def test_warm_up_gives_up_at_its_limit():
    rep = FakeReplay([["w1"]] * 10)
    with pytest.raises(TimeoutError, match="1 of 2"):
        common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                       max_seconds=20.0, chunk_seconds=5.0, replay_fn=rep)


def test_acceptance_reads_the_amendments_three_conditions():
    ok = {"non_200": 0, "errors": 0, "worker_share": {"a": 0.5, "b": 0.5}, "max_jitter_s": 0.1}
    assert probe.accept(ok, workers=2) == (True, [])
    bad = {"non_200": 2, "errors": 0, "worker_share": {"a": 0.8, "b": 0.2}, "max_jitter_s": 0.4}
    passed, why = probe.accept(bad, workers=2)
    assert not passed and len(why) == 3


def test_the_ladder_and_thresholds_are_the_amendments():
    assert probe.RATES == (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
    assert probe.STEP_SECONDS == 30.0
    assert probe.MIN_WORKER_SHARE == 0.35 and probe.MAX_JITTER_S == 0.25
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_lb_probe.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'a2_lb_common'`.

- [ ] **Step 3: Implement `scripts/a2_lb_common.py`**

```python
"""What artifact 2's LB probe and validation driver share: where, what and how to send.

The request is the service curve's shape: 13 prompt tokens, 16 output tokens,
generation not stopped early. The prompt is a list of token IDs, which the
OpenAI completions API accepts, so its length is exact without a tokenizer
here. No sampling parameters are sent: the sweep's bench requests sent none,
so both use the server's defaults (the model's generation_config).
"""

import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.open_loop import http_sender, max_jitter, replay  # noqa: E402

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"
MODEL = "Qwen/Qwen3-8B"
PROMPT_TOKEN_IDS = tuple(range(1000, 1013))
OUTPUT_TOKENS = 16
REQUEST_TIMEOUT_S = 120.0


def lb_url(endpoint_id: str) -> str:
    return f"https://{endpoint_id}.api.runpod.ai/v1/completions"


def payload() -> dict:
    return {"model": MODEL, "prompt": list(PROMPT_TOKEN_IDS), "max_tokens": OUTPUT_TOKENS,
            "ignore_eos": True}


def sender(endpoint_id: str, api_key: str):
    return http_sender(lb_url(endpoint_id), payload=payload(),
                       headers={"Authorization": f"Bearer {api_key}"},
                       timeout=REQUEST_TIMEOUT_S, keep_headers=(WORKER, SERVER_LATENCY))


def constant_rate(rate: float, seconds: float) -> tuple[float, ...]:
    return tuple(i / rate for i in range(int(round(rate * seconds))))


def server_latency_s(outcome) -> float | None:
    raw = outcome.headers.get(SERVER_LATENCY)
    return None if raw is None else float(raw) / 1000.0


def warm_up(send, *, workers: int, rps: float, min_clean: float, max_seconds: float,
            chunk_seconds: float = 5.0, replay_fn=replay, clock=time.monotonic) -> list[str]:
    """Light load until all `workers` pinned workers have answered, cleanly, for `min_clean` s.

    Returns their ids: the run's host_ids. Refuses more distinct workers than
    pinned, because the fleet is then not the one the run is about to measure.
    """
    seen: set[str] = set()
    clean = 0.0
    elapsed = 0.0
    while True:
        outs = replay_fn(constant_rate(rps, chunk_seconds), send, max_in_flight=64,
                         start_delay=0.1)
        elapsed += chunk_seconds
        seen |= {o.headers[WORKER] for o in outs if WORKER in o.headers}
        if len(seen) > workers:
            raise RuntimeError(
                f"{len(seen)} distinct workers answered ({sorted(seen)}) with {workers} pinned; "
                "the endpoint is not the fleet the run would measure. Check workersMax")
        clean = clean + chunk_seconds if all(o.status == 200 for o in outs) else 0.0
        if len(seen) == workers and clean >= min_clean:
            return sorted(seen)
        if elapsed >= max_seconds:
            raise TimeoutError(
                f"after {elapsed:g} s, {len(seen)} of {workers} pinned workers answered "
                f"(clean streak {clean:g} s); not starting a run on a fleet that is not up")


def summarize(outcomes) -> dict:
    ok = [o for o in outcomes if o.status == 200]
    workers = [o.headers.get(WORKER) for o in ok if o.headers.get(WORKER)]
    share = {w: workers.count(w) / len(workers) for w in sorted(set(workers))} if workers else {}
    client = [o.latency for o in ok if o.latency is not None]
    server = [s for s in (server_latency_s(o) for o in ok) if s is not None]
    c50 = median(client) if client else None
    s50 = median(server) if server else None
    return {
        "requests": len(outcomes),
        "non_200": sum(1 for o in outcomes if o.status is not None and o.status != 200),
        "errors": sum(1 for o in outcomes if o.error),
        "worker_share": share,
        "client_p50_s": c50,
        "server_p50_s": s50,
        "client_minus_server_p50_s": None if c50 is None or s50 is None else c50 - s50,
        "max_jitter_s": max_jitter(outcomes),
    }
```

- [ ] **Step 4: Implement `scripts/a2_lb_probe.py`**

```python
"""Paid feasibility probe for artifact 2's open-loop gate (plan 2b P1-P8).

SPENDS MONEY: two pinned RTX 4090 workers for ~10 minutes. The owner runs it
(docs/runbook-a2-validation.md). Reads RUNPOD_API_KEY and
RUNPOD_A2_LB_ENDPOINT_ID; never prints the key.

Pins 2 workers, warms up until both answer, then runs a constant-rate ladder
through the load balancer and releases (on any exit, including SIGTERM and
SIGHUP). Each step's outcomes go to <out>/step-<rate>.jsonl; the summary per
step goes to stdout and <out>/summary.json. The verdict at 450 req/s is the
amendment's acceptance rule; anything short of it stops the validation runs
until the owner decides.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import constant_rate, sender, summarize, warm_up  # noqa: E402

from autoscale.validation_schedule import (  # noqa: E402
    VALIDATION_REPLICAS,
    WARMUP_MAX_SECONDS,
    WARMUP_MIN_SECONDS,
    WARMUP_RPS,
)
from harness.open_loop import replay  # noqa: E402
from harness.runpod.pinning import WorkerPin, unwind_on_hangup_and_term  # noqa: E402

RATES = (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
STEP_SECONDS = 30.0
MIN_WORKER_SHARE = 0.35
MAX_JITTER_S = 0.25


def accept(summary: dict, *, workers: int) -> tuple[bool, list[str]]:
    why = []
    if summary["non_200"] or summary["errors"]:
        why.append(f"{summary['non_200']} non-200 and {summary['errors']} errors at the top step")
    shares = summary["worker_share"]
    if len(shares) != workers or min(shares.values(), default=0.0) < MIN_WORKER_SHARE:
        why.append(f"worker shares {shares}: each of {workers} must serve >= {MIN_WORKER_SHARE:.0%}")
    if summary["max_jitter_s"] > MAX_JITTER_S:
        why.append(f"max send jitter {summary['max_jitter_s']:.3f} s > {MAX_JITTER_S} s")
    return (not why, why)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a2-lb-probe")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args(argv)
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_A2_LB_ENDPOINT_ID"]
    pin = WorkerPin(endpoint, key, workers=VALIDATION_REPLICAS)
    if args.preflight_only:
        ep = pin.preflight()
        print(f"[preflight] {endpoint}: workersMin {ep['workersMin']}, workersMax "
              f"{ep['workersMax']}; nothing written")
        return
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; move the earlier probe aside first")
    out.mkdir(parents=True, exist_ok=True)
    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    rows = {}
    with pin:
        ids = warm_up(send, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS,
                      min_clean=WARMUP_MIN_SECONDS, max_seconds=WARMUP_MAX_SECONDS)
        print(f"[warm] workers {ids}")
        for rate in RATES:
            outs = replay(constant_rate(rate, STEP_SECONDS), send)
            with (out / f"step-{rate:g}.jsonl").open("w") as fh:
                for o in outs:
                    fh.write(json.dumps(asdict(o)) + "\n")
            rows[rate] = summarize(outs)
            print(f"[{rate:>5g} req/s] {json.dumps(rows[rate])}", flush=True)
    (out / "summary.json").write_text(json.dumps({"workers": ids, "steps": rows}, indent=1))
    passed, why = accept(rows[RATES[-1]], workers=VALIDATION_REPLICAS)
    print("[accept] PASS" if passed else "[accept] FAIL: " + "; ".join(why))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests, lint, full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_lb_probe.py -q -o addopts=""
.venv/bin/ruff check scripts/a2_lb_common.py scripts/a2_lb_probe.py tests/test_a2_lb_probe.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/a2_lb_common.py scripts/a2_lb_probe.py tests/test_a2_lb_probe.py
git commit -m "validation: the paid load-balancer feasibility probe, built and proven offline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 12: The validation driver — one pinned repeat at a time, then the verdict

`scripts/a2_validate.py` has three modes:
- `--preflight-only`: free.
- `--repeat K`: paid. It pins `VALIDATION_REPLICAS` workers, warms up, replays the schedule once, releases, and writes `data/a2/validation/repeat-K.json.gz`.
- `--judge`: free. It loads repeats 1–3, builds `RealRun`s from the pre-registered latency source, calls `validate()`, and writes `data/a2/validation/verdict.json`.

A repeat is recorded with every request's:
- scheduled and sent time;
- server and client latency;
- status, worker and error.

It is also tagged with its void reasons (amendment 2026-10-04):
- any non-200;
- a response from a worker outside the pinned set;
- a 200 without the server-latency header;
- an outcome count that differs from the schedule.

A void repeat may be run again once. Its file moves aside to `repeat-K.void.json.gz`, and a second void at the same K stops with "not evaluable". A valid repeat is never overwritten.

Host novelty means a pinned worker id in repeat K that no earlier repeat saw. It is reported in the verdict, not voided (spec §10).

**Files:**
- Create: `scripts/a2_validate.py`
- Test: `tests/test_a2_validate.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The validation driver's record, slots, repeat flow and verdict, with no network."""

import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_validate as v  # noqa: E402
from a2_lb_common import SERVER_LATENCY, WORKER  # noqa: E402
from autoscale.service import ServiceCurve  # noqa: E402
from autoscale.sim import run_fixed_capacity  # noqa: E402
from autoscale.validation_schedule import build_schedule  # noqa: E402
from harness.open_loop import Outcome  # noqa: E402

CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                     measured=True)
UNTIL = 200.0


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the validation test touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


def _schedule():
    return build_schedule(CURVE, replicas=2, kind="step", until=UNTIL, drain=20.0, seed=1)


def _model_latencies(schedule):
    result = run_fixed_capacity(list(schedule), 2, CURVE, UNTIL)
    by_arrival = dict(result.completed_requests())
    return [by_arrival[t] for t in schedule]


def _outs(schedule, factor=1.0, *, status=200, workers=("w1", "w2"), drop_header_at=None):
    lat = _model_latencies(schedule)
    outs = []
    for i, (t, l) in enumerate(zip(schedule, lat)):
        headers = {WORKER: workers[i % len(workers)], SERVER_LATENCY: f"{l * factor * 1000:.3f}"}
        if i == drop_header_at:
            headers.pop(SERVER_LATENCY)
        outs.append(Outcome(i, t, t, l * factor + 0.1, status, headers))
    return outs


def _record(schedule, outs, k=1, host_ids=("w1", "w2")):
    return v.record_from(outs, repeat=k, schedule=schedule, host_ids=list(host_ids),
                         endpoint_id="ep", template_id="tpl", started_at="2026-10-05T00:00:00Z",
                         replicas=2, until=UNTIL)


def test_a_clean_repeat_is_not_void_and_keeps_both_latencies():
    s = _schedule()
    rec = _record(s, _outs(s))
    assert rec["void"] == []
    assert len(rec["server_latency_s"]) == len(rec["client_latency_s"]) == len(s)
    assert rec["client_latency_s"][0] == pytest.approx(rec["server_latency_s"][0] + 0.1)


def test_void_reasons_non_200_novel_worker_and_missing_header():
    s = _schedule()
    assert "without a 200" in " ".join(_record(s, _outs(s, status=503))["void"])
    assert "outside the pinned set" in " ".join(
        _record(s, _outs(s, workers=("w1", "w2", "w9")))["void"])
    assert "server-latency header" in " ".join(_record(s, _outs(s, drop_header_at=3))["void"])


def test_slots_never_overwrite_a_valid_repeat_and_allow_one_void_rerun(tmp_path):
    s = _schedule()
    path = v.prepare_slot(tmp_path, 1)
    v.write_record(path, _record(s, _outs(s, status=503)))
    again = v.prepare_slot(tmp_path, 1)
    assert (tmp_path / "repeat-1.void.json.gz").exists() and again == path
    v.write_record(path, _record(s, _outs(s, status=503)))
    with pytest.raises(SystemExit, match="not evaluable"):
        v.prepare_slot(tmp_path, 1)
    v.write_record(v.prepare_slot(tmp_path, 2), _record(s, _outs(s), k=2))
    with pytest.raises(SystemExit, match="never re-run"):
        v.prepare_slot(tmp_path, 2)


class FakePin:
    def __init__(self):
        self.events = []

    def __enter__(self):
        self.events.append("pin")
        return self

    def __exit__(self, *exc):
        self.events.append("release")
        return False


def test_run_repeat_pins_warms_replays_and_releases():
    s = _schedule()
    pin = FakePin()
    rec = v.run_repeat(k=1, schedule=s, pin=pin, send=lambda i: (200, {}),
                       warm_fn=lambda send: ["w1", "w2"], replay_fn=lambda sch, send: _outs(s),
                       endpoint_id="ep", template_id="tpl", replicas=2, until=UNTIL,
                       now=lambda: "t")
    assert pin.events == ["pin", "release"] and rec["host_ids"] == ["w1", "w2"]


def test_run_repeat_releases_when_the_replay_fails():
    pin = FakePin()

    def boom(sch, send):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        v.run_repeat(k=1, schedule=_schedule(), pin=pin, send=None,
                     warm_fn=lambda send: ["w1", "w2"], replay_fn=boom, endpoint_id="ep",
                     template_id="tpl", replicas=2, until=UNTIL, now=lambda: "t")
    assert pin.events == ["pin", "release"]


def _three(tmp_path, factors, hosts=(("w1", "w2"),) * 3):
    s = _schedule()
    for k, (f, h) in enumerate(zip(factors, hosts), start=1):
        v.write_record(v.prepare_slot(tmp_path, k),
                       _record(s, _outs(s, f, workers=h), k=k, host_ids=h))


def test_judge_passes_a_model_inside_realitys_spread(tmp_path):
    _three(tmp_path, (0.97, 1.0, 1.03))
    verdict = v.judge(tmp_path, CURVE)
    assert verdict["outcome"] == "passed" and verdict["compared"] >= 10
    assert verdict["latency_source"] == "server"


def test_judge_fails_a_model_outside_it(tmp_path):
    _three(tmp_path, (1.4, 1.45, 1.5))
    assert v.judge(tmp_path, CURVE)["outcome"] == "failed"


def test_judge_reports_host_novelty_without_voiding(tmp_path):
    _three(tmp_path, (0.97, 1.0, 1.03), hosts=(("w1", "w2"), ("w1", "w2"), ("w1", "w3")))
    verdict = v.judge(tmp_path, CURVE)
    assert verdict["host_novelty"] == {"3": ["w3"]}


def test_judge_refuses_a_missing_or_void_repeat(tmp_path):
    s = _schedule()
    v.write_record(v.prepare_slot(tmp_path, 1), _record(s, _outs(s)))
    with pytest.raises(SystemExit, match="repeat 2"):
        v.judge(tmp_path, CURVE)


def test_the_lb_pin_set_names_the_gpu_and_volume():
    assert v.lb_pins("tpl-1") == {"gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
                                  "networkVolumeId": "9c7ut2slrd", "templateId": "tpl-1"}
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_validate.py -q -o addopts=""`
Expected: `ModuleNotFoundError: No module named 'a2_validate'`.

- [ ] **Step 3: Implement `scripts/a2_validate.py`**

```python
"""Artifact 2's open-loop validation gate against RunPod (spec §10).

`--repeat K` SPENDS MONEY: VALIDATION_REPLICAS pinned RTX 4090 workers for
about ten minutes. The owner runs it (docs/runbook-a2-validation.md), only
after the LB probe passed the amendment's acceptance rule. Reads
RUNPOD_API_KEY and RUNPOD_A2_LB_ENDPOINT_ID; never prints the key.

One repeat: preflight (GPU, volume, template; workersMin 0, workersMax == N),
pin, warm up until all N workers answer cleanly (their ids are the run's
host_ids), replay the ONE pre-registered schedule open-loop, release on any
exit, and write every request to data/a2/validation/repeat-K.json.gz.
`--judge` builds RealRuns from the pre-registered latency source and calls
autoscale.validation.validate.

Void rules (amendment 2026-10-04): any non-200, a response from a worker
outside the pinned set, a 200 without the server-latency header, or a short
outcome list. A void repeat is kept, moved aside, and may be run once more;
a valid repeat is never overwritten, because re-running until the band fits
is the failure the fixed repeat count exists to prevent.
"""

import argparse
import gzip
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from a2_lb_common import WORKER, sender, server_latency_s, warm_up  # noqa: E402

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve  # noqa: E402
from autoscale.validation import REPEATS, RealRun, validate  # noqa: E402
from autoscale.validation_schedule import (  # noqa: E402
    LATENCY_SOURCE,
    VALIDATION_DRAIN_SECONDS,
    VALIDATION_KIND,
    VALIDATION_REPLICAS,
    VALIDATION_SEED,
    VALIDATION_UNTIL,
    WARMUP_MAX_SECONDS,
    WARMUP_MIN_SECONDS,
    WARMUP_RPS,
    build_schedule,
)
from harness.open_loop import max_jitter, replay  # noqa: E402
from harness.runpod.pinning import WorkerPin, unwind_on_hangup_and_term  # noqa: E402
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint  # noqa: E402

OUT = Path("data/a2/validation")
SCHEMA_VERSION = 1


def lb_pins(template_id: str) -> dict:
    return {"gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "9c7ut2slrd",
            "templateId": template_id}


def record_from(outcomes, *, repeat, schedule, host_ids, endpoint_id, template_id, started_at,
                replicas, until) -> dict:
    workers = [o.headers.get(WORKER) for o in outcomes]
    server = [server_latency_s(o) for o in outcomes]
    void = []
    if len(outcomes) != len(schedule):
        void.append(f"{len(outcomes)} outcomes for {len(schedule)} scheduled requests")
    non_200 = sum(1 for o in outcomes if o.status != 200)
    if non_200:
        void.append(f"{non_200} requests without a 200")
    novel = sorted({w for w in workers if w} - set(host_ids))
    if novel:
        void.append(f"responses from workers outside the pinned set: {novel}")
    missing = sum(1 for o, s in zip(outcomes, server) if o.status == 200 and s is None)
    if missing:
        void.append(f"{missing} responses without the server-latency header")
    return {
        "schema_version": SCHEMA_VERSION, "repeat": repeat, "started_at": started_at,
        "endpoint_id": endpoint_id, "template_id": template_id, "replicas": replicas,
        "until": until, "drain": VALIDATION_DRAIN_SECONDS, "seed": VALIDATION_SEED,
        "latency_source": LATENCY_SOURCE, "host_ids": list(host_ids), "novel_workers": novel,
        "void": void, "max_jitter_s": max_jitter(outcomes),
        "schedule": list(schedule),
        "sent": [o.sent for o in outcomes],
        "server_latency_s": server,
        "client_latency_s": [o.latency for o in outcomes],
        "status": [o.status for o in outcomes],
        "worker": workers,
        "error": [o.error for o in outcomes],
    }


def read_record(path: Path) -> dict:
    with gzip.open(path, "rt") as fh:
        return json.load(fh)


def write_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        json.dump(record, fh)


def prepare_slot(out: Path, k: int) -> Path:
    path, void_path = out / f"repeat-{k}.json.gz", out / f"repeat-{k}.void.json.gz"
    if path.exists():
        if not read_record(path)["void"]:
            raise SystemExit(f"{path} holds a valid repeat {k}; a valid repeat is never re-run")
        if void_path.exists():
            raise SystemExit(
                f"repeat {k} is void twice ({void_path}, {path}); by the amendment the gate is "
                "not evaluable. Publish the causes; do not run it a third time")
        path.rename(void_path)
    return path


def run_repeat(*, k, schedule, pin, send, warm_fn, replay_fn, endpoint_id, template_id,
               replicas, until, now) -> dict:
    with pin:
        host_ids = warm_fn(send)
        started_at = now()
        outcomes = replay_fn(schedule, send)
    return record_from(outcomes, repeat=k, schedule=schedule, host_ids=host_ids,
                       endpoint_id=endpoint_id, template_id=template_id, started_at=started_at,
                       replicas=replicas, until=until)


def judge(out: Path, curve) -> dict:
    records = []
    for k in range(1, REPEATS + 1):
        path = out / f"repeat-{k}.json.gz"
        if not path.exists():
            raise SystemExit(f"repeat {k} is missing ({path}); the gate needs all {REPEATS}")
        rec = read_record(path)
        if rec["void"]:
            raise SystemExit(f"repeat {k} is void ({rec['void']}); run it once more or stop")
        records.append(rec)
    key = "server_latency_s" if LATENCY_SOURCE == "server" else "client_latency_s"
    runs = [RealRun(schedule=r["schedule"], sent=r["sent"], latencies=r[key],
                    replicas=r["replicas"], until=r["until"], host_ids=tuple(r["host_ids"]))
            for r in records]
    result = validate(runs, curve)
    novelty, seen = {}, set(records[0]["host_ids"])
    for r in records[1:]:
        new = sorted(set(r["host_ids"]) - seen)
        if new:
            novelty[str(r["repeat"])] = new
        seen |= set(r["host_ids"])
    per_repeat = []
    for r in records:
        server = [x for x in r["server_latency_s"] if x is not None]
        client = [x for x in r["client_latency_s"] if x is not None]
        per_repeat.append({"repeat": r["repeat"], "host_ids": r["host_ids"],
                           "server_p50_s": median(server), "client_p50_s": median(client),
                           "max_jitter_s": r["max_jitter_s"]})
    return {
        "outcome": result.outcome, "detail": result.detail, "compared": result.compared,
        "agreeing": result.agreeing, "misses": result.misses,
        "max_miss_seconds": None if math.isinf(result.max_miss_seconds) else result.max_miss_seconds,
        "max_miss_is_censoring": math.isinf(result.max_miss_seconds),
        "bins": [b.__dict__ for b in result.bins],
        "host_novelty": novelty, "latency_source": LATENCY_SOURCE, "per_repeat": per_repeat,
    }


def _preflight(endpoint: str, key: str, template_id: str) -> WorkerPin:
    assert_endpoint_matches(fetch_endpoint(endpoint, key), lb_pins(template_id))
    pin = WorkerPin(endpoint, key, workers=VALIDATION_REPLICAS)
    pin.preflight()
    return pin


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--repeat", type=int, choices=range(1, REPEATS + 1))
    mode.add_argument("--judge", action="store_true")
    ap.add_argument("--template-id")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--curve", default=str(DEFAULT_PATH))
    args = ap.parse_args(argv)
    out = Path(args.out)
    curve = load_measured_curve(args.curve).curve
    if args.judge:
        verdict = judge(out, curve)
        (out / "verdict.json").write_text(json.dumps(verdict, indent=1))
        print(f"[judge] {verdict['outcome']}: {verdict['detail']} (judged {verdict['compared']}, "
              f"outside {verdict['misses']}); host novelty {verdict['host_novelty'] or 'none'}")
        return
    if not args.template_id:
        ap.error("--preflight-only and --repeat need --template-id")
    key = os.environ["RUNPOD_API_KEY"]
    endpoint = os.environ["RUNPOD_A2_LB_ENDPOINT_ID"]
    pin = _preflight(endpoint, key, args.template_id)
    print(f"[preflight] {endpoint} matches the LB pin set and holds workersMax "
          f"{VALIDATION_REPLICAS}; nothing written")
    if args.preflight_only:
        return
    path = prepare_slot(out, args.repeat)
    schedule = build_schedule(curve, replicas=VALIDATION_REPLICAS, kind=VALIDATION_KIND,
                              until=VALIDATION_UNTIL, drain=VALIDATION_DRAIN_SECONDS,
                              seed=VALIDATION_SEED)
    send = sender(endpoint, key)
    unwind_on_hangup_and_term()
    record = run_repeat(
        k=args.repeat, schedule=schedule, pin=pin, send=send,
        warm_fn=lambda s: warm_up(s, workers=VALIDATION_REPLICAS, rps=WARMUP_RPS,
                                  min_clean=WARMUP_MIN_SECONDS, max_seconds=WARMUP_MAX_SECONDS),
        replay_fn=lambda sch, s: replay(sch, s), endpoint_id=endpoint,
        template_id=args.template_id, replicas=VALIDATION_REPLICAS, until=VALIDATION_UNTIL,
        now=lambda: datetime.now(UTC).isoformat(timespec="seconds"),
    )
    write_record(path, record)
    print(f"[repeat {args.repeat}] {len(schedule)} requests, host_ids {record['host_ids']}, "
          f"max jitter {record['max_jitter_s']:.3f} s, "
          + ("VOID: " + "; ".join(record["void"]) if record["void"] else "valid"))


if __name__ == "__main__":
    main()
```

Note: the pin's preflight runs twice, once in `_preflight` and again in `WorkerPin.__enter__`. That is deliberate: the slot and schedule checks sit between them, and the second read is the one immediately before the write.

- [ ] **Step 4: Run the tests, lint, full suite**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_validate.py -q -o addopts=""
.venv/bin/ruff check scripts/a2_validate.py tests/test_a2_validate.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
```

Expected: pass. If `test_judge_passes_a_model_inside_realitys_spread` fails because the synthetic band is too narrow at some bins, widen the factors to (0.95, 1.0, 1.05). Do not touch the gate's constants.

- [ ] **Step 5: Commit**

```bash
git add scripts/a2_validate.py tests/test_a2_validate.py
git commit -m "validation: the open-loop gate's driver -- one pinned repeat at a time with void rules, then the verdict

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
## Task 13: Figure 3 — the validation overlay

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. It is rendered from synthetic repeats here and looked at, at full size and at 375 px. The real figure is rendered after the three paid repeats exist (runbook, Task 14), and looked at again then.

Spec §11, figure 3: predicted versus actual trajectory with the three-run reality band.

One panel: p50 latency per 10 s bin against scheduled arrival time. It draws:
- the reality band, the min–max of the three repeats, as a shaded region;
- each repeat's p50 as a thin grey line;
- the prediction as a solid line;
- each judged miss as a red ×;
- bins not judged (censored, unstable or thin) hatched, so the reader sees which bins count.

The banner reads MEASURED, "N replicas pinned, 3 real runs of one schedule". The note states:
- requests per run;
- judged bins, misses and the outcome;
- the latency source.

**Files:**
- Modify: `autoscale/figures.py` (new `validation_overlay`, added to `__all__`)
- Modify: `scripts/a2_validate.py` (`--judge` also renders `data/a2/validation/validation_overlay.png`)
- Test: `tests/test_a2_figures.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_a2_figures.py`)

```python
from autoscale.figures import validation_overlay
from autoscale.validation import RealRun, predicted_trajectory, tolerance_band
from autoscale.validation import validate as _validate
from autoscale.validation_band import trajectory as _trajectory
from autoscale.validation_schedule import build_schedule as _build_schedule

_OV_CURVE = ServiceCurve(points=[(0, 0.2, 0.0, 0.0), (1, 0.2, 50.0, 1.0), (8, 0.3, 300.0, 1.0)],
                         measured=True)


def _overlay_inputs(factors=(0.97, 1.0, 1.03)):
    from autoscale.sim import run_fixed_capacity
    until = 200.0
    s = _build_schedule(_OV_CURVE, replicas=2, kind="step", until=until, drain=20.0, seed=1)
    by_arrival = dict(run_fixed_capacity(list(s), 2, _OV_CURVE, until).completed_requests())
    runs = [RealRun(schedule=s, sent=s, latencies=[by_arrival[t] * f for t in s], replicas=2,
                    until=until, host_ids=("w1", "w2")) for f in factors]
    predicted = predicted_trajectory(s, 2, _OV_CURVE, until)
    band_bins = tolerance_band(runs)
    repeats = [_trajectory(r.schedule, r.windowed_latencies(), until=until, bin_seconds=10.0)
               for r in runs]
    return predicted, band_bins, _validate(runs, _OV_CURVE), repeats, len(s)


def _draw_overlay(tmp_path, factors=(0.97, 1.0, 1.03)):
    predicted, band_bins, verdict, repeats, n = _overlay_inputs(factors)
    return validation_overlay(predicted, band_bins, verdict, repeats, tmp_path / "v.png",
                              replicas=2, requests_per_run=n, latency_source="server",
                              return_figure=True)


def test_overlay_draws_band_prediction_and_repeats(tmp_path):
    fig = _draw_overlay(tmp_path)
    gids = [a.get_gid() for a in fig.findobj() if hasattr(a, "get_gid")]
    assert gids.count("band") == 1 and gids.count("predicted") == 1 and gids.count("repeat") == 3


def test_overlay_marks_every_judged_miss(tmp_path):
    fig = _draw_overlay(tmp_path, factors=(1.4, 1.45, 1.5))
    _, _, verdict, _, _ = _overlay_inputs((1.4, 1.45, 1.5))
    misses = [a for a in fig.findobj() if getattr(a, "get_gid", lambda: None)() == "miss"]
    assert len(misses) == 1
    assert len(misses[0].get_xdata()) == verdict.misses


def test_overlay_states_n_outcome_source_and_banner(tmp_path):
    text = " ".join(_texts(_draw_overlay(tmp_path)))
    assert "MEASURED" in text and "2 replicas pinned, 3 real runs of one schedule" in text
    assert "requests per run" in text and "passed" in text and "server-side latency" in text


def test_overlay_axes_start_at_zero_and_text_is_legible_and_on_canvas(tmp_path):
    fig = _draw_overlay(tmp_path)
    axis = fig.axes[0]
    assert axis.get_ylim()[0] == 0 and axis.get_xlim()[0] == 0
    width_in = fig.get_size_inches()[0]
    for t in fig.findobj(match=matplotlib.text.Text):
        if t.get_text().strip():
            assert t.get_fontsize() * 375 / (72 * width_in) >= MIN_PHONE_TEXT_PX, t.get_text()
    w, h = fig.canvas.get_width_height()
    for text, box in _rendered(fig):
        assert box.x0 >= -1 and box.y0 >= -1 and box.x1 <= w + 1 and box.y1 <= h + 1, text


def test_the_band_changes_the_saved_pixels(tmp_path):
    from PIL import Image
    predicted, band_bins, verdict, repeats, n = _overlay_inputs()
    path = validation_overlay(predicted, band_bins, verdict, repeats, tmp_path / "p.png",
                              replicas=2, requests_per_run=n, latency_source="server")
    im = Image.open(path).convert("RGB")
    assert len(set(im.getdata())) > 10


def test_overlay_refuses_a_count_of_repeats_other_than_three(tmp_path):
    predicted, band_bins, verdict, repeats, n = _overlay_inputs()
    with pytest.raises(ValueError, match="3 repeats"):
        validation_overlay(predicted, band_bins, verdict, repeats[:2], tmp_path / "x.png",
                           replicas=2, requests_per_run=n, latency_source="server")
```

- [ ] **Step 2: Run them and see them fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -q -o addopts="" -k overlay`
Expected: `ImportError: cannot import name 'validation_overlay'`.

- [ ] **Step 3: Implement `validation_overlay` in `autoscale/figures.py`**

Add `"validation_overlay"` to `__all__`, then append:

```python
def validation_overlay(predicted, band_bins, verdict, repeats, path, *, replicas: int,
                       requests_per_run: int, latency_source: str, return_figure=False):
    """Figure 3. The simulator's predicted latency trajectory against three real runs.

    One panel, p50 per gate bin against SCHEDULED arrival time, the binning
    the gate judges (`autoscale.validation`), so the picture and the verdict
    are the same comparison. The band is the three repeats' min-max: the
    system's own spread, which spec §10 makes the tolerance. Each repeat is
    drawn too, thin, because a band hides whether one run is an outlier.
    Misses are marked where the prediction sits; bins the gate did not judge
    (censored, unstable or thin) are hatched, so "passed" cannot be read as
    "every bin agreed".

    Inputs are `validation_band` objects (Bin, BandBin, Validation), so this
    module still never imports the simulator (see the boundary test).
    """
    if len(repeats) != 3:
        raise ValueError(
            f"{len(repeats)} repeats; the gate and this figure take exactly 3 repeats, and "
            "a band drawn from another count is not the band that was judged")
    fig, axis = plt.subplots(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    left, right = 0.095, 0.985
    fig.subplots_adjust(left=left, right=right, top=0.86, bottom=0.245)
    centre = [(b.start + b.end) / 2 for b in predicted]
    x_right = max(b.end for b in predicted)

    ok = [(c, bb.lo, bb.hi) for c, bb in zip(centre, band_bins, strict=True)
          if bb.lo is not None and bb.hi is not None]
    if ok:
        axis.fill_between([c for c, _, _ in ok], [lo for _, lo, _ in ok],
                          [hi for _, _, hi in ok], color=MEASURED_BANNER, alpha=BAND_ALPHA,
                          linewidth=0, gid="band", label="3-run reality band (min–max)")
    for k, rep in enumerate(repeats):
        axis.plot(centre, [b.p50 if b.p50 is not None else float("nan") for b in rep],
                  color="#8a8a8a", linewidth=0.9, gid="repeat",
                  label="real runs (p50)" if k == 0 else None)
    axis.plot(centre, [b.p50 if b.p50 is not None else float("nan") for b in predicted],
              color=CURVE_COLOR, linewidth=2, gid="predicted", label="simulator (p50)")

    by_start = {v.start: v for v in verdict.bins}
    miss_x, miss_y = [], []
    for c, b in zip(centre, predicted, strict=True):
        v = by_start.get(b.start)
        if v is None:
            continue
        if v.verdict in ("outside", "censoring_disagreement"):
            miss_x.append(c)
            miss_y.append(b.p50 if b.p50 is not None else 0.0)
        elif v.verdict not in ("inside",):
            axis.axvspan(b.start, b.end, facecolor="none", edgecolor="#b0b0b0", hatch="///",
                         linewidth=0, gid="not_judged")
    axis.plot(miss_x, miss_y, "x", color=CENSOR_COLOR, markersize=8, markeredgewidth=2,
              gid="miss", label="miss (outside band)")

    _tidy(axis, "scheduled arrival time (s)", "p50 latency per 10 s bin (s)", MEASURED_BG)
    axis.set_xlim(0, x_right)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.125), ncol=4,
                fontsize=_pt(PX_LEGEND), frameon=False)
    _figure_banner(fig, left, right, "MEASURED",
                   f"{replicas} replicas pinned, 3 real runs of one schedule", MEASURED_BANNER)
    source = "server-side latency" if latency_source == "server" else "client latency"
    _note(axis, f"n={requests_per_run} requests per run · judged {verdict.compared} bins, "
                f"{verdict.misses} outside · {verdict.outcome}\n{source}; hatched: not judged",
          y=-0.245)
    return _finish(fig, path, return_figure)
```

In `scripts/a2_validate.py`'s `--judge` branch, after writing `verdict.json`, render the figure. `judge` must also return what the figure needs: add `predicted_trajectory`, `tolerance_band` and `trajectory` (from `autoscale.validation_band`) to its imports, and build the figure inputs inside `judge` from the same `runs`. Keep the JSON serialisable by returning the figure inputs separately:

```python
def figure_inputs(out: Path, curve):
    """The figure-3 inputs for the three valid repeats, from the same records the gate judged."""
    records = [read_record(out / f"repeat-{k}.json.gz") for k in range(1, REPEATS + 1)]
    key = "server_latency_s" if LATENCY_SOURCE == "server" else "client_latency_s"
    runs = [RealRun(schedule=r["schedule"], sent=r["sent"], latencies=r[key],
                    replicas=r["replicas"], until=r["until"], host_ids=tuple(r["host_ids"]))
            for r in records]
    first = runs[0]
    predicted = predicted_trajectory(first.schedule, first.replicas, curve, first.until)
    repeats = [trajectory(r.schedule, r.windowed_latencies(), until=r.until, bin_seconds=10.0)
               for r in runs]
    return predicted, tolerance_band(runs), validate(runs, curve), repeats, len(first.schedule)
```

Then, in `main`'s judge branch:

```python
        predicted, band_bins, result, repeats, n = figure_inputs(out, curve)
        print(validation_overlay(predicted, band_bins, result, repeats,
                                 out / "validation_overlay.png", replicas=VALIDATION_REPLICAS,
                                 requests_per_run=n, latency_source=LATENCY_SOURCE))
```

(`from autoscale.figures import validation_overlay`; `from autoscale.validation import predicted_trajectory, tolerance_band`; `from autoscale.validation_band import trajectory`.) Add a test to `tests/test_a2_validate.py` that runs `figure_inputs` on the `_three(tmp_path, (0.97, 1.0, 1.03))` records and checks it returns three repeat trajectories and the same outcome as `judge`.

- [ ] **Step 4: Run the tests and the import boundary**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py tests/test_a2_validate.py -q -o addopts=""
```

Expected: pass, including `test_importing_the_figures_does_not_load_the_simulator_or_artifact_one`. `validation_overlay` takes `validation_band` objects and imports nothing new at module level.

- [ ] **Step 5: Render the synthetic overlay and LOOK at it at both widths**

```bash
mkdir -p build/a2-figure3-synthetic
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "tests")
from PIL import Image
from test_a2_figures import _overlay_inputs
from autoscale.figures import validation_overlay
for name, f in (("pass", (0.97, 1.0, 1.03)), ("fail", (1.4, 1.45, 1.5))):
    p, b, v, r, n = _overlay_inputs(f)
    out = validation_overlay(p, b, v, r, Path(f"build/a2-figure3-synthetic/{name}.png"),
                             replicas=2, requests_per_run=n, latency_source="server")
    im = Image.open(out); im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
        f"build/a2-figure3-synthetic/{name}-phone.png")
    print(out, v.outcome, v.compared, v.misses)
PY
```

Open all four PNGs with the Read tool and check each of these by eye:
- **Band:** visible, and the prediction inside it on "pass".
- **Misses:** red × marks on "fail", at the predicted line.
- **Grey repeat lines:** distinguishable from the prediction.
- **Hatched bins:** only where the verdict says not judged.
- **Banner and note:** fully on the canvas.
- **Legend:** does not overlap the note.
- **Phone width:** legible at 375 px.

Describe what you saw in the report.

- [ ] **Step 6: Lint, full suite, commit**

```bash
.venv/bin/ruff check autoscale/figures.py scripts/a2_validate.py tests/test_a2_figures.py tests/test_a2_validate.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
git add autoscale/figures.py scripts/a2_validate.py tests/test_a2_figures.py tests/test_a2_validate.py
git commit -m "figures: figure 3, the validation overlay -- prediction against the three-run reality band, misses marked

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 14: The owner's runbook, full verification, report

**Files:**
- Create: `docs/runbook-a2-validation.md`

- [ ] **Step 1: Write the runbook**

Write `docs/runbook-a2-validation.md` in the register of `docs/runbook-service-sweep.md`. It is for the owner and is not a plan step; nothing in it runs without the owner's say-so. Sections:

**A. Image.**
- Push this plan's commits (the owner's call). `worker/**` changed, so CI (`build-worker.yml`) rebuilds the image; read the new `ghcr.io/...@sha256:` digest from its summary.
- Pin templates by digest, never by tag.
- Confirm the image holds `/opt/lb_serve.py` and `/opt/a2_middleware.py`. `tests/test_harness_boundary.py` already enforces the COPY lines.

**B. Template (new).**
- Image: the digest from A.
- `dockerStartCmd`: `python3 -u /opt/lb_serve.py`.
- Environment: `MODEL_ID`, `MODEL_REVISION`, `MAX_MODEL_LEN` copied from the sweep template `utujdvq2pp`, plus `PORT=8000`, `PORT_HEALTH=8000`, `HEALTH_CHECK_PATH=/health`.
- Container disk as the sweep template.

**C. Endpoint (new; type: load balancing; owner via the console).**
- GPU `NVIDIA GeForce RTX 4090`, network volume `9c7ut2slrd` (P7: if the console refuses a volume for an LB endpoint, record it and stop; every cold start would then download 16 GB).
- `workersMin` 0, **`workersMax` 2** (owner decision 3), idle timeout 5 s.
- Record its id in `.env` as `RUNPOD_A2_LB_ENDPOINT_ID`.
- The queue endpoints `a8261k5opy1ldl` and `7h0aglrmsjovyc` stay as they are.

**D. Free preflights.**

```bash
set -a; . ./.env; set +a
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_lb_probe.py --preflight-only
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --preflight-only --template-id <id>
```

Expected: both print a preflight line and write nothing. `assert_endpoint_matches` fails closed on any absent key. If an LB endpoint reports a field differently (for example `networkVolumeId`), print the keys as in `docs/runbook-service-sweep.md` section D, and decide before changing a pin.

**E. Cost.**
- One probe is 2 workers × (startup ≈ 1.5 min + warm-up ≥ 0.5 min + 6 steps × 30 s + release) ≈ 2 × 6 min. At $1.10/h per worker that is about $0.25, or about $0.50 with a cold image pull.
- One repeat is 2 workers × (startup + warm-up + 400 s + release) ≈ 2 × 10 min ≈ $0.37. Three repeats cost about $1.10.
- A void repeat costs another $0.37.
- Check the balance before and after each, and record the spend for spec §13.

**F. The probe (paid, ~$0.50).**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_lb_probe.py --out build/a2-lb-probe 2>&1 | tee build/a2-lb-probe.log
```

Read P1–P8 off the log and `build/a2-lb-probe/summary.json`:

| # | Look at | If it is not as assumed |
|---|---|---|
| P1 | The warm-up finished, and `[warm] workers [...]` names 2 | The LB never routed to a loading worker. Try `HEALTH_CHECK_PATH` on a tiny shim answering 204 while vLLM loads; that is a code change with a test. |
| P2 | Two distinct workers during warm-up, with no request reaching a third | The pin did not hold on an LB endpoint; stop. |
| P3 | `worker_share` per step | The simulator assumes even balancing. A skewed share at the top step fails acceptance. |
| P4 | `non_200` and `errors` at every step | Find the first step with failures. That rate is the LB's ceiling, and the validation load must sit below it (an amendment). |
| P5 | `server_p50_s` present at every step | The middleware did not load, or the LB strips headers. Read the engine log; the fix is in Task 8. |
| P6 | `client_minus_server_p50_s` | WAN plus LB time. Recorded for the post, not judged. |
| P7 | The endpoint was created with the volume | See C. |
| P8 | `max_jitter_s` at 450 req/s | Above 0.25 s, the laptop driver cannot hold the schedule. Run the driver from a CPU pod in EU-RO-1, or lower the load (an amendment). |

The last line is `[accept] PASS` or `[accept] FAIL: ...`. On FAIL, stop and decide with the owner; the amendment says so.

**G. Three repeats (paid, about $1.10).** Only after `[accept] PASS`:

```bash
for k in 1 2 3; do
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --repeat $k --template-id <id> 2>&1 | tee -a build/a2-validation.log
done
```

- Each line ends with `valid` or `VOID: <reasons>`.
- A void repeat is run once more with the same `--repeat K`. A second void ends the gate as not evaluable.
- Never run a valid K again; the script refuses anyway.

**H. Verdict (free).**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_validate.py --judge
```

- It writes `data/a2/validation/verdict.json` and `validation_overlay.png`.
- Look at the figure at full size and at phone width before calling it done.
- Every miss is published with its magnitude (spec §10), and host novelty is disclosed.
- Commit `data/a2/validation/` (the owner's call).

**If the run ends with `RELEASE FAILED`, the endpoint may still be pinned and billing.**
- Set `workersMin` to 0 in the console, or run `python -c "from harness.runpod.pinning import WorkerPin; import os; WorkerPin(os.environ['RUNPOD_A2_LB_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY'], workers=2).release()"`.
- Then confirm the spend rate with the GraphQL `myself { currentSpendPerHr }` query.

- [ ] **Step 2: Full verification**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -o addopts="" 2>&1 | tail -1
.venv/bin/ruff check .
./scripts/parity_check.sh 2>&1 | tail -1
```

Expected:
- the suite exits 0, with a count higher than before Task 2;
- `All checks passed!`;
- `PARITY OK` (artifact 1's published outputs, untouched by this plan).

Re-run Task 6 Step 6's placeholder parity: `PLACEHOLDER FIGURE 4 PARITY OK`.

- [ ] **Step 3: Parity audit against Task 1's inventory**

For every row of `docs/superpowers/plans/2026-10-04-artifact-2-plan-2b-inventory.md`, exercise the capability through the new code and record the command and its output line in the inventory file under "Parity audit":
- `--placeholder` renders all three figures and prints the WARNING;
- a cache from the other curve is refused;
- discards are reported per signal;
- the H3 verdict is printed under both shapes;
- `RAMP_SECONDS` is still importable;
- the two diagnostic scripts run with `--placeholder` (use `--reps 1 --seeds 1` / `--stage screen` to keep them short).

A row that cannot be shown working is a defect to fix, not to note.

- [ ] **Step 4: Commit the runbook and the audit**

```bash
git add docs/runbook-a2-validation.md docs/superpowers/plans/2026-10-04-artifact-2-plan-2b-inventory.md
git commit -m "docs: the owner's runbook for the LB probe and the three validation repeats; plan 2b parity audit

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Report**

State plainly, with the command output that shows each:
- the measured curve drives the simulator, the sweep and figure 4, with the idle point and the evidence test;
- the sensitivity arm exists and the headline sweep's output is unchanged (Task 3's hashes);
- the amendment was signed off and committed before the measured-curve sweep (the commit order);
- the measured-curve sweep's printed gaps and H3 line, labelled unvalidated;
- figures 3 (synthetic) and 4 (measured) rendered and inspected at both widths, with what was seen;
- the LB worker, pinning, open-loop sender, probe and validation driver built and proven offline, and **not run**;
- open, for plan 2c: the closed-loop gate (GPU-utilisation policy driving `workersMin`/`workersMax` changes through `WorkerPin`-style writes, which requires the owner to allow `workersMax` writes or set a ceiling, and per-replica `host_id`);
- open, for the publication plan: published figure copies with a drift guard, the post, and this artifact's spend record.

---

## Open items found while writing this plan (not fixed here)

- `docs/recon-a2.md` says pinning is "`workersMin = workersMax = N` through the REST update". Owner decision 3 refines that: the owner sets `workersMax`, and code writes only `workersMin`. The recon record stands as the measurement; the amendment states the procedure.
- `scripts/a2_service_curve.py::load_service_curve` remains, used by its tests, and does not add the idle point. `autoscale.measured_curve` is the loader for everything that simulates; the script's loader is the adapter's round-trip check. Not merged, so the adapter does not depend on `autoscale`'s idle-point decision.
- The probe and validation driver run from the owner's laptop over the WAN. If P8 fails, the remedy is a CPU pod near the workers, which is not built here.
- Figure 2's curve label is note text, not a banner strip (Task 7), because figure 2 has no headroom for a strip without moving every pixel.

## Self-review

- **Spec coverage.**
  - §10 primary gate: Tasks 4, 8–12 (pinned capacity, exact schedule, three repeats, verdict). `host_id` per replica: Task 11's warm-up ids, Task 12's per-request worker and novelty.
  - Disclosure of misses with magnitude: Task 12's verdict JSON and Task 13's figure.
  - §11 figure 3: Task 13. Figure 4 intervals and a measured curve: Task 7. N stated, axes from zero, phone legibility: those tasks' tests and visual steps.
  - §16 "absolute baseline rate and k computed and committed before any policy sweep": Tasks 4–5, with the commit-order precondition in Task 6.
  - §13 spend: the runbook records it; the publication plan publishes it.
  - Not covered by design: the closed-loop gate (plan 2c) and publication (a later plan).
- **Placeholder scan.** Every code step carries code. Three steps say "read X first and adjust to the real signature":
  - Task 6's sensitivity block, against `frontier.iso_cost_budget` / `gap_at_iso_cost`;
  - Task 7's existing fixtures;
  - Task 6's `test_a2_end_to_end.py` calls.

  Each names the file and line to read, because those signatures were not quoted in this plan's digest.
- **Type consistency.**
  - `MeasuredCurve`, `load_measured_curve`, `select_curve`, `DEFAULT_PATH`, `IDLE_CONCURRENCY` and `runs_per_level`: Task 2, used in Tasks 4, 6, 7 and 12.
  - `build_schedule(curve, *, replicas, kind, until, drain, seed)`: Task 4, used in Tasks 11, 12 and 13.
  - `WorkerPin(endpoint_id, api_key, *, workers, ...)` with `.preflight/.pin/.release` and the context manager: Task 9, used in Tasks 11 and 12.
  - `replay(schedule, send, *, max_in_flight, start_delay, ...)`, `Outcome`, `http_sender` and `max_jitter`: Task 10, used in Tasks 11 and 12.
  - `WORKER` / `SERVER_LATENCY` header names: Task 11's `a2_lb_common`, matching Task 8's lower-cased header bytes.
  - `validation_overlay(predicted, band_bins, verdict, repeats, path, *, replicas, requests_per_run, latency_source, return_figure)`: Task 13.
- **UI audit.** Tasks 7 and 13 assert beyond presence (gid counts, pixel diffs, phone floor, on-canvas) and each has a look-at-both-widths step. No encapsulation boundary. No visible UI removed: figure 4's placeholder path is byte-identical.
- **Parity audit.**
  - Task 1 inventories by reading the code and captures the baseline (the placeholder figure 4's hash, saturation, help output, the placeholder sweep cache).
  - Task 14 Step 3 exercises every preserved row.
  - Nothing is deleted: the placeholder stays, behind `--placeholder`.
