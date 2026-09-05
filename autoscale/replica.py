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

import math
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
        # NaN compares False against every `<`/`>`/`==` below, so a NaN
        # `started_at` or `lag` would slip past the negative-lag check and
        # then make every `state_at`/`ready_at` comparison silently False,
        # reporting a replica that is neither absent, starting, nor serving
        # instead of raising here. +-inf compares as an ordinary (extreme)
        # value and would pass the negative-lag check legitimately, but then
        # poison `ready_at` (`started_at + lag`) into +-inf or NaN, which
        # every later `state_at` call would compare against silently instead
        # of raising.
        for field_name, value in (("started_at", self.started_at), ("lag", self.lag)):
            if not math.isfinite(value):
                raise ValueError(
                    f"replica {self.replica_id} has {field_name}={value!r}, "
                    "which is not finite; a non-finite value compares False "
                    "against every ordering check in state_at (NaN) or "
                    "poisons ready_at's addition with inf (+-inf), so it "
                    "would silently produce a replica that is never absent, "
                    "starting, or serving instead of raising here"
                )
        if self.lag < 0:
            raise ValueError(f"negative lag {self.lag}: a replica cannot be ready before it starts")

    @property
    def ready_at(self) -> float:
        return self.started_at + self.lag

    def state_at(self, t: float) -> ReplicaState:
        if math.isnan(t):
            # `t < self.started_at` and `t < self.ready_at` are both False
            # for NaN, so without this guard a NaN query would fall through
            # both checks and return SERVING -- a confident, wrong answer --
            # instead of raising.
            raise ValueError(
                "t is NaN; NaN compares False against both boundary checks "
                "in state_at, so it would silently fall through to SERVING "
                "instead of raising"
            )
        if t < self.started_at:
            return ReplicaState.ABSENT
        if t < self.ready_at:
            return ReplicaState.STARTING
        return ReplicaState.SERVING
