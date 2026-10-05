"""Model-labelled arrival traces: Zipf popularity, two locality regimes.

Frequency and locality are separate axes (August design §7). Two traces with
the same Zipf shares can produce very different swap rates, because LRU follows
whether a model's requests cluster in time, not how often they occur. Both
generators take the same `shares`, so the only thing that differs between the
regimes is clustering.

Model ids are popularity ranks: model 0 is the hottest.
"""

import bisect
import itertools
import math
import random
from collections.abc import Sequence

__all__ = ["DECILES", "Trace", "bursty_trace", "decile_of", "spread_trace", "zipf_shares"]

DECILES = 10

Trace = list[tuple[float, int]]


def zipf_shares(n_models: int, s: float) -> tuple[float, ...]:
    """Share of traffic per model: p(k) proportional to (k + 1) ** -s, k = 0..n-1.

    s = 0 is uniform. The amendment states the form as p(k) ∝ k^-s over
    k = 1..N; this is the same distribution indexed from zero.
    """
    if type(n_models) is not int or n_models < 2:
        raise ValueError(
            f"n_models must be an int of at least 2, got {n_models!r}; with one "
            "model there is nothing to place"
        )
    if not math.isfinite(s) or s < 0:
        raise ValueError(
            f"s must be finite and non-negative, got {s!r}; a negative s makes "
            "the coldest model the most popular and inverts every decile"
        )
    weights = [(k + 1) ** -s for k in range(n_models)]
    total = math.fsum(weights)
    return tuple(w / total for w in weights)


def decile_of(n_models: int) -> tuple[int, ...]:
    """Popularity decile of each model: 0 is the hottest tenth, 9 the coldest.

    Requires `n_models` divisible by 10, so every decile holds the same number
    of models. An uneven split would make "the coldest decile" mean a different
    number of tenants at different N.
    """
    if type(n_models) is not int or n_models < DECILES or n_models % DECILES:
        raise ValueError(
            f"n_models must be a positive multiple of {DECILES}, got {n_models!r}; "
            "otherwise deciles hold different numbers of models"
        )
    per = n_models // DECILES
    return tuple(k // per for k in range(n_models))


def _check(shares: Sequence[float], total_rate: float, until: float) -> None:
    if len(shares) < 2:
        raise ValueError("a trace needs at least two models' shares")
    for i, share in enumerate(shares):
        if not math.isfinite(share) or share <= 0:
            raise ValueError(
                f"shares[{i}] is {share!r}; every model needs a positive share, "
                "or it never receives a request and silently leaves its decile"
            )
    if abs(math.fsum(shares) - 1.0) > 1e-9:
        raise ValueError(
            f"shares sum to {math.fsum(shares)!r}, not 1; the trace would offer "
            "a different total load from the one the scenario states"
        )
    for name, value in (("total_rate", total_rate), ("until", until)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"{name} is {value!r}; it must be finite and positive, or the "
                "generator either loops forever or returns an empty trace"
            )


def spread_trace(
    shares: Sequence[float], total_rate: float, until: float, rng: random.Random
) -> Trace:
    """Poisson arrivals at `total_rate` over [0, until], each labelled
    independently by `shares`. Arrivals carry no memory of which model came
    before, which is what "spread" means."""
    _check(shares, total_rate, until)
    cumulative = list(itertools.accumulate(shares))
    # Summation dust can leave the last entry a hair under 1, and a draw above
    # it would index past the last model.
    cumulative[-1] = 1.0
    out: Trace = []
    t = 0.0
    while True:
        t += rng.expovariate(total_rate)
        if t > until:
            return out
        out.append((t, bisect.bisect_right(cumulative, rng.random())))


def bursty_trace(
    shares: Sequence[float],
    total_rate: float,
    until: float,
    mean_burst: float,
    duty: float,
    rng: random.Random,
) -> Trace:
    """Each model alternates ON and OFF, and receives arrivals only while ON.

    ON periods are exponential with mean `mean_burst`. OFF periods are
    exponential with mean `mean_burst * (1 - duty) / duty`, so a model is ON a
    fraction `duty` of the time. While ON it receives Poisson arrivals at
    `share * total_rate / duty`. Its long-run rate is therefore exactly
    `share * total_rate`, the same as the spread regime at the same shares.

    Each model starts ON with probability `duty`, the stationary state. Because
    exponential periods are memoryless, the time left in that first period is a
    fresh draw. So a run does not open with every model ON at once.
    """
    _check(shares, total_rate, until)
    if not math.isfinite(mean_burst) or mean_burst <= 0:
        raise ValueError(f"mean_burst must be finite and positive, got {mean_burst!r}")
    if not (0.0 < duty < 1.0):
        raise ValueError(
            f"duty must be strictly between 0 and 1, got {duty!r}; at 1 the "
            "regime is spread under another name, and at 0 no request arrives"
        )
    mean_off = mean_burst * (1.0 - duty) / duty
    out: Trace = []
    for model, share in enumerate(shares):
        on_rate = share * total_rate / duty
        on = rng.random() < duty
        t = 0.0
        while t < until:
            length = rng.expovariate(1.0 / (mean_burst if on else mean_off))
            if on:
                end = min(t + length, until)
                a = t
                while True:
                    a += rng.expovariate(on_rate)
                    if a > end:
                        break
                    out.append((a, model))
            t += length
            on = not on
    out.sort()
    return out
