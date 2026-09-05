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
    (an arrival and a replica ready at the same float), and without an explicit
    counter the heap falls back to comparing payloads, so a run's outcome would
    depend on dataclass field order. Runs must be reproducible from a seed.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, Event]] = []
        self._counter = itertools.count()
        self.now = 0.0

    def push(self, event: Event) -> None:
        # NaN compares False against everything, including itself, so
        # `event.time < self.now` below would silently pass a NaN through
        # rather than reject it, and the heap would then order it wherever
        # heapify happens to leave it -- a wrong pop order with no exception,
        # instead of the loud failure a bad delay computation deserves.
        if math.isnan(event.time):
            raise ValueError(
                "event time is NaN; something computed a delay as e.g. "
                "inf - inf, and a NaN time sorts unpredictably in the heap "
                "instead of raising, which would silently reorder every "
                "event queued after it"
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
