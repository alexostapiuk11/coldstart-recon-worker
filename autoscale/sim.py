"""The simulation loop. Fixed capacity here; the policy-driven loop is Task 10.

Concurrency is modeled at the fleet level: each of the `replicas` serving
replicas holds exactly one request at a time, so the fleet has `replicas`
service positions, and a request's service time is read from the measured
curve at the number of requests actually in flight across the fleet the
instant it is dispatched. That is coarser than modeling vLLM's scheduler, and
deliberately so -- the curve already encodes what continuous batching does to
latency, so re-deriving it from a model would replace a measurement with an
assumption.

What that abstraction does NOT model, stated plainly because the open-loop
validation gate in plan 2 is what will expose it:

* Fleet concurrency is read from a curve measured per replica. With N
  replicas each holding one request, this asks the curve "what is latency at
  concurrency N?" -- the latency of ONE replica serving N concurrent requests
  -- even though each replica here is serving one. The fleet is effectively
  modeled as a single replica with N service positions, not as N independent
  replicas. On a rising curve that is pessimistic for a spread-out fleet.
* A request's service time is frozen at dispatch. Concurrency changes while it
  runs -- others finish, others start -- and the running request keeps the
  value it was given. A request dispatched into a busy fleet stays slow after
  the fleet drains, and one dispatched into an idle fleet stays fast after the
  fleet fills.
* Within one batch of simultaneous dispatches the curve is read at 1, 2, 3...
  as the positions fill, so the first request of a simultaneous batch is
  charged the idle-fleet service time and the last the full-batch one. Order
  within an instant therefore changes individual latencies, though not their
  sum. The `EventQueue` tiebreak makes that order deterministic, so runs
  remain reproducible from a seed; it does not make it physical.

These are limitations of the modeling approach, not bugs in it. The gate pins
replica count, drives a real transient on hardware, and compares this loop's
predicted latency trajectory against what actually happened -- which is
precisely the measurement that says whether they matter.
"""

import math
from dataclasses import dataclass, field

from autoscale.events import Event, EventQueue
from autoscale.service import ServiceCurve

__all__ = ["SimResult", "run_fixed_capacity"]


@dataclass
class SimResult:
    """The outcome of one run.

    `completed + unfinished` always equals the number of arrivals replayed:
    `run_fixed_capacity` refuses a trace that extends past its window, so
    every request in the trace is accounted for as either finished or not.
    """

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
            # Returning zeros here would report a run that completed NOTHING
            # -- the worst possible outcome, an entirely stalled fleet -- as
            # p50=p99=0.0, i.e. as the best possible one. That is the same
            # flattering direction of error `unfinished` exists to prevent,
            # and it is exactly what an overloaded arm or a too-short window
            # produces, so it is not a corner case: a lagging signal that
            # completes nothing in the window would score perfectly.
            raise ValueError(
                "no completed requests: percentiles over zero latencies "
                "would report a perfectly stalled run as p50=p99=0.0. Check "
                "`completed` before calling, and discard or widen the run "
                "rather than publishing zeros"
            )
        ordered = sorted(self.latencies)

        def q(p: float) -> float:
            idx = min(len(ordered) - 1, int(p * len(ordered)))
            return ordered[idx]

        return {"p50": q(0.50), "p90": q(0.90), "p95": q(0.95), "p99": q(0.99)}


def run_fixed_capacity(
    arrivals: list[float], replicas: int, curve: ServiceCurve, until: float
) -> SimResult:
    """Replay `arrivals` against a constant `replicas` and return the outcome.

    Service is FIFO: `waiting` is drained from the front, so a request that
    arrived later can never be dispatched before one that arrived earlier.
    """
    # Materialised before the emptiness check so an exhausted or one-shot
    # iterable cannot pass it (a generator is truthy even when it yields
    # nothing) and then silently be consumed by the validation loop before
    # the queue is built, producing a run over zero requests.
    arrivals = list(arrivals)

    # `replicas < 1` is False for a NaN and for any float above 1, so the
    # type check must come first. A float replicas is not a harmless
    # ergonomic: `len(in_flight) < capacity` with capacity=1.5 admits TWO
    # concurrent requests, so a fractional count silently rounds capacity UP
    # and reports the resulting optimistic latencies as if 1.5 replicas were
    # a meaningful fleet. A NaN passes every check and then makes
    # `len(in_flight) < capacity` False forever, so nothing is ever
    # dispatched and the run reports every request unfinished rather than
    # naming the bad input.
    # `type(...) is not int` rather than `isinstance`: it also rejects a bool
    # (a replica count of `True` is a caller bug, and `isinstance(True, int)`
    # is True), and it keeps the failure a ValueError carrying the reason,
    # which is this codebase's house style for invalid input -- see
    # `coldstart.analysis.stats._row_value`, which exists to replace a
    # context-free TypeError with an explanatory ValueError.
    if type(replicas) is not int:
        raise ValueError(
            f"replicas must be an int, got {replicas!r} ({type(replicas).__name__}); "
            "a float capacity silently rounds the concurrency limit up "
            "(len(in_flight) < 1.5 admits two requests) and a NaN one blocks "
            "every dispatch, both of which produce a plausible-looking run "
            "instead of an error"
        )
    if replicas < 1:
        raise ValueError("at least one replica is required to serve anything")
    if not arrivals:
        raise ValueError(
            "empty arrival trace: the pre-registration discards such a run "
            "rather than reporting a perfect p99 over zero requests"
        )
    # NaN compares False against `event.time > until`, so a NaN window never
    # breaks the loop and silently becomes an UNBOUNDED one -- every request
    # completes and the run reports zero unfinished. -inf breaks on the first
    # event, so nothing runs at all. +inf is an unbounded window written as a
    # number; if that is what the caller wants they should say so with a
    # finite bound, because an unbounded replay of a policy that never drains
    # its backlog does not terminate.
    if not math.isfinite(until):
        if math.isnan(until):
            raise ValueError(
                "until is NaN; `event.time > until` is False for a NaN, so "
                "the window would never end and the run would report every "
                "request completed and none unfinished -- an unbounded "
                "replay silently reported as a bounded one"
            )
        raise ValueError(
            f"until is {until!r}; +inf makes the window unbounded (a replay "
            "that never terminates if the backlog never drains) and -inf "
            "ends it before the first event, reporting a run in which "
            "nothing happened at all"
        )
    if until < 0.0:
        raise ValueError(
            f"until must be non-negative, got {until!r}; the window ends "
            "before any arrival can occur, so the run reports zero completed "
            "and zero unfinished -- a caller bug (a window computed the "
            "wrong way round) hidden behind an empty-looking result"
        )

    for t in arrivals:
        # The EventQueue rejects both of these too, but names the cause as a
        # computed delay or a backwards clock. Here the cause is a malformed
        # arrival TRACE, and saying so is the difference between checking the
        # trace and hunting a phantom arithmetic bug in the loop.
        if not math.isfinite(t):
            raise ValueError(
                f"arrival time {t!r} is not finite; a NaN sorts unpredictably "
                "in the event heap and an infinite arrival never fires, so "
                "the request would silently vanish from the run instead of "
                "being replayed"
            )
        if t < 0.0:
            raise ValueError(
                f"arrival time {t!r} is negative; the window starts at t=0, "
                "so this request arrived before the run began"
            )
        if t > until:
            # Not pedantry: such an arrival is popped after the loop has
            # already broken, so it lands in neither `completed` nor
            # `unfinished` and disappears from the accounting entirely. An
            # overloaded arm replayed against a too-short window would report
            # a handful of fast completions and no backlog -- the exact
            # direction of error that flatters a lagging signal. Refusing
            # keeps `completed + unfinished == len(arrivals)` unconditional.
            raise ValueError(
                f"arrival time {t!r} is after the window ends at until={until!r}; "
                "such a request is neither completed nor counted unfinished, "
                "so it would vanish from the accounting and make an "
                "overloaded run look uncongested. Slice the trace to the "
                "window deliberately instead"
            )

    queue = EventQueue()
    for t in arrivals:
        queue.push(Event(time=t, kind="arrival"))

    result = SimResult()
    waiting: list[float] = []  # arrival times of queued requests
    in_flight: dict[int, float] = {}  # completion event id -> arrival time
    next_id = 0
    capacity = replicas

    def start_service(now: float) -> None:
        nonlocal next_id
        while waiting and len(in_flight) < capacity:
            # FIFO: the front of `waiting` is the earliest arrival still
            # queued, so no request overtakes one that arrived before it.
            arrived = waiting.pop(0)
            concurrency = len(in_flight) + 1
            if curve.is_extrapolating(concurrency):
                result.extrapolated_samples += 1
            service = curve.latency_at(concurrency)
            next_id += 1
            in_flight[next_id] = arrived
            queue.push(Event(time=now + service, kind="done", payload={"id": next_id}))

    while (event := queue.pop()) is not None:
        # The heap pops in time order, so the first event past the window
        # means every event still queued is past it too. Breaking here leaves
        # the requests behind those events in `waiting` and `in_flight`,
        # where the tally below counts them as unfinished rather than
        # dropping them.
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
