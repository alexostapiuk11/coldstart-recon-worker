"""Measured simulator inputs, reduced from stored measurement runs.

The bridge from `placement_measure` (what the worker recorded) to plan 1's
types (what the simulator consumes): a swap-time `EmpiricalDistribution`, a
solo `ServiceCurve`, and a `ColocatedSurface`. Every reduction refuses rather
than reduces around a gap, as `harness.service_sweep.reduce_curve` does: a
missing cell or a thin one would be interpolated over by the surface and
published as measured.

Per point, the median across repetitions of each run's own median latency,
the service sweep's statistic, so a co-located latency and a solo one are the
same kind of number.
"""

from autoscale.service import ServiceCurve
from harness.stats import median
from placement.colocated import ColocatedSurface
from placement.resample import EmpiricalDistribution
from placement_measure.campaigns import parse_cell, parse_swap

__all__ = ["cell_validity", "colocated_surface", "solo_curve", "swap_distribution"]


def swap_distribution(records, *, cold: bool, targets=None) -> EmpiricalDistribution:
    """Swap durations from every ok swap in the given cache state, optionally
    only those whose incoming model is in `targets`. The simulator draws the
    cold distribution (amendment §5)."""
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok":
            continue
        _, b, is_cold = parse_swap(r.condition)
        if is_cold == cold and (targets is None or b in targets):
            samples.append(r.output["swap_s"])
    if not samples:
        raise ValueError(
            f"no ok swap with cold={cold} and targets={targets}; an empty distribution "
            "would simulate swaps that cost nothing"
        )
    return EmpiricalDistribution(samples=tuple(samples), measured=True)


def cell_validity(record) -> str | None:
    """None if the cell's measurement stands; otherwise why it does not."""
    if record.outcome != "ok":
        return f"run failed: {record.failure}"
    load = record.output.get("neighbour_load")
    if load and load.get("level"):
        if not (load.get("ramp") or {}).get("reached"):
            return "the neighbour never reached its load before the measured run"
        if load.get("ended_before_measured_run"):
            return "the neighbour ran out of requests during the measured run"
    return None


def _medians(records, *, kind_of, min_repeats) -> dict:
    by: dict = {}
    for r in records:
        if r.kind != "cell" or cell_validity(r) is not None:
            continue
        key = kind_of(r)
        if key is not None:
            by.setdefault(key, []).append(r.output["run"])
    thin = {k: len(v) for k, v in by.items() if len(v) < min_repeats}
    if thin:
        raise ValueError(f"cells with fewer than {min_repeats} valid repetitions: {thin}")
    return by


def solo_curve(records, *, levels, min_repeats: int) -> ServiceCurve:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return own if neighbour is None else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
    missing = [c for c in levels if c not in by]
    if missing:
        raise ValueError(f"solo levels {missing} have no valid run; the curve would skip them")
    points = []
    for c in levels:
        runs = by[c]
        util = [r["gpu_util"] for r in runs if r.get("gpu_util") is not None]
        if not util:
            raise ValueError(f"level {c} has no GPU utilisation reading; the curve needs one")
        points.append((c, median([r["latency_s"] for r in runs]),
                       median([r["throughput_tps"] for r in runs]), median(util)))
    return ServiceCurve(points=points, measured=True)


def colocated_surface(records, *, own_levels, neighbour_levels, min_repeats: int) -> ColocatedSurface:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return None if neighbour is None else (own, neighbour)

    by = _medians(records, kind_of=key, min_repeats=min_repeats)
    missing = [(o, n) for o in own_levels for n in neighbour_levels if (o, n) not in by]
    if missing:
        raise ValueError(
            f"grid cells {missing} have no valid run; the surface would interpolate over them "
            "and present the guess as measured"
        )
    latency = tuple(
        tuple(median([r["latency_s"] for r in by[(o, n)]]) for n in neighbour_levels)
        for o in own_levels
    )
    return ColocatedSurface(own=tuple(own_levels), neighbour=tuple(neighbour_levels),
                            latency=latency, measured=True)
