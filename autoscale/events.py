"""The simulation's spine: a time-ordered event queue with a monotonic clock.

Discrete-event rather than time-stepped. A time-stepped loop has to pick a tick
size, and the answer depends on it: too coarse and a 0.3 s TTFT rounds away,
too fine and a 190 s spike costs millions of empty iterations. Events cost
nothing when nothing happens.
"""

import heapq
import itertools
import math
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
    (an arrival and a replica ready at the same float). `Event` is deliberately
    unordered -- `@dataclass(frozen=True)` defaults to `order=False`, so it has
    no `__lt__` -- which means without the counter, a tie would fall through to
    an unsupported `Event < Event` comparison. That comparison only happens
    when the heap's internal sift actually has to compare the two tied entries,
    and whether it does depends on the shape of the heap around them: sometimes
    it blows up immediately on the tied push, sometimes only later on an
    unrelated pop, sometimes not before the run ends. An intermittent
    TypeError, not a reliable one -- which is worse, since it can pass review
    and CI on one input mix and then blow up on a production seed.

    Do not "simplify" this by adding `order=True` to `Event` and dropping the
    counter. That would make the comparison stop raising, but only by falling
    through to comparing `kind` (the next field after `time`) whenever two
    times tie -- so a run's outcome would depend on which `kind` string sorts
    first, silently. That is exactly the determinism bug this queue exists to
    avoid: an unrelated dataclass field order deciding tie order instead of
    arrival order. Runs must be reproducible from a seed.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self.now = 0.0

    def push(self, event: Event) -> None:
        # NaN compares False against everything, including itself, and +-inf
        # compare as ordinary (extreme) floats -- so `event.time < self.now`
        # below can't be trusted to catch either. A NaN would silently pass
        # through and the heap would order it wherever heapify happens to
        # leave it. A +inf would sail in as a normal push, pop last, and then
        # pin `self.now` at infinity, which makes every finite event queued
        # afterward look like a backwards-clock violation instead of naming
        # the real problem.
        if not math.isfinite(event.time):
            if math.isnan(event.time):
                raise ValueError(
                    "event time is NaN; something computed a delay as e.g. "
                    "inf - inf, and a NaN time sorts unpredictably in the heap "
                    "instead of raising, which would silently reorder every "
                    "event queued after it"
                )
            raise ValueError(
                f"event time is {event.time}, which is infinite. +inf sorts to "
                "the back of every heap and never fires, and if it were popped "
                "anyway it would pin `now` at infinity, mislabeling every "
                "later finite push as a backwards-clock violation instead of "
                "naming the real problem; -inf sorts ahead of everything and "
                "would fire before the run began. Either way the cause is an "
                "arithmetic overflow upstream, not a clock ordering error."
            )
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
