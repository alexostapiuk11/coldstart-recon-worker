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

`require_warm_compile` is pre-registration step 2's validity rule: a cell
whose measured engine compiled does not count, because compile state moves KV
capacity (amendment §5). It defaults off so the reductions read any store, and
plan 3's analysis turns it on.
"""

from autoscale.service import ServiceCurve
from harness.stats import median
from harness.store import JsonlStore
from placement.colocated import ColocatedSurface
from placement.resample import EmpiricalDistribution
from placement_measure.campaigns import parse_cell, parse_swap
from placement_measure.recon_report import COMPILED_ABOVE_S
from placement_measure.records import A4Run

__all__ = ["cell_summary", "cell_validity", "colocated_surface", "eviction_seconds",
           "held_out_check", "load_records", "short_cells", "sleep_distribution", "solo_curve",
           "swap_distribution"]


def load_records(paths) -> list[A4Run]:
    """Every record in the given stores, in order. A top-up campaign has its
    own store, because the resume guard assumes one campaign per store, and
    its cells reduce together with the campaign they top up."""
    out: list[A4Run] = []
    for path in paths:
        out += JsonlStore(path, A4Run).read_all()
    return out


def _compiled(facts: dict | None) -> bool | None:
    s4b = (facts or {}).get("s4b_s")
    return None if s4b is None else s4b > COMPILED_ABOVE_S


def swap_distribution(records, *, cold: bool, targets=None,
                      compiled: bool | None = None) -> EmpiricalDistribution:
    """Swap durations from every ok swap in the given cache state, optionally
    only those whose incoming model is in `targets`, and only those whose
    incoming engine did (True) or did not (False) compile. The simulator draws
    the cold distribution of compile-cache hits (pre-registration step 2)."""
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok":
            continue
        _, b, is_cold = parse_swap(r.condition)
        if is_cold != cold or (targets is not None and b not in targets):
            continue
        if compiled is not None and _compiled((r.output.get("b") or {}).get("facts")) is not compiled:
            continue
        samples.append(r.output["swap_s"])
    if not samples:
        raise ValueError(
            f"no ok swap with cold={cold}, targets={targets} and compiled={compiled}; an "
            "empty distribution would simulate swaps that cost nothing"
        )
    return EmpiricalDistribution(samples=tuple(samples), measured=True)


def sleep_distribution(records) -> EmpiricalDistribution:
    """Sleep-mode switch times, from every ok sleep job (amendment §6)."""
    samples = tuple(r.output["switch_s"] for r in records if r.kind == "sleep" and r.outcome == "ok")
    if not samples:
        raise ValueError("no ok sleep-mode switch; the arm has nothing to report")
    return EmpiricalDistribution(samples=samples, measured=True)


def eviction_seconds(records, *, cold: bool) -> float:
    """Median time an ok cold swap spent evicting its successor's page cache.

    `swap_s` excludes it, because a fleet does not drop its cache before a
    swap. The replay driver does, so the validation's prediction adds this to
    every swap. 0 when the validation's swaps are warm.
    """
    if not cold:
        return 0.0
    samples = []
    for r in records:
        if r.kind != "swap" or r.outcome != "ok" or not parse_swap(r.condition)[2]:
            continue
        if "cache_s" not in r.output:
            raise ValueError(f"swap {r.run_id} has no eviction time; it was measured by an image "
                             "older than plan 3's")
        samples.append(r.output["cache_s"])
    if not samples:
        raise ValueError("no ok cold swap to take an eviction time from")
    return median(samples)


def cell_validity(record, *, require_warm_compile: bool = False) -> str | None:
    """None if the cell's measurement stands; otherwise why it does not."""
    if record.outcome != "ok":
        return f"run failed: {record.failure}"
    load = record.output.get("neighbour_load")
    if load and load.get("level"):
        if not (load.get("ramp") or {}).get("reached"):
            return "the neighbour never reached its load before the measured run"
        if load.get("ended_before_measured_run"):
            return "the neighbour ran out of requests during the measured run"
    if require_warm_compile:
        facts = ((record.output.get("engines") or {}).get("measured") or {}).get("facts")
        compiled = _compiled(facts)
        if compiled is None:
            return "the measured engine's compile state was not read from its log"
        if compiled:
            return ("the measured engine compiled, and compile state moves KV capacity "
                    "(amendment §5)")
    return None


def _medians(records, *, kind_of, min_repeats, require_warm_compile: bool = False) -> dict:
    by: dict = {}
    for r in records:
        if r.kind != "cell" or cell_validity(r, require_warm_compile=require_warm_compile):
            continue
        key = kind_of(r)
        if key is not None:
            by.setdefault(key, []).append(r.output["run"])
    thin = {k: len(v) for k, v in by.items() if len(v) < min_repeats}
    if thin:
        raise ValueError(f"cells with fewer than {min_repeats} valid repetitions: {thin}")
    return by


def solo_curve(records, *, levels, min_repeats: int,
               require_warm_compile: bool = False) -> ServiceCurve:
    def key(r):
        own, neighbour = parse_cell(r.condition)
        return own if neighbour is None else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats,
                  require_warm_compile=require_warm_compile)
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


def colocated_surface(records, *, own_levels, neighbour_levels, min_repeats: int,
                      require_warm_compile: bool = False) -> ColocatedSurface:
    grid = {(o, n) for o in own_levels for n in neighbour_levels}

    def key(r):
        own, neighbour = parse_cell(r.condition)
        # Only grid cells: a held-out cell must never be folded into the
        # surface it is held out to test.
        return (own, neighbour) if (own, neighbour) in grid else None

    by = _medians(records, kind_of=key, min_repeats=min_repeats,
                  require_warm_compile=require_warm_compile)
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


def cell_summary(records, *, require_warm_compile: bool) -> dict[str, dict]:
    """Per cell condition: valid repeats, the median and range of their
    latencies, the measured engine's median KV capacity, and why any repeat
    did not count. The figure's error bars and the record of exclusions."""
    out: dict[str, dict] = {}
    for r in records:
        if r.kind != "cell":
            continue
        entry = out.setdefault(r.condition, {"latencies": [], "kv": [], "excluded": []})
        reason = cell_validity(r, require_warm_compile=require_warm_compile)
        if reason:
            entry["excluded"].append({"run_id": r.run_id, "reason": reason})
            continue
        entry["latencies"].append(r.output["run"]["latency_s"])
        kv = (((r.output.get("engines") or {}).get("measured") or {}).get("facts") or {}).get(
            "kv_capacity_tokens")
        if kv is not None:
            entry["kv"].append(kv)
    for entry in out.values():
        lat = entry.pop("latencies")
        kv = entry.pop("kv")
        entry.update({"n": len(lat), "median": median(lat) if lat else None,
                      "lo": min(lat) if lat else None, "hi": max(lat) if lat else None,
                      "kv_capacity_tokens": median(kv) if kv else None})
    return out


def short_cells(records, conditions, *, min_repeats: int, require_warm_compile: bool) -> list[str]:
    """The cells among `conditions` with fewer than `min_repeats` valid
    repeats, in the given order: what a top-up campaign must re-run."""
    summary = cell_summary(records, require_warm_compile=require_warm_compile)
    return [c for c in conditions if summary.get(c, {"n": 0})["n"] < min_repeats]


def held_out_check(records, surface: ColocatedSurface, cells, *, tolerance: float,
                   min_repeats: int, require_warm_compile: bool) -> list[dict]:
    """Does the surface predict cells it was not built from? August §9's
    second check. A cell passes if the surface's bilinear prediction lies
    inside its repeats' range, or within `tolerance` of their median: a perfect
    model falls outside the range of three repeats one time in four (both
    edges are order statistics), so the range alone would fail it too often."""
    summary = cell_summary(records, require_warm_compile=require_warm_compile)
    out = []
    for cell in cells:
        own, neighbour = parse_cell(cell)
        s = summary.get(cell, {"n": 0})
        if s["n"] < min_repeats:
            raise ValueError(f"held-out cell {cell} has {s['n']} valid repeats, below "
                             f"{min_repeats}; the check would pass or fail on noise")
        predicted = surface.latency_at(own, neighbour)
        inside = s["lo"] <= predicted <= s["hi"]
        close = abs(predicted - s["median"]) <= tolerance * s["median"]
        out.append({"cell": cell, "own": own, "neighbour": neighbour, "predicted": predicted,
                    "median": s["median"], "lo": s["lo"], "hi": s["hi"], "n": s["n"],
                    "passed": inside or close})
    return out
