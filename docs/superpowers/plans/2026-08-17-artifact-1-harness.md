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
| `coldstart/analysis/pipeline.py` | the publishability gate — partitions `derive()` output into publishable / discarded / failed, and the failure-rate / discard-count tables |
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

**Sub-phase key contract.** `parse_engine_log`'s `phases` dict is keyed by exactly the five names
`coldstart.analysis.metrics.S4_SUBPHASE_KEYS` expects: `S4a` (device init), `S4b` (compilation),
`S4c` (memory profiling), `S4d` (KV allocation), `S4e` (graph capture) — spec, stage taxonomy.
`S4b` is not optional set-dressing: it is `T_compile`, the direct measurement H3 exists to get
(B3), and the entire reason arm C exists. **A key this pinned vLLM version's logs do not emit
must be omitted from `phases` and listed in `merged`, never defaulted to `0.0` or guessed from a
neighboring line.** `metrics.derive()` already enforces the "absent, not zero" distinction on the
consumer side (an omitted key becomes `None`, not `0.0`, and is recorded in `merged_phases`) —
this parser is the producer side of that same contract and must not undermine it by inventing a
zero for a phase it never actually saw. The illustrative `PATTERNS`/`MERGED` below are
placeholders pending the Task 6 reconnaissance capture, not a prediction that `S4b` will turn out
merged — do not treat that placeholder as license to skip trying to parse `S4b` once real log
text is available.

**Files:**
- Create: `coldstart/vllm_logs.py`, `tests/test_vllm_logs.py`

**As built (2026-08-28), against the real captures.** S4b *is* delineated — the
placeholder above guessed otherwise — leaving only S4a and S4d merged. S4a has no
duration line at all and S4d reports a size rather than a time, so neither can be
recovered from this version's output.

The reconnaissance also exposed a defect in the already-built `metrics.derive()`:
it computed KV capacity as `kv_cache_blocks * block_size`, but 0.27.1 reports
`GPU KV cache size: N tokens` directly and emits neither part, so capacity came out
`None` and silently nulled the figure `supported_concurrency` depends on. `derive()`
now prefers a directly reported `kv_capacity_tokens` and keeps the product as a
fallback; the old behaviour is unchanged for versions that report the parts.

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
    # Anchored on "in total": two partial compile lines precede it.
    "S4b": re.compile(r"torch\.compile took (?P<sec>[\d.]+) s in total", re.IGNORECASE),
    "S4c": re.compile(r"Initial profiling/warmup run took (?P<sec>[\d.]+) s", re.IGNORECASE),
    "S4e": re.compile(r"Graph capturing finished in (?P<sec>[\d.]+) secs?", re.IGNORECASE),
}

# Sub-phases this version does not delineate. Reported merged, never guessed apart.
MERGED: list[str] = ["S4a", "S4d"]

# 0.27.1 reports the total directly and emits neither part.
KV_TOKENS = re.compile(r"GPU KV cache size: (?P<tokens>[\d,]+) tokens", re.IGNORECASE)


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

**As built — corrected from the version below after review.** Three defects in the original
draft, all now fixed:

1. **Cold paths were static strings (`/tmp/hf-cold`, `/tmp/vllm-cache-cold`).** RunPod
   serverless workers are reused across runs. A worker that served an earlier arm-A run and
   is picked again for a later arm-A run would find that earlier run's downloaded weights
   and compiled artifacts already sitting at those fixed paths — arm A would silently stop
   being cold, understating the A→B contrast with nothing in the data showing it. This is
   exactly the risk the spec's risk table names ("Compile cache leaking into a cold arm"),
   which pairs it with per-run verification from engine output — but verification is a
   detector, not a preventative. `CacheConfig.env()` now takes `run_id` as a required
   argument and namespaces every cold path under it
   (`/tmp/hf-cold/{run_id}`, `/tmp/vllm-cache-cold/{run_id}`), so contamination is
   structurally impossible rather than merely caught after the fact. `run_id` is an input,
   not generated inside this module — it comes from the already-existing
   `RunRecord.run_id` (`coldstart/schema.py`), so the emitted config stays reproducible
   from a stored run record. The *warm* volume paths (`/runpod-volume/hf`,
   `/runpod-volume/vllm-cache`) deliberately stay unnamespaced: pre-staging only works if a
   later run finds what an earlier run put there.
2. **The original test suite never asserted an actual `env()` value.**
   `test_env_differs_only_in_cache_variables` compared key *sets* only — a constant `env()`
   returned for every arm (the most damaging possible bug here, since it would make all
   three arms identical and the whole experiment a null result) passed every test as
   written. `tests/test_cache_config.py` now asserts literal per-arm `env()` dictionaries,
   that arm A never points at the volume, that cold paths vary by `run_id` and warm paths
   don't, and that `env()` requires `run_id` rather than accepting a default.
3. **`resolve("Z")` raised a bare `KeyError`.** Every other module in this codebase
   (`coldstart/analysis/stats.py`'s `unknown percentile` errors, for example) fails loudly
   with a message naming what was valid. `resolve()` now raises
   `ValueError(f"unknown arm {arm!r}; known: {sorted(CACHE_CONFIGS)}")`.

A fourth addition, not a fix to the draft: `tests/test_arm_isolation.py` makes the file's own
docstring claim — "this is the only thing that differs between arms" — a checked,
codebase-wide property. It AST-scans every `.py` file under `coldstart/` and `worker/`
(excluding `cache_config.py` itself, `scheduler.py`, and `coldstart/analysis/`, which
legitimately branch on or group by arm) for any comparison or `match` that branches on an
`arm`-named identifier, and fails naming the file and line if one exists. This is the test
that would catch someone later adding `if arm == "C":` inside the probe or the handler,
verified against the live tree by temporarily injecting exactly that into
`worker/recon_handler.py` and confirming the test caught it (reverted before commit).

**Open question, not resolved by this task:** whether `HF_HOME` and `VLLM_CACHE_ROOT` are
the correct variable names for the pinned image. Both are documented, current vLLM/HF
variables (`VLLM_CACHE_ROOT` is vLLM's own cache root, defaulting to `~/.cache/vllm`; `HF_HOME`
is the standard Hugging Face cache-home variable vLLM inherits via `huggingface_hub`) — but
there is at least one open vLLM issue (vllm-project/vllm#20127, v0.9.1) reporting
`VLLM_CACHE_ROOT` not being honored in a containerized deployment. Task 6's reconnaissance run
is what actually confirms these names against the pinned image; this task does not have a GPU
and cannot verify it. Do not treat the names as settled until reconnaissance output for the
pinned version shows the compile-cache directory actually moving with `VLLM_CACHE_ROOT`.

**Note on arm C:** whether arm C is even measurable depends on the reconnaissance question in
spec §5/§6.8 — whether the pinned vLLM version compiles at startup at all. If it does not, arm
C collapses into arm B and gets dropped, reverting to the two-arm design. All three arms are
still built here because that determination has not been made yet; see the comment above
`CACHE_CONFIGS` in the implementation.

**Files:**
- Create: `coldstart/cache_config.py`, `tests/test_cache_config.py`, `tests/test_arm_isolation.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cache_config.py` — see `tests/test_cache_config.py` in the repo for the full,
as-built suite (18 tests): the three per-arm shape tests below, plus literal per-arm `env()`
value assertions, the arm-A-never-points-at-the-volume guard, per-run uniqueness of cold
paths, stability of warm paths across runs, a required-`run_id` test, malformed-`run_id`
rejection, and the named-error test for an unknown arm.

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


def test_arm_a_env_values():
    assert resolve("A").env("run-123") == {
        "HF_HOME": "/tmp/hf-cold/run-123",
        "VLLM_CACHE_ROOT": "/tmp/vllm-cache-cold/run-123",
    }


def test_cold_paths_are_unique_per_run():
    env1 = resolve("A").env("run-1")
    env2 = resolve("A").env("run-2")
    assert env1["HF_HOME"] != env2["HF_HOME"]
    assert env1["VLLM_CACHE_ROOT"] != env2["VLLM_CACHE_ROOT"]


def test_unknown_arm_is_a_named_error():
    with pytest.raises(ValueError, match=r"unknown arm 'Z'.*'A', 'B', 'C'"):
        resolve("Z")
```

Also `tests/test_arm_isolation.py` — the codebase-wide invariant, independent of this module's
own correctness: no `.py` file under `coldstart/` or `worker/`, other than
`cache_config.py`/`scheduler.py`/`coldstart/analysis/`, may branch on an arm value.

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_cache_config.py tests/test_arm_isolation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.cache_config'`
(`test_arm_isolation.py` collects and passes standalone, since it scans the tree as it exists
today rather than importing the not-yet-created module.)

- [ ] **Step 3: Implement**

`coldstart/cache_config.py`:

```python
from dataclasses import dataclass

# Shared, pre-staged locations on the network volume — deliberately *not* namespaced by
# run: the entire point of "warm" is that a later run finds what an earlier run put here.
VOLUME_ROOT = "/runpod-volume"
VOLUME_HF_HOME = f"{VOLUME_ROOT}/hf"
VOLUME_VLLM_CACHE_ROOT = f"{VOLUME_ROOT}/vllm-cache"

# Cold locations. These must never be shared between runs (see CacheConfig.env below) —
# unlike the volume paths above, "cold" only holds if a reused serverless worker cannot
# find another run's leftovers here.
COLD_HF_ROOT = "/tmp/hf-cold"
COLD_VLLM_CACHE_ROOT = "/tmp/vllm-cache-cold"


@dataclass(frozen=True)
class CacheConfig:
    """The single interface that differs between arms — see spec 6.3.

    If arm behavior diverges anywhere else in this codebase, the single-variable claim
    is false and the experiment is compromised. tests/test_arm_isolation.py checks that
    structurally rather than hoping it holds.
    """

    arm: str
    weights_source: str  # "hub" | "volume"
    compile_cache_warm: bool

    def env(self, run_id: str) -> dict[str, str]:
        """Every arm sets the same variable names. Only values differ.

        A cold path is namespaced by `run_id` so a reused serverless worker can never
        silently serve one run's cache to another run's cold arm. `run_id` is a required
        input, not generated here, so the emitted config stays reproducible from a
        stored `RunRecord.run_id`.
        """
        if not run_id:
            raise ValueError(f"run_id must be a non-empty string, got {run_id!r}")
        if "/" in run_id:
            raise ValueError(f"run_id must not contain '/': {run_id!r}")

        hf_home = VOLUME_HF_HOME if self.weights_source == "volume" else f"{COLD_HF_ROOT}/{run_id}"
        cache_root = (
            VOLUME_VLLM_CACHE_ROOT
            if self.compile_cache_warm
            else f"{COLD_VLLM_CACHE_ROOT}/{run_id}"
        )
        return {"HF_HOME": hf_home, "VLLM_CACHE_ROOT": cache_root}


# Arm C's status is provisional: whether it is even measurable depends on the
# reconnaissance run (spec 5, 6.8) answering whether the pinned vLLM version compiles at
# startup at all. If it does not, arm C collapses into arm B and gets dropped. All three
# arms are built here regardless, because that determination has not been made yet.
CACHE_CONFIGS = {
    "A": CacheConfig("A", weights_source="hub", compile_cache_warm=False),
    "B": CacheConfig("B", weights_source="volume", compile_cache_warm=False),
    "C": CacheConfig("C", weights_source="volume", compile_cache_warm=True),
}


def resolve(arm: str) -> CacheConfig:
    try:
        return CACHE_CONFIGS[arm]
    except KeyError:
        raise ValueError(f"unknown arm {arm!r}; known: {sorted(CACHE_CONFIGS)}") from None
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_cache_config.py tests/test_arm_isolation.py -v`
Expected: PASS — 18 passed in `test_cache_config.py`, 4 passed in `test_arm_isolation.py`.

- [ ] **Step 5: Commit**

```bash
git add coldstart/cache_config.py tests/test_cache_config.py tests/test_arm_isolation.py
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

**Mark contract addition — `S4_start` and `S4_end` (required by the B2/B3 fixes in
`coldstart/analysis/metrics.py`).** No mark in the original contract delineates `S4`, so
`derive()` could not compute an `S4` bracket and the waterfall's "unattributed within S4" was
silently absorbing S1, all five `S4` sub-phases (including `S4b` compilation — B3), S5, and S6.
This probe is the producer of the two marks that fix that:

- `recorder.mark("S4_start")` immediately after `S3_load_done` is confirmed — device init begins
  the instant weights are resident on GPU, so the two marks land at the same instant. Add it
  right next to the existing `S3_load_done` marking in `drain()`, guarded the same way (`mark()`
  rejects duplicates).
- `recorder.mark("S4_end")` from a new log predicate, analogous to `_is_load_complete` — call it
  `_is_engine_up(line)` — that fires on whatever this vLLM version logs when the engine itself
  reports ready to accept traffic (found from the Task 6 reconnaissance captures, same discipline
  as `_is_load_complete`). This is **not** the same event as `S5_ready`: `S5_ready` is marked
  after `_wait_healthy()` returns, which is the *external* health-check endpoint responding
  ("server reports healthy," an HTTP round trip through the health poll) — a later, separate
  event from the engine's own internal "I am up" log line. Marking `S4_end` at `S5_ready` instead
  would fold all of `S5` into `S4`, which is exactly the substitution
  `t_s4_bracket = S5_ready - S3_load_done` that `metrics.derive()` now explicitly refuses to make
  (see the spec's Attribution caveat, and `test_t_s4_bracket_never_substitutes_s5_ready_minus_s3_load_done`
  in `tests/test_metrics.py`).

Until this task ships, `S4_start`/`S4_end` are absent from every real record, `derive()`'s
`t_s4_bracket` is `None` on every row, and the waterfall draws an explicitly-labelled "S4 + S5
(merged — S4_start/S4_end not yet measured)" bucket instead of guessing. That is the intended,
honest behavior of the analysis layer while this task is outstanding — not a bug to work around
by substituting `S5_ready - S3_load_done` here or in analysis.

**Warmup record contract addition — `t_dispatch_mono` (required by the B5 fix in
`coldstart/analysis/metrics.py`).** The original warmup record shape, `{req_index, ttft,
end_to_end}`, carries no absolute clock-B offset — there is no way to know when request N
*started* relative to `t0`. That makes `T_fast` (spec 7: "submit → first request within 10% of
steady-state latency") unmeasurable from a stored row, and worse, unreconstructible after the
fact: you cannot sum `end_to_end` values to infer when each request started, because that assumes
zero gap between sequential requests (no driver-side dispatch delay, no scheduling jitter between
one request's completion and the next one's dispatch) — an assumption, not a measurement. A
stored campaign with this field missing cannot be repaired offline; the field has to be recorded
live, by this probe, on every run.

This probe is the producer:

- Each warmup request must carry `t_dispatch_mono` — the monotonic instant (same clock, same
  origin as every other mark this probe emits) at which that request was dispatched. Capture it
  the same way `_one_request` already captures its own `t_start` internally; the change is to stop
  discarding that value and return it as part of the request's result dict instead:

  ```python
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
      return {"t_dispatch_mono": t_start, "ttft": ttft, "end_to_end": time.monotonic() - t_start}
  ```

  `run_probe`'s existing `warmup.append({"req_index": i, **result})` then carries the new field
  through with no further change — every warmup record gets it, not just request 1.
- `t_dispatch_mono` for request 1 must equal (or be consistent with) the existing
  `S6_request1_dispatch` mark — both name the same instant on the same clock, from two different
  call sites. A future test (`tests/test_probe_units.py` or an integration test once Task 15
  exists) should assert this, so the two never quietly drift apart.

`coldstart.analysis.metrics.t_fast_seconds` is what consumes this field: it looks up the warmup
record at `time_to_fast_index`, reads its `t_dispatch_mono`, and requires it to be present —
`derive()` returns `t_fast_seconds = None` with the reason recorded in `t_fast_reason` when it is
absent, exactly as it does for every real record today (this task is not built yet). It never
falls back to summing `end_to_end`.

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
    # t_dispatch_mono (B5) -- the absolute clock-B instant this request was
    # dispatched. Without it metrics.t_fast_seconds cannot measure T_fast and
    # will not infer it by summing end_to_end, which would assume zero gap
    # between sequential requests.
    return {"t_dispatch_mono": t_start, "ttft": ttft, "end_to_end": time.monotonic() - t_start}


def run_probe(recorder, model: str, health_timeout: float = 900.0) -> dict:
    """Returns the stage bundle. Caller owns the record assembly."""
    recorder.start()
    recorder.mark("S1_imports_done")

    log_lines: list[str] = []
    seen_load = False
    seen_engine_up = False
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
        nonlocal seen_load, seen_engine_up
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
                recorder.mark("S4_start")  # device init begins the instant weights land
                seen_load = True
            # _is_engine_up's predicate comes from Task 7's fixtures, same
            # discipline as _is_load_complete — filled in once the
            # reconnaissance capture (Task 6) shows what this vLLM version
            # logs when it reports itself ready. This is NOT S5_ready: that
            # mark fires later, on the external health-check endpoint
            # responding, not on the engine's own internal log line. Folding
            # S4_end into S5_ready would fold all of S5 into S4 — the exact
            # substitution metrics.derive() refuses to make.
            if _is_engine_up(line) and not seen_engine_up:
                recorder.mark("S4_end")
                seen_engine_up = True

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


def test_stub_warmup_carries_t_dispatch_mono_with_real_gaps_between_requests():
    """B5: a stub that omitted t_dispatch_mono (the field Task 11's real
    probe emits) would silently hide the defect metrics.t_fast_seconds
    exists to fix -- every stub-driven test would then be unable to tell a
    real per-request offset apart from the summing inference that field
    replaces. Also pins that the gap is real (non-zero): a dispatch offset
    exactly equal to the previous request's t_dispatch_mono + end_to_end
    would BE the summing inference, not a measurement of it."""
    ep = StubEndpoint(seed=1)
    warmup = ep.run(arm="A")["warmup"]
    for w in warmup:
        assert "t_dispatch_mono" in w
    for prev, nxt in zip(warmup, warmup[1:], strict=True):
        zero_gap_dispatch = prev["t_dispatch_mono"] + prev["end_to_end"]
        assert nxt["t_dispatch_mono"] > zero_gap_dispatch


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

**Emit `t_dispatch_mono` — same B5 field Task 11's real probe emits (required, not optional).**
The stub is what makes the GPU-free loop trustworthy: it works only because it is exercised
against the same record shape the real probe produces. A stub that omitted a field the real probe
emits would silently hide B5's defect again — the pipeline would look fully tested while every
stub-driven test still could not tell a real per-request measurement apart from the summing
inference `t_fast_seconds` refuses to make. The version below also does **not** derive
`S7_warmup_done` as `t_process + sum(end_to_end)` (the original draft's formula) — that is exactly
the zero-gap assumption B5 exists to eliminate. Instead each request's dispatch offset advances by
its own `end_to_end` plus a small deliberate gap, and every clock-B mark that touches warmup timing
is read back from those per-request offsets, never recomputed by summing.

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

# Deliberate, non-zero gap between one request's completion and the next
# request's dispatch (driver-side round trip / scheduling overhead). If this
# were zero, t_dispatch_mono would equal the cumulative sum of prior
# end_to_end values, and the stub could no longer distinguish a real
# per-request offset from the summing inference metrics.t_fast_seconds
# refuses to make (B5) -- it would exercise the fix without ever being able
# to catch its regression.
WARMUP_DISPATCH_GAP = 0.05


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
        t_dispatch = t_process  # request 1 dispatches the instant the server is ready
        for i in range(10):
            penalty = 1.0 + 2.0 * (0.55**i)
            e2e = steady * penalty
            warmup.append(
                {
                    "req_index": i,
                    "t_dispatch_mono": t_dispatch,
                    "ttft": e2e * 0.25,
                    "end_to_end": e2e,
                }
            )
            t_dispatch += e2e + WARMUP_DISPATCH_GAP * jitter

        first_touch = host not in self._seen
        self._seen.add(host)

        marks = [
            {"stage": "S1_imports_done", "t_mono": s1},
            {"stage": "S2_acquisition_start", "t_mono": s1},
            {"stage": "S3_load_done", "t_mono": s1 + t_weights},
            {"stage": "S5_ready", "t_mono": s1 + t_weights + s4b + s4_other},
            {"stage": "S6_request1_dispatch", "t_mono": warmup[0]["t_dispatch_mono"]},
            {"stage": "S6_first_token", "t_mono": warmup[0]["t_dispatch_mono"] + warmup[0]["ttft"]},
            {
                "stage": "S7_warmup_done",
                "t_mono": warmup[-1]["t_dispatch_mono"] + warmup[-1]["end_to_end"],
            },
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
Expected: PASS — 4 passed

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

**`t_result` is not `T_total`.** It is stamped here after `endpoint.run()` returns, which for a
serverless request/response worker is after all ten warmup requests (S7) complete — not at first
token of request 1 (S6), the spec's `T_total` boundary (spec 7). Do not treat
`t_result - t_submit` as `T_total` anywhere downstream. `derive()` (Task 16 / `coldstart/analysis/metrics.py`)
applies the documented correction — subtracting the clock-B warmup-tail duration
(`S7_warmup_done - S6_first_token`) from this raw span — to recover the spec-defined `T_total`.
See B1 under "Blocking defects found by the final integration review" for the full rationale and
the fix as built.

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

**Rebuilt over three review rounds.** Two real defects and one recurring test pathology.

The defects: the module had *two* definitions of the median — `percentiles()["p50"]` returned
an order statistic while every bootstrap used `statistics.median`, differing by 0.6s at the
planned campaign size, so the percentile table and a contrast's point estimate would have
disagreed about the same quantity in the same post. And the pooled bootstrap was being used
for the within-host subset, whose runs are paired by construction; that discards the pairing
the subset exists to create. On host-confounded data the paired interval measures 4.8s wide
against the unpaired 150.4s — the unpaired version would report no finding where the paired
one gives a clean answer.

The pathology, four times: **a test can only detect what its fixture can express.** Constant
bootstrap inputs cannot prove resampling happens. Gaussian inputs cannot distinguish median
from mean — the one estimator the spec excludes in bold, worth 24% on lognormal data. A
paired-contrast fixture with `B = C = 0` collapses `(A-B)-(B-C)` and `A-C` to the same number,
leaving the ranking claim swappable for a different statistic with 77 tests green. And a bare
`pytest.raises(ValueError)` cannot tell which guard fired, so adding a sample floor silently
disabled three parameter-guard tests — then a `match=` string loose enough to match the wrong
error disabled them again. Every instance was found by running the mutation, never by reading
the test. Any guard added to this module later needs the same treatment before it is trusted.

- [ ] **Step 1: Write the failing test**

`tests/test_stats.py`:

```python
import math
import random
import statistics

import pytest

import coldstart.analysis.stats as stats_module
from coldstart.analysis.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    MIN_SAMPLES,
    _percentile_interval,
    bootstrap_contrast_difference,
    bootstrap_median_diff,
    bootstrap_paired_contrast_difference,
    bootstrap_paired_median_diff,
    ecdf,
    percentiles,
    within_host_triples,
)

# ---------------------------------------------------------------------------
# shared fixture helpers
# ---------------------------------------------------------------------------


def _triple(idx, host, a, b, c, field="t_total"):
    return [
        {"triple_index": idx, "arm": "A", "host_id": host, field: a},
        {"triple_index": idx, "arm": "B", "host_id": host, field: b},
        {"triple_index": idx, "arm": "C", "host_id": host, field: c},
    ]


def _const_triples(n, a, b, c, field="t_total"):
    return [_triple(i, f"h{i}", a, b, c, field=field) for i in range(n)]


def _value_triples(values, field="t_total"):
    """One triple per value in `values`, with B = C = 0.0. Both a paired
    median-diff on (A, B) and a paired contrast (A-B)-(B-C) reduce to A
    exactly under this construction, so the same helper builds fixtures with
    a hand-known per-triple statistic for either function."""
    return [_triple(i, f"h{i}", v, 0.0, 0.0, field=field) for i, v in enumerate(values)]


def _gauss_triples(rng, n, mean_a, mean_b, mean_c, sd=10.0, host_offset_sd=0.0):
    triples = []
    for i in range(n):
        offset = rng.gauss(0.0, host_offset_sd) if host_offset_sd else 0.0
        a = mean_a + offset + rng.gauss(0.0, sd)
        b = mean_b + offset + rng.gauss(0.0, sd)
        c = mean_c + offset + rng.gauss(0.0, sd)
        triples.append(_triple(i, f"h{i}", a, b, c))
    return triples


# ---------------------------------------------------------------------------
# percentiles
# ---------------------------------------------------------------------------


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


# Hardcoded, not read from MIN_SAMPLES: if the test derived `need` from the
# module's own dict, a mutation to a floor's value would be self-consistent
# with the test (both the code and the test would move together) and the
# mutation would survive. Pinning the expected numbers here is what makes
# this a real pre-registration check rather than a tautology.
_EXPECTED_FLOORS = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}


def test_min_samples_matches_the_pre_registered_floors():
    assert MIN_SAMPLES == _EXPECTED_FLOORS


@pytest.mark.parametrize("name", sorted(_EXPECTED_FLOORS))
def test_every_percentile_floor_is_enforced_independently(name):
    """Each entry in MIN_SAMPLES is its own pre-registered parameter. A mutation
    that changes any single floor (not just p99's) must fail a test."""
    need = _EXPECTED_FLOORS[name]
    with pytest.raises(ValueError) as e:
        percentiles(list(range(need - 1)), want=(name,))
    assert name in str(e.value)
    # exactly at the floor it must be allowed
    p = percentiles(list(range(need)), want=(name,))
    assert name in p


def test_p50_at_the_sample_floor_even_and_odd_n():
    """Pin the linear-interpolation formula (numpy method="linear", see the
    module docstring) at p50, for both an even and an odd sample count.
    This is NOT nearest-rank: at even n the two middle order statistics are
    averaged, matching statistics.median, rather than one of them being
    picked by rounding. Values independently verified against
    numpy.percentile(xs, 50, method="linear")."""
    # n=20 (even, exactly the p50 floor): idx = 0.5*19 = 9.5 -> average of
    # xs[9]=10 and xs[10]=11 -> 10.5
    assert percentiles(list(range(1, 21)), want=("p50",))["p50"] == pytest.approx(10.5)
    # n=21 (odd): idx = 0.5*20 = 10.0 exactly -> xs[10] = 11, the true middle
    assert percentiles(list(range(1, 22)), want=("p50",))["p50"] == pytest.approx(11.0)


def test_percentile_at_the_upper_extreme_for_each_floor():
    """Pin the interpolation formula at the high end (p90/p95/p99), each
    exactly at its own sample floor. Values independently verified against
    numpy.percentile(xs, q, method="linear") on the same linear sequences."""
    assert percentiles(list(range(1, 51)), want=("p90",))["p90"] == pytest.approx(45.1)
    assert percentiles(list(range(1, 81)), want=("p95",))["p95"] == pytest.approx(76.05)
    assert percentiles(list(range(1, 501)), want=("p99",))["p99"] == pytest.approx(495.01)


def test_percentiles_rejects_non_finite_values():
    """NEW-4: `want=("p50",)` only, so the p90/p95 sample-size floors (which
    this 32-element fixture is below) can't fire and mask the non-finite
    check — the only guard that can raise here is the one under test."""
    with pytest.raises(ValueError, match="non-finite"):
        percentiles([1.0, float("nan")] + list(range(30)), want=("p50",))
    with pytest.raises(ValueError, match="non-finite"):
        percentiles([1.0, float("inf")] + list(range(30)), want=("p50",))


def test_percentiles_rejects_unknown_want_name():
    with pytest.raises(ValueError):
        percentiles(list(range(30)), want=("p50", "p42"))


def test_percentiles_p50_matches_a_bootstraps_point_estimate_on_the_same_data():
    """C1: percentiles()['p50'] and every bootstrap's point estimate must be
    the exact same quantity, computed the exact same way, not two
    definitions of 'median' that happen to agree except at even n. Isolate
    median(xs) from bootstrap_median_diff by subtracting a constant-zero
    group of the same size, and cross-check against the stdlib's own
    statistics.median as an independent oracle."""
    rng = random.Random(777)
    xs = [rng.lognormvariate(math.log(100.0), 0.5) for _ in range(100)]  # n=100
    p50 = percentiles(xs, want=("p50",))["p50"]
    zeros = [0.0] * len(xs)
    res = bootstrap_median_diff(xs, zeros, iterations=2, seed=0)
    assert p50 == res["point"]
    assert p50 == pytest.approx(statistics.median(xs))


# ---------------------------------------------------------------------------
# ecdf
# ---------------------------------------------------------------------------


def test_ecdf_is_sorted_and_ends_at_one():
    xs, ys = ecdf([3.0, 1.0, 2.0])
    assert xs == [1.0, 2.0, 3.0]
    assert ys[-1] == pytest.approx(1.0)


def test_ecdf_step_values_are_evenly_spaced():
    _xs, ys = ecdf([10.0, 20.0, 30.0, 40.0])
    assert ys == [pytest.approx(v) for v in (0.25, 0.5, 0.75, 1.0)]


def test_ecdf_on_empty_list_raises_instead_of_dividing_by_zero():
    with pytest.raises(ValueError):
        ecdf([])


def test_ecdf_tie_behavior_is_one_point_per_observation_not_per_distinct_x():
    """M6: repeated values must not be deduplicated — this is a step-plot
    shape (one (x, y) pair per observation), so the CDF value AT a tied x
    is read from the LAST occurrence, not the first."""
    xs, ys = ecdf([1.0, 2.0, 2.0, 2.0, 5.0])
    assert xs == [1.0, 2.0, 2.0, 2.0, 5.0]
    assert ys == [pytest.approx(v) for v in (0.2, 0.4, 0.6, 0.8, 1.0)]


# ---------------------------------------------------------------------------
# module documentation (I1, I2)
# ---------------------------------------------------------------------------


def test_module_docstring_states_the_percentile_and_interval_conventions():
    """I1/I2: the interpolation method and its numpy equivalent, and the
    bootstrap interval method and its limitation, must be stated somewhere
    a reader will find them — not left to be inferred from the formula."""
    doc = (stats_module.__doc__ or "").lower()
    assert "linear" in doc
    assert "numpy" in doc
    assert "percentile-method" in doc or "percentile method" in doc
    assert "biased" in doc


# ---------------------------------------------------------------------------
# _percentile_interval (C2, I4, I5)
# ---------------------------------------------------------------------------


def test_percentile_interval_pins_exact_endpoint_indices():
    """C2/I4: alpha/2 vs alpha, and the '-1' on the upper index, are exactly
    the mutations no relational assertion (lo < point < hi, or comparing
    widths across alpha) can distinguish. `draws` is a literal,
    already-known (and deliberately unsorted, to also exercise the internal
    sort) list, so the expected lo/hi are pinned by hand, not re-derived
    from the formula under test."""
    draws = [8.0, 3.0, 1.0, 6.0, 2.0, 7.0, 5.0, 4.0]  # sorted: 1..8

    # alpha=0.5: lo index = int(0.25 * 8) = 2 -> sorted[2] = 3.0
    #            hi index = int(0.75 * 8) - 1 = 5 -> sorted[5] = 6.0
    assert _percentile_interval(draws, alpha=0.5) == (3.0, 6.0)

    # alpha=0.25: lo index = int(0.125 * 8) = 1 -> sorted[1] = 2.0
    #             hi index = int(0.875 * 8) - 1 = 6 -> sorted[6] = 7.0
    assert _percentile_interval(draws, alpha=0.25) == (2.0, 7.0)


def test_percentile_interval_rejects_an_infeasible_iterations_alpha_combination():
    """I5: with too few draws for how extreme alpha is, the naive index
    arithmetic inverts. This exact input previously produced lo=900.0,
    hi=1.0 (backwards) instead of raising."""
    draws = [1.0, 50.0, 900.0]  # 3 draws
    with pytest.raises(ValueError):
        _percentile_interval(draws, alpha=0.99)


def test_percentile_interval_single_draw_does_not_wrap_around():
    """A single draw and the default-ish alpha computes hi index = -1 via
    the raw formula, which Python would silently resolve to the last
    element instead of raising."""
    with pytest.raises(ValueError):
        _percentile_interval([42.0], alpha=0.05)


def test_bootstrap_median_diff_rejects_infeasible_iterations_alpha_instead_of_inverting():
    """I5, end to end: the reviewer's exact failing example. Arrays are
    padded to clear MIN_BOOTSTRAP_SAMPLES; the bug is triggered by
    `iterations`/`alpha`, not by sample size."""
    a = [1.0, 50.0, 900.0] * 7  # 21 elements
    b = [0.0] * 21
    with pytest.raises(ValueError):
        bootstrap_median_diff(a, b, iterations=3, alpha=0.99, seed=5)


def test_bootstrap_median_diff_matches_an_independent_replay_of_the_resample_loop():
    """C2, end to end: replay bootstrap_median_diff's documented algorithm
    by hand (same seed, same per-iteration draw order: len(a) indices for
    a, then len(b) indices for b) and assert the function's lo/hi equal the
    exact order statistics of that independently-replayed draw list. `a`
    and `b` have different lengths so a bug that resampled the wrong side
    to the wrong length (I7) would also break this replay match."""
    a = [
        10.0, 12.0, 15.0, 20.0, 22.0, 25.0, 30.0, 33.0, 40.0, 45.0,
        50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0, 95.0,
    ]  # n=20
    b = [
        1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0,
        11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0,
        21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0, 30.0,
    ]  # n=30
    iterations, seed, alpha = 40, 314, 0.5

    rng = random.Random(seed)
    replayed_draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        replayed_draws.append(statistics.median(ra) - statistics.median(rb))
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_median_diff(a, b, iterations=iterations, seed=seed, alpha=alpha)
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


# ---------------------------------------------------------------------------
# bootstrap_median_diff
# ---------------------------------------------------------------------------


def test_bootstrap_interval_brackets_a_known_difference():
    a = [100.0] * 50
    b = [70.0] * 50
    res = bootstrap_median_diff(a, b, iterations=500, seed=1)
    assert res["point"] == pytest.approx(30.0)
    assert res["lo"] <= 30.0 <= res["hi"]


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
    small_a, small_b = big_a[:MIN_BOOTSTRAP_SAMPLES], big_b[:MIN_BOOTSTRAP_SAMPLES]
    wide = bootstrap_median_diff(small_a, small_b, iterations=800, seed=4)
    narrow = bootstrap_median_diff(big_a, big_b, iterations=800, seed=4)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])


def test_bootstrap_same_seed_is_reproducible_different_seed_is_not():
    """Published intervals must be reproducible from the recorded seed, so the
    same seed must give byte-identical output, and a different seed must
    actually move the resampled interval (not just be accepted as a no-op)."""
    rng = random.Random(20)
    a = [rng.gauss(100.0, 15.0) for _ in range(80)]
    b = [rng.gauss(70.0, 15.0) for _ in range(80)]
    r1 = bootstrap_median_diff(a, b, iterations=500, seed=42)
    r2 = bootstrap_median_diff(a, b, iterations=500, seed=42)
    assert r1 == r2

    r3 = bootstrap_median_diff(a, b, iterations=500, seed=43)
    assert r3 != r1


def test_bootstrap_wider_alpha_gives_narrower_interval():
    """alpha is the significance level (1 - confidence). A larger alpha demands
    less confidence, which must shrink the interval width for the same draws."""
    rng = random.Random(13)
    a = [rng.gauss(100.0, 15.0) for _ in range(80)]
    b = [rng.gauss(70.0, 15.0) for _ in range(80)]
    narrow_conf = bootstrap_median_diff(a, b, iterations=1000, seed=5, alpha=0.20)
    wide_conf = bootstrap_median_diff(a, b, iterations=1000, seed=5, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_bootstrap_median_diff_uses_median_not_mean_on_skewed_data():
    """C3: on symmetric (gaussian) fixtures mean ~= median, so a mutation
    swapping the median for the mean survives every gaussian/constant test
    in this file. Cold-start distributions are right-skewed — the spec's
    central premise, stated in bold — so only a right-skewed (lognormal)
    fixture can catch that mutation. The point estimate is an exact
    computation (no resampling noise), so this compares the two exactly."""
    rng = random.Random(556)
    a = [rng.lognormvariate(math.log(120.0), 0.5) for _ in range(60)]
    b = [rng.lognormvariate(math.log(90.0), 0.5) for _ in range(60)]
    expected_median_diff = statistics.median(a) - statistics.median(b)
    expected_mean_diff = statistics.mean(a) - statistics.mean(b)
    assert abs(expected_median_diff - expected_mean_diff) > 1.0  # fixture sanity

    res = bootstrap_median_diff(a, b, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median_diff)
    assert res["point"] != pytest.approx(expected_mean_diff, rel=1e-3)


def test_bootstrap_median_diff_rejects_below_the_bootstrap_sample_floor():
    """I3: the reviewer's exact failing example — a "95% CI" from n=1."""
    with pytest.raises(ValueError, match="at least"):
        bootstrap_median_diff([100.0], [70.0])


def test_bootstrap_median_diff_allows_exactly_at_the_bootstrap_sample_floor():
    a = [100.0] * MIN_BOOTSTRAP_SAMPLES
    b = [70.0] * MIN_BOOTSTRAP_SAMPLES
    res = bootstrap_median_diff(a, b, iterations=50, seed=1)
    assert res["point"] == pytest.approx(30.0)


def test_bootstrap_rejects_empty_sample():
    """NEW-3: `b` is padded above MIN_BOOTSTRAP_SAMPLES so only `a`'s
    emptiness can raise; `match=` pins which guard fired."""
    with pytest.raises(ValueError, match="empty"):
        bootstrap_median_diff([], [1.0] * MIN_BOOTSTRAP_SAMPLES)


def test_bootstrap_rejects_non_positive_iterations():
    """NEW-3: the original 2-element fixtures are below MIN_BOOTSTRAP_SAMPLES,
    so deleting the iterations check entirely still raises via the sample
    floor and this test can't tell the difference. Arrays are padded above
    the floor, and `match=` pins the iterations-specific message."""
    a = [1.0] * MIN_BOOTSTRAP_SAMPLES
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_median_diff(a, b, iterations=0)


def test_bootstrap_rejects_alpha_out_of_range():
    """NEW-3: same masking concern as the iterations test above."""
    a = [1.0] * MIN_BOOTSTRAP_SAMPLES
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_median_diff(a, b, alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_median_diff(a, b, alpha=1.0)


def test_bootstrap_rejects_non_finite_values():
    """NEW-4: `a` is padded to exactly MIN_BOOTSTRAP_SAMPLES so the floor
    can't fire instead of the non-finite check."""
    a = [1.0, float("nan")] + [2.0] * (MIN_BOOTSTRAP_SAMPLES - 2)
    b = [3.0] * MIN_BOOTSTRAP_SAMPLES
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_median_diff(a, b)


# ---------------------------------------------------------------------------
# bootstrap_contrast_difference
# ---------------------------------------------------------------------------


def test_contrast_difference_interval_brackets_a_known_gap():
    """Spread (non-constant) inputs so the interval can genuinely differ from
    the point estimate — constant inputs make every resample identical and
    cannot prove resampling happened."""
    rng = random.Random(21)
    a = [rng.gauss(100.0, 10.0) for _ in range(60)]
    b = [rng.gauss(70.0, 10.0) for _ in range(60)]
    c = [rng.gauss(60.0, 10.0) for _ in range(60)]
    expected_point = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    res = bootstrap_contrast_difference(a, b, c, iterations=600, seed=2)
    assert res["point"] == pytest.approx(expected_point)
    assert res["lo"] < res["point"] < res["hi"]


def test_contrast_difference_uses_median_not_mean_on_skewed_data():
    """C3: right-skewed fixture, applied to the ranking-claim function
    specifically — this is the entry point the spec singles out as
    deciding whether "compile cache mattered more" is a finding, so a
    silent mean-for-median swap here is the highest-stakes version of this
    bug in the module."""
    rng = random.Random(2024)
    a = [rng.lognormvariate(math.log(150.0), 0.6) for _ in range(30)]
    b = [rng.lognormvariate(math.log(100.0), 0.6) for _ in range(30)]
    c = [rng.lognormvariate(math.log(80.0), 0.6) for _ in range(30)]
    expected_median_contrast = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    expected_mean_contrast = (statistics.mean(a) - statistics.mean(b)) - (
        statistics.mean(b) - statistics.mean(c)
    )
    assert abs(expected_median_contrast - expected_mean_contrast) > 5.0  # fixture sanity

    res = bootstrap_contrast_difference(a, b, c, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median_contrast)
    assert res["point"] != pytest.approx(expected_mean_contrast, rel=1e-3)


def test_contrast_difference_rejects_empty_sample():
    with pytest.raises(ValueError, match="empty"):
        bootstrap_contrast_difference([], [1.0] * MIN_BOOTSTRAP_SAMPLES, [1.0] * MIN_BOOTSTRAP_SAMPLES)


def test_contrast_difference_rejects_below_the_bootstrap_sample_floor():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_contrast_difference([1.0] * 5, [1.0] * 5, [1.0] * 5)


def test_contrast_difference_same_seed_reproducible_different_seed_is_not():
    """I6: bootstrap_contrast_difference carries the ranking claim and was
    the least-tested of the four entry points — ignoring `seed` entirely
    previously survived the whole suite."""
    rng = random.Random(41)
    a = [rng.gauss(100.0, 15.0) for _ in range(40)]
    b = [rng.gauss(70.0, 15.0) for _ in range(40)]
    c = [rng.gauss(60.0, 15.0) for _ in range(40)]
    r1 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=9)
    r2 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=9)
    assert r1 == r2

    r3 = bootstrap_contrast_difference(a, b, c, iterations=300, seed=10)
    assert r3 != r1


def test_contrast_difference_wider_alpha_gives_narrower_interval():
    """I6."""
    rng = random.Random(42)
    a = [rng.gauss(100.0, 15.0) for _ in range(40)]
    b = [rng.gauss(70.0, 15.0) for _ in range(40)]
    c = [rng.gauss(60.0, 15.0) for _ in range(40)]
    narrow_conf = bootstrap_contrast_difference(a, b, c, iterations=800, seed=6, alpha=0.20)
    wide_conf = bootstrap_contrast_difference(a, b, c, iterations=800, seed=6, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_contrast_difference_handles_unequal_length_arms():
    """I7: real arms have unequal n after failure exclusion. A version that
    resampled b or c to len(a), or used a hardcoded resample length, would
    still run without crashing — only the point estimate's agreement with
    an independent computation, and the interval's sanity, would be off."""
    rng = random.Random(43)
    a = [rng.gauss(100.0, 10.0) for _ in range(20)]
    b = [rng.gauss(70.0, 10.0) for _ in range(35)]
    c = [rng.gauss(60.0, 10.0) for _ in range(50)]
    expected_point = (statistics.median(a) - statistics.median(b)) - (
        statistics.median(b) - statistics.median(c)
    )
    res = bootstrap_contrast_difference(a, b, c, iterations=300, seed=1)
    assert res["point"] == pytest.approx(expected_point)
    assert res["lo"] < res["point"] < res["hi"]


def test_contrast_difference_matches_an_independent_replay_of_the_resample_loop():
    """I7/C2, end to end: the point estimate alone can't catch a wrong
    resample length — it's computed from the original a/b/c, not the
    resampled draws — so a version that resampled b or c to len(a) instead
    of their own length would still pass the point-estimate check above.
    Replay the documented algorithm by hand (same seed, same per-iteration
    draw order: len(a), then len(b), then len(c)) with three different
    lengths, and assert the function's lo/hi equal the exact order
    statistics of that independently-replayed draw list."""
    rng = random.Random(44)
    a = [rng.gauss(100.0, 10.0) for _ in range(20)]
    b = [rng.gauss(70.0, 10.0) for _ in range(33)]
    c = [rng.gauss(60.0, 10.0) for _ in range(47)]
    iterations, seed, alpha = 50, 315, 0.5

    replay_rng = random.Random(seed)
    replayed_draws = []
    for _ in range(iterations):
        ra = [a[replay_rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[replay_rng.randrange(len(b))] for _ in range(len(b))]
        rc = [c[replay_rng.randrange(len(c))] for _ in range(len(c))]
        replayed_draws.append(
            (statistics.median(ra) - statistics.median(rb))
            - (statistics.median(rb) - statistics.median(rc))
        )
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_contrast_difference(a, b, c, iterations=iterations, seed=seed, alpha=alpha)
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


# ---------------------------------------------------------------------------
# within_host_triples
# ---------------------------------------------------------------------------


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


def test_within_host_triples_rejects_wrong_arm_count():
    """Two runs instead of three: incomplete triple, must not be kept."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_duplicate_arm():
    """Three runs, right count, but arm B is missing and A is duplicated —
    the set of arms present doesn't match the required set."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_mixed_hosts():
    """All three arms present, correct count, but not all on the same host."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h2"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_rejects_an_extra_duplicate_arm():
    """NEW-5: a set comparison would wrongly accept this group — the SET of
    arms present is {A, B, C}, matching `arms` — but there are 4 rows, not
    3 (A appears twice). This is the exact multiset-vs-set distinction the
    docstring cites to justify dropping the separate arm-count check (M2),
    so it should be the one thing that is actually pinned. The existing
    rejection tests ([A, A, C] and [A, B]) both also fail a set comparison,
    so they can't tell a multiset check from a set check apart."""
    rows = [
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "A", "host_id": "h1"},
        {"triple_index": 0, "arm": "B", "host_id": "h1"},
        {"triple_index": 0, "arm": "C", "host_id": "h1"},
    ]
    assert within_host_triples(rows, arms=("A", "B", "C")) == []


def test_within_host_triples_output_is_sorted_by_triple_index():
    """M8: rows arrive with triple 2 before triple 0 before triple 1; the
    kept groups must come back ordered by triple_index, not input order."""
    rows = []
    for idx in (2, 0, 1):
        rows.extend(
            [
                {"triple_index": idx, "arm": "A", "host_id": f"h{idx}"},
                {"triple_index": idx, "arm": "B", "host_id": f"h{idx}"},
                {"triple_index": idx, "arm": "C", "host_id": f"h{idx}"},
            ]
        )
    kept = within_host_triples(rows, arms=("A", "B", "C"))
    assert [t[0]["triple_index"] for t in kept] == [0, 1, 2]


# ---------------------------------------------------------------------------
# bootstrap_paired_median_diff / bootstrap_paired_contrast_difference
#
# within_host_triples produces *paired* data: the three runs in a triple are
# correlated (same host), not independent draws. bootstrap_median_diff and
# bootstrap_contrast_difference resample arms independently, which is correct
# for the pooled, unpaired analysis but wrong here — it would silently
# reintroduce the host confound the pairing exists to remove. These two
# functions resample whole triples with replacement instead, and report the
# median of per-triple deltas rather than a difference of two medians.
# ---------------------------------------------------------------------------


def test_paired_median_diff_point_is_median_of_per_triple_deltas():
    # 20 triples with delta 30.0, one outlier triple with delta 999.0.
    # median of 21 values, 20 of which are 30.0, is 30.0.
    deltas = [30.0] * 20 + [999.0]
    triples = _value_triples(deltas)
    res = bootstrap_paired_median_diff(triples, "A", "B", iterations=50, seed=1)
    assert res["point"] == pytest.approx(statistics.median(deltas))


def test_paired_contrast_difference_point_is_median_of_per_triple_contrasts():
    # Under the B=C=0 construction, (A-B)-(B-C) reduces to A.
    contrasts = [20.0] * 20 + [-500.0]
    triples = _value_triples(contrasts)
    res = bootstrap_paired_contrast_difference(triples, iterations=50, seed=1)
    assert res["point"] == pytest.approx(statistics.median(contrasts))


def test_paired_contrast_difference_uses_the_correct_contrast_formula():
    """NEW-1 (critical): every other test of this statistic uses
    `_value_triples`, whose B=C=0 construction makes (A-B)-(B-C) and
    (A-B)-(C-B) collapse to the same value (A), so a sign-flip mutation on
    the second term is invisible to them. B=70, C=60 here are distinct and
    non-zero, so the correct formula (A-B)-(B-C) = 30-10 = 20 is
    distinguishable from the wrong one (A-B)-(C-B) = 30-(-10) = 40, which
    is also just A-C."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    res = bootstrap_paired_contrast_difference(triples, iterations=10, seed=1)
    assert res["point"] == pytest.approx(20.0)


def test_paired_median_diff_accepts_a_callable_value_extractor():
    """value can be a key name (the default) or a callable — both t_total and
    t_weights get this treatment, so it must not be hardcoded to one field."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    res = bootstrap_paired_median_diff(
        triples, "A", "B", value=lambda r: r["t_total"] * 2, iterations=10, seed=1
    )
    assert res["point"] == pytest.approx(60.0)  # 2 * (100 - 70)


def test_paired_median_diff_accepts_a_different_key_name():
    """M4: `value`'s string-key branch was only ever exercised with
    't_total' — the docstring promises t_weights works too."""
    triples = _const_triples(20, 100.0, 70.0, 60.0, field="t_weights")
    res = bootstrap_paired_median_diff(
        triples, "A", "B", value="t_weights", iterations=20, seed=1
    )
    assert res["point"] == pytest.approx(30.0)


def test_paired_bootstrap_resamples_whole_triples_and_an_outlier_widens_it():
    """The unit of resampling is the triple, not the delta list flattened by
    coincidence. 21 constant-delta triples give a degenerate interval on
    their own; replacing a third of them with a much larger outlier delta
    must widen the interval, because an outlier triple can now be drawn
    0, 1, 2... times per resample. A version that dropped the outlier's
    leverage (e.g. sampling without replacement, or capping each triple to
    appear once) would keep this degenerate."""
    without_outlier = _value_triples([30.0] * 21)
    res_without = bootstrap_paired_median_diff(without_outlier, "A", "B", iterations=3000, seed=9)
    assert res_without["lo"] == res_without["hi"] == pytest.approx(30.0)

    with_outlier = _value_triples([30.0] * 14 + [300.0] * 7)
    res_with = bootstrap_paired_median_diff(with_outlier, "A", "B", iterations=3000, seed=9)
    assert (res_with["hi"] - res_with["lo"]) > 0.0


def test_paired_median_diff_matches_an_independent_replay_of_the_resample_loop():
    """NEW-2, mirroring the unpaired replay tests: the same reasoning
    ('a point estimate alone cannot catch a wrong resample size') applies
    to the paired engine, which is exactly where the "resample the whole
    triple" claim lives — and it was not covered. `for _ in range(1)`
    (resample of size 1) and `rng.randrange(n - 1)` (the last triple never
    drawn) both previously passed the whole suite. Replay the documented
    algorithm by hand (same seed, one randrange draw per position in the
    deltas list) and assert lo/hi equal the exact order statistics of the
    independently-replayed draws."""
    rng = random.Random(50)
    deltas = [rng.gauss(30.0, 15.0) for _ in range(25)]
    triples = _value_triples(deltas)
    iterations, seed, alpha = 40, 316, 0.5

    replay_rng = random.Random(seed)
    n = len(deltas)
    replayed_draws = []
    for _ in range(iterations):
        resample = [deltas[replay_rng.randrange(n)] for _ in range(n)]
        replayed_draws.append(statistics.median(resample))
    replayed_sorted = sorted(replayed_draws)
    expected_lo = replayed_sorted[int((alpha / 2) * iterations)]
    expected_hi = replayed_sorted[int((1 - alpha / 2) * iterations) - 1]

    res = bootstrap_paired_median_diff(
        triples, "A", "B", iterations=iterations, seed=seed, alpha=alpha
    )
    assert res["lo"] == expected_lo
    assert res["hi"] == expected_hi


def test_paired_median_diff_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(30)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    r1 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    r2 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=11)
    assert r1 == r2

    r3 = bootstrap_paired_median_diff(triples, "A", "B", iterations=500, seed=12)
    assert r3 != r1


def test_paired_median_diff_wider_alpha_gives_narrower_interval():
    rng = random.Random(31)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    narrow_conf = bootstrap_paired_median_diff(
        triples, "A", "B", iterations=800, seed=15, alpha=0.20
    )
    wide_conf = bootstrap_paired_median_diff(triples, "A", "B", iterations=800, seed=15, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_paired_median_diff_uses_median_not_mean_on_skewed_data():
    """C3, paired version: lognormal per-triple deltas via the B=C=0
    construction, so the delta list is directly a right-skewed sample."""
    rng = random.Random(42)
    deltas = [rng.lognormvariate(math.log(50.0), 1.0) for _ in range(25)]
    expected_median = statistics.median(deltas)
    expected_mean = statistics.mean(deltas)
    assert abs(expected_median - expected_mean) > 5.0  # fixture sanity

    triples = _value_triples(deltas)
    res = bootstrap_paired_median_diff(triples, "A", "B", iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median)
    assert res["point"] != pytest.approx(expected_mean, rel=1e-3)


def test_paired_contrast_difference_same_seed_reproducible_different_seed_is_not():
    rng = random.Random(32)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    r1 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    r2 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=16)
    assert r1 == r2

    r3 = bootstrap_paired_contrast_difference(triples, iterations=500, seed=17)
    assert r3 != r1


def test_paired_contrast_difference_wider_alpha_gives_narrower_interval():
    rng = random.Random(33)
    triples = _gauss_triples(rng, 40, 100.0, 70.0, 60.0, sd=10.0)
    narrow_conf = bootstrap_paired_contrast_difference(
        triples, iterations=800, seed=18, alpha=0.20
    )
    wide_conf = bootstrap_paired_contrast_difference(triples, iterations=800, seed=18, alpha=0.01)
    assert (narrow_conf["hi"] - narrow_conf["lo"]) < (wide_conf["hi"] - wide_conf["lo"])


def test_paired_contrast_difference_uses_median_not_mean_on_skewed_data():
    """C3, paired contrast version."""
    rng = random.Random(43)
    contrasts = [rng.lognormvariate(math.log(50.0), 1.0) for _ in range(25)]
    expected_median = statistics.median(contrasts)
    expected_mean = statistics.mean(contrasts)
    assert abs(expected_median - expected_mean) > 5.0  # fixture sanity

    triples = _value_triples(contrasts)
    res = bootstrap_paired_contrast_difference(triples, iterations=50, seed=1)
    assert res["point"] == pytest.approx(expected_median)
    assert res["point"] != pytest.approx(expected_mean, rel=1e-3)


def test_paired_interval_is_tighter_than_unpaired_when_host_effect_dominates():
    """The spec's own claim: disagreement between the paired and unpaired
    estimates is itself a finding, so the two must actually be *capable* of
    disagreeing. Build triples where a large per-host offset is common to
    all three arms within a triple (so it cancels in the paired delta) but
    is not accounted for by the unpaired bootstrap, which pools all A-values
    and all B-values and resamples them independently of which host/triple
    they came from. If a paired function were implemented by just calling
    the unpaired one on the pooled per-arm lists (losing the pairing), this
    assertion would fail: the widths would come out equal."""
    rng = random.Random(99)
    triples = []
    a_vals, b_vals = [], []
    for i in range(30):
        host_offset = rng.gauss(0.0, 50.0)  # dominant, shared within a triple
        a = 100.0 + host_offset + rng.gauss(0.0, 2.0)
        b = 70.0 + host_offset + rng.gauss(0.0, 2.0)
        c = 60.0 + host_offset + rng.gauss(0.0, 2.0)
        triples.append(_triple(i, f"h{i}", a, b, c))
        a_vals.append(a)
        b_vals.append(b)

    paired = bootstrap_paired_median_diff(triples, "A", "B", iterations=1500, seed=7)
    unpaired = bootstrap_median_diff(a_vals, b_vals, iterations=1500, seed=7)

    paired_width = paired["hi"] - paired["lo"]
    unpaired_width = unpaired["hi"] - unpaired["lo"]
    assert paired_width < unpaired_width


def test_paired_median_diff_rejects_below_the_bootstrap_sample_floor():
    """I3: within-host triples are explicitly expected to be a minority of
    the data, so this is the path most likely to be called with too few
    units."""
    triples = _const_triples(5, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_median_diff(triples, "A", "B")


def test_paired_contrast_difference_rejects_below_the_bootstrap_sample_floor():
    triples = _const_triples(5, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_median_diff_rejects_empty_triples():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_median_diff([], "A", "B")


def test_paired_contrast_difference_rejects_empty_triples():
    with pytest.raises(ValueError, match="at least"):
        bootstrap_paired_contrast_difference([])


def test_paired_median_diff_rejects_a_triple_missing_an_arm():
    """19 well-formed triples clear MIN_BOOTSTRAP_SAMPLES; the 20th is
    missing arm B, which is what this test actually exercises."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [{"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0}]
    ]
    with pytest.raises(ValueError, match="missing arm"):
        bootstrap_paired_median_diff(triples, "A", "B")


def test_paired_contrast_difference_rejects_a_triple_missing_an_arm():
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 70.0},
        ]
    ]
    with pytest.raises(ValueError, match="missing arm"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_finite_values():
    """19 well-formed triples clear the floor; the 20th carries the NaN
    this test is actually checking for."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [_triple(19, "h19", float("nan"), 70.0, 60.0)]
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_paired_median_diff(triples, "A", "B")
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_functions_reject_non_positive_iterations():
    """NEW-3 (same masking class, applied here proactively): a 1-triple
    fixture is below MIN_BOOTSTRAP_SAMPLES, so deleting the iterations
    check entirely would still raise via the floor and this test couldn't
    tell. 20 triples clear the floor; `match=` pins the right message."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_paired_median_diff(triples, "A", "B", iterations=0)
    with pytest.raises(ValueError, match="must be positive"):
        bootstrap_paired_contrast_difference(triples, iterations=0)


def test_paired_functions_reject_alpha_out_of_range():
    """NEW-3: same masking concern as the iterations test above."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_median_diff(triples, "A", "B", alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_contrast_difference(triples, alpha=1.0)


def test_paired_median_diff_checks_alpha_before_triples_count():
    """M7: cheap parameter checks (iterations, alpha) must run before the
    triples-count / per-triple delta work, so a caller passing both a bad
    alpha and too few (here, zero) triples gets the alpha error, not a
    "not enough triples" error that hides it."""
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_median_diff([], "A", "B", alpha=1.5)


def test_paired_contrast_difference_checks_alpha_before_triples_count():
    with pytest.raises(ValueError, match="alpha"):
        bootstrap_paired_contrast_difference([], alpha=1.5)


def test_paired_median_diff_rejects_a_triple_with_a_duplicate_arm():
    """Two rows both claim arm A; C is present too, so a missing-arm check
    alone would not catch this — the ambiguous duplicate must be its own
    rejection, not silently resolved by whichever row was written last.
    19 well-formed triples clear the floor; the 20th is the duplicate."""
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 999.0},
            {"triple_index": 19, "arm": "C", "host_id": "h19", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError, match="duplicate arm"):
        bootstrap_paired_median_diff(triples, "A", "C")


def test_paired_contrast_difference_rejects_a_triple_with_a_duplicate_arm():
    triples = _const_triples(19, 100.0, 70.0, 60.0) + [
        [
            {"triple_index": 19, "arm": "A", "host_id": "h19", "t_total": 100.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 999.0},
            {"triple_index": 19, "arm": "B", "host_id": "h19", "t_total": 70.0},
            {"triple_index": 19, "arm": "C", "host_id": "h19", "t_total": 60.0},
        ]
    ]
    with pytest.raises(ValueError, match="duplicate arm"):
        bootstrap_paired_contrast_difference(triples)


def test_paired_contrast_difference_rejects_wrong_arms_length():
    """The contrast (A-B)-(B-C) is only defined for exactly three arms. A
    2-tuple or 4-tuple must be rejected explicitly rather than crashing on
    an IndexError deep inside the per-triple delta computation."""
    triples = [_triple(0, "h1", 100.0, 70.0, 60.0)]
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B"))
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B", "C", "D"))


def test_paired_contrast_difference_rejects_a_padded_duplicate_arms_tuple():
    """A length check is not fully subsumed by a distinctness check: a
    4-tuple with one internal duplicate (A, B, B, C) has only 3 unique
    values, so `len(set(arms)) != 3` alone would wrongly accept it — the
    length must be checked too. 20 triples clear MIN_BOOTSTRAP_SAMPLES so
    the floor check can't mask this guard the way a 1-triple fixture would."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "B", "B", "C"))


def test_paired_median_diff_rejects_non_distinct_arms():
    """M5: arm_a == arm_b must be rejected, not silently returned as a
    'point': 0.0 confidence interval on nothing. Uses enough triples to
    clear MIN_BOOTSTRAP_SAMPLES, so the floor check can't mask this guard —
    a single triple would raise for the wrong reason and this test would
    pass even with the arm-distinctness guard deleted."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_median_diff(triples, "A", "A")


def test_paired_contrast_difference_rejects_non_distinct_arms():
    """M5. Same floor-masking concern as the median-diff version above."""
    triples = _const_triples(20, 100.0, 70.0, 60.0)
    with pytest.raises(ValueError):
        bootstrap_paired_contrast_difference(triples, arms=("A", "A", "A"))
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.stats'`

- [ ] **Step 3: Implement**

`coldstart/analysis/stats.py`:

```python
"""Non-parametric statistics for cold-start measurements.

Every quantity this module reports is a percentile, an ECDF, or a bootstrap
confidence interval on one of those — never a mean or a standard deviation.
Cold-start distributions are right-skewed with a heavy tail (spec 9b); a
mean is pulled by the tail and a standard deviation overstates how tight the
bulk of the distribution is.

Percentile convention: linear interpolation between order statistics —
numpy's ``method="linear"``, which is also numpy's default
(``numpy.percentile``'s ``method``/``interpolation`` argument). This is
deliberately not nearest-rank (``ceil(q * n)``, which selects an existing
observation rather than interpolating between two). The same ``_quantile``
function backs both ``percentiles()`` and the median inside every bootstrap
in this module, so ``percentiles(xs)["p50"]`` and a bootstrap's point
estimate on the same data are the same computation, not two definitions of
"median" that usually happen to agree and occasionally don't.

Confidence interval convention: percentile-method bootstrap intervals — the
alpha/2 and 1-alpha/2 order statistics of the resampled distribution. This
is first-order accurate and known to be biased for skewed statistics (it
does not correct for that skew, the way BCa does); it is used here because
it is simple and well understood, and is defensible as long as it is
stated, which this docstring is doing.

Sample floors: MIN_SAMPLES gates which percentiles ``percentiles()`` is
willing to report — a percentile from too few samples is an observation,
not a measurement (spec 5). MIN_BOOTSTRAP_SAMPLES applies the same
discipline to every bootstrap interval in this module, since every one of
them resamples a median.
"""

import math
import random

# A percentile needs enough samples to be a measurement rather than an
# observation. p99 at n=100 is one or two points — see spec 5. Each entry is
# a pre-registered parameter: changing any one of them changes what this
# module is willing to publish.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}

# Same discipline as MIN_SAMPLES, applied to bootstrap intervals: every
# bootstrap in this module resamples a median, so it inherits p50's floor.
# Without this, bootstrap_median_diff([100.0], [70.0]) would return a
# confident-looking, zero-width "95% CI" built from a single observation —
# the confidence-interval equivalent of reporting p99 from two data points.
MIN_BOOTSTRAP_SAMPLES = MIN_SAMPLES["p50"]


def _validate_samples(values: list[float], name: str) -> list[float]:
    """Fail loudly on the input domains a percentile/bootstrap silently
    mishandles: empty sequences (division by zero, IndexError, or an empty
    `random.randrange` range) and non-finite values (a NaN or inf corrupting
    a sort or a median without raising anywhere)."""
    xs = list(values)
    if not xs:
        raise ValueError(f"{name} must not be empty")
    for v in xs:
        if not math.isfinite(v):
            raise ValueError(f"{name} contains a non-finite value: {v!r}")
    return xs


def _validate_bootstrap_sample(values: list[float], name: str) -> list[float]:
    """`_validate_samples`'s checks, plus MIN_BOOTSTRAP_SAMPLES: a thin
    sample must not be allowed to bootstrap to a confident-looking interval.
    """
    xs = _validate_samples(values, name)
    if len(xs) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{name} has {len(xs)} samples; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    return xs


def _quantile(sorted_xs: list[float], q: float) -> float:
    """Linear interpolation between order statistics — numpy's
    ``method="linear"``, also numpy's default. At q=0.5 this is exactly the
    textbook median: the average of the two middle values at even n, the
    single middle value at odd n. Every median-shaped computation in this
    module (percentiles' p50, and every bootstrap's point estimate) goes
    through this one function so the same quantity cannot measure
    differently in two places in the same publication.

    `sorted_xs` must already be sorted; this does not sort, since a
    bootstrap calls it once per resample and paying to re-sort here (on top
    of the sort `_median` already does) would double the cost for nothing.
    """
    n = len(sorted_xs)
    idx = q * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_xs[lo]
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def _median(values) -> float:
    """The one median implementation this module uses — see the module
    docstring and `_quantile`. Equivalent to `statistics.median`, expressed
    via `_quantile` so it is textually the same code path as `percentiles`'s
    p50, not a second implementation that happens to agree most of the
    time."""
    return _quantile(sorted(values), 0.5)


def percentiles(values, want=("p50", "p90", "p95")) -> dict[str, float]:
    """Percentiles of `values` at the names in `want` (e.g. "p50", "p90"),
    refusing any name whose MIN_SAMPLES floor `values` doesn't meet. See the
    module docstring for the interpolation convention."""
    xs = sorted(_validate_samples(values, "values"))
    n = len(xs)
    out = {}
    for name in want:
        if name not in MIN_SAMPLES:
            raise ValueError(f"unknown percentile {name!r}; known: {sorted(MIN_SAMPLES)}")
        need = MIN_SAMPLES[name]
        if n < need:
            raise ValueError(
                f"{name} requires at least {need} samples, got {n}; "
                "reporting it would be an observation, not a measurement"
            )
        q = int(name[1:]) / 100.0
        out[name] = _quantile(xs, q)
    return out


def ecdf(values) -> tuple[list[float], list[float]]:
    """Empty input has no well-defined ECDF (the step size divides by n), so
    it is refused rather than silently returning ([], []).

    Tie behavior: a repeated value gets one (x, y) pair per observation, not
    one pair per distinct x — this is the step-function shape a plotter
    expects (e.g. matplotlib's ``plt.step(..., where="post")``), not a
    deduplicated x -> F(x) lookup table. To read the CDF value AT a
    particular x from these arrays, take the y from the LAST occurrence of
    that x; the y at an earlier tied occurrence understates F(x).
    """
    xs = sorted(_validate_samples(values, "values"))
    n = len(xs)
    return xs, [(i + 1) / n for i in range(n)]


def _check_iterations_and_alpha(iterations: int, alpha: float) -> None:
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")


def _percentile_interval(draws: list[float], alpha: float) -> tuple[float, float]:
    """The one percentile-method endpoint computation every bootstrap in
    this module uses: the alpha/2 and 1-alpha/2 order statistics of the
    resampled distribution `draws`.

    Also the one place the lo <= hi invariant is enforced. With too few
    draws for how extreme `alpha` is, the naive index arithmetic can put the
    "lo" index above the "hi" index and return a backwards interval instead
    of raising. `lo_idx > hi_idx` alone is sufficient: lo_idx = int((alpha/2)
    * n) is always >= 0, so a negative hi_idx (which would otherwise wrap
    around to the end of the sorted list via Python's negative indexing) is
    already > it, and `alpha < 1` (enforced by every caller) keeps lo_idx
    below n. Checking those cases separately would just be the same
    condition twice — see the M1-class cleanup this module already does.
    """
    xs = sorted(draws)
    n = len(xs)
    lo_idx = int((alpha / 2) * n)
    hi_idx = int((1 - alpha / 2) * n) - 1
    if lo_idx > hi_idx:
        raise ValueError(
            f"iterations={n} is too few for alpha={alpha}: the percentile-method "
            f"endpoints would invert (lo index {lo_idx}, hi index {hi_idx}); "
            "increase iterations"
        )
    return xs[lo_idx], xs[hi_idx]


def bootstrap_median_diff(a, b, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Non-parametric interval on median(a) - median(b). No distributional assumption.

    Do not call this on within_host_triples output: it resamples a and b
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_median_diff for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_bootstrap_sample(a, "a")
    b = _validate_bootstrap_sample(b, "b")
    rng = random.Random(seed)
    point = _median(a) - _median(b)
    draws = []
    for _ in range(iterations):
        ra = [a[rng.randrange(len(a))] for _ in range(len(a))]
        rb = [b[rng.randrange(len(b))] for _ in range(len(b))]
        draws.append(_median(ra) - _median(rb))
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_contrast_difference(a, b, c, iterations=10000, seed=0, alpha=0.05) -> dict:
    """Interval on (A-B) - (B-C): the ranking claim needs its own interval.

    Do not call this on within_host_triples output: it resamples a, b, and c
    independently, which is correct for the pooled, unpaired analysis but
    silently reintroduces the host confound on paired data. Use
    bootstrap_paired_contrast_difference for that.
    """
    _check_iterations_and_alpha(iterations, alpha)
    a = _validate_bootstrap_sample(a, "a")
    b = _validate_bootstrap_sample(b, "b")
    c = _validate_bootstrap_sample(c, "c")
    rng = random.Random(seed)

    def draw(xs):
        return [xs[rng.randrange(len(xs))] for _ in range(len(xs))]

    point = (_median(a) - _median(b)) - (_median(b) - _median(c))
    vals = []
    for _ in range(iterations):
        ra, rb, rc = draw(a), draw(b), draw(c)
        vals.append((_median(ra) - _median(rb)) - (_median(rb) - _median(rc)))
    lo, hi = _percentile_interval(vals, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def within_host_triples(rows, arms=("A", "B", "C")) -> list[list[dict]]:
    """Triples whose runs all landed on one host — the host confound removed.

    A group survives only if the runs cover exactly the required set of
    arms (no missing arm, no duplicate standing in for a missing one) and
    every run shares one host_id. There is no separate "right number of
    runs" check: `sorted(arm list) == sorted(arms)` can only hold at equal
    length, so a group with the wrong count is already rejected by the arm
    check. `sorted()` on `groups.items()` makes the output order
    deterministic by triple_index, rather than incidental to dict iteration
    order.
    """
    groups: dict[int, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["triple_index"], []).append(r)
    kept = []
    for _, g in sorted(groups.items()):
        if sorted(x["arm"] for x in g) != sorted(arms):
            continue
        if len({x["host_id"] for x in g}) != 1:
            continue
        kept.append(g)
    return kept


def _arm_lookup(triple: list[dict]) -> dict[str, dict]:
    """Map arm -> row for one triple, rejecting a duplicate arm outright —
    a duplicate silently shadowing a missing arm is worse than a KeyError."""
    out: dict[str, dict] = {}
    for row in triple:
        arm = row["arm"]
        if arm in out:
            raise ValueError(f"triple has duplicate arm {arm!r}: {triple}")
        out[arm] = row
    return out


def _row_value(row: dict, value) -> float:
    """`value` is a key name or a callable(row) -> float — both t_total and
    t_weights get this treatment, so it is never hardcoded to one field."""
    v = value(row) if callable(value) else row[value]
    if not math.isfinite(v):
        raise ValueError(f"non-finite value in row {row!r}: {v!r}")
    return v


def _paired_delta(triple: list[dict], arm_a: str, arm_b: str, value) -> float:
    lookup = _arm_lookup(triple)
    for arm in (arm_a, arm_b):
        if arm not in lookup:
            raise ValueError(f"triple is missing arm {arm!r}: has {sorted(lookup)}")
    return _row_value(lookup[arm_a], value) - _row_value(lookup[arm_b], value)


def _paired_contrast_delta(triple: list[dict], arms: tuple[str, str, str], value) -> float:
    lookup = _arm_lookup(triple)
    for arm in arms:
        if arm not in lookup:
            raise ValueError(f"triple is missing arm {arm!r}: has {sorted(lookup)}")
    a_val = _row_value(lookup[arms[0]], value)
    b_val = _row_value(lookup[arms[1]], value)
    c_val = _row_value(lookup[arms[2]], value)
    return (a_val - b_val) - (b_val - c_val)


def _bootstrap_median_of_units(deltas: list[float], iterations: int, seed: int, alpha: float) -> dict:
    """Shared engine for both paired bootstraps: `deltas` already holds one
    scalar per independent unit (one per triple). Resampling this list with
    replacement is what makes the unit of resampling the triple rather than
    the individual arm observation inside it.

    Callers are responsible for the MIN_BOOTSTRAP_SAMPLES floor and the
    iterations/alpha check before calling this — checking those here too
    would be a third copy of a check already made once at the public entry
    point, and would run after the (more expensive) per-triple delta
    computation instead of before it.
    """
    rng = random.Random(seed)
    n = len(deltas)
    point = _median(deltas)
    draws = []
    for _ in range(iterations):
        resample = [deltas[rng.randrange(n)] for _ in range(n)]
        draws.append(_median(resample))
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}


def bootstrap_paired_median_diff(
    triples: list[list[dict]],
    arm_a: str,
    arm_b: str,
    value="t_total",
    iterations=10000,
    seed=0,
    alpha=0.05,
) -> dict:
    """Paired bootstrap on within_host_triples output: the interval on the
    median of arm_a - arm_b, computed once per triple.

    Resamples whole triples with replacement, not individual arm
    observations — the two runs in a triple are not independent draws, they
    share a host, and treating them as interchangeable with runs from other
    triples would reintroduce the host confound within_host_triples exists
    to remove. See bootstrap_median_diff for the unpaired, pooled version.
    """
    _check_iterations_and_alpha(iterations, alpha)
    if arm_a == arm_b:
        raise ValueError(f"arm_a and arm_b must be distinct, both are {arm_a!r}")
    if len(triples) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"triples has {len(triples)} units; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    deltas = [_paired_delta(t, arm_a, arm_b, value) for t in triples]
    return _bootstrap_median_of_units(deltas, iterations, seed, alpha)


def bootstrap_paired_contrast_difference(
    triples: list[list[dict]],
    arms: tuple[str, str, str] = ("A", "B", "C"),
    value="t_total",
    iterations=10000,
    seed=0,
    alpha=0.05,
) -> dict:
    """Paired bootstrap on within_host_triples output: the interval on the
    median of (A-B) - (B-C), computed once per triple — the ranking claim on
    the cleanest subset of the dataset.

    Resamples whole triples with replacement, not individual arm
    observations; see bootstrap_paired_median_diff and
    bootstrap_contrast_difference for the reasoning and the unpaired version.
    """
    _check_iterations_and_alpha(iterations, alpha)
    if len(arms) != 3:
        raise ValueError(f"arms must have exactly 3 entries, got {arms!r}")
    if len(set(arms)) != 3:
        raise ValueError(f"arms must be distinct, got {arms!r}")
    if len(triples) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"triples has {len(triples)} units; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES} (the same floor percentiles' p50 uses), or "
            "it is an artifact of a thin sample, not a measurement"
        )
    deltas = [_paired_contrast_delta(t, arms, value) for t in triples]
    return _bootstrap_median_of_units(deltas, iterations, seed, alpha)
```

- [ ] **Step 4: Run and confirm pass**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: PASS — 80 passed

- [ ] **Step 5: Commit**

```bash
git add coldstart/analysis/stats.py tests/test_stats.py
git commit -m "feat: non-parametric statistics with a percentile sample floor"
```

---

## Task 18: Figures

These are charts, not UI. Verification is: generate from synthetic data, open the PNGs, and look at them.

**Three defects here were found only by looking, and none was catchable by the test suite.**
The waterfall clamped a negative `unattributed` term to zero with `max(0.0, ...)` and drew it
as nothing — arm C's term was -6.0s, meaning the measured sub-phases plus `T_weights` did not
fit inside the `T_process` containing them. That is a data error, and the chart was the last
place to catch it before a reader saw a plausible bar; it now raises, the same discipline
`checks.py` applies to the cross-clock residual. The warmup chart drew one steady-state band
pooled across arms, which was invisible while the fixture gave all three arms identical curves
and became plainly wrong once they differed — the band described only arm B, implying arm A
never reached steady state and arm C was permanently faster than it. Steady state is per-arm.
And the host chart spanned 5% under the title "Host heterogeneity", so it could not have shown
the hypothesis it exists to support.

Two of those were *caused* by fixtures too degenerate to express what the chart is for. Fixing
the fixture is what exposed the real bug underneath.

**Files:**
- Create: `coldstart/analysis/figures.py`, `tests/test_figures.py`

- [ ] **Step 1: Write the failing test**

`tests/test_figures.py`:

```python
"""Tests for the four artifact figures.

These are charts, not UI: a test that only asserts a PNG file exists and is
"not tiny" (the plan's given test) proves a file was written, not that the
chart is correct. Every test here instead pins something matplotlib exposes
without rendering — bar counts, stacking order, colors, axis limits, legend
text, line data — so a mutation that scrambles the chart (wrong stacking
order, an arm silently dropped, axes that don't start at zero, a median that
drifts from the published percentile table) fails a test instead of just
being an ugly PNG nobody looked at closely enough.
"""

import copy
import statistics
from pathlib import Path
from unittest.mock import patch

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest

import coldstart.analysis.figures as figures_module
from coldstart.analysis.figures import (
    RESIDUAL_COLOR,
    ecdf_plot,
    per_host_medians,
    warmup_curve,
    waterfall,
)

# Distinct per-arm warmup shape (different plateau and different initial
# spike): a fixture where all three arms shared one warmup curve — the
# original version of this fixture — makes warmup_curve's three series draw
# exactly on top of each other. A test can only detect what its fixture can
# express, and a fixture like that cannot tell "three correct series" apart
# from "the same series plotted three times" or "two series silently
# dropped." Values are illustrative (a cached/compiled arm settling faster
# and lower), not measured.
_WARMUP_STEADY = {"A": 3.0, "B": 2.0, "C": 1.2}
_WARMUP_SPIKE = {"A": 3.5, "B": 2.5, "C": 1.6}

# Per-host additive offset on t_total. Every (arm, host) pair appears
# exactly twice in a 30-row fixture (lcm(3, 5) = 15), so each host's 6 rows
# split evenly 2/2/2 across arms and this offset shifts each host's own
# median by exactly this amount — it demonstrates real host heterogeneity
# (spec H4: host variance, not just within-stage variance, drives the tail)
# rather than the near-flat (<5% spread) bar chart the unshifted fixture
# produced. Kept below half the tightest inter-arm gap (B-C, 35s baseline)
# so ecdf_plot's three per-arm distributions stay visually separated
# instead of bleeding into each other.
_HOST_OFFSET = {"h0": -10.0, "h1": -5.0, "h2": 0.0, "h3": 5.0, "h4": 10.0}

# Per-arm S4 subphases. Arm A and B keep the original constants (6.0, 12.0);
# waterfall's exact-width assertions below are pinned against those two
# arms and are untouched by this change. Arm C cannot use the same
# constants: with t_process=42.0 and t_weights=30.0, a sub-phase sum of 18.0
# would make weights + subphases (48.0) exceed t_process (42.0) -- a
# negative "unattributed" term, which waterfall() now raises on instead of
# silently clamping to zero (see the dedicated negative-term tests). Arm C's
# subphases are scaled down so the *default* fixture is internally
# consistent; the negative case gets its own explicit, separately
# constructed fixture instead of hiding inside the everyday one.
_S4_SUBPHASES = {
    "A": {"S4c": 6.0, "S4e": 12.0},
    "B": {"S4c": 6.0, "S4e": 12.0},
    "C": {"S4c": 3.0, "S4e": 6.0},
}


def rows(n=30):
    out = []
    for i in range(n):
        arm = ["A", "B", "C"][i % 3]
        host = f"h{i % 5}"
        base = {"A": 160.0, "B": 95.0, "C": 60.0}[arm]
        steady = _WARMUP_STEADY[arm]
        spike = _WARMUP_SPIKE[arm]
        out.append(
            {
                "arm": arm,
                "host_id": host,
                "t_total": base + i * 0.4 + _HOST_OFFSET[host],
                "t_platform": 18.0,
                "t_weights": base * 0.5,
                "s4_subphases": dict(_S4_SUBPHASES[arm]),
                "t_process": base - 18.0,
                "warmup": [
                    {"req_index": k, "end_to_end": steady + spike * 0.55**k} for k in range(10)
                ],
            }
        )
    return out


def _call_capturing_axes(func, *args):
    """Capture the Axes matplotlib builds for `func`'s call, so tests can
    assert on axes/patches/lines directly instead of just "a file exists".

    Every figure function calls `plt.close(fig)` right before returning.
    That deregisters the figure from pyplot's manager but does not clear
    its artists (Figure.clf() is never called), so the Axes captured here
    via a `plt.subplots` spy stays fully introspectable after the function
    returns — the only thing lost is `plt.gcf()` returning it.
    """
    captured = {}
    real_subplots = plt.subplots

    def spy(*a, **kw):
        fig, ax = real_subplots(*a, **kw)
        captured["fig"], captured["ax"] = fig, ax
        return fig, ax

    with patch("coldstart.analysis.figures.plt.subplots", side_effect=spy):
        func(*args)
    return captured["fig"], captured["ax"]


# ---------------------------------------------------------------------------
# smoke test: all four write real files (the plan's given test, kept as a
# baseline — but not treated as sufficient on its own)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# waterfall
# ---------------------------------------------------------------------------


def test_waterfall_draws_five_segments_per_arm_with_residual_first_and_correct_stacking(tmp_path):
    """Pins the exact segment widths and left offsets for arm A (measured
    branch), derived by hand from the fixture: t_platform=18 (constant),
    t_process=142, t_weights=80, S4c=6, S4e=12, so unattributed = 142 - 80 -
    18 = 44. This catches both a wrong stacking order and a wrong segment
    value, not just "some bars got drawn"."""
    data = rows()
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    assert len(ax.patches) == 15  # 3 arms x 5 segments (every row has t_weights set)

    residual_rgba = mcolors.to_rgba(RESIDUAL_COLOR)
    weights_rgba = mcolors.to_rgba("#2f6fd0")

    arm_a = ax.patches[0:5]
    assert arm_a[0].get_facecolor() == residual_rgba  # residual segment drawn first
    assert arm_a[1].get_facecolor() == weights_rgba
    widths = [p.get_width() for p in arm_a]
    assert widths == pytest.approx([18.0, 80.0, 6.0, 12.0, 44.0])
    lefts = [p.get_x() for p in arm_a]
    assert lefts == pytest.approx([0.0, 18.0, 98.0, 104.0, 116.0])


def test_waterfall_arm_c_segments_are_pinned_and_genuinely_positive(tmp_path):
    """Arm C: t_process=42, t_weights=30, S4c+S4e=9 -> unattributed = 42 -
    30 - 9 = 3, a small but genuinely positive residual (arm C's subphases
    are scaled down in the fixture specifically so this stays >= 0 -- see
    the fixture's `_S4_SUBPHASES` comment). The dedicated negative-term
    tests below cover the case that must now raise instead of clamp."""
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    arm_c = ax.patches[10:15]
    widths = [p.get_width() for p in arm_c]
    assert widths == pytest.approx([18.0, 30.0, 3.0, 6.0, 3.0])


def test_waterfall_yticklabels_carry_each_arms_n(tmp_path):
    data = rows()  # 30 rows, 10 per arm
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    labels = [t.get_text() for t in ax.get_yticklabels()]
    assert len(labels) == 3
    for lbl in labels:
        assert "n=10" in lbl


def test_waterfall_xlim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(waterfall, rows(), tmp_path / "w.png")
    assert ax.get_xlim()[0] == 0


def test_waterfall_merged_branch_draws_two_segments_labeled_merged(tmp_path):
    """The plan's given fixture never sets t_weights=None, so it never
    exercises the merged-phase branch metrics.py's derive() produces when
    the engine doesn't delineate the S2/S3 boundary. Build that fixture
    explicitly."""
    data = rows()
    for r in data:
        r["t_weights"] = None
    _fig, ax = _call_capturing_axes(waterfall, data, tmp_path / "w.png")
    assert len(ax.patches) == 6  # 3 arms x 2 segments (platform + merged)

    residual_rgba = mcolors.to_rgba(RESIDUAL_COLOR)
    arm_a = ax.patches[0:2]
    assert len(arm_a) == 2
    assert arm_a[0].get_facecolor() == residual_rgba

    _handles, labels = ax.get_legend_handles_labels()
    assert any("merged" in lbl.lower() for lbl in labels)


def test_waterfall_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    waterfall(data, tmp_path / "w.png")
    assert data == before


def test_waterfall_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        waterfall([], tmp_path / "w.png")


def test_waterfall_rejects_an_arm_with_no_rows(tmp_path):
    """Silently dropping an arm's series (the plan's `if not rs: continue`)
    is a misleading chart, not a smaller one — it must raise instead."""
    data = [r for r in rows() if r["arm"] != "C"]
    with pytest.raises(ValueError, match="C"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_uses_the_shared_median_helper(tmp_path):
    """The required fix beyond the plan text: figures.py must call
    stats.median, not statistics.median, or a chart median could silently
    disagree with the published percentile table's median on the same
    data."""
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        waterfall(rows(), tmp_path / "w.png")
    assert spy.called


def test_waterfall_raises_on_a_negative_unattributed_term_instead_of_clamping(tmp_path):
    """If the measured sub-phases plus t_weights exceed t_process, the
    decomposition does not fit inside the thing it decomposes -- checks.py
    applies exactly this discipline to a single run's t_weights ("discard,
    don't silently correct"). A max(0.0, ...) clamp (the original behavior)
    would draw a plausible-looking but understated bar instead of surfacing
    the defect; this must raise, and name the offending arm."""
    data = rows()
    for r in data:
        if r["arm"] == "C":
            # arm C: t_process=42.0, t_weights=30.0; pushing S4e to 40.0
            # makes weights + subphases = 30 + 46 = 76, well past t_process.
            r["s4_subphases"] = {"S4c": 6.0, "S4e": 40.0}
    with pytest.raises(ValueError, match="C"):
        waterfall(data, tmp_path / "w.png")


def test_waterfall_negative_unattributed_message_names_the_actual_numbers(tmp_path):
    """Pins that the raised message carries the numbers a reader would need
    to investigate (not just "something is wrong somewhere"), and that a
    well-formed arm earlier in ARMS order doesn't mask a later arm's
    defect."""
    data = rows()
    for r in data:
        if r["arm"] == "C":
            r["s4_subphases"] = {"S4c": 6.0, "S4e": 40.0}
    with pytest.raises(ValueError, match=r"-34\.0"):
        waterfall(data, tmp_path / "w.png")


# ---------------------------------------------------------------------------
# warmup_curve
# ---------------------------------------------------------------------------


def test_warmup_curve_plots_the_number_of_requests_present_in_the_data(tmp_path):
    data = rows()  # every row has a 10-request warmup
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    for ln in arm_lines:
        assert list(ln.get_xdata()) == list(range(1, 11))


def test_warmup_curve_plots_a_different_request_count_when_the_data_has_fewer(tmp_path):
    """Pins that the request count comes from the data, not a hardcoded 10:
    a fixture with 4 warmup requests per row must produce 4-point lines."""
    data = rows()
    for r in data:
        r["warmup"] = r["warmup"][:4]
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    for ln in arm_lines:
        assert list(ln.get_xdata()) == [1, 2, 3, 4]


def test_warmup_curve_series_are_visually_distinct_not_identical(tmp_path):
    """Regression guard for the fixture itself: the original `rows()` gave
    every arm the exact same warmup shape, so only the last-drawn arm's line
    was visible (the other two were drawn underneath it). A test built on
    that fixture cannot tell "three correct series" from "one series plotted
    three times" or "two series silently dropped" -- both would pass every
    other assertion in this file. Each arm's y-data must actually differ."""
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    assert len(arm_lines) == 3
    ydata = [tuple(ln.get_ydata()) for ln in arm_lines]
    assert len(set(ydata)) == 3


def test_warmup_curve_legend_labels_carry_each_arms_n(tmp_path):
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    _handles, labels = ax.get_legend_handles_labels()
    # Curve labels carry "(n=..)"; the per-arm band labels don't repeat it
    # (the band belongs to the curve right next to it in the legend), so
    # filtering on "n=" isolates just the three curve entries.
    arm_labels = [lbl for lbl in labels if "n=10" in lbl]
    assert len(arm_labels) == 3
    band_labels = [lbl for lbl in labels if "steady-state band" in lbl]
    assert len(band_labels) == 3
    assert len(labels) == 6


def test_warmup_curve_ylim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    assert ax.get_ylim()[0] == 0


def test_warmup_curve_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    warmup_curve(data, tmp_path / "w.png")
    assert data == before


def test_warmup_curve_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        warmup_curve([], tmp_path / "w.png")


def test_warmup_curve_rejects_an_arm_with_no_rows(tmp_path):
    data = [r for r in rows() if r["arm"] != "B"]
    with pytest.raises(ValueError, match="B"):
        warmup_curve(data, tmp_path / "w.png")


def test_warmup_curve_rejects_mismatched_warmup_lengths(tmp_path):
    """A row with a shorter warmup list than the rest must raise loudly
    instead of either IndexError-ing deep inside a comprehension or
    silently truncating every other row's curve to match it."""
    data = rows()
    data[0] = dict(data[0])
    data[0]["warmup"] = data[0]["warmup"][:5]
    with pytest.raises(ValueError, match="mismatch"):
        warmup_curve(data, tmp_path / "w.png")


def test_warmup_curve_steady_state_band_is_per_arm_not_pooled(tmp_path):
    """Each arm converges to its own plateau (A ~3.0, B ~2.0, C ~1.2 in this
    fixture) -- a single band pooled across all three arms would sit only
    near the middle arm's plateau, making the slowest arm look like it
    never reaches "steady state" and the fastest arm look permanently
    faster than it. A pooled-band implementation draws exactly one band
    (this asserts three, at three independently-verified levels) and fails
    this test."""
    data = rows()
    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")

    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    assert len(bands) == 3  # one band per arm, not one pooled across all three

    by_arm = {a: [r for r in data if r["arm"] == a] for a in figures_module.ARMS}
    for arm, band in zip(figures_module.ARMS, bands, strict=True):
        vals = [r["warmup"][k]["end_to_end"] for r in by_arm[arm] for k in (-3, -2, -1)]
        expected = statistics.median(vals)
        assert band.get_y() == pytest.approx(expected * 0.9)
        assert band.get_y() + band.get_height() == pytest.approx(expected * 1.1)


def test_warmup_curve_steady_state_bands_are_colored_like_their_own_line(tmp_path):
    """A band drawn in the wrong arm's color (or a neutral gray shared by
    all three, the original pooled design) would be ambiguous about which
    curve it belongs to now that there are three. Each band's color must
    match its own arm's line color exactly."""
    _fig, ax = _call_capturing_axes(warmup_curve, rows(), tmp_path / "w.png")
    arm_lines = [ln for ln in ax.lines if ln.get_marker() == "o"]
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    assert len(arm_lines) == len(bands) == 3
    for line, band in zip(arm_lines, bands, strict=True):
        assert mcolors.to_rgb(band.get_facecolor()[:3]) == mcolors.to_rgb(line.get_color())


def test_warmup_curve_per_arm_band_uses_all_of_that_arms_rows_not_just_the_first(tmp_path):
    """Same one-outlier-row concern as before, now scoped per arm: arm A's
    band must reflect all of arm A's rows, not just its first row. Give
    only arm A's first row a wildly different tail; a first-row-only
    computation would center arm A's band near 999, but the median across
    all of arm A's rows must stay well below that -- and arm B/C's bands,
    unaffected by an arm-A row, must stay near their own normal plateaus."""
    data = rows()
    for idx, r in enumerate(data):
        if r["arm"] == "A":
            data[idx] = dict(r)
            data[idx]["warmup"] = [dict(w) for w in r["warmup"]]
            for w in data[idx]["warmup"][-3:]:
                w["end_to_end"] = 999.0
            break

    _fig, ax = _call_capturing_axes(warmup_curve, data, tmp_path / "w.png")
    bands = [p for p in ax.patches if "steady-state band" in (p.get_label() or "")]
    arm_a_band, arm_b_band, arm_c_band = bands  # ARMS order is A, B, C
    assert arm_a_band.get_y() + arm_a_band.get_height() < 500.0
    assert arm_b_band.get_y() + arm_b_band.get_height() < 10.0
    assert arm_c_band.get_y() + arm_c_band.get_height() < 10.0


def test_warmup_curve_uses_the_shared_median_helper(tmp_path):
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        warmup_curve(rows(), tmp_path / "w.png")
    assert spy.called


# ---------------------------------------------------------------------------
# ecdf_plot
# ---------------------------------------------------------------------------


def test_ecdf_plot_one_step_series_per_arm(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    assert len(ax.lines) == 3


def test_ecdf_plot_legend_labels_carry_each_arms_n(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    _handles, labels = ax.get_legend_handles_labels()
    assert len(labels) == 3
    assert all("n=10" in lbl for lbl in labels)


def test_ecdf_plot_axes_start_at_zero_and_end_at_one(tmp_path):
    _fig, ax = _call_capturing_axes(ecdf_plot, rows(), tmp_path / "e.png")
    assert ax.get_xlim()[0] == 0
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    assert ylim == pytest.approx((0.0, 1.0))
    assert xlim[0] == pytest.approx(0.0)


def test_ecdf_plot_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    ecdf_plot(data, tmp_path / "e.png")
    assert data == before


def test_ecdf_plot_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        ecdf_plot([], tmp_path / "e.png")


def test_ecdf_plot_rejects_an_arm_with_no_rows(tmp_path):
    data = [r for r in rows() if r["arm"] != "A"]
    with pytest.raises(ValueError, match="A"):
        ecdf_plot(data, tmp_path / "e.png")


# ---------------------------------------------------------------------------
# per_host_medians
# ---------------------------------------------------------------------------


def test_per_host_medians_bar_count_matches_hosts(tmp_path):
    data = rows()  # host_id = f"h{i % 5}" -> 5 distinct hosts
    _fig, ax = _call_capturing_axes(per_host_medians, data, tmp_path / "h.png")
    assert len(ax.patches) == 5


def test_per_host_medians_xticklabels_carry_each_hosts_n(tmp_path):
    data = rows()  # 30 rows / 5 hosts = 6 rows per host
    _fig, ax = _call_capturing_axes(per_host_medians, data, tmp_path / "h.png")
    labels = [t.get_text() for t in ax.get_xticklabels()]
    assert len(labels) == 5
    for lbl in labels:
        assert "n=6" in lbl


def test_per_host_medians_shows_genuine_heterogeneity_not_a_flat_line(tmp_path):
    """Regression guard for the fixture: this figure exists to support the
    host-heterogeneity hypothesis (spec H4 -- host variance, not just
    within-stage variance, drives the tail). The original fixture pooled
    every host over a balanced 2/2/2 arm mix each, which made every host's
    median collapse to almost the same value (<5% spread) regardless of any
    real per-host effect -- a bug that erased host differences entirely
    would have been invisible against a chart that already looked flat."""
    _fig, ax = _call_capturing_axes(per_host_medians, rows(), tmp_path / "h.png")
    heights = [p.get_height() for p in ax.patches]
    avg = sum(heights) / len(heights)
    assert (max(heights) - min(heights)) / avg > 0.10


def test_per_host_medians_ylim_starts_at_zero(tmp_path):
    _fig, ax = _call_capturing_axes(per_host_medians, rows(), tmp_path / "h.png")
    assert ax.get_ylim()[0] == 0


def test_per_host_medians_does_not_mutate_input_rows(tmp_path):
    data = rows()
    before = copy.deepcopy(data)
    per_host_medians(data, tmp_path / "h.png")
    assert data == before


def test_per_host_medians_rejects_empty_rows(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        per_host_medians([], tmp_path / "h.png")


def test_per_host_medians_uses_the_shared_median_helper(tmp_path):
    with patch("coldstart.analysis.figures.median", wraps=figures_module.median) as spy:
        per_host_medians(rows(), tmp_path / "h.png")
    assert spy.called


# ---------------------------------------------------------------------------
# sanity check on the fixture itself, so a broken fixture doesn't masquerade
# as a passing (but vacuous) test
# ---------------------------------------------------------------------------


def test_fixture_sanity_ten_rows_per_arm_five_hosts():
    data = rows()
    assert sorted({r["arm"] for r in data}) == ["A", "B", "C"]
    assert sum(1 for r in data if r["arm"] == "A") == 10
    assert len({r["host_id"] for r in data}) == 5
```

- [ ] **Step 2: Run and confirm it fails**

Run: `.venv/bin/pytest tests/test_figures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'coldstart.analysis.figures'`

- [ ] **Step 3: Implement**

`coldstart/analysis/figures.py`:

```python
"""The four public-post figures: waterfall decomposition, warmup curve, ECDF,
and per-host medians.

These charts are the artifact for most readers — more people will look at
the waterfall than will read the method section — so every aggregate drawn
here goes through ``coldstart.analysis.stats.median``, the same function
``percentiles()``'s p50 uses. That is deliberate: a chart median computed a
different way than the reported percentile table's median would put two
different numbers for the same quantity in the same post. See
``stats.median``'s docstring for why it skips the bootstrap sample floor.

Input domains are guarded rather than left to quietly produce a misleading
chart:

- Empty ``rows`` raises, rather than drawing an empty axes with no
  indication anything is wrong.
- An arm entirely absent from ``rows`` raises, rather than the plan's
  original ``if not rs: continue`` — which would silently drop that arm's
  bar/line/legend entry, understating how many arms were actually compared.
- ``warmup_curve`` additionally requires every row's warmup list to be the
  same length; a shorter list would otherwise either IndexError deep inside
  a comprehension or (if longer) silently have its tail ignored depending on
  which row happened to be ``rows[0]``.

None of the four functions mutate their input rows.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from coldstart.analysis.stats import ecdf, median

ARMS = ["A", "B", "C"]
ARM_LABEL = {"A": "A — nothing cached", "B": "B — weights cached", "C": "C — weights + compile"}
RESIDUAL_COLOR = "#9e9e9e"  # deliberately distinct from every measured-stage color


def _validate_rows(rows) -> list[dict]:
    """Fail loudly on the one input domain every figure shares: nothing to
    plot. A copy is returned so callers get a stable list even if `rows`
    was a generator (none of the figures consume `rows` more than once, but
    this keeps that assumption from becoming load-bearing by accident)."""
    rows = list(rows)
    if not rows:
        raise ValueError("rows must not be empty")
    return rows


def _by_arm(rows) -> dict[str, list[dict]]:
    """Split rows by arm, requiring all of ARMS to be represented. Silently
    skipping a missing arm (the plan's `if not rs: continue`) would drop
    that arm's whole series from the chart with no indication anything was
    wrong — a figure that quietly compares two arms instead of three is a
    misleading chart, not a smaller one."""
    rows = _validate_rows(rows)
    by = {a: [r for r in rows if r["arm"] == a] for a in ARMS}
    missing = [a for a in ARMS if not by[a]]
    if missing:
        raise ValueError(
            f"no rows for arm(s) {missing}; refusing to silently drop "
            f"{'an arm' if len(missing) == 1 else 'arms'} from the chart"
        )
    return by


def waterfall(rows, out_path) -> Path:
    """Stacked median stage durations per arm, residual visually distinct."""
    by = _by_arm(rows)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    labels, ys = [], []
    for i, arm in enumerate(ARMS):
        rs = by[arm]
        labels.append(f"{ARM_LABEL[arm]}\n(n={len(rs)})")
        ys.append(i)
        platform = median([r["t_platform"] for r in rs])
        process = median([r["t_process"] for r in rs])

        # derive() returns t_weights=None when the engine did not delineate the
        # load boundary. Drawing a merged span as if it were T_weights would be
        # the chart telling a story the data does not support, so the merge is
        # drawn as one explicitly-labelled bar instead — spec, stage taxonomy.
        measured = [r["t_weights"] for r in rs if r["t_weights"] is not None]
        if measured:
            weights = median(measured)
            sub = {
                k: median([r["s4_subphases"].get(k, 0.0) for r in rs]) for k in ("S4c", "S4e")
            }
            unattributed = process - weights - sum(sub.values())
            if unattributed < 0:
                # A negative term means the measured components (weights +
                # subphases) don't fit inside t_process, the thing they are
                # supposed to sit inside — the decomposition itself is
                # broken, not just cosmetically short. checks.py already
                # applies this exact discipline to a single run's t_weights
                # ("discard, don't silently correct"); a max(0.0, ...) clamp
                # here would draw a plausible-looking but wrong bar, and
                # this chart is the last place before publication such a
                # defect could be caught. Raising (rather than drawing it
                # some other unmistakable way) is chosen because figures.py
                # already treats every other malformed input domain in this
                # module as fatal, not as something to render around.
                raise ValueError(
                    f"arm {arm!r}: unattributed S4 time is negative "
                    f"({unattributed:.3f}s = t_process {process:.3f} - "
                    f"t_weights {weights:.3f} - S4 subphases "
                    f"{sum(sub.values()):.3f}); the measured components do "
                    "not fit inside t_process"
                )
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
    # Arm A (the longest bar) sits at the bottom of the chart, so a
    # lower-right legend sits directly on top of its tail. Arm C (the
    # shortest bar, drawn last) is at the top, leaving the upper-right
    # corner clear regardless of how long arm A's bar grows.
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Cold start decomposition")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return Path(out_path)


def warmup_curve(rows, out_path) -> Path:
    by = _by_arm(rows)
    all_rows = [r for rs in by.values() for r in rs]

    lengths = {len(r["warmup"]) for r in all_rows}
    if len(lengths) != 1:
        raise ValueError(
            f"warmup lists have mismatched lengths across rows: {sorted(lengths)}; "
            "every row must report the same number of warmup requests"
        )
    (n_req,) = lengths
    if n_req == 0:
        raise ValueError("warmup lists are empty")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for arm in ARMS:
        rs = by[arm]
        med = [median([r["warmup"][i]["end_to_end"] for r in rs]) for i in range(n_req)]
        (line,) = ax.plot(
            range(1, n_req + 1), med, marker="o", label=f"{ARM_LABEL[arm]} (n={len(rs)})"
        )

        # Steady state is per-arm, not pooled across all three arms. Each
        # arm converges to its own plateau -- a band computed by pooling
        # every arm's rows together would sit near the middle arm's
        # plateau and be flatly wrong for the other two (e.g. the slowest
        # arm would look like it never reaches "steady state" and the
        # fastest arm would look like it beats steady state from request 2
        # on). Drawn from all of *that arm's* rows, not just its first row
        # (same one-outlier-row concern as before, now scoped per arm), in
        # that arm's own line color so the band is unambiguously "this
        # curve's" rather than a third, disconnected element.
        steady = median([r["warmup"][k]["end_to_end"] for r in rs for k in (-3, -2, -1)])
        ax.axhspan(
            steady * 0.9,
            steady * 1.1,
            color=line.get_color(),
            alpha=0.15,
            label=f"{ARM_LABEL[arm]} steady-state band (±10%)",
        )

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
    rows = _validate_rows(rows)
    hosts = sorted({r["host_id"] for r in rows})
    fig, ax = plt.subplots(figsize=(8, 4.5))
    meds = [median([r["t_total"] for r in rows if r["host_id"] == h]) for h in hosts]
    counts = [sum(1 for r in rows if r["host_id"] == h) for h in hosts]
    ax.bar(range(len(hosts)), meds)
    ax.set_xticks(range(len(hosts)), [f"{h}\n(n={c})" for h, c in zip(hosts, counts, strict=True)])
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
Expected: PASS — 37 passed

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
from coldstart.analysis.pipeline import REQUIRED_FOR_T_WEIGHTS, partition
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
    # B4: `ok = [r for r in rows if r.get("ok") and r["consistent"]]` was this
    # snippet's own bug -- a single engine-merged run anywhere in the campaign
    # still has `t_weights is None` even though it's ok and consistent, and
    # pooling it below died with a context-free TypeError from inside
    # math.isfinite. partition() is the gate that closes that hole: it also
    # requires t_weights specifically, not just ok+consistent.
    result = partition(rows, required=REQUIRED_FOR_T_WEIGHTS)
    assert len(result.publishable) > 100

    by = {a: [r["t_weights"] for r in result.publishable if r["arm"] == a] for a in "ABC"}
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
    # No `if r.status["outcome"] == "ok"` filter needed here any more --
    # within_host_triples itself now refuses to let a failed run stand in for
    # a missing arm (B4).
    rows = [derive(r) for r in store.read_all()]
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

## Blocking defects found by the final integration review

These were invisible to per-file review: every module was individually hardened, and each of
these lives in the seam *between* modules. Two of the five require worker-side changes and
therefore cannot be applied retroactively to stored data, so they must land before the paid
campaign rather than after it.

**B1 — `T_total` is stamped at the wrong event, silently inflating the residual.** The spec
defines `T_total` as clock A, *submit → first token of request 1*. Task 14's submitter stamps
`t_result` after `endpoint.run()` returns — that is after all ten warmup requests. So
`T_platform = T_total − T_process` absorbs requests 2–10 plus the result round trip: roughly
eighteen seconds of *measured, in-container* time published as "time I cannot attribute from
inside the container." Nothing crashes and the consistency check passes more comfortably, not
less. This is the artifact's credibility centrepiece corrupted by a mechanical error, in a post
whose argument is that other people's waterfalls quietly attribute time they cannot see.

The fix cannot be "stamp `t_result` earlier" — a serverless request/response worker cannot
signal the driver at first token. Correct `T_total` instead, in `derive()`, by subtracting the
clock-B duration from first token to end of job:
`T_total = (t_result − t_submit) − (S7_warmup_done − S6_first_token)`. That is a *duration*
correction across clocks, not a timestamp comparison, so it stays inside the three-clock rules.
Record the raw span too, and say in the post which is which.

**Fixed.** `derive()` (`coldstart/analysis/metrics.py`) now computes the raw span as
`t_total_job` and keeps it in the published row unconditionally, and computes `T_total` as
`t_total_job − (S7_warmup_done − S6_first_token)`. `t_platform` and `ceiling_bound` consume the
corrected `T_total`, not the raw span. The consistency check (`t_process` must not exceed
`t_total` less the RTT floor) now runs against the corrected value, which makes it meaningfully
tighter than before: previously `t_total` was inflated by the full warmup tail, so `t_process`
could never realistically approach it and the check almost never fired; now `t_total` is
`t_process` plus only the true platform residual, so the same check catches clock skew and
submit/result bookkeeping bugs the inflated value was masking.

Two states get explicit, non-silent handling rather than falling back to the uncorrected value:
a run missing `S7_warmup_done` (reached first token, then failed or was cut off mid-warmup) gets
`t_total = None`, `consistent = False`, and a dedicated `DiscardReason.MISSING_WARMUP_END` so it
is tabulatable separately from the other two consistency violations — instead of silently
publishing the wrong, still-inflated number for exactly the runs most likely to be anomalous. A
negative correction term (`S7_warmup_done` preceding `S6_first_token`, impossible on a monotonic
clock B) raises `ValueError` with the run's id and arm, the same way a missing required stage
mark does, rather than being clamped or absorbed into the consistency flag.

**B2 — the waterfall's "unattributed within S4" is neither unattributed nor within S4, and the
compile result is hiding inside it.** `figures.py` computes it as
`t_process − t_weights − (S4c + S4e)`. Since `t_process` spans S1 through S6, the remainder also
contains S1 imports, S4a device init, **S4b compilation**, S4d KV allocation, S5 and S6 — all
named, measured stages. The bar shrinks between arms B and C, which *is* the H3 effect, drawn
under the label "unattributed". The spec's quantity is different arithmetic entirely:
`S4_bracket − Σ identified sub-phases`, and `derive()` never computes an S4 bracket. As a
side-effect the waterfall now sums to exactly `t_total` by construction, inverting the spec's
"the waterfall never sums to a suspiciously exact 100%" honesty claim.

**Fixed.** The mark contract gained `S4_start`/`S4_end` (see Task 11); `derive()`
(`coldstart/analysis/metrics.py`) now computes `t_s4_bracket = S4_end − S4_start` when both marks
are present, and `s4_unattributed = t_s4_bracket − Σ(identified S4 sub-phases)`, exactly the
spec's formula — never `t_process`. `t_s1` and `t_s5` (`S5_ready − S4_end`, not
`S5_ready − S3_load_done`) are now explicit fields too, so `S1` and `S5` are their own measured
stages instead of hiding inside a remainder. `waterfall()` (`coldstart/analysis/figures.py`)
draws every stage in chronological order — `T_platform`, `S1`, `T_weights`, each identified
`S4a`–`S4e` present in the data, `unattributed within S4`, `S5`, `S6` — with the hardcoded
`("S4c", "S4e")` pair removed. A negative `s4_unattributed` raises, naming the arm and the actual
numbers, the same discipline already applied to a negative `t_weights`.

**What remains worker-side.** `S4_start`/`S4_end` are not emitted by anything yet — the probe
that marks them (Task 11) is blocked on the Task 6 reconnaissance run, so on every real record
today `t_s4_bracket` is `None`. `derive()` never substitutes `S5_ready − S3_load_done` for it
(that fold-in is exactly the misattribution B2 exists to stop), and `waterfall()` correspondingly
draws an explicit `"S4 + S5 (merged — S4_start/S4_end not yet measured)"` segment — computed
honestly from `t_process` minus the three stages that *are* independently measured today (`S1`,
`T_weights`, `S6`) — rather than a guess or a silently missing bar. This is the intended,
temporary state of the analysis layer, not a defect; it resolves itself the moment Task 11 lands
and starts emitting the two marks, with no further analysis-side change required.

**B3 — `S4b` has no producer anywhere.** `grep s4b` across `coldstart/` and `worker/` returns
only `economics.compile_cache_term`'s two parameters and their tests. `derive()` passes
`s4_subphases` through as an opaque dict and computes nothing from it. H3 — the hypothesis the
spec calls the most interesting result available in this experiment, and the entire reason arm C
exists — currently has no measurement.

**Fixed.** `derive()` now extracts all five `S4a`–`S4e` sub-phases from
`record.engine["s4_subphases"]` into explicit fields (`t_s4a`…`t_s4e`), each `None` — not `0.0`
— when the pinned engine version did not delineate it, recorded in `merged_phases` the same way
a missing `S2`/`S3` mark already is. `t_compile` is now a first-class field sourced from `S4b`;
`tests/test_metrics.py::test_t_compile_feeds_compile_cache_term` demonstrates the previously-empty
wiring end to end, feeding two `derive()` rows' `t_compile` values directly into
`economics.compile_cache_term(s4b_cold, s4b_warm)`.

**What remains worker-side.** `derive()` reads `record.engine["s4_subphases"]`; nothing populates
that field on a real run yet. That parser is Task 7's `coldstart/vllm_logs.py`, also blocked on
the Task 6 reconnaissance run, and is now specified there to use exactly the `S4a`–`S4e` key
contract this fix consumes, with the same "omit, don't zero" merge policy. Once Task 7 lands, H3
becomes measurable with no further analysis-side change: `t_compile` (arm B, cold compile) minus
`t_compile` (arm C, warm compile), aggregated across each arm's rows, is `T_compile`.

**B4 — no stage decides which rows are publishable, so each consumer invented its own error
policy.** `derive()` returns a 6-key row for failures and a 20-key row for successes, with `None`
for `t_platform` and `t_weights` on inconsistent or merged runs. There is no filter or gate.
Measured on a synthetic campaign: `waterfall` raises `KeyError: 't_platform'` on unfiltered rows
and `TypeError` on merged ones; `ecdf_plot` and `per_host_medians` raise `KeyError: 't_total'`;
`within_host_triples` accepts failed runs into the paired analysis, so the published triple count
is wrong before anything raises. Worst: **Task 19's own end-to-end snippet**, pooling
`r["t_weights"]`, dies with a context-free `TypeError` on any campaign containing a single
engine-merged run — and `t_weights` is the spec's designated primary comparison unit.

Add the missing stage: one function partitioning derived rows into publishable / discarded /
failed, owning the failure-rate and discard tables the spec requires reported separately, and
being the only input figures and stats accept.

**Fixed.** New module `coldstart/analysis/pipeline.py`, with no imports from the rest of
`coldstart.analysis` (avoids a cycle: `metrics.py` already imports `stats.py`, and `figures.py`
imports both). Its `partition(rows, required=())` is the one function meant to sit between
`[derive(r) for r in store.read_all()]` and everything downstream:

- `failed` — `row["ok"] is False`. Never folded into `discarded`, which is exactly the
  conflation the plan named: `derive()` sets `consistent=False` on a failed run's 6-key row too
  (it never reached a state where consistency could be evaluated), so `not consistent` cannot
  separate "this run failed" from "this run was discarded."
- `discarded` — `ok`, but missing something `required` demands. Each row is a shallow copy of
  the original with `exclusion_reason` (and `exclusion_labels`, its tuple form) added, so the
  reason travels with the row instead of being silently dropped.
- `publishable` — `ok`, and every name in `required` is satisfied.

"Publishable" is not one hardcoded predicate: `required` is a tuple of field names the caller
states for the analysis at hand. `"consistent"` is checked as `is True` (it is a bool present on
every ok row, so a bare not-None check would never fire); every other name is checked the
ordinary way, present and not `None`. Consistency is a floor every preset shares — `"consistent"`
appears in all four tuples below — and each tuple's remaining entries are what that metric needs
*in addition to* the floor: `REQUIRED_FOR_WARMUP = ("consistent",)` (`warmup_curve` needs nothing
beyond the floor), `REQUIRED_FOR_T_TOTAL = ("consistent",)` (`waterfall`, `ecdf_plot`,
`per_host_medians` — same floor, nothing extra: both `t_total` and `t_platform` are `None`
exactly when a row failed the clock-consistency check, so requiring it names both fields'
condition in one place), `REQUIRED_FOR_T_WEIGHTS = ("consistent", "t_weights")`, and
`REQUIRED_FOR_T_FAST = ("consistent", "t_fast_seconds")` (the A→B / B→C contrast and the
business-framing figures respectively). Consistency being universal does not collapse the case
for a per-metric `required` tuple in the first place — `t_weights` and `t_fast_seconds` still
have their own, genuinely different nullity conditions (a merged phase; a missing dispatch
offset) layered on top of the shared floor.

**Two corrections made during review, recorded here in order because the wrong-then-right
history is worth more than a clean final statement — both are the same principle applied one
step too narrowly, twice.**

**Correction 1.** The first draft of `REQUIRED_FOR_T_WEIGHTS` was `("t_weights",)` —
deliberately *without* `"consistent"` — on the reasoning that `t_weights` (S2+S3) is validated
independently of the T_total/T_process reconciliation, so a clock-inconsistent run could still
carry a perfectly good one. That reasoning is technically true and was still the wrong
conclusion: spec 6.5 rule 3 is unconditional ("Every run gets a consistency check ... Violations
are discarded ... never silently"), and a failed consistency check is a statement about the run —
its clocks or platform behavior are not trustworthy — not a per-field verdict. Publishing
`t_weights` from a run already declared broken is exactly the selective inclusion
pre-registration exists to prevent. **Ruling: consistency is a baseline requirement for every
published quantity, not a per-metric option**, applied to both `REQUIRED_FOR_T_WEIGHTS` and
`REQUIRED_FOR_T_FAST` (the same bug existed there: `t_fast_seconds` is likewise computed
independent of the T_total/T_process check). At this point `REQUIRED_FOR_WARMUP` was left at
`()`, reasoned as a deliberate exception: the warmup list is ten raw clock-B, intra-process
latency measurements with no cross-clock reconciliation step of their own, so there is nothing in
the T_total/T_process check for them to fail in the first place.

**Correction 2 — the exception carved out for `REQUIRED_FOR_WARMUP` in correction 1 was itself an
instance of the same mistake, and was overruled next.** The warmup list genuinely has no
cross-clock step of its own to fail — that part was correct. What doesn't follow is that a
consistency violation *elsewhere* in the run leaves the warmup data untouched: "clock A
misbehaved (e.g. a slow result return) and the in-container data is fine" and "this run is
anomalous in a way nobody understands" are indistinguishable from the analysis side — that
indistinguishability is precisely why the discard rule exists and is unconditional. Deciding
after the fact that the warmup list in particular still looks trustworthy is the identical
post-hoc selective inclusion correction 1 rejected for `t_weights`, and exempting it would have
made that ruling arbitrary — `t_weights` is also a pure clock-B quantity, and the same argument
was available for it and was not accepted. **`REQUIRED_FOR_WARMUP` is now `("consistent",)`. Every
preset requires consistency; there is no exception.** This does not erase the case for a
per-metric `required` tuple — `t_weights` and `t_fast_seconds` still carry their own nullity
conditions on top of the shared floor, and `T_TOTAL`/`WARMUP` needing nothing beyond the floor is
itself a real, distinguishing fact about those two analyses, not a sign the axis is redundant.

Both corrections are pinned by the same fixture row (host `h4` in `tests/test_pipeline.py`:
clock-inconsistent, but with a plausible, non-`None` `t_weights` and a warmup list that "looks
fine"), asserted landing in `discarded` by name for each preset it now fails, not merely absent
from `publishable` — see
`test_partition_t_weights_preset_excludes_the_merged_row_and_the_inconsistent_row` and
`test_partition_warmup_preset_excludes_the_failed_run_and_the_inconsistent_row`. The equivalent
interaction for `t_fast_seconds` (a run with a real `t_dispatch_mono` offset that is also
clock-inconsistent) does not occur naturally anywhere in the main mixed-campaign fixture, so it
gets its own small, dedicated fixture built specifically to express it —
`test_partition_t_fast_preset_also_excludes_an_inconsistent_row_with_a_valid_t_fast_seconds`.

The two required tables: `failure_rate_by_arm(rows)` takes the full, unpartitioned campaign (a
rate needs the total run count as its denominator, which the `failed` bucket alone doesn't
carry) and returns per-arm total/failed/rate/`by_class`. `discard_table(discarded_rows)` takes
`partition()`'s `discarded` bucket specifically and returns per-arm total/`by_reason`, where
`reason` is the row's `discard_reason` (the existing `checks.DiscardReason` enum) when excluded
for failing consistency, or `"missing_<field>"` when excluded for a `None` field. Disjoint row
populations by construction — a failed run can never appear in `discard_table`'s output, and a
discarded row can never appear in `failure_rate_by_arm`'s `failed` count — so the two rates
cannot be confused the way `consistent=False` used to allow.

`within_host_triples` (`coldstart/analysis/stats.py`) now filters `row.get("ok") is not False`
before grouping — a failed run still carries `arm`/`host_id`/`triple_index`, so before this fix
it could stand in for a missing arm and make an incomplete triple look complete, silently
inflating the published triple count. Checked as `is not False` rather than requiring
`row["ok"] is True` so hand-built rows that never went through `derive()` (existing tests) and
don't carry an `"ok"` key at all are not dropped by a filter they were never meant to satisfy.

`figures.py` and `stats.py` are hardened at the point of failure rather than restructured to
require `partition()`'s output shape — `figures.py`'s rows are deliberately "a pure consumer of
whatever fields a row happens to carry" (its own module docstring, predating this fix), and
forcing every row to carry `ok`/`consistent` would have broken that policy along with the
existing test suite built on hand-shaped rows. Instead, every dereference the bug table named
(`t_platform`, `t_process` in `waterfall`; `t_total` in `ecdf_plot`/`per_host_medians`; `warmup`
in `warmup_curve`) now goes through a new `_required_field(row, key)` that raises
`pipeline.NotPublishableError`, naming the row (`arm`/`host_id`) and the field, instead of a bare
`KeyError` (key absent) or `TypeError` (key present but `None`, surfacing three frames deep
inside `math.isfinite`). `stats.py`'s `_validate_samples` (backing `percentiles`, `ecdf`, and
both pooled bootstraps) and `_row_value` (backing the paired bootstraps `within_host_triples`
feeds) got the equivalent guard: a `None` in the pooled sample now raises a `ValueError` naming
its index and pointing at `pipeline.partition()`, not a bare `TypeError` from `math.isfinite`.

`tests/test_pipeline.py` builds one realistic mixed campaign — through real `RunRecord` ->
`derive()` round trips, never hand-typed derived dicts — containing successful runs across all
three arms (two complete within-host triples), a failed run, a clock-inconsistent run, an
engine-merged run with `t_weights is None`, and a run with no `t_dispatch_mono` offset (the
pre-Task-11 state B5 describes). It pins the partition counts under each preset (including one
row, the engine-merged run, that `partition()` correctly rules opposite ways under
`REQUIRED_FOR_T_TOTAL` vs. `REQUIRED_FOR_T_WEIGHTS` — direct evidence publishable is not one
predicate; and, since the consistency ruling above, a second row — the clock-inconsistent one —
that lands in `discarded` under `REQUIRED_FOR_T_WEIGHTS` by name, with its own exclusion reason
kept separate from the merged row's), a fixture where the failure rate (arm B) and the discard
rate (arm C) are non-zero on different arms and neither shows up in the other's table, that
`within_host_triples` now excludes the triple containing the failed run, and — at the scale where
`bootstrap_median_diff`'s sample floor actually engages — that the Task 19 pooling pattern
completes successfully on a campaign containing a merged run.

**B5 — `T_fast` in seconds has no producer, and it is the spine of the business framing.**
`metrics` yields `time_to_fast_index`, a request *index*. Every economics function consumes
`t_fast` in *seconds*. The warmup records carry `{req_index, ttft, end_to_end}` and no absolute
offset, so `T_fast` is not reconstructible from a stored row. **This one requires a worker-side
change and therefore cannot be fixed after the campaign runs.** Relatedly, the figure's
steady-state band and the tabulated `T_fast` threshold use two different estimators — pooled
median across rows versus median-of-medians per run — so a reader can see a point inside the band
while the table says the replica was not yet fast.

**Fixed, on the analysis side.** `derive()` (`coldstart/analysis/metrics.py`) now produces
`t_fast_seconds`, built with the same duration-correction technique B1 used for `T_total`: the
raw clock-A job span (`t_total_job`) minus the clock-B duration between the fast-tolerance
request's completion and job end — never a clock-A timestamp minus a clock-B timestamp directly
(spec 6.5 rule 1). This makes `T_fast` clock-A-aligned and directly comparable to `T_total`, and
`derive()` now asserts the spec's invariant (`T_fast >= T_total`) and raises, naming the run and
arm, if a record ever violates it — the same "impossible under honest instrumentation" discipline
already applied to a negative `t_weights` or `s4_unattributed`.

The new `t_fast_seconds(warmup, fast_index, t_total_job, t_warmup_done_mono)` function is the one
place this conversion happens, and it requires each warmup record to carry `t_dispatch_mono` (see
the Task 11 mark-contract addition below). **Every run recorded before that field exists — which
today is every real run and every fixture in this repo's test suite — gets `t_fast_seconds = None`
with the reason recorded in the new `t_fast_reason` field, never a value inferred by summing
`end_to_end`.** Summing would assume zero gap between sequential requests (no driver-side dispatch
delay, no scheduling jitter), which is an assumption, not a measurement, and would silently
reintroduce the exact defect this fix exists to eliminate.

The two steady-state estimators are now one. `figures.warmup_curve`'s per-arm band is the median
(via `stats.median`, routed through `metrics.steady_state_latency`) of each of that arm's rows'
*own* median-of-last-three — exactly the per-run definition `time_to_fast_index` compares against
for that run — not a pooled median over every row's last three requests combined. `FAST_TOLERANCE`
is imported from `metrics.py` into `figures.py` rather than re-hardcoded as `0.9`/`1.1` literals,
so the pre-registered tolerance exists in exactly one place. The warmup curve (figure 2) now
annotates `T_fast` per arm — a marker and label at the request each arm's own median curve first
lands within `FAST_TOLERANCE` of that arm's steady state, reusing `time_to_fast_index` rather than
a fourth copy of the threshold logic — closing the "figures" requirement in spec §7 that this
number be annotated on the plot.

Relatedly (not itself part of B5, but the same "route it through the shared function" discipline):
`metrics.steady_state_latency` now goes through `coldstart.analysis.stats.median` instead of
`statistics.median` — the one median in the pipeline that previously skipped both the shared
quantile function every other aggregate uses and its non-finite validation, so a NaN `end_to_end`
could pass through `derive()` silently.

**What remains worker-side.** `t_dispatch_mono` is not emitted by anything yet — the probe that
would emit it (Task 11) is blocked on the Task 6 reconnaissance run, so `t_fast_seconds` is `None`
on every real record today, with the reason stated in `t_fast_reason`. Task 11's and Task 13's
text below are updated to require the field once those tasks are actually built; no further
analysis-side change is needed once they land — `derive()` already consumes it the moment it's
present on a record.

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
