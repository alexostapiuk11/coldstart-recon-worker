# Artifact 1 Measurement Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the pre-registered ~300-run measurement campaign against the live RunPod endpoint, analyse the real data through the proven pipeline, and publish the artifact.

**Architecture:** The harness plan (`2026-08-17-artifact-1-harness.md`) proved every component against stubs and captured fixtures. This plan supplies the one component that never existed — a submitter that talks to the real endpoint — plus the operational guards a paid campaign needs: a pre-flight assertion that the endpoint still matches its pinned configuration, a resumable driver so a multi-hour window can be interrupted, and a priming step that gives arm C the warm compile cache its premise depends on. Then it runs the campaign across at least three windows on different days, analyses the result, renders the four figures from real data, and publishes.

**Tech Stack:** Python 3.13 (stdlib `statistics`/`random`), pytest, ruff, matplotlib, RunPod serverless REST API, vLLM 0.27.1, Qwen3-8B.

**Scope of this plan:** Tasks 1–13 below. Everything the harness plan built is assumed working: 458 tests green, the GPU-free loop closed, `fixtures/` committed, and the three reconnaissance questions answered (arm C **retained** — this vLLM compiles at startup).

**Budget:** $45–75 of GPU time across ~300 measured runs, plus roughly $5 of priming and smoke runs. The harness plan consumed only a few dollars of the $200 envelope.

**This plan removes nothing.** Every existing module is extended or consumed as-is; no component is replaced, slimmed, or deleted, so there is no capability inventory or parity gate to run. `recon/capture.py` and `worker/recon_handler.py` stay exactly as they are — they remain the reproduction path for the fixtures.

---

## Pinned configuration — the experiment's boundary

Any change to a value in this table **ends the experiment** rather than continuing across the boundary (spec §5, threats to validity). Recorded per run and asserted by Task 3.

| Property | Value |
|---|---|
| Endpoint | `ka5mryakkxumew` |
| Datacenter | `EU-RO-1` |
| GPU | `NVIDIA GeForce RTX 4090` (24 GB, tier `ADA_24`) |
| Network volume | `9c7ut2slrd` (50 GB, EU-RO-1) |
| Template | `mzadx4qugv` |
| Image | `ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:3656fbc39211c7d103bff4ed72596f3363fb3bc0f41ac3a313400a9e588b93a9` |
| vLLM | `0.27.1` |
| Model | `Qwen/Qwen3-8B` |
| Model revision | `b968826d9c46dd6066d109eabc6255188de91218` |
| `--max-model-len` | `8192` |
| FlashBoot | **off** |
| Workers | min 0, max 1 |

---

## File Structure

| Path | Responsibility |
|---|---|
| `docs/experiment.md` | pre-registration — hypotheses, analysis plan, exclusion rules. Committed before the first paid run |
| `coldstart/runpod_submitter.py` | clock A against the live endpoint; shapes the payload the driver expects |
| `coldstart/preflight.py` | asserts the endpoint still matches the pinned configuration; refuses to run otherwise |
| `coldstart/driver.py` | modified — resumable campaign |
| `scripts/run_window.py` | operator entry point for one measurement window |
| `scripts/prime_compile_cache.py` | populates the volume's compile cache so arm C is warm |
| `scripts/analyse.py` | derives every published number from the stored JSONL |
| `scripts/render_figures.py` | renders the four body figures from real data |
| `data/campaign.jsonl` | the campaign's append-only record store |
| `docs/runbook.md` | how a reader reproduces the campaign |
| `tests/test_runpod_submitter.py` | submitter tests, against captured payload shapes |
| `tests/test_preflight.py` | pre-flight guard tests |

---

## Task 1: Pre-registration — before any paid run

**This task must complete and be pushed before Task 7.** The git timestamp is what proves the hypotheses were not retrofitted to the result (spec §5). Running a paid measurement first destroys that proof permanently and cannot be repaired.

**Files:**
- Create: `docs/experiment.md`

- [ ] **Step 1: Write the pre-registration document**

`docs/experiment.md`:

```markdown
# Artifact 1 — Pre-registration

Committed before the first paid measurement run. The git timestamp on this file
is the evidence that the hypotheses below were fixed in advance.

## Configuration held fixed

Endpoint ka5mryakkxumew, EU-RO-1, NVIDIA GeForce RTX 4090 (24 GB), network
volume 9c7ut2slrd, template mzadx4qugv, image
ghcr.io/alexostapiuk11/coldstart-recon-worker@sha256:3656fbc39211c7d103bff4ed72596f3363fb3bc0f41ac3a313400a9e588b93a9,
vLLM 0.27.1, Qwen/Qwen3-8B revision b968826d9c46dd6066d109eabc6255188de91218,
--max-model-len 8192, gpu_memory_utilization at the 0.9 default, FlashBoot off,
workersMin 0, workersMax 1.

`--max-model-len 8192` is not a default. Qwen3-8B's native 40960 context needs
more KV cache than a 24 GB card has left after 15.27 GiB of weights, and the
engine refuses to start. 8192 fits with headroom and keeps supported
concurrency non-degenerate at roughly four sequences.

Any change to a value above ends the experiment rather than continuing across
the boundary.

## Arms

Cache configuration is the only thing that differs between arms
(`coldstart/cache_config.py`).

| Arm | Weights | Compile cache |
|---|---|---|
| A | hub, per-run cold path | cold, per-run path |
| B | network volume | cold, per-run path |
| C | network volume | warm, on the volume |

## Hypotheses

**H1 (decomposition).** Weight handling is the dominant directly-measured stage
— more than half of `T_process` — in the fully uncached arm.

**H2 (weight caching).** Pre-staging weights on a network volume materially
reduces weight-handling time relative to fetching from the hub.

**H3 (compile caching).** Engine compilation on a cold artifact cache is a
non-trivial term in `S4`, and warming that cache materially reduces engine-init
time. Confirmed measurable by the reconnaissance run: this vLLM version
compiles at startup, `torch.compile took 38.96 s in total` against a 53.73 s
engine init.

**H4 (tail).** The spread between median and p95 total cold start is driven
substantially by host heterogeneity rather than by variance within any single
stage.

**H5 (compile cache buys KV capacity).** A cold compile inflates the engine's
measured peak activation, reducing the KV cache budget. Arm C therefore shows
higher `kv_capacity_tokens` than arm B under otherwise identical configuration.

H5 is new in this pre-registration and is stated as a hypothesis, not a result.
It comes from the reconnaissance captures, where peak activation was 1.18 GiB
on a cold compile and 0.19 GiB on a warm one with every other memory term
identical, and KV capacity was 35,792 versus 43,040 tokens. That is n=1 per
condition and confounded by worker reuse, which is exactly why it is being
predicted in advance rather than reported from those captures.

The relative ranking of H2 and H3 is the most interesting result available.

## Analysis plan

Every derived row comes from `coldstart.analysis.metrics.derive`. Rows are
partitioned by `coldstart.analysis.pipeline.partition` before any figure or
statistic sees them; consistency is a requirement of every preset.

Primary comparison unit: `t_weights` for A→B, `t_compile` for B→C.
Reported for each contrast: median difference with a 95% bootstrap percentile
interval (`bootstrap_median_diff`, 10,000 iterations).
**The interval on the difference of the two contrasts
(`bootstrap_contrast_difference`) is reported before any ranking claim is
made.**

Secondary, supporting only: within-host triples
(`bootstrap_paired_median_diff`), reported with wider intervals and never as
the headline.

Distributions are reported as p50/p90/p95 and a full ECDF. **No p99** — at
~100 runs per arm that is one or two observations.

## Exclusion rules, fixed in advance

- A run whose clocks fail `check_consistency` is discarded, reason recorded.
- A run whose observed compile-cache state does not match its arm's expected
  state is discarded, reason recorded.
- A failed run is counted in the failure-rate table, never in the discard
  table, and never substitutes for a missing arm in a within-host triple.
- Failure rate and discard rate are published per arm.
- No run is retried in place.

## Stopping rule

Stop at 100 runs per arm, or when the intervals on **both** contrasts are tight
enough to distinguish a large effect from no effect — whichever comes first.
Both must qualify.

## Headline selection rule

Rank candidate findings by how far they transfer to a reader on different
infrastructure, and lead with the most transferable. Committed now so the
headline cannot be chosen by which result cost the most effort.
```

- [ ] **Step 2: Get sign-off on H5**

H5 is an addition to the spec's four hypotheses. Confirm with the human partner
that adding it is wanted before committing. If not, delete the H5 section and
its rationale paragraph.

- [ ] **Step 3: Commit and push, before any paid run**

```bash
git add docs/experiment.md
git commit -m "docs: pre-register hypotheses and analysis plan before the campaign"
git push origin artifact-1-harness
```

Expected: the commit exists on the remote with a timestamp preceding every
record in `data/campaign.jsonl`.

---

## Task 2: Real RunPod submitter

The one component the harness plan never built. `coldstart/submitter.py` contains only `StubSubmitter`, so `worker/handler.py` is currently unreachable from any code path.

**Files:**
- Create: `coldstart/runpod_submitter.py`, `tests/test_runpod_submitter.py`

- [ ] **Step 1: Write the failing test**

`tests/test_runpod_submitter.py`:

```python
import pytest

from coldstart.runpod_submitter import RunPodSubmitter

COMPLETED = {
    "id": "job-1",
    "status": "COMPLETED",
    "delayTime": 8577,
    "executionTime": 150577,
    "workerId": "iiewfw59dqskoe",
    "output": {
        "healthy": True,
        "run_id": "run-1",
        "arm": "A",
        "log_lines": ["Model loading took 15.27 GiB and 36.4 seconds"],
        "warmup": [{"req_index": 0, "t_dispatch_mono": 1.0, "ttft": 0.5, "end_to_end": 2.0}],
        "clock_B": {"t0_wall": 0.0, "marks": [{"stage": "S1_imports_done", "t_mono": 1.0}]},
        "host": {"host_id": "container-abc", "gpu_model": "NVIDIA GeForce RTX 4090"},
        "cache_config": {"arm": "A", "weights_source": "hub", "compile_cache_warm": False},
        "compile_cache_observed": False,
    },
}


class FakeTransport:
    """Stands in for the RunPod HTTP API."""

    def __init__(self, statuses, job_id="job-1"):
        self._statuses = list(statuses)
        self._job_id = job_id
        self.started = []

    def start(self, payload):
        self.started.append(payload)
        return self._job_id

    def status(self, job_id):
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]


def _submitter(transport, **kw):
    return RunPodSubmitter(
        transport=transport, clock=iter([100.0, 260.0]).__next__, poll_interval=0.0, **kw
    )


def test_submits_arm_and_run_id_as_job_input():
    t = FakeTransport([COMPLETED])
    _submitter(t).submit(arm="A", run_id="run-1")
    assert t.started == [{"arm": "A", "run_id": "run-1"}]


def test_records_clock_a_around_the_whole_job():
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    assert outcome.clock_A == {"t_submit": 100.0, "t_result": 260.0}
    assert outcome.error is None


def test_clock_c_is_attached_from_the_status_payload():
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    assert outcome.payload["clock_C"] == {"delay_ms": 8577, "execution_ms": 150577}


def test_platform_worker_id_becomes_the_host_id():
    """The container hostname changes when a reused worker restarts its
    container; the platform's workerId does not. Within-host pairing needs the
    identity that is stable across a worker's lifetime."""
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    host = outcome.payload["host"]
    assert host["host_id"] == "iiewfw59dqskoe"
    assert host["container_host_id"] == "container-abc"


def test_polls_until_terminal():
    running = {"id": "job-1", "status": "IN_PROGRESS"}
    t = FakeTransport([running, running, COMPLETED])
    outcome = _submitter(t).submit(arm="A", run_id="run-1")
    assert outcome.error is None


def test_platform_failure_is_captured_as_data():
    failed = {"id": "job-1", "status": "FAILED", "error": "worker exited"}
    outcome = _submitter(FakeTransport([failed])).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "worker exited" in outcome.error


def test_unhealthy_probe_is_a_failure_not_a_publishable_run():
    """The job completed, but the engine never became healthy. Recording it as
    ok would put a run with no stage marks into the publishable set."""
    unhealthy = dict(COMPLETED, output=dict(COMPLETED["output"], healthy=False))
    outcome = _submitter(FakeTransport([unhealthy])).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "health check timed out" in outcome.error


def test_poll_timeout_is_captured_as_data():
    running = {"id": "job-1", "status": "IN_PROGRESS"}
    sub = RunPodSubmitter(
        transport=FakeTransport([running]),
        clock=iter([0.0, 1.0]).__next__,
        poll_interval=0.0,
        job_timeout=0.0,
    )
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "timed out" in outcome.error


def test_transport_exception_does_not_escape():
    class Broken:
        def start(self, payload):
            raise RuntimeError("submit failed: connection reset")

    outcome = _submitter(Broken()).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "submit failed" in outcome.error


def test_keyboard_interrupt_still_escapes():
    class Stopped:
        def start(self, payload):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _submitter(Stopped()).submit(arm="A", run_id="run-1")
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_runpod_submitter.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.runpod_submitter'`

- [ ] **Step 3: Implement**

`coldstart/runpod_submitter.py`:

```python
"""Clock A against the live RunPod endpoint.

Shapes the platform's response into the payload `driver._record_from` expects,
so the driver is identical whether it is fed by the stub or by the real thing.
"""

import time

import requests

from coldstart.runpod_api import extract_lifecycle, extract_worker_id
from coldstart.submitter import SubmitOutcome

API = "https://api.runpod.ai/v2"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class HttpTransport:
    """The real endpoint. Retries the transient rejections, as recon/capture.py does."""

    def __init__(self, endpoint_id: str, api_key: str, attempts: int = 5):
        self._url = f"{API}/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._attempts = attempts

    def start(self, payload: dict) -> str:
        for attempt in range(self._attempts):
            r = requests.post(f"{self._url}/run", headers=self._headers,
                              json={"input": payload}, timeout=30)
            # 409 is returned for a window after any endpoint config change and
            # 5xx shows up under load. Both are transient; a campaign of
            # hundreds of jobs cannot abort on one of them.
            if r.status_code == 409 or r.status_code >= 500:
                if attempt == self._attempts - 1:
                    r.raise_for_status()
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()["id"]
        raise RuntimeError("unreachable: retry loop exited without returning")

    def status(self, job_id: str) -> dict:
        r = requests.get(f"{self._url}/status/{job_id}", headers=self._headers, timeout=30)
        r.raise_for_status()
        return r.json()


class RunPodSubmitter:
    """Clock A. Same interface as StubSubmitter -- submit(arm, run_id)."""

    def __init__(self, transport, clock=time.monotonic, poll_interval: float = 5.0,
                 job_timeout: float = 1800.0, sleep=time.sleep):
        self._transport = transport
        self._clock = clock
        self._poll_interval = poll_interval
        self._job_timeout = job_timeout
        self._sleep = sleep

    def _await_terminal(self, job_id: str) -> dict:
        deadline = time.monotonic() + self._job_timeout
        while True:
            status = self._transport.status(job_id)
            if status.get("status") in TERMINAL:
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} timed out after {self._job_timeout}s")
            self._sleep(self._poll_interval)

    def _payload_from(self, status: dict) -> dict:
        state = status.get("status")
        if state != "COMPLETED":
            raise RuntimeError(f"job ended {state}: {status.get('error') or 'no detail'}")
        output = dict(status.get("output") or {})
        if not output.get("healthy"):
            # The job completed but the engine never answered its health check.
            # Phrased to match checks.classify_failure's HEALTH_TIMEOUT needle.
            raise RuntimeError("health check timed out: probe reported unhealthy")

        output["clock_C"] = extract_lifecycle(status)
        host = dict(output.get("host") or {})
        # The platform's worker identity is stable across the container
        # restarts a reused serverless worker performs; the container hostname
        # is not. Within-host pairing needs the stable one.
        worker_id = extract_worker_id(status)
        if worker_id:
            host["container_host_id"] = host.get("host_id")
            host["host_id"] = worker_id
        host["job_id"] = status.get("id")
        output["host"] = host
        return output

    def submit(self, arm: str, run_id: str) -> SubmitOutcome:
        t_submit = self._clock()
        try:
            job_id = self._transport.start({"arm": arm, "run_id": run_id})
            payload = self._payload_from(self._await_terminal(job_id))
            error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            payload, error = None, str(e)
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=payload,
            error=error,
        )
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_runpod_submitter.py -q`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/runpod_submitter.py tests/test_runpod_submitter.py
git commit -m "feat: real RunPod submitter shaping the payload the driver expects"
```

---

## Task 3: Pre-flight guard

FlashBoot silently ignored `flashboot: false` at endpoint creation and only stuck after a follow-up update call. If the endpoint is ever recreated it may come back on, and the campaign would measure RunPod's cache instead of the arms — producing entirely plausible numbers. Nothing about that failure is visible in the data afterwards, which is why it is asserted before every window rather than checked once.

**Files:**
- Create: `coldstart/preflight.py`, `tests/test_preflight.py`

- [ ] **Step 1: Write the failing test**

`tests/test_preflight.py`:

```python
import pytest

from coldstart.preflight import PINNED, PreflightError, assert_endpoint_matches

OK = {
    "id": "ka5mryakkxumew",
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}


def test_matching_endpoint_passes():
    assert_endpoint_matches(OK)


def test_flashboot_enabled_is_refused():
    """The failure this catches produces plausible numbers, not an error:
    FlashBoot caches exactly what the experiment measures."""
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(dict(OK, flashboot=True))


def test_wrong_gpu_is_refused():
    with pytest.raises(PreflightError, match="gpuTypeIds"):
        assert_endpoint_matches(dict(OK, gpuTypeIds=["NVIDIA L4"]))


def test_wrong_volume_is_refused():
    with pytest.raises(PreflightError, match="networkVolumeId"):
        assert_endpoint_matches(dict(OK, networkVolumeId="other"))


def test_warm_workers_are_refused():
    """workersMin > 0 keeps a worker alive between runs, so a 'cold' start is
    not cold."""
    with pytest.raises(PreflightError, match="workersMin"):
        assert_endpoint_matches(dict(OK, workersMin=1))


def test_every_pinned_key_is_checked():
    """A key added to PINNED must actually be asserted, or the guard silently
    stops covering it."""
    for key in PINNED:
        broken = dict(OK)
        broken[key] = "definitely-wrong"
        with pytest.raises(PreflightError, match=key):
            assert_endpoint_matches(broken)


def test_missing_key_is_refused_not_defaulted():
    broken = dict(OK)
    del broken["flashboot"]
    with pytest.raises(PreflightError, match="flashboot"):
        assert_endpoint_matches(broken)
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_preflight.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.preflight'`

- [ ] **Step 3: Implement**

`coldstart/preflight.py`:

```python
"""Refuses to start a paid window unless the endpoint still matches its pins.

Every value here is part of the experiment's boundary (spec 5, threats to
validity): a change ends the experiment rather than continuing across it. The
guard exists because the failure it catches is invisible afterwards -- an
endpoint with FlashBoot back on produces a complete, plausible dataset that
measures the platform's cache instead of the arms.
"""

import requests

REST = "https://rest.runpod.io/v1"

PINNED = {
    "flashboot": False,
    "gpuTypeIds": ["NVIDIA GeForce RTX 4090"],
    "networkVolumeId": "9c7ut2slrd",
    "templateId": "mzadx4qugv",
    "workersMin": 0,
}


class PreflightError(RuntimeError):
    """The endpoint no longer matches the pinned configuration."""


def assert_endpoint_matches(endpoint: dict, pinned: dict | None = None) -> None:
    pinned = PINNED if pinned is None else pinned
    problems = []
    for key, expected in pinned.items():
        if key not in endpoint:
            problems.append(f"{key}: absent from the endpoint, expected {expected!r}")
        elif endpoint[key] != expected:
            problems.append(f"{key}: {endpoint[key]!r}, expected {expected!r}")
    if problems:
        raise PreflightError(
            "endpoint does not match the pinned configuration; refusing to spend:\n  "
            + "\n  ".join(problems)
        )


def fetch_endpoint(endpoint_id: str, api_key: str) -> dict:
    r = requests.get(
        f"{REST}/endpoints/{endpoint_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_preflight.py -q`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/preflight.py tests/test_preflight.py
git commit -m "feat: pre-flight guard refusing to spend on a drifted endpoint"
```

---

## Task 4: Resumable campaign

A window is hours long. An interrupted campaign must resume without re-running completed runs and without corrupting the schedule — the interleaving is the design's most important validity property, so resume has to continue the *same* schedule rather than build a new one.

**Files:**
- Modify: `coldstart/driver.py`
- Modify: `tests/test_driver.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_driver.py`:

```python
def test_resume_skips_completed_runs_and_keeps_the_schedule(tmp_path):
    """Resume must continue the same interleaved schedule. Rebuilding it would
    change which arm runs when, which is the confound interleaving exists to
    prevent."""

    class FailsAfter:
        def __init__(self, limit):
            self.limit = limit
            self.calls = 0
            self._inner = StubEndpoint(seed=21)

        def run(self, arm, run_id):
            self.calls += 1
            if self.calls > self.limit:
                raise KeyboardInterrupt("operator stopped the window")
            return self._inner.run(arm=arm, run_id=run_id)

    store = JsonlStore(tmp_path / "runs.jsonl")
    kw = dict(store=store, arms=["A", "B", "C"], triples=4, seed=31)
    try:
        run_campaign(submitter=StubSubmitter(FailsAfter(5)), **kw)
    except KeyboardInterrupt:
        pass
    first = store.read_all()
    assert len(first) == 5

    ep = FailsAfter(999)
    run_campaign(submitter=StubSubmitter(ep), resume=True, **kw)
    all_records = store.read_all()

    assert len(all_records) == 12
    assert ep.calls == 7, "resume must not re-run completed runs"
    assert [r.run_index for r in all_records] == list(range(12))
    # The arm at each index is the one the original schedule assigned.
    expected = [s.arm for s in build_schedule(arms=["A", "B", "C"], triples=4, seed=31)]
    assert [r.arm for r in all_records] == expected


def test_resume_is_off_by_default(tmp_path):
    """Appending a second campaign to a populated store must not silently
    skip runs the operator meant to perform."""
    store = JsonlStore(tmp_path / "runs.jsonl")
    kw = dict(store=store, arms=["A"], triples=2, seed=1)
    run_campaign(submitter=StubSubmitter(StubEndpoint(seed=22)), **kw)
    run_campaign(submitter=StubSubmitter(StubEndpoint(seed=23)), **kw)
    assert len(store.read_all()) == 4
```

Add `build_schedule` to that file's imports:

```python
from coldstart.scheduler import build_schedule
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_driver.py -q`
Expected: FAIL — `TypeError: run_campaign() got an unexpected keyword argument 'resume'`

- [ ] **Step 3: Implement**

Replace `run_campaign` in `coldstart/driver.py`:

```python
def run_campaign(submitter, store, arms, triples, seed, on_run=None, resume=False):
    """One record per scheduled run. Never retries in place -- see spec 6.6.

    `resume=True` skips runs already present in the store, keyed by
    `run_index`. The schedule is rebuilt from the same `arms`/`triples`/`seed`,
    so a resumed window continues the original interleaving rather than
    generating a new one -- interleaving is the design's most important
    validity property and a fresh schedule would change which arm runs when.

    Off by default: silently skipping runs an operator asked for is a worse
    failure than repeating them.
    """
    schedule = build_schedule(arms=arms, triples=triples, seed=seed)
    done: set[int] = set()
    if resume:
        done = {r.run_index for r in store.read_all()}
    for scheduled in schedule:
        if scheduled.run_index in done:
            continue
        run_id = _new_run_id()
        outcome = submitter.submit(arm=scheduled.arm, run_id=run_id)
        record = _record_from(scheduled, run_id, outcome)
        record.host["triple_index"] = scheduled.triple_index
        store.append(record)
        if on_run:
            on_run(record)
    return store
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_driver.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add coldstart/driver.py tests/test_driver.py
git commit -m "feat: resumable campaign continuing the original schedule"
```

---

## Task 4b: Arm-state verification gate

`docs/experiment.md` pre-registers "a run whose observed compile-cache state does not match its arm's expected state is discarded, reason recorded", and spec §10 requires compile-cache state be "verified per run from engine output, not assumed from configuration". **Nothing implements this.** The handler already returns `compile_cache_observed` and the arm's expected state is in `record.config["compile_cache_warm"]`, but no code compares them.

Without this, the failure it exists to catch is invisible: if `VLLM_CACHE_ROOT` stops reaching the engine, arm C silently becomes arm B and the campaign reports a compile effect of approximately zero — a clean, plausible, wrong result. This is the detector for exactly the leak the reconnaissance runs demonstrated by accident.

**Files:**
- Modify: `coldstart/checks.py`
- Modify: `coldstart/analysis/metrics.py`
- Modify: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics.py`:

```python
def test_arm_state_mismatch_is_discarded_with_its_own_reason():
    """Arm C configured warm but observed cold means VLLM_CACHE_ROOT did not
    reach the engine, so arm C silently ran as arm B. The campaign would
    report a compile effect near zero and look entirely healthy."""
    record = make()
    record.arm = "C"
    record.config = {"arm": "C", "compile_cache_warm": True}
    record.engine = dict(record.engine, compile_cache_observed=False)
    d = derive(record)
    assert d["consistent"] is False
    assert d["discard_reason"] == DiscardReason.ARM_STATE_MISMATCH


def test_matching_arm_state_is_left_alone():
    record = make()
    record.arm = "C"
    record.config = {"arm": "C", "compile_cache_warm": True}
    record.engine = dict(record.engine, compile_cache_observed=True)
    assert derive(record)["consistent"] is True


def test_cold_arm_observing_a_warm_cache_is_also_a_mismatch():
    """The leak direction that actually happened in reconnaissance: a cold arm
    finding a previous run's compiled artifacts."""
    record = make()
    record.arm = "A"
    record.config = {"arm": "A", "compile_cache_warm": False}
    record.engine = dict(record.engine, compile_cache_observed=True)
    d = derive(record)
    assert d["consistent"] is False
    assert d["discard_reason"] == DiscardReason.ARM_STATE_MISMATCH


def test_absent_arm_state_is_not_a_mismatch():
    """Fixtures and stub rows carry neither field. Absence is unknown, not
    a violation -- inventing one would discard every historical record."""
    record = make()
    record.config = {}
    record.engine = dict(record.engine)
    record.engine.pop("compile_cache_observed", None)
    assert derive(record)["consistent"] is True
```

Ensure `DiscardReason` is imported in that test module:

```python
from coldstart.checks import DiscardReason
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -q -k arm_state`
Expected: FAIL — `AttributeError: ARM_STATE_MISMATCH`

- [ ] **Step 3: Add the discard reason**

In `coldstart/checks.py`, add to `DiscardReason`:

```python
    ARM_STATE_MISMATCH = "arm_state_mismatch"
```

and extend that class's docstring with:

```
    ARM_STATE_MISMATCH is produced by metrics.derive() when the compile-cache
    state observed from engine output disagrees with the state the arm's
    configuration asked for. Pre-registered as an exclusion rule: an arm whose
    cache state was not what it claimed is not a slightly noisy data point, it
    is a different arm.
```

- [ ] **Step 4: Implement the check in `derive`**

In `coldstart/analysis/metrics.py`, add this helper next to the other module-level helpers:

```python
def _arm_state_mismatch(record: RunRecord) -> str | None:
    """Compare the arm's configured cache state against what was observed.

    Both sides must be present to compare. Absence is unknown, not a
    violation: fixtures and stub-built rows carry neither field, and treating
    missing as mismatched would discard every historical record.
    """
    expected = (record.config or {}).get("compile_cache_warm")
    observed = (record.engine or {}).get("compile_cache_observed")
    if expected is None or observed is None:
        return None
    if bool(expected) != bool(observed):
        return (
            f"arm {record.arm!r} configured compile_cache_warm={bool(expected)} "
            f"but engine output observed {bool(observed)}"
        )
    return None
```

Then, immediately before the `return {` that builds the derived row, add:

```python
    # Pre-registered exclusion rule: an arm whose observed cache state is not
    # the state it was configured for is a different arm, not a noisy sample.
    # Checked last so it cannot mask an earlier, more specific violation.
    mismatch = _arm_state_mismatch(record)
    if mismatch is not None and consistent:
        consistent = False
        reason = mismatch
        discard_reason = DiscardReason.ARM_STATE_MISMATCH
```

- [ ] **Step 5: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_metrics.py -q`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS — no existing test regresses. If stub or fixture rows now
discard, the "absence is unknown" branch is wrong; fix that rather than
loosening the check.

- [ ] **Step 7: Commit**

```bash
git add coldstart/checks.py coldstart/analysis/metrics.py tests/test_metrics.py
git commit -m "feat: discard runs whose observed cache state contradicts their arm"
```

---

## Task 5: Window runner

**Files:**
- Create: `scripts/run_window.py`

- [ ] **Step 1: Write the runner**

`scripts/run_window.py`:

```python
"""Run one measurement window against the live endpoint.

    .venv/bin/python scripts/run_window.py --triples 12
    .venv/bin/python scripts/run_window.py --triples 12 --resume

Reads RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID from the environment (.env is
gitignored). Refuses to start unless the endpoint still matches its pins.
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.driver import run_campaign
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter
from coldstart.store import JsonlStore

STORE = Path("data/campaign.jsonl")
ARMS = ["A", "B", "C"]
# Fixed for the whole campaign. Every window rebuilds the same schedule and
# resume continues it; changing this would re-randomise the interleaving.
SCHEDULE_SEED = 20260828


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--triples", type=int, required=True, help="triples in the full schedule")
    ap.add_argument("--resume", action="store_true", help="skip runs already in the store")
    ap.add_argument("--store", default=str(STORE))
    args = ap.parse_args()

    key = os.environ["RUNPOD_API_KEY"]
    endpoint_id = os.environ["RUNPOD_ENDPOINT_ID"]

    assert_endpoint_matches(fetch_endpoint(endpoint_id, key))
    print(f"[preflight] endpoint {endpoint_id} matches the pinned configuration", flush=True)

    store = JsonlStore(args.store)
    started = time.monotonic()
    seen = {"n": 0}

    def progress(record):
        seen["n"] += 1
        outcome = record.status["outcome"]
        detail = record.status.get("failure_class") or ""
        elapsed = time.monotonic() - started
        print(
            f"[{seen['n']:>4}] run_index={record.run_index:<4} arm={record.arm} "
            f"{outcome:<7} {detail:<20} elapsed={elapsed / 60:.1f}m",
            flush=True,
        )

    run_campaign(
        submitter=RunPodSubmitter(HttpTransport(endpoint_id, key)),
        store=store,
        arms=ARMS,
        triples=args.triples,
        seed=SCHEDULE_SEED,
        on_run=progress,
        resume=args.resume,
    )
    print(f"[done] {seen['n']} runs this invocation; store={args.store}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it refuses a drifted endpoint without spending**

Temporarily point it at a wrong pin and confirm it stops before submitting:

```bash
set -a; . ./.env; set +a
.venv/bin/python -c "
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint, PreflightError
import os
ep = fetch_endpoint(os.environ['RUNPOD_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY'])
try:
    assert_endpoint_matches(ep, {'flashboot': True})
    print('FAIL: should have refused')
except PreflightError as e:
    print('refused as expected:'); print(e)
"
```
Expected: `refused as expected:` followed by the mismatch detail.

- [ ] **Step 3: Verify the real endpoint passes pre-flight**

```bash
set -a; . ./.env; set +a
.venv/bin/python -c "
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
import os
assert_endpoint_matches(fetch_endpoint(os.environ['RUNPOD_ENDPOINT_ID'], os.environ['RUNPOD_API_KEY']))
print('preflight OK')
"
```
Expected: `preflight OK`. If it reports `flashboot: True`, fix the endpoint before continuing:

```bash
set -a; . ./.env; set +a
curl -s -X POST "https://rest.runpod.io/v1/endpoints/$RUNPOD_ENDPOINT_ID/update" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" -H 'Content-Type: application/json' \
  -d '{"flashboot": false}' > /dev/null
```

- [ ] **Step 4: Commit**

```bash
git add scripts/run_window.py
git commit -m "feat: window runner with a pre-flight gate before any spend"
```

---

## Task 6: Endpoint preparation — HF token and capacity

**Files:**
- Create: `docs/runbook.md`

- [ ] **Step 1: Set HF_TOKEN on the endpoint**

Arm A re-downloads ~16 GB from the hub on every one of its ~100 runs. The
reconnaissance captures logged
`Warning: You are sending unauthenticated requests to the HF Hub`, and hub rate
limiting would inflate arm A's `t_weights` rather than fail cleanly — it would
look like a real effect. Set a read-scoped token in the RunPod console under
the template's environment variables, as `HF_TOKEN`.

Do not put the token in this repo. Add it in the RunPod console only.

- [ ] **Step 2: Check capacity before committing to a window**

```bash
set -a; . ./.env; set +a
curl -s -X POST "https://api.runpod.io/graphql?api_key=$RUNPOD_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"query":"query { dataCenters { id gpuAvailability { gpuTypeId available stockStatus } } }"}' \
  | .venv/bin/python -c "
import json,sys
d=json.load(sys.stdin)
for dc in d['data']['dataCenters']:
    if dc['id'] != 'EU-RO-1': continue
    for g in dc.get('gpuAvailability') or []:
        if g['gpuTypeId'] == 'NVIDIA GeForce RTX 4090':
            print('EU-RO-1 RTX 4090:', g['available'], g.get('stockStatus'))
"
```
Expected: `EU-RO-1 RTX 4090: True <stock>`. If `False`, do not start a window —
a queued job with no capacity presents as a worker flapping between `ready` and
`throttled` while the job waits indefinitely, not as an error.

- [ ] **Step 3: Write the runbook**

`docs/runbook.md`:

```markdown
# Runbook — artifact 1 campaign

## Prerequisites

- `.env` with `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` (gitignored).
- `HF_TOKEN` set on the RunPod template, so arm A is not rate-limited.
- The endpoint matching the pinned configuration in `docs/experiment.md`.

## Before every window

1. Check EU-RO-1 RTX 4090 capacity (see plan Task 6, Step 2). Do not start
   without it: with no capacity the job queues forever rather than failing.
2. `scripts/run_window.py` asserts the pinned configuration itself and refuses
   to spend if the endpoint has drifted. FlashBoot is the one that matters:
   it caches exactly what this experiment measures, and an endpoint with it
   enabled produces a complete, plausible, wrong dataset.

## Running

```
set -a; . ./.env; set +a
.venv/bin/python scripts/run_window.py --triples 100 --resume
```

`--triples` is the size of the whole campaign schedule, not this window. Every
invocation rebuilds the same schedule from the fixed seed and `--resume` skips
what is already recorded, so a window is simply "run until you stop it, then
resume tomorrow". Stopping with Ctrl-C is safe: `KeyboardInterrupt` is not
caught as a run failure, and the store is append-only.

## After every window

```
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl
```

Check the per-arm counts, failure rate and discard rate before deciding whether
to run another window.
```

- [ ] **Step 4: Commit**

```bash
git add docs/runbook.md
git commit -m "docs: campaign runbook"
```

---

## Task 7: Prime arm C's compile cache — FIRST PAID STEP OF THIS PLAN

Arm C's premise is a **warm** compile cache on the network volume at `/runpod-volume/vllm-cache`. Nothing has ever written there: the reconnaissance handler used the container default `/root/.cache/vllm`. Without priming, arm C's first run compiles cold and writes the cache, so early arm-C runs measure the cold path while later ones measure the warm path — the arm would be a mixture and the effect would appear to grow with run index.

Priming runs are **not** measurements and must not enter `data/campaign.jsonl`.

**Files:**
- Create: `scripts/prime_compile_cache.py`

- [ ] **Step 1: Write the priming script**

`scripts/prime_compile_cache.py`:

```python
"""Populate the volume's compile cache so arm C is genuinely warm.

Writes to data/priming.jsonl, never to the campaign store: these runs are
setup, not measurement, and including them would mix a cold compile into arm C.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.driver import run_campaign
from coldstart.preflight import assert_endpoint_matches, fetch_endpoint
from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter
from coldstart.store import JsonlStore


def main() -> None:
    key = os.environ["RUNPOD_API_KEY"]
    endpoint_id = os.environ["RUNPOD_ENDPOINT_ID"]
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key))

    store = JsonlStore("data/priming.jsonl")
    run_campaign(
        submitter=RunPodSubmitter(HttpTransport(endpoint_id, key)),
        store=store,
        arms=["C"],
        triples=2,
        seed=1,
        on_run=lambda r: print(
            f"[prime] {r.run_id} outcome={r.status['outcome']} "
            f"compile_cache_observed={r.engine.get('compile_cache_observed')} "
            f"t_compile_s4b={(r.engine.get('s4_subphases') or {}).get('S4b')}",
            flush=True,
        ),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/prime_compile_cache.py
```

Expected: two runs. The **first** reports `compile_cache_observed=False` and an
`S4b` around 39 s (cold compile, writing the cache). The **second** reports
`compile_cache_observed=True` and an `S4b` under 1 s.

Cost: roughly $0.50.

- [ ] **Step 3: Verify the cache is genuinely warm**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
rs = JsonlStore('data/priming.jsonl').read_all()
for r in rs:
    print(r.run_index, r.status['outcome'],
          'observed=', r.engine.get('compile_cache_observed'),
          'S4b=', (r.engine.get('s4_subphases') or {}).get('S4b'))
"
```
Expected: the last run shows `observed= True` and an `S4b` under 1 s.

**If the second run still compiles cold**, stop. Arm C is not viable as
configured and the cause must be found before spending on the campaign — the
most likely cause is that `VLLM_CACHE_ROOT` is not reaching the engine, which
would mean arm C is silently identical to arm B.

- [ ] **Step 4: Commit the priming script and its records**

```bash
git add scripts/prime_compile_cache.py data/priming.jsonl
git commit -m "chore: prime the volume compile cache so arm C is warm"
```

---

## Task 8: Paid smoke — one triple

Proves the whole real path — pre-flight, submitter, handler, probe, driver, store — before committing to hours of spend. Roughly $1.

**Files:**
- Create: `data/smoke.jsonl` (generated)

- [ ] **Step 1: Run one triple**

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/run_window.py --triples 1 --store data/smoke.jsonl
```
Expected: three lines, one per arm, all `ok`.

- [ ] **Step 2: Derive the three runs and check every field the campaign needs**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
from coldstart.analysis.metrics import derive
for r in JsonlStore('data/smoke.jsonl').read_all():
    d = derive(r)
    print(f\"arm={d['arm']} ok={d['ok']} consistent={d['consistent']} \"
          f\"t_total={d['t_total']} t_weights={d['t_weights']} \"
          f\"t_compile={d['t_compile']} t_s4_bracket={d['t_s4_bracket']} \"
          f\"t_fast={d['t_fast_seconds']} kv={d['kv_capacity_tokens']} \"
          f\"host={d['host_id']}\")
"
```

Expected for all three rows: `ok=True`, `consistent=True`, and **no `None`** in
`t_total`, `t_weights`, `t_compile`, `t_s4_bracket`, `t_fast_seconds`, or
`kv_capacity_tokens`.

A `None` in `t_s4_bracket` means the probe's `S4_start`/`S4_end` marks are not
arriving. A `None` in `t_fast_seconds` means `t_dispatch_mono` is missing. Both
are worker-side and **cannot be repaired after the campaign runs** — stop and
fix before Task 9.

- [ ] **Step 3: Check the arms actually differed**

```bash
.venv/bin/python -c "
from coldstart.store import JsonlStore
for r in JsonlStore('data/smoke.jsonl').read_all():
    print(r.arm, r.config.get('env'), 'observed=', r.engine.get('compile_cache_observed'))
"
```

Expected: arm A's `HF_HOME` under `/tmp/hf-cold/<run_id>`; arms B and C at
`/runpod-volume/hf`; arm C's `VLLM_CACHE_ROOT` at `/runpod-volume/vllm-cache`
with `observed= True`; arms A and B under `/tmp/vllm-cache-cold/<run_id>` with
`observed= False`.

**If all three arms show the same paths, the campaign is meaningless** — the
handler is not applying `CacheConfig`. Stop.

Task 4b's gate catches this class of failure automatically from here on: any run
whose observed cache state contradicts its arm is discarded with
`arm_state_mismatch`. Watch that count in every window's summary — a non-zero
value means an arm is not the arm it says it is.

- [ ] **Step 4: Verify the dtype matches the checkpoint's native precision**

Spec §10 requires this and nothing else checks it. Qwen3-8B is published in
BF16; a silent conversion at load would change both the weight-transfer time
and the memory arithmetic every KV number rests on.

```bash
.venv/bin/python -c "
import re
from coldstart.store import JsonlStore
for r in JsonlStore('data/smoke.jsonl').read_all():
    text = '\n'.join(r.engine.get('log_lines') or [])
    found = set(re.findall(r'dtype=(torch\.\w+)', text))
    print(r.arm, found or 'NOT FOUND')
"
```
Expected: every arm reports `{'torch.bfloat16'}`. Anything else, or `NOT
FOUND`, stops the campaign.

Note this reads `log_lines` off the stored record, so it only works if the
driver keeps them. If it prints `NOT FOUND` for every arm, check whether
`_record_from` is storing `log_lines` before concluding the dtype is wrong.

- [ ] **Step 5: Commit the smoke records**

```bash
git add data/smoke.jsonl
git commit -m "chore: paid smoke run across all three arms"
```

---

## Task 9: Measurement windows

~100 runs per arm, ~300 total, across **at least three windows on different days** (spec §5). The schedule is fixed at 100 triples; each window runs part of it with `--resume`.

**Files:**
- Modify: `data/campaign.jsonl` (append-only, generated)

- [ ] **Step 1: Run the first window**

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/run_window.py --triples 100 --resume
```

Stop with Ctrl-C after roughly a third of the schedule (about 100 runs).
`KeyboardInterrupt` is deliberately not caught as a run failure, and the store
is append-only, so stopping is safe at any point.

- [ ] **Step 2: Check integrity before the next window**

```bash
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl --summary-only
```

Expected: per-arm counts roughly equal, and a failure rate that is not
dominated by one class. **If one arm's failure rate is far above the others,
stop and diagnose** — a systematically failing arm biases the distribution in
exactly the way the exclusion rules cannot repair. Arm A failing on
`weight_acquisition` most likely means `HF_TOKEN` is missing or rate-limited.

- [ ] **Step 3: Commit the window**

```bash
git add data/campaign.jsonl
git commit -m "data: measurement window 1"
```

- [ ] **Step 4: Repeat on a different day**

Repeat Steps 1–3 for windows 2 and 3, on separate days, until the schedule
completes. Different days are a design requirement, not a convenience: a single
window confounds the whole experiment with that window's fleet conditions.

- [ ] **Step 5: Confirm the campaign is complete**

```bash
.venv/bin/python -c "
from collections import Counter
from coldstart.store import JsonlStore
rs = JsonlStore('data/campaign.jsonl').read_all()
print('records:', len(rs))
print('by arm:', Counter(r.arm for r in rs))
print('run_index gaps:', sorted(set(range(300)) - {r.run_index for r in rs})[:10])
"
```
Expected: 300 records, 100 per arm, no gaps.

---

## Task 10: Stopping-rule evaluation

The stopping rule is "100 per arm, **or** both contrasts resolved, whichever comes first" — and both must qualify. Evaluated explicitly so stopping is a decision on the record rather than a default.

**Files:**
- Create: `scripts/analyse.py`

- [ ] **Step 1: Write the analysis script**

`scripts/analyse.py`:

```python
"""Derive every published number from the stored JSONL.

    .venv/bin/python scripts/analyse.py --store data/campaign.jsonl
    .venv/bin/python scripts/analyse.py --store data/campaign.jsonl --summary-only
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    REQUIRED_FOR_T_WEIGHTS,
    discard_table,
    failure_rate_by_arm,
    partition,
)
from coldstart.analysis.stats import (
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_median_diff,
    median,
    percentiles,
    within_host_triples,
)
from coldstart.store import JsonlStore

ITERATIONS = 10_000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()

    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    out: dict = {"n_records": len(rows)}

    out["failure_rate_by_arm"] = failure_rate_by_arm(rows)
    total_part = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    out["discard_table"] = discard_table(total_part.discarded)
    out["counts"] = {
        "publishable_t_total": len(total_part.publishable),
        "discarded": len(total_part.discarded),
        "failed": len(total_part.failed),
    }

    if args.summary_only:
        print(json.dumps(out, indent=2, default=str))
        return

    pub = total_part.publishable
    out["distributions"] = {
        arm: percentiles([r["t_total"] for r in pub if r["arm"] == arm])
        for arm in ("A", "B", "C")
    }
    # H5: does a warm compile cache buy KV capacity? Routed through the shared
    # median every other aggregate uses, not a hand-rolled index.
    out["kv_capacity_median"] = {
        arm: median([r["kv_capacity_tokens"] for r in pub if r["arm"] == arm])
        for arm in ("A", "B", "C")
        if any(r["arm"] == arm for r in pub)
    }

    weights_pub = partition(rows, required=REQUIRED_FOR_T_WEIGHTS).publishable
    by_w = {a: [r["t_weights"] for r in weights_pub if r["arm"] == a] for a in "ABC"}
    by_c = {a: [r["t_compile"] for r in pub if r["arm"] == a] for a in "ABC"}

    # Mechanism contrasts, each in the unit that explains it.
    out["contrast_A_to_B_t_weights"] = bootstrap_median_diff(
        by_w["A"], by_w["B"], iterations=ITERATIONS, seed=1
    )
    out["contrast_B_to_C_t_compile"] = bootstrap_median_diff(
        by_c["B"], by_c["C"], iterations=ITERATIONS, seed=2
    )

    # The ranking claim, in one unit across all three arms. It has to be a
    # single metric: bootstrap_contrast_difference computes
    # (median(a) - median(b)) - (median(b) - median(c)) and uses b twice, so
    # feeding it t_weights for A/B and t_compile for C would subtract two
    # different quantities and produce a number that means nothing. t_total is
    # the honest common unit -- "which cache buys more cold start back".
    by_t = {a: [r["t_total"] for r in pub if r["arm"] == a] for a in "ABC"}
    out["contrast_A_to_B_t_total"] = bootstrap_median_diff(
        by_t["A"], by_t["B"], iterations=ITERATIONS, seed=5
    )
    out["contrast_B_to_C_t_total"] = bootstrap_median_diff(
        by_t["B"], by_t["C"], iterations=ITERATIONS, seed=6
    )
    # Reported before any ranking claim is made -- spec 7.
    out["difference_of_contrasts_t_total"] = bootstrap_contrast_difference(
        by_t["A"], by_t["B"], by_t["C"], iterations=ITERATIONS, seed=3
    )

    triples = within_host_triples(rows)
    out["within_host_triples"] = len(triples)
    if len(triples) >= 20:
        out["paired_A_to_B_t_weights"] = bootstrap_paired_median_diff(
            triples, "A", "B", "t_weights", iterations=ITERATIONS, seed=4
        )
    else:
        out["paired_A_to_B_t_weights"] = (
            f"withheld: {len(triples)} triples is below the 20-unit bootstrap floor"
        )

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the campaign**

```bash
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl | tee data/analysis.json
```

- [ ] **Step 3: Record the stopping decision**

Append to `docs/experiment.md` a short section stating which branch of the
stopping rule fired, with the two intervals quoted. Stopping early requires
**both** contrasts to have resolved; if only one has, keep running.

- [ ] **Step 4: Commit**

```bash
git add scripts/analyse.py data/analysis.json docs/experiment.md
git commit -m "feat: analysis script; record the stopping decision"
```

---

## Task 11: Figures from real data

**UI task.** These four images are the artifact's most-travelled output — the waterfall in particular is what gets shared. Rendering is not verification: each figure must be looked at, and checked for legibility at the width a phone will render it.

**Files:**
- Create: `scripts/render_figures.py`

- [ ] **Step 1: Write the renderer**

`scripts/render_figures.py`:

```python
"""Render the four body figures from the stored campaign JSONL."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart.analysis import figures
from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import REQUIRED_FOR_T_TOTAL, REQUIRED_FOR_WARMUP, partition
from coldstart.store import JsonlStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/figures")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = [derive(r) for r in JsonlStore(args.store).read_all()]
    total = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable
    warm = partition(rows, required=REQUIRED_FOR_WARMUP).publishable

    for name, fn, src in [
        ("waterfall", figures.waterfall, total),
        ("warmup", figures.warmup_curve, warm),
        ("ecdf", figures.ecdf_plot, total),
        ("per_host", figures.per_host_medians, total),
    ]:
        path = fn(src, out / f"{name}.png")
        print(f"{name}: {path} ({Path(path).stat().st_size // 1024} KB, n={len(src)})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Render**

```bash
.venv/bin/python scripts/render_figures.py --store data/campaign.jsonl
```
Expected: four paths printed, each with a non-trivial size and `n` equal to the
publishable count.

- [ ] **Step 3: Look at every figure**

Open each of `build/figures/waterfall.png`, `warmup.png`, `ecdf.png`,
`per_host.png` and confirm, by eye:

- **waterfall** — `S4b compilation` appears as its own labelled band, not
  folded into `unattributed within S4`. The unattributed sliver is small and
  the bars do **not** sum to exactly `t_total` (spec §7's honesty claim).
- **warmup** — the ±10% steady-state band is drawn, `T_fast` is annotated per
  arm, and the labels do not sit on top of each other or on the curves. Real
  arms have different steady states, so unlike the synthetic run the three
  curves will separate; check the annotations still place cleanly.
- **ecdf** — three arms distinguishable; the x-axis covers the real range
  without clipping the tail.
- **per_host** — host labels legible, `n` per host shown.

- [ ] **Step 4: Verify legibility at phone width**

The figures are published in a post that most readers open on a phone, and this
repo has already had one defect of exactly this kind (`fix: enlarge waterfall
text so it survives downscaling to phone width`). Downscale each figure to
375 px wide and look again:

```bash
.venv/bin/python -c "
from pathlib import Path
import matplotlib.image as mpimg, matplotlib.pyplot as plt
for name in ['waterfall','warmup','ecdf','per_host']:
    src = Path('build/figures')/f'{name}.png'
    img = mpimg.imread(src)
    h, w = img.shape[0], img.shape[1]
    fig = plt.figure(figsize=(375/100, 375/100*h/w), dpi=100)
    ax = fig.add_axes([0,0,1,1]); ax.imshow(img); ax.axis('off')
    dst = Path('build/figures')/f'{name}-phone.png'
    fig.savefig(dst, dpi=100); plt.close(fig)
    print(dst)
"
```

Open each `*-phone.png` and confirm axis labels, legend text, and arm labels
are still readable. If any are not, raise the font sizes in
`coldstart/analysis/figures.py` and re-render — do not ship a figure that is
only legible on a laptop.

- [ ] **Step 5: Commit**

```bash
git add scripts/render_figures.py
git commit -m "feat: render the four body figures from the campaign data"
```

---

## Task 12: Reproducibility check

The spec's claim is that a reader can re-derive every number in the post from the published records without running a GPU. That has to be exercised, not asserted.

**Files:**
- Create: `tests/test_reproducibility.py`

- [ ] **Step 1: Write the test**

`tests/test_reproducibility.py`:

```python
"""Every published number must come back out of the stored JSONL.

Skipped until the campaign exists, so the suite stays green before Task 9.
"""

import json
from pathlib import Path

import pytest

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import REQUIRED_FOR_T_TOTAL, partition
from coldstart.analysis.stats import bootstrap_median_diff
from coldstart.store import JsonlStore

STORE = Path("data/campaign.jsonl")
ANALYSIS = Path("data/analysis.json")

pytestmark = pytest.mark.skipif(
    not (STORE.exists() and ANALYSIS.exists()),
    reason="campaign data not present yet",
)


def _rows():
    return [derive(r) for r in JsonlStore(STORE).read_all()]


def test_every_record_reads_back_at_the_current_schema():
    assert len(JsonlStore(STORE).read_all()) > 0


def test_contrast_reproduces_bit_for_bit_from_the_store():
    """Same store, same seed, same iterations -> same interval. If this drifts,
    the published number cannot be re-derived by a reader."""
    published = json.loads(ANALYSIS.read_text())["contrast_B_to_C_t_compile"]
    pub = partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable
    by = {a: [r["t_compile"] for r in pub if r["arm"] == a] for a in "ABC"}
    again = bootstrap_median_diff(by["B"], by["C"], iterations=10_000, seed=2)
    assert again == pytest.approx(published, rel=1e-12)


def test_no_published_row_is_missing_a_headline_field():
    for row in partition(_rows(), required=REQUIRED_FOR_T_TOTAL).publishable:
        for field in ("t_total", "t_s4_bracket", "t_compile", "kv_capacity_tokens"):
            assert row[field] is not None, f"{field} missing on {row['arm']}/{row['host_id']}"


def test_failure_and_discard_counts_add_up():
    rows = _rows()
    p = partition(rows, required=REQUIRED_FOR_T_TOTAL)
    assert len(p.publishable) + len(p.discarded) + len(p.failed) == len(rows)
```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/pytest`
Expected: PASS — every test, with the reproducibility module running (not
skipped) now that `data/campaign.jsonl` and `data/analysis.json` exist.

- [ ] **Step 3: Run ruff**

Run: `.venv/bin/ruff check coldstart worker recon scripts tests`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_reproducibility.py
git commit -m "test: every published number re-derives from the stored records"
```

---

## Task 13: Post and pre-publish gate

**Files:**
- Create: `docs/post.md`

- [ ] **Step 1: Select the headline by the pre-registered rule**

Rank the candidate findings by how far each transfers to a reader on different
infrastructure, and lead with the most transferable. The rule was committed in
Task 1 precisely so the headline is not chosen by which result cost the most
effort. Record the ranking in `docs/post.md` before writing the body.

- [ ] **Step 2: Write the post**

`docs/post.md` must contain, per spec §8:

- The headline finding in **both** systems units and money, with every
  conversion assumption stated so a reader can substitute their own
  (`coldstart/analysis/economics.py` — `Assumptions`, `foregone_tokens`,
  `gpu_cost_per_scale_up`, `break_even_events_per_day`,
  `compile_cache_break_even_events_per_day`, `supported_concurrency`).
- Both contrasts with intervals, **and the interval on their difference quoted
  before any ranking claim**.
- The four body figures.
- Failure rate and discard rate per arm, with reasons.
- `S4` sub-phases with merged phases and the unattributed remainder shown
  rather than hidden.
- KV capacity and supported concurrency at 8192 context.
- The cost asymmetry between the arms: the weight cache is a volume you rent
  continuously; the compile cache is free to store but is invalidated by any
  change to engine version, model, hardware, or flags, so every upgrade pays
  the cold compile again unless warming is built into the deploy pipeline.
- The scope limit: one provider, one GPU, one model, one vLLM version.

**The four mandatory explanations (spec §8), each a short paragraph.** None
needs additional measurement; they are what separates reporting numbers from
demonstrating you understand the system that produced them.

1. **What memory profiling is doing and why it needs a forward pass** — you
   cannot know how much HBM is free for KV cache without running the model
   once. This is also the mechanism behind H5: a cold compile is resident
   during that pass and inflates the measurement.
2. **What CUDA graph capture costs and what it buys back** — startup seconds
   traded for per-step decode latency, which is why skipping it is a real
   option with a real price.
3. **What invalidates a compile cache** — engine version, model, hardware,
   flags — and therefore why this optimisation is operationally fragile in a
   way weight caching is not.
4. **What happens to a cold replica the moment a load balancer routes to it**
   — under continuous batching a fresh replica accepts work immediately, so the
   gap between ready and fast is served to real users rather than absorbed by a
   warmup period nobody sees.

- [ ] **Step 3: Run the pre-publish gate**

Confirm, item by item:

- [ ] Every number, diagram and claim derives from this rented-hardware
      experiment and independent reasoning. **Nothing traceable to employer
      internal material.** This is the non-negotiable item.
- [ ] No p99 anywhere — ~100 runs per arm does not support one.
- [ ] The difference-of-contrasts interval appears before any ranking claim.
- [ ] Within-host triples are labelled supporting evidence, never the headline.
- [ ] `docs/experiment.md` was committed before the first record in
      `data/campaign.jsonl`. Verify:

```bash
git log -1 --format=%cI -- docs/experiment.md
git log --diff-filter=A --format=%cI -- data/campaign.jsonl | tail -1
```
Expected: the first timestamp precedes the second.

- [ ] Four figures rendered from the campaign data and visually inspected at
      full size and phone width (Task 11).
- [ ] The repo publishes raw JSONL, analysis code, figure code and runbook.

- [ ] **Step 4: Commit**

```bash
git add docs/post.md
git commit -m "docs: artifact 1 post"
```

---

## Definition of done for this plan

- [ ] `docs/experiment.md` committed and pushed **before** the first paid record.
- [ ] Real submitter, pre-flight guard and resumable driver built, with tests green.
- [ ] Arm C's compile cache primed and verified warm from engine output.
- [ ] Paid smoke run across all three arms, with every headline field non-`None`.
- [ ] ~300 runs, ~100 per arm, across at least three windows on different days.
- [ ] Failure rate and discard rate published per arm, with reasons, including `arm_state_mismatch`.
- [ ] Both contrasts reported with intervals, and the interval on their difference reported before any ranking claim.
- [ ] Four figures rendered from real data and **visually inspected**, at full size and phone width.
- [ ] Every published number re-derives from the stored JSONL (`tests/test_reproducibility.py` green, not skipped).
- [ ] Full suite green, ruff clean.
- [ ] Pre-publish gate completed, including the employer-material check.
- [ ] Total campaign spend within $45–75.
