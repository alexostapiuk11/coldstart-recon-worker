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
import random
from dataclasses import dataclass, field

from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Controller, Decision
from autoscale.events import Event, EventQueue
from autoscale.replica import Replica, ReplicaState
from autoscale.service import ServiceCurve
from autoscale.signals import SIGNALS, FleetState
from autoscale.stats import percentiles as _percentiles

__all__ = ["SimResult", "run_fixed_capacity", "run_with_policy"]


@dataclass
class SimResult:
    """The outcome of one run.

    `completed + unfinished` always equals the number of arrivals replayed:
    both `run_fixed_capacity` and `run_with_policy` refuse a trace that
    extends past `until`, so every request in the trace is accounted for as
    either finished or not. The arrival bookkeeping makes the same promise by
    value, not just by count:

        sorted(completed_arrivals + unfinished_arrivals) == sorted(arrivals)

    The count alone cannot catch a loop that records the wrong number --
    a completion time, or a request id -- because those come in exactly the
    right quantity. The identity can, and it is what the tests check.
    """

    latencies: list[float] = field(default_factory=list)
    # Arrival time of each entry in `latencies`, index for index. Kept because
    # `latencies` is appended in COMPLETION order and the open-loop validation
    # gate compares latency by ARRIVAL time -- which request came in when the
    # fleet was saturated is the whole comparison.
    completed_arrivals: list[float] = field(default_factory=list)
    # Arrival times of the requests still waiting or in flight when the window
    # closed. They are the backlog, and a trajectory that dropped them would
    # report the bins they arrived in as uncongested.
    unfinished_arrivals: list[float] = field(default_factory=list)
    completed: int = 0
    unfinished: int = 0
    extrapolated_samples: int = 0
    peak_replicas: int = 1
    peak_serving_replicas: int = 1
    scale_up_events: int = 0
    scale_down_events: int = 0
    replica_seconds: float = 0.0
    discard_reason: str | None = None

    def percentiles(self) -> dict[str, float]:
        """p50/p90/p95/p99 of request latency, as the pre-registration names.

        p99 is supported here and was not in artifact 1: a spike generates
        thousands of requests, where artifact 1 had ~100 runs per arm and
        published no p99 for exactly that reason. "Thousands" is the
        justification, so `autoscale.stats.percentiles` enforces it -- a run
        that completed a dozen requests has a second-worst latency, not a p99,
        and before the floor the sweep averaged that into the same estimate as
        a run that completed four thousand.

        Routed through `autoscale.stats` rather than computed here so that
        artifact 2's p50 and artifact 1's p50 are one convention. This was
        `ordered[min(len - 1, int(p * len))]` -- nearest-rank, which disagrees
        with artifact 1's linear interpolation by up to a whole order statistic
        on the same data (p50 of 0..999: 500.0 against 499.5).
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
        return _percentiles(self.latencies, want=("p50", "p90", "p95", "p99"))

    def completed_requests(self) -> list[tuple[float, float]]:
        """(arrival_time, latency) for every completed request.

        Refuses a result whose two lists disagree in length -- one built by
        hand, or by a loop that appends to `latencies` without recording the
        arrival. Pairing them up to the shorter list would silently attribute
        latencies to the wrong arrivals.
        """
        if len(self.completed_arrivals) != len(self.latencies):
            raise ValueError(
                f"{len(self.latencies)} latencies but {len(self.completed_arrivals)} "
                "arrival times; this result did not record when its requests "
                "arrived, so no latency can be placed in time"
            )
        return list(zip(self.completed_arrivals, self.latencies, strict=True))


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
            result.completed_arrivals.append(arrived)
            result.completed += 1
            start_service(event.time)

    result.unfinished_arrivals = sorted(waiting + list(in_flight.values()))
    result.unfinished = len(result.unfinished_arrivals)
    return result


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
    precisely why a slow cold start costs money as well as latency. It is the
    integral of the replica count over the whole window [0, until], closed out
    after the loop: stopping at the last EVENT instead would leave up to
    `evaluate_every` seconds of fleet time unbilled, and `evaluate_every` is a
    swept parameter, so the undercount would vary by arm on the cost axis of
    every Pareto frontier.

    Scale-down is LIFO -- `replicas.pop()` removes the most recently launched
    replica, which is frequently one still STARTING, already paid for and about
    to become useful. That is deliberate and it is what Kubernetes does (unready
    pods are deleted ahead of ready ones), but it has a consequence worth
    naming: a scale-up immediately followed by a scale-down destroys a replica
    that was paid for and never served, so a thrashing policy is charged the
    full cold start for nothing. That is the honest cost of thrash under this
    deletion order and it is what makes an over-reactive signal expensive here.
    A least-recently-launched (FIFO) order would instead kill a warm replica and
    keep the cold one, which is worse on every axis; a "drain the oldest, keep
    the warm ones" order is a third policy this experiment does not sweep. The
    model is LIFO, and the discard rule below counts the runs where it bit.

    The controller must be freshly constructed for each run: it carries its own
    cooldown clock, and a used one refuses to act for an entire second run.

    `discard_reason` records the first matching pre-registered exclusion
    (docs/experiment-a2.md, amended 2026-09-05): `"no_scaling_action"` when the
    policy never scaled up, then `"replica_never_served"` when NO replica the
    policy launched during the run ever reached SERVING before it was removed
    or before the window ended. The rule ranges only over replicas launched by
    the POLICY -- the initial replica the fleet starts with is excluded from
    the population, deliberately: it launches at t=0 with lag=0.0 and is
    therefore always serving, so a rule that included it in an "all failed"
    test could never fire and would be dead code. A run where SOME launched
    replicas fail to serve and others do not is KEPT -- their cost stays
    billed in `replica_seconds` from launch, because that cost (paying for a
    replica that never serves) is exactly what a slow cold start does to an
    operator, and is a measured finding rather than noise to exclude. The
    original rule fired on ANY never-served replica, which discarded 100% of
    runs on both of artifact 1's lag distributions -- see the amendment.
    The third pre-registered condition, an empty arrival trace, is refused
    outright below rather than returned as a discard -- exactly as
    `run_fixed_capacity` refuses it -- because a caller that built an empty
    trace has a bug upstream, and a returned result would still expose
    `percentiles()` over zero completions. The two discard reasons are
    disjoint: `scale_up_events == 0` implies no replica was ever launched by
    the policy, so the launched population is empty and the never-served
    check has nothing to range over.
    """
    if signal not in SIGNALS:
        raise KeyError(f"{signal!r} is not a signal; expected one of {sorted(SIGNALS)}")

    # A `Controller` is stateful: `decide` stamps `_last_action_at`, and the
    # cooldown is measured against it. Re-using one across runs is not a
    # slightly-off cooldown, it is a silently DEAD policy: the second run's
    # clock restarts at 0 while `_last_action_at` still holds a time from the
    # first, so `now - _last_action_at` is large and NEGATIVE, hence below any
    # cooldown, so `decide` returns HOLD at every single evaluation. The run
    # completes, reports `scale_up_events == 0`, and is tidily discarded as
    # "no_scaling_action" -- an entire arm of the sweep reading as an inert
    # signal because of a reused object.
    if controller._last_action_at is not None:
        raise ValueError(
            "controller has already acted (at t="
            f"{controller._last_action_at!r}) and carries that cooldown clock "
            "into this run; a re-used controller measures cooldown against the "
            "PREVIOUS run's timeline, so `now - _last_action_at` is negative "
            "for this one and every decision returns HOLD -- the run would be "
            "reported as a signal that never scaled rather than as an error. "
            "Construct a fresh Controller per run"
        )

    # Materialised before the emptiness check for the same reason as
    # `run_fixed_capacity`: a generator is truthy even when it yields nothing,
    # and would then be consumed by the validation loop below, leaving the
    # event queue to be built over zero requests.
    arrivals = list(arrivals)
    if not arrivals:
        raise ValueError(
            "empty arrival trace: the pre-registration discards such a run "
            "rather than reporting a perfect p99 over zero requests"
        )
    # Identical reasoning to `run_fixed_capacity`, and the closed loop makes
    # the NaN case worse rather than better: an unbounded window replays a
    # policy that may never drain its backlog.
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
    # Every degenerate `evaluate_every` fails SILENTLY rather than loudly, and
    # each one disables the policy while leaving a plausible-looking run:
    # zero or negative never advances the tick (an unbounded loop, or with the
    # indexed form below, a single evaluation at t=0), NaN compares False
    # against `<= until` so not one evaluation is scheduled, and +inf schedules
    # exactly the one at t=0. In all of them the controller is never asked
    # anything after t=0, the run reports `scale_up_events == 0`, and it is
    # discarded as an inert signal instead of as a bad parameter.
    if not math.isfinite(evaluate_every):
        raise ValueError(
            f"evaluate_every is {evaluate_every!r}; a NaN schedules no "
            "evaluation at all (NaN <= until is False) and +-inf schedules at "
            "most the one at t=0, so the controller is never asked to decide "
            "and the run reports a signal that never scaled rather than an "
            "invalid parameter"
        )
    if evaluate_every <= 0.0:
        raise ValueError(
            f"evaluate_every must be positive, got {evaluate_every!r}; a "
            "non-positive interval never advances the evaluation tick, so the "
            "controller is asked once at t=0 and never again -- a closed-loop "
            "run silently reduced to an open-loop one"
        )

    for t in arrivals:
        # Same three checks, and the same reason for stating them in terms of
        # the arrival TRACE, as `run_fixed_capacity`.
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
            raise ValueError(
                f"arrival time {t!r} is after the window ends at until={until!r}; "
                "such a request is neither completed nor counted unfinished, "
                "so it would vanish from the accounting and make an "
                "overloaded run look uncongested. Slice the trace to the "
                "window deliberately instead"
            )

    signal_fn = SIGNALS[signal]
    queue = EventQueue()
    # Arrivals are pushed BEFORE the evaluation ticks, so `EventQueue`'s
    # insertion-order tiebreak makes an arrival that lands exactly on a tick
    # visible to that tick's decision. Either order is defensible; what
    # matters is that it is fixed, because the tiebreak is what keeps a run
    # reproducible from its seed.
    for t in arrivals:
        queue.push(Event(time=t, kind="arrival"))
    # `i * evaluate_every` rather than a repeated `tick += evaluate_every`:
    # the accumulating form drifts, and the drift lands on the tick positions
    # themselves (its eighth tick for `evaluate_every=0.1` is
    # 0.6999999999999999, not 0.7000000000000001) and on whether the final
    # tick falls inside the window -- so the number of evaluations, and hence
    # the policy's decisions, would depend on floating-point error rather than
    # on the parameters. Written as a `while` on a growing index rather than
    # `range(int(until // evaluate_every) + 1)`: that floor DROPS the natural
    # final tick whenever the float division rounds down, so `until=1.0,
    # evaluate_every=0.1` would evaluate at 0.0 through 0.9 and never at 1.0.
    # Terminates because `evaluate_every > 0` is guarded above.
    i = 0
    while (tick := i * evaluate_every) <= until:
        queue.push(Event(time=tick, kind="evaluate"))
        i += 1

    result = SimResult()
    replicas = [Replica(replica_id=0, started_at=0.0, lag=0.0)]
    # Every replica ever launched, with the time it was removed (None if it
    # survived the run). `replicas` alone cannot answer the pre-registered
    # "did every launched replica fail to reach serving" question, because a
    # replica killed while STARTING is gone from that list -- and it is
    # precisely the one the rule is about. The initial replica is seeded here
    # too (so `replicas` and `lifetimes` stay in sync), but the discard check
    # below deliberately slices it back out: see that check for why.
    lifetimes: list[tuple[Replica, float | None]] = [(replicas[0], None)]
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
            # Nothing ready: requests stay queued and their wait accrues, which
            # is the whole point of the experiment.
            #
            # This return is defence-in-depth, not the only thing standing
            # between the loop and a ZeroDivisionError -- `capacity` below is
            # `0 * max_measured_concurrency == 0` at serving == 0, so
            # `len(in_flight) < capacity` is already False and the dividing
            # body is unreachable. Mutation testing confirms it: replacing this
            # `return` with `pass` is an equivalent mutant that no test can
            # kill. It stays anyway, because the equivalence is a property of
            # the capacity EXPRESSION rather than of the model -- give capacity
            # a floor (`max(1, serving * M)`, an easy-looking "fix" for a fleet
            # that dispatches nothing) and the division is back in reach with
            # serving still zero. Cheaper to keep than to re-derive.
            return
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
            result.completed_arrivals.append(arrived)
            result.completed += 1
            start_service(event.time)
        elif event.kind == "evaluate":
            state = FleetState(
                waiting=len(waiting),
                in_flight=len(in_flight),
                serving_replicas=serving_count(event.time),
            )
            decision = controller.decide(
                # `queue_depth` and `in_flight_concurrency` return +inf for a
                # fleet with unserved work and nothing serving. That is fine
                # for the threshold comparisons in `Controller.decide`, and it
                # is why nothing here multiplies the signal by the replica
                # count: `0 * inf` is NaN, and `decide` raises on a NaN.
                signal_value=signal_fn(state, curve),
                replicas=len(replicas),
                now=event.time,
            )
            if decision is Decision.UP:
                launched = Replica(
                    replica_id=next_replica_id,
                    started_at=event.time,
                    # The ONLY consumer of `rng` in this function, reached only
                    # from this branch, in event-queue order. Nothing here
                    # iterates a dict or a set, so the draw sequence is fixed
                    # by the seed alone.
                    lag=lags.sample(rng),
                )
                replicas.append(launched)
                lifetimes.append((launched, None))
                next_replica_id += 1
                result.scale_up_events += 1
            elif decision is Decision.DOWN:
                if not replicas:
                    # Unreachable with a sane controller -- `decide` only
                    # returns DOWN when `replicas > min_replicas` -- but a
                    # negative `min_replicas` passes `Controller.__post_init__`
                    # (which only checks max >= min) and reaches here, where
                    # `pop()` would raise a bare "pop from empty list" naming
                    # neither the fleet nor the setting that emptied it.
                    raise ValueError(
                        "scale-down requested with no replicas left; "
                        f"min_replicas={controller.min_replicas!r} permits a "
                        "fleet below zero, which is not a fleet"
                    )
                # LIFO: the newest replica, which may still be STARTING. See
                # the docstring -- this is the modeled deletion order, not an
                # accident of `pop()`.
                removed = replicas.pop()
                for slot, (replica, _) in enumerate(lifetimes):
                    if replica is removed:
                        lifetimes[slot] = (replica, event.time)
                        break
                result.scale_down_events += 1
            result.peak_replicas = max(result.peak_replicas, len(replicas))
            # Measured BEFORE the decision, which is exactly right: `replicas`
            # only changes at an evaluation, and between two evaluations
            # `serving_count` is non-decreasing (replicas only ripen), so this
            # reading is the supremum over the interval that just ended. The
            # only uncovered stretch is the tail after the last tick, closed
            # out below.
            result.peak_serving_replicas = max(result.peak_serving_replicas, state.serving_replicas)
            start_service(event.time)

    # Bill the fleet to the end of the window, not to the last event, and take
    # the serving count once more at `until` -- a replica whose lag expires
    # after the final evaluation tick did become available inside the window.
    result.replica_seconds += len(replicas) * (until - last_time)
    result.peak_serving_replicas = max(result.peak_serving_replicas, serving_count(until))

    result.unfinished_arrivals = sorted(waiting + list(in_flight.values()))
    result.unfinished = len(result.unfinished_arrivals)
    if result.scale_up_events == 0:
        result.discard_reason = "no_scaling_action"
    else:
        # `lifetimes[1:]`: the population this rule ranges over is replicas
        # LAUNCHED BY THE POLICY during the run, not the initial replica the
        # fleet starts with. `lifetimes[0]` is always that initial replica
        # (started_at=0.0, lag=0.0), which is therefore always serving from
        # t=0 -- including it here would make an "ALL of them failed" check
        # unsatisfiable, and the rule would never fire. `scale_up_events > 0`
        # (the `else` above) guarantees `lifetimes[1:]` is non-empty: every
        # UP decision appends exactly one entry to it.
        launched = lifetimes[1:]
        if all(
            replica.ready_at > (until if removed_at is None else removed_at)
            for replica, removed_at in launched
        ):
            # NO replica the policy launched ever reached SERVING -- because
            # the window ended first, or because LIFO scale-down killed it
            # while it was still starting -- means the fleet never
            # effectively grew, so the run measured the cold start rather
            # than the signal. A run where SOME launched replicas served and
            # others did not is kept: their cost stays billed, because that
            # cost is what this artifact is measuring. Amended in
            # docs/experiment-a2.md, 2026-09-05: the original rule fired on
            # ANY never-served replica and discarded 100% of runs.
            result.discard_reason = "replica_never_served"
    return result
