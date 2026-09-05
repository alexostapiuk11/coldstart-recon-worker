"""One controller, three signals. The thresholds are what the sweep varies.

Deliberately one controller rather than three tuned ones. The August design
frames the question as achievable frontiers precisely because "which signal is
best" is ill-posed -- whichever threshold set you publish decides the winner.
Sweeping one controller's thresholds across every signal is what makes the
comparison fair and robust to the objection that the loser was mistuned.

Spec SS10: controller arithmetic is unit-tested with hand-computed scenarios,
never GPU-validated -- spending GPU money to confirm arithmetic would be
theatre. tests/test_controller.py is the entire verification for this
component.
"""

import math
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
        if not math.isfinite(self.scale_up_at):
            raise ValueError(f"scale_up_at ({self.scale_up_at}) must be a finite number")
        if not math.isfinite(self.scale_down_at):
            raise ValueError(f"scale_down_at ({self.scale_down_at}) must be a finite number")
        if self.scale_down_at >= self.scale_up_at:
            raise ValueError(
                f"scale_down_at ({self.scale_down_at}) must be below scale_up_at "
                f"({self.scale_up_at}); overlapping thresholds oscillate"
            )
        if not math.isfinite(self.cooldown) or self.cooldown < 0:
            raise ValueError(
                f"cooldown ({self.cooldown}) must be a finite, non-negative number of seconds"
            )
        if self.max_replicas < self.min_replicas:
            raise ValueError(
                f"max_replicas ({self.max_replicas}) must be at least min_replicas "
                f"({self.min_replicas})"
            )

    def decide(self, signal_value: float, replicas: int, now: float) -> Decision:
        if math.isnan(signal_value):
            raise ValueError(
                "signal_value is NaN; a controller cannot decide on it -- a NaN "
                "compares False against every threshold and would silently HOLD"
            )
        if self._last_action_at is not None and now - self._last_action_at < self.cooldown:
            return Decision.HOLD
        if signal_value >= self.scale_up_at and replicas < self.max_replicas:
            self._last_action_at = now
            return Decision.UP
        if signal_value <= self.scale_down_at and replicas > self.min_replicas:
            self._last_action_at = now
            return Decision.DOWN
        return Decision.HOLD
