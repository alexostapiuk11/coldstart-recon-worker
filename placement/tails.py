"""Per-decile p99: the fairness view, under the shared sample floor.

Under swap, aggregate p99 can look fine while cold-tail tenants are unusable,
because hot models dominate the request count (August design §8). So p99 is
reported per popularity decile.

The shared statistics refuse a p99 from fewer than MIN_SAMPLES["p99"] samples.
Here a decile below the floor reports None rather than raising, because a
thin decile is an expected property of a run at high skew, and the caller
decides what that means for the grid point (amendment §8: all or nothing).
"""

from collections.abc import Sequence

from harness.stats import MIN_SAMPLES, percentiles
from placement.sim import RunResult
from placement.traffic import DECILES

__all__ = ["P99_FLOOR", "aggregate_p99", "decile_breach", "decile_counts", "decile_p99s"]

P99_FLOOR = MIN_SAMPLES["p99"]


def decile_counts(models: Sequence[int], deciles: Sequence[int]) -> tuple[int, ...]:
    """Requests per decile. `deciles[m]` is model m's decile."""
    counts = [0] * DECILES
    for m in models:
        counts[deciles[m]] += 1
    return tuple(counts)


def aggregate_p99(result: RunResult) -> float | None:
    """p99 over every post-warm-up request, None under the floor. The number a
    fleet dashboard shows, and the one the per-decile view exists to correct."""
    if len(result.latencies) < P99_FLOOR:
        return None
    return percentiles(result.latencies, want=("p99",))["p99"]


def decile_breach(
    result: RunResult, deciles: Sequence[int], slo: float
) -> tuple[float | None, ...]:
    """Fraction of each decile's requests slower than `slo`, None for a decile
    that received none. The tail-tenant SLO cost (August §8): what share of a
    cold tenant's requests miss the target its fleet was sized against."""
    slow = [0] * DECILES
    total = [0] * DECILES
    for m, latency in zip(result.models, result.latencies, strict=True):
        total[deciles[m]] += 1
        slow[deciles[m]] += latency > slo
    return tuple(None if n == 0 else s / n for s, n in zip(slow, total, strict=True))


def decile_p99s(result: RunResult, deciles: Sequence[int]) -> tuple[float | None, ...]:
    """p99 latency per decile, None where the decile is under the floor."""
    groups: list[list[float]] = [[] for _ in range(DECILES)]
    for m, latency in zip(result.models, result.latencies, strict=True):
        groups[deciles[m]].append(latency)
    return tuple(
        percentiles(group, want=("p99",))["p99"] if len(group) >= P99_FLOOR else None
        for group in groups
    )
