"""The campaign's cost, computed from reconnaissance timings (amendment §6).

Per instance: adapter setup + a warm restart + the warm-up + four timed phases.
Timings are measured at the reconnaissance points (1, 16, 64 slots) and
interpolated linearly in log2(slots) between them. The cut order is the
amendment's: the gauge control first, then the diagnostic. Sweep resolution
is the author's call and is only reported, never cut here.
"""

import math
from dataclasses import replace

from multilora.conditions import GATE, campaign_conditions, parse_condition

TIMED_PHASES = 4


def _interp(points: dict[int, float], n: int) -> float:
    xs = sorted(points)
    if n in points:
        return points[n]
    lo = max(x for x in xs if x < n)
    hi = min(x for x in xs if x > n)
    f = (math.log2(n) - math.log2(lo)) / (math.log2(hi) - math.log2(lo))
    return points[lo] + f * (points[hi] - points[lo])


def instance_seconds(n, prereg, timings) -> float:
    """`timings` maps slots to {'setup_s', 'warm_startup_s', 'seconds_per_request'}."""
    def t(key):
        return _interp({k: v[key] for k, v in timings.items()}, n)

    per_request = t("seconds_per_request")
    warmup = prereg.warmup_requests_per_adapter * n * per_request
    timed = TIMED_PHASES * prereg.requests_per_phase * per_request
    return t("setup_s") + t("warm_startup_s") + warmup + timed


def estimate(prereg, timings, *, cold_startup_s: dict[int, float], cap_usd: float = 20.0) -> dict:
    def total(p):
        seconds = 0.0
        for name in campaign_conditions(p) + [GATE]:
            cond = parse_condition(name, p)
            seconds += p.instances_per_condition * instance_seconds(cond.n_slots, p, timings)
        seconds += sum(_interp(cold_startup_s, n) + _interp(
            {k: v["warm_startup_s"] for k, v in timings.items()}, n) for n in p.sweep)
        return seconds / 3600.0

    steps = []
    current = prereg
    for label, change in (("as registered", {}), ("control cut", {"include_control": False}),
                          ("diagnostic cut", {"include_control": False, "include_diagnostic": False})):
        current = replace(prereg, **change)
        hours = total(current)
        steps.append({"step": label, "gpu_hours": hours, "usd": hours * prereg.gpu_hourly_rate})
        if hours * prereg.gpu_hourly_rate <= cap_usd:
            break
    final = steps[-1]
    return {
        "steps": steps,
        "include_control": current.include_control,
        "include_diagnostic": current.include_diagnostic,
        "gpu_hours": final["gpu_hours"],
        "usd": final["usd"],
        "over_cap": final["usd"] > cap_usd,
        "cap_usd": cap_usd,
    }
