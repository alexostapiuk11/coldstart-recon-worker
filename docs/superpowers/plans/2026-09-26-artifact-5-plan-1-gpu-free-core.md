# Artifact 5 Plan 1 — GPU-Free Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all of artifact 5's library code, tested without a GPU: one additive harness function, the `multilora/` package from the pre-registration record through the worker-side instance runner and reconnaissance probes to the four figures, and a stub worker that drives the whole path end to end.

**Architecture:** `multilora/` is artifact 5's package. It imports `harness/` and never `coldstart/` or `autoscale/`, and a test enforces that. Each server instance is one scheduled run of the harness campaign loop, stored as an `InstanceRecord` through the harness store. Analysis is pure functions from records to one JSON-shaped dict, which the figures read. A stub worker returns exactly the payload the real worker will return, from a timing model with known costs, so the tests check that the analysis recovers what was put in.

**Tech Stack:** Python 3.13, pytest, ruff, matplotlib, numpy, safetensors, and the harness from the extraction plan.

**Spec:** [the approved amendment](../specs/2026-09-26-multi-lora-serving-harness-amendment.md), which governs, over [the August design](../specs/2026-08-17-multi-lora-serving-design.md). Section references like "amendment §3f" point at the amendment.

**Plan 1 of 3.** Plan 2 builds the worker image, runs reconnaissance and commits the pre-registration. Plan 3 primes, runs the gate and the campaign, and publishes. Nothing in this plan spends money, and nothing in it needs a GPU: the two modules that call the shared serve and bench tooling take those functions as injectable arguments and are tested with fakes.

**How this plan was checked:** every code block below was first run on 2026-09-26 in a copy of the repository, with stand-ins for the harness modules built to the extraction plan's target signatures, and the four figures were rendered and inspected at desktop and phone width. It was re-checked on 2026-10-04 against `main` after the harness extraction and shared tooling landed: the code was extracted from this document into a copy of `main`, and all 145 tests the plan adds passed alongside the landed harness tests. Ruff passed with the repository's own configuration. That revision also made four changes. Tasks 3 and 4 became verification steps, because their code landed verbatim. The stub worker is driven through the harness's `PayloadStubSubmitter` instead of a second stub submitter. And the reconnaissance help probe asks `vllm bench serve` for `--help=all`.

---

## Prerequisites — do not start before these are true

- [ ] **Harness extraction Tasks 4–12 are merged.** Run:

```bash
.venv/bin/python -c "
import inspect
import harness.stats, harness.store, harness.scheduler, harness.publish, harness.figure_guards
import harness.submit, harness.failures, harness.vllm_logs, harness.runpod.submitter
from harness.store import JsonlStore
from harness.scheduler import build_schedule
from harness.publish import failure_rate_by_group, discard_table
assert list(inspect.signature(JsonlStore).parameters) == ['path', 'record_cls']
assert list(inspect.signature(build_schedule).parameters) == ['conditions', 'blocks', 'seed']
assert 'key' in inspect.signature(discard_table).parameters
print('extraction tasks 4-12 present')
"
```

Expected: `extraction tasks 4-12 present`. Anything else means stop: this plan's code imports those modules by those names.

- [ ] **The shared tooling work has landed (2026-10-04).** It brought this plan's original Tasks 3 and 4 with it. Run:

```bash
.venv/bin/python -c "
from harness.campaign import run_campaign
from harness.runpod.submitter import RunPodSubmitter
from harness.submit import PayloadStubSubmitter
assert hasattr(RunPodSubmitter, 'submit_payload')
print('campaign loop, submit_payload and the payload stub present')
"
```

Expected: `campaign loop, submit_payload and the payload stub present`.

- [ ] **The parity gate passes on `main`.** Run `./scripts/parity_check.sh`. Expected: `PARITY OK`.
- [ ] **`git status --porcelain` is empty.**

---

## File structure

```
harness/
  stats.py            MODIFY: add bootstrap_function_of_medians (additive)
  campaign.py         already on main (2026-10-04): the campaign loop; Task 3 verifies it
  runpod/submitter.py already on main: submit_payload; Task 4 verifies it
  submit.py           already on main: PayloadStubSubmitter, which the stub worker runs through
multilora/
  __init__.py         SCHEMA_VERSION; the package's one rule
  prereg.py           Preregistration: every pre-registered value, validated
  conditions.py       condition names, schedules, per-instance phase plans
  adapters.py         synthetic PEFT adapters; inspecting any adapter
  engine.py           KV, version, compile state and cache path from a startup log
  records.py          InstanceRecord; building one from a SubmitOutcome
  campaign.py         the job payload; running a schedule through the harness loop
  phase.py            amendment §3f's failure rule; per-regime summaries
  gauge.py            parsing vllm:lora_requests_info; distinct running adapters
  sampler.py          scrapes the gauge on an interval while phases run
  serving.py          the only caller of harness.serve and harness.bench; serve flags
  instance.py         one server instance end to end, inside the worker
  recon.py            reconnaissance probes and the fixed probe list
  recon_report.py     answers R1-R9 computed from captures
  budget.py           campaign cost from reconnaissance timings, with the cut order
  numbers.py          the post's generated numbers block
  worker_env.py       what the worker reads from the endpoint environment
  worker_deps.py      the real effects behind instance.Deps (worker image only)
  cli.py              credential, restart and preflight guards for paid scripts
  estimands.py        publishability partition; every amendment §4 estimand
  knee.py             the knee rule
  gate.py             the equivalence verdict
  economics.py        tenants per GPU; cost per tenant; the three-way table
  analysis.py         everything the post reports, as one JSON-shaped dict
  stub.py             GPU-free stand-in for the worker. Produces no data
  figures.py          the four figures
scripts/
  a5_stub_demo.py     stub analysis for laying out figures. NOT DATA
  a5_render_figures.py four figures plus 375 px phone copies
tests/
  conftest.py         example_prereg() and the `prereg` fixture
  test_harness_stats_function_of_medians.py, test_harness_campaign.py,
  test_harness_submit_payload.py, test_multilora_*.py (21 files)
pyproject.toml        MODIFY: add numpy and safetensors
```

---

## Task 1: Dependencies and the package boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `multilora/__init__.py`, `tests/test_multilora_boundary.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_boundary.py`:

```python
"""`multilora/` imports `harness/` and never `coldstart/` or `autoscale/`
(amendment §5). Artifact 5 needs no code and no data from artifacts 1 or 2;
one convenience import would make it depend on a package whose published
results are frozen at a tag. Parses imports, as tests/test_autoscale_boundary.py
does, so a module whose name merely contains a banned word is not flagged."""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BANNED = {"coldstart", "autoscale"}


def _top_level_imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_package_exists():
    """Guards the guard: rglob over a missing directory yields nothing."""
    assert (REPO / "multilora" / "__init__.py").is_file()


def test_multilora_never_imports_artifact_one_or_two():
    offenders = {
        str(p.relative_to(REPO)): sorted(_top_level_imports(p) & BANNED)
        for p in sorted((REPO / "multilora").rglob("*.py"))
        if _top_level_imports(p) & BANNED
    }
    assert offenders == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_boundary.py -v`
Expected: FAIL on `test_the_package_exists`, because `multilora/__init__.py` does not exist.

- [ ] **Step 3: Create the package and add the dependencies**

Create `multilora/__init__.py`:

```python
"""Artifact 5: how many LoRA adapters fit on one GPU.

Imports `harness/` and never `coldstart/` or `autoscale/`; tests/test_multilora_boundary.py
enforces it. Design: docs/superpowers/specs/2026-09-26-multi-lora-serving-harness-amendment.md.
"""

SCHEMA_VERSION = 1
```

In `pyproject.toml`, change the dependencies line to:

```toml
dependencies = ["matplotlib", "numpy", "requests", "safetensors"]
```

numpy is already installed as a matplotlib dependency. safetensors is new, and the vLLM worker image already carries it. Install it:

```bash
.venv/bin/pip install safetensors
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_multilora_boundary.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml multilora/__init__.py tests/test_multilora_boundary.py
git commit -m "feat: the multilora package, and a guard that it never imports artifact 1 or 2"
```

---

## Task 2: A bootstrap over functions of several medians

Two estimands have no fixed-shape bootstrap in the harness: the difference in differences of amendment §3b, over four independent groups, and the knee's ratio of two medians. This adds one generic function. It is additive: no existing signature changes and no caller changes.

**Files:**
- Modify: `harness/stats.py` (append)
- Create: `tests/test_harness_stats_function_of_medians.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_harness_stats_function_of_medians.py`:

```python
import math

import pytest

from harness.stats import bootstrap_function_of_medians, bootstrap_median_diff


def _sample(offset: float, n: int = 30) -> list[float]:
    return [offset + (i % 7) * 0.5 for i in range(n)]


def test_it_reproduces_the_unpaired_median_difference_exactly():
    """A difference of two medians through the generic function must be the
    same computation as the fixed-shape bootstrap, draw for draw. Same seed,
    same resampling order, same interval -- otherwise the module has two
    definitions of one interval."""
    a, b = _sample(10.0), _sample(4.0)
    generic = bootstrap_function_of_medians(
        [a, b], lambda m: m[0] - m[1], iterations=500, seed=3
    )
    fixed = bootstrap_median_diff(a, b, iterations=500, seed=3)
    assert generic == fixed


def test_difference_in_differences_point_is_the_arithmetic_on_medians():
    groups = [_sample(10.0), _sample(4.0), _sample(7.0), _sample(3.0)]
    res = bootstrap_function_of_medians(
        groups, lambda m: (m[0] - m[1]) - (m[2] - m[3]), iterations=200, seed=1
    )
    assert math.isclose(res["point"], (10.0 - 4.0) - (7.0 - 3.0))
    assert res["lo"] <= res["point"] <= res["hi"]


def test_a_ratio_of_medians_is_supported():
    res = bootstrap_function_of_medians(
        [_sample(8.0), _sample(10.0)], lambda m: 1 - m[0] / m[1], iterations=200, seed=2
    )
    assert res["lo"] <= res["point"] <= res["hi"]


def test_every_group_must_meet_the_bootstrap_floor():
    with pytest.raises(ValueError, match="samples\\[1\\]"):
        bootstrap_function_of_medians([_sample(1.0), [1.0, 2.0]], lambda m: m[0] - m[1])


def test_a_non_finite_statistic_is_refused():
    with pytest.raises(ValueError, match="non-finite"):
        bootstrap_function_of_medians([_sample(1.0), _sample(2.0)], lambda m: math.inf)


def test_empty_samples_are_refused():
    with pytest.raises(ValueError, match="at least one group"):
        bootstrap_function_of_medians([], lambda m: 0.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_harness_stats_function_of_medians.py -v`
Expected: FAIL with `ImportError: cannot import name 'bootstrap_function_of_medians'`.

- [ ] **Step 3: Append the function to `harness/stats.py`**

It uses the module's existing private helpers: `_check_iterations_and_alpha`, `_validate_bootstrap_sample`, `_median` and `_percentile_interval`. `math` and `random` are already imported there.

```python
def bootstrap_function_of_medians(
    samples, statistic, iterations=10000, seed=0, alpha=0.05
) -> dict:
    """Percentile-method interval on `statistic(medians)`, where `medians[i]`
    is the median of `samples[i]` and every sample is resampled independently.

    For quantities built from several independent groups' medians that none of
    the fixed-shape bootstraps above covers: a difference in differences over
    four groups, or a ratio of two medians. Restricting the statistic to a
    function of medians keeps it on this module's one estimator -- a caller
    cannot smuggle a mean in through it.

    Independent resampling is correct only for unpaired groups. For paired
    data, compute one value per unit and call `bootstrap_median_ci` on those.
    """
    _check_iterations_and_alpha(iterations, alpha)
    groups = [
        _validate_bootstrap_sample(s, f"samples[{i}]") for i, s in enumerate(samples)
    ]
    if not groups:
        raise ValueError("samples must contain at least one group")

    def evaluate(medians: list[float]) -> float:
        value = statistic(medians)
        if not math.isfinite(value):
            raise ValueError(f"statistic returned a non-finite value: {value!r}")
        return value

    rng = random.Random(seed)
    point = evaluate([_median(g) for g in groups])
    draws = []
    for _ in range(iterations):
        medians = [_median([g[rng.randrange(len(g))] for _ in range(len(g))]) for g in groups]
        draws.append(evaluate(medians))
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness_stats_function_of_medians.py -v`
Expected: 6 passed. The first test is the important one: it proves the new function draws exactly the same resamples as `bootstrap_median_diff`, so the module still has one definition of each interval.

- [ ] **Step 5: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`.

- [ ] **Step 6: Commit**

```bash
git add harness/stats.py tests/test_harness_stats_function_of_medians.py
git commit -m "feat: a percentile bootstrap over any function of several groups' medians"
```

---

## Task 3: The campaign loop in the harness — already on `main`

**Landed 2026-10-04, verbatim from this task's original text**, by the harness extraction and shared tooling work (commit `e904e49`). `harness/campaign.py` and `tests/test_harness_campaign.py` exist, and `coldstart/driver.run_campaign` already runs on the harness loop, with the old loop deleted. Do not recreate either file.

- [ ] **Step 1: Verify, and change nothing**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_campaign.py tests/test_driver.py -q`
Expected: pass. Nothing to commit.

If either file is missing or the tests fail, stop: `main` is not in the state this plan was checked against.

---

## Task 4: `submit_payload` and a payload stub — already on `main`

**Landed 2026-10-04, verbatim from this task's original text** (commit `86a50ae`). `RunPodSubmitter.submit_payload` and `tests/test_harness_submit_payload.py` exist. The shared tooling work also added `harness.submit.PayloadStubSubmitter`, the GPU-free twin of `submit_payload`. It round-trips the payload and output through JSON as the real transport does, and records an unhealthy engine as a failure with the same message. Task 14 drives the stub worker through it instead of defining a second stub submitter.

- [ ] **Step 1: Verify, and change nothing**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_harness_submit_payload.py tests/test_payload_stub_submitter.py tests/test_runpod_submitter.py -q`
Expected: pass. Nothing to commit.

---

## Task 5: The pre-registration record

Every analysis and job payload takes a `Preregistration`. Its values are fixed in plan 2, in `multilora/prereg_values.py`, committed with `docs/experiment-a5.md`. `prereg_table` renders every value as the markdown table that document embeds, and plan 2 adds a test that the two agree. Tests use `example_prereg()`, whose values are for tests only.

**Files:**
- Create: `multilora/prereg.py`, `tests/conftest.py`, `tests/test_multilora_prereg.py`

- [ ] **Step 1: Write the fixture and the failing test**

Create `tests/conftest.py`:

```python
import pytest

from multilora.prereg import Preregistration


def example_prereg(**overrides) -> Preregistration:
    """Values for tests only. The real ones live in multilora/prereg_values.py."""
    values = {
        "concurrency": 64,
        "rank": 16,
        "target_modules": (
            "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
        ),
        "gate_adapters": 4,
        "warmup_requests_per_adapter": 2,
        "scrape_interval_s": 1.0,
        "knee_threshold": 0.10,
        "request_tokens": 30,
        "context_length_tokens": 8192,
        "slo_ttft_p95_s": 2.0,
        "requests_per_tenant_month": 100_000.0,
        "peak_to_average": 3.0,
        "gpu_hourly_rate": 1.0,
        "schedule_seed": 5,
        "include_diagnostic": True,
        "include_control": True,
        "bench_dataset_args": (
            "--dataset-name", "random", "--random-input-len", "14", "--random-output-len", "16",
        ),
        "real_adapters": tuple((f"example/adapter-{i}", f"rev{i}") for i in range(4)),
    }
    values.update(overrides)
    return Preregistration(**values)


@pytest.fixture
def prereg() -> Preregistration:
    return example_prereg()
```

Create `tests/test_multilora_prereg.py`:

```python
import pytest

from tests.conftest import example_prereg


def test_the_example_is_valid_and_derives_the_margin_and_phase_size(prereg):
    assert prereg.equivalence_margin == pytest.approx(0.05)
    assert prereg.requests_per_phase == 640
    assert prereg.gate_slots == 8


def test_small_concurrency_still_meets_the_p95_floor():
    small = {"sweep": (1, 2, 4), "diagnostic_points": (1, 4), "control_point": 4}
    assert example_prereg(concurrency=4, **small).requests_per_phase == 80
    assert example_prereg(concurrency=9, **small).requests_per_phase == 90


def test_a_sweep_above_concurrency_is_refused():
    with pytest.raises(ValueError, match="exceeds concurrency"):
        example_prereg(concurrency=32)


def test_a_sweep_that_does_not_double_is_refused():
    with pytest.raises(ValueError, match="double"):
        example_prereg(sweep=(1, 2, 3, 4), diagnostic_points=(1,), control_point=4)


def test_too_few_instances_for_a_bootstrap_are_refused():
    with pytest.raises(ValueError, match="bootstrap floor"):
        example_prereg(instances_per_condition=19)


@pytest.mark.parametrize("tau", [0.0, 1.0, -0.1])
def test_the_knee_threshold_must_be_a_fraction(tau):
    with pytest.raises(ValueError, match="knee_threshold"):
        example_prereg(knee_threshold=tau)


def test_non_positive_rates_are_refused():
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        example_prereg(gpu_hourly_rate=0.0)


def test_every_real_gate_adapter_is_pinned_to_a_revision():
    with pytest.raises(ValueError, match="real_adapters has 3"):
        example_prereg(real_adapters=(("a", "1"), ("b", "2"), ("c", "3")))
    with pytest.raises(ValueError, match="repo id, revision"):
        example_prereg(real_adapters=(("a", "1"), ("b", "2"), ("c", "3"), ("d", "")))


def test_the_request_shape_must_be_stated():
    with pytest.raises(ValueError, match="bench_dataset_args"):
        example_prereg(bench_dataset_args=())


def test_diagnostic_and_control_points_must_be_on_the_sweep():
    with pytest.raises(ValueError, match="diagnostic_points"):
        example_prereg(diagnostic_points=(1, 3))
    with pytest.raises(ValueError, match="control_point"):
        example_prereg(control_point=48)


def test_the_table_names_every_field_and_the_derived_values(prereg):
    from dataclasses import fields

    from multilora.prereg import prereg_table

    table = prereg_table(prereg)
    for f in fields(prereg):
        assert f"| `{f.name}` |" in table
    assert "| `equivalence_margin` (derived) | `0.05` |" in table
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_prereg.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.prereg'`.

- [ ] **Step 3: Create `multilora/prereg.py`**

```python
"""The pre-registered parameters, as one validated object.

Every analysis and every job payload takes a `Preregistration` rather than
reading module constants, so the values that fix the experiment live in one
place: `multilora/prereg_values.py`, committed with `docs/experiment-a5.md`
before the first paid run. The git timestamp on that pair is the evidence the
values were fixed in advance.

The defaulted fields below are fixed by the approved design (amendment §4) and
are not expected to change. The others are fixed after reconnaissance.
"""

import math
from dataclasses import dataclass, fields

from harness.stats import MIN_BOOTSTRAP_SAMPLES, MIN_SAMPLES


@dataclass(frozen=True)
class Preregistration:
    concurrency: int  # C, amendment §3e
    rank: int  # r, also max_lora_rank, amendment §3a
    target_modules: tuple[str, ...]
    gate_adapters: int  # G, amendment §4
    warmup_requests_per_adapter: int  # [w], amendment §4
    scrape_interval_s: float  # amendment §3a
    knee_threshold: float  # tau, a fraction of throughput per doubling, amendment §4
    request_tokens: int  # prompt + output tokens at the inherited request shape
    context_length_tokens: int  # the production context length, amendment §3c
    slo_ttft_p95_s: float
    requests_per_tenant_month: float
    peak_to_average: float
    gpu_hourly_rate: float  # taken from artifact 4's committed assumptions
    schedule_seed: int
    include_diagnostic: bool  # amendment §3b; cut first if budget binds
    include_control: bool  # amendment §3a; cut before the diagnostic
    bench_dataset_args: tuple[str, ...]  # the inherited request shape, as bench serve arguments
    real_adapters: tuple[tuple[str, str], ...]  # (repo id, revision) per real gate adapter
    sweep: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)
    concentrated_k: int = 1
    instances_per_condition: int = 24
    phases_per_regime: int = 2
    diagnostic_points: tuple[int, ...] = (1, 16, 64)
    control_point: int = 64

    def __post_init__(self) -> None:
        positive_ints = {
            "concurrency": self.concurrency,
            "rank": self.rank,
            "gate_adapters": self.gate_adapters,
            "warmup_requests_per_adapter": self.warmup_requests_per_adapter,
            "request_tokens": self.request_tokens,
            "context_length_tokens": self.context_length_tokens,
            "concentrated_k": self.concentrated_k,
            "phases_per_regime": self.phases_per_regime,
        }
        for name, value in positive_ints.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive int, got {value!r}")
        positive_floats = {
            "scrape_interval_s": self.scrape_interval_s,
            "slo_ttft_p95_s": self.slo_ttft_p95_s,
            "requests_per_tenant_month": self.requests_per_tenant_month,
            "peak_to_average": self.peak_to_average,
            "gpu_hourly_rate": self.gpu_hourly_rate,
        }
        for name, value in positive_floats.items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive, got {value!r}")
        if not 0.0 < self.knee_threshold < 1.0:
            raise ValueError(f"knee_threshold must be in (0, 1), got {self.knee_threshold!r}")
        if not self.target_modules:
            raise ValueError("target_modules must not be empty")
        if not self.bench_dataset_args:
            raise ValueError("bench_dataset_args must not be empty")
        if len(self.real_adapters) != self.gate_adapters:
            raise ValueError(
                f"real_adapters has {len(self.real_adapters)} entries; gate_adapters is "
                f"{self.gate_adapters}"
            )
        for entry in self.real_adapters:
            if len(entry) != 2 or not all(entry):
                raise ValueError(f"each real adapter is (repo id, revision), got {entry!r}")
        if list(self.sweep) != sorted(set(self.sweep)) or self.sweep[0] != 1:
            raise ValueError(f"sweep must be strictly increasing from 1, got {self.sweep!r}")
        for lo, hi in zip(self.sweep, self.sweep[1:]):
            if hi != 2 * lo:
                raise ValueError(
                    f"sweep must double at every step so the knee is a doubling, got {self.sweep!r}"
                )
        if self.sweep[-1] > self.concurrency:
            raise ValueError(
                f"sweep top {self.sweep[-1]} exceeds concurrency {self.concurrency}: the spread "
                "regime cannot hold more adapters in flight than requests (amendment §3e). "
                "Lower the sweep's top to the concurrency instead."
            )
        if self.concentrated_k >= self.sweep[1]:
            raise ValueError("concentrated_k must be below the second sweep point")
        if self.instances_per_condition < MIN_BOOTSTRAP_SAMPLES:
            raise ValueError(
                f"instances_per_condition {self.instances_per_condition} is below the "
                f"bootstrap floor {MIN_BOOTSTRAP_SAMPLES}"
            )
        if not set(self.diagnostic_points) <= set(self.sweep):
            raise ValueError("diagnostic_points must be sweep points")
        if self.control_point not in self.sweep:
            raise ValueError("control_point must be a sweep point")

    @property
    def equivalence_margin(self) -> float:
        """delta = tau / 2 (amendment §4): a synthetic bias below half the knee
        threshold cannot move the knee by itself."""
        return self.knee_threshold / 2

    @property
    def requests_per_phase(self) -> int:
        """max(80, 10 x C): 80 is the p95 sample floor (amendment §4)."""
        return max(MIN_SAMPLES["p95"], 10 * self.concurrency)

    @property
    def gate_slots(self) -> int:
        """The gate registers G real and G synthetic adapters."""
        return 2 * self.gate_adapters


def prereg_table(prereg: Preregistration) -> str:
    """Every pre-registered value as a markdown table. `docs/experiment-a5.md`
    embeds this exact text, and a test fails if the two ever disagree, so the
    document a reader sees and the object the code runs on are one thing."""
    lines = ["| parameter | value |", "|---|---|"]
    for f in fields(prereg):
        lines.append(f"| `{f.name}` | `{getattr(prereg, f.name)!r}` |")
    lines.append(f"| `equivalence_margin` (derived) | `{prereg.equivalence_margin!r}` |")
    lines.append(f"| `requests_per_phase` (derived) | `{prereg.requests_per_phase!r}` |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_prereg.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/prereg.py tests/conftest.py tests/test_multilora_prereg.py
git commit -m "feat: the pre-registration as one validated record"
```

---

## Task 6: Conditions, schedules and phase plans

A condition is one kind of server instance: a sweep point, a diagnostic point, the gauge control, or the gate. The harness scheduler interleaves conditions within blocks and also orders each instance's phases, so every order is reproducible from the seed and the run index. A top-up schedule covers conditions that fall below the bootstrap floor after exclusions (amendment §4), on its own seed stream.

**Files:**
- Create: `multilora/conditions.py`, `tests/test_multilora_conditions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_conditions.py`:

```python
from collections import Counter

import pytest

from multilora.conditions import (
    CONCENTRATED,
    GATE,
    REAL,
    SPREAD,
    SYNTHETIC,
    campaign_conditions,
    campaign_schedule,
    gate_schedule,
    parse_condition,
    phase_plan,
    registered_adapters,
    topup_schedule,
)
from tests.conftest import example_prereg


def test_campaign_conditions_cover_sweep_diagnostic_and_control(prereg):
    assert campaign_conditions(prereg) == [
        "sweep-N1", "sweep-N2", "sweep-N4", "sweep-N8", "sweep-N16", "sweep-N32", "sweep-N64",
        "diag-N1", "diag-N16", "diag-N64", "ctrl-N64",
    ]


def test_cut_conditions_disappear_from_the_schedule():
    cut = example_prereg(include_diagnostic=False, include_control=False)
    assert campaign_conditions(cut) == [f"sweep-N{n}" for n in cut.sweep]


def test_every_condition_gets_the_pre_registered_instance_count(prereg):
    counts = Counter(s.condition for s in campaign_schedule(prereg))
    assert set(counts.values()) == {prereg.instances_per_condition}
    assert len(counts) == 11


def test_the_gate_has_its_own_schedule(prereg):
    sched = gate_schedule(prereg)
    assert {s.condition for s in sched} == {GATE}
    assert len(sched) == prereg.instances_per_condition


def test_parse_condition_sets_the_per_job_switches(prereg):
    assert parse_condition("sweep-N16", prereg).n_slots == 16
    diag = parse_condition("diag-N64", prereg)
    assert diag.specialize_active_lora and not diag.disable_log_stats
    ctrl = parse_condition("ctrl-N64", prereg)
    assert ctrl.disable_log_stats and not ctrl.specialize_active_lora
    assert parse_condition(GATE, prereg).n_slots == 8


@pytest.mark.parametrize("bad", ["sweep-N3", "diag-N8", "ctrl-N32", "nonsense"])
def test_unregistered_conditions_are_refused(prereg, bad):
    with pytest.raises(ValueError):
        parse_condition(bad, prereg)


def test_sweep_phases_alternate_regimes_with_the_right_adapter_lists(prereg):
    phases = phase_plan(parse_condition("sweep-N16", prereg), prereg, run_index=3)
    assert Counter(p.regime for p in phases) == {CONCENTRATED: 2, SPREAD: 2}
    assert [p.phase_index for p in phases] == [0, 1, 2, 3]
    for p in phases:
        if p.regime == CONCENTRATED:
            assert p.adapters == ("a00",)
        else:
            assert p.adapters == registered_adapters(parse_condition("sweep-N16", prereg), prereg)
            assert len(p.adapters) == 16


def test_phase_order_is_reproducible_and_varies_between_instances(prereg):
    cond = parse_condition("sweep-N8", prereg)
    assert phase_plan(cond, prereg, 7) == phase_plan(cond, prereg, 7)
    orders = {tuple(p.regime for p in phase_plan(cond, prereg, i)) for i in range(20)}
    assert len(orders) > 1


def test_at_one_slot_the_two_regimes_list_the_same_adapter(prereg):
    phases = phase_plan(parse_condition("sweep-N1", prereg), prereg, 0)
    assert {p.adapters for p in phases} == {("a00",)}


def test_gate_phases_compare_real_and_synthetic_sets_of_equal_size(prereg):
    phases = phase_plan(parse_condition(GATE, prereg), prereg, 2)
    assert Counter(p.regime for p in phases) == {REAL: 2, SYNTHETIC: 2}
    real = next(p.adapters for p in phases if p.regime == REAL)
    synth = next(p.adapters for p in phases if p.regime == SYNTHETIC)
    assert real == ("r00", "r01", "r02", "r03")
    assert synth == ("s00", "s01", "s02", "s03")


def test_a_top_up_covers_only_the_named_conditions(prereg):
    sched = topup_schedule(prereg, ["sweep-N64", "diag-N16"], blocks=3)
    assert Counter(s.condition for s in sched) == {"sweep-N64": 3, "diag-N16": 3}


def test_a_top_up_refuses_the_gate_and_unregistered_names(prereg):
    with pytest.raises(ValueError, match="registered campaign conditions"):
        topup_schedule(prereg, ["gate"], blocks=1)
    with pytest.raises(ValueError, match="registered campaign conditions"):
        topup_schedule(prereg, ["sweep-N3"], blocks=1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_conditions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.conditions'`.

- [ ] **Step 3: Create `multilora/conditions.py`**

```python
"""What one scheduled instance is, and in what order its phases run.

A condition names one kind of server instance: a sweep point, a diagnostic
point with `specialize_active_lora` on, the gauge control with stats logging
off, or the equivalence gate. The harness scheduler interleaves conditions
within blocks; this module decides what each one means and what its phases
are. Adapter names are fixed strings so a stored record says exactly which
adapters each phase listed.
"""

import re
from dataclasses import dataclass

from harness.scheduler import ScheduledRun, build_schedule
from multilora.prereg import Preregistration

SWEEP = "sweep"
DIAGNOSTIC = "diag"
CONTROL = "ctrl"
GATE = "gate"

CONCENTRATED = "concentrated"
SPREAD = "spread"
REAL = "real"
SYNTHETIC = "synthetic"

_NAMED = re.compile(r"^(sweep|diag|ctrl)-N(\d+)$")


@dataclass(frozen=True)
class Condition:
    name: str
    kind: str
    n_slots: int
    specialize_active_lora: bool
    disable_log_stats: bool


@dataclass(frozen=True)
class PhaseSpec:
    phase_index: int
    regime: str
    adapters: tuple[str, ...]


def synthetic_name(i: int) -> str:
    return f"a{i:02d}"


def real_name(i: int) -> str:
    return f"r{i:02d}"


def gate_synthetic_name(i: int) -> str:
    return f"s{i:02d}"


def condition_name(kind: str, n_slots: int) -> str:
    return f"{kind}-N{n_slots}"


def parse_condition(name: str, prereg: Preregistration) -> Condition:
    if name == GATE:
        return Condition(GATE, GATE, prereg.gate_slots, False, False)
    m = _NAMED.match(name)
    if not m:
        raise ValueError(f"unknown condition {name!r}")
    kind, n = m.group(1), int(m.group(2))
    if n not in prereg.sweep:
        raise ValueError(f"condition {name!r} is not at a sweep point {prereg.sweep}")
    if kind == DIAGNOSTIC and n not in prereg.diagnostic_points:
        raise ValueError(f"{name!r} is not a pre-registered diagnostic point")
    if kind == CONTROL and n != prereg.control_point:
        raise ValueError(f"{name!r} is not the pre-registered control point")
    return Condition(name, kind, n, kind == DIAGNOSTIC, kind == CONTROL)


def campaign_conditions(prereg: Preregistration) -> list[str]:
    """Every non-gate condition, in a fixed order the scheduler then shuffles
    within each block. The diagnostic and control conditions are present only
    if the pre-registration kept them after the budget check."""
    names = [condition_name(SWEEP, n) for n in prereg.sweep]
    if prereg.include_diagnostic:
        names += [condition_name(DIAGNOSTIC, n) for n in prereg.diagnostic_points]
    if prereg.include_control:
        names.append(condition_name(CONTROL, prereg.control_point))
    return names


def campaign_schedule(prereg: Preregistration) -> list[ScheduledRun]:
    return build_schedule(
        campaign_conditions(prereg), prereg.instances_per_condition, prereg.schedule_seed
    )


def gate_schedule(prereg: Preregistration) -> list[ScheduledRun]:
    """The gate runs first and alone (August §8), so it has its own schedule
    and its own store. Its seed is offset so it never shares a stream with the
    campaign's."""
    return build_schedule([GATE], prereg.instances_per_condition, prereg.schedule_seed + 1)


def registered_adapters(condition: Condition, prereg: Preregistration) -> tuple[str, ...]:
    if condition.kind == GATE:
        g = prereg.gate_adapters
        return tuple(real_name(i) for i in range(g)) + tuple(
            gate_synthetic_name(i) for i in range(g)
        )
    return tuple(synthetic_name(i) for i in range(condition.n_slots))


def phase_plan(
    condition: Condition, prereg: Preregistration, run_index: int
) -> list[PhaseSpec]:
    """The instance's timed phases, alternating regimes in an order drawn per
    instance. The draw reuses the harness scheduler: two regimes, `phases_per_
    regime` blocks, seeded from the campaign seed and the run index, so the
    order is reproducible from the stored record alone."""
    if condition.kind == GATE:
        g = prereg.gate_adapters
        lists = {
            REAL: tuple(real_name(i) for i in range(g)),
            SYNTHETIC: tuple(gate_synthetic_name(i) for i in range(g)),
        }
    else:
        registered = registered_adapters(condition, prereg)
        lists = {
            CONCENTRATED: registered[: prereg.concentrated_k],
            SPREAD: registered,
        }
    seed = prereg.schedule_seed * 1_000_003 + run_index
    order = build_schedule(list(lists), prereg.phases_per_regime, seed)
    return [PhaseSpec(s.run_index, s.condition, lists[s.condition]) for s in order]


def topup_schedule(prereg: Preregistration, conditions: list[str], blocks: int) -> list[ScheduledRun]:
    """Extra instances for conditions that fell below the bootstrap floor after
    exclusions (amendment §4). Own store, own seed stream; the post discloses
    them. Only named, registered, non-gate conditions may be topped up."""
    known = set(campaign_conditions(prereg))
    unknown = [c for c in conditions if c not in known]
    if unknown or not conditions:
        raise ValueError(f"top-up conditions must be registered campaign conditions: {unknown}")
    if blocks <= 0:
        raise ValueError("blocks must be positive")
    return build_schedule(list(conditions), blocks, prereg.schedule_seed + 2)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_conditions.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/conditions.py tests/test_multilora_conditions.py
git commit -m "feat: conditions, interleaved schedules, and per-instance phase order"
```

---

## Task 7: Synthetic adapters

Shapes come from the base model's own `config.json`. One test pins the amendment's size estimate for Qwen3-4B at rank 16: exactly 33,030,144 parameters, about 63 MiB at fp16. The same module decides whether a public adapter qualifies for the gate (R10), and picks among qualifying ones deterministically.

**Files:**
- Create: `multilora/adapters.py`, `tests/test_multilora_adapters.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_adapters.py`:

```python
import json

import numpy as np
import pytest
from safetensors.numpy import load_file

from multilora.adapters import (
    adapter_checksum,
    adapter_parameter_count,
    inspect_adapter,
    module_shapes,
    write_synthetic_adapter,
)

TINY = {
    "hidden_size": 8,
    "num_attention_heads": 2,
    "num_key_value_heads": 1,
    "head_dim": 4,
    "intermediate_size": 16,
    "num_hidden_layers": 2,
}
QWEN3_4B_SHAPE = {
    "hidden_size": 2560,
    "num_attention_heads": 32,
    "num_key_value_heads": 8,
    "head_dim": 128,
    "intermediate_size": 9728,
    "num_hidden_layers": 36,
}
ALL = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


def test_qwen3_4b_rank_16_matches_the_amendments_size_estimate():
    """Amendment §3c: ~33.0M parameters, ~63 MiB at fp16 per adapter."""
    params = adapter_parameter_count(QWEN3_4B_SHAPE, 16, ALL)
    assert params == 33_030_144
    assert params * 2 / 2**20 == pytest.approx(63.0, abs=0.1)


def test_grouped_query_attention_shrinks_k_and_v():
    shapes = module_shapes(TINY)
    assert shapes["q_proj"] == (8, 8)
    assert shapes["k_proj"] == (8, 4)
    assert shapes["down_proj"] == (16, 8)


def test_the_written_adapter_has_peft_names_and_shapes(tmp_path):
    write_synthetic_adapter(
        tmp_path / "a00", config=TINY, base_model="m", rank=3, target_modules=ALL, seed=1
    )
    tensors = load_file(str(tmp_path / "a00" / "adapter_model.safetensors"))
    assert len(tensors) == 2 * 7 * 2
    a = tensors["base_model.model.model.layers.1.self_attn.k_proj.lora_A.weight"]
    b = tensors["base_model.model.model.layers.1.self_attn.k_proj.lora_B.weight"]
    assert a.shape == (3, 8) and b.shape == (4, 3)
    assert a.dtype == np.float16
    assert "base_model.model.model.layers.0.mlp.up_proj.lora_B.weight" in tensors
    cfg = json.loads((tmp_path / "a00" / "adapter_config.json").read_text())
    assert cfg["r"] == 3 and cfg["peft_type"] == "LORA"
    assert cfg["target_modules"] == sorted(ALL)


def test_the_same_seed_writes_the_same_bytes(tmp_path):
    kw = {"config": TINY, "base_model": "m", "rank": 2, "target_modules": ALL}
    one = write_synthetic_adapter(tmp_path / "x", seed=4, **kw)
    two = write_synthetic_adapter(tmp_path / "y", seed=4, **kw)
    other = write_synthetic_adapter(tmp_path / "z", seed=5, **kw)
    assert one == two != other
    assert adapter_checksum(tmp_path / "x") == one


def test_inspect_reads_rank_and_modules_back(tmp_path):
    write_synthetic_adapter(
        tmp_path / "a", config=TINY, base_model="m", rank=2,
        target_modules=("q_proj", "v_proj"), seed=0,
    )
    assert inspect_adapter(tmp_path / "a") == {
        "rank": 2, "target_modules": ["q_proj", "v_proj"], "tensors": 8,
    }


def test_unsupported_modules_are_refused(tmp_path):
    with pytest.raises(ValueError, match="lm_head"):
        write_synthetic_adapter(
            tmp_path / "a", config=TINY, base_model="m", rank=2,
            target_modules=("lm_head",), seed=0,
        )


def test_a_real_adapter_qualifies_only_within_rank_and_modules():
    from multilora.adapters import real_adapter_qualifies

    ok = {"peft_type": "LORA", "r": 8, "target_modules": ["q_proj", "v_proj"]}
    assert real_adapter_qualifies(ok, rank=16, target_modules=ALL) == (True, "qualifies")
    too_big = {**ok, "r": 32}
    assert real_adapter_qualifies(too_big, rank=16, target_modules=ALL)[0] is False
    outside = {**ok, "target_modules": ["q_proj", "lm_head"]}
    assert "lm_head" in real_adapter_qualifies(outside, rank=16, target_modules=ALL)[1]
    pattern = {**ok, "target_modules": "all-linear"}
    assert real_adapter_qualifies(pattern, rank=16, target_modules=ALL)[0] is False


def test_selection_is_deterministic_and_keeps_every_rejection_reason():
    from multilora.adapters import select_real_adapters

    good = {"peft_type": "LORA", "r": 16, "target_modules": ["q_proj"]}
    cands = [
        {"id": "z/one", "sha": "1", "config": good},
        {"id": "a/two", "sha": "2", "config": good},
        {"id": "m/big", "sha": "3", "config": {**good, "r": 64}},
    ]
    res = select_real_adapters(cands, rank=16, target_modules=ALL, count=2)
    assert res["selected"] == [("a/two", "2"), ("z/one", "1")]
    assert set(res["rejected"]) == {"m/big"} and res["enough"]
    assert select_real_adapters(cands, rank=16, target_modules=ALL, count=3)["enough"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_adapters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.adapters'`.

- [ ] **Step 3: Create `multilora/adapters.py`**

```python
"""Synthetic LoRA adapters, written in the PEFT on-disk format.

For serving cost only shape matters -- rank and which modules are wrapped --
never the values inside (amendment §5 of the August design; the equivalence
gate checks it rather than asserting it). So the sweep's adapters are drawn
from a seeded normal distribution at a fixed scale, written where the worker
serves them, and identified by a checksum stored with the run.

Shapes come from the base model's own `config.json`, not from a table in this
file, so the writer cannot disagree with the checkpoint it is written for.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from safetensors import safe_open
from safetensors.numpy import save_file

# Fixed, and recorded here rather than per run: the weights must be identical
# across instances for a checksum to mean anything. 0.01 keeps activations near
# the base model's, which matters only for generated text -- serving cost does
# not depend on it, and ignore-EOS fixes output length regardless.
INIT_STD = 0.01

_ATTENTION = ("q_proj", "k_proj", "v_proj", "o_proj")
_MLP = ("gate_proj", "up_proj", "down_proj")


def module_shapes(config: dict) -> dict[str, tuple[int, int]]:
    """(in_features, out_features) per projection, from a HF decoder config."""
    hidden = config["hidden_size"]
    heads = config["num_attention_heads"]
    kv_heads = config.get("num_key_value_heads", heads)
    head_dim = config.get("head_dim") or hidden // heads
    inter = config["intermediate_size"]
    return {
        "q_proj": (hidden, heads * head_dim),
        "k_proj": (hidden, kv_heads * head_dim),
        "v_proj": (hidden, kv_heads * head_dim),
        "o_proj": (heads * head_dim, hidden),
        "gate_proj": (hidden, inter),
        "up_proj": (hidden, inter),
        "down_proj": (inter, hidden),
    }


def _module_path(layer: int, module: str) -> str:
    block = "self_attn" if module in _ATTENTION else "mlp"
    return f"base_model.model.model.layers.{layer}.{block}.{module}"


def adapter_parameter_count(config: dict, rank: int, target_modules) -> int:
    shapes = module_shapes(config)
    per_layer = sum(rank * (shapes[m][0] + shapes[m][1]) for m in target_modules)
    return per_layer * config["num_hidden_layers"]


def write_synthetic_adapter(
    path,
    *,
    config: dict,
    base_model: str,
    rank: int,
    target_modules,
    seed: int,
) -> str:
    """Write one adapter directory and return its sha256 checksum."""
    unknown = set(target_modules) - set(_ATTENTION + _MLP)
    if unknown:
        raise ValueError(f"unsupported target modules {sorted(unknown)}")
    if rank <= 0:
        raise ValueError(f"rank must be positive, got {rank}")
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    shapes = module_shapes(config)
    rng = np.random.default_rng(seed)
    tensors: dict[str, np.ndarray] = {}
    for layer in range(config["num_hidden_layers"]):
        for module in sorted(target_modules):
            in_f, out_f = shapes[module]
            prefix = _module_path(layer, module)
            tensors[f"{prefix}.lora_A.weight"] = (
                rng.standard_normal((rank, in_f), dtype=np.float32) * INIT_STD
            ).astype(np.float16)
            tensors[f"{prefix}.lora_B.weight"] = (
                rng.standard_normal((out_f, rank), dtype=np.float32) * INIT_STD
            ).astype(np.float16)
    save_file(tensors, str(path / "adapter_model.safetensors"))
    adapter_config = {
        "base_model_name_or_path": base_model,
        "bias": "none",
        "fan_in_fan_out": False,
        "inference_mode": True,
        "lora_alpha": rank,
        "lora_dropout": 0.0,
        "peft_type": "LORA",
        "r": rank,
        "target_modules": sorted(target_modules),
        "task_type": "CAUSAL_LM",
    }
    (path / "adapter_config.json").write_text(json.dumps(adapter_config, sort_keys=True))
    return adapter_checksum(path)


def adapter_checksum(path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        digest.update((path / name).read_bytes())
    return digest.hexdigest()


def inspect_adapter(path) -> dict:
    """Rank and wrapped modules of any PEFT adapter on disk, real or synthetic.
    Used to check a public adapter qualifies for the gate (R10)."""
    path = Path(path)
    cfg = json.loads((path / "adapter_config.json").read_text())
    modules: set[str] = set()
    with safe_open(str(path / "adapter_model.safetensors"), framework="numpy") as f:
        keys = list(f.keys())
    for key in keys:
        parts = key.split(".")
        if "lora_A" in parts:
            modules.add(parts[parts.index("lora_A") - 1])
    return {"rank": cfg["r"], "target_modules": sorted(modules), "tensors": len(keys)}


def real_adapter_qualifies(adapter_config: dict, *, rank: int, target_modules) -> tuple[bool, str]:
    """Whether a public adapter can stand in the equivalence gate (R10).

    Its rank must not exceed `max_lora_rank`, because the kernel runs at the
    buffer rank and a larger adapter would not load. Its modules must be a
    subset of the fixed set, so it occupies the same wrapped layers."""
    if adapter_config.get("peft_type") != "LORA":
        return False, f"peft_type is {adapter_config.get('peft_type')!r}, not LORA"
    r = adapter_config.get("r")
    if not isinstance(r, int) or r > rank:
        return False, f"rank {r!r} exceeds max_lora_rank {rank}"
    modules = adapter_config.get("target_modules") or []
    if isinstance(modules, str):
        return False, f"target_modules is a pattern {modules!r}, not a list"
    extra = sorted(set(modules) - set(target_modules))
    if extra:
        return False, f"targets modules outside the fixed set: {extra}"
    return True, "qualifies"


def select_real_adapters(candidates, *, rank: int, target_modules, count: int) -> dict:
    """Pick `count` qualifying public adapters, deterministically: sorted by
    repo id, so rerunning the search cannot quietly pick different adapters.
    `candidates` is [{"id", "sha", "config"}]; every rejection keeps its reason."""
    selected, rejected = [], {}
    for c in sorted(candidates, key=lambda c: c["id"]):
        ok, reason = real_adapter_qualifies(c["config"], rank=rank, target_modules=target_modules)
        if ok and len(selected) < count:
            selected.append((c["id"], c["sha"]))
        elif not ok:
            rejected[c["id"]] = reason
    return {"selected": selected, "rejected": rejected, "enough": len(selected) == count}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_adapters.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/adapters.py tests/test_multilora_adapters.py
git commit -m "feat: seeded synthetic LoRA adapters in PEFT format, shaped from the model config"
```

---

## Task 8: Engine facts from a startup log

The compile-cache state is classified from each instance's own log, not from the cache directory (amendment §3d). The tests use artifact 1's committed logs: one cold compile at 38.96 s, and warm starts at 0.30 s and 0.29 s.

**Files:**
- Create: `multilora/engine.py`, `tests/test_multilora_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_engine.py`:

```python
from pathlib import Path

from multilora.engine import compile_state, engine_facts

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "vllm_logs"


def _lines(name: str) -> list[str]:
    return (LOGS / name).read_text().splitlines()


def test_a_first_ever_compile_is_cold_and_names_its_cache_directory():
    facts = engine_facts(_lines("startup_0.log"))
    assert facts["compile_state"] == "cold"
    assert facts["s4b_seconds"] == 38.96
    assert facts["kv_capacity_tokens"] == 35_792
    assert facts["cache_dir"].endswith("/torch_compile_cache/905735a5a3/rank_0_0/backbone")


def test_a_cache_hit_is_warm():
    facts = engine_facts(_lines("startup_1.log"))
    assert facts["compile_state"] == "warm"
    assert facts["kv_capacity_tokens"] == 43_040


def test_a_log_without_a_compile_line_is_unknown_not_warm():
    assert engine_facts(["some unrelated line"])["compile_state"] == "unknown"


def test_the_threshold_is_artifact_ones_priming_criterion():
    assert compile_state(0.99) == "warm"
    assert compile_state(1.0) == "cold"
    assert compile_state(None) == "unknown"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.engine'`.

- [ ] **Step 3: Create `multilora/engine.py`**

```python
"""Engine facts read from one instance's startup log.

KV capacity, version and model come from the harness parser unchanged. Two
facts are added for artifact 5:

- Whether the torch.compile cache was warm (amendment §3d). The compile cache
  is keyed on `max_loras`, so each sweep point has its own directory under one
  root, and a directory-exists check would read warm for every point after the
  first priming run. The log is per instance and cannot be fooled that way.
- The cache directory the engine used, which carries the configuration hash,
  recorded so a surprising instance can be traced to the cache it hit.
"""

import re

from harness.vllm_logs import parse_engine_log

# Artifact 1's priming criterion (docs/experiment.md): a warm compile cache
# brings `torch.compile took ... s in total` under one second. Its committed
# logs show 38.96 s cold and 0.29-0.30 s warm.
WARM_S4B_MAX_SECONDS = 1.0

_CACHE_DIR = re.compile(r"Using cache directory: (?P<path>\S+)")


def compile_state(s4b_seconds: float | None) -> str:
    if s4b_seconds is None:
        return "unknown"
    return "warm" if s4b_seconds < WARM_S4B_MAX_SECONDS else "cold"


def engine_facts(log_lines: list[str]) -> dict:
    text = "\n".join(log_lines)
    parsed = parse_engine_log(text)
    s4b = parsed.phases.get("S4b")
    m = _CACHE_DIR.search(text)
    return {
        **parsed.engine_info,
        "s4b_seconds": s4b,
        "compile_state": compile_state(s4b),
        "cache_dir": m.group("path") if m else None,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_engine.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/engine.py tests/test_multilora_engine.py
git commit -m "feat: read compile-cache state from each instance's own startup log"
```

---

## Task 9: The instance record and the job payload

`records.py` documents the payload contract the worker returns. `multilora/instance.py` (Task 17) implements it, and the stub in Task 14 mimics it. `campaign.py` builds what each job asks the worker to do, and the priming payloads plan 3 submits before the campaign.

**Files:**
- Create: `multilora/records.py`, `multilora/campaign.py`, `tests/test_multilora_records.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_records.py`:

```python
from pathlib import Path

from harness.scheduler import ScheduledRun
from harness.store import JsonlStore
from harness.submit import SubmitOutcome
from multilora import SCHEMA_VERSION
from multilora.campaign import job_payload
from multilora.records import InstanceRecord, build_record

LOG = (Path(__file__).resolve().parents[1] / "fixtures/vllm_logs/startup_1.log").read_text()


def test_an_ok_outcome_becomes_a_record_with_engine_facts():
    payload = {
        "healthy": True,
        "log_lines": LOG.splitlines(),
        "served_cmd": ["vllm", "serve"],
        "host": {"host_id": "w1", "vcpus": 16},
        "adapters": {"a00": "abc"},
        "phases": [{"phase_index": 0}],
        "gauge_samples": [],
    }
    rec = build_record(
        ScheduledRun(3, 1, "sweep-N1"), "run-x",
        SubmitOutcome(clock_A={"t_submit": 1.0, "t_result": 2.0}, payload=payload, error=None),
    )
    assert rec.outcome == "ok" and rec.schema_version == SCHEMA_VERSION
    assert (rec.run_index, rec.block_index, rec.condition) == (3, 1, "sweep-N1")
    assert rec.engine["compile_state"] == "warm"
    assert rec.engine["kv_capacity_tokens"] == 43_040
    assert rec.host["vcpus"] == 16


def test_a_failed_outcome_is_a_classified_record_with_its_evidence():
    rec = build_record(
        ScheduledRun(0, 0, "gate"), "run-y",
        SubmitOutcome(
            clock_A={"t_submit": 0.0, "t_result": 9.0},
            payload=None,
            error="health check timed out: probe reported unhealthy",
            diagnostics={"log_lines": ["CUDA out of memory"]},
        ),
    )
    assert rec.outcome == "failed"
    assert rec.failure_class == "health_timeout"
    assert rec.diagnostics == {"log_lines": ["CUDA out of memory"]}
    assert rec.phases == []


def test_records_round_trip_through_the_harness_store(tmp_path):
    store = JsonlStore(tmp_path / "a5.jsonl", InstanceRecord)
    rec = InstanceRecord(1, 0, 0, "sweep-N2", "r", "ok", None, None, {"t_submit": 0.0},
                         engine={"compile_state": "warm"})
    store.append(rec)
    assert store.read_all() == [rec]


def test_the_job_payload_carries_everything_the_worker_needs(prereg):
    payload = job_payload(ScheduledRun(5, 0, "diag-N16"), "run-z", prereg)
    assert payload["n_slots"] == 16
    assert payload["registered"] == [f"a{i:02d}" for i in range(16)]
    assert payload["specialize_active_lora"] is True
    assert payload["disable_log_stats"] is False
    assert payload["concurrency"] == prereg.concurrency
    assert payload["requests_per_phase"] == prereg.requests_per_phase
    assert len(payload["phases"]) == 4
    assert {p["regime"] for p in payload["phases"]} == {"concentrated", "spread"}
    assert payload["dataset_args"] == list(prereg.bench_dataset_args)
    assert payload["real_adapters"] == []


def test_a_gate_payload_names_each_real_adapter_and_its_revision(prereg):
    payload = job_payload(ScheduledRun(0, 0, "gate"), "run-g", prereg)
    assert payload["n_slots"] == 8
    assert payload["real_adapters"][0] == {
        "name": "r00", "repo": "example/adapter-0", "revision": "rev0",
    }
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_records.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.records'`.

- [ ] **Step 3: Create `multilora/records.py`**

```python
"""One server instance's stored result, and how it is built from a job outcome.

The worker returns, for a healthy instance (plan 3 implements it; the stub in
this package mimics it):

    healthy        True
    log_lines      the engine's startup output
    served_cmd     the exact `vllm serve` argument list
    host           host_id, gpu_model, vcpus (the submitter adds platform ids)
    adapters       {adapter name: sha256 checksum}
    phases         one dict per timed phase: phase_index, regime, adapters,
                   concurrency, num_requests, duration_s, completed, failed,
                   and the tool's raw per-request ttfts, output_lens, errors
    gauge_samples  {phase_index, t, running} per scrape

Raw arrays are stored unaltered. Amendment §3f's rules are applied at analysis
time, in `multilora.phase`, so a rule can be audited against the data it ran on.
"""

from dataclasses import asdict, dataclass, field

from harness.failures import classify_failure
from multilora import SCHEMA_VERSION
from multilora.engine import engine_facts


@dataclass
class InstanceRecord:
    schema_version: int
    run_index: int
    block_index: int
    condition: str
    run_id: str
    outcome: str  # "ok" | "failed"
    failure: str | None
    failure_class: str | None
    clock_A: dict
    host: dict = field(default_factory=dict)
    engine: dict = field(default_factory=dict)
    served_cmd: list = field(default_factory=list)
    adapters: dict = field(default_factory=dict)
    phases: list = field(default_factory=list)
    gauge_samples: list = field(default_factory=list)
    diagnostics: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InstanceRecord":
        return cls(**d)


def build_record(scheduled, run_id: str, outcome) -> InstanceRecord:
    """A failed job is a record too: failures are data, and the failure-rate
    table counts them. Its evidence travels in `diagnostics`."""
    common = {
        "schema_version": SCHEMA_VERSION,
        "run_index": scheduled.run_index,
        "block_index": scheduled.block_index,
        "condition": scheduled.condition,
        "run_id": run_id,
        "clock_A": outcome.clock_A,
    }
    if outcome.payload is None:
        return InstanceRecord(
            **common,
            outcome="failed",
            failure=outcome.error,
            failure_class=classify_failure(outcome.error).value,
            diagnostics=outcome.diagnostics,
        )
    p = outcome.payload
    return InstanceRecord(
        **common,
        outcome="ok",
        failure=None,
        failure_class=None,
        host=dict(p.get("host") or {}),
        engine=engine_facts(p.get("log_lines") or []),
        served_cmd=list(p.get("served_cmd") or []),
        adapters=dict(p.get("adapters") or {}),
        phases=list(p.get("phases") or []),
        gauge_samples=list(p.get("gauge_samples") or []),
    )
```

- [ ] **Step 4: Create `multilora/campaign.py`**

```python
"""Artifact 5's use of the harness campaign loop: what one job asks the worker
to do, and how its outcome becomes a stored record."""

from harness.campaign import run_campaign
from harness.scheduler import ScheduledRun
from multilora.conditions import (
    GATE,
    SWEEP,
    condition_name,
    parse_condition,
    phase_plan,
    real_name,
    registered_adapters,
)
from multilora.prereg import Preregistration
from multilora.records import build_record


def job_payload(scheduled, run_id: str, prereg: Preregistration) -> dict:
    condition = parse_condition(scheduled.condition, prereg)
    return {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "condition": condition.name,
        "n_slots": condition.n_slots,
        "registered": list(registered_adapters(condition, prereg)),
        "specialize_active_lora": condition.specialize_active_lora,
        "disable_log_stats": condition.disable_log_stats,
        "phases": [
            {"phase_index": p.phase_index, "regime": p.regime, "adapters": list(p.adapters)}
            for p in phase_plan(condition, prereg, scheduled.run_index)
        ],
        "concurrency": prereg.concurrency,
        "requests_per_phase": prereg.requests_per_phase,
        "warmup_requests_per_adapter": prereg.warmup_requests_per_adapter,
        "scrape_interval_s": prereg.scrape_interval_s,
        "adapter_seed": prereg.schedule_seed,
        "dataset_args": list(prereg.bench_dataset_args),
        "real_adapters": [
            {"name": real_name(i), "repo": repo, "revision": revision}
            for i, (repo, revision) in enumerate(prereg.real_adapters)
        ]
        if condition.kind == GATE
        else [],
    }


def run(schedule, submitter, store, prereg: Preregistration, *, resume=False, on_run=None):
    """`submitter` is anything with `submit_payload(payload) -> SubmitOutcome`:
    the harness RunPod submitter, or `harness.submit.PayloadStubSubmitter`
    around `multilora.stub.StubInstanceEndpoint.run`."""
    return run_campaign(
        schedule,
        lambda scheduled, run_id: submitter.submit_payload(job_payload(scheduled, run_id, prereg)),
        build_record,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        on_run=on_run,
        resume=resume,
    )


def priming_payloads(prereg: Preregistration) -> list[tuple[ScheduledRun, dict]]:
    """Two untimed starts per sweep point (amendment §3d). The compile cache is
    keyed on max_loras, so each point compiles on its first start; the second
    must then read warm. Priming runs go to their own store and are never data."""
    out = []
    index = 0
    for n in prereg.sweep:
        for attempt in (0, 1):
            scheduled = ScheduledRun(index, attempt, condition_name(SWEEP, n))
            payload = job_payload(scheduled, f"prime-N{n}-{attempt}", prereg)
            payload["phases"] = []
            payload["warmup_requests_per_adapter"] = 1
            out.append((scheduled, payload))
            index += 1
    return out


def priming_verdict(records) -> dict:
    """Per sweep point: the second start must be warm. Anything else means the
    campaign would open on cold compiles, and must not start."""
    by_n: dict[str, dict] = {}
    for rec in records:
        state = rec.engine.get("compile_state") if rec.outcome == "ok" else "failed"
        by_n.setdefault(rec.condition, {})[rec.block_index] = state
    return {
        cond: {"first": s.get(0), "second": s.get(1), "ok": s.get(1) == "warm"}
        for cond, s in by_n.items()
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_records.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add multilora/records.py multilora/campaign.py tests/test_multilora_records.py
git commit -m "feat: the instance record, its builder, and the job payload"
```

---

## Task 10: The failure rule and per-regime summaries

This is amendment §3f in code. It applies to the stored raw arrays, so a rule can always be audited against the data it ran on.

**Files:**
- Create: `multilora/phase.py`, `tests/test_multilora_phase.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_phase.py`:

```python
import pytest

from multilora.phase import (
    PhaseCountMismatch,
    check_counts,
    is_failure,
    phase_summaries,
    successful,
    summarize,
)
from multilora.records import InstanceRecord


def phase(ttfts, lens, errors, *, duration=10.0, index=0, regime="spread", completed=None, failed=None):
    ok = sum(1 for t, n, e in zip(ttfts, lens, errors) if not is_failure(t, n, e))
    return {
        "phase_index": index,
        "regime": regime,
        "ttfts": ttfts,
        "output_lens": lens,
        "errors": errors,
        "duration_s": duration,
        "completed": ok if completed is None else completed,
        "failed": len(ttfts) - ok if failed is None else failed,
    }


def test_three_kinds_of_failure_are_removed():
    p = phase([0.1, 0.0, 0.2, 0.3], [16, 16, 0, 16], ["", "", "", "boom"])
    assert successful(p) == ([0.1], [16])


def test_an_empty_error_string_with_zero_ttft_is_still_a_failure():
    """vLLM 0.27.1 records some failures as error=\"\" with ttft 0.0."""
    assert is_failure(0.0, 16, "")


def test_counts_that_agree_pass():
    check_counts(phase([0.1, 0.0], [16, 16], ["", ""]))


def test_counts_that_disagree_fail_the_phase():
    p = phase([0.1, 0.0], [16, 16], ["", ""], completed=2, failed=0)
    with pytest.raises(PhaseCountMismatch, match="tool reports 2 completed"):
        check_counts(p)


def test_mismatched_array_lengths_are_refused():
    with pytest.raises(ValueError, match="differ in length"):
        successful(phase([0.1], [16, 16], [""]))


def test_throughput_is_total_tokens_over_total_duration():
    a = phase([0.1] * 50, [16] * 50, [""] * 50, duration=10.0)
    b = phase([0.2] * 50, [16] * 50, [""] * 50, duration=6.0)
    s = summarize([a, b])
    assert s["throughput_tps"] == pytest.approx(100 * 16 / 16.0)
    assert s["request_rate"] == pytest.approx(100 / 16.0)
    assert s["ttft_p50"] == pytest.approx(0.15)
    assert s["n_ok"] == 100 and s["n_failed"] == 0


def test_failed_requests_do_not_enter_ttft_or_throughput():
    p = phase([0.1] * 90 + [0.0] * 10, [16] * 90 + [16] * 10, [""] * 100, duration=9.0)
    s = summarize([p])
    assert s["n_failed"] == 10
    assert s["throughput_tps"] == pytest.approx(90 * 16 / 9.0)


def test_p95_needs_the_sample_floor():
    with pytest.raises(ValueError, match="p95 requires at least 80"):
        summarize([phase([0.1] * 40, [16] * 40, [""] * 40)])


def test_phase_summaries_are_in_phase_order():
    rec = InstanceRecord(
        1, 0, 0, "gate", "r", "ok", None, None, {},
        phases=[
            phase([0.3] * 80, [16] * 80, [""] * 80, index=2, regime="real"),
            phase([0.1] * 80, [16] * 80, [""] * 80, index=0, regime="real"),
            phase([0.9] * 80, [16] * 80, [""] * 80, index=1, regime="synthetic"),
        ],
    )
    assert [s["ttft_p50"] for s in phase_summaries(rec, "real")] == [0.1, 0.3]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_phase.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.phase'`.

- [ ] **Step 3: Create `multilora/phase.py`**

```python
"""Amendment §3f's rules for reading one phase of `vllm bench serve` output,
and the per-instance summaries every estimand is built from.

A request is a failure if its error string is non-empty, OR its TTFT is 0.0,
OR its output length is 0. vLLM 0.27.1 records some failures with an empty
error string and saves no per-request success flag, so the error field alone
undercounts. The tool's own completed/failed counts are the cross-check: a
phase whose counts disagree with this rule is not trusted at all.
"""

from harness.stats import percentiles


class PhaseCountMismatch(ValueError):
    """The failure rule and the tool's own counts disagree for a phase."""


def is_failure(ttft: float, output_len: int, error: str) -> bool:
    return bool(error) or ttft == 0.0 or output_len == 0


def successful(phase: dict) -> tuple[list[float], list[int]]:
    ttfts, lens, errors = phase["ttfts"], phase["output_lens"], phase["errors"]
    if not (len(ttfts) == len(lens) == len(errors)):
        raise ValueError(
            f"phase {phase.get('phase_index')}: per-request arrays differ in length "
            f"({len(ttfts)}, {len(lens)}, {len(errors)})"
        )
    ok = [i for i in range(len(ttfts)) if not is_failure(ttfts[i], lens[i], errors[i])]
    return [ttfts[i] for i in ok], [lens[i] for i in ok]


def check_counts(phase: dict) -> None:
    ok_ttfts, _ = successful(phase)
    n_ok = len(ok_ttfts)
    n_failed = len(phase["ttfts"]) - n_ok
    if (n_ok, n_failed) != (phase["completed"], phase["failed"]):
        raise PhaseCountMismatch(
            f"phase {phase.get('phase_index')}: the failure rule finds {n_ok} ok and "
            f"{n_failed} failed, the tool reports {phase['completed']} completed and "
            f"{phase['failed']} failed"
        )


def summarize(phases: list[dict]) -> dict:
    """TTFT percentiles over the successful requests of `phases`, and
    throughput as total successful output tokens over total phase duration."""
    if not phases:
        raise ValueError("no phases to summarize")
    ttfts: list[float] = []
    tokens = 0
    n_ok = 0
    n_total = 0
    duration = 0.0
    for phase in phases:
        ok_ttfts, ok_lens = successful(phase)
        ttfts += ok_ttfts
        tokens += sum(ok_lens)
        n_ok += len(ok_ttfts)
        n_total += len(phase["ttfts"])
        duration += phase["duration_s"]
    if duration <= 0:
        raise ValueError("phase duration must be positive")
    pct = percentiles(ttfts, want=("p50", "p95"))
    return {
        "ttft_p50": pct["p50"],
        "ttft_p95": pct["p95"],
        "throughput_tps": tokens / duration,
        "request_rate": n_ok / duration,
        "n_ok": n_ok,
        "n_failed": n_total - n_ok,
    }


def regime_summary(record, regime: str) -> dict:
    return summarize([p for p in record.phases if p["regime"] == regime])


def phase_summaries(record, regime: str) -> list[dict]:
    """One summary per phase of `regime`, in phase order. The gate's resolution
    check compares a regime's first phase with its second (amendment §4)."""
    phases = sorted(
        (p for p in record.phases if p["regime"] == regime), key=lambda p: p["phase_index"]
    )
    return [summarize([p]) for p in phases]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_phase.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/phase.py tests/test_multilora_phase.py
git commit -m "feat: the three-way failure rule, the count cross-check, and regime summaries"
```

---

## Task 11: The manipulation check

The parser reads one scrape; the sampler scrapes on an interval while phases run and tags each sample with the phase the caller says is current.

**Files:**
- Create: `multilora/gauge.py`, `multilora/sampler.py`, `tests/test_multilora_gauge.py`, `tests/test_multilora_sampler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_gauge.py`:

```python
from multilora.gauge import distinct_running, running_adapters
from multilora.records import InstanceRecord

SCRAPE = """# HELP vllm:lora_requests_info Running stats on lora requests.
# TYPE vllm:lora_requests_info gauge
vllm:lora_requests_info{max_lora="16",running_lora_adapters="a00",waiting_lora_adapters=""} 1.7590001e+09
vllm:lora_requests_info{max_lora="16",running_lora_adapters="a03,a01,a02",waiting_lora_adapters="a04"} 1.7590009e+09
vllm:lora_requests_info{max_lora="16",running_lora_adapters="",waiting_lora_adapters=""} 1.7590005e+09
vllm:num_requests_running{model_name="m"} 3.0
"""


def test_the_newest_series_is_the_current_state():
    assert running_adapters(SCRAPE) == ["a01", "a02", "a03"]


def test_an_absent_gauge_is_none_not_empty():
    assert running_adapters("vllm:num_requests_running 3.0\n") is None


def test_an_idle_scheduler_is_an_empty_list():
    idle = 'vllm:lora_requests_info{max_lora="4",running_lora_adapters="",waiting_lora_adapters=""} 5.0\n'
    assert running_adapters(idle) == []


def test_distinct_running_is_per_regime_and_skips_missing_samples():
    rec = InstanceRecord(
        1, 0, 0, "sweep-N4", "r", "ok", None, None, {},
        phases=[{"phase_index": 0, "regime": "spread"}, {"phase_index": 1, "regime": "concentrated"}],
        gauge_samples=[
            {"phase_index": 0, "t": 1.0, "running": ["a00", "a01", "a02"]},
            {"phase_index": 0, "t": 2.0, "running": None},
            {"phase_index": 1, "t": 3.0, "running": ["a00"]},
        ],
    )
    assert distinct_running(rec, "spread") == [3]
    assert distinct_running(rec, "concentrated") == [1]
```

Create `tests/test_multilora_sampler.py`:

```python
from multilora.sampler import GaugeSampler

SCRAPE = (
    'vllm:lora_requests_info{max_lora="4",running_lora_adapters="a01,a00",'
    'waiting_lora_adapters=""} 9.0\n'
)


def test_nothing_is_recorded_between_phases():
    s = GaugeSampler(lambda: SCRAPE, interval=1.0, clock=lambda: 5.0)
    s.sample_once()
    assert s.samples == []


def test_a_sample_is_tagged_with_the_current_phase():
    s = GaugeSampler(lambda: SCRAPE, interval=1.0, clock=lambda: 5.0)
    s.set_phase(2)
    s.sample_once()
    assert s.samples == [{"phase_index": 2, "t": 5.0, "running": ["a00", "a01"]}]


def test_a_failed_scrape_is_a_recorded_gap():
    def boom():
        raise OSError("connection refused")

    s = GaugeSampler(boom, interval=1.0, clock=lambda: 1.0)
    s.set_phase(0)
    s.sample_once()
    assert s.samples == [{"phase_index": 0, "t": 1.0, "running": None}]


def test_the_thread_samples_until_exit():
    s = GaugeSampler(lambda: SCRAPE, interval=0.01)
    s.set_phase(1)
    with s:
        import time

        time.sleep(0.1)
    count = len(s.samples)
    assert count >= 3
    assert all(x["phase_index"] == 1 for x in s.samples)
    import time

    time.sleep(0.05)
    assert len(s.samples) == count, "no samples after exit"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multilora_gauge.py tests/test_multilora_sampler.py -v`
Expected: FAIL with `ModuleNotFoundError` for `multilora.gauge` and `multilora.sampler`.

- [ ] **Step 3: Create `multilora/gauge.py`**

```python
"""The manipulation check: which adapters the scheduler was running, sampled
from vLLM's `vllm:lora_requests_info` gauge (amendment §3a).

The gauge encodes its state in label values and stamps each update with the
current time as its value. The Prometheus client keeps every label combination
it has ever seen, so a scrape returns many series; the current state is the
one with the newest timestamp. This is a sample of scheduler state at each
scrape, not a count per batch, and is published under that name.
"""

import re

_SERIES = re.compile(r"^vllm:lora_requests_info\{(?P<labels>[^}]*)\}\s+(?P<value>\S+)", re.MULTILINE)
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def running_adapters(metrics_text: str) -> list[str] | None:
    """Adapters in the newest `running_lora_adapters` label, sorted. None when
    the gauge is absent, as it is with `--disable-log-stats`."""
    newest: tuple[float, str] | None = None
    for m in _SERIES.finditer(metrics_text):
        labels = dict(_LABEL.findall(m.group("labels")))
        value = float(m.group("value"))
        if newest is None or value > newest[0]:
            newest = (value, labels.get("running_lora_adapters", ""))
    if newest is None:
        return None
    return sorted(a for a in newest[1].split(",") if a)


def distinct_running(record, regime: str) -> list[int]:
    """Distinct running adapters at each scrape during `regime`'s phases."""
    phases = {p["phase_index"] for p in record.phases if p["regime"] == regime}
    return [
        len(s["running"])
        for s in record.gauge_samples
        if s["phase_index"] in phases and s["running"] is not None
    ]
```

- [ ] **Step 4: Create `multilora/sampler.py`**

```python
"""Samples vLLM's LoRA gauge on a fixed interval while load runs (amendment §3a).

A background thread scrapes `/metrics` every `interval` seconds and records the
running adapter set against whichever phase the caller says is current. The
caller owns phase boundaries; the sampler never guesses them. A scrape that
fails is recorded as `running: None` rather than skipped, so a gap in the
manipulation check is visible in the record.
"""

import threading
import time
from collections.abc import Callable
from typing import Self

from multilora.gauge import running_adapters


class GaugeSampler:
    def __init__(
        self,
        fetch_metrics: Callable[[], str],
        interval: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        if interval <= 0:
            raise ValueError(f"interval must be positive, got {interval}")
        self._fetch = fetch_metrics
        self._interval = interval
        self._clock = clock
        self._phase: int | None = None
        self._samples: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_phase(self, phase_index: int | None) -> None:
        """`None` between phases: nothing is recorded while no phase runs."""
        with self._lock:
            self._phase = phase_index

    def sample_once(self) -> None:
        with self._lock:
            phase = self._phase
        if phase is None:
            return
        try:
            running = running_adapters(self._fetch())
        except Exception:  # noqa: BLE001 -- a failed scrape is a recorded gap
            running = None
        with self._lock:
            self._samples.append({"phase_index": phase, "t": self._clock(), "running": running})

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.sample_once()

    def __enter__(self) -> Self:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5 * self._interval + 5)

    @property
    def samples(self) -> list[dict]:
        with self._lock:
            return list(self._samples)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_gauge.py tests/test_multilora_sampler.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add multilora/gauge.py multilora/sampler.py tests/test_multilora_gauge.py tests/test_multilora_sampler.py
git commit -m "feat: read the running adapter set from vLLM's LoRA gauge, on an interval"
```

---

## Task 12: The knee and the equivalence gate

Both rules are fixed by amendment §4 before any data exists. Their thresholds come from the pre-registration.

**Files:**
- Create: `multilora/knee.py`, `multilora/gate.py`, `tests/test_multilora_knee.py`, `tests/test_multilora_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multilora_knee.py`:

```python
import pytest

from multilora.knee import knee


def _flat(value: float, n: int = 24) -> list[float]:
    return [value * (1 + 0.001 * ((i % 5) - 2)) for i in range(n)]


def test_a_flat_curve_has_no_knee_and_reports_the_top():
    res = knee({1: _flat(100), 2: _flat(99), 4: _flat(98)}, tau=0.10, iterations=200)
    assert res["knee"] is None and res["above_top"]
    assert res["slots_below_knee"] == 4


def test_the_first_doubling_whose_drop_exceeds_tau_is_the_knee():
    curve = {1: _flat(100), 2: _flat(99), 4: _flat(97), 8: _flat(80), 16: _flat(60)}
    res = knee(curve, tau=0.10, iterations=200)
    assert res["knee"] == {"lower": 4, "upper": 8}
    assert res["slots_below_knee"] == 4
    eight = next(d for d in res["doublings"] if d["n"] == 8)
    assert eight["point"] == pytest.approx(1 - 80 / 97, rel=1e-3)
    assert eight["crosses"] and eight["resolved"]


def test_a_noisy_crossing_still_sets_the_knee_but_is_marked_unresolved():
    noisy = [110.0 if i % 2 else 70.0 for i in range(24)]
    res = knee({1: _flat(100), 2: noisy}, tau=0.05, iterations=500)
    d = res["doublings"][0]
    assert d["crosses"] and not d["resolved"]
    assert res["knee"] == {"lower": 1, "upper": 2}


def test_a_sweep_without_doublings_is_refused():
    with pytest.raises(ValueError, match="doublings"):
        knee({1: _flat(1), 3: _flat(1)}, tau=0.1, iterations=200)
```

Create `tests/test_multilora_gate.py`:

```python
from multilora.gate import verdict


def _row(real: float, synth: float, real2: float) -> dict:
    return {
        "real": {"ttft_p50": real, "throughput_tps": 1000.0 / real},
        "synthetic": {"ttft_p50": synth, "throughput_tps": 1000.0 / synth},
        "real_phases": [
            {"ttft_p50": real, "throughput_tps": 1000.0 / real},
            {"ttft_p50": real2, "throughput_tps": 1000.0 / real2},
        ],
    }


def _rows(bias: float, jitter: float) -> list[dict]:
    rows = []
    for i in range(24):
        wobble = jitter * ((i % 5) - 2) / 2
        real = 0.10 * (1 + wobble)
        rows.append(_row(real, real * (1 + bias), real * (1 + wobble / 4)))
    return rows


def test_indistinguishable_adapters_pass():
    assert verdict(_rows(bias=0.0, jitter=0.01), delta=0.05, iterations=500)["verdict"] == "pass"


def test_a_bias_beyond_the_margin_fails():
    res = verdict(_rows(bias=0.2, jitter=0.01), delta=0.05, iterations=500)
    assert res["verdict"] == "fail"
    assert not res["metrics"]["ttft_p50"]["inside"]


def test_real_against_real_noise_wider_than_the_margin_is_inconclusive_not_a_pass():
    rows = []
    for i in range(24):
        real2 = 0.10 * (1.3 if i % 2 else 0.7)
        rows.append(_row(0.10, 0.10, real2))
    res = verdict(rows, delta=0.05, iterations=500)
    assert res["verdict"] == "inconclusive"
    assert res["alpha"] == 0.10
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multilora_knee.py tests/test_multilora_gate.py -v`
Expected: FAIL with `ModuleNotFoundError` for `multilora.knee` and `multilora.gate`.

- [ ] **Step 3: Create `multilora/knee.py`**

```python
"""The knee (amendment §4).

m(N) = 1 - T(N) / T(N/2), with T the spread regime's throughput. The knee is
the smallest N whose POINT estimate of m(N) exceeds tau, reported as the
interval (N/2, N] because the sweep resolves only doublings.

Point estimate, not significance: requiring the interval to clear tau would
miss a real but noisy drop and push the knee -- and tenants per GPU -- upward.
Whether each crossing is also resolved (its interval's lower bound above tau)
is reported beside it, descriptively, without a multiplicity correction.
"""

from harness.stats import bootstrap_function_of_medians


def knee(throughput_by_n: dict[int, list[float]], tau: float, iterations=10000, seed=0) -> dict:
    ns = sorted(throughput_by_n)
    for n in ns[1:]:
        if n // 2 not in throughput_by_n or n % 2:
            raise ValueError(f"sweep point {n} has no half-point; the knee needs doublings")
    doublings = []
    knee_upper = None
    for n in ns[1:]:
        res = bootstrap_function_of_medians(
            [throughput_by_n[n], throughput_by_n[n // 2]],
            lambda m: 1 - m[0] / m[1],
            iterations=iterations,
            seed=seed,
        )
        crosses = res["point"] > tau
        doublings.append(
            {"n": n, **res, "crosses": crosses, "resolved": crosses and res["lo"] > tau}
        )
        if crosses and knee_upper is None:
            knee_upper = n
    return {
        "tau": tau,
        "doublings": doublings,
        "knee": None if knee_upper is None else {"lower": knee_upper // 2, "upper": knee_upper},
        "slots_below_knee": ns[-1] if knee_upper is None else knee_upper // 2,
        "above_top": knee_upper is None,
    }
```

- [ ] **Step 4: Create `multilora/gate.py`**

```python
"""The equivalence gate (amendment §4).

Statistic, per instance: (synthetic - real) / real, each side aggregated over
its two phases, for TTFT p50 and throughput. Margin delta = tau / 2.

- pass: the 90% bootstrap interval of the median statistic lies inside
  +/- delta for both metrics -- two one-sided tests at the 5% level.
- inconclusive: the same statistic for the first real phase against the
  second does not fit inside +/- delta. The gate then cannot resolve delta,
  and "no difference found" would mean nothing. Single phases are noisier than
  the gate's two-phase aggregates, so this check is conservative.
- fail: otherwise.
"""

from harness.stats import bootstrap_median_ci
from multilora.conditions import REAL, SYNTHETIC

GATE_METRICS = ("ttft_p50", "throughput_tps")
ALPHA = 0.10


def _inside(ci: dict, delta: float) -> bool:
    return -delta < ci["lo"] and ci["hi"] < delta


def verdict(rows: list[dict], delta: float, iterations=10000, seed=0) -> dict:
    metrics = {}
    for m in GATE_METRICS:
        rel = [(r[SYNTHETIC][m] - r[REAL][m]) / r[REAL][m] for r in rows]
        resolution = [
            (r["real_phases"][1][m] - r["real_phases"][0][m]) / r["real_phases"][0][m]
            for r in rows
        ]
        ci = bootstrap_median_ci(rel, iterations=iterations, seed=seed, alpha=ALPHA)
        res_ci = bootstrap_median_ci(resolution, iterations=iterations, seed=seed, alpha=ALPHA)
        metrics[m] = {
            "statistic": ci,
            "per_instance": rel,
            "resolution": res_ci,
            "inside": _inside(ci, delta),
            "resolved": _inside(res_ci, delta),
        }
    if not all(v["resolved"] for v in metrics.values()):
        outcome = "inconclusive"
    elif all(v["inside"] for v in metrics.values()):
        outcome = "pass"
    else:
        outcome = "fail"
    return {"delta": delta, "alpha": ALPHA, "n": len(rows), "metrics": metrics, "verdict": outcome}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_knee.py tests/test_multilora_gate.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add multilora/knee.py multilora/gate.py tests/test_multilora_knee.py tests/test_multilora_gate.py
git commit -m "feat: the knee rule and the equivalence verdict, as pre-registered"
```

---

## Task 13: Tenants, cost, and the three-way table

Artifact 4's results arrive at `data/a4/cost_per_tenant.json` as a grid of rows with a pre-registered `reference` row, per the format agreed with artifact 4's session on 2026-09-26. This task reads that format. Plan 3 reads the real file.

**Files:**
- Create: `multilora/economics.py`, `tests/test_multilora_economics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_economics.py`:

```python
import math

import pytest

from multilora.economics import (
    HOURS_PER_MONTH,
    SECONDS_PER_MONTH,
    cost_per_tenant_month,
    tenant_peak_rate,
    tenants_per_gpu,
    three_way_table,
)
from tests.conftest import example_prereg


def test_peak_rate_scales_the_monthly_average():
    assert tenant_peak_rate(SECONDS_PER_MONTH, 3.0) == pytest.approx(3.0)


def test_slots_bind_when_throughput_and_memory_are_ample(prereg):
    res = tenants_per_gpu(
        slots_below_knee=16, request_rate=100.0, ttft_p95=0.5, max_concurrency=4000, prereg=prereg
    )
    assert res["binding"] == "slots" and res["tenants"] == 16
    assert not res["memory_binds"]


def test_throughput_binds_for_a_busy_tenant():
    busy = example_prereg(requests_per_tenant_month=SECONDS_PER_MONTH * 2.0, peak_to_average=1.0)
    res = tenants_per_gpu(
        slots_below_knee=64, request_rate=20.0, ttft_p95=0.5, max_concurrency=4000, prereg=busy
    )
    assert res["bounds"]["throughput"] == 10
    assert res["binding"] == "throughput"


def test_memory_is_littles_law_on_the_operating_point(prereg):
    res = tenants_per_gpu(
        slots_below_knee=64, request_rate=100.0, ttft_p95=0.5, max_concurrency=32, prereg=prereg
    )
    peak = tenant_peak_rate(prereg.requests_per_tenant_month, prereg.peak_to_average)
    assert res["bounds"]["memory"] == math.floor(32 * 100.0 / (prereg.concurrency * peak))
    assert res["memory_binds"]


def test_an_slo_miss_is_infeasible_not_zero(prereg):
    res = tenants_per_gpu(
        slots_below_knee=8, request_rate=100.0, ttft_p95=9.0, max_concurrency=4000, prereg=prereg
    )
    assert res["feasible"] is False and res["tenants"] is None


def test_cost_is_a_month_of_gpu_over_tenants():
    assert cost_per_tenant_month(2.0, 4) == pytest.approx(2.0 * HOURS_PER_MONTH / 4)
    with pytest.raises(ValueError):
        cost_per_tenant_month(2.0, 0)


def _a4(**row_overrides) -> dict:
    row = {
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
        **row_overrides,
    }
    return {
        "gpu_hourly_rate": 1.0,
        "n_models": 20,
        "reference": {"regime": "low-locality", "s": 1.1},
        "rows": [row, {**row, "s": 0.8, "dedicated_cost_per_tenant_month": 999.0}],
    }


def test_the_table_reads_artifact_fours_reference_row(prereg):
    table = three_way_table(16, prereg, _a4())
    assert [r["strategy"] for r in table] == ["dedicated", "swapped", "adapter"]
    assert table[0]["cost"] == 730.0
    assert table[0]["source"] == "artifact 4, low-locality regime, s = 1.1"
    assert table[-1]["upper_bound"] is True


def test_a_measured_sleep_mode_arm_becomes_a_fourth_row(prereg):
    table = three_way_table(16, prereg, _a4(sleep_mode_cost_per_tenant_month=60.0))
    assert [r["strategy"] for r in table] == ["dedicated", "swapped", "sleep mode", "adapter"]


def test_a_malformed_artifact_four_file_is_refused(prereg):
    with pytest.raises(ValueError, match="lack"):
        three_way_table(16, prereg, {"gpu_hourly_rate": 1.0})
    bad = _a4()
    bad["reference"] = {"regime": "high-locality", "s": 1.1}
    with pytest.raises(ValueError, match="matches 0 rows"):
        three_way_table(16, prereg, bad)
    with pytest.raises(ValueError, match="swapped_cost"):
        three_way_table(16, prereg, _a4(swapped_cost_per_tenant_month=None))
    with pytest.raises(ValueError, match="one rate"):
        three_way_table(16, prereg, {**_a4(), "gpu_hourly_rate": 2.5})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_economics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.economics'`.

- [ ] **Step 3: Create `multilora/economics.py`**

```python
"""Tenants per GPU and cost per tenant per month (amendment §4).

Three bounds on tenants, the smallest wins:

- by slots: the last sweep point below the knee. A lower bound, because vLLM's
  intended multi-tenant mode holds more adapters on the CPU than in slots
  (amendment §3a).
- by throughput: measured request throughput divided by one tenant's peak
  request rate, valid only if TTFT p95 at concurrency C meets the SLO.
- by memory: Little's law on the measured operating point. C concurrent
  requests sustaining request rate r spend W = C / r in the system, so a
  tenant's peak rate p occupies p x W concurrent slots, and the KV ceiling K
  holds K / (p x W) tenants -- which equals by_throughput x K / C.
"""

import math

HOURS_PER_MONTH = 365.0 * 24.0 / 12.0
SECONDS_PER_MONTH = HOURS_PER_MONTH * 3600.0

A4_KEYS = ("gpu_hourly_rate", "reference", "rows")


def tenant_peak_rate(requests_per_tenant_month: float, peak_to_average: float) -> float:
    return requests_per_tenant_month / SECONDS_PER_MONTH * peak_to_average


def tenants_per_gpu(
    *,
    slots_below_knee: int,
    request_rate: float,
    ttft_p95: float,
    max_concurrency: int,
    prereg,
) -> dict:
    peak = tenant_peak_rate(prereg.requests_per_tenant_month, prereg.peak_to_average)
    slo_met = ttft_p95 <= prereg.slo_ttft_p95_s
    if not slo_met:
        return {
            "feasible": False,
            "reason": f"TTFT p95 {ttft_p95:.3f} s exceeds the SLO {prereg.slo_ttft_p95_s} s at C",
            "tenants": None,
        }
    by_throughput = math.floor(request_rate / peak)
    by_memory = math.floor(max_concurrency * request_rate / (prereg.concurrency * peak))
    bounds = {"slots": slots_below_knee, "throughput": by_throughput, "memory": by_memory}
    binding = min(bounds, key=bounds.get)
    return {
        "feasible": True,
        "bounds": bounds,
        "binding": binding,
        "tenants": bounds[binding],
        "tenant_peak_rate": peak,
        "memory_binds": by_memory < by_throughput,
    }


def cost_per_tenant_month(gpu_hourly_rate: float, tenants: int) -> float:
    if tenants <= 0:
        raise ValueError(f"tenants must be positive, got {tenants}")
    return gpu_hourly_rate * HOURS_PER_MONTH / tenants


def a4_reference_row(a4: dict) -> dict:
    """Artifact 4's costs depend on the skew and locality grid point, so its
    results file names a reference point, fixed in its second pre-registration
    step. This returns that point's row, and refuses a file where the reference
    matches no row, several rows, or a row with a strategy not evaluable."""
    missing = [k for k in A4_KEYS if k not in a4]
    if missing:
        raise ValueError(f"artifact 4 results lack {missing}")
    ref = a4["reference"]
    matches = [r for r in a4["rows"] if r["regime"] == ref["regime"] and r["s"] == ref["s"]]
    if len(matches) != 1:
        raise ValueError(f"artifact 4's reference {ref} matches {len(matches)} rows, not 1")
    row = matches[0]
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        if row.get(key) is None:
            raise ValueError(f"artifact 4's reference row has no {key}")
    return row


def three_way_table(adapter_tenants: int, prereg, a4: dict) -> list[dict]:
    """Artifact 4's columns are consumed as committed data, never recomputed,
    and must share this artifact's GPU hourly rate. A sleep-mode column is
    included when artifact 4 measured one."""
    row = a4_reference_row(a4)
    if not math.isclose(a4["gpu_hourly_rate"], prereg.gpu_hourly_rate):
        raise ValueError(
            f"artifact 4 used ${a4['gpu_hourly_rate']}/h and this pre-registration "
            f"${prereg.gpu_hourly_rate}/h; the three columns must share one rate"
        )
    source = f"artifact 4, {row['regime']} regime, s = {row['s']}"
    table = [
        {"strategy": "dedicated", "cost": row["dedicated_cost_per_tenant_month"], "source": source},
        {"strategy": "swapped", "cost": row["swapped_cost_per_tenant_month"], "source": source},
    ]
    if row.get("sleep_mode_cost_per_tenant_month") is not None:
        table.append(
            {"strategy": "sleep mode", "cost": row["sleep_mode_cost_per_tenant_month"], "source": source}
        )
    table.append(
        {
            "strategy": "adapter",
            "cost": cost_per_tenant_month(prereg.gpu_hourly_rate, adapter_tenants),
            "source": "artifact 5",
            "upper_bound": True,
        }
    )
    return table
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_economics.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/economics.py tests/test_multilora_economics.py
git commit -m "feat: tenants per GPU from three bounds, and cost per tenant per month"
```

---

## Task 14: Estimands, the analysis, and the stub end to end

The estimands route every record through `harness.publish.partition`, and `publishable_counts` reports per condition whether the bootstrap floor is met before any analysis runs. The stub worker has known costs, so the end-to-end test checks that the analysis recovers them. This task has no failing-test step per module, because the end-to-end test is the specification for all three modules together.

**Files:**
- Create: `multilora/estimands.py`, `multilora/analysis.py`, `multilora/stub.py`, `tests/test_multilora_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_end_to_end.py`:

```python
"""The whole GPU-free path: schedule -> stub worker -> harness loop -> store ->
analysis. The stub's timing model has known costs, so the analysis must
recover them. Nothing here is data."""

import pytest

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.estimands import instance_rows, point_at
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint, StubModel
from tests.conftest import example_prereg

A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


def _collect(tmp_path, prereg, model, name):
    store = JsonlStore(tmp_path / f"{name}.jsonl", InstanceRecord)
    schedule = gate_schedule(prereg) if name == "gate" else campaign_schedule(prereg)
    run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(model, seed=1).run), store, prereg)
    return store.read_all()


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    prereg = example_prereg(knee_threshold=0.08)
    tmp = tmp_path_factory.mktemp("a5")
    records = _collect(tmp, prereg, StubModel(), "campaign")
    gate = _collect(tmp, prereg, StubModel(), "gate")
    return prereg, records, analyse(records, gate, prereg, a4=A4, iterations=300)


def test_every_scheduled_instance_is_stored(result):
    prereg, records, _ = result
    assert len(records) == 11 * prereg.instances_per_condition


def test_the_gate_passes_when_synthetic_and_real_are_the_same_model(result):
    assert result[2]["gate"]["verdict"] == "pass"


def test_heterogeneity_costs_throughput_and_grows_with_slots(result):
    sweep = result[2]["sweep"]
    costs = [point_at(sweep, n)["heterogeneity"]["throughput_tps"]["point"] for n in (2, 8, 64)]
    assert costs[0] < 0 and costs[0] > costs[1] > costs[2]


def test_the_recovered_heterogeneity_cost_matches_the_model_at_the_top(result):
    point = point_at(result[2]["sweep"], 64)
    conc = point["median"]["concentrated"]["throughput_tps"]
    expected = conc * ((1 - 0.05 * 6) * (1 - 0.01) - 1)
    assert point["heterogeneity"]["throughput_tps"]["point"] == pytest.approx(expected, rel=0.05)


def test_the_slot_overhead_diagnostic_recovers_most_of_the_slot_cost(result):
    by_n = {o["n_slots"]: o for o in result[2]["sweep"]["slot_overhead"]}
    overhead = by_n[64]["throughput_tps"]["point"]
    base = StubModel().base_tps
    assert overhead == pytest.approx(-base * 0.06 * 0.8, rel=0.25)


def test_memory_shrinks_with_slots_but_does_not_bind_at_this_shape(result):
    sweep = result[2]["sweep"]
    assert point_at(sweep, 64)["memory"]["kv_tokens"] < point_at(sweep, 1)["memory"]["kv_tokens"]
    assert point_at(sweep, 64)["memory"]["max_concurrency_request_shape"] > 64


def test_tenants_and_the_cost_table_are_produced(result):
    out = result[2]
    assert out["tenants"]["feasible"]
    assert out["tenants"]["tenants"] <= out["knee"]["slots_below_knee"]
    assert [r["strategy"] for r in out["cost_table"]] == ["dedicated", "swapped", "adapter"]


def test_failures_and_cold_compiles_are_counted_not_dropped(tmp_path):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    records = _collect(tmp_path, prereg, StubModel(fail_every=10, cold_compile_every=7), "campaign")
    parts = instance_rows(records, prereg)
    n = len(records)
    assert len(parts.failed) == n // 10
    assert len(parts.discarded) > 0
    assert all(r["exclusion_reason"] == "missing_compile_warm" for r in parts.discarded)
    assert len(parts.publishable) + len(parts.discarded) + len(parts.failed) == n



def test_the_analysis_is_json_with_string_keys_only(result):
    """data/a5/analysis.json is what the post and figures read. An integer key
    would silently become a string on the round trip and break every lookup."""
    import json

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert isinstance(key, str), f"non-string key {key!r}"
                walk(value)
        elif isinstance(obj, list | tuple):
            for value in obj:
                walk(value)

    walk(result[2])
    json.dumps(result[2])


def test_publishable_counts_flag_a_condition_below_the_floor(tmp_path):
    from multilora.estimands import publishable_counts

    prereg = example_prereg(include_diagnostic=False, include_control=False)
    records = _collect(tmp_path, prereg, StubModel(fail_every=3), "campaign")
    counts = publishable_counts(records, prereg)
    assert set(counts) == {f"sweep-N{n}" for n in prereg.sweep}
    assert all(c["failed"] > 0 for c in counts.values())
    assert any(not c["meets_floor"] for c in counts.values())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_end_to_end.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.analysis'`.

- [ ] **Step 3: Create `multilora/estimands.py`**

```python
"""Amendment §4's estimands, from stored records to intervals.

Every record passes through `harness.publish.partition` first, so a failed
instance, a cold-compiled instance and a phase whose counts disagree with the
failure rule are each counted and excluded rather than silently averaged in.

Paired quantities -- the heterogeneity cost -- are one difference per
instance, bootstrapped with `bootstrap_median_ci`. That is the same
computation as the harness's paired bootstrap, without its artifact-1 field
names (amendment §2). Quantities across instances are unpaired.
"""

from harness.publish import PartitionResult, partition
from harness.stats import (
    MIN_BOOTSTRAP_SAMPLES,
    bootstrap_function_of_medians,
    bootstrap_median_ci,
    bootstrap_median_diff,
    median,
)
from multilora.conditions import (
    CONCENTRATED,
    CONTROL,
    DIAGNOSTIC,
    GATE,
    REAL,
    SPREAD,
    SWEEP,
    SYNTHETIC,
    condition_name,
    parse_condition,
)
from multilora.phase import PhaseCountMismatch, check_counts, phase_summaries, regime_summary
from multilora.prereg import Preregistration

METRICS = ("throughput_tps", "ttft_p50", "ttft_p95")
REQUIRED = ("compile_warm", "counts_ok", "kv_capacity_tokens")


def instance_rows(records, prereg: Preregistration) -> PartitionResult:
    rows = []
    for rec in records:
        cond = parse_condition(rec.condition, prereg)
        row = {
            "ok": rec.outcome == "ok",
            "run_index": rec.run_index,
            "condition": rec.condition,
            "kind": cond.kind,
            "n_slots": cond.n_slots,
            "host_id": rec.host.get("host_id"),
            "failure_class": rec.failure_class,
        }
        if rec.outcome == "ok":
            row["compile_state"] = rec.engine.get("compile_state")
            row["compile_warm"] = True if row["compile_state"] == "warm" else None
            row["kv_capacity_tokens"] = rec.engine.get("kv_capacity_tokens")
            try:
                for phase in rec.phases:
                    check_counts(phase)
                row["counts_ok"] = True
            except PhaseCountMismatch as e:
                row["counts_ok"] = None
                row["count_mismatch"] = str(e)
            if row["counts_ok"]:
                regimes = (REAL, SYNTHETIC) if cond.kind == GATE else (CONCENTRATED, SPREAD)
                for regime in regimes:
                    row[regime] = regime_summary(rec, regime)
                if cond.kind == GATE:
                    row["real_phases"] = phase_summaries(rec, REAL)
        rows.append(row)
    return partition(rows, required=REQUIRED)


def rows_for(rows: list[dict], condition: str) -> list[dict]:
    return [r for r in rows if r["condition"] == condition]


def _values(rows, regime: str, metric: str) -> list[float]:
    return [r[regime][metric] for r in rows]


def heterogeneity_cost(rows, metric: str, iterations=10000, seed=0) -> dict:
    """Spread minus concentrated, paired within each instance."""
    deltas = [r[SPREAD][metric] - r[CONCENTRATED][metric] for r in rows]
    return {**bootstrap_median_ci(deltas, iterations=iterations, seed=seed), "n": len(deltas)}


def registered_slot_cost(rows_n, rows_1, metric: str, iterations=10000, seed=0) -> dict:
    """Concentrated at N minus concentrated at one slot, unpaired."""
    res = bootstrap_median_diff(
        _values(rows_n, CONCENTRATED, metric),
        _values(rows_1, CONCENTRATED, metric),
        iterations=iterations,
        seed=seed,
    )
    return {**res, "n": [len(rows_n), len(rows_1)]}


def slot_overhead(default_n, default_1, special_n, special_1, metric, iterations=10000, seed=0) -> dict:
    """Amendment §3b's difference in differences, concentrated regime, unpaired:
    [default(N) - default(1)] - [specialized(N) - specialized(1)]."""
    groups = [
        _values(g, CONCENTRATED, metric) for g in (default_n, default_1, special_n, special_1)
    ]
    res = bootstrap_function_of_medians(
        groups, lambda m: (m[0] - m[1]) - (m[2] - m[3]), iterations=iterations, seed=seed
    )
    return {**res, "n": [len(g) for g in groups]}


def gauge_overhead(sweep_rows, control_rows, metric, iterations=10000, seed=0) -> dict:
    """Heterogeneity cost with default stats minus with `--disable-log-stats`,
    at the control point, unpaired (amendment §3a)."""
    def deltas(rows):
        return [r[SPREAD][metric] - r[CONCENTRATED][metric] for r in rows]

    res = bootstrap_median_diff(
        deltas(sweep_rows), deltas(control_rows), iterations=iterations, seed=seed
    )
    return {**res, "n": [len(sweep_rows), len(control_rows)]}


def memory_ceiling(rows, prereg: Preregistration) -> dict:
    """KV tokens at a sweep point, as maximum concurrency at the inherited
    request shape and at the production context length (amendment §3c)."""
    per_instance = [r["kv_capacity_tokens"] for r in rows]
    kv = median(per_instance)
    return {
        "kv_tokens": kv,
        "kv_by_instance": per_instance,
        "max_concurrency_request_shape": int(kv // prereg.request_tokens),
        "max_concurrency_context": int(kv // prereg.context_length_tokens),
        "n": len(rows),
    }


def sweep_estimands(publishable, prereg: Preregistration, iterations=10000, seed=0) -> dict:
    """Every per-point estimand the post reports. JSON-shaped: points are a
    list carrying their own slot count, so a round trip through
    `data/a5/analysis.json` cannot turn keys into strings."""
    at_one = rows_for(publishable, condition_name(SWEEP, 1))
    points = []
    for n in prereg.sweep:
        rows = rows_for(publishable, condition_name(SWEEP, n))
        point = {
            "n_slots": n,
            "n": len(rows),
            "memory": memory_ceiling(rows, prereg),
            "median": {
                regime: {m: median(_values(rows, regime, m)) for m in METRICS}
                for regime in (CONCENTRATED, SPREAD)
            },
            "interval": {
                regime: {
                    m: bootstrap_median_ci(_values(rows, regime, m), iterations=iterations, seed=seed)
                    for m in METRICS
                }
                for regime in (CONCENTRATED, SPREAD)
            },
        }
        if n == 1:
            point["heterogeneity"] = {"by_construction": 0.0}
            point["registered_slot"] = {"by_construction": 0.0}
        else:
            point["heterogeneity"] = {
                m: heterogeneity_cost(rows, m, iterations, seed) for m in METRICS
            }
            point["registered_slot"] = {
                m: registered_slot_cost(rows, at_one, m, iterations, seed) for m in METRICS
            }
        points.append(point)
    out = {"points": points}
    if prereg.include_diagnostic:
        d1 = rows_for(publishable, condition_name(DIAGNOSTIC, 1))
        out["slot_overhead"] = [
            {
                "n_slots": n,
                **{
                    m: slot_overhead(
                        rows_for(publishable, condition_name(SWEEP, n)), at_one,
                        rows_for(publishable, condition_name(DIAGNOSTIC, n)), d1,
                        m, iterations, seed,
                    )
                    for m in METRICS
                },
            }
            for n in prereg.diagnostic_points
            if n != 1
        ]
    if prereg.include_control:
        n = prereg.control_point
        out["gauge_overhead"] = {
            "n_slots": n,
            **{
                m: gauge_overhead(
                    rows_for(publishable, condition_name(SWEEP, n)),
                    rows_for(publishable, condition_name(CONTROL, n)),
                    m, iterations, seed,
                )
                for m in METRICS
            },
        }
    return out


def point_at(sweep: dict, n_slots: int) -> dict:
    return next(p for p in sweep["points"] if p["n_slots"] == n_slots)


def publishable_counts(records, prereg: Preregistration) -> dict[str, dict]:
    """Per condition: stored, failed, discarded and publishable instances, and
    whether publishable meets the bootstrap floor. Checked before analysis."""
    parts = instance_rows(records, prereg)
    out: dict[str, dict] = {}
    for bucket, rows in (("publishable", parts.publishable), ("discarded", parts.discarded),
                         ("failed", parts.failed)):
        for r in rows:
            entry = out.setdefault(r["condition"], {"publishable": 0, "discarded": 0, "failed": 0})
            entry[bucket] += 1
    for entry in out.values():
        entry["meets_floor"] = entry["publishable"] >= MIN_BOOTSTRAP_SAMPLES
    return out
```

- [ ] **Step 4: Create `multilora/analysis.py`**

```python
"""Everything the post reports, assembled from the two stores.

One JSON-able dict, written by `scripts/a5_analyse.py` to
`data/a5/analysis.json`. Every number in the post and every figure reads from
it, so a published number can always be traced back to the records.
"""

from dataclasses import asdict

from harness.publish import discard_table, failure_rate_by_group
from harness.stats import MIN_BOOTSTRAP_SAMPLES, median
from multilora.conditions import SPREAD, SWEEP, condition_name
from multilora.economics import tenants_per_gpu, three_way_table
from multilora.estimands import instance_rows, point_at, rows_for, sweep_estimands
from multilora.gate import verdict
from multilora.knee import knee


def gate_verdict(gate_records, prereg, iterations=10000, seed=0) -> dict:
    """The gate alone. `scripts/a5_run.py --which campaign` refuses to start
    unless this says pass (August §8: nothing else runs until the gate passes
    or its failure is characterized)."""
    rows = instance_rows(gate_records, prereg)
    if len(rows.publishable) < MIN_BOOTSTRAP_SAMPLES:
        return {
            "verdict": "insufficient",
            "n": len(rows.publishable),
            "delta": prereg.equivalence_margin,
            "reason": f"{len(rows.publishable)} publishable gate instances; the bootstrap "
            f"needs {MIN_BOOTSTRAP_SAMPLES}",
        }
    return verdict(rows.publishable, prereg.equivalence_margin, iterations, seed)


def analyse(records, gate_records, prereg, a4: dict | None = None, iterations=10000, seed=0) -> dict:
    campaign = instance_rows(records, prereg)
    gate = instance_rows(gate_records, prereg)
    all_rows = campaign.publishable + campaign.discarded + campaign.failed
    gate_rows = gate.publishable + gate.discarded + gate.failed
    out = {
        "prereg": asdict(prereg),
        "failures": failure_rate_by_group(all_rows + gate_rows, "condition"),
        "discards": discard_table(campaign.discarded + gate.discarded, "condition"),
        "gate": gate_verdict(gate_records, prereg, iterations, seed),
    }
    sweep = sweep_estimands(campaign.publishable, prereg, iterations, seed)
    out["sweep"] = sweep
    throughput = {
        n: [r[SPREAD]["throughput_tps"] for r in rows_for(campaign.publishable, condition_name(SWEEP, n))]
        for n in prereg.sweep
    }
    k = knee(throughput, prereg.knee_threshold, iterations, seed)
    out["knee"] = k
    at = k["slots_below_knee"]
    spread_at = point_at(sweep, at)["median"][SPREAD]
    rate_rows = rows_for(campaign.publishable, condition_name(SWEEP, at))
    tenants = tenants_per_gpu(
        slots_below_knee=at,
        request_rate=median([r[SPREAD]["request_rate"] for r in rate_rows]),
        ttft_p95=spread_at["ttft_p95"],
        max_concurrency=point_at(sweep, at)["memory"]["max_concurrency_context"],
        prereg=prereg,
    )
    out["tenants"] = tenants
    if a4 is not None and tenants["feasible"]:
        out["cost_table"] = three_way_table(tenants["tenants"], prereg, a4)
    return out
```

- [ ] **Step 5: Create `multilora/stub.py`**

```python
"""A GPU-free stand-in for artifact 5's worker.

`StubInstanceEndpoint.run(payload)` returns exactly the payload shape the real
worker returns (see `multilora.records`), built from a small timing model with
a known registered-slot cost, a known heterogeneity cost and a known gauge
cost. Tests use it to check that the analysis recovers what was put in; the
figure scripts use it to lay out charts before any paid run. Nothing it
produces is data, and nothing in it is published.

Drive it through `harness.submit.PayloadStubSubmitter(endpoint.run)`. That is
the harness's GPU-free twin of `RunPodSubmitter.submit_payload`: it round-trips
payload and output through JSON as the real transport does, and records an
unhealthy engine as a failure exactly as the real submitter does. A second
stub submitter here would be one more copy of that decision to drift.
"""

import math
import random
from dataclasses import dataclass

from multilora.conditions import REAL, SPREAD, SYNTHETIC

OUTPUT_TOKENS = 16


@dataclass(frozen=True)
class StubModel:
    base_tps: float = 2400.0
    slot_cost_per_doubling: float = 0.01
    heterogeneity_per_doubling: float = 0.05
    specialize_recovers: float = 0.8
    gauge_cost_at_top: float = 0.01
    base_ttft_s: float = 0.08
    kv_tokens_at_one: int = 90_000
    kv_tokens_per_slot: int = 440
    cold_compile_kv_loss: int = 7_000
    cold_compile_every: int = 0
    fail_every: int = 0
    synthetic_bias: float = 0.0
    noise: float = 0.02


class StubInstanceEndpoint:
    def __init__(self, model: StubModel | None = None, seed: int = 0):
        self.model = model or StubModel()
        self.seed = seed
        self.calls = 0

    def _tps(self, regime, n_slots, n_active, specialize, stats_off, rng) -> float:
        m = self.model
        slot = m.slot_cost_per_doubling * math.log2(n_slots)
        if specialize:
            slot *= 1 - m.specialize_recovers
        tps = m.base_tps * (1 - slot)
        if regime in (SPREAD, REAL, SYNTHETIC):
            tps *= 1 - m.heterogeneity_per_doubling * math.log2(n_active)
            if not stats_off:
                tps *= 1 - m.gauge_cost_at_top * math.log2(n_active) / 6
        if regime == SYNTHETIC:
            tps *= 1 + m.synthetic_bias
        return tps * (1 + m.noise * rng.gauss(0.0, 1.0))

    def run(self, payload: dict) -> dict:
        self.calls += 1
        m = self.model
        rng = random.Random(self.seed * 1_000_003 + payload["run_index"])
        if m.fail_every and self.calls % m.fail_every == 0:
            return {"healthy": False, "log_lines": ["torch.OutOfMemoryError: CUDA out of memory"]}
        cold = bool(m.cold_compile_every) and self.calls % m.cold_compile_every == 0
        n_slots = payload["n_slots"]
        kv = m.kv_tokens_at_one - m.kv_tokens_per_slot * (n_slots - 1)
        if cold:
            kv -= m.cold_compile_kv_loss
        log = [
            "Initializing a V1 LLM engine (v0.27.1) with config: model='Qwen/Qwen3-4B'",
            f"torch.compile took {38.5 if cold else 0.3:.2f} s in total",
            f"GPU KV cache size: {kv:,} tokens",
        ]
        if cold:
            log.insert(1, "Using cache directory: /runpod-volume/vllm-cache/torch_compile_cache/"
                          f"stub{n_slots:03d}/rank_0_0/backbone")
        conc = payload["concurrency"]
        n_req = payload["requests_per_phase"]
        phases, samples = [], []
        for spec in payload["phases"]:
            n_active = min(len(spec["adapters"]), conc)
            tps = self._tps(
                spec["regime"], n_slots, n_active,
                payload["specialize_active_lora"], payload["disable_log_stats"], rng,
            )
            median_ttft = m.base_ttft_s * m.base_tps / tps
            ttfts = [median_ttft * math.exp(0.15 * rng.gauss(0.0, 1.0)) for _ in range(n_req)]
            phases.append({
                "phase_index": spec["phase_index"],
                "regime": spec["regime"],
                "adapters": spec["adapters"],
                "concurrency": conc,
                "num_requests": n_req,
                "duration_s": n_req * OUTPUT_TOKENS / tps,
                "completed": n_req,
                "failed": 0,
                "ttfts": ttfts,
                "output_lens": [OUTPUT_TOKENS] * n_req,
                "errors": [""] * n_req,
            })
            running = None if payload["disable_log_stats"] else sorted(spec["adapters"][:n_active])
            samples += [
                {"phase_index": spec["phase_index"], "t": float(i), "running": running}
                for i in range(3)
            ]
        return {
            "healthy": True,
            "log_lines": log,
            "served_cmd": ["vllm", "serve", "Qwen/Qwen3-4B", "--max-loras", str(n_slots)],
            "host": {"host_id": "stub-container", "gpu_model": "stub", "vcpus": 16},
            "adapters": {name: f"stub-{name}" for name in payload["registered"]},
            "phases": phases,
            "gauge_samples": samples,
        }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_end_to_end.py -v`
Expected: 10 passed. The module fixture runs 288 stub instances, so allow it several seconds.

- [ ] **Step 7: Commit**

```bash
git add multilora/estimands.py multilora/analysis.py multilora/stub.py tests/test_multilora_end_to_end.py
git commit -m "feat: estimands, the assembled analysis, and a stub worker that exercises both"
```

---

## Task 15: The generated numbers block, the gate on its own, and priming checks

Three small pieces plan 3 relies on. The post's numbers are generated from the analysis, so none can be typed by hand. The campaign runner needs the gate's verdict on its own, and must get "insufficient" rather than a crash when the gate has too few instances. The priming check must fail unless every sweep point's second start read warm.

**Files:**
- Create: `multilora/numbers.py`, `tests/test_multilora_numbers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_numbers.py`:

```python
import pytest

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse, gate_verdict
from multilora.campaign import priming_payloads, priming_verdict, run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.numbers import END, START, block_in, numbers_block, replace_block
from multilora.records import InstanceRecord, build_record
from multilora.stub import StubInstanceEndpoint, StubModel
from tests.conftest import example_prereg

A4 = {"gpu_hourly_rate": 1.0, "n_models": 20, "reference": {"regime": "low", "s": 1.1},
      "rows": [{"regime": "low", "s": 1.1, "dedicated_cost_per_tenant_month": 730.0,
                "swapped_cost_per_tenant_month": 120.0, "sleep_mode_cost_per_tenant_month": None}]}


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    tmp = tmp_path_factory.mktemp("n")
    out = {}
    for name, schedule in (("campaign", campaign_schedule(prereg)), ("gate", gate_schedule(prereg))):
        store = JsonlStore(tmp / f"{name}.jsonl", InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=4).run), store, prereg)
        out[name] = store.read_all()
    return prereg, out


def test_the_block_is_regenerated_identically(stores):
    prereg, s = stores
    analysis = analyse(s["campaign"], s["gate"], prereg, a4=A4, iterations=200)
    block = numbers_block(analysis)
    assert block.startswith(START) and block.endswith(END)
    assert "| Equivalence gate | pass, n = 24 instances |" in block
    assert "| Cost per tenant per month, adapter |" in block and "an upper bound" in block
    post = f"# Title\n\n{START}\nstale\n{END}\n\nText."
    updated = replace_block(post, block)
    assert block_in(updated) == block
    assert updated.endswith("\n\nText.")


def test_the_gate_verdict_alone_matches_the_full_analysis(stores):
    prereg, s = stores
    alone = gate_verdict(s["gate"], prereg, iterations=200)
    full = analyse(s["campaign"], s["gate"], prereg, iterations=200)["gate"]
    assert alone == full


def test_priming_starts_each_point_twice_with_no_timed_phases(prereg):
    pairs = priming_payloads(prereg)
    assert len(pairs) == 2 * len(prereg.sweep)
    assert all(p["phases"] == [] for _, p in pairs)
    assert [s.block_index for s, _ in pairs[:2]] == [0, 1]


def test_priming_passes_only_when_every_second_start_is_warm(prereg):
    def records(model):
        endpoint = StubInstanceEndpoint(model, seed=1)
        sub = PayloadStubSubmitter(endpoint.run)
        return [build_record(s, p["run_id"], sub.submit_payload(p)) for s, p in priming_payloads(prereg)]

    good = priming_verdict(records(StubModel()))
    assert all(v["ok"] for v in good.values())
    bad = priming_verdict(records(StubModel(cold_compile_every=2)))
    assert not all(v["ok"] for v in bad.values())


def test_a_gate_with_too_few_instances_is_insufficient_not_a_crash(stores):
    prereg, s = stores
    res = gate_verdict(s["gate"][:10], prereg, iterations=200)
    assert res["verdict"] == "insufficient" and res["n"] == 10
    assert gate_verdict([], prereg)["verdict"] == "insufficient"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_numbers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.numbers'`. `gate_verdict`, `priming_payloads` and `priming_verdict` already exist from Tasks 9 and 14.

- [ ] **Step 3: Create `multilora/numbers.py`**

```python
"""The post's numbers, generated from `data/a5/analysis.json`.

The post carries a block between two markers. `scripts/a5_numbers.py`
rewrites it from the analysis and tests/test_a5_post.py fails if the block in
the post differs from a fresh generation, so a number cannot be edited by hand
or left stale after a re-analysis.
"""

from multilora.conditions import CONCENTRATED, SPREAD
from multilora.estimands import point_at

START = "<!-- a5-numbers:start -->"
END = "<!-- a5-numbers:end -->"


def _ci(ci: dict, scale: float = 1.0, unit: str = "") -> str:
    return (
        f"{ci['point'] * scale:,.1f}{unit} "
        f"(95% interval {ci['lo'] * scale:,.1f} to {ci['hi'] * scale:,.1f}{unit})"
    )


def numbers_block(analysis: dict) -> str:
    sweep = analysis["sweep"]
    top_n = sweep["points"][-1]["n_slots"]
    top = point_at(sweep, top_n)
    one = point_at(sweep, 1)
    knee = analysis["knee"]
    tenants = analysis["tenants"]
    gate = analysis["gate"]
    rows = [
        ("Equivalence gate", f"{gate['verdict']}, n = {gate['n']} instances"),
        (
            "Knee",
            f"above {top_n} slots" if knee["above_top"]
            else f"between {knee['knee']['lower']} and {knee['knee']['upper']} slots",
        ),
        (
            f"Heterogeneity cost at {top_n} slots, throughput",
            _ci(top["heterogeneity"]["throughput_tps"], unit=" tokens/s"),
        ),
        (
            f"Heterogeneity cost at {top_n} slots, TTFT p50",
            _ci(top["heterogeneity"]["ttft_p50"], scale=1000.0, unit=" ms"),
        ),
        (
            f"Registered-slot cost at {top_n} slots, throughput",
            _ci(top["registered_slot"]["throughput_tps"], unit=" tokens/s"),
        ),
        (
            "Throughput at 1 slot",
            f"{one['median'][CONCENTRATED]['throughput_tps']:,.0f} tokens/s",
        ),
        (
            f"Spread throughput at {top_n} slots",
            f"{top['median'][SPREAD]['throughput_tps']:,.0f} tokens/s",
        ),
        (
            "KV capacity, 1 slot to top",
            f"{one['memory']['kv_tokens']:,.0f} to {top['memory']['kv_tokens']:,.0f} tokens",
        ),
    ]
    if tenants["feasible"]:
        rows.append(
            ("Tenants per GPU", f"{tenants['tenants']} (bound by {tenants['binding']}; a lower bound)")
        )
    else:
        rows.append(("Tenants per GPU", f"infeasible: {tenants['reason']}"))
    for row in analysis.get("cost_table", []):
        label = f"Cost per tenant per month, {row['strategy']}"
        suffix = " (an upper bound)" if row.get("upper_bound") else ""
        rows.append((label, f"${row['cost']:,.2f}{suffix}"))
    body = ["| quantity | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows]]
    return "\n".join([START, *body, END])


def replace_block(post: str, block: str) -> str:
    start, end = post.index(START), post.index(END) + len(END)
    return post[:start] + block + post[end:]


def block_in(post: str) -> str:
    start, end = post.index(START), post.index(END) + len(END)
    return post[start:end]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_numbers.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/numbers.py tests/test_multilora_numbers.py
git commit -m "feat: generate the post's numbers from the analysis; test gate and priming checks"
```

---

## Task 16: The four figures

Visual work. `superpowers:verifying-visual-output` applies: tests assert computed properties (text size at phone width, axis origins, instance counts on the figure), and Task 20 is the eyes-on check.

**Files:**
- Create: `multilora/figures.py`, `tests/test_multilora_figures.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_multilora_figures.py`:

```python
import matplotlib.text
import pytest

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.figures import FIGURES
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint
from tests.conftest import example_prereg

A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    tmp = tmp_path_factory.mktemp("fig")
    stores = {}
    for name, schedule in (("campaign", campaign_schedule(prereg)), ("gate", gate_schedule(prereg))):
        store = JsonlStore(tmp / f"{name}.jsonl", InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=2).run), store, prereg)
        stores[name] = store.read_all()
    return analyse(stores["campaign"], stores["gate"], prereg, a4=A4, iterations=200)


def _rendered_px(fig, size_pt: float) -> float:
    return size_pt * PHONE_WIDTH_PX / (72 * fig.get_size_inches()[0])


@pytest.mark.parametrize("name", sorted(FIGURES))
def test_every_figure_writes_a_file(analysis, tmp_path, name):
    FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert (tmp_path / f"{name}.png").stat().st_size > 10_000


@pytest.mark.parametrize("name", sorted(FIGURES))
def test_every_text_element_is_legible_at_phone_width(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    small = [
        (t.get_text(), round(_rendered_px(fig, t.get_fontsize()), 2))
        for t in fig.findobj(matplotlib.text.Text)
        if t.get_text().strip() and _rendered_px(fig, t.get_fontsize()) < MIN_PHONE_TEXT_PX
    ]
    assert small == []


@pytest.mark.parametrize("name", ["throughput_ttft", "kv_capacity", "equivalence"])
def test_the_instance_count_is_on_the_figure(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    texts = " ".join(t.get_text() for t in fig.findobj(matplotlib.text.Text))
    assert "n = " in texts


def test_value_axes_start_at_zero(analysis, tmp_path):
    fig = FIGURES["throughput_ttft"](analysis, tmp_path / "a.png")
    assert all(ax.get_ylim()[0] == 0 for ax in fig.axes)
    fig = FIGURES["kv_capacity"](analysis, tmp_path / "b.png")
    assert fig.axes[0].get_ylim()[0] == 0
    fig = FIGURES["cost_per_tenant"](analysis, tmp_path / "c.png")
    assert fig.axes[0].get_xlim()[0] == 0


def test_the_equivalence_band_is_the_pre_registered_margin(analysis, tmp_path):
    fig = FIGURES["equivalence"](analysis, tmp_path / "e.png")
    labels = [t.get_text() for t in fig.findobj(matplotlib.text.Text)]
    assert f"margin ±{100 * analysis['gate']['delta']:.1f}%" in labels


def test_empty_input_is_refused(analysis, tmp_path):
    empty = {**analysis, "sweep": {"points": []}}
    with pytest.raises(ValueError, match="must not be empty"):
        FIGURES["throughput_ttft"](empty, tmp_path / "x.png")


def test_a_sleep_mode_row_gets_its_own_bar(analysis, tmp_path):
    rows = analysis["cost_table"]
    with_sleep = rows[:2] + [{"strategy": "sleep mode", "cost": 60.0, "source": "a4"}] + rows[2:]
    fig = FIGURES["cost_per_tenant"]({**analysis, "cost_table": with_sleep}, tmp_path / "c.png")
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["dedicated", "swapped", "sleep mode", "adapter"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_multilora_figures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'multilora.figures'`.

- [ ] **Step 3: Create `multilora/figures.py`**

```python
"""Artifact 5's four figures, drawn from `data/a5/analysis.json`.

Same constraints as every artifact: N stated on the figure, no truncated
axes, intervals shown, legible at phone width, empty input refused, rendered
and looked at before anything is called done. Sizes are set in rendered
phone pixels through `harness.figure_guards.phone_pt`, so widening a canvas
cannot quietly shrink the text below the floor.

1. Throughput and TTFT against adapters registered, both regimes, the gap
   between them shaded: the heterogeneity cost.
2. KV capacity against adapters registered: the memory effect, as capacity.
3. The equivalence gate: synthetic against real, with the margin.
4. Cost per tenant per month, three strategies. Artifact 4's swap cost is the
   swapped bar here, in money, rather than a line on figure 1 (amendment §7).
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from harness.figure_guards import phone_pt, validate_rows

PX_TITLE = 10.0
PX_TEXT = 8.4
WIDTH_IN = 8.0

COLOR = {"concentrated": "#2f6fd0", "spread": "#c04a4a"}
LABEL = {"concentrated": "concentrated (1 adapter active)", "spread": "spread (all active)"}
STRATEGY_COLOR = {
    "dedicated": "#888888",
    "swapped": "#c88a2e",
    "sleep mode": "#8a6fc8",
    "adapter": "#2f6fd0",
}
GAP_COLOR = "#f2c9c9"
BAND_COLOR = "#dfe9f7"


def _pt(px: float) -> float:
    return phone_pt(px, WIDTH_IN)


def _style(ax) -> None:
    ax.tick_params(labelsize=_pt(PX_TEXT))
    ax.xaxis.label.set_size(_pt(PX_TEXT))
    ax.yaxis.label.set_size(_pt(PX_TEXT))
    ax.grid(alpha=0.3)


def _n_text(points) -> str:
    ns = sorted({p["n"] for p in points})
    return f"n = {ns[0]}" if len(ns) == 1 else f"n = {ns[0]}–{ns[-1]}"


def throughput_and_ttft(analysis: dict, out_path):
    points = validate_rows(analysis["sweep"]["points"])
    xs = [p["n_slots"] for p in points]
    fig, axes = plt.subplots(2, 1, figsize=(WIDTH_IN, 9.0), sharex=True)
    panels = (("throughput_tps", "Throughput (tokens/s)"), ("ttft_p50", "TTFT p50 (s)"))
    for ax, (metric, ylabel) in zip(axes, panels):
        medians = {}
        for regime in ("concentrated", "spread"):
            med = [p["median"][regime][metric] for p in points]
            lo = [p["interval"][regime][metric]["lo"] for p in points]
            hi = [p["interval"][regime][metric]["hi"] for p in points]
            medians[regime] = med
            ax.errorbar(
                xs, med,
                yerr=[[m - low for m, low in zip(med, lo)], [h - m for m, h in zip(med, hi)]],
                color=COLOR[regime], marker="o", capsize=4, lw=2, label=LABEL[regime],
            )
        ax.fill_between(
            xs, medians["concentrated"], medians["spread"],
            color=GAP_COLOR, label="heterogeneity cost",
        )
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        _style(ax)
    axes[0].legend(fontsize=_pt(PX_TEXT), loc="lower left")
    axes[1].set_xscale("log", base=2)
    axes[1].set_xticks(xs, [str(x) for x in xs])
    axes[1].set_xlabel("Adapters registered (GPU slots)")
    fig.suptitle(
        f"Serving cost as adapters are added · {_n_text(points)} instances per point\n"
        "medians with 95% intervals",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def kv_capacity(analysis: dict, out_path):
    points = validate_rows(analysis["sweep"]["points"])
    context = analysis["prereg"]["context_length_tokens"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 5.5))
    for i, p in enumerate(points):
        values = p["memory"]["kv_by_instance"]
        ax.scatter([p["n_slots"]] * len(values), values, color="#555555", alpha=0.35, s=14,
                   label="per instance" if i == 0 else None)
    xs = [p["n_slots"] for p in points]
    ax.plot(xs, [p["memory"]["kv_tokens"] for p in points], color="#2f6fd0", marker="o", lw=2,
            label="median")
    ax.set_xscale("log", base=2)
    ax.set_xticks(xs, [str(x) for x in xs])
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Adapters registered (GPU slots)")
    ax.set_ylabel("KV cache capacity (tokens)")
    first, last = points[0]["memory"], points[-1]["memory"]
    ax.text(
        0.02, 0.05,
        f"max concurrent requests at {context:,} tokens: "
        f"{first['max_concurrency_context']} → {last['max_concurrency_context']}",
        transform=ax.transAxes, fontsize=_pt(PX_TEXT),
    )
    ax.legend(fontsize=_pt(PX_TEXT), loc="upper right")
    _style(ax)
    ax.set_title(
        f"KV capacity by slot count · {_n_text(points)} instances per point",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def equivalence(analysis: dict, out_path):
    gate = analysis["gate"]
    if "metrics" not in gate:
        raise ValueError(f"the gate has no verdict to draw: {gate['verdict']}")
    delta = gate["delta"]
    fig, axes = plt.subplots(2, 1, figsize=(WIDTH_IN, 7.5))
    names = {"ttft_p50": "TTFT p50", "throughput_tps": "Throughput"}
    for ax, metric in zip(axes, ("ttft_p50", "throughput_tps")):
        m = gate["metrics"][metric]
        per = validate_rows([{"v": v} for v in m["per_instance"]])
        ax.axvspan(-100 * delta, 100 * delta, color=BAND_COLOR, label=f"margin ±{100 * delta:.1f}%")
        ax.axvline(0, color="#333333", lw=1)
        ax.scatter([100 * r["v"] for r in per], [1.0] * len(per), color="#555555", alpha=0.5, s=16,
                   label="per instance")
        for y, key, label, color in (
            (0.55, "statistic", "synthetic − real, 90% interval", "#c04a4a"),
            (0.2, "resolution", "real − real, 90% interval", "#2f6fd0"),
        ):
            ci = m[key]
            ax.errorbar(100 * ci["point"], y,
                        xerr=[[100 * (ci["point"] - ci["lo"])], [100 * (ci["hi"] - ci["point"])]],
                        color=color, marker="o", capsize=5, lw=2, label=label)
        span = max(2 * delta, *(abs(r["v"]) for r in per)) * 100 * 1.15
        ax.set_xlim(-span, span)
        ax.set_ylim(0, 1.3)
        ax.set_yticks([])
        ax.set_xlabel(f"{names[metric]}: relative difference (%)")
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=_pt(PX_TEXT), loc="lower center", ncol=2)
    fig.suptitle(
        f"Synthetic vs real adapters · verdict: {gate['verdict']} · n = {gate['n']} instances",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    fig.savefig(out_path, dpi=150)
    return fig


def cost_per_tenant(analysis: dict, out_path):
    rows = validate_rows(analysis["cost_table"])
    prereg = analysis["prereg"]
    fig, ax = plt.subplots(figsize=(WIDTH_IN, 4.6))
    labels = [r["strategy"] for r in rows]
    costs = [r["cost"] for r in rows]
    bars = ax.barh(labels, costs, color=[STRATEGY_COLOR[s] for s in labels])
    for bar, row in zip(bars, rows):
        if row.get("upper_bound"):
            bar.set_hatch("//")
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" ${row['cost']:,.0f}",
                va="center", fontsize=_pt(PX_TEXT))
    ax.set_xlim(0, max(costs) * 1.3)
    ax.invert_yaxis()
    ax.set_xlabel("Cost per tenant per month (USD)")
    fig.text(
        0.02, 0.02,
        f"${prereg['gpu_hourly_rate']}/GPU-hour · {prereg['requests_per_tenant_month']:,.0f} "
        "requests/tenant/month\nadapter bar: tenants are a lower bound, so its cost is an upper bound",
        fontsize=_pt(PX_TEXT * 0.9),
    )
    _style(ax)
    ax.set_title(
        f"Cost per tenant per month · adapter: {analysis['tenants']['tenants']} tenants per GPU",
        fontsize=_pt(PX_TITLE),
    )
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    fig.savefig(out_path, dpi=150)
    return fig


FIGURES = {
    "throughput_ttft": throughput_and_ttft,
    "kv_capacity": kv_capacity,
    "equivalence": equivalence,
    "cost_per_tenant": cost_per_tenant,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_figures.py -v`
Expected: 15 passed.

- [ ] **Step 5: Commit**

```bash
git add multilora/figures.py tests/test_multilora_figures.py
git commit -m "feat: artifact 5's four figures, legible at phone width"
```

---

## Task 17: The serving adapter and the instance runner

`serving.py` is the only module that calls the shared harness tooling: `harness.serve.served` and `harness.bench.run_bench`, with the interface agreed with artifact 4's session on 2026-09-26. Both are injectable, and neither needs to exist for this task, because the tests pass fakes. `instance.py` is what the worker runs for one scheduled instance. Its output is the payload contract `records.py` documents, and one test feeds it straight into `build_record` to prove that.

**Files:**
- Create: `multilora/serving.py`, `multilora/instance.py`, `tests/test_multilora_serving.py`, `tests/test_multilora_instance.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multilora_serving.py`:

```python
import pytest

from multilora.serving import (
    SPECIALIZE_FLAG,
    run_phase,
    serve,
    serve_args,
)


def _args(**kw):
    base = {
        "revision": "abc123",
        "max_model_len": 8192,
        "n_slots": 2,
        "rank": 16,
        "lora_modules": {"a00": "/tmp/a5-adapters/a00", "a01": "/tmp/a5-adapters/a01"},
        "specialize_active_lora": False,
        "disable_log_stats": False,
    }
    base.update(kw)
    return serve_args(**base)


def test_every_registered_adapter_gets_its_own_slot():
    args = _args()
    assert args[args.index("--max-loras") + 1] == "2"
    assert args[args.index("--max-cpu-loras") + 1] == "2"
    assert args[args.index("--max-lora-rank") + 1] == "16"
    assert "--no-enable-prefix-caching" in args
    i = args.index("--lora-modules")
    assert args[i + 1 : i + 3] == ["a00=/tmp/a5-adapters/a00", "a01=/tmp/a5-adapters/a01"]


def test_the_per_job_switches_add_their_flags():
    assert SPECIALIZE_FLAG in _args(specialize_active_lora=True)
    assert "--disable-log-stats" in _args(disable_log_stats=True)
    plain = _args()
    assert SPECIALIZE_FLAG not in plain and "--disable-log-stats" not in plain


def test_slot_count_must_match_the_adapters_registered():
    with pytest.raises(ValueError, match="1 adapters registered for 2 slots"):
        _args(lora_modules={"a00": "/x"})


def test_serve_passes_through_to_the_harness_lifecycle():
    calls = []

    def fake_served(model, *, args, env):
        calls.append((model, args, env))
        return "ctx"

    assert serve("m", ["--x"], {"HF_HOME": "/h"}, served=fake_served) == "ctx"
    assert calls == [("m", ["--x"], {"HF_HOME": "/h"})]


def test_a_phase_is_round_robin_with_eos_ignored_and_raw_arrays_kept():
    seen = {}

    def fake_run_bench(base_url, **kw):
        seen.update(kw, base_url=base_url)
        return {
            "duration": 12.5, "completed": 3, "failed": 1,
            "ttfts": [0.1, 0.2, 0.0, 0.3], "output_lens": [16, 16, 0, 16],
            "errors": ["", "", "boom", ""], "mean_ttft_ms": 150.0,
        }

    phase = run_phase(
        "http://127.0.0.1:8000", model="m", adapters=("a00", "a01"), concurrency=64,
        num_requests=4, dataset_args=["--dataset-name", "random"], seed=7,
        result_dir="/tmp/r", run_bench=fake_run_bench,
    )
    assert seen["lora_assignment"] == "round-robin"
    assert seen["ignore_eos"] is True
    assert seen["lora_modules"] == ["a00", "a01"]
    assert seen["max_concurrency"] == 64
    assert phase["ttfts"] == [0.1, 0.2, 0.0, 0.3]
    assert phase["duration_s"] == 12.5
    assert "mean_ttft_ms" not in phase, "summary statistics are never carried"
```

Create `tests/test_multilora_instance.py`:

```python
import contextlib
import json

import pytest

from harness.scheduler import ScheduledRun
from harness.submit import SubmitOutcome
from multilora import serving
from multilora.campaign import job_payload
from multilora.instance import Deps, run_instance, synthetic_seed
from multilora.records import build_record

TINY = {
    "hidden_size": 8, "num_attention_heads": 2, "num_key_value_heads": 1,
    "head_dim": 4, "intermediate_size": 16, "num_hidden_layers": 2,
}
MODULES = ("q_proj", "v_proj")
KV_LINE = "GPU KV cache size: 50,000 tokens"
WARM = "torch.compile took 0.31 s in total"


class FakeServer:
    def __init__(self, healthy=True):
        self.base_url = "http://127.0.0.1:8000"
        self.log_lines = [WARM, KV_LINE]
        self.healthy = healthy


def fake_served(calls, healthy=True):
    @contextlib.contextmanager
    def served(model, *, args, env):
        calls.append({"model": model, "args": args, "env": env})
        yield FakeServer(healthy)

    return served


def fake_bench(calls):
    def run_bench(base_url, **kw):
        calls.append(kw)
        n = kw["num_prompts"]
        return {
            "duration": n * 0.01, "completed": n, "failed": 0,
            "ttfts": [0.05] * n, "output_lens": [16] * n, "errors": [""] * n,
        }

    return run_bench


def _deps(served_calls, bench_calls, healthy=True, downloads=None):
    def download(repo, revision, dest):
        (downloads if downloads is not None else []).append((repo, revision, dest))
        from multilora.adapters import write_synthetic_adapter

        write_synthetic_adapter(dest, config=TINY, base_model="m", rank=2,
                                target_modules=MODULES, seed=99)

    metrics = 'vllm:lora_requests_info{running_lora_adapters="a00",waiting_lora_adapters=""} 1.0\n'
    return Deps(
        model_config=lambda model, revision: TINY,
        download_adapter=download,
        http_get=lambda url: metrics,
        host_info=lambda: {"host_id": "container", "vcpus": 8},
        served=fake_served(served_calls, healthy),
        run_bench=fake_bench(bench_calls),
    )


@pytest.fixture(autouse=True)
def adapter_root(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "ADAPTER_ROOT", str(tmp_path / "adapters"))


def _run(payload, deps):
    return run_instance(
        payload, model="Qwen/Qwen3-4B", revision="rev", max_model_len=8192, rank=2,
        target_modules=MODULES, env={"HF_HOME": "/h"}, deps=deps,
    )


def test_an_instance_warms_every_adapter_then_runs_the_phases_in_order(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N4"), "run-1", prereg)
    served_calls, bench_calls = [], []
    out = _run(payload, _deps(served_calls, bench_calls))
    assert out["healthy"] is True
    warm = bench_calls[0]
    assert warm["lora_modules"] == ["a00", "a01", "a02", "a03"]
    assert warm["num_prompts"] == prereg.warmup_requests_per_adapter * 4
    timed = bench_calls[1:]
    assert [c["lora_modules"] for c in timed] == [p["adapters"] for p in payload["phases"]]
    assert all(c["num_prompts"] == prereg.requests_per_phase for c in timed)
    assert all(c["lora_assignment"] == "round-robin" and c["ignore_eos"] for c in timed)
    assert [p["phase_index"] for p in out["phases"]] == [0, 1, 2, 3]
    args = served_calls[0]["args"]
    assert args[args.index("--max-loras") + 1] == "4"


def test_the_output_becomes_a_well_formed_record(prereg):
    payload = job_payload(ScheduledRun(3, 0, "sweep-N2"), "run-1", prereg)
    out = _run(payload, _deps([], []))
    rec = build_record(
        ScheduledRun(3, 0, "sweep-N2"), "run-1",
        SubmitOutcome(clock_A={"t_submit": 0.0, "t_result": 1.0}, payload=out, error=None),
    )
    assert rec.engine["kv_capacity_tokens"] == 50_000
    assert rec.engine["compile_state"] == "warm"
    assert set(rec.adapters) == {"a00", "a01"}
    assert len(rec.phases) == 4
    json.dumps(rec.to_dict())


def test_an_unhealthy_engine_returns_its_log_and_runs_no_load(prereg):
    payload = job_payload(ScheduledRun(0, 0, "sweep-N1"), "run-1", prereg)
    bench_calls = []
    out = _run(payload, _deps([], bench_calls, healthy=False))
    assert out["healthy"] is False
    assert KV_LINE in out["log_lines"]
    assert bench_calls == []


def test_synthetic_adapters_are_reused_when_parameters_match(prereg, tmp_path):
    payload = job_payload(ScheduledRun(0, 0, "sweep-N2"), "run-1", prereg)
    first = _run(payload, _deps([], []))["adapters"]
    marker = tmp_path / "adapters" / "a00" / "adapter_model.safetensors"
    mtime = marker.stat().st_mtime_ns
    second = _run(payload, _deps([], []))["adapters"]
    assert first == second
    assert marker.stat().st_mtime_ns == mtime, "an identical adapter was rewritten"


def test_gate_instances_download_real_adapters_at_their_pinned_revision(prereg):
    payload = job_payload(ScheduledRun(0, 0, "gate"), "run-g", prereg)
    downloads = []
    out = _run(payload, _deps([], [], downloads=downloads))
    assert [(repo, rev) for repo, rev, _ in downloads] == list(prereg.real_adapters)
    assert set(out["adapters"]) == {f"r{i:02d}" for i in range(4)} | {f"s{i:02d}" for i in range(4)}


def test_sweep_and_gate_synthetic_seeds_never_collide():
    assert synthetic_seed(1, "a00") != synthetic_seed(1, "s00")
    assert len({synthetic_seed(1, f"a{i:02d}") for i in range(64)}) == 64
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multilora_serving.py tests/test_multilora_instance.py -v`
Expected: FAIL with `ModuleNotFoundError` for `multilora.serving` and `multilora.instance`.

- [ ] **Step 3: Create `multilora/serving.py`**

```python
"""The only module that calls the shared harness tooling (amendment §2).

`harness.serve.served` starts and stops a `vllm serve` process and
`harness.bench.run_bench` runs `vllm bench serve` against it. Both come from
the standalone harness tooling plan that artifact 4 owns, with the interface
agreed on 2026-09-26. Everything artifact 5 adds on top -- which flags a sweep
point needs, and how a bench result becomes a stored phase -- lives here, so a
change on the harness side touches this one file.

Both harness callables are injectable, so tests run without an engine.
"""

import os

# Written inside the container at job start; never on the network volume.
ADAPTER_ROOT = "/tmp/a5-adapters"
# The CLI spelling of LoRAConfig.specialize_active_lora. Checked against the
# pinned engine's own help text by tests/test_multilora_engine_flags.py, which
# plan 2 adds once reconnaissance has captured that text.
SPECIALIZE_FLAG = "--specialize-active-lora"
ENGINE_FLAGS = (
    "--enable-lora",
    "--max-loras",
    "--max-cpu-loras",
    "--max-lora-rank",
    "--lora-modules",
    "--no-enable-prefix-caching",
    "--disable-log-stats",
    SPECIALIZE_FLAG,
)
BENCH_FLAGS = (
    "--dataset-name",
    "--random-input-len",
    "--random-output-len",
    "--lora-modules",
    "--lora-assignment",
    "--max-concurrency",
    "--ignore-eos",
    "--save-detailed",
    "--num-warmups",
    "--ready-check-timeout-sec",
)


def serve_args(
    *,
    revision: str,
    max_model_len: int,
    n_slots: int,
    rank: int,
    lora_modules: dict[str, str],
    specialize_active_lora: bool,
    disable_log_stats: bool,
) -> list[str]:
    """`vllm serve` flags for one instance (amendment §3a, §3g, §4).

    `max_loras = max_cpu_loras = n_slots`, so every registered adapter is
    resident and the resident-versus-swapped path never runs. Prefix caching is
    off so a phase cannot inherit another phase's cached prefixes."""
    if len(lora_modules) != n_slots:
        raise ValueError(f"{len(lora_modules)} adapters registered for {n_slots} slots")
    args = [
        "--revision", revision,
        "--max-model-len", str(max_model_len),
        "--enable-lora",
        "--max-loras", str(n_slots),
        "--max-cpu-loras", str(n_slots),
        "--max-lora-rank", str(rank),
        "--no-enable-prefix-caching",
        "--lora-modules", *[f"{name}={path}" for name, path in lora_modules.items()],
    ]
    if specialize_active_lora:
        args.append(SPECIALIZE_FLAG)
    if disable_log_stats:
        args.append("--disable-log-stats")
    return args


def adapter_path(name: str) -> str:
    return os.path.join(ADAPTER_ROOT, name)


def _harness_served():
    from harness.serve import served

    return served


def _harness_run_bench():
    from harness.bench import run_bench

    return run_bench


def serve(model: str, args: list[str], env: dict, served=None):
    """A context manager yielding `.base_url`, `.log_lines` and `.healthy`."""
    return (served or _harness_served())(model, args=args, env=env)


def run_phase(
    base_url: str,
    *,
    model: str,
    adapters,
    concurrency: int,
    num_requests: int,
    dataset_args,
    seed: int,
    result_dir,
    run_bench=None,
) -> dict:
    """One phase: round-robin over `adapters` at fixed concurrency, EOS ignored.
    Returns the phase fields `multilora.records` documents, with the tool's
    per-request arrays unaltered."""
    raw = (run_bench or _harness_run_bench())(
        base_url,
        model=model,
        lora_modules=list(adapters),
        lora_assignment="round-robin",
        max_concurrency=concurrency,
        num_prompts=num_requests,
        dataset_args=list(dataset_args),
        ignore_eos=True,
        seed=seed,
        result_dir=result_dir,
    )
    return {
        "concurrency": concurrency,
        "num_requests": num_requests,
        "duration_s": raw["duration"],
        "completed": raw["completed"],
        "failed": raw["failed"],
        "ttfts": raw["ttfts"],
        "output_lens": raw["output_lens"],
        "errors": raw["errors"],
    }
```

- [ ] **Step 4: Create `multilora/instance.py`**

```python
"""One server instance, end to end, inside the worker (amendment §4).

1. Make every registered adapter present on local disk: synthetic ones are
   written (or reused when a matching copy already exists on this worker), real
   ones are downloaded at their pinned revision.
2. Start the engine with one slot per adapter.
3. Untimed warm-up: every registered adapter serves `w` requests.
4. The timed phases, in the payload's order, with the gauge sampler running.
5. Return the payload contract documented in `multilora.records`.

Every external effect goes through `Deps`, so tests drive the whole sequence
with fakes and the worker supplies the real ones.
"""

import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from multilora.adapters import adapter_checksum, write_synthetic_adapter
from multilora.sampler import GaugeSampler
from multilora.serving import adapter_path, run_phase, serve, serve_args

_MARKER = "a5_params.json"


@dataclass
class Deps:
    model_config: Callable[[str, str], dict]
    download_adapter: Callable[[str, str, str], None]
    http_get: Callable[[str], str]
    host_info: Callable[[], dict]
    served: Callable | None = None
    run_bench: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def synthetic_seed(adapter_seed: int, name: str) -> int:
    """Deterministic per adapter: the sweep's a00..a63 and the gate's s00..s07
    never share a stream."""
    offset = 0 if name.startswith("a") else 5_000
    return adapter_seed * 10_000 + offset + int(name[1:])


def ensure_synthetic(name: str, *, config: dict, model: str, rank: int, target_modules, seed: int) -> str:
    """Write the adapter unless this worker already holds one written with the
    same parameters; either way return its checksum. A 64-slot instance would
    otherwise rewrite ~4 GB of identical weights on every job."""
    path = adapter_path(name)
    params = {
        "config": config, "model": model, "rank": rank,
        "target_modules": sorted(target_modules), "seed": seed,
    }
    marker = os.path.join(path, _MARKER)
    if os.path.exists(marker):
        with open(marker) as f:
            if json.load(f) == params:
                return adapter_checksum(path)
    checksum = write_synthetic_adapter(
        path, config=config, base_model=model, rank=rank, target_modules=target_modules, seed=seed
    )
    with open(marker, "w") as f:
        json.dump(params, f)
    return checksum


def prepare_adapters(payload: dict, *, model: str, revision: str, rank: int, target_modules, deps: Deps) -> dict:
    config = deps.model_config(model, revision)
    real = {r["name"]: r for r in payload.get("real_adapters", [])}
    checksums = {}
    for name in payload["registered"]:
        if name in real:
            deps.download_adapter(real[name]["repo"], real[name]["revision"], adapter_path(name))
            checksums[name] = adapter_checksum(adapter_path(name))
        else:
            checksums[name] = ensure_synthetic(
                name, config=config, model=model, rank=rank, target_modules=target_modules,
                seed=synthetic_seed(payload["adapter_seed"], name),
            )
    return checksums


def run_instance(
    payload: dict,
    *,
    model: str,
    revision: str,
    max_model_len: int,
    rank: int,
    target_modules,
    env: dict,
    deps: Deps,
    after_ready: Callable | None = None,
) -> dict:
    t0 = deps.clock()
    checksums = prepare_adapters(
        payload, model=model, revision=revision, rank=rank, target_modules=target_modules, deps=deps
    )
    setup_s = deps.clock() - t0
    args = serve_args(
        revision=revision,
        max_model_len=max_model_len,
        n_slots=payload["n_slots"],
        rank=rank,
        lora_modules={name: adapter_path(name) for name in payload["registered"]},
        specialize_active_lora=payload["specialize_active_lora"],
        disable_log_stats=payload["disable_log_stats"],
    )
    common = {
        "served_cmd": ["vllm", "serve", model, *args],
        "host": deps.host_info(),
        "adapters": checksums,
        "setup_s": setup_s,
    }
    t_start = deps.clock()
    with serve(model, args, env, served=deps.served) as server, tempfile.TemporaryDirectory() as tmp:
        startup_s = deps.clock() - t_start
        if not server.healthy:
            return {"healthy": False, "log_lines": list(server.log_lines), "startup_s": startup_s, **common}
        extra = after_ready(server) if after_ready else {}

        def phase(adapters, n, seed, sub):
            return run_phase(
                server.base_url, model=model, adapters=adapters,
                concurrency=payload["concurrency"], num_requests=n,
                dataset_args=payload["dataset_args"], seed=seed,
                result_dir=os.path.join(tmp, sub), run_bench=deps.run_bench,
            )

        warm = phase(
            payload["registered"],
            payload["warmup_requests_per_adapter"] * len(payload["registered"]),
            payload["run_index"], "warmup",
        )
        sampler = GaugeSampler(
            lambda: deps.http_get(f"{server.base_url}/metrics"), payload["scrape_interval_s"]
        )
        phases = []
        with sampler:
            for spec in payload["phases"]:
                sampler.set_phase(spec["phase_index"])
                result = phase(
                    spec["adapters"], payload["requests_per_phase"],
                    payload["run_index"] * 100 + spec["phase_index"], f"phase{spec['phase_index']}",
                )
                sampler.set_phase(None)
                phases.append({**spec, **result})
        return {
            "healthy": True,
            "log_lines": list(server.log_lines),
            "startup_s": startup_s,
            "warmup": {"num_requests": warm["num_requests"], "failed": warm["failed"]},
            "phases": phases,
            "gauge_samples": sampler.samples,
            **common,
            **extra,
        }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_serving.py tests/test_multilora_instance.py -v`
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add multilora/serving.py multilora/instance.py tests/test_multilora_serving.py tests/test_multilora_instance.py
git commit -m "feat: one server instance end to end, through the shared serve and bench tooling"
```

---

## Task 18: Reconnaissance probes, the recon report, and the budget

Plan 2 runs these against the live endpoint. The probes reuse the instance runner, so reconnaissance exercises the same code path the campaign will. The report computes R1–R9 from captures instead of transcribing them. The budget turns reconnaissance timings into GPU-hours and applies the amendment's cut order.

**Files:**
- Create: `multilora/recon.py`, `multilora/recon_report.py`, `multilora/budget.py`, `tests/test_multilora_recon.py`, `tests/test_multilora_budget.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multilora_recon.py`:

```python
import contextlib

import pytest

from multilora import serving
from multilora.instance import Deps
from multilora.recon import RECON_POINTS, recon_payloads, run_probe
from multilora.recon_report import report

TINY = {
    "hidden_size": 8, "num_attention_heads": 2, "num_key_value_heads": 1,
    "head_dim": 4, "intermediate_size": 16, "num_hidden_layers": 2,
}
HELP = " ".join(serving.ENGINE_FLAGS + serving.BENCH_FLAGS)
GAUGE = 'vllm:lora_requests_info{running_lora_adapters="a00,a01",waiting_lora_adapters=""} 1.0\n'


@pytest.fixture(autouse=True)
def adapter_root(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "ADAPTER_ROOT", str(tmp_path / "adapters"))


def _deps():
    class Server:
        def __init__(self):
            self.base_url = "http://x"
            self.log_lines = ["torch.compile took 0.30 s in total", "GPU KV cache size: 40,000 tokens"]
            self.healthy = True

    @contextlib.contextmanager
    def served(model, *, args, env):
        yield Server()

    def run_bench(base_url, **kw):
        n = kw["num_prompts"]
        return {"duration": n * 0.02, "completed": n, "failed": 0,
                "ttfts": [0.1] * n, "output_lens": [16] * n, "errors": [""] * n}

    return Deps(model_config=lambda m, r: TINY, download_adapter=lambda *a: None,
                http_get=lambda url: GAUGE, host_info=dict, served=served, run_bench=run_bench)


KW = {"model": "m", "revision": "r", "max_model_len": 8192, "rank": 2,
      "target_modules": ("q_proj",), "env": {}}


def test_the_probe_list_covers_each_point_twice_and_the_two_switches():
    payloads = recon_payloads(concurrency=64, dataset_args=["--x"], adapter_seed=1)
    labels = [p["label"] for p in payloads]
    assert labels[0] == "help"
    for n in RECON_POINTS:
        assert f"lora-N{n}-first" in labels and f"lora-N{n}-restart" in labels
    assert "lora-N64-specialize" in labels and "lora-N64-no-stats" in labels
    assert "lora-gate-real" not in labels


def test_real_candidates_add_a_gate_shaped_probe():
    payloads = recon_payloads(concurrency=64, dataset_args=["--x"], adapter_seed=1,
                              real_candidates=[("org/a", "r1"), ("org/b", "r2")])
    gate = payloads[-1]
    assert gate["label"] == "lora-gate-real"
    assert gate["registered"] == ["r00", "r01", "s00", "s01"]
    assert gate["real_adapters"][1] == {"name": "r01", "repo": "org/b", "revision": "r2"}


def test_a_lora_probe_answers_every_adapter_and_scrapes_the_gauge():
    payload = recon_payloads(concurrency=4, dataset_args=["--x"], adapter_seed=1)[3]
    out = run_probe(payload, deps=_deps(), post_status=lambda url, body: 200,
                    post_json=lambda url, body: {"count": 13}, **KW)
    assert set(out["completion_status"]) == set(payload["registered"])
    assert out["a1_prompt_tokens"] == 13
    assert "lora_requests_info" in out["metrics_idle"]
    assert len(out["phases"]) == 1 and out["phases"][0]["regime"] == "spread"


def test_the_help_probe_records_failures_as_answers():
    def run_cmd(cmd):
        return {"cmd": cmd, "returncode": 2, "stdout": "", "stderr": "no such command"}

    out = run_probe({"probe": "help"}, deps=None, post_status=None, run_cmd=run_cmd)
    assert out["bench_help"]["returncode"] == 2


def test_the_report_turns_captures_into_answers():
    payloads = recon_payloads(concurrency=4, dataset_args=["--x"], adapter_seed=1)
    help_out = {"healthy": True,
                "serve_help": {"stdout": HELP, "stderr": ""},
                "bench_help": {"stdout": HELP, "stderr": ""}}
    captures = [{"label": "help", "payload": payloads[0],
                 "outcome": {"payload": help_out, "error": None, "diagnostics": None}}]
    for p in payloads[1:3]:
        out = run_probe(p, deps=_deps(), post_status=lambda url, body: 200,
                        post_json=lambda url, body: {"count": 13}, **KW)
        captures.append({"label": p["label"], "payload": p,
                         "outcome": {"payload": out, "error": None, "diagnostics": None}})
    answers = report(captures)
    assert answers["R4_bench_flags_missing"] == []
    assert answers["R4_engine_flags_missing"] == []
    assert answers["R2_highest_healthy_slots"] == 1
    assert answers["R3_every_adapter_answered"] is True
    assert answers["R6_kv_reported_with_lora"] is True
    assert answers["R7_gauge_exported"] is True
    assert answers["R9_specialize_flag_present"] is True
    assert answers["probes"]["lora-N1-first"]["phase_seconds_per_request"] == pytest.approx(0.02)
    assert answers["request_shape_prompt_tokens"] == [13]


def test_both_help_probes_ask_for_every_flag():
    """vLLM 0.27.1's `vllm bench serve --help` prints no flags; only `--help=all`
    lists them (shared tooling report, 2026-10-04). A plain `--help` would read
    as every bench flag missing, and plan 2's R4 rule would stop for nothing."""
    seen = []

    def run_cmd(cmd):
        seen.append(cmd)
        return {"cmd": cmd, "returncode": 0, "stdout": "", "stderr": ""}

    run_probe({"probe": "help"}, deps=None, post_status=None, run_cmd=run_cmd)
    assert [c[-1] for c in seen] == ["--help=all", "--help=all"]
```

Create `tests/test_multilora_budget.py`:

```python
import pytest

from multilora.budget import estimate, instance_seconds
from tests.conftest import example_prereg

TIMINGS = {
    1: {"setup_s": 5.0, "warm_startup_s": 40.0, "seconds_per_request": 0.01},
    16: {"setup_s": 20.0, "warm_startup_s": 45.0, "seconds_per_request": 0.012},
    64: {"setup_s": 60.0, "warm_startup_s": 55.0, "seconds_per_request": 0.016},
}
COLD = {1: 90.0, 16: 95.0, 64: 110.0}


def test_instance_time_is_setup_startup_warmup_and_four_phases(prereg):
    expected = 5.0 + 40.0 + prereg.warmup_requests_per_adapter * 1 * 0.01 + 4 * 640 * 0.01
    assert instance_seconds(1, prereg, TIMINGS) == pytest.approx(expected)


def test_unmeasured_points_interpolate_in_log2(prereg):
    at_4 = instance_seconds(4, prereg, TIMINGS)
    assert instance_seconds(1, prereg, TIMINGS) < at_4 < instance_seconds(16, prereg, TIMINGS)


def test_within_the_cap_nothing_is_cut():
    res = estimate(example_prereg(gpu_hourly_rate=0.5), TIMINGS, cold_startup_s=COLD, cap_usd=20.0)
    assert res["include_control"] and res["include_diagnostic"]
    assert len(res["steps"]) == 1 and not res["over_cap"]


def test_over_the_cap_the_control_goes_first_then_the_diagnostic():
    pricey = example_prereg(gpu_hourly_rate=1.0)
    full = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=1e9)["usd"]
    res = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=full * 0.93)
    assert [s["step"] for s in res["steps"]][:2] == ["as registered", "control cut"]
    assert res["include_control"] is False
    tight = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=1.0)
    assert tight["include_diagnostic"] is False and tight["over_cap"] is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multilora_recon.py tests/test_multilora_budget.py -v`
Expected: FAIL with `ModuleNotFoundError` for `multilora.recon` and `multilora.budget`.

- [ ] **Step 3: Create `multilora/recon.py`**

```python
"""Reconnaissance: capture what the pinned engine actually does (amendment §6).

Measures nothing that is published. Two probe kinds run in the worker:

- `help`: the engine's and the benchmark client's own help text, which settles
  whether the flags `multilora.serving` uses exist (R4, R9).
- `lora`: one instance through `multilora.instance.run_instance`, with one
  spread phase over every adapter, plus a single completion per adapter and one
  idle scrape of `/metrics` (R2, R3, R5-R8).

`recon_payloads` is the fixed probe list the capture script submits. Its first
three sweep points run twice, so the first compiles and the second shows what a
warm restart costs.
"""

import subprocess

# Artifact 1's request, the inherited shape (August §3): this prompt, 16 output
# tokens. The lora probe asks the engine's own tokenizer how many tokens the
# prompt is, which fixes `--random-input-len` in the pre-registration.
A1_PROMPT = "Explain what a key-value cache does, in two sentences."
A1_OUTPUT_TOKENS = 16

from multilora.conditions import SPREAD, gate_synthetic_name, real_name, synthetic_name
from multilora.instance import run_instance

RECON_POINTS = (1, 16, 64)


def _capture(cmd: list[str]) -> dict:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        return {"cmd": cmd, "returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr}
    except Exception as e:  # noqa: BLE001 -- a missing subcommand is itself the answer
        return {"cmd": cmd, "returncode": None, "stdout": "", "stderr": str(e)}


def help_probe(run_cmd=_capture) -> dict:
    return {
        "healthy": True,
        "serve_help": run_cmd(["vllm", "serve", "--help=all"]),
        # `--help=all`, not `--help`: vLLM 0.27.1's `vllm bench serve --help`
        # prints no flags at all (shared tooling report, 2026-10-04), which
        # would read as every bench flag missing and stop reconnaissance.
        "bench_help": run_cmd(["vllm", "bench", "serve", "--help=all"]),
    }


def lora_probe(payload: dict, *, deps, post_status, post_json, **instance_kw) -> dict:
    def after_ready(server):
        statuses = {
            name: post_status(
                f"{server.base_url}/v1/completions",
                {"model": name, "prompt": "Hello", "max_tokens": 4},
            )
            for name in payload["registered"]
        }
        tokenized = post_json(
            f"{server.base_url}/tokenize", {"model": instance_kw["model"], "prompt": A1_PROMPT}
        )
        return {
            "completion_status": statuses,
            "metrics_idle": deps.http_get(f"{server.base_url}/metrics"),
            "a1_prompt_tokens": tokenized.get("count"),
        }

    return run_instance(payload, deps=deps, after_ready=after_ready, **instance_kw)


def run_probe(
    payload: dict, *, deps, post_status, post_json=None, run_cmd=_capture, **instance_kw
) -> dict:
    if payload["probe"] == "help":
        return help_probe(run_cmd)
    if payload["probe"] == "lora":
        return lora_probe(
            payload, deps=deps, post_status=post_status, post_json=post_json, **instance_kw
        )
    raise ValueError(f"unknown probe {payload['probe']!r}")


def _lora_payload(label, registered, *, concurrency, dataset_args, adapter_seed,
                  specialize=False, disable_log_stats=False, real_adapters=()) -> dict:
    return {
        "probe": "lora",
        "label": label,
        "run_index": 0,
        "condition": "recon",
        "n_slots": len(registered),
        "registered": list(registered),
        "specialize_active_lora": specialize,
        "disable_log_stats": disable_log_stats,
        "phases": [{"phase_index": 0, "regime": SPREAD, "adapters": list(registered)}],
        "concurrency": concurrency,
        "requests_per_phase": max(80, 10 * concurrency),
        "warmup_requests_per_adapter": 1,
        "scrape_interval_s": 1.0,
        "adapter_seed": adapter_seed,
        "dataset_args": list(dataset_args),
        "real_adapters": list(real_adapters),
    }


def recon_payloads(*, concurrency: int, dataset_args, adapter_seed: int, real_candidates=()) -> list[dict]:
    """The fixed probe list. `real_candidates` is [(repo, revision), ...] from
    scripts/a5_find_real_adapters.py; when given, one probe serves them beside
    as many synthetic adapters, which is the gate's configuration (R10)."""
    kw = {"concurrency": concurrency, "dataset_args": dataset_args, "adapter_seed": adapter_seed}
    out = [{"probe": "help", "label": "help"}]
    for n in RECON_POINTS:
        names = [synthetic_name(i) for i in range(n)]
        out.append(_lora_payload(f"lora-N{n}-first", names, **kw))
        out.append(_lora_payload(f"lora-N{n}-restart", names, **kw))
    top = [synthetic_name(i) for i in range(RECON_POINTS[-1])]
    out.append(_lora_payload("lora-N64-specialize", top, specialize=True, **kw))
    out.append(_lora_payload("lora-N64-no-stats", top, disable_log_stats=True, **kw))
    if real_candidates:
        g = len(real_candidates)
        real = [
            {"name": real_name(i), "repo": repo, "revision": rev}
            for i, (repo, rev) in enumerate(real_candidates)
        ]
        names = [r["name"] for r in real] + [gate_synthetic_name(i) for i in range(g)]
        out.append(_lora_payload("lora-gate-real", names, real_adapters=real, **kw))
    return out
```

- [ ] **Step 4: Create `multilora/recon_report.py`**

```python
"""Answers to reconnaissance questions R1-R9, computed from the committed
captures in `fixtures/a5/` (amendment §6). R10 comes from
scripts/a5_find_real_adapters.py and the `lora-gate-real` probe.

Computed rather than transcribed, so `docs/recon-a5.md` can be regenerated and
checked against the captures it cites.
"""

from multilora.engine import engine_facts
from multilora.gauge import running_adapters
from multilora.serving import BENCH_FLAGS, ENGINE_FLAGS, SPECIALIZE_FLAG


def _output(capture: dict) -> dict | None:
    """The worker's output: the payload on success, the diagnostics on an
    unhealthy engine, None when the job produced nothing."""
    outcome = capture["outcome"]
    return outcome.get("payload") or outcome.get("diagnostics")


def _help_text(captures, key) -> str:
    for c in captures:
        if c["label"] == "help" and _output(c):
            h = _output(c)[key]
            return h["stdout"] + h["stderr"]
    return ""


def _lora(captures):
    return [c for c in captures if c["label"].startswith("lora-") and _output(c)]


def _max_running_at_top(healthy: list[dict]) -> int | None:
    """None, not 0, when the gauge produced no sample at the top point: an
    absent observation must not read as an observed zero."""
    if not healthy:
        return None
    top = max(p["n_slots"] for p in healthy)
    seen = [p["max_distinct_running"] for p in healthy
            if p["n_slots"] == top and p["max_distinct_running"] is not None]
    return max(seen) if seen else None


def report(captures: list[dict]) -> dict:
    serve_help = _help_text(captures, "serve_help")
    bench_help = _help_text(captures, "bench_help")
    per_probe = {}
    for c in _lora(captures):
        out = _output(c)
        facts = engine_facts(out.get("log_lines") or [])
        running = [
            len(s["running"]) for s in out.get("gauge_samples", []) if s["running"] is not None
        ]
        phase = (out.get("phases") or [{}])[0]
        per_probe[c["label"]] = {
            "n_slots": c["payload"]["n_slots"],
            "healthy": bool(out.get("healthy")),
            "startup_s": out.get("startup_s"),
            "setup_s": out.get("setup_s"),
            "compile_state": facts["compile_state"],
            "kv_capacity_tokens": facts.get("kv_capacity_tokens"),
            "completions_ok": all(s == 200 for s in (out.get("completion_status") or {}).values())
            if out.get("completion_status") else None,
            "gauge_exported": running_adapters(out.get("metrics_idle") or "") is not None,
            "max_distinct_running": max(running) if running else None,
            "phase_seconds_per_request": (phase["duration_s"] / phase["num_requests"])
            if phase.get("num_requests") else None,
            "phase_arrays_complete": bool(phase) and len(phase["ttfts"]) == phase["num_requests"]
            == len(phase["output_lens"]) == len(phase["errors"]),
            "a1_prompt_tokens": out.get("a1_prompt_tokens"),
        }
    healthy = [p for p in per_probe.values() if p["healthy"]]
    return {
        "R1_in_batch_cap_is_max_loras": "--max-loras" in serve_help,
        "R2_highest_healthy_slots": max((p["n_slots"] for p in healthy), default=None),
        "R3_every_adapter_answered": all(p["completions_ok"] for p in healthy),
        "R4_bench_flags_missing": [f for f in BENCH_FLAGS if f not in bench_help],
        "R4_engine_flags_missing": [f for f in ENGINE_FLAGS if f not in serve_help],
        "R4_phase_arrays_complete": all(p["phase_arrays_complete"] for p in healthy),
        "R5_max_distinct_running_at_top": _max_running_at_top(healthy),
        "R6_kv_reported_with_lora": all(p["kv_capacity_tokens"] for p in healthy),
        "R7_gauge_exported": any(p["gauge_exported"] for p in healthy),
        "R9_specialize_flag_present": SPECIALIZE_FLAG in serve_help,
        "request_shape_prompt_tokens": sorted(
            {p["a1_prompt_tokens"] for p in healthy if p["a1_prompt_tokens"] is not None}
        ),
        "probes": per_probe,
    }
```

- [ ] **Step 5: Create `multilora/budget.py`**

```python
"""The campaign's cost, computed from reconnaissance timings (amendment §6).

Per instance: adapter setup + a warm restart + the warm-up + four timed phases.
Timings are measured at the reconnaissance points (1, 16, 64 slots) and
interpolated linearly in log2(slots) between them. The cut order is the
amendment's: the gauge control first, then the diagnostic. Sweep resolution
is the author's call and is only reported, never cut here.
"""

import math
from dataclasses import replace

from multilora.conditions import GATE, campaign_conditions, parse_condition

TIMED_PHASES = 4


def _interp(points: dict[int, float], n: int) -> float:
    xs = sorted(points)
    if n in points:
        return points[n]
    lo = max(x for x in xs if x < n)
    hi = min(x for x in xs if x > n)
    f = (math.log2(n) - math.log2(lo)) / (math.log2(hi) - math.log2(lo))
    return points[lo] + f * (points[hi] - points[lo])


def instance_seconds(n, prereg, timings) -> float:
    """`timings` maps slots to {'setup_s', 'warm_startup_s', 'seconds_per_request'}."""
    def t(key):
        return _interp({k: v[key] for k, v in timings.items()}, n)

    per_request = t("seconds_per_request")
    warmup = prereg.warmup_requests_per_adapter * n * per_request
    timed = TIMED_PHASES * prereg.requests_per_phase * per_request
    return t("setup_s") + t("warm_startup_s") + warmup + timed


def estimate(prereg, timings, *, cold_startup_s: dict[int, float], cap_usd: float = 20.0) -> dict:
    def total(p):
        seconds = 0.0
        for name in campaign_conditions(p) + [GATE]:
            cond = parse_condition(name, p)
            seconds += p.instances_per_condition * instance_seconds(cond.n_slots, p, timings)
        seconds += sum(_interp(cold_startup_s, n) + _interp(
            {k: v["warm_startup_s"] for k, v in timings.items()}, n) for n in p.sweep)
        return seconds / 3600.0

    steps = []
    current = prereg
    for label, change in (("as registered", {}), ("control cut", {"include_control": False}),
                          ("diagnostic cut", {"include_control": False, "include_diagnostic": False})):
        current = replace(prereg, **change)
        hours = total(current)
        steps.append({"step": label, "gpu_hours": hours, "usd": hours * prereg.gpu_hourly_rate})
        if hours * prereg.gpu_hourly_rate <= cap_usd:
            break
    final = steps[-1]
    return {
        "steps": steps,
        "include_control": current.include_control,
        "include_diagnostic": current.include_diagnostic,
        "gpu_hours": final["gpu_hours"],
        "usd": final["usd"],
        "over_cap": final["usd"] > cap_usd,
        "cap_usd": cap_usd,
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_multilora_recon.py tests/test_multilora_budget.py -v`
Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add multilora/recon.py multilora/recon_report.py multilora/budget.py tests/test_multilora_recon.py tests/test_multilora_budget.py
git commit -m "feat: reconnaissance probes, answers computed from captures, and the budget"
```

---

## Task 19: Worker glue and the guards paid scripts share

`worker_env.py` reads what the endpoint fixes, and refuses a missing value or a set `VLLM_TUNED_CONFIG_FOLDER` before any GPU time is spent. `worker_deps.py` supplies the real effects: Hugging Face downloads, HTTP, and host facts. It is imported only in the worker image, and its Hugging Face import is local, so this repository's environment does not need that package. `cli.py` holds the credential check, the silent-restart guard, the pin extraction, and the choice between the live submitter and the stub.

**Files:**
- Create: `multilora/worker_env.py`, `multilora/worker_deps.py`, `multilora/cli.py`, `tests/test_multilora_worker_env.py`, `tests/test_multilora_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multilora_worker_env.py`:

```python
import pytest

from multilora.worker_env import VOLUME_ENV, instance_kwargs, volume_env

ENV = {
    "MODEL_ID": "Qwen/Qwen3-4B",
    "MODEL_REVISION": "abc",
    "MAX_MODEL_LEN": "8192",
    "A5_MAX_LORA_RANK": "16",
    "A5_TARGET_MODULES": "q_proj,k_proj,v_proj",
}


def test_the_fixed_values_come_from_the_environment():
    kw = instance_kwargs(ENV)
    assert kw == {
        "model": "Qwen/Qwen3-4B", "revision": "abc", "max_model_len": 8192, "rank": 16,
        "target_modules": ("q_proj", "k_proj", "v_proj"),
    }


def test_a_missing_value_fails_before_any_gpu_time():
    with pytest.raises(RuntimeError, match="A5_MAX_LORA_RANK"):
        instance_kwargs({k: v for k, v in ENV.items() if k != "A5_MAX_LORA_RANK"})


def test_tuned_kernel_configs_are_refused():
    with pytest.raises(RuntimeError, match="VLLM_TUNED_CONFIG_FOLDER"):
        instance_kwargs({**ENV, "VLLM_TUNED_CONFIG_FOLDER": "/cfg"})


def test_an_unmounted_volume_is_refused_not_created():
    made = []
    with pytest.raises(RuntimeError, match="not mounted"):
        volume_env(isdir=lambda p: False, makedirs=lambda p, exist_ok: made.append(p))
    assert made == []


def test_a_mounted_volume_gets_artifact_fives_own_cache_root():
    made = []
    env = volume_env(isdir=lambda p: True, makedirs=lambda p, exist_ok: made.append(p))
    assert env == VOLUME_ENV
    assert env["VLLM_CACHE_ROOT"].endswith("/a5/vllm-cache")
    assert sorted(made) == sorted(VOLUME_ENV.values())
```

Create `tests/test_multilora_cli.py`:

```python
import pytest

from multilora.cli import guard_against_silent_restart, pins_from_endpoint, require_credentials

ENDPOINT = {
    "flashboot": False, "gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "vol",
    "templateId": "tpl", "workersMin": 0, "name": "a5", "workersMax": 1,
}


def test_credentials_are_required():
    with pytest.raises(SystemExit, match="RUNPOD_ENDPOINT_ID"):
        require_credentials({"RUNPOD_API_KEY": "k"})
    assert require_credentials({"RUNPOD_API_KEY": "k", "RUNPOD_ENDPOINT_ID": "e"}) == ("k", "e")


def test_a_populated_store_needs_resume_or_force():
    guard_against_silent_restart(0, "s", resume=False, force=False)
    guard_against_silent_restart(5, "s", resume=True, force=False)
    guard_against_silent_restart(5, "s", resume=False, force=True)
    with pytest.raises(SystemExit, match="5 record"):
        guard_against_silent_restart(5, "s", resume=False, force=False)


def test_pins_are_the_five_fields_and_refuse_flashboot():
    assert pins_from_endpoint(ENDPOINT) == {k: ENDPOINT[k] for k in (
        "flashboot", "gpuTypeIds", "networkVolumeId", "templateId", "workersMin")}
    with pytest.raises(ValueError, match="flashboot"):
        pins_from_endpoint({**ENDPOINT, "flashboot": True})
    with pytest.raises(ValueError, match="workersMin"):
        pins_from_endpoint({**ENDPOINT, "workersMin": 1})
    with pytest.raises(ValueError, match="lacks"):
        pins_from_endpoint({"flashboot": False})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_multilora_worker_env.py tests/test_multilora_cli.py -v`
Expected: FAIL with `ModuleNotFoundError` for `multilora.worker_env` and `multilora.cli`.

- [ ] **Step 3: Create `multilora/worker_env.py`**

```python
"""What the worker reads from the endpoint's environment (amendment §4).

Anything not under study is fixed in the endpoint environment rather than
passed per job, as artifact 1's handler does: a per-job override would be a
second thing that can differ between conditions. Missing values fail loudly
at job start, before any GPU time is spent on a misconfigured engine.
"""

import os

VOLUME_ROOT = "/runpod-volume"
# Artifact 5's own compile-cache root. Separate from artifact 1's
# /runpod-volume/vllm-cache so the two artifacts' caches never mix.
VOLUME_ENV = {
    "HF_HOME": f"{VOLUME_ROOT}/hf",
    "VLLM_CACHE_ROOT": f"{VOLUME_ROOT}/a5/vllm-cache",
}
REQUIRED = ("MODEL_ID", "MODEL_REVISION", "MAX_MODEL_LEN", "A5_MAX_LORA_RANK", "A5_TARGET_MODULES")


def instance_kwargs(environ=None) -> dict:
    environ = os.environ if environ is None else environ
    missing = [k for k in REQUIRED if not environ.get(k)]
    if missing:
        raise RuntimeError(f"endpoint environment lacks {missing}")
    if environ.get("VLLM_TUNED_CONFIG_FOLDER"):
        raise RuntimeError(
            "VLLM_TUNED_CONFIG_FOLDER is set; tuned kernel configs key tile choice on "
            "max_loras, a second slot-dependent cost (amendment §3b). Unset it."
        )
    return {
        "model": environ["MODEL_ID"],
        "revision": environ["MODEL_REVISION"],
        "max_model_len": int(environ["MAX_MODEL_LEN"]),
        "rank": int(environ["A5_MAX_LORA_RANK"]),
        "target_modules": tuple(environ["A5_TARGET_MODULES"].split(",")),
    }


def volume_env(isdir=os.path.isdir, makedirs=os.makedirs) -> dict:
    """Engine cache paths on the network volume, refusing to fabricate it.
    Creating a missing mount point would put the caches on container disk and
    make every instance compile cold while looking warm to nothing -- artifact
    1's handler refuses for the same reason."""
    if not isdir(VOLUME_ROOT):
        raise RuntimeError(f"{VOLUME_ROOT} is not mounted")
    for path in VOLUME_ENV.values():
        makedirs(path, exist_ok=True)
    return dict(VOLUME_ENV)
```

- [ ] **Step 4: Create `multilora/worker_deps.py`**

```python
"""The real effects behind `multilora.instance.Deps`, used only in the worker
image. Imports are local so the package imports without huggingface_hub,
which the vLLM image carries and a laptop need not."""

import json
import os
import socket
import subprocess

import requests

from multilora.instance import Deps


def model_config(model: str, revision: str) -> dict:
    from huggingface_hub import hf_hub_download

    with open(hf_hub_download(model, "config.json", revision=revision)) as f:
        return json.load(f)


def download_adapter(repo: str, revision: str, dest: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo, revision=revision, local_dir=dest,
        allow_patterns=["adapter_config.json", "adapter_model.safetensors"],
    )


def http_get(url: str) -> str:
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.text


def post_status(url: str, body: dict) -> int:
    return requests.post(url, json=body, timeout=120).status_code


def post_json(url: str, body: dict) -> dict:
    r = requests.post(url, json=body, timeout=60)
    r.raise_for_status()
    return r.json()


def host_info() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, check=False,
        ).stdout.strip()
        gpu, driver = (p.strip() for p in out.split(",")[:2])
    except Exception:  # noqa: BLE001 -- host metadata never fails a measured run
        gpu, driver = "unknown", "unknown"
    return {
        "gpu_model": gpu,
        "driver_version": driver,
        "host_id": socket.gethostname(),
        "vcpus": os.cpu_count(),
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
    }


def real_deps() -> Deps:
    return Deps(
        model_config=model_config,
        download_adapter=download_adapter,
        http_get=http_get,
        host_info=host_info,
    )
```

- [ ] **Step 5: Create `multilora/cli.py`**

`submitter_for` imports `multilora.pins` only on the live path. Plan 3 creates that module; the `--stub` path never needs it.

```python
"""Guards shared by artifact 5's scripts that spend money."""

import os

PIN_KEYS = ("flashboot", "gpuTypeIds", "networkVolumeId", "templateId", "workersMin")


def require_credentials(environ=None) -> tuple[str, str]:
    environ = os.environ if environ is None else environ
    missing = [n for n in ("RUNPOD_API_KEY", "RUNPOD_ENDPOINT_ID") if not environ.get(n)]
    if missing:
        raise SystemExit(
            f"missing {', '.join(missing)}; load them with `set -a; . ./.env; set +a`"
        )
    return environ["RUNPOD_API_KEY"], environ["RUNPOD_ENDPOINT_ID"]


def guard_against_silent_restart(existing: int, path, *, resume: bool, force: bool) -> None:
    """Forgetting --resume would re-submit and re-pay for every stored run and
    append duplicate run indices. Require --resume, or --force-restart to say
    that is intended -- artifact 1's runner learned this the expensive way."""
    if resume or not existing or force:
        return
    raise SystemExit(
        f"refusing to start: {existing} record(s) already exist in {path} and --resume was "
        "not passed; pass --resume to continue, or --force-restart to re-run from index 0"
    )


def pins_from_endpoint(endpoint: dict) -> dict:
    """The five fields artifact 1 pinned, read off a live endpoint. Refuses an
    endpoint whose configuration would measure the platform instead of the
    engine: FlashBoot on, or a warm worker kept around."""
    missing = [k for k in PIN_KEYS if k not in endpoint]
    if missing:
        raise ValueError(f"endpoint lacks {missing}")
    pins = {k: endpoint[k] for k in PIN_KEYS}
    if pins["flashboot"] is not False:
        raise ValueError("flashboot must be off")
    if pins["workersMin"] != 0:
        raise ValueError("workersMin must be 0")
    return pins


def submitter_for(*, stub: bool):
    """The live RunPod submitter after a passing preflight, or the stub for a
    GPU-free rehearsal of exactly the same path."""
    if stub:
        from harness.submit import PayloadStubSubmitter
        from multilora.stub import StubInstanceEndpoint

        return PayloadStubSubmitter(StubInstanceEndpoint(seed=0).run)
    from harness.runpod.preflight import assert_endpoint_matches, fetch_endpoint
    from harness.runpod.submitter import HttpTransport, RunPodSubmitter
    from multilora.pins import PINNED

    key, endpoint_id = require_credentials()
    assert_endpoint_matches(fetch_endpoint(endpoint_id, key), PINNED)
    print(f"[preflight] endpoint {endpoint_id} matches multilora/pins.py", flush=True)
    return RunPodSubmitter(HttpTransport(endpoint_id, key))
```

- [ ] **Step 6: Run the tests, and check the worker module imports here**

Run: `.venv/bin/python -m pytest tests/test_multilora_worker_env.py tests/test_multilora_cli.py -v`
Expected: 8 passed.

Run: `.venv/bin/python -c "import multilora.worker_deps; print('ok')"`
Expected: `ok`, even though `huggingface_hub` is not installed here.

- [ ] **Step 7: Commit**

```bash
git add multilora/worker_env.py multilora/worker_deps.py multilora/cli.py tests/test_multilora_worker_env.py tests/test_multilora_cli.py
git commit -m "feat: worker environment and effects, and the guards paid scripts share"
```

---

## Task 20: Render from the stub and look at every figure

**Files:**
- Create: `scripts/a5_stub_demo.py`, `scripts/a5_render_figures.py`

- [ ] **Step 1: Create `scripts/a5_stub_demo.py`**

```python
"""Produce a stub analysis for laying out artifact 5's figures. NOT DATA.

    .venv/bin/python scripts/a5_stub_demo.py --out build/a5-stub

Runs both schedules against the stub worker and writes analysis.json. Every
value comes from `multilora.stub.StubModel`; nothing here may be published.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.prereg import Preregistration
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint

DEMO = Preregistration(
    concurrency=64, rank=16,
    target_modules=("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"),
    gate_adapters=4, warmup_requests_per_adapter=2, scrape_interval_s=1.0, knee_threshold=0.08,
    request_tokens=30, context_length_tokens=8192, slo_ttft_p95_s=2.0,
    requests_per_tenant_month=100_000.0, peak_to_average=3.0, gpu_hourly_rate=1.0,
    schedule_seed=1, include_diagnostic=True, include_control=True,
    bench_dataset_args=("--dataset-name", "random", "--random-input-len", "14",
                        "--random-output-len", "16"),
    real_adapters=tuple((f"example/adapter-{i}", f"rev{i}") for i in range(4)),
)
DEMO_A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = {}
    for name, schedule in (("campaign", campaign_schedule(DEMO)), ("gate", gate_schedule(DEMO))):
        path = out / f"{name}.jsonl"
        path.unlink(missing_ok=True)
        store = JsonlStore(path, InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=3).run), store, DEMO)
        records[name] = store.read_all()
    result = analyse(records["campaign"], records["gate"], DEMO, a4=DEMO_A4, iterations=2000)
    result["NOT_DATA"] = "stub output from multilora.stub; never publish"
    (out / "analysis.json").write_text(json.dumps(result, indent=1, sort_keys=True))
    print(f"[ok] {out / 'analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create `scripts/a5_render_figures.py`**

```python
"""Render artifact 5's four figures from an analysis file.

    .venv/bin/python scripts/a5_render_figures.py --analysis data/a5/analysis.json --out build/a5-figures

Also writes a 375 px wide `-phone.png` copy of each figure, which is what gets
looked at for legibility before a figure is called done.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt
from PIL import Image

from harness.figure_guards import PHONE_WIDTH_PX
from multilora.figures import FIGURES


def phone_copy(src: Path) -> Path:
    """Downscale to the width `harness.figure_guards` calibrates legibility at."""
    dst = src.with_name(src.stem + "-phone.png")
    with Image.open(src) as im:
        height = round(im.height * PHONE_WIDTH_PX / im.width)
        im.resize((PHONE_WIDTH_PX, height), Image.LANCZOS).save(dst)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    analysis = json.loads(Path(args.analysis).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, draw in FIGURES.items():
        if name == "cost_per_tenant" and "cost_table" not in analysis:
            print(f"[skip] {name}: no cost table (artifact 4 results not supplied)")
            continue
        path = out / f"{name}.png"
        plt.close(draw(analysis, path))
        print(f"[ok] {path} and {phone_copy(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Render**

```bash
.venv/bin/python scripts/a5_stub_demo.py --out build/a5-stub
.venv/bin/python scripts/a5_render_figures.py --analysis build/a5-stub/analysis.json --out build/a5-stub/figures
```

Expected: `[ok]` for `analysis.json` and for each of the four figures and their `-phone.png` copies. `build/` is gitignored. Nothing here is data.

- [ ] **Step 4: Look at each desktop figure**

Open all four `build/a5-stub/figures/*.png` files that do not end in `-phone.png`. Check each against this list, and fix `multilora/figures.py` before moving on if any item fails:

- **throughput_ttft:** two stacked panels on a shared log-2 x axis, with ticks at 1, 2, 4, 8, 16, 32 and 64. Both regimes have error bars, the gap between them is shaded, the y axes start at 0, the title states n, and the legend covers no data.
- **kv_capacity:** a median line, per-instance dots, a y axis from 0, and the max-concurrency note inside the axes.
- **equivalence:** the ±margin band, per-instance dots, two interval bars per panel, the legend below both panels covering nothing, and the verdict and n in the title.
- **cost_per_tenant:** one bar per strategy starting at 0, the adapter bar hatched, dollar labels at the bar ends, and the two-line assumptions note below the axis with no large empty band.

- [ ] **Step 5: Look at each phone copy**

Open the four `*-phone.png` files. They are 375 px wide, the width the harness calibrates legibility at. Every label, tick and legend entry must be readable without zooming. The tests already assert the size floor, and this step catches overlap and clipping, which they cannot.

- [ ] **Step 6: Commit the scripts**

```bash
git add scripts/a5_stub_demo.py scripts/a5_render_figures.py
git commit -m "feat: stub rendering path for laying out artifact 5's figures"
```

---

## Task 21: Full verification

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: every test passes, including artifact 1's published-figure and reproducibility tests. This plan adds 145.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check multilora harness scripts tests coldstart`
Expected: `All checks passed!`

- [ ] **Step 3: Run the parity gate**

Run: `./scripts/parity_check.sh`
Expected: `PARITY OK`. Artifact 1's published numbers and figures are unchanged by this plan.

- [ ] **Step 4: Confirm the boundary**

Run: `.venv/bin/python -m pytest tests/test_multilora_boundary.py tests/test_harness_boundary.py -v`
Expected: all pass. `multilora/` imports no `coldstart/` or `autoscale/`, and `harness/` imports no `coldstart/`.

---

## Self-review notes

**Spec coverage, amendment §5's build list:**

| Build item | Task |
|---|---|
| Synthetic adapter writer | 7 |
| Real-adapter qualification and deterministic selection | 7 |
| Worker handler logic, with the gauge sampler | 11, 17 |
| Cache configuration (network-volume paths, refusing an unmounted volume) | 19 |
| Record class | 9 |
| Analysis: per-instance estimands, paired heterogeneity cost, knee, equivalence test | 10, 12, 14 |
| Cost table from artifact 4's output | 13 |
| Four figures with their tests | 16, 20 |
| GPU-free stub | 14 |
| Reconnaissance probes and report | 18 |
| Priming payloads and check | 9, 15 |
| Campaign-loop lift, `run_campaign` migrated | landed on `main` 2026-10-04; Task 3 verifies |
| Generic multi-sample bootstrap | 2 |
| `submit_payload` and the payload stub | landed on `main` 2026-10-04; Task 4 verifies |

Left to plan 2: the worker image changes and both handler files, the reconnaissance scripts and run, `docs/recon-a5.md`, `docs/experiment-a5.md` and `prereg_values.py`. Left to plan 3: the pin set, the priming and campaign runs, the analysis and numbers scripts, the published figures and their byte-exact test, and the post.

**Amendment §4 coverage:** the one-instance structure is the phase plan (Task 6), the payload (Task 9) and the instance runner (Task 17). 24 instances per condition is enforced in Task 5. The estimands are Task 14, the knee and the gate Task 12, and tenants Task 13. The difference in differences uses Task 2's bootstrap. Amendment §3d's compile-state rule is Task 8, and §3f's failure rule is Task 10.

**Parity:** this plan no longer changes artifact 1's code. The campaign-loop migration it originally carried landed on `main` with the shared tooling work, gated there by artifact 1's driver tests and the parity gate. Task 2 is additive to `harness/stats.py`, and the parity gate runs after it.

**Type consistency:** `InstanceRecord`'s fields, the payload keys in `records.py`'s docstring, `job_payload`'s keys, the stub's output and `run_instance`'s output were checked against each other by running them into `build_record` (Tasks 14 and 17).
