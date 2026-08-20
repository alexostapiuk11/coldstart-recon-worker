# Artifact 1 Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and prove the cold-start measurement harness for artifact 1, up to the point where it runs end-to-end against stubs and the analysis pipeline produces every published figure from synthetic data.

**Architecture:** A driver on macOS submits jobs to a RunPod serverless endpoint and times them on its own monotonic clock (A). A probe inside the container brackets `vllm serve` with its own monotonic clock (B), parses the engine's log output for `S4` sub-phases, drives ten warmup requests, and returns a stage bundle as the job result. RunPod's API supplies lifecycle timestamps (clock C). Everything lands in append-only JSONL, and a pure offline analysis layer computes the residual, the derived metrics, and the figures. A reconnaissance run happens early and cheaply to capture real engine logs and API responses as fixtures, which then back both the parser tests and a stub engine that replays them — so all later development is free.

**Tech Stack:** Python 3.13 (stdlib `statistics` and `random` for all analysis), pytest, ruff, matplotlib, Docker, RunPod serverless, vLLM, Qwen3-8B.

**Scope of this plan:** Tasks 1–19 below. The measurement campaign itself (pre-registration commit, ~300 paid runs, real-data analysis, the post) is a separate plan written once this harness is proven — it is execution, not software.

**Budget consumed by this plan:** roughly $5–15, all in Task 6 and Task 11 (reconnaissance and one integration run). The measurement budget of $45–75 is untouched.

**Learning guide:** spec §9b. Teaching checkpoints are marked **TEACH** and reference the module they ground.

---

## File Structure

| Path | Responsibility |
|---|---|
| `pyproject.toml` | deps, pytest and ruff config |
| `coldstart/recorder.py` | `StageRecorder` — clock B monotonic marks, bundle serialization |
| `coldstart/schema.py` | `RunRecord` and nested payloads, `SCHEMA_VERSION` |
| `coldstart/store.py` | append-only JSONL read/write |
| `coldstart/scheduler.py` | arm triples, randomization, run indices |
| `coldstart/cache_config.py` | the one interface that differs between arms |
| `coldstart/vllm_logs.py` | engine log → `S4` sub-phases + engine info |
| `coldstart/runpod_api.py` | clock C lifecycle timestamps |
| `coldstart/submitter.py` | clock A timestamps, dispatch, result capture |
| `coldstart/checks.py` | consistency checks, residual, failure classification |
| `coldstart/driver.py` | orchestration |
| `coldstart/stubs/stub_engine.py` | replays captured logs with configurable timing |
| `coldstart/stubs/stub_endpoint.py` | in-process stand-in for the RunPod endpoint |
| `coldstart/analysis/metrics.py` | derived metrics |
| `coldstart/analysis/stats.py` | percentiles, ECDF, bootstrap |
| `coldstart/analysis/figures.py` | the four figures |
| `worker/probe.py` | in-container probe: brackets `vllm serve`, drives warmup |
| `worker/handler.py` | RunPod serverless handler |
| `worker/Dockerfile` | pinned image |
| `recon/capture.py` | reconnaissance run — capture only |
| `fixtures/` | committed real logs and API responses |
| `tests/` | one test module per source module |

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `coldstart/__init__.py`, `tests/test_smoke.py`, `.gitignore` (modify)

- [ ] **Step 1: Create the virtualenv and install tooling**

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install pytest matplotlib requests ruff
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "coldstart"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["matplotlib", "requests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py313"
```

`pythonpath = ["."]` is what makes `from coldstart import ...` work. Without it, `.venv/bin/pytest`
does not put the repo root on `sys.path` — pytest inserts `tests/` instead, since `tests/` has no
`__init__.py` — and every import of the package fails.

**Do not solve this by installing the package.** `pip install -e .` would work locally but puts the
import mechanism in undeclared venv state rather than in a committed file, so a fresh clone breaks.
It also drags in `[build-system]` and `[tool.setuptools]` sections to satisfy setuptools flat-layout
discovery, and leaves an untracked `coldstart.egg-info/`. For a project whose entire claim is
reproducibility, the import path must be committed. `pythonpath` requires pytest ≥ 7.0 (core, not a
plugin) and is resolved relative to rootdir, so it holds regardless of the directory tests are run
from.

- [ ] **Step 3: Create package dirs and a failing smoke test**

```bash
mkdir -p coldstart/analysis coldstart/stubs worker recon fixtures tests
touch coldstart/__init__.py coldstart/analysis/__init__.py coldstart/stubs/__init__.py
```

`tests/test_smoke.py`:

```python
from coldstart import SCHEMA_VERSION


def test_schema_version_is_an_int():
    assert isinstance(SCHEMA_VERSION, int)
```

- [ ] **Step 4: Run it and confirm it fails**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: FAIL — `ImportError: cannot import name 'SCHEMA_VERSION'`

- [ ] **Step 5: Make it pass**

`coldstart/__init__.py`:

```python
SCHEMA_VERSION = 1
```

- [ ] **Step 6: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 7: Add venv to .gitignore and commit**

```bash
printf '.venv/\n__pycache__/\n*.pyc\n' >> .gitignore
git add pyproject.toml coldstart tests .gitignore
git commit -m "chore: scaffold coldstart package with pytest and ruff"
```

---

## Task 2: Stage recorder (clock B)

**TEACH — grounds §9b Module 7 (monotonic vs wall clocks).** After this task, show the user that two successive `time.time()` calls can move backwards under a clock adjustment while `time.monotonic()` cannot, and that `t0_wall` exists only for correlation, never for arithmetic.

**Files:**
- Create: `coldstart/recorder.py`, `tests/test_recorder.py`

- [ ] **Step 1: Write the failing test**

`tests/test_recorder.py`:

```python
import pytest
from coldstart.recorder import StageRecorder


def test_marks_are_monotonic_and_relative_to_t0():
    r = StageRecorder(clock=iter([100.0, 100.5, 101.25]).__next__)
    r.start()
    r.mark("S1")
    r.mark("S2")
    b = r.bundle()
    assert b["marks"] == [{"stage": "S1", "t_mono": 0.5}, {"stage": "S2", "t_mono": 1.25}]


def test_duration_between_two_stages():
    r = StageRecorder(clock=iter([10.0, 12.0, 15.0]).__next__)
    r.start()
    r.mark("S1")
    r.mark("S2")
    assert r.duration("S1", "S2") == 3.0


def test_mark_before_start_is_an_error():
    r = StageRecorder()
    with pytest.raises(RuntimeError):
        r.mark("S1")


def test_duplicate_stage_is_an_error():
    r = StageRecorder(clock=iter([0.0, 1.0, 2.0]).__next__)
    r.start()
    r.mark("S1")
    with pytest.raises(ValueError):
        r.mark("S1")
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_recorder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.recorder'`

- [ ] **Step 3: Implement**

`coldstart/recorder.py`:

```python
import time


class StageRecorder:
    """Clock B. Monotonic marks relative to t0.

    Wall time is captured once at start for correlation with other clocks only.
    It is never used for arithmetic — see spec 6.5 rule 1.
    """

    def __init__(self, clock=time.monotonic, wall_clock=time.time):
        self._clock = clock
        self._wall_clock = wall_clock
        self._t0 = None
        self._t0_wall = None
        self._marks: list[dict] = []

    def start(self) -> None:
        self._t0 = self._clock()
        self._t0_wall = self._wall_clock()

    def mark(self, stage: str) -> float:
        if self._t0 is None:
            raise RuntimeError("start() must be called before mark()")
        if any(m["stage"] == stage for m in self._marks):
            raise ValueError(f"stage {stage!r} already marked")
        t = self._clock() - self._t0
        self._marks.append({"stage": stage, "t_mono": t})
        return t

    def at(self, stage: str) -> float:
        for m in self._marks:
            if m["stage"] == stage:
                return m["t_mono"]
        raise KeyError(stage)

    def duration(self, start_stage: str, end_stage: str) -> float:
        return self.at(end_stage) - self.at(start_stage)

    def bundle(self) -> dict:
        return {"t0_wall": self._t0_wall, "marks": list(self._marks)}
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_recorder.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/recorder.py tests/test_recorder.py
git commit -m "feat: stage recorder with monotonic clock B marks"
```

---

## Task 3: Run record schema and JSONL store

**Files:**
- Create: `coldstart/schema.py`, `coldstart/store.py`, `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:

```python
import json

from coldstart.schema import SCHEMA_VERSION, RunRecord
from coldstart.store import JsonlStore


def make_record(run_id="r1", run_index=0, arm="A"):
    return RunRecord(
        run_id=run_id,
        run_index=run_index,
        arm=arm,
        clock_A={"t_submit": 1000.0, "t_result": 1090.0},
        clock_C={},
        clock_B={"t0_wall": 1000.4, "marks": [{"stage": "S1", "t_mono": 2.0}]},
        warmup=[],
        engine={},
        host={"host_id": "h1", "first_touch": True},
        config={"vllm_version": "0.0.0"},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_every_field_survives_the_round_trip(tmp_path):
    path = tmp_path / "runs.jsonl"
    store = JsonlStore(path)
    store.append(make_record())

    on_disk = json.loads(path.read_text().strip())
    assert on_disk["run_id"] == "r1"
    assert on_disk["run_index"] == 0
    assert on_disk["arm"] == "A"
    assert on_disk["clock_A"] == {"t_submit": 1000.0, "t_result": 1090.0}
    assert on_disk["clock_B"] == {"t0_wall": 1000.4, "marks": [{"stage": "S1", "t_mono": 2.0}]}
    assert on_disk["clock_C"] == {}
    assert on_disk["warmup"] == []
    assert on_disk["engine"] == {}
    assert on_disk["host"] == {"host_id": "h1", "first_touch": True}
    assert on_disk["config"] == {"vllm_version": "0.0.0"}
    assert on_disk["status"] == {"outcome": "ok", "failure_class": None, "failure_detail": None}
    assert on_disk["schema_version"] == SCHEMA_VERSION
    assert set(on_disk) == set(RunRecord.__dataclass_fields__)

    assert store.read_all()[0].to_dict() == on_disk


def test_append_is_additive(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    store.append(make_record("r1", 0, "A"))
    store.append(make_record("r2", 1, "B"))
    assert [r.run_id for r in store.read_all()] == ["r1", "r2"]


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "runs.jsonl"
    path.write_text('{"schema_version": 999, "run_id": "x"}\n')
    store = JsonlStore(path)
    try:
        store.read_all()
    except ValueError as e:
        assert "999" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_missing_file_reads_as_empty(tmp_path):
    assert JsonlStore(tmp_path / "nope.jsonl").read_all() == []


def test_fields_from_a_newer_build_are_ignored(tmp_path):
    path = tmp_path / "runs.jsonl"
    rec = make_record().to_dict()
    rec["field_from_the_future"] = 42
    path.write_text(json.dumps(rec) + "\n")
    got = JsonlStore(path).read_all()
    assert len(got) == 1
    assert got[0].run_id == "r1"


def test_parent_directories_are_created(tmp_path):
    store = JsonlStore(tmp_path / "deep" / "nested" / "runs.jsonl")
    store.append(make_record())
    assert len(store.read_all()) == 1
```

**On the round-trip assertion, and a trap worth understanding.** `RunRecord` is the contract
between four components that never share memory — a probe in a container, a driver on a laptop,
the store, and the analysis layer. A serialization bug there surfaces as inexplicable analysis
results, not a failing test, so this assertion has to be thorough.

The obvious form is `assert got.to_dict() == original.to_dict()`, and **it does not work.** If
`to_dict()` is itself broken, both sides are corrupted identically and compare equal — the test
uses the very method it is trying to verify. It was written that way first and a mutation
corrupting `run_index` passed it.

The fix is to break the symmetry: assert the **on-disk JSON against literal expected values**, so
nothing under test appears on both sides of the comparison. `set(on_disk) == set(RunRecord.__dataclass_fields__)`
then catches a silently dropped field, and the final line confirms the read path reproduces what
was written. This is the same principle as the harness itself — compare against an independent
reference, not against another output of the thing you are measuring.

The other three cover paths the driver will exercise on its very first call: reading before any
run exists, reading a record written by a newer build, and creating a nested output directory.

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.schema'`

- [ ] **Step 3: Implement the schema**

`coldstart/schema.py`:

```python
from dataclasses import asdict, dataclass, field

from coldstart import SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "RunRecord"]


@dataclass
class RunRecord:
    """One measurement run. The interface between worker, driver, store, analysis."""

    run_id: str
    run_index: int
    arm: str
    clock_A: dict
    clock_C: dict
    clock_B: dict
    warmup: list
    engine: dict
    host: dict
    config: dict
    status: dict
    schema_version: int = field(default=SCHEMA_VERSION)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunRecord":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {d.get('schema_version')!r}; "
                f"this build reads {SCHEMA_VERSION}"
            )
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
```

- [ ] **Step 4: Implement the store**

`coldstart/store.py`:

```python
import json
from pathlib import Path

from coldstart.schema import RunRecord


class JsonlStore:
    """Append-only. Never rewrites or deletes a record — see spec 6.6."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: RunRecord) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def read_all(self) -> list[RunRecord]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(RunRecord.from_dict(json.loads(line)))
        return out
```

- [ ] **Step 5: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: PASS — 6 passed

- [ ] **Step 6: Commit**

```bash
git add coldstart/schema.py coldstart/store.py tests/test_store.py
git commit -m "feat: versioned run record schema and append-only JSONL store"
```

---

### Deferred from Task 3 — partial-write handling

Two review findings were deliberately not fixed in Task 3, recorded here so they are not lost:

- `read_all` raises a bare `JSONDecodeError` with no line number when a record is malformed.
- Blank or truncated lines are skipped silently rather than reported.

Both are the same underlying gap: the store has no story for a **partially written final line**,
which is a real possibility for an append-only file being written during a long GPU campaign that
gets interrupted. The right fix is not a `try/except` bolted onto `read_all` — it is deciding
whether a truncated tail line should be dropped with a warning or should fail the load outright,
which is a data-integrity decision, not an ergonomics one.

Address it in Task 15, where the driver's failure handling is specified and the answer becomes
obvious in context. Until then the campaign is small enough that a corrupt file would be noticed
immediately.

---

## Task 4: Scheduler — interleaved randomized triples

**TEACH — grounds §9b Module 9 (confounding and interleaving).** After this task, print a blocked sequence (`AAA...BBB...CCC...`) next to the interleaved one and have the user say what a platform slowdown at 3pm would do to each.

**Files:**
- Create: `coldstart/scheduler.py`, `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:

```python
from collections import Counter

from coldstart.scheduler import build_schedule


def test_each_triple_contains_each_arm_exactly_once():
    sched = build_schedule(arms=["A", "B", "C"], triples=10, seed=1)
    assert len(sched) == 30
    for i in range(0, 30, 3):
        assert sorted(s.arm for s in sched[i : i + 3]) == ["A", "B", "C"]


def test_run_index_and_triple_index_are_sequential():
    sched = build_schedule(arms=["A", "B", "C"], triples=4, seed=1)
    assert [s.run_index for s in sched] == list(range(12))
    assert [s.triple_index for s in sched[:6]] == [0, 0, 0, 1, 1, 1]


def test_same_seed_is_reproducible_and_different_seed_is_not():
    a = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=7)]
    b = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=7)]
    c = [s.arm for s in build_schedule(["A", "B", "C"], 20, seed=8)]
    assert a == b
    assert a != c


def test_arms_are_balanced_overall():
    sched = build_schedule(["A", "B", "C"], 30, seed=3)
    assert Counter(s.arm for s in sched) == {"A": 30, "B": 30, "C": 30}


def test_arm_order_varies_between_triples():
    sched = build_schedule(["A", "B", "C"], 30, seed=5)
    first_of_each_triple = [sched[i].arm for i in range(0, 90, 3)]
    assert len(set(first_of_each_triple)) == 3, "every triple began with the same arm"


def test_all_six_permutations_occur_about_equally():
    """Non-degeneracy is not randomization.

    A cyclic rotation, a first-position bias, and a naive Fisher-Yates all pass every
    other test in this file while destroying the property interleaving exists to give.
    Only uniformity over all six permutations catches them.
    """
    n = 30000
    sched = build_schedule(["A", "B", "C"], n, seed=11)
    counts = Counter("".join(s.arm for s in sched[i : i + 3]) for i in range(0, 3 * n, 3))
    assert len(counts) == 6, f"only {len(counts)} of 6 permutations occurred"
    expected = n / 6
    tolerance = 5 * (n * (1 / 6) * (5 / 6)) ** 0.5  # 5 standard deviations
    for perm, got in sorted(counts.items()):
        assert abs(got - expected) < tolerance, f"{perm}: {got}, expected ~{expected:.0f}"


def test_a_fixed_seed_reproduces_a_known_schedule():
    """The pre-registered seed must reproduce the published schedule across refactors."""
    sched = build_schedule(["A", "B", "C"], 4, seed=5)
    assert [s.arm for s in sched] == ["A", "B", "C", "A", "B", "C", "B", "A", "C", "C", "A", "B"]
```

**Why four tests are not enough here, and this matters more than anywhere else in the plan.**
Interleaving is the single most important validity decision in the experiment, and the obvious
tests pin the wrong thing. Mutation testing found three changes that pass composition, balance,
seed-reproducibility, and first-position non-degeneracy while destroying randomization:

| Mutation | Detection by the first five tests | Damage |
|---|---|---|
| Cyclic rotation only | **0%** across 20,000 seeds | Only 3 of 6 permutations. First position stays uniform, so nothing fires — but arm B follows arm A 78% of the time versus 44% correct. On rented hardware where run 1 may warm the host for runs 2 and 3, that confounds carryover with arm |
| First-position bias (A ~93%) | 59% of seeds, **and seed 5 survives** | Biases the dependent variable directly, since position-within-triple is where cold-start time lives |
| Naive Fisher-Yates | **0%** | The most likely real implementation error of the three |

Only uniformity over all six permutations catches them. Verified: the correct implementation
deviates by at most 36 against a tolerance of 323, so the test is deterministic rather than
flaky, and the whole suite still runs in under a tenth of a second.

The golden-schedule test exists for the reproducibility claim — nothing else pins the concrete
seed-to-schedule mapping, so a refactor of the shuffle call would silently change which schedule
a published seed produces.

**Deferred deliberately:** behaviour outside the 3-arm case is unconstrained, `triple_index`
computed as `idx // 3` survives (identical for 3 arms, wrong for any other count), and negative
`triples` silently returns an empty schedule rather than erroring. Add the guard when `driver.py`
lands in Task 15 and a real caller exists.

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.scheduler'`

- [ ] **Step 3: Implement**

`coldstart/scheduler.py`:

```python
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledRun:
    run_index: int
    triple_index: int
    arm: str


def build_schedule(arms: list[str], triples: int, seed: int) -> list[ScheduledRun]:
    """Interleaved, randomized within each triple.

    Blocking all of one arm together would confound the intervention with
    time-varying platform conditions — see spec 5, sample plan.
    """
    rng = random.Random(seed)
    out: list[ScheduledRun] = []
    idx = 0
    for t in range(triples):
        order = list(arms)
        rng.shuffle(order)
        for arm in order:
            out.append(ScheduledRun(run_index=idx, triple_index=t, arm=arm))
            idx += 1
    return out
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_scheduler.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/scheduler.py tests/test_scheduler.py
git commit -m "feat: interleaved randomized triple scheduler"
```

---

## Task 5: Minimal reconnaissance worker image

This container exists only to capture reality. It starts `vllm serve`, saves every log line verbatim, hits the server once, and returns the raw text. No parsing, no measurement.

**Files:**
- Create: `worker/Dockerfile`, `worker/recon_handler.py`, `worker/requirements.txt`

- [ ] **Step 1: Write the recon handler**

`worker/recon_handler.py`:

```python
"""Reconnaissance handler. Captures raw engine output. Measures nothing."""

import os
import subprocess
import threading
import time

import requests
import runpod

MODEL = os.environ["MODEL_ID"]
PORT = 8000


def _wait_healthy(timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def handler(job):
    lines: list[str] = []
    proc = subprocess.Popen(
        ["vllm", "serve", MODEL, "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    def drain():
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))

    drain_thread = threading.Thread(target=drain, daemon=True)
    drain_thread.start()

    healthy = False
    completion = None
    try:
        healthy = _wait_healthy()
        if healthy:
            r = requests.post(
                f"http://127.0.0.1:{PORT}/v1/completions",
                json={"model": MODEL, "prompt": "Hello", "max_tokens": 4},
                timeout=120,
            )
            completion = r.json()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        # stdout reaches EOF only once the process is gone; join so the drain
        # thread finishes appending before we read `lines`.
        drain_thread.join(timeout=15)

    return {
        "healthy": healthy,
        "log_lines": lines,
        "completion": completion,
        "drain_completed": not drain_thread.is_alive(),
        "env": {
            "MODEL_ID": MODEL,
            "VLLM_CACHE_ROOT": os.environ.get("VLLM_CACHE_ROOT"),
            "HOME": os.environ.get("HOME"),
        },
        "cache_dirs": {
            p: sorted(os.listdir(p))[:50]
            for p in ["/root/.cache", "/root/.cache/vllm"]
            if os.path.isdir(p)
        },
    }


runpod.serverless.start({"handler": handler})
```

- [ ] **Step 2: Write requirements and Dockerfile**

`worker/requirements.txt`:

```
runpod
requests
```

`worker/Dockerfile`:

```dockerfile
# Pinned by digest rather than tag. The artifact's reproducibility claim requires that
# a reader rebuilding this image gets the same engine, and `latest` drifts. Resolved
# 2026-08-19 from vllm/vllm-openai:latest; the vLLM version inside is recorded by the
# reconnaissance run and published alongside the results.
ARG VLLM_DIGEST=sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
FROM vllm/vllm-openai@${VLLM_DIGEST}

ENV HF_HOME=/runpod-volume/hf
ENV VLLM_CACHE_ROOT=/root/.cache/vllm
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt

COPY recon_handler.py /opt/recon_handler.py
COPY probe.py /opt/probe.py
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/recon_handler.py"]
```

- [ ] **Step 3: Create placeholder probe and handler so the image builds**

```bash
printf '# filled in Task 12\n' > worker/probe.py
printf '# filled in Task 13\n' > worker/handler.py
```

- [ ] **Step 4: Validate the Dockerfile without building it**

Run: `docker build --check --platform linux/amd64 -t coldstart-recon:dev worker/`
Expected: syntax validated, warnings reported, nothing executed.

**Do not run a full build here.** The vLLM base image is many gigabytes, cross-building for
`linux/amd64` on Apple Silicon is slow, and the image has to be built for real when it is pushed
to a registry in Task 6 anyway. A full build now spends significant time and disk to learn
something Task 6 learns for free.

If the Docker daemon is not running, record the Dockerfile as **unvalidated** and move on rather
than starting Docker. The first real build in Task 6 will surface any syntax error, cheaply.

**Pin the base image by digest, not by tag.** `latest` moves, and the artifact claims a pinned
engine version — a reader who rebuilds this image months later must get the same vLLM. Resolve the
digest with `docker buildx imagetools inspect vllm/vllm-openai:latest` and use the multi-platform
manifest-list digest, which selects the right architecture under `--platform`. The vLLM version
*inside* that image is then read from the reconnaissance capture and published with the results;
the digest guarantees the image, the capture identifies what it contains.

**On the draining thread.** The handler starts the drain thread *before* the `try` block and
joins it in `finally`, after the process has exited. This is not stylistic. `proc.stdout` reaches
EOF only once the process is gone, so terminating without joining can drop the tail of the log —
and this container's whole purpose is capturing a complete startup log to commit as fixtures.
A dropped line would produce a fixture that silently omits a phase, and every downstream parser
is built against that capture. `drain_completed` is returned so a truncated capture announces
itself instead of being trusted.

- [ ] **Step 5: Commit**

```bash
git add worker/
git commit -m "feat: reconnaissance worker image that captures raw engine output"
```

---

## Task 6: Reconnaissance run — FIRST PAID STEP

**TEACH — grounds §9b Modules 3, 4, 5, 6.** This is the first time real engine output exists. Walk the captured log with the user line by line: find the memory-profiling pass, the KV block count, the graph capture, and whether a compile step appears. These modules are much easier to teach against actual output than in the abstract.

**Human setup required before this task** — these cannot be automated:
1. Create a RunPod account and generate an API key.
2. Push the image to a registry RunPod can pull from.
3. Create a serverless endpoint pinned to one 24 GB GPU type and one region.
4. Create a network volume and note its mount path.
5. Export `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`.

**Files:**
- Create: `recon/capture.py`, `fixtures/README.md`

- [ ] **Step 1: Write the capture script**

`recon/capture.py`:

```python
"""Reconnaissance capture. Submits a few jobs and saves everything verbatim.

Publishes nothing. The sample is far too small and the config is not frozen.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.runpod.ai/v2"
KEY = os.environ["RUNPOD_API_KEY"]
ENDPOINT = os.environ["RUNPOD_ENDPOINT_ID"]
OUT = Path("fixtures")


def submit(payload: dict) -> str:
    r = requests.post(
        f"{API}/{ENDPOINT}/run",
        headers={"Authorization": f"Bearer {KEY}"},
        json={"input": payload},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def poll(job_id: str, timeout=1800) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(
            f"{API}/{ENDPOINT}/status/{job_id}",
            headers={"Authorization": f"Bearer {KEY}"},
            timeout=30,
        )
        r.raise_for_status()
        last = r.json()
        if last.get("status") in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            return last
        time.sleep(5)
    return last or {"status": "POLL_TIMEOUT"}


def main(n: int) -> None:
    (OUT / "vllm_logs").mkdir(parents=True, exist_ok=True)
    (OUT / "runpod_api").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        print(f"[recon] submitting {i + 1}/{n}", flush=True)
        job_id = submit({"recon": True})
        status = poll(job_id)
        (OUT / "runpod_api" / f"status_{i}.json").write_text(json.dumps(status, indent=2))
        out = (status.get("output") or {})
        lines = out.get("log_lines") or []
        (OUT / "vllm_logs" / f"startup_{i}.log").write_text("\n".join(lines))
        print(f"[recon] {job_id} status={status.get('status')} log_lines={len(lines)}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
```

- [ ] **Step 2: Smoke test with a tiny model first**

Set the endpoint's `MODEL_ID` to a small checkpoint (for example `Qwen/Qwen3-0.6B`) and run:

Run: `.venv/bin/python recon/capture.py 1`
Expected: one `fixtures/runpod_api/status_0.json` and one `fixtures/vllm_logs/startup_0.log`, with `healthy: true` in the output. Cost: cents.

This proves the container, the endpoint, and the capture path work before spending on the real model.

- [ ] **Step 3: Capture with the pinned model**

Set `MODEL_ID` to the pinned Qwen3-8B revision, then:

Run: `.venv/bin/python recon/capture.py 3`
Expected: three log files and three status files. Cost: a few dollars.

- [ ] **Step 4: Answer the three reconnaissance questions in writing**

Read `fixtures/vllm_logs/startup_0.log` and `fixtures/runpod_api/status_0.json`, then record answers in `fixtures/README.md`:

```markdown
# Reconnaissance captures

Captured <DATE> against endpoint <ID>, GPU <TYPE>, region <REGION>,
image digest <DIGEST>, vLLM <VERSION>, model revision <HASH>.

Published as fixtures, not as results — sample size 3, configuration not frozen.

## Q1 — engine log format
Phase lines observed, verbatim, one per S4 sub-stage found:
- S4a device init: `<exact line>`
- S4b compilation: `<exact line or NOT PRESENT>`
- S4c memory profiling: `<exact line>`
- S4d KV allocation: `<exact line>`
- S4e graph capture: `<exact line or NOT PRESENT>`

Sub-stages this version does NOT delineate: <list — these get reported merged>

## Q2 — platform API lifecycle fields
Fields present in the status payload: <list>
queued-at exposed: yes/no
started-at exposed: yes/no
=> residual can be split into queue vs bring-up: yes/no

## Q3 — compile-at-startup
Does this version compile at startup: yes/no
Cache location observed: <path>
=> H3 and arm C: RETAINED / DROPPED
```

- [ ] **Step 5: Commit the fixtures**

```bash
git add fixtures/
git commit -m "chore: reconnaissance captures — real engine logs and API responses"
```

- [ ] **Step 6: If arm C was dropped, update the spec**

Only if Q3 answered "no": edit the spec's hypotheses section to record that H3 and arm C were dropped after reconnaissance, and change the scheduler call sites from three arms to two. The experiment reverts to the two-arm design with nothing else changed.

```bash
git add docs/superpowers/specs/2026-08-17-cold-start-decomposition-design.md
git commit -m "docs: drop H3 and arm C — pinned vLLM version does not compile at startup"
```

---

## Task 7: vLLM log parser

Patterns come from the real captures in Task 6. Write the test using **exact lines copied out of `fixtures/vllm_logs/startup_0.log`** — do not invent log text.

**Files:**
- Create: `coldstart/vllm_logs.py`, `tests/test_vllm_logs.py`

- [ ] **Step 1: Write the failing test against real fixture text**

`tests/test_vllm_logs.py`:

```python
from pathlib import Path

from coldstart.vllm_logs import parse_engine_log

FIXTURE = Path("fixtures/vllm_logs/startup_0.log")


def test_parses_the_real_capture():
    result = parse_engine_log(FIXTURE.read_text())
    # Every sub-phase this vLLM version delineates must be found.
    # Phases the version does not emit stay absent and are reported merged.
    assert result.phases, "no phases parsed from the real capture"
    for name, seconds in result.phases.items():
        assert name in {"S4a", "S4b", "S4c", "S4d", "S4e"}
        assert seconds >= 0.0


def test_extracts_kv_cache_blocks():
    result = parse_engine_log(FIXTURE.read_text())
    assert result.engine_info["kv_cache_blocks"] > 0


def test_unparseable_text_yields_empty_phases_not_an_exception():
    result = parse_engine_log("nothing useful here\nat all\n")
    assert result.phases == {}
    assert result.engine_info == {}


def test_merged_phases_are_reported():
    result = parse_engine_log(FIXTURE.read_text())
    assert isinstance(result.merged, list)
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_vllm_logs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.vllm_logs'`

- [ ] **Step 3: Implement, with patterns taken from the fixture**

`coldstart/vllm_logs.py`. Replace each `PATTERNS` regex with one matching the exact line recorded in `fixtures/README.md` Q1. Delete entries for sub-phases this version does not emit and list them in `MERGED`.

```python
import re
from dataclasses import dataclass, field

# Filled from fixtures/README.md Q1 — the lines this vLLM version actually emits.
# Each pattern must capture a float in group "sec".
PATTERNS: dict[str, re.Pattern] = {
    "S4c": re.compile(r"memory profiling.*took (?P<sec>[\d.]+) seconds", re.I),
    "S4e": re.compile(r"graph capturing finished in (?P<sec>[\d.]+) secs", re.I),
}

# Sub-phases this version does not delineate. Reported merged, never guessed apart.
MERGED: list[str] = ["S4a", "S4b", "S4d"]

KV_BLOCKS = re.compile(r"GPU KV cache size: (?P<blocks>[\d,]+) tokens", re.I)
BLOCK_SIZE = re.compile(r"block_size[=: ]+(?P<n>\d+)", re.I)


@dataclass
class ParsedLog:
    phases: dict[str, float] = field(default_factory=dict)
    engine_info: dict = field(default_factory=dict)
    merged: list[str] = field(default_factory=list)


def parse_engine_log(text: str) -> ParsedLog:
    """Extract S4 sub-phase durations and engine facts from vLLM startup output.

    Absence is never an error: a phase this version does not emit is simply not
    reported, and appears in `merged` instead. The bracketed S4 total from clock B
    stays authoritative — see spec 5, attribution caveat.
    """
    phases: dict[str, float] = {}
    for name, pat in PATTERNS.items():
        m = pat.search(text)
        if m:
            phases[name] = float(m.group("sec"))

    info: dict = {}
    m = KV_BLOCKS.search(text)
    if m:
        info["kv_cache_blocks"] = int(m.group("blocks").replace(",", ""))
    m = BLOCK_SIZE.search(text)
    if m:
        info["block_size"] = int(m.group("n"))

    return ParsedLog(phases=phases, engine_info=info, merged=list(MERGED) if phases else [])
```

- [ ] **Step 4: Run, adjust patterns until they match the real capture**

Run: `.venv/bin/pytest tests/test_vllm_logs.py -v`
Expected: PASS. If a pattern misses, print the fixture and fix the regex against the actual text — never edit the fixture to fit the regex.

- [ ] **Step 5: Commit**

```bash
git add coldstart/vllm_logs.py tests/test_vllm_logs.py
git commit -m "feat: vLLM startup log parser built against real captures"
```

---

## Task 8: RunPod API client (clock C)

**Files:**
- Create: `coldstart/runpod_api.py`, `tests/test_runpod_api.py`

- [ ] **Step 1: Write the failing test against the captured status payload**

`tests/test_runpod_api.py`:

```python
import json
from pathlib import Path

from coldstart.runpod_api import extract_lifecycle

FIXTURE = Path("fixtures/runpod_api/status_0.json")


def test_extracts_whatever_lifecycle_fields_exist():
    payload = json.loads(FIXTURE.read_text())
    life = extract_lifecycle(payload)
    assert isinstance(life, dict)
    for k in life:
        assert k in {"queued_at", "started_at", "completed_at", "delay_ms", "execution_ms"}


def test_missing_fields_are_absent_not_none():
    life = extract_lifecycle({"status": "COMPLETED"})
    assert life == {}


def test_residual_splittable_reports_honestly():
    from coldstart.runpod_api import residual_splittable

    assert residual_splittable({"delay_ms": 100, "execution_ms": 200}) is True
    assert residual_splittable({}) is False
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_runpod_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.runpod_api'`

- [ ] **Step 3: Implement**

Adjust `FIELD_MAP` to the field names actually present in `fixtures/runpod_api/status_0.json`.

`coldstart/runpod_api.py`:

```python
# Keys as they appear in the real status payload — see fixtures/README.md Q2.
FIELD_MAP = {
    "delayTime": "delay_ms",
    "executionTime": "execution_ms",
}


def extract_lifecycle(payload: dict) -> dict:
    """Clock C. Returns only fields the platform actually exposes.

    Absent fields are omitted rather than set to None, so downstream code can
    check presence without ambiguity — the residual split is opportunistic
    (spec 6.5) and the design must work if nothing useful is exposed.
    """
    out = {}
    for src, dst in FIELD_MAP.items():
        if src in payload and payload[src] is not None:
            out[dst] = payload[src]
    return out


def residual_splittable(lifecycle: dict) -> bool:
    """True when clock C can split T_platform into queue delay vs bring-up."""
    return "delay_ms" in lifecycle and "execution_ms" in lifecycle
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_runpod_api.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/runpod_api.py tests/test_runpod_api.py
git commit -m "feat: clock C lifecycle extraction from real API payloads"
```

---

## Task 9: Cache configuration — the one thing that differs between arms

**TEACH — grounds §9b Modules 1, 2, 5.** Show the user that this file is the *entire* difference between arms, and that a diff of arm behavior anywhere else in the codebase would invalidate the experiment.

**Files:**
- Create: `coldstart/cache_config.py`, `tests/test_cache_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cache_config.py`:

```python
import pytest

from coldstart.cache_config import CACHE_CONFIGS, resolve


def test_three_arms_exist():
    assert sorted(CACHE_CONFIGS) == ["A", "B", "C"]


def test_arm_a_is_fully_cold():
    c = resolve("A")
    assert c.weights_source == "hub"
    assert c.compile_cache_warm is False


def test_arm_b_caches_weights_only():
    c = resolve("B")
    assert c.weights_source == "volume"
    assert c.compile_cache_warm is False


def test_arm_c_caches_both():
    c = resolve("C")
    assert c.weights_source == "volume"
    assert c.compile_cache_warm is True


def test_env_differs_only_in_cache_variables():
    envs = {arm: set(resolve(arm).env().keys()) for arm in CACHE_CONFIGS}
    assert envs["A"] == envs["B"] == envs["C"], "arms must set the same variables"


def test_unknown_arm_is_an_error():
    with pytest.raises(KeyError):
        resolve("Z")
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_cache_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.cache_config'`

- [ ] **Step 3: Implement**

`coldstart/cache_config.py`:

```python
from dataclasses import dataclass

VOLUME_ROOT = "/runpod-volume"


@dataclass(frozen=True)
class CacheConfig:
    """The single interface that differs between arms — see spec 6.3.

    If arm behavior diverges anywhere else in this codebase, the single-variable
    claim is false and the experiment is compromised.
    """

    arm: str
    weights_source: str  # "hub" | "volume"
    compile_cache_warm: bool

    def env(self) -> dict[str, str]:
        """Every arm sets the same variable names. Only values differ."""
        if self.weights_source == "volume":
            hf_home = f"{VOLUME_ROOT}/hf"
        else:
            hf_home = "/tmp/hf-cold"

        if self.compile_cache_warm:
            cache_root = f"{VOLUME_ROOT}/vllm-cache"
        else:
            cache_root = "/tmp/vllm-cache-cold"

        return {"HF_HOME": hf_home, "VLLM_CACHE_ROOT": cache_root}


CACHE_CONFIGS = {
    "A": CacheConfig("A", weights_source="hub", compile_cache_warm=False),
    "B": CacheConfig("B", weights_source="volume", compile_cache_warm=False),
    "C": CacheConfig("C", weights_source="volume", compile_cache_warm=True),
}


def resolve(arm: str) -> CacheConfig:
    return CACHE_CONFIGS[arm]
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_cache_config.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/cache_config.py tests/test_cache_config.py
git commit -m "feat: cache configuration as the single inter-arm difference"
```

---

## Task 10: Consistency checks, residual, failure classification

**TEACH — grounds §9b Modules 6, 7, 11.** Walk the three clock-discipline rules against this code, and show why `retry_in_place` does not exist as a function anywhere.

**Files:**
- Create: `coldstart/checks.py`, `tests/test_checks.py`

**Hardening folded in after code review.** The first version of this task accepted NaN as a
valid run: every IEEE-754 comparison against NaN is false, so a NaN in either clock fell
through `residual < 0`, `t_process > t_total` and the floor check straight to the accept
path, and `store.py` round-trips NaN through JSON unchanged. A missing clock-B mark would
have been published rather than discarded. Inputs are now validated. Also fixed: the bare
`"oom"` needle matched inside `"no room left on device"`, filing an ENOSPC failure in the
out-of-memory bucket; `check_consistency` returned a bare 2-tuple, which is always truthy,
so `if check_consistency(...)` accepted every run including the violations; and the discard
reason was free-form prose that downstream tabulation would have had to substring-match.

- [ ] **Step 1: Write the failing test**

`tests/test_checks.py`:

```python
import json

import pytest

from coldstart.checks import (
    _SIGNATURES,
    DiscardReason,
    FailureClass,
    check_consistency,
    classify_failure,
    compute_residual,
)


def test_residual_is_total_minus_process():
    assert compute_residual(t_total=100.0, t_process=70.0) == 30.0


def test_consistency_passes_when_process_fits_inside_total():
    result = check_consistency(t_total=100.0, t_process=70.0, rtt_floor=0.5)
    assert result.ok is True
    assert result.reason is None
    assert result.discard_reason is None
    assert bool(result) is True


def test_consistency_fails_when_process_exceeds_total():
    result = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    assert result.ok is False
    assert "exceeds" in result.reason
    assert result.discard_reason is DiscardReason.PROCESS_EXCEEDS_TOTAL
    assert bool(result) is False


def test_consistency_fails_when_residual_is_below_the_rtt_floor():
    result = check_consistency(t_total=70.2, t_process=70.0, rtt_floor=0.5)
    assert result.ok is False
    assert "rtt_floor" in result.reason
    assert result.discard_reason is DiscardReason.RESIDUAL_BELOW_RTT_FLOOR
    assert bool(result) is False


def test_negative_residual_is_never_silently_returned():
    with pytest.raises(ValueError):
        compute_residual(t_total=50.0, t_process=70.0)


def test_failure_classification():
    assert classify_failure("CUDA out of memory") is FailureClass.OOM
    assert classify_failure("health check timed out") is FailureClass.HEALTH_TIMEOUT
    assert classify_failure("could not download weights") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("image pull backoff") is FailureClass.IMAGE_PULL
    assert classify_failure("no workers available") is FailureClass.PROVISIONING_TIMEOUT
    assert classify_failure("failed to initialize") is FailureClass.ENGINE_INIT
    assert classify_failure("first token timed out") is FailureClass.TTFT_TIMEOUT
    assert classify_failure("submit failed") is FailureClass.SUBMIT_ERROR
    assert classify_failure("something nobody predicted") is FailureClass.UNKNOWN


def test_every_failure_class_except_unknown_is_reachable():
    """A taxonomy with unreachable members is a taxonomy that lies about coverage.

    Without this, deleting a signature row is invisible: the deleted class simply
    stops being produced and every other test still passes.
    """
    reachable = {classify_failure(n.text) for _, needles in _SIGNATURES for n in needles}
    assert reachable == set(FailureClass) - {FailureClass.UNKNOWN}


# --- C1: non-finite / negative clock readings must raise, not be silently
# accepted. NaN compares False against every operator, so without an
# explicit isfinite guard `residual < 0`, `t_process > t_total`, and
# `< rtt_floor` all fall through to the accept path.


@pytest.mark.parametrize(
    "t_total,t_process",
    [
        (float("nan"), 10.0),
        (100.0, float("nan")),
        (float("inf"), 10.0),
        (100.0, float("inf")),
        (100.0, -5.0),
        (-5.0, 100.0),
    ],
)
def test_compute_residual_rejects_non_finite_and_negative_inputs(t_total, t_process):
    with pytest.raises(ValueError):
        compute_residual(t_total=t_total, t_process=t_process)


@pytest.mark.parametrize(
    "t_total,t_process",
    [
        (float("nan"), 10.0),
        (100.0, float("nan")),
        (float("inf"), 10.0),
        (100.0, -5.0),
    ],
)
def test_check_consistency_rejects_non_finite_and_negative_inputs(t_total, t_process):
    with pytest.raises(ValueError):
        check_consistency(t_total=t_total, t_process=t_process, rtt_floor=0.5)


# --- C2: DEFAULT_RTT_FLOOR must actually be exercised by at least one test
# that omits the rtt_floor kwarg.


def test_check_consistency_uses_default_rtt_floor_when_not_supplied():
    below = check_consistency(t_total=100.04, t_process=100.0)
    assert below.ok is False

    above = check_consistency(t_total=100.06, t_process=100.0)
    assert above.ok is True


# --- I3: pin the accept/reject boundary exactly at rtt_floor.


def test_check_consistency_boundary_at_exactly_rtt_floor():
    result = check_consistency(t_total=100.5, t_process=100.0, rtt_floor=0.5)
    assert result.ok is True


def test_check_consistency_boundary_just_below_rtt_floor():
    result = check_consistency(t_total=100.49, t_process=100.0, rtt_floor=0.5)
    assert result.ok is False


def test_check_consistency_boundary_just_above_rtt_floor():
    result = check_consistency(t_total=100.51, t_process=100.0, rtt_floor=0.5)
    assert result.ok is True


# --- I5: the bare "oom" needle must be word-boundary anchored, not a raw
# substring match.


def test_oom_needle_does_not_match_substring_inside_another_word():
    assert classify_failure("no room left on device") is FailureClass.UNKNOWN


def test_oom_needle_does_not_match_inside_unrelated_word():
    assert classify_failure("vroom vroom, engines starting") is FailureClass.UNKNOWN


# --- I4: row order in _SIGNATURES is a priority policy (root cause beats
# symptom); pin it with a deliberately multi-signal string.


def test_signature_priority_prefers_root_cause_over_symptom():
    detail = "EngineCore failed to initialize: CUDA out of memory"
    assert classify_failure(detail) is FailureClass.OOM


# --- I7: classification must be case-insensitive.


def test_classify_failure_is_case_insensitive():
    assert classify_failure("ERROR: Out Of Memory") is FailureClass.OOM


# --- I6: every needle must have a real (non-reachability-test) assertion.
# 8 of the 15 needles are already exercised by test_failure_classification
# and the priority/case tests above; these cover the remaining 7.
#
# These wrapper strings are synthetic — real engine failure text arrives
# with the Task 6 reconnaissance fixtures. They only confirm the needle is
# wired to its class, not that the wrapping is realistic.


def test_classify_failure_covers_needles_not_exercised_elsewhere():
    assert classify_failure("worker exited: oom") is FailureClass.OOM
    assert classify_failure("probe failed: health timeout") is FailureClass.HEALTH_TIMEOUT
    assert classify_failure("error: failed to fetch") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("pull error: hf hub unreachable") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("registry error: manifest unknown") is FailureClass.IMAGE_PULL
    assert (
        classify_failure("scheduler: provisioning timed out")
        is FailureClass.PROVISIONING_TIMEOUT
    )
    assert classify_failure("startup: engine init failed") is FailureClass.ENGINE_INIT


# --- I9: check_consistency and compute_residual must agree at the boundary
# where t_process == t_total (residual is exactly zero, not negative).


def test_process_equal_to_total_is_a_zero_residual_not_a_violation():
    assert compute_residual(t_total=100.0, t_process=100.0) == 0.0
    result = check_consistency(t_total=100.0, t_process=100.0, rtt_floor=0.0)
    assert result.ok is True


# --- I10: discard reasons are a closed enum, not free-form prose swappable
# without a test noticing. Already pinned per-branch above; this locks the
# two members can't be confused with each other.


def test_discard_reasons_are_distinct_enum_members():
    exceeds = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    below_floor = check_consistency(t_total=70.2, t_process=70.0, rtt_floor=0.5)
    assert exceeds.discard_reason is not below_floor.discard_reason
    assert {exceeds.discard_reason, below_floor.discard_reason} == set(DiscardReason)


# --- I8: ConsistencyResult must be falsy exactly when the run is invalid,
# so `if check_consistency(...):` cannot silently accept a violation.


def test_check_consistency_result_is_falsy_when_invalid():
    result = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    assert not result


def test_check_consistency_result_is_truthy_when_valid():
    result = check_consistency(t_total=100.0, t_process=70.0, rtt_floor=0.5)
    assert result


# --- M11: StrEnum must serialize identically via str() and json.dumps().


def test_failure_class_str_and_json_serialization_agree():
    assert str(FailureClass.OOM) == "oom"
    assert f"{FailureClass.OOM}" == "oom"
    assert json.dumps(FailureClass.OOM) == '"oom"'


# --- M12: classify_failure's None path must actually be exercised.


def test_classify_failure_handles_none_detail():
    assert classify_failure(None) is FailureClass.UNKNOWN


# --- M13: the rtt_floor violation message must show both operands, not
# just the floor, so a marginal miss can be told apart from a gross one.


def test_rtt_floor_violation_message_includes_residual_and_floor():
    t_total, t_process, rtt_floor = 70.2, 70.0, 0.5
    residual = compute_residual(t_total=t_total, t_process=t_process)
    result = check_consistency(t_total=t_total, t_process=t_process, rtt_floor=rtt_floor)
    assert str(residual) in result.reason
    assert str(rtt_floor) in result.reason
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.checks'`

- [ ] **Step 3: Implement**

`coldstart/checks.py`:

```python
import math
import re
from enum import StrEnum
from typing import NamedTuple

# Clock A and clock B live on different machines. The residual absorbs the
# network round trip, so a residual smaller than this floor means the two
# clocks disagree — see spec 6.5 rule 3.
DEFAULT_RTT_FLOOR = 0.05


class FailureClass(StrEnum):
    SUBMIT_ERROR = "submit_error"
    PROVISIONING_TIMEOUT = "provisioning_timeout"
    IMAGE_PULL = "image_pull"
    WEIGHT_ACQUISITION = "weight_acquisition"
    OOM = "oom"
    ENGINE_INIT = "engine_init"
    HEALTH_TIMEOUT = "health_timeout"
    TTFT_TIMEOUT = "ttft_timeout"
    UNKNOWN = "unknown"


class DiscardReason(StrEnum):
    """Mirrors FailureClass: a closed taxonomy so a downstream reader can
    tabulate discards by class instead of substring-matching the free-form
    `reason` string that check_consistency also returns."""

    PROCESS_EXCEEDS_TOTAL = "process_exceeds_total"
    RESIDUAL_BELOW_RTT_FLOOR = "residual_below_rtt_floor"


class _Needle:
    """Plain substring match, unless `regex` is given for a needle short
    enough to misfire inside an unrelated word (e.g. "oom" inside "room")."""

    __slots__ = ("_regex", "text")

    def __init__(self, text: str, *, regex: re.Pattern[str] | None = None):
        self.text = text
        self._regex = regex

    def matches(self, low: str) -> bool:
        if self._regex is not None:
            return self._regex.search(low) is not None
        return self.text in low


# Row order is a priority policy, not incidental: classify_failure is
# first-match-wins, so when a failure string carries multiple signals the
# earliest matching row wins. Root cause outranks the symptom it commonly
# produces, e.g. OOM (root cause) is checked before ENGINE_INIT and
# HEALTH_TIMEOUT (symptoms an OOM often also trips).
_SIGNATURES = [
    (
        FailureClass.OOM,
        (_Needle("out of memory"), _Needle("oom", regex=re.compile(r"\boom\b"))),
    ),
    (
        FailureClass.HEALTH_TIMEOUT,
        (_Needle("health check timed out"), _Needle("health timeout")),
    ),
    (
        FailureClass.WEIGHT_ACQUISITION,
        (_Needle("download weights"), _Needle("failed to fetch"), _Needle("hf hub")),
    ),
    (FailureClass.IMAGE_PULL, (_Needle("image pull"), _Needle("manifest unknown"))),
    (
        FailureClass.PROVISIONING_TIMEOUT,
        (_Needle("no workers available"), _Needle("provisioning timed out")),
    ),
    (FailureClass.ENGINE_INIT, (_Needle("engine init"), _Needle("failed to initialize"))),
    (FailureClass.TTFT_TIMEOUT, (_Needle("first token timed out"),)),
    (FailureClass.SUBMIT_ERROR, (_Needle("submit failed"),)),
]


def classify_failure(detail: str | None) -> FailureClass:
    low = (detail or "").lower()
    for cls, needles in _SIGNATURES:
        if any(needle.matches(low) for needle in needles):
            return cls
    return FailureClass.UNKNOWN


def _validate_clock_inputs(t_total: float, t_process: float) -> None:
    """Guard both clock readings before any arithmetic — mirrors the
    precondition guards in StageRecorder.mark (coldstart/recorder.py).

    NaN compares False against every operator, so without this guard a NaN
    input falls through every check downstream and is silently accepted.
    """
    for name, value in (("t_total", t_total), ("t_process", t_process)):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value}")
        if value < 0:
            raise ValueError(f"{name} must be non-negative, got {value}")


def compute_residual(t_total: float, t_process: float) -> float:
    """The one permitted cross-clock subtraction — see spec 6.5 rule 2."""
    _validate_clock_inputs(t_total, t_process)
    residual = t_total - t_process
    if residual < 0:
        raise ValueError(
            f"negative residual: t_process={t_process} exceeds t_total={t_total}; "
            "this run must be discarded, not corrected"
        )
    return residual


class ConsistencyResult(NamedTuple):
    """`bool(result)` reflects `ok`, so `if check_consistency(...):` is
    correct for the one function whose job is to reject."""

    ok: bool
    reason: str | None
    discard_reason: DiscardReason | None

    def __bool__(self) -> bool:
        return self.ok


def check_consistency(
    t_total: float, t_process: float, rtt_floor: float = DEFAULT_RTT_FLOOR
) -> ConsistencyResult:
    """Apply the discard rule fixed in advance (spec 6.5 rule 3).

    Detects a violation and describes it; this function does not persist
    anything, so the caller is responsible for recording the result.
    """
    _validate_clock_inputs(t_total, t_process)
    if t_process > t_total:
        return ConsistencyResult(
            False,
            f"t_process {t_process} exceeds t_total {t_total}",
            DiscardReason.PROCESS_EXCEEDS_TOTAL,
        )
    # Single source of truth for the exceeds/negative-residual invariant —
    # see compute_residual above.
    residual = compute_residual(t_total, t_process)
    if residual < rtt_floor:
        return ConsistencyResult(
            False,
            f"residual {residual} below rtt_floor {rtt_floor}",
            DiscardReason.RESIDUAL_BELOW_RTT_FLOOR,
        )
    return ConsistencyResult(True, None, None)
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_checks.py -v`
Expected: PASS — 33 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/checks.py tests/test_checks.py
git commit -m "feat: clock consistency checks, residual, failure taxonomy"
```

---

## Task 11: Worker probe — the real measurement path

**Do not reimplement the warmup trio here.** `steady_state_latency`, `warmup_penalty` and
`time_to_fast_index` are pre-registered definitions and they live in
`coldstart/analysis/metrics.py` (Task 16), along with the `FAST_TOLERANCE` constant. Import
them. Two copies of a pre-registered parameter are two copies free to drift, and the one
that drifts silently is the one that gets published.

**Files:**
- Modify: `worker/probe.py` (replace placeholder)
- Create: `tests/test_probe_units.py`

- [ ] **Step 1: Write the failing test for the pure parts**

`tests/test_probe_units.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from probe import steady_state_latency, time_to_fast, warmup_penalty


WARMUP = [
    {"req_index": 0, "ttft": 2.0, "end_to_end": 6.0},
    {"req_index": 1, "ttft": 1.0, "end_to_end": 3.0},
    {"req_index": 2, "ttft": 0.6, "end_to_end": 2.2},
    {"req_index": 3, "ttft": 0.5, "end_to_end": 2.05},
    {"req_index": 4, "ttft": 0.5, "end_to_end": 2.0},
    {"req_index": 5, "ttft": 0.5, "end_to_end": 2.0},
    {"req_index": 6, "ttft": 0.5, "end_to_end": 2.0},
    {"req_index": 7, "ttft": 0.5, "end_to_end": 2.0},
    {"req_index": 8, "ttft": 0.5, "end_to_end": 2.0},
    {"req_index": 9, "ttft": 0.5, "end_to_end": 2.0},
]


def test_steady_state_is_median_of_last_three():
    assert steady_state_latency(WARMUP) == 2.0


def test_warmup_penalty_is_first_over_steady_state():
    assert warmup_penalty(WARMUP) == 3.0


def test_time_to_fast_finds_first_request_within_ten_percent():
    # 2.2 is 10% above 2.0 and qualifies; 3.0 does not.
    assert time_to_fast(WARMUP, tolerance=0.10) == 2


def test_time_to_fast_is_zero_when_the_replica_starts_fast():
    flat = [{"req_index": i, "ttft": 0.5, "end_to_end": 2.0} for i in range(10)]
    assert time_to_fast(flat, tolerance=0.10) == 0


def test_time_to_fast_none_branch_is_defensive_only():
    """Steady state is derived from the tail, so some request always qualifies.

    The None return is unreachable with well-formed input and exists so a
    malformed warmup list fails loudly rather than returning a wrong index.
    """
    assert time_to_fast([], tolerance=0.10) is None
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_probe_units.py -v`
Expected: FAIL — `ImportError: cannot import name 'steady_state_latency'`

- [ ] **Step 3: Implement the probe**

`worker/probe.py`:

```python
"""In-container probe. Clock B. Brackets `vllm serve` and drives warmup.

Runs the canonical server path as a subprocess rather than the Python engine API,
because the artifact must measure the startup path people actually deploy —
see spec 6.3.
"""

import os
import statistics
import subprocess
import threading
import time

import requests

PORT = 8000
WARMUP_REQUESTS = 10
MAX_TOKENS = 16
PROMPT = "Explain what a key-value cache does, in two sentences."


def steady_state_latency(warmup: list[dict]) -> float:
    """Median end-to-end latency of requests 8-10 — fixed before data (spec 7)."""
    return statistics.median(w["end_to_end"] for w in warmup[-3:])


def warmup_penalty(warmup: list[dict]) -> float:
    return warmup[0]["end_to_end"] / steady_state_latency(warmup)


def time_to_fast(warmup: list[dict], tolerance: float = 0.10) -> int | None:
    """Index of the first request within `tolerance` of steady state, else None."""
    if not warmup:
        return None
    threshold = steady_state_latency(warmup) * (1.0 + tolerance)
    for w in warmup:
        if w["end_to_end"] <= threshold:
            return w["req_index"]
    return None


def _wait_healthy(timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.25)
    return False


def _one_request(model: str) -> dict:
    t_start = time.monotonic()
    ttft = None
    with requests.post(
        f"http://127.0.0.1:{PORT}/v1/completions",
        json={"model": model, "prompt": PROMPT, "max_tokens": MAX_TOKENS, "stream": True},
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        for chunk in r.iter_lines():
            if chunk and ttft is None:
                ttft = time.monotonic() - t_start
    return {"ttft": ttft, "end_to_end": time.monotonic() - t_start}


def run_probe(recorder, model: str, health_timeout: float = 900.0) -> dict:
    """Returns the stage bundle. Caller owns the record assembly."""
    recorder.start()
    recorder.mark("S1_imports_done")

    log_lines: list[str] = []
    seen_load = False
    recorder.mark("S2_acquisition_start")
    proc = subprocess.Popen(
        ["vllm", "serve", model, "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )

    def drain():
        nonlocal seen_load
        for line in proc.stdout:
            log_lines.append(line.rstrip("\n"))
            # S3_load_done marks "weights resident on GPU" — the end of T_weights
            # (S2+S3). It is observable only from the engine's own log stream, so
            # the exact predicate comes from Task 7's fixtures and is filled in
            # there. Do NOT approximate it with S5_ready: S5 is on the far side of
            # all of S4, and folding the compile term into the weights term would
            # credit weight caching with the compile-cache saving.
            if _is_load_complete(line) and not seen_load:
                recorder.mark("S3_load_done")  # mark() rejects duplicates; guard first
                seen_load = True

    threading.Thread(target=drain, daemon=True).start()

    healthy = _wait_healthy(health_timeout)
    recorder.mark("S5_ready")
    if not healthy:
        proc.terminate()
        return {
            "healthy": False,
            "log_lines": log_lines,
            "warmup": [],
            "clock_B": recorder.bundle(),
        }

    warmup = []
    for i in range(WARMUP_REQUESTS):
        if i == 0:
            recorder.mark("S6_request1_dispatch")
        result = _one_request(model)
        if i == 0:
            recorder.mark("S6_first_token")
        warmup.append({"req_index": i, **result})
    recorder.mark("S7_warmup_done")

    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()

    return {
        "healthy": True,
        "log_lines": log_lines,
        "warmup": warmup,
        "clock_B": recorder.bundle(),
        "derived": {
            "steady_state_latency": steady_state_latency(warmup),
            "warmup_penalty": warmup_penalty(warmup),
            "time_to_fast_index": time_to_fast(warmup),
        },
    }
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_probe_units.py -v`
Expected: PASS — 7 passed

- [ ] **Step 5: Commit**

```bash
git add worker/probe.py tests/test_probe_units.py
git commit -m "feat: worker probe brackets vllm serve and drives ten warmup requests"
```

---

## Task 12: Worker handler

**Files:**
- Modify: `worker/handler.py` (replace placeholder), `worker/Dockerfile`

- [ ] **Step 1: Implement the handler**

`worker/handler.py`:

```python
"""RunPod serverless handler. Returns the stage bundle as the job result.

Telemetry rides the result channel rather than the log channel, so no run is
lost to log-retrieval failure — see spec 6.1.
"""

import os
import socket
import subprocess
import sys

import runpod

sys.path.insert(0, "/opt")

from probe import run_probe  # noqa: E402

sys.path.insert(0, "/opt/coldstart_pkg")

from coldstart.recorder import StageRecorder  # noqa: E402


def _gpu_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()
        name, driver = [p.strip() for p in out.split(",")[:2]]
    except Exception:
        name, driver = "unknown", "unknown"
    return {"gpu_model": name, "driver_version": driver, "host_id": socket.gethostname()}


def handler(job):
    model = os.environ["MODEL_ID"]
    recorder = StageRecorder()
    result = run_probe(recorder, model)
    result["host"] = _gpu_info()
    result["env_observed"] = {
        "HF_HOME": os.environ.get("HF_HOME"),
        "VLLM_CACHE_ROOT": os.environ.get("VLLM_CACHE_ROOT"),
    }
    result["compile_cache_observed"] = os.path.isdir(
        os.path.join(os.environ.get("VLLM_CACHE_ROOT", "/nonexistent"), "torch_compile_cache")
    )
    return result


runpod.serverless.start({"handler": handler})
```

- [ ] **Step 2: Stage the package next to the Dockerfile**

Docker can only copy from the build context, so the package is staged into `worker/` at build
time and gitignored — the source of truth stays at the repo root.

```bash
rm -rf worker/coldstart_pkg && mkdir -p worker/coldstart_pkg
cp -r coldstart worker/coldstart_pkg/coldstart
printf 'worker/coldstart_pkg/\n' >> .gitignore
```

- [ ] **Step 3: Update the Dockerfile**

In `worker/Dockerfile`, add this line immediately after the `COPY handler.py` line:

```dockerfile
COPY coldstart_pkg /opt/coldstart_pkg
```

and replace the final `CMD` line with:

```dockerfile
CMD ["python", "-u", "/opt/handler.py"]
```

- [ ] **Step 4: Build to verify**

Run: `docker build --platform linux/amd64 -t coldstart-worker:dev worker/`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add worker/handler.py worker/Dockerfile .gitignore
git commit -m "feat: serverless handler returning stage bundle via result channel"
```

---

## Task 13: Stub engine and stub endpoint — the GPU-free loop

**TEACH — grounds §9b Module 6.** The stub replays the *real* captured log, so the parser is exercised against reality with no GPU. Show the user that this is why the loop is trustworthy rather than a toy.

**Files:**
- Create: `coldstart/stubs/stub_engine.py`, `coldstart/stubs/stub_endpoint.py`, `tests/test_stubs.py`

- [ ] **Step 1: Write the failing test**

`tests/test_stubs.py`:

```python
from coldstart.stubs.stub_endpoint import StubEndpoint


def test_stub_returns_a_bundle_shaped_like_the_real_one():
    ep = StubEndpoint(seed=1)
    result = ep.run(arm="A")
    assert result["healthy"] is True
    assert len(result["warmup"]) == 10
    assert result["log_lines"], "stub must replay the real captured log"
    assert "clock_B" in result


def test_arms_produce_different_weight_times():
    ep = StubEndpoint(seed=1)
    a = ep.run(arm="A")["synthetic_truth"]["t_weights"]
    b = ep.run(arm="B")["synthetic_truth"]["t_weights"]
    assert a > b, "cold arm must be slower in the stub's ground truth"


def test_same_seed_reproduces():
    assert (
        StubEndpoint(seed=5).run(arm="A")["synthetic_truth"]
        == StubEndpoint(seed=5).run(arm="A")["synthetic_truth"]
    )
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_stubs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.stubs.stub_endpoint'`

- [ ] **Step 3: Implement the stub engine**

`coldstart/stubs/stub_engine.py`:

```python
from pathlib import Path

FIXTURE = Path("fixtures/vllm_logs/startup_0.log")


def replay_log_lines() -> list[str]:
    """Replay the real captured engine log so the parser sees reality, not invention."""
    if not FIXTURE.exists():
        raise FileNotFoundError(
            f"{FIXTURE} missing — run recon/capture.py (Task 6) before using the stub"
        )
    return FIXTURE.read_text().splitlines()
```

- [ ] **Step 4: Implement the stub endpoint**

`coldstart/stubs/stub_endpoint.py`:

```python
import random
import uuid

from coldstart.stubs.stub_engine import replay_log_lines

# Plausible ground truth in seconds. Values are arbitrary but ordered so the
# analysis has a known answer to recover.
ARM_PROFILE = {
    "A": {"t_weights": 95.0, "s4b": 40.0},
    "B": {"t_weights": 30.0, "s4b": 40.0},
    "C": {"t_weights": 30.0, "s4b": 3.0},
}


class StubEndpoint:
    """In-process stand-in for the RunPod endpoint. No network, no cost."""

    def __init__(self, seed: int = 0, hosts: int = 6):
        self._rng = random.Random(seed)
        self._hosts = [f"host-{i}" for i in range(hosts)]
        self._seen: set[str] = set()

    def run(self, arm: str) -> dict:
        prof = ARM_PROFILE[arm]
        jitter = self._rng.lognormvariate(0.0, 0.25)
        host = self._rng.choice(self._hosts)
        host_factor = 1.0 + 0.15 * self._hosts.index(host)

        t_weights = prof["t_weights"] * jitter * host_factor
        s4b = prof["s4b"] * jitter
        s1 = 4.0 * jitter
        s4_other = 25.0 * jitter
        t_process = s1 + t_weights + s4b + s4_other
        t_platform = 18.0 * self._rng.lognormvariate(0.0, 0.4)

        steady = 2.0
        warmup = []
        for i in range(10):
            penalty = 1.0 + 2.0 * (0.55**i)
            e2e = steady * penalty
            warmup.append({"req_index": i, "ttft": e2e * 0.25, "end_to_end": e2e})

        first_touch = host not in self._seen
        self._seen.add(host)

        marks = [
            {"stage": "S1_imports_done", "t_mono": s1},
            {"stage": "S2_acquisition_start", "t_mono": s1},
            {"stage": "S3_load_done", "t_mono": s1 + t_weights},
            {"stage": "S5_ready", "t_mono": s1 + t_weights + s4b + s4_other},
            {"stage": "S6_request1_dispatch", "t_mono": t_process},
            {"stage": "S6_first_token", "t_mono": t_process + warmup[0]["ttft"]},
            {"stage": "S7_warmup_done", "t_mono": t_process + sum(w["end_to_end"] for w in warmup)},
        ]

        return {
            "job_id": str(uuid.uuid4()),
            "healthy": True,
            "log_lines": replay_log_lines(),
            "warmup": warmup,
            "clock_B": {"t0_wall": 0.0, "marks": marks},
            "host": {"host_id": host, "gpu_model": "stub", "driver_version": "0", "first_touch": first_touch},
            "compile_cache_observed": arm == "C",
            "synthetic_truth": {
                "t_weights": t_weights,
                "t_process": t_process,
                "t_platform": t_platform,
            },
        }
```

- [ ] **Step 5: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_stubs.py -v`
Expected: PASS — 3 passed

- [ ] **Step 6: Commit**

```bash
git add coldstart/stubs tests/test_stubs.py
git commit -m "feat: GPU-free stub endpoint replaying real captured engine logs"
```

---

## Task 14: Job submitter (clock A)

**Files:**
- Create: `coldstart/submitter.py`, `tests/test_submitter.py`

- [ ] **Step 1: Write the failing test**

`tests/test_submitter.py`:

```python
from coldstart.stubs.stub_endpoint import StubEndpoint
from coldstart.submitter import StubSubmitter


def test_submitter_records_clock_a_and_returns_payload():
    sub = StubSubmitter(StubEndpoint(seed=2), clock=iter([1000.0, 1120.0]).__next__)
    outcome = sub.submit(arm="A")
    assert outcome.clock_A == {"t_submit": 1000.0, "t_result": 1120.0}
    assert outcome.payload["healthy"] is True
    assert outcome.error is None


def test_submit_failure_is_captured_not_raised():
    class Boom:
        def run(self, arm):
            raise RuntimeError("submit failed: endpoint unreachable")

    sub = StubSubmitter(Boom(), clock=iter([0.0, 1.0]).__next__)
    outcome = sub.submit(arm="A")
    assert outcome.payload is None
    assert "submit failed" in outcome.error
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_submitter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.submitter'`

- [ ] **Step 3: Implement**

`coldstart/submitter.py`:

```python
import time
from dataclasses import dataclass


@dataclass
class SubmitOutcome:
    clock_A: dict
    payload: dict | None
    error: str | None


class StubSubmitter:
    """Clock A against the in-process stub. Same interface as the real submitter."""

    def __init__(self, endpoint, clock=time.monotonic):
        self._endpoint = endpoint
        self._clock = clock

    def submit(self, arm: str) -> SubmitOutcome:
        t_submit = self._clock()
        try:
            payload = self._endpoint.run(arm=arm)
            error = None
        except Exception as e:  # failures are data — see spec 6.6
            payload, error = None, str(e)
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=payload,
            error=error,
        )
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_submitter.py -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/submitter.py tests/test_submitter.py
git commit -m "feat: clock A submitter with failures captured as data"
```

---

## Task 15: Driver — end-to-end orchestration

**Files:**
- Create: `coldstart/driver.py`, `tests/test_driver.py`

- [ ] **Step 1: Write the failing test**

`tests/test_driver.py`:

```python
from coldstart.driver import run_campaign
from coldstart.store import JsonlStore
from coldstart.stubs.stub_endpoint import StubEndpoint
from coldstart.submitter import StubSubmitter


def test_campaign_writes_one_record_per_scheduled_run(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=3)),
        store=store,
        arms=["A", "B", "C"],
        triples=5,
        seed=11,
    )
    records = store.read_all()
    assert len(records) == 15
    assert sorted({r.arm for r in records}) == ["A", "B", "C"]


def test_failed_runs_are_recorded_and_never_retried(tmp_path):
    class SometimesBroken:
        def __init__(self):
            self.calls = 0
            self._inner = StubEndpoint(seed=4)

        def run(self, arm):
            self.calls += 1
            if self.calls % 3 == 0:
                raise RuntimeError("health check timed out")
            return self._inner.run(arm=arm)

    ep = SometimesBroken()
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(ep),
        store=store,
        arms=["A", "B", "C"],
        triples=3,
        seed=1,
    )
    records = store.read_all()
    assert len(records) == 9, "every scheduled run yields exactly one record"
    assert ep.calls == 9, "no run may be retried in place"
    failed = [r for r in records if r.status["outcome"] == "failed"]
    assert failed and failed[0].status["failure_class"] == "health_timeout"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_driver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.driver'`

- [ ] **Step 3: Implement**

`coldstart/driver.py`:

```python
import uuid

from coldstart.checks import classify_failure
from coldstart.scheduler import build_schedule
from coldstart.schema import RunRecord
from coldstart.vllm_logs import parse_engine_log


def _record_from(scheduled, outcome) -> RunRecord:
    if outcome.error is not None:
        return RunRecord(
            run_id=str(uuid.uuid4()),
            run_index=scheduled.run_index,
            arm=scheduled.arm,
            clock_A=outcome.clock_A,
            clock_C={},
            clock_B={},
            warmup=[],
            engine={},
            host={},
            config={},
            status={
                "outcome": "failed",
                "failure_class": classify_failure(outcome.error).value,
                "failure_detail": outcome.error,
            },
        )

    p = outcome.payload
    parsed = parse_engine_log("\n".join(p.get("log_lines", [])))
    return RunRecord(
        run_id=p.get("job_id", str(uuid.uuid4())),
        run_index=scheduled.run_index,
        arm=scheduled.arm,
        clock_A=outcome.clock_A,
        clock_C=p.get("clock_C", {}),
        clock_B=p.get("clock_B", {}),
        warmup=p.get("warmup", []),
        engine={
            **parsed.engine_info,
            "s4_subphases": parsed.phases,
            "s4_merged": parsed.merged,
            "compile_cache_observed": p.get("compile_cache_observed"),
        },
        host=p.get("host", {}),
        config=p.get("config", {}),
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def run_campaign(submitter, store, arms, triples, seed, on_run=None):
    """One record per scheduled run. Never retries in place — see spec 6.6."""
    schedule = build_schedule(arms=arms, triples=triples, seed=seed)
    for scheduled in schedule:
        outcome = submitter.submit(arm=scheduled.arm)
        record = _record_from(scheduled, outcome)
        record.host["triple_index"] = scheduled.triple_index
        store.append(record)
        if on_run:
            on_run(record)
    return store
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_driver.py -v`
Expected: PASS — 2 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/driver.py tests/test_driver.py
git commit -m "feat: driver orchestrating scheduled runs into the store"
```

---

## Task 16: Derived metrics

**Files:**
- Create: `coldstart/analysis/metrics.py`, `tests/test_metrics.py`

**Hardening folded in after code review.** The first version of this task passed its own
nine tests while twenty-two of twenty-five mutations survived them. The three that were
caught were all in the `T_weights` region; everything around it was undefended. A
mis-ordered mark produced a negative `t_weights` flagged consistent; `kv_cache_blocks == 0`
was indistinguishable from the engine reporting nothing; a missing `S2` mark was reported as
a merged `S3`; failed runs lost their `failure_class` entirely, making the published
failure-rate-per-arm table impossible to build from derived rows. Worst of the set,
`FAST_TOLERANCE` — a *pre-registered* analysis parameter — could be changed from `0.10` to
`0.0` or `10.0` with the whole suite still green. The warmup trio is now extracted as named,
independently tested functions so Task 11 imports the pre-registered definitions rather than
growing a second copy of them.

- [ ] **Step 1: Write the failing test**

`tests/test_metrics.py`:

```python
import pytest

from coldstart.analysis.metrics import (
    ceiling_bound,
    derive,
    steady_state_latency,
    time_to_fast_index,
    warmup_penalty,
)
from coldstart.checks import DiscardReason
from coldstart.schema import RunRecord

# Distinct per-request values with a non-flat tail, so the last-three window,
# the median (vs. max), and warmup[0] (vs. warmup[1]) are each pinned by a
# formula that no other formula over the same list would also satisfy.
# Last three (idx 7, 8, 9) = [4.0, 3.2, 2.0] -> median (steady) = 3.2.
_WARMUP_LATENCIES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 3.4, 4.0, 3.2, 2.0]


def make(arm="A", t_submit=0.0, t_result=150.0, marks=None, warmup=None):
    marks = marks or [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 130.0},
    ]
    warmup = warmup or [
        {"req_index": i, "ttft": 0.5, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)
    ]
    return RunRecord(
        run_id="r",
        run_index=0,
        arm=arm,
        clock_A={"t_submit": t_submit, "t_result": t_result},
        clock_C={},
        clock_B={"t0_wall": 0.0, "marks": marks},
        warmup=warmup,
        engine={"kv_cache_blocks": 8192, "block_size": 16},
        host={"host_id": "h1"},
        config={},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_t_process_is_t0_to_first_token():
    d = derive(make())
    assert d["t_process"] == 102.0


def test_t_total_is_submit_to_result():
    assert derive(make())["t_total"] == 150.0


def test_residual_is_the_difference():
    assert derive(make())["t_platform"] == pytest.approx(48.0)


def test_kv_capacity_is_blocks_times_block_size():
    assert derive(make())["kv_capacity_tokens"] == 8192 * 16


def test_steady_state_and_warmup_penalty():
    d = derive(make())
    assert d["steady_state_latency"] == pytest.approx(3.2)
    assert d["warmup_penalty"] == pytest.approx(10.0 / 3.2)


def test_time_to_fast_index_uses_the_registered_tolerance():
    # steady=3.2, threshold=3.2*1.1=3.52. idx6=3.4 is the first value <= 3.52.
    # A tolerance of 0.0 would instead land on idx8 (3.2); 10.0 would land on
    # idx0 (10.0) — see test_time_to_fast_index_* below for those directly.
    d = derive(make())
    assert d["time_to_fast_index"] == 6


def test_inconsistent_run_is_flagged_not_silently_kept():
    d = derive(make(t_result=50.0))
    assert d["consistent"] is False
    assert d["t_platform"] is None
    assert d["inconsistency_reason"] is not None
    assert d["discard_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL


def test_residual_below_rtt_floor_is_flagged_inconsistent():
    # t_process=102.0 (default marks), t_result=102.03 -> residual=0.03,
    # below the 0.05 rtt floor.
    d = derive(make(t_result=102.03))
    assert d["consistent"] is False
    assert d["t_platform"] is None
    assert d["discard_reason"] == DiscardReason.RESIDUAL_BELOW_RTT_FLOOR


def test_failed_run_is_not_processed_and_keeps_its_classification():
    rec = make()
    rec.host = {"host_id": "h9", "triple_index": 2}
    rec.status = {
        "outcome": "failed",
        "failure_class": "oom",
        "failure_detail": "CUDA out of memory",
    }
    d = derive(rec)
    assert d == {
        "ok": False,
        "arm": "A",
        "host_id": "h9",
        "triple_index": 2,
        "consistent": False,
        "failure_class": "oom",
    }


def test_failed_run_guard_is_not_a_noop():
    # Guards against `if False:` replacing the outcome check: with a broken
    # guard, this failed run would fall through to the ok-run path (which the
    # default fixture's marks/clocks would happily compute), producing a
    # 20-key "ok": True row instead of the 6-key failure row asserted above.
    rec = make()
    rec.status = {"outcome": "failed", "failure_class": None, "failure_detail": None}
    d = derive(rec)
    assert d["ok"] is False
    assert "t_total" not in d


def test_t_weights_is_s2_plus_s3_and_stops_at_the_load_boundary():
    """T_weights is S2+S3 (spec, stage taxonomy) — it must NOT run to S5_ready.

    S5_ready is on the far side of all of S4: device init, compilation, memory
    profiling, KV allocation, graph capture. Measuring to S5 would fold the
    compile term into the weights term, and arms B and C differ *only* in the
    compile term — so the harness would credit weight caching with the entire
    compile-cache saving. That is the one confusion this experiment exists to
    prevent, so it gets a test.
    """
    d = derive(make())
    assert d["t_weights"] == pytest.approx(50.0)  # 54.0 - 4.0, not 100.0 - 4.0


def test_t_weights_is_none_when_the_load_boundary_was_not_delineated():
    """Merged phases are reported merged, never guessed apart — spec, stage taxonomy."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S3_load_done"]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["t_s2_to_ready"] == pytest.approx(96.0)
    assert d["merged_phases"] == ["S3"]


def test_t_weights_is_none_when_the_acquisition_start_was_not_delineated():
    """A missing S2 mark is a different defect from a missing S3 mark and must
    be named correctly — not folded into the same 'S3' label."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S2_acquisition_start"]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["t_s2_to_ready"] is None
    assert d["merged_phases"] == ["S2"]


def test_t_weights_negative_is_flagged_inconsistent_not_corrected():
    """S3_load_done preceding S2_acquisition_start is impossible, not a sign
    error. `abs()`-ing it would silently publish a wrong number."""
    marks = [
        {"stage": "S2_acquisition_start", "t_mono": 60.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
    ]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["consistent"] is False
    assert d["merged_phases"] == []  # both marks were present; the value was just invalid


def test_t_weights_exceeding_t_process_is_flagged_inconsistent():
    """A weights phase longer than the process containing it is impossible."""
    marks = [
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 500.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
    ]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["consistent"] is False


def test_returned_row_carries_identity_and_reason():
    rec = make()
    rec.host = {"host_id": "h7", "triple_index": 3}
    d = derive(rec)
    assert d["arm"] == "A"
    assert d["host_id"] == "h7"
    assert d["triple_index"] == 3
    assert d["inconsistency_reason"] is None


def test_kv_capacity_is_zero_not_none_when_blocks_report_zero():
    """kv_cache_blocks == 0 is a real, alarming engine state — distinct from
    the engine not reporting the field at all."""
    rec = make()
    rec.engine = {"kv_cache_blocks": 0, "block_size": 16}
    d = derive(rec)
    assert d["kv_cache_blocks"] == 0
    assert d["kv_capacity_tokens"] == 0


def test_kv_capacity_is_none_when_engine_omits_the_fields():
    rec = make()
    rec.engine = {}
    d = derive(rec)
    assert d["kv_cache_blocks"] is None
    assert d["kv_capacity_tokens"] is None


def test_missing_process_mark_raises_with_run_identity():
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S6_first_token"]
    rec = make(marks=marks)
    rec.run_id = "run-42"
    with pytest.raises(KeyError) as exc_info:
        derive(rec)
    message = str(exc_info.value)
    assert "run-42" in message
    assert "A" in message


def test_ceiling_bound_is_the_share_removable():
    assert ceiling_bound(t_weights=40.0, t_total=200.0) == pytest.approx(0.20)


def test_ceiling_bound_rejects_zero_total():
    with pytest.raises(ValueError):
        ceiling_bound(t_weights=10.0, t_total=0.0)


def test_ceiling_bound_rejects_weights_exceeding_total():
    with pytest.raises(ValueError):
        ceiling_bound(t_weights=300.0, t_total=200.0)


# --- direct tests for the extracted warmup-trio functions (I10) ---
# These pin the definitions themselves, independent of RunRecord plumbing —
# and are what Task 11's worker/probe.py is meant to import instead of
# re-deriving the same formulas.


def test_steady_state_latency_is_median_of_last_three():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)]
    assert steady_state_latency(warmup) == pytest.approx(3.2)


def test_steady_state_latency_is_none_for_empty_warmup():
    assert steady_state_latency([]) is None


def test_warmup_penalty_is_first_over_steady():
    warmup = [{"req_index": 0, "end_to_end": 9.6}, {"req_index": 1, "end_to_end": 3.2}]
    assert warmup_penalty(warmup, steady=3.2) == pytest.approx(3.0)


def test_warmup_penalty_is_none_when_steady_is_zero():
    warmup = [{"req_index": 0, "end_to_end": 5.0}]
    assert warmup_penalty(warmup, steady=0.0) is None


def test_time_to_fast_index_returns_first_index_within_tolerance():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate([10.0, 3.4, 3.2])]
    assert time_to_fast_index(warmup, steady=3.2, tolerance=0.10) == 1


def test_time_to_fast_index_zero_tolerance_moves_the_index():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate([10.0, 3.4, 3.2])]
    assert time_to_fast_index(warmup, steady=3.2, tolerance=0.0) == 2


def test_time_to_fast_index_is_none_when_steady_is_none():
    assert time_to_fast_index([{"req_index": 0, "end_to_end": 1.0}], steady=None) is None
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.metrics'`

- [ ] **Step 3: Implement**

`coldstart/analysis/metrics.py`:

```python
import statistics
from typing import TypedDict

from coldstart.checks import DiscardReason, check_consistency, compute_residual
from coldstart.schema import RunRecord

FAST_TOLERANCE = 0.10  # fixed before data — see spec 7


class DerivedRow(TypedDict, total=False):
    """One derived row: the interface between the harness and every published
    figure. `total=False` because a failed run (six keys: ok, arm, host_id,
    triple_index, consistent, failure_class) and an ok run (twenty keys) are
    genuinely different contracts, not a partially-filled version of each
    other — see `derive`.
    """

    ok: bool
    arm: str
    host_id: str | None
    triple_index: int | None
    failure_class: str | None
    t_total: float
    t_process: float
    t_platform: float | None
    t_weights: float | None
    t_s2_to_ready: float | None
    merged_phases: list[str]
    s4_subphases: dict
    warmup: list[dict]
    steady_state_latency: float | None
    warmup_penalty: float | None
    time_to_fast_index: int | None
    kv_cache_blocks: int | None
    kv_capacity_tokens: int | None
    consistent: bool
    inconsistency_reason: str | None
    discard_reason: DiscardReason | None


def _marks(record: RunRecord) -> dict[str, float]:
    return {m["stage"]: m["t_mono"] for m in record.clock_B.get("marks", [])}


def _require_mark(marks: dict[str, float], stage: str, record: RunRecord) -> float:
    """Fail loudly, but never anonymously — mid-campaign a bare KeyError gives
    no way to find the offending run."""
    try:
        return marks[stage]
    except KeyError as exc:
        raise KeyError(
            f"run {record.run_id!r} (arm {record.arm!r}): missing required stage mark {stage!r}"
        ) from exc


def steady_state_latency(warmup: list[dict]) -> float | None:
    """Median end-to-end latency of the last three warmup requests — spec 7.

    Extracted as a named function (rather than inlined in `derive`) because
    the plan reuses this exact definition in `worker/probe.py` (Task 11);
    importing it from here keeps the two sites from drifting apart.
    """
    if not warmup:
        return None
    return statistics.median(w["end_to_end"] for w in warmup[-3:])


def warmup_penalty(warmup: list[dict], steady: float | None) -> float | None:
    """Ratio of the first warmup request's latency to steady state.

    Undefined when steady state is exactly zero — an implausible latency
    reading that must not be silently reported as "no penalty" (that would
    conflate it with the "no warmup data" case) nor crash the batch with a
    ZeroDivisionError. Both are treated as None; the `consistent`/reason
    machinery is not extended to warmup data, so there is nowhere else to
    surface the anomaly.
    """
    if not warmup or steady is None or steady <= 0:
        return None
    return warmup[0]["end_to_end"] / steady


def time_to_fast_index(
    warmup: list[dict], steady: float | None, tolerance: float = FAST_TOLERANCE
) -> int | None:
    """First request index whose latency lands within `tolerance` of steady state."""
    if steady is None:
        return None
    threshold = steady * (1.0 + tolerance)
    for w in warmup:
        if w["end_to_end"] <= threshold:
            return w["req_index"]
    return None


def ceiling_bound(t_weights: float, t_total: float) -> float:
    """Largest fraction of T_total removable if T_weights went to zero."""
    if t_total <= 0:
        raise ValueError(f"t_total must be positive, got {t_total}")
    if not (0 <= t_weights <= t_total):
        raise ValueError(f"t_weights {t_weights} must be within [0, t_total={t_total}]")
    return t_weights / t_total


def derive(record: RunRecord) -> DerivedRow:
    if record.status["outcome"] != "ok":
        # A failed run never reaches stage marks or clocks, but it still
        # needs to be countable by arm and by host — that's what feeds the
        # failure-rate tables and keeps FailureClass reachable from analysis.
        return {
            "ok": False,
            "arm": record.arm,
            "host_id": record.host.get("host_id"),
            "triple_index": record.host.get("triple_index"),
            "consistent": False,
            "failure_class": record.status.get("failure_class"),
        }

    m = _marks(record)
    t_process = _require_mark(m, "S6_first_token", record)
    t_total = record.clock_A["t_result"] - record.clock_A["t_submit"]
    checked = check_consistency(t_total=t_total, t_process=t_process)
    # Carry all three ConsistencyResult fields through: discard_reason is a
    # closed enum specifically so a downstream reader can tabulate discards
    # by class instead of substring-matching the free-form `reason` string.
    consistent, reason, discard_reason = checked.ok, checked.reason, checked.discard_reason

    # T_weights = S2 + S3 (spec, stage taxonomy). The volume arms may memory-map
    # weights, fusing acquisition and HBM load with no clean boundary between
    # them, which is exactly why the pair is the primary unit rather than S2
    # alone. If the engine did not delineate the load boundary at all, the phase
    # is reported merged rather than silently widened to S5_ready — widening it
    # would swallow the whole of S4, including the compile term.
    t_acq_start = m.get("S2_acquisition_start")
    t_load_done = m.get("S3_load_done")
    t_ready = m.get("S5_ready")
    merged: list[str] = []
    if t_acq_start is None:
        merged.append("S2")
    if t_load_done is None:
        merged.append("S3")

    t_weights: float | None
    if merged:
        t_weights = None
    else:
        t_weights = t_load_done - t_acq_start
        # A stage duration is an intra-clock quantity, so it earns the same
        # discipline compute_residual applies on the cross-clock path: a
        # negative or out-of-bounds duration means the run is broken, not
        # that the number needs correcting (e.g. abs()) before publication.
        if t_weights < 0:
            consistent = False
            reason = (
                f"t_weights {t_weights} is negative: S3_load_done precedes S2_acquisition_start"
            )
            t_weights = None
        elif t_weights > t_process:
            consistent = False
            reason = f"t_weights {t_weights} exceeds t_process {t_process}"
            t_weights = None

    t_s2_to_ready = (
        t_ready - t_acq_start if t_acq_start is not None and t_ready is not None else None
    )

    blocks = record.engine.get("kv_cache_blocks")
    block_size = record.engine.get("block_size")
    # `is not None` rather than truthiness: kv_cache_blocks == 0 is a real
    # (and alarming) engine state, not the same thing as "not reported".
    kv_tokens = blocks * block_size if blocks is not None and block_size is not None else None

    warmup = record.warmup
    steady = steady_state_latency(warmup)
    penalty = warmup_penalty(warmup, steady)
    fast_index = time_to_fast_index(warmup, steady)

    return {
        "ok": True,
        "arm": record.arm,
        "host_id": record.host.get("host_id"),
        "triple_index": record.host.get("triple_index"),
        "t_total": t_total,
        "t_process": t_process,
        "t_platform": compute_residual(t_total, t_process) if consistent else None,
        "t_weights": t_weights,
        "t_s2_to_ready": t_s2_to_ready,
        "merged_phases": merged,
        "s4_subphases": record.engine.get("s4_subphases", {}),
        "warmup": warmup,
        "steady_state_latency": steady,
        "warmup_penalty": penalty,
        "time_to_fast_index": fast_index,
        "kv_cache_blocks": blocks,
        "kv_capacity_tokens": kv_tokens,
        "consistent": consistent,
        "inconsistency_reason": reason,
        "discard_reason": discard_reason,
    }
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_metrics.py -v`
Expected: PASS — 29 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/analysis/metrics.py tests/test_metrics.py
git commit -m "feat: derived metrics with consistency gating"
```

---

## Task 16b: Business-framing metrics

Spec §7 requires every finding stated in money as well as seconds. These are pure arithmetic over
data already collected — no extra runs — and they are the numbers that travel to a budget owner.

**TEACH — grounds §9b Modules 1 and 2 in economic terms.** After this task, have the user compute
the break-even for a scale-up frequency of their choosing and say in one sentence whether the cache
is worth renting.

**Files:**
- Create: `coldstart/analysis/economics.py`, `tests/test_economics.py`

**Corrected after code review.** The first version returned only the GPU rental share under
the name `cost_per_scale_up`, while the spec defined that quantity as rental *plus* the value
of foregone tokens. At the published assumptions the omitted term is 11-90% of the GPU cost
depending on token price, so every cache break-even was biased conservative — caching looked
worse than it is. The spec was itself ambiguous (it required a priced quantity while
publishing no price, and reported foregone tokens as a count two sections earlier); the spec
is fixed and the module now separates `gpu_cost_per_scale_up`, `foregone_token_value` and
`total_cost_per_scale_up`, with the priced functions raising rather than silently returning a
partial figure. The compile cache got its own break-even: it is not rented, it is re-warmed
per version change, and one monthly-cost formula cannot express both shapes. Also closed:
`Assumptions` accepted NaN in every field, because NaN fails every `<= 0` comparison.

- [ ] **Step 1: Write the failing test**

`tests/test_economics.py`:

```python
import math
from dataclasses import replace

import pytest

from coldstart.analysis.economics import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    Assumptions,
    annual_cost,
    break_even_events_per_day,
    cache_is_worth_renting,
    compile_cache_break_even_events_per_day,
    compile_cache_term,
    foregone_token_value,
    foregone_tokens,
    gpu_cost_per_scale_up,
    supported_concurrency,
    total_cost_per_scale_up,
)

ASSUME = Assumptions(
    gpu_hourly_rate=0.80,
    scale_ups_per_day=48,
    steady_state_tokens_per_sec=40.0,
    volume_monthly_cost=7.0,
    assumed_context_length=2048,
)


def _assumptions(**overrides):
    """ASSUME with one or more fields overridden, for tests that isolate a
    single field's effect on a formula. Goes through `Assumptions.__post_init__`
    just like any other construction, so an override that violates validation
    still raises."""
    return replace(ASSUME, **overrides)


# ---------------------------------------------------------------------------
# Plan's seven tests (cost_per_scale_up renamed to gpu_cost_per_scale_up per
# code review C2; break-even's signature and tolerance updated per I3/I10 —
# behavior for these specific calls is unchanged).
# ---------------------------------------------------------------------------


def test_foregone_tokens_is_time_times_throughput():
    assert foregone_tokens(t_fast=120.0, assumptions=ASSUME) == pytest.approx(4800.0)


def test_gpu_cost_per_scale_up_prices_the_gpu_seconds():
    # 120s at $0.80/hr = $0.02666...
    result = gpu_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)
    assert result == pytest.approx(0.026667, abs=1e-5)


def test_annual_cost_scales_by_frequency():
    per_event = gpu_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)
    assert annual_cost(per_event, ASSUME) == pytest.approx(per_event * 48 * 365)


def test_supported_concurrency_divides_capacity_by_context():
    assert supported_concurrency(kv_capacity_tokens=131072, assumptions=ASSUME) == 64


def test_break_even_is_where_savings_cover_the_standing_cost():
    # Saving 60s per event at $0.80/hr = $0.01333 per event. A $7/month
    # volume needs 525 events/month = 17.260274 events/day to pay for
    # itself, using DAYS_PER_MONTH = DAYS_PER_YEAR / 12 (not a bare 30 —
    # see the reconciliation note on the constants). Tight tolerance: a
    # bare-30.0 DAYS_PER_MONTH would give 17.5, which this must reject.
    ev = break_even_events_per_day(seconds_saved=60.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == pytest.approx(17.260274, abs=1e-5)


def test_break_even_is_infinite_when_nothing_is_saved():
    ev = break_even_events_per_day(seconds_saved=0.0, standing_monthly_cost=7.0, assumptions=ASSUME)
    assert ev == float("inf")


def test_compile_cache_term_is_cold_minus_warm():
    assert compile_cache_term(s4b_cold=42.0, s4b_warm=3.0) == pytest.approx(39.0)


# ---------------------------------------------------------------------------
# Assumptions validation — range checks. volume_monthly_cost and
# output_token_price_per_million are otherwise never read by a formula that
# also takes an explicit override (break_even's standing_monthly_cost /
# include_foregone_tokens argument), so construction-time validation is the
# only place either field is exercised as "live" data at all.
# ---------------------------------------------------------------------------


def test_assumptions_rejects_non_positive_gpu_hourly_rate():
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        _assumptions(gpu_hourly_rate=0.0)


def test_assumptions_rejects_non_positive_scale_ups_per_day():
    with pytest.raises(ValueError, match="scale_ups_per_day"):
        _assumptions(scale_ups_per_day=0)


def test_assumptions_rejects_non_positive_steady_state_tokens_per_sec():
    with pytest.raises(ValueError, match="steady_state_tokens_per_sec"):
        _assumptions(steady_state_tokens_per_sec=-1.0)


def test_assumptions_rejects_negative_volume_monthly_cost():
    with pytest.raises(ValueError, match="volume_monthly_cost"):
        _assumptions(volume_monthly_cost=-0.01)


def test_assumptions_accepts_zero_volume_monthly_cost():
    # Zero is a real state (no standing rental cost at all), unlike negative.
    assert _assumptions(volume_monthly_cost=0.0).volume_monthly_cost == 0.0


def test_assumptions_rejects_non_positive_assumed_context_length():
    with pytest.raises(ValueError, match="assumed_context_length"):
        _assumptions(assumed_context_length=0)


def test_assumptions_rejects_negative_output_token_price_per_million():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        _assumptions(output_token_price_per_million=-0.01)


def test_assumptions_defaults_output_token_price_per_million_to_none():
    assert Assumptions(
        gpu_hourly_rate=0.80,
        scale_ups_per_day=48,
        steady_state_tokens_per_sec=40.0,
        volume_monthly_cost=7.0,
        assumed_context_length=2048,
    ).output_token_price_per_million is None


# ---------------------------------------------------------------------------
# Assumptions validation — NaN and inf, per field (code review C1). NaN
# fails every `<=`/`<` comparison, so a validator written as a bare range
# check waves it through; each of these would have passed silently before
# the fix routed every field through the finite check first.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf")], ids=["nan", "inf"])
@pytest.mark.parametrize(
    "field",
    [
        "gpu_hourly_rate",
        "scale_ups_per_day",
        "steady_state_tokens_per_sec",
        "volume_monthly_cost",
        "assumed_context_length",
        "output_token_price_per_million",
    ],
)
def test_assumptions_rejects_non_finite_field(field, bad_value):
    with pytest.raises(ValueError, match=field):
        _assumptions(**{field: bad_value})


# ---------------------------------------------------------------------------
# foregone_tokens
# ---------------------------------------------------------------------------


def test_foregone_tokens_scales_with_steady_state_tokens_per_sec():
    fast = _assumptions(steady_state_tokens_per_sec=100.0)
    assert foregone_tokens(t_fast=10.0, assumptions=fast) == pytest.approx(1000.0)


def test_foregone_tokens_at_zero_t_fast_is_zero():
    assert foregone_tokens(t_fast=0.0, assumptions=ASSUME) == 0.0


def test_foregone_tokens_rejects_negative_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        foregone_tokens(t_fast=-1.0, assumptions=ASSUME)


def test_foregone_tokens_rejects_non_finite_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        foregone_tokens(t_fast=float("nan"), assumptions=ASSUME)


# ---------------------------------------------------------------------------
# gpu_cost_per_scale_up
# ---------------------------------------------------------------------------


def test_gpu_cost_per_scale_up_at_one_hour_equals_the_hourly_rate():
    # Literal 3600.0, not SECONDS_PER_HOUR, on the input side: importing the
    # module's own constant here would make the assertion pass even under a
    # mutant that changes SECONDS_PER_HOUR, since the same (wrong) constant
    # would cancel out of both the input and the implementation.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    assert gpu_cost_per_scale_up(t_fast=3600.0, assumptions=rate_one) == pytest.approx(1.0)


def test_gpu_cost_per_scale_up_at_zero_t_fast_is_zero():
    assert gpu_cost_per_scale_up(t_fast=0.0, assumptions=ASSUME) == 0.0


def test_gpu_cost_per_scale_up_rejects_negative_t_fast():
    with pytest.raises(ValueError, match="t_fast"):
        gpu_cost_per_scale_up(t_fast=-1.0, assumptions=ASSUME)


# ---------------------------------------------------------------------------
# foregone_token_value / total_cost_per_scale_up — spec line 713's full,
# two-term definition of a scale-up event's cost (code review C2).
# ---------------------------------------------------------------------------


def test_foregone_token_value_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        foregone_token_value(t_fast=120.0, assumptions=ASSUME)


def test_foregone_token_value_prices_the_tokens():
    priced = _assumptions(output_token_price_per_million=2.0)
    # foregone_tokens = 120 * 40 = 4800; value = 4800 * (2.0 / 1e6) = 0.0096
    assert foregone_token_value(t_fast=120.0, assumptions=priced) == pytest.approx(0.0096)


def test_total_cost_per_scale_up_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        total_cost_per_scale_up(t_fast=120.0, assumptions=ASSUME)


def test_total_cost_per_scale_up_is_gpu_cost_plus_foregone_value():
    priced = _assumptions(output_token_price_per_million=2.0)
    # gpu_cost = 120/3600*0.8 = 0.026667; foregone_value = 0.0096; sum = 0.036267
    result = total_cost_per_scale_up(t_fast=120.0, assumptions=priced)
    assert result == pytest.approx(0.036267, abs=1e-5)
    assert result == pytest.approx(
        gpu_cost_per_scale_up(120.0, priced) + foregone_token_value(120.0, priced)
    )


# ---------------------------------------------------------------------------
# annual_cost
# ---------------------------------------------------------------------------


def test_annual_cost_scales_with_scale_ups_per_day():
    ten = _assumptions(scale_ups_per_day=10)
    twenty = _assumptions(scale_ups_per_day=20)
    cost = 0.05
    assert annual_cost(cost, twenty) == pytest.approx(2 * annual_cost(cost, ten))


def test_annual_cost_uses_days_per_year_exactly():
    # cost_per_event and scale_ups_per_day chosen to be 1, so the result is
    # DAYS_PER_YEAR alone. Literal 365.0 on the expectation side, not
    # DAYS_PER_YEAR — a mutant changing DAYS_PER_YEAR would otherwise cancel
    # against itself here.
    one_per_day = _assumptions(scale_ups_per_day=1)
    assert annual_cost(1.0, one_per_day) == pytest.approx(365.0)


def test_annual_cost_at_zero_cost_per_event_is_zero():
    assert annual_cost(0.0, ASSUME) == 0.0


def test_annual_cost_rejects_negative_cost_per_event():
    with pytest.raises(ValueError, match="cost_per_event"):
        annual_cost(-1.0, ASSUME)


def test_annual_cost_rejects_non_finite_cost_per_event():
    with pytest.raises(ValueError, match="cost_per_event"):
        annual_cost(float("nan"), ASSUME)


# ---------------------------------------------------------------------------
# supported_concurrency
# ---------------------------------------------------------------------------


def test_supported_concurrency_when_capacity_smaller_than_one_context_is_zero():
    # A real deployment state (a KV cache too small to hold even one
    # context), not an error — must not raise and must not floor-divide to
    # a nonsensical negative or fractional value.
    assert supported_concurrency(kv_capacity_tokens=100, assumptions=ASSUME) == 0


def test_supported_concurrency_at_exact_context_boundary():
    ctx = ASSUME.assumed_context_length
    assert supported_concurrency(kv_capacity_tokens=ctx, assumptions=ASSUME) == 1
    assert supported_concurrency(kv_capacity_tokens=ctx - 1, assumptions=ASSUME) == 0
    assert supported_concurrency(kv_capacity_tokens=2 * ctx, assumptions=ASSUME) == 2


def test_supported_concurrency_rejects_negative_capacity():
    with pytest.raises(ValueError, match="kv_capacity_tokens"):
        supported_concurrency(kv_capacity_tokens=-1, assumptions=ASSUME)


def test_supported_concurrency_rejects_non_finite_capacity():
    with pytest.raises(ValueError, match="kv_capacity_tokens"):
        supported_concurrency(kv_capacity_tokens=float("nan"), assumptions=ASSUME)


def test_supported_concurrency_coerces_float_capacity_to_int():
    # kv_capacity_tokens can arrive as a float from parsed vLLM log output;
    # the -> int contract must hold regardless.
    result = supported_concurrency(kv_capacity_tokens=131072.0, assumptions=ASSUME)
    assert result == 64
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# compile_cache_term
# ---------------------------------------------------------------------------


def test_compile_cache_term_is_zero_when_cold_equals_warm():
    assert compile_cache_term(s4b_cold=10.0, s4b_warm=10.0) == 0.0


def test_compile_cache_term_is_negative_when_warm_exceeds_cold():
    # Measurement noise can make a "warm" run look slower than "cold" — the
    # function reports that honestly rather than clamping it away.
    assert compile_cache_term(s4b_cold=5.0, s4b_warm=10.0) == pytest.approx(-5.0)


def test_compile_cache_term_rejects_non_finite_cold():
    with pytest.raises(ValueError, match="s4b_cold"):
        compile_cache_term(s4b_cold=float("nan"), s4b_warm=3.0)


def test_compile_cache_term_rejects_non_finite_warm():
    with pytest.raises(ValueError, match="s4b_warm"):
        compile_cache_term(s4b_cold=42.0, s4b_warm=float("inf"))


# ---------------------------------------------------------------------------
# break_even_events_per_day
# ---------------------------------------------------------------------------


def test_break_even_is_negative_infinite_when_the_cache_made_things_slower():
    # seconds_saved < 0 is a real state (a cache that regressed cold start),
    # not invalid input — it must not raise. It returns -inf rather than
    # +inf so a reader can tell this apart from the "no difference" case
    # (code review I7): a bare "break-even: inf" doesn't distinguish noise
    # from a real regression.
    ev = break_even_events_per_day(
        seconds_saved=-30.0, assumptions=ASSUME, standing_monthly_cost=7.0
    )
    assert ev == float("-inf")


def test_break_even_rejects_non_finite_seconds_saved():
    with pytest.raises(ValueError, match="seconds_saved"):
        break_even_events_per_day(
            seconds_saved=float("nan"), assumptions=ASSUME, standing_monthly_cost=7.0
        )


def test_break_even_rejects_negative_standing_monthly_cost():
    with pytest.raises(ValueError, match="standing_monthly_cost"):
        break_even_events_per_day(
            seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=-1.0
        )


def test_break_even_is_zero_when_standing_cost_is_zero():
    # No standing cost to recoup means the cache "pays for itself" at any
    # frequency, including zero.
    ev = break_even_events_per_day(
        seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=0.0
    )
    assert ev == pytest.approx(0.0)


def test_break_even_scales_inversely_with_gpu_hourly_rate():
    cheap = _assumptions(gpu_hourly_rate=1.0)
    pricey = _assumptions(gpu_hourly_rate=2.0)
    ev_cheap = break_even_events_per_day(
        seconds_saved=3600.0, assumptions=cheap, standing_monthly_cost=100.0
    )
    ev_pricey = break_even_events_per_day(
        seconds_saved=3600.0, assumptions=pricey, standing_monthly_cost=100.0
    )
    assert ev_pricey == pytest.approx(ev_cheap / 2)


def test_break_even_uses_days_per_year_over_twelve_for_month_length():
    # Ties DAYS_PER_MONTH to DAYS_PER_YEAR / 12 through the public function:
    # 1 event/day at $1/event, with the standing monthly cost set to exactly
    # one "average" month of that spend, must break even at 1 event/day.
    # seconds_saved is the literal 3600.0 (not SECONDS_PER_HOUR) so a
    # SECONDS_PER_HOUR mutation can't cancel out of this test too.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    ev = break_even_events_per_day(
        seconds_saved=3600.0,
        assumptions=rate_one,
        standing_monthly_cost=DAYS_PER_YEAR / 12.0,
    )
    assert ev == pytest.approx(1.0)


def test_break_even_defaults_standing_cost_to_assumptions_volume_monthly_cost():
    # Code review I3: volume_monthly_cost must be a live input, not dead
    # data next to a separately-supplied standing_monthly_cost argument.
    # Compared against an explicit call carrying the *same* nonzero value
    # (not against another fallback call) so a mutant that replaces the
    # fallback with a constant (e.g. always 0.0) can't hide by having both
    # sides of the comparison degenerate to the same wrong answer.
    custom = _assumptions(volume_monthly_cost=14.0)
    ev_via_default = break_even_events_per_day(seconds_saved=60.0, assumptions=custom)
    ev_via_explicit = break_even_events_per_day(
        seconds_saved=60.0, assumptions=custom, standing_monthly_cost=14.0
    )
    assert ev_via_default == pytest.approx(ev_via_explicit)
    assert ev_via_default != pytest.approx(0.0)


def test_break_even_explicit_standing_cost_overrides_assumptions():
    ev_override = break_even_events_per_day(
        seconds_saved=60.0, assumptions=ASSUME, standing_monthly_cost=3.5
    )
    ev_default = break_even_events_per_day(seconds_saved=60.0, assumptions=ASSUME)
    assert ev_override == pytest.approx(ev_default / 2)  # 3.5 is half of ASSUME's 7.0


def test_break_even_include_foregone_tokens_requires_a_price():
    with pytest.raises(ValueError, match="output_token_price_per_million"):
        break_even_events_per_day(
            seconds_saved=60.0,
            assumptions=ASSUME,
            standing_monthly_cost=7.0,
            include_foregone_tokens=True,
        )


def test_break_even_include_foregone_tokens_lowers_the_break_even():
    # Valuing the foregone tokens too makes each saved second worth more,
    # so fewer events/day are needed to recoup the same standing cost.
    priced = _assumptions(output_token_price_per_million=1.0)
    ev_gpu_only = break_even_events_per_day(
        seconds_saved=60.0, assumptions=priced, standing_monthly_cost=7.0
    )
    ev_total = break_even_events_per_day(
        seconds_saved=60.0,
        assumptions=priced,
        standing_monthly_cost=7.0,
        include_foregone_tokens=True,
    )
    assert ev_total < ev_gpu_only


# ---------------------------------------------------------------------------
# compile_cache_break_even_events_per_day — spec line 717's break-even for
# the compile cache, whose standing cost is a one-off re-warm charge per
# version change rather than a monthly rental (code review I4).
# ---------------------------------------------------------------------------


def test_compile_cache_break_even_converts_rewarm_cost_exactly():
    # seconds_saved=3600s at rate=1.0 -> $1 saved/event. rewarm_cost=1.0 at
    # DAYS_PER_MONTH version changes/month -> standing_monthly_cost =
    # DAYS_PER_MONTH exactly -> events_per_month = DAYS_PER_MONTH ->
    # events_per_day = 1.0. An implementation that added rather than
    # multiplied rewarm_cost and version_changes_per_month would drift
    # noticeably off 1.0.
    rate_one = _assumptions(gpu_hourly_rate=1.0)
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=3600.0,
        rewarm_cost=1.0,
        version_changes_per_month=DAYS_PER_MONTH,
        assumptions=rate_one,
    )
    assert ev == pytest.approx(1.0)


def test_compile_cache_break_even_is_negative_infinite_when_slower():
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=-5.0,
        rewarm_cost=5.0,
        version_changes_per_month=2.0,
        assumptions=ASSUME,
    )
    assert ev == float("-inf")


def test_compile_cache_break_even_at_zero_version_changes_is_zero():
    # No version changes means the re-warm cost never recurs — free.
    ev = compile_cache_break_even_events_per_day(
        seconds_saved=60.0,
        rewarm_cost=5.0,
        version_changes_per_month=0.0,
        assumptions=ASSUME,
    )
    assert ev == pytest.approx(0.0)


def test_compile_cache_break_even_rejects_negative_rewarm_cost():
    with pytest.raises(ValueError, match="rewarm_cost"):
        compile_cache_break_even_events_per_day(
            seconds_saved=60.0,
            rewarm_cost=-1.0,
            version_changes_per_month=2.0,
            assumptions=ASSUME,
        )


def test_compile_cache_break_even_rejects_negative_version_changes_per_month():
    with pytest.raises(ValueError, match="version_changes_per_month"):
        compile_cache_break_even_events_per_day(
            seconds_saved=60.0,
            rewarm_cost=5.0,
            version_changes_per_month=-1.0,
            assumptions=ASSUME,
        )


# ---------------------------------------------------------------------------
# cache_is_worth_renting — the one-sentence verdict, spec line 719 (code
# review I8).
# ---------------------------------------------------------------------------


def test_cache_is_worth_renting_true_when_frequency_exceeds_break_even():
    assert cache_is_worth_renting(ASSUME, 17.260274) is True  # 48/day > 17.26/day


def test_cache_is_worth_renting_false_when_frequency_is_below_break_even():
    assert cache_is_worth_renting(ASSUME, 100.0) is False  # 48/day < 100/day


def test_cache_is_worth_renting_false_at_exact_break_even():
    assert cache_is_worth_renting(ASSUME, 48.0) is False  # equal, not "exceeds"


def test_cache_is_worth_renting_false_for_infinite_break_even():
    assert cache_is_worth_renting(ASSUME, float("inf")) is False


def test_cache_is_worth_renting_false_for_negative_infinite_break_even():
    # A naive `scale_ups_per_day > break_even` is True for any finite
    # frequency against -inf; a regression must never read as "worth it".
    assert cache_is_worth_renting(ASSUME, float("-inf")) is False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_days_per_month_is_derived_from_days_per_year():
    assert DAYS_PER_MONTH == pytest.approx(DAYS_PER_YEAR / 12.0)
    assert not math.isclose(DAYS_PER_MONTH, 30.0)
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_economics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.economics'`

- [ ] **Step 3: Implement**

`coldstart/analysis/economics.py`:

```python
"""Business-framing metrics — spec 7: every finding travels in dollars as well as
seconds. Pure functions over data already collected elsewhere in this package;
no I/O, no records, no extra runs.
"""

import math
from dataclasses import dataclass

SECONDS_PER_HOUR = 3600.0

# DAYS_PER_MONTH is derived from DAYS_PER_YEAR (rather than a bare round 30.0)
# so "events/day" and "events/year" figures agree on how long a month is.
DAYS_PER_YEAR = 365.0
DAYS_PER_MONTH = DAYS_PER_YEAR / 12.0


def _require_finite(value: float, name: str) -> None:
    """Fail loudly: NaN and inf compare False against every ordering operator,
    so without this a non-finite value slides past every `<=`/`<` check below
    and silently poisons a published figure. Same pattern as
    coldstart/checks.py's `_validate_clock_inputs`, reimplemented here because
    the required range differs per call site (positive-only, non-negative, or
    unconstrained)."""
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value!r}")


def _require_finite_non_negative(value: float, name: str) -> None:
    _require_finite(value, name)
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value!r}")


def _require_finite_positive(value: float, name: str) -> None:
    _require_finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value!r}")


@dataclass(frozen=True)
class Assumptions:
    """Published in the post so a reader can substitute their own — see spec 7.

    Validated at construction: every field feeds a number that gets
    published, so a nonsensical assumption (negative, zero where positive is
    required, or NaN/inf) must fail the moment it's constructed rather than
    propagate silently into a wrong headline figure several calls later.
    """

    gpu_hourly_rate: float
    scale_ups_per_day: float
    steady_state_tokens_per_sec: float
    volume_monthly_cost: float
    assumed_context_length: int
    # Optional: unlocks foregone_token_value / total_cost_per_scale_up. Spec
    # line 713 prices a scale-up event's cost as GPU rental *plus* the value
    # of foregone tokens, but publishes no token price among its three
    # standard assumptions — so this stays unset, and those two functions
    # stay unusable, until a reader supplies one.
    output_token_price_per_million: float | None = None

    def __post_init__(self) -> None:
        _require_finite_positive(self.gpu_hourly_rate, "gpu_hourly_rate")
        _require_finite_positive(self.scale_ups_per_day, "scale_ups_per_day")
        _require_finite_positive(
            self.steady_state_tokens_per_sec, "steady_state_tokens_per_sec"
        )
        _require_finite_non_negative(self.volume_monthly_cost, "volume_monthly_cost")
        _require_finite_positive(self.assumed_context_length, "assumed_context_length")
        if self.output_token_price_per_million is not None:
            _require_finite_non_negative(
                self.output_token_price_per_million, "output_token_price_per_million"
            )


def foregone_tokens(t_fast: float, assumptions: Assumptions) -> float:
    """Output the replica could have produced while starting or still slow."""
    _require_finite_non_negative(t_fast, "t_fast")
    return t_fast * assumptions.steady_state_tokens_per_sec


def gpu_cost_per_scale_up(t_fast: float, assumptions: Assumptions) -> float:
    """The GPU-rental share of a scale-up event's cost — not the total.

    See `total_cost_per_scale_up` for GPU cost plus foregone-token value,
    which is what spec line 713 actually defines "cost per scale-up event"
    to mean.
    """
    _require_finite_non_negative(t_fast, "t_fast")
    return (t_fast / SECONDS_PER_HOUR) * assumptions.gpu_hourly_rate


def foregone_token_value(t_fast: float, assumptions: Assumptions) -> float:
    """Dollar value of the tokens `foregone_tokens` counts — spec line 713's
    second cost term.

    Requires `assumptions.output_token_price_per_million`; raises rather than
    silently pricing the tokens at zero, which would be indistinguishable
    from "priced at zero" actually being the assumption.
    """
    if assumptions.output_token_price_per_million is None:
        raise ValueError(
            "foregone_token_value requires assumptions.output_token_price_per_million "
            "to be set"
        )
    tokens = foregone_tokens(t_fast, assumptions)
    return tokens * (assumptions.output_token_price_per_million / 1_000_000.0)


def total_cost_per_scale_up(t_fast: float, assumptions: Assumptions) -> float:
    """GPU rental cost plus the value of foregone tokens — spec line 713's
    full definition of a scale-up event's cost. Raises under the same
    condition as `foregone_token_value`."""
    return gpu_cost_per_scale_up(t_fast, assumptions) + foregone_token_value(t_fast, assumptions)


def annual_cost(cost_per_event: float, assumptions: Assumptions) -> float:
    """Annualizes a per-event cost over the calendar year (`DAYS_PER_YEAR`,
    365 days), not by compounding `DAYS_PER_MONTH` twelve times — stated
    explicitly so "annual" doesn't silently mean whichever convention a
    reader assumes. (The two are numerically equal here since
    `DAYS_PER_MONTH = DAYS_PER_YEAR / 12`, but this function doesn't rely on
    that; it uses `DAYS_PER_YEAR` directly.)
    """
    _require_finite_non_negative(cost_per_event, "cost_per_event")
    return cost_per_event * assumptions.scale_ups_per_day * DAYS_PER_YEAR


def supported_concurrency(kv_capacity_tokens: int, assumptions: Assumptions) -> int:
    """Always reported with its assumed context length attached.

    A KV cache smaller than one context is a real, if degenerate, deployment
    state — it returns 0 rather than raising. A negative or non-finite
    capacity cannot come from measuring a real cache, so those fail loudly
    instead of floor-dividing into a nonsensical negative concurrency.
    `kv_capacity_tokens` may arrive as a float (parsed vLLM log output), so
    the result is coerced back to `int` to honor the return type.
    """
    _require_finite_non_negative(kv_capacity_tokens, "kv_capacity_tokens")
    return int(kv_capacity_tokens // assumptions.assumed_context_length)


def compile_cache_term(s4b_cold: float, s4b_warm: float) -> float:
    """T_compile — the cost of a cold compile cache.

    May legitimately be negative or zero (measurement noise can make a
    "warm" run look no faster than, or even slower than, "cold") — that's a
    real result and is returned as-is. Non-finite inputs are not a real
    measurement, though, and fail loudly rather than propagating a NaN into
    a downstream break-even figure.
    """
    _require_finite(s4b_cold, "s4b_cold")
    _require_finite(s4b_warm, "s4b_warm")
    return s4b_cold - s4b_warm


def break_even_events_per_day(
    seconds_saved: float,
    assumptions: Assumptions,
    standing_monthly_cost: float | None = None,
    *,
    include_foregone_tokens: bool = False,
) -> float:
    """Scale-up frequency at which the weight cache pays for the continuous
    monthly rental cost of keeping it warm.

    This is the number a platform lead actually wants — "does caching help"
    is not a decision, "at what volume does it pay for itself" is. It prices
    a *rental* standing cost; the compile cache's standing cost is a
    different shape (a one-off re-warm charge per version change, not a
    monthly rental) — see `compile_cache_break_even_events_per_day`.

    `standing_monthly_cost` defaults to `assumptions.volume_monthly_cost` so
    the published `Assumptions` stay the single source of truth for the
    headline figure; pass an explicit value to price a different rental tier
    without editing the assumptions.

    By default a saved second is priced at the GPU rental rate alone
    (`assumptions.gpu_hourly_rate`) — the same partial accounting
    `gpu_cost_per_scale_up` uses, and the basis this module's published
    headline figure uses today, since spec 7 does not yet publish a token
    price. Pass `include_foregone_tokens=True` to also value the tokens that
    second could have produced (requires
    `assumptions.output_token_price_per_million`), matching
    `total_cost_per_scale_up`.

    `seconds_saved` may legitimately be negative — a cache that made cold
    starts slower is a real, if unfortunate, measurement, not invalid
    input — so it never breaks even either way, but the *sign* of the result
    keeps the two "never" cases distinguishable: `seconds_saved == 0` (the
    cache was a wash) returns `+inf`; `seconds_saved < 0` (the cache made
    things worse — a real regression) returns `-inf`. A reader seeing just
    "break-even: inf" can't tell noise from a regression; the sign lets them.
    """
    _require_finite(seconds_saved, "seconds_saved")
    if standing_monthly_cost is None:
        standing_monthly_cost = assumptions.volume_monthly_cost
    _require_finite_non_negative(standing_monthly_cost, "standing_monthly_cost")

    if seconds_saved < 0:
        return float("-inf")
    if seconds_saved == 0:
        return float("inf")

    hourly_rate = assumptions.gpu_hourly_rate
    if include_foregone_tokens:
        if assumptions.output_token_price_per_million is None:
            raise ValueError(
                "include_foregone_tokens=True requires "
                "assumptions.output_token_price_per_million to be set"
            )
        hourly_rate += (
            assumptions.steady_state_tokens_per_sec
            * (assumptions.output_token_price_per_million / 1_000_000.0)
            * SECONDS_PER_HOUR
        )

    saving_per_event = (seconds_saved / SECONDS_PER_HOUR) * hourly_rate
    events_per_month = standing_monthly_cost / saving_per_event
    return events_per_month / DAYS_PER_MONTH


def compile_cache_break_even_events_per_day(
    seconds_saved: float,
    rewarm_cost: float,
    version_changes_per_month: float,
    assumptions: Assumptions,
) -> float:
    """The compile cache's counterpart to `break_even_events_per_day` — spec
    line 717 requires a break-even for both caches.

    The weight cache's standing cost is a continuous monthly rental. The
    compile cache's standing cost is a one-off `rewarm_cost` paid each time
    the engine version changes and the cache must be rebuilt — a different
    shape, not just a different number. `version_changes_per_month` converts
    that lumpy, per-version cost into the monthly-equivalent figure the
    shared break-even formula expects, so the two caches' break-evens land in
    the same unit (events/day) and can be read side by side.
    """
    _require_finite_non_negative(rewarm_cost, "rewarm_cost")
    _require_finite_non_negative(version_changes_per_month, "version_changes_per_month")
    standing_monthly_cost = rewarm_cost * version_changes_per_month
    return break_even_events_per_day(seconds_saved, assumptions, standing_monthly_cost)


def cache_is_worth_renting(assumptions: Assumptions, break_even: float) -> bool:
    """The one-sentence verdict spec line 719 asks for: at the assumed
    scale-up frequency, does this cache earn back its standing cost?

    A `break_even` of `+inf` (no savings) or `-inf` (a regression) is never
    worth it, regardless of `assumptions.scale_ups_per_day` — `-inf` in
    particular must not compare as "worth it" just because every finite
    frequency is numerically greater than negative infinity. Only a finite,
    non-negative break-even below the assumed frequency clears the bar.
    """
    if not math.isfinite(break_even):
        return False
    return assumptions.scale_ups_per_day > break_even
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_economics.py -v`
Expected: PASS — 73 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/analysis/economics.py tests/test_economics.py
git commit -m "feat: business-framing metrics including cache break-even volume"
```

---

## Task 17: Statistics — percentiles, ECDF, bootstrap

**TEACH — grounds §9b Modules 8 and 10.** After this task, run the bootstrap on a deliberately tiny sample and show the interval widen; then show that `percentiles()` refuses p99 below the sample floor.

**Files:**
- Create: `coldstart/analysis/stats.py`, `tests/test_stats.py`

- [ ] **Step 1: Write the failing test**

`tests/test_stats.py`:

```python
import random

import pytest

from coldstart.analysis.stats import (
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    ecdf,
    percentiles,
    within_host_triples,
)


def test_percentiles_reports_p50_p90_p95():
    p = percentiles(list(range(1, 101)))
    assert p["p50"] == pytest.approx(50.5, abs=1.0)
    assert "p90" in p and "p95" in p


def test_p99_is_refused_below_the_sample_floor():
    with pytest.raises(ValueError) as e:
        percentiles(list(range(100)), want=("p99",))
    assert "p99" in str(e.value)


def test_p99_is_allowed_with_enough_samples():
    p = percentiles(list(range(1000)), want=("p50", "p99"))
    assert "p99" in p


def test_ecdf_is_sorted_and_ends_at_one():
    xs, ys = ecdf([3.0, 1.0, 2.0])
    assert xs == [1.0, 2.0, 3.0]
    assert ys[-1] == pytest.approx(1.0)


def test_bootstrap_interval_brackets_a_known_difference():
    a = [100.0] * 50
    b = [70.0] * 50
    res = bootstrap_median_diff(a, b, iterations=500, seed=1)
    assert res["point"] == pytest.approx(30.0)
    assert res["lo"] <= 30.0 <= res["hi"]


def test_contrast_difference_interval_brackets_a_known_gap():
    # A-B is 30, B-C is 10, so the contrast difference is 20.
    a, b, c = [100.0] * 40, [70.0] * 40, [60.0] * 40
    res = bootstrap_contrast_difference(a, b, c, iterations=400, seed=2)
    assert res["point"] == pytest.approx(20.0)
    assert res["lo"] <= 20.0 <= res["hi"]


def test_bootstrap_actually_resamples():
    """Constant inputs make every resample identical, so they cannot prove the
    bootstrap resamples at all — a version that skipped resampling entirely would
    pass. Spread inputs give the interval something to be wider than the point."""
    rng = random.Random(11)
    a = [rng.gauss(100.0, 15.0) for _ in range(60)]
    b = [rng.gauss(70.0, 15.0) for _ in range(60)]
    res = bootstrap_median_diff(a, b, iterations=800, seed=3)
    assert res["lo"] < res["point"] < res["hi"]
    assert res["lo"] > 0.0  # the real 30s gap survives resampling


def test_smaller_samples_give_wider_intervals():
    """The sample floor exists because small n buys a wide interval, not a wrong
    one. This pins that relationship instead of asserting it in prose."""
    rng = random.Random(12)
    big_a = [rng.gauss(100.0, 15.0) for _ in range(200)]
    big_b = [rng.gauss(70.0, 15.0) for _ in range(200)]
    small_a, small_b = big_a[:12], big_b[:12]
    wide = bootstrap_median_diff(small_a, small_b, iterations=800, seed=4)
    narrow = bootstrap_median_diff(big_a, big_b, iterations=800, seed=4)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])


def test_within_host_triples_keeps_only_complete_same_host_groups():
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
        {"triple_index": 1, "arm": "A", "host_id": "h1"},
        {"triple_index": 1, "arm": "B", "host_id": "h2"},
        {"triple_index": 1, "arm": "C", "host_id": "h1"},
    ]
    kept = within_host_triples(rows, arms=("A", "B", "C"))
    assert [t[0]["triple_index"] for t in kept] == [0]
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.stats'`

- [ ] **Step 3: Implement**

`coldstart/analysis/stats.py`:

```python
import random
import statistics

# A percentile needs enough samples to be a measurement rather than an
# observation. p99 at n=100 is one or two points — see spec 5.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}


def percentiles(values, want=("p50", "p90", "p95")) -> dict[str, float]:
    xs = sorted(values)
    n = len(xs)
    out = {}
    for name in want:
        need = MIN_SAMPLES[name]
        if n < need:
            raise ValueError(
                f"{name} requires at least {need} samples, got {n}; "
                "reporting it would be an observation, not a measurement"
            )
        q = int(name[1:]) / 100.0
        idx = min(n - 1, max(0, round(q * (n - 1))))
        out[name] = xs[idx]
    return out


def ecdf(values) -> tuple[list[float], list[float]]:
    xs = sorted(values)
    n = len(xs)
    return xs, [(i + 1) / n for i in range(n)]


def bootstrap_median_diff(a, b, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Non-parametric interval on median(a) - median(b). No distributional assumption."""
    rng = random.Random(seed)
    a, b = list(a), list(b)
    point = statistics.median(a) - statistics.median(b)
    draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        draws.append(statistics.median(ra) - statistics.median(rb))
    draws.sort()
    lo = draws[int((alpha / 2) * iterations)]
    hi = draws[int((1 - alpha / 2) * iterations) - 1]
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_contrast_difference(a, b, c, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Interval on (A-B) - (B-C): the ranking claim needs its own interval."""
    rng = random.Random(seed)
    a, b, c = list(a), list(b), list(c)
    med = statistics.median

    def draw(xs):
        return [xs[rng.randrange(len(xs))] for _ in range(len(xs))]

    point = (med(a) - med(b)) - (med(b) - med(c))
    vals = []
    for _ in range(iterations):
        ra, rb, rc = draw(a), draw(b), draw(c)
        vals.append((med(ra) - med(rb)) - (med(rb) - med(rc)))
    vals.sort()
    return {
        "point": point,
        "lo": vals[int((alpha / 2) * iterations)],
        "hi": vals[int((1 - alpha / 2) * iterations) - 1],
    }


def within_host_triples(rows, arms=("A", "B", "C")) -> list[list[dict]]:
    """Triples whose runs all landed on one host — the host confound removed."""
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["triple_index"], []).append(r)
    kept = []
    for _, g in sorted(groups.items()):
        if len(g) != len(arms):
            continue
        if sorted(x["arm"] for x in g) != sorted(arms):
            continue
        if len({x["host_id"] for x in g}) != 1:
            continue
        kept.append(g)
    return kept
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/analysis/stats.py tests/test_stats.py
git commit -m "feat: non-parametric statistics with a percentile sample floor"
```

---

## Task 18: Figures

These are charts, not UI. Verification is: generate from synthetic data, open the PNGs, and look at them.

**Files:**
- Create: `coldstart/analysis/figures.py`, `tests/test_figures.py`

- [ ] **Step 1: Write the failing test**

`tests/test_figures.py`:

```python
from pathlib import Path

from coldstart.analysis.figures import ecdf_plot, per_host_medians, warmup_curve, waterfall


def rows(n=30):
    out = []
    for i in range(n):
        arm = ["A", "B", "C"][i % 3]
        base = {"A": 160.0, "B": 95.0, "C": 60.0}[arm]
        out.append(
            {
                "arm": arm,
                "host_id": f"h{i % 5}",
                "t_total": base + i * 0.4,
                "t_platform": 18.0,
                "t_weights": base * 0.5,
                "s4_subphases": {"S4c": 6.0, "S4e": 12.0},
                "t_process": base - 18.0,
                "warmup": [{"req_index": k, "end_to_end": 2.0 * (1 + 2 * 0.55**k)} for k in range(10)],
            }
        )
    return out


def test_all_four_figures_write_files(tmp_path: Path):
    data = rows()
    paths = [
        waterfall(data, tmp_path / "waterfall.png"),
        warmup_curve(data, tmp_path / "warmup.png"),
        ecdf_plot(data, tmp_path / "ecdf.png"),
        per_host_medians(data, tmp_path / "hosts.png"),
    ]
    for p in paths:
        assert p.exists() and p.stat().st_size > 5000, f"{p} looks empty"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_figures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.figures'`

- [ ] **Step 3: Implement**

`coldstart/analysis/figures.py`:

```python
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from coldstart.analysis.stats import ecdf

ARMS = ["A", "B", "C"]
ARM_LABEL = {"A": "A — nothing cached", "B": "B — weights cached", "C": "C — weights + compile"}
RESIDUAL_COLOR = "#9e9e9e"  # deliberately distinct from measured stages


def _by_arm(rows):
    return {a: [r for r in rows if r["arm"] == a] for a in ARMS}


def waterfall(rows, out_path) -> Path:
    """Stacked median stage durations per arm, residual visually distinct."""
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    labels, ys = [], []
    for i, arm in enumerate(ARMS):
        rs = by[arm]
        if not rs:
            continue
        labels.append(f"{ARM_LABEL[arm]}\n(n={len(rs)})")
        ys.append(i)
        platform = statistics.median(r["t_platform"] for r in rs)
        process = statistics.median(r["t_process"] for r in rs)

        # derive() returns t_weights=None when the engine did not delineate the
        # load boundary. Drawing a merged span as if it were T_weights would be
        # the chart telling a story the data does not support, so the merge is
        # drawn as one explicitly-labelled bar instead — spec, stage taxonomy.
        measured = [r["t_weights"] for r in rs if r["t_weights"] is not None]
        if measured:
            weights = statistics.median(measured)
            sub = {
                k: statistics.median([r["s4_subphases"].get(k, 0.0) for r in rs])
                for k in ("S4c", "S4e")
            }
            unattributed = max(0.0, process - weights - sum(sub.values()))
            segments = [
                (platform, "T_platform (not attributable)", RESIDUAL_COLOR),
                (weights, "T_weights (S2+S3)", "#2f6fd0"),
                (sub["S4c"], "S4c memory profiling", "#4a8a4a"),
                (sub["S4e"], "S4e graph capture", "#c88a2e"),
                (unattributed, "unattributed within S4", "#d9c8a9"),
            ]
        else:
            segments = [
                (platform, "T_platform (not attributable)", RESIDUAL_COLOR),
                (process, "S2 to ready (phases merged by engine)", "#7f8fa6"),
            ]

        left = 0.0
        for value, label, color in segments:
            ax.barh(i, value, left=left, color=color, label=label if i == 0 else None)
            left += value

    ax.set_yticks(ys, labels)
    ax.set_xlabel("seconds (median)")
    ax.set_xlim(left=0)
    ax.legend(loc="lower right", fontsize=8)
    ax.set_title("Cold start decomposition")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def warmup_curve(rows, out_path) -> Path:
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        if not rs:
            continue
        n_req = len(rs[0]["warmup"])
        med = [statistics.median(r["warmup"][i]["end_to_end"] for r in rs) for i in range(n_req)]
        ax.plot(range(1, n_req + 1), med, marker="o", label=f"{ARM_LABEL[arm]} (n={len(rs)})")
    steady = statistics.median(rows[0]["warmup"][k]["end_to_end"] for k in (-3, -2, -1))
    ax.axhspan(steady * 0.9, steady * 1.1, color="#eeeeee", label="steady-state band (±10%)")
    ax.set_xlabel("request index")
    ax.set_ylabel("end-to-end latency (s)")
    ax.set_ylim(bottom=0)
    ax.set_title("Ready is not fast")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def ecdf_plot(rows, out_path) -> Path:
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        if not rs:
            continue
        xs, ys = ecdf([r["t_total"] for r in rs])
        ax.step(xs, ys, where="post", label=f"{ARM_LABEL[arm]} (n={len(rs)})")
    ax.set_xlabel("T_total (s)")
    ax.set_ylabel("fraction of runs ≤ x")
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1)
    ax.set_title("Distribution, not a mean")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def per_host_medians(rows, out_path) -> Path:
    hosts = sorted({r["host_id"] for r in rows})
    fig, ax = plt.subplots(figsize=(8, 4.5))
    meds = [statistics.median(r["t_total"] for r in rows if r["host_id"] == h) for h in hosts]
    counts = [sum(1 for r in rows if r["host_id"] == h) for h in hosts]
    ax.bar(range(len(hosts)), meds)
    ax.set_xticks(range(len(hosts)), [f"{h}\n(n={c})" for h, c in zip(hosts, counts)])
    ax.set_ylabel("median T_total (s)")
    ax.set_ylim(bottom=0)
    ax.set_title("Host heterogeneity")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_figures.py -v`
Expected: PASS — 1 passed

- [ ] **Step 5: Generate and LOOK at the figures**

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import sys
sys.path.insert(0, "tests")
from test_figures import rows
from coldstart.analysis.figures import waterfall, warmup_curve, ecdf_plot, per_host_medians
out = Path("build/figures"); out.mkdir(parents=True, exist_ok=True)
waterfall(rows(), out / "waterfall.png")
warmup_curve(rows(), out / "warmup.png")
ecdf_plot(rows(), out / "ecdf.png")
per_host_medians(rows(), out / "hosts.png")
print("wrote", sorted(p.name for p in out.iterdir()))
PY
open build/figures/*.png
```

**This step is not complete until you have looked at all four PNGs.** Confirm: axes start at zero, N appears on every series, the residual band is visually distinct from measured stages, and text is legible at phone size. A chart that renders without error is not a chart that reads.

- [ ] **Step 6: Commit**

```bash
printf 'build/\n' >> .gitignore
git add coldstart/analysis/figures.py tests/test_figures.py .gitignore
git commit -m "feat: the four artifact figures"
```

---

## Task 19: End-to-end synthetic validation

Proves the whole pipeline recovers a known answer before any paid measurement run.

**Files:**
- Create: `tests/test_end_to_end.py`

- [ ] **Step 1: Write the failing test**

`tests/test_end_to_end.py`:

```python
from coldstart.analysis.metrics import derive
from coldstart.analysis.stats import bootstrap_median_diff, within_host_triples
from coldstart.driver import run_campaign
from coldstart.store import JsonlStore
from coldstart.stubs.stub_endpoint import StubEndpoint
from coldstart.submitter import StubSubmitter


def test_pipeline_recovers_the_stubs_known_ordering(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=42)),
        store=store,
        arms=["A", "B", "C"],
        triples=40,
        seed=42,
    )
    rows = [derive(r) for r in store.read_all()]
    ok = [r for r in rows if r.get("ok") and r["consistent"]]
    assert len(ok) > 100

    by = {a: [r["t_weights"] for r in ok if r["arm"] == a] for a in "ABC"}
    ab = bootstrap_median_diff(by["A"], by["B"], iterations=400, seed=1)
    assert ab["lo"] > 0, "weight caching effect must be recovered with a positive interval"


def test_within_host_triples_are_found(tmp_path):
    store = JsonlStore(tmp_path / "runs.jsonl")
    run_campaign(
        submitter=StubSubmitter(StubEndpoint(seed=7, hosts=2)),
        store=store,
        arms=["A", "B", "C"],
        triples=40,
        seed=7,
    )
    rows = [derive(r) for r in store.read_all() if r.status["outcome"] == "ok"]
    kept = within_host_triples(rows)
    assert kept, "with only 2 hosts some triples must land on one host"
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_end_to_end.py -v`
Expected: FAIL — the module under test exists but assertions have not been satisfied yet, or import errors surface remaining gaps.

- [ ] **Step 3: Fix whatever the test exposes**

No new modules. This task exists to surface integration gaps between components built in isolation. Fix them where they are.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -v`
Expected: PASS — all tests across all modules

- [ ] **Step 5: Run ruff**

Run: `.venv/bin/ruff check coldstart worker recon tests`
Expected: no errors. Fix any that appear.

- [ ] **Step 6: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: end-to-end synthetic validation recovers known effect ordering"
```

---

## Definition of done for this plan

- [ ] All 19 tasks complete, full suite green, ruff clean.
- [ ] `fixtures/` contains real engine logs and API responses, committed.
- [ ] `fixtures/README.md` answers all three reconnaissance questions, including whether arm C survives.
- [ ] The harness runs a 120-run campaign end to end against stubs with no GPU and no cost.
- [ ] All four figures generated from synthetic data and **visually inspected**.
- [ ] The analysis pipeline recovers the stub's known effect ordering with an interval excluding zero.
- [ ] Business-framing metrics implemented and tested, including cache break-even volume.
- [ ] Total spend under $15.

**Not in this plan, deliberately:** pre-registration commit, the ~300-run paid campaign, real-data analysis, and the post. Those follow in a second plan once this harness is proven — the whole point of the GPU-free loop is that measurement code is proven before it costs money.
