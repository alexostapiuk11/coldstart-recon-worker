# Artifact 2 Statistical Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a defensible statistical layer between "the sweep ran" and "here is the headline number" — every published quantity carries an interval, the iso-cost budget is a pre-registered rule that actually binds, and H3's verdict is computed on the production path under both spike shapes.

**Architecture:** `run_sweep` stops collapsing each configuration's 30 repetitions to a mean and instead carries the per-repetition samples on `PolicyPoint`; point estimates become medians through one shared quantile implementation that matches artifact 1's linear-interpolation convention. The gap's interval comes from a bootstrap that resamples *repetition indices* and rebuilds the frontiers inside each draw, so uncertainty propagates through the frontier selection rather than around it. Figures gain interval bands; the convergence figure's "MEASURED" banner becomes conditional on the service curve's own `measured` flag, since the lag arms are measured but the p99 axis they are drawn on is not.

**Tech Stack:** Python 3.13, pytest, matplotlib, ruff. No new dependencies.

**Observable change requiring sign-off:** Task 4 changes every published point estimate from the **mean** of a policy's 30 repetitions to the **median**. Every number in the artifact moves. It is the right change — artifact 1's standing rule is that a mean is never published for right-skewed data, and per-run p99s under a heavy-tailed workload are right-skewed — but it is a change of estimator on a pre-registered experiment, so it is called out here, disclosed in `docs/experiment-a2.md` by Task 11, and must not be made silently. **Do not start Task 4 without confirming this.**

**Non-goals (stated so they are not silently absorbed):**
- Correcting the winner's curse (final-review finding #8). The bootstrap makes it *visible* in the interval; removing the bias needs a held-out selection split, which is a separate design question.
- Measuring the service curve. Everything here still runs against `SERVICE_CURVE_PLACEHOLDER` under `allow_unmeasured=True`; plan 2 is what replaces it.
- The harness extraction. See Task 2's note on why `autoscale/stats.py` is a deliberate second implementation rather than an import.

---

## File Structure

| File | Responsibility |
|---|---|
| `autoscale/stats.py` | **Create.** Quantiles, medians, percentile-method bootstrap intervals, sample floors. Artifact 2's own copy of artifact 1's conventions, pinned to them by a conformance test. |
| `tests/test_autoscale_stats.py` | **Create.** Unit tests plus the conformance test against `coldstart.analysis.stats`. |
| `autoscale/sim.py` | **Modify.** `SimResult.percentiles` routes through `autoscale.stats` and gains a sample floor. |
| `autoscale/frontier.py` | **Modify.** `PolicyPoint` carries per-repetition samples; add `iso_cost_budget` and `gap_interval`. |
| `autoscale/sweep.py` | **Modify.** `run_sweep` retains per-repetition samples instead of averaging them away. |
| `autoscale/figures.py` | **Modify.** Interval bands on both figures; conditional MEASURED banner. |
| `scripts/a2_render_figures.py` | **Modify.** Ramp sweeps, the four gaps, `h3_verdict` on the production path, budget rule from one place. |
| `docs/experiment-a2.md` | **Modify.** Dated amendment: aggregator, interval convention, iso-cost budget rule. |

---

### Task 1: Baseline the current numbers and figures

Nothing in this plan is verifiable without a record of what the sweep produces today. This task creates that record; Task 12 compares against it.

**Files:**
- Create: `build/a2-baseline/` (gitignored working directory)

- [ ] **Step 1: Capture the current sweep output**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py \
  --out build/a2-baseline --refresh 2>&1 | tee build/a2-baseline/render.log
```

Expected: a `WARNING: rendering against the PLACEHOLDER service curve` line, per-arm point counts and discard tallies, `frontiers.png` written, and the run then exiting non-zero on the convergence figure's guard (`SystemExit`). Record whichever of those happens — it is the baseline, not a target.

- [ ] **Step 2: Record the baseline numbers that must not change silently**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY' | tee build/a2-baseline/summary.txt
import json
raw = json.loads(open("build/a2-baseline/sweep-cache.json").read())
for label, rows in raw["sources"].items():
    by = {}
    for cost, p99, signal, up, down in rows:
        by.setdefault(signal, []).append((cost, p99))
    print(label, {s: (len(v), round(min(c for c, _ in v), 2), round(min(p for _, p in v), 4))
                  for s, v in sorted(by.items())})
print("swept", raw["swept"])
PY
```

- [ ] **Step 3: Record the baseline figures at both viewports**

```bash
cp build/a2-baseline/frontiers.png build/a2-baseline/frontiers-desktop-BEFORE.png
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
im = Image.open("build/a2-baseline/frontiers.png")
im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
    "build/a2-baseline/frontiers-phone-BEFORE.png")
PY
```

- [ ] **Step 4: Look at both baseline images**

Open `build/a2-baseline/frontiers-desktop-BEFORE.png` and `frontiers-phone-BEFORE.png` and note in the task report: are axis labels legible at 375 px, and how much whitespace is there around the frontier lines? Task 9 adds interval bands into that space, and Task 12 compares against these two images.

- [ ] **Step 5: Commit the baseline record**

```bash
git add docs/superpowers/plans/2026-09-17-artifact-2-statistical-layer.md
git commit -m "docs: plan for artifact 2's statistical layer"
```

(`build/` is gitignored; the images stay local as the comparison artifact.)

---

### Task 2: `autoscale/stats.py` — one quantile, one interval

**Why a second implementation rather than an import:** `tests/test_autoscale_boundary.py` enforces that exactly one file in `autoscale/` imports `coldstart`, and that file is the lag-ECDF adapter. Routing statistics through it would make an adapter named for one job do two. The alternative — moving `coldstart/analysis/stats.py` into a shared `harness/` package — is the pending harness extraction, which edits artifact 1's published code and is explicitly out of scope here. So this is a deliberate duplication, and Step 5's conformance test is what stops the two copies drifting: it asserts they agree on the same inputs, and fails if either changes alone. When the harness extraction lands, this file collapses into an import and the conformance test becomes redundant.

**Files:**
- Create: `autoscale/stats.py`
- Test: `tests/test_autoscale_stats.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Artifact 2's statistics, pinned to artifact 1's conventions.

The conformance test at the bottom is the point of this file: `autoscale`
cannot import `coldstart` (tests/test_autoscale_boundary.py), so these are a
second implementation of the same conventions, and a second implementation
that nothing compares is a second answer waiting to be published.
"""

import math

import pytest

from autoscale.stats import (
    MIN_SAMPLES,
    bootstrap_interval,
    median,
    percentiles,
    quantile,
)


def test_quantile_interpolates_between_order_statistics():
    # Not nearest-rank: q=0.5 on four points is the mean of the middle two.
    assert quantile(sorted([1.0, 2.0, 3.0, 4.0]), 0.5) == pytest.approx(2.5)


def test_quantile_at_the_endpoints_is_the_endpoint():
    xs = sorted([1.0, 5.0, 9.0])
    assert quantile(xs, 0.0) == 1.0
    assert quantile(xs, 1.0) == 9.0


def test_median_of_an_even_sample_is_the_mean_of_the_middle_two():
    assert median([4.0, 1.0, 3.0, 2.0]) == pytest.approx(2.5)


def test_an_empty_sample_is_refused():
    with pytest.raises(ValueError, match="must not be empty"):
        median([])


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_sample_value_is_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        median([1.0, bad, 3.0])


def test_percentiles_below_the_sample_floor_are_refused():
    """A percentile from too few samples is an observation, not a
    measurement. p99 needs 500; asking for it from 30 must raise rather than
    return a number that looks like the other four."""
    with pytest.raises(ValueError, match="p99"):
        percentiles([float(i) for i in range(30)], want=("p99",))


def test_percentiles_above_the_floor_are_reported():
    xs = [float(i) for i in range(600)]
    got = percentiles(xs, want=("p50", "p99"))
    assert got["p50"] == pytest.approx(299.5)
    assert got["p99"] == pytest.approx(593.01)


def test_bootstrap_interval_brackets_the_point_estimate():
    xs = [float(i) for i in range(40)]
    got = bootstrap_interval(xs, iterations=2000, seed=0)
    assert got["lo"] <= got["point"] <= got["hi"]
    assert got["point"] == pytest.approx(median(xs))


def test_bootstrap_interval_is_reproducible_from_its_seed():
    xs = [float(i) for i in range(40)]
    assert bootstrap_interval(xs, iterations=500, seed=7) == bootstrap_interval(
        xs, iterations=500, seed=7
    )


def test_bootstrap_interval_below_the_floor_is_refused():
    """The confidence-interval equivalent of reporting p99 from two points:
    without this, a single observation yields a confident-looking zero-width
    interval."""
    with pytest.raises(ValueError, match="at least"):
        bootstrap_interval([1.0], iterations=100, seed=0)


def test_too_few_iterations_for_the_alpha_is_refused():
    """The percentile-method endpoints invert rather than raise on their own,
    returning a backwards interval."""
    with pytest.raises(ValueError, match="too few"):
        bootstrap_interval([float(i) for i in range(30)], iterations=5, alpha=0.01, seed=0)


def test_a_zero_width_sample_gives_a_zero_width_interval():
    """Not a degenerate case to guard against -- it is the correct answer, and
    it is the one artifact 2 actually hits: under the placeholder service curve
    every repetition of a policy can deliver the identical p99."""
    got = bootstrap_interval([3.0] * 30, iterations=500, seed=0)
    assert got == {"point": 3.0, "lo": 3.0, "hi": 3.0}


def test_it_agrees_with_artifact_ones_implementation():
    """The anti-drift device. `autoscale` cannot import `coldstart`, so these
    conventions are implemented twice; this test is the only thing making the
    second copy a copy rather than a second answer. Tests may import artifact 1
    -- tests/test_autoscale_boundary.py scans `autoscale/`, not `tests/`."""
    from coldstart.analysis import stats as a1

    xs = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0, 5.0, 8.0,
          9.0, 7.0, 9.0, 3.0, 2.0, 3.0, 8.0, 4.0, 6.0, 2.0, 6.0, 4.0]

    assert median(xs) == a1.median(xs)
    assert MIN_SAMPLES == a1.MIN_SAMPLES
    for q in (0.0, 0.1, 0.25, 0.5, 0.9, 0.99, 1.0):
        assert quantile(sorted(xs), q) == a1._quantile(sorted(xs), q)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_autoscale_stats.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'autoscale.stats'`

- [ ] **Step 3: Write the implementation**

```python
"""Artifact 2's non-parametric statistics.

Same conventions as artifact 1, deliberately: linear-interpolation quantiles
(numpy's `method="linear"`), percentile-method bootstrap intervals, and sample
floors gating what may be reported. Two artifacts in one publication reporting
"the median" two different ways is the kind of discrepancy a reader finds and
an author cannot explain.

WHY THIS IS A SECOND IMPLEMENTATION rather than an import of
`coldstart.analysis.stats`: `tests/test_autoscale_boundary.py` enforces that
exactly one file in `autoscale/` imports artifact 1, and that file is the
lag-ECDF adapter -- artifact 2 depends on artifact 1 for measured DATA, not for
library code, which is what keeps the simulator runnable without artifact 1's
store on disk and keeps the pending harness extraction a one-file change. The
duplication is held honest by `test_it_agrees_with_artifact_ones_implementation`,
which fails if either copy changes alone. When `harness/` exists, this file
becomes an import and that test becomes redundant.

Percentile convention: linear interpolation between order statistics. Not
nearest-rank -- `sorted[int(q * n)]`, which artifact 2's own `SimResult` used
until this module existed, and which disagrees with artifact 1 by up to a whole
order statistic on the same data.

Confidence interval convention: percentile-method bootstrap -- the alpha/2 and
1-alpha/2 order statistics of the resampled distribution. First-order accurate
and known to be biased for skewed statistics (BCa corrects for that; this does
not). Defensible as long as it is stated, which this is.
"""

import math
import random

__all__ = [
    "MIN_BOOTSTRAP_SAMPLES",
    "MIN_SAMPLES",
    "bootstrap_interval",
    "median",
    "percentiles",
    "quantile",
]

# Copied from artifact 1 and pinned equal to it by the conformance test. A
# percentile needs enough samples to be a measurement rather than an
# observation.
MIN_SAMPLES = {"p50": 20, "p90": 50, "p95": 80, "p99": 500}

# Every bootstrap here resamples a median, so it inherits p50's floor.
MIN_BOOTSTRAP_SAMPLES = MIN_SAMPLES["p50"]


def _validate(values, name: str) -> list[float]:
    """Fail loudly on the inputs a quantile or bootstrap silently mishandles.

    NaN is the dangerous one and it is silent: it compares False against every
    ordering test, so `sorted()` leaves it wherever it happened to sit and the
    interpolation below reads two neighbours that are not the ones the quantile
    names. An infinity sorts legitimately and then poisons the arithmetic.
    """
    xs = list(values)
    if not xs:
        raise ValueError(f"{name} must not be empty; there is no quantile of nothing")
    for i, v in enumerate(xs):
        if v is None or not math.isfinite(v):
            raise ValueError(
                f"{name}[{i}] is {v!r}, which is not finite; a NaN compares "
                "False against every ordering test, so it would not sort to a "
                "predictable position and the interpolation would read the "
                "wrong pair of order statistics instead of raising here"
            )
    return xs


def quantile(sorted_xs: list[float], q: float) -> float:
    """Linear interpolation between order statistics.

    `sorted_xs` must already be sorted; this does not sort, because a bootstrap
    calls it once per resample and re-sorting here would double that cost.
    """
    n = len(sorted_xs)
    if n == 0:
        raise ValueError("cannot take a quantile of an empty sample")
    idx = q * (n - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_xs[lo]
    frac = idx - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def median(values) -> float:
    """The one median this package uses. Routes through `quantile` so a chart's
    median and a table's p50 are one computation, not two definitions that
    usually agree."""
    return quantile(sorted(_validate(values, "values")), 0.5)


def percentiles(values, want=("p50", "p90", "p95", "p99")) -> dict[str, float]:
    """The requested percentiles, refusing any whose sample floor is unmet.

    Refusing rather than returning-and-flagging: a number in a dict is a number
    a caller will publish, and "p99 from 30 samples" is indistinguishable in a
    figure from "p99 from 30,000".
    """
    xs = _validate(values, "values")
    ordered = sorted(xs)
    out: dict[str, float] = {}
    for name in want:
        floor = MIN_SAMPLES[name]
        if len(ordered) < floor:
            raise ValueError(
                f"{name} needs at least {floor} samples and got {len(ordered)}; "
                "a percentile from too few samples is an observation, not a "
                "measurement, and once it is in the returned dict nothing "
                "downstream can tell it apart from a well-supported one"
            )
        out[name] = quantile(ordered, float(name[1:]) / 100.0)
    return out


def _percentile_interval(draws: list[float], alpha: float) -> tuple[float, float]:
    """The alpha/2 and 1-alpha/2 order statistics of the resampled distribution.

    Also the one place the lo <= hi invariant is enforced: with too few draws
    for how extreme `alpha` is, the naive index arithmetic puts the lo index
    above the hi index and returns a BACKWARDS interval rather than raising.
    """
    xs = sorted(draws)
    n = len(xs)
    lo_idx = int((alpha / 2) * n)
    hi_idx = int((1 - alpha / 2) * n) - 1
    if lo_idx > hi_idx:
        raise ValueError(
            f"iterations={n} is too few for alpha={alpha}: the percentile-method "
            f"endpoints would invert (lo index {lo_idx}, hi index {hi_idx}) and "
            "return a backwards interval instead of raising; increase iterations"
        )
    return xs[lo_idx], xs[hi_idx]


def bootstrap_interval(values, iterations: int = 10000, seed: int = 0, alpha: float = 0.05) -> dict:
    """A percentile-method interval on the median of `values`.

    Returns `{"point", "lo", "hi"}`. `point` is the median of the observed
    sample, not the mean of the bootstrap draws: the draws estimate the
    sampling distribution's SPREAD, and reporting their centre instead would
    publish a subtly different estimator from the one named.
    """
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")
    xs = _validate(values, "values")
    if len(xs) < MIN_BOOTSTRAP_SAMPLES:
        raise ValueError(
            f"a bootstrap interval needs at least {MIN_BOOTSTRAP_SAMPLES} "
            f"samples and got {len(xs)}; below that the resampled distribution "
            "is a handful of repeated values and the interval comes out "
            "confident-looking and meaningless"
        )
    rng = random.Random(seed)
    point = quantile(sorted(xs), 0.5)
    n = len(xs)
    draws = [
        quantile(sorted(xs[rng.randrange(n)] for _ in range(n)), 0.5) for _ in range(iterations)
    ]
    lo, hi = _percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_autoscale_stats.py -x`
Expected: PASS, 12 tests.

- [ ] **Step 5: Verify the boundary is still intact and lint**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_autoscale_boundary.py && .venv/bin/ruff check .`
Expected: PASS, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add autoscale/stats.py tests/test_autoscale_stats.py
git commit -m "feat: artifact 2's statistics, pinned to artifact 1's conventions"
```

---

### Task 3: `SimResult.percentiles` uses the shared quantile and a sample floor

The current implementation is `ordered[min(len-1, int(p * n))]` — nearest-rank, and it disagrees with artifact 1 on the same data. It also reports p99 from any non-empty sample, so a run that completed 12 requests publishes a p99 that is its second-worst latency.

**Files:**
- Modify: `autoscale/sim.py:73-100`
- Test: `tests/test_sim.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sim.py`:

```python
def test_percentiles_use_the_same_convention_as_artifact_one():
    """Artifact 2 used nearest-rank (`ordered[int(p * n)]`) while artifact 1
    interpolates. Two artifacts in one publication reporting "p50" two ways is
    a discrepancy a reader finds and an author cannot explain."""
    from autoscale.stats import quantile

    result = _result_with_latencies([float(i) for i in range(1000)])
    got = result.percentiles()
    ordered = [float(i) for i in range(1000)]
    assert got["p50"] == pytest.approx(quantile(ordered, 0.50))
    assert got["p99"] == pytest.approx(quantile(ordered, 0.99))


def test_percentiles_refuse_a_p99_from_too_few_completions():
    """A run that completed 12 requests has no p99 -- it has a second-worst
    latency. Before the floor, that number was reported in the same dict field
    as a p99 backed by thousands of requests, and the sweep averaged the two
    together."""
    result = _result_with_latencies([float(i) for i in range(12)])
    with pytest.raises(ValueError, match="p99"):
        result.percentiles()
```

Add the helper near the top of the file if one does not already exist:

```python
def _result_with_latencies(latencies):
    """A SimResult carrying only what `percentiles()` reads, so these tests do
    not depend on the simulator's other bookkeeping."""
    return SimResult(
        latencies=list(latencies),
        replica_seconds=1.0,
        completed=len(latencies),
        unfinished=0,
        scale_up_events=0,
        scale_down_events=0,
        discard_reason=None,
    )
```

If `SimResult`'s field list differs, read it at `autoscale/sim.py` and construct accordingly — do not change the dataclass to suit the test.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_sim.py -k "convention or too_few" -x`
Expected: FAIL — the p50 assertion off by an order statistic, and no raise on 12 completions.

- [ ] **Step 3: Replace the quantile helper**

In `autoscale/sim.py`, add to the imports:

```python
from autoscale.stats import percentiles as _percentiles
```

and replace the body of `SimResult.percentiles` after the empty-latencies guard:

```python
    def percentiles(self) -> dict[str, float]:
        """p50/p90/p95/p99 of request latency, as the pre-registration names.

        p99 is supported here and was not in artifact 1: a spike generates
        thousands of requests, where artifact 1 had ~100 runs per arm and
        published no p99 for exactly that reason. "Thousands" is the
        justification, so `autoscale.stats.percentiles` enforces it -- a run
        that completed 12 requests has a second-worst latency, not a p99, and
        before the floor the sweep averaged that into the same estimate as a
        run that completed 4,000.

        Routed through `autoscale.stats` rather than computed here so artifact
        2's p50 and artifact 1's p50 are one convention. This used to be
        `ordered[min(len - 1, int(p * len))]` -- nearest-rank, which disagrees
        with artifact 1's linear interpolation by up to a whole order statistic
        on the same data.
        """
        if not self.latencies:
            raise ValueError(
                "no completed requests: percentiles over zero latencies "
                "would report a perfectly stalled run as p50=p99=0.0. Check "
                "`completed` before calling, and discard or widen the run "
                "rather than publishing zeros"
            )
        return _percentiles(self.latencies, want=("p50", "p90", "p95", "p99"))
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
Expected: the two new tests pass. **Other tests will fail** — any that assert a specific percentile value, and any sweep/end-to-end test whose runs complete fewer than 500 requests. Fix each by reading what it asserts:
- A test asserting a nearest-rank value: update the expected number and note in the commit that the convention changed.
- A test whose run is too short for p99: lengthen its window or give it enough arrivals. **Do not lower `MIN_SAMPLES`** — the floor is the point of the task.

- [ ] **Step 5: Re-run until green, then lint**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q && .venv/bin/ruff check .`
Expected: all pass, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add autoscale/sim.py tests/
git commit -m "fix: artifact 2 reported percentiles by a different convention from artifact 1"
```

---

### Task 4: `PolicyPoint` carries its repetitions

A 30-repetition estimate and a 1-repetition estimate are currently indistinguishable downstream. Carrying the samples is what makes every later task possible — the intervals, the gap bootstrap, and the `n` on the figures.

**Files:**
- Modify: `autoscale/frontier.py:225-260` (the `PolicyPoint` dataclass)
- Test: `tests/test_frontier.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_frontier.py`:

```python
def test_a_policy_point_carries_its_repetitions():
    p = PolicyPoint(
        cost_samples=(10.0, 12.0, 14.0),
        p99_samples=(1.0, 2.0, 3.0),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    assert p.n == 3
    assert p.cost == pytest.approx(12.0)  # median, not mean
    assert p.p99 == pytest.approx(2.0)


def test_the_point_estimate_is_a_median_not_a_mean():
    """Artifact 1's rule -- never a mean for right-skewed data -- applies to
    the per-run p99s too. One catastrophic repetition should not move a
    policy's published p99 by a third of the way to itself."""
    p = PolicyPoint(
        cost_samples=(10.0,) * 29 + (10.0,),
        p99_samples=(1.0,) * 29 + (100.0,),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    assert p.p99 == pytest.approx(1.0)


def test_a_policy_point_with_no_repetitions_is_refused():
    with pytest.raises(ValueError, match="no repetitions"):
        PolicyPoint(
            cost_samples=(),
            p99_samples=(),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_mismatched_sample_counts_are_refused():
    """cost and p99 come from the same runs, so unequal lengths mean the two
    axes of one point were computed over different repetition sets -- and the
    bootstrap in `gap_interval` resamples ONE index list for both."""
    with pytest.raises(ValueError, match="same runs"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0,),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_non_finite_sample_is_still_refused(bad):
    with pytest.raises(ValueError, match="not finite"):
        PolicyPoint(
            cost_samples=(1.0, bad),
            p99_samples=(1.0, 2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_a_negative_sample_is_still_refused():
    with pytest.raises(ValueError, match="negative"):
        PolicyPoint(
            cost_samples=(1.0, 2.0),
            p99_samples=(1.0, -2.0),
            signal="queue_depth",
            scale_up_at=2.0,
            scale_down_at=0.5,
        )


def test_a_policy_points_interval_brackets_its_point_estimate():
    p = PolicyPoint(
        cost_samples=tuple(float(i) for i in range(30)),
        p99_samples=tuple(float(i) for i in range(30)),
        signal="queue_depth",
        scale_up_at=2.0,
        scale_down_at=0.5,
    )
    lo, hi = p.p99_interval(iterations=500, seed=0)
    assert lo <= p.p99 <= hi
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -k "policy_point or point_estimate or mismatched" -x`
Expected: FAIL — `TypeError: PolicyPoint.__init__() got an unexpected keyword argument 'cost_samples'`

- [ ] **Step 3: Rewrite `PolicyPoint`**

Replace the dataclass in `autoscale/frontier.py`. Keep every existing guard — the NaN and negative checks below are the same ones, moved from the two scalars onto the samples they are now computed from.

```python
@dataclass(frozen=True)
class PolicyPoint:
    """One policy's outcome, carrying the repetitions it was estimated from.

    It used to carry two scalars -- the MEAN cost and MEAN p99 across
    repetitions -- and nothing else. A 30-repetition estimate and a
    1-repetition estimate were then indistinguishable to every consumer, so no
    figure could show an interval and the published H3 gap had no uncertainty
    attached to it at all. The samples are kept instead, and the scalars are
    derived: 55 policies x 30 repetitions x 2 floats is nothing to hold, and it
    is what lets `gap_interval` resample repetitions and rebuild the frontier
    inside each draw, propagating uncertainty THROUGH the frontier selection
    rather than around it.

    The point estimate is the MEDIAN, not the mean it used to be. Artifact 1's
    standing rule -- never a mean or a standard deviation for right-skewed data
    -- applies to per-run p99s as much as to raw latencies: a single
    catastrophic repetition moves a 30-run mean by a thirtieth of its own
    excess, and under a heavy-tailed workload that repetition is the normal
    case, not an outlier. The pre-registration fixes the repetition count but
    not the aggregator, so this is a documented change of estimator, disclosed
    in docs/experiment-a2.md rather than made silently.
    """

    cost_samples: tuple[float, ...]  # replica-seconds, one per kept repetition
    p99_samples: tuple[float, ...]  # seconds of request latency, same runs
    signal: str
    scale_up_at: float
    scale_down_at: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_samples", tuple(self.cost_samples))
        object.__setattr__(self, "p99_samples", tuple(self.p99_samples))

        if not self.cost_samples or not self.p99_samples:
            raise ValueError(
                "a policy point with no repetitions is a configuration that "
                "produced nothing, not a policy that scored zero; `run_sweep` "
                "skips those rather than emitting a point, so reaching here "
                "means a caller built one by hand"
            )
        if len(self.cost_samples) != len(self.p99_samples):
            raise ValueError(
                f"cost has {len(self.cost_samples)} samples and p99 has "
                f"{len(self.p99_samples)}; both axes of a point come from the "
                "SAME runs, and `gap_interval` resamples one index list for "
                "both -- unequal lengths mean the two axes were computed over "
                "different repetition sets and pairing them is meaningless"
            )

        # The same guards this class has always had, applied to the samples the
        # scalars are now computed from. A NaN is the dangerous case and it is
        # silent in both directions: a NaN p99 fails `point.p99 < best_p99`, so
        # the point is DROPPED from its own frontier -- an arm whose runs
        # produced garbage would publish a frontier that simply omits them,
        # looking sparser rather than broken. A NaN cost fails `p.cost <= cost`
        # in `_p99_at_cost`, so the point is invisible at every iso-cost slice.
        # An infinite cost passes every comparison as an ordinary extreme value
        # and sits on the frontier as affordable-at-infinity.
        for field_name, samples in (("cost", self.cost_samples), ("p99", self.p99_samples)):
            for i, value in enumerate(samples):
                if not math.isfinite(value):
                    raise ValueError(
                        f"{field_name}_samples[{i}] is {value!r}, which is not "
                        "finite; a NaN compares False against every ordering "
                        "test in pareto_frontier and _p99_at_cost, so the "
                        "point would be silently dropped from its own frontier "
                        "instead of raising here, and an infinity would sit on "
                        "the frontier as an ordinary extreme value"
                    )
                # Both axes are physical readings with a floor: replica-seconds
                # is an integral of a non-negative replica count, latency is a
                # duration. Lower is better on both, so a negative value does
                # not read as a small one but as a WINNING one.
                if value < 0:
                    raise ValueError(
                        f"{field_name}_samples[{i}] is {value!r}, which is "
                        "negative; lower is better on both frontier axes, so a "
                        "negative value does not read as a small one but as a "
                        "point that dominates every honest policy in the sweep"
                    )
        for field_name, value in (
            ("scale_up_at", self.scale_up_at),
            ("scale_down_at", self.scale_down_at),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{field_name} is {value!r}, which is not finite")

    @property
    def n(self) -> int:
        """Repetitions kept. Not the pre-registered 30 -- the exclusion rules
        discard runs, and a point built from 4 surviving repetitions must be
        distinguishable from one built from 30."""
        return len(self.p99_samples)

    @property
    def cost(self) -> float:
        return stats.median(self.cost_samples)

    @property
    def p99(self) -> float:
        return stats.median(self.p99_samples)

    def p99_interval(self, iterations: int = 10000, seed: int = 0) -> tuple[float, float]:
        """A 95% percentile-bootstrap interval on this policy's p99."""
        got = stats.bootstrap_interval(self.p99_samples, iterations=iterations, seed=seed)
        return got["lo"], got["hi"]

    def cost_interval(self, iterations: int = 10000, seed: int = 0) -> tuple[float, float]:
        got = stats.bootstrap_interval(self.cost_samples, iterations=iterations, seed=seed)
        return got["lo"], got["hi"]
```

Add to the imports at the top of `autoscale/frontier.py`:

```python
from autoscale import stats
```

- [ ] **Step 4: Run the full suite and fix every construction site**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`

Every `PolicyPoint(cost=..., p99=...)` in tests and scripts now fails. Fix each by passing single-element or repeated tuples — e.g. a test helper becomes:

```python
def _p(cost, p99, signal="queue_depth", up=2.0, down=0.5, n=30):
    """Repetition samples rather than scalars. `n` copies of one value keeps
    every existing frontier test asserting exactly what it asserted before --
    the median of n identical values is that value -- while satisfying the
    bootstrap floor where a test asks for an interval."""
    return PolicyPoint(
        cost_samples=(float(cost),) * n,
        p99_samples=(float(p99),) * n,
        signal=signal,
        scale_up_at=up,
        scale_down_at=down,
    )
```

- [ ] **Step 5: Re-run until green, then lint**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q && .venv/bin/ruff check .`
Expected: all pass, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add autoscale/frontier.py tests/
git commit -m "feat: policy points carry their repetitions, so an estimate has a sample size"
```

---

### Task 5: `run_sweep` stops averaging the repetitions away

**Files:**
- Modify: `autoscale/sweep.py:180-238`
- Test: `tests/test_frontier.py` (the sweep tests live there)

- [ ] **Step 1: Write the failing test**

```python
def test_the_sweep_carries_every_kept_repetition(monkeypatch):
    """The sweep used to emit `sum(costs) / len(costs)` and discard the rest,
    so nothing downstream could tell a 30-repetition estimate from a
    1-repetition one -- which is why no figure in this artifact could carry an
    interval."""
    monkeypatch.setattr("autoscale.sweep.REPETITIONS", 5)
    monkeypatch.setattr("autoscale.sweep.THRESHOLDS", {s: ((4.0,), (0.5,)) for s in SIGNALS})
    points, _ = run_sweep(
        SweepConfig(
            shape=SpikeShape(kind="step", baseline_rate=13.5, k=8.5, ramp=0.0, sustain=190.0),
            lags=LagDistribution(samples=[40.0]),
            curve=SERVICE_CURVE_PLACEHOLDER,
            arm="A",
            until=400.0,
        ),
        seed=11,
        allow_unmeasured=True,
    )
    assert points, "a sweep producing no points cannot demonstrate anything"
    for p in points:
        assert p.n <= 5
        assert len(p.cost_samples) == len(p.p99_samples) == p.n
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -k kept_repetition -x`
Expected: FAIL — `TypeError` from the `PolicyPoint(cost=..., p99=...)` call still inside `run_sweep`.

- [ ] **Step 3: Emit the samples**

In `autoscale/sweep.py`, replace the point construction at the end of the threshold loop:

```python
                if not costs:
                    continue
                points.append(
                    PolicyPoint(
                        cost_samples=tuple(costs),
                        p99_samples=tuple(p99s),
                        signal=signal,
                        scale_up_at=up,
                        scale_down_at=down,
                    )
                )
```

and replace the aggregator paragraph in `run_sweep`'s docstring:

```
    `cost` and `p99` are the MEDIAN across the repetitions each point carries,
    computed by `PolicyPoint` from the samples this returns rather than
    collapsed here. They were means, and they were collapsed here: the sweep
    emitted two scalars and discarded the 30 values behind them, which is why
    nothing downstream could attach an interval to anything.

    Median rather than mean for the reason artifact 1 gives for never
    publishing one: these are per-run p99s of a heavy-tailed workload, and a
    single catastrophic repetition moves a 30-run mean by a thirtieth of its
    own excess. The estimand is unchanged and is still per-run, not pooled:
    pooling latencies across runs estimates the tail of the mixture over runs,
    weighting each run by how many requests it happened to complete, whereas
    the design is 30 equally weighted repetitions whose estimand is the p99 a
    typical run of that policy delivers -- and "typical" is what a median
    reports. The pre-registration fixes the repetition count but not the
    aggregator; the change is disclosed in docs/experiment-a2.md.
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q && .venv/bin/ruff check .`
Expected: all pass. The cross-process reproducibility test still passes — the samples are deterministic, so their median is.

- [ ] **Step 5: Commit**

```bash
git add autoscale/sweep.py tests/test_frontier.py
git commit -m "feat: the sweep keeps its repetitions instead of averaging them away"
```

---

### Task 6: One pre-registered iso-cost budget rule

Today the budget is computed two incompatible ways — `min(cost) * 2` in `scripts/a2_render_figures.py` and `max(f[0].cost for f in frontiers.values())` in a test — and at the script's version every frontier is fully affordable, so the "iso-cost slice" is silently "each signal's unconstrained best". A slice that constrains nothing is not a slice.

**Files:**
- Modify: `autoscale/frontier.py`
- Test: `tests/test_frontier.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_budget_is_the_cheapest_at_which_every_signal_can_operate():
    """The rule: max over signals of that signal's cheapest frontier point.
    Any lower and some signal has nothing affordable, so the gap is undefined
    rather than smaller."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization"), _p(40, 7.0, "utilization")],
    }
    assert iso_cost_budget(frontiers) == pytest.approx(25.0)


def test_the_budget_binds_on_at_least_one_signal():
    """The defect this rule replaces: at `min(cost) * 2` every frontier was
    fully affordable, so the slice constrained nothing and the "iso-cost gap"
    was the spread between each signal's unconstrained best. At this rule the
    most expensive-floor signal has exactly one affordable policy, by
    construction."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "utilization": [_p(25, 9.0, "utilization"), _p(40, 7.0, "utilization")],
    }
    budget = iso_cost_budget(frontiers)
    affordable = {s: [p for p in f if p.cost <= budget] for s, f in frontiers.items()}
    assert min(len(v) for v in affordable.values()) == 1
    assert all(v for v in affordable.values())


def test_the_budget_of_an_empty_frontier_set_is_refused():
    with pytest.raises(ValueError, match="no frontiers"):
        iso_cost_budget({})


def test_the_budget_of_a_frontier_with_no_points_is_refused():
    with pytest.raises(ValueError, match="utilization"):
        iso_cost_budget({"queue_depth": [_p(10, 4.0)], "utilization": []})


def test_the_budget_is_always_sliceable_by_gap_at_iso_cost():
    """The two functions are a pair: a budget this returns must never make
    `gap_at_iso_cost` raise `no point costs X or less`."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization")],
    }
    gap = gap_at_iso_cost(frontiers, cost=iso_cost_budget(frontiers))
    assert gap == pytest.approx(5.5)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -k budget -x`
Expected: FAIL — `ImportError: cannot import name 'iso_cost_budget'`

- [ ] **Step 3: Implement it**

Add to `autoscale/frontier.py` and to `__all__`:

```python
def iso_cost_budget(frontiers: dict[str, list[PolicyPoint]]) -> float:
    """The pre-registered iso-cost budget: the cheapest spend at which EVERY
    compared signal has at least one policy.

    `max` over each signal's cheapest frontier point. Two properties make this
    the rule rather than a number someone picked:

    - It is derivable from the sweep, not chosen after seeing it. Nothing about
      where the gap lands can influence it.
    - It binds. At exactly this budget the most expensive-floor signal has
      precisely one affordable policy, so the slice is a real constraint on at
      least one signal. The rule it replaces -- `min(cost) * 2`, written in the
      render script and nowhere pre-registered -- left every frontier fully
      affordable against the placeholder curve, which quietly turned "the
      inter-signal gap at iso-cost" into "the spread between each signal's
      unconstrained best". That is a different quantity under the published
      name, and the more flattering one: it removes the cost axis from a
      comparison whose whole premise is a cost/latency tradeoff.

    Going any LOWER is not a stricter comparison, it is an undefined one:
    `gap_at_iso_cost` refuses a budget some signal cannot reach, because
    dropping that signal would report a spread between the survivors under the
    same name. This is therefore the lowest budget at which H3 has an answer at
    all.
    """
    if not frontiers:
        raise ValueError(
            "no frontiers, so there is no budget every signal can operate at; "
            "a gap needs at least two frontiers to be a spread between anything"
        )
    floors = {}
    for signal, frontier in frontiers.items():
        if not frontier:
            raise ValueError(
                f"the frontier for {signal!r} is empty, so it has no cheapest "
                "policy and there is no budget at which every signal can "
                "operate. An empty frontier is a finding about that signal, "
                "not a signal to compute the budget without"
            )
        floors[signal] = min(p.cost for p in frontier)
    return max(floors.values())
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -x && .venv/bin/ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autoscale/frontier.py tests/test_frontier.py
git commit -m "feat: one iso-cost budget rule, and one that actually binds"
```

---

### Task 7: An interval on the gap itself

The headline number. The bootstrap resamples *repetition indices* — one index list shared by every policy in the draw, which preserves the arrival-trace pairing the seed fix bought — recomputes each policy's median from the resampled repetitions, rebuilds the frontiers, re-derives the budget, and re-slices. Uncertainty then propagates *through* the frontier selection, which is where the winner's curse lives.

**Files:**
- Modify: `autoscale/frontier.py`
- Test: `tests/test_frontier.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_gap_interval_brackets_the_point_gap():
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
        "utilization": [_p(25, 9.0, "utilization")],
    }
    got = gap_interval(frontiers, iterations=400, seed=0)
    assert got["lo"] <= got["point"] <= got["hi"]
    assert got["point"] == pytest.approx(gap_at_iso_cost(frontiers, iso_cost_budget(frontiers)))


def test_identical_repetitions_give_a_zero_width_gap_interval():
    """Not a corner case -- it is what the placeholder service curve actually
    produces, and a reader must be able to tell "the gap is 0.1 s and certain"
    from "the gap is 0.1 s and we have no idea"."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth")],
        "in_flight_concurrency": [_p(10, 4.0, "in_flight_concurrency")],
        "utilization": [_p(10, 4.5, "utilization")],
    }
    got = gap_interval(frontiers, iterations=400, seed=0)
    assert got["lo"] == got["hi"] == pytest.approx(0.5)


def test_the_gap_interval_widens_with_noisier_repetitions():
    """The property that makes the interval worth publishing."""

    def noisy(spread, signal):
        return PolicyPoint(
            cost_samples=(10.0,) * 30,
            p99_samples=tuple(4.0 + spread * (i % 5) for i in range(30)),
            signal=signal,
            scale_up_at=2.0,
            scale_down_at=0.5,
        )

    def width(spread):
        f = {
            "queue_depth": [noisy(spread, "queue_depth")],
            "in_flight_concurrency": [noisy(spread * 2, "in_flight_concurrency")],
            "utilization": [noisy(spread * 3, "utilization")],
        }
        got = gap_interval(f, iterations=800, seed=3)
        return got["hi"] - got["lo"]

    assert width(1.0) > width(0.1)


def test_the_gap_interval_resamples_one_index_list_for_every_policy(monkeypatch):
    """The pairing the seed fix bought is destroyed by resampling each policy's
    repetitions independently: repetition r of queue_depth and repetition r of
    in_flight_concurrency are the SAME arrival trace, and a bootstrap that
    breaks that correspondence re-introduces exactly the traffic variance
    `_derive_seed` was changed to cancel."""
    seen = []

    def spy(samples, index):
        seen.append(tuple(index))
        return [samples[i] for i in index]

    monkeypatch.setattr("autoscale.frontier._take", spy)
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 3.0, "queue_depth")],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency")],
    }
    gap_interval(frontiers, iterations=3, seed=0, expected=("queue_depth", "in_flight_concurrency"))
    # Three policies x three draws, but only three DISTINCT index lists.
    assert len(seen) == 9
    assert len(set(seen)) <= 3


def test_the_gap_interval_refuses_an_incomplete_signal_set():
    """Same reason `gap_at_iso_cost` does, and it matters more here: an
    interval on a spread between the wrong set of signals reads as an interval
    on the headline."""
    with pytest.raises(ValueError, match="in_flight_concurrency"):
        gap_interval({"queue_depth": [_p(10, 4.0)]}, iterations=100, seed=0)


def test_the_gap_interval_requires_equal_repetition_counts():
    """Resampling one index list across policies requires the policies to have
    the same number of repetitions. Unequal counts mean the exclusion rules bit
    the signals differently -- publishable, and not something to paper over by
    truncating to the shortest."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth", n=30)],
        "in_flight_concurrency": [_p(14, 3.5, "in_flight_concurrency", n=12)],
        "utilization": [_p(25, 9.0, "utilization", n=30)],
    }
    with pytest.raises(ValueError, match="different numbers of repetitions"):
        gap_interval(frontiers, iterations=100, seed=0)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -k gap_interval -x`
Expected: FAIL — `ImportError: cannot import name 'gap_interval'`

- [ ] **Step 3: Implement it**

Add to `autoscale/frontier.py` and to `__all__`:

```python
def _take(samples: tuple[float, ...], index: tuple[int, ...]) -> list[float]:
    """Indexed separately so a test can prove one index list is shared across
    every policy in a draw -- see
    `test_the_gap_interval_resamples_one_index_list_for_every_policy`."""
    return [samples[i] for i in index]


def gap_interval(
    frontiers: dict[str, list[PolicyPoint]],
    iterations: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
    expected: Iterable[str] = COMPARED_SIGNALS,
) -> dict:
    """A percentile-bootstrap interval on the iso-cost gap.

    Resamples REPETITION INDICES, not policies and not latencies, and uses ONE
    index list per draw across every policy in every signal. That is not an
    implementation convenience -- repetition r of queue_depth and repetition r
    of in_flight_concurrency are replays of the same arrival trace (see
    `sweep._derive_seed`), and resampling each policy independently would break
    that correspondence and re-introduce precisely the traffic-to-traffic
    variance the shared seed was changed to cancel. The bootstrap would then
    report an interval wider than the design actually achieves, on a gap that
    is a paired difference.

    Each draw rebuilds the frontiers and re-derives the budget from the
    resampled repetitions rather than reusing the observed ones. That is the
    expensive choice and it is the honest one: WHICH policy sits on a frontier
    is itself estimated, and a bootstrap that holds the frontier fixed reports
    the uncertainty of a slice through a curve it pretends was known in
    advance. Doing it this way also lets the winner's curse show up in the
    interval -- each frontier is a minimum over 17 to 19 noisy estimates, so
    the point gap is biased, and the resampled draws inherit that bias rather
    than hiding it. NOTE: this makes the bias VISIBLE, not corrected; a
    correction needs a held-out selection split and is not attempted here.

    Returns `{"point", "lo", "hi", "budget"}`. `point` and `budget` are the
    observed values, not bootstrap centres: the draws estimate spread, and
    reporting their centre would publish a different estimator from the one
    named.
    """
    if iterations <= 0:
        raise ValueError(f"iterations must be positive, got {iterations}")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be strictly between 0 and 1, got {alpha}")

    wanted = set(expected)
    missing = sorted(wanted - set(frontiers))
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; an interval on a spread "
            f"across {sorted(wanted)} cannot be computed from the ones present "
            f"({sorted(frontiers)}), and an interval on the wrong signal set "
            "reads as an interval on the headline"
        )

    all_points = [p for f in frontiers.values() for p in f]
    if not all_points:
        raise ValueError("every frontier is empty; there is no gap to put an interval on")
    counts = {p.n for p in all_points}
    if len(counts) > 1:
        raise ValueError(
            f"policies have different numbers of repetitions ({sorted(counts)}); "
            "one shared index list per draw requires equal counts. Unequal "
            "counts mean the pre-registered exclusion rules bit the signals "
            "differently, which is a finding to publish about those signals, "
            "not something to paper over by truncating to the shortest"
        )
    n = counts.pop()

    observed_budget = iso_cost_budget(frontiers)
    point = gap_at_iso_cost(frontiers, cost=observed_budget, expected=wanted)

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(iterations):
        index = tuple(rng.randrange(n) for _ in range(n))
        resampled = {
            signal: pareto_frontier(
                [
                    PolicyPoint(
                        cost_samples=tuple(_take(p.cost_samples, index)),
                        p99_samples=tuple(_take(p.p99_samples, index)),
                        signal=p.signal,
                        scale_up_at=p.scale_up_at,
                        scale_down_at=p.scale_down_at,
                    )
                    for p in f
                ]
            )
            for signal, f in frontiers.items()
        }
        budget = iso_cost_budget(resampled)
        draws.append(gap_at_iso_cost(resampled, cost=budget, expected=wanted))

    lo, hi = stats._percentile_interval(draws, alpha)
    return {"point": point, "lo": lo, "hi": hi, "budget": observed_budget}
```

Add `import random` to `autoscale/frontier.py`'s imports.

- [ ] **Step 4: Run to verify the tests pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_frontier.py -x && .venv/bin/ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add autoscale/frontier.py tests/test_frontier.py
git commit -m "feat: an interval on H3's gap, bootstrapped through the frontier selection"
```

---

### Task 8: The ramp sweep, and H3's verdict on the production path

`h3_verdict` is called only from tests. No ramp sweep exists. The pre-registration requires the gap "computed separately for step and ramp, both reported", and H3 holds only if the halving occurs under both — so as things stand the headline hypothesis cannot be evaluated at all by running the artifact.

**Files:**
- Modify: `scripts/a2_render_figures.py`
- Test: `tests/test_a2_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_a2_end_to_end.py`:

```python
def test_the_render_script_evaluates_h3_under_both_shapes(tmp_path):
    """H3 is the headline and `h3_verdict` was reachable only from tests: no
    ramp sweep existed, and nothing on the production path called it. Running
    the artifact could not evaluate its own headline hypothesis."""
    import scripts.a2_render_figures as render

    assert hasattr(render, "RAMP_SECONDS")
    assert render.RAMP_SECONDS == 95.0  # docs/experiment-a2.md, "Traffic model"

    src = Path(render.__file__).read_text()
    assert "h3_verdict" in src, (
        "the render script never computes H3's verdict, so the artifact's "
        "headline hypothesis cannot be evaluated by running it"
    )
    assert 'kind="ramp"' in src, "no ramp sweep; H3 requires the gap under both shapes"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_end_to_end.py -k h3_under_both -x`
Expected: FAIL — `AttributeError: module has no attribute 'RAMP_SECONDS'`

- [ ] **Step 3: Add the ramp sweep and the verdict**

In `scripts/a2_render_figures.py`, add near the other constants:

```python
RAMP_SECONDS = 95.0  # docs/experiment-a2.md, "Traffic model": R = D / 2
```

Replace the imports line for `frontier` with:

```python
from autoscale.frontier import (
    PolicyPoint,
    gap_at_iso_cost,
    gap_interval,
    h3_verdict,
    iso_cost_budget,
    pareto_frontier,
)
```

In `_run_everything`, after the existing step sweeps, add the ramp sweeps and the four gaps:

```python
    # H3 is evaluated under BOTH shapes or not at all -- the pre-registration
    # fixes that, because H4 already predicts the ramp's margins shrink, so a
    # ramp-only halving is both the easier outcome and the less interesting
    # one. Until this existed the script swept only the step, so running the
    # artifact could not evaluate its own headline.
    ramp_shape = _preregistered_shape(
        SERVICE_CURVE_PLACEHOLDER, kind="ramp", ramp=RAMP_SECONDS
    )
    print(
        f"ramp spike: baseline={ramp_shape.baseline_rate:.1f} rps, "
        f"k={ramp_shape.k:.1f}, ramp={ramp_shape.ramp:g}s, sustain={ramp_shape.sustain:g}s"
    )
    for arm in ("A", "C"):
        sources[f"ramp arm {arm}"] = _sweep(
            f"ramp arm {arm}", ramp_shape, lags[arm], f"ramp-{arm}"
        )

    gaps: dict[str, dict] = {}
    for label in ("arm A", "arm C", "ramp arm A", "ramp arm C"):
        per_signal = {s: pareto_frontier(ps) for s, ps in _by_signal(sources[label]).items()}
        got = gap_interval(per_signal, iterations=GAP_BOOTSTRAP_ITERATIONS, seed=SEED)
        gaps[label] = got
        print(
            f"{label}: gap={got['point']:.4f}s "
            f"[{got['lo']:.4f}, {got['hi']:.4f}] at budget "
            f"{got['budget']:.1f} replica-seconds (n={ {s: f[0].n for s, f in per_signal.items()} })"
        )

    verdict = h3_verdict(
        step_gap_a=gaps["arm A"]["point"],
        step_gap_c=gaps["arm C"]["point"],
        ramp_gap_a=gaps["ramp arm A"]["point"],
        ramp_gap_c=gaps["ramp arm C"]["point"],
    )
    print(
        f"\nH3: holds={verdict.holds} partial={verdict.partial} "
        f"evaluable={verdict.evaluable}\n  {verdict.detail}"
    )
    # The verdict is computed from POINT gaps, and every one of them has an
    # interval printed above. A halving that is inside the noise is not a
    # halving; the intervals are what a reader checks that against, and they
    # are printed rather than folded into the boolean because a three-state
    # verdict with an interval quietly absorbed into it is a four-state
    # verdict nobody declared.
    if any(g["lo"] == g["hi"] == 0.0 for g in gaps.values()):
        print(
            "  NOTE: at least one gap is identically zero with a zero-width "
            "interval. Against the placeholder service curve every policy on a "
            "shared arrival trace delivers the same p99, so this is the "
            "expected reading and it says nothing about the real system."
        )
```

Add near the other constants:

```python
# 2000 draws is enough for 95% percentile endpoints (the 50th and 1950th order
# statistics) without the bootstrap dominating a sweep that is already minutes
# of CPU.
GAP_BOOTSTRAP_ITERATIONS = 2000
```

Change `_run_everything`'s return to `return sources, swept, gaps`, update its caller in `main`, and update `_dump`/`_load` to round-trip `gaps`:

```python
def _dump(path: Path, sources, swept, gaps) -> None:
    path.write_text(
        json.dumps(
            {
                "sources": {
                    label: [
                        [list(p.cost_samples), list(p.p99_samples), p.signal,
                         p.scale_up_at, p.scale_down_at]
                        for p in points
                    ]
                    for label, points in sources.items()
                },
                "swept": {str(k): v for k, v in swept.items()},
                "gaps": gaps,
            },
            indent=1,
        )
    )


def _load(path: Path):
    raw = json.loads(path.read_text())
    sources = {
        label: [
            PolicyPoint(cost_samples=tuple(c), p99_samples=tuple(p), signal=s,
                        scale_up_at=u, scale_down_at=d)
            for c, p, s, u, d in rows
        ]
        for label, rows in raw["sources"].items()
    }
    return sources, {float(k): v for k, v in raw["swept"].items()}, raw.get("gaps", {})
```

Replace the swept-lag budget line with the rule:

```python
        swept[lag] = gap_at_iso_cost(per_signal, cost=iso_cost_budget(per_signal))
```

**Note on the cache:** the schema changed, so any existing `sweep-cache.json` is unreadable. Run with `--refresh` the first time; if `_load` raises on an old cache, that is correct — do not add a compatibility shim for a gitignored draft cache.

- [ ] **Step 4: Run the test and the script**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_end_to_end.py -x
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py \
  --out build/a2-figures-draft --refresh 2>&1 | tee build/a2-render.log
```

Expected: the test passes; the script prints four gap lines with intervals and an H3 verdict. It takes roughly twice as long as before (two more sweeps). It may still exit non-zero on a figure guard — that is Task 10's subject, and the gap lines print before the figures are drawn.

- [ ] **Step 5: Record the numbers in the task report**

Paste the four gap lines and the H3 verdict into the task report. These are the numbers Task 11's amendment has to describe honestly.

- [ ] **Step 6: Commit**

```bash
git add scripts/a2_render_figures.py tests/test_a2_end_to_end.py
git commit -m "feat: sweep the ramp and evaluate H3 on the production path"
```

---

### Task 9: Interval bands on both figures

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. DOM-presence-style assertions (`path.exists()`, "the function returned") are **not** acceptable evidence here — every step below produces either a pixel assertion or a human-eyes checkpoint.

**Files:**
- Modify: `autoscale/figures.py:237-411`
- Test: `tests/test_a2_figures.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_frontier_figure_draws_an_interval_band_per_signal():
    """Spec 11 requires an interval on every published figure. Without one, a
    30-repetition frontier and a 1-repetition frontier are the same picture."""
    fig = frontiers(ALL_THREE, path=None, return_figure=True)
    axis = fig.axes[0]
    # `fill_between` produces a PolyCollection; one per signal.
    bands = [c for c in axis.collections if type(c).__name__ == "PolyCollection"]
    assert len(bands) == len(SIGNAL_ORDER), (
        f"expected one interval band per signal, found {len(bands)}"
    )
    plt.close(fig)


def test_the_convergence_figure_draws_an_interval_band_on_the_swept_curve():
    # No `curve_measured` yet -- Task 10 adds that parameter and updates this
    # call. Passing it here would make this test fail on a TypeError for a
    # reason that has nothing to do with interval bands.
    fig = convergence(
        ALL_THREE, ALL_THREE_C, swept=SWEPT_WITH_INTERVALS, path=None, return_figure=True
    )
    right = fig.axes[1]
    bands = [c for c in right.collections if type(c).__name__ == "PolyCollection"]
    assert bands, "the modeled panel's gap curve carries no interval"
    plt.close(fig)


def test_the_figure_states_the_repetition_count_behind_it():
    """`n=55 policy points` said how many policies were drawn, never how many
    runs each was estimated from -- so a 1-repetition sweep and a 30-repetition
    sweep carried identical annotations."""
    fig = frontiers(ALL_THREE, path=None, return_figure=True)
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "repetitions" in text, f"no repetition count anywhere on the figure: {text!r}"
    plt.close(fig)
```

Add the fixture `SWEPT_WITH_INTERVALS` near the other module-level fixtures:

```python
# `swept` maps lag -> gap. With intervals it maps lag -> {"point", "lo", "hi"}.
SWEPT_WITH_INTERVALS = {
    20.0: {"point": 0.8, "lo": 0.5, "hi": 1.1},
    40.0: {"point": 0.6, "lo": 0.4, "hi": 0.9},
    60.0: {"point": 0.5, "lo": 0.2, "hi": 0.9},
}
ALL_THREE_C = {s: _points(s, (i + 1) * 0.3) for i, s in enumerate(SIGNAL_ORDER)}
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -k "band or repetition" -x`
Expected: FAIL — zero `PolyCollection`s found.

- [ ] **Step 3: Draw the bands**

In `autoscale/figures.py`'s `frontiers`, after each signal's line is plotted, add its band:

```python
        # The interval, as a band rather than error bars: a frontier is a
        # curve, and per-point bars on three overlapping curves are unreadable
        # at 375 px. `alpha` low enough that three overlapping bands stay
        # distinguishable from one another and from the lines they belong to.
        lo = [p.p99_interval(iterations=BAND_ITERATIONS, seed=BAND_SEED)[0] for p in points]
        hi = [p.p99_interval(iterations=BAND_ITERATIONS, seed=BAND_SEED)[1] for p in points]
        axis.fill_between(
            [p.cost for p in points], lo, hi, color=color, alpha=0.18, linewidth=0
        )
```

In `convergence`, accept the richer `swept` mapping and band the modeled curve:

```python
    # `swept` values may be a bare float (the gap) or a mapping with an
    # interval. Both are accepted because the modeled panel is a sensitivity
    # sweep over invented lags, and a caller sweeping it cheaply without
    # bootstrapping each point is doing something reasonable -- but a value
    # WITH an interval must never be drawn without it.
    def _point(v):
        return v["point"] if isinstance(v, dict) else v

    axis_values = [_point(swept[k]) for k in lags]
    right.plot(lags, axis_values, "o-", markersize=5, linewidth=2, color=MODELED_BANNER)
    if all(isinstance(swept[k], dict) for k in lags):
        right.fill_between(
            lags,
            [swept[k]["lo"] for k in lags],
            [swept[k]["hi"] for k in lags],
            color=MODELED_BANNER,
            alpha=0.18,
            linewidth=0,
        )
```

Add near the other module constants:

```python
# Bands are drawn once per render and the sweep behind them is minutes of CPU,
# so 2000 draws costs nothing noticeable here and matches the iterations the
# published gap interval uses.
BAND_ITERATIONS = 2000
BAND_SEED = 0
```

Extend the `_note` text in both panels to carry the repetition count:

```python
    reps = sorted({p.n for data in (frontiers_a, frontiers_c) for v in data.values() for p in v})
    reps_text = f"{reps[0]} repetitions" if len(reps) == 1 else f"{reps[0]}-{reps[-1]} repetitions"
    _note(left, f"n={n_a + n_c} policy points ({n_a} A, {n_c} C), {reps_text}\n{_span(measured_p99)}")
```

and the same `reps_text` construction inside `frontiers`, appended to its own note.

- [ ] **Step 4: Run the tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -x`
Expected: PASS.

- [ ] **Step 5: Render and LOOK at both figures at desktop width**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-draft
```

Open `build/a2-figures-draft/frontiers.png`. Confirm by eye, and state each in the task report:
- Three bands are visible and distinguishable where they overlap.
- Bands do not swamp the lines (if a band is so wide the line is lost, that is a **finding about the data**, not a styling bug — report it, do not shrink the band to hide it).
- The repetition count appears in the note under the axes.

- [ ] **Step 6: Verify at 375 px and LOOK**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
for name in ("frontiers", "convergence"):
    try:
        im = Image.open(f"build/a2-figures-draft/{name}.png")
    except FileNotFoundError:
        print(f"{name}.png absent -- note it and continue")
        continue
    im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
        f"build/a2-figures-draft/{name}-phone.png")
    print(f"wrote {name}-phone.png")
PY
```

Open each `-phone.png`. Confirm the bands are still visible and the legend and axis labels are still legible. Attach both paths to the task report.

- [ ] **Step 7: Commit**

```bash
git add autoscale/figures.py tests/test_a2_figures.py
git commit -m "feat: intervals on both of artifact 2's figures"
```

---

### Task 10: The MEASURED banner must depend on the service curve

The left panel is stamped `MEASURED / artifact 1's two lag arms`. The lag arms *are* measured. The p99 axis they are plotted against is not — every y-value comes from the invented `SERVICE_CURVE_PLACEHOLDER` points. A banner that says MEASURED over an axis of invented numbers is the exact claim this figure's elaborate labelling exists to prevent, made by the labelling itself.

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`.

**Files:**
- Modify: `autoscale/figures.py:237-320`
- Test: `tests/test_a2_figures.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_measured_banner_requires_a_measured_service_curve():
    """The banner said MEASURED because the LAG arms are measured. The p99
    axis those arms are drawn against comes entirely from the placeholder
    service curve's invented points -- so the panel claimed measurement for
    numbers that were invented, using the very labelling built to stop that
    claim being made."""
    fig = convergence(
        ALL_THREE, ALL_THREE_C, swept=SWEPT_WITH_INTERVALS, path=None,
        curve_measured=False, return_figure=True,
    )
    text = " ".join(t.get_text() for t in fig.findobj(plt.Text))
    assert "MEASURED LAG, MODELED LATENCY" in text
    assert "placeholder service curve" in text
    plt.close(fig)


def test_the_measured_banner_is_restored_by_a_measured_curve():
    fig = convergence(
        ALL_THREE, ALL_THREE_C, swept=SWEPT_WITH_INTERVALS, path=None,
        curve_measured=True, return_figure=True,
    )
    words = [t.get_text() for t in fig.findobj(plt.Text)]
    assert "MEASURED" in words
    assert "MEASURED LAG, MODELED LATENCY" not in words
    plt.close(fig)


def test_curve_measured_must_be_stated():
    """No default. A default of True publishes an unmeasured curve as measured
    whenever a caller forgets; a default of False silently downgrades a real
    result. The caller knows which curve it passed to the sweep."""
    with pytest.raises(TypeError):
        convergence(ALL_THREE, ALL_THREE_C, swept=SWEPT_WITH_INTERVALS, path=None)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -k banner -x`
Expected: FAIL — `convergence() got an unexpected keyword argument 'curve_measured'`

- [ ] **Step 3: Make the banner conditional**

Change the signature — `curve_measured` is keyword-only and has **no default**:

```python
def convergence(frontiers_a, frontiers_c, swept, path, *, curve_measured, return_figure=False):
```

and replace the left panel's banner call:

```python
    # The lag arms are measured; the p99 axis they are drawn against is not,
    # unless the service curve behind the sweep was measured too. Stamping
    # MEASURED over a placeholder-derived axis is the precise claim the banner
    # system exists to prevent, made by the banner system. No default on
    # `curve_measured` for the same reason: a default of True publishes an
    # unmeasured curve as measured whenever a caller forgets to pass it, which
    # is the flattering direction, and a default of False silently downgrades a
    # real result. The caller knows which curve it swept.
    if curve_measured:
        _banner(left, "MEASURED", "artifact 1's two lag arms", MEASURED_BANNER)
    else:
        _banner(
            left,
            "MEASURED LAG, MODELED LATENCY",
            "artifact 1's lag arms; p99 from the placeholder service curve",
            MODELED_BANNER,
        )
```

- [ ] **Step 4: Update every existing caller**

`curve_measured` has no default, so **every** existing `convergence(...)` call now fails with a `TypeError` — including the interval-band test Task 9 added, which deliberately omitted the parameter because it did not yet exist. Find them all and pass the right value:

```bash
grep -rn "convergence(" tests/ scripts/ autoscale/
```

Each test that is not about the banner passes `curve_measured=True` (they assert about bands and guards, not provenance). In `scripts/a2_render_figures.py`:

```python
        print(
            convergence(
                arm_a, arm_c, swept, out / "convergence.png",
                curve_measured=SERVICE_CURVE_PLACEHOLDER.measured,
            )
        )
```

- [ ] **Step 5: Run the tests**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_a2_figures.py -x && .venv/bin/ruff check .`
Expected: PASS.

- [ ] **Step 6: Render and LOOK at the banner, at both viewports**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-draft
```

Open `build/a2-figures-draft/convergence.png` (if the figure's other guards let it render; if not, render it directly from a REPL with the fixtures). Confirm by eye and report:
- The left banner reads `MEASURED LAG, MODELED LATENCY` and is the **modeled** colour, not the measured green.
- The longer banner text has not overflowed the strip or collided with the panel title.
- Downscale to 375 px as in Task 9 Step 6 and confirm the banner text is still legible. **This is the step most likely to fail** — the new banner string is more than twice as long as `MEASURED`.

- [ ] **Step 7: Commit**

```bash
git add autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
git commit -m "fix: a MEASURED banner over a placeholder-derived axis"
```

---

### Task 11: Amend the pre-registration

Three changes here alter what the artifact publishes, and all three must be disclosed with their timing and reason. The pre-registration's credibility rests entirely on amendments being visible.

**Files:**
- Modify: `docs/experiment-a2.md`

- [ ] **Step 1: Append the amendment**

Add at the end of the "Analysis plan" section:

```markdown
### Amendment, 2026-09-17: the statistical layer

Three changes, all made before any sweep against a measured service curve had
been run — every sweep to this point used the explicitly-unmeasured placeholder
under `allow_unmeasured=True`, so there was no result to tune any of them
against.

**1. Aggregator: mean → median.** Each policy's published cost and p99 were the
arithmetic MEAN of its 30 per-run values. This document fixes the repetition
count but not the aggregator, so no pre-registered quantity changes — but the
estimator does, and artifact 1's standing rule is that a mean is never
published for right-skewed data. Per-run p99s under a heavy-tailed workload are
right-skewed, and a single catastrophic repetition moves a 30-run mean by a
thirtieth of its own excess. The estimand is unchanged and still per-run: the
p99 a typical run of that policy delivers.

**2. Intervals on every published quantity.** Percentile-method bootstrap, the
same convention as artifact 1 (and pinned equal to it by a conformance test,
since `autoscale` cannot import `coldstart`). The gap's interval resamples
repetition INDICES with one shared index list across all policies in a draw,
preserving the arrival-trace pairing, and rebuilds the frontiers inside each
draw so that uncertainty propagates through the frontier selection. This makes
the winner's-curse bias visible — each frontier is a minimum over 17 to 19
noisy estimates — but does not correct it; a correction needs a held-out
selection split and is not attempted.

Artifact 2's percentile convention was also nearest-rank while artifact 1's is
linear interpolation, and artifact 2 applied no sample floor. Both are now
artifact 1's, including `MIN_SAMPLES["p99"] = 500` — a run that completed a
dozen requests has a second-worst latency, not a p99.

**3. The iso-cost budget is now a rule.** It was not pre-registered at all, and
was implemented two incompatible ways: `min(cost) * 2` in the render script and
`max` of the per-signal cheapest points in a test. Against the placeholder
curve the script's version left every frontier fully affordable, so the
"inter-signal gap at iso-cost" was in fact the spread between each signal's
UNCONSTRAINED best — a different quantity under the published name, and the
more flattering one, since it removes the cost axis from a comparison whose
premise is a cost/latency tradeoff.

The budget is now **the cheapest spend at which every compared signal has at
least one policy**: the maximum over signals of that signal's cheapest frontier
point. It is derivable from the sweep rather than chosen after seeing it, and
it binds by construction — at exactly this budget the most expensive-floor
signal has precisely one affordable policy. Any lower budget is not a stricter
comparison but an undefined one, since some signal would have nothing
affordable and dropping it would report a spread between the survivors under
the same name.
```

- [ ] **Step 2: Record what the change did to the numbers**

Append, filling in from Task 8's recorded output and Task 1's baseline:

```markdown
**Effect on the draft numbers, against the placeholder curve.** Before/after
for the step-shape arm-A gap: <baseline> → <new> [<lo>, <hi>]. Reported here
so the amendment cannot be read as cosmetic. These are placeholder-curve
numbers and say nothing about the real system; plan 2's measured curve is what
makes them a result.
```

- [ ] **Step 3: Commit**

```bash
git add docs/experiment-a2.md
git commit -m "docs: disclose the statistical layer as a dated amendment"
```

---

### Task 12: Manual visual checkpoint and parity report

**UI task.** REQUIRED SUB-SKILL: `superpowers:verifying-visual-output`. This is the step that catches what the automated layers cannot.

**Files:** none modified — this task produces evidence.

- [ ] **Step 1: Confirm artifact 1 is untouched**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q tests/test_published_figures.py tests/test_autoscale_boundary.py
git diff --stat main -- coldstart/ scripts/analyse.py scripts/render_figures.py docs/post.md
```

Expected: tests pass; **the diff is empty**. Artifact 2's statistical layer must not have touched artifact 1. A non-empty diff here is a stop-and-report.

- [ ] **Step 2: Run the whole suite and lint**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q; echo "EXIT=$?"
.venv/bin/ruff check .
```

Expected: `EXIT=0`, `All checks passed!`

- [ ] **Step 3: Render the real figures end to end**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/a2_render_figures.py \
  --out build/a2-figures-final --refresh 2>&1 | tee build/a2-final.log
```

- [ ] **Step 4: Look at both figures at desktop width**

Open `build/a2-figures-final/frontiers.png` and `convergence.png`. Compare each against `build/a2-baseline/frontiers-desktop-BEFORE.png` from Task 1. Confirm and report:
- Interval bands present on every signal.
- Repetition count stated on the figure.
- The convergence banner reflects the placeholder curve.
- Nothing that was legible before is now obscured by a band.

- [ ] **Step 5: Look at both figures at 375 px**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
from PIL import Image
for name in ("frontiers", "convergence"):
    im = Image.open(f"build/a2-figures-final/{name}.png")
    im.resize((375, round(375 * im.height / im.width)), Image.LANCZOS).save(
        f"build/a2-figures-final/{name}-phone.png")
PY
```

Open both `-phone.png` files, compare against `build/a2-baseline/frontiers-phone-BEFORE.png`, and confirm legibility of bands, banner, legend, and axis labels. Attach all four paths to the task report.

- [ ] **Step 6: Write the parity and findings report**

In the task report, state:
- The four gaps with intervals, and H3's verdict.
- Whether any gap's interval contains zero — and if so, say plainly that the headline is not detectable at this sample size against the placeholder curve.
- Which of the final-review findings this plan closed (#2, #4, #5, #6, #7) and which remain open (#8 winner's curse, #9 stale rationale and the duplicated traffic derivation).

- [ ] **Step 7: Commit any stragglers**

```bash
git status --short
git add -A && git commit -m "chore: artifact 2 statistical layer, final verification"
```

---

## Coverage against the final-review findings

| Finding | Task | Status |
|---|---|---|
| #2 no dispersion or intervals carried | 4, 5, 7, 9 | closed |
| #4 iso-cost budget not pre-registered, two implementations, non-binding | 6, 8, 11 | closed |
| #5 no ramp sweep, `h3_verdict` unreachable from production | 8 | closed |
| #6 convergence stamps MEASURED over placeholder-derived axes | 10 | closed |
| #7 percentile convention differs from artifact 1, no sample floor | 2, 3 | closed |
| #8 winner's curse with unequal candidate counts (19/17/19) | 7 | **made visible, not corrected** — stated as a non-goal |
| #9 stale `blocked` rationale, `D`/`R` literals, third copy of the traffic derivation | — | **open** — not in scope; `RAMP_SECONDS` in Task 8 removes one of the three literal sites |
