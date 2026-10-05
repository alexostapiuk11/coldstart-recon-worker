# Artifact 4 Plan 2 — Measurement Preparation and Reconnaissance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, test and put into the worker image everything artifact 4 needs before it can measure. That is the first pre-registration step, the reconnaissance probes and their report, the swap measurement, the co-location cell, the measurement campaigns and the reductions to the simulator's inputs. Then hand the paid reconnaissance run to the owner, with its runbook.

**Architecture:** A new worker-side package, `placement_measure/`, imports only `harness/` and the standard library, and a fresh-interpreter test enforces that from Task 1. Two thin handlers in `worker/` call it, selected by the template's `dockerStartCmd` as the service sweep's handler is. It reuses the shared tooling rather than rewriting it:
- **from `harness.serve`:** `served()`, with `.stop()` and a port per engine;
- **from `harness.bench`:** `run_bench`;
- **from `harness.sweep_worker`:** `run_one`, `PromptPlan` and `random_dataset_args`;
- **from `harness.campaign`:** `run_campaign`;
- **from the RunPod submitter:** `submit_payload`;
- **from `harness.submit`:** the stub `PayloadStubSubmitter`.

The local side reduces stored runs into plan 1's types in `placement/inputs.py`.

**Tech Stack:** Python 3.13, pytest, ruff, `requests`, the RunPod serverless API through `harness.runpod`, GitHub Actions for the image build. No new dependencies; `huggingface_hub` is already in the vLLM image.

**Governing documents:** [the scope amendment](../specs/2026-09-26-multi-model-serving-economics-scope.md), approved 2026-09-26. This plan covers its §1e items 4–8, the first pre-registration step (§3), the swap measurement conditions (§5), the sleep-mode probe (§6), and the reconnaissance behind §2's measurement gate.

---

## Scope

**This is plan 2 of three.** [Plan 1](2026-09-26-artifact-4-plan-1.md) builds the GPU-free simulator. [Plan 3](2026-10-04-artifact-4-plan-3.md) measures, validates and publishes. Its Part A is GPU-free and can run beside this plan's Part A; its Part B starts from this plan's reconnaissance record. [The implementation timeline](2026-10-04-artifact-4-implementation-timeline.md) orders all three.

**Part A (Tasks 1–17) spends nothing.** Every engine, bench run and GPU reading in it is faked. **Part B (Tasks 18–19) spends money,** and its paid step is the owner's: an agent stops at Task 18.

**Every code block in this plan was run before it was written down.** It ran on 2026-10-04 in a clean copy of `main` at commit `03d9345`, with plan 1's files added. A script read this document and executed it in order: each file it creates, each edit, each test, lint and commit step. Every expected failure failed and every expected pass passed. At the end:
- the whole suite passed, 1,841 tests, of which plan 2's are 90;
- `ruff check .` was clean;
- the parity gate printed `PARITY OK`;
- `scripts/a4_recon_capture.py --list` printed the eight jobs.

That run caught one defect an earlier check had missed: Task 2's test imported fakes Task 3 creates. It is fixed below. The plan's code blocks are generated from those files, not retyped.

**Existing code is extended, not replaced.** Three files change: `worker/Dockerfile` and `.github/workflows/build-worker.yml` gain lines, and `tests/test_harness_boundary.py` gains one name in a set. Nothing is removed or rewritten, so no capability inventory or parity gate is needed. **No task changes pixels.**

## Prerequisites — STOP if any is false

1. **Plan 1 has landed.** Task 14 builds its types; Tasks 1–13 need nothing from it.

   ```bash
   test -f placement/colocated.py && test -f placement/resample.py && echo OK
   ```

2. **The shared in-container tooling is on `main`.** The interfaces this plan calls:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
   import inspect
   from harness.serve import served, Server
   from harness.bench import run_bench, BenchError
   from harness.sweep_worker import run_one, PromptPlan, random_dataset_args, max_num_seqs_from_log
   from harness.campaign import run_campaign
   from harness.submit import PayloadStubSubmitter
   assert 'port' in inspect.signature(served).parameters and hasattr(Server, 'stop')
   assert 'run' in inspect.signature(run_bench).parameters
   print('OK')"
   ```

3. **No other session holds uncommitted edits to `worker/Dockerfile`, `.github/workflows/build-worker.yml` or `tests/test_harness_boundary.py`.** Task 10 edits them, and so does artifact 5's plan 2, to add `multilora`.

   ```bash
   git status --porcelain -- worker/Dockerfile .github/workflows/build-worker.yml tests/test_harness_boundary.py
   ```

   Expected: no output.

## Rules this plan operates under

- **Several workstreams share this checkout.** Never `git add -A` or `git add .`; every commit names its files. Run ruff only on the files a task touched.
- **`PYTHONDONTWRITEBYTECODE=1`** on every pytest run, and **`-o addopts=""`**, so the summary line with the count is printed.
- **Test counts are relative.** "Passes" means pytest exits 0. A count that drops between two runs means a file stopped being collected: stop and investigate.
- **House style.** Every error message names what went wrong and the consequence of it passing silently. Every docstring says why, and names the alternative rejected.
- **Never edit** another session's plans or specs, the published `data/` and `docs/figures/`, or `worker/probe.py`.
- **ruff in this repository** enables more than the defaults. In particular, PLC0414 rejects `import X as X`, RUF100 rejects a `noqa` that suppresses nothing, and B008 rejects a function call in a default argument. Add a `noqa` only after ruff reports the rule.

## Facts this plan relies on, and how each was checked

| Fact | Checked |
|---|---|
| `gpu_memory_utilization` is a per-instance limit, so two engines at 0.45 share a card | `vllm/config/cache.py`, v0.27.1 tag, 2026-10-04 |
| `/sleep?level=N`, `/wake_up` and `/is_sleeping` exist, only with `VLLM_SERVER_DEV_MODE=1`, and need `--enable-sleep-mode` | `vllm/entrypoints/serve/dev/sleep/api_router.py`, `serve/__init__.py`, `engine/arg_utils.py`, v0.27.1 |
| `vllm:num_requests_running` is exported on `/metrics` | `vllm/v1/metrics/loggers.py`, v0.27.1 |
| The five checkpoints' revisions | Hugging Face model API, 2026-10-04 |
| `served().stop()` measures until the parent exits, not until memory is free | `harness/serve.py`'s docstring |
| pandas is absent from the image, so the custom dataset fails | artifact 2's pilot, 2026-10-04 |
| 8B engine startup 84.5 s cold and 30.6 s warm; teardown 0.5 s | artifact 2's pilot, 2026-10-04 |

**UNVERIFIED until the paid run:**
- **Page-cache eviction.** Whether `posix_fadvise` evicts pages of a file on the network volume, and whether `drop_caches` is writable in the container.
- **Sleep mode in the image.** Whether it works there at all, and how much GPU memory a sleeping engine keeps.
- **Two engines at the split.** Whether both start at 0.45, and with how much KV each.
- **Platform limits.** The volume's download throughput, the per-second price, and the job-output size limit, which matters for the two 200-line log tails a cell returns.

Reconnaissance answers the engine and cache questions. The runbook marks the platform ones.

---

## File structure

```
placement_measure/          worker side: imports harness/ and the standard library only
  __init__.py               (Task 1)
  engine.py                 EngineSpec, engine_facts, log_tail          (Task 2)
  gpu_memory.py             memory.used readings, the release wait      (Task 3)
  pagecache.py              Cached:, drop_caches, fadvise                (Task 4)
  metrics.py                vllm:num_requests_running sampler           (Task 5)
  swap.py                   one process-level swap                      (Task 6)
  colocation.py             one co-location cell                        (Task 7)
  prereg.py                 step 1's values                             (Task 8)
  recon.py                  the reconnaissance probes                   (Task 9)
  jobs.py                   one measurement job                         (Task 10)
  pins.py, recon_plan.py    the pin set, the reconnaissance jobs        (Task 11)
  records.py, campaigns.py  the stored record, the campaign designs     (Task 12)
  recon_report.py           answers from the captures                   (Task 13)
placement/inputs.py         stored runs -> plan 1's simulator inputs    (Task 14)
worker/a4_recon_handler.py, worker/a4_measure_handler.py                (Task 10)
scripts/a4_recon_capture.py, a4_recon_report.py, a4_measure.py          (Task 15)
docs/experiment-a4.md       pre-registration, step 1                    (Task 8)
docs/runbook-a4-recon.md    the owner's paid-run checklist              (Task 16)
tests/a4_fakes.py           shared fakes                                (Task 3)
```

---

## Task 1: The `placement_measure/` package and its import boundary

**Files:**
- Create: `placement_measure/__init__.py`
- Test: `tests/test_placement_measure_boundary.py`

The worker image runs this package, so its defining constraint lands first. It may import `harness/` and the standard library only:
- **Never `coldstart/`.** The image carries it, so a stray import would work there and hide the dependency.
- **Never `autoscale/` or `placement/`.** The image does not carry them, so the import would fail on a paid run.

Each module is imported in a fresh interpreter, for the reason plan 1's boundary test gives. The test is parametrised over whatever modules exist, so later tasks extend it without editing it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_boundary.py`:

```python
"""`placement_measure/` runs inside the worker image, so it may import only
`harness/` and the standard library: never `coldstart/` (which the image
carries, so a stray import would work there and hide the dependency), never
`autoscale/` or `placement/` (which it does not carry, so the import would be
an ImportError on a paid run). Each module is imported in a fresh interpreter,
because pytest shares `sys.modules` across the session and other tests import
`coldstart`."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"coldstart", "autoscale", "placement"}
MODULES = sorted(f"placement_measure.{p.stem}" for p in (ROOT / "placement_measure").glob("*.py")
                 if p.stem != "__init__")


def test_the_package_exists():
    """Guards the guard: with no package the parametrised test below has no
    cases and passes by checking nothing."""
    assert (ROOT / "placement_measure" / "__init__.py").is_file()


def _loads(module: str) -> set[str]:
    code = (f"import importlib, sys; importlib.import_module({module!r}); "
            "print(sorted({m.split('.')[0] for m in sys.modules}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
                         check=False)
    assert out.returncode == 0, out.stderr
    return set(ast.literal_eval(out.stdout))


@pytest.mark.parametrize("module", MODULES)
def test_the_worker_package_loads_neither_coldstart_nor_autoscale(module):
    """The image carries it beside coldstart/, so a stray import would work in
    the image and hide the dependency; and autoscale/ is not in the image at
    all, so importing it would be an ImportError on a paid run."""
    loaded = _loads(module)
    assert not loaded & FORBIDDEN, sorted(loaded & FORBIDDEN)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_boundary.py -q`

Expected: FAIL: `test_the_package_exists`. The parametrised test has no cases yet, which is exactly why the guard exists.

- [ ] **Step 3: Create the package**

```bash
mkdir -p placement_measure && : > placement_measure/__init__.py
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add placement_measure/__init__.py tests/test_placement_measure_boundary.py
git commit -m "feat: the placement_measure package, importable without coldstart or autoscale"
```

---

## Task 2: An engine's configuration and the facts its log states

**Files:**
- Create: `placement_measure/engine.py`
- Test: `tests/test_placement_measure_engine.py`

Artifact 4's jobs start several engines per job: two co-resident checkpoints, or a swap from one to another. So each engine's model, revision and memory share travel in the payload as an `EngineSpec`. The service sweep instead reads its single model from the endpoint's environment. Every flag that changes a measurement is explicit, and prefix caching is pinned off, as in the sweep.

`engine_facts` reads three things from the whole log:
- **KV capacity**, for the go/no-go;
- **`S4b`**, the compile time, which reads a swap-in's compile state rather than inferring it (amendment §5);
- **the batch limit.**

It reuses `harness.vllm_logs` and `harness.sweep_worker.max_num_seqs_from_log`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_engine.py`:

```python
import pytest

from placement_measure.engine import EngineSpec, engine_facts, log_tail

SPEC = EngineSpec("Qwen/Qwen3-4B", "1cfa9a72", 0.45, 2048, 256)


def test_serve_args_pin_every_measurement_flag():
    args = SPEC.serve_args()
    assert args[:8] == ["--revision", "1cfa9a72", "--gpu-memory-utilization", "0.45",
                        "--max-model-len", "2048", "--max-num-seqs", "256"]
    assert "--no-enable-prefix-caching" in args
    assert "--port" not in args


@pytest.mark.parametrize("extra", [("--max_num_seqs", "8"), ("--revision=x",), ("--port", "9")])
def test_a_flag_the_spec_owns_cannot_come_back_through_extra_args(extra):
    with pytest.raises(ValueError, match="owns"):
        EngineSpec("Qwen/Qwen3-4B", "r", 0.45, 2048, 256, extra_args=extra)


@pytest.mark.parametrize("kwargs", [{"revision": ""}, {"gpu_memory_utilization": 1.5},
                                    {"max_model_len": 0}])
def test_an_unpinned_or_impossible_engine_is_refused(kwargs):
    base = {"model": "Qwen/Qwen3-4B", "revision": "r", "gpu_memory_utilization": 0.45,
            "max_model_len": 2048, "max_num_seqs": 256}
    with pytest.raises(ValueError):
        EngineSpec(**{**base, **kwargs})


def test_a_spec_round_trips_through_json_shapes():
    spec = EngineSpec("Qwen/Qwen3-4B", "r", 0.45, 2048, 256, extra_args=("--enable-sleep-mode",))
    assert EngineSpec.from_dict(spec.to_dict()) == spec

# The compile line vLLM 0.27.1 logs; tests/a4_fakes.py, written in Task 3, logs the same.
COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"

def test_engine_facts_read_kv_capacity_compile_time_and_batch_limit():
    from sweep_fakes import KV_LINE, NON_DEFAULT_LINE

    facts = engine_facts([NON_DEFAULT_LINE, KV_LINE, COMPILE_LINE.format(s=0.33)])
    assert facts["kv_capacity_tokens"] == 35792
    assert facts["s4b_s"] == 0.33
    assert facts["max_num_seqs"] == 256


def test_the_log_tail_keeps_the_end_and_the_true_count():
    out = log_tail([f"line {i}" for i in range(500)])
    assert out["log_lines_total"] == 500
    assert out["log_tail"][-1] == "line 499"
    assert len(out["log_tail"]) == 200
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_engine.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.engine'`

- [ ] **Step 3: Implement**

Create `placement_measure/engine.py`:

```python
"""One engine's configuration, and the facts its startup log states.

Artifact 4's jobs start several engines per job: two co-resident checkpoints,
or a swap from one to another. So the model, its revision and its memory share
travel in the job payload as an `EngineSpec`, not in the endpoint environment
the way the service sweep's single model does (`worker/sweep_handler.py`). The
local driver builds every spec from the pre-registration's pin set, so a
campaign still cannot run two configurations by accident.

Every flag that changes what an engine measures is explicit, even where it
equals vLLM 0.27.1's default: a default that moves in a later version would
change the measurement with no error. Prefix caching is off, as in the service
sweep, so a repeated random prompt cannot be served partly from cache.
"""

import math
from dataclasses import asdict, dataclass

from harness.sweep_worker import max_num_seqs_from_log
from harness.vllm_logs import parse_engine_log

__all__ = ["EngineSpec", "engine_facts", "log_tail"]

# What comes back of an engine's log: the last lines, each capped. Artifact 4
# reads its facts from the whole log before the cap (`engine_facts`); the tail
# is evidence for a human, and the job output's size limit is UNVERIFIED (the
# shared tooling plan's item 12), so it stays small.
LOG_TAIL_LINES = 200
LOG_LINE_CHARS = 2000


@dataclass(frozen=True)
class EngineSpec:
    model: str
    revision: str
    gpu_memory_utilization: float
    max_model_len: int
    max_num_seqs: int
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_args", tuple(self.extra_args))
        if not self.model or not self.revision:
            raise ValueError(
                "an engine needs a model and a pinned revision; an unpinned one "
                "lets the checkpoint move under the experiment between jobs"
            )
        if not (math.isfinite(self.gpu_memory_utilization) and 0 < self.gpu_memory_utilization <= 1):
            raise ValueError(
                f"gpu_memory_utilization {self.gpu_memory_utilization!r} must be in (0, 1]; "
                "vLLM refuses anything else at startup, after the job has paid for the pull"
            )
        for name, value in (("max_model_len", self.max_model_len), ("max_num_seqs", self.max_num_seqs)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive int, got {value!r}")
        owned = {"--revision", "--gpu-memory-utilization", "--max-model-len", "--max-num-seqs", "--port"}
        clash = [a for a in self.extra_args if a.split("=", 1)[0].replace("_", "-") in owned]
        if clash:
            raise ValueError(
                f"extra_args {clash} set a flag the spec owns; argparse keeps the last of "
                "two values silently, so the engine would not be the one the spec records"
            )

    def serve_args(self) -> list[str]:
        """Everything after `vllm serve <model>` except `--port`, which
        `harness.serve.served` adds itself."""
        return [
            "--revision", self.revision,
            "--gpu-memory-utilization", str(self.gpu_memory_utilization),
            "--max-model-len", str(self.max_model_len),
            "--max-num-seqs", str(self.max_num_seqs),
            "--no-enable-prefix-caching",
            *self.extra_args,
        ]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["extra_args"] = list(self.extra_args)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EngineSpec":
        return cls(**{**d, "extra_args": tuple(d.get("extra_args", ()))})


def engine_facts(lines) -> dict:
    """KV capacity, version, compile time and the batch limit, from the whole log.

    `s4b_s` is the `torch.compile took N s in total` reading: artifact 1
    published 19.0 s for a compile and 0.33 s for a cache hit, which is how a
    swap-in's compile state is read rather than inferred (amendment §5).
    """
    parsed = parse_engine_log("\n".join(lines))
    max_num_seqs, source = max_num_seqs_from_log(lines)
    return {
        **parsed.engine_info,
        "s4b_s": parsed.phases.get("S4b"),
        "s4_subphases": parsed.phases,
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
    }


def log_tail(lines) -> dict:
    kept = [
        line if len(line) <= LOG_LINE_CHARS else f"{line[:LOG_LINE_CHARS]}...[cut]"
        for line in list(lines)[-LOG_TAIL_LINES:]
    ]
    return {"log_tail": kept, "log_lines_total": len(lines)}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_engine.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/engine.py tests/test_placement_measure_engine.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/engine.py tests/test_placement_measure_engine.py
git commit -m "feat: an engine spec carried in the payload, and the facts its log states"
```

---

## Task 3: GPU memory, and the wait for a stopped engine's memory

**Files:**
- Create: `placement_measure/gpu_memory.py`
- Create: `tests/a4_fakes.py`
- Test: `tests/test_placement_measure_gpu_memory.py`

`harness.serve.Server.stop()` returns when the engine's parent process exits. Its docstring says it does not measure memory release, and leaves that to artifact 4's swap handler. This module is that handler's half.

It reads `memory.used`, not utilisation. Artifact 2's pilot found that utilisation reads 100% at any load, and it says nothing about whether the card has room for the next engine. A timeout is recorded as `released: False`, never raised, so the swap's record keeps it.

The test fakes, `tests/a4_fakes.py`, land here because this is their first user. They build on `tests/sweep_fakes.py`'s engine log lines.

- [ ] **Step 1: Create the shared fakes**

Create `tests/a4_fakes.py`:

```python
"""Fakes for artifact 4's worker side: engines that start on named ports,
nvidia-smi memory readings on a script, and a clock a test advances.

Not a test module; test files import it by name, as they import sweep_fakes.
"""

import contextlib
import subprocess

from sweep_fakes import KV_LINE, NON_DEFAULT_LINE, VERSION_LINE

COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"


class Clock:
    def __init__(self, t: float = 100.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class FakeServer:
    def __init__(self, model, args, port, healthy, log_lines):
        self.model = model
        self.base_url = f"http://127.0.0.1:{port}"
        self.cmd = ["vllm", "serve", model, "--port", str(port), *args]
        self.healthy = healthy
        self.log_lines = list(log_lines)
        self.stops = 0

    def stop(self) -> float:
        self.stops += 1
        return 0.5


class FakeEngines:
    """`served` that records every start, takes `startup_s` of fake time per
    engine, and logs a compile time per model."""

    def __init__(self, clock: Clock, *, startup_s=None, healthy=None, compile_s=None):
        self.clock = clock
        self.startup_s = startup_s or {}
        self.healthy = healthy or {}
        self.compile_s = compile_s or {}
        self.started: list[FakeServer] = []

    @contextlib.contextmanager
    def served(self, model, *, args, env, port=8000, health_timeout=900.0):
        assert env.get("HF_HUB_OFFLINE") == "1", "engines must never download mid-measurement"
        self.clock.t += self.startup_s.get(model, 30.0)
        lines = [VERSION_LINE, NON_DEFAULT_LINE, KV_LINE,
                 COMPILE_LINE.format(s=self.compile_s.get(model, 19.0))]
        server = FakeServer(model, args, port, self.healthy.get(model, True), lines)
        self.started.append(server)
        try:
            yield server
        finally:
            server.stop()


def memory_script(readings):
    """A `subprocess.run` stand-in answering nvidia-smi with each reading in
    turn (MiB used), then the last one forever. None means the query fails."""
    state = {"i": 0}

    def run(cmd, **kwargs):
        i = min(state["i"], len(readings) - 1)
        state["i"] += 1
        used = readings[i]
        if used is None:
            return subprocess.CompletedProcess(cmd, 9, "", "NVML: not found")
        return subprocess.CompletedProcess(cmd, 0, f"{used}, 24564\n", "")

    return run
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_placement_measure_gpu_memory.py`:

```python
import pytest
from a4_fakes import Clock, memory_script

from placement_measure.gpu_memory import read_memory, wait_for_release


def test_memory_reads_used_and_total():
    assert read_memory(run=memory_script([1234]))["used_mib"] == 1234.0


def test_an_unreadable_card_is_a_sample_not_a_crash():
    reading = read_memory(run=memory_script([None]))
    assert reading["used_mib"] is None
    assert "NVML" in reading["error"]


def test_release_waits_until_memory_falls_to_the_target():
    clock = Clock(0.0)
    out = wait_for_release(
        1000, timeout_s=10, poll_s=0.25, run=memory_script([9000, 9000, 4000, 900]),
        clock=clock, sleep=clock.sleep,
    )
    assert out["released"]
    assert out["seconds"] == pytest.approx(0.75)
    assert len(out["samples"]) == 4


def test_release_that_never_comes_is_recorded_not_raised():
    clock = Clock(0.0)
    out = wait_for_release(1000, timeout_s=1.0, run=memory_script([9000]), clock=clock,
                           sleep=clock.sleep)
    assert not out["released"]
    assert out["seconds"] >= 1.0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_gpu_memory.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.gpu_memory'`

- [ ] **Step 4: Implement**

Create `placement_measure/gpu_memory.py`:

```python
"""GPU memory readings, and the wait until a stopped engine's memory is free.

`harness.serve.Server.stop()` returns when the `vllm serve` parent has exited,
and says explicitly that it does not measure memory release: the driver frees
a dead process's memory shortly after, and how shortly is part of what a swap
costs (amendment §5). This module measures that part. It reads `memory.used`,
not `utilization.gpu`: artifact 2's pilot found utilisation reads 100% at any
load, and it says nothing about whether the card has room for the next engine.

A failed query is data, as in `harness.gpu_util`: an unreadable card is a
sample with `used_mib` None and an `error`, never an invented number.
"""

import subprocess
import time
from collections.abc import Callable

__all__ = ["QUERY", "read_memory", "wait_for_release"]

QUERY = ("nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits")
QUERY_TIMEOUT_S = 5.0


def read_memory(*, gpu_index: int = 0, run: Callable = subprocess.run) -> dict:
    cmd = [*QUERY, f"--id={gpu_index}"]
    try:
        proc = run(cmd, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_S)
        raw = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return {"used_mib": None, "total_mib": None, "raw": raw,
                    "error": f"exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"}
        used, total = (float(part) for part in raw.split(","))
    except Exception as e:  # noqa: BLE001 -- an unreadable card is a sample, not a crash
        return {"used_mib": None, "total_mib": None, "raw": locals().get("raw", ""),
                "error": repr(e)[:200]}
    return {"used_mib": used, "total_mib": total, "raw": raw, "error": None}


def wait_for_release(
    target_used_mib: float,
    *,
    timeout_s: float,
    poll_s: float = 0.25,
    gpu_index: int = 0,
    run: Callable = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll until `memory.used` is at or below `target_used_mib`.

    The caller sets the target from a reading taken before the engine started
    plus a tolerance, because the card's idle usage is not zero and differs
    between hosts. Returns `released`, the `seconds` from the call to the first
    reading at or below target (or to the timeout), and every sample. A timeout
    is `released: False`, not an exception: the swap's record keeps it and the
    analysis decides, rather than the job dying with nothing stored.
    """
    t0 = clock()
    samples = []
    while True:
        reading = read_memory(gpu_index=gpu_index, run=run)
        now = clock() - t0
        samples.append({"t_s": now, **reading})
        used = reading["used_mib"]
        if used is not None and used <= target_used_mib:
            return {"released": True, "seconds": now, "target_used_mib": target_used_mib,
                    "samples": samples}
        if now >= timeout_s:
            return {"released": False, "seconds": now, "target_used_mib": target_used_mib,
                    "samples": samples}
        sleep(poll_s)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_gpu_memory.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/gpu_memory.py tests/a4_fakes.py tests/test_placement_measure_gpu_memory.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement_measure/gpu_memory.py tests/a4_fakes.py tests/test_placement_measure_gpu_memory.py
git commit -m "feat: read GPU memory, and time a stopped engine's release"
```

---

## Task 4: Page-cache state and eviction

**Files:**
- Create: `placement_measure/pagecache.py`
- Test: `tests/test_placement_measure_pagecache.py`

A twenty-model fleet's weights don't fit in host memory, but a three-model validation set's do. Measured on a warm cache, swaps would look faster than the simulated fleet's (amendment §5).

Two eviction methods are tried in turn, and each is recorded:
- **`drop_caches`**, which needs root and a writable `/proc/sys`;
- **`posix_fadvise(DONTNEED)`** on each weight file, which needs no privilege.

Whether the second works on RunPod's network volume is UNVERIFIED. The kernel's `Cached:` figure, read before and after, is the evidence. Neither method is assumed to work; that is a reconnaissance answer.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_pagecache.py`:

```python
from placement_measure.pagecache import cached_kib, make_cold, weight_files


def test_cached_reads_the_kernels_figure(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 100 kB\nCached:          123456 kB\n")
    assert cached_kib(str(meminfo)) == 123456
    assert cached_kib(str(tmp_path / "missing")) is None


def test_weight_files_resolve_the_snapshot_symlinks(tmp_path):
    blobs = tmp_path / "hub" / "models--Qwen--Qwen3-4B" / "blobs"
    snap = tmp_path / "hub" / "models--Qwen--Qwen3-4B" / "snapshots" / "rev1"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (blobs / "abc").write_text("w")
    (snap / "model-00001-of-00001.safetensors").symlink_to(blobs / "abc")
    (snap / "config.json").write_text("{}")
    assert weight_files(str(tmp_path), "Qwen/Qwen3-4B", "rev1") == [str((blobs / "abc").resolve())]


def test_make_cold_records_both_attempts_and_the_evidence(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("Cached: 500 kB\n")
    weights = tmp_path / "w.safetensors"
    weights.write_text("w")
    advised = []
    out = make_cold(
        [str(weights)], meminfo=str(meminfo), drop_path=str(tmp_path / "no" / "drop_caches"),
        sync=lambda: None, fadvise=lambda fd, off, n, advice: advised.append(advice),
    )
    drop, fadv = out["attempts"]
    assert not drop["ok"]  # the drop path's directory does not exist, like a read-only /proc/sys
    assert fadv["ok"] and fadv["files"] == 1 and advised
    assert out["cached_kib_before"] == 500
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_pagecache.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.pagecache'`

- [ ] **Step 3: Implement**

Create `placement_measure/pagecache.py`:

```python
"""Whether a swap-in's weights are read from storage or from the host's page cache.

A twenty-model fleet's weights do not fit in host memory, and a three-model
validation set's do (amendment §5). Measured with the cache warm, swaps would
look faster than the simulated fleet's. So every swap records the cache state
it ran in, and can ask for the weights to be evicted first.

Two eviction methods, tried in order, each recorded:

- `drop_caches`: write "3" to /proc/sys/vm/drop_caches after a sync. Needs
  root and a writable /proc/sys, which a container may not have.
- `fadvise`: `posix_fadvise(POSIX_FADV_DONTNEED)` on every weight file. Needs
  no privilege, but whether it evicts pages of a file on RunPod's network
  volume is UNVERIFIED; reconnaissance reads `Cached:` from /proc/meminfo
  before and after to see.

Neither is assumed to work. The answer is a reconnaissance result.
"""

import contextlib
import os
from collections.abc import Callable
from pathlib import Path

__all__ = ["cached_kib", "make_cold", "weight_files"]

MEMINFO = "/proc/meminfo"
DROP_CACHES = "/proc/sys/vm/drop_caches"
# Linux only; None elsewhere (the macOS test host), where fadvise is reported
# as unavailable rather than faked.
POSIX_FADVISE = getattr(os, "posix_fadvise", None)


def cached_kib(path: str = MEMINFO) -> int | None:
    """The kernel's `Cached:` figure, in KiB; None if it cannot be read."""
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith("Cached:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def weight_files(hf_home: str, model: str, revision: str) -> list[str]:
    """The checkpoint's safetensors files in the Hugging Face cache, resolved.

    The cache stores a snapshot as symlinks into `blobs/`; the page cache holds
    the blobs, so those are what get evicted.
    """
    org, name = model.split("/", 1)
    snapshot = Path(hf_home) / "hub" / f"models--{org}--{name}" / "snapshots" / revision
    return sorted(str(p.resolve()) for p in snapshot.glob("*.safetensors"))


def _drop_all(drop_path: str, sync: Callable[[], None]) -> dict:
    try:
        sync()
        Path(drop_path).write_text("3\n")
    except OSError as e:
        return {"method": "drop_caches", "ok": False, "error": repr(e)[:200]}
    return {"method": "drop_caches", "ok": True, "error": None}


def _fadvise_all(paths, fadvise: Callable | None) -> dict:
    if fadvise is None:
        return {"method": "fadvise", "ok": False, "error": "os.posix_fadvise is unavailable",
                "files": 0}
    errors = []
    for path in paths:
        fd = None
        try:
            fd = os.open(path, os.O_RDONLY)
            fadvise(fd, 0, 0, getattr(os, "POSIX_FADV_DONTNEED", 4))
        except OSError as e:
            errors.append(f"{path}: {e!r}"[:200])
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
    return {"method": "fadvise", "ok": not errors and bool(paths), "errors": errors,
            "files": len(paths)}


def make_cold(
    paths,
    *,
    meminfo: str = MEMINFO,
    drop_path: str = DROP_CACHES,
    sync: Callable[[], None] = os.sync,
    fadvise: Callable | None = POSIX_FADVISE,
) -> dict:
    """Try both evictions and record what the kernel's cache did.

    `cached_kib_before` and `cached_kib_after` are the evidence: a method can
    report success and evict nothing, which is exactly the network-volume case
    that is unverified.
    """
    paths = list(paths)
    before = cached_kib(meminfo)
    attempts = [_drop_all(drop_path, sync), _fadvise_all(paths, fadvise)]
    after = cached_kib(meminfo)
    return {
        "requested": True,
        "files": paths,
        "attempts": attempts,
        "cached_kib_before": before,
        "cached_kib_after": after,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_pagecache.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/pagecache.py tests/test_placement_measure_pagecache.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/pagecache.py tests/test_placement_measure_pagecache.py
git commit -m "feat: record and try to evict a checkpoint's page-cache state"
```

---

## Task 5: The engine's running-request count

**Files:**
- Create: `placement_measure/metrics.py`
- Test: `tests/test_placement_measure_metrics.py`

A co-located measurement is valid only if the neighbour carried its load for the whole measured run. The neighbour's bench client can't say so: it reports what it sent, not what the engine ran at each moment.

vLLM 0.27.1 exports `vllm:num_requests_running` on `/metrics`. This was checked in `vllm/v1/metrics/loggers.py` at the v0.27.1 tag on 2026-10-04. The measured run samples that metric on the neighbour, and the cell keeps the samples.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_metrics.py`:

```python
from a4_fakes import Clock

from placement_measure.metrics import running_from_text, wait_running


def test_running_requests_sum_every_series_and_ignore_comments():
    text = (
        "# HELP vllm:num_requests_running Number of requests in model execution batches.\n"
        'vllm:num_requests_running{engine="0",model_name="m"} 3.0\n'
        'vllm:num_requests_running{engine="1",model_name="m"} 2.0\n'
        'vllm:num_requests_running_total 99\n'
        'vllm:num_requests_waiting{engine="0"} 7.0\n'
    )
    assert running_from_text(text) == 5.0
    assert running_from_text("# nothing\n") is None


def test_wait_running_returns_once_the_load_is_reached():
    clock = Clock(0.0)

    class R:
        def __init__(self, n):
            self.text = f"vllm:num_requests_running 0\nvllm:num_requests_running{{e=\"0\"}} {n}\n"

        def raise_for_status(self):
            pass

    loads = iter([0, 2, 4, 8])
    out = wait_running("http://x", at_least=8, timeout_s=10, get=lambda url, timeout: R(next(loads)),
                       clock=clock, sleep=clock.sleep)
    assert out["reached"] and out["last"]["running"] == 8
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_metrics.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.metrics'`

- [ ] **Step 3: Implement**

Create `placement_measure/metrics.py`:

```python
"""The engine's own count of requests in flight, from its Prometheus endpoint.

A co-located measurement is only valid if the neighbour engine was carrying
its load for the whole measured run. The neighbour's bench client cannot say
so: it reports what it sent, not what the engine was running at each instant.
vLLM 0.27.1 exports `vllm:num_requests_running` on `/metrics`
(vllm/v1/metrics/loggers.py at the v0.27.1 tag), so the measured run samples
it on the neighbour and keeps the samples.
"""

import threading
import time
from collections.abc import Callable
from typing import Self

import requests

__all__ = ["RUNNING_METRIC", "RunningSampler", "read_running", "running_from_text", "wait_running"]

RUNNING_METRIC = "vllm:num_requests_running"
REQUEST_TIMEOUT_S = 2.0


def running_from_text(text: str) -> float | None:
    """Sum of every `vllm:num_requests_running` series; None if there is none.

    Summed over label sets because one engine can export one series per
    engine core; a single series is the case seen on one GPU.
    """
    values = []
    for line in text.splitlines():
        if line.startswith(RUNNING_METRIC) and not line.startswith("#"):
            name = line.split("{", 1)[0].split(" ", 1)[0]
            if name == RUNNING_METRIC:
                values.append(float(line.rsplit(" ", 1)[1]))
    return sum(values) if values else None


def read_running(base_url: str, *, get: Callable = requests.get) -> dict:
    try:
        r = get(f"{base_url}/metrics", timeout=REQUEST_TIMEOUT_S)
        r.raise_for_status()
        return {"running": running_from_text(r.text), "error": None}
    except Exception as e:  # noqa: BLE001 -- an unreadable endpoint is a sample, not a crash
        return {"running": None, "error": repr(e)[:200]}


def wait_running(
    base_url: str,
    *,
    at_least: float,
    timeout_s: float,
    poll_s: float = 0.25,
    get: Callable = requests.get,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Wait until the engine runs `at_least` requests, so the measured run
    starts under the neighbour's full load rather than its ramp-up."""
    t0 = clock()
    last = None
    while True:
        last = read_running(base_url, get=get)
        elapsed = clock() - t0
        if last["running"] is not None and last["running"] >= at_least:
            return {"reached": True, "seconds": elapsed, "last": last}
        if elapsed >= timeout_s:
            return {"reached": False, "seconds": elapsed, "last": last}
        sleep(poll_s)


class RunningSampler:
    """Samples `vllm:num_requests_running` on a background thread while in a `with`."""

    def __init__(
        self,
        base_url: str,
        interval: float = 0.5,
        *,
        get: Callable = requests.get,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.base_url = base_url
        self.interval = interval
        self.samples: list[dict] = []
        self._get = get
        self._clock = clock
        self._t0 = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        k = 0
        while True:
            started = self._clock()
            self.samples.append({"t_s": started - self._t0, **read_running(self.base_url, get=self._get)})
            k += 1
            if self._stop.wait(max(0.0, self._t0 + k * self.interval - self._clock())):
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
            self._thread.join(timeout=self.interval + REQUEST_TIMEOUT_S + 1.0)

    def values(self) -> list[float]:
        return [s["running"] for s in self.samples if s["running"] is not None]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_metrics.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/metrics.py tests/test_placement_measure_metrics.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/metrics.py tests/test_placement_measure_metrics.py
git commit -m "feat: sample the engine's own count of requests in flight"
```

---

## Task 6: A process-level swap

**Files:**
- Create: `placement_measure/swap.py`
- Test: `tests/test_placement_measure_swap.py`

This builds amendment §1e item 5. A swap's duration is the sum of what a fleet pays between the victim draining and the incoming model serving:
- **teardown**, from `.stop()`;
- **memory release**, from Task 3;
- **the successor's bring-up**, until it answers `/health`.

The simulator draws from that sum. Draining is the simulator's own business, so A serves nothing here.

Engines run with `HF_HUB_OFFLINE=1`, because a download during a timed swap would be published as a slow swap. The tests' fake `served` refuses to start an engine without that flag.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_swap.py`:

```python
"""A process-level swap, against fake engines, memory and cache.

A's engine takes 40 s of fake time to start, B's 25 s; `stop()` returns
0.5 s; memory reads 9000 MiB twice then falls to idle. So the swap is
teardown 0.5 + release (two 0.25 s polls) + B's 25 s.
"""

import pytest
from a4_fakes import Clock, FakeEngines, memory_script

from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.swap import SwapDeps, measure_swap

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.92, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.92, 2048, 256)


def _deps(engines, clock, readings, cache_calls):
    run = memory_script(readings)
    return SwapDeps(
        served=engines.served,
        read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda target, timeout_s: wait_for_release(
            target, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: cache_calls.append(paths) or {"requested": True, "files": paths},
        weight_files=lambda hf_home, model, revision: [f"{hf_home}/{model}@{revision}"],
        clock=clock,
    )


def _swap(cold=False, healthy=None, readings=(500, 9000, 9000, 500)):
    clock = Clock()
    engines = FakeEngines(clock, startup_s={A.model: 40.0, B.model: 25.0}, healthy=healthy,
                          compile_s={B.model: 0.33})
    cache_calls = []
    out = measure_swap(A, B, cold=cold, hf_home="/vol/hf", release_tolerance_mib=256,
                       release_timeout_s=60, deps=_deps(engines, clock, list(readings), cache_calls))
    return out, engines, cache_calls


def test_the_swap_is_teardown_plus_release_plus_bring_up():
    out, engines, _ = _swap()
    assert out["healthy"]
    assert out["teardown_s"] == 0.5
    assert out["release"]["released"] and out["release"]["seconds"] == pytest.approx(0.5)
    assert out["b"]["startup_s"] == pytest.approx(25.0)
    assert out["swap_s"] == pytest.approx(0.5 + 0.5 + 25.0)
    assert [s.model for s in engines.started] == [A.model, B.model]


def test_the_release_target_is_the_idle_reading_plus_the_tolerance():
    out, _, _ = _swap()
    assert out["baseline_memory"]["used_mib"] == 500
    assert out["release"]["target_used_mib"] == 756


def test_the_incoming_models_compile_state_is_read_from_its_log():
    out, _, _ = _swap()
    assert out["b"]["facts"]["s4b_s"] == 0.33
    assert out["a"]["facts"]["s4b_s"] == 19.0


def test_a_cold_swap_evicts_the_incoming_models_weights_and_records_it():
    out, _, calls = _swap(cold=True)
    assert calls == [[f"/vol/hf/{B.model}@rb"]]
    assert out["cache"]["requested"]
    warm, _, none = _swap(cold=False)
    assert none == [] and warm["cache"] == {"requested": False}


def test_an_unhealthy_incoming_engine_is_a_failed_swap_with_its_log():
    out, _, _ = _swap(healthy={B.model: False})
    assert not out["healthy"] and out["swap_s"] is None
    assert "never answered" in out["failure"]
    assert out["b"]["log_tail"]


def test_an_unhealthy_outgoing_engine_never_starts_the_successor():
    out, engines, _ = _swap(healthy={A.model: False})
    assert not out["healthy"]
    assert [s.model for s in engines.started] == [A.model]


def test_memory_that_is_never_released_leaves_no_swap_time():
    out, _, _ = _swap(readings=(500, 9000))
    assert not out["release"]["released"]
    assert out["swap_s"] is None and "not released" in out["failure"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_swap.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.swap'`

- [ ] **Step 3: Implement**

Create `placement_measure/swap.py`:

```python
"""One process-level swap: engine A serving, torn down, its memory released,
optionally its successor's weights evicted from the page cache, engine B up.

The swap's duration is the sum of the three parts a fleet pays between the
victim draining and the incoming model serving: `teardown_s` (A's process
exiting, from `Server.stop()`), `release.seconds` (the card's memory back at
its idle level), and `b_startup_s` (B from spawn to answering `/health`). The
simulator draws from the distribution of that sum (amendment §5). Draining A's
in-flight requests is the simulator's own business and is not measured here:
A serves nothing in this job.

Engines run with `HF_HUB_OFFLINE=1`. Weights must already be on the network
volume (reconnaissance's `stage` probe puts them there); a download in the
middle of a measured swap would read as a very slow swap and be published as
one.

`healthy` in the result means both engines answered `/health`. That is the
field `RunPodSubmitter` treats as success, so a swap whose B never came up is
stored as failed with this output as its diagnostics.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from placement_measure.engine import EngineSpec, engine_facts, log_tail

__all__ = ["ENGINE_ENV", "SwapDeps", "measure_swap"]

ENGINE_ENV = {"HF_HUB_OFFLINE": "1"}
PORT = 8000


@dataclass
class SwapDeps:
    """The effects, injectable so tests run a swap without an engine or a GPU.
    None means the real one, resolved lazily so importing needs no vLLM."""

    served: Callable | None = None
    read_memory: Callable | None = None
    wait_for_release: Callable | None = None
    make_cold: Callable | None = None
    weight_files: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: SwapDeps) -> SwapDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.read_memory is None or d.wait_for_release is None:
        from placement_measure import gpu_memory

        d.read_memory = d.read_memory or gpu_memory.read_memory
        d.wait_for_release = d.wait_for_release or gpu_memory.wait_for_release
    if d.make_cold is None or d.weight_files is None:
        from placement_measure import pagecache

        d.make_cold = d.make_cold or pagecache.make_cold
        d.weight_files = d.weight_files or pagecache.weight_files
    return d


def _engine_part(spec: EngineSpec, server, startup_s: float) -> dict:
    lines = list(server.log_lines)
    return {
        "spec": spec.to_dict(),
        "healthy": bool(server.healthy),
        "startup_s": startup_s,
        "served_cmd": list(server.cmd),
        "facts": engine_facts(lines),
        **log_tail(lines),
    }


def measure_swap(
    a: EngineSpec,
    b: EngineSpec,
    *,
    cold: bool,
    hf_home: str,
    release_tolerance_mib: float,
    release_timeout_s: float,
    deps: SwapDeps | None = None,
) -> dict:
    d = _resolve(deps or SwapDeps())
    baseline = d.read_memory()
    t0 = d.clock()
    with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT) as sa:
        part_a = _engine_part(a, sa, d.clock() - t0)
        teardown_s = sa.stop()
    out = {"cold": cold, "baseline_memory": baseline, "a": part_a, "teardown_s": teardown_s}
    if not part_a["healthy"]:
        return {**out, "healthy": False, "b": None, "swap_s": None,
                "failure": "engine A never answered /health; there is no swap to time"}
    if baseline["used_mib"] is None:
        return {**out, "healthy": False, "b": None, "swap_s": None,
                "failure": "the idle memory reading failed, so release has no target"}
    release = d.wait_for_release(
        baseline["used_mib"] + release_tolerance_mib, timeout_s=release_timeout_s
    )
    cache = d.make_cold(d.weight_files(hf_home, b.model, b.revision)) if cold else {"requested": False}
    t1 = d.clock()
    with d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=PORT) as sb:
        part_b = _engine_part(b, sb, d.clock() - t1)
        sb.stop()
    ok = part_b["healthy"] and release["released"]
    return {
        **out,
        "healthy": part_b["healthy"],
        "release": release,
        "cache": cache,
        "b": part_b,
        "swap_s": teardown_s + release["seconds"] + part_b["startup_s"] if ok else None,
        "failure": None if ok else (
            "engine B never answered /health" if not part_b["healthy"]
            else "A's memory was not released within the timeout"
        ),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_swap.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/swap.py tests/test_placement_measure_swap.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/swap.py tests/test_placement_measure_swap.py
git commit -m "feat: time a process-level swap to the successor's health, memory release included"
```

---

## Task 7: One cell of the co-location grid

**Files:**
- Create: `placement_measure/colocation.py`
- Test: `tests/test_placement_measure_colocation.py`

This builds amendment §1e item 4. It produces one point of plan 1's two-load surface: A's latency at its own concurrency while its neighbour, B, holds a load. Three kinds of cell share one code path:
- **solo:** A alone at full memory;
- **idle neighbour:** A at the split, with B resident and idle;
- **loaded:** A at the split, with B loaded.

**Reused, not rewritten.** The measured run is the service sweep's own `run_one`, under the shared failure rule. Its prompts are random at a fixed length. Artifact 4's request shape is its own (amendment §4), and the image can't run the custom dataset, because pandas is absent.

**How the neighbour's load is enforced.** It runs on a thread whose bench run stops the moment the measured run ends. That needed a stoppable stand-in for `subprocess.run`, because `run_bench` can't be cancelled. The cell waits for B to report its load before measuring, samples B throughout, and flags a neighbour that ran out early.

**Serial start-up.** Engines start one after the other, so neither profiles its memory while the other allocates.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_colocation.py`:

```python
"""One co-location cell, against fake engines, bench and samplers."""

import contextlib
import threading

import pytest
from a4_fakes import Clock, FakeEngines

from harness.bench import BenchError
from placement_measure.colocation import CellDeps, CellSpec, measure_cell, stoppable_run
from placement_measure.engine import EngineSpec

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


def _cell(neighbour, **over):
    return CellSpec(**{"own": 8, "neighbour": neighbour, "input_len": 1024, "output_len": 256,
                       "num_prompts": 160, "warmup_prompts": 8, "neighbour_prompts": 100_000,
                       "seed": 7, **over})


class FakeSampler:
    def __init__(self, base_url, values):
        self.base_url = base_url
        self.samples = [{"t_s": i * 0.5, "running": v, "error": None} for i, v in enumerate(values)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def values(self):
        return [s["running"] for s in self.samples]


def _deps(clock, *, neighbour_finishes=False, reached=True, healthy=None, run_one=None):
    engines = FakeEngines(clock, healthy=healthy)
    calls = {"run_one": [], "bench": []}

    def fake_run_one(base_url, **kw):
        calls["run_one"].append((base_url, kw))
        if neighbour_finishes:
            # The fake neighbour returns at once; a measured run lasts far
            # longer than the microseconds its thread needs to finish.
            threading.Event().wait(0.2)
        return {"latency_s": 0.8, "plan": kw["plan"].to_dict(), "level": kw["level"]}

    def fake_bench(base_url, **kw):
        calls["bench"].append((base_url, kw))
        stop_run = kw["run"]
        if neighbour_finishes:
            return {"completed": 1}
        # Block like a long tool run until the cell stops it, then fail the way
        # a terminated tool does.
        stop_run.stop.wait(5)
        raise BenchError("vllm bench serve exited -15")

    def fake_stoppable(stop):
        run = lambda *a, **k: None
        run.stop = stop
        return run

    deps = CellDeps(
        served=engines.served, run_one=run_one or fake_run_one, run_bench=fake_bench,
        sampler_factory=lambda: contextlib.nullcontext(),
        running_sampler=lambda base_url: FakeSampler(base_url, [8, 8, 7, 8]),
        wait_running=lambda base_url, at_least, timeout_s: {"reached": reached, "seconds": 2.0},
        stoppable=fake_stoppable, clock=clock,
    )
    return deps, engines, calls


def test_a_solo_cell_runs_one_engine_at_its_own_concurrency():
    deps, engines, calls = _deps(Clock())
    out = measure_cell(A, None, _cell(None), deps=deps)
    assert out["healthy"] and out["run"]["level"] == 8
    assert [s.base_url for s in engines.started] == ["http://127.0.0.1:8000"]
    plan = calls["run_one"][0][1]["plan"]
    assert plan.path == "random-fixed-length"
    assert "--random-input-len" in plan.dataset_args and "1024" in plan.dataset_args


def test_an_idle_neighbour_cell_starts_both_engines_and_loads_neither():
    deps, engines, calls = _deps(Clock())
    out = measure_cell(A, B, _cell(0), deps=deps)
    assert [s.base_url.rsplit(":", 1)[1] for s in engines.started] == ["8000", "8001"]
    assert out["neighbour_load"] == {"level": 0}
    assert calls["bench"] == []


def test_a_loaded_cell_holds_the_neighbour_through_the_measured_run():
    deps, _, calls = _deps(Clock())
    out = measure_cell(A, B, _cell(8), deps=deps)
    load = out["neighbour_load"]
    assert out["run"]["latency_s"] == 0.8
    assert calls["bench"][0][0] == "http://127.0.0.1:8001"
    assert calls["bench"][0][1]["max_concurrency"] == 8
    assert load["ended"] == "stopped" and not load["ended_before_measured_run"]
    assert load["median_running"] == 8 and load["min_running"] == 7


def test_a_neighbour_that_finished_early_is_flagged():
    deps, _, _ = _deps(Clock(), neighbour_finishes=True)
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert out["neighbour_load"]["ended"] == "finished"
    assert out["neighbour_load"]["ended_before_measured_run"]


def test_a_neighbour_that_never_ramped_is_recorded():
    deps, _, _ = _deps(Clock(), reached=False)
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert out["neighbour_load"]["ramp"]["reached"] is False


def test_an_unhealthy_neighbour_fails_the_cell_before_any_load():
    deps, _, calls = _deps(Clock(), healthy={B.model: False})
    out = measure_cell(A, B, _cell(8), deps=deps)
    assert not out["healthy"] and calls["run_one"] == [] and calls["bench"] == []


def test_a_failed_measurement_is_data_and_the_engines_are_stopped():
    def broken(base_url, **kw):
        raise BenchError("exited 1")

    deps, engines, _ = _deps(Clock(), run_one=broken)
    out = measure_cell(A, B, _cell(0), deps=deps)
    assert out["healthy"] and out["run"] is None and "BenchError" in out["run_error"]
    assert all(s.stops >= 1 for s in engines.started)


def test_stoppable_run_ends_a_long_tool_when_asked(tmp_path):
    stop = threading.Event()
    run = stoppable_run(stop)
    threading.Timer(0.3, stop.set).start()
    proc = run(["sleep", "30"], capture_output=True, text=True, check=False)
    assert proc.returncode != 0


def test_stoppable_run_returns_a_finished_tools_output():
    run = stoppable_run(threading.Event())
    proc = run(["echo", "hi"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0 and proc.stdout.strip() == "hi"


def test_a_cell_spec_refuses_impossible_loads():
    with pytest.raises(ValueError):
        _cell(-1)
    with pytest.raises(ValueError):
        CellSpec(own=0, neighbour=None, input_len=1, output_len=1, num_prompts=1,
                 warmup_prompts=0, neighbour_prompts=0, seed=1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_colocation.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.colocation'`

- [ ] **Step 3: Implement**

Create `placement_measure/colocation.py`:

```python
"""One cell of the co-location grid: a measured load on engine A while engine B,
resident on the same card, carries a held background load.

The cell's output is A's latency at its own concurrency `own` with its
neighbour at concurrency `neighbour` -- one point of the two-load surface
`placement.colocated.ColocatedSurface` interpolates (amendment §1e item 3).
Three kinds of cell, all on the same code:

- `neighbour is None`: A alone at full memory. The solo curve.
- `neighbour == 0`: A at the split, B resident and idle. The solo-at-split
  curve, the surface's first column.
- `neighbour > 0`: A at the split under B's load.

The measured run is `harness.sweep_worker.run_one`, the service sweep's own:
one warm-up, then one `vllm bench serve` at `own`, summarised under the shared
failure rule, so a co-located latency and a solo one mean the same thing. Its
prompts are random at a fixed length (`random_dataset_args`), because artifact
4's request shape is its own (amendment §4) and the image cannot run the
custom dataset (pandas is absent, artifact 2's pilot, 2026-10-04).

Why the neighbour's load is checked rather than assumed. The neighbour runs
its own bench client on a thread, sized to outlast the measured run and
stopped as soon as the measured run ends. Before the measured run starts, the
cell waits until B reports at least `neighbour` requests running; during it,
`vllm:num_requests_running` on B is sampled. A neighbour that finished early,
or never reached its load, leaves the cell flagged in its own output rather
than silently measured against a lighter neighbour.

Engines start one after the other (A, then B). vLLM sizes its KV cache from a
profiling pass, and two engines profiling at once would each see the other's
allocations as they happen; whether that changes the result is UNVERIFIED,
and serial startup removes the question.
"""

import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness.bench import BenchError
from harness.stats import median
from harness.sweep_worker import PromptPlan, random_dataset_args
from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV

__all__ = ["PROMPT_PATH", "CellDeps", "CellSpec", "measure_cell", "stoppable_run"]

PORT_MEASURED = 8000
PORT_NEIGHBOUR = 8001
PROMPT_PATH = "random-fixed-length"
NEIGHBOUR_SEED_OFFSET = 700_000
STOP_POLL_S = 0.5


@dataclass(frozen=True)
class CellSpec:
    own: int
    neighbour: int | None
    input_len: int
    output_len: int
    num_prompts: int
    warmup_prompts: int
    neighbour_prompts: int
    seed: int
    ramp_timeout_s: float = 60.0

    def __post_init__(self) -> None:
        if type(self.own) is not int or self.own < 1:
            raise ValueError(f"own concurrency must be a positive int, got {self.own!r}")
        if self.neighbour is not None and (type(self.neighbour) is not int or self.neighbour < 0):
            raise ValueError(
                f"neighbour must be None (solo) or an int >= 0, got {self.neighbour!r}"
            )
        if self.neighbour and self.neighbour_prompts < 1:
            raise ValueError("a loaded neighbour needs neighbour_prompts to send")


def stoppable_run(stop: threading.Event, popen: Callable = subprocess.Popen) -> Callable:
    """A `subprocess.run` stand-in for `harness.bench.run_bench` that ends the
    tool early when `stop` is set.

    `run_bench` has no way to cancel a run, and the neighbour's load must end
    when the measured run does, or the job pays for minutes of load nobody
    reads. Output goes to temporary files rather than pipes, so a chatty tool
    cannot fill a pipe nobody reads and block. A stopped run exits non-zero,
    and `run_bench` raises `BenchError`, which the neighbour thread expects.
    """

    def run(cmd, *, capture_output, text, check, timeout=None):
        with tempfile.TemporaryFile("w+") as out, tempfile.TemporaryFile("w+") as err:
            proc = popen(cmd, stdout=out, stderr=err, text=True)
            deadline = None if timeout is None else time.monotonic() + timeout
            while proc.poll() is None:
                if stop.wait(STOP_POLL_S) or (deadline is not None and time.monotonic() > deadline):
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            out.seek(0)
            err.seek(0)
            return subprocess.CompletedProcess(cmd, proc.returncode, out.read(), err.read())

    return run


@dataclass
class CellDeps:
    served: Callable | None = None
    run_one: Callable | None = None
    run_bench: Callable | None = None
    sampler_factory: Callable | None = None
    running_sampler: Callable | None = None
    wait_running: Callable | None = None
    stoppable: Callable = stoppable_run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: CellDeps) -> CellDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.run_one is None:
        from harness.sweep_worker import run_one

        d.run_one = run_one
    if d.run_bench is None:
        from harness.bench import run_bench

        d.run_bench = run_bench
    if d.sampler_factory is None:
        from harness.gpu_util import GpuUtilSampler

        d.sampler_factory = GpuUtilSampler
    if d.running_sampler is None or d.wait_running is None:
        from placement_measure import metrics

        d.running_sampler = d.running_sampler or metrics.RunningSampler
        d.wait_running = d.wait_running or metrics.wait_running
    return d


def _engine(spec: EngineSpec, server) -> dict:
    lines = list(server.log_lines)
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "served_cmd": list(server.cmd),
            "facts": engine_facts(lines), **log_tail(lines)}


def _plan(cell: CellSpec) -> PromptPlan:
    return PromptPlan(
        path=PROMPT_PATH,
        dataset_args=tuple(random_dataset_args(input_len=cell.input_len, output_len=cell.output_len)),
        prompt_tokens=cell.input_len,
    )


def _measure(d: CellDeps, server, spec: EngineSpec, cell: CellSpec, workdir, deadline) -> dict:
    return d.run_one(
        server.base_url, model=spec.model, level=cell.own, num_prompts=cell.num_prompts,
        warmup_prompts=cell.warmup_prompts, plan=_plan(cell), seed=cell.seed, workdir=workdir,
        run_bench=d.run_bench, sampler_factory=d.sampler_factory, deadline=deadline, clock=d.clock,
    )


def _loaded(d: CellDeps, ea, eb, a: EngineSpec, b: EngineSpec, cell: CellSpec, workdir, deadline):
    stop = threading.Event()
    finished = threading.Event()
    state: dict = {}

    def load() -> None:
        try:
            d.run_bench(
                eb.base_url, model=b.model, max_concurrency=cell.neighbour,
                num_prompts=cell.neighbour_prompts, dataset_args=list(_plan(cell).dataset_args),
                ignore_eos=True, seed=cell.seed + NEIGHBOUR_SEED_OFFSET,
                result_dir=Path(workdir) / "neighbour", run=d.stoppable(stop),
            )
            state["ended"] = "finished"
        except BenchError as e:
            state["ended"] = "stopped" if stop.is_set() else f"error: {e}"[:400]
        finally:
            finished.set()

    thread = threading.Thread(target=load, daemon=True)
    thread.start()
    try:
        ramp = d.wait_running(eb.base_url, at_least=cell.neighbour, timeout_s=cell.ramp_timeout_s)
        with d.running_sampler(eb.base_url) as sampler:
            run = _measure(d, ea, a, cell, workdir, deadline)
        # Read before `stop` is set: a neighbour that ended by then ran out of
        # prompts during the measured run, so part of that run was measured
        # against a lighter neighbour than the cell is labelled with.
        ended_early = finished.is_set()
    finally:
        stop.set()
        thread.join(timeout=30)
    values = sampler.values()
    return run, {
        "level": cell.neighbour,
        "ramp": ramp,
        "samples": sampler.samples,
        "median_running": median(values) if values else None,
        "min_running": min(values) if values else None,
        "ended": state.get("ended"),
        "ended_before_measured_run": ended_early,
    }


def measure_cell(
    a: EngineSpec,
    b: EngineSpec | None,
    cell: CellSpec,
    *,
    deadline: float | None = None,
    deps: CellDeps | None = None,
) -> dict:
    d = _resolve(deps or CellDeps())
    common = {"cell": asdict(cell)}
    with tempfile.TemporaryDirectory() as tmp:
        if cell.neighbour is None:
            with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT_MEASURED) as ea:
                engines = {"measured": _engine(a, ea), "neighbour": None}
                if not ea.healthy:
                    return {**common, "healthy": False, "engines": engines, "run": None,
                            "run_error": None, "neighbour_load": None}
                try:
                    run, run_error = _measure(d, ea, a, cell, os.path.join(tmp, "m"), deadline), None
                except Exception as e:  # noqa: BLE001 -- failures are data; the log must survive
                    run, run_error = None, f"{type(e).__name__}: {e}"
                ea.stop()
            return {**common, "healthy": True, "engines": engines, "run": run,
                    "run_error": run_error, "neighbour_load": None}
        if b is None:
            raise ValueError("a co-located cell needs the neighbour's engine spec")
        with (
            d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=PORT_MEASURED) as ea,
            d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=PORT_NEIGHBOUR) as eb,
        ):
            engines = {"measured": _engine(a, ea), "neighbour": _engine(b, eb)}
            if not (ea.healthy and eb.healthy):
                return {**common, "healthy": False, "engines": engines, "run": None,
                        "run_error": None, "neighbour_load": None}
            try:
                if cell.neighbour == 0:
                    run = _measure(d, ea, a, cell, os.path.join(tmp, "m"), deadline)
                    neighbour_load = {"level": 0}
                else:
                    run, neighbour_load = _loaded(d, ea, eb, a, b, cell, tmp, deadline)
                run_error = None
            except Exception as e:  # noqa: BLE001 -- failures are data; the logs must survive
                run, neighbour_load, run_error = None, None, f"{type(e).__name__}: {e}"
            eb.stop()
            ea.stop()
        engines = {"measured": _engine(a, ea), "neighbour": _engine(b, eb)}
    return {**common, "healthy": True, "engines": engines, "run": run, "run_error": run_error,
            "neighbour_load": neighbour_load}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_colocation.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/colocation.py tests/test_placement_measure_colocation.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/colocation.py tests/test_placement_measure_colocation.py
git commit -m "feat: one co-location cell, with the neighbour's load held and evidenced"
```

---

## Task 8: Pre-registration, step 1

**Files:**
- Create: `placement_measure/prereg.py`
- Create: `docs/experiment-a4.md`
- Test: `tests/test_placement_measure_prereg.py`

Amendment §3 fixes these values before reconnaissance, because recon is itself paid and its go/no-go must be settled before its answer is seen:
- the pinned checkpoints;
- T_max and the engine flags;
- the memory split;
- the go/no-go criterion;
- the swap rules.

They live as code in `prereg.py` and as prose in `docs/experiment-a4.md`, and a test fails if the two disagree.

**Artifact 5 depends on this document.** Its plan 2 reads artifact 4's primary model, revision, GPU class and vLLM base digest from it.

**Where the values came from.** The revisions are the commit each checkpoint's `main` pointed at on 2026-10-04, read from the Hugging Face model API. Running two engines at 0.45 each is vLLM's documented way to share a card: `CacheConfig.gpu_memory_utilization` is a per-instance limit, checked at the v0.27.1 tag.

**This commit must land before any reconnaissance job runs.** Its git timestamp is the evidence that the values came first.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_prereg.py`:

```python
"""The pre-registration document and the values jobs run on must agree."""

from pathlib import Path

from placement_measure import prereg

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a4.md").read_text()


def test_every_revision_is_stated():
    for model, revision in prereg.CANDIDATES.items():
        assert f"`{model}` | `{revision}`" in DOC, model


def test_the_primary_and_fallback_are_stated_with_their_revisions():
    for model in (prereg.PRIMARY, prereg.FALLBACK):
        assert f"`{model}` at revision `{prereg.CANDIDATES[model]}`" in DOC


def test_the_engine_flags_and_memory_split_are_stated():
    for text in (f"T_max = `{prereg.T_MAX}`", f"--max-model-len {prereg.MAX_MODEL_LEN}",
                 f"--max-num-seqs {prereg.MAX_NUM_SEQS}", f"`{prereg.SPLIT_GMU}`",
                 f"`{prereg.SOLO_GMU}`", f"`{prereg.SLEEP_GMU:.2f}`"):
        assert text in DOC, text


def test_the_go_no_go_threshold_is_stated():
    assert f"`{prereg.GO_NO_GO_TOKENS:,}`" in DOC
    assert prereg.GO_NO_GO_TOKENS == prereg.GO_NO_GO_MIN_REQUESTS * prereg.T_MAX


def test_the_platform_and_image_are_stated():
    for text in (prereg.GPU_TYPE, prereg.NETWORK_VOLUME, prereg.VLLM_VERSION,
                 prereg.VLLM_BASE_DIGEST, prereg.HF_HOME):
        assert text in DOC, text


def test_the_base_digest_is_the_one_the_image_builds_from():
    dockerfile = (Path(__file__).resolve().parents[1] / "worker" / "Dockerfile").read_text()
    assert f"ARG VLLM_DIGEST={prereg.VLLM_BASE_DIGEST}" in dockerfile


def test_the_release_rule_is_stated():
    assert f"`{prereg.RELEASE_TOLERANCE_MIB}` MiB" in DOC
    assert f"`{prereg.RELEASE_TIMEOUT_S}` s" in DOC
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_prereg.py -q`

Expected: FAIL with `ImportError: cannot import name 'prereg' from 'placement_measure'`

- [ ] **Step 3: Implement**

Create `placement_measure/prereg.py`:

```python
"""The first pre-registration step's values, as code (amendment §3).

`docs/experiment-a4.md` states them in prose and
`tests/test_placement_measure_prereg.py` fails if the two disagree, so the
document a reader checks and the values a job runs on cannot drift apart.
Committed before the reconnaissance run, because recon is itself paid and its
go/no-go must be fixed before its answer is seen. Everything chosen after
recon -- the request shape, the grid, the design -- is the second step's.

Revisions are the commit each checkpoint's `main` pointed at on 2026-10-04,
read from the Hugging Face model API. Artifact 5 reads the primary model, its
revision, the GPU class and the vLLM base digest from here (its plan 2).
"""

from placement_measure.engine import EngineSpec

__all__ = [
    "CANDIDATES", "FALLBACK", "GO_NO_GO_MIN_REQUESTS", "MAX_MODEL_LEN", "MAX_NUM_SEQS",
    "PRIMARY", "SLEEP_GMU", "SOLO_GMU", "SPLIT_GMU", "T_MAX", "engine",
]

# Checkpoint -> revision. All Qwen3ForCausalLM; the four 4B ones share every
# shape, and differ in rope_theta (1e6 for Qwen3-4B and -Base, 5e6 for the
# -2507 pair) and maximum length (amendment §3).
CANDIDATES = {
    "Qwen/Qwen3-4B": "1cfa9a7208912126459214e8b04321603b3df60c",
    "Qwen/Qwen3-4B-Base": "906bfd4b4dc7f14ee4320094d8b41684abff8539",
    "Qwen/Qwen3-4B-Instruct-2507": "cdbee75f17c01a7cc42f958dc650907174af0554",
    "Qwen/Qwen3-4B-Thinking-2507": "768f209d9ea81521153ed38c47d515654e938aea",
    "Qwen/Qwen3-1.7B": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
}
PRIMARY = "Qwen/Qwen3-4B"
FALLBACK = "Qwen/Qwen3-1.7B"

GPU_TYPE = "NVIDIA GeForce RTX 4090"
NETWORK_VOLUME = "9c7ut2slrd"
VLLM_VERSION = "0.27.1"
# worker/Dockerfile's ARG VLLM_DIGEST, which artifacts 1, 2, 4 and 5 share.
VLLM_BASE_DIGEST = "sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967"

# The per-request token ceiling. The request shape, fixed in step 2, is at or
# below it, so `--max-model-len` equals it.
T_MAX = 2048
MAX_MODEL_LEN = T_MAX
# Pinned rather than defaulted, as the service sweep pins it: vLLM logs a
# defaulted value only at DEBUG, so a run could not record its batch limit.
MAX_NUM_SEQS = 256
# Each of two co-resident engines. vLLM's limit is per instance
# (CacheConfig.gpu_memory_utilization, v0.27.1), so two at 0.45 is its
# documented way to share a card, leaving 10% for both CUDA contexts.
SPLIT_GMU = 0.45
# A lone engine: artifact 1's measured budget (21.64 GiB at 0.92, fixtures/README.md).
SOLO_GMU = 0.92
# The sleep probe's two engines start one while the other sleeps; each at 0.80
# leaves room for the sleeping one's residue, whose size is what it measures.
SLEEP_GMU = 0.80

# Go/no-go: both engines healthy at SPLIT_GMU, and each one's logged KV
# capacity at least this many T_MAX-token requests.
GO_NO_GO_MIN_REQUESTS = 8
GO_NO_GO_TOKENS = GO_NO_GO_MIN_REQUESTS * T_MAX

# A swap's memory is released when the card reads at most its idle level plus
# this; the wait gives up after RELEASE_TIMEOUT_S and records that it did.
RELEASE_TOLERANCE_MIB = 512
RELEASE_TIMEOUT_S = 120
HF_HOME = "/runpod-volume/hf"  # worker/Dockerfile's ENV HF_HOME
JOB_BUDGET_S = 1800  # the endpoint's executionTimeout


def engine(model: str, gmu: float, extra_args=()) -> EngineSpec:
    """An engine on a pre-registered checkpoint, every other flag pinned."""
    return EngineSpec(model, CANDIDATES[model], gmu, MAX_MODEL_LEN, MAX_NUM_SEQS, tuple(extra_args))
```

- [ ] **Step 4: Write `docs/experiment-a4.md`**

Create `docs/experiment-a4.md`:

````markdown
# Artifact 4 — Pre-registration

Committed in two dated steps, because reconnaissance is itself a paid run and
the request shape depends on what it reports (scope amendment §3). The git
timestamp on each step's commit is the evidence that its values were fixed before the
data they govern existed. `placement_measure/prereg.py` holds step 1's values
as code, and `tests/test_placement_measure_prereg.py` fails if it and this
document disagree.

## Step 1 — fixed before reconnaissance

### Configuration

- **GPU:** `NVIDIA GeForce RTX 4090`, 24 GB, the same class as artifacts 1 and 2.
  Network volume `9c7ut2slrd`; weights are read from it (`HF_HOME=/runpod-volume/hf`).
- **Engine:** vLLM `0.27.1`, base image
  `sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967`
  (`worker/Dockerfile`'s `ARG VLLM_DIGEST`). The built image's digest is
  recorded in the reconnaissance record, since it is built after this step.
- **Primary model:** `Qwen/Qwen3-4B` at revision `1cfa9a7208912126459214e8b04321603b3df60c`.
  It is also artifact 5's base model (scope amendment, decision 1).
- **Fallback model:** `Qwen/Qwen3-1.7B` at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.
- **Candidates for the validation set**, each pinned to the commit its `main`
  pointed at on 2026-10-04:

| Checkpoint | Revision |
|---|---|
| `Qwen/Qwen3-4B` | `1cfa9a7208912126459214e8b04321603b3df60c` |
| `Qwen/Qwen3-4B-Base` | `906bfd4b4dc7f14ee4320094d8b41684abff8539` |
| `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` |
| `Qwen/Qwen3-4B-Thinking-2507` | `768f209d9ea81521153ed38c47d515654e938aea` |
| `Qwen/Qwen3-1.7B` | `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` |

- **Per-request token ceiling:** T_max = `2048`. Every engine runs with
  `--max-model-len 2048`, `--max-num-seqs 256` and `--no-enable-prefix-caching`.
- **Memory:** `--gpu-memory-utilization 0.45` for each of two co-resident
  engines; `0.92` for a lone engine (artifact 1's measured budget); `0.80` for
  each engine in the sleep-mode probe.

### The go/no-go

The model class passes if, with two engines co-resident at `0.45` each, both
reach `/health` and each engine's logged KV capacity is at least `16,384`
tokens (8 × T_max).

- If the primary pair passes, the model class is Qwen3-4B.
- If it fails and the fallback pair passes, the model class is Qwen3-1.7B, and
  the change is recorded in the reconnaissance record.
- If both fail, the design changes rather than the measurement: stop, and
  return to the scope amendment (§3).

`placement_measure/recon_report.py` applies this criterion to the capture; it
does not choose it.

### Swap measurement conditions

- Engines start with `HF_HUB_OFFLINE=1`, so a missing checkpoint fails the
  engine instead of being downloaded during a timed swap.
- A swap's duration is teardown (the engine process exiting) plus memory
  release plus the successor's bring-up to `/health`.
- Memory is released when `memory.used` reads at most the idle level plus
  `512` MiB. The wait gives up after `120` s and records that it did.

### What step 2 fixes, after reconnaissance

The request shape (input and output length, at or below T_max), the
validation checkpoint set, N, the Zipf grid, both locality regimes'
parameters, the offered load, the SLO, the hot-model threshold, the sizing and
pairing rules, the warm-up window, the repetition count, the run-length pilot
rule, the interference grid, the swap campaign's pairs and cache states, and
the validation tolerance construction (scope amendment §12). It also records
the owner's decision on the bursty-regime sizing gap (scope amendment §14).
````

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_prereg.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/prereg.py tests/test_placement_measure_prereg.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement_measure/prereg.py docs/experiment-a4.md tests/test_placement_measure_prereg.py
git commit -m "prereg: artifact 4 step 1, fixed before reconnaissance"
```

---

## Task 9: The reconnaissance probes

**Files:**
- Create: `placement_measure/recon.py`
- Test: `tests/test_placement_measure_recon.py`

This builds amendment §1e item 6. There is one probe per question, and each runs as its own job, so a hang loses only its own answer:
- **`stage`**, which puts every checkpoint on the volume;
- **`coresidency`**, the go/no-go;
- **`swaps`**, covering compile reuse, eviction and release;
- **`early_start`**;
- **`sleep`**, using the `/sleep`, `/wake_up` and `/is_sleeping` routes in development mode, checked at the v0.27.1 tag;
- **`help`**.

**`healthy` means the probe finished.** An engine that failed to start is an answer, not a failed job.

**Two details from writing this:**
- **The swap budget guard learns as it goes.** A fixed 400 s floor admitted a swap that overran, so the guard now rises to 1.25 times the longest swap already run in the job.
- **The weight-update endpoints are out.** vLLM's development endpoints need a training peer to push weights, so they aren't a serving swap. They are recorded as considered and excluded.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_recon.py`:

```python
import subprocess

import pytest
from a4_fakes import Clock, FakeEngines, memory_script

from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.swap import SwapDeps

A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


class Resp:
    def __init__(self, status=200, text="{}"):
        self.status_code, self.text = status, text


def _deps(clock, engines, readings=(500, 9000, 500), posted=None, snapshot=None, run_command=None):
    run = memory_script(list(readings))
    posted = posted if posted is not None else []

    def post(url, **kw):
        posted.append(url)
        return Resp()

    return ReconDeps(
        served=engines.served,
        read_memory=lambda: read_memory(run=run),
        swap_deps=SwapDeps(
            served=engines.served, read_memory=lambda: read_memory(run=run),
            wait_for_release=lambda target, timeout_s: wait_for_release(
                target, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
            make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock),
        snapshot_download=snapshot or (lambda repo_id, revision: f"/vol/{repo_id}@{revision}"),
        post=post, get=lambda url, **kw: Resp(text='{"is_sleeping": true}'),
        run_command=run_command or (lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")),
        clock=clock,
    )


def test_an_unknown_probe_is_refused():
    with pytest.raises(ValueError, match="unknown probe"):
        run_probe({"probe": "guess", "job_budget_s": 1800})


def test_stage_records_every_checkpoint_and_whether_all_landed():
    clock = Clock()

    def snapshot(repo_id, revision):
        if repo_id.endswith("Base"):
            raise OSError("401")
        return "/vol/x"

    out = run_probe({"probe": "stage", "job_budget_s": 1800,
                     "models": [{"model": A.model, "revision": "ra"},
                                {"model": B.model, "revision": "rb"}]},
                    _deps(clock, FakeEngines(clock), snapshot=snapshot))
    staged = out["result"]["staged"]
    assert out["healthy"] and [s["error"] is None for s in staged] == [True, False]
    assert not out["result"]["complete"]


def test_coresidency_reports_both_engines_kv_and_memory():
    clock = Clock()
    engines = FakeEngines(clock)
    out = run_probe({"probe": "coresidency", "job_budget_s": 1800,
                     "a": A.to_dict(), "b": B.to_dict()}, _deps(clock, engines))
    r = out["result"]
    assert r["engines"]["a"]["facts"]["kv_capacity_tokens"] == 35792
    assert r["engines"]["b"]["healthy"]
    assert [s.base_url[-4:] for s in engines.started] == ["8000", "8001"]
    assert r["both_memory"]["used_mib"] == 9000


def test_coresidency_with_a_failed_engine_is_an_answer_not_a_failed_job():
    clock = Clock()
    out = run_probe({"probe": "coresidency", "job_budget_s": 1800, "a": A.to_dict(),
                     "b": B.to_dict()}, _deps(clock, FakeEngines(clock, healthy={B.model: False})))
    assert out["healthy"] and not out["result"]["engines"]["b"]["healthy"]
    assert out["result"]["smoke"]["b"] is None


def test_swaps_stop_starting_new_swaps_when_the_budget_runs_low():
    clock = Clock()
    engines = FakeEngines(clock, startup_s={A.model: 300.0, B.model: 300.0})
    swap = {"a": A.to_dict(), "b": B.to_dict(), "cold": False}
    out = run_probe({"probe": "swaps", "job_budget_s": 1200, "hf_home": "/vol/hf",
                     "release_tolerance_mib": 256, "release_timeout_s": 60,
                     "swaps": [swap, swap, swap]},
                    _deps(clock, engines, readings=(500, 500)))
    r = out["result"]
    assert len(r["swaps"]) == 1 and len(r["skipped_for_budget"]) == 2


def test_early_start_starts_the_successor_without_waiting_for_release():
    clock = Clock()
    engines = FakeEngines(clock)
    out = run_probe({"probe": "early_start", "job_budget_s": 1800, "a": A.to_dict(),
                     "b": B.to_dict()}, _deps(clock, engines, readings=(9000,)))
    assert out["result"]["memory_when_b_started"]["used_mib"] == 9000
    assert out["result"]["b"]["healthy"]


def test_sleep_runs_the_sleep_wake_sequence_in_dev_mode():
    clock = Clock()
    engines = FakeEngines(clock)
    posted = []
    sleepy = EngineSpec(A.model, "ra", 0.8, 2048, 256, extra_args=("--enable-sleep-mode",))
    out = run_probe({"probe": "sleep", "job_budget_s": 1800, "a": sleepy.to_dict(),
                     "b": EngineSpec(B.model, "rb", 0.8, 2048, 256,
                                     extra_args=("--enable-sleep-mode",)).to_dict()},
                    _deps(clock, engines, posted=posted))
    r = out["result"]
    assert [u.rsplit("/", 1)[1] for u in posted] == [
        "sleep?level=1", "sleep?level=1", "wake_up", "completions"]
    assert r["sleep_a"]["status"] == 200 and r["is_sleeping_a"]["body"] == '{"is_sleeping": true}'
    assert "--enable-sleep-mode" in engines.started[0].cmd


def test_help_lists_the_flags_the_image_does_not_know():
    clock = Clock()

    def run_command(cmd, **kw):
        text = "--max-concurrency --ignore-eos" if cmd[1] == "bench" else "--revision --max-num-seqs"
        return subprocess.CompletedProcess(cmd, 0, text, "")

    out = run_probe({"probe": "help", "job_budget_s": 1800},
                    _deps(clock, FakeEngines(clock), run_command=run_command))
    assert "--enable-sleep-mode" in out["result"]["serve"]["missing"]
    assert "--random-input-len" in out["result"]["bench"]["missing"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.recon'`

- [ ] **Step 3: Implement**

Create `placement_measure/recon.py`:

```python
"""Artifact 4's reconnaissance probes. Capture-only: nothing here is a result.

Each probe answers one question the amendment leaves to reconnaissance, and
returns raw readings; `placement_measure.recon_report` turns the saved outputs
into answers. One probe per job, so a probe that hangs or dies loses only its
own question.

| probe         | question (amendment section)                                        |
|---------------|---------------------------------------------------------------------|
| `stage`       | put every pinned checkpoint on the network volume before any timing |
| `coresidency` | do two engines fit at the split, with how much KV each (§3 go/no-go)|
| `swaps`       | compile reuse per target, page-cache eviction, memory release (§3, §5)|
| `early_start` | does an engine start while the previous one's memory is held (§5)   |
| `sleep`       | does sleep mode work, and what does a sleep-based swap cost (§6)    |
| `help`        | does the pinned image accept every flag artifact 4 passes           |

Considered and not probed: vLLM 0.27.1's development weight-update endpoints
(`/update_weights` and the weight-transfer engine under
vllm/entrypoints/serve/dev/rlhf). They load weights pushed by a training peer
over a transfer engine, not a checkpoint from disk, so they are not a serving
swap.

`healthy` in every probe's output means the probe ran to its end, which is the
field `RunPodSubmitter` treats as success. An engine that failed to start is
an answer here -- for `coresidency` it is the go/no-go's "no" -- not a failed
job, and the per-engine `healthy` fields carry it.
"""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV, SwapDeps, measure_swap

__all__ = ["PROBES", "ReconDeps", "run_probe"]

TEARDOWN_RESERVE_S = 120.0
# A swap needs two engine starts and a release wait; one is not started with
# less than this left, because a job the platform kills returns nothing. Once a
# swap has run in this job, the bar rises to SWAP_BUDGET_MARGIN times the
# longest one so far: a fixed floor alone admitted a swap that overran when the
# engines started slower than the floor assumed.
MIN_SWAP_BUDGET_S = 400.0
SWAP_BUDGET_MARGIN = 1.25
SMOKE = {"prompt": "Hello", "max_tokens": 4}
DEV_ENV = {"VLLM_SERVER_DEV_MODE": "1"}
SERVE_FLAGS = ("--enable-sleep-mode", "--gpu-memory-utilization", "--max-num-seqs",
               "--max-model-len", "--no-enable-prefix-caching", "--revision")
BENCH_FLAGS = ("--random-input-len", "--random-output-len", "--random-range-ratio",
               "--random-prefix-len", "--max-concurrency", "--ignore-eos")


@dataclass
class ReconDeps:
    served: Callable | None = None
    read_memory: Callable | None = None
    swap_deps: SwapDeps | None = None
    snapshot_download: Callable | None = None
    post: Callable = requests.post
    get: Callable = requests.get
    run_command: Callable = subprocess.run
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: ReconDeps) -> ReconDeps:
    if d.served is None:
        from harness.serve import served

        d.served = served
    if d.read_memory is None:
        from placement_measure.gpu_memory import read_memory

        d.read_memory = read_memory
    if d.swap_deps is None:
        d.swap_deps = SwapDeps(served=d.served, read_memory=d.read_memory, clock=d.clock)
    if d.snapshot_download is None:
        from huggingface_hub import snapshot_download

        d.snapshot_download = snapshot_download
    return d


def _timed(d: ReconDeps, fn: Callable) -> dict:
    t0 = d.clock()
    try:
        r = fn()
        body = r.text[:500]
        return {"status": r.status_code, "seconds": d.clock() - t0, "body": body, "error": None}
    except Exception as e:  # noqa: BLE001 -- an endpoint that is absent is the answer
        return {"status": None, "seconds": d.clock() - t0, "body": None, "error": repr(e)[:300]}


def _smoke(d: ReconDeps, server, model: str) -> dict:
    return _timed(d, lambda: d.post(f"{server.base_url}/v1/completions",
                                    json={"model": model, **SMOKE}, timeout=60))


def _engine(spec: EngineSpec, server) -> dict:
    lines = list(server.log_lines)
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "served_cmd": list(server.cmd),
            "facts": engine_facts(lines), **log_tail(lines)}


def probe_stage(p: dict, d: ReconDeps, deadline: float) -> dict:
    staged = []
    for m in p["models"]:
        t0 = d.clock()
        try:
            path = d.snapshot_download(repo_id=m["model"], revision=m["revision"])
            staged.append({**m, "path": str(path), "seconds": d.clock() - t0, "error": None})
        except Exception as e:  # noqa: BLE001 -- one missing checkpoint must not hide the rest
            staged.append({**m, "path": None, "seconds": d.clock() - t0, "error": repr(e)[:300]})
        if d.clock() >= deadline:
            break
    return {"staged": staged, "complete": len(staged) == len(p["models"])
            and all(s["error"] is None for s in staged)}


def probe_coresidency(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    idle = d.read_memory()
    with (
        d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=8000) as ea,
        d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=8001) as eb,
    ):
        both = d.read_memory()
        smoke = {
            "a": _smoke(d, ea, a.model) if ea.healthy else None,
            "b": _smoke(d, eb, b.model) if eb.healthy else None,
        }
        eb.stop()
        ea.stop()
    return {"idle_memory": idle, "both_memory": both, "smoke": smoke,
            "engines": {"a": _engine(a, ea), "b": _engine(b, eb)}}


def probe_swaps(p: dict, d: ReconDeps, deadline: float) -> dict:
    results, skipped = [], []
    longest = 0.0
    for s in p["swaps"]:
        if deadline - d.clock() < max(MIN_SWAP_BUDGET_S, SWAP_BUDGET_MARGIN * longest):
            skipped.append(s)
            continue
        started = d.clock()
        results.append(measure_swap(
            EngineSpec.from_dict(s["a"]), EngineSpec.from_dict(s["b"]), cold=bool(s["cold"]),
            hf_home=p["hf_home"], release_tolerance_mib=p["release_tolerance_mib"],
            release_timeout_s=p["release_timeout_s"], deps=d.swap_deps,
        ))
        longest = max(longest, d.clock() - started)
    return {"swaps": results, "skipped_for_budget": skipped}


def probe_early_start(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    with d.served(a.model, args=a.serve_args(), env=dict(ENGINE_ENV), port=8000) as ea:
        first = _engine(a, ea)
        teardown_s = ea.stop()
    at_start = d.read_memory()
    with d.served(b.model, args=b.serve_args(), env=dict(ENGINE_ENV), port=8000) as eb:
        second = _engine(b, eb)
        eb.stop()
    return {"a": first, "teardown_s": teardown_s, "memory_when_b_started": at_start, "b": second}


def probe_sleep(p: dict, d: ReconDeps, deadline: float) -> dict:
    a, b = EngineSpec.from_dict(p["a"]), EngineSpec.from_dict(p["b"])
    env = {**ENGINE_ENV, **DEV_ENV}
    steps: dict = {}
    with d.served(a.model, args=a.serve_args(), env=env, port=8000) as ea:
        steps["a"] = _engine(a, ea)
        if ea.healthy:
            steps["memory_a_awake"] = d.read_memory()
            steps["sleep_a"] = _timed(d, lambda: d.post(f"{ea.base_url}/sleep?level=1", timeout=300))
            steps["is_sleeping_a"] = _timed(d, lambda: d.get(f"{ea.base_url}/is_sleeping", timeout=10))
            steps["memory_a_asleep"] = d.read_memory()
            with d.served(b.model, args=b.serve_args(), env=env, port=8001) as eb:
                steps["b"] = _engine(b, eb)
                if eb.healthy:
                    steps["memory_b_awake_a_asleep"] = d.read_memory()
                    steps["sleep_b"] = _timed(d, lambda: d.post(f"{eb.base_url}/sleep?level=1", timeout=300))
                    steps["wake_a"] = _timed(d, lambda: d.post(f"{ea.base_url}/wake_up", timeout=300))
                    steps["smoke_a_after_wake"] = _smoke(d, ea, a.model)
                    steps["memory_a_awake_b_asleep"] = d.read_memory()
                eb.stop()
            ea.stop()
    return steps


def probe_help(p: dict, d: ReconDeps, deadline: float) -> dict:
    out = {}
    for name, cmd, flags in (
        ("serve", ["vllm", "serve", "--help=all"], SERVE_FLAGS),
        ("bench", ["vllm", "bench", "serve", "--help=all"], BENCH_FLAGS),
    ):
        try:
            proc = d.run_command(cmd, capture_output=True, text=True, check=False, timeout=60)
            text = proc.stdout or ""
            out[name] = {"returncode": proc.returncode,
                         "missing": [f for f in flags if f not in text], "error": None}
        except Exception as e:  # noqa: BLE001 -- a missing tool is the answer
            out[name] = {"returncode": None, "missing": list(flags), "error": repr(e)[:300]}
    return out


PROBES = {
    "stage": probe_stage,
    "coresidency": probe_coresidency,
    "swaps": probe_swaps,
    "early_start": probe_early_start,
    "sleep": probe_sleep,
    "help": probe_help,
}


def run_probe(payload: dict, deps: ReconDeps | None = None) -> dict:
    name = payload["probe"]
    if name not in PROBES:
        raise ValueError(f"unknown probe {name!r}; known: {sorted(PROBES)}")
    d = _resolve(deps or ReconDeps())
    t0 = d.clock()
    deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
    result = PROBES[name](payload, d, deadline)
    return {"healthy": True, "probe": name, "label": payload.get("label"),
            "elapsed_s": d.clock() - t0, "result": result}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/recon.py tests/test_placement_measure_recon.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/recon.py tests/test_placement_measure_recon.py
git commit -m "feat: artifact 4's reconnaissance probes, capture-only"
```

---

## Task 10: The measurement job, the two handlers, and the image

**Files:**
- Create: `placement_measure/jobs.py`
- Create: `worker/a4_recon_handler.py`
- Create: `worker/a4_measure_handler.py`
- Modify: `worker/Dockerfile`
- Modify: `.github/workflows/build-worker.yml`
- Modify: `tests/test_harness_boundary.py`
- Test: `tests/test_placement_measure_jobs.py`

The handlers are thin, as the sweep's is. All the logic lives in `placement_measure`, where tests reach it without the runpod SDK.

The image gets the package and both handler files. The repo's own tests demand three things here:
- **A COPY line per worker module** (`test_dockerfile_copies_every_worker_module`).
- **A COPY for every first-party package the image imports.** This needs `placement_measure` added to `FIRST_PARTY`.
- **A CI trigger for every copied package.**

The job tests send payloads through `PayloadStubSubmitter`, which round-trips both ways through JSON, so an output that won't serialise fails here and not on a paid job.

**Coordination.** Artifact 5's plan 2 edits the same `FIRST_PARTY` line, Dockerfile and workflow to add `multilora`. Both edits are additive. Whichever lands second keeps both.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_jobs.py`:

```python
"""The measurement job, end to end through the harness's JSON-round-tripping
stub submitter, and the two handlers."""

import sys
from pathlib import Path

import pytest
from a4_fakes import Clock, FakeEngines, memory_script
from test_placement_measure_colocation import _cell
from test_placement_measure_colocation import _deps as cell_deps

from harness.submit import PayloadStubSubmitter
from placement_measure.engine import EngineSpec
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.jobs import measure_job
from placement_measure.swap import SwapDeps

ROOT = Path(__file__).resolve().parents[1]
A = EngineSpec("Qwen/Qwen3-4B", "ra", 0.45, 2048, 256)
B = EngineSpec("Qwen/Qwen3-4B-Base", "rb", 0.45, 2048, 256)


def _swap_deps(clock, healthy=None):
    run = memory_script([500, 9000, 500])
    return SwapDeps(
        served=FakeEngines(clock, healthy=healthy).served, read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda t, timeout_s: wait_for_release(
            t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock)


def _swap_payload(**over):
    return {"kind": "swap", "run_id": "r1", "a": A.to_dict(), "b": B.to_dict(), "cold": True,
            "hf_home": "/vol/hf", "release_tolerance_mib": 256, "release_timeout_s": 60,
            "job_budget_s": 1800, **over}


def _host():
    return {"host_id": "h1", "runpod_pod_id": None}


def test_a_swap_job_survives_the_json_round_trip_and_reads_as_success():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(p, swap_deps=_swap_deps(clock), host=_host,
                                                     clock=clock))
    outcome = sub.submit_payload(_swap_payload())
    assert outcome.error is None
    assert outcome.payload["run_id"] == "r1" and outcome.payload["swap_s"] > 0


def test_a_failed_swap_reaches_the_submitter_as_a_failure_with_diagnostics():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(
        p, swap_deps=_swap_deps(clock, healthy={B.model: False}), host=_host, clock=clock))
    outcome = sub.submit_payload(_swap_payload())
    assert outcome.payload is None and outcome.diagnostics["b"]["log_tail"]


def test_a_cell_job_survives_the_json_round_trip():
    clock = Clock()
    deps, _, _ = cell_deps(clock)
    payload = {"kind": "cell", "run_id": "r2", "a": A.to_dict(), "b": B.to_dict(),
               "cell": vars(_cell(8)), "job_budget_s": 1800}
    sub = PayloadStubSubmitter(lambda p: measure_job(p, cell_deps=deps, host=_host, clock=clock))
    outcome = sub.submit_payload(payload)
    assert outcome.error is None and outcome.payload["neighbour_load"]["level"] == 8


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown kind"):
        measure_job({"kind": "guess", "run_id": "x"})


def test_the_handlers_import_without_the_runpod_sdk():
    sys.path.insert(0, str(ROOT / "worker"))
    import a4_measure_handler
    import a4_recon_handler

    assert callable(a4_measure_handler.handler) and callable(a4_recon_handler.handler)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_jobs.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.jobs'`

- [ ] **Step 3: Implement**

Create `placement_measure/jobs.py`:

```python
"""One measurement job: a swap, or a co-location cell, chosen by `kind`.

The worker handler (`worker/a4_measure_handler.py`) is a thin shell around
`measure_job`, so everything here runs in tests with injected effects. Every
output carries the payload's `run_id` and the host, because the local record
must name the run it came from and the host a run landed on, as artifact 1's
and the service sweep's records do.
"""

import os
import socket
import time
from collections.abc import Callable

from placement_measure.colocation import CellDeps, CellSpec, measure_cell
from placement_measure.engine import EngineSpec
from placement_measure.swap import SwapDeps, measure_swap

__all__ = ["KINDS", "measure_job"]

KINDS = ("swap", "cell")
TEARDOWN_RESERVE_S = 120.0


def host_info() -> dict:
    return {"host_id": socket.gethostname(), "runpod_pod_id": os.environ.get("RUNPOD_POD_ID")}


def measure_job(
    payload: dict,
    *,
    swap_deps: SwapDeps | None = None,
    cell_deps: CellDeps | None = None,
    host: Callable[[], dict] = host_info,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    kind = payload["kind"]
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; known: {KINDS}")
    # Required and never defaulted: a run that cannot say which run it was is
    # a mislabelled point, not a slightly worse one.
    common = {"run_id": payload["run_id"], "kind": kind, "host": host()}
    t0 = clock()
    if kind == "swap":
        out = measure_swap(
            EngineSpec.from_dict(payload["a"]), EngineSpec.from_dict(payload["b"]),
            cold=bool(payload["cold"]), hf_home=payload["hf_home"],
            release_tolerance_mib=payload["release_tolerance_mib"],
            release_timeout_s=payload["release_timeout_s"], deps=swap_deps,
        )
    else:
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
        b = payload.get("b")
        out = measure_cell(
            EngineSpec.from_dict(payload["a"]), None if b is None else EngineSpec.from_dict(b),
            CellSpec(**payload["cell"]), deadline=deadline, deps=cell_deps,
        )
    return {**out, **common, "elapsed_s": clock() - t0}
```

- [ ] **Step 4: Add `worker/a4_recon_handler.py`**

Create `worker/a4_recon_handler.py`:

```python
"""Artifact 4's reconnaissance handler. Captures; publishes nothing.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/a4_recon_handler.py`. One probe per job; see
placement_measure/recon.py for what each answers.
"""

from placement_measure.recon import run_probe


def handler(job):
    return run_probe(job.get("input") or {})


def main():
    # Imported here so tests can import the handler without the runpod SDK.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add `worker/a4_measure_handler.py`**

Create `worker/a4_measure_handler.py`:

```python
"""Artifact 4's measurement handler: one swap or one co-location cell per job.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/a4_measure_handler.py`. See placement_measure/jobs.py.
"""

from placement_measure.jobs import measure_job


def handler(job):
    return measure_job(job.get("input") or {})


def main():
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Wire the package and handlers into the image**

In `worker/Dockerfile`, directly after the line

```dockerfile
COPY worker/sweep_handler.py /opt/sweep_handler.py
```

add:

```dockerfile
# Artifact 4's worker side: its package (imports only harness/, never
# coldstart/ or autoscale/) and its two handlers, each selected by
# dockerStartCmd like the sweep's.
COPY placement_measure /opt/placement_measure
COPY worker/a4_recon_handler.py /opt/a4_recon_handler.py
COPY worker/a4_measure_handler.py /opt/a4_measure_handler.py
```

In `.github/workflows/build-worker.yml`, directly below `- "harness/**"` in the `paths` filter, add:

```yaml
      # Artifact 4's worker package, vendored for worker/a4_*_handler.py --
      # same reasoning as the two above.
      - "placement_measure/**"
```

In `tests/test_harness_boundary.py`, change the constant to:

```python
FIRST_PARTY = {"coldstart", "harness", "placement_measure", "worker", "recon"}
```

(If artifact 5's plan 2 has already added `"multilora"`, keep it.)

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_jobs.py tests/test_placement_measure_boundary.py tests/test_harness_boundary.py -q`

Expected: PASS.

- [ ] **Step 8: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/jobs.py worker/a4_recon_handler.py worker/a4_measure_handler.py tests/test_placement_measure_jobs.py tests/test_harness_boundary.py`

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add placement_measure/jobs.py worker/a4_recon_handler.py worker/a4_measure_handler.py worker/Dockerfile .github/workflows/build-worker.yml tests/test_harness_boundary.py tests/test_placement_measure_jobs.py
git commit -m "feat: artifact 4's handlers in the worker image"
```

---

## Task 11: The reconnaissance job list and the pin set

**Files:**
- Create: `placement_measure/pins.py`
- Create: `placement_measure/recon_plan.py`
- Test: `tests/test_placement_measure_recon_plan.py`

One list of every paid reconnaissance job, built from the pre-registration, so the capture script, its tests and a reader all see the same jobs. `--list` prints them for free.

The swap order makes compile reuse readable from `S4b`:
- **Same-RoPE pairs:** Qwen3-4B and -Base share `rope_theta`, and so do the two -2507 checkpoints.
- **Crossings:** the other two swaps cross between those two groups, which tests whether the difference matters (amendment §3).
- **Cache state:** one pair runs both warm and cold (§5).

The pin set copies the service sweep's: GPU, volume, execution timeout and template.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_recon_plan.py`:

```python
import json

import pytest

from placement_measure.pins import pins
from placement_measure.prereg import CANDIDATES, SPLIT_GMU
from placement_measure.recon_plan import recon_jobs


def test_every_recon_job_is_labelled_once_and_pins_every_revision():
    jobs = recon_jobs()
    labels = [j["label"] for j in jobs]
    assert len(labels) == len(set(labels))
    specs = [s for j in jobs for k in ("a", "b") if k in j for s in [j[k]]]
    specs += [s[k] for j in jobs for s in j.get("swaps", []) for k in ("a", "b")]
    assert specs and all(s["revision"] == CANDIDATES[s["model"]] for s in specs)
    json.dumps(jobs)  # a job that does not serialise fails here, not on a paid run


def test_the_coresidency_jobs_use_the_split():
    jobs = {j["label"]: j for j in recon_jobs()}
    for label in ("coresidency-primary", "coresidency-fallback"):
        assert jobs[label]["a"]["gpu_memory_utilization"] == SPLIT_GMU
        assert jobs[label]["b"]["gpu_memory_utilization"] == SPLIT_GMU


def test_the_stage_job_stages_every_candidate():
    stage = next(j for j in recon_jobs() if j["probe"] == "stage")
    assert {m["model"] for m in stage["models"]} == set(CANDIDATES)


def test_pins_require_the_template():
    assert pins("tpl")["templateId"] == "tpl"
    with pytest.raises(ValueError):
        pins("")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon_plan.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.pins'`

- [ ] **Step 3: Implement**

Create `placement_measure/pins.py`:

```python
"""Artifact 4's endpoint pin set, checked before any job is submitted.

Same GPU class and network volume as artifacts 1 and 2, so the weights staged
on the volume are the ones every engine reads. The template is artifact 4's
own (its dockerStartCmd selects one of the two handlers) and is passed in,
because it is provisioned when the paid run is prepared. A pin set is one
experiment's boundary, so it lives with the experiment, not in `harness/`.
"""

from placement_measure.prereg import GPU_TYPE, JOB_BUDGET_S, NETWORK_VOLUME

__all__ = ["PINNED_BASE", "pins"]

PINNED_BASE = {
    "gpuTypeIds": [GPU_TYPE],
    "networkVolumeId": NETWORK_VOLUME,
    "executionTimeoutMs": JOB_BUDGET_S * 1000,
}


def pins(template_id: str) -> dict:
    if not template_id:
        raise ValueError(
            "a template id is required; without it the preflight would accept an "
            "endpoint running any image and any start command"
        )
    return {**PINNED_BASE, "templateId": template_id}
```

- [ ] **Step 4: Add `placement_measure/recon_plan.py`**

Create `placement_measure/recon_plan.py`:

```python
"""The reconnaissance jobs, built from the pre-registered values.

One list, so the capture script and its tests agree on what is submitted, and
a reader can see every paid job before any is run (`--list`).

The swap order is chosen so each answer is readable from one job's S4b
readings: the first engine of a fresh worker compiles; after it, a successor
whose S4b is a cache hit shares the compile cache. Qwen3-4B and -Base share
`rope_theta`; the -2507 pair shares a different one. The two crossings
(-Base to -Instruct-2507, -Thinking-2507 back to Qwen3-4B) test whether the
difference matters (amendment §3). One pair runs warm and cold, to see whether
eviction changes the swap (§5).
"""

from placement_measure.prereg import (
    CANDIDATES,
    FALLBACK,
    HF_HOME,
    JOB_BUDGET_S,
    PRIMARY,
    RELEASE_TIMEOUT_S,
    RELEASE_TOLERANCE_MIB,
    SLEEP_GMU,
    SOLO_GMU,
    SPLIT_GMU,
    engine,
)

__all__ = ["recon_jobs"]

BASE = "Qwen/Qwen3-4B-Base"
INSTRUCT = "Qwen/Qwen3-4B-Instruct-2507"
THINKING = "Qwen/Qwen3-4B-Thinking-2507"


def _swap(a: str, b: str, cold: bool) -> dict:
    return {"a": engine(a, SOLO_GMU).to_dict(), "b": engine(b, SOLO_GMU).to_dict(), "cold": cold}


def recon_jobs() -> list[dict]:
    common = {"job_budget_s": JOB_BUDGET_S}
    swap_common = {**common, "probe": "swaps", "hf_home": HF_HOME,
                   "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                   "release_timeout_s": RELEASE_TIMEOUT_S}
    sleepy = ("--enable-sleep-mode",)
    return [
        {**common, "label": "help", "probe": "help"},
        {**common, "label": "stage", "probe": "stage",
         "models": [{"model": m, "revision": r} for m, r in CANDIDATES.items()]},
        {**common, "label": "coresidency-primary", "probe": "coresidency",
         "a": engine(PRIMARY, SPLIT_GMU).to_dict(), "b": engine(BASE, SPLIT_GMU).to_dict()},
        {**common, "label": "coresidency-fallback", "probe": "coresidency",
         "a": engine(FALLBACK, SPLIT_GMU).to_dict(), "b": engine(FALLBACK, SPLIT_GMU).to_dict()},
        {**swap_common, "label": "swaps-compile",
         "swaps": [_swap(PRIMARY, BASE, False), _swap(BASE, INSTRUCT, False),
                   _swap(INSTRUCT, THINKING, False), _swap(THINKING, PRIMARY, False)]},
        {**swap_common, "label": "swaps-cache",
         "swaps": [_swap(PRIMARY, BASE, False), _swap(BASE, PRIMARY, True),
                   _swap(PRIMARY, BASE, True), _swap(BASE, PRIMARY, False)]},
        {**common, "label": "early-start", "probe": "early_start",
         "a": engine(PRIMARY, SOLO_GMU).to_dict(), "b": engine(BASE, SOLO_GMU).to_dict()},
        {**common, "label": "sleep", "probe": "sleep",
         "a": engine(PRIMARY, SLEEP_GMU, sleepy).to_dict(),
         "b": engine(BASE, SLEEP_GMU, sleepy).to_dict()},
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon_plan.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/pins.py placement_measure/recon_plan.py tests/test_placement_measure_recon_plan.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement_measure/pins.py placement_measure/recon_plan.py tests/test_placement_measure_recon_plan.py
git commit -m "feat: the reconnaissance jobs and artifact 4's pin set"
```

---

## Task 12: The stored record and the campaign designs

**Files:**
- Create: `placement_measure/records.py`
- Create: `placement_measure/campaigns.py`
- Test: `tests/test_placement_measure_campaigns.py`

This builds amendment §1e item 8. There is one record type for both kinds of job, and it keeps the worker's output whole. Typing out fields now would decide which readings matter before any paid run, and the raw samples are what a reader checks a reduction against.

A record is `ok` only if the job produced its measurement, either a swap time or a run. Anything else is stored as `failed`, so the failure-rate table counts it.

The two designs schedule through `harness.scheduler`, which interleaves conditions within each block. They choose no grid, pair or request shape; the second pre-registration step supplies those. The neighbour's request count is set to outlast the measured run four times over, and Task 7 flags it if it still runs out.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_campaigns.py`:

```python
import pytest

from harness.scheduler import ScheduledRun
from harness.submit import SubmitOutcome
from placement_measure.campaigns import (
    CellDesign,
    SwapDesign,
    cell_condition,
    parse_cell,
    parse_swap,
    swap_condition,
)
from placement_measure.records import A4Run, build_record


def test_conditions_round_trip():
    assert parse_swap(swap_condition("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base", True)) == (
        "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base", True)
    assert parse_cell(cell_condition(8, 16)) == (8, 16)
    assert parse_cell(cell_condition(8, None)) == (8, None)
    with pytest.raises(ValueError):
        parse_cell("c8")


def test_a_swap_design_interleaves_every_pair_and_state_per_block():
    design = SwapDesign(pairs=(("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"),), cold_states=(True, False),
                        repeats=3, seed=1)
    sched = design.schedule()
    assert len(sched) == 6
    for b in range(3):
        assert len({s.condition for s in sched if s.block_index == b}) == 2
    payload = design.payload(sched[0], "rid")
    assert payload["kind"] == "swap" and payload["run_id"] == "rid"


def test_a_cell_design_sizes_the_neighbour_to_outlast_the_measured_run():
    design = CellDesign(measured_model="Qwen/Qwen3-4B", neighbour_model="Qwen/Qwen3-4B-Base",
                        own_levels=(2, 8), neighbour_levels=(0, 8), solo=True, input_len=1024,
                        output_len=256, repeats=2, seed=3)
    assert len(design.conditions()) == 6
    p = design.payload(ScheduledRun(0, 0, "pair:o2:n8"), "rid")
    cell = p["cell"]
    # 100 measured prompts at concurrency 2 is 51 waves; the neighbour gets
    # four times that many waves of 8.
    assert cell["num_prompts"] == 100 and cell["neighbour_prompts"] == 4 * 8 * 51
    solo = design.payload(ScheduledRun(1, 0, "solo:o8"), "rid")
    assert solo["b"] is None and solo["a"]["gpu_memory_utilization"] == 0.92


def _outcome(payload=None, error=None, diagnostics=None):
    return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=payload, error=error,
                         diagnostics=diagnostics)


def test_records_are_ok_only_with_a_measurement():
    s = ScheduledRun(0, 0, "swap:a>b:cold")
    ok = build_record(s, "r", _outcome({"swap_s": 30.0}), kind="swap", source="stub")
    no_time = build_record(s, "r", _outcome({"swap_s": None, "failure": "x"}), kind="swap", source="stub")
    failed = build_record(s, "r", _outcome(error="boom", diagnostics={"b": {}}), kind="swap", source="stub")
    assert (ok.outcome, no_time.outcome, failed.outcome) == ("ok", "failed", "failed")
    assert failed.output == {"b": {}} and failed.failure == "boom"
    assert A4Run.from_dict(ok.to_dict()) == ok
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_campaigns.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.campaigns'`

- [ ] **Step 3: Implement**

Create `placement_measure/records.py`:

```python
"""The stored record of one measurement job, and the `build_record` callback
`harness.campaign.run_campaign` calls.

One record type for both kinds of job: the worker's output is kept whole
(`output`), and the reductions in `placement.inputs` read the fields they need
from it. Splitting it into typed fields here would decide, before any paid run,
which readings matter; the swap's memory samples and the cell's neighbour-load
samples are the evidence a reader checks a reduction against.

`outcome` is "ok" only if the job returned AND produced its measurement: a
swap with a time, a cell with a run. A job whose engine never came up, or
whose measurement failed, is "failed", with the reason, and still stored, so
the failure-rate table counts it (spec 6.6).
"""

from dataclasses import asdict, dataclass

from harness.scheduler import ScheduledRun

__all__ = ["SCHEMA_VERSION", "A4Run", "build_record"]

SCHEMA_VERSION = 1


@dataclass
class A4Run:
    run_id: str
    run_index: int
    condition: str
    block_index: int
    kind: str
    outcome: str
    failure: str | None
    clock_A: dict
    output: dict | None
    source: str
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "A4Run":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"record schema {d.get('schema_version')!r}; this build reads {SCHEMA_VERSION}"
            )
        return cls(**d)


def _failure_of(kind: str, output: dict) -> str | None:
    if kind == "swap":
        return None if output.get("swap_s") is not None else (output.get("failure") or "no swap time")
    if output.get("run") is None:
        return output.get("run_error") or "no measured run"
    return None


def build_record(scheduled: ScheduledRun, run_id: str, outcome, *, kind: str, source: str) -> A4Run:
    base = {"run_id": run_id, "run_index": scheduled.run_index, "condition": scheduled.condition,
            "block_index": scheduled.block_index, "kind": kind, "clock_A": dict(outcome.clock_A),
            "source": source}
    if outcome.error is not None:
        return A4Run(**base, outcome="failed", failure=outcome.error, output=outcome.diagnostics)
    failure = _failure_of(kind, outcome.payload)
    return A4Run(**base, outcome="failed" if failure else "ok", failure=failure,
                 output=outcome.payload)
```

- [ ] **Step 4: Add `placement_measure/campaigns.py`**

Create `placement_measure/campaigns.py`:

```python
"""Measurement campaigns: the interleaved schedule, and each job's payload.

Two campaigns, each one schedule from `harness.scheduler.build_schedule`, so
conditions are interleaved within each block and a condition is never
confounded with time-varying platform state (artifact 1 spec 5):

- swaps: a condition is an ordered checkpoint pair and a cache state.
- cells: a condition is a grid cell -- `solo:o8`, or `pair:o8:n16`.

The designs are dataclasses whose values the second pre-registration step
fixes; nothing here chooses a grid, a pair or a request shape.
"""

from dataclasses import dataclass

from harness.scheduler import ScheduledRun, build_schedule
from harness.service_sweep import num_prompts_for
from placement_measure.prereg import (
    HF_HOME,
    JOB_BUDGET_S,
    RELEASE_TIMEOUT_S,
    RELEASE_TOLERANCE_MIB,
    SOLO_GMU,
    SPLIT_GMU,
    engine,
)

__all__ = ["CellDesign", "SwapDesign", "cell_condition", "parse_cell", "parse_swap",
           "swap_condition"]


def swap_condition(a: str, b: str, cold: bool) -> str:
    return f"swap:{a}>{b}:{'cold' if cold else 'warm'}"


def parse_swap(condition: str) -> tuple[str, str, bool]:
    kind, pair, state = condition.split(":")
    a, b = pair.split(">")
    if kind != "swap" or state not in ("cold", "warm"):
        raise ValueError(f"{condition!r} is not a swap condition")
    return a, b, state == "cold"


def cell_condition(own: int, neighbour: int | None) -> str:
    return f"solo:o{own}" if neighbour is None else f"pair:o{own}:n{neighbour}"


def parse_cell(condition: str) -> tuple[int, int | None]:
    parts = condition.split(":")
    if parts[0] == "solo" and len(parts) == 2:
        return int(parts[1][1:]), None
    if parts[0] == "pair" and len(parts) == 3:
        return int(parts[1][1:]), int(parts[2][1:])
    raise ValueError(f"{condition!r} is not a cell condition")


@dataclass(frozen=True)
class SwapDesign:
    pairs: tuple[tuple[str, str], ...]
    cold_states: tuple[bool, ...]
    repeats: int
    seed: int

    def schedule(self) -> list[ScheduledRun]:
        conditions = [swap_condition(a, b, c) for a, b in self.pairs for c in self.cold_states]
        return build_schedule(conditions, self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        a, b, cold = parse_swap(scheduled.condition)
        return {"kind": "swap", "run_id": run_id, "a": engine(a, SOLO_GMU).to_dict(),
                "b": engine(b, SOLO_GMU).to_dict(), "cold": cold, "hf_home": HF_HOME,
                "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                "release_timeout_s": RELEASE_TIMEOUT_S, "job_budget_s": JOB_BUDGET_S}


@dataclass(frozen=True)
class CellDesign:
    measured_model: str
    neighbour_model: str
    own_levels: tuple[int, ...]
    neighbour_levels: tuple[int, ...]  # 0 is the idle-neighbour column
    solo: bool
    input_len: int
    output_len: int
    repeats: int
    seed: int
    waves: int = 20
    min_prompts: int = 100
    warmup_waves: int = 1
    # The neighbour is sent this many times the measured run's request-waves,
    # and stopped when the measured run ends; a neighbour that still ran out
    # is flagged in the cell's own output.
    neighbour_overrun: int = 4

    def conditions(self) -> list[str]:
        cells = [cell_condition(o, n) for o in self.own_levels for n in self.neighbour_levels]
        if self.solo:
            cells += [cell_condition(o, None) for o in self.own_levels]
        return cells

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule(self.conditions(), self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        own, neighbour = parse_cell(scheduled.condition)
        num_prompts = num_prompts_for(own, waves=self.waves, minimum=self.min_prompts)
        neighbour_prompts = 0 if not neighbour else self.neighbour_overrun * neighbour * (
            num_prompts // own + 1)
        gmu = SOLO_GMU if neighbour is None else SPLIT_GMU
        return {
            "kind": "cell", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
            "a": engine(self.measured_model, gmu).to_dict(),
            "b": None if neighbour is None else engine(self.neighbour_model, SPLIT_GMU).to_dict(),
            "cell": {"own": own, "neighbour": neighbour, "input_len": self.input_len,
                     "output_len": self.output_len, "num_prompts": num_prompts,
                     "warmup_prompts": self.warmup_waves * own,
                     "neighbour_prompts": neighbour_prompts,
                     "seed": self.seed * 1000 + scheduled.run_index},
        }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_campaigns.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/records.py placement_measure/campaigns.py tests/test_placement_measure_campaigns.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement_measure/records.py placement_measure/campaigns.py tests/test_placement_measure_campaigns.py
git commit -m "feat: the measurement record and the two campaign designs"
```

---

## Task 13: The reconnaissance report

**Files:**
- Create: `placement_measure/recon_report.py`
- Test: `tests/test_placement_measure_recon_report.py`

This turns the saved captures into answers.
- **The go/no-go** is the pre-registered criterion, applied and not chosen.
- **Compile state** reads as a compile or a cache hit at 5 s. Artifact 1 published 19.0 s for a compile and 0.33 s for a hit, two orders of magnitude apart, so the threshold's exact value decides nothing near either figure.
- **A probe that failed outright** is reported as unanswered, never as a "no".
- **Every full-memory engine's KV capacity,** with its compile state (`kv_solo`). Plan 3's request-shape rule reads the solo capacity beside the split one, and compile state moves KV capacity (amendment §5).

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_recon_report.py`:

```python
from placement_measure.prereg import GO_NO_GO_TOKENS
from placement_measure.recon_report import render, report


def _capture(label, probe, result=None, error=None):
    payload = None if result is None else {"healthy": True, "probe": probe, "result": result}
    return {"label": label, "probe": probe, "submitted": {},
            "outcome": {"clock_A": {}, "payload": payload, "error": error, "diagnostics": None}}


def _engines(kv_a, kv_b, healthy=(True, True)):
    return {"engines": {k: {"healthy": h, "facts": {"kv_capacity_tokens": kv}}
                        for k, kv, h in (("a", kv_a, healthy[0]), ("b", kv_b, healthy[1]))}}


def _swap(a, b, s4b, swap_s, cache=None, released=True, kv=(90000, 88000)):
    return {"a": {"spec": {"model": a}, "facts": {"s4b_s": 19.0, "kv_capacity_tokens": kv[0]}},
            "b": {"spec": {"model": b}, "facts": {"s4b_s": s4b, "kv_capacity_tokens": kv[1]}},
            "swap_s": swap_s, "cache": cache or {"requested": False},
            "release": {"released": released, "seconds": 0.8}}


def test_the_report_applies_the_preregistered_go_no_go():
    rep = report([
        _capture("coresidency-primary", "coresidency", _engines(GO_NO_GO_TOKENS, 20000)),
        _capture("coresidency-fallback", "coresidency", _engines(GO_NO_GO_TOKENS - 1, 90000)),
    ])
    assert rep["go_no_go"]["primary"]["passed"] is True
    assert rep["go_no_go"]["fallback"]["passed"] is False


def test_a_failed_probe_is_unanswered_not_a_no():
    rep = report([_capture("coresidency-primary", "coresidency", error="timeout")])
    assert rep["go_no_go"]["primary"] == {"answered": False, "passed": None,
                                          "reason": "the probe produced no result"}


def test_the_report_reads_compile_reuse_cache_eviction_and_release():
    cold_cache = {"requested": True, "attempts": [{"method": "drop_caches", "ok": False},
                                                  {"method": "fadvise", "ok": True}],
                  "cached_kib_before": 9_000_000, "cached_kib_after": 1_000_000}
    rep = report([
        _capture("swaps-compile", "swaps", {"swaps": [_swap("x", "y", 19.0, 60.0),
                                                      _swap("y", "z", 0.3, 30.0)]}),
        _capture("swaps-cache", "swaps", {"swaps": [_swap("x", "y", 0.3, 45.0, cold_cache),
                                                    _swap("y", "x", 0.3, 28.0, released=False)]}),
    ])
    assert [r["b_compiled"] for r in rep["compile_reuse"]] == [True, False]
    cold = rep["cache_eviction"][0]
    assert (cold["b"], cold["b_compiled"]) == ("y", False)
    assert cold["methods_ok"] == {"drop_caches": False, "fadvise": True}
    assert cold["cached_kib_drop"] == 8_000_000
    assert rep["release"]["n"] == 3 and rep["release"]["never_released"] == 1
    assert "go/no-go (primary): unanswered" in render(rep)


def test_the_report_reads_every_solo_engines_kv_with_its_compile_state():
    rep = report([_capture("swaps-compile", "swaps", {"swaps": [
        _swap("x", "y", 0.3, 30.0, kv=(85000, 91000))]})])
    assert rep["kv_solo"] == [
        {"model": "x", "kv_capacity_tokens": 85000, "s4b_s": 19.0, "compiled": True},
        {"model": "y", "kv_capacity_tokens": 91000, "s4b_s": 0.3, "compiled": False},
    ]
    assert rep["cache_eviction"] == []
    assert "solo engine y: KV 91000 tokens, compiled False" in render(rep)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon_report.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement_measure.recon_report'`

- [ ] **Step 3: Implement**

Create `placement_measure/recon_report.py`:

```python
"""Reconnaissance answers, computed from the saved captures. Publishes nothing.

Each capture is what `scripts/a4_recon_capture.py` saved for one job: the
payload it submitted and the submitter's outcome, verbatim. A job that failed
outright has no `payload` in its outcome; its question is then reported as
unanswered, never as a "no".

The go/no-go criterion is the pre-registered one (`prereg.GO_NO_GO_TOKENS`,
amendment §3); this module applies it and does not choose it.
"""

from harness.stats import median
from placement_measure.prereg import GO_NO_GO_MIN_REQUESTS, GO_NO_GO_TOKENS, T_MAX

__all__ = ["COMPILED_ABOVE_S", "render", "report"]

# Artifact 1 published S4b at 19.0 s for a compile and 0.33 s for a cache hit
# (data/analysis.json). A reading above this is a compile; below, a hit. The
# gap is two orders of magnitude, so the threshold's exact value does not
# decide any reading near either published figure.
COMPILED_ABOVE_S = 5.0


def _result(capture: dict) -> dict | None:
    payload = (capture.get("outcome") or {}).get("payload")
    return None if payload is None else payload.get("result")


def _by_label(captures) -> dict[str, dict]:
    return {c["label"]: c for c in captures}


def go_no_go(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False, "passed": None, "reason": "the probe produced no result"}
    engines = r["engines"]
    kv = [engines[k]["facts"].get("kv_capacity_tokens") for k in ("a", "b")]
    healthy = [engines[k]["healthy"] for k in ("a", "b")]
    passed = all(healthy) and all(t is not None and t >= GO_NO_GO_TOKENS for t in kv)
    return {"answered": True, "passed": passed, "healthy": healthy, "kv_capacity_tokens": kv,
            "required_tokens": GO_NO_GO_TOKENS,
            "criterion": f"both healthy, each KV >= {GO_NO_GO_MIN_REQUESTS} x T_MAX ({T_MAX})"}


def _swaps(capture: dict | None) -> list[dict]:
    r = None if capture is None else _result(capture)
    return [] if r is None else r["swaps"]


def compile_reuse(capture: dict | None) -> list[dict]:
    out = []
    for s in _swaps(capture):
        b = s.get("b") or {}
        s4b = (b.get("facts") or {}).get("s4b_s")
        out.append({"a": s["a"]["spec"]["model"], "b": (b.get("spec") or {}).get("model"),
                    "b_s4b_s": s4b, "b_compiled": None if s4b is None else s4b > COMPILED_ABOVE_S,
                    "swap_s": s.get("swap_s")})
    return out


def kv_solo(captures) -> list[dict]:
    """Every full-memory engine's logged KV capacity, with its compile state.

    The swap probes start each engine alone at `SOLO_GMU`, so they are the
    solo readings beside the co-residency probe's split ones. Compile state is
    carried because it moves KV capacity: artifact 1 published 35,792 tokens
    without a warm compile cache and 43,040 with one (amendment §5).
    """
    out = []
    for c in captures:
        for s in _swaps(c):
            for side in ("a", "b"):
                engine = s.get(side) or {}
                facts = engine.get("facts") or {}
                s4b = facts.get("s4b_s")
                out.append({"model": (engine.get("spec") or {}).get("model"),
                            "kv_capacity_tokens": facts.get("kv_capacity_tokens"),
                            "s4b_s": s4b,
                            "compiled": None if s4b is None else s4b > COMPILED_ABOVE_S})
    return out


def cache_eviction(capture: dict | None) -> list[dict]:
    out = []
    for s in _swaps(capture):
        cache = s.get("cache") or {}
        b = s.get("b") or {}
        s4b = (b.get("facts") or {}).get("s4b_s")
        common = {"b": (b.get("spec") or {}).get("model"), "swap_s": s.get("swap_s"),
                  "b_compiled": None if s4b is None else s4b > COMPILED_ABOVE_S}
        if not cache.get("requested"):
            out.append({"cold": False, **common})
            continue
        before, after = cache.get("cached_kib_before"), cache.get("cached_kib_after")
        out.append({
            "cold": True, **common,
            "methods_ok": {a["method"]: a["ok"] for a in cache.get("attempts", [])},
            "cached_kib_drop": None if before is None or after is None else before - after,
        })
    return out


def release(captures) -> dict:
    seconds = [s["release"]["seconds"] for c in captures for s in _swaps(c)
               if s.get("release") and s["release"]["released"]]
    unreleased = sum(1 for c in captures for s in _swaps(c)
                     if s.get("release") and not s["release"]["released"])
    return {"n": len(seconds), "median_s": median(seconds) if seconds else None,
            "max_s": max(seconds) if seconds else None, "never_released": unreleased}


def early_start(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False}
    return {"answered": True, "b_healthy": r["b"]["healthy"],
            "memory_when_b_started_mib": r["memory_when_b_started"]["used_mib"]}


def sleep_mode(capture: dict | None) -> dict:
    r = None if capture is None else _result(capture)
    if r is None:
        return {"answered": False}

    def status(step):
        return (r.get(step) or {}).get("status")

    works = status("sleep_a") == 200 and status("wake_a") == 200 and status("smoke_a_after_wake") == 200
    return {
        "answered": True, "works": works,
        "sleep_s": (r.get("sleep_a") or {}).get("seconds"),
        "wake_s": (r.get("wake_a") or {}).get("seconds"),
        "memory_sleeping_mib": (r.get("memory_a_asleep") or {}).get("used_mib"),
        "statuses": {k: status(k) for k in ("sleep_a", "is_sleeping_a", "sleep_b", "wake_a",
                                            "smoke_a_after_wake")},
    }


def report(captures) -> dict:
    by = _by_label(captures)
    help_r = None if "help" not in by else _result(by["help"])
    return {
        "help": help_r,
        "staged": None if "stage" not in by else _result(by["stage"]),
        "go_no_go": {"primary": go_no_go(by.get("coresidency-primary")),
                     "fallback": go_no_go(by.get("coresidency-fallback"))},
        "compile_reuse": compile_reuse(by.get("swaps-compile")),
        "cache_eviction": cache_eviction(by.get("swaps-cache")),
        "release": release([by[k] for k in ("swaps-compile", "swaps-cache") if k in by]),
        "kv_solo": kv_solo([by[k] for k in ("swaps-compile", "swaps-cache") if k in by]),
        "early_start": early_start(by.get("early-start")),
        "sleep_mode": sleep_mode(by.get("sleep")),
    }


def render(rep: dict) -> str:
    g = rep["go_no_go"]
    lines = ["# Artifact 4 reconnaissance answers", ""]
    for key in ("primary", "fallback"):
        v = g[key]
        lines.append(f"- go/no-go ({key}): " + (
            "unanswered" if not v["answered"] else
            f"{'PASS' if v['passed'] else 'FAIL'}; KV {v['kv_capacity_tokens']} vs "
            f"{v['required_tokens']} required; healthy {v['healthy']}"))
    for row in rep["compile_reuse"]:
        lines.append(f"- swap {row['a']} -> {row['b']}: S4b {row['b_s4b_s']} s, "
                     f"compiled {row['b_compiled']}, swap {row['swap_s']} s")
    for row in rep["cache_eviction"]:
        lines.append(f"- {'cold' if row['cold'] else 'warm'} swap: {row['swap_s']} s"
                     + (f"; methods {row['methods_ok']}; Cached fell {row['cached_kib_drop']} KiB"
                        if row["cold"] else ""))
    for row in rep["kv_solo"]:
        lines.append(f"- solo engine {row['model']}: KV {row['kv_capacity_tokens']} tokens, "
                     f"compiled {row['compiled']}")
    rel = rep["release"]
    lines.append(f"- memory release: median {rel['median_s']} s, max {rel['max_s']} s over "
                 f"{rel['n']} swaps; never released {rel['never_released']}")
    e = rep["early_start"]
    lines.append("- early start: " + ("unanswered" if not e["answered"] else
                 f"B healthy {e['b_healthy']} with {e['memory_when_b_started_mib']} MiB in use"))
    s = rep["sleep_mode"]
    lines.append("- sleep mode: " + ("unanswered" if not s["answered"] else
                 f"works {s['works']}; sleep {s['sleep_s']} s, wake {s['wake_s']} s, "
                 f"{s['memory_sleeping_mib']} MiB held asleep; statuses {s['statuses']}"))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_recon_report.py tests/test_placement_measure_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement_measure/recon_report.py tests/test_placement_measure_recon_report.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/recon_report.py tests/test_placement_measure_recon_report.py
git commit -m "feat: reconnaissance answers from the saved captures"
```

---

## Task 14: Measured simulator inputs

**Files:**
- Create: `placement/inputs.py`
- Test: `tests/test_placement_inputs.py`

**Plan 1 must have landed before this task:** this module builds plan 1's `ServiceCurve`, `ColocatedSurface` and `EmpiricalDistribution`.

This bridges what the worker recorded and what plan 1's simulator consumes. It produces a swap-time distribution, a solo curve and a co-located surface. Each point is the median across repetitions of each run's own median latency, the service sweep's statistic.

Every reduction refuses rather than reduces around a gap, because the surface would interpolate over a missing cell and present the guess as measured. A loaded cell whose neighbour never ramped, or ran out, is excluded with its reason.

The module lives in `placement/` and imports only coldstart-free code. Plan 1's transitive boundary test and its no-reimplementation test both cover it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_inputs.py`:

```python
"""The reductions' refusals, on hand-built records. The happy path runs end to
end in tests/test_a4_measure_end_to_end.py."""

import pytest

from placement.inputs import cell_validity, colocated_surface, swap_distribution
from placement_measure.records import A4Run


def test_a_cell_whose_neighbour_ran_out_does_not_count():
    rec = A4Run(run_id="r", run_index=0, condition="pair:o4:n4", block_index=0, kind="cell",
                outcome="ok", failure=None, clock_A={}, source="stub",
                output={"run": {"latency_s": 1.0, "throughput_tps": 1.0, "gpu_util": 1.0},
                        "neighbour_load": {"level": 4, "ramp": {"reached": True},
                                           "ended_before_measured_run": True}})
    assert "ran out" in cell_validity(rec)
    with pytest.raises(ValueError, match="interpolate"):
        colocated_surface([rec], own_levels=(4,), neighbour_levels=(4,), min_repeats=1)


def test_the_swap_distribution_draws_only_the_requested_cache_state():
    def rec(cond, s):
        return A4Run(run_id="r", run_index=0, condition=cond, block_index=0, kind="swap",
                     outcome="ok", failure=None, clock_A={}, source="stub", output={"swap_s": s})

    records = [rec("swap:a>b:cold", 40.0), rec("swap:a>b:warm", 20.0), rec("swap:b>a:cold", 41.0)]
    assert swap_distribution(records, cold=True).samples == (40.0, 41.0)
    with pytest.raises(ValueError):
        swap_distribution(records, cold=False, targets={"zzz"})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_inputs.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.inputs'`

- [ ] **Step 3: Implement**

Create `placement/inputs.py`:

```python
"""Measured simulator inputs, reduced from stored measurement runs.

The bridge from `placement_measure` (what the worker recorded) to plan 1's
types (what the simulator consumes): a swap-time `EmpiricalDistribution`, a
solo `ServiceCurve`, and a `ColocatedSurface`. Every reduction refuses rather
than reduces around a gap, as `harness.service_sweep.reduce_curve` does: a
missing cell or a thin one would be interpolated over by the surface and
published as measured.

Per point, the median across repetitions of each run's own median latency,
the service sweep's statistic, so a co-located latency and a solo one are the
same kind of number.
"""

from autoscale.service import ServiceCurve
from harness.stats import median
from placement.colocated import ColocatedSurface
from placement.resample import EmpiricalDistribution
from placement_measure.campaigns import parse_cell, parse_swap

__all__ = ["cell_validity", "colocated_surface", "solo_curve", "swap_distribution"]


def swap_distribution(records, *, cold: bool, targets=None) -> EmpiricalDistribution:
    """Swap durations from every ok swap in the given cache state, optionally
    only those whose incoming model is in `targets`. The simulator draws the
    cold distribution (amendment §5)."""
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok":
            continue
        _, b, is_cold = parse_swap(r.condition)
        if is_cold == cold and (targets is None or b in targets):
            samples.append(r.output["swap_s"])
    if not samples:
        raise ValueError(
            f"no ok swap with cold={cold} and targets={targets}; an empty distribution "
            "would simulate swaps that cost nothing"
        )
    return EmpiricalDistribution(samples=tuple(samples), measured=True)


def cell_validity(record) -> str | None:
    """None if the cell's measurement stands; otherwise why it does not."""
    if record.outcome != "ok":
        return f"run failed: {record.failure}"
    load = record.output.get("neighbour_load")
    if load and load.get("level"):
        if not (load.get("ramp") or {}).get("reached"):
            return "the neighbour never reached its load before the measured run"
        if load.get("ended_before_measured_run"):
            return "the neighbour ran out of requests during the measured run"
    return None


def _medians(records, *, kind_of, min_repeats) -> dict:
    by: dict = {}
    for r in records:
        if r.kind != "cell" or cell_validity(r) is not None:
            continue
        key = kind_of(r)
        if key is not None:
            by.setdefault(key, []).append(r.output["run"])
    thin = {k: len(v) for k, v in by.items() if len(v) < min_repeats}
    if thin:
        raise ValueError(f"cells with fewer than {min_repeats} valid repetitions: {thin}")
    return by


def solo_curve(records, *, levels, min_repeats: int) -> ServiceCurve:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return own if neighbour is None else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
    missing = [c for c in levels if c not in by]
    if missing:
        raise ValueError(f"solo levels {missing} have no valid run; the curve would skip them")
    points = []
    for c in levels:
        runs = by[c]
        util = [r["gpu_util"] for r in runs if r.get("gpu_util") is not None]
        if not util:
            raise ValueError(f"level {c} has no GPU utilisation reading; the curve needs one")
        points.append((c, median([r["latency_s"] for r in runs]),
                       median([r["throughput_tps"] for r in runs]), median(util)))
    return ServiceCurve(points=points, measured=True)


def colocated_surface(records, *, own_levels, neighbour_levels, min_repeats: int) -> ColocatedSurface:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return None if neighbour is None else (own, neighbour)

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
    missing = [(o, n) for o in own_levels for n in neighbour_levels if (o, n) not in by]
    if missing:
        raise ValueError(
            f"grid cells {missing} have no valid run; the surface would interpolate over them "
            "and present the guess as measured"
        )
    latency = tuple(
        tuple(median([r["latency_s"] for r in by[(o, n)]]) for n in neighbour_levels)
        for o in own_levels
    )
    return ColocatedSurface(own=tuple(own_levels), neighbour=tuple(neighbour_levels),
                            latency=latency, measured=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_inputs.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/inputs.py tests/test_placement_inputs.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/inputs.py tests/test_placement_inputs.py
git commit -m "feat: reduce measured runs to the simulator's inputs, refusing gaps"
```

---

## Task 15: The three scripts, and a GPU-free campaign end to end

**Files:**
- Create: `scripts/a4_recon_capture.py`
- Create: `scripts/a4_recon_report.py`
- Create: `scripts/a4_measure.py`
- Test: `tests/test_a4_recon_capture.py`
- Test: `tests/test_a4_measure_end_to_end.py`

Three scripts:
- **Capture** submits through `RunPodSubmitter.submit_payload`, saves every outcome verbatim, and never overwrites a capture.
- **Report** writes the answers.
- **Measure** runs a campaign through `harness.campaign.run_campaign` into its own store, with the same resume guard every artifact uses.

The end-to-end test runs a small co-location campaign through the real loop, the JSON-round-tripping stub submitter, the job dispatcher and the store. It reduces the result to a solo curve and a surface, and checks they recover exactly the latency the fake engines were given. It also checks that resume submits nothing twice.

- [ ] **Step 1: Write the failing test**

Create `tests/test_a4_recon_capture.py`:

```python
import importlib.util
import json
from pathlib import Path

import pytest

from harness.submit import SubmitOutcome

ROOT = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _outcome(payload=None, error=None, diagnostics=None):
    return SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=payload, error=error,
                         diagnostics=diagnostics)


def test_the_capture_script_never_overwrites_evidence(tmp_path):
    capture = _script("a4_recon_capture").capture
    jobs = [{"label": "help", "probe": "help"}]
    capture(jobs, lambda job: _outcome({"healthy": True}), tmp_path)
    saved = json.loads((tmp_path / "help.json").read_text())
    assert saved["outcome"]["payload"] == {"healthy": True}
    with pytest.raises(SystemExit, match="overwrite"):
        capture(jobs, lambda job: _outcome({"healthy": True}), tmp_path)


def test_the_capture_script_lists_jobs_without_spending(capsys):
    _script("a4_recon_capture").main(["--list"])
    out = capsys.readouterr().out
    assert "coresidency-primary" in out and "sleep" in out
```

- [ ] **Step 2: Write the second failing test**

Create `tests/test_a4_measure_end_to_end.py`:

```python
"""A small co-location campaign through the real loop, submitter, dispatcher
and store, reduced to a solo curve and a surface. The fake engines' latency is
1 + 0.1 x own + 0.05 x neighbour, so the reductions must recover it exactly."""

import contextlib
import importlib.util
from pathlib import Path

import pytest
from a4_fakes import Clock, FakeEngines

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from placement.inputs import colocated_surface, solo_curve
from placement_measure.campaigns import CellDesign
from placement_measure.colocation import CellDeps
from placement_measure.jobs import measure_job
from placement_measure.records import A4Run

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("a4_measure", ROOT / "scripts" / "a4_measure.py")
a4_measure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a4_measure)

DESIGN = CellDesign(measured_model="Qwen/Qwen3-4B", neighbour_model="Qwen/Qwen3-4B-Base",
                    own_levels=(1, 4), neighbour_levels=(0, 4), solo=True, input_len=512,
                    output_len=64, repeats=2, seed=11)


class Sampler:
    def __init__(self, base_url):
        self.samples = [{"t_s": 0.0, "running": 4.0, "error": None}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def values(self):
        return [4.0]


def _worker(payload):
    neighbour = payload["cell"]["neighbour"] or 0
    clock = Clock()

    def run_one(base_url, **kw):
        return {"latency_s": 1 + 0.1 * kw["level"] + 0.05 * neighbour,
                "throughput_tps": 100.0 * kw["level"], "gpu_util": 1.0}

    def bench(base_url, **kw):
        kw["run"].stop.wait(5)
        from harness.bench import BenchError
        raise BenchError("stopped")

    def stoppable(stop):
        run = lambda *a, **k: None
        run.stop = stop
        return run

    deps = CellDeps(served=FakeEngines(clock).served, run_one=run_one, run_bench=bench,
                    sampler_factory=contextlib.nullcontext, running_sampler=Sampler,
                    wait_running=lambda *a, **k: {"reached": True, "seconds": 1.0},
                    stoppable=stoppable, clock=clock)
    return measure_job(payload, cell_deps=deps, host=lambda: {"host_id": "h"}, clock=clock)


def test_a_cell_campaign_reduces_to_the_latencies_the_engines_produced(tmp_path):
    store = tmp_path / "cells.jsonl"
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(_worker).submit_payload,
                               store, source="stub")
    records = JsonlStore(store, A4Run).read_all()
    assert len(records) == 12 and all(r.outcome == "ok" for r in records)
    surface = colocated_surface(records, own_levels=(1, 4), neighbour_levels=(0, 4), min_repeats=2)
    assert surface.measured
    assert surface.latency_at(4, 4) == pytest.approx(1 + 0.4 + 0.2)
    assert surface.latency_at(1, 0) == pytest.approx(1.1)
    curve = solo_curve(records, levels=(1, 4), min_repeats=2)
    assert curve.latency_at(4) == pytest.approx(1.4) and curve.measured


def test_resume_skips_the_runs_already_stored(tmp_path):
    store = tmp_path / "cells.jsonl"
    calls = []

    def counting(payload):
        calls.append(payload["run_id"])
        return _worker(payload)

    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(counting).submit_payload,
                               store, source="stub")
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(counting).submit_payload,
                               store, source="stub", resume=True)
    assert len(calls) == 12


def test_a_missing_cell_is_refused_not_interpolated(tmp_path):
    store = tmp_path / "cells.jsonl"
    a4_measure.run_measurement(DESIGN, "cell", PayloadStubSubmitter(_worker).submit_payload,
                               store, source="stub")
    records = [r for r in JsonlStore(store, A4Run).read_all() if r.condition != "pair:o4:n4"]
    with pytest.raises(ValueError, match="interpolate"):
        colocated_surface(records, own_levels=(1, 4), neighbour_levels=(0, 4), min_repeats=2)
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_a4_recon_capture.py tests/test_a4_measure_end_to_end.py -q`

Expected: FAIL with `FileNotFoundError` for the scripts

- [ ] **Step 4: Implement**

Create `scripts/a4_recon_capture.py`:

```python
"""Submit artifact 4's reconnaissance jobs; save every outcome verbatim.

    .venv/bin/python scripts/a4_recon_capture.py --list
    set -a; . ./.env; set +a
    .venv/bin/python scripts/a4_recon_capture.py --preflight-only --template-id <id>
    .venv/bin/python scripts/a4_recon_capture.py --template-id <id> [--only help,stage]

Reads RUNPOD_API_KEY and RUNPOD_A4_ENDPOINT_ID. The endpoint's template must
run `python3 -u /opt/a4_recon_handler.py`. `--list` prints every job and
spends nothing; `--preflight-only` makes one GET.

Each job's outcome is written to fixtures/a4/recon/<label>.json as it lands,
and an existing file is never overwritten: a capture is evidence, and a re-run
goes under a new label or after the old file is moved by hand.
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from placement_measure.pins import pins
from placement_measure.recon_plan import recon_jobs

OUT = Path("fixtures/a4/recon")


def capture(jobs, submit_payload, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = [out_dir / f"{job['label']}.json" for job in jobs]
    existing = [str(p) for p in targets if p.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite captures {existing}; a capture is evidence")
    written = []
    for job, path in zip(jobs, targets, strict=True):
        outcome = submit_payload(job)
        path.write_text(json.dumps({"label": job["label"], "probe": job["probe"],
                                    "submitted": job, "outcome": asdict(outcome)}, indent=1))
        print(f"[capture] {job['label']}: {'ok' if outcome.error is None else outcome.error}",
              flush=True)
        written.append(path)
    return written


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--template-id")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    jobs = recon_jobs()
    if args.only:
        wanted = args.only.split(",")
        unknown = sorted(set(wanted) - {j["label"] for j in jobs})
        if unknown:
            raise SystemExit(f"unknown labels {unknown}")
        jobs = [j for j in jobs if j["label"] in wanted]
    if args.list:
        for job in jobs:
            print(job["label"], job["probe"], json.dumps(job)[:200])
        return
    key, endpoint = os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_A4_ENDPOINT_ID"]
    assert_endpoint_matches(fetch_endpoint(endpoint, key), pins(args.template_id))
    print(f"[preflight] endpoint {endpoint} matches artifact 4's pin set", flush=True)
    if args.preflight_only:
        return
    capture(jobs, RunPodSubmitter(HttpTransport(endpoint, key)).submit_payload, Path(args.out))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add `scripts/a4_recon_report.py`**

Create `scripts/a4_recon_report.py`:

```python
"""Compute artifact 4's reconnaissance answers from the saved captures.

    .venv/bin/python scripts/a4_recon_report.py [--captures fixtures/a4/recon]

Writes fixtures/a4/recon-report.json and prints the answers as markdown, the
raw material for docs/recon-a4.md. Spends nothing.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from placement_measure.recon_report import render, report


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--captures", default="fixtures/a4/recon")
    ap.add_argument("--out", default="fixtures/a4/recon-report.json")
    args = ap.parse_args(argv)
    paths = sorted(Path(args.captures).glob("*.json"))
    if not paths:
        raise SystemExit(f"no captures in {args.captures}")
    rep = report([json.loads(p.read_text()) for p in paths])
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(render(rep))
    return rep


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add `scripts/a4_measure.py`**

Create `scripts/a4_measure.py`:

```python
"""Run one of artifact 4's measurement campaigns on a RunPod endpoint.

    set -a; . ./.env; set +a
    .venv/bin/python scripts/a4_measure.py --kind cell --design <design.json> \\
        --template-id <id> --store data/a4/cells.jsonl [--resume] [--preflight-only]

Reads RUNPOD_API_KEY and RUNPOD_A4_ENDPOINT_ID; the template must run
`python3 -u /opt/a4_measure_handler.py`. The design file holds a SwapDesign or
CellDesign's fields, written by the second pre-registration step. `--store`
has no default: each campaign gets its own store, because the resume guard
assumes a store holds one campaign.
"""

import argparse
import json
import os
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.campaign import run_campaign
from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
from harness.runpod.submitter import HttpTransport, RunPodSubmitter
from harness.store import JsonlStore
from placement_measure.campaigns import CellDesign, SwapDesign
from placement_measure.pins import pins
from placement_measure.records import A4Run, build_record

DESIGNS = {"swap": SwapDesign, "cell": CellDesign}


def load_design(kind: str, path) -> SwapDesign | CellDesign:
    raw = json.loads(Path(path).read_text())
    fields = {k: tuple(tuple(x) if isinstance(x, list) else x for x in v) if isinstance(v, list)
              else v for k, v in raw.items()}
    return DESIGNS[kind](**fields)


def run_measurement(design, kind: str, submit_payload, store_path, *, source: str,
                    resume: bool = False):
    return run_campaign(
        design.schedule(),
        lambda scheduled, run_id: submit_payload(design.payload(scheduled, run_id)),
        partial(build_record, kind=kind, source=source),
        JsonlStore(store_path, A4Run),
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=lambda r: print(f"[run {r.run_index}] {r.condition}: {r.outcome}", flush=True),
        resume=resume,
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--kind", choices=sorted(DESIGNS), required=True)
    ap.add_argument("--design", required=True)
    ap.add_argument("--template-id")
    ap.add_argument("--store")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--preflight-only", action="store_true")
    args = ap.parse_args(argv)
    design = load_design(args.kind, args.design)
    key, endpoint = os.environ["RUNPOD_API_KEY"], os.environ["RUNPOD_A4_ENDPOINT_ID"]
    assert_endpoint_matches(fetch_endpoint(endpoint, key), pins(args.template_id))
    print(f"[preflight] endpoint {endpoint} matches artifact 4's pin set", flush=True)
    if args.preflight_only:
        return
    if not args.store:
        raise SystemExit("--store is required for a paid run; each campaign gets its own")
    print(f"{len(design.schedule())} jobs", flush=True)
    run_measurement(design, args.kind, RunPodSubmitter(HttpTransport(endpoint, key)).submit_payload,
                    args.store, source="runpod", resume=args.resume)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_a4_recon_capture.py tests/test_a4_measure_end_to_end.py -q`

Expected: PASS.

- [ ] **Step 8: Lint the files this task touched**

Run: `.venv/bin/ruff check scripts/a4_recon_capture.py scripts/a4_recon_report.py scripts/a4_measure.py tests/test_a4_recon_capture.py tests/test_a4_measure_end_to_end.py`

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add scripts/a4_recon_capture.py scripts/a4_recon_report.py scripts/a4_measure.py tests/test_a4_recon_capture.py tests/test_a4_measure_end_to_end.py
git commit -m "feat: capture, report and campaign scripts, proven end to end without a GPU"
```

---

## Task 16: The reconnaissance runbook

**Files:**
- Create: `docs/runbook-a4-recon.md`

The owner's checklist for the paid run, in the style of `docs/runbook-service-sweep.md`. It covers the image, template, endpoint, a free preflight, a cost estimate with its unverified inputs marked, the run order with a stop at the go/no-go, and what to commit afterwards. Running it is not a plan step.

- [ ] **Step 1: Write `docs/runbook-a4-recon.md`**

Create `docs/runbook-a4-recon.md`:

````markdown
# Runbook: artifact 4's paid reconnaissance

For the owner; not a plan step. Do not run any of this without the owner's
say-so. It rents a GPU.

**Before starting:** `docs/experiment-a4.md` step 1 is committed (its git
timestamp must predate every capture), and the image has been rebuilt with
artifact 4's handlers.

**A. Image.** Push the commits that add `placement_measure/` and the two
`worker/a4_*_handler.py` files. CI (`build-worker.yml`) rebuilds the worker
image because `placement_measure/**` and `worker/**` changed; its summary
prints `ghcr.io/<repo>@sha256:...`. Record that digest; the reconnaissance
record cites it. The base image, vLLM 0.27.1, is unchanged.

**B. Template.** A new one; artifacts 1 and 2's stay as they are.
- Image: the digest from A, never a tag.
- `dockerStartCmd`: `python3 -u /opt/a4_recon_handler.py`. On the default
  command every job fails with `KeyError: 'arm'` (artifact 1's handler).
- No model environment variables: artifact 4's jobs name their checkpoints in
  the payload, pinned by `placement_measure/prereg.py`.
- Container disk as artifact 1's template; network volume `9c7ut2slrd`.

**C. Endpoint.** GPU `NVIDIA GeForce RTX 4090`; `workersMin` 0; `workersMax` 1;
`idleTimeout` 5 s; `executionTimeoutMs` 1800000; the template from B.

**D. Free preflight.** One GET, no job.

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_A4_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --list
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --preflight-only --template-id <template id>
```

Expected: eight jobs listed, then `[preflight] endpoint <id> matches artifact 4's pin set`.

**E. Cost estimate.** Eight jobs. Rough wall time per job, from artifact 2's
pilot on this image (8B engine startup 84.5 s cold, 30.6 s warm; teardown
0.5 s) and nothing measured for the 4B checkpoints yet:

| Job | What runs | Estimate |
|---|---|---|
| `help` | two `--help=all` calls | 1–2 min |
| `stage` | download five checkpoints, about 36 GB, to the volume | 5–15 min, UNVERIFIED volume throughput |
| `coresidency-primary`, `-fallback` | two engine starts each | 3–5 min each |
| `swaps-compile`, `swaps-cache` | four swaps each, two starts per swap | 8–15 min each |
| `early-start` | two starts | 2–4 min |
| `sleep` | two starts, two sleeps, one wake | 3–6 min |

That is roughly 35–70 GPU-minutes. Price it with RunPod's per-second rate on
the day, read off the console (UNVERIFIED; the shared tooling plan's item 13).
The first job on a new endpoint may queue for the image pull: artifact 2's
pilot waited 743 s, and its balance change suggests the wait was not billed
(moderate confidence). The staged checkpoints add about 36 GB to the network
volume's storage bill, at a monthly rate also read off the console.

**F. Run, in this order.** Each job's outcome is saved as it lands, and a file
that exists is never overwritten.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only help,stage
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only coresidency-primary,coresidency-fallback
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_report.py
```

Stop here and read the go/no-go. If the primary pair fails and the fallback
passes, the model class changes and the remaining jobs should be rebuilt for
it before they are run; that is an edit to `placement_measure/recon_plan.py`,
reviewed like any other. If both fail, stop: the design changes (scope
amendment §3). Otherwise:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --template-id <id> --only swaps-compile,swaps-cache,early-start,sleep
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_report.py
```

**G. After the run.** Commit `fixtures/a4/recon/` and
`fixtures/a4/recon-report.json`, record the image digest from A and the
console's spend, and write `docs/recon-a4.md` from the report's output. Plan 3
starts from that record.
````

- [ ] **Step 2: Commit**

```bash
git add docs/runbook-a4-recon.md
git commit -m "docs: artifact 4's reconnaissance runbook"
```

---

## Task 17: Verify Part A

**Files:** none changed.

- [ ] **Step 1: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`

Expected: exit 0, with the count before Task 1 plus this plan's 90 tests.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

- [ ] **Step 3: Parity gate**

Run: `./scripts/parity_check.sh`

Expected: `PARITY OK`. This plan touches nothing artifact 1 publishes; the gate proves it.

- [ ] **Step 4: List the paid jobs without spending**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_capture.py --list`

Expected: eight lines, `help`, `stage`, `coresidency-primary`, `coresidency-fallback`, `swaps-compile`, `swaps-cache`, `early-start` and `sleep`, each with its payload's first 200 characters.

---

## Part B — the paid reconnaissance

## Task 18: STOP — the owner runs reconnaissance

**An agent does not run this task.** It rents a GPU, which is the owner's decision.

- [ ] **Step 1: Confirm the pre-registration came first**

```bash
git log -1 --format='%H %ci' -- docs/experiment-a4.md
```

Record the commit and time. Every capture must be later.

- [ ] **Step 2: The owner follows `docs/runbook-a4-recon.md`, sections A to F**

That means pushing for the image build, then the template, endpoint, preflight and cost estimate, then the capture in two halves with the go/no-go between them. If the go/no-go fails for the primary pair, the runbook says what follows; if both pairs fail, the plan ends here and the design returns to the scope amendment.

---

## Task 19: After the run — the reconnaissance record

**Files:**
- Create: `fixtures/a4/recon/*.json` (already written by the capture), `fixtures/a4/recon-report.json`, `docs/recon-a4.md`

- [ ] **Step 1: Compute the answers**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_recon_report.py`

Expected: the markdown answers on stdout, and `fixtures/a4/recon-report.json` written.

- [ ] **Step 2: Write the record**

Create `docs/recon-a4.md` from the report, with these sections, each stating its source capture:

1. **Image and spend:** the built digest from the runbook's step A, and the console's spend for the eight jobs.
2. **Go/no-go:** the KV capacity of each engine against 16,384 tokens, and the model class that follows.
3. **Compile reuse:** each swap's `S4b`, and whether same-architecture checkpoints share the compile cache across `rope_theta`.
4. **Page cache:** which eviction method worked, with the `Cached:` drop as evidence, and what the simulator draws from as a result (amendment §5).
5. **Memory release:** median and maximum, and whether an engine starts before release (`early-start`).
6. **Sleep mode:** whether it works, sleep and wake times, and the memory a sleeping engine holds. That decides whether it is simulated (amendment §6, decision 9).
7. **What plan 3 now has:** the KV capacities solo and at the split, which bound the request shape the second pre-registration step chooses (amendment §4).
8. **Decisions for the owner:** the bursty-regime sizing gap (amendment §14), and anything recon contradicted.

- [ ] **Step 3: Commit the evidence and the record**

```bash
git add fixtures/a4/recon fixtures/a4/recon-report.json docs/recon-a4.md
git commit -m "recon: artifact 4's reconnaissance captures, answers and record"
```

- [ ] **Step 4: Tell artifact 5's session the model class**

If it changed to the fallback, artifact 5's base model changes with it (amendment §11). That is a message to its session, not an edit to its files.

---

## What plan 3 does with this plan's answers

[Plan 3](2026-10-04-artifact-4-plan-3.md) fixes, before these answers are read, the rules that turn them into the second pre-registration step:
- the request shape, from the split and solo KV capacities (Task 13's `kv_solo` exists for it);
- the validation checkpoint set, from compile reuse;
- the cold-swap rule, from what eviction did;
- whether the sleep-mode arm is measured;
- the inputs to a ranking-blind regime screen.

Its Part B then applies those rules, runs the paid campaigns with Task 15's `scripts/a4_measure.py`, validates against three replays on one GPU, and publishes.

---

## Self-review notes

**Spec coverage.**

| Amendment item | Task |
|---|---|
| §1e item 4, the two-engine co-location harness | 7 |
| §1e item 5, the swap handler: teardown, memory release, `S4b`, page-cache state | 3, 4, 6 |
| §1e item 6, the reconnaissance handler: co-residency, swap, sleep mode | 9, 10 |
| §1e item 7, the replay driver | Plan 3, Task 4 |
| §1e item 8, records and the pin set | 11, 12 |
| §3, step 1 and the numeric go/no-go | 8, 13 |
| §5, weight source pinned to the volume | `HF_HOME` and offline engines (6, 7) |
| §5, compile state read from `S4b` | 2, 6, 13 |
| §5, teardown to memory release | 3, 6 |
| §5, the page cache recorded per swap | 4, 6 |
| §6, the sleep-mode probe | 9 |
| §2's measurement gate, extraction tasks 5–12 and the shared tooling | Prerequisite 2 |

Artifact 5's dependency on `docs/experiment-a4.md` is met by Task 8.

**Reuse audit.** Each shared component is called, not copied:
- `served` and its `.stop()`;
- `run_bench` and its `run` hook;
- `run_one`;
- `PromptPlan` and `random_dataset_args`;
- `max_num_seqs_from_log`;
- `parse_engine_log`;
- `run_campaign`;
- `JsonlStore`;
- `build_schedule` and `num_prompts_for`;
- `RunPodSubmitter.submit_payload` and `PayloadStubSubmitter`;
- `assert_endpoint_matches` and `fetch_endpoint`.

There are two small duplications, both deliberate:
- **`log_tail`.** The sweep's log cap lives in `worker/sweep_handler.py`, a script, not a module this package can import.
- **`host_info`.** For the same reason.

**Placeholder scan.** No step says "TBD" or "similar to Task N"; every code step carries the whole file, and every edit to an existing file shows the exact lines.

**Type consistency.** These names are used across tasks and were checked against the generated code:
- `EngineSpec.serve_args` and `to_dict`/`from_dict`;
- `CellSpec`;
- `measure_swap(...)` and `measure_cell(...)`;
- `run_probe` and `measure_job`;
- `A4Run`;
- `SwapDesign.payload` and `CellDesign.payload`;
- `parse_cell` and `parse_swap`;
- `colocated_surface`, `solo_curve` and `swap_distribution`.

**UI and parity audits.** Not applicable (see Scope).
