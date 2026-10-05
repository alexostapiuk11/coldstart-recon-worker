"""How long each grid point must run so every decile clears the p99 floor.

Publication is all-or-nothing per grid point: a decile's p99 is published only
if it clears the floor in every one of R repetitions (amendment §8). For all R
to clear together with probability 0.95, each must clear with probability
1 - 0.05 / R. Sizing each run to clear 95% of the time would leave all 30
clearing together only about 21% of the time.

Bursty traffic is overdispersed, so no formula sizes it. The window is found
by a pilot: count-only traces, drawn from the same processes as `traffic` but
on their own seed range, growing the window until the pilot's miss rate is
within budget. Only counts are needed, and a count is a Poisson draw given a
model's ON time, so the pilot never builds a trace or runs the simulator.
"""

import math
from collections.abc import Sequence

import numpy as np

from placement.tails import P99_FLOOR
from placement.traffic import DECILES

__all__ = ["pilot_window"]


def _counts(
    shares: Sequence[float],
    regime: str,
    total_rate: float,
    window: float,
    mean_burst: float,
    duty: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Requests per model over one window, drawn from the regime's process."""
    rates = np.asarray(shares) * total_rate
    if regime == "spread":
        return rng.poisson(rates * window)
    mean_off = mean_burst * (1.0 - duty) / duty
    on_time = np.zeros(len(shares))
    for k in range(len(shares)):
        on = rng.random() < duty
        t = 0.0
        while t < window:
            length = rng.exponential(mean_burst if on else mean_off)
            if on:
                on_time[k] += min(length, window - t)
            t += length
            on = not on
    return rng.poisson(rates / duty * on_time)


def pilot_window(
    shares: Sequence[float],
    deciles: Sequence[int],
    regime: str,
    total_rate: float,
    repetitions: int,
    mean_burst: float,
    duty: float,
    pilot_traces: int,
    seed: int,
    start: float,
    grow: float = 1.10,
    max_rounds: int = 60,
) -> float:
    """The smallest measured window, growing from `start` by `grow`, at which
    at most `floor(pilot_traces * 0.05 / repetitions)` pilot traces leave some
    decile under the floor."""
    if regime not in ("spread", "bursty"):
        raise ValueError(f"unknown regime {regime!r}")
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError(f"repetitions must be a positive int, got {repetitions!r}")
    allowed = math.floor(pilot_traces * 0.05 / repetitions)
    if pilot_traces < 1 or allowed < 1:
        raise ValueError(
            f"{pilot_traces} pilot traces allow no misses at {repetitions} "
            "repetitions, so no finite window could pass; the pilot would only "
            "stop at max_rounds and report a window it never verified. Use at "
            f"least {math.ceil(repetitions / 0.05)} pilot traces"
        )
    if not math.isfinite(start) or start <= 0 or not grow > 1.0:
        raise ValueError("start must be positive and grow above 1")
    index = np.asarray(deciles)
    window = start
    for _ in range(max_rounds):
        rng = np.random.default_rng(seed)
        misses = 0
        for _ in range(pilot_traces):
            per_model = _counts(shares, regime, total_rate, window, mean_burst, duty, rng)
            per_decile = np.bincount(index, weights=per_model, minlength=DECILES)
            if (per_decile < P99_FLOOR).any():
                misses += 1
                if misses > allowed:
                    break
        if misses <= allowed:
            return window
        window *= grow
    raise RuntimeError(
        f"no window up to {window:.0f} s passed the pilot in {max_rounds} rounds; "
        "a grid point this thin should be removed from the grid, not run short"
    )
