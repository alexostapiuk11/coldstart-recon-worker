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
    # Post-warm-up arrivals whose model was resident and admitting on some GPU
    # when the request arrived: August §8's hit rate is hits / len(latencies).
    hits: int = 0
    # When each swap began. `swaps` counts warm-up and drain-out swaps too; a
    # swap rate is read from the starts inside the measured window.
    swap_starts: list[float] = field(default_factory=list)


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
        result.swap_starts.append(now)
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
            if now >= warmup and hosts[m]:
                result.hits += 1
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
