# Artifact 2 Plan 2a — the Recon-Independent Half of Plan 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, with no GPU and no spend, everything in spec §15's "plan 2" that does not depend on what reconnaissance finds: the Q1/Q2 capture tooling that *produces* those answers, the open-loop validation gate's arithmetic, figure 4, and a single home for the traffic model.

**Architecture:** Three independent tracks in one plan. (1) **Recon** — `recon/capture_a2.py` drives a max>1 endpoint through a fixed protocol and saves every response verbatim; `recon/analyse_a2.py` tabulates the evidence and is proven against artifact 1's committed fixtures. (2) **Validation core** — `SimResult` starts keeping each request's arrival time, `autoscale/validation_band.py` turns latency trajectories into a tolerance band and a three-state verdict with no import path to `coldstart` (artifact 4 imports it), and `autoscale/validation.py` is artifact 2's gate on top: its constants, its run record, and the replay into `run_fixed_capacity`. (3) **Traffic consolidation** — four copies of the traffic-model derivation collapse into `autoscale/traffic.py`, gated on byte-identical shapes and diagnostic outputs, with the old code deleted last. Figure 4 is a new matplotlib chart in `autoscale/figures.py`: no encapsulation boundary is involved and no visible figure is removed — the existing two figures are re-rendered and compared byte-for-byte to prove they did not move.

**Tech Stack:** Python 3.13, pytest, matplotlib, `requests` (recon only), ruff. No new dependencies.

---

## Why this plan exists, and what it deliberately leaves out

The artifact-2 simulator plan (`2026-09-04-artifact-2-simulator.md`) scoped itself as plan 1 of 2 and deferred reconnaissance, the service-curve sweep, the validation gates and publication to a plan 2 that "cannot be written honestly until reconnaissance answers what the platform supports". That is true of *some* of plan 2. This plan is the part it is not true of.

**Non-goals — plan 2b, after reconnaissance has run:**

- **Running the capture.** Task 3 builds it; running it rents GPUs. That spend is the operator's decision against the spec §13 budget, not a plan step.
- **The open-loop load driver and capacity pinning — plan 2b.** How capacity is pinned is Q1; how the platform routes concurrent work across pinned replicas is Q2. Writing either now would encode a guess.
- **The in-container load-generation core, the `vllm serve` lifecycle and the single-engine service-curve sweep — a separate harness plan, not plan 2b.** Decided 2026-09-26 as decision 4 of `docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md` (§1d, §2): artifacts 4 and 5 need these without platform scaling, so they are built once, without waiting for artifact 2's reconnaissance. Plan 2b keeps only what is platform-specific. Artifact 2's service curve is measured with that shared sweep.
- **The closed-loop gate.** Conditional on Q2 by spec §9's own go/no-go table.
- **Figure 3 (validation overlay).** Its time axis and bin density come from the load driver's real schedule. Task 8 builds the arithmetic it will plot; the chart waits for a real run's shape.
- **Intervals on figure 4.** Spec §11 requires intervals on every figure. `ServiceCurve` carries one value per concurrency level because the placeholder has no repeats; per-level dispersion is a sweep-format decision that plan 2b makes. Figure 4 here states N and labels itself NOT MEASURED, and plan 2b adds the band.

## Rules this plan operates under

- **Two workstreams share this checkout.** Never `git add -A` or `git add .`; every commit step names its files. Never run `ruff --fix` over the whole repo; run it on the files the task touched. Both have swept another session's in-progress work into a commit here before.
- **`PYTHONDONTWRITEBYTECODE=1`** on every pytest and script invocation. `.pyc` invalidation keys on mtime-seconds plus size, and a stale cache can make moved code look like it still works.
- **Test counts are not quoted as absolutes.** The suite grows under other workstreams. "Passes" means `pytest` exits 0; a count that *drops* between two runs means a test file stopped being collected, and is a stop-and-investigate.
- Every error message names what went wrong **and** the consequence of it passing silently. Every docstring says *why*, including the alternative rejected. That is this repository's house style, and reviewers hold new code to it.

## Cross-plan coupling

- **Harness extraction** (`2026-09-03-harness-extraction.md`, Tasks 1–3 done). `recon/analyse_a2.py` (Task 4) imports `coldstart.vllm_logs` and `coldstart.runpod_api`, which that plan moves to `harness/`. Its import-rewrite list names `coldstart/`, `worker/`, `scripts/` and `tests/` — **not `recon/`**. Task 4 Step 6 adds a line to the harness plan so the rewrite covers this file.
- `tests/test_a2_figures.py` already imports `MIN_PHONE_TEXT_PX` from `coldstart.analysis.figures`; Task 10 keeps that import, which the harness plan already tracks.
- **Artifact 4 imports `autoscale/validation_band.py`** (Task 8) across a transitive import boundary against `coldstart` — requested by artifact 4's session and recorded as decision 12 of `docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md`. That module must never import `autoscale.sim`, `autoscale.coldstart_ecdf`, or anything that reaches them; a subprocess test checks `sys.modules` after importing it, because `tests/test_autoscale_boundary.py` sees direct imports only.

---

## File Structure

| File | Responsibility |
|---|---|
| `docs/superpowers/plans/2026-09-26-artifact-2-plan-2a-inventory.md` | **Create (Task 1).** Every capability of the four traffic-derivation copies, with a keep/drop decision each. |
| `docs/recon-a2.md` | **Modify (Task 2).** Correct the Q2 reasoning and the KV-mechanism claim against evidence already committed. |
| `recon/capture_a2.py` | **Create (Task 3).** The Q1/Q2 capture protocol. stdlib + `requests` only. |
| `recon/analyse_a2.py` | **Create (Task 4).** Tabulates captured jobs: worker, delay, execution, compile time, weights download, KV capacity. |
| `autoscale/traffic.py` | **Create (Task 5).** The traffic model's one home: constants, `saturation_rps`, `spike_shape`. |
| `scripts/a2_render_figures.py`, `scripts/a2_gap_noise_floor.py`, `scripts/a2_regime_probe.py` | **Modify (Task 6).** Call `autoscale.traffic` instead of deriving. Render keeps two delegating shims until Task 11. |
| `autoscale/sim.py` | **Modify (Task 7).** `SimResult` keeps each request's arrival time, in both loops. |
| `autoscale/validation_band.py` | **Create (Task 8).** Trajectory, tolerance band, three-state verdict over plain sequences. No pre-registered values; no import path to `coldstart`. Shared with artifact 4. |
| `autoscale/validation.py` | **Create (Task 8).** Artifact 2's gate: pre-registered constants, `RealRun`, the one-schedule checks, the replay into `run_fixed_capacity`. |
| `docs/experiment-a2.md` | **Modify (Task 9).** Pre-register the validation gate's pass rule. **Sign-off required.** |
| `autoscale/figures.py` | **Modify (Task 10).** `service_curve()` — figure 4 — and `censoring_onset()`. |
| `tests/test_a2_end_to_end.py`, `scripts/a2_render_figures.py` | **Modify (Task 11).** Delete the last copies of the derivation, gated on parity. |
| `tests/test_recon_capture_a2.py`, `tests/test_recon_analyse_a2.py`, `tests/test_traffic.py`, `tests/test_validation_band.py`, `tests/test_validation.py`, `tests/test_a2_figures.py`, `tests/test_sim.py` | Tests, per task. |

---

## Task 1: Inventory the traffic derivation and capture a "before" baseline

The consolidation in Tasks 5, 6 and 11 replaces existing code, so this repository's rules require an inventory built **by reading the code** and a baseline to compare against — before anything is designed. This task is read-only apart from two new files, and it runs first so the slow part of the baseline can grind in the background while Tasks 2–4 (recon, which touch none of this code) proceed.

**Files:**
- Create: `docs/superpowers/plans/2026-09-26-artifact-2-plan-2a-inventory.md`
- Create (gitignored, local only): `build/plan2a-baseline/`

- [ ] **Step 1: Confirm every site the inventory names still exists**

Run:

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
grep -rn -E "_saturation_rps|_preregistered_shape|BASELINE_FRACTION_OF_SATURATION|ADDITIONAL_REPLICAS_AT_PEAK|RAMP_SECONDS|SpikeShape\(|sustain=190|sustain = 190" scripts tests autoscale | grep -v "^tests/test_arrivals.py"
```

Expected: hits in `scripts/a2_render_figures.py`, `scripts/a2_gap_noise_floor.py`, `scripts/a2_regime_probe.py` and `tests/test_a2_end_to_end.py`, plus `autoscale/arrivals.py` (the class and a docstring). If a site appears that the table in Step 2 does not list, **add a row for it before continuing** — an unlisted capability is the failure this task exists to prevent.

- [ ] **Step 2: Write the inventory**

Create `docs/superpowers/plans/2026-09-26-artifact-2-plan-2a-inventory.md`:

````markdown
# Plan 2a — Traffic-Derivation Inventory and Decision Log

Built by reading the code at the commit plan 2a started from. Every capability
carries a decision. A capability in neither column is a planning bug.

The derivation — baseline a fraction of one replica's saturation, `k` sized to
require a number of additional replicas at the measured service rate — lived in
FOUR places, not the three the 2026-09-17 review counted. The fourth,
`tests/test_a2_end_to_end.py`, was a deliberate independent copy: its docstring
says "the derivation is duplicated rather than imported because `scripts/` is
not an importable package". `autoscale/traffic.py` is importable, so that reason
ends with this plan.

## Consolidated into `autoscale/traffic.py` — behavior unchanged

| # | Capability | Where it lived | Becomes |
|---|---|---|---|
| 1 | Saturation = **max** over measured points of `c / latency_at(c)`, `c > 0` — max, not the last point, because continuous batching makes throughput non-monotonic past the knee | `a2_render_figures._saturation_rps`; `a2_end_to_end._shape` (inline copy) | `saturation_rps(curve)` |
| 2 | Baseline = `BASELINE_FRACTION_OF_SATURATION × saturation`; peak = baseline + `ADDITIONAL_REPLICAS_AT_PEAK × saturation`; `k = peak / baseline` — this exact operation order, so floats stay byte-identical | `a2_render_figures._preregistered_shape`; `a2_gap_noise_floor` (override path); `a2_regime_probe._probe` and `._verify` (inline); `a2_end_to_end._shape` | `spike_shape(curve, kind, ...)` |
| 3 | Sustain `D` = 190 s, as the literal `190.0` in four places | render, noise floor, probe `main`, end-to-end (`SUSTAIN = 95.0`, a deliberately halved window) | `SUSTAIN_SECONDS`, and a `sustain=` keyword for the halved test window |
| 4 | Ramp `R` = `D / 2` = 95 s | `a2_render_figures.RAMP_SECONDS`; end-to-end `RAMP = 47.5` | Derived inside `spike_shape` from `sustain`, so no caller can break R = D/2 |
| 5 | `BASELINE_FRACTION_OF_SATURATION = 0.70`, `ADDITIONAL_REPLICAS_AT_PEAK = 0.25`, with provenance comments | render (module constants); end-to-end (duplicate constants) | `autoscale/traffic.py` constants |
| 6 | Candidate override: a caller may pass a different baseline fraction / additional replicas, to measure a candidate regime **before** the pre-registration is amended to adopt it | noise floor (`--baseline-fraction`, `--additional-replicas`, each falling back to the pre-registered value); probe (both stages) | `baseline_fraction=` / `additional_replicas=` keywords |
| 7 | "NOT the pre-registered traffic model" printed whenever the override is used | noise floor | **Preserved in the noise floor**, unchanged |
| 8 | The constants agree with the text of `docs/experiment-a2.md` (`baseline = **70%**`, `**0.25 additional replicas**`) — an amendment must touch the document | `test_the_traffic_constants_match_the_render_script_and_the_preregistration` | `tests/test_traffic.py`, extended to `D` and `R` |
| 9 | Ramp is half the sustain | `test_the_ramp_is_half_the_sustain_as_the_pre_registration_states` (via `render._preregistered_shape`) | Same test, via `spike_shape` |
| 10 | The render script evaluates H3 under both shapes: its source contains `kind="ramp"` and `h3_verdict(` | `test_the_render_script_evaluates_h3_under_both_shapes` | **Preserved.** Task 6 calls `spike_shape(..., kind="ramp")` by keyword so this source check keeps meaning what it says |
| 11 | `render.RAMP_SECONDS == 95.0` is asserted by a test | same test | Preserved: render imports `RAMP_SECONDS` from `autoscale.traffic` |

## Preserved in place — related, deliberately NOT consolidated

| Capability | Where | Why it stays |
|---|---|---|
| `PREREG_BASELINE_FRACTION = 0.40`, `PREREG_ADDITIONAL_REPLICAS = 3`, `PREREG_MAX_REPLICAS = 12` | `a2_regime_probe.py` | The ORIGINAL registration, kept as the origin of the disclosed search. Folding them into the current-rule constants would erase the record of what was amended. |
| `UNTIL = 400.0`, `SEED = 17`, `SWEPT_LAGS` | `a2_render_figures.py` | The render's simulation window and sensitivity sweep, not the traffic model. |
| `UNTIL = 200.0`, `REPETITIONS_UNDER_TEST` | `a2_end_to_end.py` | The test's reduced window, justified in its own comment. |
| Iso-cost budget `min(p.cost for p in points) * 2` | `a2_gap_noise_floor.py` | The **retired** budget rule. Kept because the script's docstring pins a documented historical result (0.314 s, 2026-09-17) computed with it; changing it would make that record irreproducible. Out of scope; flagged. |
| Inline iso-cost budget + gap in `_verify` | `a2_regime_probe.py` | A second copy of `iso_cost_budget`/`gap_at_iso_cost` without the FP-dust tolerance or the completeness guard. Out of scope for plan 2a — it is the budget, not the traffic model — and flagged for a follow-up. Its outputs are pinned by the Task 1 baseline, so a later fix will show its effect. |
| `peak = baseline + additional_replicas * saturation` as a **reported** value | `a2_regime_probe.py` | The probe reports `peak_rps` and `peak_over_saturation`. Recomputing them from the shape (`baseline × k`) can differ in the last bit and break byte parity for a label. The line stays as a report of the inputs, commented as such; it constructs no shape. |

## Intentionally dropped

| Capability | Why |
|---|---|
| `a2_render_figures._saturation_rps` and `._preregistered_shape` (private) | Replaced by `autoscale.traffic`. Delegating shims survive Tasks 6–10 so the end-to-end test keeps exercising the old entry points as a parity check; Task 11 deletes them once parity is proven. Private helpers of a script — no external caller. |
| The end-to-end test's local copy of the derivation and constants | The reason for the copy ("`scripts/` is not importable") no longer applies. The agreement it guarded becomes structural: there is one copy. |
| The `_preregistered_shape(curve, kind, ramp)` `ramp` argument | R = D/2 is derived, not passed. The Task 6 shim raises if a caller passes a ramp that disagrees, rather than silently ignoring it. |

No caller-observable capability is dropped: every script keeps its CLI, flags,
outputs and printed warnings.
````

- [ ] **Step 3: Capture the shape baseline (fast)**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
mkdir -p build/plan2a-baseline
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY' > build/plan2a-baseline/shapes.json
"""Every shape the OLD code paths produce, for fixed inputs. `json` writes
floats with repr(), which round-trips exactly, so a byte comparison of this
file is a bit-exact comparison of every field."""
import json, sys
sys.path[:0] = [".", "scripts"]
import a2_render_figures as r
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as C

def fields(s):
    return [s.kind, s.baseline_rate, s.k, s.ramp, s.sustain]

out = {"saturation_rps": r._saturation_rps(C)}
out["render_step"] = fields(r._preregistered_shape(C, kind="step", ramp=0.0))
out["render_ramp"] = fields(r._preregistered_shape(C, kind="ramp", ramp=r.RAMP_SECONDS))
# The probe's and noise floor's inline arithmetic, reproduced line for line
# from a2_regime_probe._probe / a2_gap_noise_floor, for the candidates the
# probe actually searches plus the adopted and original regimes.
sat = r._saturation_rps(C)
for f in (0.10, 0.20, 0.40, 0.70):
    for a in (0.25, 0.5, 1, 2, 3):
        baseline = f * sat
        peak = baseline + a * sat
        out[f"candidate_{f}_{a}"] = ["step", baseline, peak / baseline, 0.0, 190.0]
print(json.dumps(out, indent=1, sort_keys=True))
PY
head -c 400 build/plan2a-baseline/shapes.json
```

Expected: a JSON object whose `render_step` is `["step", 23.57..., 1.357..., 0.0, 190.0]`.

- [ ] **Step 4: Capture the diagnostic baselines (minutes)**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py \
  --seeds 2 --reps 3 --out build/plan2a-baseline/noise_floor.json > /dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py \
  --seeds 2 --reps 3 --baseline-fraction 0.40 --additional-replicas 0.5 \
  --out build/plan2a-baseline/noise_floor_candidate.json > /dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_regime_probe.py \
  --stage screen --out build/plan2a-baseline/probe_screen.json > /dev/null
ls -la build/plan2a-baseline/
```

Expected: four files. The probe screen takes roughly three minutes.

- [ ] **Step 5: Start the full-sweep baseline in the background**

This is the end-to-end parity reference for Task 12: a fresh `--refresh` sweep at the starting commit. It takes on the order of 30 minutes. Start it and move on to Task 2 — Tasks 2–4 touch none of the code it exercises.

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 nohup .venv/bin/python scripts/a2_render_figures.py \
  --out build/plan2a-baseline/figures --refresh > build/plan2a-baseline/render.log 2>&1 &
echo "baseline render started"
```

Before Task 5 begins, confirm it finished: `tail -3 build/plan2a-baseline/render.log` shows the figure paths, and `build/plan2a-baseline/figures/sweep-cache.json` exists.

- [ ] **Step 6: Commit the inventory**

```bash
git add docs/superpowers/plans/2026-09-26-artifact-2-plan-2a-inventory.md
git commit -m "docs: inventory the traffic derivation before consolidating it"
```

---

## Task 2: Correct the recon record against evidence already committed

`docs/recon-a2.md` gives two reasons artifact 1's captures all landed on one worker — serial submission and the `max 1` cap — and calls the arm-C KV mechanism "plausible". The repository already holds evidence that corrects both, and Task 3's protocol is designed around the correction, so it lands first.

**Files:**
- Modify: `docs/recon-a2.md:62-68` and `:127-130`

- [ ] **Step 1: Replace the Q2 causal paragraph**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from pathlib import Path
p = Path("docs/recon-a2.md"); t = p.read_text()

old = """The spec's §1 table attributes artifact 1's single-host result to serial
submission — *"artifact 1 submitted serially, so the platform never needed a
second worker"* — which is true and is not the whole reason. **The endpoint caps
at one worker.** Concurrency alone would not have produced a second; it would
have produced a queue. Two independent causes, and only one of them is fixed by
submitting concurrently."""
new = """The spec's §1 table attributes artifact 1's single-host result to serial
submission — *"artifact 1 submitted serially, so the platform never needed a
second worker"* — which is true and is not the whole reason. There are three
causes, and the committed record documents all of them:

1. **Serial submission.** One job in flight at a time.
2. **The endpoint caps at one worker.** Concurrency alone would not have
   produced a second; it would have produced a queue.
3. **Host affinity.** `docs/experiment.md` (H4) records that with `idleTimeout`
   at its 5 s minimum *"workers do terminate between runs, and RunPod still
   re-allocates the same physical machine because it has the image cached. Across
   27 runs of a discarded first window we observed 2 distinct hosts, one of them
   serving 23 runs."* For the three recon captures specifically,
   `fixtures/README.md` adds a fourth, narrower effect: they were submitted back
   to back inside the idle window, so the *container* survived between jobs —
   which is why runs 1 and 2 show a 0.3 s `torch.compile` against run 0's 39 s.

The third is the one that matters for Q2. Raising the cap and submitting
concurrently fixes causes 1 and 2, but host affinity means a driven scale-up may
still land on a host that already holds the image — which is precisely the
"warm-host restart" outcome §9 asks about. The capture protocol therefore has to
separate three things a single `workerId` conflates: a surviving **container**
(warm compile cache), a re-allocated **host** after termination (image cached,
container cold), and a genuinely **new host** (image pull visible in
`delayTime`)."""
assert old in t, "Q2 paragraph not found verbatim; re-read docs/recon-a2.md"
t = t.replace(old, new)

old2 = """Arm C's KV cache is **20% larger** than arm A's, measured, in artifact 1's own
data. The plausible mechanism is that arm C's warm `torch.compile` cache means
compilation is not holding transient memory when vLLM profiles for KV
allocation, leaving more behind."""
new2 = """Arm C's KV cache is **20% larger** than arm A's, measured, in artifact 1's own
data. The mechanism is not merely plausible — `fixtures/README.md` shows it on
a single worker. Between recon run 0 (cold `torch.compile`, 38.96 s) and runs 1–2
(warm, 0.30 s and 0.29 s), peak activation during vLLM's memory profiling fell
from 1.18 GiB to 0.19 GiB and the KV cache rose from 35,792 to 43,040 tokens —
the same two values artifact 1's arms A/B and C report. A cold compile holds
about a gigabyte of transient memory at the moment vLLM sizes the KV cache, and
that gigabyte is what arm C gets back."""
assert old2 in t, "KV mechanism paragraph not found verbatim"
p.write_text(t.replace(old2, new2))
print("recon-a2.md corrected")
PY
```

Expected: `recon-a2.md corrected`.

- [ ] **Step 2: Verify every number quoted against its source**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
grep -n "2 distinct hosts, one of them serving 23 runs" docs/experiment.md
grep -n "1.18 GiB\|0.19 GiB\|38.96 s\|0.30 s\|0.29 s" fixtures/README.md
```

Expected: the host-affinity sentence in `docs/experiment.md`, and the table row values in `fixtures/README.md`. If any quoted number is not in its source, fix the quote — do not keep a number the record does not contain.

- [ ] **Step 3: Commit**

```bash
git add docs/recon-a2.md
git commit -m "recon: the one-worker result had a third cause, and the KV mechanism has direct evidence"
```

---

## Task 3: The Q1/Q2 capture script

The one piece that turns "plan 2b cannot be written honestly" into "it can". Built and proven entirely against a fake HTTP session; running it for real is the operator's call.

**Files:**
- Create: `recon/capture_a2.py`
- Test: `tests/test_recon_capture_a2.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recon_capture_a2.py`:

```python
"""The artifact-2 reconnaissance capture, proven without a network.

Every property tested here is one whose failure costs money or corrupts the
evidence: a capture that spends against a misconfigured endpoint, leaves a
worker pinned and billing, writes the API key into a committed fixture, or
polls before every job of a burst is submitted (which would serialise the
burst and answer Q2 about the wrong experiment).
"""

import itertools
import json
import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "recon"))

import capture_a2

EID = "ep-test"
KEY = "sk-THIS-MUST-NEVER-REACH-DISK"
GOOD_ENDPOINT = {"id": EID, "flashboot": False, "workersMin": 0, "workersMax": 2}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Scripted RunPod. `endpoint` is mutated by /update, as the real one is."""

    def __init__(self, endpoint=None, health_status=200, health_raises=False,
                 ignore_release=False):
        self.endpoint = dict(endpoint or GOOD_ENDPOINT)
        self.health_status = health_status
        self.health_raises = health_raises
        self.ignore_release = ignore_release
        self.calls = []
        self._jobs = itertools.count(1)

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url, None))
        if url.endswith(f"/endpoints/{EID}"):
            return FakeResponse(200, dict(self.endpoint))
        if url.endswith("/health"):
            if self.health_raises:
                raise requests.ConnectionError("health endpoint dropped the connection")
            if self.health_status != 200:
                return FakeResponse(self.health_status, {"error": "not found"})
            return FakeResponse(200, {"workers": {"running": self.endpoint["workersMin"]}})
        if "/status/" in url:
            job = url.rsplit("/", 1)[1]
            return FakeResponse(200, {
                "id": job, "status": "COMPLETED", "workerId": f"w-{job}",
                "delayTime": 100, "executionTime": 5000,
                "output": {"log_lines": ["torch.compile took 1.00 s in total"]},
            })
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers, json, timeout):
        self.calls.append(("POST", url, json))
        if url.endswith("/run"):
            return FakeResponse(200, {"id": f"job{next(self._jobs)}"})
        if url.endswith("/update"):
            if not (self.ignore_release and json.get("workersMin") == 0):
                self.endpoint.update(json)
            return FakeResponse(200, dict(self.endpoint))
        raise AssertionError(f"unexpected POST {url}")


def _capture(tmp_path, session):
    return capture_a2.Capture(
        EID, KEY, out=tmp_path / "a2_recon", workers=2, session=session,
        clock=itertools.count(0, 50).__next__, sleep=lambda s: None,
    )


def _posts(session, suffix):
    return [body for method, url, body in session.calls if method == "POST" and url.endswith(suffix)]


@pytest.mark.parametrize("override, word", [
    ({"flashboot": True}, "flashboot"),
    ({"workersMin": 1}, "workersMin"),
    ({"workersMax": 1}, "workersMax"),
])
def test_it_refuses_to_spend_against_a_misconfigured_endpoint(tmp_path, override, word):
    """FlashBoot on measures RunPod's cache instead of a cold start;
    workersMin > 0 keeps a worker warm between bursts; workersMax below the
    burst size makes the burst a queue. Each produces a plausible, wrong
    answer to Q2. Nothing may be submitted or updated."""
    session = FakeSession(dict(GOOD_ENDPOINT, **override))
    with pytest.raises(capture_a2.RefuseToSpend, match=word):
        _capture(tmp_path, session).run()
    assert [c for c in session.calls if c[0] == "POST"] == []


def test_a_burst_submits_every_job_before_polling_any(tmp_path):
    """Polling job 1 to completion before submitting job 2 serialises the
    burst, which reproduces artifact 1's one-worker result by construction
    and answers Q2 about the wrong experiment."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    first_burst = session.calls[: next(
        i for i, c in enumerate(session.calls) if "/status/" in c[1]
    )]
    assert sum(1 for c in first_burst if c[1].endswith("/run")) == 2


def test_the_scale_phase_pins_then_releases_then_restores(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert _posts(session, "/update") == [
        {"workersMin": 2}, {"workersMin": 0}, {"workersMin": 0},
    ]


def test_workers_max_is_never_written(tmp_path):
    """workersMax is the cost ceiling the operator chose. A capture that
    raised it would be spending beyond what was authorised."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert all("workersMax" not in body for body in _posts(session, "/update"))


def test_workers_min_is_restored_when_a_phase_fails(tmp_path):
    """A pinned worker bills by the second whether or not anything runs on it.
    The failure must still propagate -- a swallowed error would read as a
    completed capture."""
    session = FakeSession(health_raises=True)
    with pytest.raises(requests.ConnectionError):
        _capture(tmp_path, session).run()
    assert session.endpoint["workersMin"] == 0


def test_a_restore_that_does_not_land_is_loud(tmp_path):
    session = FakeSession(ignore_release=True)
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        _capture(tmp_path, session).run()


def test_the_api_key_never_reaches_disk(tmp_path):
    """Everything under the output directory is destined for fixtures/, which
    is committed. Request headers carry the key and are never recorded."""
    _capture(tmp_path, FakeSession()).run()
    for path in (tmp_path / "a2_recon").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(), f"{path.name} contains the API key"


def test_every_platform_response_is_recorded(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    lines = (tmp_path / "a2_recon" / "capture.jsonl").read_text().splitlines()
    assert len(lines) == len(session.calls)
    entry = json.loads(lines[0])
    assert set(entry) == {"t", "method", "url", "request", "status_code", "response"}


def test_a_missing_health_endpoint_is_recorded_not_fatal(tmp_path):
    """`GET /v2/{id}/health` is the one platform call this repository has
    never exercised. If it does not exist, that is a Q1 finding -- worker
    counts are not observable that way -- and the job-level workerIds remain.
    It must not abort the capture."""
    session = FakeSession(health_status=404)
    _capture(tmp_path, session).run()
    entries = [json.loads(l) for l in
               (tmp_path / "a2_recon" / "capture.jsonl").read_text().splitlines()]
    assert any(e["url"].endswith("/health") and e["status_code"] == 404 for e in entries)


def test_each_job_status_is_saved_verbatim(tmp_path):
    _capture(tmp_path, FakeSession()).run()
    saved = sorted(p.name for p in (tmp_path / "a2_recon").glob("burst*.json"))
    assert saved == ["burst1_0.json", "burst1_1.json", "burst2_0.json", "burst2_1.json"]
    assert json.loads((tmp_path / "a2_recon" / "burst1_0.json").read_text())["workerId"]


def test_a_burst_of_one_is_refused(tmp_path):
    """One worker cannot demonstrate that the platform starts DISTINCT
    workers, which is the whole of Q2's first half."""
    with pytest.raises(ValueError, match="at least 2"):
        capture_a2.Capture(EID, KEY, out=tmp_path, workers=1, session=FakeSession())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_recon_capture_a2.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'capture_a2'`.

- [ ] **Step 3: Write the capture script**

Create `recon/capture_a2.py`:

```python
"""Artifact 2 reconnaissance: Q1 (replica-count control) and Q2 (distinct
workers under concurrent load -- genuine cold start, or warm-host restart).

Spec §9. Saves every platform response verbatim into fixtures/a2_recon/ and
publishes nothing. Like recon/capture.py it imports only the standard library
and `requests`, so a reader can reproduce the committed fixtures without
installing this repository's packages; the retry loop is therefore a
deliberate third copy (coldstart/runpod_submitter.py explains the second).

WHAT IS ASSUMED, AND HOW THE CAPTURE CHECKS IT. Known from committed evidence:
`POST {REST}/endpoints/{id}/update` changes endpoint configuration
(recon/README.md, the flashboot fix); `workersMin` and `workersMax` are endpoint
fields (coldstart/preflight.py, docs/experiment.md); `/run` and `/status/{job}`
behave as recon/capture.py found. NOT known: `GET {API}/{id}/health` as a way to
observe worker counts -- every `/health` in this repository is vLLM's own local
check. The capture polls it anyway and records whatever comes back, a 404
included, because "the platform does not expose worker counts" is itself a Q1
finding, and job-level workerIds remain as a fallback observation of scale.

It never writes `workersMax`: that is the cost ceiling, and it belongs to the
human who provisioned the endpoint. It raises `workersMin` only inside the scale
phase, restores it to 0 in a `finally`, and re-reads the endpoint to prove the
restore landed -- a pinned worker bills by the second whether or not anything
runs on it.

PROTOCOL
  preflight  GET the endpoint. Refuse unless flashboot is false, workersMin is 0
             and workersMax >= WORKERS >= 2.
  burst1     Submit WORKERS jobs back to back, ALL before any is polled, so the
             platform must start more than one worker if it ever will (Q2a).
  idle       Wait IDLE_WAIT_SECONDS -- far past the 5 s idleTimeout -- so every
             container from burst1 terminates. Without this, burst2 would reuse
             live containers and measure container survival, not host affinity.
  burst2     The same again. A workerId repeated from burst1 is a host the
             platform re-allocated after termination: a warm-host candidate
             (docs/experiment.md saw 23 of 27 runs on one host). Its engine log
             says whether the container was cold (full torch.compile) and its
             delayTime whether an image was pulled.
  scale      Set workersMin = WORKERS, poll health for SCALE_OBSERVE_SECONDS; set
             workersMin = 0, poll again (Q1: acknowledgement and time to effect).
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.runpod.ai/v2"
REST = "https://rest.runpod.io/v1"
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
WORKERS = 2
IDLE_WAIT_SECONDS = 60.0
SCALE_OBSERVE_SECONDS = 600.0
POLL_SECONDS = 5.0
# Artifact 1's first priming run spent 1898 s in `delayTime` alone pulling the
# image to a cold host; a shorter budget records a healthy run as a timeout.
JOB_TIMEOUT_SECONDS = 5400.0
OUT = Path("fixtures") / "a2_recon"


class RefuseToSpend(RuntimeError):
    """The endpoint is not configured for this capture. Nothing was submitted
    and nothing was changed."""


class Capture:
    def __init__(self, endpoint_id, api_key, out=OUT, workers=WORKERS,
                 session=requests, clock=time.time, sleep=time.sleep, attempts=5):
        if workers < 2:
            raise ValueError(
                f"workers={workers}; a burst needs at least 2 jobs, because one "
                "worker cannot demonstrate that the platform starts DISTINCT "
                "workers, which is the first half of Q2"
            )
        self._id = endpoint_id
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._out = Path(out)
        self._out.mkdir(parents=True, exist_ok=True)
        self._log = self._out / "capture.jsonl"
        self._workers = workers
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._attempts = attempts

    def _record(self, method, url, body, response):
        # The request HEADERS are never written: they carry the API key, and
        # this directory is committed as fixtures.
        try:
            payload = response.json()
        except ValueError:
            payload = getattr(response, "text", None)
        entry = {"t": self._clock(), "method": method, "url": url, "request": body,
                 "status_code": response.status_code, "response": payload}
        with self._log.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return payload

    def _call(self, method, url, body=None, require_ok=True):
        for attempt in range(self._attempts):
            if method == "GET":
                r = self._session.get(url, headers=self._headers, timeout=30)
            else:
                r = self._session.post(url, headers=self._headers, json=body, timeout=30)
            payload = self._record(method, url, body, r)
            # 409 follows any endpoint config change for a while and 5xx shows
            # up under load; both are transient. Every attempt is recorded, so
            # the retry is visible in the evidence rather than hidden by it.
            if (r.status_code == 409 or r.status_code >= 500) and attempt < self._attempts - 1:
                self._sleep(2**attempt)
                continue
            if require_ok and not 200 <= r.status_code < 300:
                raise RuntimeError(f"{method} {url} returned {r.status_code}: {payload!r}")
            return payload
        raise RuntimeError("unreachable: retry loop exited without returning")

    def endpoint(self) -> dict:
        return self._call("GET", f"{REST}/endpoints/{self._id}")

    def preflight(self) -> dict:
        ep = self.endpoint()
        problems = []
        if ep.get("flashboot") is not False:
            problems.append(
                f"flashboot is {ep.get('flashboot')!r}; it caches worker state to "
                "accelerate cold starts, so Q2 would measure RunPod's cache"
            )
        if ep.get("workersMin") != 0:
            problems.append(
                f"workersMin is {ep.get('workersMin')!r}; a standing worker is "
                "warm between bursts and hides the cold start Q2 asks about"
            )
        workers_max = ep.get("workersMax")
        if not isinstance(workers_max, int) or workers_max < self._workers:
            problems.append(
                f"workersMax is {workers_max!r}, below the burst of {self._workers}; "
                "the burst would queue on one worker and reproduce artifact 1's "
                "result by construction"
            )
        if problems:
            raise RefuseToSpend("refusing to spend:\n  " + "\n  ".join(problems))
        return ep

    def _submit(self) -> str:
        return self._call("POST", f"{API}/{self._id}/run", {"input": {"recon": True}})["id"]

    def _await(self, job_id: str) -> dict:
        deadline = self._clock() + JOB_TIMEOUT_SECONDS
        while True:
            status = self._call("GET", f"{API}/{self._id}/status/{job_id}")
            if status.get("status") in TERMINAL_STATES or self._clock() >= deadline:
                return status
            self._sleep(POLL_SECONDS)

    def burst(self, label: str) -> list[str]:
        # Every job is submitted before any is polled. Polling job 1 to
        # completion first would serialise the burst -- artifact 1's design,
        # and the reason it could never see a second worker.
        ids = [self._submit() for _ in range(self._workers)]
        for i, job_id in enumerate(ids):
            status = self._await(job_id)
            (self._out / f"{label}_{i}.json").write_text(json.dumps(status, indent=2))
        return ids

    def _set_workers_min(self, n: int) -> None:
        self._call("POST", f"{REST}/endpoints/{self._id}/update", {"workersMin": n})

    def _observe(self, seconds: float) -> None:
        deadline = self._clock() + seconds
        while self._clock() < deadline:
            self._call("GET", f"{API}/{self._id}/health", require_ok=False)
            self._sleep(POLL_SECONDS)

    def scale(self) -> None:
        self._set_workers_min(self._workers)
        self._observe(SCALE_OBSERVE_SECONDS)
        self._set_workers_min(0)
        self._observe(SCALE_OBSERVE_SECONDS)

    def restore(self) -> None:
        self._set_workers_min(0)
        if self.endpoint().get("workersMin") != 0:
            raise RuntimeError(
                "RESTORE FAILED: workersMin is not 0 after the capture. Set it to "
                "0 by hand now -- a pinned worker bills continuously whether or "
                "not anything is running on it"
            )

    def run(self) -> None:
        # Preflight sits OUTSIDE the try: a refusal changed nothing, so there
        # is nothing to restore, and restoring would be a write to an endpoint
        # the capture just declined to touch.
        self.preflight()
        try:
            self.burst("burst1")
            self._sleep(IDLE_WAIT_SECONDS)
            self.burst("burst2")
            self.scale()
        finally:
            self.restore()


def main(argv: list[str]) -> None:
    key = os.environ["RUNPOD_API_KEY"]
    # Deliberately NOT artifact 1's RUNPOD_ENDPOINT_ID. This capture changes
    # workersMin on the endpoint it is pointed at; an inherited variable would
    # point it at artifact 1's pinned endpoint. Preflight would refuse that one
    # (workersMax 1), but the name makes the intent unmistakable first.
    endpoint = os.environ["RUNPOD_A2_ENDPOINT_ID"]
    capture = Capture(endpoint, key)
    if "--preflight-only" in argv:
        print(json.dumps(capture.preflight(), indent=2))
        return
    capture.run()


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_recon_capture_a2.py -q && .venv/bin/ruff check recon/capture_a2.py tests/test_recon_capture_a2.py`
Expected: all tests pass, `All checks passed!`.

- [ ] **Step 5: Document how to run it**

Append to `recon/README.md`:

```markdown
## Artifact 2 capture (spec §9 Q1/Q2)

Needs a **new** endpoint — worker bounds and datacenter are fixed at creation,
so artifact 1's `ka5mryakkxumew` cannot be repurposed. Provision one with
`workersMin 0`, `workersMax` at least 2, the same template and a volume in a
datacenter with verified 24GB stock, then force `flashboot: false` with a
follow-up `POST /endpoints/{id}/update` (it silently ignores `false` at create).

```
export RUNPOD_API_KEY=...
export RUNPOD_A2_ENDPOINT_ID=...    # NOT artifact 1's RUNPOD_ENDPOINT_ID

.venv/bin/python recon/capture_a2.py --preflight-only   # free: one GET
.venv/bin/python recon/capture_a2.py                     # spends: 4 jobs + a pinned window
.venv/bin/python recon/analyse_a2.py fixtures/a2_recon
```

The full run pins `workersMax` workers for up to 10 minutes and runs four cold
starts. Its cost is small against the spec §13 envelope, but it is real, and
running it is the operator's decision. Record the answers in `docs/recon-a2.md`.
```

- [ ] **Step 6: Commit**

```bash
git add recon/capture_a2.py tests/test_recon_capture_a2.py recon/README.md
git commit -m "recon: a capture protocol that can answer Q1 and Q2, proven without a network"
```

---

## Task 4: Tabulate the captured evidence

**Files:**
- Create: `recon/analyse_a2.py`
- Test: `tests/test_recon_analyse_a2.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recon_analyse_a2.py`:

```python
"""The analysis is proven against artifact 1's committed recon fixtures, whose
contents fixtures/README.md already documents -- so every expected value below
is checked against a written record, not against this code's own output."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "recon"))

import analyse_a2

FIXTURES = REPO / "fixtures" / "runpod_api"


@pytest.fixture(scope="module")
def rows():
    return analyse_a2.load(FIXTURES, "status_*.json")


def test_one_row_per_captured_job(rows):
    assert [r["label"] for r in rows] == ["status_0", "status_1", "status_2"]


def test_the_worker_identity_is_read_off_the_payload(rows):
    """fixtures/README.md: all three landed on worker iiewfw59dqskoe."""
    assert {r["worker_id"] for r in rows} == {"iiewfw59dqskoe"}
    assert analyse_a2.distinct_workers(rows) == 1


def test_compile_time_separates_a_cold_container_from_a_warm_one(rows):
    """fixtures/README.md's table: 38.96 s cold, then 0.30 s and 0.29 s."""
    assert [r["compile_s"] for r in rows] == pytest.approx([38.96, 0.30, 0.29])


def test_kv_capacity_is_reported(rows):
    assert [r["kv_tokens"] for r in rows] == [35792, 43040, 43040]


def test_platform_delay_is_reported(rows):
    assert [r["delay_ms"] for r in rows] == [8577, 127, 127]


def test_a_failed_job_is_a_row_of_absences_not_a_crash(tmp_path):
    """A FAILED job carries no output. The table must show that it happened --
    dropping it would make a flaky burst look like a smaller clean one."""
    (tmp_path / "burst1_0.json").write_text(json.dumps({"status": "FAILED", "id": "j"}))
    [row] = analyse_a2.load(tmp_path, "burst*.json")
    assert row["status"] == "FAILED"
    assert row["worker_id"] is None and row["compile_s"] is None


def test_an_empty_capture_directory_is_refused(tmp_path):
    with pytest.raises(ValueError, match="no job payloads"):
        analyse_a2.load(tmp_path, "burst*.json")


def test_the_table_renders_every_row(rows):
    table = analyse_a2.render_table(rows)
    assert table.count("iiewfw59dqskoe") == 3
    assert "38.96" in table
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_recon_analyse_a2.py -q`
Expected: `ModuleNotFoundError: No module named 'analyse_a2'`.

- [ ] **Step 3: Write the analysis script**

Create `recon/analyse_a2.py`:

```python
"""Tabulate artifact 2's reconnaissance captures -- evidence, not verdicts.

One row per job: which worker ran it, how long the platform delayed it, how
long it executed, what the engine log says about compilation and weights, and
the KV capacity it reported. The Q1/Q2 verdicts are written into
docs/recon-a2.md by a person reading this table beside capture.jsonl. The rules
for calling a start "warm-host" are exactly what the capture is meant to inform,
so encoding them here in advance would decide the answer before seeing the data.

Unlike capture_a2.py this is not a frozen reproduction tool, so it imports
artifact 1's log parser and payload accessors instead of re-deriving them: a
second parser for the same log format is a second answer waiting to diverge.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.runpod_api import extract_lifecycle, extract_worker_id
from coldstart.vllm_logs import parse_engine_log

# Present only when weights were NOT already on disk (fixtures/README.md,
# parser hazard 1), so its presence distinguishes a host that had to fetch.
WEIGHTS_DOWNLOAD = re.compile(r"Time spent downloading weights", re.IGNORECASE)

COLUMNS = ("label", "status", "worker_id", "delay_ms", "execution_ms",
           "compile_s", "weights_downloaded", "kv_tokens")


def job_row(label: str, status: dict) -> dict:
    lifecycle = extract_lifecycle(status)
    lines = (status.get("output") or {}).get("log_lines") or []
    text = "\n".join(lines)
    parsed = parse_engine_log(text) if lines else None
    return {
        "label": label,
        "status": status.get("status"),
        "worker_id": extract_worker_id(status),
        "delay_ms": lifecycle.get("delay_ms"),
        "execution_ms": lifecycle.get("execution_ms"),
        "compile_s": parsed.phases.get("S4b") if parsed else None,
        "weights_downloaded": bool(WEIGHTS_DOWNLOAD.search(text)) if lines else None,
        "kv_tokens": parsed.engine_info.get("kv_capacity_tokens") if parsed else None,
    }


def load(directory: Path, pattern: str) -> list[dict]:
    paths = sorted(Path(directory).glob(pattern))
    if not paths:
        raise ValueError(
            f"no job payloads match {pattern!r} in {directory}; an empty table "
            "would read as a capture in which nothing happened"
        )
    return [job_row(p.stem, json.loads(p.read_text())) for p in paths]


def distinct_workers(rows: list[dict]) -> int:
    return len({r["worker_id"] for r in rows if r["worker_id"]})


def render_table(rows: list[dict]) -> str:
    def cell(v):
        return "—" if v is None else str(v)

    head = "| " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * len(COLUMNS)
    body = ["| " + " | ".join(cell(r[c]) for c in COLUMNS) + " |" for r in rows]
    return "\n".join([head, rule, *body, "", f"distinct workers: {distinct_workers(rows)}"])


def main(argv: list[str]) -> None:
    directory = Path(argv[0]) if argv else Path("fixtures") / "a2_recon"
    print(render_table(load(directory, "burst*.json")))


if __name__ == "__main__":
    main(sys.argv[1:])
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_recon_analyse_a2.py -q && .venv/bin/ruff check recon/analyse_a2.py tests/test_recon_analyse_a2.py`
Expected: all pass, `All checks passed!`.

- [ ] **Step 5: Confirm the boundary guard is untouched**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_autoscale_boundary.py tests/test_harness_boundary.py -q`
Expected: pass. (`recon/` is outside both guards' scope; this confirms nothing under `autoscale/` or `harness/` changed.)

- [ ] **Step 6: Register the file with the harness extraction's import rewrite**

In `docs/superpowers/plans/2026-09-03-harness-extraction.md`, directly under the `**Architecture:**` paragraph, add:

```markdown
**Added 2026-09-26 by plan 2a:** `recon/analyse_a2.py` imports `coldstart.vllm_logs` and `coldstart.runpod_api`. Both move in this plan (Tasks 5 and 12), and the rewrite list above does not name `recon/`. Include it in those two tasks' import rewrites. `recon/capture.py` and `recon/capture_a2.py` import neither, by design.
```

- [ ] **Step 7: Commit**

```bash
git add recon/analyse_a2.py tests/test_recon_analyse_a2.py docs/superpowers/plans/2026-09-03-harness-extraction.md
git commit -m "recon: tabulate captured jobs, proven against artifact 1's documented fixtures"
```

---

## Task 5: `autoscale/traffic.py` — the traffic model's one home

Before starting: confirm Task 1 Step 5's background render finished (`build/plan2a-baseline/figures/sweep-cache.json` exists).

**Files:**
- Create: `autoscale/traffic.py`
- Test: `tests/test_traffic.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_traffic.py`:

```python
from pathlib import Path

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,
    BASELINE_FRACTION_OF_SATURATION,
    RAMP_SECONDS,
    SUSTAIN_SECONDS,
    saturation_rps,
    spike_shape,
)

REPO = Path(__file__).resolve().parents[1]


def test_saturation_is_the_best_point_not_the_last():
    """Continuous batching makes throughput non-monotonic past the knee. On the
    placeholder the top point (64 at 2.10 s) sustains 30.5 rps while 32 at
    0.95 s sustains 33.7 -- reading the last point understates saturation 9%."""
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) == pytest.approx(32 / 0.95)
    assert saturation_rps(SERVICE_CURVE_PLACEHOLDER) > 64 / 2.10


def test_every_constructible_curve_has_a_positive_concurrency_point():
    """`saturation_rps` takes a max over points with positive concurrency and
    has no empty-case guard, because ServiceCurve makes the empty case
    unconstructible: at least two points, distinct concurrencies, none
    negative -- so at least one is positive. Pinned here so that if
    ServiceCurve ever relaxes one of those, this fails instead of
    `saturation_rps` raising a context-free `max()` error."""
    with pytest.raises(ValueError, match="distinct"):
        ServiceCurve(points=[(0, 0.3, 1.0, 0.1), (0, 0.3, 1.0, 0.1)], measured=False)


def test_the_step_follows_the_preregistered_rule():
    sat = saturation_rps(SERVICE_CURVE_PLACEHOLDER)
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    assert shape.kind == "step"
    assert shape.baseline_rate == pytest.approx(0.70 * sat, rel=1e-15)
    assert shape.k == pytest.approx((0.70 + 0.25) / 0.70, rel=1e-12)
    assert shape.ramp == 0.0
    assert shape.sustain == 190.0


def test_the_ramp_is_half_the_sustain():
    assert spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp").ramp == 95.0


def test_a_reduced_window_keeps_r_equal_to_d_over_two():
    """The end-to-end test halves the window for speed. R = D/2 must hold there
    too, which is why the ramp is derived rather than accepted."""
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "ramp", sustain=95.0)
    assert shape.ramp == 47.5


def test_a_candidate_regime_can_be_measured_before_it_is_adopted():
    shape = spike_shape(
        SERVICE_CURVE_PLACEHOLDER, "step", baseline_fraction=0.40, additional_replicas=0.5
    )
    assert shape.k == pytest.approx((0.40 + 0.5) / 0.40)


@pytest.mark.parametrize("name", ["sustain", "baseline_fraction", "additional_replicas"])
@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_parameters_are_refused(name, bad):
    with pytest.raises(ValueError, match=name):
        spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", **{name: bad})


def test_the_constants_are_the_ones_the_preregistration_states():
    """An amendment to the traffic model is a change to a pre-registered
    quantity. It has to touch the document, not just this module."""
    prereg = (REPO / "docs" / "experiment-a2.md").read_text()
    assert BASELINE_FRACTION_OF_SATURATION == 0.70
    assert "baseline = **70%** of measured saturation" in prereg
    assert ADDITIONAL_REPLICAS_AT_PEAK == 0.25
    assert "**0.25 additional replicas**" in prereg
    assert SUSTAIN_SECONDS == 190.0
    assert "rounded to **190 s**" in prereg
    assert RAMP_SECONDS == 95.0
    assert "= **95 s**" in prereg
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_traffic.py -q`
Expected: `ModuleNotFoundError: No module named 'autoscale.traffic'`.

- [ ] **Step 3: Write the module**

Create `autoscale/traffic.py`:

```python
"""The traffic model, stated once.

docs/experiment-a2.md fixes the traffic model as a RULE over the service curve
-- baseline a fraction of one replica's saturation, `k` sized to require some
number of additional replicas at the measured service rate -- with "the two
absolute rates computed from the service curve and committed before any policy
sweep runs". Literals fixed against one curve silently stop implementing the
rule the moment the curve is replaced, which is exactly what plan 2's measured
sweep will do.

Until this module the rule lived in four places: the render script, the
noise-floor diagnostic, the regime probe (twice, inline) and the end-to-end
test. They agreed because a test compared two of them and because the
2026-09-17 amendment was applied by hand in each. When the measured curve
lands, one place changes.

R = D/2 is encoded structurally: `spike_shape` derives the ramp from the
sustain instead of accepting both, so no caller can pass a pair that breaks the
pre-registered relationship -- including the end-to-end test's halved window.
"""

import math

from autoscale.arrivals import SpikeShape
from autoscale.service import ServiceCurve

__all__ = [
    "ADDITIONAL_REPLICAS_AT_PEAK",
    "BASELINE_FRACTION_OF_SATURATION",
    "RAMP_SECONDS",
    "SUSTAIN_SECONDS",
    "saturation_rps",
    "spike_shape",
]

# D = 2 x p95(arm A) = 192.7 s, rounded. Pinned to arm A and held constant
# across both distributions so the composition comparison varies one thing.
SUSTAIN_SECONDS = 190.0
# R = D / 2.
RAMP_SECONDS = SUSTAIN_SECONDS / 2
# Both amended 2026-09-17 from 40% and 3. As first registered they put the peak
# at 3.4x one replica's saturation and every policy delivered an identical p99;
# docs/experiment-a2.md states the old values, the evidence and the search.
BASELINE_FRACTION_OF_SATURATION = 0.70
ADDITIONAL_REPLICAS_AT_PEAK = 0.25


def saturation_rps(curve: ServiceCurve) -> float:
    """Requests per second one replica sustains at its best operating point.

    A max over the measured points rather than the value at the last one:
    continuous batching makes throughput non-monotonic past the latency knee.

    No empty-case guard: ServiceCurve refuses fewer than two points, duplicate
    concurrencies and negative ones, so at least one point is positive.
    `tests/test_traffic.py` pins that guarantee rather than testing a branch
    that cannot run.
    """
    return max(c / curve.latency_at(c) for c, _, _, _ in curve.points if c > 0)


def spike_shape(
    curve: ServiceCurve,
    kind: str,
    *,
    sustain: float = SUSTAIN_SECONDS,
    baseline_fraction: float = BASELINE_FRACTION_OF_SATURATION,
    additional_replicas: float = ADDITIONAL_REPLICAS_AT_PEAK,
) -> SpikeShape:
    """The pre-registered spike of `kind`, derived from `curve`.

    `baseline_fraction` and `additional_replicas` default to the pre-registered
    values. The regime probe and the noise-floor diagnostic override them to
    measure a candidate BEFORE the pre-registration is amended to adopt it;
    any caller that overrides them is running a different experiment and
    should say so wherever it prints.

    The arithmetic order -- baseline, then peak as baseline plus the additional
    rate, then k as their ratio -- is the order every previous copy used, kept
    so the consolidation changes no float in any shape.
    """
    for name, value in (
        ("sustain", sustain),
        ("baseline_fraction", baseline_fraction),
        ("additional_replicas", additional_replicas),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"{name} is {value!r}; it must be finite and positive. Zero "
                "additional replicas is not a spike, a zero baseline makes k "
                "infinite, and a NaN passes every later comparison silently"
            )
    saturation = saturation_rps(curve)
    baseline = baseline_fraction * saturation
    peak = baseline + additional_replicas * saturation
    return SpikeShape(
        kind=kind,
        baseline_rate=baseline,
        k=peak / baseline,
        ramp=sustain / 2 if kind == "ramp" else 0.0,
        sustain=sustain,
    )
```

- [ ] **Step 4: Run the tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_traffic.py tests/test_autoscale_boundary.py -q && .venv/bin/ruff check autoscale/traffic.py tests/test_traffic.py`
Expected: all pass. The boundary test confirms `autoscale/traffic.py` does not import `coldstart`.

- [ ] **Step 5: Commit**

```bash
git add autoscale/traffic.py tests/test_traffic.py
git commit -m "feat: the traffic model's one home, with R = D/2 made structural"
```

---

## Task 6: Switch every caller to `autoscale.traffic`, gated on byte parity

The old private helpers in the render script become delegating shims — kept until Task 11 so the end-to-end test keeps exercising them as a second parity check. Nothing is deleted in this task.

**Files:**
- Modify: `scripts/a2_render_figures.py:40-78`, `:115`, `:170`
- Modify: `scripts/a2_gap_noise_floor.py:36-49`, `:93-116`
- Modify: `scripts/a2_regime_probe.py:54-70`, `:92-97`, `:167-172`, `:224-225`

- [ ] **Step 1: Render script — import the model, shim the old helpers, switch the call sites**

In `scripts/a2_render_figures.py`, replace the three constant lines

```python
BASELINE_FRACTION_OF_SATURATION = 0.70  # docs/experiment-a2.md, amended 2026-09-17
ADDITIONAL_REPLICAS_AT_PEAK = 0.25  # docs/experiment-a2.md, amended 2026-09-17
RAMP_SECONDS = 95.0  # docs/experiment-a2.md, "Traffic model": R = D / 2
```

with nothing (delete them), and add directly after `from autoscale.sweep import SweepConfig, run_sweep`:

```python
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,  # noqa: F401 -- tests read render.*; plan 2a Task 11
    BASELINE_FRACTION_OF_SATURATION,  # noqa: F401 -- tests read render.*; plan 2a Task 11
    RAMP_SECONDS,  # noqa: F401 -- tests read render.*; plan 2a Task 11
    saturation_rps,
    spike_shape,
)
```

This repository enables PLC0414, so the `X as X` re-export idiom is not available; a
`noqa` per name is what keeps the three test-facing constants importable as `render.*`
until Task 11 without a lint error.

Replace the whole of `_saturation_rps` and `_preregistered_shape` (docstrings included — the old docstring still says "baseline is 40%… three additional replicas", which the 2026-09-17 amendment made false) with:

```python
def _saturation_rps(curve) -> float:
    """Shim for `autoscale.traffic.saturation_rps`. Deleted in plan 2a Task 11,
    once parity with the old derivation has been proven through it."""
    return saturation_rps(curve)


def _preregistered_shape(curve, kind: str, ramp: float) -> SpikeShape:
    """Shim for `autoscale.traffic.spike_shape`. Deleted in plan 2a Task 11.

    The `ramp` argument is no longer an input -- R = D/2 is derived -- but a
    caller passing one that disagrees is told so rather than silently ignored.
    """
    shape = spike_shape(curve, kind)
    if ramp != shape.ramp:
        raise ValueError(
            f"ramp={ramp!r} disagrees with the pre-registered R = D/2 = "
            f"{shape.ramp!r} for kind={kind!r}; the ramp is derived, not chosen"
        )
    return shape
```

Switch the two call sites. Line 115:

```python
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, kind="step")
```

Line 170:

```python
    ramp_shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, kind="ramp")
```

`kind=` stays a keyword: `test_the_render_script_evaluates_h3_under_both_shapes` asserts the source contains `kind="ramp"`, and that check should keep meaning what it says.

- [ ] **Step 2: Noise floor — import from the model, not from the render script**

In `scripts/a2_gap_noise_floor.py`, replace

```python
import a2_render_figures as render_mod
from a2_render_figures import (
    UNTIL,
    _by_signal,
    _preregistered_shape,
    _saturation_rps,
)
```

with

```python
from a2_render_figures import UNTIL, _by_signal
```

remove `from autoscale.arrivals import SpikeShape`, and add

```python
from autoscale.traffic import (
    ADDITIONAL_REPLICAS_AT_PEAK,
    BASELINE_FRACTION_OF_SATURATION,
    spike_shape,
)
```

Replace the shape-construction block (the `if args.baseline_fraction is not None ...` / `else` pair) with:

```python
    if args.baseline_fraction is not None or args.additional_replicas is not None:
        fraction = (
            args.baseline_fraction
            if args.baseline_fraction is not None
            else BASELINE_FRACTION_OF_SATURATION
        )
        additional = (
            args.additional_replicas
            if args.additional_replicas is not None
            else ADDITIONAL_REPLICAS_AT_PEAK
        )
        shape = spike_shape(
            SERVICE_CURVE_PLACEHOLDER,
            "step",
            baseline_fraction=fraction,
            additional_replicas=additional,
        )
        print(
            f"NOT the pre-registered traffic model: baseline={fraction:.0%} of "
            f"saturation, {additional} additional replicas at peak "
            f"(peak/saturation={fraction + additional:.2f})"
        )
    else:
        shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
```

- [ ] **Step 3: Regime probe — both inline copies and the `main` literal**

In `scripts/a2_regime_probe.py`, change `from a2_render_figures import UNTIL, _saturation_rps` to `from a2_render_figures import UNTIL`, remove `SpikeShape` from the `autoscale.arrivals` import (keep `arrival_times`), and add, directly after the `from autoscale.sweep import (...)` block (ruff's import order):

```python
from autoscale.traffic import SUSTAIN_SECONDS, saturation_rps, spike_shape
```

In **both** `_probe` and `_verify`, replace

```python
    saturation = _saturation_rps(CURVE)
    baseline = baseline_fraction * saturation
    peak = baseline + additional_replicas * saturation
    shape = SpikeShape(
        kind="step", baseline_rate=baseline, k=peak / baseline, ramp=0.0, sustain=sustain
    )
```

with

```python
    shape = spike_shape(
        CURVE,
        "step",
        sustain=sustain,
        baseline_fraction=baseline_fraction,
        additional_replicas=additional_replicas,
    )
    saturation = saturation_rps(CURVE)
    baseline = shape.baseline_rate
    # Reported, not used to build anything: the probe prints and stores the
    # peak it searched. Recomputing it as baseline x k can differ in the last
    # bit, which would break byte parity for a label.
    peak = baseline + additional_replicas * saturation
```

In `main`, replace

```python
    sustain = 190.0  # pre-registered D, held fixed: it is measured (2 x p95 arm A)
    saturation = _saturation_rps(CURVE)
```

with

```python
    sustain = SUSTAIN_SECONDS  # pre-registered D, held fixed: measured, 2 x p95 arm A
    saturation = saturation_rps(CURVE)
```

- [ ] **Step 4: Lint the three scripts**

Run: `.venv/bin/ruff check scripts/a2_render_figures.py scripts/a2_gap_noise_floor.py scripts/a2_regime_probe.py`
Expected: `All checks passed!` If ruff reports an unused import, remove exactly that import — do not use `--fix` on the directory.

- [ ] **Step 5: Parity — shapes, bit-exact**

Re-run Task 1 Step 3's script, which calls the render helpers — now shims over `autoscale.traffic` — into a new file, and compare:

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
mkdir -p build/plan2a-after
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY' > build/plan2a-after/shapes.json
import json, sys
sys.path[:0] = [".", "scripts"]
import a2_render_figures as r
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as C
from autoscale.traffic import spike_shape

def fields(s):
    return [s.kind, s.baseline_rate, s.k, s.ramp, s.sustain]

out = {"saturation_rps": r._saturation_rps(C)}
out["render_step"] = fields(r._preregistered_shape(C, kind="step", ramp=0.0))
out["render_ramp"] = fields(r._preregistered_shape(C, kind="ramp", ramp=r.RAMP_SECONDS))
for f in (0.10, 0.20, 0.40, 0.70):
    for a in (0.25, 0.5, 1, 2, 3):
        out[f"candidate_{f}_{a}"] = fields(
            spike_shape(C, "step", baseline_fraction=f, additional_replicas=a)
        )
print(json.dumps(out, indent=1, sort_keys=True))
PY
cmp build/plan2a-baseline/shapes.json build/plan2a-after/shapes.json && echo "SHAPES: byte-identical"
```

Expected: `SHAPES: byte-identical`. **Any difference is a stop.** It means the consolidation changed a float, and every downstream number with it.

- [ ] **Step 6: Parity — the diagnostics' outputs**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py \
  --seeds 2 --reps 3 --out build/plan2a-after/noise_floor.json > /dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py \
  --seeds 2 --reps 3 --baseline-fraction 0.40 --additional-replicas 0.5 \
  --out build/plan2a-after/noise_floor_candidate.json > /dev/null
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_regime_probe.py \
  --stage screen --out build/plan2a-after/probe_screen.json > /dev/null
for f in noise_floor noise_floor_candidate probe_screen; do
  cmp -s build/plan2a-baseline/$f.json build/plan2a-after/$f.json && echo "$f: identical" || echo "$f: DIFFERS"
done
```

Expected: three `identical` lines.

- [ ] **Step 7: Full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q; echo "EXIT=$?"`
Expected: `EXIT=0`. The end-to-end test still derives shapes with its own local copy and still compares its constants against `render.*` — which now resolve to `autoscale.traffic` — so it is a live third parity check.

- [ ] **Step 8: Commit**

```bash
git add scripts/a2_render_figures.py scripts/a2_gap_noise_floor.py scripts/a2_regime_probe.py
git commit -m "refactor: every script derives the traffic model from autoscale.traffic

Shapes, the noise-floor outputs and the probe screen are byte-identical
to the Task 1 baseline. The render script keeps two delegating shims
until plan 2a Task 11 so the end-to-end test keeps exercising the old
entry points as a parity check."
```

---

## Task 7: `SimResult` keeps each request's arrival time

`latencies` is appended in **completion** order, and the arrival time — known at the append site, in `in_flight` — is thrown away. A latency-over-time trajectory cannot be rebuilt from what is stored. Additive: nothing that reads `latencies` changes.

**Files:**
- Modify: `autoscale/sim.py` — the `SimResult` dataclass, lines 266 and 270 (fixed capacity), lines 531 and 602 (policy loop)
- Test: `tests/test_sim.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sim.py`:

```python
def test_each_completed_latency_carries_its_arrival_time():
    """`latencies` is appended in COMPLETION order and used to drop the arrival
    time, so a latency-over-time trajectory -- what the open-loop validation
    gate compares -- could not be rebuilt from a SimResult at all."""
    from autoscale.service import SERVICE_CURVE_PLACEHOLDER

    arrivals = [0.0, 0.5, 1.0]
    result = run_fixed_capacity(arrivals, replicas=1, curve=SERVICE_CURVE_PLACEHOLDER, until=10.0)
    pairs = result.completed_requests()
    assert [a for a, _ in pairs] == arrivals
    assert [lat for _, lat in pairs] == result.latencies


def test_unfinished_requests_keep_their_arrival_times():
    """An unfinished request is the backlog. Dropping its arrival time would
    let a trajectory show the bins it came from as uncongested."""
    from autoscale.service import SERVICE_CURVE_PLACEHOLDER

    result = run_fixed_capacity([0.0, 0.1, 9.99], replicas=1,
                                curve=SERVICE_CURVE_PLACEHOLDER, until=10.0)
    assert result.unfinished_arrivals == [9.99]
    assert len(result.unfinished_arrivals) == result.unfinished


def test_a_half_populated_result_is_refused():
    """A SimResult built by hand with latencies but no arrivals must not pass
    for a complete one."""
    with pytest.raises(ValueError, match="arrival"):
        SimResult(latencies=[1.0, 2.0], completed=2).completed_requests()


def test_the_policy_loop_records_arrival_times_too(policy_run_result):
    """Both loops, or the field lies about any closed-loop result."""
    assert len(policy_run_result.completed_arrivals) == len(policy_run_result.latencies)
    assert len(policy_run_result.unfinished_arrivals) == policy_run_result.unfinished
```

And add the fixture near the top of `tests/test_sim.py` (after the imports):

```python
@pytest.fixture
def policy_run_result():
    import random

    from autoscale.arrivals import arrival_times
    from autoscale.coldstart_ecdf import LagDistribution
    from autoscale.controller import Controller
    from autoscale.service import SERVICE_CURVE_PLACEHOLDER
    from autoscale.sim import run_with_policy
    from autoscale.traffic import spike_shape

    rng = random.Random(3)
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", sustain=40.0)
    return run_with_policy(
        arrivals=arrival_times(shape, until=100.0, rng=rng),
        signal="queue_depth",
        controller=Controller(scale_up_at=2.0, scale_down_at=0.5, cooldown=30.0, max_replicas=4),
        lags=LagDistribution(samples=[20.0]),
        curve=SERVICE_CURVE_PLACEHOLDER,
        until=100.0,
        evaluate_every=5.0,
        rng=rng,
    )
```

If `tests/test_sim.py` does not already import `run_fixed_capacity`, `SimResult` and `pytest` at module level, add them to its imports.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_sim.py -q -k "arrival or half_populated"`
Expected: FAIL — `AttributeError: 'SimResult' object has no attribute 'completed_requests'`.

- [ ] **Step 3: Add the fields and the accessor**

In `autoscale/sim.py`, add to the `SimResult` dataclass after `latencies`:

```python
    # Arrival time of each entry in `latencies`, index for index. Kept because
    # `latencies` is appended in COMPLETION order and the open-loop validation
    # gate compares latency by ARRIVAL time -- which request came in when the
    # fleet was saturated is the whole comparison.
    completed_arrivals: list[float] = field(default_factory=list)
    # Arrival times of the requests still waiting or in flight when the window
    # closed. They are the backlog, and a trajectory that dropped them would
    # report the bins they arrived in as uncongested.
    unfinished_arrivals: list[float] = field(default_factory=list)
```

and a method on `SimResult`, after `percentiles`:

```python
    def completed_requests(self) -> list[tuple[float, float]]:
        """(arrival_time, latency) for every completed request.

        Refuses a result whose two lists disagree in length -- one built by
        hand, or by a loop that appends to `latencies` without recording the
        arrival. Pairing them up to the shorter list would silently attribute
        latencies to the wrong arrivals.
        """
        if len(self.completed_arrivals) != len(self.latencies):
            raise ValueError(
                f"{len(self.latencies)} latencies but {len(self.completed_arrivals)} "
                "arrival times; this result did not record when its requests "
                "arrived, so no latency can be placed in time"
            )
        return list(zip(self.completed_arrivals, self.latencies, strict=True))
```

- [ ] **Step 4: Record arrivals in both loops**

At **both** append sites (fixed capacity, currently line 266; policy loop, currently line 531), directly after `result.latencies.append(event.time - arrived)`, add:

```python
            result.completed_arrivals.append(arrived)
```

At **both** tally sites (currently lines 270 and 602), replace

```python
    result.unfinished = len(waiting) + len(in_flight)
```

with

```python
    result.unfinished_arrivals = sorted(waiting + list(in_flight.values()))
    result.unfinished = len(result.unfinished_arrivals)
```

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_sim.py -q && PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q; echo "EXIT=$?"`
Expected: `EXIT=0`.

- [ ] **Step 6: Parity — the sweep's outputs did not move**

`latencies`, `unfinished` and everything computed from them must be unchanged. Re-run Task 6 Step 6's noise-floor command and compare against the baseline again:

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py \
  --seeds 2 --reps 3 --out build/plan2a-after/noise_floor_t7.json > /dev/null
cmp build/plan2a-baseline/noise_floor.json build/plan2a-after/noise_floor_t7.json && echo "noise floor: identical"
```

Expected: `noise floor: identical`.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff check autoscale/sim.py tests/test_sim.py
git add autoscale/sim.py tests/test_sim.py
git commit -m "feat: SimResult keeps each request's arrival time, in both loops"
```

---

## Task 8: The validation core — the shared arithmetic, then artifact 2's gate

Two modules, split on the import boundary. `autoscale/validation_band.py` holds the band and verdict arithmetic over plain sequences and imports nothing that reaches `coldstart`. `autoscale/validation.py` is artifact 2's gate: its pre-registered constants, the `RealRun` record, and the replay into `run_fixed_capacity`.

**Why the split.** `autoscale.sim` imports `autoscale.coldstart_ecdf`, which imports `coldstart` at load time — measured: `import autoscale.sim` puts `coldstart` in `sys.modules`, `import autoscale.stats` does not. Artifact 4's placement simulator needs the band and verdict and forbids `coldstart` transitively; it asked, and its scope record (`docs/superpowers/specs/2026-09-26-multi-model-serving-economics-scope.md` §1d, decision 12) depends on the answer. The arithmetic is artifact-agnostic anyway — nothing in it knows how a prediction was made or how a run was driven.

**Files:**
- Create: `autoscale/validation_band.py`
- Create: `autoscale/validation.py`
- Test: `tests/test_validation_band.py`, `tests/test_validation.py`

- [ ] **Step 1: Write the failing tests for the shared arithmetic**

Create `tests/test_validation_band.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

from autoscale.validation_band import BandBin, Bin, band, compare, trajectory

REPO = Path(__file__).resolve().parents[1]
# The comparison threshold these tests hold compare() to. Chosen here, not
# imported from any artifact: each artifact pre-registers its own.
MIN_COMPARED = 5


def _schedule(bins):
    """20 requests per 10 s bin, spaced 0.5 s: exactly the p50 sample floor."""
    return tuple(i * 0.5 for i in range(20 * bins))


def _trajectory(latency, bins=6):
    schedule = _schedule(bins)
    lat = latency if isinstance(latency, list) else [latency] * len(schedule)
    return trajectory(schedule, lat, until=10.0 * bins, bin_seconds=10.0)


def _pred(p50s):
    return [Bin(i * 10.0, (i + 1) * 10.0, 20, 20, 0, p, "ok") for i, p in enumerate(p50s)]


def _band(n, lo=1.0, hi=1.2, status="ok"):
    return [BandBin(i * 10.0, (i + 1) * 10.0, lo, hi, status) for i in range(n)]


# ---- the boundary this module exists for -----------------------------------

def test_importing_it_does_not_load_artifact_one():
    """Artifact 4's placement simulator imports this module across a
    TRANSITIVE boundary against `coldstart`. `autoscale.sim` reaches
    `coldstart` through `autoscale.coldstart_ecdf`, so one convenience import
    of it here would end the arrangement silently -- and
    tests/test_autoscale_boundary.py checks direct imports only, so it would
    not notice. A fresh interpreter, because this test process has already
    loaded `coldstart` through other test modules."""
    code = (
        "import sys; import autoscale.validation_band; "
        "print(sorted(m for m in sys.modules if m == 'coldstart' or m.startswith('coldstart.')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]", (
        f"importing autoscale.validation_band loads {out.stdout.strip()}; artifact 4 "
        "imports this module precisely because it must not pull in artifact 1's package"
    )


# ---- trajectory -------------------------------------------------------------

def test_a_bin_with_enough_completed_requests_reports_its_median():
    [first, second] = trajectory(_schedule(2), [1.0] * 40, until=20.0, bin_seconds=10.0)
    assert (first.status, first.p50, first.requests) == ("ok", 1.0, 20)
    assert second.status == "ok"


def test_a_bin_with_any_unfinished_request_is_censored_not_summarised():
    """The median of the requests that FINISHED, in a bin where some did not,
    is biased low by exactly the slow ones that are missing."""
    lat = [1.0] * 40
    lat[5] = None
    first, _ = trajectory(_schedule(2), lat, until=20.0, bin_seconds=10.0)
    assert first.status == "censored" and first.p50 is None and first.unfinished == 1


def test_a_bin_below_the_sample_floor_is_thin():
    first, _ = trajectory(_schedule(2)[:19] + (15.0,), [1.0] * 20, until=20.0, bin_seconds=10.0)
    assert first.status == "thin" and first.p50 is None


def test_an_empty_bin_is_empty():
    bins = trajectory([15.0] * 20, [1.0] * 20, until=20.0, bin_seconds=10.0)
    assert bins[0].status == "empty"


def test_an_arrival_at_the_window_edge_lands_in_the_last_bin():
    bins = trajectory([20.0], [1.0], until=20.0, bin_seconds=10.0)
    assert bins[-1].requests == 1


def test_the_bin_width_has_no_default():
    """Each artifact pre-registers its own. A default here would let one
    artifact silently run on another's."""
    with pytest.raises(TypeError):
        trajectory([1.0], [1.0], until=20.0)


# ---- band -------------------------------------------------------------------

def test_the_band_is_the_spread_of_the_repeats():
    b = band([_trajectory(1.0), _trajectory(1.2), _trajectory(1.1)], min_repeats=3)
    assert all(x.status == "ok" for x in b)
    assert (b[0].lo, b[0].hi) == pytest.approx((1.0, 1.2))


def test_fewer_repeats_than_required_is_refused():
    with pytest.raises(ValueError, match="at least 3"):
        band([_trajectory(1.0), _trajectory(1.1)], min_repeats=3)


def test_a_band_of_one_run_is_refused_whatever_the_caller_asks_for():
    """One run has zero spread, so the band would hold a model to that run's
    noise exactly."""
    with pytest.raises(ValueError, match="at least two"):
        band([_trajectory(1.0)], min_repeats=1)


def test_repeats_binned_differently_are_refused():
    with pytest.raises(ValueError, match="edges"):
        band([_trajectory(1.0), _trajectory(1.0, bins=5), _trajectory(1.0)], min_repeats=3)


def test_a_bin_the_system_itself_disagrees_about_is_unstable():
    lat = [1.0] * 120
    lat[3] = None
    b = band([_trajectory(1.0), _trajectory(1.1), _trajectory(lat)], min_repeats=3)
    assert b[0].status == "unstable"


# ---- compare ----------------------------------------------------------------

def test_every_bin_inside_the_band_passes():
    v = compare(_pred([1.1] * 6), _band(6), min_compared_bins=MIN_COMPARED)
    assert v.outcome == "passed" and v.compared == 6 and v.max_miss_seconds == 0.0


def test_a_miss_is_reported_with_its_magnitude():
    v = compare(_pred([1.1] * 5 + [1.5]), _band(6), min_compared_bins=MIN_COMPARED)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.3)
    assert v.bins[-1].verdict == "outside"


def test_reality_backlogged_while_the_model_kept_up_is_a_miss():
    """The flattering direction: the model says the fleet coped and reality
    did not. Excluding the bin because reality is censored would pass exactly
    the failure the gate exists to catch."""
    b = _band(5) + [BandBin(50.0, 60.0, None, None, "censored")]
    v = compare(_pred([1.1] * 6), b, min_compared_bins=MIN_COMPARED)
    assert v.outcome == "failed"
    assert v.bins[-1].verdict == "censoring_disagreement"
    assert v.max_miss_seconds == float("inf")


def test_both_backlogged_in_the_same_bin_agree():
    pred = _pred([1.1] * 5) + [Bin(50.0, 60.0, 20, 15, 5, None, "censored")]
    b = _band(5) + [BandBin(50.0, 60.0, None, None, "censored")]
    assert compare(pred, b, min_compared_bins=MIN_COMPARED).outcome == "passed"


def test_too_few_comparable_bins_is_not_evaluable_rather_than_a_pass():
    """Zero misses over too few compared bins is not agreement."""
    b = _band(MIN_COMPARED - 1) + [
        BandBin((MIN_COMPARED - 1) * 10.0, MIN_COMPARED * 10.0, None, None, "unstable")
    ]
    v = compare(_pred([1.1] * MIN_COMPARED), b, min_compared_bins=MIN_COMPARED)
    assert v.outcome == "not_evaluable"


def test_a_gate_that_requires_no_evidence_is_refused():
    with pytest.raises(ValueError, match="min_compared_bins"):
        compare(_pred([1.1] * 6), _band(6), min_compared_bins=0)


def test_mismatched_bin_edges_are_refused():
    with pytest.raises(ValueError, match="edges"):
        compare(_pred([1.1] * 6), _band(5), min_compared_bins=MIN_COMPARED)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation_band.py -q`
Expected: `ModuleNotFoundError: No module named 'autoscale.validation_band'`.

- [ ] **Step 3: Write the shared arithmetic**

Create `autoscale/validation_band.py`:

```python
"""Replay-validation arithmetic: latency trajectories, a tolerance band from
real repeats, and a three-state verdict. Artifact-agnostic, and free of
artifact 1.

It knows nothing about how a prediction was produced or how a real run was
driven -- callers hand it arrival times and latencies. And it imports nothing
that reaches `coldstart`: artifact 4's placement simulator imports it across a
transitive boundary against artifact 1's package, and gets the band and verdict
without artifact 2's even-balancing replay. `autoscale.validation` is artifact
2's gate built on top: its pre-registered constants, its run record, and the
replay into `run_fixed_capacity`. tests/test_validation_band.py checks the
boundary in a fresh interpreter.

No pre-registered value lives here. Bin width, required repeats and the minimum
number of comparable bins are required keywords, because each artifact
pre-registers its own and a default would let one silently inherit another's.

Three decisions, each with its rejected alternative:

- **The per-bin statistic is the p50, not the p99.** A 10 s bin holds a few
  hundred requests at the rates these artifacts drive, and the p99's sample
  floor is 500 (`autoscale.stats.MIN_SAMPLES`). A p99 trajectory would be all
  "thin".
- **A bin with any unfinished request is censored**, never summarised. The
  median of the requests that finished is biased low by exactly the slow ones
  missing. A censored bin is compared by WHETHER both sides backlogged: reality
  backlogged and the model did not is a miss -- the flattering one -- not a bin
  excluded for lack of a number.
- **The verdict has three states.** Zero misses over too few compared bins is
  not agreement, so fewer than `min_compared_bins` comparable bins is
  "not_evaluable", as `frontier.h3_verdict` treats a gap it cannot assess.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.stats import MIN_SAMPLES, percentiles

__all__ = ["BandBin", "Bin", "BinVerdict", "Validation", "band", "compare", "trajectory"]


@dataclass(frozen=True)
class Bin:
    start: float
    end: float
    requests: int
    completed: int
    unfinished: int
    p50: float | None
    status: str  # "ok" | "censored" | "thin" | "empty"


@dataclass(frozen=True)
class BandBin:
    start: float
    end: float
    lo: float | None
    hi: float | None
    status: str  # "ok" | "censored" | "unstable" | "insufficient"


@dataclass(frozen=True)
class BinVerdict:
    start: float
    end: float
    verdict: str
    miss_seconds: float


@dataclass(frozen=True)
class Validation:
    bins: tuple[BinVerdict, ...]
    compared: int
    agreeing: int
    outcome: str  # "passed" | "failed" | "not_evaluable"
    detail: str
    max_miss_seconds: float


def trajectory(arrivals, latencies, *, until: float, bin_seconds: float) -> list[Bin]:
    """Per-bin p50 of latency, keyed by the arrival times the caller passes,
    over [0, until). `latencies[i]` is None for a request that had not
    completed when the window closed."""
    arrivals, latencies = list(arrivals), list(latencies)
    if len(arrivals) != len(latencies):
        raise ValueError("arrivals and latencies must be the same length")
    if not math.isfinite(bin_seconds) or bin_seconds <= 0:
        raise ValueError(f"bin_seconds must be finite and positive, got {bin_seconds!r}")
    if not math.isfinite(until) or until <= 0:
        raise ValueError(f"until must be finite and positive, got {until!r}")
    n_bins = math.ceil(until / bin_seconds)
    done: list[list[float]] = [[] for _ in range(n_bins)]
    open_: list[int] = [0] * n_bins
    for t, lat in zip(arrivals, latencies, strict=True):
        # An arrival exactly at `until` belongs to the last bin, not to a bin
        # past the window that nothing else would ever report.
        i = min(int(t // bin_seconds), n_bins - 1)
        if lat is None:
            open_[i] += 1
        else:
            done[i].append(lat)
    out = []
    for i in range(n_bins):
        completed, unfinished = len(done[i]), open_[i]
        start, end = i * bin_seconds, min((i + 1) * bin_seconds, until)
        if completed + unfinished == 0:
            status, p50 = "empty", None
        elif unfinished:
            status, p50 = "censored", None
        elif completed < MIN_SAMPLES["p50"]:
            status, p50 = "thin", None
        else:
            status, p50 = "ok", percentiles(done[i], want=("p50",))["p50"]
        out.append(Bin(start, end, completed + unfinished, completed, unfinished, p50, status))
    return out


def band(trajectories: Sequence[Sequence[Bin]], *, min_repeats: int) -> list[BandBin]:
    """Per bin, the min and max p50 across real repeats of ONE schedule.

    Whether the repeats really replayed one schedule is the caller's to check
    -- it is a property of how the runs were driven, which this module does
    not see. What it does check: enough repeats, and identical binning.
    """
    if min_repeats < 2:
        raise ValueError(
            f"min_repeats={min_repeats}; a band needs at least two runs, because "
            "one run has zero spread and would hold a model to that run's noise"
        )
    runs = [list(t) for t in trajectories]
    if len(runs) < min_repeats:
        raise ValueError(
            f"{len(runs)} repeats; the band needs at least {min_repeats}. Fewer makes "
            "it the spread of too few numbers to say anything about reproducibility"
        )
    edges = [(b.start, b.end) for b in runs[0]]
    if any([(b.start, b.end) for b in run] != edges for run in runs[1:]):
        raise ValueError("repeats were binned differently; their bin edges disagree")
    out = []
    for column in zip(*runs, strict=True):
        statuses = {b.status for b in column}
        start, end = column[0].start, column[0].end
        if statuses == {"ok"}:
            values = [b.p50 for b in column]
            out.append(BandBin(start, end, min(values), max(values), "ok"))
        elif statuses == {"censored"}:
            out.append(BandBin(start, end, None, None, "censored"))
        elif "censored" in statuses:
            # The real system backlogged on some repeats and not others: it
            # disagrees with itself about whether it kept up, so there is no
            # band a model could be held to.
            out.append(BandBin(start, end, None, None, "unstable"))
        else:
            out.append(BandBin(start, end, None, None, "insufficient"))
    return out


def compare(predicted: Sequence[Bin], band_bins: Sequence[BandBin], *,
            min_compared_bins: int) -> Validation:
    if min_compared_bins < 1:
        raise ValueError(
            f"min_compared_bins={min_compared_bins}; a gate that requires no "
            "comparable bins passes on no evidence at all"
        )
    predicted, band_bins = list(predicted), list(band_bins)
    if len(predicted) != len(band_bins) or any(
        (p.start, p.end) != (b.start, b.end) for p, b in zip(predicted, band_bins, strict=False)
    ):
        raise ValueError("predicted and band bin edges differ; they were binned differently")
    verdicts = []
    for p, b in zip(predicted, band_bins, strict=True):
        if b.status in ("unstable", "insufficient"):
            verdicts.append(BinVerdict(b.start, b.end, f"excluded_{b.status}", 0.0))
        elif b.status == "censored" or p.status == "censored":
            if b.status == p.status == "censored":
                verdicts.append(BinVerdict(b.start, b.end, "agree_censored", 0.0))
            else:
                # One side kept up and the other did not. A censored latency
                # is only bounded below, so the miss has no finite magnitude
                # and is reported as unbounded rather than as zero.
                verdicts.append(BinVerdict(b.start, b.end, "censoring_disagreement", math.inf))
        elif p.status != "ok":
            verdicts.append(BinVerdict(b.start, b.end, "excluded_insufficient", 0.0))
        elif b.lo <= p.p50 <= b.hi:
            verdicts.append(BinVerdict(b.start, b.end, "inside", 0.0))
        else:
            miss = b.lo - p.p50 if p.p50 < b.lo else p.p50 - b.hi
            verdicts.append(BinVerdict(b.start, b.end, "outside", miss))

    judged = [v for v in verdicts if not v.verdict.startswith("excluded")]
    agreeing = sum(1 for v in judged if v.verdict in ("inside", "agree_censored"))
    max_miss = max((v.miss_seconds for v in judged), default=0.0)
    if len(judged) < min_compared_bins:
        outcome = "not_evaluable"
        detail = (f"{len(judged)} comparable bins, below the {min_compared_bins} required; "
                  "zero misses over too few bins is not agreement")
    elif agreeing == len(judged):
        outcome, detail = "passed", f"all {len(judged)} comparable bins agree"
    else:
        outcome = "failed"
        detail = (f"{len(judged) - agreeing} of {len(judged)} bins disagree; "
                  f"largest miss {max_miss:.3g} s")
    return Validation(tuple(verdicts), len(judged), agreeing, outcome, detail, max_miss)
```

- [ ] **Step 4: Run the shared tests, and prove the boundary test bites**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation_band.py -q && .venv/bin/ruff check autoscale/validation_band.py tests/test_validation_band.py`
Expected: all pass, `All checks passed!`.

Then add `import autoscale.sim  # noqa: F401` as the last import in `autoscale/validation_band.py` and rerun `-k does_not_load_artifact_one`. Expected: **FAIL**, naming the `coldstart` modules it loads. Remove the line and rerun: pass. A boundary guard never seen failing is not known to guard anything.

- [ ] **Step 5: Write the failing tests for artifact 2's gate**

Create `tests/test_validation.py`:

```python
"""Artifact 2's gate: its run record, the replay into the simulator, and its
pre-registered constants. The band and verdict arithmetic is tested in
tests/test_validation_band.py."""

import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.validation import RealRun, predicted_trajectory, tolerance_band, validate


# 20 requests per 10 s bin, spaced 0.5 s: the p50 sample floor exactly, and
# sparse enough that one placeholder replica serves each alone at the
# concurrency-1 latency of 0.30 s.
def _schedule(bins):
    return tuple(i * 0.5 for i in range(20 * bins))


def _run(latency, bins=6, host="w1"):
    schedule = _schedule(bins)
    lat = latency if isinstance(latency, list) else [latency] * len(schedule)
    return RealRun(schedule=schedule, sent=schedule, latencies=tuple(lat),
                   replicas=1, until=10.0 * bins, host_ids=(host,))


def test_the_prediction_replays_the_schedule_through_the_simulator():
    bins = predicted_trajectory(_schedule(2), replicas=1, curve=SERVICE_CURVE_PLACEHOLDER,
                                until=20.0, bin_seconds=10.0)
    assert [b.p50 for b in bins] == pytest.approx([0.30, 0.30])


def test_the_band_comes_from_the_real_repeats():
    band = tolerance_band([_run(1.0), _run(1.2), _run(1.1)], bin_seconds=10.0)
    assert (band[0].lo, band[0].hi) == pytest.approx((1.0, 1.2))


def test_fewer_than_three_repeats_is_refused():
    with pytest.raises(ValueError, match="3"):
        tolerance_band([_run(1.0), _run(1.1)], bin_seconds=10.0)


def test_repeats_of_different_schedules_are_refused():
    """The band is the system's own reproducibility on ONE trace. Repeats of
    different traces fold traffic variance into it and widen it for free."""
    shifted = _schedule(6)[1:] + (59.9,)
    other = RealRun(schedule=shifted, sent=shifted, latencies=(1.0,) * 120,
                    replicas=1, until=60.0, host_ids=("w1",))
    with pytest.raises(ValueError, match="schedule"):
        tolerance_band([_run(1.0), _run(1.1), other], bin_seconds=10.0)


def test_a_run_that_did_not_hold_the_schedule_is_refused():
    schedule = _schedule(6)
    drifted = RealRun(schedule=schedule, sent=tuple(t + 2.0 for t in schedule),
                      latencies=(1.0,) * 120, replicas=1, until=60.0, host_ids=("w1",))
    with pytest.raises(ValueError, match="jitter"):
        tolerance_band([_run(1.0), _run(1.1), drifted], bin_seconds=10.0)


def test_real_runs_that_bracket_the_model_pass():
    runs = [_run(0.29), _run(0.30), _run(0.31)]
    assert validate(runs, SERVICE_CURVE_PLACEHOLDER, bin_seconds=10.0).outcome == "passed"


def test_real_runs_far_from_the_model_fail_with_the_distance():
    v = validate([_run(1.0), _run(1.1), _run(1.2)], SERVICE_CURVE_PLACEHOLDER, bin_seconds=10.0)
    assert v.outcome == "failed"
    assert v.max_miss_seconds == pytest.approx(0.70)


@pytest.mark.parametrize("override, match", [
    ({"sent": (0.0,)}, "length"),
    ({"host_ids": ()}, "host"),
    ({"latencies": (-1.0,) + (1.0,) * 119}, "latenc"),
    ({"replicas": True}, "replicas"),
    ({"until": 5.0}, "until"),
])
def test_a_malformed_real_run_is_refused(override, match):
    base = {"schedule": _schedule(6), "sent": _schedule(6), "latencies": (1.0,) * 120,
            "replicas": 1, "until": 60.0, "host_ids": ("w1",)}
    with pytest.raises(ValueError, match=match):
        RealRun(**{**base, **override})
```

- [ ] **Step 6: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation.py -q`
Expected: `ModuleNotFoundError: No module named 'autoscale.validation'`.

- [ ] **Step 7: Write artifact 2's gate**

Create `autoscale/validation.py`:

```python
"""Artifact 2's open-loop validation gate (spec §10), GPU-free.

Pin capacity, drive a real transient load from a fixed arrival SCHEDULE,
replay that same schedule into `run_fixed_capacity`, and compare the predicted
latency trajectory against what happened. Three real repeats of the schedule
set the tolerance band -- "a model cannot be required to be more reproducible
than the system it models". The load driver is plan 2b's.

This module holds what is artifact 2's: the pre-registered constants, the
`RealRun` record, the checks that the repeats really replayed one schedule, and
the replay into the simulator. The band and verdict arithmetic is
`autoscale.validation_band`, kept separate because `autoscale.sim` -- imported
here -- pulls in `coldstart`, and artifact 4 needs that arithmetic without it.

Bins are keyed by SCHEDULED arrival time, not observed send time: every repeat
and the prediction then place exactly the same requests in the same bins, and
driver jitter cannot move a request across a boundary and manufacture a
difference no system produced. Jitter is bounded instead, and a run exceeding
the bound is refused -- it replayed a different trace, so it tests nothing.

The constants are fixed by docs/experiment-a2.md ("Validation gate — pass
rule"). Changing one after the first real validation run is an amendment.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.validation_band import BandBin, Bin, Validation, band, compare, trajectory

__all__ = [
    "BIN_SECONDS",
    "MAX_SEND_JITTER_SECONDS",
    "MIN_COMPARED_BINS",
    "MIN_REPEATS",
    "RealRun",
    "predicted_trajectory",
    "tolerance_band",
    "validate",
]

MIN_REPEATS = 3  # spec §10: "Three real repeats; their spread sets the tolerance band"
BIN_SECONDS = 10.0
MAX_SEND_JITTER_SECONDS = 0.5
MIN_COMPARED_BINS = 5


@dataclass(frozen=True)
class RealRun:
    """One real open-loop run at pinned capacity, as the load driver records it.

    `latencies[i]` is None when request i had not completed when the window
    closed. `host_ids` is the platform identity of every replica that served
    (spec §10's new requirement): artifact 1 saw one first-touch cold start at
    2266.6 s against a 39-96 s norm, and a host-novelty event inside a
    validation run is indistinguishable from a simulator bug unless the host is
    on record.
    """

    schedule: tuple[float, ...]
    sent: tuple[float, ...]
    latencies: tuple[float | None, ...]
    replicas: int
    until: float
    host_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("schedule", "sent", "latencies", "host_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        n = len(self.schedule)
        if n == 0 or len(self.sent) != n or len(self.latencies) != n:
            raise ValueError(
                f"schedule, sent and latencies must be one entry per request and "
                f"non-empty; got length {n}, {len(self.sent)}, {len(self.latencies)}. "
                "Misaligned lists attribute latencies to the wrong requests"
            )
        if type(self.replicas) is not int or self.replicas < 1:
            raise ValueError(f"replicas must be a positive int, got {self.replicas!r}")
        if not math.isfinite(self.until) or self.until <= 0:
            raise ValueError(f"until must be finite and positive, got {self.until!r}")
        if not self.host_ids or not all(isinstance(h, str) and h for h in self.host_ids):
            raise ValueError(
                "host_ids is empty or holds a blank id; spec §10 requires the host "
                "of every replica, because a host-novelty event is otherwise "
                "indistinguishable from a simulator bug"
            )
        previous = 0.0
        for t in self.schedule:
            if not math.isfinite(t) or t < previous or t > self.until:
                raise ValueError(
                    f"schedule entry {t!r} is not finite, not ascending, or past "
                    f"until={self.until!r}; the simulator would refuse to replay it"
                )
            previous = t
        if not all(math.isfinite(s) for s in self.sent):
            raise ValueError("a send time is not finite")
        for lat in self.latencies:
            if lat is not None and (not math.isfinite(lat) or lat < 0):
                raise ValueError(
                    f"latency {lat!r} is not a finite non-negative duration; use "
                    "None for a request that had not completed"
                )

    def send_jitter(self) -> float:
        return max(abs(s - t) for s, t in zip(self.sent, self.schedule, strict=True))


def predicted_trajectory(schedule, replicas: int, curve: ServiceCurve, until: float,
                         bin_seconds: float = BIN_SECONDS) -> list[Bin]:
    result = run_fixed_capacity(list(schedule), replicas, curve, until)
    pairs = result.completed_requests()
    arrivals = [a for a, _ in pairs] + list(result.unfinished_arrivals)
    latencies = [lat for _, lat in pairs] + [None] * len(result.unfinished_arrivals)
    return trajectory(arrivals, latencies, until=until, bin_seconds=bin_seconds)


def _check_repeats(runs: Sequence[RealRun]) -> None:
    """What only a RealRun can tell: that the repeats replayed ONE schedule, at
    one capacity, faithfully. How many repeats are enough is `band`'s check."""
    if not runs:
        raise ValueError("no real runs; there is nothing to build a band from")
    first = runs[0]
    for run in runs[1:]:
        if (run.schedule, run.replicas, run.until) != (first.schedule, first.replicas, first.until):
            raise ValueError(
                "repeats differ in schedule, replicas or window; the band must be "
                "the system's own spread on ONE trace, and mixing traces folds "
                "traffic variance into it and widens it for free"
            )
    for run in runs:
        if run.send_jitter() > MAX_SEND_JITTER_SECONDS:
            raise ValueError(
                f"send jitter {run.send_jitter():.3f} s exceeds "
                f"{MAX_SEND_JITTER_SECONDS} s; the driver did not replay the "
                "schedule, so the run tested a different trace from the one the "
                "simulator replays"
            )


def tolerance_band(runs: Sequence[RealRun], bin_seconds: float = BIN_SECONDS) -> list[BandBin]:
    _check_repeats(runs)
    return band(
        [trajectory(r.schedule, r.latencies, until=r.until, bin_seconds=bin_seconds)
         for r in runs],
        min_repeats=MIN_REPEATS,
    )


def validate(runs: Sequence[RealRun], curve: ServiceCurve,
             bin_seconds: float = BIN_SECONDS) -> Validation:
    tolerance = tolerance_band(runs, bin_seconds)
    first = runs[0]
    predicted = predicted_trajectory(first.schedule, first.replicas, curve, first.until,
                                     bin_seconds)
    return compare(predicted, tolerance, min_compared_bins=MIN_COMPARED_BINS)
```

- [ ] **Step 8: Run both test files and the boundary guards**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation_band.py tests/test_validation.py tests/test_autoscale_boundary.py -q && .venv/bin/ruff check autoscale/validation_band.py autoscale/validation.py tests/test_validation_band.py tests/test_validation.py`
Expected: all pass, `All checks passed!`.

- [ ] **Step 9: Commit**

```bash
git add autoscale/validation_band.py autoscale/validation.py tests/test_validation_band.py tests/test_validation.py
git commit -m "feat: the validation gate's arithmetic, in a module artifact 4 can import without artifact 1"
```

---

## Task 9: Pre-register the validation gate's pass rule — **STOP for sign-off**

Spec §10 fixes three repeats and "their spread sets the tolerance band", and requires misses to be reported with magnitude. It does not fix what counts as passing, the bin width, the jitter bound or the minimum evidence. Those are four pre-registered quantities, and they must be committed **before any real validation run exists** — the same discipline as the traffic model.

**Files:**
- Modify: `docs/experiment-a2.md` (new section before `## Stopping rule`)

- [ ] **Step 1: Present the proposed rule to the human partner and wait**

Show the text in Step 2 and ask for explicit approval or changes. Do not commit it on your own authority: it decides whether the artifact's credibility claim holds.

- [ ] **Step 2: On approval, insert the section**

Insert immediately before `## Stopping rule` in `docs/experiment-a2.md`:

```markdown
## Validation gate — pass rule

Fixed 2026-09-26, before any real validation run exists. Implemented in
`autoscale/validation.py`; changing any value below after the first real run is
an amendment.

- **Repeats:** 3 real runs of **one** fixed arrival schedule at pinned capacity.
  Repeats of different schedules are refused: the band must be the system's own
  spread on one trace.
- **Trajectory:** latency p50 per **10 s** bin, keyed by *scheduled* arrival
  time. p50 rather than p99 because a 10 s bin holds a few hundred requests and
  the p99 floor is 500.
- **Driver fidelity:** a run whose send times drift more than **0.5 s** from
  the schedule is refused; it replayed a different trace.
- **Band:** per bin, the min and max of the three repeats' p50.
- **Censoring:** a bin with any unfinished request is censored. Model and
  reality both censored in a bin is agreement; one censored and the other not
  is a **miss of unbounded magnitude**. A bin censored on some repeats and not
  others is excluded as unstable and reported.
- **Pass:** every comparable bin agrees, over **at least 5** comparable bins.
  Fewer is **not evaluable** — never a pass.
- **Disclosure:** every miss is published with its magnitude, as spec §10
  already requires.
```

- [ ] **Step 3: Pin the constants to the document**

Append to `tests/test_validation.py`:

```python
def test_the_constants_are_the_ones_the_preregistration_states():
    from pathlib import Path

    from autoscale import validation

    prereg = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a2.md").read_text()
    assert "## Validation gate — pass rule" in prereg
    assert validation.MIN_REPEATS == 3 and "3 real runs" in prereg
    assert validation.BIN_SECONDS == 10.0 and "**10 s** bin" in prereg
    assert validation.MAX_SEND_JITTER_SECONDS == 0.5 and "**0.5 s**" in prereg
    assert validation.MIN_COMPARED_BINS == 5 and "**at least 5**" in prereg
```

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_validation.py -q`
Expected: pass. If the partner changed a value in Step 1, change the constant in `autoscale/validation.py` and this test together.

- [ ] **Step 4: Commit**

```bash
git add docs/experiment-a2.md tests/test_validation.py
git commit -m "prereg: the validation gate's pass rule, fixed before any real run exists"
```

---

## Task 10: Figure 4 — the service curve with utilization censoring visible

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. Artist-presence assertions are not completion evidence here; the censored region must be shown to have real pixel extent, and the rendered chart must be looked at at both widths.

**Files:**
- Modify: `autoscale/figures.py` (new public `service_curve`, `censoring_onset`)
- Modify: `scripts/a2_render_figures.py` (render figure 4)
- Test: `tests/test_a2_figures.py`

- [ ] **Step 1: Write the failing tests**

Fix the layout harness first. `_rendered` pairs tick locations with tick labels by
zipping two lists that only line up while every label is visible; figure 4's shared
x-axis hides the upper panels' labels, and the strict zip raises. Replace, inside
`_rendered`:

```python
            artists += [
                label
                for loc, label in zip(
                    matplotlib_axis.get_majorticklocs(),
                    matplotlib_axis.get_majorticklabels(),
                    strict=True,
                )
                if lo <= loc <= hi
            ]
```

with

```python
            # Each tick paired with ITS OWN label. Zipping get_majorticklocs()
            # against get_majorticklabels() only lines up while every label is
            # visible: shared axes hide the upper panels' labels, the label list
            # comes back shorter, and the pairing is off by however many were
            # hidden. Hidden labels are dropped by the get_visible() filter below.
            artists += [
                tick.label1
                for tick in matplotlib_axis.get_major_ticks()
                if lo <= tick.get_loc() <= hi
            ]
```

Then, in `tests/test_a2_figures.py`, change the import line

```python
from autoscale.figures import SIGNAL_ORDER, convergence, frontiers
```

to

```python
from autoscale.figures import (
    SIGNAL_ORDER,
    UTILIZATION_CENSOR_AT,
    censoring_onset,
    convergence,
    frontiers,
    service_curve,
)
```

and, directly after the existing `from autoscale.frontier import PolicyPoint` line, add
`from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve` (ruff's import
order puts `service` after `frontier`).

Add a realistic fixture curve beside the other module-level fixtures:

```python
# Ten levels, wide tick labels, the knee mid-range: what a measured sweep looks
# like, rather than the placeholder's seven tidy powers of two.
WIDE_CURVE = ServiceCurve(
    points=[(c, 0.28 + 0.0009 * c * c, min(560.0, 55.0 * c), min(1.0, 0.16 * c ** 0.55))
            for c in (1, 2, 4, 6, 8, 12, 16, 24, 32, 48)],
    measured=True,
)
```

Extend `_draw` so the shared layout tests cover figure 4 — add, immediately before the line `data = ALL_THREE if case == "minimal" else WIDE_A`:

```python
    if figure == "service_curve":
        curve = SERVICE_CURVE_PLACEHOLDER if case == "minimal" else WIDE_CURVE
        return service_curve(curve, path=tmp_path / "s.png", return_figure=True)
```

Add `"service_curve"` to the `figure` parametrize list of **both** `test_every_text_artist_clears_the_phone_legibility_floor` and `test_no_text_runs_off_the_canvas`, so each reads:

```python
@pytest.mark.parametrize("figure", ["convergence", "frontiers", "service_curve"])
```

Then append:

```python
def test_censoring_starts_where_utilization_crosses_the_top_of_its_grid():
    """Placeholder: utilization 0.85 at 8, 0.96 at 16. Linear interpolation --
    the same ServiceCurve uses -- puts 0.95 at 8 + 0.10/0.11 x 8."""
    assert UTILIZATION_CENSOR_AT == 0.95
    assert censoring_onset(SERVICE_CURVE_PLACEHOLDER) == pytest.approx(8 + 0.10 / 0.11 * 8)


def test_no_censoring_when_utilization_never_reaches_the_threshold(tmp_path):
    low = ServiceCurve(points=[(1, 0.3, 50.0, 0.2), (8, 0.4, 300.0, 0.6)], measured=False)
    assert censoring_onset(low) is None
    fig = service_curve(low, path=tmp_path / "s.png", return_figure=True)
    assert not [p for ax in fig.axes for p in ax.patches if p.get_gid() == "censored"]
    assert "never reached" in " ".join(_texts(fig))


def test_the_censored_region_is_painted_on_every_panel(tmp_path):
    """Not "a patch exists" -- a zero-width span exists and paints nothing,
    which is the defect a presence check would pass. Real pixel width."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    spans = [p for ax in fig.axes for p in ax.patches if p.get_gid() == "censored"]
    assert len(spans) == 3
    assert all(p.get_window_extent(renderer).width > 20 for p in spans)


def test_an_unmeasured_curve_says_so_on_the_chart(tmp_path):
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    assert "NOT MEASURED" in _texts(fig)


def test_a_measured_curve_is_labelled_measured(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    words = _texts(fig)
    assert "MEASURED" in words and "NOT MEASURED" not in words


def test_n_is_stated_on_the_service_curve(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    assert "n=10" in " ".join(_texts(fig))


def test_every_service_curve_axis_starts_at_zero(tmp_path):
    fig = service_curve(WIDE_CURVE, path=tmp_path / "s.png", return_figure=True)
    for axis in fig.axes:
        assert axis.get_ylim()[0] == 0 and axis.get_xlim()[0] == 0


@pytest.mark.parametrize("curve", [SERVICE_CURVE_PLACEHOLDER, WIDE_CURVE], ids=["placeholder", "measured"])
def test_the_figure_4_banner_holds_its_word_and_clears_the_panels(curve, tmp_path):
    """The first draft reused `_banner`, which sizes its strip as a fraction of
    ONE panel's height. On three short stacked panels the strip came out
    shorter than the word inside it and the subtitle landed on the top panel --
    while every legibility and off-canvas test in this file passed."""
    fig = service_curve(curve, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    [strip] = fig.patches
    strip_box = strip.get_window_extent(renderer)
    word = next(t for t in fig.texts if t.get_text() in ("MEASURED", "NOT MEASURED"))
    word_box = word.get_window_extent(renderer)
    assert strip_box.y0 <= word_box.y0 and word_box.y1 <= strip_box.y1, (
        f"banner word spans y {word_box.y0:.0f}..{word_box.y1:.0f}, outside its "
        f"strip at {strip_box.y0:.0f}..{strip_box.y1:.0f}"
    )
    top_panel = fig.axes[0].get_window_extent(renderer)
    for text in fig.texts:
        assert text.get_window_extent(renderer).y0 >= top_panel.y1, (
            f"{text.get_text()!r} overlaps the top panel"
        )


def test_each_y_label_fits_the_height_of_its_own_panel(tmp_path):
    """Three short panels leave little height for a rotated label. The first
    draft's single-line labels ran past their panels and into each other.
    Checked against each label's OWN panel rather than against its neighbours:
    a neighbour-overlap check misses one long label beside two short ones."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for axis in fig.axes:
        panel = axis.get_window_extent(renderer)
        label = axis.yaxis.label.get_window_extent(renderer)
        assert panel.y0 - 1 <= label.y0 and label.y1 <= panel.y1 + 1, (
            f"{axis.yaxis.label.get_text()!r} spans y {label.y0:.0f}..{label.y1:.0f}, "
            f"past its panel at {panel.y0:.0f}..{panel.y1:.0f}"
        )


def test_the_censored_band_reaches_the_right_edge(tmp_path):
    """A band that stops at the last measured point reads as censoring that
    ENDS there."""
    fig = service_curve(SERVICE_CURVE_PLACEHOLDER, path=tmp_path / "s.png", return_figure=True)
    for axis in fig.axes:
        [span] = [p for p in axis.patches if p.get_gid() == "censored"]
        x1 = span.get_x() + span.get_width()
        assert x1 == pytest.approx(axis.get_xlim()[1])
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -q`
Expected: `ImportError: cannot import name 'UTILIZATION_CENSOR_AT'`.

- [ ] **Step 3: Implement**

In `autoscale/figures.py`, add `from itertools import pairwise` directly above `from pathlib import Path`, and directly after `from autoscale.stats import MIN_BOOTSTRAP_SAMPLES` add:

```python
from autoscale.sweep import THRESHOLDS
```

add to `__all__`: `"UTILIZATION_CENSOR_AT"`, `"censoring_onset"`, `"service_curve"`, and add near the other constants:

```python
# The top of utilization's pre-registered scale-up grid. Above the load where
# utilization reaches it, utilization exceeds EVERY threshold the utilization
# policy can be set to, so more load is invisible to that policy -- H2's
# censoring mechanism, read off the grid rather than chosen for the chart.
UTILIZATION_CENSOR_AT = max(THRESHOLDS["utilization"][0])
CENSOR_COLOR = "#c0392b"
CURVE_COLOR = "#333333"
```

and at the end of the module:

```python
def censoring_onset(curve, threshold: float = UTILIZATION_CENSOR_AT) -> float | None:
    """The lowest concurrency at which utilization reaches `threshold`.

    Linear interpolation between measured points, the same interpolation
    `ServiceCurve` itself uses, so the shaded region begins where the model
    the simulator runs on says it does. None if utilization never reaches the
    threshold in the measured range.
    """
    points = [(c, u) for c, _, _, u in curve.points]
    if points[0][1] >= threshold:
        return float(points[0][0])
    for (c0, u0), (c1, u1) in pairwise(points):
        if u0 < threshold <= u1:
            return c0 + (threshold - u0) / (u1 - u0) * (c1 - c0)
    return None


def _figure_banner(fig, left: float, right: float, word: str, subtitle: str, color: str) -> None:
    """The measured/modeled strip, in FIGURE coordinates, for a stacked figure.

    `_banner` sizes its strip as a fraction of one panel's height, which suits
    figures 1 and 2's tall panels and fails on figure 4's three short ones: the
    strip comes out shorter than the word inside it and the subtitle lands on
    the top panel. It is not changed to fit, because that would move figure
    1's pixels; a stacked figure has one header for all its panels, so it is
    drawn once, against the figure, spanning the panels' shared width.
    """
    fig.patches.append(
        Rectangle((left, 0.935), right - left, 0.05, transform=fig.transFigure,
                  facecolor=color, edgecolor="none", zorder=5)
    )
    fig.text((left + right) / 2, 0.96, word, ha="center", va="center",
             fontsize=_pt(PX_BANNER), fontweight="bold", color="white", zorder=6)
    fig.text((left + right) / 2, 0.928, subtitle, ha="center", va="top",
             fontsize=_pt(PX_SUBTITLE), color=color)


def service_curve(curve, path, return_figure=False):
    """Figure 4. Latency, throughput and GPU utilization against concurrency,
    with the region where utilization is censored shaded on all three.

    Three stacked panels sharing the concurrency axis rather than one panel
    with three y-axes: the quantities have unrelated units, and a twin-axis
    chart invites reading one curve against another's scale. The shading is on
    every panel because the point of the figure is the COINCIDENCE -- latency
    still climbing while utilization has flattened -- and a reader has to see
    both sides of the boundary in one glance.

    No interval band yet: `ServiceCurve` carries one value per level. Plan 2b
    adds per-level dispersion when the sweep format is fixed.
    """
    left, right = 0.13, 0.985
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))
    fig.subplots_adjust(left=left, right=right, top=0.86, bottom=0.20, hspace=0.22)
    concurrency = [c for c, _, _, _ in curve.points]
    # A little past the last point, and the shading runs to the same edge: a
    # band that stopped at the last measured point would read as censoring
    # that ENDS there, and an axis ending exactly on it would clip the marker.
    x_right = max(concurrency) * 1.04
    onset = censoring_onset(curve)
    background = MEASURED_BG if curve.measured else MODELED_BG
    for axis, index, label in (
        (axes[0], 1, "latency\n(s)"),
        (axes[1], 2, "throughput\n(tok/s)"),
        (axes[2], 3, "GPU\nutilization"),
    ):
        axis.plot(concurrency, [p[index] for p in curve.points], "o-",
                  markersize=5, linewidth=2, color=CURVE_COLOR)
        _tidy(axis, "", label, background)
        axis.set_xlim(0, x_right)
        if onset is not None:
            axis.axvspan(onset, x_right, color=CENSOR_COLOR, alpha=BAND_ALPHA,
                         linewidth=0, gid="censored")
    axes[2].set_ylim(0, 1.05)
    axes[2].axhline(UTILIZATION_CENSOR_AT, color=CENSOR_COLOR, linewidth=1, linestyle=":")
    axes[2].set_xlabel("concurrency per replica", fontsize=_pt(PX_AXIS_LABEL))
    if curve.measured:
        _figure_banner(fig, left, right, "MEASURED", "one replica, concurrency swept",
                       MEASURED_BANNER)
    else:
        _figure_banner(fig, left, right, "NOT MEASURED", "placeholder curve: invented points",
                       MODELED_BANNER)
    # Two lines, each short: at the phone floor a note line wider than ~75
    # characters runs past 375 px, and the off-canvas test fails on it.
    shading = (
        f"shaded: utilization ≥ {UTILIZATION_CENSOR_AT:g} (from {onset:.3g}), "
        "above every utilization threshold"
        if onset is not None
        else f"utilization ≥ {UTILIZATION_CENSOR_AT:g} never reached in the measured range"
    )
    _note(axes[2], f"n={len(curve.points)} concurrency levels\n{shading}", y=-0.42)
    return _finish(fig, path, return_figure)
```

- [ ] **Step 4: Run the figure tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -q`
Expected: all pass. If the legibility or off-canvas tests fail for `service_curve`, adjust **only** `left`/`right`, the `subplots_adjust` values and the `_note` `y` offset — never a font size below the `PX_*` constants, which exist to keep text at or above the phone floor.

- [ ] **Step 5: Render figure 4 from the script**

In `scripts/a2_render_figures.py`, add `service_curve` to the `from autoscale.figures import` line, and in `main`, directly after the `if not SERVICE_CURVE_PLACEHOLDER.measured:` warning block, add:

```python
    # Figure 4 needs no sweep -- only the curve -- so it renders first and
    # renders even when a figure guard later refuses to draw the others.
    print(service_curve(SERVICE_CURVE_PLACEHOLDER, out / "service_curve.png"))
```

Run:

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-draft 2>&1 | tail -4
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
im = Image.open("build/a2-figures-draft/service_curve.png")
im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
    "build/a2-figures-draft/service_curve-phone.png")
print("phone variant written")
PY
```

- [ ] **Step 6: LOOK at it, at both widths**

Open `build/a2-figures-draft/service_curve.png` and `service_curve-phone.png` with the Read tool. State in the task report, for each:

- The red shaded band starts near concurrency 15 on **all three** panels and runs to the right edge.
- Latency visibly keeps rising inside the shaded region while utilization is flat near 1.0 — the mechanism the figure exists to show. If the eye cannot see that coincidence at 375 px, the figure has failed its purpose even if every test passes.
- The banner reads **NOT MEASURED** in the modeled blue, not the measured green.
- The `n=7` note is present and not clipped; the dotted 0.95 line is visible on the utilization panel.
- The banner word sits inside its strip and the subtitle clears the top panel; each
  y-axis label fits its own panel; the shading runs to the right edge. A first draft
  of this figure shipped all three defects past every other test in this file --
  the three layout tests above exist because of it, and this look is what found them.
- At 375 px the dotted 0.95 line is faint. Acceptable: the shading carries the
  message. Say so in the report rather than thickening it silently.

- [ ] **Step 7: Commit**

```bash
.venv/bin/ruff check autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
git add autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
git commit -m "feat: figure 4, the service curve with utilization censoring visible"
```

---

## Task 11: Delete the last copies of the derivation — gated on parity

Last code task. Deletion happens only after every **Preserved** row of the Task 1 inventory is re-verified through the replacement.

**Files:**
- Modify: `scripts/a2_render_figures.py` (delete the two shims)
- Modify: `tests/test_a2_end_to_end.py:72-104`, `:400-431`, `:462-470`
- Test: `tests/test_traffic.py` (add the structural guard)

- [ ] **Step 1: Parity gate — every preserved capability, exercised**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
# Inventory rows 1-6: shapes bit-exact through the replacement
cmp build/plan2a-baseline/shapes.json build/plan2a-after/shapes.json && echo "rows 1-6: shapes identical"
# Row 6-7: override path and its warning, and the default path
for f in noise_floor noise_floor_candidate probe_screen; do
  cmp -s build/plan2a-baseline/$f.json build/plan2a-after/$f.json && echo "$f: identical" || echo "$f: DIFFERS"
done
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_gap_noise_floor.py --seeds 1 --reps 1 \
  --baseline-fraction 0.40 --out /dev/null 2>&1 | grep -c "NOT the pre-registered traffic model"
# Rows 8-11: the doc-agreement, ramp, H3-source and RAMP_SECONDS tests
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_traffic.py \
  "tests/test_a2_end_to_end.py::test_the_render_script_evaluates_h3_under_both_shapes" \
  "tests/test_a2_end_to_end.py::test_the_ramp_is_half_the_sustain_as_the_pre_registration_states"
```

Expected: `shapes identical`, three `identical`, a count of `1`, tests pass. **Any failure stops this task.** Nothing is deleted on "it compiles".

- [ ] **Step 2: Write the structural guard (failing)**

Append to `tests/test_traffic.py`:

```python
def test_no_script_constructs_a_spike_shape_itself():
    """The consolidation, made permanent. Four copies of this derivation agreed
    only because a test compared two of them and an amendment was applied by
    hand in each; the next copy would be the fifth. Parses rather than greps,
    so a comment or docstring mentioning SpikeShape is not a violation."""
    import ast

    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "SpikeShape":
                offenders.append(path.name)
            if isinstance(node, ast.FunctionDef) and node.name in (
                "_saturation_rps", "_preregistered_shape"
            ):
                offenders.append(f"{path.name}:{node.name}")
    assert offenders == [], (
        f"{offenders} derive the traffic model locally. Use autoscale.traffic -- "
        "a second copy stops implementing the pre-registered rule the moment "
        "the service curve or an amendment changes one and not the other"
    )
```

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_traffic.py -q -k no_script`
Expected: FAIL naming `a2_render_figures.py:_saturation_rps` and `a2_render_figures.py:_preregistered_shape`.

- [ ] **Step 3: Delete the shims**

In `scripts/a2_render_figures.py`, delete the functions `_saturation_rps` and `_preregistered_shape` entirely, and replace the `autoscale.traffic` import block with:

```python
from autoscale.traffic import (
    RAMP_SECONDS,  # noqa: F401 -- tests/test_a2_end_to_end.py reads render.RAMP_SECONDS
    spike_shape,
)
```

The two fraction constants were re-exported only for the agreement test deleted in Step 4, and `saturation_rps` only for the shim. **Keep** `from autoscale.arrivals import SpikeShape`: `_sweep` annotates its parameter with it, and the structural guard bans *constructing* a `SpikeShape` in a script, not naming the type.

- [ ] **Step 4: Replace the end-to-end test's copy**

In `tests/test_a2_end_to_end.py`:

Delete the two lines

```python
BASELINE_FRACTION_OF_SATURATION = 0.70  # docs/experiment-a2.md, amended 2026-09-17
ADDITIONAL_REPLICAS_AT_PEAK = 0.25  # docs/experiment-a2.md, amended 2026-09-17
```

Replace the whole `_shape` function with:

```python
def _shape(kind: str, ramp: float) -> SpikeShape:
    """The pre-registered spike over the reduced SUSTAIN window.

    This used to be an independent copy of the derivation, because `scripts/`
    is not importable. `autoscale.traffic` is, and one copy is the only kind
    that cannot drift. `ramp` is checked rather than passed: R = D/2 is derived.
    """
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, kind, sustain=SUSTAIN)
    assert shape.ramp == ramp, f"ramp {ramp} is not D/2 = {shape.ramp} for this window"
    return shape
```

and add `from autoscale.traffic import spike_shape` directly after the `from autoscale.sweep import ...` line (ruff's import order).

Delete `test_the_traffic_constants_match_the_render_script_and_the_preregistration` entirely — its render-versus-test half is now structural (one copy), and its document half lives in `tests/test_traffic.py::test_the_constants_are_the_ones_the_preregistration_states`, which also covers `D` and `R`.

In `test_the_ramp_is_half_the_sustain_as_the_pre_registration_states`, replace

```python
    shape = render._preregistered_shape(
        render.SERVICE_CURVE_PLACEHOLDER, kind="ramp", ramp=render.RAMP_SECONDS
    )
```

with

```python
    shape = spike_shape(render.SERVICE_CURVE_PLACEHOLDER, kind="ramp")
```

- [ ] **Step 5: Run everything**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
.venv/bin/ruff check scripts/a2_render_figures.py tests/test_a2_end_to_end.py tests/test_traffic.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q; echo "EXIT=$?"
./scripts/parity_check.sh 2>&1 | tail -3
```

Expected: `All checks passed!`, `EXIT=0`, and `PARITY OK` — artifact 1's published numbers and figures untouched by anything in this plan.

- [ ] **Step 6: Commit**

```bash
git add scripts/a2_render_figures.py tests/test_a2_end_to_end.py tests/test_traffic.py
git commit -m "refactor: delete the last copies of the traffic derivation

Gated on every preserved capability in the plan 2a inventory being
re-verified through autoscale.traffic: shapes bit-exact, both
diagnostics byte-identical, the override warning intact, and the
document-agreement, ramp and H3-source tests passing. A structural test
now fails if any script derives the model locally again."
```

---

## Task 12: Manual visual checkpoint and end-to-end parity

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. Modifies nothing; produces evidence.

- [ ] **Step 1: The full sweep, against the Task 1 baseline**

The strongest parity statement this plan can make: a fresh `--refresh` sweep through the consolidated code reproduces the baseline sweep **byte for byte**. Roughly 30 minutes; run it in the background.

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py \
  --out build/plan2a-after/figures --refresh > build/plan2a-after/render.log 2>&1
cmp build/plan2a-baseline/figures/sweep-cache.json build/plan2a-after/figures/sweep-cache.json \
  && echo "SWEEP: byte-identical"
for f in frontiers convergence; do
  cmp -s build/plan2a-baseline/figures/$f.png build/plan2a-after/figures/$f.png \
    && echo "$f.png: identical" || echo "$f.png: DIFFERS"
done
```

Expected: `SWEEP: byte-identical`, and both existing figures identical — the consolidation moved no pixel of figures 1 and 2.

- [ ] **Step 2: Produce phone variants of all three figures**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
for name in ("frontiers", "convergence", "service_curve"):
    im = Image.open(f"build/plan2a-after/figures/{name}.png")
    im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
        f"build/plan2a-after/figures/{name}-phone.png")
    print(f"{name}: {im.width}x{im.height} -> phone")
PY
```

- [ ] **Step 3: Look at all six images**

Open each with the Read tool — `frontiers.png`, `convergence.png`, `service_curve.png` and their `-phone.png` variants. In the task report, confirm for each: no clipped text, banners correct for the placeholder curve, `n=` stated, and on figure 4 that the censored band and the latency-versus-utilization coincidence are visible at 375 px. Attach all six paths.

- [ ] **Step 4: Final suite, lint, artifact-1 parity**

```bash
cd /Users/oleksiiostapiuk/projects/ai/artifacts
./scripts/parity_check.sh 2>&1 | tail -3
git status --short
```

Expected: `PARITY OK`, and `git status` shows only files other workstreams own, or nothing.

- [ ] **Step 5: Report**

State plainly, with the command output that shows each:

- Recon tooling built and proven offline; **not run** — running it is the operator's spend decision.
- Validation core built; pass rule pre-registered (or the sign-off still pending, if Task 9 stopped).
- Figure 4 rendered and inspected at both widths.
- Traffic model consolidated from four copies to one, with shapes, diagnostics, the full sweep and figures 1–2 all byte-identical to the baseline.
- Open, carried to plan 2b: capacity pinning, the platform-routed load driver, the closed-loop gate, figure 3, and intervals on figure 4.
- Open, in the shared harness plan (scope decision 4): the in-container load generator, the `vllm serve` lifecycle and the single-engine service-curve sweep that measures artifact 2's curve.
- Open, flagged by this plan's inventory: the regime probe's inline iso-cost budget lacks the FP-dust tolerance and completeness guard.
