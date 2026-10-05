# Artifact 4 Plan 3 — Measurement, Validation and Publication

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything between artifact 4's reconnaissance and its published post:
- the second pre-registration step;
- the paid measurement campaigns and the trace-replay validation;
- the sweep on measured inputs, and the analysis;
- the four figures;
- artifact 5's cost file;
- the post.

**Architecture:** Part A (Tasks 1–18) spends nothing. It extends plan 1's simulator and plan 2's worker package where the measurements need it, and adds:
- the pre-registered decision rules (`placement/step2.py`);
- a ranking-blind screen for offered load and SLO;
- an in-container replay driver held to the simulator's swap rule;
- the validation gate on artifact 2's band arithmetic;
- one analysis script from every store to `data/a4/analysis.json`, which the figures, the cost file and the post read and nothing recomputes.

Part B (Tasks 19–28) applies those rules to reconnaissance's answers, runs the paid campaigns through the owner, and publishes.

**Tech Stack:** Python 3.13, pytest, ruff, matplotlib, the RunPod serverless API through `harness.runpod`. No new dependencies.

**Governing documents:**
- [the scope amendment](../specs/2026-09-26-multi-model-serving-economics-scope.md), with the owner's §14 decision of 2026-10-04;
- [the August design](../specs/2026-08-17-multi-model-serving-economics-design.md), for the metrics (§8), validation (§9) and publication (§10);
- [the implementation timeline](2026-10-04-artifact-4-implementation-timeline.md), for where this plan sits.

---

## Scope

**This is plan 3 of three.** [Plan 1](2026-09-26-artifact-4-plan-1.md) builds the GPU-free simulator; [plan 2](2026-10-04-artifact-4-plan-2.md) builds the worker side and runs reconnaissance. This plan covers the rest of amendment §1e (items 7, 9, 10, 11), the second pre-registration step (§3, §12), the measurement and validation August §5 and §9 describe, and publication (August §10).

**Part A spends nothing; Part B spends money, and every paid step in it is the owner's.** An agent stops at Tasks 22 and 23's paid steps and at Task 28's publication.

**Every code block in this plan was run before it was written down.** It ran on 2026-10-04 in a clean copy of `main` at `03d9345`, with plan 1 added and plan 2 executed from its own text (as revised the same day). A script read this document and executed it in order: each file it creates, each edit it shows, each test, lint and commit step. Every expected failure failed, and every expected pass passed. At the end, the repository's whole suite (1,993 tests, 152 of them this plan's) passed, `ruff check .` was clean, and artifact 1's parity gate printed `PARITY OK`. The code blocks are generated from those files, not retyped. Part B's new files ran on a simulated publication, as Task 27 says.

**An independent review ran before the plan was written.** It read every file Part A adds, and its ten findings are fixed in the code below. The largest: the first validation trace could not be replayed within a job (Task 8 says how the rule changed).

**No task changes what artifact 1 or 2 publishes.** Task 18 runs artifact 1's parity gate to prove it.

## Prerequisites — STOP if any is false

1. **Plans 1 and 2 have landed** (Part A edits their files):

   ```bash
   test -f placement/sim.py && test -f placement/inputs.py && test -f placement_measure/jobs.py && test -f placement_measure/recon_report.py && echo OK
   ```

2. **Plan 2's reconnaissance report records solo KV capacity** (`kv_solo`). Plan 2 was revised on 2026-10-04 to add it; a checkout of plan 2 from before that lacks it:

   ```bash
   grep -n "def kv_solo" placement_measure/recon_report.py
   ```

3. **No other session holds uncommitted edits to the files Part A modifies:**

   ```bash
   git status --porcelain -- placement placement_measure scripts/a4_sweep.py scripts/a4_measure.py tests/a4_fakes.py tests/test_a4_sweep.py tests/test_placement_boundary.py docs/experiment-a4.md
   ```

   Expected: no output.

Part B has its own prerequisites (Task 19).

## Changes to existing code — inventory and parity

Part A extends plan 1's and plan 2's code; it replaces nothing and removes nothing. Every change below was made by reading the existing file. The parity gate for each is that file's existing tests passing unchanged, which each task's test step runs.

| File | Change | Capabilities kept | Dropped |
|---|---|---|---|
| `placement/fleet.py` | `hot_allocation` gains `peak_factor`, default 1 | all; the default reproduces plan 1 exactly | none |
| `placement/evaluate.py` | ON-period sizing in the bursty regime; five new per-repetition fields with defaults; optional `slo` | all; old caches still load | none |
| `placement/sim.py` | counts hits and records swap start times | all | none |
| `placement/tails.py` | adds `aggregate_p99`, `decile_breach` | all | none |
| `placement/inputs.py` | warm-compile rule (off by default), compile filter, five new reductions; the surface keys only grid cells | all; plan 2's calls behave as before | none |
| `scripts/a4_sweep.py` | cache version; `grid` and the pooled evaluation move to `placement/grid.py` unchanged; `evaluations_for` extracted | `grid`, the cache, `run`, the summary and `main` | none |
| `tests/test_a4_sweep.py` | the cache-reuse test patches `evaluate_grid`, the name the script now calls | the same assertion | none |
| `placement_measure/campaigns.py` | `extra_cells`; `SleepDesign`, `ReplayDesign` | all | none |
| `placement_measure/jobs.py`, `records.py`, `scripts/a4_measure.py` | the `sleep` and `replay` kinds | all | none |
| `placement_measure/swap.py` | times the page-cache eviction as `cache_s`; `swap_s` unchanged | all | none |
| `tests/a4_fakes.py` | two more lines in the fake engine log | all | none |
| `tests/test_placement_boundary.py` | `ADAPTERS` admits `a1_reference.py`, as its own comment asks | all | none |
| `docs/experiment-a4.md` | appends step 2's rules | step 1, verbatim | none |

**Task 14 changes pixels.** Its tests check geometry: text size at phone width, text on the canvas, N stated. A person also looks at every figure at desktop width and at 375 px (superpowers:verifying-visual-output). Task 25 repeats the look on the real figures.

## Task 1: Bursty-regime sizing on ON-period load (amendment §14, decided 2026-10-04)

**Files:**
- Modify: `placement/fleet.py`
- Modify: `placement/evaluate.py`
- Test: `tests/test_placement_on_period_sizing.py`

The owner decided §14's open question on 2026-10-04: in the bursty regime, the hot-model rule and dedicate's fleet size use each model's load **while it is ON**, its average divided by the duty.

**Why it matters.** Plan 1 sized on the average. On its placeholder sweep that left even dedicate missing a p99 SLO in the bursty regime: a GPU sized for the average carried five times that during a burst at duty 0.2. So every strategy came out dominated, and the regime the August design expects swap to win could show nothing.

**What changes.** `hot_allocation` gains a `peak_factor`, 1 by default. `evaluate_point` passes 1 / duty for bursty points and 1 for spread ones. It stays one rule, applied to all three strategies, so dedicate's M is still fixed by construction and still bounds the search.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_on_period_sizing.py`:

```python
"""Amendment §14, decided by the owner on 2026-10-04: in the bursty regime the
hot-model rule and dedicate's fleet size are set on a model's ON-period load.

A bursty model gets all of its traffic while ON, a fraction `duty` of the time,
so its load then is its average divided by duty. Plan 1 sized on the average,
and on its placeholder sweep every strategy, dedicate included, came out
dominated in the bursty regime: a GPU sized for the average carried five times
that during a burst. The rule stays one rule, applied to all three strategies.
"""

import math

import pytest

from placement.evaluate import GridPoint, evaluate_point, sizing_load_factor
from placement.fleet import family, hot_allocation
from placement.traffic import zipf_shares
from tests.test_placement_evaluate import ENGINES, SCENARIO, SWAP


def test_the_peak_factor_scales_every_models_load():
    # Loads at factor 5 are 3.0, 1.0, 0.5, 0.5 GPUs: model 0 needs
    # ceil(3.0 / 0.7) = 5 pinned GPUs and model 1 ceil(1.0 / 0.7) = 2.
    shares = (0.6, 0.2, 0.1, 0.1)
    assert hot_allocation(shares, offered_gpus=1.0, hot_fraction=0.7) == {}
    assert hot_allocation(shares, offered_gpus=1.0, hot_fraction=0.7, peak_factor=5.0) == {0: 5, 1: 2}


@pytest.mark.parametrize("bad", [0.5, math.nan, math.inf])
def test_a_peak_factor_below_one_or_not_finite_is_refused(bad):
    with pytest.raises(ValueError, match="peak_factor"):
        hot_allocation((0.5, 0.5), offered_gpus=1.0, hot_fraction=0.7, peak_factor=bad)


def test_spread_sizes_on_the_average_and_bursty_on_the_on_period():
    assert sizing_load_factor("spread", 0.2) == 1.0
    assert sizing_load_factor("bursty", 0.2) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        sizing_load_factor("bursty", 1.0)
    with pytest.raises(ValueError):
        sizing_load_factor("steady", 0.2)


def _dedicate_m(shares, peak_factor):
    hot = hot_allocation(shares, SCENARIO.offered_gpus, SCENARIO.hot_fraction, peak_factor)
    (only,) = family("dedicate", shares, hot)
    return only.m


def test_the_evaluation_applies_the_regimes_factor_to_every_strategy():
    shares = zipf_shares(SCENARIO.n_models, 1.0)
    for regime, factor in (("spread", 1.0), ("bursty", 1.0 / SCENARIO.duty)):
        evaluation = evaluate_point(GridPoint(1.0, regime, 40.0), SCENARIO, ENGINES, SWAP,
                                    repetitions=1, seed=0)
        assert evaluation.outcomes["dedicate"][0].m == _dedicate_m(shares, factor), regime
        hot = hot_allocation(shares, SCENARIO.offered_gpus, SCENARIO.hot_fraction, factor)
        # Swap and co-locate start from the same pinned GPUs: one rule for all three.
        assert evaluation.outcomes["swap"][0].m == sum(hot.values()) + 1, regime
    assert _dedicate_m(shares, 1.0 / SCENARIO.duty) > _dedicate_m(shares, 1.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_on_period_sizing.py -q`

Expected: FAIL — `ImportError: cannot import name 'sizing_load_factor' from 'placement.evaluate'`

- [ ] **Step 3: Add the peak factor to the hot-model rule and apply it per regime**

In `placement/fleet.py`, replace:

```python
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
```

with:

```python
def hot_allocation(
    shares: Sequence[float], offered_gpus: float, hot_fraction: float, peak_factor: float = 1.0
) -> dict[int, int]:
    """Pinned GPUs per hot model.

    `offered_gpus` is the total offered load in units of one GPU's measured
    saturation. A model whose load exceeds `hot_fraction` of one GPU is hot and
    gets ceil(load / hot_fraction) pinned GPUs, so none of its GPUs is asked to
    run above `hot_fraction` of saturation.

    `peak_factor` scales each model's average load to the load the rule sizes
    for. It is 1 in the spread regime. In the bursty regime it is 1 / duty: a
    model receives all its traffic while ON, so its load then is its average
    divided by duty, and a GPU sized for the average is asked to carry five
    times that during a burst at duty 0.2 (amendment §14, decided 2026-10-04).
    The rule is still one rule for all three strategies.
    """
    if not math.isfinite(offered_gpus) or offered_gpus <= 0:
        raise ValueError(f"offered_gpus must be finite and positive, got {offered_gpus!r}")
    if not (0.0 < hot_fraction <= 1.0):
        raise ValueError(
            f"hot_fraction must be in (0, 1], got {hot_fraction!r}; above 1 a hot "
            "model's GPU would be planned past saturation"
        )
    if not math.isfinite(peak_factor) or peak_factor < 1.0:
        raise ValueError(
            f"peak_factor must be finite and at least 1, got {peak_factor!r}; below 1 "
            "the rule would size a model for less than its average load"
        )
    hot = {}
    for model, share in enumerate(shares):
        load = share * offered_gpus * peak_factor
```

In `placement/evaluate.py`, replace:

```python
    "load_evaluations",
]
```

with:

```python
    "load_evaluations",
    "sizing_load_factor",
]
```

In `placement/evaluate.py`, replace:

```python
def _seed(seed: int, point: GridPoint, rep: int, stream: str) -> int:
```

with:

```python
def sizing_load_factor(regime: str, duty: float) -> float:
    """What the hot-model rule multiplies a model's average load by.

    1 in the spread regime; 1 / duty in the bursty one, where a model's load
    while ON is its average divided by duty (amendment §14, decided
    2026-10-04). Sizing on the average there left even dedicate missing a p99
    SLO, so every strategy came out dominated by construction.
    """
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}")
    if regime == "spread":
        return 1.0
    if not (0.0 < duty < 1.0):
        raise ValueError(f"duty must be strictly between 0 and 1, got {duty!r}")
    return 1.0 / duty


def _seed(seed: int, point: GridPoint, rep: int, stream: str) -> int:
```

In `placement/evaluate.py`, replace:

```python
    hot = hot_allocation(shares, scenario.offered_gpus, scenario.hot_fraction)
```

with:

```python
    hot = hot_allocation(
        shares, scenario.offered_gpus, scenario.hot_fraction,
        peak_factor=sizing_load_factor(point.regime, scenario.duty),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_on_period_sizing.py tests/test_placement_fleet.py tests/test_placement_evaluate.py -q`

Expected: PASS — plan 1's fleet and evaluation tests still pass unchanged

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement/fleet.py placement/evaluate.py tests/test_placement_on_period_sizing.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/fleet.py placement/evaluate.py tests/test_placement_on_period_sizing.py
git commit -m "sizing: in the bursty regime the hot-model rule sizes on ON-period load, as the owner decided for amendment §14"
```

---

## Task 2: Hit rate, aggregate p99 and per-decile SLO breach

**Files:**
- Modify: `placement/sim.py`
- Modify: `placement/tails.py`
- Modify: `placement/evaluate.py`
- Modify: `scripts/a4_sweep.py`
- Test: `tests/test_placement_outcomes.py`

August §8 lists metrics plan 1 does not record. Three of them carry the post's argument:
- **Hit rate:** the share of requests whose model was resident when they arrived.
- **Aggregate p99:** the number a fleet dashboard shows.
- **Per-decile SLO breach:** the share of each popularity decile's requests slower than the SLO. This is August's "tail-tenant SLO cost".

It also records when each swap began, so the swap rate counts only swaps inside the measured window: warm-up and drain-out swaps are artefacts of a finite run.

The last two together show what sizing on the aggregate does to cold tenants (August §8, "Averages hide tenants").

**How they are added.** Each configuration of each strategy records them per repetition, beside its decile p99s. The fields have defaults, so a cache written by plan 1's code still loads. The sweep's cache key gains a version number, so such a cache is never reused with the new fields empty. The breach needs an SLO, so `evaluate_point` takes an optional one. The sizing never reads it, which lets the screen in Task 6 evaluate once and score several SLOs.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_outcomes.py`:

```python
"""What each simulated configuration reports beyond the per-decile p99s that
sizing reads: the hit rate, the aggregate p99 and the per-decile SLO breach.

These are August §8's metrics. The aggregate p99 and the breach fraction carry
the post's fairness argument: a fleet sized on the aggregate looks fine while
its cold tenants miss the target (amendment §1e item 9).
"""

import json
import random

import pytest

from harness.stats import percentiles
from placement.evaluate import GridPoint, dump_evaluations, evaluate_point, load_evaluations
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import RunResult, simulate
from placement.tails import P99_FLOOR, aggregate_p99, decile_breach
from tests.test_placement_evaluate import ENGINES, SCENARIO, SWAP


def _swap_one_gpu():
    return Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1))


def test_a_request_for_a_resident_model_is_a_hit_and_one_behind_a_swap_is_not():
    trace = [(1.0, 0), (2.0, 1), (2.5, 0), (40.0, 0)]
    result = simulate(trace, _swap_one_gpu(), ENGINES,
                      EmpiricalDistribution(samples=(10.0,), measured=True), 0.0, random.Random(0))
    # 0 is resident at t=1: a hit. 1 is not at t=2: a miss, and a swap to 1
    # (done at 12). 0 at 2.5 finds 1 loading: a miss, and a swap back (done at
    # 22.2, after 1's request drains). 0 at 40 is resident again: a hit.
    assert (result.hits, result.swaps) == (2, 2)
    assert len(result.latencies) == 4
    assert result.swap_starts == [2.0, pytest.approx(12.2)]


def test_warm_up_arrivals_are_not_counted_as_hits():
    trace = [(1.0, 0), (2.0, 0), (30.0, 0)]
    result = simulate(trace, _swap_one_gpu(), ENGINES, SWAP, 10.0, random.Random(0))
    assert result.hits == 1 and len(result.latencies) == 1


def test_the_aggregate_p99_is_over_every_request_and_refuses_a_thin_run():
    latencies = [float(i) for i in range(P99_FLOOR)]
    result = RunResult(m=1, arrivals=[0.0] * P99_FLOOR, models=[0] * P99_FLOOR, latencies=latencies)
    assert aggregate_p99(result) == percentiles(latencies, want=("p99",))["p99"]
    thin = RunResult(m=1, arrivals=[0.0], models=[0], latencies=[1.0])
    assert aggregate_p99(thin) is None


def test_the_breach_is_the_share_of_each_deciles_requests_above_the_slo():
    result = RunResult(m=1, arrivals=[0.0] * 5, models=[0, 0, 0, 9, 9],
                       latencies=[1.0, 3.0, 5.0, 1.0, 2.0])
    deciles = tuple(range(10))
    breach = decile_breach(result, deciles, slo=2.0)
    assert breach[0] == pytest.approx(2 / 3)
    assert breach[9] == 0.0  # 2.0 is not above an SLO of 2.0
    assert breach[1:9] == (None,) * 8


def test_the_evaluation_reports_every_metric_per_repetition():
    evaluation = evaluate_point(GridPoint(1.0, "spread", 40.0), SCENARIO, ENGINES, SWAP,
                                repetitions=2, seed=0, slo=1.0)
    for configs in evaluation.outcomes.values():
        for c in configs:
            assert len(c.aggregate_p99s) == len(c.hits) == len(c.requests) == 2
            assert len(c.decile_breach) == 2 and all(len(r) == 10 for r in c.decile_breach)
            assert all(h <= n for h, n in zip(c.hits, c.requests, strict=True))
            assert all(w <= s for w, s in zip(c.window_swaps, c.swaps, strict=True))
    dedicate = evaluation.outcomes["dedicate"][0]
    assert dedicate.hits == dedicate.requests  # every model always resident
    assert evaluation.outcomes["swap"][0].hits < evaluation.outcomes["swap"][0].requests


def test_without_an_slo_there_is_no_breach_and_sizing_is_unchanged():
    point = GridPoint(1.0, "spread", 40.0)
    plain = evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=1, seed=3)
    with_slo = evaluate_point(point, SCENARIO, ENGINES, SWAP, repetitions=1, seed=3, slo=1.0)
    assert all(c.decile_breach == () for cs in plain.outcomes.values() for c in cs)
    for strategy in plain.outcomes:
        assert [c.decile_p99s for c in plain.outcomes[strategy]] == [
            c.decile_p99s for c in with_slo.outcomes[strategy]]


def test_the_new_fields_survive_the_cache_and_an_older_cache_still_loads(tmp_path):
    evaluation = evaluate_point(GridPoint(1.0, "spread", 40.0), SCENARIO, ENGINES, SWAP,
                                repetitions=1, seed=0, slo=1.0)
    path = tmp_path / "cache.json"
    dump_evaluations(path, [evaluation])
    assert load_evaluations(path) == [evaluation]
    raw = json.loads(path.read_text())
    for configs in raw[0]["outcomes"].values():
        for o in configs:
            for key in ("aggregate_p99s", "hits", "requests", "decile_breach", "window_swaps"):
                del o[key]
    path.write_text(json.dumps(raw))
    (old,) = load_evaluations(path)
    assert old.outcomes["swap"][0].hits == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_outcomes.py -q`

Expected: FAIL — `ImportError: cannot import name 'aggregate_p99' from 'placement.tails'`

- [ ] **Step 3: Record the three metrics**

In `placement/sim.py`, replace:

```python
    m: int
    arrivals: list[float] = field(default_factory=list)
    models: list[int] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    completed: int = 0
    swaps: int = 0
    extrapolated: int = 0
```

with:

```python
    m: int
    arrivals: list[float] = field(default_factory=list)
    models: list[int] = field(default_factory=list)
    latencies: list[float] = field(default_factory=list)
    completed: int = 0
    swaps: int = 0
    extrapolated: int = 0
    # Post-warm-up arrivals whose model was resident and admitting on some GPU
    # when the request arrived: August §8's hit rate is hits / len(latencies).
    hits: int = 0
    # When each swap began. `swaps` counts warm-up and drain-out swaps too; a
    # swap rate is read from the starts inside the measured window.
    swap_starts: list[float] = field(default_factory=list)
```

In `placement/sim.py`, replace:

```python
        if event.kind == "arrival":
            m = event.payload["model"]
            last_used[m] = now
```

with:

```python
        if event.kind == "arrival":
            m = event.payload["model"]
            if now >= warmup and hosts[m]:
                result.hits += 1
            last_used[m] = now
```

In `placement/sim.py`, replace:

```python
        gpus[g].state = _SWAPPING
        result.swaps += 1
```

with:

```python
        gpus[g].state = _SWAPPING
        result.swaps += 1
        result.swap_starts.append(now)
```

In `placement/tails.py`, replace:

```python
__all__ = ["P99_FLOOR", "decile_counts", "decile_p99s"]
```

with:

```python
__all__ = ["P99_FLOOR", "aggregate_p99", "decile_breach", "decile_counts", "decile_p99s"]
```

In `placement/tails.py`, replace:

```python
def decile_p99s(result: RunResult, deciles: Sequence[int]) -> tuple[float | None, ...]:
```

with:

```python
def aggregate_p99(result: RunResult) -> float | None:
    """p99 over every post-warm-up request, None under the floor. The number a
    fleet dashboard shows, and the one the per-decile view exists to correct."""
    if len(result.latencies) < P99_FLOOR:
        return None
    return percentiles(result.latencies, want=("p99",))["p99"]


def decile_breach(
    result: RunResult, deciles: Sequence[int], slo: float
) -> tuple[float | None, ...]:
    """Fraction of each decile's requests slower than `slo`, None for a decile
    that received none. The tail-tenant SLO cost (August §8): what share of a
    cold tenant's requests miss the target its fleet was sized against."""
    slow = [0] * DECILES
    total = [0] * DECILES
    for m, latency in zip(result.models, result.latencies, strict=True):
        total[deciles[m]] += 1
        slow[deciles[m]] += latency > slo
    return tuple(None if n == 0 else s / n for s, n in zip(slow, total, strict=True))


def decile_p99s(result: RunResult, deciles: Sequence[int]) -> tuple[float | None, ...]:
```

In `placement/evaluate.py`, replace:

```python
from placement.tails import P99_FLOOR, decile_counts, decile_p99s
```

with:

```python
from placement.tails import P99_FLOOR, aggregate_p99, decile_breach, decile_counts, decile_p99s
```

In `placement/evaluate.py`, replace:

```python
@dataclass(frozen=True)
class ConfigOutcome:
    """One configuration's results, one entry per repetition."""

    strategy: str
    m: int
    decile_p99s: tuple[tuple[float | None, ...], ...]
    swaps: tuple[int, ...]
    extrapolated: tuple[int, ...]
```

with:

```python
@dataclass(frozen=True)
class ConfigOutcome:
    """One configuration's results, one entry per repetition.

    `decile_breach` is empty unless the evaluation was given an SLO; the
    sizing never reads it, so the screen evaluates once and scores several
    SLOs against the same p99s.
    """

    strategy: str
    m: int
    decile_p99s: tuple[tuple[float | None, ...], ...]
    swaps: tuple[int, ...]
    extrapolated: tuple[int, ...]
    aggregate_p99s: tuple[float | None, ...] = ()
    hits: tuple[int, ...] = ()
    requests: tuple[int, ...] = ()
    decile_breach: tuple[tuple[float | None, ...], ...] = ()
    # Swaps that began inside the measured window, [warm-up, until].
    window_swaps: tuple[int, ...] = ()
```

In `placement/evaluate.py`, replace:

```python
    repetitions: int,
    seed: int,
) -> PointEvaluation:
    shares = zipf_shares(scenario.n_models, point.s)
```

with:

```python
    repetitions: int,
    seed: int,
    slo: float | None = None,
) -> PointEvaluation:
    shares = zipf_shares(scenario.n_models, point.s)
```

In `placement/evaluate.py`, replace:

```python
        strategy: [{"p99s": [], "swaps": [], "extrapolated": []} for _ in configs]
```

with:

```python
        strategy: [
            {"p99s": [], "swaps": [], "extrapolated": [], "agg": [], "hits": [], "requests": [],
             "breach": [], "window_swaps": []}
            for _ in configs
        ]
```

In `placement/evaluate.py`, replace:

```python
                slot["extrapolated"].append(result.extrapolated)
```

with:

```python
                slot["extrapolated"].append(result.extrapolated)
                slot["agg"].append(aggregate_p99(result))
                slot["hits"].append(result.hits)
                slot["requests"].append(len(result.latencies))
                slot["window_swaps"].append(
                    sum(1 for t in result.swap_starts if scenario.warmup <= t <= point.until))
                if slo is not None:
                    slot["breach"].append(decile_breach(result, deciles, slo))
```

In `placement/evaluate.py`, replace:

```python
                extrapolated=tuple(slot["extrapolated"]),
            )
            for placement, slot in zip(families[strategy], per_config[strategy], strict=True)
```

with:

```python
                extrapolated=tuple(slot["extrapolated"]),
                aggregate_p99s=tuple(slot["agg"]),
                hits=tuple(slot["hits"]),
                requests=tuple(slot["requests"]),
                decile_breach=tuple(slot["breach"]),
                window_swaps=tuple(slot["window_swaps"]),
            )
            for placement, slot in zip(families[strategy], per_config[strategy], strict=True)
```

In `placement/evaluate.py`, replace:

```python
                    extrapolated=tuple(o["extrapolated"]),
                )
                for o in configs
```

with:

```python
                    extrapolated=tuple(o["extrapolated"]),
                    aggregate_p99s=tuple(o.get("aggregate_p99s", ())),
                    hits=tuple(o.get("hits", ())),
                    requests=tuple(o.get("requests", ())),
                    decile_breach=tuple(tuple(rep) for rep in o.get("decile_breach", ())),
                    window_swaps=tuple(o.get("window_swaps", ())),
                )
                for o in configs
```

In `scripts/a4_sweep.py`, replace:

```python
PILOT_SEED_OFFSET = 1_000_003
CROSSOVER_ITERATIONS = 2000
```

with:

```python
PILOT_SEED_OFFSET = 1_000_003
CROSSOVER_ITERATIONS = 2000
# Bumped whenever an evaluation gains a field, so a cache written by older code
# is never read back with the new fields silently empty.
CACHE_VERSION = 2
```

In `scripts/a4_sweep.py`, replace:

```python
        [asdict(design), asdict(engines.solo), asdict(engines.colocated), asdict(swap_time)],
```

with:

```python
        [CACHE_VERSION, asdict(design), asdict(engines.solo), asdict(engines.colocated),
         asdict(swap_time)],
```

In `scripts/a4_sweep.py`, replace:

```python
                    [design.repetitions] * len(points),
                    [design.seed] * len(points),
                )
```

with:

```python
                    [design.repetitions] * len(points),
                    [design.seed] * len(points),
                    [design.slo_seconds] * len(points),
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_outcomes.py tests/test_placement_sim.py tests/test_placement_tails.py tests/test_placement_evaluate.py tests/test_a4_sweep.py -q`

Expected: PASS — plan 1's tests still pass unchanged

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement/sim.py placement/tails.py placement/evaluate.py scripts/a4_sweep.py tests/test_placement_outcomes.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/sim.py placement/tails.py placement/evaluate.py scripts/a4_sweep.py tests/test_placement_outcomes.py
git commit -m "sim: hit rate, aggregate p99 and per-decile SLO breach, per configuration and repetition"
```

---

## Task 3: The sleep-mode job, and cell designs beyond the grid

**Files:**
- Modify: `placement_measure/campaigns.py`
- Modify: `placement_measure/jobs.py`
- Modify: `placement_measure/records.py`
- Modify: `scripts/a4_measure.py`
- Test: `tests/test_placement_measure_sleep_and_extra_cells.py`

**Sleep mode.** Amendment §6 measures a sleep-mode arm and reports it beside the crossover, if reconnaissance finds sleep mode working. Plan 2's reconnaissance has a probe that runs one sleep-mode switch. This task makes it a measurement job, `kind: "sleep"`, so the arm can be repeated through the same campaign loop and store as every other measurement.

**What the switch costs.** It is B's sleep plus A's wake: the in-process counterpart of a swap. It counts only if every step answered 200, including a completion from A after waking.

**Cells beyond the grid.** `CellDesign` gains `extra_cells`, conditions outside the grid's product, for two uses:
- the two held-out cells the interference check predicts (August §9's second check);
- a top-up of cells left short of valid repeats.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_sleep_and_extra_cells.py`:

```python
"""The sleep-mode arm as a measurement job, and cell designs that name cells
outside the grid's product: the held-out cells and any top-up."""

import pytest
from a4_fakes import Clock, FakeEngines
from test_placement_measure_recon import Resp, _deps

from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement_measure.campaigns import CellDesign, SleepDesign, parse_sleep, sleep_condition
from placement_measure.jobs import measure_job, sleep_switch
from placement_measure.prereg import SLEEP_GMU
from placement_measure.records import build_record

A, B = "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"


def _host():
    return {"host_id": "h1", "runpod_pod_id": None}


def _timed_deps(clock, statuses=None):
    """Recon fakes whose endpoints take time: sleep 2 s, wake 3 s, a
    completion 0.5 s. `statuses` overrides the HTTP status per URL suffix."""
    deps = _deps(clock, FakeEngines(clock))
    cost = {"sleep?level=1": 2.0, "wake_up": 3.0, "completions": 0.5}
    statuses = statuses or {}

    def post(url, **kw):
        suffix = next(k for k in cost if url.endswith(k))
        clock.t += cost[suffix]
        return Resp(status=statuses.get(suffix, 200))

    deps.post = post
    return deps


def _payload():
    design = SleepDesign(a=A, b=B, repeats=2, seed=5)
    return design.payload(design.schedule()[0], "r1")


def test_the_condition_round_trips_and_a_malformed_one_is_refused():
    assert parse_sleep(sleep_condition(A, B)) == (A, B)
    for bad in ("sleep:ab", f"swap:{A}>{B}", "sleep:>b"):
        with pytest.raises(ValueError):
            parse_sleep(bad)


def test_a_sleep_design_starts_both_engines_in_sleep_mode():
    design = SleepDesign(a=A, b=B, repeats=3, seed=5)
    assert len(design.schedule()) == 3
    p = _payload()
    assert p["kind"] == "sleep" and p["run_id"] == "r1"
    for side in ("a", "b"):
        assert p[side]["gpu_memory_utilization"] == SLEEP_GMU
        assert "--enable-sleep-mode" in p[side]["extra_args"]


def test_the_switch_is_bs_sleep_plus_as_wake_through_the_json_round_trip():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(p, recon_deps=_timed_deps(clock),
                                                     host=_host, clock=clock))
    outcome = sub.submit_payload(_payload())
    assert outcome.error is None
    out = outcome.payload
    assert out["switch_s"] == pytest.approx(2.0 + 3.0)
    assert out["first_request_after_wake_s"] == pytest.approx(0.5)
    assert out["run_id"] == "r1" and out["kind"] == "sleep"
    record = build_record(ScheduledRun(0, 0, sleep_condition(A, B)), "r1", outcome,
                          kind="sleep", source="stub")
    assert record.outcome == "ok"


def test_a_wake_that_fails_is_no_switch_and_a_failed_record():
    clock = Clock()
    out = measure_job(_payload(), recon_deps=_timed_deps(clock, {"wake_up": 404}),
                      host=_host, clock=clock)
    assert out["switch_s"] is None and "did not answer 200" in out["failure"]
    record = build_record(ScheduledRun(0, 0, sleep_condition(A, B)), "r1",
                          PayloadStubSubmitter(lambda p: out).submit_payload({}),
                          kind="sleep", source="stub")
    assert record.outcome == "failed" and "did not answer 200" in record.failure


def test_an_engine_that_never_came_up_is_reported_as_unhealthy():
    steps = {"a": {"healthy": True}, "b": {"healthy": False}}
    out = sleep_switch(steps)
    assert out["healthy"] is False and out["switch_s"] is None
    assert "never answered /health" in out["failure"]


def _cells(**over):
    fields = {"measured_model": A, "neighbour_model": B, "own_levels": (2, 8),
              "neighbour_levels": (0, 8), "solo": False, "input_len": 768, "output_len": 256,
              "repeats": 2, "seed": 3}
    return CellDesign(**{**fields, **over})


def test_extra_cells_join_the_grid_once():
    design = _cells(extra_cells=("pair:o3:n12", "pair:o2:n8"))
    assert design.conditions() == ["pair:o2:n0", "pair:o2:n8", "pair:o8:n0", "pair:o8:n8",
                                   "pair:o3:n12"]


def test_a_design_of_extra_cells_alone_is_a_top_up():
    top_up = _cells(own_levels=(), neighbour_levels=(), extra_cells=("pair:o8:n8", "solo:o2"))
    assert top_up.conditions() == ["pair:o8:n8", "solo:o2"]
    assert top_up.payload(ScheduledRun(0, 0, "solo:o2"), "r")["b"] is None


def test_a_malformed_extra_cell_or_an_empty_design_is_refused():
    with pytest.raises(ValueError):
        _cells(extra_cells=("o3:n12",))
    with pytest.raises(ValueError, match="nothing"):
        _cells(own_levels=(), neighbour_levels=()).conditions()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_sleep_and_extra_cells.py -q`

Expected: FAIL — `ImportError: cannot import name 'SleepDesign' from 'placement_measure.campaigns'`

- [ ] **Step 3: Add the sleep job and extra cells**

In `placement_measure/campaigns.py`, replace:

```python
Two campaigns, each one schedule from `harness.scheduler.build_schedule`, so
conditions are interleaved within each block and a condition is never
confounded with time-varying platform state (artifact 1 spec 5):

- swaps: a condition is an ordered checkpoint pair and a cache state.
- cells: a condition is a grid cell -- `solo:o8`, or `pair:o8:n16`.
```

with:

```python
Each campaign is one schedule from `harness.scheduler.build_schedule`, so
conditions are interleaved within each block and a condition is never
confounded with time-varying platform state (artifact 1 spec 5):

- swaps: a condition is an ordered checkpoint pair and a cache state.
- cells: a condition is a grid cell -- `solo:o8`, or `pair:o8:n16`.
- sleep: one condition, the sleep-mode switch between two checkpoints
  (amendment §6), measured only if reconnaissance found sleep mode working.
```

In `placement_measure/campaigns.py`, replace:

```python
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
```

with:

```python
from placement_measure.prereg import (
    HF_HOME,
    JOB_BUDGET_S,
    RELEASE_TIMEOUT_S,
    RELEASE_TOLERANCE_MIB,
    SLEEP_GMU,
    SOLO_GMU,
    SPLIT_GMU,
    engine,
)

__all__ = ["CellDesign", "SleepDesign", "SwapDesign", "cell_condition", "parse_cell",
           "parse_sleep", "parse_swap", "sleep_condition", "swap_condition"]

SLEEP_FLAGS = ("--enable-sleep-mode",)
```

In `placement_measure/campaigns.py`, replace:

```python
def cell_condition(own: int, neighbour: int | None) -> str:
```

with:

```python
def sleep_condition(a: str, b: str) -> str:
    return f"sleep:{a}>{b}"


def parse_sleep(condition: str) -> tuple[str, str]:
    kind, _, pair = condition.partition(":")
    a, sep, b = pair.partition(">")
    if kind != "sleep" or not sep or not a or not b:
        raise ValueError(f"{condition!r} is not a sleep condition")
    return a, b


def cell_condition(own: int, neighbour: int | None) -> str:
```

In `placement_measure/campaigns.py`, replace:

```python
    # The neighbour is sent this many times the measured run's request-waves,
    # and stopped when the measured run ends; a neighbour that still ran out
    # is flagged in the cell's own output.
    neighbour_overrun: int = 4

    def conditions(self) -> list[str]:
        cells = [cell_condition(o, n) for o in self.own_levels for n in self.neighbour_levels]
        if self.solo:
            cells += [cell_condition(o, None) for o in self.own_levels]
        return cells
```

with:

```python
    # The neighbour is sent this many times the measured run's request-waves,
    # and stopped when the measured run ends; a neighbour that still ran out
    # is flagged in the cell's own output.
    neighbour_overrun: int = 4
    # Cells outside the grid's product: the held-out cells the interference
    # check predicts, or a top-up of cells left short of valid repetitions.
    extra_cells: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_cells", tuple(self.extra_cells))
        for c in self.extra_cells:
            parse_cell(c)

    def conditions(self) -> list[str]:
        cells = [cell_condition(o, n) for o in self.own_levels for n in self.neighbour_levels]
        if self.solo:
            cells += [cell_condition(o, None) for o in self.own_levels]
        cells += [c for c in self.extra_cells if c not in cells]
        if not cells:
            raise ValueError("a cell design with no cells would schedule nothing")
        return cells
```

In `placement_measure/campaigns.py`, replace:

```python
                     "neighbour_prompts": neighbour_prompts,
                     "seed": self.seed * 1000 + scheduled.run_index},
        }
```

with:

```python
                     "neighbour_prompts": neighbour_prompts,
                     "seed": self.seed * 1000 + scheduled.run_index},
        }


@dataclass(frozen=True)
class SleepDesign:
    """Repeats of one sleep-mode switch: A sleeps, B starts and serves, B
    sleeps, A wakes and serves. The switch's cost is B's sleep plus A's wake
    (`placement_measure.jobs`), the in-process counterpart of a swap."""

    a: str
    b: str
    repeats: int
    seed: int

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule([sleep_condition(self.a, self.b)], self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        a, b = parse_sleep(scheduled.condition)
        return {"kind": "sleep", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "a": engine(a, SLEEP_GMU, SLEEP_FLAGS).to_dict(),
                "b": engine(b, SLEEP_GMU, SLEEP_FLAGS).to_dict()}
```

In `placement_measure/jobs.py`, replace:

```python
"""One measurement job: a swap, or a co-location cell, chosen by `kind`.
```

with:

```python
"""One measurement job, chosen by `kind`: a swap, a co-location cell, or a
sleep-mode switch.
```

In `placement_measure/jobs.py`, replace:

```python
from placement_measure.colocation import CellDeps, CellSpec, measure_cell
from placement_measure.engine import EngineSpec
from placement_measure.swap import SwapDeps, measure_swap

__all__ = ["KINDS", "measure_job"]

KINDS = ("swap", "cell")
TEARDOWN_RESERVE_S = 120.0
```

with:

```python
from placement_measure.colocation import CellDeps, CellSpec, measure_cell
from placement_measure.engine import EngineSpec
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.swap import SwapDeps, measure_swap

__all__ = ["KINDS", "measure_job", "sleep_switch"]

KINDS = ("swap", "cell", "sleep")
TEARDOWN_RESERVE_S = 120.0
SLEEP_STEPS = ("sleep_a", "sleep_b", "wake_a", "smoke_a_after_wake")


def sleep_switch(steps: dict) -> dict:
    """The sleep probe's steps, reduced to one switch.

    The switch from serving B back to serving A costs B's sleep plus A's wake.
    It counts only if every step answered 200, including a completion from A
    after waking: a wake that returns before A can serve is not a switch.
    """
    statuses = {k: (steps.get(k) or {}).get("status") for k in SLEEP_STEPS}
    engines_up = all((steps.get(k) or {}).get("healthy") for k in ("a", "b"))
    ok = engines_up and all(s == 200 for s in statuses.values())
    return {
        "healthy": engines_up,
        "statuses": statuses,
        "switch_s": steps["sleep_b"]["seconds"] + steps["wake_a"]["seconds"] if ok else None,
        "first_request_after_wake_s": (steps.get("smoke_a_after_wake") or {}).get("seconds"),
        "memory_a_asleep_mib": (steps.get("memory_a_asleep") or {}).get("used_mib"),
        "failure": None if ok else (
            "an engine never answered /health" if not engines_up
            else f"a sleep-mode step did not answer 200: {statuses}"),
    }
```

In `placement_measure/jobs.py`, replace:

```python
    swap_deps: SwapDeps | None = None,
    cell_deps: CellDeps | None = None,
```

with:

```python
    swap_deps: SwapDeps | None = None,
    cell_deps: CellDeps | None = None,
    recon_deps: ReconDeps | None = None,
```

In `placement_measure/jobs.py`, replace:

```python
    else:
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
        b = payload.get("b")
```

with:

```python
    elif kind == "sleep":
        probe = run_probe({"probe": "sleep", "job_budget_s": payload["job_budget_s"],
                           "a": payload["a"], "b": payload["b"]}, recon_deps)
        out = {**sleep_switch(probe["result"]), "steps": probe["result"]}
    else:
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S
        b = payload.get("b")
```

In `placement_measure/records.py`, replace:

```python
def _failure_of(kind: str, output: dict) -> str | None:
    if kind == "swap":
        return None if output.get("swap_s") is not None else (output.get("failure") or "no swap time")
```

with:

```python
def _failure_of(kind: str, output: dict) -> str | None:
    if kind == "swap":
        return None if output.get("swap_s") is not None else (output.get("failure") or "no swap time")
    if kind == "sleep":
        return None if output.get("switch_s") is not None else (
            output.get("failure") or "no switch time")
```

In `scripts/a4_measure.py`, replace:

```python
from placement_measure.campaigns import CellDesign, SwapDesign
```

with:

```python
from placement_measure.campaigns import CellDesign, SleepDesign, SwapDesign
```

In `scripts/a4_measure.py`, replace:

```python
DESIGNS = {"swap": SwapDesign, "cell": CellDesign}
```

with:

```python
DESIGNS = {"swap": SwapDesign, "cell": CellDesign, "sleep": SleepDesign}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_sleep_and_extra_cells.py tests/test_placement_measure_campaigns.py tests/test_placement_measure_jobs.py tests/test_a4_measure_end_to_end.py tests/test_placement_measure_boundary.py -q`

Expected: PASS — plan 2's tests still pass unchanged

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement_measure/campaigns.py placement_measure/jobs.py placement_measure/records.py scripts/a4_measure.py tests/test_placement_measure_sleep_and_extra_cells.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement_measure/campaigns.py placement_measure/jobs.py placement_measure/records.py scripts/a4_measure.py tests/test_placement_measure_sleep_and_extra_cells.py
git commit -m "measure: the sleep-mode switch as a job, and cell designs that name held-out or top-up cells"
```

---

## Task 4: The in-container trace-replay driver

**Files:**
- Create: `placement_measure/replay.py`
- Modify: `placement_measure/swap.py`
- Modify: `placement_measure/campaigns.py`
- Modify: `placement_measure/jobs.py`
- Modify: `placement_measure/records.py`
- Modify: `scripts/a4_measure.py`
- Test: `tests/test_placement_measure_replay.py`

This builds amendment §1e item 7, August §9's validation gate: three models on one GPU, genuine swaps, and a recorded trace replayed at its exact timestamps. `vllm bench serve` cannot do it. It sends a dataset at a rate, not a schedule at its timestamps, and it has no notion of a request waiting for its model to be swapped in.

**The driver's policy is the simulator's swap-LRU for a pool of one GPU,** restated because this package may not import `placement`:
- requests for the resident tenant go out at once, up to the solo curve's top measured concurrency;
- a request for another tenant drains the GPU and swaps;
- after a swap, the next waiting tenant goes oldest-first.

Task 8 holds the driver and the simulator to each other.

**Design.** One event loop owns all state. Requests run on a thread pool and swaps on their own thread, and both report back through one queue. Engine ownership is explicit:
- a swap that fails stops the engine it started, and closes the outgoing one if its teardown raised;
- an engine whose record cannot be built is stopped before the error propagates;
- a deadline that falls mid-swap waits up to 240 s for the swap and then stops its engine, because an engine left running would hold the next job's port and memory. The replay job's deadline reserves that wait on top of the 120 s teardown reserve, so the wait cannot outlast the platform's 1800 s timeout.

Prompts are token ids drawn from a seed, so every repeat sends identical prompts of exactly `input_len` tokens without a tokenizer. The output echoes the schedule, so a stored record is self-contained.

**One edit to plan 2's swap measurement.** A cold replay drops the incoming checkpoint's page cache before every swap-in, and a fleet does not. So `measure_swap` now times the eviction separately, as `cache_s`. `swap_s`, the number the simulator draws, still excludes it; the validation's prediction adds it back (Task 8).

**The tests use the real clock.** The driver is threaded, so its tests run fake engines that take hundredths of a second and assert orders and counts. They passed 12 runs in a row, and 3 runs with eight CPU-burning processes alongside.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_measure_replay.py`:

```python
"""The trace-replay driver, on fake engines that take real (short) time.

The driver runs threads, so these tests use the real clock with durations of
hundredths of a second, and assert orders and counts rather than exact times.
"""

import contextlib
import threading
import time

import pytest
from a4_fakes import FakeServer

from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement_measure import jobs
from placement_measure import replay as replay_module
from placement_measure.campaigns import REPLAY_CONDITION, ReplayDesign
from placement_measure.engine import EngineSpec
from placement_measure.jobs import measure_job
from placement_measure.records import build_record
from placement_measure.replay import ReplayDeps, ReplaySpec, complete, prompt_ids, replay

TENANTS = tuple(EngineSpec(m, f"r{i}", 0.92, 2048, 256)
                for i, m in enumerate(("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base",
                                       "Qwen/Qwen3-4B-Instruct-2507")))


class TimedEngines:
    """`served` that sleeps `startup_s` before answering, like an engine
    loading, and counts how many engines are up at once."""

    def __init__(self, startup_s=0.05, healthy=None):
        self.startup_s, self.healthy = startup_s, healthy or {}
        self.started: list[FakeServer] = []
        self.up = 0
        self.most_up = 0
        self.lock = threading.Lock()

    @contextlib.contextmanager
    def served(self, model, *, args, env, port=8000, health_timeout=900.0):
        assert env.get("HF_HUB_OFFLINE") == "1"
        time.sleep(self.startup_s)
        server = FakeServer(model, args, port, self.healthy.get(model, True), [])
        with self.lock:
            self.started.append(server)
            self.up += 1
            self.most_up = max(self.most_up, self.up)
        try:
            yield server
        finally:
            with self.lock:
                self.up -= 1


class Completions:
    """`complete` that takes `service_s` and records which model answered."""

    def __init__(self, service_s=0.03, fail_model=None):
        self.service_s, self.fail_model = service_s, fail_model
        self.calls: list[tuple[str, int, int]] = []

    def __call__(self, base_url, model, ids, max_tokens):
        self.calls.append((model, len(ids), max_tokens))
        time.sleep(self.service_s)
        failed = model == self.fail_model
        return {"ok": not failed, "status": 500 if failed else 200,
                "completion_tokens": None if failed else max_tokens,
                "error": "boom" if failed else None}


def _deps(engines=None, completions=None):
    return ReplayDeps(
        served=(engines or TimedEngines()).served, complete=completions or Completions(),
        read_memory=lambda: {"used_mib": 500},
        wait_for_release=lambda target, timeout_s: {"released": True, "seconds": 0.0},
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [],
    )


def _spec(schedule, *, max_in_flight=8, until=None, cold=False):
    return ReplaySpec(tenants=TENANTS, schedule=tuple(schedule),
                      until=until if until is not None else schedule[-1][0] + 1.0,
                      input_len=12, output_len=4, max_in_flight=max_in_flight, cold=cold,
                      seed=7, hf_home="/vol/hf", release_tolerance_mib=512,
                      release_timeout_s=60)


def _soon(seconds=30.0):
    return time.monotonic() + seconds


def test_swaps_follow_the_simulators_rule_and_latency_counts_the_wait():
    engines, completions = TimedEngines(startup_s=0.05), Completions(service_s=0.03)
    # Tenant 1 at 0.10 forces a swap; tenant 0 at 0.11 waits through it and
    # forces the swap back once tenant 1's request has drained; tenant 2 at
    # 0.40 forces a third.
    schedule = [(0.0, 0), (0.02, 0), (0.10, 1), (0.11, 0), (0.40, 2)]
    out = replay(_spec(schedule, cold=True), deadline=_soon(),
                 deps=_deps(engines, completions))
    assert out["healthy"] and out["failure"] is None and not out["deadline_hit"]
    assert [(s["from"], s["to"]) for s in out["swaps"]] == [(0, 1), (1, 0), (0, 2)]
    assert all(s["cache"] == {"requested": True} for s in out["swaps"])
    assert all(x is not None for x in out["done"]) and all(out["ok"])
    # Request 2 waited for a whole engine start before it was even sent.
    assert out["sent"][2] - out["arrived"][2] >= engines.startup_s
    # Request 3 (tenant 0) was sent only after the swap back had completed.
    assert out["sent"][3] >= out["swaps"][1]["ready"]
    assert [m for m, _, _ in completions.calls] == [
        TENANTS[0].model, TENANTS[0].model, TENANTS[1].model, TENANTS[0].model, TENANTS[2].model]
    # One GPU: an engine is never started before the previous one stopped.
    assert engines.most_up == 1


def test_arrivals_land_on_the_schedule():
    schedule = [(0.1 * i, 0) for i in range(6)]
    out = replay(_spec(schedule), deadline=_soon(), deps=_deps())
    jitter = max(a - t for a, (t, _) in zip(out["arrived"], schedule, strict=True))
    assert 0.0 <= jitter < 0.08


def test_the_cap_queues_requests_in_the_driver():
    completions = Completions(service_s=0.03)
    out = replay(_spec([(0.0, 0), (0.0, 0), (0.0, 0)], max_in_flight=1), deadline=_soon(),
                 deps=_deps(completions=completions))
    sent = out["sent"]
    assert sent == sorted(sent) and sent[2] - sent[0] >= 2 * completions.service_s * 0.9


def test_the_deadline_stops_the_replay_and_leaves_the_rest_unfinished():
    schedule = [(0.0, 0), (0.05, 0), (5.0, 0)]
    out = replay(_spec(schedule), deadline=time.monotonic() + 0.3, deps=_deps())
    assert out["deadline_hit"] and out["sent"][2] is None and out["unsent"] == 1
    assert out["done"][0] is not None


def test_a_deadline_mid_swap_waits_for_the_swap_and_stops_its_engine():
    engines = TimedEngines(startup_s=0.3)
    out = replay(_spec([(0.0, 1)]), deadline=time.monotonic() + 0.45, deps=_deps(engines))
    assert out["deadline_hit"] and not out["engine_left_running"]
    assert len(out["swaps"]) == 1 and engines.up == 0


def test_an_incoming_engine_that_never_comes_up_ends_the_replay_as_a_failure():
    engines = TimedEngines(healthy={TENANTS[1].model: False})
    out = replay(_spec([(0.0, 0), (0.05, 1), (0.1, 0)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and "never answered /health" in out["failure"]
    assert out["done"][1] is None and engines.up == 0


def test_a_first_engine_that_never_comes_up_replays_nothing():
    engines = TimedEngines(healthy={TENANTS[0].model: False})
    out = replay(_spec([(0.0, 0)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and out["unsent"] == 1 and engines.up == 0


def test_an_errored_request_is_recorded_not_dropped():
    out = replay(_spec([(0.0, 0), (0.0, 1)]), deadline=_soon(),
                 deps=_deps(completions=Completions(fail_model=TENANTS[1].model)))
    assert out["ok"] == [True, False] and out["errors"][1] == "boom"
    assert out["done"][1] is not None


def test_prompts_are_fixed_by_the_seed_and_distinct_per_request():
    assert prompt_ids(7, 3, 16) == prompt_ids(7, 3, 16)
    assert prompt_ids(7, 3, 16) != prompt_ids(7, 4, 16)
    assert len(prompt_ids(7, 0, 1024)) == 1024


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_a_completion_must_return_exactly_the_tokens_asked_for():
    seen = {}

    def post(url, json, timeout):
        seen.update(json)
        return Resp(200, {"usage": {"completion_tokens": json["max_tokens"]}})

    assert complete("http://e", "m", [1, 2], 4, post=post)["ok"]
    assert seen["ignore_eos"] is True and seen["prompt"] == [1, 2]
    short = complete("http://e", "m", [1], 4,
                     post=lambda url, json, timeout: Resp(200, {"usage": {"completion_tokens": 2}}))
    assert not short["ok"]
    assert not complete("http://e", "m", [1], 4, post=lambda *a, **k: Resp(503, {}))["ok"]

    def broken(*a, **k):
        raise ConnectionError("refused")

    assert "refused" in complete("http://e", "m", [1], 4, post=broken)["error"]


@pytest.mark.parametrize("schedule, reason", [
    ([(0.2, 0), (0.1, 0)], "ascending"),
    ([(0.0, 3)], "tenant 3"),
    ([(5.0, 0)], "past until"),
    ([], "empty"),
])
def test_a_malformed_spec_is_refused(schedule, reason):
    with pytest.raises(ValueError, match=reason):
        ReplaySpec(tenants=TENANTS, schedule=tuple(schedule), until=1.0, input_len=1,
                   output_len=1, max_in_flight=1, cold=False, seed=0, hf_home="/h",
                   release_tolerance_mib=1, release_timeout_s=1)


def _design(**over):
    fields = {"tenants": tuple(t.model for t in TENANTS), "trace": ((0.0, 0), (0.05, 1)),
              "until": 1.0, "input_len": 12, "output_len": 4, "max_in_flight": 8, "cold": False,
              "repeats": 3, "seed": 7}
    return ReplayDesign(**{**fields, **over})


def test_every_repeat_of_a_replay_design_sends_the_same_trace():
    design = _design()
    runs = design.schedule()
    assert [r.condition for r in runs] == [REPLAY_CONDITION] * 3
    a, b = (design.payload(r, f"id{i}") for i, r in enumerate(runs[:2]))
    assert {**a, "run_id": None} == {**b, "run_id": None}
    with pytest.raises(ValueError):
        design.payload(ScheduledRun(0, 0, "swap:a>b:cold"), "x")


def test_a_replay_job_round_trips_and_its_record_reads_ok():
    design = _design()
    payload = design.payload(design.schedule()[0], "r1")
    sub = PayloadStubSubmitter(lambda p: measure_job(
        p, replay_deps=_deps(), host=lambda: {"host_id": "h", "runpod_pod_id": None}))
    outcome = sub.submit_payload(payload)
    assert outcome.error is None and outcome.payload["run_id"] == "r1"
    record = build_record(ScheduledRun(0, 0, REPLAY_CONDITION), "r1", outcome, kind="replay",
                          source="stub")
    assert record.outcome == "ok"


def test_a_replay_with_an_errored_request_or_cut_short_is_a_failed_record():
    run = ScheduledRun(0, 0, REPLAY_CONDITION)
    errored = {"healthy": True, "failure": None, "deadline_hit": False, "ok": [True, False]}
    cut = {"healthy": True, "failure": None, "deadline_hit": True, "ok": [True]}
    for output, reason in ((errored, "did not complete cleanly"), (cut, "job budget")):
        outcome = PayloadStubSubmitter(lambda p, o=output: o).submit_payload({})
        record = build_record(run, "r", outcome, kind="replay", source="stub")
        assert record.outcome == "failed" and reason in record.failure


class StopFails(TimedEngines):
    """An engine whose stop raises, as a wedged process might."""

    @contextlib.contextmanager
    def served(self, model, **kw):
        with super().served(model, **kw) as server:
            def stop():
                raise RuntimeError("stop wedged")

            server.stop = stop
            yield server


def test_a_teardown_that_raises_still_releases_the_engine():
    engines = StopFails()
    out = replay(_spec([(0.0, 0), (0.05, 1)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and "stop wedged" in out["failure"]
    assert engines.up == 0


def test_an_engine_whose_record_cannot_be_built_is_stopped(monkeypatch):
    engines = TimedEngines()

    def unreadable(*args):
        raise ValueError("unreadable log")

    monkeypatch.setattr(replay_module, "_engine_part", unreadable)
    with pytest.raises(ValueError, match="unreadable log"):
        replay(_spec([(0.0, 0)]), deadline=_soon(), deps=_deps(engines))
    assert engines.up == 0


def test_the_replay_job_reserves_time_for_a_mid_swap_wait():
    # The deadline leaves room for the wait and the teardown after it.
    assert jobs.TEARDOWN_RESERVE_S + replay_module.SWAP_WAIT_S < 1800 / 2


def test_a_cold_swap_times_its_eviction_apart_from_the_swap():
    from a4_fakes import Clock, FakeEngines, memory_script

    from placement_measure.gpu_memory import read_memory, wait_for_release
    from placement_measure.swap import SwapDeps, measure_swap

    clock = Clock()
    run = memory_script([500, 9000, 500])

    def make_cold(paths):
        clock.t += 2.5
        return {"requested": True}

    deps = SwapDeps(served=FakeEngines(clock).served, read_memory=lambda: read_memory(run=run),
                    wait_for_release=lambda t, timeout_s: wait_for_release(
                        t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
                    make_cold=make_cold, weight_files=lambda *a: [], clock=clock)
    out = measure_swap(TENANTS[0], TENANTS[1], cold=True, hf_home="/h", release_tolerance_mib=512,
                       release_timeout_s=60, deps=deps)
    assert out["cache_s"] == pytest.approx(2.5)
    assert out["swap_s"] == pytest.approx(out["teardown_s"] + out["release"]["seconds"]
                                          + out["b"]["startup_s"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_replay.py -q`

Expected: FAIL — `ImportError: cannot import name 'replay' from 'placement_measure'`

- [ ] **Step 3: Write the driver**

Create `placement_measure/replay.py`:

```python
"""Trace replay on one GPU: tenants sharing it by process-level swap, at the
trace's exact arrival times. August §9's validation gate, amendment §1e item 7.

`vllm bench serve` cannot do this. It sends a dataset at a rate, not a recorded
schedule at its timestamps, and it has no notion of a request waiting for its
model to be swapped in. So the driver is artifact 4's own.

The policy is the simulator's swap-LRU for a pool of one GPU
(`placement/sim.py`), restated here because this package may not import
`placement`:

- A request for the resident tenant is sent at once if fewer than
  `max_in_flight` are in flight, and queued first-in first-out otherwise. The
  cap is the solo curve's top measured concurrency, the simulator's capacity.
- A request for any other tenant queues. If no swap is under way, the GPU stops
  admitting the resident's requests (they queue too), drains the ones in
  flight, and swaps: teardown, memory release, eviction of the incoming
  checkpoint from the page cache when `cold`, and the incoming engine up to
  `/health`.
- When a swap completes, the incoming tenant's queue is sent up to the cap.
  Then, if another tenant is waiting, the next swap starts at once, for the
  tenant whose oldest request has waited longest -- as the simulator's
  `schedule_swaps` runs after every `swap_done`.
- With one GPU the victim is always the resident, so LRU's choice across GPUs
  is not exercised. Unit tests cover it on the simulator (amendment §7).

Latency runs from a request's arrival, as in the simulator, so time queued
behind a swap counts. Arrival is the driver's clock when it handled the
scheduled arrival; how far that lags the schedule is the send jitter
`placement.validation` bounds. Every time in the output is seconds since the
replay's start, `t0`, which is taken once the first engine is healthy.

One event loop owns all state. Requests run on a thread pool and swaps on
their own thread; both report back through one queue, so no state is shared
between threads.
"""

import contextlib
import queue
import random
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import requests

from placement_measure.engine import EngineSpec, engine_facts, log_tail
from placement_measure.swap import ENGINE_ENV, PORT

__all__ = ["ReplayDeps", "ReplaySpec", "complete", "prompt_ids", "replay"]

# Token ids drawn for a prompt: well inside every Qwen3 vocabulary, and past the
# low ids where special tokens live. Ids rather than text, so the prompt is
# exactly `input_len` tokens without a tokenizer in the driver.
PROMPT_ID_RANGE = (1000, 30000)
PROMPT_SEED_STRIDE = 1_000_003
REQUEST_TIMEOUT_S = 600.0
# A swap still running at the deadline is waited for this long, so its engine
# can be stopped: an engine left running holds the port and the memory the
# worker's next job needs. `placement_measure.jobs` reserves this much of the
# job budget on top of its teardown reserve, so the wait cannot outlast the
# platform's timeout.
SWAP_WAIT_S = 240.0


@dataclass(frozen=True)
class ReplaySpec:
    tenants: tuple[EngineSpec, ...]
    schedule: tuple[tuple[float, int], ...]  # (seconds after t0, tenant index), ascending
    until: float
    input_len: int
    output_len: int
    max_in_flight: int
    cold: bool
    seed: int
    hf_home: str
    release_tolerance_mib: float
    release_timeout_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenants", tuple(self.tenants))
        object.__setattr__(self, "schedule", tuple((float(t), int(m)) for t, m in self.schedule))
        if len(self.tenants) < 2:
            raise ValueError("a replay needs at least two tenants, or nothing is ever swapped")
        if not self.schedule:
            raise ValueError("an empty schedule replays nothing")
        previous = 0.0
        for t, m in self.schedule:
            if not (previous <= t <= self.until):
                raise ValueError(
                    f"schedule entry at {t!r} is not ascending or falls past until={self.until!r}; "
                    "the simulator would refuse to replay it"
                )
            if not 0 <= m < len(self.tenants):
                raise ValueError(f"schedule names tenant {m}, but there are {len(self.tenants)}")
            previous = t
        if type(self.max_in_flight) is not int or self.max_in_flight < 1:
            raise ValueError(f"max_in_flight must be a positive int, got {self.max_in_flight!r}")

    @classmethod
    def from_payload(cls, p: dict) -> "ReplaySpec":
        return cls(
            tenants=tuple(EngineSpec.from_dict(t) for t in p["tenants"]),
            schedule=tuple((t, m) for t, m in p["schedule"]),
            until=float(p["until"]), input_len=int(p["input_len"]),
            output_len=int(p["output_len"]), max_in_flight=int(p["max_in_flight"]),
            cold=bool(p["cold"]), seed=int(p["seed"]), hf_home=p["hf_home"],
            release_tolerance_mib=float(p["release_tolerance_mib"]),
            release_timeout_s=float(p["release_timeout_s"]),
        )


def prompt_ids(seed: int, index: int, input_len: int) -> list[int]:
    """The prompt of request `index`: fixed by the seed, so every repeat of a
    replay sends identical prompts, and distinct per request, so a prompt is
    never served from a cache of an earlier one."""
    rng = random.Random(seed * PROMPT_SEED_STRIDE + index)
    return [rng.randrange(*PROMPT_ID_RANGE) for _ in range(input_len)]


def complete(base_url: str, model: str, ids: list[int], max_tokens: int,
             *, post: Callable = requests.post) -> dict:
    """One completion of exactly `max_tokens` tokens. `ignore_eos` is vLLM's
    own request field; without it a model that stops early makes service time
    depend on which checkpoint answered (amendment §3)."""
    try:
        r = post(f"{base_url}/v1/completions",
                 json={"model": model, "prompt": ids, "max_tokens": max_tokens,
                       "ignore_eos": True, "temperature": 0.0},
                 timeout=REQUEST_TIMEOUT_S)
        tokens = None
        if r.status_code == 200:
            tokens = (r.json().get("usage") or {}).get("completion_tokens")
        ok = r.status_code == 200 and tokens == max_tokens
        return {"ok": ok, "status": r.status_code, "completion_tokens": tokens,
                "error": None if ok else r.text[:300]}
    except Exception as e:  # noqa: BLE001 -- a failed request is data; the replay must finish
        return {"ok": False, "status": None, "completion_tokens": None, "error": repr(e)[:300]}


@dataclass
class ReplayDeps:
    """The effects, injectable so tests replay without an engine or a GPU.
    None means the real one, resolved lazily so importing needs no vLLM."""

    served: Callable | None = None
    complete: Callable = complete
    read_memory: Callable | None = None
    wait_for_release: Callable | None = None
    make_cold: Callable | None = None
    weight_files: Callable | None = None
    clock: Callable[[], float] = field(default=time.monotonic)


def _resolve(d: ReplayDeps) -> ReplayDeps:
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
    return {"spec": spec.to_dict(), "healthy": bool(server.healthy), "startup_s": startup_s,
            "facts": engine_facts(lines), **log_tail(lines)}


class _Engine:
    """One running engine, entered in one thread and stopped in another."""

    def __init__(self, d: ReplayDeps, spec: EngineSpec):
        self.spec = spec
        self.stack = contextlib.ExitStack()
        self.closed = False
        try:
            t = d.clock()
            self.server = self.stack.enter_context(
                d.served(spec.model, args=spec.serve_args(), env=dict(ENGINE_ENV), port=PORT))
            self.part = _engine_part(spec, self.server, d.clock() - t)
        except BaseException:
            # An engine that started but whose record could not be built must
            # still be stopped, or it holds the GPU with nothing tracking it.
            self.stack.close()
            raise

    def stop(self) -> float:
        teardown_s = self.server.stop()
        self.close()
        return teardown_s

    def close(self) -> None:
        """Exit the engine's context once; safe after `stop` and after a failed stop."""
        if not self.closed:
            self.closed = True
            self.stack.close()


def replay(spec: ReplaySpec, *, deadline: float, deps: ReplayDeps | None = None) -> dict:
    """Replay `spec.schedule` and return every request's times and every swap.

    `deadline` is on `deps.clock`. Past it nothing new is sent or swapped,
    and requests still waiting or in flight are reported unfinished (None),
    because a job the platform kills returns nothing at all.
    """
    d = _resolve(deps or ReplayDeps())
    n = len(spec.schedule)
    arrived: list[float | None] = [None] * n
    sent: list[float | None] = [None] * n
    done: list[float | None] = [None] * n
    ok: list[bool] = [False] * n
    errors: list[str | None] = [None] * n
    swaps: list[dict] = []
    baseline = d.read_memory()
    # The schedule is echoed so the stored record is self-contained: the
    # validation checks that every repeat replayed the same trace from the
    # records alone.
    out = {"tenants": [t.to_dict() for t in spec.tenants], "until": spec.until,
           "schedule": [[t, m] for t, m in spec.schedule], "baseline_memory": baseline}

    def unreplayed(failure: str, initial=None) -> dict:
        return {**out, "initial": initial, "healthy": False, "failure": failure,
                "arrived": arrived, "sent": sent, "done": done, "ok": ok, "errors": errors,
                "swaps": swaps, "deadline_hit": False, "unsent": n}

    if baseline.get("used_mib") is None:
        return unreplayed("the idle memory reading failed, so a swap's release has no target")
    engine: _Engine | None = _Engine(d, spec.tenants[0])
    if not engine.part["healthy"]:
        engine.stop()
        return unreplayed("the first engine never answered /health", engine.part)
    out["initial"] = engine.part

    events: queue.Queue = queue.Queue()
    pool = ThreadPoolExecutor(max_workers=spec.max_in_flight)
    t0 = d.clock()

    def now() -> float:
        return d.clock() - t0

    resident = 0
    state = "serving"  # | "draining" | "swapping"
    target: int | None = None
    in_flight = 0
    waiting: dict[int, deque[int]] = {m: deque() for m in range(len(spec.tenants))}
    failure: str | None = None

    def send(i: int) -> None:
        nonlocal in_flight
        in_flight += 1
        sent[i] = now()
        base_url, model = engine.server.base_url, engine.spec.model
        ids = prompt_ids(spec.seed, i, spec.input_len)

        def work() -> None:
            result = d.complete(base_url, model, ids, spec.output_len)
            events.put(("done", i, d.clock() - t0, result))

        pool.submit(work)

    def dispatch() -> None:
        q = waiting[resident]
        while state == "serving" and q and in_flight < spec.max_in_flight:
            send(q.popleft())

    def run_swap(outgoing: int, incoming: int, previous: "_Engine") -> None:
        record = {"from": outgoing, "to": incoming, "swap_start": now()}
        try:
            record["teardown_s"] = previous.stop()
            release = d.wait_for_release(baseline["used_mib"] + spec.release_tolerance_mib,
                                         timeout_s=spec.release_timeout_s)
            record["release"] = release
            b = spec.tenants[incoming]
            record["cache"] = (d.make_cold(d.weight_files(spec.hf_home, b.model, b.revision))
                               if spec.cold else {"requested": False})
            new = _Engine(d, b)
            record["b"] = new.part
            record["ready"] = now()
            events.put(("swap_done", record, new))
        except Exception as e:  # noqa: BLE001 -- the loop must hear about it, not hang
            record["error"] = f"{type(e).__name__}: {e}"[:400]
            # If the outgoing engine's stop raised, its context is still open.
            try:
                previous.close()
            except Exception as cleanup:  # noqa: BLE001 -- reported, never raised from here
                record["cleanup_error"] = repr(cleanup)[:300]
            events.put(("swap_done", record, None))

    def start_swap() -> None:
        nonlocal state
        state = "swapping"
        threading.Thread(target=run_swap, args=(resident, target, engine), daemon=True).start()

    def schedule_swap() -> None:
        # One swap at a time on one GPU. The oldest waiter among the tenants
        # that are not resident goes first.
        nonlocal state, target
        if state != "serving":
            return
        others = [m for m, q in waiting.items() if q and m != resident]
        if not others:
            return
        target = min(others, key=lambda m: spec.schedule[waiting[m][0]][0])
        state = "draining"
        if in_flight == 0:
            start_swap()

    k = 0
    deadline_hit = False
    while True:
        if k == n and in_flight == 0 and state == "serving" and not any(waiting.values()):
            break
        if d.clock() >= deadline:
            deadline_hit = True
            break
        timeout = deadline - d.clock()
        if k < n:
            timeout = min(timeout, max(0.0, t0 + spec.schedule[k][0] - d.clock()))
        try:
            event = events.get(timeout=max(0.0, timeout))
        except queue.Empty:
            event = None
        if event is not None and event[0] == "done":
            _, i, t_done, result = event
            in_flight -= 1
            done[i], ok[i] = t_done, bool(result["ok"])
            errors[i] = result.get("error")
            if state == "draining" and in_flight == 0:
                start_swap()
            else:
                dispatch()
        elif event is not None and event[0] == "swap_done":
            _, record, new = event
            swaps.append(record)
            engine, state = new, "serving"
            if new is None or not new.part["healthy"] or not record["release"]["released"]:
                failure = record.get("error") or (
                    "the incoming engine never answered /health" if new is None
                    or not new.part["healthy"]
                    else "the outgoing engine's memory was not released within the timeout")
                break
            resident, target = record["to"], None
            dispatch()
            schedule_swap()
        while k < n and t0 + spec.schedule[k][0] <= d.clock():
            m = spec.schedule[k][1]
            arrived[k] = now()
            waiting[m].append(k)
            if m == resident:
                dispatch()
            schedule_swap()
            k += 1

    pool.shutdown(wait=False, cancel_futures=True)
    engine_left_running = False
    if state == "swapping":
        # The deadline fell mid-swap. The swap thread owns the outgoing engine
        # and will start the incoming one; wait for it, then stop that. Nothing
        # else is in flight while swapping, so the next event is the swap's.
        engine = None
        try:
            _, record, engine = events.get(timeout=SWAP_WAIT_S)
            swaps.append(record)
        except queue.Empty:
            engine_left_running = True
    if engine is not None:
        engine.stop()
    return {
        **out,
        "healthy": failure is None,
        "failure": failure,
        "arrived": arrived, "sent": sent, "done": done, "ok": ok, "errors": errors,
        "swaps": swaps,
        "deadline_hit": deadline_hit,
        "engine_left_running": engine_left_running,
        "unsent": sum(1 for s in sent if s is None),
    }
```

- [ ] **Step 4: Add the replay job kind and its campaign design**

In `placement_measure/campaigns.py`, replace:

```python
- sleep: one condition, the sleep-mode switch between two checkpoints
  (amendment §6), measured only if reconnaissance found sleep mode working.
```

with:

```python
- sleep: one condition, the sleep-mode switch between two checkpoints
  (amendment §6), measured only if reconnaissance found sleep mode working.
- replay: one condition, `replay`, repeated: the same trace replayed on one
  GPU, whose repeats' spread is the validation band (August §9).
```

In `placement_measure/campaigns.py`, replace:

```python
__all__ = ["CellDesign", "SleepDesign", "SwapDesign", "cell_condition", "parse_cell",
           "parse_sleep", "parse_swap", "sleep_condition", "swap_condition"]
```

with:

```python
__all__ = ["REPLAY_CONDITION", "CellDesign", "ReplayDesign", "SleepDesign", "SwapDesign",
           "cell_condition", "parse_cell", "parse_sleep", "parse_swap", "sleep_condition",
           "swap_condition"]

REPLAY_CONDITION = "replay"
```

In `placement_measure/campaigns.py`, replace:

```python
        a, b = parse_sleep(scheduled.condition)
        return {"kind": "sleep", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "a": engine(a, SLEEP_GMU, SLEEP_FLAGS).to_dict(),
                "b": engine(b, SLEEP_GMU, SLEEP_FLAGS).to_dict()}
```

with:

```python
        a, b = parse_sleep(scheduled.condition)
        return {"kind": "sleep", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "a": engine(a, SLEEP_GMU, SLEEP_FLAGS).to_dict(),
                "b": engine(b, SLEEP_GMU, SLEEP_FLAGS).to_dict()}


@dataclass(frozen=True)
class ReplayDesign:
    """Repeats of one trace replayed on one GPU (`placement_measure.replay`).

    Every repeat gets the identical payload apart from its run id: the same
    tenants, trace, request shape, cap and prompt seed. The band is the real
    system's spread on ONE trace, and anything that varied between repeats
    would widen it for free (artifact 2's `autoscale.validation`).
    """

    tenants: tuple[str, ...]
    trace: tuple[tuple[float, int], ...]
    until: float
    input_len: int
    output_len: int
    max_in_flight: int
    cold: bool
    repeats: int
    seed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenants", tuple(self.tenants))
        object.__setattr__(self, "trace", tuple((float(t), int(m)) for t, m in self.trace))

    def schedule(self) -> list[ScheduledRun]:
        return build_schedule([REPLAY_CONDITION], self.repeats, self.seed)

    def payload(self, scheduled: ScheduledRun, run_id: str) -> dict:
        if scheduled.condition != REPLAY_CONDITION:
            raise ValueError(f"{scheduled.condition!r} is not a replay condition")
        return {"kind": "replay", "run_id": run_id, "job_budget_s": JOB_BUDGET_S,
                "tenants": [engine(m, SOLO_GMU).to_dict() for m in self.tenants],
                "schedule": [[t, m] for t, m in self.trace], "until": self.until,
                "input_len": self.input_len, "output_len": self.output_len,
                "max_in_flight": self.max_in_flight, "cold": self.cold, "seed": self.seed,
                "hf_home": HF_HOME, "release_tolerance_mib": RELEASE_TOLERANCE_MIB,
                "release_timeout_s": RELEASE_TIMEOUT_S}
```

In `placement_measure/jobs.py`, replace:

```python
"""One measurement job, chosen by `kind`: a swap, a co-location cell, or a
sleep-mode switch.
```

with:

```python
"""One measurement job, chosen by `kind`: a swap, a co-location cell, a
sleep-mode switch, or a trace replay.
```

In `placement_measure/jobs.py`, replace:

```python
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.swap import SwapDeps, measure_swap
```

with:

```python
from placement_measure.recon import ReconDeps, run_probe
from placement_measure.replay import SWAP_WAIT_S, ReplayDeps, ReplaySpec, replay
from placement_measure.swap import SwapDeps, measure_swap
```

In `placement_measure/jobs.py`, replace:

```python
KINDS = ("swap", "cell", "sleep")
```

with:

```python
KINDS = ("swap", "cell", "sleep", "replay")
```

In `placement_measure/jobs.py`, replace:

```python
    recon_deps: ReconDeps | None = None,
```

with:

```python
    recon_deps: ReconDeps | None = None,
    replay_deps: ReplayDeps | None = None,
```

In `placement_measure/jobs.py`, replace:

```python
        out = {**sleep_switch(probe["result"]), "steps": probe["result"]}
```

with:

```python
        out = {**sleep_switch(probe["result"]), "steps": probe["result"]}
    elif kind == "replay":
        # The driver may wait SWAP_WAIT_S for a swap still running at its
        # deadline, then stop the engine; both must fit inside the budget.
        deadline = t0 + float(payload["job_budget_s"]) - TEARDOWN_RESERVE_S - SWAP_WAIT_S
        out = replay(ReplaySpec.from_payload(payload), deadline=deadline, deps=replay_deps)
```

In `placement_measure/records.py`, replace:

```python
    if kind == "sleep":
        return None if output.get("switch_s") is not None else (
            output.get("failure") or "no switch time")
```

with:

```python
    if kind == "sleep":
        return None if output.get("switch_s") is not None else (
            output.get("failure") or "no switch time")
    if kind == "replay":
        # A replay cut short by the job budget, or with a request that errored,
        # is not a repeat of the trace: an errored request has no latency, and
        # the budget is the platform's limit, not the system under test's.
        if output.get("failure"):
            return output["failure"]
        if output.get("deadline_hit"):
            return "the replay hit the job budget before every request finished"
        bad = sum(1 for ok in output.get("ok", ()) if not ok)
        return f"{bad} requests did not complete cleanly" if bad else None
```

In `placement_measure/swap.py`, replace:

```python
    cache = d.make_cold(d.weight_files(hf_home, b.model, b.revision)) if cold else {"requested": False}
    t1 = d.clock()
```

with:

```python
    # Eviction is timed apart from the swap. A fleet does not drop its page
    # cache before a swap, so `swap_s` excludes it; the replay driver does, so
    # the validation's prediction adds it back (`placement.validation`).
    tc = d.clock()
    cache = d.make_cold(d.weight_files(hf_home, b.model, b.revision)) if cold else {"requested": False}
    t1 = d.clock()
```

In `placement_measure/swap.py`, replace:

```python
        "cache": cache,
        "b": part_b,
```

with:

```python
        "cache": cache,
        "cache_s": t1 - tc,
        "b": part_b,
```

In `scripts/a4_measure.py`, replace:

```python
from placement_measure.campaigns import CellDesign, SleepDesign, SwapDesign
```

with:

```python
from placement_measure.campaigns import CellDesign, ReplayDesign, SleepDesign, SwapDesign
```

In `scripts/a4_measure.py`, replace:

```python
DESIGNS = {"swap": SwapDesign, "cell": CellDesign, "sleep": SleepDesign}
```

with:

```python
DESIGNS = {"swap": SwapDesign, "cell": CellDesign, "sleep": SleepDesign,
           "replay": ReplayDesign}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_measure_replay.py tests/test_placement_measure_jobs.py tests/test_placement_measure_swap.py tests/test_placement_measure_boundary.py -q`

Expected: PASS — 21 replay tests in about 3 seconds, and plan 2's swap and job tests unchanged

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check placement_measure/replay.py placement_measure/swap.py placement_measure/campaigns.py placement_measure/jobs.py placement_measure/records.py scripts/a4_measure.py tests/test_placement_measure_replay.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement_measure/replay.py placement_measure/swap.py placement_measure/campaigns.py placement_measure/jobs.py placement_measure/records.py scripts/a4_measure.py tests/test_placement_measure_replay.py
git commit -m "measure: replay a trace on one GPU with real swaps, by the simulator's swap rule"
```

---

## Task 5: Pre-registration step 2, part 1: the rules

**Files:**
- Create: `placement/step2.py`
- Modify: `docs/experiment-a4.md`
- Create: `tests/a4_examples.py`
- Test: `tests/test_placement_step2.py`
- Test: `tests/test_placement_step2_doc.py`

Amendment §3 commits step 2 "before the first measurement run". This task goes further: it fixes the **rules** that turn reconnaissance's answers into values, before those answers are read. Once reconnaissance reports, every value follows mechanically, and none is chosen by someone who has seen the data. The rules cover:
- the request shape;
- the grids;
- the held-out cells;
- the validation set;
- the swap campaign;
- the cold-swap rule;
- the sleep arm;
- the simulated design;
- the screen's candidates;
- the validation gate.

**A rule whose input reconnaissance did not answer raises `NotDecidable`.** That is a stop for the owner, never a default.

**Two thresholds are stated relative to later measurements:**
- **the SLO,** a multiple of the simulated swap's median, which the screen chooses in Task 6;
- **the validation trace's load,** a fraction of the measured solo saturation.

**Commit this before `docs/recon-a4.md` exists, if you can.** The commit's timestamp is then the evidence that the rules predate reconnaissance's answers. If reconnaissance has already run, the rules still predate the first measurement, which is what amendment §12 requires; say which in the commit message.

The document and the code are tied by a test, as plan 2's step 1 is.

- [ ] **Step 1: Create the example reconnaissance reports the tests share**

Create `tests/a4_examples.py`:

```python
"""Example reconnaissance reports for plan 3's tests, in the shape
`placement_measure.recon_report.report` returns.

Not a test module. The numbers are invented but plausible: a 4B split engine
logging about 18k tokens of KV, a solo one about 88k, swaps of 30-45 s.
"""

import copy

PRIMARY, BASE = "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"
INSTRUCT, THINKING = "Qwen/Qwen3-4B-Instruct-2507", "Qwen/Qwen3-4B-Thinking-2507"
FALLBACK = "Qwen/Qwen3-1.7B"


def _go(passed, kv):
    return {"answered": True, "passed": passed, "healthy": [True, True],
            "kv_capacity_tokens": list(kv), "required_tokens": 16384}


REPORT = {
    "help": {"serve": {"returncode": 0, "missing": []}, "bench": {"returncode": 0, "missing": []}},
    "staged": {"all_staged": True},
    "go_no_go": {"primary": _go(True, (18_432, 18_100)), "fallback": _go(True, (52_000, 52_000))},
    "compile_reuse": [
        {"a": PRIMARY, "b": BASE, "b_s4b_s": 0.31, "b_compiled": False, "swap_s": 33.0},
        {"a": BASE, "b": INSTRUCT, "b_s4b_s": 0.33, "b_compiled": False, "swap_s": 31.5},
        {"a": INSTRUCT, "b": THINKING, "b_s4b_s": 0.30, "b_compiled": False, "swap_s": 32.2},
        {"a": THINKING, "b": PRIMARY, "b_s4b_s": 0.29, "b_compiled": False, "swap_s": 30.8},
    ],
    "cache_eviction": [
        {"cold": False, "b": BASE, "b_compiled": False, "swap_s": 31.0},
        {"cold": True, "b": PRIMARY, "b_compiled": False, "swap_s": 44.0,
         "methods_ok": {"drop_caches": False, "fadvise": True}, "cached_kib_drop": 7_600_000},
        {"cold": True, "b": BASE, "b_compiled": False, "swap_s": 45.5,
         "methods_ok": {"drop_caches": False, "fadvise": True}, "cached_kib_drop": 7_500_000},
        {"cold": False, "b": PRIMARY, "b_compiled": False, "swap_s": 30.5},
    ],
    "release": {"n": 8, "median_s": 0.9, "max_s": 2.1, "never_released": 0},
    "kv_solo": [
        {"model": PRIMARY, "kv_capacity_tokens": 86_000, "s4b_s": 19.2, "compiled": True},
        {"model": BASE, "kv_capacity_tokens": 88_100, "s4b_s": 0.31, "compiled": False},
        {"model": PRIMARY, "kv_capacity_tokens": 88_300, "s4b_s": 0.29, "compiled": False},
    ],
    "early_start": {"answered": True, "b_healthy": True, "memory_when_b_started_mib": 600},
    "sleep_mode": {"answered": True, "works": True, "sleep_s": 2.1, "wake_s": 3.4,
                   "memory_sleeping_mib": 1400, "statuses": {}},
}


def example_report(**changes) -> dict:
    """A deep copy of REPORT with top-level keys replaced."""
    report = copy.deepcopy(REPORT)
    report.update(copy.deepcopy(changes))
    return report
```

- [ ] **Step 2: Write the failing rule tests**

Create `tests/test_placement_step2.py`:

```python
"""Pre-registration step 2's rules, applied to example reconnaissance reports.

Each rule is checked on the answer it turns on, both ways, and every
unanswered input is a stop rather than a default.
"""

import random

import pytest
from a4_examples import BASE, FALLBACK, INSTRUCT, PRIMARY, example_report

from autoscale.service import ServiceCurve
from autoscale.traffic import saturation_rps
from placement import step2
from placement.step2 import (
    NotDecidable,
    SweepChoice,
    measurement_design,
    provisional_swap_samples,
    request_shape,
    sweep_design,
    validation_design,
)
from placement.traffic import bursty_trace, zipf_shares


def test_the_request_shape_is_the_shortest_at_which_the_split_kv_binds():
    # 18,100 // 512 = 35 > 32; // 1024 = 17 <= 32.
    assert request_shape(18_100) == {"input_len": 768, "output_len": 256, "split_ceiling": 17}
    # At the go/no-go floor, 16,384 // 512 = 32: the shortest candidate already binds.
    assert request_shape(16_384)["input_len"] == 256
    # A larger cache needs a longer request, up to T_max.
    assert request_shape(60_000) == {"input_len": 1792, "output_len": 256, "split_ceiling": 29}
    assert request_shape(200_000)["input_len"] + 256 == 2048


def test_a_cache_too_large_to_bind_below_max_num_seqs_stops():
    with pytest.raises(NotDecidable, match="cannot bind"):
        request_shape(2048 * 256)


def test_grids_run_past_their_kv_ceiling():
    assert step2.power_levels(17) == (1, 2, 4, 8, 16, 32)
    assert step2.power_levels(86) == (1, 2, 4, 8, 16, 32, 64, 128, 256)
    assert step2.power_levels(None)[-1] == 256


def test_the_primary_class_measures_everything_reconnaissance_allowed():
    m = measurement_design(example_report())
    assert m["model"] == PRIMARY and m["shape"]["input_len"] == 768
    assert m["own_levels"] == (1, 2, 4, 8, 16, 32) and m["neighbour_levels"] == (0, 8, 16, 32)
    # The solo ceiling is the measured model's own warm reading: the compiling
    # 86,000 and the -Base 88,100 are not it. 88,300 // 1024 = 86.
    assert m["kv_solo_tokens"] == 88_300 and m["solo_ceiling"] == 86
    assert m["held_out"] == ("pair:o12:n24", "pair:o24:n12")
    assert m["validation_set"] == (PRIMARY, BASE, INSTRUCT)
    assert m["simulated_swap"] == {"cold": True, "compiled": False}
    cells = m["cells"]
    conditions = cells.conditions()
    assert "pair:o32:n32" in conditions and "solo:o256" in conditions
    assert set(m["held_out"]) <= set(conditions)
    assert cells.neighbour_model == BASE and cells.repeats == step2.CELL_REPEATS
    swaps = m["swaps"]
    assert len(swaps.pairs) == 6 and swaps.cold_states == (True, False) and swaps.repeats == 3
    assert m["sleep"] is not None and m["sleep_simulated"] is False


def test_a_failed_primary_falls_back_with_three_tenants_of_one_checkpoint():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    m = measurement_design(report)
    assert m["model"] == FALLBACK and m["validation_set"] == (FALLBACK,) * 3
    assert m["swaps"].pairs == ((FALLBACK, FALLBACK),) and m["swaps"].repeats == 16
    # Reconnaissance has no solo 1.7B reading, so the solo grid spans everything.
    assert m["solo_ceiling"] is None and m["solo_levels"][-1] == 256
    assert m["cells"].neighbour_model == FALLBACK


def test_both_classes_failing_or_an_unanswered_go_no_go_stops():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    report["go_no_go"]["fallback"]["passed"] = False
    with pytest.raises(NotDecidable, match="design changes"):
        measurement_design(report)
    report["go_no_go"]["primary"] = {"answered": False, "passed": None}
    with pytest.raises(NotDecidable, match="did not answer"):
        measurement_design(report)


def test_a_compile_miss_on_any_swap_in_makes_the_validation_set_one_checkpoint():
    report = example_report()
    report["compile_reuse"][1]["b_compiled"] = True
    m = measurement_design(report)
    assert m["compile_shared"] is False and m["validation_set"] == (PRIMARY,) * 3


def test_eviction_that_did_not_empty_the_cache_leaves_only_warm_swaps():
    report = example_report()
    report["cache_eviction"][1]["cached_kib_drop"] = 100_000
    m = measurement_design(report)
    assert m["eviction_works"] is False and m["swaps"].cold_states == (False,)
    assert m["simulated_swap"]["cold"] is False


def test_unanswered_compile_or_eviction_questions_stop():
    report = example_report()
    report["compile_reuse"][0]["b_compiled"] = None
    with pytest.raises(NotDecidable, match="compile state"):
        measurement_design(report)
    with pytest.raises(NotDecidable, match="cold swap"):
        measurement_design(example_report(cache_eviction=[]))


def test_sleep_mode_that_does_not_work_is_not_measured():
    m = measurement_design(example_report(sleep_mode={"answered": True, "works": False}))
    assert m["sleep"] is None


def test_the_provisional_swaps_are_reconnaissances_own_in_the_simulated_state():
    report = example_report()
    m = measurement_design(report)
    assert provisional_swap_samples(report, m) == (44.0, 45.5)
    report["cache_eviction"][1]["cached_kib_drop"] = 0
    warm = provisional_swap_samples(report, measurement_design(report))
    assert warm == (31.0, 30.5, 33.0, 31.5, 32.2, 30.8)


def test_the_sweep_design_sets_the_slo_from_the_swap_median():
    design = sweep_design(SweepChoice(offered_gpus=2.0, slo_swap_multiple=4.0), 40.0)
    assert design.slo_seconds == 160.0 and design.offered_gpus == 2.0
    assert design.skews == step2.SKEWS and design.preregistered
    assert design.n_models == 20 and design.duty == 0.2
    with pytest.raises(ValueError):
        sweep_design(SweepChoice(2.0, 4.0), 0.0)


def test_the_validation_trace_is_one_draw_from_a_registered_seed():
    """One draw, not its expectation: over 900 s a bursty model has only a few
    ON periods, so the realised load can sit well below the target. The real
    repeats and the simulator replay the same draw, so that is no bias."""
    m = measurement_design(example_report())
    curve = ServiceCurve(points=[(1, 4.0, 60.0, 0.3), (16, 6.0, 600.0, 0.9),
                                 (32, 9.0, 800.0, 1.0)], measured=True)
    seed = step2.VALIDATION_SEEDS[1]
    design = validation_design(m, curve, seed)
    assert design == validation_design(m, curve, seed) and design.tenants == m["validation_set"]
    assert design.max_in_flight == 32 and design.cold is True and design.seed == seed
    expected = bursty_trace(zipf_shares(3, step2.VALIDATION_S),
                            step2.VALIDATION_LOAD * saturation_rps(curve),
                            step2.VALIDATION_WINDOW_S, step2.VALIDATION_MEAN_BURST_S,
                            step2.VALIDATION_DUTY, random.Random(seed))
    assert list(design.trace) == expected
    with pytest.raises(ValueError, match="pre-registered"):
        validation_design(m, curve, 17)
```

- [ ] **Step 3: Write the failing document test**

Create `tests/test_placement_step2_doc.py`:

```python
"""The pre-registration's step 2 rules and the code that applies them must agree."""

from pathlib import Path

from placement import step2

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a4.md").read_text()
PART = DOC[DOC.index("## Step 2, part 1"):]


def _fmt(x) -> str:
    return f"`{x}`"


def test_the_section_exists_after_step_1():
    assert DOC.index("## Step 1") < DOC.index("## Step 2, part 1")


def test_the_request_shape_rule_is_stated():
    assert _fmt(step2.OUTPUT_LEN) in PART and _fmt(step2.SPLIT_CEILING_TARGET) in PART
    assert ", ".join(_fmt(n) for n in step2.TOTAL_LEN_CANDIDATES) in PART
    assert _fmt(step2.LEVEL_HEADROOM) in PART


def test_the_campaign_rules_are_stated():
    for value in (step2.CELL_REPEATS, step2.CELL_MIN_VALID, step2.SWAPS_PER_STATE,
                  step2.SLEEP_REPEATS, step2.EVICTION_MIN_FRACTION):
        assert _fmt(value) in PART, value
    for model in (step2.BASE, step2.INSTRUCT):
        assert _fmt(model) in PART


def test_the_simulated_design_is_stated():
    for value in (step2.N_MODELS, step2.HOT_FRACTION, int(step2.WARMUP_S), int(step2.MEAN_BURST_S),
                  step2.DUTY, step2.REPETITIONS, step2.PILOT_TRACES, step2.SWEEP_SEED,
                  step2.SCREEN_REPETITIONS, step2.SCREEN_SEED):
        assert _fmt(value) in PART, value
    assert ", ".join(str(s) for s in step2.SKEWS) in PART
    for value in step2.SCREEN_OFFERED_GPUS + step2.SCREEN_SLO_SWAP_MULTIPLES:
        assert _fmt(value) in PART, value
    assert f"s = {_fmt(step2.REFERENCE['s'])}" in PART and step2.REFERENCE["regime"] in PART


def test_the_validation_gate_is_stated():
    seeds = step2.VALIDATION_SEEDS
    assert seeds == tuple(range(seeds[0], seeds[-1] + 1))
    assert f"seeds {_fmt(seeds[0])} to {_fmt(seeds[-1])}" in PART
    for value in (step2.VALIDATION_S, step2.VALIDATION_LOAD, step2.VALIDATION_DUTY,
                  int(step2.VALIDATION_DRAIN_LIMIT_S), int(step2.VALIDATION_WINDOW_S),
                  step2.VALIDATION_MIN_SWAPS,
                  int(step2.VALIDATION_MEAN_BURST_S), step2.VALIDATION_REPEATS,
                  int(step2.VALIDATION_BIN_S), step2.MAX_SEND_JITTER_S, step2.MIN_COMPARED_BINS,
                  step2.MAX_MISS_FRACTION, step2.EDGE_TOLERANCE_S, step2.SWAP_COUNT_SLACK,
                  step2.HELD_OUT_TOLERANCE):
        assert _fmt(value) in PART, value


def test_the_section_14_decision_is_recorded():
    assert "Decided 2026-10-04" in PART and "ON-period load" in PART
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_step2.py tests/test_placement_step2_doc.py -q`

Expected: FAIL — an `ImportError` for `placement.step2`

- [ ] **Step 5: Write the rules**

Create `placement/step2.py`:

```python
"""Pre-registration step 2, as rules: how reconnaissance's answers become the
measurement design, the simulated design and the validation gate.

Amendment §3 commits the pre-registration in two steps, the second "before the
first measurement run", because the request shape depends on what
reconnaissance reports. This module goes one further. It fixes the RULES
before reconnaissance's answers are read, so that once they are, every value
follows mechanically, and none was chosen by someone who had seen the data
(`docs/experiment-a4.md`, "Step 2"). The values themselves are written to
`placement/registered.py` by `scripts/a4_step2.py`, before the first
measurement run.

A rule that needs an answer reconnaissance did not give raises
`NotDecidable`. That is a stop for the owner, never a default: a guessed
input here would be pre-registered as if it had been measured.

Two thresholds are relative to measurements made later, and are stated as
multiples so they need no value now: the SLO is a multiple of the simulated
swap's median, chosen by the ranking-blind screen (`placement.screen`), and
the validation trace's load is a fraction of the measured solo saturation.
"""

import math
import random
from dataclasses import dataclass

from autoscale.service import ServiceCurve
from autoscale.traffic import saturation_rps
from placement.design import Design
from placement.traffic import bursty_trace, zipf_shares
from placement_measure.campaigns import CellDesign, ReplayDesign, SleepDesign, SwapDesign
from placement_measure.prereg import FALLBACK, MAX_NUM_SEQS, PRIMARY, T_MAX

__all__ = [
    "NotDecidable", "SweepChoice", "measurement_design", "provisional_swap_samples",
    "request_shape", "sweep_design", "validation_design",
]

BASE = "Qwen/Qwen3-4B-Base"
INSTRUCT = "Qwen/Qwen3-4B-Instruct-2507"
# The co-located grid's neighbour. The fallback class has one checkpoint, so
# its two co-resident engines are two copies of it, as in reconnaissance.
NEIGHBOUR = {PRIMARY: BASE, FALLBACK: FALLBACK}
# bf16 weights, amendment §3's table.
WEIGHTS_GIB = {PRIMARY: 7.49, FALLBACK: 3.78}

# --- The request shape (amendment §4) ---
# Fixed output, so service time does not depend on where a checkpoint would
# have stopped (`ignore_eos`, amendment §3).
OUTPUT_LEN = 256
# Total tokens per request, tried shortest first; the last is T_max.
TOTAL_LEN_CANDIDATES = (512, 1024, 1536, 2048)
# The shortest request at which the split engine's KV holds at most this many
# requests at once. That puts the KV ceiling inside a measured grid of a
# handful of points, where its bend can be seen, and well below max_num_seqs.
SPLIT_CEILING_TARGET = 32
# Each grid runs past its KV ceiling by this factor, so the bend is measured
# rather than extrapolated.
LEVEL_HEADROOM = 1.5

# --- The measurement campaigns ---
CELL_REPEATS = 4
# A cell needs this many valid repeats: a run whose measured engine compiled is
# not valid, because compile state moves KV capacity (amendment §5), and the
# first engine on a fresh worker compiles. The fourth repeat absorbs that.
CELL_MIN_VALID = 3
SWAPS_PER_STATE = 16
SLEEP_REPEATS = 8
# Page-cache eviction "works" if every cold swap in reconnaissance had a method
# succeed and the kernel's Cached figure fell by at least this fraction of one
# 4B checkpoint's weights (reconnaissance's cold swaps were 4B).
EVICTION_MIN_FRACTION = 0.5
CELLS_SEED, SWAPS_SEED, SLEEP_SEED = 4101, 4102, 4103

# --- The simulated design (amendment §7, §8, §12) ---
N_MODELS = 20
SKEWS = (0.6, 0.8, 1.0, 1.25, 1.5, 2.0)
REGIMES = ("spread", "bursty")
HOT_FRACTION = 0.7
WARMUP_S = 300.0
MEAN_BURST_S = 120.0
DUTY = 0.2
REPETITIONS = 30
PILOT_TRACES = 1200
SWEEP_SEED = 20261004
# Artifact 5's cost table reads this grid point (amendment §11).
REFERENCE = {"regime": "bursty", "s": 1.0}

# --- The ranking-blind screen (`placement.screen`) ---
# Candidates in preference order; a tie in the screen's score goes to the
# earlier one: offered load first, then the tighter SLO, the one closer to a
# serving target. Offered load is in units of one GPU's saturation, the SLO in
# multiples of the simulated swap's median.
SCREEN_OFFERED_GPUS = (4.0, 2.0, 1.0)
SCREEN_SLO_SWAP_MULTIPLES = (1.0, 2.0, 4.0)
SCREEN_REPETITIONS = 5
SCREEN_SEED = 20261005

# --- The validation gate (August §9) ---
VALIDATION_S = 1.0
VALIDATION_LOAD = 0.3  # of the measured solo saturation
VALIDATION_WINDOW_S = 900.0
VALIDATION_MEAN_BURST_S = 180.0
VALIDATION_DUTY = 0.25
# Draws tried in order; the first whose predicted replay is feasible is used
# (`placement.validation.validation_trace`). One GPU swapping among three
# bursty tenants ping-pongs whenever two are ON at once, so a single draw can
# swap once or a hundred times; a trace whose backlog outlasts the job, or
# that hardly swaps, validates nothing. Chosen on 2026-10-04 by simulating
# draws: with a 4B-like curve and 25-60 s swaps, these parameters gave a
# feasible draw within the first two seeds in every case tried, where a
# 120 s burst at duty 1/3 or a higher load often gave none.
VALIDATION_SEEDS = tuple(range(4104, 4124))
VALIDATION_MIN_SWAPS = 4
VALIDATION_REPEATS = 3
# 30 s, not artifact 2's 10 s: at this load a 10 s bin can hold fewer requests
# than the p50's 20-sample floor, and every bin would be thin.
VALIDATION_BIN_S = 30.0
# Feasible means the predicted last completion is at most this many seconds
# after the replay starts: the job's 1800 s, less its 120 s teardown reserve,
# the driver's 240 s wait for a swap in progress, and 240 s for the first
# engine's start before the replay's clock begins.
VALIDATION_DRAIN_LIMIT_S = 1200.0
MAX_SEND_JITTER_S = 0.5
MIN_COMPARED_BINS = 10
MAX_MISS_FRACTION = 0.5
EDGE_TOLERANCE_S = 0.001
# The predicted swap count must lie within the real repeats' range, widened by
# this many swaps either side.
SWAP_COUNT_SLACK = 1
# The interference check: a held-out cell passes if the surface's prediction
# is inside its repeats' range, or within this fraction of their median.
HELD_OUT_TOLERANCE = 0.10

assert TOTAL_LEN_CANDIDATES[-1] == T_MAX


class NotDecidable(ValueError):
    """Reconnaissance did not answer something a rule needs. Stop: the owner
    decides, and the decision is recorded as an amendment."""


def _answered(entry: dict, what: str) -> dict:
    if not entry.get("answered"):
        raise NotDecidable(f"reconnaissance did not answer {what}; no rule may guess it")
    return entry


def model_class(report: dict) -> str:
    g = report["go_no_go"]
    if _answered(g["primary"], "the primary go/no-go")["passed"]:
        return PRIMARY
    if _answered(g["fallback"], "the fallback go/no-go")["passed"]:
        return FALLBACK
    raise NotDecidable("both model classes failed the go/no-go: the design changes, not the "
                       "measurement (amendment §3)")


def kv_split(report: dict, model: str) -> int:
    key = "primary" if model == PRIMARY else "fallback"
    return min(report["go_no_go"][key]["kv_capacity_tokens"])


def kv_solo(report: dict, model: str) -> int | None:
    """The smallest warm-compile solo reading for `model`, or None when
    reconnaissance has none: its swaps ran only the 4B checkpoints."""
    readings = [r["kv_capacity_tokens"] for r in report["kv_solo"]
                if r["model"] == model and r["compiled"] is False
                and r["kv_capacity_tokens"] is not None]
    return min(readings) if readings else None


def request_shape(kv_split_tokens: int) -> dict:
    for total in TOTAL_LEN_CANDIDATES:
        if kv_split_tokens // total <= SPLIT_CEILING_TARGET:
            break
    ceiling = kv_split_tokens // total
    if ceiling >= MAX_NUM_SEQS:
        raise NotDecidable(
            f"at T_max the split engine still holds {ceiling} requests, at or above "
            f"max_num_seqs {MAX_NUM_SEQS}: KV cannot bind, and amendment §4 cannot be met"
        )
    return {"input_len": total - OUTPUT_LEN, "output_len": OUTPUT_LEN, "split_ceiling": ceiling}


def power_levels(ceiling: int | None) -> tuple[int, ...]:
    """1, 2, 4, ... up to the first level at least `LEVEL_HEADROOM` times the
    ceiling, capped at max_num_seqs. No ceiling means the full range."""
    top = MAX_NUM_SEQS if ceiling is None else min(MAX_NUM_SEQS, LEVEL_HEADROOM * ceiling)
    levels = [1]
    while levels[-1] < top:
        levels.append(levels[-1] * 2)
    return tuple(min(level, MAX_NUM_SEQS) for level in levels)


def held_out_cells(own: tuple[int, ...], neighbour: tuple[int, ...]) -> tuple[str, ...]:
    """Two cells between grid points, never measured into the surface, that
    the surface must predict (August §9's second check)."""
    if len(own) < 4 or len(neighbour) < 3:
        raise NotDecidable(f"the grid {own} x {neighbour} is too small to hold cells out of")
    cells = ((own[-3] * 3 // 2, neighbour[2] * 3 // 2), (own[-2] * 3 // 2, neighbour[1] * 3 // 2))
    return tuple(f"pair:o{o}:n{n}" for o, n in cells)


def compile_shared(report: dict) -> bool:
    rows = report["compile_reuse"]
    if not rows or any(r["b_compiled"] is None for r in rows):
        raise NotDecidable("reconnaissance did not read every swap-in's compile state")
    return not any(r["b_compiled"] for r in rows)


def eviction_works(report: dict) -> bool:
    cold = [r for r in report["cache_eviction"] if r["cold"]]
    if not cold:
        raise NotDecidable("reconnaissance ran no cold swap, so eviction is unanswered")
    need = EVICTION_MIN_FRACTION * WEIGHTS_GIB[PRIMARY] * 1024 * 1024
    return all(any(r["methods_ok"].values()) and r["cached_kib_drop"] is not None
               and r["cached_kib_drop"] >= need for r in cold)


def sleep_works(report: dict) -> bool:
    s = report["sleep_mode"]
    return bool(s.get("answered") and s.get("works"))


def validation_set(model: str, shared: bool) -> tuple[str, str, str]:
    """Three distinct checkpoints if every swap-in reused the compile cache, so
    swap cost does not depend on the target; otherwise three tenants of one
    checkpoint, which are config-matched by construction (amendment §3)."""
    if model == PRIMARY and shared:
        return (PRIMARY, BASE, INSTRUCT)
    return (model, model, model)


def swap_pairs(vset: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    distinct = list(dict.fromkeys(vset))
    if len(distinct) == 1:
        return ((distinct[0], distinct[0]),)
    return tuple((a, b) for a in distinct for b in distinct if a != b)


def measurement_design(report: dict) -> dict:
    """Everything reconnaissance decides, from its report alone."""
    model = model_class(report)
    shape = request_shape(kv_split(report, model))
    total = shape["input_len"] + shape["output_len"]
    solo = kv_solo(report, model)
    solo_ceiling = None if solo is None else solo // total
    own = power_levels(shape["split_ceiling"])
    neighbour = (0, *own[-3:])
    shared, cold_works, sleepy = compile_shared(report), eviction_works(report), sleep_works(report)
    vset = validation_set(model, shared)
    pairs = swap_pairs(vset)
    cells = CellDesign(
        measured_model=model, neighbour_model=NEIGHBOUR[model], own_levels=own,
        neighbour_levels=neighbour, solo=False, input_len=shape["input_len"],
        output_len=shape["output_len"], repeats=CELL_REPEATS, seed=CELLS_SEED,
        extra_cells=tuple(f"solo:o{c}" for c in power_levels(solo_ceiling))
        + held_out_cells(own, neighbour),
    )
    swaps = SwapDesign(pairs=pairs, cold_states=(True, False) if cold_works else (False,),
                       repeats=math.ceil(SWAPS_PER_STATE / len(pairs)), seed=SWAPS_SEED)
    sleep = SleepDesign(a=model, b=NEIGHBOUR[model], repeats=SLEEP_REPEATS,
                        seed=SLEEP_SEED) if sleepy else None
    return {
        "model": model, "shape": shape, "kv_split_tokens": kv_split(report, model),
        "kv_solo_tokens": solo, "solo_ceiling": solo_ceiling,
        "own_levels": own, "neighbour_levels": neighbour,
        "solo_levels": power_levels(solo_ceiling), "held_out": held_out_cells(own, neighbour),
        "compile_shared": shared, "eviction_works": cold_works, "sleep_works": sleepy,
        # The simulator draws swaps from the cold distribution if eviction
        # works, else the warm one, and only swap-ins that reused the compile
        # cache: a fleet's steady state, in which a model has been served on
        # the host before (amendment §5).
        "simulated_swap": {"cold": cold_works, "compiled": False},
        # Sleep mode is measured and reported beside the crossover, never
        # simulated: the simulator would need the host RAM a sleeping model
        # takes, which reconnaissance does not measure (amendment §6).
        "sleep_simulated": False,
        "validation_set": vset, "cells": cells, "swaps": swaps, "sleep": sleep,
    }


def provisional_swap_samples(report: dict, measurement: dict) -> tuple[float, ...]:
    """Reconnaissance's own swap times in the simulated state: the only swap
    measurements that exist when the screen runs, before the swap campaign.

    Cold swaps if eviction works, warm ones otherwise; compile-cache hits only.
    The warm ones include the compile probe's swaps, all of which were warm.
    """
    cold = measurement["simulated_swap"]["cold"]
    rows = [r for r in report["cache_eviction"] if r["cold"] == cold]
    if not cold:
        rows += report["compile_reuse"]
    samples = tuple(r["swap_s"] for r in rows
                    if r["swap_s"] is not None and r["b_compiled"] is False)
    if not samples:
        raise NotDecidable(f"reconnaissance has no {'cold' if cold else 'warm'} swap with a "
                           "compile-cache hit, so the screen has no swap time to draw")
    return samples


@dataclass(frozen=True)
class SweepChoice:
    """The screen's pick: offered load, and the SLO as a swap multiple."""

    offered_gpus: float
    slo_swap_multiple: float


def sweep_design(choice: SweepChoice, swap_median_s: float, *, repetitions: int = REPETITIONS,
                 seed: int = SWEEP_SEED, preregistered: bool = True) -> Design:
    if not math.isfinite(swap_median_s) or swap_median_s <= 0:
        raise ValueError(f"swap_median_s must be finite and positive, got {swap_median_s!r}")
    return Design(
        n_models=N_MODELS, offered_gpus=choice.offered_gpus, hot_fraction=HOT_FRACTION,
        warmup=WARMUP_S, mean_burst=MEAN_BURST_S, duty=DUTY, skews=SKEWS, regimes=REGIMES,
        repetitions=repetitions, slo_seconds=choice.slo_swap_multiple * swap_median_s,
        pilot_traces=PILOT_TRACES, seed=seed, preregistered=preregistered,
    )


def validation_design(measurement: dict, solo_curve: ServiceCurve, seed: int) -> ReplayDesign:
    """The replayed trace: three tenants at Zipf s = VALIDATION_S, bursty, at
    VALIDATION_LOAD of the measured solo saturation, drawn once from `seed`.
    Every repeat replays this one draw. Which of VALIDATION_SEEDS is used is
    decided by `placement.validation.validation_trace`."""
    if seed not in VALIDATION_SEEDS:
        raise ValueError(f"seed {seed!r} is not one of the pre-registered validation seeds")
    shares = zipf_shares(len(measurement["validation_set"]), VALIDATION_S)
    rate = VALIDATION_LOAD * saturation_rps(solo_curve)
    trace = bursty_trace(shares, rate, VALIDATION_WINDOW_S, VALIDATION_MEAN_BURST_S,
                         VALIDATION_DUTY, random.Random(seed))
    shape = measurement["shape"]
    return ReplayDesign(
        tenants=measurement["validation_set"], trace=tuple(trace), until=VALIDATION_WINDOW_S,
        input_len=shape["input_len"], output_len=shape["output_len"],
        max_in_flight=int(solo_curve.max_measured_concurrency),
        cold=measurement["eviction_works"], repeats=VALIDATION_REPEATS, seed=seed,
    )
```

- [ ] **Step 6: State the rules in the pre-registration**

In `docs/experiment-a4.md`, replace:

````markdown
### What step 2 fixes, after reconnaissance

The request shape (input and output length, at or below T_max), the
validation checkpoint set, N, the Zipf grid, both locality regimes'
parameters, the offered load, the SLO, the hot-model threshold, the sizing and
pairing rules, the warm-up window, the repetition count, the run-length pilot
rule, the interference grid, the swap campaign's pairs and cache states, and
the validation tolerance construction (scope amendment §12). It also records
the owner's decision on the bursty-regime sizing gap (scope amendment §14).
````

with:

````markdown
### What step 2 fixes, after reconnaissance

The request shape (input and output length, at or below T_max), the
validation checkpoint set, N, the Zipf grid, both locality regimes'
parameters, the offered load, the SLO, the hot-model threshold, the sizing and
pairing rules, the warm-up window, the repetition count, the run-length pilot
rule, the interference grid, the swap campaign's pairs and cache states, and
the validation tolerance construction (scope amendment §12). It also records
the owner's decision on the bursty-regime sizing gap (scope amendment §14).
Step 2 is itself committed in two parts, below: its rules, then its values.

## Step 2, part 1 — rules, fixed before reconnaissance's answers are read

Every value step 2 needs is fixed here as a rule, so that once reconnaissance
reports, the values follow mechanically. `placement/step2.py` holds these rules
as code, and `tests/test_placement_step2_doc.py` fails if it and this section
disagree. A rule whose input reconnaissance did not answer stops the
experiment for the owner's decision; nothing defaults.

### The owner's decision on scope amendment §14

Decided 2026-10-04: in the bursty regime, the hot-model rule and dedicate's
fleet size are set on each model's ON-period load, its average divided by the
duty (`peak_factor` 1 / duty). In the spread regime they use the average. It
remains one rule, applied identically to all three strategies.

### Model class and request shape

- **Model class:** the primary if its go/no-go passed; otherwise the fallback
  if its go/no-go passed; otherwise stop.
- **Output length:** fixed at `256` tokens per request, with `ignore_eos`.
- **Total length:** the shortest of `512`, `1024`, `1536`, `2048` tokens at
  which the split engine's logged KV capacity, divided by the total, is at most
  `32` requests. Input length is the total minus the output length. If even
  T_max leaves 256 or more requests, the KV split cannot bind and the
  experiment stops (scope amendment §4).
- **KV readings used:** the split capacity is the smaller of the two
  co-resident engines'. The solo capacity is the smallest reading of the
  measured checkpoint at full memory with a compile-cache hit; with none, the
  solo grid spans the full range.

### The measurement campaigns

- **Grids:** concurrency levels 1, 2, 4, ... up to the first at least `1.5`
  times the KV ceiling (capacity divided by total length), capped at 256. The
  co-located grid uses the split ceiling for its own levels, and its neighbour
  levels are 0 (idle) and the top three own levels. The solo grid uses the solo
  ceiling.
- **Neighbour checkpoint:** `Qwen/Qwen3-4B-Base` for the 4B class; a second
  engine of `Qwen/Qwen3-1.7B` for the fallback.
- **Held-out cells:** two cells between grid points, never used to build the
  surface, each value rounded down: own 1.5 times the third-from-top own level with neighbour 1.5 times
  the third neighbour level, and own 1.5 times the second-from-top own level
  with neighbour 1.5 times the second neighbour level.
- **Repeats:** each cell `4` times, interleaved; a cell needs `3` valid
  repeats. A run is valid only if its measured engine read the compile cache
  (`S4b` at most 5 s), because compile state moves KV capacity.
- **Compile sharing:** shared if every swap-in in reconnaissance's compile
  probe hit the cache.
- **Validation set:** `Qwen/Qwen3-4B`, `Qwen/Qwen3-4B-Base` and
  `Qwen/Qwen3-4B-Instruct-2507` if the class is 4B and compile is shared;
  otherwise three tenants of the measured checkpoint.
- **Swap campaign:** every ordered pair of distinct checkpoints in the
  validation set (or the one checkpoint swapped to itself), with
  `16` swaps per cache state in total, rounded up per pair.
- **Page-cache eviction works** if, in every cold swap reconnaissance ran, a
  method succeeded and the kernel's `Cached:` figure fell by at least `0.5` of
  one 4B checkpoint's weights. Then swaps are measured cold and warm, and the
  simulator and validation use cold swaps; otherwise warm only, and this is a
  stated limit.
- **Simulated swaps:** drawn from the measured swaps in the simulated cache
  state whose incoming engine hit the compile cache.
- **Sleep mode:** measured `8` times if reconnaissance found it working, and
  reported beside the crossover. It is never simulated: that needs the host
  memory a sleeping model holds, which reconnaissance does not measure (scope
  amendment §6).

### The simulated design

- **Fleet:** N = `20` models; Zipf skews `0.6, 0.8, 1.0, 1.25, 1.5, 2.0`; both
  locality regimes; hot-model fraction `0.7`; warm-up `300` s; bursty mean
  burst `120` s at duty `0.2`; `30` repetitions; run length from the pilot
  rule with `1200` pilot traces; seed `20261004`.
- **Sizing and pairing:** as scope amendment §7, with the §14 decision above.
- **Offered load and SLO:** chosen by a ranking-blind screen from offered loads
  of `4.0`, `2.0` and `1.0` GPUs of saturation and SLOs of `1.0`, `2.0` and
  `4.0` times the simulated swap's median. The screen runs `5` repetitions on
  seed `20261005`, on provisional inputs: the placeholder engines and
  reconnaissance's own swap times. Each evaluable grid point scores the number
  of distinct sized fleets among the three strategies, minus one (0 to 2); a
  candidate's score is the sum. It never looks at which strategy is cheaper.
  The highest score wins; a tie goes to the earlier candidate, offered load
  first, then the tighter SLO, in the order listed.
- **Artifact 5's reference point:** the bursty regime at s = `1.0`.

### The validation gate

- **Trace:** the validation set's three tenants at Zipf s = `1.0`, bursty with
  mean burst `180` s at duty `0.25`, offered at `0.3` of the measured solo
  saturation over a `900` s window. The driver caps requests in flight at the
  solo curve's top measured concurrency.
- **Draw:** the first of seeds `4104` to `4123`, in order, whose replay is
  feasible. Feasible means that the simulator, replaying the draw as the
  prediction below does, finishes its last request within `1200` s, leaves at
  least `10` bins with a median, and swaps at least `4` times. The check runs on
  the measured curve and swaps, before any replay, and reads only predicted
  feasibility, never a verdict. If no draw is feasible, the gate cannot run as
  registered and the owner decides.
- **Band:** exactly `3` real repeats of that one trace, binned at `30` s by
  scheduled arrival. A request counts as unfinished if its scheduled arrival
  plus its latency is past the window, the clock the prediction uses. A repeat
  whose arrivals lag the schedule by more than `0.5` s is refused.
- **Prediction:** the simulator replays the same trace on one GPU holding the
  first tenant, with the solo curve, and every swap at the median of the
  measured swaps in the validation's cache state plus the median page-cache
  eviction, which a cold replay pays before every swap-in and a fleet does not.
- **Pass rule:** at least `10` judged bins, at most `0.5` of them missing,
  band edges widened by `0.001` s (`autoscale/validation_band.py`). The
  predicted swap count must also lie within the real repeats' range, widened by
  `1` either side.
- **Interference check:** each held-out cell passes if the surface's
  prediction lies inside its repeats' range or within `0.1` of their median.
  A failure is reported against the co-locate strategy, not hidden.
````

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_step2.py tests/test_placement_step2_doc.py tests/test_placement_measure_prereg.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — the step-1 document test still passes

- [ ] **Step 8: Lint**

Run: `.venv/bin/ruff check placement/step2.py tests/a4_examples.py tests/test_placement_step2.py tests/test_placement_step2_doc.py`

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add placement/step2.py docs/experiment-a4.md tests/a4_examples.py tests/test_placement_step2.py tests/test_placement_step2_doc.py
git commit -m "prereg: artifact 4's step 2 rules, fixed before reconnaissance's answers are read"
```

---

## Task 6: The ranking-blind regime screen

**Files:**
- Create: `placement/grid.py`
- Modify: `scripts/a4_sweep.py`
- Modify: `tests/test_a4_sweep.py`
- Create: `placement/screen.py`
- Create: `scripts/a4_screen.py`
- Test: `tests/test_placement_screen.py`

Amendment §14 found plan 1's placeholder sweep degenerate. Artifact 2 met the same problem and answered it with a screen whose question cannot be read as "strategy X is better" (`docs/findings-a2-degenerate-regime.md`). This is artifact 4's version. Per candidate offered load and SLO, each evaluable grid point scores how many of the three strategies it tells apart: the number of distinct sized fleets, minus one. The highest total wins, and a tie goes to the earlier candidate in the pre-registered order. It runs on provisional inputs, because step 2 must be committed before measurement: the placeholder engines and reconnaissance's own swap times.

**The first version of the score was useless, and the run that showed it is recorded here.** It counted points where the fleets were "not all equal". On the example report all nine candidates scored 12 of 12: co-locate's paired fleet beat dedicate everywhere, which alone made every point count. The same run showed what Task 1's decision buys. In the bursty regime swap now sized 7–11 GPUs below dedicate and traded places with co-locate. In the spread regime swap still sized to dedicate's M, which is the expected thrash. Rescored with the current rule, the same run's candidates range from 15 to 19.

**This moves existing code.** The sweep's grid builder and its pooled evaluation move unchanged from `scripts/a4_sweep.py` to `placement/grid.py`, so the screen builds exactly the grid the sweep does. Inventory of what moves, from reading `scripts/a4_sweep.py`:
- `grid()` and `PILOT_SEED_OFFSET`: preserved, moved verbatim;
- the `ProcessPoolExecutor` map over `evaluate_point`: preserved, as `evaluate_grid`;
- the cache, `run`, the summary and `main`: unchanged, in place.

Nothing is dropped. The parity gate is `tests/test_a4_sweep.py` passing. Its one edit makes the cache-reuse test patch `evaluate_grid`, the name the script now calls, so it still proves the cache was reused.

**Measured cost.** On the example report the full screen took 25.5 minutes on 8 cores, about 8.5 minutes per offered load.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_screen.py`:

```python
"""The ranking-blind screen: its score, its tie-break, and the script's plumbing.

The score is checked on hand-built evaluations whose sized fleets are known,
so no simulation runs here. The script is checked with its evaluator patched,
which is what makes it fast: the screen's simulations are its own task step.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_examples import example_report

from placement import step2
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.screen import choose, run_screen, score, told_apart

REPO = Path(__file__).resolve().parents[1]


def _evaluation(s, p99_by_strategy, reps=2):
    """One grid point whose configurations have the given p99 in every
    decile and repetition: {strategy: [(m, p99), ...]}."""
    outcomes = {
        strategy: tuple(
            ConfigOutcome(strategy=strategy, m=m, decile_p99s=((p99,) * 10,) * reps,
                          swaps=(0,) * reps, extrapolated=(0,) * reps)
            for m, p99 in configs)
        for strategy, configs in p99_by_strategy.items()
    }
    return PointEvaluation(point=GridPoint(s, "spread", 100.0), outcomes=outcomes,
                           counts=((600,) * 10,) * reps)


SEPARATING = _evaluation(1.0, {"dedicate": [(10, 1.0)], "swap": [(6, 9.0), (8, 1.0)],
                               "colocate": [(5, 1.0)]})
TIED = _evaluation(1.5, {"dedicate": [(10, 1.0)], "swap": [(6, 9.0), (10, 1.0)],
                         "colocate": [(5, 9.0), (10, 1.0)]})


def test_a_point_scores_the_strategies_it_tells_apart():
    assert told_apart({"dedicate": 10, "swap": 8, "colocate": 5}) == 2
    # Co-locate alone differing tells only one strategy apart: the case that
    # made the first version of this score useless.
    assert told_apart({"dedicate": 10, "swap": 10, "colocate": 5}) == 1
    assert told_apart({"dedicate": 10, "swap": 10, "colocate": 10}) == 0
    assert told_apart({"dedicate": None, "swap": None, "colocate": None}) == 0
    assert told_apart(None) == 0


def test_the_score_sums_over_points_and_depends_on_the_slo():
    loose = score([SEPARATING, TIED], slo=2.0)
    assert (loose["score"], loose["evaluable"]) == (2, 2)
    # At an SLO under every p99 all three are dominated everywhere: degenerate.
    assert score([SEPARATING, TIED], slo=0.5)["score"] == 0


def test_a_tie_goes_to_the_earlier_candidate():
    scored = [{"score": 3, "n": 0}, {"score": 5, "n": 1}, {"score": 5, "n": 2}]
    assert choose(scored)["n"] == 1
    with pytest.raises(ValueError):
        choose([])


def test_the_screen_evaluates_once_per_load_and_scores_every_slo():
    calls = []

    def evaluate(offered):
        calls.append(offered)
        return [SEPARATING] if offered == 2.0 else [TIED]

    result = run_screen(evaluate, swap_median_s=1.0)
    assert calls == list(step2.SCREEN_OFFERED_GPUS)
    assert len(result["candidates"]) == len(step2.SCREEN_OFFERED_GPUS) * len(
        step2.SCREEN_SLO_SWAP_MULTIPLES)
    # Only offered 2.0 tells strategies apart, and at every SLO multiple (a
    # p99 equal to the SLO meets it). The tie goes to the tightest, 1.
    assert result["chosen"] == {"offered_gpus": 2.0, "slo_swap_multiple": 1.0}
    assert result["choice"] == step2.SweepChoice(2.0, 1.0)


def _script():
    spec = importlib.util.spec_from_file_location("a4_screen", REPO / "scripts" / "a4_screen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_builds_the_registered_grid_on_provisional_inputs(tmp_path, monkeypatch):
    script = _script()
    seen = []

    def fake_evaluate_grid(points, scenario, engines, swap_time, repetitions, seed, slo, workers):
        seen.append({"points": points, "offered": scenario.offered_gpus, "swap": swap_time,
                     "repetitions": repetitions, "seed": seed, "slo": slo})
        return [SEPARATING]

    monkeypatch.setattr(script, "evaluate_grid", fake_evaluate_grid)
    monkeypatch.setattr(script, "grid", lambda design, scenario: [design])
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(example_report()))
    out = tmp_path / "screen.json"
    result = script.main(["--report", str(report_path), "--out", str(out), "--workers", "1"])
    assert [s["offered"] for s in seen] == list(step2.SCREEN_OFFERED_GPUS)
    first = seen[0]
    assert first["repetitions"] == step2.SCREEN_REPETITIONS and first["seed"] == step2.SCREEN_SEED
    assert first["slo"] is None and first["swap"].measured is False
    assert first["swap"].samples == (44.0, 45.5)
    design = first["points"][0]
    assert design.skews == step2.SKEWS and design.preregistered is False
    saved = json.loads(out.read_text())
    assert saved["chosen"] == result["chosen"] and saved["swap_median_s"] == pytest.approx(44.75)
    assert "PLACEHOLDER" in saved["provisional_inputs"]["engines"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_screen.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.screen'`

- [ ] **Step 3: Move the grid and its evaluation into the package**

Create `placement/grid.py`:

```python
"""The sweep's grid, and its evaluation across worker processes.

Moved here unchanged from `scripts/a4_sweep.py` so that the ranking-blind
screen (`scripts/a4_screen.py`) builds its grid and evaluates it exactly as the
sweep does. A screen that sized its runs or seeded its pilot differently would
be screening a different experiment.
"""

from concurrent.futures import ProcessPoolExecutor

from placement.design import Design
from placement.evaluate import GridPoint, PointEvaluation, Scenario, evaluate_point
from placement.resample import EmpiricalDistribution
from placement.runlength import pilot_window
from placement.sim import Engines
from placement.tails import P99_FLOOR
from placement.traffic import decile_of, zipf_shares

__all__ = ["PILOT_SEED_OFFSET", "evaluate_grid", "grid"]

# The pilot draws from its own seed range, so it never shares a stream with a
# repetition it is sizing.
PILOT_SEED_OFFSET = 1_000_003


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


def evaluate_grid(
    points: list[GridPoint],
    scenario: Scenario,
    engines: Engines,
    swap_time: EmpiricalDistribution,
    repetitions: int,
    seed: int,
    slo: float | None,
    workers: int,
) -> list[PointEvaluation]:
    """`evaluate_point` at every grid point, one process per point."""
    n = len(points)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(evaluate_point, points, [scenario] * n, [engines] * n,
                             [swap_time] * n, [repetitions] * n, [seed] * n, [slo] * n))
```

- [ ] **Step 4: Point the sweep script at the moved code**

In `scripts/a4_sweep.py`, replace:

```python
import argparse
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
```

with:

```python
import argparse
import hashlib
import json
import sys
from dataclasses import asdict
```

In `scripts/a4_sweep.py`, replace:

```python
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
```

with:

```python
from placement.evaluate import Scenario, dump_evaluations, load_evaluations
from placement.grid import evaluate_grid, grid
from placement.money import Assumptions, monthly_difference
from placement.resample import EmpiricalDistribution
from placement.sim import Engines
from placement.sizing import sized_fleet

CROSSOVER_ITERATIONS = 2000
```

In `scripts/a4_sweep.py`, replace:

```python
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
```

with:

```python

```

In `scripts/a4_sweep.py`, replace:

```python
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
                    [design.slo_seconds] * len(points),
                )
            )
        dump_evaluations(cache, evaluations)
```

with:

```python
        evaluations = evaluate_grid(
            grid(design, scenario), scenario, engines, swap_time, design.repetitions,
            design.seed, design.slo_seconds, workers,
        )
        dump_evaluations(cache, evaluations)
```

In `tests/test_a4_sweep.py`, replace:

```python
    monkeypatch.setattr(script, "evaluate_point", _must_not_run)
```

with:

```python
    # The sweep evaluates through `placement.grid.evaluate_grid` since plan 3
    # moved it there; patching the name the script calls is what proves the
    # cache was reused.
    monkeypatch.setattr(script, "evaluate_grid", _must_not_run)
```

- [ ] **Step 5: Write the screen**

Create `placement/screen.py`:

```python
"""The ranking-blind regime screen: which offered load and SLO make the
three-way comparison defined at all.

Plan 1's sweep on placeholder inputs came out degenerate in both regimes
(amendment §14): swap sized to dedicate's M at every skew, partly because the
placeholder SLO was shorter than one swap. Artifact 2 met the same problem and
answered it with a screen whose question cannot be read as "strategy X is
better" (docs/findings-a2-degenerate-regime.md). This is that screen for
artifact 4.

Its question, per candidate: how many of the three strategies does each
evaluable grid point tell apart? A point scores the number of distinct sized
fleets among the three, minus one: 0 when all are equal (all dominated, or all
at dedicate's M), 2 when all three differ. The candidate's score is the sum.
It says whether the strategies can be told apart; it says nothing about which
is cheaper, so searching for a high score cannot smuggle in a preferred
winner. The highest score wins, and a tie goes to the earlier candidate in
`placement.step2`'s pre-registered order.

The first version counted points where the fleets were "not all equal". Run on
an example report, every candidate scored 12 of 12: co-locate's fully paired
fleet beat dedicate everywhere, which alone made every point count, while
swap sized to dedicate's M at most of them. A score every candidate maxes
out chooses nothing.

It runs on provisional inputs, because it must finish before the first
measurement run (amendment §12): the placeholder engines and
reconnaissance's own swap times. The SLO is a multiple of the swap median, so
the chosen multiple carries over to the measured swaps unchanged.
"""

from collections.abc import Callable, Sequence

from placement.evaluate import PointEvaluation
from placement.sizing import sized_fleet
from placement.step2 import SCREEN_OFFERED_GPUS, SCREEN_SLO_SWAP_MULTIPLES, SweepChoice

__all__ = ["choose", "run_screen", "score", "told_apart"]


def told_apart(sized: dict[str, int | None] | None) -> int:
    """How many strategies beyond the first this point tells apart: distinct
    sized fleets minus one, a dominated strategy counting as one value. 0 for
    a point that is not evaluable."""
    return 0 if sized is None else len(set(sized.values())) - 1


def score(evaluations: Sequence[PointEvaluation], slo: float) -> dict:
    rows = []
    for e in evaluations:
        sized = sized_fleet(e, list(range(e.repetitions)), slo)
        rows.append({"regime": e.point.regime, "s": e.point.s, "sized": sized,
                     "told_apart": told_apart(sized)})
    return {"score": sum(r["told_apart"] for r in rows),
            "evaluable": sum(r["sized"] is not None for r in rows), "points": rows}


def choose(scored: Sequence[dict]) -> dict:
    """The first candidate with the highest score: `max` keeps the first of
    equals, and `scored` is in pre-registered order."""
    if not scored:
        raise ValueError("no candidates were scored")
    return max(scored, key=lambda c: c["score"])


def run_screen(evaluate: Callable[[float], list[PointEvaluation]], swap_median_s: float) -> dict:
    """`evaluate(offered_gpus)` returns the grid's evaluations at that load.
    It is called once per offered load: the SLO only enters the scoring, so
    every SLO candidate is scored against the same evaluations."""
    scored = []
    for offered in SCREEN_OFFERED_GPUS:
        evaluations = evaluate(offered)
        for multiple in SCREEN_SLO_SWAP_MULTIPLES:
            slo = multiple * swap_median_s
            scored.append({"offered_gpus": offered, "slo_swap_multiple": multiple,
                           "slo_seconds": slo, **score(evaluations, slo)})
    best = choose(scored)
    return {"swap_median_s": swap_median_s, "candidates": scored,
            "chosen": {"offered_gpus": best["offered_gpus"],
                       "slo_swap_multiple": best["slo_swap_multiple"]},
            "choice": SweepChoice(best["offered_gpus"], best["slo_swap_multiple"])}
```

- [ ] **Step 6: Write the screen's script**

Create `scripts/a4_screen.py`:

```python
"""Run the ranking-blind regime screen and record its choice. Spends nothing.

    .venv/bin/python scripts/a4_screen.py [--report fixtures/a4/recon-report.json] \\
        [--out data/a4/screen.json] [--workers 4]

Reads reconnaissance's report, builds the provisional inputs the screen runs
on (the placeholder engines and reconnaissance's own swap times), and scores
every pre-registered candidate (`placement.screen`). Run it after the
reconnaissance record is committed and before `scripts/a4_step2.py`, which
reads its output. Minutes of CPU; it prints each offered load as it goes.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.traffic import saturation_rps
from harness.stats import median
from placement.evaluate import Scenario
from placement.grid import evaluate_grid, grid
from placement.placeholders import PLACEHOLDER_ENGINES
from placement.resample import EmpiricalDistribution
from placement.screen import run_screen
from placement.step2 import (
    SCREEN_REPETITIONS,
    SCREEN_SEED,
    SweepChoice,
    measurement_design,
    provisional_swap_samples,
    sweep_design,
)


def screen(report: dict, *, workers: int, engines=PLACEHOLDER_ENGINES) -> dict:
    measurement = measurement_design(report)
    samples = provisional_swap_samples(report, measurement)
    swap_time = EmpiricalDistribution(samples=samples, measured=False)
    swap_median = median(list(samples))

    def evaluate(offered: float):
        # The SLO multiple passed here is a placeholder: evaluation does not
        # read the SLO, and `run_screen` scores every multiple afterwards.
        design = sweep_design(SweepChoice(offered, 1.0), swap_median,
                              repetitions=SCREEN_REPETITIONS, seed=SCREEN_SEED,
                              preregistered=False)
        scenario = Scenario(
            n_models=design.n_models, offered_gpus=design.offered_gpus,
            saturation_rps=saturation_rps(engines.solo), hot_fraction=design.hot_fraction,
            warmup=design.warmup, mean_burst=design.mean_burst, duty=design.duty,
        )
        print(f"[screen] offered {offered} GPUs: evaluating {len(design.skews) * 2} points",
              flush=True)
        return evaluate_grid(grid(design, scenario), scenario, engines, swap_time,
                             design.repetitions, design.seed, None, workers)

    result = run_screen(evaluate, swap_median)
    result.pop("choice")
    result["provisional_inputs"] = {
        "engines": "placement.placeholders.PLACEHOLDER_ENGINES (invented; the screen only)",
        "swap_samples": list(samples),
        "simulated_swap": measurement["simulated_swap"],
    }
    return result


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", default="fixtures/a4/recon-report.json")
    ap.add_argument("--out", default="data/a4/screen.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    result = screen(json.loads(Path(args.report).read_text()), workers=args.workers)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    for c in result["candidates"]:
        print(f"  offered {c['offered_gpus']}, SLO {c['slo_swap_multiple']} x swap "
              f"({c['slo_seconds']:.0f} s): {c['score']} of {c['evaluable']} evaluable points "
              "separate the strategies")
    print(f"chosen: {result['chosen']}")
    return result


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_screen.py tests/test_a4_sweep.py tests/test_a4_end_to_end.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — the sweep's own tests pass, including cache reuse

- [ ] **Step 8: Lint**

Run: `.venv/bin/ruff check placement/grid.py placement/screen.py scripts/a4_screen.py scripts/a4_sweep.py tests/test_a4_sweep.py tests/test_placement_screen.py`

Expected: `All checks passed!`

- [ ] **Step 9: Commit**

```bash
git add placement/grid.py placement/screen.py scripts/a4_screen.py scripts/a4_sweep.py tests/test_a4_sweep.py tests/test_placement_screen.py
git commit -m "screen: a ranking-blind choice of offered load and SLO, on the sweep's own grid"
```

---

## Task 7: The reductions under step 2's rules

**Files:**
- Modify: `placement/inputs.py`
- Test: `tests/test_placement_inputs_step2.py`

Plan 2's reductions turn stores into the simulator's inputs. Step 2 adds rules they must apply:
- **A cell whose measured engine compiled does not count.** Compile state moves KV capacity (amendment §5), and the first engine on a fresh worker compiles. `require_warm_compile` turns the rule on. It defaults off, so plan 2's callers are unchanged.
- **Swaps can be filtered by the incoming engine's compile state.** The simulator draws compile-cache hits.
- **A held-out cell never enters the surface it tests.** The surface now keys only grid cells.

New:
- `sleep_distribution`;
- `eviction_seconds`, the median page-cache eviction a cold replay pays before each swap-in;
- `cell_summary`, the per-cell record of valid repeats, ranges, KV and every exclusion with its reason;
- `short_cells`, what a top-up must re-run;
- `held_out_check`;
- `load_records`, for a campaign and its top-up read together.

**The held-out pass rule.** A cell passes if the prediction is inside its repeats' range, or within 10% of their median. The range alone fails a perfect model one time in four with three repeats.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_inputs_step2.py`:

```python
"""The reductions under pre-registration step 2's rules: warm-compile validity,
compile-filtered swaps, the sleep arm, held-out cells, top-ups and
multi-store reads."""

import pytest

from harness.store import JsonlStore
from placement.colocated import ColocatedSurface
from placement.inputs import (
    cell_summary,
    cell_validity,
    colocated_surface,
    held_out_check,
    load_records,
    short_cells,
    sleep_distribution,
    solo_curve,
    swap_distribution,
)
from placement_measure.records import A4Run


def _cell(condition, latency, s4b=0.3, kv=18_000, i=0, outcome="ok"):
    return A4Run(run_id=f"{condition}-{i}", run_index=i, condition=condition, block_index=0,
                 kind="cell", outcome=outcome, failure=None if outcome == "ok" else "x",
                 clock_A={}, source="stub",
                 output={"run": {"latency_s": latency, "throughput_tps": 10.0 * latency,
                                 "gpu_util": 0.9},
                         "engines": {"measured": {"facts": {"s4b_s": s4b,
                                                            "kv_capacity_tokens": kv}}},
                         "neighbour_load": {"level": 0}})


def _swap(condition, swap_s, s4b):
    return A4Run(run_id=condition, run_index=0, condition=condition, block_index=0, kind="swap",
                 outcome="ok", failure=None, clock_A={}, source="stub",
                 output={"swap_s": swap_s, "b": {"facts": {"s4b_s": s4b}}})


def test_a_compiling_measured_engine_is_excluded_only_under_the_rule():
    compiled = _cell("pair:o4:n0", 1.0, s4b=19.0)
    assert cell_validity(compiled) is None
    assert "compiled" in cell_validity(compiled, require_warm_compile=True)
    unread = _cell("pair:o4:n0", 1.0, s4b=None)
    assert "not read" in cell_validity(unread, require_warm_compile=True)


def test_the_rule_reaches_the_curve_and_the_surface():
    records = [_cell("solo:o1", 1.0, i=0), _cell("solo:o1", 1.2, i=1),
               _cell("solo:o1", 5.0, s4b=19.0, i=2),
               _cell("solo:o2", 1.5, i=0), _cell("solo:o2", 1.7, i=1)]
    curve = solo_curve(records, levels=(1, 2), min_repeats=2, require_warm_compile=True)
    assert curve.latency_at(1) == pytest.approx(1.1)
    with pytest.raises(ValueError, match="fewer than 3"):
        solo_curve(records, levels=(1, 2), min_repeats=3, require_warm_compile=True)


def test_a_held_out_cell_never_enters_the_surface_and_need_not_be_complete():
    grid = [_cell(f"pair:o{o}:n{n}", 1.0 + o + n, i=i)
            for o in (2, 4) for n in (0, 4) for i in range(2)]
    held = [_cell("pair:o3:n2", 99.0)]  # one repeat, wildly off: must not matter
    surface = colocated_surface(grid + held, own_levels=(2, 4), neighbour_levels=(0, 4),
                                min_repeats=2, require_warm_compile=True)
    assert surface.latency_at(3, 2) == pytest.approx(1.0 + 3 + 2)


def test_the_held_out_check_passes_inside_the_range_or_near_the_median():
    surface = ColocatedSurface(own=(2, 4), neighbour=(0, 4), latency=((1.0, 2.0), (3.0, 4.0)),
                               measured=True)
    # Predicted at (3, 2) is 2.5.
    near = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((2.6, 2.7, 2.8))]
    far = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((3.4, 3.5, 3.6))]
    inside = [_cell("pair:o3:n2", v, i=i) for i, v in enumerate((2.0, 2.9, 3.6))]

    def check(recs):
        return held_out_check(recs, surface, ["pair:o3:n2"], tolerance=0.1, min_repeats=3,
                              require_warm_compile=True)[0]

    assert check(near)["passed"] and check(inside)["passed"]
    result = check(far)
    assert not result["passed"] and result["predicted"] == pytest.approx(2.5)
    with pytest.raises(ValueError, match="valid repeats"):
        check(near[:2])


def test_the_summary_records_exclusions_and_kv():
    records = [_cell("pair:o4:n0", 1.0, kv=18_000, i=0), _cell("pair:o4:n0", 1.4, kv=18_200, i=1),
               _cell("pair:o4:n0", 9.0, s4b=19.0, i=2), _cell("pair:o4:n0", 0.0, i=3, outcome="failed")]
    s = cell_summary(records, require_warm_compile=True)["pair:o4:n0"]
    assert (s["n"], s["median"], s["lo"], s["hi"]) == (2, pytest.approx(1.2), 1.0, 1.4)
    assert s["kv_capacity_tokens"] == 18_100
    assert [e["reason"].split(",")[0] for e in s["excluded"]] == [
        "the measured engine compiled", "run failed: x"]


def test_short_cells_name_what_a_top_up_must_rerun():
    records = [_cell("pair:o4:n0", 1.0, i=i) for i in range(3)] + [
        _cell("pair:o4:n4", 1.0, i=0), _cell("pair:o4:n4", 1.0, s4b=19.0, i=1)]
    conditions = ["pair:o4:n0", "pair:o4:n4", "pair:o8:n0"]
    assert short_cells(records, conditions, min_repeats=3,
                       require_warm_compile=True) == ["pair:o4:n4", "pair:o8:n0"]


def test_swaps_are_drawn_by_compile_state_when_asked():
    records = [_swap("swap:a>b:cold", 40.0, 0.3), _swap("swap:b>a:cold", 70.0, 19.0),
               _swap("swap:a>b:warm", 30.0, 0.3)]
    assert swap_distribution(records, cold=True).samples == (40.0, 70.0)
    assert swap_distribution(records, cold=True, compiled=False).samples == (40.0,)
    assert swap_distribution(records, cold=True, compiled=True).samples == (70.0,)
    with pytest.raises(ValueError):
        swap_distribution(records, cold=False, compiled=True)


def test_the_sleep_arm_is_its_ok_switches():
    def rec(s, outcome="ok"):
        return A4Run(run_id="r", run_index=0, condition="sleep:a>b", block_index=0, kind="sleep",
                     outcome=outcome, failure=None, clock_A={}, source="stub",
                     output={"switch_s": s})

    assert sleep_distribution([rec(5.0), rec(None, "failed"), rec(6.0)]).samples == (5.0, 6.0)
    with pytest.raises(ValueError):
        sleep_distribution([rec(None, "failed")])


def test_records_load_from_several_stores_in_order(tmp_path):
    a, b = JsonlStore(tmp_path / "a.jsonl", A4Run), JsonlStore(tmp_path / "b.jsonl", A4Run)
    a.append(_cell("solo:o1", 1.0, i=0))
    b.append(_cell("solo:o1", 2.0, i=1))
    loaded = load_records([tmp_path / "a.jsonl", tmp_path / "b.jsonl"])
    assert [r.output["run"]["latency_s"] for r in loaded] == [1.0, 2.0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_inputs_step2.py -q`

Expected: FAIL — `ImportError: cannot import name 'cell_summary' from 'placement.inputs'`

- [ ] **Step 3: Apply step 2's rules in the reductions**

In `placement/inputs.py`, replace:

```python
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
```

with:

```python
Per point, the median across repetitions of each run's own median latency,
the service sweep's statistic, so a co-located latency and a solo one are the
same kind of number.

`require_warm_compile` is pre-registration step 2's validity rule: a cell
whose measured engine compiled does not count, because compile state moves KV
capacity (amendment §5). It defaults off so the reductions read any store, and
plan 3's analysis turns it on.
"""

from autoscale.service import ServiceCurve
from harness.stats import median
from harness.store import JsonlStore
from placement.colocated import ColocatedSurface
from placement.resample import EmpiricalDistribution
from placement_measure.campaigns import parse_cell, parse_swap
from placement_measure.recon_report import COMPILED_ABOVE_S
from placement_measure.records import A4Run

__all__ = ["cell_summary", "cell_validity", "colocated_surface", "eviction_seconds",
           "held_out_check", "load_records", "short_cells", "sleep_distribution", "solo_curve",
           "swap_distribution"]


def load_records(paths) -> list[A4Run]:
    """Every record in the given stores, in order. A top-up campaign has its
    own store, because the resume guard assumes one campaign per store, and
    its cells reduce together with the campaign they top up."""
    out: list[A4Run] = []
    for path in paths:
        out += JsonlStore(path, A4Run).read_all()
    return out


def _compiled(facts: dict | None) -> bool | None:
    s4b = (facts or {}).get("s4b_s")
    return None if s4b is None else s4b > COMPILED_ABOVE_S
```

In `placement/inputs.py`, replace:

```python
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
```

with:

```python
def swap_distribution(records, *, cold: bool, targets=None,
                      compiled: bool | None = None) -> EmpiricalDistribution:
    """Swap durations from every ok swap in the given cache state, optionally
    only those whose incoming model is in `targets`, and only those whose
    incoming engine did (True) or did not (False) compile. The simulator draws
    the cold distribution of compile-cache hits (pre-registration step 2)."""
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok":
            continue
        _, b, is_cold = parse_swap(r.condition)
        if is_cold != cold or (targets is not None and b not in targets):
            continue
        if compiled is not None and _compiled((r.output.get("b") or {}).get("facts")) is not compiled:
            continue
        samples.append(r.output["swap_s"])
    if not samples:
        raise ValueError(
            f"no ok swap with cold={cold}, targets={targets} and compiled={compiled}; an "
            "empty distribution would simulate swaps that cost nothing"
        )
    return EmpiricalDistribution(samples=tuple(samples), measured=True)


def sleep_distribution(records) -> EmpiricalDistribution:
    """Sleep-mode switch times, from every ok sleep job (amendment §6)."""
    samples = tuple(r.output["switch_s"] for r in records if r.kind == "sleep" and r.outcome == "ok")
    if not samples:
        raise ValueError("no ok sleep-mode switch; the arm has nothing to report")
    return EmpiricalDistribution(samples=samples, measured=True)


def eviction_seconds(records, *, cold: bool) -> float:
    """Median time an ok cold swap spent evicting its successor's page cache.

    `swap_s` excludes it, because a fleet does not drop its cache before a
    swap. The replay driver does, so the validation's prediction adds this to
    every swap. 0 when the validation's swaps are warm.
    """
    if not cold:
        return 0.0
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok" or not parse_swap(r.condition)[2]:
            continue
        if "cache_s" not in r.output:
            raise ValueError(f"swap {r.run_id} has no eviction time; it was measured by an image "
                             "older than plan 3's")
        samples.append(r.output["cache_s"])
    if not samples:
        raise ValueError("no ok cold swap to take an eviction time from")
    return median(samples)


def cell_validity(record, *, require_warm_compile: bool = False) -> str | None:
    """None if the cell's measurement stands; otherwise why it does not."""
    if record.outcome != "ok":
        return f"run failed: {record.failure}"
    load = record.output.get("neighbour_load")
    if load and load.get("level"):
        if not (load.get("ramp") or {}).get("reached"):
            return "the neighbour never reached its load before the measured run"
        if load.get("ended_before_measured_run"):
            return "the neighbour ran out of requests during the measured run"
    if require_warm_compile:
        facts = ((record.output.get("engines") or {}).get("measured") or {}).get("facts")
        compiled = _compiled(facts)
        if compiled is None:
            return "the measured engine's compile state was not read from its log"
        if compiled:
            return ("the measured engine compiled, and compile state moves KV capacity "
                    "(amendment §5)")
    return None


def _medians(records, *, kind_of, min_repeats, require_warm_compile: bool = False) -> dict:
    by: dict = {}
    for r in records:
        if r.kind != "cell" or cell_validity(r, require_warm_compile=require_warm_compile):
            continue
```

In `placement/inputs.py`, replace:

```python
def solo_curve(records, *, levels, min_repeats: int) -> ServiceCurve:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return own if neighbour is None else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
```

with:

```python
def solo_curve(records, *, levels, min_repeats: int,
               require_warm_compile: bool = False) -> ServiceCurve:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return own if neighbour is None else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats,
                  require_warm_compile=require_warm_compile)
```

In `placement/inputs.py`, replace:

```python
def colocated_surface(records, *, own_levels, neighbour_levels, min_repeats: int) -> ColocatedSurface:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return None if neighbour is None else (own, neighbour)

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
```

with:

```python
def colocated_surface(records, *, own_levels, neighbour_levels, min_repeats: int,
                      require_warm_compile: bool = False) -> ColocatedSurface:
    grid = {(o, n) for o in own_levels for n in neighbour_levels}

    def key(r):
        own, neighbour = parse_cell(r.condition)
        # Only grid cells: a held-out cell must never be folded into the
        # surface it is held out to test.
        return (own, neighbour) if (own, neighbour) in grid else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats,
                  require_warm_compile=require_warm_compile)
```

In `placement/inputs.py`, replace:

```python
    return ColocatedSurface(own=tuple(own_levels), neighbour=tuple(neighbour_levels),
                            latency=latency, measured=True)
```

with:

```python
    return ColocatedSurface(own=tuple(own_levels), neighbour=tuple(neighbour_levels),
                            latency=latency, measured=True)


def cell_summary(records, *, require_warm_compile: bool) -> dict[str, dict]:
    """Per cell condition: valid repeats, the median and range of their
    latencies, the measured engine's median KV capacity, and why any repeat
    did not count. The figure's error bars and the record of exclusions."""
    out: dict[str, dict] = {}
    for r in records:
        if r.kind != "cell":
            continue
        entry = out.setdefault(r.condition, {"latencies": [], "kv": [], "excluded": []})
        reason = cell_validity(r, require_warm_compile=require_warm_compile)
        if reason:
            entry["excluded"].append({"run_id": r.run_id, "reason": reason})
            continue
        entry["latencies"].append(r.output["run"]["latency_s"])
        kv = (((r.output.get("engines") or {}).get("measured") or {}).get("facts") or {}).get(
            "kv_capacity_tokens")
        if kv is not None:
            entry["kv"].append(kv)
    for entry in out.values():
        lat = entry.pop("latencies")
        kv = entry.pop("kv")
        entry.update({"n": len(lat), "median": median(lat) if lat else None,
                      "lo": min(lat) if lat else None, "hi": max(lat) if lat else None,
                      "kv_capacity_tokens": median(kv) if kv else None})
    return out


def short_cells(records, conditions, *, min_repeats: int, require_warm_compile: bool) -> list[str]:
    """The cells among `conditions` with fewer than `min_repeats` valid
    repeats, in the given order: what a top-up campaign must re-run."""
    summary = cell_summary(records, require_warm_compile=require_warm_compile)
    return [c for c in conditions if summary.get(c, {"n": 0})["n"] < min_repeats]


def held_out_check(records, surface: ColocatedSurface, cells, *, tolerance: float,
                   min_repeats: int, require_warm_compile: bool) -> list[dict]:
    """Does the surface predict cells it was not built from? August §9's
    second check. A cell passes if the surface's bilinear prediction lies
    inside its repeats' range, or within `tolerance` of their median: a perfect
    model falls outside the range of three repeats one time in four (both
    edges are order statistics), so the range alone would fail it too often."""
    summary = cell_summary(records, require_warm_compile=require_warm_compile)
    out = []
    for cell in cells:
        own, neighbour = parse_cell(cell)
        s = summary.get(cell, {"n": 0})
        if s["n"] < min_repeats:
            raise ValueError(f"held-out cell {cell} has {s['n']} valid repeats, below "
                             f"{min_repeats}; the check would pass or fail on noise")
        predicted = surface.latency_at(own, neighbour)
        inside = s["lo"] <= predicted <= s["hi"]
        close = abs(predicted - s["median"]) <= tolerance * s["median"]
        out.append({"cell": cell, "own": own, "neighbour": neighbour, "predicted": predicted,
                    "median": s["median"], "lo": s["lo"], "hi": s["hi"], "n": s["n"],
                    "passed": inside or close})
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_inputs_step2.py tests/test_placement_inputs.py tests/test_a4_measure_end_to_end.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — plan 2's reduction tests still pass unchanged

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement/inputs.py tests/test_placement_inputs_step2.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/inputs.py tests/test_placement_inputs_step2.py
git commit -m "inputs: warm-compile validity, compile-filtered swaps, the sleep arm, held-out cells and top-ups"
```

---

## Task 8: The validation gate

**Files:**
- Create: `placement/validation.py`
- Test: `tests/test_placement_validation.py`

This is August §9's gate, built on artifact 2's band and verdict arithmetic (`autoscale/validation_band.py`), which has no import path to `coldstart`.

**What is artifact 4's own:**
- **The real replay's record.** Latency runs from arrival, and is cut at the window as the simulator's is.
- **The check that the three repeats replayed one trace.** It also requires each to name its host.
- **The prediction.** It is the simulator on one GPU holding the first tenant, with the measured solo curve and every swap at the measured median. A fixed swap time keeps the prediction deterministic: the band is the real system's spread, and a prediction drawn from a distribution would add the simulator's own noise to the comparison.
- **The swap-timeline check August §9 also asks for.** The predicted swap count must lie within the real repeats' range, plus or minus one.
- **The cut at the window,** on the schedule's clock for both sides. Judged on actual arrival, a request finishing within the send jitter of the window's end could be censored on one side only.
- **The choice of trace.** `validation_trace` tries the pre-registered seeds in order and takes the first draw the simulator predicts is feasible: drained within 1200 s, at least 10 bins with a median, at least 4 swaps. It reads only predicted feasibility on measured inputs, never a verdict.

**Why the trace needed that rule.** An independent review of the first version simulated its trace: three bursty tenants on one GPU ping-pong whenever two are ON at once, and the draw needed 98 swaps and over 2,600 s to drain against a job's 1,680 s. Every replay would have hit the job budget, and the analysis would then have crashed on too few ok replays. Lowering the load did not help, because the swap count follows burst overlap, not load. Simulating draws on 2026-10-04 settled the registered parameters (load 0.3, mean burst 180 s, duty 0.25): with a 4B-like curve and 25-60 s swaps, a feasible draw came within the first two seeds in every case tried.

**The tests know the verdict in advance.** Their real latencies are the simulator's own, offset per repeat, so they pass. With 2 s added they fail, and with the swap count moved past the slack they fail.

**The driver and the simulator are tested against each other.** One test runs the replay driver from Task 4 and the simulator on the same thousand-fold-scaled trace and requires the same swaps in the same order.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_validation.py`:

```python
"""The validation gate on hand-built replay records whose latencies are the
simulator's own, offset per repeat, so the verdict is known in advance; and
one cross-check that the real driver and the simulator swap alike."""

import random
import time

import pytest
from test_placement_measure_replay import TENANTS, Completions, TimedEngines, _deps

from autoscale.service import ServiceCurve
from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement import validation
from placement.colocated import ColocatedSurface
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.validation import check_repeats, predict, replay_run, validate
from placement_measure.records import A4Run
from placement_measure.replay import ReplaySpec, replay

CURVE = ServiceCurve(points=[(1, 0.5, 2.0, 0.3), (8, 0.6, 13.0, 1.0)], measured=True)
SURFACE = ColocatedSurface(own=(1, 8), neighbour=(0, 8), latency=((0.5, 0.6), (0.6, 0.7)),
                           measured=True)
ENGINES = Engines(CURVE, SURFACE)
SWAP_S = 20.0
UNTIL = 400.0
# Tenant 0 every 0.4 s, so a 10 s bin holds 25 requests (the p50 floor is 20);
# tenant 1 and tenant 2 each force a swap and the swap back.
SCHEDULE = sorted([(round(0.4 * i, 3), 0) for i in range(900)]
                  + [(100.0 + 0.5 * i, 1) for i in range(20)]
                  + [(220.0 + 0.5 * i, 2) for i in range(20)])


def _simulated():
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    result = simulate(SCHEDULE, placement, ENGINES,
                      EmpiricalDistribution(samples=(SWAP_S,), measured=True), 0.0,
                      random.Random(0))
    # Keyed by (arrival, tenant): tenants 0 and 1 both arrive at 100.0 s.
    by_request = dict(zip(zip(result.arrivals, result.models, strict=True), result.latencies,
                          strict=True))
    return [by_request[(t, m)] for t, m in SCHEDULE], result.swaps


def _record(i, latencies, swaps, *, jitter=0.0, host="h"):
    arrived = [t + jitter for t, _ in SCHEDULE]
    output = {"schedule": [[t, m] for t, m in SCHEDULE], "until": UNTIL, "arrived": arrived,
              "done": [a + lat for a, lat in zip(arrived, latencies, strict=True)],
              "swaps": [{}] * swaps, "host": {"host_id": f"{host}{i}"}}
    return A4Run(run_id=f"r{i}", run_index=i, condition="replay", block_index=i, kind="replay",
                 outcome="ok", failure=None, clock_A={}, output=output, source="stub")


def _records(offsets=(-0.01, 0.0, 0.01), bias=0.0, swaps=None):
    latencies, sim_swaps = _simulated()
    return [_record(i, [lat + off + bias for lat in latencies],
                    sim_swaps if swaps is None else swaps)
            for i, off in enumerate(offsets)]


def test_the_prediction_is_the_simulators_replay_of_the_trace():
    bins, swaps, last_done = predict([t for t, _ in SCHEDULE], [m for _, m in SCHEDULE], UNTIL,
                                     ENGINES, SWAP_S)
    # Tenant 0 keeps arriving while tenants 1 and 2 are served, so the GPU
    # swaps back and forth: the thrash the simulator models.
    assert swaps == _simulated()[1] > 4
    assert len(bins) == 14  # 400 s in 30 s bins
    assert last_done == max(t + lat for (t, _), lat in zip(SCHEDULE, _simulated()[0], strict=True))


def test_reality_that_matches_the_simulator_passes():
    result = validate(_records(), ENGINES, SWAP_S)
    assert result["outcome"] == "passed", result["latency"]["detail"]
    n = _simulated()[1]
    assert result["swaps"] == {"predicted": n, "real": [n, n, n], "agree": True}
    assert result["latency"]["compared"] >= 10 and result["hosts"] == ["h0", "h1", "h2"]


def test_reality_two_seconds_slower_fails_on_latency():
    result = validate(_records(bias=2.0), ENGINES, SWAP_S)
    assert result["outcome"] == "failed" and result["latency"]["outcome"] == "failed"


def test_a_swap_count_outside_the_slack_fails_even_when_latency_agrees():
    n = _simulated()[1]
    result = validate(_records(swaps=n + 2), ENGINES, SWAP_S)
    assert result["latency"]["outcome"] == "passed" and result["outcome"] == "failed"
    assert validate(_records(swaps=n + 1), ENGINES, SWAP_S)["outcome"] == "passed"


def test_the_gate_needs_exactly_three_repeats_of_one_trace():
    runs = [replay_run(r) for r in _records()]
    with pytest.raises(ValueError, match="exactly 3"):
        check_repeats(runs[:2])
    other = _records()[0]
    other.output["schedule"][5][0] += 0.001
    with pytest.raises(ValueError, match="ONE trace"):
        check_repeats([replay_run(other), *runs[1:]])


def test_a_replay_that_lagged_the_schedule_is_refused():
    latencies, swaps = _simulated()
    late = _record(0, latencies, swaps, jitter=0.6)
    with pytest.raises(ValueError, match="lag the schedule"):
        check_repeats([replay_run(late), *(replay_run(r) for r in _records()[1:])])


def test_only_an_ok_replay_record_qualifies():
    failed = _records()[0]
    failed.outcome = "failed"
    with pytest.raises(ValueError, match="not an ok replay"):
        replay_run(failed)


def test_a_request_finishing_after_the_window_is_cut():
    run = replay_run(_records()[0])
    for t, lat, cut in zip(run.schedule, run.latencies, run.windowed_latencies(), strict=True):
        assert (cut is None) == (t + lat > UNTIL)
    # Strictly after the window: a request finishing exactly at `until` counts,
    # as in the simulator's `event.time > until`.
    late = replay_run(_record(0, [UNTIL + 1.0] * len(SCHEDULE), 4))
    assert set(late.windowed_latencies()) == {None}


def test_the_cut_is_on_the_schedules_clock_so_jitter_cannot_censor_one_side():
    latencies, swaps = _simulated()
    # The last request finishes 0.2 s before the window ends, on schedule.
    t_last = SCHEDULE[-1][0]
    latencies = [*latencies[:-1], UNTIL - t_last - 0.2]
    # Handled 0.4 s late, it actually finishes 0.2 s after the window. On the
    # schedule's clock, the one the prediction uses, it is still inside.
    late = replay_run(_record(0, latencies, swaps, jitter=0.4))
    assert late.windowed_latencies()[-1] is not None


def test_the_real_driver_and_the_simulator_make_the_same_swaps():
    """The driver restates the simulator's swap rule; this holds them to each
    other on one GPU, with every duration scaled down a thousand-fold."""
    scale = 1000.0
    # Groups at least 40 s apart (40 ms here), so no two events race.
    groups = [(0.0, 0), (60.0, 1), (120.0, 0), (200.0, 2), (260.0, 1)]
    schedule = [(round(start + 1.0 * i, 3) / scale, m) for start, m in groups for i in range(10)]
    spec = ReplaySpec(tenants=TENANTS, schedule=tuple(schedule), until=0.4, input_len=4,
                      output_len=4, max_in_flight=8, cold=False, seed=1, hf_home="/h",
                      release_tolerance_mib=512, release_timeout_s=60)
    out = replay(spec, deadline=time.monotonic() + 30,
                 deps=_deps(TimedEngines(startup_s=SWAP_S / scale),
                            Completions(service_s=0.5 / scale)))
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    sim = simulate([(t * scale, m) for t, m in schedule], placement, ENGINES,
                   EmpiricalDistribution(samples=(SWAP_S,), measured=True), 0.0, random.Random(0))
    assert len(out["swaps"]) == sim.swaps == 4
    assert [(s["from"], s["to"]) for s in out["swaps"]] == [(0, 1), (1, 0), (0, 2), (2, 1)]


def test_a_stub_replay_round_trips_into_a_qualifying_record():
    from placement_measure.jobs import measure_job
    from placement_measure.records import build_record

    payload = {"kind": "replay", "run_id": "r", "job_budget_s": 1800,
               "tenants": [t.to_dict() for t in TENANTS], "schedule": [[0.0, 0], [0.02, 1]],
               "until": 1.0, "input_len": 4, "output_len": 4, "max_in_flight": 4, "cold": False,
               "seed": 1, "hf_home": "/h", "release_tolerance_mib": 512, "release_timeout_s": 60}
    outcome = PayloadStubSubmitter(lambda p: measure_job(
        p, replay_deps=_deps(), host=lambda: {"host_id": "h9", "runpod_pod_id": None})
    ).submit_payload(payload)
    record = build_record(ScheduledRun(0, 0, "replay"), "r", outcome, kind="replay", source="stub")
    run = validation.replay_run(record)
    assert run.schedule == (0.0, 0.02) and run.tenants == (0, 1) and run.host_id == "h9"
    assert run.swaps == 1 and all(lat is not None for lat in run.latencies)


def _measurement():
    from a4_examples import example_report

    from placement.step2 import measurement_design

    return measurement_design(example_report())


def test_the_trace_is_the_first_registered_draw_whose_replay_is_feasible():
    from placement import step2
    from placement.validation import validation_trace

    # A 4B-like curve: about 4 s per request alone, 22 s at 128 in flight.
    curve = ServiceCurve(points=[(1, 4.0, 0.25, 0.3), (8, 4.5, 1.8, 0.6), (16, 5.0, 3.2, 0.8),
                                 (32, 6.5, 4.9, 0.9), (64, 11.0, 5.8, 1.0), (128, 22.0, 5.8, 1.0)],
                         measured=True)
    design, checks = validation_trace(_measurement(), Engines(curve, SURFACE), swap_s=39.0)
    assert checks[-1]["feasible"] and all(not c["feasible"] for c in checks[:-1])
    assert checks[0]["seed"] == step2.VALIDATION_SEEDS[0]
    assert design == step2.validation_design(_measurement(), curve, checks[-1]["seed"])
    last = checks[-1]
    assert last["predicted_last_done_s"] <= step2.VALIDATION_DRAIN_LIMIT_S
    assert last["predicted_swaps"] >= step2.VALIDATION_MIN_SWAPS and last["ok_bins"] >= 10


def test_a_trace_no_registered_load_can_replay_in_a_job_stops():
    from placement.step2 import NotDecidable
    from placement.validation import validation_trace

    with pytest.raises(NotDecidable, match="no pre-registered validation draw is feasible"):
        validation_trace(_measurement(), ENGINES, swap_s=400.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_validation.py -q`

Expected: FAIL — `ImportError: cannot import name 'validation' from 'placement'`

- [ ] **Step 3: Write the gate**

Create `placement/validation.py`:

```python
"""Artifact 4's validation gate: three models, one GPU, real swaps, one
replayed trace, and the simulator held to the real repeats' spread (August §9).

The band and verdict arithmetic is artifact 2's, shared through the
coldstart-free `autoscale.validation_band`. What is artifact 4's own is here:
the record of one real replay, the check that the repeats replayed one trace,
the simulator's prediction of that trace, and a second test August §9 asks
for, that the simulator reproduces the swap timeline as well as the latency.
Every threshold is pre-registered in `placement.step2`.

Bins are keyed by SCHEDULED arrival, as in artifact 2's gate, so every repeat
and the prediction place the same requests in the same bins and driver jitter
cannot move a request across a boundary. Jitter is bounded instead.

The prediction replays the trace on one GPU that starts holding the first
tenant, as the driver does, with the measured solo curve and every swap at the
median measured swap in the validation's cache state, plus the median
page-cache eviction a cold replay pays and a fleet does not. A fixed swap
time keeps the prediction deterministic: the band is the real system's
spread, and a prediction drawn from a distribution would add the simulator's
own noise to the comparison.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from autoscale.validation_band import BandBin, Bin, band, compare, trajectory
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.step2 import (
    EDGE_TOLERANCE_S,
    MAX_MISS_FRACTION,
    MAX_SEND_JITTER_S,
    MIN_COMPARED_BINS,
    SWAP_COUNT_SLACK,
    VALIDATION_BIN_S,
    VALIDATION_DRAIN_LIMIT_S,
    VALIDATION_MIN_SWAPS,
    VALIDATION_REPEATS,
    VALIDATION_SEEDS,
    NotDecidable,
    validation_design,
)
from placement_measure.campaigns import ReplayDesign

__all__ = ["ReplayRun", "check_repeats", "predict", "replay_run", "tolerance_band", "validate",
           "validation_trace"]


@dataclass(frozen=True)
class ReplayRun:
    """One real replay. `latencies[i]` is request i's completion minus its
    arrival, None if it never completed; `windowed_latencies` applies the cut
    at `until`, on the same clock as the simulator's trajectory."""

    schedule: tuple[float, ...]
    tenants: tuple[int, ...]
    arrived: tuple[float, ...]
    latencies: tuple[float | None, ...]
    until: float
    swaps: int
    host_id: str

    def windowed_latencies(self) -> tuple[float | None, ...]:
        """None where the request finished after `until`, judged on the
        SCHEDULE's clock (scheduled arrival plus latency), as the prediction
        is. Judged on actual arrival instead, a request finishing within the
        send jitter of the window's end could be censored on one side only,
        and the gate would score an unbounded miss neither system made."""
        return tuple(None if lat is None or t + lat > self.until else lat
                     for t, lat in zip(self.schedule, self.latencies, strict=True))

    def send_jitter(self) -> float:
        return max(a - t for a, t in zip(self.arrived, self.schedule, strict=True))


def replay_run(record) -> ReplayRun:
    """A stored replay record as a `ReplayRun`. Only an ok record qualifies:
    `placement_measure.records` marks a replay failed if a request errored or
    the job budget cut it short."""
    if record.kind != "replay" or record.outcome != "ok":
        raise ValueError(f"run {record.run_id} is not an ok replay ({record.kind}, {record.outcome})")
    out = record.output
    schedule = tuple(float(t) for t, _ in record_schedule(out))
    arrived = out["arrived"]
    if any(a is None for a in arrived):
        raise ValueError(f"replay {record.run_id} left arrivals unhandled; it replayed part of the trace")
    latencies = tuple(None if d is None else d - a for a, d in zip(arrived, out["done"], strict=True))
    return ReplayRun(schedule=schedule, tenants=tuple(m for _, m in record_schedule(out)),
                     arrived=tuple(arrived), latencies=latencies, until=float(out["until"]),
                     swaps=len(out["swaps"]), host_id=(out.get("host") or {}).get("host_id") or "")


def record_schedule(output: dict) -> list[tuple[float, int]]:
    """The trace a replay was given, as the driver echoed it into its output."""
    return [(float(t), int(m)) for t, m in output["schedule"]]


def check_repeats(runs: Sequence[ReplayRun]) -> None:
    if len(runs) != VALIDATION_REPEATS:
        raise ValueError(
            f"{len(runs)} ok replays; the gate needs exactly {VALIDATION_REPEATS}. Fewer is "
            "too little spread, and more widens a min-max band until the model fits"
        )
    first = runs[0]
    for run in runs[1:]:
        if (run.schedule, run.tenants, run.until) != (first.schedule, first.tenants, first.until):
            raise ValueError(
                "the replays differ in trace or window; the band must be the system's spread "
                "on ONE trace, and mixing traces widens it for free"
            )
    for run in runs:
        if run.send_jitter() > MAX_SEND_JITTER_S:
            raise ValueError(
                f"a replay's arrivals lag the schedule by {run.send_jitter():.3f} s, more than "
                f"{MAX_SEND_JITTER_S} s; it replayed a different trace from the one predicted"
            )
    if not all(run.host_id for run in runs):
        raise ValueError("a replay does not name its host; a host-novelty event would then be "
                         "indistinguishable from a simulator bug")


def tolerance_band(runs: Sequence[ReplayRun]) -> list[BandBin]:
    check_repeats(runs)
    return band([trajectory(r.schedule, r.windowed_latencies(), until=r.until,
                            bin_seconds=VALIDATION_BIN_S) for r in runs],
                min_repeats=VALIDATION_REPEATS)


def predict(schedule: Sequence[float], tenants: Sequence[int], until: float, engines: Engines,
            swap_median_s: float) -> tuple[list[Bin], int, float]:
    """The simulator's trajectory of the trace, its swap count, and when its
    last request completes (drain-out included)."""
    if not math.isfinite(swap_median_s) or swap_median_s < 0:
        raise ValueError(f"swap_median_s must be a finite duration, got {swap_median_s!r}")
    n_tenants = max(tenants) + 1
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=tuple(range(n_tenants)))
    result = simulate(list(zip(schedule, tenants, strict=True)), placement, engines,
                      EmpiricalDistribution(samples=(swap_median_s,), measured=True), 0.0,
                      random.Random(0))
    windowed = [None if a + lat > until else lat
                for a, lat in zip(result.arrivals, result.latencies, strict=True)]
    last_done = max(a + lat for a, lat in zip(result.arrivals, result.latencies, strict=True))
    bins = trajectory(result.arrivals, windowed, until=until, bin_seconds=VALIDATION_BIN_S)
    return bins, result.swaps, last_done


def validation_trace(measurement: dict, engines: Engines,
                     swap_s: float) -> tuple[ReplayDesign, list[dict]]:
    """The pre-registered validation trace from the first of VALIDATION_SEEDS
    whose predicted replay is feasible, and the check of every draw tried.

    Feasible: the simulator, given the measured curve and `swap_s` (the
    median swap plus its eviction time, as the replay pays both), drains the
    trace within VALIDATION_DRAIN_LIMIT_S, at least MIN_COMPARED_BINS of its
    bins hold a median, and it swaps at least VALIDATION_MIN_SWAPS times. A
    trace failing the first two would be paid for and then refused, by the
    job budget or by the gate's own minimum; one failing the third would
    not exercise the swaps the gate exists to test. Run before any replay, on
    measured inputs: the choice reads predicted feasibility, never a verdict.
    """
    checks = []
    for seed in VALIDATION_SEEDS:
        design = validation_design(measurement, engines.solo, seed)
        bins, swaps, last_done = predict([t for t, _ in design.trace],
                                         [m for _, m in design.trace], design.until, engines,
                                         swap_s)
        ok_bins = sum(b.status == "ok" for b in bins)
        feasible = (last_done <= VALIDATION_DRAIN_LIMIT_S and ok_bins >= MIN_COMPARED_BINS
                    and swaps >= VALIDATION_MIN_SWAPS)
        checks.append({"seed": seed, "requests": len(design.trace), "predicted_swaps": swaps,
                       "predicted_last_done_s": last_done, "ok_bins": ok_bins,
                       "feasible": feasible})
        if feasible:
            return design, checks
    raise NotDecidable(f"no pre-registered validation draw is feasible: {checks}. The gate "
                       "cannot run as registered; this is the owner's decision")


def validate(records, engines: Engines, swap_median_s: float) -> dict:
    """The gate end to end. `outcome` is "passed" only if the latency verdict
    passed and the swap count agrees; a latency verdict that is not evaluable
    stays "not_evaluable", whatever the swaps say."""
    runs = [replay_run(r) for r in records if r.kind == "replay" and r.outcome == "ok"]
    tolerance = tolerance_band(runs)
    first = runs[0]
    predicted, predicted_swaps, _ = predict(first.schedule, first.tenants, first.until, engines,
                                            swap_median_s)
    verdict = compare(predicted, tolerance, min_compared_bins=MIN_COMPARED_BINS,
                      max_miss_fraction=MAX_MISS_FRACTION,
                      edge_tolerance_seconds=EDGE_TOLERANCE_S)
    real_swaps = [r.swaps for r in runs]
    swaps_agree = min(real_swaps) - SWAP_COUNT_SLACK <= predicted_swaps <= max(real_swaps) + SWAP_COUNT_SLACK
    if verdict.outcome == "not_evaluable":
        outcome = "not_evaluable"
    elif verdict.outcome == "passed" and swaps_agree:
        outcome = "passed"
    else:
        outcome = "failed"
    return {
        "outcome": outcome,
        "latency": {"outcome": verdict.outcome, "detail": verdict.detail,
                    "compared": verdict.compared, "agreeing": verdict.agreeing,
                    "max_miss_seconds": verdict.max_miss_seconds},
        "swaps": {"predicted": predicted_swaps, "real": real_swaps, "agree": swaps_agree},
        "swap_median_s": swap_median_s,
        "hosts": [r.host_id for r in runs],
        "requests": len(first.schedule),
        "bins": [{"start": p.start, "end": p.end, "predicted": p.p50, "lo": b.lo, "hi": b.hi,
                  "verdict": v.verdict}
                 for p, b, v in zip(predicted, tolerance, verdict.bins, strict=True)],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_validation.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — 13 tests, including the driver-against-simulator test

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement/validation.py tests/test_placement_validation.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/validation.py tests/test_placement_validation.py
git commit -m "validation: three real replays' band, the simulator's prediction, and the swap timeline"
```

---

## Task 9: Pre-registration step 2, part 2: rendering the values

**Files:**
- Create: `placement/registration.py`
- Create: `scripts/a4_step2.py`
- Test: `tests/test_placement_registration.py`

Once reconnaissance's report and the screen's choice exist, `scripts/a4_step2.py values` applies the rules and writes three things from one computation:
- `placement/registered.py`, the values as literals;
- `data/a4/designs/*.json`, the campaign designs `scripts/a4_measure.py` reads;
- the "Step 2, part 2" section of the pre-registration.

**It refuses to write anything twice.** Its date is required rather than defaulted, because the date is part of the record.

`scripts/a4_step2.py replay` writes the validation trace's design later, after the cell and swap campaigns, under the same rules: it reduces the curve, the surface and the swaps, and keeps the first feasible draw. Every draw it tried goes to `data/a4/designs/replay-check.json`; if none is feasible it stops.

`mismatches` re-derives the values. Part B's `tests/test_placement_registered.py` uses it, so a hand edit to any of the three outputs, or a rule changed after the values, fails.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_registration.py`:

```python
"""Step 2's values: rendered once from the rules, into code, design files and
the pre-registration, and re-derivable from the committed inputs."""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_examples import example_report
from test_placement_inputs_step2 import _cell

from harness.store import JsonlStore
from placement.registration import (
    SECTION,
    design_files,
    mismatches,
    render_doc,
    render_module,
    values,
)
from placement.step2 import measurement_design
from placement_measure.records import A4Run

REPO = Path(__file__).resolve().parents[1]
SCREEN = {"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}
RATE, PROVENANCE = 0.69, "RunPod serverless RTX 4090 flex price, read from the console 2026-10-14"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _values(report=None):
    return values(measurement_design(report or example_report()), SCREEN, rate=RATE,
                  provenance=PROVENANCE)


def test_the_values_are_the_rules_applied_to_the_report_and_the_screen():
    v = _values()
    assert v["MODEL"] == "Qwen/Qwen3-4B" and (v["INPUT_LEN"], v["OUTPUT_LEN"]) == (768, 256)
    assert v["OFFERED_GPUS"] == 2.0 and v["SLO_SWAP_MULTIPLE"] == 4.0
    assert v["SWAP_COLD_STATES"] == (True, False) and v["SLEEP_MEASURED"] is True
    with pytest.raises(ValueError, match="positive"):
        values(measurement_design(example_report()), SCREEN, rate=0.0, provenance=PROVENANCE)
    with pytest.raises(ValueError, match="provenance"):
        values(measurement_design(example_report()), SCREEN, rate=RATE, provenance=" ")


def test_the_module_holds_literals_that_read_back_as_the_values():
    v = _values()
    namespace: dict = {}
    exec(render_module(v, "2026-10-14"), namespace)  # noqa: S102 -- our own rendered literals
    assert {k: namespace[k] for k in v} == v
    assert mismatches({k: namespace[k] for k in v}, v) == []


def test_mismatches_name_every_difference():
    v = _values()
    drifted = {**v, "INPUT_LEN": 1792}
    drifted.pop("HELD_OUT")
    found = mismatches(drifted, v)
    assert len(found) == 2 and found[0].startswith("HELD_OUT") and "1792" in found[1]


def test_the_doc_section_states_every_decision():
    v = _values()
    doc = render_doc(v, "2026-10-14")
    assert doc.startswith(SECTION) and "Committed 2026-10-14" in doc
    for text in ("`Qwen/Qwen3-4B`", "`768` input", "`18,100` tokens", "`(1, 2, 4, 8, 16, 32)`",
                 "`('pair:o12:n24', 'pair:o24:n12')`", "swaps measured cold and warm",
                 "`0.69` dollars", PROVENANCE):
        assert text in doc, text


def test_a_fallback_without_a_solo_reading_says_so():
    report = example_report()
    report["go_no_go"]["primary"]["passed"] = False
    assert "not measured by reconnaissance" in render_doc(_values(report), "2026-10-14")


def test_the_design_files_load_back_as_the_designs():
    measurement = measurement_design(example_report())
    files = design_files(measurement)
    assert set(files) == {"cells", "swaps", "sleep"}
    a4_measure = _load("a4_measure")
    for kind, name in (("cell", "cells"), ("swap", "swaps"), ("sleep", "sleep")):
        path_json = json.loads(json.dumps(files[name]))
        design = a4_measure.DESIGNS[kind](**{
            k: tuple(tuple(x) if isinstance(x, list) else x for x in val)
            if isinstance(val, list) else val for k, val in path_json.items()})
        assert design == measurement[name], name


def _root(tmp_path):
    (tmp_path / "fixtures" / "a4").mkdir(parents=True)
    (tmp_path / "data" / "a4").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "placement").mkdir()
    (tmp_path / "fixtures/a4/recon-report.json").write_text(json.dumps(example_report()))
    (tmp_path / "data/a4/screen.json").write_text(json.dumps(SCREEN))
    # The document as it stands before step 2's values: after publication the
    # repository's own copy has them, and the script refuses a second section.
    doc = (REPO / "docs" / "experiment-a4.md").read_text().split(SECTION)[0]
    (tmp_path / "docs" / "experiment-a4.md").write_text(doc)
    return tmp_path


def test_the_script_writes_everything_once(tmp_path):
    root = _root(tmp_path)
    script = _load("a4_step2")
    args = ["--root", str(root), "values", "--rate", str(RATE), "--provenance", PROVENANCE,
            "--date", "2026-10-14"]
    script.main(args)
    assert (root / "placement/registered.py").read_text() == render_module(_values(), "2026-10-14")
    assert {p.name for p in (root / "data/a4/designs").iterdir()} == {
        "cells.json", "swaps.json", "sleep.json"}
    doc = (root / "docs/experiment-a4.md").read_text()
    assert doc.count(SECTION) == 1 and doc.index("## Step 2, part 1") < doc.index(SECTION)
    with pytest.raises(SystemExit, match="already has"):
        script.main(args)


def _write_measured(root, measurement):
    """Every cell the registered grids need, three valid repeats each, with
    latency 1 + 0.1 x own, and eight cold and eight warm compile-hit swaps."""
    cells = JsonlStore(root / "data/a4/cells.jsonl", A4Run)
    conditions = ([f"solo:o{c}" for c in measurement["solo_levels"]]
                  + [f"pair:o{o}:n{n}" for o in measurement["own_levels"]
                     for n in measurement["neighbour_levels"]])
    for condition in conditions:
        own = int(condition.split(":")[1][1:])
        for i in range(3):
            cells.append(_cell(condition, 1.0 + 0.1 * own, i=i))
    swaps = JsonlStore(root / "data/a4/swaps.jsonl", A4Run)
    for i in range(16):
        cold = i % 2 == 0
        swaps.append(A4Run(
            run_id=f"s{i}", run_index=i, condition=f"swap:a>b:{'cold' if cold else 'warm'}",
            block_index=0, kind="swap", outcome="ok", failure=None, clock_A={}, source="stub",
            output={"swap_s": 30.0 + i, "cache_s": 2.0, "b": {"facts": {"s4b_s": 0.3}}}))


def test_the_replay_design_is_the_first_feasible_draw_on_the_measured_curve(tmp_path):
    root = _root(tmp_path)
    measurement = measurement_design(example_report())
    _write_measured(root, measurement)
    design = _load("a4_step2").main(["--root", str(root), "replay", "--cells",
                                     "data/a4/cells.jsonl", "--swaps", "data/a4/swaps.jsonl"])
    assert tuple(design["tenants"]) == measurement["validation_set"]
    assert design["max_in_flight"] == measurement["solo_levels"][-1]
    saved = json.loads((root / "data/a4/designs/replay.json").read_text())
    assert saved == json.loads(json.dumps(design))
    check = json.loads((root / "data/a4/designs/replay-check.json").read_text())
    # The cold compile-hit swaps are 30, 32, ..., 44 s: median 37, plus 2 s of eviction.
    assert check["swap_s"] == pytest.approx(39.0)
    assert check["checks"][-1]["feasible"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_registration.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.registration'`

- [ ] **Step 3: Write the rendering**

Create `placement/registration.py`:

```python
"""Pre-registration step 2, part 2: the values, rendered from the rules.

`placement.step2` fixes the rules. Once reconnaissance's report and the
screen's choice exist, `scripts/a4_step2.py` applies the rules and writes
three things from the one set of values this module computes:

- `placement/registered.py`, the values as literals, so a reader sees every
  one without running anything;
- `data/a4/designs/*.json`, the campaign designs `scripts/a4_measure.py` reads;
- the "Step 2, part 2" section of `docs/experiment-a4.md`.

`mismatches` re-derives the values and names every difference, so
`tests/test_placement_registered.py` fails if any of the three drifts from the
rules applied to the committed inputs.
"""

import dataclasses
import math
import pprint

__all__ = ["design_files", "mismatches", "render_doc", "render_module", "values"]

SECTION = "## Step 2, part 2 — values, fixed before the first measurement run"


def values(measurement: dict, screen: dict, *, rate: float, provenance: str) -> dict:
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError(f"the GPU hourly rate must be finite and positive, got {rate!r}")
    if not provenance.strip():
        raise ValueError("the rate needs its provenance: where and when it was read")
    shape = measurement["shape"]
    swaps = measurement["swaps"]
    chosen = screen["chosen"]
    return {
        "MODEL": measurement["model"],
        "INPUT_LEN": shape["input_len"],
        "OUTPUT_LEN": shape["output_len"],
        "KV_SPLIT_TOKENS": measurement["kv_split_tokens"],
        "KV_SOLO_TOKENS": measurement["kv_solo_tokens"],
        "SPLIT_CEILING": shape["split_ceiling"],
        "SOLO_CEILING": measurement["solo_ceiling"],
        "OWN_LEVELS": tuple(measurement["own_levels"]),
        "NEIGHBOUR_LEVELS": tuple(measurement["neighbour_levels"]),
        "SOLO_LEVELS": tuple(measurement["solo_levels"]),
        "HELD_OUT": tuple(measurement["held_out"]),
        "COMPILE_SHARED": measurement["compile_shared"],
        "EVICTION_WORKS": measurement["eviction_works"],
        "SLEEP_MEASURED": measurement["sleep"] is not None,
        "VALIDATION_SET": tuple(measurement["validation_set"]),
        "SWAP_PAIRS": tuple(tuple(p) for p in swaps.pairs),
        "SWAP_COLD_STATES": tuple(swaps.cold_states),
        "SWAP_REPEATS": swaps.repeats,
        "OFFERED_GPUS": chosen["offered_gpus"],
        "SLO_SWAP_MULTIPLE": chosen["slo_swap_multiple"],
        "GPU_HOURLY_RATE": rate,
        "RATE_PROVENANCE": provenance,
    }


def render_module(v: dict, date: str) -> str:
    lines = [
        '"""Pre-registration step 2, part 2: the values, committed ' + date + ",",
        "before the first measurement run.",
        "",
        "Generated by scripts/a4_step2.py from fixtures/a4/recon-report.json and",
        "data/a4/screen.json under the rules in placement/step2.py. Literals only.",
        "tests/test_placement_registered.py re-derives every value from those inputs",
        'and fails on any difference."""',
        "",
    ]
    # pformat wraps long tuples across lines; its output is still a literal.
    lines += [f"{name} = {pprint.pformat(value, width=96)}" for name, value in v.items()]
    return "\n".join(lines) + "\n"


def _solo(v: dict) -> str:
    if v["KV_SOLO_TOKENS"] is None:
        return "not measured by reconnaissance, so the solo grid spans the full range"
    return f"`{v['KV_SOLO_TOKENS']:,}` tokens, ceiling `{v['SOLO_CEILING']}`"


def render_doc(v: dict, date: str) -> str:
    pairs = ", ".join(f"{a} to {b}" for a, b in v["SWAP_PAIRS"])
    states = " and ".join("cold" if c else "warm" for c in v["SWAP_COLD_STATES"])
    return "\n".join([
        SECTION,
        "",
        f"Committed {date}. Every value below is the rules of part 1 applied to",
        "`fixtures/a4/recon-report.json` and `data/a4/screen.json`;",
        "`placement/registered.py` holds them as code, and",
        "`tests/test_placement_registered.py` re-derives them.",
        "",
        f"- **Model class:** `{v['MODEL']}`.",
        f"- **Request shape:** `{v['INPUT_LEN']}` input and `{v['OUTPUT_LEN']}` output tokens.",
        (f"- **KV capacity:** split `{v['KV_SPLIT_TOKENS']:,}` tokens, ceiling "
         f"`{v['SPLIT_CEILING']}` requests; solo {_solo(v)}."),
        (f"- **Co-located grid:** own levels `{v['OWN_LEVELS']}`, neighbour levels "
         f"`{v['NEIGHBOUR_LEVELS']}`; held-out cells `{v['HELD_OUT']}`."),
        f"- **Solo grid:** `{v['SOLO_LEVELS']}`.",
        f"- **Compile cache shared across the 4B checkpoints:** `{v['COMPILE_SHARED']}`.",
        f"- **Page-cache eviction works:** `{v['EVICTION_WORKS']}`; swaps measured {states}.",
        f"- **Sleep-mode arm measured:** `{v['SLEEP_MEASURED']}`.",
        f"- **Validation set:** `{v['VALIDATION_SET']}`.",
        f"- **Swap campaign:** {pairs}; `{v['SWAP_REPEATS']}` repeats per pair and state.",
        (f"- **Screen's choice:** offered load `{v['OFFERED_GPUS']}` GPUs of saturation; SLO "
         f"`{v['SLO_SWAP_MULTIPLE']}` times the simulated swap's median."),
        (f"- **GPU hourly rate:** `{v['GPU_HOURLY_RATE']}` dollars, {v['RATE_PROVENANCE']}. "
         "Artifact 5 reads the same rate from here."),
        "",
    ])


def design_files(measurement: dict) -> dict[str, dict]:
    """The campaign designs as the JSON `scripts/a4_measure.py --design` reads."""
    out = {"cells": dataclasses.asdict(measurement["cells"]),
           "swaps": dataclasses.asdict(measurement["swaps"])}
    if measurement["sleep"] is not None:
        out["sleep"] = dataclasses.asdict(measurement["sleep"])
    return out


def mismatches(registered: dict, expected: dict) -> list[str]:
    """Every name whose committed value differs from the re-derived one, or is
    missing from either side."""
    names = sorted(set(registered) | set(expected))
    return [f"{n}: registered {registered.get(n)!r}, rules give {expected.get(n)!r}"
            for n in names if registered.get(n) != expected.get(n)]
```

- [ ] **Step 4: Write the script**

Create `scripts/a4_step2.py`:

```python
"""Write pre-registration step 2's values from the rules. Spends nothing.

    .venv/bin/python scripts/a4_step2.py values --rate <dollars per GPU-hour> \\
        --provenance "<where and when the rate was read>" --date YYYY-MM-DD
    .venv/bin/python scripts/a4_step2.py replay --cells data/a4/cells.jsonl [--cells ...] \\
        [--swaps data/a4/swaps.jsonl]

`values` runs after the reconnaissance record and the screen are committed,
and before the first measurement run. It reads fixtures/a4/recon-report.json
and data/a4/screen.json, applies placement/step2.py's rules, and writes
placement/registered.py, data/a4/designs/{cells,swaps[,sleep]}.json and the
"Step 2, part 2" section of docs/experiment-a4.md. It refuses to overwrite.

`replay` runs after the cell and swap campaigns. The validation trace's load
is a fraction of the measured solo saturation, and which pre-registered draw
is used depends on whether the simulator, given the measured curve and swaps,
predicts its replay can finish within a job and genuinely swaps. So it reduces
both, writes data/a4/designs/replay.json, and records every draw it tried in
data/a4/designs/replay-check.json. If no draw is feasible it stops.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.stats import median
from placement.inputs import (
    colocated_surface,
    eviction_seconds,
    load_records,
    solo_curve,
    swap_distribution,
)
from placement.registration import SECTION, design_files, render_doc, render_module, values
from placement.sim import Engines
from placement.step2 import CELL_MIN_VALID, measurement_design
from placement.validation import validation_trace

REPO = Path(__file__).resolve().parents[1]
REPORT = Path("fixtures/a4/recon-report.json")
SCREEN = Path("data/a4/screen.json")
MODULE = Path("placement/registered.py")
DESIGNS = Path("data/a4/designs")
DOC = Path("docs/experiment-a4.md")


def _write_new(path: Path, text: str) -> None:
    if path.exists():
        raise SystemExit(f"{path} exists; step 2's values are written once. Remove it only if "
                         "nothing has been measured under it, and say so in the commit")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"wrote {path}")


def write_values(root: Path, rate: float, provenance: str, date: str) -> dict:
    report = json.loads((root / REPORT).read_text())
    screen = json.loads((root / SCREEN).read_text())
    measurement = measurement_design(report)
    v = values(measurement, screen, rate=rate, provenance=provenance)
    doc = (root / DOC).read_text()
    if SECTION in doc:
        raise SystemExit(f"{DOC} already has the step 2 values section")
    _write_new(root / MODULE, render_module(v, date))
    for name, design in design_files(measurement).items():
        _write_new(root / DESIGNS / f"{name}.json", json.dumps(design, indent=1) + "\n")
    (root / DOC).write_text(doc.rstrip("\n") + "\n\n" + render_doc(v, date))
    print(f"appended the step 2 values section to {DOC}")
    return v


def replay_swap_seconds(measurement: dict, swaps) -> float:
    """What one swap costs the replay: the median simulated swap, plus the
    page-cache eviction a cold replay pays before each swap-in."""
    cold = measurement["eviction_works"]
    simulated = swap_distribution(swaps, cold=cold, compiled=False)
    return median(list(simulated.samples)) + eviction_seconds(swaps, cold=cold)


def write_replay(root: Path, cell_stores: list[str], swap_stores: list[str]) -> dict:
    report = json.loads((root / REPORT).read_text())
    measurement = measurement_design(report)
    cells = load_records([root / s for s in cell_stores])
    warm = {"min_repeats": CELL_MIN_VALID, "require_warm_compile": True}
    curve = solo_curve(cells, levels=measurement["solo_levels"], **warm)
    surface = colocated_surface(cells, own_levels=measurement["own_levels"],
                                neighbour_levels=measurement["neighbour_levels"], **warm)
    swap_s = replay_swap_seconds(measurement, load_records([root / s for s in swap_stores]))
    trace, checks = validation_trace(measurement, Engines(curve, surface), swap_s)
    design = dataclasses.asdict(trace)
    _write_new(root / DESIGNS / "replay.json", json.dumps(design, indent=1) + "\n")
    _write_new(root / DESIGNS / "replay-check.json",
               json.dumps({"swap_s": swap_s, "checks": checks}, indent=1) + "\n")
    for c in checks:
        print(f"  seed {c['seed']}: {c['requests']} requests, {c['predicted_swaps']} swaps, last "
              f"done {c['predicted_last_done_s']:.0f} s, {c['ok_bins']} bins with a median: "
              f"{'feasible' if c['feasible'] else 'not feasible'}")
    print(f"validation trace: {len(design['trace'])} requests over {design['until']:.0f} s, "
          f"cap {design['max_in_flight']} in flight, cold={design['cold']}")
    return design


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(REPO))
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("values")
    v.add_argument("--rate", type=float, required=True)
    v.add_argument("--provenance", required=True)
    # Required, not today's date: the date is part of the record, and a
    # default would stamp whatever day the script happened to be re-run.
    v.add_argument("--date", required=True)
    r = sub.add_parser("replay")
    r.add_argument("--cells", action="append", required=True)
    r.add_argument("--swaps", action="append")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.command == "values":
        return write_values(root, args.rate, args.provenance, args.date)
    return write_replay(root, args.cells, args.swaps or ["data/a4/swaps.jsonl"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_registration.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — 8 tests

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check placement/registration.py scripts/a4_step2.py tests/test_placement_registration.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement/registration.py scripts/a4_step2.py tests/test_placement_registration.py
git commit -m "prereg: render step 2's values into code, designs and the document, once"
```

---

## Task 10: The analysis: every published number about the sweep

**Files:**
- Create: `placement/analysis.py`
- Modify: `scripts/a4_sweep.py`
- Create: `tests/a4_evaluations.py`
- Test: `tests/test_placement_analysis.py`

This builds August §8's metrics, the amendment's sizing and crossover, and the money view, as plain JSON-ready dicts. Per grid point and strategy, at the fleet each is sized to, it reports:
- cost, monthly, per tenant and per million output tokens;
- aggregate p99 with a bootstrap interval;
- per-decile p99 and SLO breach;
- hit rate and swaps per hour.

Per regime, it reports the decision rule as skew ranges, the gaps no range may claim (a point not evaluable, or where no strategy meets the SLO), and the crossover estimate. A run of points never spans a gap, so "s = 0.6–1.0: co-locate" cannot cover a point in the middle that said nothing.

**Two views carry the fairness argument:**
- `aggregate_rule` sizes on the aggregate p99 instead, and reports what the coldest decile gets at that cheaper fleet;
- `fairness` compares swap and co-locate decile by decile at a common fleet, paired by repetition, through `harness.stats.bootstrap_paired_median_diff` (amendment §8).

**One edit to the sweep script.** Its cached evaluation becomes `evaluations_for`, so the analysis reads the same evaluations the sweep's summary does.

**The tests use hand-built evaluations whose sizing is known in advance.** Every family has every M from its smallest to dedicate's, as a real one does.

- [ ] **Step 1: Create the hand-built evaluations the tests share**

Create `tests/a4_evaluations.py`:

```python
"""Hand-built evaluations for plan 3's analysis, cost-file and figure tests.

Not a test module. Every configuration's numbers are chosen so the sizing is
known in advance: a configuration "meets" an SLO of 10 s when its p99s are 5 s
and misses it when they are 50 s.
"""

from placement.design import Design
from placement.evaluate import ConfigOutcome, GridPoint, PointEvaluation
from placement.money import Assumptions

REPS = 20
SLO = 10.0
RATE = Assumptions(gpu_hourly_rate=0.69, provenance="test rate")
DESIGN = Design(n_models=20, offered_gpus=2.0, hot_fraction=0.7, warmup=100.0, mean_burst=120.0,
                duty=0.2, skews=(0.6, 1.0), regimes=("spread", "bursty"), repetitions=REPS,
                slo_seconds=SLO, pilot_traces=1200, seed=17, preregistered=True)


def config(strategy, m, *, cold_p99=5.0, warm_p99=5.0, aggregate=4.0, breach=0.0, hits=95,
           swaps=0, jitter=True):
    """A configuration whose coldest decile has p99 `cold_p99` and the others
    `warm_p99`, varying by a few hundredths across repetitions so intervals
    have width."""
    def wobble(x, r):
        return x + (0.01 * (r % 5) if jitter else 0.0)

    return ConfigOutcome(
        strategy=strategy, m=m,
        decile_p99s=tuple((wobble(warm_p99, r),) * 9 + (wobble(cold_p99, r),) for r in range(REPS)),
        swaps=(swaps,) * REPS, extrapolated=(0,) * REPS,
        aggregate_p99s=tuple(wobble(aggregate, r) for r in range(REPS)),
        window_swaps=(swaps,) * REPS,
        hits=(hits,) * REPS, requests=(100,) * REPS,
        decile_breach=tuple((0.0,) * 9 + (breach,) for _ in range(REPS)),
    )


def evaluation(s, regime, outcomes, *, counts=600):
    return PointEvaluation(point=GridPoint(s, regime, 3700.0), outcomes=outcomes,
                           counts=((counts,) * 10,) * REPS)


def _family(strategy, ms, meets_from, passing=None, **failing):
    """Every M from `ms`, as a real family has: configurations from
    `meets_from` meet the SLO with `passing`'s numbers, and those below miss
    it with `failing`'s."""
    return tuple(config(strategy, m, **(passing or {})) if m >= meets_from
                 else config(strategy, m, **failing) for m in ms)


def swap_cheap(s, regime):
    """Dedicate at 10; swap meets the SLO from 6; co-locate only at 10. Swap at
    4 and 5 meets the aggregate but not the coldest decile."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 6, {"swaps": 12, "hits": 90}, cold_p99=50.0,
                        breach=0.3, swaps=40),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def dedicate_only(s, regime):
    """Swap and co-locate meet the SLO only at dedicate's 10: a three-way tie."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 10, cold_p99=50.0, warm_p99=50.0, aggregate=50.0),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def swap_dominated(s, regime):
    """Swap misses the SLO even at dedicate's 10."""
    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 10),),
        "swap": _family("swap", range(4, 11), 11, cold_p99=50.0, warm_p99=50.0, aggregate=50.0),
        "colocate": _family("colocate", range(7, 11), 10, cold_p99=50.0, warm_p99=50.0,
                            aggregate=50.0),
    })


def sweep():
    """Spread: a three-way tie at s=0.6, swap at s=1.0. Bursty: swap at both."""
    return [dedicate_only(0.6, "spread"), swap_cheap(1.0, "spread"),
            swap_cheap(0.6, "bursty"), swap_cheap(1.0, "bursty")]


SKEWS = (0.6, 0.8, 1.0, 1.25, 1.5, 2.0)


def _point(s, regime, swap_from, colocate_from):
    """Swap meets the SLO from `swap_from` GPUs, co-locate from
    `colocate_from`; both families run up to dedicate's 12. Latency falls as
    the fleet grows, so the aggregate p99 has some shape to draw."""
    def family(strategy, ms, meets_from):
        return tuple(
            config(strategy, m, cold_p99=5.0 + (12 - m) * 0.4, warm_p99=3.0 + (12 - m) * 0.2,
                   aggregate=2.5 + (12 - m) * 0.15 + s, hits=90, swaps=20 - m)
            if m >= meets_from else
            config(strategy, m, cold_p99=40.0, breach=0.25, aggregate=3.0 + s, swaps=60)
            for m in ms)

    return evaluation(s, regime, {
        "dedicate": (config("dedicate", 12, aggregate=2.0 + s, cold_p99=4.0),),
        "swap": family("swap", range(5, 13), swap_from),
        "colocate": family("colocate", range(8, 13), colocate_from),
    })


def rich_sweep():
    """Six skews per regime, for drawing figures with some shape to them:
    swap thrashes at low skew in the spread regime and wins earlier when
    arrivals are bursty."""
    spread = {0.6: (13, 12), 0.8: (12, 11), 1.0: (11, 10), 1.25: (9, 10), 1.5: (7, 10), 2.0: (6, 9)}
    bursty = {0.6: (11, 11), 0.8: (9, 10), 1.0: (8, 10), 1.25: (7, 10), 1.5: (6, 9), 2.0: (5, 9)}
    return ([_point(s, "spread", *spread[s]) for s in SKEWS]
            + [_point(s, "bursty", *bursty[s]) for s in SKEWS])
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_placement_analysis.py`:

```python
"""The analysis on hand-built evaluations whose sizing is known in advance."""

import dataclasses

import pytest
from a4_evaluations import (
    DESIGN,
    RATE,
    REPS,
    SLO,
    config,
    evaluation,
    swap_cheap,
    sweep,
)

from placement.analysis import analyse, fairness, point_view, size_by_aggregate
from placement.money import HOURS_PER_MONTH, SECONDS_PER_HOUR, monthly_cost

TOTAL_RATE, OUTPUT_LEN = 5.0, 256
REFERENCE = {"regime": "bursty", "s": 1.0}


def _view(e):
    return point_view(e, DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE)


def test_the_aggregate_sizes_a_fleet_the_coldest_decile_does_not_accept():
    e = swap_cheap(1.0, "spread")
    reps = list(range(REPS))
    assert size_by_aggregate(e.outcomes["swap"], reps, SLO) == 4
    view = _view(e)
    assert view["sized"] == {"dedicate": 10, "swap": 6, "colocate": 10}
    rule = view["aggregate_rule"]["swap"]
    assert rule["m"] == 4 and rule["coldest_decile_breach"] == 0.3
    assert rule["coldest_decile_p99"] == pytest.approx(50.02)
    assert rule["decile_p99"][0] == pytest.approx(5.02) and rule["decile_p99"][9] == rule[
        "coldest_decile_p99"]


def test_costs_are_the_sized_fleet_priced_three_ways():
    swap = _view(swap_cheap(1.0, "spread"))["strategies"]["swap"]
    cost = monthly_cost(6, RATE)
    assert swap["monthly_cost"] == pytest.approx(cost)
    assert swap["cost_per_tenant_month"] == pytest.approx(cost / 20)
    tokens = TOTAL_RATE * OUTPUT_LEN * HOURS_PER_MONTH * SECONDS_PER_HOUR
    assert swap["cost_per_million_tokens"] == pytest.approx(cost / tokens * 1e6)


def test_latency_hit_rate_and_swaps_are_read_at_the_sized_fleet():
    swap = _view(swap_cheap(1.0, "spread"))["strategies"]["swap"]
    ap = swap["aggregate_p99"]
    assert ap["lo"] <= ap["point"] <= ap["hi"] and ap["point"] == pytest.approx(4.02)
    assert swap["hit_rate"] == pytest.approx(0.9)
    # 12 swaps in the window from warm-up (100 s) to the end (3700 s).
    assert swap["swaps_per_hour"] == pytest.approx(12 / 3600.0 * 3600)
    assert swap["decile_p99"][9] == pytest.approx(5.02) and swap["decile_breach"][9] == 0.0


def test_a_cheapest_tie_and_the_dollar_gap_are_reported():
    view = _view(swap_cheap(1.0, "spread"))
    assert view["cheapest"] == ["swap"]
    assert view["dedicate_over_cheapest_per_month"] == pytest.approx(
        monthly_cost(10, RATE) - monthly_cost(6, RATE))


def test_a_point_under_the_floor_is_not_evaluable():
    thin = evaluation(1.0, "spread", swap_cheap(1.0, "spread").outcomes, counts=499)
    assert _view(thin) == {"regime": "spread", "s": 1.0, "window_s": 3600.0, "evaluable": False}


def test_fairness_pairs_by_repetition_at_the_larger_sized_fleet():
    e = evaluation(1.0, "bursty", {
        "dedicate": (config("dedicate", 10),),
        "swap": (config("swap", 6, cold_p99=6.0), config("swap", 8, cold_p99=6.0)),
        "colocate": (config("colocate", 8, cold_p99=5.0),),
    })
    result = fairness(e, {"dedicate": 10, "swap": 6, "colocate": 8})
    assert result["m"] == 8
    # Every repetition's coldest-decile difference is exactly 1.0 s.
    assert result["deciles"][9]["point"] == pytest.approx(1.0)
    assert result["deciles"][9]["lo"] == pytest.approx(1.0)
    assert result["deciles"][0]["point"] == pytest.approx(0.0)
    assert fairness(e, {"dedicate": 10, "swap": None, "colocate": 8}) is None


def test_the_full_analysis_states_the_decision_rule_and_the_crossover():
    result = analyse(sweep(), DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                     reference=REFERENCE)
    spread = result["regimes"]["spread"]
    # At s = 0.6 swap and co-locate only meet the SLO at dedicate's M: a
    # three-way tie, reported as a tie (amendment §8), not as a win for dedicate.
    assert spread["decision_rule"] == [
        {"from_s": 0.6, "to_s": 0.6, "cheapest": ["colocate", "dedicate", "swap"]},
        {"from_s": 1.0, "to_s": 1.0, "cheapest": ["swap"]},
    ]
    assert spread["crossover"]["between"] == [[0.6, 1.0]]
    c = spread["crossover"]
    assert c["no_crossing"] + c["one_crossing"] + c["many_crossings"] == c["iterations"]
    bursty = result["regimes"]["bursty"]
    assert bursty["decision_rule"] == [{"from_s": 0.6, "to_s": 1.0, "cheapest": ["swap"]}]
    assert bursty["crossover"]["between"] == []
    assert result["fairness"]["m"] == 10  # swap sized 6, co-locate 10
    assert result["rate"] == {"gpu_hourly_rate": 0.69, "provenance": "test rate"}
    assert result["design"]["skews"] == [0.6, 1.0]


def test_a_reference_that_is_not_a_grid_point_is_refused():
    with pytest.raises(ValueError, match="matches 0"):
        analyse(sweep(), DESIGN, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                reference={"regime": "bursty", "s": 1.5})


def test_the_decision_rule_never_spans_a_point_that_said_nothing():
    """Swap is cheapest at 0.6 and 1.0, but 0.8 is not evaluable: two runs
    and a gap, not "s = 0.6-1.0: swap"."""
    thin = evaluation(0.8, "spread", swap_cheap(0.8, "spread").outcomes, counts=499)
    evaluations = [swap_cheap(0.6, "spread"), thin, swap_cheap(1.0, "spread"),
                   *[e for e in sweep() if e.point.regime == "bursty"]]
    design = dataclasses.replace(DESIGN, skews=(0.6, 0.8, 1.0))
    result = analyse(evaluations, design, total_rate=TOTAL_RATE, output_len=OUTPUT_LEN, rate=RATE,
                     reference=REFERENCE)
    spread = result["regimes"]["spread"]
    assert spread["decision_rule"] == [
        {"from_s": 0.6, "to_s": 0.6, "cheapest": ["swap"]},
        {"from_s": 1.0, "to_s": 1.0, "cheapest": ["swap"]},
    ]
    assert spread["gaps"] == [{"s": 0.8, "reason": "not evaluable"}]


def test_a_point_where_nothing_meets_the_slo_is_a_gap():
    import placement.analysis as module

    view = {"s": 1.0, "evaluable": True, "cheapest": []}
    segments, gaps = module._segments([view])
    assert segments == [] and gaps == [{"s": 1.0, "reason": "no strategy meets the SLO"}]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_analysis.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.analysis'`

- [ ] **Step 4: Write the analysis**

Create `placement/analysis.py`:

```python
"""Every published number about the sweep, from its evaluations.

August §8's metrics, the amendment's sizing and crossover (§7, §8), and the
money view, as plain JSON-ready dicts. `scripts/a4_analyse.py` writes them to
`data/a4/analysis.json`; the figures, the cost file and the post read that
file and recompute nothing, as artifact 1's figures read `data/analysis.json`.

Per grid point and strategy, at the fleet each strategy is sized to:

- cost: monthly, per tenant, and per million output tokens at the offered load;
- aggregate p99, the median across repetitions with a bootstrap interval;
- per-decile p99 and SLO breach, medians across repetitions;
- hit rate (requests whose model was resident on arrival) and swaps per hour.

Two views carry the post's fairness argument (August §8, "Averages hide
tenants"). `aggregate_rule` sizes every strategy on the aggregate p99 instead
of the per-decile one, and reports what the coldest decile gets at that
cheaper fleet. `fairness` compares swap and co-locate decile by decile at a
common fleet size, paired by repetition, with `harness.stats`'s paired
bootstrap (amendment §8).
"""

from collections.abc import Sequence

from harness.stats import bootstrap_median_ci, bootstrap_paired_median_diff, median
from placement.crossover import cheapest, estimate_crossover
from placement.design import Design
from placement.evaluate import ConfigOutcome, PointEvaluation
from placement.fleet import STRATEGIES
from placement.money import HOURS_PER_MONTH, SECONDS_PER_HOUR, Assumptions, monthly_cost
from placement.sizing import sized_fleet
from placement.traffic import DECILES

__all__ = ["analyse", "fairness", "point_view", "size_by_aggregate"]

BOOTSTRAP_ITERATIONS = 10_000
CROSSOVER_ITERATIONS = 2000
COLDEST = DECILES - 1


def size_by_aggregate(outcomes: Sequence[ConfigOutcome], reps: Sequence[int], slo: float) -> int | None:
    """The smallest M whose median-across-repetitions AGGREGATE p99 meets the
    SLO: what a fleet dashboard would size to. None if none does."""
    for outcome in outcomes:
        values = [outcome.aggregate_p99s[r] for r in reps]
        if any(v is None for v in values):
            raise ValueError(f"{outcome.strategy} at M={outcome.m} has a repetition under the "
                             "aggregate p99 floor; it cannot be sized on the aggregate")
        if median(values) <= slo:
            return outcome.m
    return None


def _at(outcomes: Sequence[ConfigOutcome], m: int) -> ConfigOutcome:
    for outcome in outcomes:
        if outcome.m == m:
            return outcome
    raise ValueError(f"no configuration at M={m}")


def _median_or_none(values):
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _strategy_view(c: ConfigOutcome, reps, *, warmup: float, until: float, n_models: int,
                   tokens_per_month: float, rate: Assumptions, seed: int) -> dict:
    aggregate = [c.aggregate_p99s[r] for r in reps]
    ci = bootstrap_median_ci(aggregate, iterations=BOOTSTRAP_ITERATIONS, seed=seed)
    cost = monthly_cost(c.m, rate)
    return {
        "m": c.m,
        "monthly_cost": cost,
        "cost_per_tenant_month": cost / n_models,
        "cost_per_million_tokens": cost / tokens_per_month * 1e6,
        "aggregate_p99": {"point": median(aggregate), "lo": ci["lo"], "hi": ci["hi"]},
        "decile_p99": [median([c.decile_p99s[r][d] for r in reps]) for d in range(DECILES)],
        "decile_breach": ([_median_or_none([c.decile_breach[r][d] for r in reps])
                           for d in range(DECILES)] if c.decile_breach else None),
        "hit_rate": sum(c.hits[r] for r in reps) / sum(c.requests[r] for r in reps),
        # Swaps begun inside the measured window, over its length: warm-up
        # and drain-out swaps are artefacts of a finite run (amendment §7).
        "swaps_per_hour": median([c.window_swaps[r] / (until - warmup) * SECONDS_PER_HOUR
                                  for r in reps]),
        "extrapolated_dispatches": sum(c.extrapolated[r] for r in reps),
    }


def point_view(e: PointEvaluation, design: Design, *, total_rate: float, output_len: int,
               rate: Assumptions) -> dict:
    reps = list(range(e.repetitions))
    base = {"regime": e.point.regime, "s": e.point.s, "window_s": e.point.until - design.warmup}
    sized = sized_fleet(e, reps, design.slo_seconds)
    if sized is None:
        return {**base, "evaluable": False}
    tokens_per_month = total_rate * output_len * HOURS_PER_MONTH * SECONDS_PER_HOUR
    views = {}
    for i, strategy in enumerate(STRATEGIES):
        m = sized[strategy]
        views[strategy] = None if m is None else _strategy_view(
            _at(e.outcomes[strategy], m), reps, warmup=design.warmup, until=e.point.until,
            n_models=design.n_models,
            tokens_per_month=tokens_per_month, rate=rate, seed=design.seed + i)
    aggregate_rule = {}
    for strategy in STRATEGIES:
        m = size_by_aggregate(e.outcomes[strategy], reps, design.slo_seconds)
        if m is None:
            aggregate_rule[strategy] = None
            continue
        c = _at(e.outcomes[strategy], m)
        breach = ([c.decile_breach[r][COLDEST] for r in reps] if c.decile_breach else [])
        deciles = [median([c.decile_p99s[r][d] for r in reps]) for d in range(DECILES)]
        aggregate_rule[strategy] = {
            "m": m,
            "decile_p99": deciles,
            "coldest_decile_p99": deciles[COLDEST],
            "coldest_decile_breach": _median_or_none(breach),
        }
    best = sorted(cheapest(sized))
    feasible = [m for m in sized.values() if m is not None]
    return {
        **base, "evaluable": True, "sized": sized, "cheapest": best, "strategies": views,
        "aggregate_rule": aggregate_rule,
        "dedicate_over_cheapest_per_month": (
            None if sized["dedicate"] is None or not feasible
            else monthly_cost(sized["dedicate"], rate) - monthly_cost(min(feasible), rate)),
    }


def fairness(e: PointEvaluation, sized: dict, *, a: str = "swap", b: str = "colocate",
             seed: int = 0) -> dict | None:
    """Per-decile p99 of `a` minus `b` at a common fleet size, paired by
    repetition. The common size is the larger of the two sized fleets, which
    both families contain because both reach dedicate's M. None when either
    strategy is dominated."""
    if sized.get(a) is None or sized.get(b) is None:
        return None
    m = max(sized[a], sized[b])
    ca, cb = _at(e.outcomes[a], m), _at(e.outcomes[b], m)
    reps = range(e.repetitions)
    deciles = []
    for d in range(DECILES):
        units = [[{"arm": a, "p99": ca.decile_p99s[r][d]}, {"arm": b, "p99": cb.decile_p99s[r][d]}]
                 for r in reps]
        deciles.append(bootstrap_paired_median_diff(units, a, b, value="p99",
                                                    iterations=BOOTSTRAP_ITERATIONS, seed=seed + d))
    return {"m": m, "a": a, "b": b, "deciles": deciles}


def _segments(points: list[dict]) -> tuple[list[dict], list[dict]]:
    """The decision rule: runs of adjacent grid points with the same cheapest
    set, as skew ranges, and the points no run may claim.

    A point that is not evaluable, or where no strategy meets the SLO, ends a
    run and is listed as a gap. The crossover estimator skips such points too
    (`placement.crossover.crossings` locates only points with a cheapest set),
    but a rule stated as "s = 0.6-1.0: co-locate" must not cover a point in
    the middle that said nothing."""
    segments: list[dict] = []
    gaps: list[dict] = []
    current: dict | None = None
    for p in points:
        if not p["evaluable"] or not p["cheapest"]:
            gaps.append({"s": p["s"], "reason": "not evaluable" if not p["evaluable"]
                         else "no strategy meets the SLO"})
            current = None
            continue
        if current is not None and current["cheapest"] == p["cheapest"]:
            current["to_s"] = p["s"]
        else:
            current = {"from_s": p["s"], "to_s": p["s"], "cheapest": p["cheapest"]}
            segments.append(current)
    return segments, gaps


def analyse(evaluations: Sequence[PointEvaluation], design: Design, *, total_rate: float,
            output_len: int, rate: Assumptions, reference: dict) -> dict:
    regimes = {}
    for regime in design.regimes:
        chosen = sorted((e for e in evaluations if e.point.regime == regime),
                        key=lambda e: e.point.s)
        points = [point_view(e, design, total_rate=total_rate, output_len=output_len, rate=rate)
                  for e in chosen]
        estimate = estimate_crossover(chosen, design.slo_seconds,
                                      iterations=CROSSOVER_ITERATIONS, seed=design.seed)
        skews = [e.point.s for e in chosen]
        segments, gaps = _segments(points)
        regimes[regime] = {
            "points": points,
            "decision_rule": segments,
            "gaps": gaps,
            "crossover": {
                "between": [[skews[i], skews[j]] for i, j in estimate.point],
                "interval_lower_point": (None if estimate.interval is None
                                         else [skews[i] for i in estimate.interval]),
                "no_crossing": estimate.no_crossing, "one_crossing": estimate.one_crossing,
                "many_crossings": estimate.many_crossings, "iterations": estimate.iterations,
            },
        }
    ref = [e for e in evaluations
           if e.point.regime == reference["regime"] and e.point.s == reference["s"]]
    if len(ref) != 1:
        raise ValueError(f"the reference point {reference} matches {len(ref)} grid points, not 1")
    ref_sized = sized_fleet(ref[0], list(range(ref[0].repetitions)), design.slo_seconds)
    return {
        "design": {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(design).items()},
        "rate": {"gpu_hourly_rate": rate.gpu_hourly_rate, "provenance": rate.provenance},
        "total_rate_rps": total_rate,
        "output_len": output_len,
        "reference": dict(reference),
        "regimes": regimes,
        "fairness": None if ref_sized is None else fairness(ref[0], ref_sized, seed=design.seed),
    }
```

- [ ] **Step 5: Expose the sweep's cached evaluation**

In `scripts/a4_sweep.py`, replace:

```python
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
        evaluations = evaluate_grid(
            grid(design, scenario), scenario, engines, swap_time, design.repetitions,
            design.seed, design.slo_seconds, workers,
        )
        dump_evaluations(cache, evaluations)
        print(f"cached {len(evaluations)} grid points to {cache}")

    everything
```

with:

```python
def scenario_for(design: Design, engines: Engines) -> Scenario:
    return Scenario(
        n_models=design.n_models, offered_gpus=design.offered_gpus,
        saturation_rps=saturation_rps(engines.solo), hot_fraction=design.hot_fraction,
        warmup=design.warmup, mean_burst=design.mean_burst, duty=design.duty,
    )


def evaluations_for(design: Design, engines: Engines, swap_time: EmpiricalDistribution,
                    out: Path, workers: int, refresh: bool = False) -> list:
    """The grid's evaluations, from the cache when every input matches.
    `scripts/a4_analyse.py` reads the sweep through here, so the analysis and
    the summary are computed from the same evaluations."""
    out.mkdir(parents=True, exist_ok=True)
    scenario = scenario_for(design, engines)
    cache = out / f"evaluations-{_cache_key(design, engines, swap_time)}.json"
    if cache.exists() and not refresh:
        print(f"reusing {cache} (--refresh to re-run)")
        return load_evaluations(cache)
    evaluations = evaluate_grid(
        grid(design, scenario), scenario, engines, swap_time, design.repetitions,
        design.seed, design.slo_seconds, workers,
    )
    dump_evaluations(cache, evaluations)
    print(f"cached {len(evaluations)} grid points to {cache}")
    return evaluations


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
    evaluations = evaluations_for(design, engines, swap_time, out, workers, refresh)

    everything
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_analysis.py tests/test_a4_sweep.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — the sweep's tests still pass

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check placement/analysis.py scripts/a4_sweep.py tests/a4_evaluations.py tests/test_placement_analysis.py`

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add placement/analysis.py scripts/a4_sweep.py tests/a4_evaluations.py tests/test_placement_analysis.py
git commit -m "analysis: sizing, money, latency, fairness and the crossover, from the sweep's evaluations"
```

---

## Task 11: Figure 4's inputs: a swap's stages, and artifact 1's reference

**Files:**
- Create: `placement/stages.py`
- Create: `placement/a1_reference.py`
- Modify: `tests/test_placement_boundary.py`
- Test: `tests/test_placement_stages.py`

Amendment §5: figure 4 shows the 4B swap's own measured stages, each marked paid or skipped under artifact 1's taxonomy, with artifact 1's 8B medians only as a labelled reference.

**The swap's stages.** `stages.py` splits each stored swap into teardown, memory release and the successor's bring-up. The bring-up is split by the successor's own log:
- weight loading;
- engine init, of which torch.compile is one part;
- the rest: the `vllm serve` process starting and importing, which a process-level swap re-pays, plus the API server and the health poll.

A swap whose log lacks either line is not estimated. It is counted and named beside the medians, and only a stratum with no readable swap is refused. Compile state comes from the engine's facts, the field the simulator's swap distribution filters on, so the figure decomposes exactly the swaps the simulator draws.

**Artifact 1's reference.** `a1_reference.py` reads artifact 1's committed store through artifact 1's own derivation, arm C: weights on the volume and a warm compile cache. It is the ONE module in `placement/` allowed to load `coldstart` (amendment §7), so this task adds its file name to the boundary test's `ADAPTERS`, as that test's comment asks, and nothing else. It returns 100 runs, with a weight-loading median of 21.34 s.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_stages.py`:

```python
"""Figure 4's inputs: a swap's own stages from its logs, and artifact 1's
reference medians through the one adapter allowed to load `coldstart`."""

import subprocess
import sys
from pathlib import Path

import pytest

from placement.stages import STAGES, stage_medians, swap_stages
from placement_measure.records import A4Run

REPO = Path(__file__).resolve().parents[1]
LOADING = ("(EngineCore pid=1) INFO 10-12 10:00:05 [model_runner.py:329] Model loading took "
           "7.49 GiB and {w} seconds")
INIT = ("(EngineCore pid=1) INFO 10-12 10:00:15 [core.py:348] init engine (profile, create kv "
        "cache, warmup model) took {i} s (compilation: {c} s)")


def _swap(cold=True, *, weights=8.0, init=10.0, compile_s=0.3, startup=30.0, lines=None, i=0):
    log = lines if lines is not None else [LOADING.format(w=weights), INIT.format(i=init, c=compile_s)]
    return A4Run(run_id=f"s{i}", run_index=i, condition=f"swap:a>b:{'cold' if cold else 'warm'}",
                 block_index=0, kind="swap", outcome="ok", failure=None, clock_A={},
                 source="stub",
                 output={"teardown_s": 0.5, "release": {"seconds": 1.5}, "swap_s": 32.0,
                         "b": {"startup_s": startup, "log_tail": log,
                               "facts": {"s4b_s": compile_s}}})


def test_a_swap_splits_into_its_paid_stages():
    stages = swap_stages(_swap())
    assert stages == {"teardown_s": 0.5, "release_s": 1.5, "process_and_health_s": 12.0,
                      "weights_s": 8.0, "engine_init_rest_s": pytest.approx(9.7),
                      "compile_s": 0.3, "swap_s": 32.0}
    paid = sum(stages[k] for k in STAGES)
    assert paid == pytest.approx(stages["swap_s"])


def test_a_log_without_its_stage_lines_is_refused():
    with pytest.raises(ValueError, match="model-loading"):
        swap_stages(_swap(lines=[INIT.format(i=10.0, c=0.3)]))
    with pytest.raises(ValueError, match="engine-init"):
        swap_stages(_swap(lines=[LOADING.format(w=8.0)]))


def test_stages_that_exceed_the_bring_up_are_refused():
    with pytest.raises(ValueError, match="exceed"):
        swap_stages(_swap(weights=25.0, init=10.0, startup=30.0))


def test_medians_are_over_the_simulated_cache_and_compile_state():
    records = [_swap(True, weights=8.0, i=0), _swap(True, weights=10.0, i=1),
               _swap(False, weights=2.0, i=2), _swap(True, compile_s=19.0, init=25.0, startup=45.0, i=3)]
    m = stage_medians(records, cold=True)
    assert m["n"] == 2 and m["stages"]["weights_s"] == pytest.approx(9.0)
    assert m["unreadable"] == []
    assert stage_medians(records, cold=True, compiled=True)["n"] == 1
    with pytest.raises(ValueError, match="no readable ok swap"):
        stage_medians(records, cold=False, compiled=True)


def test_the_reference_is_artifact_ones_arm_c():
    from placement.a1_reference import stage_medians as a1

    ref = a1(REPO / "data" / "campaign.jsonl")
    assert ref["arm"] == "C" and ref["n"] == 100 and ref["model"] == "Qwen/Qwen3-8B"
    assert ref["stages"]["t_weights"] == pytest.approx(21.34, abs=0.01)


def test_only_the_adapter_loads_coldstart():
    probe = ("import importlib, sys; importlib.import_module({!r}); "
             "print(any(m.startswith('coldstart') for m in sys.modules))")
    results = {}
    for module in ("placement.a1_reference", "placement.stages"):
        out = subprocess.run([sys.executable, "-c", probe.format(module)], cwd=REPO,
                             capture_output=True, text=True, check=True)
        results[module] = out.stdout.strip()
    assert results == {"placement.a1_reference": "True", "placement.stages": "False"}


def test_an_unreadable_log_is_counted_not_fatal_unless_nothing_is_readable():
    records = [_swap(True, i=0), _swap(True, lines=[INIT.format(i=10.0, c=0.3)], i=1)]
    m = stage_medians(records, cold=True)
    assert m["n"] == 1 and m["unreadable"][0]["run_id"] == "s1"
    with pytest.raises(ValueError, match="1 unreadable"):
        stage_medians(records[1:], cold=True)


def test_a_swap_without_a_compile_reading_is_in_no_stratum():
    record = _swap(True)
    record.output["b"]["facts"] = {}
    with pytest.raises(ValueError, match="no readable"):
        stage_medians([record], cold=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_stages.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.stages'`

- [ ] **Step 3: Write the swap's stage split**

Create `placement/stages.py`:

```python
"""A process-level swap's measured stages, for figure 4.

Amendment §5: figure 4 separates the taxonomy from the magnitude. It shows the
4B swap's own measured stages, each marked paid or skipped under artifact 1's
taxonomy, and puts artifact 1's 8B cold-start medians beside them only as a
labelled reference (`placement.a1_reference`).

From each stored swap:

- `teardown_s`: engine A's process exiting (`Server.stop()`);
- `release_s`: A's GPU memory returning to the idle level;
- B's bring-up, `startup_s`, split by B's own log into weight loading (vLLM's
  "Model loading took ... seconds", artifact 1's S3), engine initialisation
  ("init engine ... took ... s", S4, of which torch.compile is `compile_s`,
  S4b), and the rest: the `vllm serve` process starting and importing (S2,
  which a process-level swap re-pays, amendment §5), the API server, and the
  health poll that ends the swap (S5).

A swap whose log lacks either line is not estimated: the stage split would
otherwise be invented for it. `stage_medians` counts and names such swaps
beside the medians, and refuses only if none can be read.

Compile state comes from the engine's facts (`s4b_s`, read from its whole log
in the container), the same field `placement.inputs.swap_distribution`
filters on, so the figure decomposes exactly the swaps the simulator draws.
"""

import re

from harness.stats import median
from placement_measure.campaigns import parse_swap
from placement_measure.recon_report import COMPILED_ABOVE_S

__all__ = ["STAGES", "stage_medians", "swap_stages"]

MODEL_LOADING = re.compile(r"Model loading took [\d.]+ GiB and (?P<sec>[\d.]+) seconds")
INIT_ENGINE = re.compile(r"init engine \(profile, create kv cache, warmup model\) took "
                         r"(?P<sec>[\d.]+) s")
# In the order a swap pays them.
STAGES = ("teardown_s", "release_s", "process_and_health_s", "weights_s", "engine_init_rest_s",
          "compile_s")


def _last(pattern: re.Pattern, lines) -> float | None:
    found = [float(m["sec"]) for line in lines if (m := pattern.search(line))]
    return found[-1] if found else None


def swap_stages(record) -> dict:
    out = record.output
    b = out.get("b") or {}
    lines = b.get("log_tail") or []
    weights, init = _last(MODEL_LOADING, lines), _last(INIT_ENGINE, lines)
    if weights is None or init is None:
        raise ValueError(f"swap {record.run_id}'s engine log lacks the "
                         f"{'model-loading' if weights is None else 'engine-init'} line; its "
                         "stages cannot be read, and estimating them would invent the split")
    compile_s = (b.get("facts") or {}).get("s4b_s")
    if compile_s is None:
        raise ValueError(f"swap {record.run_id}'s engine facts have no compile time (S4b)")
    rest = b["startup_s"] - weights - init
    if rest < 0:
        raise ValueError(f"swap {record.run_id}: weight loading and engine init ({weights + init:.2f}"
                         f" s) exceed the measured bring-up ({b['startup_s']:.2f} s)")
    return {
        "teardown_s": out["teardown_s"],
        "release_s": out["release"]["seconds"],
        "process_and_health_s": rest,
        "weights_s": weights,
        "engine_init_rest_s": init - compile_s,
        "compile_s": compile_s,
        "swap_s": out["swap_s"],
    }


def stage_medians(records, *, cold: bool, compiled: bool = False) -> dict:
    """Median of each stage over the ok swaps in one cache and compile state:
    the simulated state, so figure 4 decomposes the swap the simulator draws."""
    rows, unreadable = [], []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok" or parse_swap(r.condition)[2] != cold:
            continue
        s4b = ((r.output.get("b") or {}).get("facts") or {}).get("s4b_s")
        # A swap with no compile reading is outside every stratum, as it is
        # for `swap_distribution`.
        if s4b is None or (s4b > COMPILED_ABOVE_S) != compiled:
            continue
        try:
            rows.append(swap_stages(r))
        except ValueError as e:
            unreadable.append({"run_id": r.run_id, "reason": str(e)})
    if not rows:
        raise ValueError(f"no readable ok swap with cold={cold} and compiled={compiled} to "
                         f"decompose ({len(unreadable)} unreadable)")
    return {"n": len(rows), "cold": cold, "compiled": compiled, "unreadable": unreadable,
            "stages": {k: median([row[k] for row in rows]) for k in (*STAGES, "swap_s")}}
```

- [ ] **Step 4: Write the reference adapter**

Create `placement/a1_reference.py`:

```python
"""Artifact 1's 8B cold-start stage medians: figure 4's labelled reference bar.

The ONE module in `placement/` allowed to load `coldstart` (amendment §7,
tests/test_placement_boundary.py's ADAPTERS). It reads artifact 1's committed
store through artifact 1's own derivation, so the reference is the number
artifact 1 published, not a re-derivation of it. Nothing in `placement/`
imports this module at module level; `scripts/a4_analyse.py` does, once.

The reference arm is C, weights on the network volume with a warm compile
cache: the closest of artifact 1's arms to the swap the simulator draws, whose
weights come from the volume and whose compile cache is warm (pre-registration
step 2). The magnitudes are an 8B model's, which is why the figure labels them
a reference and never subtracts a swap from them (amendment §5).
"""

from coldstart.analysis.metrics import derive
from coldstart.schema import RunRecord
from harness.stats import median
from harness.store import JsonlStore

__all__ = ["REFERENCE_ARM", "STAGES", "stage_medians"]

REFERENCE_ARM = "C"
# Artifact 1's stage keys, in the order a cold start pays them.
STAGES = ("t_platform", "t_weights", "t_s4_bracket", "t_s5", "t_s6")


def stage_medians(store_path, arm: str = REFERENCE_ARM) -> dict:
    rows = [r for r in (derive(rec) for rec in JsonlStore(store_path, RunRecord).read_all())
            if r["ok"] and r["arm"] == arm and r.get("consistent")
            and all(r.get(k) is not None for k in STAGES)]
    if not rows:
        raise ValueError(f"artifact 1's store has no consistent arm-{arm} run with every stage")
    return {"arm": arm, "n": len(rows), "model": "Qwen/Qwen3-8B",
            "stages": {k: median([r[k] for r in rows]) for k in STAGES}}
```

- [ ] **Step 5: Admit the adapter, and only it, to the boundary**

In `tests/test_placement_boundary.py`, replace:

```python
# Module file names allowed to load `coldstart`. Empty until the measurement
# plan adds figure 4's adapter, which reads artifact 1's published stage
# medians. When it lands, add its file name here and nothing else.
ADAPTERS: frozenset[str] = frozenset()
```

with:

```python
# Module file names allowed to load `coldstart`: figure 4's adapter, which
# reads artifact 1's published stage medians (plan 3). Nothing else.
ADAPTERS: frozenset[str] = frozenset({"a1_reference.py"})
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_stages.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — the boundary test now loads every other module without `coldstart`

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check placement/stages.py placement/a1_reference.py tests/test_placement_boundary.py tests/test_placement_stages.py`

Expected: `All checks passed!`

- [ ] **Step 8: Commit**

```bash
git add placement/stages.py placement/a1_reference.py tests/test_placement_boundary.py tests/test_placement_stages.py
git commit -m "figure 4: a swap's measured stages, and artifact 1's arm-C medians through the one coldstart adapter"
```

---

## Task 12: The analysis script

**Files:**
- Create: `scripts/a4_analyse.py`
- Create: `tests/a4_stores.py`
- Test: `tests/test_a4_analyse.py`

One script turns every store into `data/a4/analysis.json`. It:
- reduces the solo curve and the surface under the warm-compile rule;
- draws the simulated swaps;
- builds the registered sweep design;
- runs or reuses the sweep;
- analyses it;
- adds the inputs, figure 4's stages and reference, the held-out check and the validation verdict.

A validation the gate refuses to run (too few ok replays, or replays of different traces) is recorded as `refused`, with the reason. It does not stop the script: the refusal is itself the result to publish, and raising would also withhold the sweep, the cost file and the figures.

Everything published reads that file and recomputes nothing.

**The test runs the script on synthetic stores** (`tests/a4_stores.py`). Their latency is exactly bilinear and their replays are the simulator's own, so validation and the held-out check must pass. The sweep's evaluations are hand-built, because the real sweep is hours of CPU and `tests/test_a4_sweep.py` already runs it small.

- [ ] **Step 1: Create the synthetic stores the tests share**

Create `tests/a4_stores.py`:

```python
"""Synthetic measurement stores for plan 3's end-to-end tests: every campaign
a registered design runs, written as the real stores would be.

Not a test module. Latency is 1 + 0.1 x own + 0.05 x neighbour seconds, so the
surface is exactly bilinear and the held-out cells pass. Replays are the
simulator's own latencies on the validation trace, offset by -10, 0 and +10 ms
per repeat, so validation passes.
"""

import random

from a4_examples import example_report
from test_placement_inputs_step2 import _cell
from test_placement_stages import _swap as _staged_swap

from harness.stats import median
from harness.store import JsonlStore
from placement.fleet import Gpu, Placement
from placement.inputs import colocated_surface, eviction_seconds, solo_curve, swap_distribution
from placement.registration import values
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.step2 import CELL_MIN_VALID, measurement_design
from placement.validation import validation_trace
from placement_measure.campaigns import parse_cell
from placement_measure.records import A4Run

SCREEN = {"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}
SWAP_S = 32.0


def registered() -> dict:
    return values(measurement_design(example_report()), SCREEN, rate=0.69,
                  provenance="test rate, not a quote")


def latency(own, neighbour):
    return 1.0 + 0.1 * own + 0.05 * (neighbour or 0)


def _cells(reg) -> list[A4Run]:
    conditions = ([f"solo:o{c}" for c in reg["SOLO_LEVELS"]]
                  + [f"pair:o{o}:n{n}" for o in reg["OWN_LEVELS"] for n in reg["NEIGHBOUR_LEVELS"]]
                  + list(reg["HELD_OUT"]))
    out = []
    for condition in conditions:
        own, neighbour = parse_cell(condition)
        for i, offset in enumerate((-0.01, 0.0, 0.01)):
            out.append(_cell(condition, latency(own, neighbour) + offset, i=i))
    return out


def _swaps() -> list[A4Run]:
    out = []
    for i in range(8):
        for cold in (True, False):
            r = _staged_swap(cold, i=len(out))
            r.output["swap_s"] = SWAP_S + i * 0.5 + (4.0 if cold else 0.0)
            r.output["b"]["facts"] = {"s4b_s": 0.3}
            if cold:
                r.output["cache_s"] = 1.0
            out.append(r)
    return out


def _sleep() -> list[A4Run]:
    return [A4Run(run_id=f"z{i}", run_index=i, condition="sleep:a>b", block_index=i, kind="sleep",
                  outcome="ok", failure=None, clock_A={}, source="stub",
                  output={"switch_s": 5.0 + 0.1 * i}) for i in range(8)]


def replay_swap_seconds(swaps) -> float:
    """The replay's swap: the median cold compile-hit swap plus the median
    eviction, as `scripts/a4_step2.py replay` computes it."""
    simulated = swap_distribution(swaps, cold=True, compiled=False)
    return median(list(simulated.samples)) + eviction_seconds(swaps, cold=True)


def _replays(reg, cells, swaps) -> list[A4Run]:
    """Three replays of the registered validation trace whose latencies are
    the simulator's, given these cells' curves and these swaps."""
    measurement = measurement_design(example_report())
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=reg["SOLO_LEVELS"], min_repeats=CELL_MIN_VALID, **warm)
    surface = colocated_surface(cells, own_levels=reg["OWN_LEVELS"],
                                neighbour_levels=reg["NEIGHBOUR_LEVELS"],
                                min_repeats=CELL_MIN_VALID, **warm)
    swap_s = replay_swap_seconds(swaps)
    design, _ = validation_trace(measurement, Engines(solo, surface), swap_s)
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    result = simulate(list(design.trace), placement, Engines(solo, surface),
                      EmpiricalDistribution(samples=(swap_s,), measured=True), 0.0,
                      random.Random(0))
    by_request = dict(zip(zip(result.arrivals, result.models, strict=True), result.latencies,
                          strict=True))
    lat = [by_request[(t, m)] for t, m in design.trace]
    out = []
    for i, off in enumerate((-0.01, 0.0, 0.01)):
        arrived = [t for t, _ in design.trace]
        output = {"schedule": [[t, m] for t, m in design.trace], "until": design.until,
                  "arrived": arrived,
                  "done": [a + x + off for a, x in zip(arrived, lat, strict=True)],
                  "swaps": [{}] * result.swaps, "host": {"host_id": f"h{i}"},
                  "ok": [True] * len(arrived)}
        out.append(A4Run(run_id=f"v{i}", run_index=i, condition="replay", block_index=i,
                         kind="replay", outcome="ok", failure=None, clock_A={}, source="stub",
                         output=output))
    return out


def write_stores(root) -> dict:
    """Write every store under `root/data/a4/` and return the registered values."""
    reg = registered()
    cells, swaps = _cells(reg), _swaps()
    for name, records in (("cells", cells), ("swaps", swaps), ("sleep", _sleep()),
                          ("replay", _replays(reg, cells, swaps))):
        store = JsonlStore(root / "data" / "a4" / f"{name}.jsonl", A4Run)
        for r in records:
            store.append(r)
    return reg
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_a4_analyse.py`:

```python
"""The analysis script end to end on synthetic stores, with the sweep's
evaluations replaced by hand-built ones (the sweep itself is tested in
tests/test_a4_sweep.py): every reduction, the validation, the held-out check,
figure 4's stages and the reference, and the analysis, into one file."""

import importlib.util
from pathlib import Path

import pytest
from a4_evaluations import sweep
from a4_stores import SWAP_S, write_stores

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("a4_analyse", REPO / "scripts" / "a4_analyse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    root = tmp_path_factory.mktemp("a4")
    reg = write_stores(root)
    script = _script()
    seen = {}

    def evaluations_for(design, engines, swap_time, out, workers, refresh=False):
        seen.update(design=design, engines=engines, swap_time=swap_time)
        return sweep()

    script.a4_sweep.evaluations_for = evaluations_for
    result = script.analyse_all(reg, script.STORES, root=root,
                                a1_store=REPO / "data" / "campaign.jsonl",
                                sweep_out=root / "sweep", workers=1)
    return result, seen, reg


def test_the_sweep_runs_on_the_measured_inputs_and_the_registered_choice(analysis):
    _, seen, reg = analysis
    design, engines, swap_time = seen["design"], seen["engines"], seen["swap_time"]
    assert engines.measured and swap_time.measured and design.preregistered
    # Cold compile-cache hits only: SWAP_S + 0.5 i + 4 for i in 0..7.
    assert swap_time.samples == tuple(SWAP_S + 0.5 * i + 4.0 for i in range(8))
    assert design.slo_seconds == pytest.approx(reg["SLO_SWAP_MULTIPLE"] * (SWAP_S + 4.0 + 1.75))
    assert design.offered_gpus == reg["OFFERED_GPUS"]


def test_the_inputs_held_out_check_and_validation_are_recorded(analysis):
    result, _, reg = analysis
    inputs = result["inputs"]
    assert inputs["solo_curve"][0][:2] == [1, pytest.approx(1.1)]
    assert inputs["surface"]["own"] == list(reg["OWN_LEVELS"])
    assert inputs["swaps"]["simulated"]["n"] == 8
    assert set(inputs["swaps"]["strata"]) == {"cold_hit", "warm_hit"}
    assert inputs["sleep_mode"]["n"] == 8
    assert inputs["stages"]["n"] == 8 and inputs["a1_reference"]["arm"] == "C"
    assert [c["passed"] for c in result["held_out"]] == [True, True]
    assert result["validation"]["outcome"] == "passed", result["validation"]["latency"]
    assert result["validation"]["point"] == {"regime": "bursty", "s": 1.0, "models": 3, "gpus": 1}


def test_the_analysis_itself_is_in_the_same_file(analysis):
    result, _, _ = analysis
    assert set(result["regimes"]) == {"spread", "bursty"}
    assert result["reference"] == {"regime": "bursty", "s": 1.0}
    assert result["rate"]["gpu_hourly_rate"] == 0.69
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_a4_analyse.py -q`

Expected: FAIL — `FileNotFoundError` for `scripts/a4_analyse.py`

- [ ] **Step 4: Write the script**

Create `scripts/a4_analyse.py`:

```python
"""Reduce every measurement store, validate, run the sweep on measured inputs,
and write data/a4/analysis.json. Spends nothing.

    .venv/bin/python scripts/a4_analyse.py [--workers 4] [--refresh] \\
        [--cells data/a4/cells.jsonl ...] [--swaps ...] [--sleep ...] [--replay ...]

Every value the post, the figures and data/a4/cost_per_tenant.json publish
comes from the file this writes. It reads the registered values
(placement/registered.py), the stores, and artifact 1's store for figure 4's
reference. The sweep's evaluations are cached under build/a4-sweep, keyed by
every input, as scripts/a4_sweep.py caches them; the first run is hours of CPU.

Each `--cells` (and the other store flags) may be given more than once: a
top-up campaign has its own store and reduces together with the one it tops up.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import a4_sweep

from autoscale.traffic import saturation_rps
from harness.stats import median, percentiles
from placement.analysis import analyse
from placement.inputs import (
    cell_summary,
    colocated_surface,
    eviction_seconds,
    held_out_check,
    load_records,
    sleep_distribution,
    solo_curve,
    swap_distribution,
)
from placement.money import Assumptions
from placement.sim import Engines
from placement.stages import stage_medians
from placement.step2 import (
    CELL_MIN_VALID,
    HELD_OUT_TOLERANCE,
    REFERENCE,
    VALIDATION_S,
    SweepChoice,
    sweep_design,
)
from placement.validation import validate

REPO = Path(__file__).resolve().parents[1]
STORES = {"cells": ["data/a4/cells.jsonl"], "swaps": ["data/a4/swaps.jsonl"],
          "sleep": ["data/a4/sleep.jsonl"], "replay": ["data/a4/replay.jsonl"]}


def _summary(samples) -> dict:
    samples = sorted(samples)
    p = percentiles(samples, want=("p50", "p90")) if len(samples) >= 50 else {
        "p50": median(samples), "p90": None}
    return {"n": len(samples), "min": samples[0], "max": samples[-1], "p50": p["p50"],
            "p90": p["p90"], "samples": samples}


def registered_values() -> dict:
    from placement import registered

    return {k: getattr(registered, k) for k in dir(registered) if k.isupper()}


def analyse_all(reg: dict, stores: dict[str, list[str]], *, root: Path, a1_store: Path,
                sweep_out: Path, workers: int, refresh: bool = False) -> dict:
    cells = load_records([root / s for s in stores["cells"]])
    swaps = load_records([root / s for s in stores["swaps"]])
    replays = load_records([root / s for s in stores["replay"]])
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=reg["SOLO_LEVELS"], min_repeats=CELL_MIN_VALID, **warm)
    surface = colocated_surface(cells, own_levels=reg["OWN_LEVELS"],
                                neighbour_levels=reg["NEIGHBOUR_LEVELS"],
                                min_repeats=CELL_MIN_VALID, **warm)
    engines = Engines(solo=solo, colocated=surface)
    cold = reg["EVICTION_WORKS"]
    swap_time = swap_distribution(swaps, cold=cold, compiled=False)
    swap_median = median(list(swap_time.samples))
    design = sweep_design(SweepChoice(reg["OFFERED_GPUS"], reg["SLO_SWAP_MULTIPLE"]), swap_median)
    rate = Assumptions(gpu_hourly_rate=reg["GPU_HOURLY_RATE"], provenance=reg["RATE_PROVENANCE"])
    total_rate = design.offered_gpus * saturation_rps(solo)

    evaluations = a4_sweep.evaluations_for(design, engines, swap_time, sweep_out, workers, refresh)
    result = analyse(evaluations, design, total_rate=total_rate, output_len=reg["OUTPUT_LEN"],
                     rate=rate, reference=REFERENCE)

    from placement.a1_reference import stage_medians as a1_stage_medians

    swap_strata = {}
    for state in ((True, False) if cold else (False,)):
        for compiled in (False, True):
            try:
                d = swap_distribution(swaps, cold=state, compiled=compiled)
            except ValueError:
                continue
            swap_strata[f"{'cold' if state else 'warm'}_{'compiled' if compiled else 'hit'}"] = (
                _summary(d.samples))
    sleep = None
    if reg["SLEEP_MEASURED"]:
        sleep = _summary(sleep_distribution(load_records([root / s for s in stores["sleep"]])).samples)
    summary = cell_summary(cells, **warm)
    result["inputs"] = {
        "model": reg["MODEL"],
        "request_shape": {"input_len": reg["INPUT_LEN"], "output_len": reg["OUTPUT_LEN"]},
        "kv": {"split_tokens": reg["KV_SPLIT_TOKENS"], "split_ceiling": reg["SPLIT_CEILING"],
               "solo_tokens": reg["KV_SOLO_TOKENS"], "solo_ceiling": reg["SOLO_CEILING"]},
        "solo_curve": [list(p) for p in solo.points],
        "saturation_rps": saturation_rps(solo),
        # The registered levels, which are the surface's grid: ints, so a
        # reader can name the cell they come from ("pair:o8:n16").
        "surface": {"own": list(reg["OWN_LEVELS"]), "neighbour": list(reg["NEIGHBOUR_LEVELS"]),
                    "latency": [list(row) for row in surface.latency]},
        "cells": summary,
        "swaps": {"simulated": {"cold": cold, "compiled": False, **_summary(swap_time.samples)},
                  "strata": swap_strata},
        "sleep_mode": sleep,
        "stages": stage_medians(swaps, cold=cold),
        "a1_reference": a1_stage_medians(a1_store),
    }
    result["held_out"] = held_out_check(cells, surface, reg["HELD_OUT"],
                                        tolerance=HELD_OUT_TOLERANCE,
                                        min_repeats=CELL_MIN_VALID, **warm)
    replay_swap_s = swap_median + eviction_seconds(swaps, cold=cold)
    try:
        verdict = validate(replays, engines, replay_swap_s)
    except ValueError as e:
        # Too few ok replays, or replays of different traces: the gate could
        # not be run, which is itself the result to publish. Raising here
        # would also withhold the sweep, the cost file and the figures.
        verdict = {"outcome": "refused", "detail": str(e), "swap_median_s": replay_swap_s}
    result["validation"] = {
        **verdict,
        # Where figure 1 marks the validated operating point (August §9).
        "point": {"regime": "bursty", "s": VALIDATION_S, "models": 3, "gpus": 1},
    }
    return result


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in STORES:
        ap.add_argument(f"--{name}", action="append")
    ap.add_argument("--out", default="data/a4/analysis.json")
    ap.add_argument("--sweep-out", default="build/a4-sweep")
    ap.add_argument("--a1-store", default="data/campaign.jsonl")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    stores = {name: getattr(args, name) or default for name, default in STORES.items()}
    result = analyse_all(registered_values(), stores, root=REPO, a1_store=REPO / args.a1_store,
                         sweep_out=REPO / args.sweep_out, workers=args.workers,
                         refresh=args.refresh)
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {args.out}: validation {result['validation']['outcome']}, held-out "
          f"{[c['passed'] for c in result['held_out']]}")
    for regime, r in result["regimes"].items():
        print(f"  {regime}: decision rule {r['decision_rule']}; crossover {r['crossover']['between']}")
    return result


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_a4_analyse.py -q`

Expected: PASS — 3 tests

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check scripts/a4_analyse.py tests/a4_stores.py tests/test_a4_analyse.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add scripts/a4_analyse.py tests/a4_stores.py tests/test_a4_analyse.py
git commit -m "analysis: one script from every store to data/a4/analysis.json"
```

---

## Task 13: Artifact 5's file: cost per tenant

**Files:**
- Create: `placement/cost_file.py`
- Create: `scripts/a4_cost_file.py`
- Test: `tests/test_placement_cost_file.py`

`data/a4/cost_per_tenant.json` is in the format agreed with artifact 5's session on 2026-09-26 (amendment §11):
- `gpu_hourly_rate`;
- `n_models`;
- the pre-registered `reference` point;
- one row per regime and skew, with dedicated, swapped and sleep-mode cost per tenant per month, null where dominated or not evaluable.

Sleep mode is never simulated, so its column is always null.

**It refuses anything artifact 5 would refuse.** A reference matching no row, or a reference row with no dedicated or no swapped cost, raises. A dominated swap at the reference is a finding for the owner, not a gap to fill.

The test restates artifact 5's reader rules as a contract, because artifact 5's package is not importable here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_cost_file.py`:

```python
"""The file artifact 5 reads, held to the contract agreed on 2026-09-26.

`_artifact_5_reads` restates artifact 5's reader rules (its plan 1, Task 13,
`a4_reference_row`): artifact 5's package is not importable from here, so its
rules are copied as a contract, and a change on either side breaks this test
or theirs."""

import importlib.util
import json
from pathlib import Path

import pytest
from a4_evaluations import DESIGN, RATE, swap_dominated, sweep

from placement.analysis import analyse
from placement.cost_file import build

REPO = Path(__file__).resolve().parents[1]
REFERENCE = {"regime": "bursty", "s": 1.0}


def _analysis(evaluations=None, reference=REFERENCE):
    return analyse(evaluations or sweep(), DESIGN, total_rate=5.0, output_len=256, rate=RATE,
                   reference=reference)


def _artifact_5_reads(a4: dict) -> dict:
    missing = [k for k in ("gpu_hourly_rate", "reference", "rows") if k not in a4]
    assert not missing, missing
    ref = a4["reference"]
    matches = [r for r in a4["rows"] if r["regime"] == ref["regime"] and r["s"] == ref["s"]]
    assert len(matches) == 1
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        assert matches[0].get(key) is not None, key
    return matches[0]


def test_the_file_meets_artifact_5s_contract():
    result = build(_analysis())
    row = _artifact_5_reads(result)
    assert result["gpu_hourly_rate"] == 0.69 and result["n_models"] == 20
    # Swap sized 6 GPUs and dedicate 10, over 20 tenants.
    assert row["swapped_cost_per_tenant_month"] < row["dedicated_cost_per_tenant_month"]
    assert row["sleep_mode_cost_per_tenant_month"] is None
    assert len(result["rows"]) == 4 and {r["regime"] for r in result["rows"]} == {"spread", "bursty"}


def test_a_dominated_swap_at_the_reference_is_refused_not_written():
    evaluations = [*sweep()[:3], swap_dominated(1.0, "bursty")]
    with pytest.raises(ValueError, match="no swapped cost"):
        build(_analysis(evaluations))


def test_the_script_writes_the_file(tmp_path):
    analysis = tmp_path / "analysis.json"
    analysis.write_text(json.dumps(_analysis()))
    spec = importlib.util.spec_from_file_location("a4_cost_file", REPO / "scripts" / "a4_cost_file.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path / "cost.json"
    module.main(["--analysis", str(analysis), "--out", str(out)])
    _artifact_5_reads(json.loads(out.read_text()))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_cost_file.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.cost_file'`

- [ ] **Step 3: Write the file's builder**

Create `placement/cost_file.py`:

```python
"""`data/a4/cost_per_tenant.json`: artifact 4's per-tenant costs for artifact 5.

The format was agreed with artifact 5's session on 2026-09-26 (amendment §11):
`gpu_hourly_rate`, `n_models`, a `reference` grid point fixed in the second
pre-registration step, and one row per (regime, s) with the dedicated, swapped
(process-level arm) and sleep-mode cost per tenant per month, null where a
strategy is dominated or the point is not evaluable. Sleep mode is never
simulated here (amendment §6), so its column is always null.

Artifact 5 refuses the file if the reference matches zero or several rows, if
the reference row has no dedicated or no swapped cost, or if the rate differs
from its own. `build` refuses the first two itself, so a file artifact 5 would
refuse is never written; the rate is artifact 5's to check, since it reads
artifact 4's committed rate (its plan 2).
"""

__all__ = ["build"]


def _cost(point: dict, strategy: str) -> float | None:
    if not point["evaluable"]:
        return None
    view = point["strategies"][strategy]
    return None if view is None else view["cost_per_tenant_month"]


def build(analysis: dict) -> dict:
    rows = []
    for regime, r in analysis["regimes"].items():
        for p in r["points"]:
            rows.append({
                "regime": regime, "s": p["s"],
                "dedicated_cost_per_tenant_month": _cost(p, "dedicate"),
                "swapped_cost_per_tenant_month": _cost(p, "swap"),
                "sleep_mode_cost_per_tenant_month": None,
            })
    ref = analysis["reference"]
    matches = [row for row in rows if row["regime"] == ref["regime"] and row["s"] == ref["s"]]
    if len(matches) != 1:
        raise ValueError(f"the reference {ref} matches {len(matches)} rows, not 1")
    for key in ("dedicated_cost_per_tenant_month", "swapped_cost_per_tenant_month"):
        if matches[0][key] is None:
            raise ValueError(
                f"the reference row has no {key.split('_')[0]} cost (dominated or not "
                "evaluable); artifact 5 would refuse the file. This is a finding for the "
                "owner, not a gap to fill"
            )
    return {
        "gpu_hourly_rate": analysis["rate"]["gpu_hourly_rate"],
        "rate_provenance": analysis["rate"]["provenance"],
        "n_models": analysis["design"]["n_models"],
        "reference": dict(ref),
        "rows": rows,
        "source": "artifact 4, data/a4/analysis.json; process-level swap arm",
    }
```

- [ ] **Step 4: Write the script**

Create `scripts/a4_cost_file.py`:

```python
"""Write data/a4/cost_per_tenant.json for artifact 5 from data/a4/analysis.json.

    .venv/bin/python scripts/a4_cost_file.py [--analysis data/a4/analysis.json] \\
        [--out data/a4/cost_per_tenant.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from placement.cost_file import build


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--analysis", default="data/a4/analysis.json")
    ap.add_argument("--out", default="data/a4/cost_per_tenant.json")
    args = ap.parse_args(argv)
    result = build(json.loads(Path(args.analysis).read_text()))
    Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    ref = next(r for r in result["rows"] if r["regime"] == result["reference"]["regime"]
               and r["s"] == result["reference"]["s"])
    print(f"wrote {args.out}: reference {result['reference']}: dedicated "
          f"${ref['dedicated_cost_per_tenant_month']:.2f}, swapped "
          f"${ref['swapped_cost_per_tenant_month']:.2f} per tenant per month")
    return result


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_cost_file.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — 3 tests

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check placement/cost_file.py scripts/a4_cost_file.py tests/test_placement_cost_file.py`

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add placement/cost_file.py scripts/a4_cost_file.py tests/test_placement_cost_file.py
git commit -m "cost file: artifact 4's per-tenant costs for artifact 5, refusing what artifact 5 would refuse"
```

---

## Task 14: The four figures (changes pixels)

**Files:**
- Create: `placement/figures.py`
- Create: `scripts/a4_render_figures.py`
- Create: `tests/a4_analysis_example.py`
- Test: `tests/test_placement_figures.py`

These are August §10's four figures, drawn from `analysis.json` alone, under the constraints every artifact's figures share: intervals shown, N stated, no truncated axes, and legible on a phone.
1. **The crossover:** fleet and aggregate p99 against skew, per regime, with the crossover interval and the validated point.
2. **p99 by popularity decile:** at the reference skew, beside swap sized on the aggregate.
3. **The measured interference surface:** with the solo curve, both KV ceilings and the held-out cells.
4. **The swap's stages:** beside artifact 1's cold start.

**This task changes pixels, so the global rules for visual work apply.** The tests are the geometry layer:
- every text clears the phone floor;
- every painted text stays on the canvas;
- N is stated;
- a missing regime, stage or cell is refused rather than drawn around;
- a regime not evaluable at the reference is said on its panel, not raised, so it cannot stop the other figures rendering.

**The visual layer is a person looking.** It covers each figure at desktop width and at 375 px, from a complete synthetic analysis now, and from the real one in Part B.

**How the drafts were inspected.** The prototype's first drafts were looked at, and three defects fixed before this plan was written:
- figure 4's in-segment names collided;
- figure 2's legend covered the SLO label;
- figure 1's "validated" label sat on the data.

Figure 4 also stopped implying a one-to-one stage mapping. Artifact 1's `T_weights` includes the process start and imports, so each bar keeps its own artifact's stage names. Its bar ends are marked as sums of stage medians, with the median swap stated beside them, because the two differ and the SLO is a multiple of the second.

**Rendering is deterministic** (one test renders twice and compares bytes), which Part B's drift test relies on.

- [ ] **Step 1: Create the complete synthetic analysis the figure tests share**

Create `tests/a4_analysis_example.py`:

```python
"""A complete synthetic `data/a4/analysis.json`, for the figure and post tests.

Not a test module. Its inputs come from tests/a4_stores.py's stores through
the real analysis script, and its sweep from tests/a4_evaluations.py's
`rich_sweep`, analysed at that sweep's 10 s SLO so the crossover has shape.
"""

import dataclasses
import importlib.util
from pathlib import Path

from a4_evaluations import DESIGN, RATE, SKEWS, rich_sweep
from a4_stores import write_stores

from placement.analysis import analyse

REPO = Path(__file__).resolve().parents[1]


def example_analysis(root: Path) -> dict:
    spec = importlib.util.spec_from_file_location("a4_analyse", REPO / "scripts" / "a4_analyse.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    reg = write_stores(root)
    script.a4_sweep.evaluations_for = lambda *a, **k: rich_sweep()
    result = script.analyse_all(reg, script.STORES, root=root,
                                a1_store=REPO / "data" / "campaign.jsonl",
                                sweep_out=root / "sweep", workers=1)
    result.update(analyse(rich_sweep(), dataclasses.replace(DESIGN, skews=SKEWS),
                          total_rate=5.0, output_len=256, rate=RATE,
                          reference={"regime": "bursty", "s": 1.0}))
    return result
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_placement_figures.py`:

```python
"""Artifact 4's four figures on a complete synthetic analysis: every text
legible at phone width and on the canvas, N stated, and refusals instead of
charts that compare fewer things than they appear to.

These are layer-2 checks (geometry), not the visual check. The visual check is
a human looking at each render at full size and at 375 px, which plan 3's
figure task and its publication task both require."""

import copy

import matplotlib
import matplotlib.pyplot as plt
import pytest
from a4_analysis_example import example_analysis

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from placement.figures import FIGURES

NAMES = sorted(FIGURES)


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    return example_analysis(tmp_path_factory.mktemp("a4"))


@pytest.fixture(autouse=True)
def _close():
    yield
    plt.close("all")


def _draw(name, analysis, tmp_path):
    return FIGURES[name](analysis, tmp_path / f"{name}.png", return_figure=True)


def _visible_texts(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    artists = list(fig.texts)
    for ax in fig.axes:
        artists += [ax.title, ax.xaxis.label, ax.yaxis.label, *ax.texts]
        # Only ticks inside the view limits: an axis keeps labels for ticks it
        # never paints, and they report extents off the canvas (artifact 2's
        # tests/test_a2_figures.py met the same trap).
        for axis, lim in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            lo, hi = sorted(lim)
            artists += [tick.label1 for tick in axis.get_major_ticks() if lo <= tick.get_loc() <= hi]
        legend = ax.get_legend()
        if legend:
            artists += legend.get_texts()
    for legend in fig.legends:
        artists += legend.get_texts()
    return [(t, t.get_window_extent(renderer)) for t in artists
            if t.get_text().strip() and t.get_visible()]


@pytest.mark.parametrize("name", NAMES)
def test_the_figure_renders_to_a_png(name, analysis, tmp_path):
    out = FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and out.stat().st_size > 20_000


@pytest.mark.parametrize("name", NAMES)
def test_every_text_clears_the_phone_floor(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    width_in = fig.get_size_inches()[0]
    for text in fig.findobj(match=matplotlib.text.Text):
        if text.get_text().strip():
            px = text.get_fontsize() * PHONE_WIDTH_PX / (72 * width_in)
            assert px >= MIN_PHONE_TEXT_PX, f"{text.get_text()!r} is {px:.1f}px on a phone"


@pytest.mark.parametrize("name", NAMES)
def test_no_text_runs_off_the_canvas(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    width_px, height_px = fig.get_size_inches() * fig.dpi
    for text, box in _visible_texts(fig):
        assert box.x0 >= -1 and box.x1 <= width_px + 1, f"{text.get_text()!r} is cut off sideways"
        assert box.y0 >= -1 and box.y1 <= height_px + 1, f"{text.get_text()!r} is cut off vertically"


@pytest.mark.parametrize("name", NAMES)
def test_n_is_stated(name, analysis, tmp_path):
    fig = _draw(name, analysis, tmp_path)
    texts = " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))
    assert "n=" in texts or "n>=" in texts or "runs" in texts


def test_the_crossover_figure_marks_the_validated_point_and_dominated_strategies(analysis, tmp_path):
    fig = _draw("crossover", analysis, tmp_path)
    texts = [t.get_text() for t in fig.findobj(match=matplotlib.text.Text)]
    assert any("validated" in t for t in texts) and any("dominated" in t for t in texts)


def test_the_deciles_figure_shows_swap_sized_on_the_aggregate(analysis, tmp_path):
    fig = _draw("deciles", analysis, tmp_path)
    labels = [t.get_text() for ax in fig.axes for t in ax.get_legend().get_texts()]
    assert any("sized on aggregate" in label for label in labels)


def test_a_missing_regime_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["regimes"]["bursty"]
    for name in ("crossover", "deciles"):
        with pytest.raises(ValueError, match="regime"):
            FIGURES[name](broken, tmp_path / "x.png")


def test_a_regime_not_evaluable_at_the_reference_is_said_not_raised(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    for p in broken["regimes"]["spread"]["points"]:
        if p["s"] == broken["reference"]["s"]:
            p.clear()
            p.update({"regime": "spread", "s": broken["reference"]["s"], "window_s": 1.0,
                      "evaluable": False})
    fig = FIGURES["deciles"](broken, tmp_path / "x.png", return_figure=True)
    texts = [t.get_text() for t in fig.findobj(match=matplotlib.text.Text)]
    assert any("not evaluable here" in t for t in texts)


def test_figure_4_states_the_median_swap_beside_the_summed_stages(analysis, tmp_path):
    fig = FIGURES["swap_stages"](analysis, tmp_path / "x.png", return_figure=True)
    swap = analysis["inputs"]["stages"]["stages"]["swap_s"]
    texts = " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))
    assert f"Median swap: {swap:.1f} s" in texts and "Σ" in texts


def test_a_missing_stage_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["inputs"]["stages"]["stages"]["release_s"]
    with pytest.raises(ValueError, match="swap stage"):
        FIGURES["swap_stages"](broken, tmp_path / "x.png")


def test_a_surface_cell_without_its_summary_is_refused(analysis, tmp_path):
    broken = copy.deepcopy(analysis)
    del broken["inputs"]["cells"]["pair:o8:n16"]
    with pytest.raises(ValueError, match="no summary"):
        FIGURES["interference"](broken, tmp_path / "x.png")


def test_the_render_script_writes_each_figure_and_its_phone_copy(analysis, tmp_path):
    import importlib.util
    import json
    from pathlib import Path

    from matplotlib.image import imread

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("render", repo / "scripts" / "a4_render_figures.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(analysis))
    written = script.main(["--analysis", str(path), "--out", str(tmp_path / "figs")])
    assert len(written) == 8
    for name in NAMES:
        assert imread(tmp_path / "figs" / f"{name}-phone.png").shape[1] == PHONE_WIDTH_PX
    # Deterministic: a second render is byte-identical, which the drift test
    # added at publication relies on.
    again = script.main(["--analysis", str(path), "--out", str(tmp_path / "again")])
    assert [p.read_bytes() for p in written] == [p.read_bytes() for p in again]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_figures.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.figures'`

- [ ] **Step 4: Write the figures**

Create `placement/figures.py`:

```python
"""Artifact 4's four body figures, drawn from `data/a4/analysis.json` alone.

August §10's four, under the constraints every artifact's figures share:
intervals shown, N stated, no truncated axes, legible on a phone, and looked at
by a human before anything is called done (`harness.figure_guards`).

1. `crossover`: the fleet each strategy is sized to, and its aggregate p99,
   against skew, one column per locality regime. The crossover interval is
   shaded and the validated operating point is marked (August §9).
2. `deciles`: p99 by popularity decile at the reference skew, each strategy at
   its own sized fleet, beside swap sized on the aggregate p99 instead.
3. `interference`: the measured co-location surface as one curve per
   neighbour load, the solo curve, both KV ceilings, and the held-out cells.
4. `swap_stages`: the 4B swap's measured stages, each marked paid or skipped
   under artifact 1's taxonomy, with artifact 1's 8B cold start as a labelled
   reference (amendment §5).

The text budget is artifact 2's: at the phone floor a figure holds about 90
characters across, whatever its width, so labels are terse, figures grow
tall rather than wide, and margins are set explicitly.

Refusals rather than best-effort drawing: a regime, strategy or stage missing
from the analysis raises instead of drawing a chart that compares fewer things
than it appears to.
"""

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from harness.figure_guards import phone_pt
from placement.fleet import STRATEGIES

__all__ = ["FIGURES", "crossover", "deciles", "interference", "swap_stages"]

STRATEGY_COLOR = {"dedicate": "#4f6d7a", "swap": "#c0392b", "colocate": "#2f6fd0"}
STRATEGY_MARKER = {"dedicate": "s", "swap": "o", "colocate": "^"}
REGIME_TITLE = {"spread": "spread arrivals", "bursty": "bursty arrivals"}
NOTE_COLOR = "#3f3f3f"
FIG_WIDTH_IN = 7.0
PX_TITLE = 9.0
PX_LABEL = 8.2
PX_TICK = 7.8
PX_NOTE = 7.8


def _pt(px: float, width: float = FIG_WIDTH_IN) -> float:
    return phone_pt(px, width)


def _require(mapping: dict, keys, what: str) -> None:
    missing = [k for k in keys if k not in mapping]
    if missing:
        raise ValueError(f"the analysis has no {what} {missing}; refusing to draw a chart that "
                         "silently compares fewer of them")


def _save(fig, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    return path


def _style(ax, width: float = FIG_WIDTH_IN) -> None:
    ax.tick_params(labelsize=_pt(PX_TICK, width))
    ax.grid(alpha=0.25, linewidth=0.6)


def _finish(fig, path, return_figure: bool):
    out = _save(fig, path)
    if return_figure:
        return fig
    plt.close(fig)
    return out


def crossover(analysis: dict, path, *, return_figure: bool = False):
    regimes = analysis["regimes"]
    order = [r for r in ("spread", "bursty") if r in regimes]
    _require(regimes, analysis["design"]["regimes"], "regime")
    slo = analysis["design"]["slo_seconds"]
    reps = analysis["design"]["repetitions"]
    fig, axes = plt.subplots(2, len(order), figsize=(FIG_WIDTH_IN, 8.6), sharex=True,
                             squeeze=False)
    for col, regime in enumerate(order):
        r = regimes[regime]
        top, bottom = axes[0][col], axes[1][col]
        points = r["points"]
        skews = [p["s"] for p in points]
        top_m = 0
        for strategy in STRATEGIES:
            xs, ms, lats, los, his = [], [], [], [], []
            for p in points:
                if not p["evaluable"] or p["strategies"].get(strategy) is None:
                    continue
                v = p["strategies"][strategy]
                xs.append(p["s"])
                ms.append(v["m"])
                ap = v["aggregate_p99"]
                lats.append(ap["point"])
                los.append(ap["point"] - ap["lo"])
                his.append(ap["hi"] - ap["point"])
            top_m = max([top_m, *ms])
            style = {"color": STRATEGY_COLOR[strategy], "marker": STRATEGY_MARKER[strategy],
                     "markersize": 5, "linewidth": 1.4}
            top.plot(xs, ms, label=strategy, **style)
            bottom.errorbar(xs, lats, yerr=[los, his], capsize=2, **style)
        for p in points:
            if not p["evaluable"]:
                top.annotate("not\nevaluable", (p["s"], 0), ha="center", va="bottom",
                             fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
                continue
            dominated = [s for s in STRATEGIES if p["strategies"].get(s) is None]
            for k, strategy in enumerate(dominated):
                top.plot(p["s"], top_m * 1.08 + k * top_m * 0.05, marker="x", linestyle="none",
                         color=STRATEGY_COLOR[strategy], markersize=6)
        c = r["crossover"]
        if c["interval_lower_point"]:
            lo, hi = c["interval_lower_point"]
            right = skews[min(skews.index(hi) + 1, len(skews) - 1)]
            top.axvspan(lo, right, color="#f2d7a6", alpha=0.45, linewidth=0)
        for a, b in c["between"]:
            top.axvline((a + b) / 2, color="#a0522d", linewidth=1.0, linestyle="--")
        bottom.axhline(slo, color="#555555", linewidth=1.0, linestyle=":")
        bottom.annotate(f"SLO {slo:.0f} s", (skews[0], slo), xytext=(2, 3),
                        textcoords="offset points", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
        top.set_title(REGIME_TITLE[regime], fontsize=_pt(PX_TITLE))
        top.set_ylim(0, top_m * 1.25 + 1)
        validated = analysis.get("validation", {}).get("point")
        if validated and validated["regime"] == regime:
            for ax in (top, bottom):
                ax.axvline(validated["s"], color="#2f6b34", linewidth=1.2, linestyle="-.")
            top.annotate("validated\npoint", (validated["s"], top_m * 1.25 + 1), xytext=(3, -4),
                         textcoords="offset points", va="top", fontsize=_pt(PX_NOTE),
                         color="#2f6b34")
        top.yaxis.set_major_locator(MaxNLocator(integer=True))
        bottom.set_ylim(bottom=0)
        bottom.set_xlabel("Zipf skew s", fontsize=_pt(PX_LABEL))
        for ax in (top, bottom):
            _style(ax)
    axes[0][0].set_ylabel("GPUs to meet SLO", fontsize=_pt(PX_LABEL))
    axes[1][0].set_ylabel("aggregate p99 (s)", fontsize=_pt(PX_LABEL))
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False,
               fontsize=_pt(PX_LABEL), bbox_to_anchor=(0.5, 0.045))
    fig.text(0.5, 0.012, f"x = dominated; shaded = crossover 95% interval; n={reps} runs per point",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.95, bottom=0.15, hspace=0.12, wspace=0.22)
    return _finish(fig, path, return_figure)


def deciles(analysis: dict, path, *, return_figure: bool = False):
    ref = analysis["reference"]
    slo = analysis["design"]["slo_seconds"]
    regimes = analysis["regimes"]
    _require(regimes, analysis["design"]["regimes"], "regime")
    order = [r for r in ("spread", "bursty") if r in regimes]
    fig, axes = plt.subplots(len(order), 1, figsize=(FIG_WIDTH_IN, 8.0), sharex=True,
                             squeeze=False)
    xs = list(range(1, 11))
    for row, regime in enumerate(order):
        ax = axes[row][0]
        point = next((p for p in regimes[regime]["points"] if p["s"] == ref["s"]), None)
        if point is None:
            raise ValueError(f"{regime} has no grid point at s = {ref['s']}")
        ax.set_title(f"{REGIME_TITLE[regime]}, s = {ref['s']}", fontsize=_pt(PX_TITLE))
        if not point["evaluable"]:
            # Said on the panel, not raised: one regime that is not evaluable
            # at the reference must not stop every other figure from rendering.
            ax.text(0.5, 0.5, "not evaluable here:\na decile missed the p99 floor",
                    transform=ax.transAxes, ha="center", va="center", fontsize=_pt(PX_LABEL),
                    color=NOTE_COLOR)
            ax.set_yticks([])
            _style(ax)
            continue
        for strategy in STRATEGIES:
            v = point["strategies"].get(strategy)
            if v is None:
                continue
            ax.plot(xs, v["decile_p99"], color=STRATEGY_COLOR[strategy],
                    marker=STRATEGY_MARKER[strategy], markersize=5, linewidth=1.4,
                    label=f"{strategy}, {v['m']} GPUs")
        agg = point["aggregate_rule"].get("swap")
        sized = point["strategies"].get("swap")
        if agg is not None and (sized is None or agg["m"] < sized["m"]):
            ax.plot(xs, agg["decile_p99"], color=STRATEGY_COLOR["swap"], linestyle="--",
                    marker="o", markerfacecolor="white", markersize=5, linewidth=1.2,
                    label=f"swap sized on aggregate, {agg['m']} GPUs")
        ax.axhline(slo, color="#555555", linewidth=1.0, linestyle=":")
        ax.annotate(f"SLO {slo:.0f} s", (1, slo), xytext=(2, 3), textcoords="offset points",
                    fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("p99 (s)", fontsize=_pt(PX_LABEL))
        ax.legend(fontsize=_pt(PX_NOTE), frameon=False, loc="center left")
        _style(ax)
    axes[-1][0].set_xticks(xs, ["1\nhottest", *map(str, range(2, 10)), "10\ncoldest"])
    axes[-1][0].set_xlabel("popularity decile", fontsize=_pt(PX_LABEL))
    reps = analysis["design"]["repetitions"]
    fig.text(0.5, 0.012, f"median of {reps} runs' p99 per decile", ha="center",
             fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.95, bottom=0.13, hspace=0.22)
    return _finish(fig, path, return_figure)


def interference(analysis: dict, path, *, return_figure: bool = False):
    inputs = analysis["inputs"]
    surface = inputs["surface"]
    cells = inputs["cells"]
    kv = inputs["kv"]
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 6.4))
    shades = ["#9ecae1", "#4292c6", "#2171b5", "#08306b"]
    if len(surface["neighbour"]) > len(shades):
        raise ValueError("more neighbour levels than the figure has shades for")
    n_min = math.inf
    for j, neighbour in enumerate(surface["neighbour"]):
        own = surface["own"]
        lo, hi, mid = [], [], []
        for o in own:
            cell = cells.get(f"pair:o{o}:n{neighbour}")
            if cell is None or cell["n"] == 0:
                raise ValueError(f"the surface has cell ({o}, {neighbour}) but no summary for it")
            n_min = min(n_min, cell["n"])
            mid.append(cell["median"])
            lo.append(cell["median"] - cell["lo"])
            hi.append(cell["hi"] - cell["median"])
        label = "split, neighbour idle" if neighbour == 0 else f"split, neighbour at {neighbour}"
        ax.errorbar(own, mid, yerr=[lo, hi], color=shades[j], marker="o", markersize=4,
                    linewidth=1.4, capsize=2, label=label)
    solo = inputs["solo_curve"]
    ax.plot([p[0] for p in solo], [p[1] for p in solo], color="#222222", linewidth=1.6,
            marker="s", markersize=4, label="solo, full memory")
    for check in analysis.get("held_out", []):
        ax.plot(check["own"], check["median"], marker="D", markerfacecolor="white",
                markeredgecolor="#a0522d", linestyle="none", markersize=7)
        ax.plot(check["own"], check["predicted"], marker="x", color="#a0522d", markersize=7,
                linestyle="none")
    ax.plot([], [], marker="D", markerfacecolor="white", markeredgecolor="#a0522d",
            linestyle="none", label="held out: measured, x = predicted")
    for ceiling, text in ((kv["split_ceiling"], "KV full, split"),
                          (kv["solo_ceiling"], "KV full, solo")):
        if ceiling is None:
            continue
        ax.axvline(ceiling, color="#777777", linestyle=":", linewidth=1.0)
        ax.annotate(text, (ceiling, 0), xytext=(3, 4), textcoords="offset points", rotation=90,
                    fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    ax.set_xscale("log", base=2)
    ax.set_ylim(bottom=0)
    ax.set_xlabel("own concurrency (requests in flight)", fontsize=_pt(PX_LABEL))
    ax.set_ylabel("latency per request (s)", fontsize=_pt(PX_LABEL))
    ax.legend(fontsize=_pt(PX_NOTE), frameon=False, loc="upper left")
    _style(ax)
    shape = inputs["request_shape"]
    fig.text(0.5, 0.012, f"{shape['input_len']}+{shape['output_len']} tokens; median and "
             f"range of n>={n_min} runs per point", ha="center", fontsize=_pt(PX_NOTE),
             color=NOTE_COLOR)
    fig.subplots_adjust(left=0.11, right=0.98, top=0.97, bottom=0.14)
    return _finish(fig, path, return_figure)


# (key, legend label, colour, hatched). Hatched marks a stage the other bar
# does not have: teardown and release are paid only by a swap; the platform's
# scheduling and container start, and the first token, are not in a swap. The
# two bars' stages are each artifact's own: artifact 1's T_weights includes
# the process start and imports, which a swap's log puts in its first bar.
SWAP_SEGMENTS = (
    ("teardown_s", "teardown (swap only)", "#8c6d31", True),
    ("release_s", "memory release (swap only)", "#bd9e39", True),
    ("process_and_health_s", "process start, imports, health", "#8e6fc4", False),
    ("weights_s", "weight load", "#2f6fd0", False),
    ("compile_s", "torch.compile (S4b)", "#d95f02", False),
    ("engine_init_rest_s", "engine init, rest", "#e6ab02", False),
)
REFERENCE_SEGMENTS = (
    ("t_platform", "T_platform (not in a swap)", "#9e9e9e", True),
    ("t_weights", "T_weights (S2+S3)", "#9ecae1", False),
    ("t_s4_bracket", "S4 engine init", "#fdd57e", False),
    ("t_s5", "S5 health", "#c7b8e8", False),
    ("t_s6", "S6 first token (not in a swap)", "#4f6d7a", True),
)
IN_BAR_MIN_S = 3.0


def swap_stages(analysis: dict, path, *, return_figure: bool = False):
    stages = analysis["inputs"]["stages"]
    ref = analysis["inputs"]["a1_reference"]
    _require(stages["stages"], [k for k, *_ in SWAP_SEGMENTS], "swap stage")
    _require(ref["stages"], [k for k, *_ in REFERENCE_SEGMENTS], "reference stage")
    fig, ax = plt.subplots(figsize=(FIG_WIDTH_IN, 6.4))
    model = analysis["inputs"]["model"].split("/")[-1]
    state = "cold cache" if stages["cold"] else "warm cache"
    rows = (
        (1.0, f"{model} swap\n{state}, n={stages['n']}", stages["stages"], SWAP_SEGMENTS),
        (0.0, f"Qwen3-8B cold\nstart, n={ref['n']}\n(artifact 1)", ref["stages"],
         REFERENCE_SEGMENTS),
    )
    totals = []
    for y, _, values, segments in rows:
        left = 0.0
        for key, label, color, hatched in segments:
            width = values[key]
            ax.barh(y, width, left=left, color=color, edgecolor="white",
                    hatch="///" if hatched else None, height=0.55, label=label)
            if width >= IN_BAR_MIN_S:
                ax.text(left + width / 2, y, f"{width:.1f}", ha="center", va="center",
                        fontsize=_pt(PX_NOTE), color="#111111")
            left += width
        ax.text(left + 0.4, y, f"Σ {left:.1f} s", va="center", fontsize=_pt(PX_LABEL))
        totals.append(left)
    ax.set_yticks([1.0, 0.0], [rows[0][1], rows[1][1]], fontsize=_pt(PX_TICK))
    ax.set_xlim(0, max(totals) * 1.18)
    ax.set_ylim(-0.5, 1.5)
    ax.set_xlabel("seconds (median)", fontsize=_pt(PX_LABEL))
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.42, -0.16), ncol=2, frameon=False,
              fontsize=_pt(PX_NOTE))
    # A bar's end is the sum of its stages' medians, which is not the median of
    # the totals; the median swap, the number the SLO is a multiple of, is
    # stated beside it so the two are never read as one.
    fig.text(0.5, 0.055, f"Σ: sum of stage medians. Median swap: {stages['stages']['swap_s']:.1f} s",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.text(0.5, 0.012, "hatched: in one bar only. The 8B bar is a reference, not a baseline",
             ha="center", fontsize=_pt(PX_NOTE), color=NOTE_COLOR)
    fig.subplots_adjust(left=0.2, right=0.97, top=0.97, bottom=0.40)
    return _finish(fig, path, return_figure)


FIGURES = {"crossover": crossover, "deciles": deciles, "interference": interference,
           "swap_stages": swap_stages}
```

- [ ] **Step 5: Write the render script, with phone copies**

Create `scripts/a4_render_figures.py`:

```python
"""Render artifact 4's four figures, and their phone-width inspection copies,
from data/a4/analysis.json. Spends nothing.

    .venv/bin/python scripts/a4_render_figures.py [--analysis data/a4/analysis.json] \\
        [--out build/a4-figures]

Writes <name>.png and <name>-phone.png for each figure. The phone copy is the
figure downscaled to 375 px wide, the width the post is read at on a phone,
made the way artifact 1's runbook makes its own (docs/runbook.md). It exists
to be LOOKED AT: the tests check text sizes and positions, not whether the
chart reads.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from harness.figure_guards import PHONE_WIDTH_PX
from placement.figures import FIGURES


def phone_copy(src: Path, dst: Path) -> Path:
    img = mpimg.imread(src)
    h, w = img.shape[0], img.shape[1]
    fig = plt.figure(figsize=(PHONE_WIDTH_PX / 100, PHONE_WIDTH_PX / 100 * h / w), dpi=100)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.imshow(img)
    ax.axis("off")
    fig.savefig(dst, dpi=100)
    plt.close(fig)
    return dst


def main(argv=None) -> list[Path]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--analysis", default="data/a4/analysis.json")
    ap.add_argument("--out", default="build/a4-figures")
    args = ap.parse_args(argv)
    analysis = json.loads(Path(args.analysis).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, draw in FIGURES.items():
        path = draw(analysis, out / f"{name}.png")
        written += [path, phone_copy(path, out / f"{name}-phone.png")]
        print(f"wrote {path} and its phone copy")
    return written


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_figures.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — 24 tests

- [ ] **Step 7: Render the drafts**

Render the four figures from the complete synthetic analysis the tests use:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'EOF'
import json, sys
from pathlib import Path
sys.path[:0] = ["tests", "."]
from a4_analysis_example import example_analysis
root = Path("build/a4-draft")
root.mkdir(parents=True, exist_ok=True)
(root / "analysis.json").write_text(json.dumps(example_analysis(root)))
EOF
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_render_figures.py --analysis build/a4-draft/analysis.json --out build/a4-draft/figures
```

Expected: eight lines, `wrote build/a4-draft/figures/<name>.png and its phone copy` for each figure (the phone copy is written alongside).

- [ ] **Step 8: Look at every draft, at both widths**

Use superpowers:verifying-visual-output. These are PNG figures, not a page, so its layers map onto them like this:
- **Layer 2 (geometry)** is the test file above: every text above the phone floor and on the canvas.
- **Layer 3 (screenshots)** is the render itself: open each `build/a4-draft/figures/<name>.png` (desktop width) and `<name>-phone.png` (375 px, a phone), and LOOK at both.
- **Layer 4 (eyes on)** is confirming, per figure, what a reader must be able to see:

| Figure | Must be visible at both widths |
|---|---|
| `crossover` | two columns, spread and bursty; three strategy lines in the top row with an `x` for a dominated point; the aggregate p99 with error bars and the dotted SLO line in the bottom row; the green "validated point" line on the bursty column; the legend and footnote below, uncut |
| `deciles` | two panels; deciles 1 (hottest) to 10 (coldest); the dashed "swap sized on aggregate" line rising at the coldest decile above the SLO line; the legend clear of the SLO label |
| `interference` | the solo curve and four split curves with range bars; the two held-out diamonds; both "KV full" lines labelled; the x axis in powers of two |
| `swap_stages` | two bars with seconds inside the wide segments and `Σ` totals at the ends; hatched segments; the two-column legend below, uncut; both footnote lines, including "Median swap" |

Write down anything that overlaps, is cut off or cannot be read on the phone copy, fix it in `placement/figures.py`, re-run Steps 4 and 6, and look again. Attach the two `crossover` images' paths to the task report.

- [ ] **Step 9: Lint**

Run: `.venv/bin/ruff check placement/figures.py scripts/a4_render_figures.py tests/a4_analysis_example.py tests/test_placement_figures.py`

Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
git add placement/figures.py scripts/a4_render_figures.py tests/a4_analysis_example.py tests/test_placement_figures.py
git commit -m "figures: artifact 4's four, from analysis.json, legible at phone width"
```

---

## Task 15: The GPU-free rehearsal, end to end

**Files:**
- Modify: `tests/a4_fakes.py`
- Test: `tests/test_a4_plan3_end_to_end.py`

This runs the whole of Part B's procedure on fakes, with real stores, real scripts and real records:
1. `a4_step2 values` on an example report.
2. The cell, swap and sleep campaigns from the written design files, through `scripts/a4_measure.py`'s loop, `measure_job` and the harness's JSON-round-tripping stub submitter.
3. `a4_step2 replay` from the cells.
4. `a4_analyse`.
5. The cost file.
6. The figures.

It catches what unit tests cannot: a design file that does not load back, a payload a job cannot run, a record a reduction cannot read.

The fake engines' logs gain the two lines figure 4's stage split reads (`tests/a4_fakes.py`). Plan 2's tests do not read them.

- [ ] **Step 1: Give the fake engines the two log lines figure 4 reads**

In `tests/a4_fakes.py`, replace:

```python
COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"
```

with:

```python
COMPILE_LINE = "(EngineCore pid=340) INFO 10-04 12:00:30 [monitor.py:53] torch.compile took {s} s in total"
# The two lines plan 3's figure 4 splits a swap-in by (placement/stages.py).
LOADING_LINE = ("(EngineCore pid=340) INFO 10-04 12:00:20 [model_runner.py:329] Model loading took "
                "7.49 GiB and 8.0 seconds")
INIT_LINE = ("(EngineCore pid=340) INFO 10-04 12:00:40 [core.py:348] init engine (profile, create "
             "kv cache, warmup model) took {s} s (compilation: {c} s)")
```

In `tests/a4_fakes.py`, replace:

```python
        lines = [VERSION_LINE, NON_DEFAULT_LINE, KV_LINE,
                 COMPILE_LINE.format(s=self.compile_s.get(model, 19.0))]
```

with:

```python
        compile_s = self.compile_s.get(model, 19.0)
        lines = [VERSION_LINE, NON_DEFAULT_LINE, KV_LINE, LOADING_LINE,
                 COMPILE_LINE.format(s=compile_s), INIT_LINE.format(s=compile_s + 10.0, c=compile_s)]
```

- [ ] **Step 2: Write the rehearsal**

Create `tests/test_a4_plan3_end_to_end.py`:

```python
"""Plan 3's GPU-free rehearsal: from a reconnaissance report to every file the
publication reads, through the scripts the paid steps use, on fake workers.

1. `scripts/a4_step2.py values` writes the registered values and design files.
2. The cell, swap and sleep campaigns run through `scripts/a4_measure.py`'s
   loop, each payload through `placement_measure.jobs.measure_job` on fakes,
   JSON round-tripped by the harness's stub submitter, into their stores.
3. `scripts/a4_step2.py replay` writes the validation trace from those cells.
   The replays themselves are the simulator's latencies on that trace
   (tests/a4_stores.py): the real driver runs in real time, and its own tests
   cover it against the simulator.
4. `scripts/a4_analyse.py` reduces everything; the sweep's evaluations are
   hand-built, because the real sweep is hours of CPU (tests/test_a4_sweep.py
   runs it small).
5. `scripts/a4_cost_file.py` and `scripts/a4_render_figures.py` finish.
"""

import contextlib
import importlib.util
import json
from pathlib import Path

import pytest
from a4_evaluations import rich_sweep
from a4_examples import example_report
from a4_fakes import Clock, FakeEngines, memory_script
from a4_stores import _replays
from test_a4_measure_end_to_end import Sampler
from test_placement_cost_file import _artifact_5_reads
from test_placement_measure_sleep_and_extra_cells import _timed_deps

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from placement.inputs import load_records
from placement.registration import SECTION
from placement_measure.colocation import CellDeps
from placement_measure.gpu_memory import read_memory, wait_for_release
from placement_measure.jobs import measure_job
from placement_measure.records import A4Run
from placement_measure.swap import SwapDeps

REPO = Path(__file__).resolve().parents[1]
WARM = {"Qwen/Qwen3-4B": 0.3, "Qwen/Qwen3-4B-Base": 0.3, "Qwen/Qwen3-4B-Instruct-2507": 0.3}
HOST = {"host_id": "h1", "runpod_pod_id": None}


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cell_worker(payload):
    clock = Clock()
    neighbour = payload["cell"]["neighbour"] or 0

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

    deps = CellDeps(served=FakeEngines(clock, compile_s=WARM).served, run_one=run_one,
                    run_bench=bench, sampler_factory=contextlib.nullcontext,
                    running_sampler=Sampler,
                    wait_running=lambda *a, **k: {"reached": True, "seconds": 1.0},
                    stoppable=stoppable, clock=clock)
    return measure_job(payload, cell_deps=deps, host=lambda: HOST, clock=clock)


def _swap_worker(payload):
    clock = Clock()
    run = memory_script([500, 9000, 500])
    deps = SwapDeps(
        served=FakeEngines(clock, compile_s=WARM).served, read_memory=lambda: read_memory(run=run),
        wait_for_release=lambda t, timeout_s: wait_for_release(
            t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [], clock=clock)
    return measure_job(payload, swap_deps=deps, host=lambda: HOST, clock=clock)


def _sleep_worker(payload):
    clock = Clock()
    return measure_job(payload, recon_deps=_timed_deps(clock), host=lambda: HOST, clock=clock)


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    root = tmp_path_factory.mktemp("a4")
    for d in ("fixtures/a4", "data/a4", "docs", "placement"):
        (root / d).mkdir(parents=True)
    (root / "fixtures/a4/recon-report.json").write_text(json.dumps(example_report()))
    (root / "data/a4/screen.json").write_text(
        json.dumps({"chosen": {"offered_gpus": 2.0, "slo_swap_multiple": 4.0}}))
    # Before step 2's values, which the repository's copy has after publication.
    doc = (REPO / "docs/experiment-a4.md").read_text().split(SECTION)[0]
    (root / "docs/experiment-a4.md").write_text(doc)
    step2 = _script("a4_step2")
    reg = step2.write_values(root, 0.69, "test rate, not a quote", "2026-10-14")

    measure = _script("a4_measure")
    for kind, name, worker in (("cell", "cells", _cell_worker), ("swap", "swaps", _swap_worker),
                               ("sleep", "sleep", _sleep_worker)):
        design = measure.load_design(kind, root / "data/a4/designs" / f"{name}.json")
        measure.run_measurement(design, kind, PayloadStubSubmitter(worker).submit_payload,
                                root / "data/a4" / f"{name}.jsonl", source="stub")
    step2.write_replay(root, ["data/a4/cells.jsonl"], ["data/a4/swaps.jsonl"])
    cells = load_records([root / "data/a4/cells.jsonl"])
    swaps = load_records([root / "data/a4/swaps.jsonl"])
    store = JsonlStore(root / "data/a4/replay.jsonl", A4Run)
    for record in _replays(reg, cells, swaps):
        store.append(record)

    analyse = _script("a4_analyse")
    analyse.a4_sweep.evaluations_for = lambda *a, **k: rich_sweep()
    analysis = analyse.analyse_all(reg, analyse.STORES, root=root,
                                   a1_store=REPO / "data/campaign.jsonl",
                                   sweep_out=root / "sweep", workers=1)
    (root / "data/a4/analysis.json").write_text(json.dumps(analysis, indent=1))
    return root, reg, analysis


def test_every_campaign_ran_ok_through_the_real_loop(rehearsal):
    root, reg, _ = rehearsal
    for name in ("cells", "swaps", "sleep"):
        records = load_records([root / "data/a4" / f"{name}.jsonl"])
        assert records and all(r.outcome == "ok" for r in records), name
    cells = load_records([root / "data/a4/cells.jsonl"])
    conditions = {r.condition for r in cells}
    assert set(reg["HELD_OUT"]) <= conditions and f"solo:o{reg['SOLO_LEVELS'][-1]}" in conditions


def test_the_reductions_validation_and_held_out_check_pass(rehearsal):
    _, _, analysis = rehearsal
    assert analysis["validation"]["outcome"] == "passed"
    assert [c["passed"] for c in analysis["held_out"]] == [True, True]
    assert analysis["inputs"]["stages"]["n"] > 0
    assert analysis["inputs"]["sleep_mode"]["n"] == 8


def test_the_cost_file_and_the_figures_are_written(rehearsal, tmp_path):
    root, _, _ = rehearsal
    out = root / "data/a4/cost_per_tenant.json"
    _script("a4_cost_file").main(["--analysis", str(root / "data/a4/analysis.json"),
                                  "--out", str(out)])
    _artifact_5_reads(json.loads(out.read_text()))
    written = _script("a4_render_figures").main(
        ["--analysis", str(root / "data/a4/analysis.json"), "--out", str(tmp_path / "figs")])
    assert len(written) == 8 and all(p.stat().st_size > 10_000 for p in written)
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_a4_plan3_end_to_end.py tests/test_placement_measure_swap.py tests/test_placement_measure_jobs.py -q`

Expected: PASS — 3 rehearsal tests, and plan 2's swap and job tests unchanged

- [ ] **Step 4: Lint**

Run: `.venv/bin/ruff check tests/a4_fakes.py tests/test_a4_plan3_end_to_end.py`

Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tests/a4_fakes.py tests/test_a4_plan3_end_to_end.py
git commit -m "test: plan 3's campaigns, analysis, cost file and figures rehearsed end to end on fakes"
```

---

## Task 16: The post's headline numbers

**Files:**
- Create: `placement/post_numbers.py`
- Test: `tests/test_placement_post_numbers.py`

Every headline number the post quotes is rendered once, from `analysis.json`, in a fixed format: dollars to the cent, seconds to one decimal place, whole percentages. The list:
- the decision rule;
- the crossover;
- the reference costs;
- the aggregate-sized fleet's coldest-decile breach;
- the swap and sleep medians;
- the KV ceilings;
- the validation and held-out results.

Part B's post test requires each string verbatim in the post. A number typed by hand drifts the first time the data is re-analysed. Artifact 1 holds its explainer to `explainer/numbers.json` the same way.

- [ ] **Step 1: Write the failing test**

Create `tests/test_placement_post_numbers.py`:

```python
"""The post's headline numbers, rendered from a complete synthetic analysis."""

import pytest
from a4_analysis_example import example_analysis

from placement.post_numbers import numbers


@pytest.fixture(scope="module")
def nums(tmp_path_factory):
    return numbers(example_analysis(tmp_path_factory.mktemp("a4")))


def test_the_decision_rule_and_crossover_are_stated_per_regime(nums):
    assert nums["bursty_decision_rule"].startswith("s = 0.6: ")
    assert "swap" in nums["bursty_decision_rule"]
    assert nums["spread_crossover"].startswith("between s = ")


def test_the_reference_costs_are_dollars_with_cents(nums):
    for key in ("ref_dedicate_per_tenant", "ref_swap_per_tenant", "ref_dedicate_over_cheapest"):
        assert nums[key].startswith("$") and nums[key][-3] == "."


def test_the_fairness_number_is_a_whole_percentage(nums):
    assert nums["ref_swap_aggregate_coldest_breach"] == "25%"
    assert nums["ref_swap_aggregate_gpus"] == "5 GPUs"


def test_validation_and_inputs_are_stated(nums):
    assert nums["validation_outcome"] == "passed"
    assert nums["validation_bins"].endswith("judged bins")
    assert nums["held_out"] == "2 of 2 held-out cells"
    assert nums["swap_median"].endswith(" s") and nums["sleep_switch_median"].endswith(" s")
    assert nums["kv_split_ceiling"] == "17 requests" and nums["kv_solo_ceiling"] == "86 requests"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_post_numbers.py -q`

Expected: FAIL — `ModuleNotFoundError: No module named 'placement.post_numbers'`

- [ ] **Step 3: Write the numbers**

Create `placement/post_numbers.py`:

```python
"""The post's headline numbers, formatted once from `data/a4/analysis.json`.

The post quotes each of these strings verbatim, and `tests/test_a4_post.py`
(written at publication) fails if any is missing from `docs/post-a4.md`. A
number typed by hand drifts from the data the first time the data is
re-analysed; a number rendered here cannot. Artifact 1 holds its explainer to
`explainer/numbers.json` the same way.

Formats are fixed here, not at the call site: two decimal places for dollars,
one for seconds, whole percentages.
"""

from placement.fleet import STRATEGIES

__all__ = ["numbers"]


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def _s(x: float) -> str:
    return f"{x:.1f} s"


def _rule(segments: list[dict]) -> str:
    parts = []
    for seg in segments:
        span = (f"s = {seg['from_s']}" if seg["from_s"] == seg["to_s"]
                else f"s = {seg['from_s']}–{seg['to_s']}")
        parts.append(f"{span}: {' = '.join(seg['cheapest']) or 'none meets the SLO'}")
    return "; ".join(parts)


def numbers(analysis: dict) -> dict[str, str]:
    out: dict[str, str] = {
        "slo": _s(analysis["design"]["slo_seconds"]),
        "offered_gpus": f"{analysis['design']['offered_gpus']:g} GPUs",
        "gpu_hourly_rate": _usd(analysis["rate"]["gpu_hourly_rate"]),
        "repetitions": str(analysis["design"]["repetitions"]),
    }
    for regime, r in analysis["regimes"].items():
        out[f"{regime}_decision_rule"] = _rule(r["decision_rule"])
        if r["gaps"]:
            out[f"{regime}_gaps"] = "; ".join(f"s = {g['s']}: {g['reason']}" for g in r["gaps"])
        between = r["crossover"]["between"]
        out[f"{regime}_crossover"] = ("no crossover in the swept range" if not between else
                                      "; ".join(f"between s = {a} and s = {b}" for a, b in between))
    ref = analysis["reference"]
    point = next(p for p in analysis["regimes"][ref["regime"]]["points"] if p["s"] == ref["s"])
    if point["evaluable"]:
        for strategy in STRATEGIES:
            v = point["strategies"][strategy]
            if v is not None:
                out[f"ref_{strategy}_gpus"] = f"{v['m']} GPUs"
                out[f"ref_{strategy}_per_tenant"] = _usd(v["cost_per_tenant_month"])
                out[f"ref_{strategy}_per_million_tokens"] = _usd(v["cost_per_million_tokens"])
        if point["dedicate_over_cheapest_per_month"] is not None:
            out["ref_dedicate_over_cheapest"] = _usd(point["dedicate_over_cheapest_per_month"])
        agg = point["aggregate_rule"].get("swap")
        if agg is not None and agg["coldest_decile_breach"] is not None:
            out["ref_swap_aggregate_gpus"] = f"{agg['m']} GPUs"
            out["ref_swap_aggregate_coldest_breach"] = f"{agg['coldest_decile_breach']:.0%}"
    inputs = analysis["inputs"]
    out["swap_median"] = _s(inputs["swaps"]["simulated"]["p50"])
    if inputs.get("sleep_mode"):
        out["sleep_switch_median"] = _s(inputs["sleep_mode"]["p50"])
    out["kv_split_ceiling"] = f"{inputs['kv']['split_ceiling']} requests"
    if inputs["kv"]["solo_ceiling"] is not None:
        out["kv_solo_ceiling"] = f"{inputs['kv']['solo_ceiling']} requests"
    v = analysis["validation"]
    out["validation_outcome"] = v["outcome"]
    if "latency" in v:
        misses = v["latency"]["compared"] - v["latency"]["agreeing"]
        out["validation_bins"] = f"{misses} of {v['latency']['compared']} judged bins"
    passed = sum(c["passed"] for c in analysis["held_out"])
    out["held_out"] = f"{passed} of {len(analysis['held_out'])} held-out cells"
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_post_numbers.py tests/test_placement_boundary.py tests/test_placement_no_reimplementation.py -q`

Expected: PASS — 4 tests

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check placement/post_numbers.py tests/test_placement_post_numbers.py`

Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add placement/post_numbers.py tests/test_placement_post_numbers.py
git commit -m "post: the headline numbers, formatted once from the analysis"
```

---

## Task 17: The campaigns runbook

**Files:**
- Create: `docs/runbook-a4-campaigns.md`

The owner's procedure for Part B's paid steps, in the shape of plan 2's reconnaissance runbook:
- the second template;
- the preflight;
- the cost estimate and the pre-registered cut order;
- the cell campaign with its top-up procedure;
- swaps and sleep mode;
- the validation trace and its replays;
- what to record.

- [ ] **Step 1: Write the runbook**

Create `docs/runbook-a4-campaigns.md`:

````markdown
# Runbook: artifact 4's paid measurement campaigns

For the owner; not a plan step. Do not run any of this without the owner's
say-so. It rents a GPU for roughly half a day in total, spread over several
sessions.

**Before starting**, all four must hold, in this order:
1. `docs/recon-a4.md` is committed, and its go/no-go passed for one class.
2. `data/a4/screen.json` is committed.
3. `docs/experiment-a4.md` has its "Step 2, part 2" section,
   `placement/registered.py` exists, and both are committed. Their git
   timestamp must predate every campaign record.
4. The worker image has been rebuilt from a commit containing plan 3's worker
   changes (`placement_measure/replay.py` and the `sleep` and `replay` job kinds).

**A. Image.** Push. CI (`build-worker.yml`) rebuilds the image because
`placement_measure/**` changed; record the digest its summary prints. The
analysis cites it beside reconnaissance's.

**B. Template.** A second template beside the reconnaissance one: the same
image digest, network volume `9c7ut2slrd` and container disk, but
`dockerStartCmd` `python3 -u /opt/a4_measure_handler.py`. Point the endpoint
(`RUNPOD_A4_ENDPOINT_ID`) at it: `workersMin` 0, `workersMax` 1, `idleTimeout`
5 s, `executionTimeoutMs` 1800000. One worker keeps the compile cache warm
across a campaign, so only the first job on a fresh worker compiles.

**C. Free preflight.** One GET, no job.

```bash
set -a; . ./.env; set +a   # RUNPOD_API_KEY, RUNPOD_A4_ENDPOINT_ID
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind cell --design data/a4/designs/cells.json --template-id <template id> --preflight-only
```

Expected: `[preflight] endpoint <id> matches artifact 4's pin set`.

**D. Cost estimate.** Wall time per job, from artifact 2's pilot on this
image (an 8B engine started in 84.5 s cold and 30.6 s warm) and nothing yet
measured for a 4B engine under load, so every figure here is an estimate:

| Campaign | Jobs at the example design | Per job | GPU time |
|---|---|---|---|
| Cells: solo grid, co-located grid, held-out cells | about 35 cells x 4 repeats = 140 | 2-6 min: one or two engine starts, then a measured run of at least 100 requests | 7-11 h |
| Swaps | 6 pairs x 2 cache states x 3 = 36 | 1-3 min: two engine starts | 1-2 h |
| Sleep mode, if reconnaissance found it working | 8 | 3-5 min | under 1 h |
| Validation replays | 3 | 20-28 min: a 900 s trace plus swaps and drain | about 1.5 h |

`scripts/a4_measure.py` prints the job count before it submits; the exact
count follows from the registered design. Price it with RunPod's per-second
rate on the day, read off the console. At the repository's illustrative
$0.00031/s, about 12 GPU-hours is about $13. **If the budget binds, cut in
the pre-registered order (scope amendment §9): the interference grid's
resolution first.** That is an amendment to step 2, committed before the cut
campaign runs, never a quiet edit to a design file.

**E. Cells.** The longest campaign. It resumes where it stopped, so it can run
over several sessions.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind cell --design data/a4/designs/cells.json --template-id <id> --store data/a4/cells.jsonl
```

To continue after a stop, add `--resume`. When it finishes, list the cells
that are short of valid repeats (a run whose measured engine compiled does not
count):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import json
from placement import registered as R
from placement.inputs import load_records, short_cells
from placement.step2 import CELL_MIN_VALID
cells = [f'solo:o{c}' for c in R.SOLO_LEVELS] + [f'pair:o{o}:n{n}' for o in R.OWN_LEVELS for n in R.NEIGHBOUR_LEVELS] + list(R.HELD_OUT)
print(json.dumps(short_cells(load_records(['data/a4/cells.jsonl']), cells, min_repeats=CELL_MIN_VALID, require_warm_compile=True)))"
```

If any are listed, write a top-up design: a copy of `data/a4/designs/cells.json`
with `own_levels` and `neighbour_levels` set to `[]`, `solo` false,
`extra_cells` set to the listed cells, `repeats` 2 and a new `seed`, saved as
`data/a4/designs/cells-topup-1.json` and committed before it runs. Run it into
its own store, `data/a4/cells-topup-1.jsonl`. Every later step takes both
stores (`--cells` twice).

**F. Swaps, then sleep mode** (skip sleep mode if `registered.SLEEP_MEASURED` is False):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind swap --design data/a4/designs/swaps.json --template-id <id> --store data/a4/swaps.jsonl
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind sleep --design data/a4/designs/sleep.json --template-id <id> --store data/a4/sleep.jsonl
```

**G. The validation trace, then its replays.** The trace's load is a fraction
of the measured solo saturation, and the pre-registered draw is the first whose
replay the simulator predicts will finish within a job and genuinely swap. So
the design is written from the cell and swap stores, then committed, then run.
Add `--cells` once per cell store, top-ups included:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_step2.py replay --cells data/a4/cells.jsonl --swaps data/a4/swaps.jsonl
git add data/a4/designs/replay.json data/a4/designs/replay-check.json && git commit -m "data: artifact 4's validation trace, from the measured curve and swaps"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_measure.py --kind replay --design data/a4/designs/replay.json --template-id <id> --store data/a4/replay.jsonl
```

If the script stops with "no pre-registered validation draw is feasible", do
not run anything: the gate cannot run as registered, and the owner decides,
as an amendment. `replay-check.json` records every draw tried and why.

The gate needs exactly three ok replays. A replay marked failed (a request
errored, or the job budget cut it short) does not count, and a fourth repeat
is not run to replace it: an open repeat count lets the band grow until the
model fits (artifact 2's gate). Stop and record the failure; the owner
decides whether the validation is re-run as a whole, as a disclosed amendment.

The replay payload carries the whole trace, and its output every request's
times. At the example design that is a few hundred kilobytes each way.
RunPod's payload and output limits are UNVERIFIED (the shared tooling plan's
item 12). If a replay comes back truncated or refused, that is the cause.

**H. After the runs.** Commit every store and design file, and record from the
console: the spend per campaign and the image digest. `docs/spend-a4.md`
(plan 3) collects them. The analysis is CPU only, and plan 3's next task.
````

- [ ] **Step 2: Commit**

```bash
git add docs/runbook-a4-campaigns.md
git commit -m "docs: the runbook for artifact 4's paid measurement campaigns"
```

---

## Task 18: Verification

**Files:**

Part A is done only when the whole repository passes, not just this plan's files.

- [ ] **Step 1: Run the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" -q`

Expected: every test passes. Plan 3 adds 152 to the count before it (1,841 on the commit it was verified against, 1,993 after), which is relative because other sessions add tests too.

- [ ] **Step 2: Lint everything**

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

- [ ] **Step 3: Run artifact 1's parity gate**

Run: `bash scripts/parity_check.sh`

Expected: `PARITY OK`. Plan 3 changes nothing artifact 1 publishes; this proves it.

- [ ] **Step 4: Confirm the worker image will carry plan 3's worker code**

Run: `grep -n 'placement_measure' worker/Dockerfile .github/workflows/build-worker.yml`

Expected: plan 2's `COPY placement_measure /opt/placement_measure` and the CI path `placement_measure/**`. The new `replay.py` and the new job kinds ride on them, and the handler is unchanged, so no image file changes.

- [ ] **Step 5: Stop**

Part A is complete. Part B starts only when its own prerequisites hold, and its paid steps are the owner's.

---

# Part B — measurement and publication

Part B starts only when Task 19's prerequisites hold. Its paid steps are the owner's: an agent stops at each STOP and waits. Each agent step names its command and what to commit.

## Task 19: Prerequisites for Part B — STOP if any is false

- [ ] **Step 1: Reconnaissance is recorded and passed**

```bash
test -f docs/recon-a4.md && test -f fixtures/a4/recon-report.json && echo OK
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import json; r = json.load(open('fixtures/a4/recon-report.json'))
print({k: v['passed'] for k, v in r['go_no_go'].items()})
from placement.step2 import measurement_design; print(measurement_design(r)['model'])"
```

Expected: `OK`, at least one class `True`, and a model name. A `NotDecidable` here is a STOP for the owner, with its message.

- [ ] **Step 2: The owner has given the GPU hourly rate and where it was read**

It is read off the RunPod console on the day, for the pinned GPU class. Artifact 5 takes the same rate from this artifact, so it is asked for once, here, and written into step 2.

---

## Task 20: The screen

- [ ] **Step 1: Run it in the background, and log it**

```bash
PYTHONDONTWRITEBYTECODE=1 nohup .venv/bin/python scripts/a4_screen.py --workers 8 > build/a4-screen.log 2>&1 &
```

It took 25.5 minutes on 8 cores on the example report. Expected at the end of the log: nine candidate lines and `chosen: {...}`.

- [ ] **Step 2: Commit**

```bash
git add data/a4/screen.json
git commit -m "data: artifact 4's ranking-blind screen, on reconnaissance's swaps and the placeholder engines"
```

---

## Task 21: Pre-registration step 2, part 2 — the values

- [ ] **Step 1: Write the values**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_step2.py values --rate <rate> --provenance "<where and when the owner read it>" --date <today>
```

Expected: `placement/registered.py`, `data/a4/designs/cells.json`, `swaps.json` (and `sleep.json` if sleep mode works) written, and the section appended.

- [ ] **Step 2: Add the test that re-derives them**

Create `tests/test_placement_registered.py`:

```python
"""Step 2's committed values are the pre-registered rules applied to the
committed reconnaissance report and screen, and nothing else.

`placement/registered.py`, the design files and the "Step 2, part 2" section
of `docs/experiment-a4.md` were all written by `scripts/a4_step2.py values`.
This re-derives every value, so a hand edit to any of the three, or a change
to a rule after the values were committed, fails here."""

import json
import re
from pathlib import Path

from placement import registered
from placement.registration import SECTION, design_files, mismatches, render_doc, values
from placement.screen import choose
from placement.step2 import measurement_design

REPO = Path(__file__).resolve().parents[1]
REPORT = json.loads((REPO / "fixtures" / "a4" / "recon-report.json").read_text())
SCREEN = json.loads((REPO / "data" / "a4" / "screen.json").read_text())
DOC = (REPO / "docs" / "experiment-a4.md").read_text()


def _committed() -> dict:
    return {k: getattr(registered, k) for k in dir(registered) if k.isupper()}


def _expected() -> dict:
    return values(measurement_design(REPORT), SCREEN, rate=registered.GPU_HOURLY_RATE,
                  provenance=registered.RATE_PROVENANCE)


def test_the_registered_values_are_the_rules_applied_to_the_inputs():
    assert mismatches(_committed(), _expected()) == []


def test_the_screens_recorded_choice_is_its_best_candidate():
    best = choose(SCREEN["candidates"])
    assert SCREEN["chosen"] == {"offered_gpus": best["offered_gpus"],
                                "slo_swap_multiple": best["slo_swap_multiple"]}


def test_the_design_files_are_the_registered_designs():
    for name, design in design_files(measurement_design(REPORT)).items():
        committed = json.loads((REPO / "data" / "a4" / "designs" / f"{name}.json").read_text())
        assert committed == json.loads(json.dumps(design)), name


def test_the_document_states_the_values_verbatim():
    assert DOC.count(SECTION) == 1
    date = re.search(r"Committed (\d{4}-\d{2}-\d{2})\.", DOC[DOC.index(SECTION):]).group(1)
    assert render_doc(_committed(), date) in DOC
```

- [ ] **Step 3: Run it**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -o addopts="" tests/test_placement_registered.py tests/test_placement_step2_doc.py -q`

Expected: PASS.

- [ ] **Step 4: Commit, before any measurement runs**

```bash
git add placement/registered.py data/a4/designs docs/experiment-a4.md tests/test_placement_registered.py
git commit -m "prereg: artifact 4's step 2 values, from reconnaissance and the screen, before the first measurement"
```

- [ ] **Step 5: Tell artifact 5's session the rate and the reference point**

Artifact 5's step 2 reads `GPU_HOURLY_RATE` from `placement/registered.py`, and its cost table reads the reference point `{"regime": "bursty", "s": 1.0}` from the file Task 26 writes. That is a message to its session, not an edit to its files.

---

## Task 22: The paid campaigns — STOP: the owner runs them

- [ ] **Step 1: Hand over**

The owner follows `docs/runbook-a4-campaigns.md`, sections A to F:
- the image rebuild and template;
- the preflight;
- the cell campaign and any top-up;
- swaps;
- sleep mode.

The agent does nothing until the owner reports the stores committed.

---

## Task 23: The validation trace and its replays

- [ ] **Step 1: Write the trace's design**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_step2.py replay --cells data/a4/cells.jsonl --swaps data/a4/swaps.jsonl
```

Add `--cells` once per top-up store. Expected: one line per draw tried and `validation trace: ...`. If it stops with "no pre-registered validation draw is feasible", STOP: that is the owner's decision, and nothing is replayed.

- [ ] **Step 2: Commit**

```bash
git add data/a4/designs/replay.json data/a4/designs/replay-check.json
git commit -m "data: artifact 4's validation trace, from the measured curve and swaps"
```

- [ ] **Step 3: STOP — the owner runs the three replays** (runbook section G)

---

## Task 24: The analysis

- [ ] **Step 1: Run it in the background, and log it**

```bash
PYTHONDONTWRITEBYTECODE=1 nohup .venv/bin/python scripts/a4_analyse.py --workers 8 > build/a4-analyse.log 2>&1 &
```

Add `--cells` per cell store if there was a top-up (every store, the main one included). The sweep is hours of CPU the first time; its evaluations are cached under `build/a4-sweep/`. Expected at the end: `wrote data/a4/analysis.json: validation <outcome>, held-out [...]` and one decision-rule line per regime.

- [ ] **Step 2: Read the verdicts before anything else**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import json; a = json.load(open('data/a4/analysis.json'))
print(a['validation']['outcome'], a['validation'].get('detail'))
print([(c['cell'], c['passed']) for c in a['held_out']])
print({r: v['gaps'] for r, v in a['regimes'].items()})"
```

If validation is anything but `passed`, or a held-out cell failed: STOP and report to the owner. August §9: a miss is publishable with its magnitude; a genuine model bug may be fixed and re-validated, with the fix disclosed; the choice is the owner's.

- [ ] **Step 3: Commit**

```bash
git add data/a4/analysis.json data/a4/*.jsonl
git commit -m "data: artifact 4's analysis on measured inputs"
```

---

## Task 25: The figures (changes pixels)

- [ ] **Step 1: Render**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_render_figures.py --out build/a4-figures
```

- [ ] **Step 2: Look at every figure, at both widths**

Use superpowers:verifying-visual-output, as in Task 14:
- open each `build/a4-figures/<name>.png` and `<name>-phone.png`;
- confirm what Task 14's table lists;
- fix anything that overlaps or cannot be read on the phone copy, in `placement/figures.py`, re-run Task 14's tests, and render again.

Real data puts labels where synthetic data did not, so this look is not optional.

- [ ] **Step 3: Publish the copies**

```bash
mkdir -p docs/figures/a4 && cp build/a4-figures/*.png docs/figures/a4/
git add docs/figures/a4
git commit -m "figures: artifact 4's four, rendered from data/a4/analysis.json, with phone copies"
```

---

## Task 26: Artifact 5's file

- [ ] **Step 1: Write it**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a4_cost_file.py
```

Expected: `wrote data/a4/cost_per_tenant.json: reference ...: dedicated $..., swapped $... per tenant per month`. If it raises because swap is dominated or the point is not evaluable at the reference, STOP: that is a finding for the owner and for artifact 5, not a gap to fill.

- [ ] **Step 2: Commit, and tell artifact 5's session the file is ready**

```bash
git add data/a4/cost_per_tenant.json
git commit -m "data: artifact 4's cost per tenant, for artifact 5"
```

---

## Task 27: The post, and its gates

- [ ] **Step 1: Print the numbers the post must quote**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "
import json; from placement.post_numbers import numbers
for k, v in numbers(json.load(open('data/a4/analysis.json'))).items(): print(f'{k}: {v}')"
```

- [ ] **Step 2: Draft `docs/post-a4.md`**

**Shape.** It opens with an HTML comment holding `Permanent slug: /experiments/multi-model-placement` and the rule that the slug never changes, as `docs/post.md` does. Then the lead: the decision rule, as a rule a reader can locate their workload against. Then these sections, in this order:
- `## The crossover`, with figure 1;
- `## Why the naive answer is wrong`, the aggregate p99 against the per-tenant p99, with figure 2;
- `## The three primitives, measured`: swap cost with figure 4, interference with figure 3, and the KV split;
- `## Method`: the simulator, the traffic model, validation, and a link to `docs/experiment-a4.md`'s pre-registration;
- `## Where the boundary moves`, between the locality regimes;
- `## The excluded option`, adapter multiplexing and its precondition;
- `## Limits`;
- `## Reproduce it`;
- `## Next`.

**Required explanations** (August §10, amendment §5):
- why a swap is cheaper than a cold start and which stages it skips;
- that a process-level swap still re-pays interpreter startup;
- why co-located models do not halve each other's throughput;
- why a shrunken KV budget hurts more than proportionally;
- why the aggregate p99 is the wrong SLO for a multi-tenant fleet.

**Numbers and statements.**
- Every number from Step 1 is quoted verbatim, in both units: systems and dollars, with the rate's provenance.
- Each figure is linked as `![...](figures/a4/<name>.png)`.
- The validated point is stated, and so is extrapolation beyond it.
- The sleep-mode arm, if measured, is given beside the crossover and never folded into it.

The draft is the agent's; the owner revises it.

- [ ] **Step 3: Add the post, figure and parity gates**

Create `tests/test_a4_post.py`:

```python
"""Artifact 4's post quotes its numbers from the committed analysis, follows
the structure August §10 fixed, and carries the explanations it requires.

Every headline number is rendered by `placement.post_numbers` and must appear
verbatim: a number typed by hand drifts the first time the data is
re-analysed. The section headings are August §10's post structure."""

import json
from pathlib import Path

import pytest

from placement.post_numbers import numbers

REPO = Path(__file__).resolve().parents[1]
POST = (REPO / "docs" / "post-a4.md").read_text()
ANALYSIS = json.loads((REPO / "data" / "a4" / "analysis.json").read_text())
HEADINGS = (
    "## The crossover",
    "## Why the naive answer is wrong",
    "## The three primitives, measured",
    "## Method",
    "## Where the boundary moves",
    "## The excluded option",
    "## Limits",
    "## Reproduce it",
    "## Next",
)
# August §10's required explanations, and the amendment's additions: each must
# be argued in the post, so each has a phrase the argument cannot avoid.
REQUIRED = (
    "skips",                # why a swap is cheaper than a cold start, and what it skips
    "interpreter",          # a process-level swap re-pays interpreter startup (amendment §5)
    "KV",                   # why a shrunken KV budget hurts more than proportionally
    "aggregate p99",        # why the aggregate is the wrong SLO for a multi-tenant fleet
    "adapter",              # the excluded fourth option and its precondition
    "validated",            # the validated operating point, and extrapolation beyond it
    "pre-registration",     # the link to docs/experiment-a4.md
)


@pytest.mark.parametrize("key, value", sorted(numbers(ANALYSIS).items()))
def test_every_headline_number_is_quoted_verbatim(key, value):
    assert value in POST, f"{key}: the post does not say {value!r}"


@pytest.mark.parametrize("heading", HEADINGS)
def test_the_post_follows_the_fixed_structure(heading):
    assert f"\n{heading}" in POST


def test_the_headings_are_in_order():
    positions = [POST.index(f"\n{h}") for h in HEADINGS]
    assert positions == sorted(positions)


@pytest.mark.parametrize("phrase", REQUIRED)
def test_each_required_explanation_is_there(phrase):
    assert phrase in POST


def test_the_post_has_its_permanent_slug_and_links_the_pre_registration():
    assert "Permanent slug: /experiments/" in POST
    assert "experiment-a4.md" in POST
```

Create `tests/test_a4_published_figures.py`:

```python
"""The figures artifact 4's post links must be the ones its committed analysis
renders, as tests/test_published_figures.py holds artifact 1's.

`build/` is gitignored, so the published copies live in `docs/figures/a4/`.
A figure fix that lands in `placement/figures.py` without a re-render leaves a
stale PNG that nothing else in the suite can see. Renders are deterministic
(`tests/test_placement_figures.py` checks it), so the comparison is exact."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "docs" / "figures" / "a4"
FIGURES = ("crossover", "deciles", "interference", "swap_stages")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp("a4-figures")
    result = subprocess.run(
        [sys.executable, "scripts/a4_render_figures.py", "--analysis", "data/a4/analysis.json",
         "--out", str(out)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return out


@pytest.mark.parametrize("name", FIGURES)
def test_the_published_figure_is_what_the_analysis_renders(name, rendered):
    published = PUBLISHED / f"{name}.png"
    assert published.exists(), f"{published.relative_to(REPO)} is missing; see plan 3's figure task"
    assert published.read_bytes() == (rendered / f"{name}.png").read_bytes(), (
        f"{published.relative_to(REPO)} is stale: re-render and copy it in, or explain why "
        "the render changed")


@pytest.mark.parametrize("name", FIGURES)
def test_the_phone_copy_is_published_for_inspection(name, rendered):
    phone = PUBLISHED / f"{name}-phone.png"
    assert phone.exists() and phone.read_bytes() == (rendered / f"{name}-phone.png").read_bytes()


@pytest.mark.parametrize("name", FIGURES)
def test_the_post_links_the_figure(name):
    post = (REPO / "docs" / "post-a4.md").read_text()
    assert f"(figures/a4/{name}.png)" in post
```

Create `scripts/a4_parity_check.sh`:

```bash
#!/usr/bin/env bash
# Every published artifact-4 number and pixel, re-derived from the committed
# stores. Artifact 1's scripts/parity_check.sh, pointed at artifact 4.
#
# The analysis re-runs the sweep unless build/a4-sweep holds its cached
# evaluations. On a fresh clone that is hours of CPU; with the cache, seconds.
# The cache key covers every input, so a stale cache is never reused.
set -euo pipefail

PY=.venv/bin/python
export PYTHONDONTWRITEBYTECODE=1
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

echo "== tests =="
$PY -m pytest -q

echo "== lint =="
$PY -m ruff check .

echo "== analysis: every published number =="
CELLS=$(ls data/a4/cells*.jsonl | sed 's/^/--cells /' | tr '\n' ' ')
# shellcheck disable=SC2086
$PY scripts/a4_analyse.py $CELLS --out "$OUT/analysis.json" > /dev/null
if ! diff -q "$OUT/analysis.json" data/a4/analysis.json > /dev/null; then
  echo "PARITY FAILURE: analysis output differs from data/a4/analysis.json"
  diff "$OUT/analysis.json" data/a4/analysis.json | head -40
  exit 1
fi
echo "analysis.json: identical"

echo "== artifact 5's file =="
$PY scripts/a4_cost_file.py --analysis data/a4/analysis.json --out "$OUT/cost.json" > /dev/null
cmp -s "$OUT/cost.json" data/a4/cost_per_tenant.json || { echo "PARITY FAILURE: cost_per_tenant.json"; exit 1; }
echo "cost_per_tenant.json: identical"

echo "== figures: every published pixel =="
$PY scripts/a4_render_figures.py --analysis data/a4/analysis.json --out "$OUT/figures" > /dev/null
for f in crossover deciles interference swap_stages; do
  for v in "$f" "$f-phone"; do
    cmp -s "$OUT/figures/$v.png" "docs/figures/a4/$v.png" || { echo "PARITY FAILURE: $v.png"; exit 1; }
  done
  echo "$f.png: identical"
done

echo
echo "PARITY OK"
```

- [ ] **Step 4: Run every gate**

Run: `bash scripts/a4_parity_check.sh`

Expected: `PARITY OK`. It runs the whole suite and lint, then re-derives `analysis.json`, the cost file and all eight images, and compares each byte for byte. These scripts were run in full on a simulated publication on 2026-10-04: there, the sweep's cache made the analysis take seconds, and every comparison passed.

- [ ] **Step 5: Commit, and STOP for the owner's review**

```bash
chmod +x scripts/a4_parity_check.sh
git add docs/post-a4.md tests/test_a4_post.py tests/test_a4_published_figures.py scripts/a4_parity_check.sh
git commit -m "post: artifact 4's draft, with its number, figure and parity gates"
```

---

## Task 28: Spend, the definition of done, and publication — the owner's

- [ ] **Step 1: Wall-clock per campaign, from the stores**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'EOF'
import glob
from placement.inputs import load_records
for path in sorted(glob.glob("data/a4/*.jsonl")):
    runs = load_records([path])
    seconds = sum(r.clock_A["t_result"] - r.clock_A["t_submit"] for r in runs
                  if r.clock_A.get("t_result") is not None)
    print(f"{path}: {len(runs)} jobs, {seconds / 3600:.2f} h from submit to result")
EOF
```

Submit-to-result time includes queueing, so it bounds the billed time from above. The billed amount is read off the console.

- [ ] **Step 2: The owner writes `docs/spend-a4.md`**

It has one row per paid step (reconnaissance, each campaign, the replays), each giving:
- jobs;
- hours from Step 1;
- the console's dollars, and the date they were read;
- the image digest.

The amendment §12 requires this artifact's own spend recorded.

- [ ] **Step 3: Check the definition of done**

Check it item by item: amendment §12's deltas, and every August §13 item they leave standing. Mark each met item with the commit or file that meets it. An unmet item is a STOP.

- [ ] **Step 4: Publish — the owner, after artifact 2's post**

Run artifacts 1 and 2's pre-publish boundary gate, and confirm `scripts/a4_parity_check.sh` passes on the commit to be published.

---

## Self-review notes

**Spec coverage.**

| Requirement | Task |
|---|---|
| Amendment §14, the owner's decision | 1 |
| August §8: hit rate, swap rate, aggregate and per-decile p99, cost per token, tail-tenant SLO cost, crossover | 2, 10 |
| §1e item 7, the in-container replay driver | 4 |
| §6, the sleep-mode arm, measured and reported, not simulated | 3, 5, 12 |
| §3 and §12, the second pre-registration step, before the first measurement | 5 (rules), 9 and 21 (values) |
| §14's regime screen, ranking-blind | 6, 20 |
| §5: page cache, compile state and warm-compile validity | 5, 7, 11 |
| August §9: the replay gate, the band from three repeats, the swap timeline, the interference check | 3, 7, 8, 23, 24 |
| §1e item 9, analysis; item 10, the money view | 10, 12 |
| §1e item 11, four figures and their drift test | 11, 14, 25, 27 |
| §11, `data/a4/cost_per_tenant.json` in the agreed format | 13, 26 |
| August §10, the post's structure and required explanations | 16, 27 |
| §12, the transitive boundary with exactly one adapter | 11 |
| §12, spend recorded | 28 |
| Publication after artifact 2 | 28 |

**Placeholder scan.** No step says "TBD" or "similar to Task N". Every code step carries the whole file or the exact lines it replaces. Three places take values only Part B can supply, by design: the rate, its provenance and the date (Task 21).

**Type consistency.** These names are used across tasks and were checked against the generated code:
- `measurement_design`, `SweepChoice`, `sweep_design`, `validation_design(measurement, curve, seed)`;
- `validation_trace` and `predict`'s three return values;
- `ReplayDesign.trace`, `REPLAY_CONDITION`;
- `ConfigOutcome`'s new fields;
- `cell_summary`, `held_out_check`, `eviction_seconds`;
- `analyse`, `numbers`, `build`;
- the analysis keys the figures read (`regimes`, `inputs`, `held_out`, `validation`, `reference`).

**UI verification audit.** Task 14 and Task 25 change pixels. Each has geometry tests beyond presence, a render at both desktop and phone width, and a person looking at both. There is no encapsulation boundary, and no visible UI is removed.

**Parity audit.** No capability is dropped; the table under "Changes to existing code" lists each modified file's kept capabilities, and each task's test step runs that file's existing tests. The one move, `grid` into `placement/grid.py`, is verified by `tests/test_a4_sweep.py`, which still proves the cache is reused. Nothing is deleted.

**What only the owner decides:**
- the rate (Task 19);
- the paid runs (Tasks 22 and 23);
- any infeasible validation draw, failed validation or held-out cell (Tasks 23 and 24);
- a dominated swap at artifact 5's reference point (Task 26);
- the post's final text, and publication (Tasks 27 and 28).
