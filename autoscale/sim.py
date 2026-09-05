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
  fleet stays slow after the fleet drains, and vice versa. Within a single
  instant this also means the per-replica load rises as a simultaneous batch
  fills, so the first request dispatched is charged `ceil(1 / replicas)` and
  the last `ceil(k / replicas)`; the `EventQueue` tiebreak makes that order
  deterministic, so runs stay reproducible from a seed -- it does not make
  the order physical. The distortion is two-sided rather than systematically
  flattering, and the open-loop validation gate is exactly the measurement
  that says whether it matters.

What is NOT modeled is vLLM's scheduler itself, deliberately: the curve
already encodes what continuous batching does to latency, so re-deriving it
from a model would replace a measurement with an assumption.
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
    # ergonomic: it makes both halves of the model incoherent. Capacity
    # `1.5 * max_measured_concurrency` is not a whole number of requests, and
    # `len(in_flight) < capacity` rounds it UP (capacity 1.5 admits TWO), while
    # `ceil(in_flight / 1.5)` is a per-replica load on a replica that does not
    # exist -- and the resulting optimistic latencies are reported as if 1.5
    # replicas were a meaningful fleet. A NaN passes every check and then makes
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
    # Per replica, not per fleet: the curve measured ONE replica at a swept
    # concurrency, so `max_measured_concurrency` is how many requests a single
    # replica was actually observed serving.
    capacity = replicas * curve.max_measured_concurrency

    def start_service(now: float) -> None:
        nonlocal next_id
        while waiting and len(in_flight) < capacity:
            # FIFO: the front of `waiting` is the earliest arrival still
            # queued, so no request overtakes one that arrived before it.
            arrived = waiting.pop(0)
            # The load on the replica this request lands on, under even
            # balancing -- not the fleet total. `+ 1` counts the request being
            # dispatched, and `ceil` rounds a fleet that cannot be divided
            # evenly toward the replica carrying the extra request.
            concurrency = math.ceil((len(in_flight) + 1) / replicas)
            # Tying capacity to the measured range means this is normally
            # unreachable: `len(in_flight) + 1 <= replicas * M` implies
            # `ceil((len(in_flight) + 1) / replicas) <= M` for a whole-number
            # M. It can still fire when the curve's top measured point is
            # fractional -- capacity 1.5 admits two requests, whose load is 2
            # -- so the guard stays rather than becoming an assumption.
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
