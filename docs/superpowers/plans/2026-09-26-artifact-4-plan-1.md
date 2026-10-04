# Artifact 4 Plan 1 — the GPU-free Placement Simulator and Analysis

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and prove, with no GPU and no spend, everything artifact 4's crossover rests on that needs no measurement: model-labelled traffic, the placement simulator, fleet sizing, the per-decile fairness view, the crossover estimator and its interval, the money view, the run-length pilot, and the sweep that ties them together.

**Architecture:** A new `placement/` package that never loads `coldstart`, directly or transitively; a subprocess test enforces it from Task 1. It reuses artifact 2's coldstart-free `autoscale/events.py` and `autoscale/service.py`, and the shared statistics in `harness/stats.py`. It writes its own simulation loop, because artifact 2's has no replica identity. Each strategy is a family of placements in ascending GPU count. Every (configuration, repetition) pair is simulated on common random numbers. Sizing then picks each strategy's smallest SLO-meeting fleet per grid point, and a repetition bootstrap re-sizes inside every draw to locate where the cheapest strategy changes. All inputs are placeholders flagged unmeasured, and the sweep refuses them without an explicit flag.

**Tech Stack:** Python 3.13 standard library; numpy in the run-length pilot only, already installed as a matplotlib dependency; pytest; ruff. No new dependencies.

**Governing documents:** [the scope amendment](../specs/2026-09-26-multi-model-serving-economics-scope.md), approved 2026-09-26 with all twelve decisions accepted, which governs where it conflicts with [the August design](../specs/2026-08-17-multi-model-serving-economics-design.md). Section numbers below are the amendment's unless marked "August".

---

## Scope of this plan

This is **plan 1 of three** for artifact 4, plus the shared in-container tooling plan that amendment decision 4 creates. It covers the amendment's §1e items 1, 2, 3, 9, 10 and 13, and the GPU-free half of §2's gates. The last section says what the other plans cover and why they cannot be written yet.

**This plan adds only.** No existing module is replaced, slimmed or deleted. `autoscale/`, `coldstart/` and `harness/` are read and never modified. So no capability inventory, "before" baseline or parity gate is required.

**No task changes pixels.** All four figures are deferred to plan 3, where two of them need measured data and the figure guards will have moved (extraction task 11). The UI verification rules therefore do not apply to this plan. They apply in full to plan 3.

**Every line of code in this plan was run before it was written down.** It ran in a scratch copy of the repository where `harness/stats.py` was a verbatim copy of `coldstart/analysis/stats.py`, which is exactly what extraction task 4 produces. The 121 tests below passed there, and ruff passed with the repository's settings. The plan's code blocks are generated from those files, not retyped.

## Prerequisites — STOP if either is false

1. **Before Task 1: extraction task 4 has landed** (`docs/superpowers/plans/2026-09-03-harness-extraction.md`). Amendment §2 gates GPU-free work on it, because code written against `coldstart.analysis.stats` would be rewritten when it moves.

   ```bash
   test -f harness/stats.py && grep -q "def percentiles" harness/stats.py && echo OK
   ```

2. **Before Task 16 only: artifact 2 plan 2a Task 5 has landed** (`docs/superpowers/plans/2026-09-26-artifact-2-plan-2a.md`). The sweep script imports `autoscale.traffic.saturation_rps` rather than re-deriving it. Tasks 1–15 do not need it.

   ```bash
   grep -q "def saturation_rps" autoscale/traffic.py && echo OK
   ```

## Rules this plan operates under

- **Several workstreams share this checkout.** Artifacts 2 and 5 commit here too. Never `git add -A` or `git add .`; every commit step names its files. Run ruff only on the files a task touched.
- **`PYTHONDONTWRITEBYTECODE=1`** on every pytest run, as artifact 2's plans require. A stale bytecode cache can make moved code look like it still works.
- **Test counts are not quoted as absolutes.** Other workstreams add tests. "Passes" means pytest exits 0. A count that drops between two runs means a test file stopped being collected, and is a stop-and-investigate.
- **House style.** Every error message names what went wrong and the consequence of it passing silently. Every docstring says why, including the alternative rejected. Reviewers hold new code to both.

## Decisions already fixed — not re-opened by this plan

These are the amendment's, recorded here so an implementer does not re-derive them:

- `placement/` never loads `coldstart`, checked transitively (§7).
- Hot models get pinned solo GPUs in every strategy; the strategies differ only on the tail (§7).
- Swap grows its pool one GPU at a time; co-locate starts fully paired, busiest with least busy, and un-pairs its busiest pair per added GPU; both reach dedicate's capacity at dedicate's M (§7).
- Sizing is once per grid point: the smallest M whose median-across-repetitions p99 meets the SLO in every decile (§7).
- A decile's p99 is published at a grid point only if it clears the 500-sample floor in every repetition (§8).
- Drain-out, not censoring; warm-up arrivals simulated but not reported (§7).
- The crossover is a pair of adjacent grid points; its interval comes from resampling repetitions through sizing and location (§8).

One refinement is made by this plan and recorded in Task 7: LRU counts a dispatch as a use, not only an arrival.

---

## File structure

```
placement/
  __init__.py      empty
  resample.py      measured swap times, resampled             (Task 3)
  traffic.py       Zipf shares, deciles, spread and bursty    (Task 4)
  colocated.py     two-load latency surface                   (Task 5)
  fleet.py         hot-model rule, placement families         (Task 6)
  sim.py           the placement simulator                    (Task 7)
  tails.py         per-decile p99 under the floor             (Task 8)
  evaluate.py      one grid point, common random numbers      (Task 9)
  sizing.py        smallest SLO-meeting fleet                 (Task 10)
  crossover.py     crossover and its interval                 (Task 11)
  money.py         monthly cost; calendar pinned to A1's      (Task 12)
  runlength.py     the run-length pilot                       (Task 13)
  design.py        the sweep's design record                  (Task 14)
  placeholders.py  invented inputs, flagged unmeasured        (Task 14)
scripts/
  a4_sweep.py      the sweep                                  (Task 16)
tests/
  test_placement_boundary.py            (Task 1)
  test_placement_no_reimplementation.py (Task 2)
  test_placement_<module>.py            one per module, Tasks 3-14
  test_a4_end_to_end.py                 (Task 15)
  test_a4_sweep.py                      (Task 16)
```

Imports run one way: `traffic`, `colocated`, `resample` and `fleet` depend on nothing in the package; `sim` on those; `tails` on `sim`; `evaluate` on all of them; `sizing` on `evaluate`; `crossover` on `sizing`. `money`, `runlength` and `design` sit beside them.

---

## Task 1: The `placement/` package and its transitive import boundary

**Files:**
- Create: `placement/__init__.py`
- Test: `tests/test_placement_boundary.py`

The package's defining constraint lands first, so every later task is checked against it from the moment it exists. `placement/` may never load `coldstart`, directly or transitively. The existing `tests/test_autoscale_boundary.py` only parses direct imports. That is not enough here: `autoscale.sim` never names `coldstart` but loads it through `autoscale.coldstart_ecdf`. So this test imports each module in a fresh subprocess and inspects `sys.modules`. It also guards the guard in both directions: the package must exist, and the probe must report `autoscale.sim` as loading `coldstart`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_boundary.py`:

```python
"""`placement/` must never load `coldstart`, directly or transitively.

Artifact 4 depends on artifact 1 for measured numbers only, and only figure 4
needs them. Keeping every other module coldstart-free means the simulator runs
without artifact 1's store on disk, and the pending harness extraction never
has to touch this package.

A direct-import check is not enough here, which is why this test differs from
tests/test_autoscale_boundary.py. `autoscale.sim` imports
`autoscale.coldstart_ecdf`, which imports `coldstart` when it loads, so a
module that imports only `autoscale.sim` passes a direct check while loading
artifact 1 anyway. This test imports each module and inspects `sys.modules`.

Each import runs in a fresh subprocess. pytest shares `sys.modules` across the
whole session, and other test files import `coldstart`, so an in-process check
would pass or fail depending on which tests ran first.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "placement"

# Module file names allowed to load `coldstart`. Empty until the measurement
# plan adds figure 4's adapter, which reads artifact 1's published stage
# medians. When it lands, add its file name here and nothing else.
ADAPTERS: frozenset[str] = frozenset()

_PROBE = (
    "import importlib, sys; importlib.import_module({name!r}); "
    "print(any(m == 'coldstart' or m.startswith('coldstart.') for m in sys.modules))"
)


def _loads_coldstart(module: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(name=module)],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert result.returncode == 0, f"importing {module} failed:\n{result.stderr}"
    return result.stdout.strip() == "True"


def _module_name(path: Path) -> str:
    parts = path.relative_to(REPO).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def test_the_package_exists():
    """Guards the guard: `rglob` over a missing directory yields nothing, so
    the test below would pass vacuously if `placement/` were never created."""
    assert (PACKAGE / "__init__.py").is_file()


def test_no_module_loads_coldstart_even_transitively():
    offenders = [
        _module_name(path)
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name not in ADAPTERS and _loads_coldstart(_module_name(path))
    ]
    assert offenders == [], (
        f"{offenders} load `coldstart` when imported. Only figure 4's adapter "
        "may. Look for an import of autoscale.sim or autoscale.coldstart_ecdf, "
        "both of which load artifact 1 transitively, and take the measured "
        "numbers as parameters instead."
    )


def test_the_probe_sees_a_transitive_import():
    """Guards the guard in the other direction. `autoscale.sim` never names
    `coldstart` but loads it through `autoscale.coldstart_ecdf`. If the probe
    reported False here, the check above would be blind to exactly the case it
    exists for."""
    assert _loads_coldstart("autoscale.sim")
    assert not _loads_coldstart("autoscale.events")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_boundary.py -q`

Expected: FAIL: `test_the_package_exists` — `placement/__init__.py` does not exist yet. The other two pass: the scan over a missing directory is vacuous, which is exactly why the first test exists.

- [ ] **Step 3: Create the package**

```bash
mkdir -p placement && : > placement/__init__.py
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add placement/__init__.py tests/test_placement_boundary.py
git commit -m "feat: the placement package, and a boundary that sees transitive imports"
```

---

## Task 2: No re-implementation of the shared libraries

**Files:**
- Test: `tests/test_placement_no_reimplementation.py`

The amendment's rule is "never a third copy" of the statistics or the figure guards. It replaces the August DoD's unmeasurable "does not re-implement" with a check (amendment §12). The check is a name collision between any function `placement/` defines and any module-level function in `harness/stats.py`, `autoscale/stats.py`, or the figure guards. Until extraction task 11 moves the guards, they live in `coldstart/analysis/figures.py`, and the test falls back to that file automatically. Only module-level names count on the reference side. A helper nested inside a chart function cannot be imported, so counting it produced a false collision on `draw` while this plan was written.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_no_reimplementation.py`:

```python
"""No function in `placement/` re-implements one the shared libraries define.

The amendment's rule is "never a third copy" of the statistics or the figure
guards. A rule like that rots unless something checks it, and "does not
re-implement" cannot be checked directly, so this checks the observable
symptom: a function name, public or private, that `placement/` defines and a
reference module also defines.

A name collision is not proof of duplication, and a renamed copy would slip
past. It catches the common case, where a helper is re-written under its
familiar name. A deliberate local helper that shares a name goes in `ALLOWED`
with the reason beside it, so the exception is visible in review.

Modules are parsed, not imported, so this needs no `sys.modules` isolation.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "placement"

# name -> why placement/ deliberately defines it too.
ALLOWED: dict[str, str] = {}


def _reference_files() -> list[Path]:
    files = [REPO / "harness" / "stats.py", REPO / "autoscale" / "stats.py"]
    guards = REPO / "harness" / "figure_guards.py"
    # Until the extraction's task 11 moves them, the figure guards live in
    # artifact 1's figures module.
    files.append(guards if guards.is_file() else REPO / "coldstart" / "analysis" / "figures.py")
    return files


def _defined(path: Path) -> set[str]:
    """Every function and method name in `path`, at any depth."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _shared(path: Path) -> set[str]:
    """Module-level function names only. A shared helper is something another
    module can import, which a function nested inside a chart function is not;
    counting those would flag names like `draw` that collide by accident."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_the_reference_modules_exist():
    """Guards the guard: a missing reference file would make every name look
    unique. `harness/stats.py` appears when the extraction's task 4 lands,
    which is this plan's prerequisite."""
    missing = [str(p.relative_to(REPO)) for p in _reference_files() if not p.is_file()]
    assert missing == [], f"reference modules missing: {missing}"


def test_the_parser_sees_known_definitions():
    assert "median" in _shared(REPO / "harness" / "stats.py")


def test_placement_defines_nothing_the_shared_libraries_define():
    reference: set[str] = set()
    for path in _reference_files():
        reference |= _shared(path)
    collisions = sorted(
        (name, str(path.relative_to(REPO)))
        for path in sorted(PACKAGE.rglob("*.py"))
        for name in _defined(path) & reference
        if name not in ALLOWED
    )
    assert collisions == [], (
        f"{collisions}: these names are already defined by a shared library. "
        "Import the shared function instead of writing a new one, or add the "
        "name to ALLOWED with the reason it has to be local."
    )
```

- [ ] **Step 2: Run it**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_no_reimplementation.py -q`

Expected: PASS: the package holds only `__init__.py`. A check that has never failed proves nothing, so the next step makes it fail on purpose.

- [ ] **Step 3: Prove it bites, then remove the probe**

```bash
printf 'def median(values):\n    return 0\n' > placement/_bite.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_no_reimplementation.py -q
rm placement/_bite.py
```

Expected: FAIL naming `('median', 'placement/_bite.py')`, then the file is removed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_placement_no_reimplementation.py
git commit -m "test: placement must not re-implement the shared statistics or figure guards"
```

---

## Task 3: An empirical distribution for swap times

**Files:**
- Create: `placement/resample.py`
- Test: `tests/test_placement_resample.py`

Swap durations are drawn from the measured sample, the way artifact 2 draws cold-start lags. `autoscale.coldstart_ecdf.LagDistribution` does this already, but its module loads `coldstart`, so importing it would break Task 1's boundary (amendment §1c). The class is short, and its validation is the part that matters. It carries a `measured` flag, as `ServiceCurve` does, so the sweep can refuse placeholders. The method is `draw`, not `sample`, to keep the name distinct from anything the shared modules might define.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_resample.py`:

```python
import random

import pytest

from placement.resample import EmpiricalDistribution


def test_a_draw_is_always_a_measured_value():
    dist = EmpiricalDistribution(samples=(12.0, 18.5, 30.0), measured=True)
    rng = random.Random(3)
    assert {dist.draw(rng) for _ in range(200)} == {12.0, 18.5, 30.0}


def test_draws_are_reproducible_from_the_seed():
    dist = EmpiricalDistribution(samples=(1.0, 2.0, 3.0, 4.0), measured=True)
    first = [dist.draw(random.Random(9)) for _ in range(5)]
    again = [dist.draw(random.Random(9)) for _ in range(5)]
    assert first == again


@pytest.mark.parametrize(
    "samples",
    [(), (float("nan"),), (float("inf"),), (-1.0,), (True,), ("3",)],
)
def test_it_refuses_samples_that_would_corrupt_a_run(samples):
    with pytest.raises(ValueError):
        EmpiricalDistribution(samples=samples, measured=True)


def test_samples_cannot_be_mutated_after_validation():
    dist = EmpiricalDistribution(samples=[1.0, 2.0], measured=True)
    assert isinstance(dist.samples, tuple)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_resample.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.resample'`

- [ ] **Step 3: Implement**

Create `placement/resample.py`:

```python
"""A measured sample to draw from, resampled rather than fitted.

Artifact 2 draws cold-start lags the same way, through
`autoscale.coldstart_ecdf.LagDistribution`. That class is not reused: its
module imports `coldstart` when it loads, and nothing in `placement/` may load
`coldstart` (tests/test_placement_boundary.py). The idea is reused; the
dependency is not.

Resampling, not fitting, for artifact 2's reason: a parametric tail invents
structure the data does not show, and the swap-time tail is what decides how
badly swap treats cold tenants.
"""

import math
import random
from dataclasses import dataclass

__all__ = ["EmpiricalDistribution"]


@dataclass(frozen=True)
class EmpiricalDistribution:
    """Measured durations in seconds. `measured` is False for a placeholder.

    The flag exists for the reason `ServiceCurve.measured` does: a sweep run on
    invented numbers produces output that looks exactly like a real one, so the
    sweep script refuses an unmeasured input unless told otherwise.
    """

    samples: tuple[float, ...]
    measured: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", tuple(self.samples))
        if not self.samples:
            raise ValueError(
                "an empirical distribution needs at least one sample; an empty "
                "one has nothing to draw, and a caller that defaulted it to zero "
                "would simulate swaps that cost nothing"
            )
        for i, v in enumerate(self.samples):
            if isinstance(v, bool) or not isinstance(v, int | float):
                # ValueError, not TypeError: every sibling check here raises
                # ValueError naming the index, so a caller catches one type.
                raise ValueError(  # noqa: TRY004
                    f"sample [{i}] is {v!r}, not a number; a bool passes "
                    "isinstance(v, int) and would be drawn as 0 or 1 seconds"
                )
            if not math.isfinite(v):
                raise ValueError(
                    f"sample [{i}] is {v!r}; a non-finite duration either raises "
                    "deep inside the event loop or, as +inf, parks a GPU forever"
                )
            if v < 0:
                raise ValueError(
                    f"sample [{i}] is {v!r}; a negative swap time would make a "
                    "GPU ready before its swap began"
                )

    def draw(self, rng: random.Random) -> float:
        """One value. The caller supplies `rng`, so a run is reproducible from one seed."""
        return rng.choice(self.samples)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_resample.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/resample.py tests/test_placement_resample.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/resample.py tests/test_placement_resample.py
git commit -m "feat: an empirical swap-time distribution that does not load artifact 1"
```

---

## Task 4: Model-labelled traffic: Zipf shares, deciles, spread and bursty traces

**Files:**
- Create: `placement/traffic.py`
- Test: `tests/test_placement_traffic.py`

Two regimes with identical frequency and different locality (amendment §7). The bursty generator is a per-model ON/OFF process whose long-run rate equals the model's Zipf share, starting each model in its stationary state so a run does not open with every model ON. Two tests carry the regime distinction: long-run rates must follow the shares in both regimes, and bursty traffic must cluster where spread does not, measured as the variance-to-mean ratio of binned counts. The rate test pools ten seeds. One bursty run's rate spreads by 3–4%, measured over 40 seeds while this plan was written, with mean error under 0.5% for every model. A single seed at a 10% tolerance passed only by luck.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_traffic.py`:

```python
import math
import random
from collections import Counter

import pytest

from placement.traffic import bursty_trace, decile_of, spread_trace, zipf_shares


def test_zipf_shares_sum_to_one_and_fall_with_rank():
    shares = zipf_shares(20, 1.0)
    assert math.isclose(sum(shares), 1.0)
    assert list(shares) == sorted(shares, reverse=True)


def test_zipf_shares_match_the_amendments_table():
    """Amendment §8: at s = 2.0 over 20 models the coldest decile (the two
    least popular models) carries 0.33% of traffic, and the hottest model
    62.7%."""
    shares = zipf_shares(20, 2.0)
    assert round(shares[18] + shares[19], 4) == 0.0033
    assert round(shares[0], 3) == 0.627


def test_s_zero_is_uniform():
    assert zipf_shares(4, 0.0) == (0.25, 0.25, 0.25, 0.25)


@pytest.mark.parametrize("n, s", [(1, 1.0), (20, -0.5), (20, float("nan")), (2.0, 1.0)])
def test_zipf_refuses_bad_parameters(n, s):
    with pytest.raises(ValueError):
        zipf_shares(n, s)


def test_deciles_split_models_evenly_hottest_first():
    assert decile_of(20) == tuple(k // 2 for k in range(20))
    with pytest.raises(ValueError):
        decile_of(25)


@pytest.mark.parametrize("generator", ["spread", "bursty"])
def test_long_run_rates_follow_the_shares(generator):
    """Pooled over ten seeds. One bursty run's rate for a model is set by its
    total ON time, which spreads by 3-4% per run at this window (measured over
    40 seeds while writing this test, with mean error under 0.5% for every
    model). Pooling ten runs puts 5% at about four standard errors, so the test
    checks the generator's bias, not one seed's luck."""
    shares = zipf_shares(4, 1.0)
    until = 100000.0
    totals = Counter()
    for seed in range(10):
        rng = random.Random(seed)
        if generator == "spread":
            trace = spread_trace(shares, 2.0, until, rng)
        else:
            trace = bursty_trace(shares, 2.0, until, mean_burst=20.0, duty=0.2, rng=rng)
        totals.update(model for _, model in trace)
    for k, share in enumerate(shares):
        assert totals[k] / (10 * until) == pytest.approx(2.0 * share, rel=0.05)


def _dispersion(trace, model, until, width):
    """Variance over mean of per-window request counts. About 1 for Poisson."""
    bins = [0] * int(until // width)
    for t, m in trace:
        if m == model and t < len(bins) * width:
            bins[int(t // width)] += 1
    mean = sum(bins) / len(bins)
    return sum((b - mean) ** 2 for b in bins) / len(bins) / mean


def test_bursty_clusters_and_spread_does_not():
    """The whole reason for two regimes: same shares, different clustering."""
    shares = zipf_shares(4, 1.0)
    until = 20000.0
    spread = spread_trace(shares, 2.0, until, random.Random(2))
    bursty = bursty_trace(shares, 2.0, until, 20.0, 0.2, random.Random(2))
    assert _dispersion(spread, 0, until, 10.0) == pytest.approx(1.0, abs=0.15)
    assert _dispersion(bursty, 0, until, 10.0) > 3.0


@pytest.mark.parametrize("generator", ["spread", "bursty"])
def test_a_trace_is_sorted_and_inside_the_window(generator):
    shares = zipf_shares(4, 0.5)
    rng = random.Random(5)
    if generator == "spread":
        trace = spread_trace(shares, 5.0, 100.0, rng)
    else:
        trace = bursty_trace(shares, 5.0, 100.0, 10.0, 0.3, rng)
    times = [t for t, _ in trace]
    assert times == sorted(times)
    assert all(0.0 < t <= 100.0 for t in times)
    assert {m for _, m in trace} <= {0, 1, 2, 3}


def test_traces_are_reproducible_from_the_seed():
    shares = zipf_shares(4, 1.0)
    assert spread_trace(shares, 3.0, 50.0, random.Random(8)) == spread_trace(
        shares, 3.0, 50.0, random.Random(8)
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shares": (0.5, 0.4), "total_rate": 1.0, "until": 10.0},
        {"shares": (0.5, 0.5), "total_rate": 0.0, "until": 10.0},
        {"shares": (0.5, 0.5), "total_rate": 1.0, "until": float("inf")},
        {"shares": (1.0, 0.0), "total_rate": 1.0, "until": 10.0},
    ],
)
def test_spread_refuses_inputs_that_misstate_the_load(kwargs):
    with pytest.raises(ValueError):
        spread_trace(rng=random.Random(0), **kwargs)


@pytest.mark.parametrize("duty", [0.0, 1.0, float("nan")])
def test_bursty_refuses_a_duty_that_is_not_a_burst(duty):
    with pytest.raises(ValueError):
        bursty_trace((0.5, 0.5), 1.0, 10.0, 5.0, duty, random.Random(0))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_traffic.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.traffic'`

- [ ] **Step 3: Implement**

Create `placement/traffic.py`:

```python
"""Model-labelled arrival traces: Zipf popularity, two locality regimes.

Frequency and locality are separate axes (August design §7). Two traces with
the same Zipf shares can produce very different swap rates, because LRU follows
whether a model's requests cluster in time, not how often they occur. Both
generators take the same `shares`, so the only thing that differs between the
regimes is clustering.

Model ids are popularity ranks: model 0 is the hottest.
"""

import bisect
import itertools
import math
import random
from collections.abc import Sequence

__all__ = ["DECILES", "Trace", "bursty_trace", "decile_of", "spread_trace", "zipf_shares"]

DECILES = 10

Trace = list[tuple[float, int]]


def zipf_shares(n_models: int, s: float) -> tuple[float, ...]:
    """Share of traffic per model: p(k) proportional to (k + 1) ** -s, k = 0..n-1.

    s = 0 is uniform. The amendment states the form as p(k) ∝ k^-s over
    k = 1..N; this is the same distribution indexed from zero.
    """
    if type(n_models) is not int or n_models < 2:
        raise ValueError(
            f"n_models must be an int of at least 2, got {n_models!r}; with one "
            "model there is nothing to place"
        )
    if not math.isfinite(s) or s < 0:
        raise ValueError(
            f"s must be finite and non-negative, got {s!r}; a negative s makes "
            "the coldest model the most popular and inverts every decile"
        )
    weights = [(k + 1) ** -s for k in range(n_models)]
    total = math.fsum(weights)
    return tuple(w / total for w in weights)


def decile_of(n_models: int) -> tuple[int, ...]:
    """Popularity decile of each model: 0 is the hottest tenth, 9 the coldest.

    Requires `n_models` divisible by 10, so every decile holds the same number
    of models. An uneven split would make "the coldest decile" mean a different
    number of tenants at different N.
    """
    if type(n_models) is not int or n_models < DECILES or n_models % DECILES:
        raise ValueError(
            f"n_models must be a positive multiple of {DECILES}, got {n_models!r}; "
            "otherwise deciles hold different numbers of models"
        )
    per = n_models // DECILES
    return tuple(k // per for k in range(n_models))


def _check(shares: Sequence[float], total_rate: float, until: float) -> None:
    if len(shares) < 2:
        raise ValueError("a trace needs at least two models' shares")
    for i, share in enumerate(shares):
        if not math.isfinite(share) or share <= 0:
            raise ValueError(
                f"shares[{i}] is {share!r}; every model needs a positive share, "
                "or it never receives a request and silently leaves its decile"
            )
    if abs(math.fsum(shares) - 1.0) > 1e-9:
        raise ValueError(
            f"shares sum to {math.fsum(shares)!r}, not 1; the trace would offer "
            "a different total load from the one the scenario states"
        )
    for name, value in (("total_rate", total_rate), ("until", until)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"{name} is {value!r}; it must be finite and positive, or the "
                "generator either loops forever or returns an empty trace"
            )


def spread_trace(
    shares: Sequence[float], total_rate: float, until: float, rng: random.Random
) -> Trace:
    """Poisson arrivals at `total_rate` over [0, until], each labelled
    independently by `shares`. Arrivals carry no memory of which model came
    before, which is what "spread" means."""
    _check(shares, total_rate, until)
    cumulative = list(itertools.accumulate(shares))
    # Summation dust can leave the last entry a hair under 1, and a draw above
    # it would index past the last model.
    cumulative[-1] = 1.0
    out: Trace = []
    t = 0.0
    while True:
        t += rng.expovariate(total_rate)
        if t > until:
            return out
        out.append((t, bisect.bisect_right(cumulative, rng.random())))


def bursty_trace(
    shares: Sequence[float],
    total_rate: float,
    until: float,
    mean_burst: float,
    duty: float,
    rng: random.Random,
) -> Trace:
    """Each model alternates ON and OFF, and receives arrivals only while ON.

    ON periods are exponential with mean `mean_burst`. OFF periods are
    exponential with mean `mean_burst * (1 - duty) / duty`, so a model is ON a
    fraction `duty` of the time. While ON it receives Poisson arrivals at
    `share * total_rate / duty`. Its long-run rate is therefore exactly
    `share * total_rate`, the same as the spread regime at the same shares.

    Each model starts ON with probability `duty`, the stationary state. Because
    exponential periods are memoryless, the time left in that first period is a
    fresh draw. So a run does not open with every model ON at once.
    """
    _check(shares, total_rate, until)
    if not math.isfinite(mean_burst) or mean_burst <= 0:
        raise ValueError(f"mean_burst must be finite and positive, got {mean_burst!r}")
    if not (0.0 < duty < 1.0):
        raise ValueError(
            f"duty must be strictly between 0 and 1, got {duty!r}; at 1 the "
            "regime is spread under another name, and at 0 no request arrives"
        )
    mean_off = mean_burst * (1.0 - duty) / duty
    out: Trace = []
    for model, share in enumerate(shares):
        on_rate = share * total_rate / duty
        on = rng.random() < duty
        t = 0.0
        while t < until:
            length = rng.expovariate(1.0 / (mean_burst if on else mean_off))
            if on:
                end = min(t + length, until)
                a = t
                while True:
                    a += rng.expovariate(on_rate)
                    if a > end:
                        break
                    out.append((a, model))
            t += length
            on = not on
    out.sort()
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_traffic.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/traffic.py tests/test_placement_traffic.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/traffic.py tests/test_placement_traffic.py
git commit -m "feat: Zipf-labelled traces in a spread and a bursty regime"
```

---

## Task 5: The co-located latency surface

**Files:**
- Create: `placement/colocated.py`
- Test: `tests/test_placement_colocated.py`

`ServiceCurve` is indexed by one concurrency. A co-located model's latency depends on its own load and its neighbour's, so the measured object is a two-dimensional surface, interpolated bilinearly (amendment §1e item 3). Queries outside the grid are clamped, matching `ServiceCurve`, and `is_extrapolating` reports them so the simulator can count them. The test surface is bilinear by construction, so interpolation must reproduce it exactly anywhere inside the grid.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_colocated.py`:

```python
import pytest

from placement.colocated import ColocatedSurface

# latency = 1 + 0.5 * neighbour + 0.25 * (own - 1): bilinear by construction, so
# interpolation must reproduce it exactly anywhere inside the grid.
SURFACE = ColocatedSurface(
    own=(1, 3),
    neighbour=(0, 2),
    latency=((1.0, 2.0), (1.5, 2.5)),
    measured=True,
)


@pytest.mark.parametrize(
    "own, neighbour, expected",
    [(1, 0, 1.0), (3, 2, 2.5), (2, 1, 1.75), (1, 1, 1.5), (3, 0, 1.5)],
)
def test_it_interpolates_bilinearly(own, neighbour, expected):
    assert SURFACE.latency_at(own, neighbour) == pytest.approx(expected)


def test_it_clamps_outside_the_grid_and_says_so():
    assert SURFACE.latency_at(5, 9) == pytest.approx(2.5)
    assert SURFACE.is_extrapolating(5, 1)
    assert SURFACE.is_extrapolating(1, 9)
    assert not SURFACE.is_extrapolating(3, 2)


def test_capacity_is_the_top_measured_own_load():
    assert SURFACE.max_own_concurrency == 3.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"own": (1,), "neighbour": (0, 2), "latency": ((1.0, 2.0),)},
        {"own": (1, 1), "neighbour": (0, 2), "latency": ((1.0, 2.0), (1.0, 2.0))},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, 2.0),)},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, float("nan")), (1.0, 2.0))},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, -2.0), (1.0, 2.0))},
    ],
)
def test_it_refuses_a_table_that_would_misreport_latency(kwargs):
    with pytest.raises(ValueError):
        ColocatedSurface(measured=True, **kwargs)


def test_a_nan_load_is_refused():
    with pytest.raises(ValueError):
        SURFACE.latency_at(float("nan"), 0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_colocated.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.colocated'`

- [ ] **Step 3: Implement**

Create `placement/colocated.py`:

```python
"""Latency of a co-located model as a function of two loads.

`autoscale.service.ServiceCurve` is indexed by one concurrency. A co-located
model's latency depends on its own load and on its neighbour's, because the two
engines contend for compute and memory bandwidth rather than a cleanly divided
resource (August design §5.2). So the measured object is a surface: latency at
each (own, neighbour) grid point, interpolated bilinearly between them.

Bilinear rather than anything smoother, for the reason `ServiceCurve` gives for
linear: a smoother fit invents curvature between measured points.

At the grid's edges, queries are clamped, not extrapolated, matching
`ServiceCurve`. `is_extrapolating` reports when a query went above the grid, so
the simulator can count it instead of hiding it.
"""

import bisect
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["ColocatedSurface"]


def _grid(values: Sequence[float], name: str) -> tuple[float, ...]:
    xs = tuple(float(v) for v in values)
    if len(xs) < 2:
        raise ValueError(f"{name} needs at least two points to interpolate between")
    for v in xs:
        if not math.isfinite(v) or v < 0:
            raise ValueError(
                f"{name} contains {v!r}; a load is a finite, non-negative "
                "concurrency, and anything else poisons the interpolation"
            )
    if any(b <= a for a, b in itertools.pairwise(xs)):
        raise ValueError(
            f"{name} must be strictly ascending; a repeated point makes the "
            "interpolation divide by zero for any query landing on it"
        )
    return xs


def _bracket(grid: tuple[float, ...], x: float) -> tuple[int, float]:
    """Index i and fraction f with x = grid[i] + f * (grid[i+1] - grid[i]),
    clamped to the grid."""
    if x <= grid[0]:
        return 0, 0.0
    if x >= grid[-1]:
        return len(grid) - 2, 1.0
    i = bisect.bisect_right(grid, x) - 1
    return i, (x - grid[i]) / (grid[i + 1] - grid[i])


@dataclass(frozen=True)
class ColocatedSurface:
    """`latency[i][j]` is the latency in seconds of one request of a model at
    own concurrency `own[i]` while its neighbour runs at `neighbour[j]`.

    The neighbour-0 column is the solo-at-split curve: one engine, the other
    idle but resident. `measured` is False for a placeholder.
    """

    own: tuple[float, ...]
    neighbour: tuple[float, ...]
    latency: tuple[tuple[float, ...], ...]
    measured: bool

    def __post_init__(self) -> None:
        own = _grid(self.own, "own")
        neighbour = _grid(self.neighbour, "neighbour")
        rows = tuple(tuple(float(v) for v in row) for row in self.latency)
        if len(rows) != len(own) or any(len(row) != len(neighbour) for row in rows):
            raise ValueError(
                f"latency must be {len(own)} rows of {len(neighbour)} values, one "
                "per (own, neighbour) grid point; a ragged table would pair "
                "latencies with the wrong loads"
            )
        for row in rows:
            for v in row:
                if not math.isfinite(v) or v < 0:
                    raise ValueError(f"latency contains {v!r}; it must be finite and non-negative")
        object.__setattr__(self, "own", own)
        object.__setattr__(self, "neighbour", neighbour)
        object.__setattr__(self, "latency", rows)

    @property
    def max_own_concurrency(self) -> float:
        """The most requests one co-located model was measured serving. The
        simulator caps a pair GPU's per-model load here, as artifact 2 caps a
        replica at its curve's top measured concurrency."""
        return self.own[-1]

    def is_extrapolating(self, own: float, neighbour: float) -> bool:
        if math.isnan(own) or math.isnan(neighbour):
            raise ValueError("a NaN load compares False against both grid bounds")
        return own > self.own[-1] or neighbour > self.neighbour[-1]

    def latency_at(self, own: float, neighbour: float) -> float:
        if math.isnan(own) or math.isnan(neighbour):
            raise ValueError(
                "a NaN load compares False against every grid bound and would "
                "return a plausible latency computed from nothing"
            )
        i, fi = _bracket(self.own, own)
        j, fj = _bracket(self.neighbour, neighbour)
        z = self.latency
        return (
            z[i][j] * (1 - fi) * (1 - fj)
            + z[i + 1][j] * fi * (1 - fj)
            + z[i][j + 1] * (1 - fi) * fj
            + z[i + 1][j + 1] * fi * fj
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_colocated.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/colocated.py tests/test_placement_colocated.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/colocated.py tests/test_placement_colocated.py
git commit -m "feat: a two-load latency surface for co-located models"
```

---

## Task 6: Placements: the hot-model rule and each strategy's family

**Files:**
- Create: `placement/fleet.py`
- Test: `tests/test_placement_fleet.py`

This task encodes the rules that decide the headline, so its tests pin them one by one (amendment §7). A hot model gets `ceil(load / hot_fraction)` pinned solo GPUs in every strategy. Letting only some strategies replicate would make the others infeasible at high skew by construction. Dedicate has one placement. Swap grows its pool one GPU at a time, starting with the most popular tail models resident. Co-locate starts with every tail model paired, busiest with least busy, and un-pairs the busiest remaining pair per added GPU. Both families reach dedicate's capacity at dedicate's M, which is the sizing search's upper bound.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_fleet.py`:

```python
import pytest

from placement.fleet import Gpu, Placement, family, hot_allocation
from placement.traffic import zipf_shares


def test_a_model_above_the_hot_fraction_gets_enough_pinned_gpus():
    # Model 0 carries 0.6 of 4 GPUs of load = 2.4 GPUs; at 0.7 per GPU that
    # needs ceil(2.4 / 0.7) = 4 pinned GPUs. Model 1 carries 0.8, also hot.
    hot = hot_allocation((0.6, 0.2, 0.1, 0.1), offered_gpus=4.0, hot_fraction=0.7)
    assert hot == {0: 4, 1: 2}


def test_nothing_is_hot_at_low_load():
    assert hot_allocation(zipf_shares(20, 1.0), offered_gpus=0.5, hot_fraction=0.7) == {}


def test_dedicate_is_one_gpu_per_tail_model_plus_pinned():
    (only,) = family("dedicate", (0.6, 0.2, 0.1, 0.1), {0: 4})
    assert only.m == 4 + 3
    assert only.served == {0, 1, 2, 3}


def test_swap_grows_its_pool_and_reaches_dedicates_m():
    shares = (0.6, 0.2, 0.1, 0.1)
    configs = family("swap", shares, {0: 4})
    assert [c.m for c in configs] == [5, 6, 7]
    assert configs[0].pool_models == (1, 2, 3)
    # The first residents are the most popular tail models.
    assert [g.models for g in configs[1].gpus if g.kind == "pool"] == [(1,), (2,)]
    assert configs[-1].m == family("dedicate", shares, {0: 4})[0].m


def test_colocate_pairs_hot_with_cold_and_unpairs_busiest_first():
    shares = zipf_shares(6, 1.0)
    configs = family("colocate", shares, {})
    assert [c.m for c in configs] == [3, 4, 5, 6]
    first = {g.models for g in configs[0].gpus}
    assert first == {(0, 5), (1, 4), (2, 3)}
    # The busiest pair, (0, 5), is the first to be split.
    assert (0, 5) not in {g.models for g in configs[1].gpus}
    assert all(g.kind == "solo" for g in configs[-1].gpus)


def test_an_odd_tail_leaves_one_model_solo():
    configs = family("colocate", zipf_shares(5, 1.0), {})
    assert configs[0].m == 3
    assert sum(g.kind == "solo" for g in configs[0].gpus) == 1


def test_every_strategy_serves_every_model():
    shares = zipf_shares(20, 1.5)
    hot = hot_allocation(shares, offered_gpus=4.0, hot_fraction=0.7)
    for strategy in ("dedicate", "swap", "colocate"):
        for placement in family(strategy, shares, hot):
            assert placement.served == set(range(20))


def test_all_hot_leaves_one_placement():
    assert len(family("swap", (0.5, 0.5), {0: 1, 1: 1})) == 1


@pytest.mark.parametrize(
    "gpus, pool_models",
    [
        ((Gpu("pool", (1,)),), ()),
        ((Gpu("pinned", (0,)),), (1,)),
        ((Gpu("pool", (1,)), Gpu("pool", (1,))), (1, 2)),
        ((Gpu("pinned", (0,)), Gpu("pool", (0,))), (0,)),
    ],
)
def test_an_inconsistent_swap_placement_is_refused(gpus, pool_models):
    with pytest.raises(ValueError):
        Placement("swap", gpus, pool_models)


def test_a_pair_needs_two_distinct_models():
    with pytest.raises(ValueError):
        Gpu("pair", (1, 1))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_fleet.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.fleet'`

- [ ] **Step 3: Implement**

Create `placement/fleet.py`:

```python
"""Placements: which GPU holds which model, per strategy and fleet size.

The rules are the amendment's §7:

- Hot models are identified once, by one rule, and get pinned solo GPUs in
  every strategy. Letting only some strategies replicate would make the others
  infeasible at high skew by construction.
- The strategies differ only in how the tail is placed.
- Each strategy is a family of placements ordered by GPU count M. Dedicate has
  one member. Swap grows its shared pool one GPU at a time. Co-locate starts
  fully paired and un-pairs its busiest pair per added GPU. Both of the latter
  reach dedicate's capacity at dedicate's M, which bounds the sizing search.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["STRATEGIES", "Gpu", "Placement", "family", "hot_allocation"]

STRATEGIES = ("dedicate", "swap", "colocate")
_ONE_MODEL = ("pinned", "solo", "pool")


@dataclass(frozen=True)
class Gpu:
    """`kind` is pinned (a hot model), solo (one tail model), pair (two tail
    models co-located), or pool (a swap GPU; `models` is its first resident)."""

    kind: str
    models: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))
        if self.kind in _ONE_MODEL:
            if len(self.models) != 1:
                raise ValueError(f"a {self.kind} GPU holds exactly one model, got {self.models}")
        elif self.kind == "pair":
            if len(self.models) != 2 or self.models[0] == self.models[1]:
                raise ValueError(f"a pair GPU holds two distinct models, got {self.models}")
        else:
            raise ValueError(f"unknown GPU kind {self.kind!r}")


@dataclass(frozen=True)
class Placement:
    strategy: str
    gpus: tuple[Gpu, ...]
    # The tail models the swap pool serves. Empty for dedicate and co-locate.
    pool_models: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gpus", tuple(self.gpus))
        object.__setattr__(self, "pool_models", tuple(self.pool_models))
        if self.strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy {self.strategy!r}")
        pool = [g for g in self.gpus if g.kind == "pool"]
        if bool(pool) != bool(self.pool_models):
            raise ValueError(
                "pool GPUs and pool models come together: a pool with no models "
                "idles, and pool models with no pool GPU are never served"
            )
        if pool and self.strategy != "swap":
            raise ValueError("only the swap strategy has a pool")
        residents = [g.models[0] for g in pool]
        if len(set(residents)) != len(residents) or not set(residents) <= set(self.pool_models):
            raise ValueError(
                "each pool GPU starts with a distinct pool model; a model resident "
                "twice breaks swap's at-most-once rule"
            )
        pinned = {m for g in self.gpus if g.kind == "pinned" for m in g.models}
        placed = [m for g in self.gpus if g.kind in ("solo", "pair") for m in g.models]
        if len(set(placed)) != len(placed):
            raise ValueError("a tail model is placed on more than one GPU")
        overlap = (set(placed) | set(self.pool_models)) & pinned
        if overlap or set(placed) & set(self.pool_models):
            raise ValueError("a model is placed in two roles at once")

    @property
    def m(self) -> int:
        return len(self.gpus)

    @property
    def served(self) -> frozenset[int]:
        return frozenset(m for g in self.gpus for m in g.models) | frozenset(self.pool_models)


def hot_allocation(
    shares: Sequence[float], offered_gpus: float, hot_fraction: float
) -> dict[int, int]:
    """Pinned GPUs per hot model.

    `offered_gpus` is the total offered load in units of one GPU's measured
    saturation. A model whose load exceeds `hot_fraction` of one GPU is hot and
    gets ceil(load / hot_fraction) pinned GPUs, so none of its GPUs is asked to
    run above `hot_fraction` of saturation.
    """
    if not math.isfinite(offered_gpus) or offered_gpus <= 0:
        raise ValueError(f"offered_gpus must be finite and positive, got {offered_gpus!r}")
    if not (0.0 < hot_fraction <= 1.0):
        raise ValueError(
            f"hot_fraction must be in (0, 1], got {hot_fraction!r}; above 1 a hot "
            "model's GPU would be planned past saturation"
        )
    hot = {}
    for model, share in enumerate(shares):
        load = share * offered_gpus
        if load > hot_fraction:
            hot[model] = math.ceil(load / hot_fraction)
    return hot


def family(strategy: str, shares: Sequence[float], hot: dict[int, int]) -> tuple[Placement, ...]:
    """Every placement the sizing search considers for `strategy`, by ascending M."""
    pinned = tuple(Gpu("pinned", (m,)) for m in sorted(hot) for _ in range(hot[m]))
    tail = [m for m in range(len(shares)) if m not in hot]  # hottest first
    if strategy == "dedicate" or not tail:
        return (Placement(strategy, pinned + tuple(Gpu("solo", (m,)) for m in tail)),)
    if strategy == "swap":
        return tuple(
            Placement(
                "swap",
                pinned + tuple(Gpu("pool", (m,)) for m in tail[:size]),
                pool_models=tuple(tail),
            )
            for size in range(1, len(tail) + 1)
        )
    if strategy == "colocate":
        half = len(tail) // 2
        # Busiest tail model with the least busy, and inward. This keeps each
        # busier model's neighbour quiet; it does not balance pair loads.
        pairs = [(tail[i], tail[-1 - i]) for i in range(half)]
        leftover = (tail[half],) if len(tail) % 2 else ()
        # Un-pair the busiest remaining pair first.
        pairs.sort(key=lambda p: -(shares[p[0]] + shares[p[1]]))
        placements = []
        for split in range(len(pairs) + 1):
            solos = [m for pair in pairs[:split] for m in pair] + list(leftover)
            gpus = (
                pinned
                + tuple(Gpu("pair", pair) for pair in pairs[split:])
                + tuple(Gpu("solo", (m,)) for m in sorted(solos))
            )
            placements.append(Placement("colocate", gpus))
        return tuple(placements)
    raise ValueError(f"unknown strategy {strategy!r}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_fleet.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/fleet.py tests/test_placement_fleet.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/fleet.py tests/test_placement_fleet.py
git commit -m "feat: placement families with one hot-model rule for every strategy"
```

---

## Task 7: The placement simulator

**Files:**
- Create: `placement/sim.py`
- Test: `tests/test_placement_sim.py`

The loop artifact 2's simulator cannot become (amendment §1c): per-GPU residency, routing by residency with least in-flight first, per-model FIFO queues, capacity at the top measured concurrency, co-located service time read at the neighbour's current load, swap-LRU with draining, warm-up discard, and drain-out instead of censoring. It reuses `autoscale.events.EventQueue` and `autoscale.service.ServiceCurve`, both coldstart-free.

Every test is a hand-computed scenario. `FLAT` serves any load up to 2 in exactly 1 s, `PAIR` adds 0.5 s per request in flight next door, and `SWAP10` always takes 10 s, so every expected latency is a sum a reader can check. The LRU test discriminates: had the wrong victim been chosen, the final request would need a swap, and both its latency and the swap count would differ.

**One refinement over the amendment's wording, recorded here.** The amendment names the victim "the resident model with the oldest last-request time". This implementation counts a dispatch as a use as well as an arrival. Otherwise a model just swapped in, whose queued requests all arrived long ago, would be the next victim before it served its backlog, and a one-GPU pool would thrash forever.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_sim.py`:

```python
"""The placement loop, against hand-computed scenarios.

FLAT serves any load up to 2 in exactly 1 s, so every latency below is a sum of
whole seconds a reader can check by hand. PAIR slows a co-located request by
0.5 s per request its neighbour has in flight. SWAP10 takes 10 s, every time.
"""

import random

import pytest

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.fleet import Gpu, Placement, family
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.traffic import spread_trace, zipf_shares

FLAT = ServiceCurve(points=[(1, 1.0, 1.0, 0.5), (2, 1.0, 2.0, 1.0)], measured=True)
PAIR = ColocatedSurface(own=(1, 2), neighbour=(0, 2), latency=((1.0, 2.0), (1.0, 2.0)), measured=True)
ENGINES = Engines(solo=FLAT, colocated=PAIR)
SWAP10 = EmpiricalDistribution(samples=(10.0,), measured=True)


def _run(trace, placement, warmup=0.0, swap=SWAP10, seed=0):
    return simulate(trace, placement, ENGINES, swap, warmup, random.Random(seed))


def _by_arrival(result):
    return sorted(zip(result.arrivals, result.models, result.latencies))


def _swap_pool(size, pool_models):
    gpus = tuple(Gpu("pool", (m,)) for m in pool_models[:size])
    return Placement("swap", gpus, pool_models=pool_models)


def test_a_dedicated_request_takes_its_measured_latency():
    placement = Placement("dedicate", (Gpu("solo", (0,)), Gpu("solo", (1,))))
    result = _run([(0.0, 0), (0.0, 1)], placement)
    assert result.latencies == [1.0, 1.0]


def test_a_request_beyond_capacity_waits_its_turn():
    placement = Placement("dedicate", (Gpu("solo", (0,)),))
    result = _run([(0.0, 0), (0.0, 0), (0.0, 0)], placement)
    assert sorted(result.latencies) == [1.0, 1.0, 2.0]


def test_a_hot_model_spreads_across_its_pinned_gpus():
    placement = Placement("dedicate", (Gpu("pinned", (0,)), Gpu("pinned", (0,))))
    four = _run([(0.0, 0)] * 4, placement)
    assert four.latencies == [1.0] * 4
    five = _run([(0.0, 0)] * 5, placement)
    assert sorted(five.latencies) == [1.0, 1.0, 1.0, 1.0, 2.0]


def test_a_colocated_request_is_slowed_by_its_neighbour():
    placement = Placement("colocate", (Gpu("pair", (0, 1)),))
    result = _run([(0.0, 0), (0.0, 1)], placement)
    # Model 0 dispatches first with an idle neighbour; model 1 then sees one
    # request in flight next door.
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.0, 1, 1.5)]


def test_a_non_resident_model_waits_for_a_swap():
    result = _run([(0.0, 1)], _swap_pool(1, (0, 1)))
    assert result.latencies == [11.0]
    assert result.swaps == 1


def test_the_victim_drains_before_it_swaps():
    # Model 0's request holds the GPU until t=1; the swap then runs 1..11.
    result = _run([(0.0, 0), (0.5, 1)], _swap_pool(1, (0, 1)))
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.5, 1, 11.5)]


def test_an_evicted_model_waits_for_a_swap_back():
    # t=0.5 model 1 evicts model 0: drain to 1, swap to 11, serve 11..12.
    # t=2 model 0 waits: the only GPU is busy swapping. At 11 it is scheduled,
    # the GPU drains model 1 at 12, swaps back by 22, and serves by 23.
    result = _run([(0.0, 0), (0.5, 1), (2.0, 0)], _swap_pool(1, (0, 1)))
    assert _by_arrival(result) == [(0.0, 0, 1.0), (0.5, 1, 11.5), (2.0, 0, 21.0)]
    assert result.swaps == 2


def test_a_model_already_being_swapped_in_gets_no_second_swap():
    result = _run([(0.0, 1), (1.0, 1)], _swap_pool(1, (0, 1)))
    assert result.swaps == 1
    # Both are dispatched when the swap finishes at t=10.
    assert _by_arrival(result) == [(0.0, 1, 11.0), (1.0, 1, 10.0)]


def test_lru_evicts_the_least_recently_used_resident():
    # Model 1 was last used at t=0, model 0 at t=3, so model 2 evicts model 1.
    trace = [(0.0, 1), (3.0, 0), (4.0, 2), (5.0, 0)]
    result = _run(trace, _swap_pool(2, (0, 1, 2)))
    assert result.swaps == 1
    assert _by_arrival(result)[-1] == (5.0, 0, 1.0)


def test_warmup_requests_run_but_are_not_reported():
    placement = Placement("dedicate", (Gpu("solo", (0,)),))
    result = _run([(0.0, 0), (0.0, 0), (0.0, 0), (5.0, 0)], placement, warmup=1.0)
    assert result.completed == 4
    assert _by_arrival(result) == [(5.0, 0, 1.0)]


def test_every_request_completes_even_under_heavy_swapping():
    shares = zipf_shares(10, 0.5)
    trace = spread_trace(shares, 6.0, 300.0, random.Random(4))
    placement = family("swap", shares, {})[1]
    result = _run(trace, placement)
    assert result.completed == len(trace) == len(result.latencies)
    assert result.swaps > 10


def test_the_same_seed_gives_the_same_run():
    shares = zipf_shares(10, 1.0)
    trace = spread_trace(shares, 4.0, 200.0, random.Random(1))
    placement = family("swap", shares, {})[2]
    varied = EmpiricalDistribution(samples=(5.0, 9.0, 14.0), measured=True)
    a = _run(trace, placement, swap=varied, seed=3)
    b = _run(trace, placement, swap=varied, seed=3)
    assert (a.latencies, a.swaps) == (b.latencies, b.swaps)


def test_a_model_the_placement_does_not_serve_is_refused():
    with pytest.raises(ValueError, match="does not serve"):
        _run([(0.0, 7)], Placement("dedicate", (Gpu("solo", (0,)),)))


def test_an_unsorted_trace_is_refused():
    with pytest.raises(ValueError, match="sorted"):
        _run([(2.0, 0), (1.0, 0)], Placement("dedicate", (Gpu("solo", (0,)),)))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_sim.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.sim'`

- [ ] **Step 3: Implement**

Create `placement/sim.py`:

```python
"""The placement simulator: a fixed fleet, routing by residency, swap as LRU.

Built on artifact 2's event queue and service-curve type, not on artifact 2's
loop. That loop has no replica identity -- load is spread as
ceil(in_flight / replicas) -- and placement is exactly the question of which GPU
holds which model (amendment §1c). The semantics are fixed by the amendment's
§7; the comments below say where each rule lives.

Two simplifications carry over from artifact 2 and are stated in the post:

- Service time is frozen at dispatch. For a co-located request this includes
  the neighbour's load at that instant, so a neighbour that gets busier
  mid-request does not slow it further. The interference curve is the check
  on whether that matters.
- Capacity is the top measured concurrency. A request beyond it queues rather
  than being served at an extrapolated latency.
"""

import math
import random
from collections import deque
from dataclasses import dataclass, field

from autoscale.events import Event, EventQueue
from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.fleet import Placement
from placement.resample import EmpiricalDistribution
from placement.traffic import Trace

__all__ = ["Engines", "RunResult", "simulate"]

_SERVING, _DRAINING, _SWAPPING = "serving", "draining", "swapping"


@dataclass(frozen=True)
class Engines:
    """What one GPU does. `solo` serves pinned, solo and pool GPUs, measured
    at full memory. `colocated` serves each model on a pair GPU."""

    solo: ServiceCurve
    colocated: ColocatedSurface

    @property
    def measured(self) -> bool:
        return self.solo.measured and self.colocated.measured


@dataclass
class RunResult:
    """One run. The three lists are aligned and hold post-warm-up requests
    only; every request, warm-up included, is counted in `completed`.

    Arrival times are kept, not just latencies, because trace-replay
    validation compares latency trajectories over time.
    """

    m: int
    arrivals: list[float] = field(default_factory=list)
    models: list[int] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    completed: int = 0
    swaps: int = 0
    extrapolated: int = 0


@dataclass
class _Gpu:
    kind: str
    capacity: float
    in_flight: dict[int, int]  # resident model -> requests in flight on this GPU
    state: str = _SERVING
    target: int | None = None  # the model a draining or swapping GPU is loading


def _check_trace(trace: Trace, placement: Placement, warmup: float) -> None:
    if not math.isfinite(warmup) or warmup < 0:
        raise ValueError(f"warmup must be finite and non-negative, got {warmup!r}")
    previous = 0.0
    for i, (t, model) in enumerate(trace):
        if not math.isfinite(t) or t < previous:
            raise ValueError(
                f"trace[{i}] has time {t!r} after {previous!r}; a trace must be "
                "finite and sorted, or the event queue reorders it silently"
            )
        if model not in placement.served:
            raise ValueError(
                f"trace[{i}] asks for model {model!r}, which the placement does "
                "not serve; the request would queue forever and the run would "
                "report a latency for nothing"
            )
        previous = t


def simulate(
    trace: Trace,
    placement: Placement,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    warmup: float,
    rng: random.Random,
) -> RunResult:
    """Serve `trace` on `placement` until every request has completed.

    Drain-out, not censoring: after the last arrival the simulation keeps
    running until the queues are empty. Excluding unfinished requests would
    drop exactly the cold-tail requests stuck behind swaps, which flatters swap
    (amendment §7). Requests that arrive before `warmup` are simulated but not
    reported. `rng` draws swap durations only; the trace is already fixed.
    """
    _check_trace(trace, placement, warmup)
    result = RunResult(m=placement.m)

    gpus: list[_Gpu] = []
    hosts: dict[int, list[int]] = {m: [] for m in placement.served}
    for g, spec in enumerate(placement.gpus):
        capacity = (
            engines.colocated.max_own_concurrency
            if spec.kind == "pair"
            else engines.solo.max_measured_concurrency
        )
        gpus.append(_Gpu(spec.kind, capacity, {m: 0 for m in spec.models}))
        for m in spec.models:
            hosts[m].append(g)
    pool = [g for g, gpu in enumerate(gpus) if gpu.kind == "pool"]
    pool_models = placement.pool_models
    queues: dict[int, deque[float]] = {m: deque() for m in placement.served}
    # Last time a model was asked for or served. LRU's clock: counting
    # dispatches as well as arrivals keeps a model that has just been swapped
    # in from being the next victim before it serves its backlog.
    last_used: dict[int, float] = dict.fromkeys(placement.served, -math.inf)
    pending: set[int] = set()  # pool models a GPU is draining or swapping toward

    events = EventQueue()
    for t, m in trace:
        events.push(Event(time=t, kind="arrival", payload={"model": m}))

    def dispatch(m: int, now: float) -> None:
        # Routing by residency, least in-flight first; FIFO within a model.
        queue = queues[m]
        while queue:
            best = None
            for g in hosts[m]:
                load = gpus[g].in_flight[m]
                if load < gpus[g].capacity and (best is None or load < gpus[best].in_flight[m]):
                    best = g
            if best is None:
                return
            arrived = queue.popleft()
            gpu = gpus[best]
            own = gpu.in_flight[m] + 1
            if gpu.kind == "pair":
                neighbour = next(load for x, load in gpu.in_flight.items() if x != m)
                if engines.colocated.is_extrapolating(own, neighbour):
                    result.extrapolated += 1
                service = engines.colocated.latency_at(own, neighbour)
            else:
                if engines.solo.is_extrapolating(own):
                    result.extrapolated += 1
                service = engines.solo.latency_at(own)
            gpu.in_flight[m] = own
            last_used[m] = now
            events.push(
                Event(now + service, "done", {"gpu": best, "model": m, "arrived": arrived})
            )

    def start_swap(g: int, now: float) -> None:
        gpus[g].state = _SWAPPING
        result.swaps += 1
        events.push(Event(now + swap_time.draw(rng), "swap_done", {"gpu": g}))

    def victim() -> int | None:
        # The least recently used resident across the pool's serving GPUs.
        serving = [g for g in pool if gpus[g].state == _SERVING]
        if not serving:
            return None
        return min(serving, key=lambda g: (last_used[next(iter(gpus[g].in_flight))], g))

    def schedule_swaps(now: float) -> None:
        # One swap per waiting, non-resident pool model, oldest waiter first.
        # A model already being swapped in is in `pending` and never gets a
        # second swap.
        waiting = [m for m in pool_models if queues[m] and not hosts[m] and m not in pending]
        waiting.sort(key=lambda m: queues[m][0])
        for x in waiting:
            g = victim()
            if g is None:
                return
            gpu = gpus[g]
            (resident,) = gpu.in_flight
            hosts[resident] = []  # stop admitting the evicted model
            gpu.state, gpu.target = _DRAINING, x
            pending.add(x)
            if gpu.in_flight[resident] == 0:
                start_swap(g, now)

    while (event := events.pop()) is not None:
        now = event.time
        if event.kind == "arrival":
            m = event.payload["model"]
            last_used[m] = now
            queues[m].append(now)
            dispatch(m, now)
            if queues[m] and not hosts[m]:
                schedule_swaps(now)
        elif event.kind == "done":
            g, m, arrived = event.payload["gpu"], event.payload["model"], event.payload["arrived"]
            gpu = gpus[g]
            gpu.in_flight[m] -= 1
            result.completed += 1
            if arrived >= warmup:
                result.arrivals.append(arrived)
                result.models.append(m)
                result.latencies.append(now - arrived)
            if gpu.state == _DRAINING and gpu.in_flight[m] == 0:
                start_swap(g, now)
            else:
                dispatch(m, now)
        elif event.kind == "swap_done":
            g = event.payload["gpu"]
            gpu = gpus[g]
            x = gpu.target
            gpu.in_flight = {x: 0}
            gpu.state, gpu.target = _SERVING, None
            hosts[x] = [g]
            pending.discard(x)
            last_used[x] = now
            dispatch(x, now)
            schedule_swaps(now)

    stranded = sum(len(q) for q in queues.values())
    if stranded or result.completed != len(trace):
        raise RuntimeError(
            f"{stranded} requests never completed ({result.completed} of "
            f"{len(trace)} did); drain-out guarantees every request is served, "
            "so this is a simulator bug, and publishing the run would drop the "
            "requests most likely to be the slowest"
        )
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_sim.py tests/test_placement_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Record throughput**

The sweep's CPU budget follows from this number, so measure it rather than assume it.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import random, time
from autoscale.service import SERVICE_CURVE_PLACEHOLDER as C
from placement.colocated import ColocatedSurface
from placement.fleet import family, hot_allocation
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.traffic import zipf_shares, spread_trace
surface = ColocatedSurface(own=(1, 32), neighbour=(0, 32), latency=((0.32, 0.4), (1.0, 1.3)), measured=False)
engines = Engines(C, surface)
swap = EmpiricalDistribution((20.0,), False)
shares = zipf_shares(20, 1.0)
hot = hot_allocation(shares, 4.0, 0.7)
trace = spread_trace(shares, 4 * 33.68, 600.0, random.Random(1))
for strategy in ('dedicate', 'swap', 'colocate'):
    configs = family(strategy, shares, hot)
    placement = configs[len(configs) // 2]
    start = time.perf_counter()
    result = simulate(trace, placement, engines, swap, 60.0, random.Random(0))
    print(strategy, placement.m, result.swaps, f'{len(trace) / (time.perf_counter() - start):,.0f} req/s')
"
```

Expected, on the machine this plan was written on (8 cores): roughly 200,000–270,000 requests per second, with swap the slowest. Note the figure in the task report. At that rate, the full placeholder sweep in Task 17 is about half an hour of CPU before parallelism.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/sim.py tests/test_placement_sim.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement/sim.py tests/test_placement_sim.py
git commit -m "feat: the placement simulator: routing by residency, swap-LRU, drain-out"
```

---

## Task 8: Per-decile p99 under the shared sample floor

**Files:**
- Create: `placement/tails.py`
- Test: `tests/test_placement_tails.py`

The fairness view (August design §8), computed with the shared `percentiles` and its floor of 500 samples. A decile under the floor reports `None` rather than raising. At high skew a thin decile is an expected property of a run, not a bug, and the caller decides what it means for the grid point. The tests pin the floor to the shared constant, so a change there cannot slip past this module.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_tails.py`:

```python
import pytest

from placement.sim import RunResult
from placement.tails import P99_FLOOR, decile_counts, decile_p99s

DECILES_OF_TEN = tuple(range(10))  # ten models, one per decile


def _result(latencies_by_model):
    result = RunResult(m=1)
    for model, latencies in latencies_by_model.items():
        for latency in latencies:
            result.arrivals.append(0.0)
            result.models.append(model)
            result.latencies.append(latency)
    return result


def test_the_floor_is_the_shared_statistics_floor():
    assert P99_FLOOR == 500


def test_a_decile_at_the_floor_reports_the_linear_interpolation_p99():
    # 1..500: p99 at index 0.99 * 499 = 494.01 lands between 495 and 496.
    result = _result({0: [float(v) for v in range(1, 501)]})
    p99s = decile_p99s(result, DECILES_OF_TEN)
    assert p99s[0] == pytest.approx(495.01)


def test_a_decile_under_the_floor_reports_none_not_a_number():
    result = _result({0: [1.0] * 500, 9: [1.0] * 499})
    p99s = decile_p99s(result, DECILES_OF_TEN)
    assert p99s[0] == 1.0
    assert p99s[9] is None
    assert p99s[1:9] == (None,) * 8


def test_counts_group_models_into_their_deciles():
    assert decile_counts([0, 1, 1, 19], tuple(k // 2 for k in range(20))) == (
        3, 0, 0, 0, 0, 0, 0, 0, 0, 1,
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_tails.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.tails'`

- [ ] **Step 3: Implement**

Create `placement/tails.py`:

```python
"""Per-decile p99: the fairness view, under the shared sample floor.

Under swap, aggregate p99 can look fine while cold-tail tenants are unusable,
because hot models dominate the request count (August design §8). So p99 is
reported per popularity decile.

The shared statistics refuse a p99 from fewer than MIN_SAMPLES["p99"] samples.
Here a decile below the floor reports None rather than raising, because a
thin decile is an expected property of a run at high skew, and the caller
decides what that means for the grid point (amendment §8: all or nothing).
"""

from collections.abc import Sequence

from harness.stats import MIN_SAMPLES, percentiles
from placement.sim import RunResult
from placement.traffic import DECILES

__all__ = ["P99_FLOOR", "decile_counts", "decile_p99s"]

P99_FLOOR = MIN_SAMPLES["p99"]


def decile_counts(models: Sequence[int], deciles: Sequence[int]) -> tuple[int, ...]:
    """Requests per decile. `deciles[m]` is model m's decile."""
    counts = [0] * DECILES
    for m in models:
        counts[deciles[m]] += 1
    return tuple(counts)


def decile_p99s(result: RunResult, deciles: Sequence[int]) -> tuple[float | None, ...]:
    """p99 latency per decile, None where the decile is under the floor."""
    groups: list[list[float]] = [[] for _ in range(DECILES)]
    for m, latency in zip(result.models, result.latencies, strict=True):
        groups[deciles[m]].append(latency)
    return tuple(
        percentiles(group, want=("p99",))["p99"] if len(group) >= P99_FLOOR else None
        for group in groups
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_tails.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/tails.py tests/test_placement_tails.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/tails.py tests/test_placement_tails.py
git commit -m "feat: per-decile p99, withheld under the shared sample floor"
```

---

## Task 9: Evaluating one grid point, on common random numbers

**Files:**
- Create: `placement/evaluate.py`
- Test: `tests/test_placement_evaluate.py`

Sizing picks the cheapest configuration meeting the SLO, and the bootstrap re-sizes inside every draw, so both need every (configuration, repetition) result, not only the winner's. This task computes them once. Repetition r is the same trace and the same swap-duration stream for every strategy and configuration: neither is in the seed key, as in artifact 2's `sweep._derive_seed`. So strategy differences are paired and traffic variance cancels. The test for this checks that decile counts depend only on the repetition. Results are cached to JSON, and a round-trip test proves the cache loses nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_evaluate.py`:

```python
from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.evaluate import (
    GridPoint,
    Scenario,
    dump_evaluations,
    evaluate_point,
    load_evaluations,
)
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.0, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.2, 0.3), (0.3, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
SWAP = EmpiricalDistribution(samples=(2.0, 3.0), measured=True)
SCENARIO = Scenario(
    n_models=10, offered_gpus=1.5, saturation_rps=13.3, hot_fraction=0.7,
    warmup=5.0, mean_burst=5.0, duty=0.3,
)


def _evaluate(point, seed=0, reps=2):
    return evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=reps, seed=seed)


def test_every_strategy_reports_every_configuration_in_ascending_m():
    evaluation = _evaluate(GridPoint(1.0, "spread", 40.0))
    for strategy, configs in evaluation.outcomes.items():
        ms = [c.m for c in configs]
        assert ms == sorted(ms), strategy
        assert all(len(c.decile_p99s) == 2 for c in configs)
    assert len(evaluation.outcomes["dedicate"]) == 1


def test_every_configuration_sees_the_same_traffic():
    """Common random numbers: the decile counts are a property of the trace,
    and the trace does not depend on the strategy or the configuration."""
    evaluation = _evaluate(GridPoint(0.0, "bursty", 40.0))
    assert evaluation.repetitions == 2
    assert evaluation.counts[0] != evaluation.counts[1]


def test_the_largest_swap_pool_never_swaps():
    evaluation = _evaluate(GridPoint(1.0, "spread", 40.0))
    assert set(evaluation.outcomes["swap"][-1].swaps) == {0}
    assert sum(evaluation.outcomes["swap"][0].swaps) > 0


def test_evaluation_is_reproducible_and_survives_the_cache(tmp_path):
    point = GridPoint(1.0, "spread", 40.0)
    first, again = _evaluate(point, seed=4), _evaluate(point, seed=4)
    assert first == again
    path = tmp_path / "cache.json"
    dump_evaluations(path, [first])
    assert load_evaluations(path) == [first]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_evaluate.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.evaluate'`

- [ ] **Step 3: Implement**

Create `placement/evaluate.py`:

```python
"""Evaluate one grid point: every configuration of every strategy, every repetition.

Everything the sizing and the crossover interval need is computed here once.
Sizing picks the cheapest configuration that meets the SLO, and the bootstrap
re-sizes inside every draw, so both need the per-decile p99 of every
(configuration, repetition), not only the winner's.

Common random numbers: repetition r is the same trace for every strategy and
every configuration, and the same swap-duration stream. Neither the strategy
nor the configuration is in the seed key, so strategy differences are paired
within a repetition and traffic variance cancels, as in artifact 2's
`sweep._derive_seed`.
"""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from placement.fleet import STRATEGIES, family, hot_allocation
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.tails import P99_FLOOR, decile_counts, decile_p99s
from placement.traffic import bursty_trace, decile_of, spread_trace, zipf_shares

__all__ = [
    "REGIMES",
    "ConfigOutcome",
    "GridPoint",
    "PointEvaluation",
    "Scenario",
    "dump_evaluations",
    "evaluate_point",
    "load_evaluations",
]

REGIMES = ("spread", "bursty")


@dataclass(frozen=True)
class Scenario:
    """Everything the pre-registration fixes that is not a grid coordinate.

    `offered_gpus` is total load in units of one GPU's saturation, and
    `saturation_rps` is that saturation in requests per second, computed from
    the measured solo curve by the caller.
    """

    n_models: int
    offered_gpus: float
    saturation_rps: float
    hot_fraction: float
    warmup: float
    mean_burst: float
    duty: float

    @property
    def total_rate(self) -> float:
        return self.offered_gpus * self.saturation_rps


@dataclass(frozen=True)
class GridPoint:
    """One cell of the sweep. `until` is warm-up plus the measured window,
    which the run-length pilot sets per grid point."""

    s: float
    regime: str
    until: float

    def __post_init__(self) -> None:
        if self.regime not in REGIMES:
            raise ValueError(f"unknown regime {self.regime!r}")
        if not math.isfinite(self.until) or self.until <= 0:
            raise ValueError(f"until must be finite and positive, got {self.until!r}")


@dataclass(frozen=True)
class ConfigOutcome:
    """One configuration's results, one entry per repetition."""

    strategy: str
    m: int
    decile_p99s: tuple[tuple[float | None, ...], ...]
    swaps: tuple[int, ...]
    extrapolated: tuple[int, ...]


@dataclass(frozen=True)
class PointEvaluation:
    point: GridPoint
    # Per strategy, its configurations in ascending M.
    outcomes: dict[str, tuple[ConfigOutcome, ...]]
    # Post-warm-up requests per decile, one tuple per repetition. The same for
    # every configuration, because the trace is.
    counts: tuple[tuple[int, ...], ...]

    @property
    def repetitions(self) -> int:
        return len(self.counts)

    @property
    def floor_met(self) -> bool:
        """Every decile cleared the p99 floor in every repetition."""
        return all(c >= P99_FLOOR for rep in self.counts for c in rep)


def _seed(seed: int, point: GridPoint, rep: int, stream: str) -> int:
    """Stable across processes, unlike `hash()`; see artifact 2's
    `sweep._derive_seed` for why that matters."""
    key = f"{seed}|{point.s!r}|{point.regime}|{point.until!r}|{rep}|{stream}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def evaluate_point(
    point: GridPoint,
    scenario: Scenario,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    repetitions: int,
    seed: int,
) -> PointEvaluation:
    shares = zipf_shares(scenario.n_models, point.s)
    deciles = decile_of(scenario.n_models)
    hot = hot_allocation(shares, scenario.offered_gpus, scenario.hot_fraction)
    families = {strategy: family(strategy, shares, hot) for strategy in STRATEGIES}
    per_config: dict[str, list[dict[str, list]]] = {
        strategy: [{"p99s": [], "swaps": [], "extrapolated": []} for _ in configs]
        for strategy, configs in families.items()
    }
    counts = []
    for rep in range(repetitions):
        rng = random.Random(_seed(seed, point, rep, "trace"))
        if point.regime == "spread":
            trace = spread_trace(shares, scenario.total_rate, point.until, rng)
        else:
            trace = bursty_trace(
                shares, scenario.total_rate, point.until, scenario.mean_burst, scenario.duty, rng
            )
        counts.append(decile_counts([m for t, m in trace if t >= scenario.warmup], deciles))
        for strategy, configs in families.items():
            for i, placement in enumerate(configs):
                result = simulate(
                    trace,
                    placement,
                    engines,
                    swap_time,
                    scenario.warmup,
                    random.Random(_seed(seed, point, rep, "swap")),
                )
                slot = per_config[strategy][i]
                slot["p99s"].append(decile_p99s(result, deciles))
                slot["swaps"].append(result.swaps)
                slot["extrapolated"].append(result.extrapolated)
    outcomes = {
        strategy: tuple(
            ConfigOutcome(
                strategy=strategy,
                m=placement.m,
                decile_p99s=tuple(slot["p99s"]),
                swaps=tuple(slot["swaps"]),
                extrapolated=tuple(slot["extrapolated"]),
            )
            for placement, slot in zip(families[strategy], per_config[strategy], strict=True)
        )
        for strategy in STRATEGIES
    }
    return PointEvaluation(point=point, outcomes=outcomes, counts=tuple(counts))


def dump_evaluations(path: Path, evaluations: list[PointEvaluation]) -> None:
    """Cache to JSON, so re-drawing a table does not re-run a sweep."""
    path.write_text(json.dumps([asdict(e) for e in evaluations]))


def load_evaluations(path: Path) -> list[PointEvaluation]:
    loaded = []
    for raw in json.loads(path.read_text()):
        outcomes = {
            strategy: tuple(
                ConfigOutcome(
                    strategy=o["strategy"],
                    m=o["m"],
                    decile_p99s=tuple(tuple(rep) for rep in o["decile_p99s"]),
                    swaps=tuple(o["swaps"]),
                    extrapolated=tuple(o["extrapolated"]),
                )
                for o in configs
            )
            for strategy, configs in raw["outcomes"].items()
        }
        loaded.append(
            PointEvaluation(
                point=GridPoint(**raw["point"]),
                outcomes=outcomes,
                counts=tuple(tuple(rep) for rep in raw["counts"]),
            )
        )
    return loaded
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_evaluate.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/evaluate.py tests/test_placement_evaluate.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/evaluate.py tests/test_placement_evaluate.py
git commit -m "feat: evaluate every configuration at a grid point on common random numbers"
```

---

## Task 10: Fleet sizing

**Files:**
- Create: `placement/sizing.py`
- Test: `tests/test_placement_sizing.py`

The smallest M at which a strategy's median-across-repetitions p99 meets the SLO in every decile. `None` means dominated below dedicate's M (amendment §7). The median is the shared `harness.stats.median`, not a local one. Task 2's test would catch a local `median`. A grid point where any decile missed the floor in any repetition is not evaluable, and sizing refuses it rather than sizing from the repetitions that happened to clear (amendment §8). The resampling test shows why sizing takes repetition ids, duplicates included: that is how the bootstrap in Task 11 puts uncertainty into the sizing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_sizing.py`:

```python
import pytest

from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.sizing import size, sized_fleet


def _outcome(strategy, m, p99s_per_rep):
    """`p99s_per_rep` is one value per repetition, applied to every decile."""
    return ConfigOutcome(
        strategy=strategy,
        m=m,
        decile_p99s=tuple((v,) * 10 for v in p99s_per_rep),
        swaps=(0,) * len(p99s_per_rep),
        extrapolated=(0,) * len(p99s_per_rep),
    )


def test_the_smallest_m_whose_median_p99_meets_the_slo_wins():
    outcomes = [
        _outcome("swap", 3, [9.0, 9.0, 9.0]),
        _outcome("swap", 4, [1.0, 9.0, 2.0]),  # median 2.0 meets 5.0
        _outcome("swap", 5, [1.0, 1.0, 1.0]),
    ]
    assert size(outcomes, [0, 1, 2], slo=5.0) == 4


def test_a_strategy_that_never_meets_the_slo_is_dominated():
    assert size([_outcome("swap", 3, [9.0])], [0], slo=5.0) is None


def test_resampled_reps_with_duplicates_change_the_answer():
    outcomes = [_outcome("swap", 3, [1.0, 9.0, 9.0]), _outcome("swap", 4, [1.0, 1.0, 1.0])]
    assert size(outcomes, [0, 1, 2], slo=5.0) == 4
    assert size(outcomes, [0, 0, 1], slo=5.0) == 3


def test_every_decile_must_meet_it():
    worst = ConfigOutcome("swap", 3, ((1.0,) * 9 + (9.0,),), (0,), (0,))
    assert size([worst], [0], slo=5.0) is None


def test_configurations_out_of_order_are_refused():
    with pytest.raises(ValueError, match="ascending"):
        size([_outcome("swap", 5, [1.0]), _outcome("swap", 4, [1.0])], [0], slo=5.0)


def test_a_decile_under_the_floor_cannot_be_sized():
    thin = ConfigOutcome("swap", 3, ((1.0,) * 9 + (None,),), (0,), (0,))
    with pytest.raises(ValueError, match="floor"):
        size([thin], [0], slo=5.0)


def _evaluation(counts):
    outcomes = {
        "dedicate": (_outcome("dedicate", 6, [1.0]),),
        "swap": (_outcome("swap", 3, [9.0]), _outcome("swap", 4, [1.0])),
        "colocate": (_outcome("colocate", 5, [1.0]),),
    }
    return PointEvaluation(GridPoint(1.0, "spread", 100.0), outcomes, counts)


def test_a_grid_point_is_sized_only_when_every_decile_cleared_the_floor():
    assert sized_fleet(_evaluation(((500,) * 10,)), [0], slo=5.0) == {
        "dedicate": 6,
        "swap": 4,
        "colocate": 5,
    }
    assert sized_fleet(_evaluation(((500,) * 9 + (499,),)), [0], slo=5.0) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_sizing.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.sizing'`

- [ ] **Step 3: Implement**

Create `placement/sizing.py`:

```python
"""Fleet sizing: the smallest M at which a strategy meets the SLO.

The SLO is a p99 target that every popularity decile must meet, where a
decile's p99 is the median across repetitions of its per-repetition p99. That
is artifact 2's estimand: the p99 a typical run delivers.

Sizing is done once per grid point over a set of repetitions, not once per
repetition (amendment §7). The bootstrap in `crossover` calls this with
resampled repetition ids, duplicates included, to put the uncertainty into the
sizing itself.
"""

import math
from collections.abc import Sequence

from harness.stats import median
from placement.evaluate import ConfigOutcome, PointEvaluation
from placement.fleet import STRATEGIES
from placement.traffic import DECILES

__all__ = ["size", "sized_fleet"]


def size(outcomes: Sequence[ConfigOutcome], reps: Sequence[int], slo: float) -> int | None:
    """The smallest M in `outcomes` that meets `slo` in every decile.

    None means dominated: no configuration up to dedicate's M meets the SLO.
    """
    if not math.isfinite(slo) or slo <= 0:
        raise ValueError(f"slo must be a finite, positive number of seconds, got {slo!r}")
    if not reps:
        raise ValueError("sizing needs at least one repetition")
    ms = [o.m for o in outcomes]
    if ms != sorted(ms):
        raise ValueError(
            f"configurations must come in ascending M, got {ms}; out of order, "
            "the first to meet the SLO is not the cheapest"
        )
    for outcome in outcomes:
        meets = True
        for d in range(DECILES):
            values = [outcome.decile_p99s[r][d] for r in reps]
            if any(v is None for v in values):
                raise ValueError(
                    f"decile {d} is under the p99 floor in a repetition; the grid "
                    "point is not evaluable and must be excluded before sizing"
                )
            if median(values) > slo:
                meets = False
                break
        if meets:
            return outcome.m
    return None


def sized_fleet(
    evaluation: PointEvaluation, reps: Sequence[int], slo: float
) -> dict[str, int | None] | None:
    """Sized M per strategy, or None when the grid point is not evaluable.

    Not evaluable means some decile missed the p99 floor in some repetition.
    Publishing that decile from the repetitions that did clear it would keep
    the runs that happened to send more traffic to the cold tail (§8).
    """
    if not evaluation.floor_met:
        return None
    return {strategy: size(evaluation.outcomes[strategy], reps, slo) for strategy in STRATEGIES}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_sizing.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/sizing.py tests/test_placement_sizing.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/sizing.py tests/test_placement_sizing.py
git commit -m "feat: size each strategy to the smallest fleet meeting a per-decile SLO"
```

---

## Task 11: The crossover and its interval

**Files:**
- Create: `placement/crossover.py`
- Test: `tests/test_placement_crossover.py`

Sizing is once per grid point, so cost there is one integer, and a paired difference of per-repetition costs would have zero width (amendment §8). The interval comes from resampling repetition ids, using one resample for every strategy at every grid point so the common-trace pairing survives. Every strategy is re-sized and the crossover re-located inside each draw. A crossover is reported as the pair of adjacent located grid points it lies between. Draws with no crossing or several crossings are counted and published, not dropped. The endpoint arithmetic is `harness.stats._percentile_interval`, imported rather than copied, because it is the one percentile-method endpoint computation in the publication.

The borderline test is the important one. At the middle grid point, swap's small pool passes in exactly half the repetitions, so resamples disagree about it, and the interval has to widen to cover both neighbouring grid intervals rather than report false precision.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_crossover.py`:

```python
import pytest

from placement.crossover import cheapest, crossings, estimate_crossover
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation

REPS = 20
FLOOR_MET = ((500,) * 10,) * REPS


def _outcome(strategy, m, p99s_per_rep):
    return ConfigOutcome(
        strategy=strategy,
        m=m,
        decile_p99s=tuple((v,) * 10 for v in p99s_per_rep),
        swaps=(0,) * REPS,
        extrapolated=(0,) * REPS,
    )


def _point(s, swap_small_p99s, counts=FLOOR_MET):
    """Dedicate needs 10 GPUs. Swap needs 10, or 6 when its small pool meets
    the SLO of 5 s -- which `swap_small_p99s` decides, repetition by repetition."""
    outcomes = {
        "dedicate": (_outcome("dedicate", 10, [1.0] * REPS),),
        "swap": (_outcome("swap", 6, swap_small_p99s), _outcome("swap", 10, [1.0] * REPS)),
        "colocate": (_outcome("colocate", 10, [1.0] * REPS),),
    }
    return PointEvaluation(GridPoint(s, "spread", 100.0), outcomes, counts)


def test_cheapest_reports_ties_and_domination():
    assert cheapest({"dedicate": 10, "swap": 6, "colocate": None}) == {"swap"}
    assert cheapest({"dedicate": 10, "swap": 10}) == {"dedicate", "swap"}
    assert cheapest({"dedicate": None, "swap": None}) == frozenset()


def test_crossings_skip_points_that_cannot_be_located():
    a, b = frozenset({"dedicate"}), frozenset({"swap"})
    assert crossings([a, a, b]) == ((1, 2),)
    assert crossings([a, None, frozenset(), b]) == ((0, 3),)
    assert crossings([a, a]) == ()


def test_a_clean_crossover_is_located_in_every_draw():
    # Swap's small pool fails at s=0.5 and passes at s=1.5 and 2.0 in every
    # repetition, so every resample finds the same single crossing.
    points = [_point(0.5, [9.0] * REPS), _point(1.5, [1.0] * REPS), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=200)
    assert got.point == ((0, 1),)
    assert got.chosen[0] == {"dedicate", "swap", "colocate"}
    assert got.chosen[1] == {"swap"}
    assert (got.one_crossing, got.no_crossing, got.many_crossings) == (200, 0, 0)
    assert got.interval == (0, 0)


def test_a_borderline_point_widens_the_interval_rather_than_hiding():
    # At s=1.0 swap's small pool passes in exactly half the repetitions, so its
    # median sits on the SLO boundary and resamples disagree about it.
    half = [1.0] * (REPS // 2) + [9.0] * (REPS // 2)
    points = [_point(0.5, [9.0] * REPS), _point(1.0, half), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=400, seed=1)
    assert got.one_crossing == 400
    assert got.interval == (0, 1)


def test_a_point_under_the_floor_is_excluded_not_guessed():
    thin = ((500,) * 9 + (499,),) + FLOOR_MET[1:]
    points = [_point(0.5, [9.0] * REPS), _point(1.0, [1.0] * REPS, counts=thin), _point(2.0, [1.0] * REPS)]
    got = estimate_crossover(points, slo=5.0, iterations=50)
    assert got.chosen[1] is None
    assert got.point == ((0, 2),)


def test_too_few_repetitions_are_refused():
    short = PointEvaluation(GridPoint(1.0, "spread", 100.0), _point(1.0, [1.0] * REPS).outcomes, FLOOR_MET[:5])
    with pytest.raises(ValueError, match="bootstrap"):
        estimate_crossover([short], slo=5.0)


def test_mixed_regimes_are_refused():
    a = _point(0.5, [9.0] * REPS)
    b = PointEvaluation(GridPoint(1.0, "bursty", 100.0), a.outcomes, FLOOR_MET)
    with pytest.raises(ValueError, match="one regime"):
        estimate_crossover([a, b], slo=5.0)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_crossover.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.crossover'`

- [ ] **Step 3: Implement**

Create `placement/crossover.py`:

```python
"""Where the cheapest SLO-meeting strategy changes along the skew axis.

Sizing is once per grid point, so a strategy's cost there is one integer M,
not a per-repetition sample. A paired difference of per-repetition costs would
have zero width. The uncertainty lives in the sizing, so the interval comes
from resampling repetitions and re-sizing every strategy inside each draw,
then re-locating the crossover (amendment §8). This is the approach artifact
2's gap interval takes through its frontier selection.

A crossover is reported as the pair of adjacent evaluable grid points it lies
between. Cost is integer M, and interpolating between grid points would invent
precision the sizing does not have.
"""

import itertools
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# Private in the shared module, and imported rather than copied: it is the one
# percentile-method endpoint computation every interval in this publication
# uses, and a local copy would be a third implementation of it.
from harness.stats import MIN_BOOTSTRAP_SAMPLES, _percentile_interval
from placement.evaluate import PointEvaluation
from placement.sizing import sized_fleet

__all__ = ["CrossoverEstimate", "cheapest", "choices", "crossings", "estimate_crossover"]

Choice = frozenset[str] | None  # None: grid point not evaluable


def cheapest(sized: dict[str, int | None]) -> frozenset[str]:
    """The strategies tied for the smallest sized M. Empty when all are dominated."""
    feasible = {s: m for s, m in sized.items() if m is not None}
    if not feasible:
        return frozenset()
    best = min(feasible.values())
    return frozenset(s for s, m in feasible.items() if m == best)


def choices(evaluations: Sequence[PointEvaluation], reps: Sequence[int], slo: float) -> list[Choice]:
    out: list[Choice] = []
    for evaluation in evaluations:
        sized = sized_fleet(evaluation, reps, slo)
        out.append(None if sized is None else cheapest(sized))
    return out


def crossings(chosen: Sequence[Choice]) -> tuple[tuple[int, int], ...]:
    """Adjacent pairs of located grid points whose cheapest set differs.

    A point is located when it is evaluable and some strategy meets the SLO
    there. Points that are not are skipped, so a crossing is between the two
    nearest located points on either side of it.
    """
    located = [(i, c) for i, c in enumerate(chosen) if c]
    return tuple(
        (i, j) for (i, a), (j, b) in itertools.pairwise(located) if a != b
    )


@dataclass(frozen=True)
class CrossoverEstimate:
    chosen: tuple[Choice, ...]  # cheapest strategies per grid point, all repetitions
    point: tuple[tuple[int, int], ...]  # crossings on all repetitions
    iterations: int
    no_crossing: int  # draws with none in the swept range
    one_crossing: int
    many_crossings: int
    # Percentile-method bounds on the lower grid index of the crossing, over
    # the draws with exactly one. None when too few draws located one.
    interval: tuple[int, int] | None


def estimate_crossover(
    evaluations: Sequence[PointEvaluation],
    slo: float,
    iterations: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> CrossoverEstimate:
    """Evaluations must be one locality regime, in ascending skew."""
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    skews = [e.point.s for e in evaluations]
    if skews != sorted(skews) or len({e.point.regime for e in evaluations}) != 1:
        raise ValueError("evaluations must be one regime, in ascending skew")
    reps = {e.repetitions for e in evaluations}
    if len(reps) != 1:
        raise ValueError(f"every grid point needs the same repetition count, got {sorted(reps)}")
    (n,) = reps
    if n < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"{n} repetitions; a bootstrap interval needs at least "
            f"{MIN_BOOTSTRAP_SAMPLES}, or it is an artifact of a thin sample"
        )
    everything = list(range(n))
    chosen = choices(evaluations, everything, slo)
    rng = random.Random(seed)
    counts = {0: 0, 1: 0, 2: 0}
    located: list[float] = []
    for _ in range(iterations):
        # One resample of repetition ids for every strategy at every grid
        # point, so the pairing through common traces survives the resample.
        draw = [rng.randrange(n) for _ in everything]
        found = crossings(choices(evaluations, draw, slo))
        counts[min(len(found), 2)] += 1
        if len(found) == 1:
            located.append(float(found[0][0]))
    interval = None
    if located:
        try:
            lo, hi = _percentile_interval(located, alpha)
        except ValueError:
            # Too few single-crossing draws for this alpha. The counts above
            # are published beside the estimate, and they say why.
            interval = None
        else:
            interval = (math.floor(lo), math.floor(hi))
    return CrossoverEstimate(
        chosen=tuple(chosen),
        point=crossings(chosen),
        iterations=iterations,
        no_crossing=counts[0],
        one_crossing=counts[1],
        many_crossings=counts[2],
        interval=interval,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_crossover.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/crossover.py tests/test_placement_crossover.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/crossover.py tests/test_placement_crossover.py
git commit -m "feat: locate the crossover, with an interval resampled through sizing"
```

---

## Task 12: The money view

**Files:**
- Create: `placement/money.py`
- Test: `tests/test_placement_money.py`

A fixed fleet runs all month, so the crossover in dollars is the GPU difference times hours per month times the rate (August design §8). The calendar constants are defined locally because their home is artifact 1's module, which `placement/` may not load. A conformance test, which may import `coldstart`, pins them equal to artifact 1's, the same pattern artifact 2 uses for its statistics copy. The assumptions record requires a provenance string, so an illustrative rate cannot be published looking like a quoted price.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_money.py`:

```python
import pytest

from coldstart.analysis import economics
from placement.money import (
    DAYS_PER_MONTH,
    SECONDS_PER_HOUR,
    Assumptions,
    monthly_cost,
    monthly_difference,
)

RATE = Assumptions(gpu_hourly_rate=0.5, provenance="illustrative round number")


def test_the_calendar_agrees_with_artifact_one():
    """A test may import `coldstart`; the package may not."""
    assert SECONDS_PER_HOUR == economics.SECONDS_PER_HOUR
    assert DAYS_PER_MONTH == economics.DAYS_PER_MONTH


def test_a_fleet_costs_its_gpus_times_the_month():
    assert monthly_cost(10, RATE) == pytest.approx(10 * 24 * 365 / 12 * 0.5)


def test_the_crossover_in_dollars_is_the_gpu_difference_priced():
    assert monthly_difference(21, 12, RATE) == pytest.approx(9 * 24 * 365 / 12 * 0.5)


@pytest.mark.parametrize("rate", [0.0, -1.0, float("nan")])
def test_a_nonsensical_rate_is_refused(rate):
    with pytest.raises(ValueError):
        Assumptions(gpu_hourly_rate=rate, provenance="x")


def test_an_unlabelled_rate_is_refused():
    with pytest.raises(ValueError, match="provenance"):
        Assumptions(gpu_hourly_rate=1.0, provenance=" ")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_money.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.money'`

- [ ] **Step 3: Implement**

Create `placement/money.py`:

```python
"""The money view: a sized fleet in monthly dollars.

A fixed fleet runs all month, so monthly cost is M GPUs times the hours in a
month times the hourly rate. The crossover in dollars is the difference in M
between two strategies, priced the same way (August design §8).

The calendar constants are defined here rather than imported, because their
home, `coldstart.analysis.economics`, is artifact 1's module and `placement/`
may not load `coldstart`. tests/test_placement_money.py pins them equal to
artifact 1's, so the two artifacts cannot disagree about how long a month is.
"""

import math
from dataclasses import dataclass

__all__ = ["DAYS_PER_MONTH", "SECONDS_PER_HOUR", "Assumptions", "monthly_cost", "monthly_difference"]

SECONDS_PER_HOUR = 3600.0
DAYS_PER_YEAR = 365.0
DAYS_PER_MONTH = DAYS_PER_YEAR / 12.0
HOURS_PER_MONTH = 24.0 * DAYS_PER_MONTH


@dataclass(frozen=True)
class Assumptions:
    """Published beside the result, so a reader can substitute their own."""

    gpu_hourly_rate: float
    provenance: str

    def __post_init__(self) -> None:
        if not math.isfinite(self.gpu_hourly_rate) or self.gpu_hourly_rate <= 0:
            raise ValueError(f"gpu_hourly_rate must be finite and positive, got {self.gpu_hourly_rate!r}")
        if not self.provenance.strip():
            raise ValueError(
                "provenance must say where the rate came from; an unlabelled "
                "illustrative rate reads as a quoted price"
            )


def monthly_cost(m: int, assumptions: Assumptions) -> float:
    if type(m) is not int or m < 0:
        raise ValueError(f"m must be a non-negative GPU count, got {m!r}")
    return m * HOURS_PER_MONTH * assumptions.gpu_hourly_rate


def monthly_difference(m_more: int, m_fewer: int, assumptions: Assumptions) -> float:
    """What the larger fleet costs per month over the smaller."""
    return monthly_cost(m_more, assumptions) - monthly_cost(m_fewer, assumptions)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_money.py tests/test_placement_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/money.py tests/test_placement_money.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/money.py tests/test_placement_money.py
git commit -m "feat: price a sized fleet by the month, calendar pinned to artifact 1's"
```

---

## Task 13: The run-length pilot

**Files:**
- Create: `placement/runlength.py`
- Test: `tests/test_placement_runlength.py`

All-or-nothing publication needs every decile to clear the floor in all R repetitions. For that to hold with probability 0.95, each run must clear with probability 1 − 0.05/R. Sizing runs to clear only 95% of the time would leave all 30 clearing together about 21% of the time (amendment §8). Bursty traffic is overdispersed, so no formula sizes it. The pilot draws count-only traces from the same processes on its own seed range, and grows the window until the miss rate is within budget. A count is a Poisson draw given a model's ON time, so the pilot never builds a trace or runs the simulator. It is the only module here that uses numpy, which is already installed as a matplotlib dependency.

The spread test cross-checks the pilot against the amendment's normal-approximation table: at s = 1.0 over 20 models, the pilot's answer lands within 5% of 19,950 requests.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_runlength.py`:

```python
import math

import pytest

from placement.runlength import pilot_window
from placement.traffic import decile_of, zipf_shares

DECILES_20 = decile_of(20)


def test_spread_matches_the_amendments_table():
    """Amendment §8: at s = 1.0 over 20 models, all 30 repetitions clear the
    floor with 95% probability at about 19,950 requests per run. The pilot
    finds its window empirically, so it lands near that, not on it."""
    shares = zipf_shares(20, 1.0)
    window = pilot_window(
        shares, DECILES_20, "spread", total_rate=100.0, repetitions=30,
        mean_burst=30.0, duty=0.2, pilot_traces=1200, seed=0, start=150.0, grow=1.02,
    )
    assert 100.0 * window == pytest.approx(19950, rel=0.05)


def test_bursty_needs_a_longer_window_than_spread():
    shares = zipf_shares(20, 1.0)
    common = {
        "total_rate": 100.0, "repetitions": 30, "mean_burst": 30.0, "duty": 0.2,
        "pilot_traces": 1200, "seed": 0, "start": 150.0, "grow": 1.05,
    }
    spread = pilot_window(shares, DECILES_20, "spread", **common)
    bursty = pilot_window(shares, DECILES_20, "bursty", **common)
    assert bursty > spread


def test_too_few_pilot_traces_to_allow_any_miss_are_refused():
    with pytest.raises(ValueError, match="pilot traces"):
        pilot_window(
            zipf_shares(20, 1.0), DECILES_20, "spread", 100.0, repetitions=30,
            mean_burst=30.0, duty=0.2, pilot_traces=500, seed=0, start=150.0,
        )


def test_the_pilot_is_reproducible():
    kwargs = {
        "shares": zipf_shares(20, 0.6), "deciles": DECILES_20, "regime": "bursty",
        "total_rate": 100.0, "repetitions": 30, "mean_burst": 30.0, "duty": 0.2,
        "pilot_traces": 600, "seed": 3, "start": 80.0,
    }
    assert pilot_window(**kwargs) == pilot_window(**kwargs)
    assert math.isfinite(pilot_window(**kwargs))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_runlength.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.runlength'`

- [ ] **Step 3: Implement**

Create `placement/runlength.py`:

```python
"""How long each grid point must run so every decile clears the p99 floor.

Publication is all-or-nothing per grid point: a decile's p99 is published only
if it clears the floor in every one of R repetitions (amendment §8). For all R
to clear together with probability 0.95, each must clear with probability
1 - 0.05 / R. Sizing each run to clear 95% of the time would leave all 30
clearing together only about 21% of the time.

Bursty traffic is overdispersed, so no formula sizes it. The window is found
by a pilot: count-only traces, drawn from the same processes as `traffic` but
on their own seed range, growing the window until the pilot's miss rate is
within budget. Only counts are needed, and a count is a Poisson draw given a
model's ON time, so the pilot never builds a trace or runs the simulator.
"""

import math
from collections.abc import Sequence

import numpy as np

from placement.tails import P99_FLOOR
from placement.traffic import DECILES

__all__ = ["pilot_window"]


def _counts(
    shares: Sequence[float],
    regime: str,
    total_rate: float,
    window: float,
    mean_burst: float,
    duty: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Requests per model over one window, drawn from the regime's process."""
    rates = np.asarray(shares) * total_rate
    if regime == "spread":
        return rng.poisson(rates * window)
    mean_off = mean_burst * (1.0 - duty) / duty
    on_time = np.zeros(len(shares))
    for k in range(len(shares)):
        on = rng.random() < duty
        t = 0.0
        while t < window:
            length = rng.exponential(mean_burst if on else mean_off)
            if on:
                on_time[k] += min(length, window - t)
            t += length
            on = not on
    return rng.poisson(rates / duty * on_time)


def pilot_window(
    shares: Sequence[float],
    deciles: Sequence[int],
    regime: str,
    total_rate: float,
    repetitions: int,
    mean_burst: float,
    duty: float,
    pilot_traces: int,
    seed: int,
    start: float,
    grow: float = 1.10,
    max_rounds: int = 60,
) -> float:
    """The smallest measured window, growing from `start` by `grow`, at which
    at most `floor(pilot_traces * 0.05 / repetitions)` pilot traces leave some
    decile under the floor."""
    if regime not in ("spread", "bursty"):
        raise ValueError(f"unknown regime {regime!r}")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError(f"repetitions must be a positive int, got {repetitions!r}")
    allowed = math.floor(pilot_traces * 0.05 / repetitions)
    if pilot_traces < 1 or allowed < 1:
        raise ValueError(
            f"{pilot_traces} pilot traces allow no misses at {repetitions} "
            "repetitions, so no finite window could pass; the pilot would only "
            "stop at max_rounds and report a window it never verified. Use at "
            f"least {math.ceil(repetitions / 0.05)} pilot traces"
        )
    if not math.isfinite(start) or start <= 0 or not grow > 1.0:
        raise ValueError("start must be positive and grow above 1")
    index = np.asarray(deciles)
    window = start
    for _ in range(max_rounds):
        rng = np.random.default_rng(seed)
        misses = 0
        for _ in range(pilot_traces):
            per_model = _counts(shares, regime, total_rate, window, mean_burst, duty, rng)
            per_decile = np.bincount(index, weights=per_model, minlength=DECILES)
            if (per_decile < P99_FLOOR).any():
                misses += 1
                if misses > allowed:
                    break
        if misses <= allowed:
            return window
        window *= grow
    raise RuntimeError(
        f"no window up to {window:.0f} s passed the pilot in {max_rounds} rounds; "
        "a grid point this thin should be removed from the grid, not run short"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_runlength.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/runlength.py tests/test_placement_runlength.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/runlength.py tests/test_placement_runlength.py
git commit -m "feat: a pilot that sizes each grid point's window to clear the p99 floor"
```

---

## Task 14: The design record and the placeholder inputs

**Files:**
- Create: `placement/design.py`
- Create: `placement/placeholders.py`
- Test: `tests/test_placement_design.py`

Every value the second pre-registration step fixes goes in one record, so the measurement plan swaps placeholder for registered design in one place. `preregistered` is False until the values come from a committed `docs/experiment-a4.md`. The placeholders are invented. Artifact 2's placeholder solo curve is reused because it is also coldstart-free and also flagged unmeasured, even though it is shaped like the 8B model, not the 4B. A test pins every placeholder as unmeasured, because the sweep's refusal rests entirely on those flags.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_design.py`:

```python
import pytest

from placement.design import Design
from placement.placeholders import (
    PLACEHOLDER_DESIGN,
    PLACEHOLDER_ENGINES,
    PLACEHOLDER_SWAP_TIME,
)

VALID = {
    "n_models": 20, "offered_gpus": 4.0, "hot_fraction": 0.7, "warmup": 120.0,
    "mean_burst": 30.0, "duty": 0.2, "skews": (0.6, 1.0), "regimes": ("spread",),
    "repetitions": 30, "slo_seconds": 4.0, "pilot_traces": 1200, "seed": 1,
    "preregistered": True,
}


def test_a_valid_design_constructs():
    assert Design(**VALID).skews == (0.6, 1.0)


@pytest.mark.parametrize(
    "change",
    [
        {"skews": (1.0, 0.6)},
        {"skews": (0.6, 0.6)},
        {"regimes": ()},
        {"regimes": ("spiky",)},
        {"slo_seconds": 0.0},
        {"slo_seconds": float("nan")},
    ],
)
def test_a_design_that_would_misplace_the_crossover_is_refused(change):
    with pytest.raises(ValueError):
        Design(**{**VALID, **change})


def test_every_placeholder_says_it_is_one():
    """The sweep's refusal rests on these flags. A placeholder flagged as
    measured would produce a result indistinguishable from a real one."""
    assert not PLACEHOLDER_ENGINES.solo.measured
    assert not PLACEHOLDER_ENGINES.colocated.measured
    assert not PLACEHOLDER_ENGINES.measured
    assert not PLACEHOLDER_SWAP_TIME.measured
    assert not PLACEHOLDER_DESIGN.preregistered
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_design.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'placement.design'`

- [ ] **Step 3: Implement**

Create `placement/design.py`:

```python
"""The sweep's design: every value the second pre-registration step fixes.

One record, so the measurement plan swaps the placeholder for the registered
design in one place. `preregistered` is False until the values come from a
committed `docs/experiment-a4.md`; the sweep script refuses an unregistered
design unless told otherwise, for the reason it refuses unmeasured inputs.
"""

import math
from dataclasses import dataclass

from placement.evaluate import REGIMES

__all__ = ["Design"]


@dataclass(frozen=True)
class Design:
    n_models: int
    offered_gpus: float
    hot_fraction: float
    warmup: float
    mean_burst: float
    duty: float
    skews: tuple[float, ...]
    regimes: tuple[str, ...]
    repetitions: int
    slo_seconds: float
    pilot_traces: int
    seed: int
    preregistered: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "skews", tuple(self.skews))
        object.__setattr__(self, "regimes", tuple(self.regimes))
        if list(self.skews) != sorted(set(self.skews)):
            raise ValueError(
                f"skews must be distinct and ascending, got {self.skews}; the "
                "crossover is located between neighbouring grid points"
            )
        if not self.regimes or not set(self.regimes) <= set(REGIMES):
            raise ValueError(f"regimes must be drawn from {REGIMES}, got {self.regimes}")
        if not math.isfinite(self.slo_seconds) or self.slo_seconds <= 0:
            raise ValueError(f"slo_seconds must be finite and positive, got {self.slo_seconds!r}")
```

- [ ] **Step 4: Add `placement/placeholders.py`**

Create `placement/placeholders.py`:

```python
"""Invented inputs, so the GPU-free half runs end to end before hardware time is bought.

THE NUMBERS ARE INVENTED. Every object here is marked unmeasured or
unregistered, and scripts/a4_sweep.py refuses them unless run with
--allow-unmeasured. The measurement plan replaces all of them.

- The solo curve is artifact 2's placeholder, which is shaped like the 8B
  model, not the 4B one artifact 4 will measure.
- The co-located surface is that curve scaled up by 5% for the memory split
  and by a further 7-33% as the neighbour's load rises.
- Swap times are a plausible spread around 20 s.
- The design's values are proposals, not the registered ones.
"""

from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from placement.colocated import ColocatedSurface
from placement.design import Design
from placement.money import Assumptions
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

__all__ = ["PLACEHOLDER_DESIGN", "PLACEHOLDER_ENGINES", "PLACEHOLDER_RATE", "PLACEHOLDER_SWAP_TIME"]

COLOCATED_PLACEHOLDER = ColocatedSurface(
    own=(1, 2, 4, 8, 16, 32),
    neighbour=(0, 8, 16, 32),
    latency=(
        (0.315, 0.336, 0.366, 0.42),
        (0.326, 0.347, 0.378, 0.434),
        (0.347, 0.37, 0.403, 0.462),
        (0.399, 0.426, 0.464, 0.532),
        (0.546, 0.582, 0.634, 0.728),
        (0.997, 1.064, 1.159, 1.33),
    ),
    measured=False,
)

PLACEHOLDER_ENGINES = Engines(solo=SERVICE_CURVE_PLACEHOLDER, colocated=COLOCATED_PLACEHOLDER)

PLACEHOLDER_SWAP_TIME = EmpiricalDistribution(
    samples=(17.8, 18.9, 19.6, 20.2, 20.9, 21.7, 23.4, 26.1), measured=False
)

PLACEHOLDER_DESIGN = Design(
    n_models=20,
    offered_gpus=4.0,
    hot_fraction=0.7,
    warmup=120.0,
    mean_burst=30.0,
    duty=0.2,
    skews=(0.6, 1.0, 1.5, 2.0),
    regimes=("spread", "bursty"),
    repetitions=30,
    slo_seconds=4.0,
    pilot_traces=1200,
    seed=17,
    preregistered=False,
)

PLACEHOLDER_RATE = Assumptions(
    gpu_hourly_rate=0.70, provenance="illustrative round number for a 24 GB card, not a quote"
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_placement_design.py tests/test_placement_boundary.py -q`

Expected: PASS.

- [ ] **Step 6: Lint the files this task touched**

Run: `.venv/bin/ruff check placement/design.py placement/placeholders.py tests/test_placement_design.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement/design.py placement/placeholders.py tests/test_placement_design.py
git commit -m "feat: one design record, and placeholder inputs that say they are placeholders"
```

---

## Task 15: GPU-free end-to-end proof

**Files:**
- Test: `tests/test_a4_end_to_end.py`

Two properties are checked through the real traffic, simulator, evaluation and sizing code, because each exposes a wrong rule rather than a wrong number. When swaps cost nothing, swap needs fewer GPUs than dedicate: the prototype sized dedicate at 10, swap at 4 and co-locate at 5. When swaps cost hours, the only swap configuration meeting the SLO is the one with a pool slot for every tail model, which is dedicate's M exactly. If the family, sizing or drain-out rules were wrong, one of these would fail.

- [ ] **Step 1: Write the failing test**

Create `tests/test_a4_end_to_end.py`:

```python
"""GPU-free proof that the pipeline answers the question it exists for.

Small, measured-flagged synthetic inputs, so every run is seconds, not minutes.
Two properties are checked through the real traffic, simulator, evaluation and
sizing code, because each would expose a wrong rule rather than a wrong number:

- When swaps cost nothing, swap needs fewer GPUs than dedicate.
- When swaps cost hours, the only swap configuration meeting the SLO is the one
  with a pool slot for every tail model, which is dedicate's M exactly.
"""

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.evaluate import GridPoint, Scenario, evaluate_point
from placement.resample import EmpiricalDistribution
from placement.sim import Engines
from placement.sizing import sized_fleet

CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.3, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.21, 0.3), (0.32, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
FREE = EmpiricalDistribution(samples=(0.0,), measured=True)
PROHIBITIVE = EmpiricalDistribution(samples=(10_000.0,), measured=True)
# Ten models at 4 rps each, uniform: 640 expected requests per decile in the
# 160 s window, comfortably over the 500 floor in every repetition.
SCENARIO = Scenario(
    n_models=10, offered_gpus=3.0, saturation_rps=40.0 / 3.0, hot_fraction=0.7,
    warmup=5.0, mean_burst=5.0, duty=0.3,
)
POINT = GridPoint(s=0.0, regime="spread", until=165.0)
SLO = 2.0


def _sized(swap_time):
    evaluation = evaluate_point(POINT, SCENARIO, ENGINES, swap_time, repetitions=3, seed=1)
    assert evaluation.floor_met
    return sized_fleet(evaluation, [0, 1, 2], SLO)


def test_free_swaps_need_fewer_gpus_than_dedicate():
    sized = _sized(FREE)
    assert sized["dedicate"] == 10
    assert sized["swap"] is not None and sized["swap"] < sized["dedicate"]


def test_prohibitive_swaps_size_swap_to_dedicates_m():
    sized = _sized(PROHIBITIVE)
    assert sized["swap"] == sized["dedicate"] == 10
```

- [ ] **Step 2: Run it**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a4_end_to_end.py -q`

Expected: PASS: every module it exercises exists by now. This task adds no code; its test is the proof that the modules compose. If it fails, the defect is in an earlier task, and that task gets fixed and re-reviewed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_a4_end_to_end.py
git commit -m "test: GPU-free proof that sizing responds to swap cost as it must"
```

---

## Task 16: The sweep script

**Files:**
- Create: `scripts/a4_sweep.py`
- Test: `tests/test_a4_sweep.py`

**Prerequisite 2 must hold before this task** (artifact 2 plan 2a Task 5 has landed `autoscale.traffic.saturation_rps`). The script imports it rather than re-deriving saturation.

This ties the pipeline together: pilot each grid point's window, evaluate in parallel, cache, size, locate the crossover per regime, and price the result. It refuses placeholders unless run with `--allow-unmeasured`, and says so before anything runs, as artifact 2's render script does. The cache file name is a hash of every input, so a changed input can never reuse a stale cache. The tests use small, measured-flagged inputs and an unregistered design, so the refusal and the flag are both exercised. The cache test replaces `evaluate_point` with a function that fails if called.

- [ ] **Step 1: Write the failing test**

Create `tests/test_a4_sweep.py`:

```python
"""The sweep script, end to end on small measured-flagged inputs.

It must refuse an unregistered design or unmeasured inputs unless told
otherwise, run the whole pipeline when told, and reuse its cache rather than
re-running a sweep whose inputs have not changed.
"""

import importlib.util
from pathlib import Path

import pytest

from autoscale.service import ServiceCurve
from placement.colocated import ColocatedSurface
from placement.design import Design
from placement.money import Assumptions
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

REPO = Path(__file__).resolve().parents[1]
CURVE = ServiceCurve(points=[(1, 0.2, 5.0, 0.3), (4, 0.3, 13.3, 1.0)], measured=True)
SURFACE = ColocatedSurface(
    own=(1, 4), neighbour=(0, 4), latency=((0.21, 0.3), (0.32, 0.45)), measured=True
)
ENGINES = Engines(CURVE, SURFACE)
FREE = EmpiricalDistribution(samples=(0.0,), measured=True)
SLO = 2.0

def _script():
    spec = importlib.util.spec_from_file_location("a4_sweep", REPO / "scripts" / "a4_sweep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DESIGN = Design(
    n_models=10, offered_gpus=3.0, hot_fraction=0.7, warmup=5.0, mean_burst=5.0,
    duty=0.3, skews=(0.0, 0.5), regimes=("spread",), repetitions=20, slo_seconds=SLO,
    pilot_traces=400, seed=5, preregistered=False,
)
RATE = Assumptions(gpu_hourly_rate=1.0, provenance="test")


def test_the_sweep_refuses_an_unregistered_design_without_the_flag(tmp_path):
    with pytest.raises(SystemExit, match="design"):
        _script().run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=1, allow_unmeasured=False)


def test_the_sweep_runs_end_to_end_and_reuses_its_cache(tmp_path, monkeypatch):
    script = _script()
    summary = script.run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=2, allow_unmeasured=True)
    rows = summary["regimes"]["spread"]["rows"]
    assert [row["s"] for row in rows] == [0.0, 0.5]
    assert all(row["sized"] is not None for row in rows)
    crossover = summary["regimes"]["spread"]["crossover"]
    assert crossover["no_crossing"] + crossover["one_crossing"] + crossover["many_crossings"] == 2000
    assert (tmp_path / "summary.json").is_file()

    def _must_not_run(*args, **kwargs):
        raise AssertionError("the cache should have been reused")

    monkeypatch.setattr(script, "evaluate_point", _must_not_run)
    again = script.run(DESIGN, ENGINES, FREE, RATE, tmp_path, workers=1, allow_unmeasured=True)
    assert again["regimes"] == summary["regimes"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a4_sweep.py -q`

Expected: FAIL with `FileNotFoundError` for `scripts/a4_sweep.py`

- [ ] **Step 3: Implement**

Create `scripts/a4_sweep.py`:

```python
"""Run artifact 4's sweep: size every strategy at every grid point, locate the crossover.

Against PLACEHOLDER inputs until the measurement plan replaces them. The output
is then a check that the machinery works, not a result, which is why the script
refuses unmeasured inputs unless run with --allow-unmeasured and says so on
stdout before anything runs.

The evaluations are cached to JSON under a name derived from every input, so
re-printing a summary does not re-run the sweep, and a changed input can never
silently reuse a stale cache. `--refresh` re-runs it anyway.
"""

import argparse
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.traffic import saturation_rps
from placement.crossover import estimate_crossover
from placement.design import Design
from placement.evaluate import (
    GridPoint,
    Scenario,
    dump_evaluations,
    evaluate_point,
    load_evaluations,
)
from placement.money import Assumptions, monthly_difference
from placement.resample import EmpiricalDistribution
from placement.runlength import pilot_window
from placement.sim import Engines
from placement.sizing import sized_fleet
from placement.tails import P99_FLOOR
from placement.traffic import decile_of, zipf_shares

# The pilot draws from its own seed range, so it never shares a stream with a
# repetition it is sizing.
PILOT_SEED_OFFSET = 1_000_003
CROSSOVER_ITERATIONS = 2000


def _require_measured(design: Design, engines: Engines, swap_time: EmpiricalDistribution, allow: bool) -> None:
    unmeasured = [
        name
        for name, ok in (
            ("solo curve", engines.solo.measured),
            ("co-located surface", engines.colocated.measured),
            ("swap times", swap_time.measured),
            ("design", design.preregistered),
        )
        if not ok
    ]
    if not unmeasured:
        return
    if not allow:
        raise SystemExit(
            f"refusing to sweep: {', '.join(unmeasured)} are placeholders. Their "
            "output is indistinguishable from a result in every format. Pass "
            "--allow-unmeasured to check the machinery against them."
        )
    print(f"WARNING: {', '.join(unmeasured)} are placeholders. This is not a result.")


def grid(design: Design, scenario: Scenario) -> list[GridPoint]:
    """One grid point per (regime, skew), each with the window its pilot found."""
    deciles = decile_of(design.n_models)
    points = []
    for regime in design.regimes:
        for s in design.skews:
            shares = zipf_shares(design.n_models, s)
            coldest = min(sum(sh for sh, d in zip(shares, deciles) if d == k) for k in range(10))
            # Start the pilot at half the break-even window; it only grows.
            start = 0.5 * P99_FLOOR / (coldest * scenario.total_rate)
            window = pilot_window(
                shares, deciles, regime, scenario.total_rate, design.repetitions,
                design.mean_burst, design.duty, design.pilot_traces,
                seed=design.seed + PILOT_SEED_OFFSET, start=start,
            )
            points.append(GridPoint(s=s, regime=regime, until=design.warmup + window))
    return points


def _cache_key(design, engines, swap_time) -> str:
    material = json.dumps(
        [asdict(design), asdict(engines.solo), asdict(engines.colocated), asdict(swap_time)],
        sort_keys=True, default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def run(
    design: Design,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    rate: Assumptions,
    out: Path,
    workers: int,
    allow_unmeasured: bool,
    refresh: bool = False,
) -> dict:
    _require_measured(design, engines, swap_time, allow_unmeasured)
    out.mkdir(parents=True, exist_ok=True)
    scenario = Scenario(
        n_models=design.n_models, offered_gpus=design.offered_gpus,
        saturation_rps=saturation_rps(engines.solo), hot_fraction=design.hot_fraction,
        warmup=design.warmup, mean_burst=design.mean_burst, duty=design.duty,
    )
    cache = out / f"evaluations-{_cache_key(design, engines, swap_time)}.json"
    if cache.exists() and not refresh:
        print(f"reusing {cache} (--refresh to re-run)")
        evaluations = load_evaluations(cache)
    else:
        points = grid(design, scenario)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            evaluations = list(
                pool.map(
                    evaluate_point,
                    points,
                    [scenario] * len(points),
                    [engines] * len(points),
                    [swap_time] * len(points),
                    [design.repetitions] * len(points),
                    [design.seed] * len(points),
                )
            )
        dump_evaluations(cache, evaluations)
        print(f"cached {len(evaluations)} grid points to {cache}")

    everything = list(range(design.repetitions))
    summary: dict = {"design": asdict(design), "rate": asdict(rate), "regimes": {}}
    for regime in design.regimes:
        chosen = sorted((e for e in evaluations if e.point.regime == regime), key=lambda e: e.point.s)
        rows = []
        print(f"\n{regime}: s, window (s), M dedicate / swap / colocate, cheapest, extrapolated")
        for e in chosen:
            sized = sized_fleet(e, everything, design.slo_seconds)
            extrapolated = sum(sum(c.extrapolated) for cs in e.outcomes.values() for c in cs)
            row = {
                "s": e.point.s,
                "window": e.point.until - design.warmup,
                "sized": sized,
                "extrapolated_dispatches": extrapolated,
            }
            rows.append(row)
            cells = "not evaluable" if sized is None else " / ".join(
                "dominated" if sized[k] is None else str(sized[k]) for k in ("dedicate", "swap", "colocate")
            )
            print(f"  {e.point.s:<4} {row['window']:>8.0f}  {cells}  {extrapolated}")
        crossover = estimate_crossover(
            chosen, design.slo_seconds, iterations=CROSSOVER_ITERATIONS, seed=design.seed
        )
        skews = [e.point.s for e in chosen]
        located = [(skews[i], skews[j]) for i, j in crossover.point]
        interval = None if crossover.interval is None else tuple(skews[i] for i in crossover.interval)
        print(
            f"  crossover between s = {located or 'none in range'}; interval on its lower "
            f"grid point {interval}; draws: none {crossover.no_crossing}, one "
            f"{crossover.one_crossing}, several {crossover.many_crossings} of {crossover.iterations}"
        )
        for row in rows:
            sized = row["sized"]
            if sized and sized["dedicate"] is not None:
                cheaper = [m for m in sized.values() if m is not None]
                row["dedicate_over_cheapest_per_month"] = monthly_difference(
                    sized["dedicate"], min(cheaper), rate
                )
        summary["regimes"][regime] = {
            "rows": rows,
            "crossover": {
                "between": located,
                "interval_lower_point": interval,
                "no_crossing": crossover.no_crossing,
                "one_crossing": crossover.one_crossing,
                "many_crossings": crossover.many_crossings,
                "iterations": crossover.iterations,
            },
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build/a4-sweep")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--allow-unmeasured", action="store_true")
    args = ap.parse_args()
    from placement.placeholders import (
        PLACEHOLDER_DESIGN,
        PLACEHOLDER_ENGINES,
        PLACEHOLDER_RATE,
        PLACEHOLDER_SWAP_TIME,
    )

    run(
        PLACEHOLDER_DESIGN, PLACEHOLDER_ENGINES, PLACEHOLDER_SWAP_TIME, PLACEHOLDER_RATE,
        Path(args.out), args.workers, args.allow_unmeasured, args.refresh,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a4_sweep.py -q`

Expected: PASS.

- [ ] **Step 5: Lint the files this task touched**

Run: `.venv/bin/ruff check scripts/a4_sweep.py tests/test_a4_sweep.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/a4_sweep.py tests/test_a4_sweep.py
git commit -m "feat: the artifact 4 sweep, refusing placeholders unless told"
```

---

## Task 17: Verify the whole plan, and run the placeholder sweep once

**Files:** none changed.

Nothing is committed in this task. It is the evidence that the plan's pieces work together at full scale, which no unit test above reaches.

- [ ] **Step 1: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`

Expected: exit 0, with a test count at least the count before Task 1 plus this plan's 121.

- [ ] **Step 2: Lint everything this plan added**

Run: `.venv/bin/ruff check placement scripts/a4_sweep.py tests/test_placement_*.py tests/test_a4_*.py`

Expected: `All checks passed!`

- [ ] **Step 3: Run the placeholder sweep and record what it took**

It takes about 45 minutes, longer than an agent's foreground command may run, so start it in the background with its output in a log file. Then wait for that background command to finish; do not poll it in a loop.

```bash
mkdir -p build/a4-sweep && /usr/bin/time -p env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_sweep.py --allow-unmeasured --workers 8 > build/a4-sweep/run.log 2>&1; echo "EXIT $?" >> build/a4-sweep/run.log
```

When it finishes, read `build/a4-sweep/run.log`. The last lines carry `real`, `user` and `sys` times and `EXIT 0`.

Expected: the `WARNING` line naming all four placeholder inputs, then per regime one row per skew and a crossover line with its draw counts, and `build/a4-sweep/summary.json` written. `build/` is gitignored; commit nothing from it. Parallelism is one grid point per worker, so wall time is set by the heaviest grid point, the bursty regime at the highest skew, whose pilot window is longest. On the machine this plan was written on (8 cores, `--workers 8`), the run took 43 minutes of wall time and 2.1 CPU-hours. The heaviest point's pilot window was 2,582 s.

**Expect no crossover in either regime on these inputs. That is not a bug.** The placeholder run gave the following:

| regime | s = 0.6 | s = 1.0 | s = 1.5 | s = 2.0 |
|---|---|---|---|---|
| spread: M dedicate / swap / co-locate | 20 / 20 / 10 | 21 / 21 / 12 | 22 / 22 / 13 | 23 / 23 / 14 |
| bursty | all dominated | all dominated | all dominated | all dominated |

- **Spread.** Co-locate is cheapest everywhere, and swap sizes to dedicate's M. Twenty models share four GPUs' worth of load, so every model receives a request every few seconds, and a pool even one GPU short of holding every tail model thrashes: the coldest deciles' p99s were 90–224 s at s = 0.6. The placeholder SLO of 4 s is also shorter than one 20 s swap.
- **Bursty.** Every strategy is dominated, dedicate included. A model's load during an ON period is five times its average at duty 0.2, and the placement rules size GPUs on average load, so dedicate's hottest deciles reached p99s of 160–470 s.

Both are properties of the placeholder design point, recorded as work for plan 3 in the next section. If a run on these inputs shows anything else, stop and investigate.

Record in the task report: wall time, worker count, and the per-regime table. These numbers describe the machinery on invented inputs and are **not a result**; they must not be quoted anywhere as one.

- [ ] **Step 4: Confirm the refusal works outside the tests too**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_sweep.py`

Expected: exits non-zero with `refusing to sweep: solo curve, co-located surface, swap times, design are placeholders`.

---

## What the later plans cover, and why they are not written yet

**The shared in-container tooling plan (amendment decision 4, written next).** It lifts the `vllm serve` lifecycle into `harness/` as a context manager, which artifact 4 owns by decision 11, leaving `worker/probe.py` frozen as artifact 1's measured path. It also adds `vllm bench serve` as the shared load path, the single-engine service-curve sweep, and the campaign loop lifted from `coldstart/driver.run_campaign` with a record-builder callback. It is GPU-free to build against the stub engine, and it needs no reconnaissance answers. Artifacts 2 and 5 depend on it too, so it is its own plan rather than part of this one. Two interfaces are already agreed with artifact 5's session, which codes against them now. The first is `harness/serve.py` `served(model, *, args, env, port=8000, health_timeout=900.0)`, a context manager yielding `.base_url`, `.log_lines` and `.healthy`, plus an idempotent `.stop() -> float` that artifact 4's swap handler uses to time teardown inside the context. The second is `harness/bench.py` `run_bench(base_url, *, model, lora_modules, lora_assignment, max_concurrency, num_prompts, dataset_args, ignore_eos, seed, result_dir) -> dict`, which returns `vllm bench serve`'s saved JSON unaltered.

**Artifact 4 plan 2: measurement preparation that does not depend on reconnaissance.** This covers the first pre-registration step in `docs/experiment-a4.md` (model candidates and pins, T_max, `--max-model-len`, the memory split, and the go/no-go criterion), and the recon handler variant (co-residency, one swap, the sleep-mode probe). It also covers `recon/capture.py`'s output-directory change, the swap measurement handler, the two-engine co-location harness, and the record classes and pin set (amendment §1e items 4–8). It builds on the shared tooling plan, so it is written after that plan exists.

**Artifact 4 plan 3: everything after reconnaissance.** This covers the second pre-registration step, which turns the placeholder `Design` into the registered one, and the measured inputs that replace every placeholder in `placement/placeholders.py`. It also covers the replay driver with its one-schedule check on top of `autoscale/validation_band.py`, figure 4's adapter (the one module allowed into `ADAPTERS` in Task 1's test), the four figures under the full UI verification rules, and publication. It also writes `data/a4/cost_per_tenant.json` in the format agreed with artifact 5: `gpu_hourly_rate`, `n_models`, a `reference` grid point fixed in the second pre-registration step, and one row per (regime, s) with dedicated, swapped (process-level arm) and optional sleep-mode cost per tenant per month, null where dominated or not evaluable. It cannot be written honestly now. The request shape, the validation checkpoint set, whether sleep mode exists, and whether the page cache can be dropped are all recon answers (amendment §3–§6). Writing those tasks today would mean inventing them.

**Two findings from this plan's placeholder run that plan 3 must resolve before the second pre-registration step.**

1. **A design point can make the comparison degenerate**, exactly as artifact 2's pre-registered traffic model did (`docs/findings-a2-degenerate-regime.md`). The placeholder point is degenerate in both regimes (Task 17). Plan 3 therefore includes a ranking-blind regime screen in the style of `scripts/a2_regime_probe.py`. It chooses offered load, N, SLO and duty where dedicate meets the SLO and the strategies are distinguishable, without reference to which one wins, and it runs before the design is registered.
2. **An open design question for the owner.** The hot-model rule and dedicate's fixed M size GPUs on average load. Under bursty traffic, ON-period load is average divided by duty, so average-load sizing cannot meet a p99 SLO, and every strategy comes out dominated. There are two options. One is to size on ON-period load in the bursty regime. The other is to let every family, dedicate included, search M upward to a common cap. The amendment is silent on this, it changes what "dominated" means, and it is recorded there as an open item (§14).

---

## Self-review notes

**Spec coverage.** Amendment §1e item 1 → Task 4. Item 2 → Tasks 6 and 7. Item 3 → Task 5. Item 9 → Tasks 8, 10, 11 and 13. Item 10 → Task 12. Item 13 → Task 1, plus the no-reimplementation check (§12) in Task 2. §2's GPU-free gate → Prerequisite 1. §6 (sleep mode) needs a measurement and is plan 3. §7's semantics map as follows: hot rule and families → Task 6; routing, capacity, LRU, drain-out, warm-up and frozen-at-dispatch → Task 7; traffic regimes → Task 4; transitive boundary → Task 1; calendar constants → Task 12. §8's floor → Task 8, all-or-nothing → Task 10, pilot → Task 13, crossover estimator → Task 11. Items 4–8, 11 and 12 are plans 2 and 3, as the previous section says.

**One deviation from the amendment, stated in Task 7.** LRU's clock counts dispatches as well as arrivals. It is a refinement of the amendment's "oldest last-request time", made because the literal reading makes a one-GPU pool thrash without serving its backlog.

**Placeholder scan.** No step says "TBD", "add error handling", or "similar to Task N". Every code step carries the complete file.

**Type consistency.** Names used across tasks, checked against the generated code: `Engines(solo, colocated)`, `RunResult.models/latencies/arrivals`, `Placement.m/served/pool_models`, `ConfigOutcome.decile_p99s`, `PointEvaluation.floor_met/repetitions`, `sized_fleet(evaluation, reps, slo)`, `estimate_crossover(evaluations, slo, iterations, seed, alpha)`, `pilot_window(...)`, `Design(...)`.

**UI audit.** Not applicable: no task changes pixels (see Scope).

**Parity audit.** Not applicable: the plan adds only (see Scope).
