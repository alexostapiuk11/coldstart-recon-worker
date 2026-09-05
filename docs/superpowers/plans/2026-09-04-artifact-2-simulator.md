# Artifact 2 — Simulator and Analysis Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and prove, with no GPU, the discrete-event simulator, the three-signal policy module, the threshold sweep, and the frontier analysis that artifact 2's headline rests on.

**Architecture:** A new `autoscale/` package, independent of `coldstart/` except for one adapter module that reads artifact 1's cold-start distribution out of `data/campaign.jsonl`. Every component is deterministic given a seed, so the whole path is testable against hand-computed scenarios; the service curve is a measured input the simulator interpolates, and until the real sweep runs (plan 2) it is fed a synthetic curve marked as such. Nothing here spends money.

**Tech Stack:** Python 3.13 (stdlib `heapq`, `random`, `bisect`, `statistics`), pytest, ruff, matplotlib. Reuses artifact 1's `harness`/`coldstart` statistics and figure conventions.

**Scope of this plan:** Plan 1 of 2, per spec §15. Tasks 1–13 below. Reconnaissance against the live platform (Q1/Q2/Q3), the real service-curve sweep, the validation gates, and publication are **plan 2** — none of them can be written honestly until reconnaissance answers what the platform supports.

**This plan adds only.** No existing module is replaced, slimmed, or deleted, so there is no capability inventory or parity gate to run. `coldstart/` is read from and never modified.

---

## The one coupling to artifact 1, and why it is one file

`autoscale/coldstart_ecdf.py` is the only module in this package that imports `coldstart`. Everything else takes plain numbers.

This matters twice. It keeps the simulator testable without artifact 1's data present, and it means the pending harness extraction
(`docs/superpowers/plans/2026-09-03-harness-extraction.md`) touches exactly one file in this tree instead of a dozen.

**Sampling pool decision, fixed here:** the ECDF resamples **repeat-host runs only** — 99 for arm A, 100 for arm C. Artifact 1's single first-touch run (arm A, 2266.6 s) is excluded, for the same mechanical reason artifact 1 excluded it from its own ECDF: it measures image distribution to a host that has never held the image, not a cold start. Host novelty is carried as a named risk in spec §14 and is recorded per replica during validation, not smuggled into the lag distribution where one observation in 100 would dominate every p99 in the sweep.

---

## File structure

```
autoscale/
  __init__.py           empty
  coldstart_ecdf.py     artifact 1's measured lag distributions — the only coldstart import
  events.py             event queue and simulation clock
  arrivals.py           Poisson arrivals with a time-varying rate; step and ramp shapes
  service.py            measured service curve -> service time and utilization
  replica.py            one replica's lifecycle: absent -> starting -> serving
  sim.py                the simulation loop; fixed capacity or policy-driven
  signals.py            the three scaling signals, computed from simulation state
  controller.py         threshold controller: signal crosses -> decision -> delay -> replica
  sweep.py              threshold sweep across signals, shapes, and distributions
  frontier.py           Pareto frontier, iso-cost slice, the H3 gap metric
  figures.py            the four body figures
scripts/
  a2_sweep.py           run the sweep, write results JSONL
  a2_render_figures.py  render the four figures
docs/
  experiment-a2.md      pre-registration
```

---

## Task 1: Pre-registration

**Files:**
- Create: `docs/experiment-a2.md`

Committed before any analysis code exists, so the git timestamp is evidence the hypotheses predate the results. Artifact 1 did this and it is the reason its headline-selection claim is checkable.

- [ ] **Step 1: Write the pre-registration**

Create `docs/experiment-a2.md`:

```markdown
# Artifact 2 — Pre-registration

Committed before the simulator, the sweep, or any result exists. The git
timestamp on this file is the evidence that what follows was fixed in advance.

## Question

For an LLM serving deployment whose scale-up lag is a measured cold-start
distribution, does reducing that lag change how much the choice of autoscaling
signal matters?

## Measured inputs, fixed

- Cold-start lag: artifact 1's empirical ECDF, resampled. Arm A (p50 81.1 s,
  n=99 repeat-host) and arm C (p50 39.4 s, n=100 repeat-host). The single
  first-touch run (arm A, 2266.6 s) is excluded: it measures image
  distribution, not a cold start.
- Lag includes `T_platform` (median 4.07-4.83 s). From the autoscaler's point
  of view the wait is the wait.
- Replicas are binary: absent or serving. Justified by artifact 1's
  measurement that `T_fast` is request 1 and per-arm steady-state medians
  differ by 0.6 ms.

## Traffic model, fixed

- `D` sustain = 2 x p95(arm A) = 192.7 s, rounded to **190 s**. Pinned to arm A
  and held constant across both distributions so the composition comparison
  varies exactly one thing.
- `R` ramp = `D`/2 = **95 s**.
- baseline = **40%** of measured saturation.
- `k` = magnitude requiring **3 additional replicas** at the measured service
  rate.

The two absolute rates are computed from the service curve and committed
**before any policy sweep runs**.

## Hypotheses

**H1.** In-flight concurrency dominates the other two on the cost/p99 frontier
for the step spike.

**H2.** GPU utilization is the worst of the three, and the mechanism is
censoring: its frontier degrades most in the high-load region where the signal
has saturated.

**H3 (headline).** The inter-signal frontier gap at iso-cost shrinks by at
least half between the arm-A distribution and the arm-C distribution.

Gap is the p99-damage spread between the best and worst signal at the iso-cost
slice, in seconds. Computed separately for step and ramp, both reported. H3
holds only if the halving occurs under **both** shapes. A halving under one
shape only is published as a partial result, not rounded up to confirmation.

**H4.** The ranking is stable across step and ramp, but margins shrink on the
ramp.

## Analysis plan

Frontiers are compared, not points. The headline sentence comes from the
iso-cost slice. Percentiles reported: p50, p90, p95, p99 of request latency
within a spike. p99 is supported here and was not in artifact 1: a spike
generates thousands of requests, where artifact 1 had ~100 runs per arm.

## Exclusion rules

A simulation run is discarded if the arrival trace is empty, if any replica
never reaches serving before the run ends, or if the policy produces no scaling
action across the entire spike -- each makes the run uninformative about the
signal rather than an observation about it. Discards are counted and reported
by signal, never silently dropped.

## Stopping rule

The sweep is exhaustive over the pre-declared threshold grid; there is no
sequential stopping decision to make. Repetitions per configuration are fixed
at 30 before any result is inspected.
```

- [ ] **Step 2: Commit**

```bash
git add docs/experiment-a2.md
git commit -m "docs: pre-register artifact 2's hypotheses and analysis plan"
```

---

## Task 2: The cold-start ECDF adapter

**Files:**
- Create: `autoscale/__init__.py`, `autoscale/coldstart_ecdf.py`
- Test: `tests/test_coldstart_ecdf.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_coldstart_ecdf.py`:

```python
import pytest

from autoscale.coldstart_ecdf import LagDistribution, load_measured_lags


def test_arm_pools_exclude_the_first_touch_run():
    """Artifact 1's single first-touch run (arm A, 2266.6 s) measures image
    distribution to a host that has never held the image, not a cold start.
    One such observation in 100 would dominate every p99 in the sweep."""
    lags = load_measured_lags("data/campaign.jsonl")

    assert len(lags["A"].samples) == 99
    assert len(lags["C"].samples) == 100
    assert max(lags["A"].samples) < 200.0


def test_measured_medians_match_artifact_ones_published_numbers():
    lags = load_measured_lags("data/campaign.jsonl")

    assert lags["A"].median() == pytest.approx(81.1, abs=0.5)
    assert lags["C"].median() == pytest.approx(39.4, abs=0.5)


def test_sampling_is_deterministic_given_a_seed():
    d = LagDistribution(samples=[10.0, 20.0, 30.0])

    first = [d.sample(seed_rng(1)) for _ in range(5)]
    second = [d.sample(seed_rng(1)) for _ in range(5)]

    assert first == second


def seed_rng(seed):
    import random

    return random.Random(seed)


def test_sampling_only_ever_returns_measured_values():
    """Resampling, not fitting. A value the campaign never observed must never
    come out -- that is the whole reason this is an ECDF and not a parametric
    fit (spec section 3)."""
    import random

    d = LagDistribution(samples=[10.0, 20.0, 30.0])
    rng = random.Random(7)

    drawn = {d.sample(rng) for _ in range(200)}

    assert drawn <= {10.0, 20.0, 30.0}


def test_an_empty_distribution_refuses_to_be_built():
    with pytest.raises(ValueError, match="at least one sample"):
        LagDistribution(samples=[])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_coldstart_ecdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale'`

- [ ] **Step 3: Write the implementation**

```bash
mkdir -p autoscale && touch autoscale/__init__.py
```

Create `autoscale/coldstart_ecdf.py`:

```python
"""Artifact 1's measured cold-start distributions, as a resampling source.

The ONLY module in this package that imports `coldstart`. Everything else takes
plain numbers, which keeps the simulator testable without artifact 1's data on
disk and confines the pending harness extraction to one file.

Resampling, not fitting. Artifact 1 measured p95/p50 of about 1.2 on both arms;
fitting a parametric tail to that would invent structure the data does not show,
and the tail is exactly where an autoscaling simulation is most sensitive.
"""

import random
from dataclasses import dataclass

from coldstart.analysis.metrics import derive
from coldstart.analysis.pipeline import (
    REQUIRED_FOR_T_TOTAL,
    annotate_first_touch,
    partition,
)
from coldstart.schema import RunRecord
from coldstart.store import JsonlStore

__all__ = ["LagDistribution", "load_measured_lags"]


@dataclass
class LagDistribution:
    """An empirical distribution of scale-up lag, in seconds.

    `samples` is the measured population itself, not summary statistics: a draw
    returns a value the campaign actually observed or it returns nothing.
    """

    samples: list[float]

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(
                "a lag distribution needs at least one sample; an empty one "
                "would make every scale-up instantaneous and silently turn the "
                "simulation into a no-cold-start baseline"
            )

    def sample(self, rng: random.Random) -> float:
        """One draw. `rng` is supplied by the caller so a whole simulation run
        is reproducible from a single seed."""
        return rng.choice(self.samples)

    def median(self) -> float:
        ordered = sorted(self.samples)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2


def load_measured_lags(store_path: str) -> dict[str, LagDistribution]:
    """Artifact 1's per-arm lag distributions, keyed by arm.

    Repeat-host runs only. Artifact 1's one first-touch run took 2266.6 s
    against a 39-96 s norm because the host had never pulled the image; it is
    a platform event, not a cold start, and artifact 1 excluded it from its own
    ECDF on a mechanical first-on-its-host rule applied to every run. The same
    rule applies here. Host novelty is carried as a named risk and recorded per
    replica during validation instead.
    """
    records = JsonlStore(store_path, RunRecord).read_all()
    rows = annotate_first_touch([derive(r) for r in records])
    publishable = partition(rows, required=REQUIRED_FOR_T_TOTAL).publishable

    by_arm: dict[str, list[float]] = {}
    for row in publishable:
        if row.get("first_touch") is not False:
            continue
        by_arm.setdefault(row["arm"], []).append(row["t_total"])
    return {arm: LagDistribution(samples=vals) for arm, vals in by_arm.items()}
```

Note: `JsonlStore(store_path, RunRecord)` assumes the harness extraction's Task 8 has run. If it has not, use `JsonlStore(store_path)` — the one-argument form — and fix it when the extraction lands. The extraction plan's grep for `JsonlStore(` will find this call site.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_coldstart_ecdf.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale tests/test_coldstart_ecdf.py
git commit -m "feat: artifact 1's measured lag distributions as a resampling source"
```

---

## Task 3: Event queue and clock

**Files:**
- Create: `autoscale/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_events.py`:

```python
import pytest

from autoscale.events import Event, EventQueue


def test_events_pop_in_time_order_not_insertion_order():
    q = EventQueue()
    q.push(Event(time=3.0, kind="c"))
    q.push(Event(time=1.0, kind="a"))
    q.push(Event(time=2.0, kind="b"))

    assert [q.pop().kind for _ in range(3)] == ["a", "b", "c"]


def test_ties_break_on_insertion_order_so_runs_are_reproducible():
    """Two events at the identical timestamp is not exotic -- an arrival and a
    replica becoming ready can land on the same float. Without a deterministic
    tiebreak the heap order depends on the payload's comparison, which for
    dataclasses is field order, which makes a run's outcome depend on an
    unrelated attribute."""
    q = EventQueue()
    q.push(Event(time=1.0, kind="first"))
    q.push(Event(time=1.0, kind="second"))

    assert [q.pop().kind for _ in range(2)] == ["first", "second"]


def test_clock_never_moves_backwards():
    q = EventQueue()
    q.push(Event(time=5.0, kind="a"))
    q.pop()

    with pytest.raises(ValueError, match="backwards"):
        q.push(Event(time=4.0, kind="b"))


def test_popping_an_empty_queue_returns_none():
    assert EventQueue().pop() is None


def test_now_tracks_the_last_popped_event():
    q = EventQueue()
    q.push(Event(time=2.5, kind="a"))
    assert q.now == 0.0
    q.pop()
    assert q.now == 2.5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.events'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/events.py`:

```python
"""The simulation's spine: a time-ordered event queue with a monotonic clock.

Discrete-event rather than time-stepped. A time-stepped loop has to pick a tick
size, and the answer depends on it: too coarse and a 0.3 s TTFT rounds away,
too fine and a 190 s spike costs millions of empty iterations. Events cost
nothing when nothing happens.
"""

import heapq
import itertools
from dataclasses import dataclass, field

__all__ = ["Event", "EventQueue"]


@dataclass(frozen=True)
class Event:
    time: float
    kind: str
    payload: dict = field(default_factory=dict)


class EventQueue:
    """Min-heap on time, with insertion order as the tiebreak.

    The tiebreak is load-bearing, not tidiness: simultaneous events are common
    (an arrival and a replica ready at the same float), and without an explicit
    counter the heap falls back to comparing payloads, so a run's outcome would
    depend on dataclass field order. Runs must be reproducible from a seed.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self.now = 0.0

    def push(self, event: Event) -> None:
        if event.time < self.now:
            raise ValueError(
                f"event at t={event.time} would move the clock backwards from "
                f"t={self.now}. Something computed a negative delay -- a lag "
                "sample, a service time, or a controller decision offset."
            )
        heapq.heappush(self._heap, (event.time, next(self._counter), event))

    def pop(self) -> Event | None:
        if not self._heap:
            return None
        _, _, event = heapq.heappop(self._heap)
        self.now = event.time
        return event

    def __len__(self) -> int:
        return len(self._heap)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_events.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/events.py tests/test_events.py
git commit -m "feat: time-ordered event queue with a deterministic tiebreak"
```

---

## Task 4: Arrival traces

**Files:**
- Create: `autoscale/arrivals.py`
- Test: `tests/test_arrivals.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_arrivals.py`:

```python
import random

import pytest

from autoscale.arrivals import SpikeShape, arrival_times, rate_at


def test_step_rate_jumps_at_spike_start_and_holds():
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)

    assert rate_at(shape, -1.0) == 2.0
    assert rate_at(shape, 0.0) == 8.0
    assert rate_at(shape, 189.0) == 8.0
    assert rate_at(shape, 191.0) == 2.0


def test_ramp_rises_linearly_then_holds():
    shape = SpikeShape(kind="ramp", baseline_rate=2.0, k=4.0, ramp=95.0, sustain=190.0)

    assert rate_at(shape, 0.0) == 2.0
    assert rate_at(shape, 47.5) == pytest.approx(5.0)
    assert rate_at(shape, 95.0) == pytest.approx(8.0)
    assert rate_at(shape, 200.0) == pytest.approx(8.0)
    assert rate_at(shape, 300.0) == 2.0


def test_arrivals_are_reproducible_from_a_seed():
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=10.0)

    a = arrival_times(shape, until=20.0, rng=random.Random(3))
    b = arrival_times(shape, until=20.0, rng=random.Random(3))

    assert a == b


def test_arrival_times_are_sorted_and_within_the_window():
    shape = SpikeShape(kind="step", baseline_rate=5.0, k=3.0, ramp=0.0, sustain=10.0)

    times = arrival_times(shape, until=30.0, rng=random.Random(11))

    assert times == sorted(times)
    assert all(0.0 <= t <= 30.0 for t in times)
    assert len(times) > 0


def test_the_spike_produces_more_arrivals_than_the_same_span_of_baseline():
    """The thinning must actually thin. A bug that ignored rate_at would still
    produce sorted times in range and pass every other test here."""
    shape = SpikeShape(kind="step", baseline_rate=1.0, k=10.0, ramp=0.0, sustain=100.0)
    times = arrival_times(shape, until=200.0, rng=random.Random(5))

    during = len([t for t in times if 0.0 <= t < 100.0])
    after = len([t for t in times if 100.0 <= t < 200.0])

    assert during > 3 * after


def test_a_ramp_shape_with_zero_ramp_is_rejected():
    """A ramp of zero is a step wearing a different label, and publishing it as
    a ramp would misreport which shape produced a result (H4)."""
    with pytest.raises(ValueError, match="ramp"):
        SpikeShape(kind="ramp", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_arrivals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.arrivals'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/arrivals.py`:

```python
"""Poisson arrivals with a time-varying rate, in the two shapes the spec fixes.

The spike starts at t=0. Time before 0 is baseline warm-up the simulation needs
so the queue is not empty when the spike lands -- an autoscaler evaluated from a
cold, idle system would see a step from nothing, which is not the incident
operators care about.
"""

import math
import random
from dataclasses import dataclass

__all__ = ["SpikeShape", "arrival_times", "rate_at"]


@dataclass(frozen=True)
class SpikeShape:
    kind: str  # "step" or "ramp"
    baseline_rate: float  # requests/second before and after the spike
    k: float  # peak is k x baseline
    ramp: float  # seconds to reach peak; 0 for a step
    sustain: float  # seconds at peak, measured from t=0

    def __post_init__(self) -> None:
        if self.kind not in ("step", "ramp"):
            raise ValueError(f"kind must be 'step' or 'ramp', got {self.kind!r}")
        if self.kind == "ramp" and self.ramp <= 0:
            raise ValueError(
                "a ramp shape needs ramp > 0; a zero ramp is a step wearing a "
                "different label, and H4 compares the two shapes by name"
            )
        if self.kind == "step" and self.ramp != 0:
            raise ValueError("a step shape must have ramp == 0")
        if self.baseline_rate <= 0 or self.k < 1 or self.sustain <= 0:
            raise ValueError(
                "baseline_rate and sustain must be positive and k at least 1"
            )


def rate_at(shape: SpikeShape, t: float) -> float:
    """Arrival rate in requests/second at time `t`. The spike occupies [0, sustain]."""
    peak = shape.baseline_rate * shape.k
    if t < 0.0 or t > shape.sustain:
        return shape.baseline_rate
    if shape.kind == "step":
        return peak
    if t >= shape.ramp:
        return peak
    fraction = t / shape.ramp
    return shape.baseline_rate + fraction * (peak - shape.baseline_rate)


def arrival_times(shape: SpikeShape, until: float, rng: random.Random) -> list[float]:
    """Arrival timestamps in [0, until], by thinning.

    Thinning rather than piecewise-exponential sampling: draw from a homogeneous
    Poisson process at the maximum rate and keep each point with probability
    rate_at(t)/max_rate. It is exact for any rate function, including the ramp,
    without special-casing the shape -- and the ramp is precisely where a
    hand-rolled piecewise sampler gets the boundary wrong.
    """
    max_rate = shape.baseline_rate * shape.k
    times: list[float] = []
    t = 0.0
    while True:
        t += -math.log(1.0 - rng.random()) / max_rate
        if t > until:
            return times
        if rng.random() <= rate_at(shape, t) / max_rate:
            times.append(t)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_arrivals.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/arrivals.py tests/test_arrivals.py
git commit -m "feat: Poisson arrivals by thinning, in step and ramp shapes"
```

---

## Task 5: The service curve

**Files:**
- Create: `autoscale/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_service.py`:

```python
import pytest

from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve


def test_latency_interpolates_between_measured_points():
    curve = ServiceCurve(
        points=[(1, 0.10, 100.0, 0.20), (10, 0.30, 400.0, 0.80)], measured=True
    )

    assert curve.latency_at(1) == pytest.approx(0.10)
    assert curve.latency_at(10) == pytest.approx(0.30)
    assert curve.latency_at(5) == pytest.approx(0.10 + (4 / 9) * 0.20, abs=1e-6)


def test_concurrency_below_the_first_measured_point_clamps():
    curve = ServiceCurve(points=[(2, 0.10, 100.0, 0.2), (10, 0.30, 400.0, 0.8)], measured=True)
    assert curve.latency_at(1) == pytest.approx(0.10)


def test_concurrency_above_the_last_measured_point_is_flagged_extrapolation():
    """The spec requires extrapolation beyond the validated range to be visible
    rather than silently plausible."""
    curve = ServiceCurve(points=[(1, 0.10, 100.0, 0.2), (10, 0.30, 400.0, 0.8)], measured=True)

    assert curve.is_extrapolating(11) is True
    assert curve.is_extrapolating(10) is False


def test_utilization_saturates_at_one():
    curve = ServiceCurve(points=[(1, 0.1, 100.0, 0.4), (10, 0.3, 400.0, 0.99)], measured=True)
    assert curve.utilization_at(10) == pytest.approx(0.99)
    assert curve.utilization_at(50) <= 1.0


def test_the_placeholder_curve_knows_it_is_not_measured():
    """Plan 2 replaces this with the real sweep. Until then nothing may publish
    a number derived from it without saying so."""
    assert SERVICE_CURVE_PLACEHOLDER.measured is False


def test_an_unsorted_or_empty_curve_is_rejected():
    with pytest.raises(ValueError, match="ascending"):
        ServiceCurve(points=[(10, 0.3, 400.0, 0.8), (1, 0.1, 100.0, 0.2)], measured=True)
    with pytest.raises(ValueError, match="at least two"):
        ServiceCurve(points=[(1, 0.1, 100.0, 0.2)], measured=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.service'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/service.py`:

```python
"""The measured service curve: what one replica does as concurrency rises.

Measured, not modeled. Continuous batching makes latency-versus-concurrency
strongly non-linear in a way no queueing formula reproduces, which is why the
spec buys this curve on hardware rather than deriving it. Linear interpolation
between measured points is deliberate: a spline would invent curvature between
samples, and the sweep is dense enough that straight segments are honest.
"""

import bisect
from dataclasses import dataclass

__all__ = ["ServiceCurve", "SERVICE_CURVE_PLACEHOLDER"]


@dataclass
class ServiceCurve:
    """`points` are (concurrency, latency_seconds, throughput_tps, gpu_utilization),
    ascending by concurrency.

    `measured` is False for the placeholder used until plan 2's sweep runs. Any
    figure or number derived from an unmeasured curve must say so -- the whole
    methodological claim is that every parameter is measured and only the
    control loop is modeled.
    """

    points: list[tuple[int, float, float, float]]
    measured: bool

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("a service curve needs at least two points to interpolate")
        concurrencies = [p[0] for p in self.points]
        if concurrencies != sorted(concurrencies):
            raise ValueError("service curve points must be in ascending concurrency order")

    @property
    def max_measured_concurrency(self) -> int:
        return self.points[-1][0]

    def is_extrapolating(self, concurrency: int) -> bool:
        return concurrency > self.max_measured_concurrency

    def _interpolate(self, concurrency: int, index: int) -> float:
        xs = [p[0] for p in self.points]
        if concurrency <= xs[0]:
            return self.points[0][index]
        if concurrency >= xs[-1]:
            return self.points[-1][index]
        i = bisect.bisect_left(xs, concurrency)
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = self.points[i - 1][index], self.points[i][index]
        return y0 + (concurrency - x0) / (x1 - x0) * (y1 - y0)

    def latency_at(self, concurrency: int) -> float:
        return self._interpolate(concurrency, 1)

    def throughput_at(self, concurrency: int) -> float:
        return self._interpolate(concurrency, 2)

    def utilization_at(self, concurrency: int) -> float:
        return min(1.0, self._interpolate(concurrency, 3))


# Shapes chosen to be qualitatively right for continuous batching -- latency
# flat then rising, throughput rising then flattening, utilization saturating
# well before the latency knee, which is the censoring H2 predicts. The NUMBERS
# ARE INVENTED and exist only so the simulator and sweep can be built and tested
# before hardware time is bought. Plan 2 replaces this wholesale.
SERVICE_CURVE_PLACEHOLDER = ServiceCurve(
    points=[
        (1, 0.30, 53.0, 0.18),
        (2, 0.31, 103.0, 0.34),
        (4, 0.33, 194.0, 0.61),
        (8, 0.38, 337.0, 0.85),
        (16, 0.52, 492.0, 0.96),
        (32, 0.95, 539.0, 0.99),
        (64, 2.10, 549.0, 1.00),
    ],
    measured=False,
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_service.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/service.py tests/test_service.py
git commit -m "feat: measured service curve with an explicitly unmeasured placeholder"
```

---

## Task 6: Replica lifecycle

**Files:**
- Create: `autoscale/replica.py`
- Test: `tests/test_replica.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_replica.py`:

```python
import pytest

from autoscale.replica import Replica, ReplicaState


def test_a_replica_starts_absent_and_becomes_serving_after_its_lag():
    r = Replica(replica_id=1, started_at=10.0, lag=39.4)

    assert r.state_at(10.0) is ReplicaState.STARTING
    assert r.state_at(49.3) is ReplicaState.STARTING
    assert r.state_at(49.4) is ReplicaState.SERVING


def test_a_replica_is_absent_before_it_was_ever_started():
    r = Replica(replica_id=1, started_at=10.0, lag=39.4)
    assert r.state_at(9.9) is ReplicaState.ABSENT


def test_ready_at_is_start_plus_lag():
    assert Replica(replica_id=1, started_at=10.0, lag=39.4).ready_at == pytest.approx(49.4)


def test_there_is_no_degraded_state():
    """Artifact 1 measured the degraded window at ~0.1 s: T_fast is request 1
    for all three arms and per-arm steady-state medians differ by 0.6 ms. The
    binary model is a measured finding, not a convenience -- see spec section 6.
    A future stack that reports ready before warmup completes needs this state
    back, and that is a spec change, not a quiet addition here."""
    assert [s.name for s in ReplicaState] == ["ABSENT", "STARTING", "SERVING"]


def test_a_negative_lag_is_refused():
    with pytest.raises(ValueError, match="negative"):
        Replica(replica_id=1, started_at=0.0, lag=-1.0)


def test_host_id_is_carried_for_validation_runs():
    """Spec section 10: a scale-up onto a host without the image costs ~2266 s,
    not 39-96 s. Without the host recorded, a platform event is
    indistinguishable from a simulator bug after the fact."""
    r = Replica(replica_id=1, started_at=0.0, lag=39.4, host_id="qerlaykt4q0ves")
    assert r.host_id == "qerlaykt4q0ves"
    assert Replica(replica_id=2, started_at=0.0, lag=39.4).host_id is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_replica.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.replica'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/replica.py`:

```python
"""One replica's lifecycle. Binary by measurement, not by convenience.

Artifact 1 found `T_fast` equals request 1 on all three arms, request 1 sits
7.6-7.7% above steady state, and per-arm steady-state medians differ by 0.6 ms.
So there is no serving-but-slow state to model here: vLLM answers /health only
after its warmup completes, putting the expensive work inside S4, ahead of
readiness.

That is a property of THIS serving stack. A stack that reports ready earlier
serves its degraded window to real users, and this model would understate every
policy's damage. Spec section 6 states the boundary; the post states it too.
"""

from dataclasses import dataclass
from enum import Enum

__all__ = ["Replica", "ReplicaState"]


class ReplicaState(Enum):
    ABSENT = "absent"
    STARTING = "starting"
    SERVING = "serving"


@dataclass(frozen=True)
class Replica:
    replica_id: int
    started_at: float
    lag: float
    # Recorded during validation runs only. Artifact 1 measured one first-touch
    # cold start at 2266.6 s against a 39-96 s norm; without the host, such an
    # event inside a validation run is indistinguishable from a model error.
    host_id: str | None = None

    def __post_init__(self) -> None:
        if self.lag < 0:
            raise ValueError(f"negative lag {self.lag}: a replica cannot be ready before it starts")

    @property
    def ready_at(self) -> float:
        return self.started_at + self.lag

    def state_at(self, t: float) -> ReplicaState:
        if t < self.started_at:
            return ReplicaState.ABSENT
        if t < self.ready_at:
            return ReplicaState.STARTING
        return ReplicaState.SERVING
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_replica.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/replica.py tests/test_replica.py
git commit -m "feat: binary replica lifecycle, justified by artifact 1's warmup measurement"
```

---

## Task 7: The simulation loop at fixed capacity

**Files:**
- Create: `autoscale/sim.py`
- Test: `tests/test_sim.py`

Fixed capacity first, no policy. This is exactly what the open-loop validation gate replays in plan 2, so it must be correct before any controller exists on top of it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sim.py`:

```python
import pytest

from autoscale.service import ServiceCurve
from autoscale.sim import SimResult, run_fixed_capacity

FLAT = ServiceCurve(
    points=[(1, 0.5, 2.0, 0.5), (100, 0.5, 200.0, 1.0)], measured=True
)


def test_one_arrival_on_an_idle_replica_waits_only_for_service():
    result = run_fixed_capacity(arrivals=[0.0], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5])


def test_requests_beyond_capacity_queue_rather_than_vanish():
    """Three simultaneous arrivals, one replica, 0.5 s service: they complete
    at 0.5, 1.0 and 1.5, so latencies are 0.5, 1.0, 1.5."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=FLAT, until=10.0)

    assert result.latencies == pytest.approx([0.5, 1.0, 1.5])
    assert len(result.latencies) == 3


def test_two_replicas_halve_the_queue():
    result = run_fixed_capacity(arrivals=[0.0, 0.0], replicas=2, curve=FLAT, until=10.0)
    assert result.latencies == pytest.approx([0.5, 0.5])


def test_requests_still_in_flight_when_the_window_ends_are_counted_not_dropped():
    """Dropping them would make every overloaded policy look better than it is,
    which is the exact direction of error that would flatter a lagging signal."""
    result = run_fixed_capacity(arrivals=[0.0, 0.0, 0.0], replicas=1, curve=FLAT, until=0.6)

    assert result.completed == 1
    assert result.unfinished == 2


def test_zero_replicas_is_refused():
    with pytest.raises(ValueError, match="at least one replica"):
        run_fixed_capacity(arrivals=[0.0], replicas=0, curve=FLAT, until=1.0)


def test_an_empty_arrival_trace_is_refused():
    """A discard reason in the pre-registration, surfaced as an error here so it
    cannot silently produce a run with no latencies and a perfect p99."""
    with pytest.raises(ValueError, match="empty"):
        run_fixed_capacity(arrivals=[], replicas=1, curve=FLAT, until=1.0)


def test_result_reports_the_percentiles_the_pre_registration_names():
    result = run_fixed_capacity(
        arrivals=[float(i) * 0.1 for i in range(200)], replicas=2, curve=FLAT, until=100.0
    )

    assert set(result.percentiles()) == {"p50", "p90", "p95", "p99"}
    assert result.percentiles()["p50"] <= result.percentiles()["p99"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sim.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.sim'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/sim.py`:

```python
"""The simulation loop. Fixed capacity here; the policy-driven loop is Task 10.

Concurrency is modeled PER REPLICA, because that is what the service curve
measures: one replica, concurrency swept. Fleet capacity is
`serving_replicas x curve.max_measured_concurrency`, and a request's service
time is read from the curve at the per-replica load under even balancing,
`ceil(in_flight / serving_replicas)`.

Getting this wrong is not subtle. An earlier version set capacity to the
replica COUNT -- one request per replica -- then read the per-replica curve at
FLEET concurrency. That caps a replica at a single concurrent request, which
contradicts continuous batching outright: artifact 1 measured KV capacity
supporting roughly 69-84 concurrent requests at this request shape. It would
make the autoscaler add replicas far more aggressively than reality requires,
and replica-seconds is the cost axis of every Pareto frontier, so H1, H2 and
the H3 headline would all inherit the distortion.

Two simplifications remain, both deliberate and both stated in the post:

- **Even balancing.** Requests are assumed spread evenly across serving
  replicas rather than assigned to specific ones. Real load balancers do
  round-robin or least-connections, which is close; modeling individual
  replica assignment would add a scheduler this experiment does not measure.
- **Service time is frozen at dispatch.** A request dispatched into a busy
  fleet stays slow after the fleet drains, and vice versa. The distortion is
  two-sided rather than systematically flattering, and the open-loop
  validation gate is exactly the measurement that says whether it matters.

What is NOT modeled is vLLM's scheduler itself, deliberately: the curve
already encodes what continuous batching does to latency, so re-deriving it
from a model would replace a measurement with an assumption.
"""

from dataclasses import dataclass, field

from autoscale.events import Event, EventQueue
from autoscale.service import ServiceCurve

__all__ = ["SimResult", "run_fixed_capacity"]


@dataclass
class SimResult:
    latencies: list[float] = field(default_factory=list)
    completed: int = 0
    unfinished: int = 0
    extrapolated_samples: int = 0

    def percentiles(self) -> dict[str, float]:
        """p50/p90/p95/p99 of request latency, as the pre-registration names.

        p99 is supported here and was not in artifact 1: a spike generates
        thousands of requests, where artifact 1 had ~100 runs per arm and
        published no p99 for exactly that reason.
        """
        if not self.latencies:
            return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0}
        ordered = sorted(self.latencies)

        def q(p: float) -> float:
            idx = min(len(ordered) - 1, int(p * len(ordered)))
            return ordered[idx]

        return {"p50": q(0.50), "p90": q(0.90), "p95": q(0.95), "p99": q(0.99)}


def run_fixed_capacity(
    arrivals: list[float], replicas: int, curve: ServiceCurve, until: float
) -> SimResult:
    """Replay `arrivals` against a constant `replicas` and return the outcome."""
    if replicas < 1:
        raise ValueError("at least one replica is required to serve anything")
    if not arrivals:
        raise ValueError(
            "empty arrival trace: the pre-registration discards such a run "
            "rather than reporting a perfect p99 over zero requests"
        )

    queue = EventQueue()
    for t in arrivals:
        queue.push(Event(time=t, kind="arrival"))

    result = SimResult()
    waiting: list[float] = []  # arrival times of queued requests
    in_flight: dict[int, float] = {}  # completion event id -> arrival time
    next_id = 0
    # Per replica, not per fleet: the curve measured ONE replica at a swept
    # concurrency, so `max_measured_concurrency` is how many requests a single
    # replica was actually observed serving.
    capacity = replicas * curve.max_measured_concurrency

    def start_service(now: float) -> None:
        nonlocal next_id
        while waiting and len(in_flight) < capacity:
            arrived = waiting.pop(0)
            concurrency = math.ceil((len(in_flight) + 1) / replicas)
            if curve.is_extrapolating(concurrency):
                result.extrapolated_samples += 1
            service = curve.latency_at(concurrency)
            next_id += 1
            in_flight[next_id] = arrived
            queue.push(Event(time=now + service, kind="done", payload={"id": next_id}))

    while (event := queue.pop()) is not None:
        if event.time > until:
            break
        if event.kind == "arrival":
            waiting.append(event.time)
            start_service(event.time)
        elif event.kind == "done":
            arrived = in_flight.pop(event.payload["id"])
            result.latencies.append(event.time - arrived)
            result.completed += 1
            start_service(event.time)

    result.unfinished = len(waiting) + len(in_flight)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sim.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/sim.py tests/test_sim.py
git commit -m "feat: fixed-capacity simulation loop, the open-loop gate's replay target"
```

---

## Task 8: The three signals

**Files:**
- Create: `autoscale/signals.py`
- Test: `tests/test_signals.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_signals.py`:

```python
import pytest

from autoscale.service import ServiceCurve
from autoscale.signals import FleetState, queue_depth, utilization, in_flight_concurrency

CURVE = ServiceCurve(
    points=[(1, 0.30, 53.0, 0.18), (8, 0.38, 337.0, 0.85), (32, 0.95, 539.0, 0.99)],
    measured=True,
)


def test_queue_depth_counts_waiting_requests_per_serving_replica():
    state = FleetState(waiting=12, in_flight=4, serving_replicas=2)
    assert queue_depth(state, CURVE) == pytest.approx(6.0)


def test_in_flight_concurrency_counts_active_requests_per_serving_replica():
    state = FleetState(waiting=12, in_flight=4, serving_replicas=2)
    assert in_flight_concurrency(state, CURVE) == pytest.approx(2.0)


def test_utilization_reads_the_measured_curve_and_saturates():
    """H2's mechanism: utilization is censored. Past the point where the curve
    reaches 1.0 the signal cannot distinguish busy from catastrophically
    overloaded, so a policy driven by it stops responding to worsening load."""
    mild = FleetState(waiting=0, in_flight=8, serving_replicas=1)
    severe = FleetState(waiting=500, in_flight=32, serving_replicas=1)
    catastrophic = FleetState(waiting=5000, in_flight=64, serving_replicas=1)

    assert utilization(mild, CURVE) == pytest.approx(0.85)
    assert utilization(severe, CURVE) == pytest.approx(0.99)
    assert utilization(catastrophic, CURVE) == utilization(severe, CURVE)


def test_the_other_two_signals_keep_discriminating_where_utilization_cannot():
    """The same two states utilization cannot separate."""
    severe = FleetState(waiting=500, in_flight=32, serving_replicas=1)
    catastrophic = FleetState(waiting=5000, in_flight=64, serving_replicas=1)

    assert queue_depth(catastrophic, CURVE) > queue_depth(severe, CURVE)
    assert in_flight_concurrency(catastrophic, CURVE) > in_flight_concurrency(severe, CURVE)


def test_signals_with_no_serving_replicas_report_maximum_pressure():
    """Zero serving replicas is the state right after a scale-from-zero, and it
    is the moment a policy most needs a defined signal. Dividing by zero
    replicas must not crash or silently read as 'no pressure'."""
    state = FleetState(waiting=50, in_flight=0, serving_replicas=0)

    assert queue_depth(state, CURVE) == float("inf")
    assert in_flight_concurrency(state, CURVE) == float("inf")
    assert utilization(state, CURVE) == 1.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_signals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.signals'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/signals.py`:

```python
"""The three scaling signals, each a pure function of fleet state.

Pure functions of one state object rather than methods on the simulator, so the
same code computes the signal in simulation and against a real deployment in
plan 2's closed-loop gate. The spec's confirmatory gate requires "same policy
code, real API"; that is only true if the signal is not entangled with the
simulator.
"""

from dataclasses import dataclass

from autoscale.service import ServiceCurve

__all__ = ["FleetState", "queue_depth", "in_flight_concurrency", "utilization", "SIGNALS"]


@dataclass(frozen=True)
class FleetState:
    waiting: int
    in_flight: int
    serving_replicas: int


def queue_depth(state: FleetState, curve: ServiceCurve) -> float:
    """Requests waiting per serving replica. `curve` is unused; the uniform
    signature is what lets the controller treat all three interchangeably."""
    if state.serving_replicas == 0:
        return float("inf")
    return state.waiting / state.serving_replicas


def in_flight_concurrency(state: FleetState, curve: ServiceCurve) -> float:
    """Active requests per serving replica."""
    if state.serving_replicas == 0:
        return float("inf")
    return state.in_flight / state.serving_replicas


def utilization(state: FleetState, curve: ServiceCurve) -> float:
    """GPU utilization, read off the measured curve at current per-replica load.

    This is the signal H2 predicts is worst, and the mechanism is visible right
    here: the curve saturates at 1.0, so beyond that point the signal returns
    the same value for a busy fleet and a collapsing one. A policy driven by it
    stops receiving information exactly when it most needs it. Queue depth and
    concurrency have no ceiling and keep discriminating.
    """
    if state.serving_replicas == 0:
        return 1.0
    per_replica = state.in_flight / state.serving_replicas
    return curve.utilization_at(int(per_replica))


SIGNALS = {
    "queue_depth": queue_depth,
    "in_flight_concurrency": in_flight_concurrency,
    "utilization": utilization,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_signals.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/signals.py tests/test_signals.py
git commit -m "feat: the three scaling signals, with utilization's censoring made visible"
```

---

## Task 9: The threshold controller

**Files:**
- Create: `autoscale/controller.py`
- Test: `tests/test_controller.py`

Spec §10: controller arithmetic is unit-tested with hand-computed scenarios, never GPU-validated. This task is that unit test.

- [ ] **Step 1: Write the failing test**

Create `tests/test_controller.py`:

```python
import pytest

from autoscale.controller import Controller, Decision


def test_no_action_below_the_scale_up_threshold():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=4.9, replicas=2, now=0.0) is Decision.HOLD


def test_scale_up_when_the_signal_crosses():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=5.0, replicas=2, now=0.0) is Decision.UP


def test_cooldown_suppresses_a_second_action():
    """Without a cooldown a policy fires on every evaluation while the signal
    stays high, launching a replica per tick and making every signal look
    identically aggressive. Real autoscalers have one; modeling them without it
    would idealize away the constraint the comparison is about."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)

    assert c.decide(signal_value=9.0, replicas=2, now=0.0) is Decision.UP
    assert c.decide(signal_value=9.0, replicas=3, now=29.9) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=3, now=30.0) is Decision.UP


def test_scale_down_below_the_low_threshold():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=0.5, replicas=3, now=0.0) is Decision.DOWN


def test_never_scales_below_one_replica():
    """Scale-to-zero would make the next request pay a full cold start and turn
    the comparison into a measurement of the idle timeout instead of the signal."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=0.0, replicas=1, now=0.0) is Decision.HOLD


def test_never_scales_above_the_cap():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=4)
    assert c.decide(signal_value=100.0, replicas=4, now=0.0) is Decision.HOLD


def test_an_infinite_signal_scales_up():
    """Zero serving replicas reports infinite pressure (Task 8). The controller
    must act on it rather than propagating a NaN through the comparison."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=float("inf"), replicas=1, now=0.0) is Decision.UP


def test_inverted_thresholds_are_refused():
    with pytest.raises(ValueError, match="scale_down_at"):
        Controller(scale_up_at=1.0, scale_down_at=5.0, cooldown=30.0, max_replicas=10)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_controller.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.controller'`

- [ ] **Step 3: Write the implementation**

Create `autoscale/controller.py`:

```python
"""One controller, three signals. The thresholds are what the sweep varies.

Deliberately one controller rather than three tuned ones. The August design
frames the question as achievable frontiers precisely because "which signal is
best" is ill-posed -- whichever threshold set you publish decides the winner.
Sweeping one controller's thresholds across every signal is what makes the
comparison fair and robust to the objection that the loser was mistuned.
"""

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["Controller", "Decision"]


class Decision(Enum):
    UP = "up"
    DOWN = "down"
    HOLD = "hold"


@dataclass
class Controller:
    scale_up_at: float
    scale_down_at: float
    cooldown: float
    max_replicas: int
    min_replicas: int = 1
    _last_action_at: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.scale_down_at >= self.scale_up_at:
            raise ValueError(
                f"scale_down_at ({self.scale_down_at}) must be below scale_up_at "
                f"({self.scale_up_at}); overlapping thresholds oscillate"
            )

    def decide(self, signal_value: float, replicas: int, now: float) -> Decision:
        if self._last_action_at is not None and now - self._last_action_at < self.cooldown:
            return Decision.HOLD
        if signal_value >= self.scale_up_at and replicas < self.max_replicas:
            self._last_action_at = now
            return Decision.UP
        if signal_value <= self.scale_down_at and replicas > self.min_replicas:
            self._last_action_at = now
            return Decision.DOWN
        return Decision.HOLD
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_controller.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/controller.py tests/test_controller.py
git commit -m "feat: one threshold controller, swept rather than tuned per signal"
```

---

## Task 10: The policy-driven simulation

**Files:**
- Modify: `autoscale/sim.py`
- Test: `tests/test_sim_policy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_sim_policy.py`:

```python
import random

import pytest

from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.service import ServiceCurve
from autoscale.sim import run_with_policy

SLOW = ServiceCurve(points=[(1, 1.0, 1.0, 0.5), (100, 1.0, 100.0, 1.0)], measured=True)
INSTANT_LAG = LagDistribution(samples=[0.0])
SLOW_LAG = LagDistribution(samples=[60.0])


def _controller():
    return Controller(scale_up_at=2.0, scale_down_at=0.5, cooldown=10.0, max_replicas=6)


def test_a_sustained_overload_adds_replicas():
    arrivals = [float(i) * 0.2 for i in range(200)]
    result = run_with_policy(
        arrivals=arrivals,
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.peak_replicas > 1
    assert result.scale_up_events > 0


def test_replicas_do_not_serve_before_their_lag_elapses():
    """The property the whole artifact is about. With a 60 s lag inside a 30 s
    window, a scale-up decision buys nothing and latency must reflect that."""
    arrivals = [float(i) * 0.2 for i in range(150)]
    result = run_with_policy(
        arrivals=arrivals,
        signal="queue_depth",
        controller=_controller(),
        lags=SLOW_LAG,
        curve=SLOW,
        until=30.0,
        evaluate_every=1.0,
        rng=random.Random(1),
    )

    assert result.peak_serving_replicas == 1
    assert result.scale_up_events > 0


def test_shorter_lag_produces_lower_p99_all_else_equal():
    """The composition claim in miniature: the only difference between these two
    runs is the lag distribution."""
    arrivals = [float(i) * 0.2 for i in range(400)]
    kwargs = dict(
        arrivals=arrivals,
        signal="queue_depth",
        curve=SLOW,
        until=120.0,
        evaluate_every=1.0,
    )
    slow = run_with_policy(
        controller=_controller(), lags=SLOW_LAG, rng=random.Random(2), **kwargs
    )
    fast = run_with_policy(
        controller=_controller(), lags=INSTANT_LAG, rng=random.Random(2), **kwargs
    )

    assert fast.percentiles()["p99"] < slow.percentiles()["p99"]


def test_the_same_seed_reproduces_the_run_exactly():
    arrivals = [float(i) * 0.2 for i in range(100)]
    kwargs = dict(
        arrivals=arrivals,
        signal="utilization",
        lags=LagDistribution(samples=[10.0, 20.0, 30.0]),
        curve=SLOW,
        until=60.0,
        evaluate_every=1.0,
    )
    a = run_with_policy(controller=_controller(), rng=random.Random(9), **kwargs)
    b = run_with_policy(controller=_controller(), rng=random.Random(9), **kwargs)

    assert a.latencies == pytest.approx(b.latencies)
    assert a.scale_up_events == b.scale_up_events


def test_a_run_with_no_scaling_action_is_flagged_for_discard():
    """A pre-registered discard reason: a run where the policy never acted says
    nothing about the signal."""
    quiet = [0.0, 50.0]
    result = run_with_policy(
        arrivals=quiet,
        signal="queue_depth",
        controller=_controller(),
        lags=INSTANT_LAG,
        curve=SLOW,
        until=100.0,
        evaluate_every=1.0,
        rng=random.Random(4),
    )

    assert result.scale_up_events == 0
    assert result.discard_reason == "no_scaling_action"


def test_an_unknown_signal_name_is_refused():
    with pytest.raises(KeyError, match="not_a_signal"):
        run_with_policy(
            arrivals=[0.0],
            signal="not_a_signal",
            controller=_controller(),
            lags=INSTANT_LAG,
            curve=SLOW,
            until=1.0,
            evaluate_every=1.0,
            rng=random.Random(1),
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_sim_policy.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_with_policy'`

- [ ] **Step 3: Write the implementation**

Append to `autoscale/sim.py`, and extend its imports:

```python
import math
import random

from autoscale.controller import Controller, Decision
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.replica import Replica, ReplicaState
from autoscale.signals import SIGNALS, FleetState
```

Add to `SimResult`:

```python
    peak_replicas: int = 1
    peak_serving_replicas: int = 1
    scale_up_events: int = 0
    scale_down_events: int = 0
    replica_seconds: float = 0.0
    discard_reason: str | None = None
```

Then append the function:

```python
def run_with_policy(
    arrivals: list[float],
    signal: str,
    controller: Controller,
    lags: LagDistribution,
    curve: ServiceCurve,
    until: float,
    evaluate_every: float,
    rng: random.Random,
) -> SimResult:
    """Closed loop: the controller observes the fleet and changes replica count.

    A replica launched at time t begins serving at t + lag, where lag is one
    draw from the measured distribution. `replica_seconds` accumulates billable
    time from launch, not from ready -- you pay for a starting replica, which is
    precisely why a slow cold start costs money as well as latency.
    """
    if signal not in SIGNALS:
        raise KeyError(f"{signal!r} is not a signal; expected one of {sorted(SIGNALS)}")
    if not arrivals:
        raise ValueError("empty arrival trace")

    signal_fn = SIGNALS[signal]
    queue = EventQueue()
    for t in arrivals:
        queue.push(Event(time=t, kind="arrival"))
    tick = 0.0
    while tick <= until:
        queue.push(Event(time=tick, kind="evaluate"))
        tick += evaluate_every

    result = SimResult()
    replicas = [Replica(replica_id=0, started_at=0.0, lag=0.0)]
    waiting: list[float] = []
    in_flight: dict[int, float] = {}
    next_request_id = 0
    next_replica_id = 1
    last_time = 0.0

    def serving_count(now: float) -> int:
        return sum(1 for r in replicas if r.state_at(now) is ReplicaState.SERVING)

    def start_service(now: float) -> None:
        nonlocal next_request_id
        serving = serving_count(now)
        if serving == 0:
            return  # nothing ready; requests stay queued and their wait accrues
        capacity = serving * curve.max_measured_concurrency
        while waiting and len(in_flight) < capacity:
            arrived = waiting.pop(0)
            concurrency = math.ceil((len(in_flight) + 1) / serving)
            if curve.is_extrapolating(concurrency):
                result.extrapolated_samples += 1
            next_request_id += 1
            in_flight[next_request_id] = arrived
            queue.push(
                Event(
                    time=now + curve.latency_at(concurrency),
                    kind="done",
                    payload={"id": next_request_id},
                )
            )

    while (event := queue.pop()) is not None:
        if event.time > until:
            break
        result.replica_seconds += len(replicas) * (event.time - last_time)
        last_time = event.time

        if event.kind == "arrival":
            waiting.append(event.time)
            start_service(event.time)
        elif event.kind == "done":
            arrived = in_flight.pop(event.payload["id"])
            result.latencies.append(event.time - arrived)
            result.completed += 1
            start_service(event.time)
        elif event.kind == "evaluate":
            state = FleetState(
                waiting=len(waiting),
                in_flight=len(in_flight),
                serving_replicas=serving_count(event.time),
            )
            decision = controller.decide(
                signal_value=signal_fn(state, curve),
                replicas=len(replicas),
                now=event.time,
            )
            if decision is Decision.UP:
                replicas.append(
                    Replica(
                        replica_id=next_replica_id,
                        started_at=event.time,
                        lag=lags.sample(rng),
                    )
                )
                next_replica_id += 1
                result.scale_up_events += 1
            elif decision is Decision.DOWN:
                replicas.pop()
                result.scale_down_events += 1
            result.peak_replicas = max(result.peak_replicas, len(replicas))
            result.peak_serving_replicas = max(result.peak_serving_replicas, state.serving_replicas)
            start_service(event.time)

    result.unfinished = len(waiting) + len(in_flight)
    if result.scale_up_events == 0:
        result.discard_reason = "no_scaling_action"
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_sim_policy.py tests/test_sim.py -v`
Expected: 13 passed.

- [ ] **Step 5: Commit**

```bash
git add autoscale/sim.py tests/test_sim_policy.py
git commit -m "feat: policy-driven simulation with lag drawn from the measured ECDF"
```

---

## Task 11: Sweep, frontier, and the H3 gap metric

**Files:**
- Create: `autoscale/sweep.py`, `autoscale/frontier.py`
- Test: `tests/test_frontier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_frontier.py`:

```python
import pytest

from autoscale.frontier import PolicyPoint, gap_at_iso_cost, h3_verdict, pareto_frontier


def _p(cost, p99, signal="queue_depth"):
    return PolicyPoint(cost=cost, p99=p99, signal=signal, scale_up_at=1.0, scale_down_at=0.1)


def test_frontier_keeps_only_non_dominated_points():
    points = [_p(10, 5), _p(12, 6), _p(20, 2), _p(15, 3)]

    frontier = pareto_frontier(points)

    assert [(f.cost, f.p99) for f in frontier] == [(10, 5), (15, 3), (20, 2)]


def test_a_point_dominated_on_both_axes_is_dropped():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5), _p(11, 6)])] == [(10, 5)]


def test_ties_on_cost_keep_the_better_p99():
    assert [(f.cost, f.p99) for f in pareto_frontier([_p(10, 5), _p(10, 3)])] == [(10, 3)]


def test_gap_at_iso_cost_is_the_spread_between_best_and_worst_signal():
    """The H3 metric, in seconds, at equal spend."""
    frontiers = {
        "queue_depth": [_p(10, 4.0, "queue_depth"), _p(20, 2.0, "queue_depth")],
        "utilization": [_p(10, 9.0, "utilization"), _p(20, 7.0, "utilization")],
        "in_flight_concurrency": [
            _p(10, 3.0, "in_flight_concurrency"),
            _p(20, 1.5, "in_flight_concurrency"),
        ],
    }

    assert gap_at_iso_cost(frontiers, cost=10) == pytest.approx(6.0)
    assert gap_at_iso_cost(frontiers, cost=20) == pytest.approx(5.5)


def test_h3_holds_only_when_the_gap_halves_under_both_shapes():
    """Pre-registered: a halving under one shape only is a partial result, not
    a confirmation. H4 already predicts the ramp's margins shrink, which makes a
    ramp-only halving the easy and less interesting outcome."""
    both = h3_verdict(step_gap_a=10.0, step_gap_c=4.0, ramp_gap_a=8.0, ramp_gap_c=3.0)
    assert both.holds is True

    ramp_only = h3_verdict(step_gap_a=10.0, step_gap_c=9.0, ramp_gap_a=8.0, ramp_gap_c=3.0)
    assert ramp_only.holds is False
    assert ramp_only.partial is True
    assert "ramp" in ramp_only.detail

    neither = h3_verdict(step_gap_a=10.0, step_gap_c=9.5, ramp_gap_a=8.0, ramp_gap_c=7.9)
    assert neither.holds is False
    assert neither.partial is False


def test_exactly_half_counts_as_holding():
    """'at least half' is inclusive; stating it here so the boundary is not
    decided by a floating-point comparison written in a hurry."""
    assert h3_verdict(step_gap_a=10.0, step_gap_c=5.0, ramp_gap_a=8.0, ramp_gap_c=4.0).holds


def test_an_empty_frontier_is_refused():
    with pytest.raises(ValueError, match="empty"):
        pareto_frontier([])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_frontier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.frontier'`

- [ ] **Step 3: Write the frontier module**

Create `autoscale/frontier.py`:

```python
"""Pareto frontiers, the iso-cost slice, and H3's verdict.

Frontiers rather than points, because every policy has thresholds and whichever
set you publish decides the winner. Comparing frontiers is what makes the
comparison fair and robust to the objection that the loser was mistuned.
"""

from dataclasses import dataclass

__all__ = ["PolicyPoint", "H3Verdict", "pareto_frontier", "gap_at_iso_cost", "h3_verdict"]


@dataclass(frozen=True)
class PolicyPoint:
    cost: float  # replica-seconds
    p99: float  # seconds of request latency
    signal: str
    scale_up_at: float
    scale_down_at: float


@dataclass(frozen=True)
class H3Verdict:
    holds: bool
    partial: bool
    detail: str


def pareto_frontier(points: list[PolicyPoint]) -> list[PolicyPoint]:
    """Non-dominated points, ascending by cost. Lower cost and lower p99 are
    both better, so a point is dominated when another is at least as good on
    both axes."""
    if not points:
        raise ValueError("cannot compute a frontier from an empty point set")
    ordered = sorted(points, key=lambda p: (p.cost, p.p99))
    frontier: list[PolicyPoint] = []
    best_p99 = float("inf")
    for point in ordered:
        if point.p99 < best_p99:
            frontier.append(point)
            best_p99 = point.p99
    return frontier


def _p99_at_cost(frontier: list[PolicyPoint], cost: float) -> float:
    """The best p99 achievable at or below `cost` on this frontier."""
    affordable = [p for p in frontier if p.cost <= cost]
    if not affordable:
        raise ValueError(f"no point on this frontier costs {cost} or less")
    return min(p.p99 for p in affordable)


def gap_at_iso_cost(frontiers: dict[str, list[PolicyPoint]], cost: float) -> float:
    """The H3 metric: p99 spread between the best and worst signal at equal spend."""
    achieved = [_p99_at_cost(f, cost) for f in frontiers.values()]
    return max(achieved) - min(achieved)


def h3_verdict(
    step_gap_a: float, step_gap_c: float, ramp_gap_a: float, ramp_gap_c: float
) -> H3Verdict:
    """H3 holds only if the gap at least halves under BOTH spike shapes.

    Pre-registered that way because H4 already predicts the ramp's margins
    shrink, so a ramp-only halving is both the easier outcome and the less
    interesting one. A single-shape halving is published as partial rather than
    rounded up.
    """
    step_halved = step_gap_c <= step_gap_a / 2
    ramp_halved = ramp_gap_c <= ramp_gap_a / 2

    if step_halved and ramp_halved:
        return H3Verdict(True, False, "gap at least halved under both step and ramp")
    if step_halved or ramp_halved:
        shape = "step" if step_halved else "ramp"
        return H3Verdict(
            False,
            True,
            f"gap halved under {shape} only; published as a partial result, "
            "not as confirmation",
        )
    return H3Verdict(False, False, "gap did not halve under either shape")
```

- [ ] **Step 4: Write the sweep module**

Create `autoscale/sweep.py`:

```python
"""The threshold sweep: one controller, every signal, both shapes, both
measured lag distributions.

Repetitions are fixed at 30 per configuration by the pre-registration, before
any result was inspected, so the count cannot be chosen to make an interval
land where it is wanted.
"""

import hashlib
import random
from dataclasses import dataclass

from autoscale.arrivals import SpikeShape, arrival_times
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller
from autoscale.frontier import PolicyPoint
from autoscale.service import ServiceCurve
from autoscale.signals import SIGNALS
from autoscale.sim import run_with_policy

__all__ = ["SweepConfig", "run_sweep"]

REPETITIONS = 30
COOLDOWN_SECONDS = 30.0
EVALUATE_EVERY_SECONDS = 5.0
MAX_REPLICAS = 12


def _derive_seed(seed: int, signal: str, up: float, down: float, rep: int) -> int:
    """A per-configuration seed that is stable ACROSS PROCESSES.

    Not `hash((seed, signal, up, down, rep))`: Python randomizes string hashing
    per process unless PYTHONHASHSEED is set, so a hash-derived seed would give
    a different sweep on every invocation while looking deterministic inside any
    single run -- including inside the test that checks reproducibility. The
    artifact's whole claim is that a reader re-running this gets these numbers.
    """
    key = f"{seed}|{signal}|{up}|{down}|{rep}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


Task 5's review established that `ServiceCurve.measured` was inert — nothing read it, so the placeholder's "self-identifying" property prevented nothing. Task 5 made the flag *trustworthy* (frozen dataclass, tuple points, so it cannot be reassigned or bypassed). **This task is where it becomes load-bearing.** `run_sweep` refuses an unmeasured curve unless the caller says so in words, so invented numbers can only reach a result file deliberately:

```python
def _require_measured_curve(curve: ServiceCurve, allow_unmeasured: bool) -> None:
    """The artifact's whole claim is that every parameter is measured and only
    the control loop is modeled. Until plan 2's hardware sweep runs, the service
    curve is invented placeholder points; a sweep against them produces
    frontiers that look exactly like real ones. The flag is not a comment --
    reaching a result from unmeasured points requires typing
    `allow_unmeasured=True`, which is greppable in a way a stale comment is not.
    """
    if curve.measured or allow_unmeasured:
        return
    raise ValueError(
        "refusing to sweep against an unmeasured service curve. These points "
        "are invented placeholders and the frontiers derived from them would "
        "be indistinguishable from measured ones in every output format. Pass "
        "allow_unmeasured=True to run a layout or plumbing check against them."
    )
```


# PER-SIGNAL THRESHOLD GRIDS. The three signals do not share units, so one
# numeric grid cannot span all three:
#
#   queue_depth            requests waiting per replica     0 .. unbounded
#   in_flight_concurrency  active requests per replica      0 .. max_measured_concurrency
#   utilization            a FRACTION                       0 .. 1
#
# Sweeping the single grid (2, 4, 8, 16) across all three -- the original
# design -- puts every threshold above utilization's maximum possible value, so
# that policy never fires and its whole frontier collapses to one "never scale"
# point. H2 ("utilization is worst") would then be confirmed trivially by a
# units mismatch rather than by the censoring mechanism the artifact publishes,
# which would make the headline indefensible.
#
# This is NOT the per-signal tuning the design rejects. That rejection is about
# refusing to hand-pick each signal's best operating point; giving each signal a
# grid that spans its own range is what makes the frontiers comparable at all.
# The grids are pre-registered in docs/experiment-a2.md before any sweep runs,
# so they cannot be chosen to produce a result.
THRESHOLDS: dict[str, tuple[tuple[float, ...], tuple[float, ...]]] = {
    # signal: (scale_up_grid, scale_down_grid)
    "queue_depth": ((1.0, 2.0, 4.0, 8.0, 16.0), (0.0, 0.25, 0.5, 1.0)),
    "in_flight_concurrency": ((2.0, 4.0, 8.0, 12.0, 16.0), (0.5, 1.0, 2.0, 4.0)),
    "utilization": ((0.50, 0.65, 0.80, 0.90, 0.95), (0.05, 0.15, 0.30, 0.50)),
}


@dataclass(frozen=True)
class SweepConfig:
    shape: SpikeShape
    lags: LagDistribution
    curve: ServiceCurve
    arm: str
    until: float


def run_sweep(
    config: SweepConfig, seed: int, allow_unmeasured: bool = False
) -> tuple[list[PolicyPoint], list[str]]:
    """Every (signal, up, down) combination, `REPETITIONS` times each.

    Returns the policy points and the discard reasons encountered. Discards are
    returned rather than dropped so the count can be published per signal, as
    the pre-registration requires.
    """
    _require_measured_curve(config.curve, allow_unmeasured)
    points: list[PolicyPoint] = []
    discards: list[str] = []

    for signal in sorted(SIGNALS):
        up_grid, down_grid = THRESHOLDS[signal]
        for up in up_grid:
            for down in down_grid:
                if down >= up:
                    continue
                costs: list[float] = []
                p99s: list[float] = []
                for rep in range(REPETITIONS):
                    rng = random.Random(_derive_seed(seed, signal, up, down, rep))
                    arrivals = arrival_times(config.shape, until=config.until, rng=rng)
                    if not arrivals:
                        discards.append("empty_trace")
                        continue
                    result = run_with_policy(
                        arrivals=arrivals,
                        signal=signal,
                        controller=Controller(
                            scale_up_at=up,
                            scale_down_at=down,
                            cooldown=COOLDOWN_SECONDS,
                            max_replicas=MAX_REPLICAS,
                        ),
                        lags=config.lags,
                        curve=config.curve,
                        until=config.until,
                        evaluate_every=EVALUATE_EVERY_SECONDS,
                        rng=rng,
                    )
                    if result.discard_reason:
                        discards.append(result.discard_reason)
                        continue
                    costs.append(result.replica_seconds)
                    p99s.append(result.percentiles()["p99"])
                if not costs:
                    continue
                points.append(
                    PolicyPoint(
                        cost=sum(costs) / len(costs),
                        p99=sum(p99s) / len(p99s),
                        signal=signal,
                        scale_up_at=up,
                        scale_down_at=down,
                    )
                )
    return points, discards
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_frontier.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add autoscale/frontier.py autoscale/sweep.py tests/test_frontier.py
git commit -m "feat: threshold sweep, Pareto frontiers, and H3's two-shape verdict"
```

---

## Task 12: The four figures

**Files:**
- Create: `autoscale/figures.py`, `scripts/a2_render_figures.py`
- Test: `tests/test_a2_figures.py`

Figures are pixels. Per the repo's standing rule, this task does not end without eyes on the rendered output — a chart that executes without error is not a chart that reads.

- [ ] **Step 1: Write the failing test**

Create `tests/test_a2_figures.py`:

```python
import matplotlib

matplotlib.use("Agg")

import pytest

from autoscale.figures import convergence, frontiers
from autoscale.frontier import PolicyPoint
from harness.figure_guards import MIN_PHONE_TEXT_PX


def _points(signal, offset):
    return [
        PolicyPoint(cost=c, p99=c / 10 + offset, signal=signal, scale_up_at=1.0, scale_down_at=0.1)
        for c in (100.0, 200.0, 400.0)
    ]


FRONTIERS_A = {s: _points(s, i) for i, s in enumerate(["queue_depth", "utilization"], start=1)}
FRONTIERS_C = {s: _points(s, i * 0.3) for i, s in enumerate(["queue_depth", "utilization"], start=1)}


def test_convergence_figure_renders_both_panels(tmp_path):
    out = convergence(FRONTIERS_A, FRONTIERS_C, swept={20.0: 6.0, 80.0: 12.0}, path=tmp_path / "c.png")
    assert out.exists()


def test_the_modeled_panel_is_labelled_on_the_chart_itself(tmp_path):
    """Spec section 11: the measured/modeled boundary is drawn on the chart, not
    left to the caption, so a reader who only looks at figures still sees which
    half is measurement."""
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept={20.0: 6.0, 80.0: 12.0},
        path=tmp_path / "c.png", return_figure=True,
    )
    texts = [t.get_text().lower() for t in fig.findobj(match=matplotlib.text.Text)]

    assert any("measured" in t for t in texts)
    assert any("modeled" in t for t in texts)


def test_every_text_artist_clears_the_phone_legibility_floor(tmp_path):
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept={20.0: 6.0, 80.0: 12.0},
        path=tmp_path / "c.png", return_figure=True,
    )
    width_in = fig.get_size_inches()[0]

    for text in fig.findobj(match=matplotlib.text.Text):
        if not text.get_text().strip():
            continue
        px = text.get_fontsize() * 375 / (72 * width_in)
        assert px >= MIN_PHONE_TEXT_PX, f"{text.get_text()!r} renders at {px:.1f}px on a phone"


def test_n_is_stated_on_the_figure(tmp_path):
    fig = convergence(
        FRONTIERS_A, FRONTIERS_C, swept={20.0: 6.0, 80.0: 12.0},
        path=tmp_path / "c.png", return_figure=True,
    )
    texts = " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))
    assert "n=" in texts.lower()


def test_frontiers_figure_refuses_to_silently_drop_a_signal(tmp_path):
    with pytest.raises(ValueError, match="utilization"):
        frontiers({"queue_depth": _points("queue_depth", 1)}, path=tmp_path / "f.png")


def test_frontiers_figure_renders_with_all_three(tmp_path):
    all_three = {s: _points(s, i) for i, s in enumerate(
        ["queue_depth", "utilization", "in_flight_concurrency"], start=1)}
    assert frontiers(all_three, path=tmp_path / "f.png").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_a2_figures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autoscale.figures'`

Note: this test imports `harness.figure_guards`, which the harness extraction's Task 11 creates. If the extraction has not landed, import `MIN_PHONE_TEXT_PX` from `coldstart.analysis.figures` instead and fix it when the extraction runs.

- [ ] **Step 3: Write the implementation**

Create `autoscale/figures.py`:

```python
"""Artifact 2's body figures.

Same constraints as artifact 1: no truncated axes, N stated on the figure,
legible at phone width, no series silently dropped, and rendered output looked
at by a human before anything is called done.

The convergence figure carries the artifact's argument and has one job artifact
1's figures did not: it puts measured and modeled results side by side, so the
boundary between them has to be visible ON the chart. A reader who only looks at
figures must not come away believing the swept-lag panel was measured.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from autoscale.frontier import PolicyPoint, pareto_frontier

__all__ = ["convergence", "frontiers"]

SIGNAL_ORDER = ("queue_depth", "in_flight_concurrency", "utilization")
SIGNAL_LABEL = {
    "queue_depth": "queue depth",
    "in_flight_concurrency": "in-flight concurrency",
    "utilization": "GPU utilization",
}
SIGNAL_COLOR = {
    "queue_depth": "#2f6fd0",
    "in_flight_concurrency": "#4a8a4a",
    "utilization": "#c04a4a",
}
FIG_WIDTH_IN = 11.0
MEASURED_BG = "#eef7ee"
MODELED_BG = "#e8f1ff"


def _pt(px: float) -> float:
    """Point size rendering at `px` pixels once downscaled to 375 px width."""
    return px * 72 * FIG_WIDTH_IN / 375


def convergence(frontiers_a, frontiers_c, swept, path, return_figure=False):
    """Figure 1. Left panel measured, right panel modeled, boundary on the chart."""
    fig, (left, right) = plt.subplots(1, 2, figsize=(FIG_WIDTH_IN, 5.0))

    n_a = sum(len(v) for v in frontiers_a.values())
    n_c = sum(len(v) for v in frontiers_c.values())

    left.set_facecolor(MEASURED_BG)
    for label, data, style in (("arm A, 81.1 s", frontiers_a, "-"), ("arm C, 39.4 s", frontiers_c, "--")):
        for signal, points in data.items():
            front = pareto_frontier(points)
            left.plot(
                [p.cost for p in front], [p.p99 for p in front],
                style, color=SIGNAL_COLOR.get(signal, "#555"),
                label=f"{SIGNAL_LABEL.get(signal, signal)} ({label})",
            )
    left.set_title("MEASURED — artifact 1's two distributions", fontsize=_pt(9.0))
    left.set_xlabel("cost (replica-seconds)", fontsize=_pt(8.5))
    left.set_ylabel("p99 request latency (s)", fontsize=_pt(8.5))
    left.legend(fontsize=_pt(8.0))
    left.text(
        0.02, 0.02, f"n={n_a + n_c} policy points", transform=left.transAxes,
        fontsize=_pt(8.0),
    )

    right.set_facecolor(MODELED_BG)
    lags = sorted(swept)
    right.plot(lags, [swept[k] for k in lags], "o-", color="#2f6fd0")
    right.set_title("MODELED — lag swept, not measured", fontsize=_pt(9.0))
    right.set_xlabel("cold-start lag (s)", fontsize=_pt(8.5))
    right.set_ylabel("inter-signal gap at iso-cost (s)", fontsize=_pt(8.5))
    right.text(
        0.02, 0.02, f"n={len(lags)} modeled lag values", transform=right.transAxes,
        fontsize=_pt(8.0),
    )

    for axis in (left, right):
        axis.tick_params(labelsize=_pt(8.0))
        axis.set_ylim(bottom=0)
        axis.set_xlim(left=0)

    fig.tight_layout()
    fig.savefig(path, dpi=100)
    if return_figure:
        return fig
    plt.close(fig)
    return Path(path)


def frontiers(by_signal, path, return_figure=False):
    """Figure 2. All three signals, or it refuses to draw."""
    missing = [s for s in SIGNAL_ORDER if s not in by_signal]
    if missing:
        raise ValueError(
            f"no frontier for signal(s) {missing}; refusing to publish a chart "
            "that appears to compare three signals while showing fewer"
        )

    fig, axis = plt.subplots(figsize=(FIG_WIDTH_IN, 5.0))
    total = 0
    for signal in SIGNAL_ORDER:
        front = pareto_frontier(by_signal[signal])
        total += len(front)
        axis.plot(
            [p.cost for p in front], [p.p99 for p in front], "o-",
            color=SIGNAL_COLOR[signal], label=SIGNAL_LABEL[signal],
        )
    axis.set_xlabel("cost (replica-seconds)", fontsize=_pt(8.5))
    axis.set_ylabel("p99 request latency (s)", fontsize=_pt(8.5))
    axis.legend(fontsize=_pt(8.0))
    axis.tick_params(labelsize=_pt(8.0))
    axis.set_ylim(bottom=0)
    axis.set_xlim(left=0)
    axis.text(0.02, 0.02, f"n={total} frontier points", transform=axis.transAxes, fontsize=_pt(8.0))
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    if return_figure:
        return fig
    plt.close(fig)
    return Path(path)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_a2_figures.py -v`
Expected: 6 passed.

- [ ] **Step 5: Write the render script**

Create `scripts/a2_render_figures.py`:

```python
"""Render artifact 2's figures. Against the PLACEHOLDER service curve until
plan 2's sweep runs -- output is a draft for inspecting layout, not a result."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.figures import convergence, frontiers
from autoscale.frontier import gap_at_iso_cost, pareto_frontier
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.sweep import SweepConfig, run_sweep

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="data/campaign.jsonl")
    ap.add_argument("--out", default="build/a2-figures-draft")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if not SERVICE_CURVE_PLACEHOLDER.measured:
        print("WARNING: rendering against the PLACEHOLDER service curve. "
              "These figures are a layout draft, not a result.")

    lags = load_measured_lags(args.store)
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)

    by_arm = {}
    for arm in ("A", "C"):
        points, discards = run_sweep(
            SweepConfig(
                shape=shape, lags=lags[arm], curve=SERVICE_CURVE_PLACEHOLDER, arm=arm,
                until=400.0,
            ),
            seed=17,
            allow_unmeasured=True,  # placeholder curve; layout draft, not a result
        )
        print(f"arm {arm}: {len(points)} policy points, {len(discards)} discards")
        by_arm[arm] = {
            s: [p for p in points if p.signal == s] for s in {p.signal for p in points}
        }

    swept = {}
    for lag_value in (20.0, 40.0, 60.0, 80.0, 120.0):
        from autoscale.coldstart_ecdf import LagDistribution

        points, _ = run_sweep(
            SweepConfig(
                shape=shape, lags=LagDistribution(samples=[lag_value]),
                curve=SERVICE_CURVE_PLACEHOLDER, arm=f"synthetic-{lag_value}",
                until=400.0,
            ),
            seed=17,
            allow_unmeasured=True,  # placeholder curve; layout draft, not a result
        )
        per_signal = {
            s: pareto_frontier([p for p in points if p.signal == s])
            for s in {p.signal for p in points}
        }
        swept[lag_value] = gap_at_iso_cost(per_signal, cost=min(p.cost for p in points) * 2)

    print(convergence(by_arm["A"], by_arm["C"], swept, out / "convergence.png"))
    print(frontiers(by_arm["A"], out / "frontiers.png"))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Render against the placeholder curve**

```bash
.venv/bin/python scripts/a2_render_figures.py --out build/a2-figures-draft
```

Expected: a `WARNING: rendering against the PLACEHOLDER service curve` line, then per-arm point and discard counts, then two file paths.

- [ ] **Step 7: Look at both PNGs, at full size and downscaled to 375 px**

```bash
open build/a2-figures-draft/convergence.png build/a2-figures-draft/frontiers.png
```

Confirm: the measured and modeled panels are visually distinguishable, every axis starts at zero, the legend does not cover data, and no text is clipped. Then downscale and look again:

```bash
.venv/bin/python -c "
from pathlib import Path
import matplotlib.image as mpimg, matplotlib.pyplot as plt
for name in ['convergence','frontiers']:
    src = Path('build/a2-figures-draft')/f'{name}.png'
    img = mpimg.imread(src); h, w = img.shape[0], img.shape[1]
    fig = plt.figure(figsize=(375/100, 375/100*h/w), dpi=100)
    ax = fig.add_axes([0,0,1,1]); ax.imshow(img); ax.axis('off')
    dst = src.with_name(f'{name}-phone.png'); fig.savefig(dst, dpi=100); plt.close(fig)
    print(dst)
"
```

Attach both paths to the task report and state what you saw. A figure that renders is not a figure that reads.

- [ ] **Step 8: Commit**

```bash
git add autoscale/figures.py scripts/a2_render_figures.py tests/test_a2_figures.py
git commit -m "feat: artifact 2's figures, with the measured/modeled boundary on the chart"
```

---

## Task 13: GPU-free end-to-end proof

**Files:**
- Create: `tests/test_a2_end_to_end.py`

The gate this whole plan exists to reach: the entire path runs, deterministically, with no GPU and no money spent.

- [ ] **Step 1: Write the test**

Create `tests/test_a2_end_to_end.py`:

```python
"""The whole path: artifact 1's measured lags -> sweep -> frontiers -> H3.

Spec section 15: the expensive half does not start until the cheap half is
proven. This is the proof.
"""

import matplotlib

matplotlib.use("Agg")

from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import load_measured_lags
from autoscale.frontier import gap_at_iso_cost, h3_verdict, pareto_frontier
from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from autoscale.sweep import SweepConfig, run_sweep

def _sweep(arm, lags, shape):
    return run_sweep(
        SweepConfig(
            shape=shape, lags=lags, curve=SERVICE_CURVE_PLACEHOLDER, arm=arm,
            until=400.0,
        ),
        seed=17,
        allow_unmeasured=True,  # placeholder curve; this proves plumbing, not a result
    )


def test_the_whole_path_runs_on_artifact_ones_real_data():
    lags = load_measured_lags("data/campaign.jsonl")
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)

    points_a, discards_a = _sweep("A", lags["A"], shape)
    points_c, _ = _sweep("C", lags["C"], shape)

    assert points_a and points_c
    front_a = {s: pareto_frontier([p for p in points_a if p.signal == s])
               for s in {p.signal for p in points_a}}
    front_c = {s: pareto_frontier([p for p in points_c if p.signal == s])
               for s in {p.signal for p in points_c}}

    cost = max(min(p.cost for p in points_a), min(p.cost for p in points_c)) * 2
    gap_a = gap_at_iso_cost(front_a, cost=cost)
    gap_c = gap_at_iso_cost(front_c, cost=cost)

    assert gap_a >= 0.0 and gap_c >= 0.0
    assert isinstance(discards_a, list)


def test_the_sweep_is_reproducible_from_its_seed():
    lags = load_measured_lags("data/campaign.jsonl")
    shape = SpikeShape(kind="step", baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0)

    first, _ = _sweep("A", lags["A"], shape)
    second, _ = _sweep("A", lags["A"], shape)

    assert [(p.cost, p.p99, p.signal) for p in first] == [
        (p.cost, p.p99, p.signal) for p in second
    ]


def test_h3_verdict_is_computable_end_to_end():
    verdict = h3_verdict(step_gap_a=10.0, step_gap_c=4.0, ramp_gap_a=8.0, ramp_gap_c=3.0)
    assert verdict.holds is True
    assert verdict.detail


def test_nothing_publishes_a_number_from_the_placeholder_curve_unmarked():
    """The placeholder must stay self-identifying until plan 2 replaces it."""
    assert SERVICE_CURVE_PLACEHOLDER.measured is False


def test_the_sweep_reproduces_across_processes_not_just_within_one():
    """The reproducibility test above runs in one process, where even a
    hash-derived seed looks stable. Python randomizes string hashing PER
    PROCESS, so a sweep seeded that way would give different numbers to a
    reader re-running it while passing every in-process test. This runs the
    sweep in two fresh interpreters and compares."""
    import subprocess
    import sys

    program = (
        "from autoscale.arrivals import SpikeShape;"
        "from autoscale.coldstart_ecdf import load_measured_lags;"
        "from autoscale.service import SERVICE_CURVE_PLACEHOLDER;"
        "from autoscale.sweep import SweepConfig, run_sweep;"
        "lags = load_measured_lags('data/campaign.jsonl');"
        "shape = SpikeShape(kind='step', baseline_rate=2.0, k=4.0, ramp=0.0, sustain=190.0);"
        "pts, _ = run_sweep(SweepConfig(shape=shape, lags=lags['A'],"
        " curve=SERVICE_CURVE_PLACEHOLDER, arm='A', until=400.0),"
        " seed=17, allow_unmeasured=True);"
        "print(round(sum(p.p99 for p in pts), 6))"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", program], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    ]

    assert runs[0] == runs[1], (
        f"the sweep produced {runs[0]} and {runs[1]} in two fresh processes; "
        "something in the seed derivation depends on per-process state"
    )
```

- [ ] **Step 2: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass, including artifact 1's 541 — this plan adds only, so no existing test may change.

- [ ] **Step 3: Verify artifact 1 is untouched**

Run: `./scripts/parity_check.sh` if the harness extraction's Task 2 has landed; otherwise:

```bash
.venv/bin/python scripts/analyse.py --store data/campaign.jsonl | diff - data/analysis.json && echo "artifact 1 analysis unchanged"
```

Expected: no diff. This plan reads artifact 1's data and must not perturb it.

- [ ] **Step 4: Run lint**

Run: `.venv/bin/python -m ruff check .`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tests/test_a2_end_to_end.py
git commit -m "test: the whole artifact 2 path runs GPU-free on artifact 1's real data"
```

---

## What plan 2 covers, and why it cannot be written yet

Reconnaissance Q1/Q2/Q3, the real service-curve sweep, both validation gates, the frontier campaign, and publication.

It cannot be written honestly now because **its content depends on what reconnaissance finds.** Whether the confirmatory gate exists at all depends on Q2; the sweep's concurrency range depends on Q3; the absolute baseline rate and `k` depend on the measured service curve. Writing those tasks today would mean inventing the answers, which is the failure mode this repo's reconnaissance discipline exists to prevent.

Plan 2 gets written after reconnaissance runs and its findings are committed as fixtures.

---

## Self-review notes

**Spec coverage.** §5 measured inputs → Tasks 2, 5. §6 replica model → Task 6. §7 hypotheses → Task 1, with H3's two-shape rule enforced in code at Task 11. §8 traffic model → Tasks 1, 4. §11 figures → Task 12. §14's host-novelty risk → `Replica.host_id` in Task 6. §9 reconnaissance, §10 validation, §12 post, §13 budget are plan 2 by §15's split, and the section above says so rather than leaving them unaccounted.

**Two forward references, both flagged inline.** `JsonlStore(path, RunRecord)` in Task 2 and `harness.figure_guards` in Task 12 assume the harness extraction has landed. Each carries the one-line fallback for running before it does. They are the only two.

**Determinism is load-bearing and tested three ways** — arrivals (Task 4), a policy run (Task 10), and the whole sweep (Task 13). Without it the frontier comparison is noise, and a sweep that quietly changed between runs would be indistinguishable from a real effect.
