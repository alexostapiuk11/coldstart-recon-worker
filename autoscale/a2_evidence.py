"""Numbers the post derives from committed load-balancer, validation and host evidence.

Pure functions over the records' plain dicts, so the post analysis
(scripts/a2_post_analysis.py) and its tests share one implementation. Nothing
here is pre-registered: these are the evidence behind the post's findings
about RunPod's load balancer and host speed, and the post says so.
"""

import statistics
from collections import defaultdict

__all__ = ["delivered_rate", "host_speed_table", "per_worker_concurrency", "stall_share"]

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"


def delivered_rate(rows) -> float:
    """Completions per second over the span of completion times, 200s only.

    Completions, not sends: the first probe offered 25-100 req/s and the path
    delivered ~17/s, which a send count would hide.
    """
    done = sorted(r["sent"] + r["latency"] for r in rows
                  if r.get("status") == 200 and r.get("latency") is not None)
    if len(done) < 2:
        raise ValueError("fewer than two completions; a rate needs a span")
    return len(done) / (done[-1] - done[0])


def per_worker_concurrency(rows, *, return_leg_s: float) -> dict:
    """Mean and peak requests in flight on each worker, server-side.

    The probes ran before the engine stamped its arrival time, so each server
    interval is reconstructed: it ends `return_leg_s` before the client saw
    the response (about half the ~0.2 s unloaded load-balancer overhead) and
    lasts the stamped server latency. The approximation shifts intervals by a
    fraction of a second and is disclosed with every number it produces.
    Rejected: client-side intervals, which include the load balancer's own
    time and so overstate what a worker held.
    """
    per: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        h = r.get("headers") or {}
        if r.get("status") != 200 or WORKER not in h or SERVER_LATENCY not in h:
            continue
        server = float(h[SERVER_LATENCY]) / 1000.0
        end = r["sent"] + r["latency"] - return_leg_s
        per[h[WORKER]].append((end - server, end))
    out = {}
    for worker, intervals in per.items():
        # At equal timestamps (t, -1) sorts before (t, 1): a request ending exactly
        # when another starts does not count as overlap.
        events = sorted([(a, 1) for a, _ in intervals] + [(b, -1) for _, b in intervals])
        level = peak = 0
        area, last = 0.0, events[0][0]
        for t, d in events:
            area += level * (t - last)
            last = t
            level += d
            peak = max(peak, level)
        span = events[-1][0] - events[0][0]
        out[worker] = {"requests": len(intervals), "max": peak,
                       "mean": area / span if span > 0 else 0.0}
    return out


def stall_share(record, *, threshold_s: float) -> float:
    """Fraction of completed requests whose client latency exceeded `threshold_s`."""
    lat = [x for x, st in zip(record["client_latency_s"], record["status"], strict=True)
           if x is not None and st == 200]
    if not lat:
        raise ValueError("no completed requests; a share of nothing is not zero")
    return sum(1 for x in lat if x > threshold_s) / len(lat)


def host_speed_table(runs, curve_latency: dict) -> dict:
    """Per host and level: median latency of the ok runs, run count, ratio to the curve."""
    by: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        if r.get("outcome") == "ok":
            by[r["host"]["host_id"]][int(r["level"])].append(r["latency_s"])
    return {host: {level: {"median_s": statistics.median(v), "n": len(v),
                           "ratio": statistics.median(v) / curve_latency[level]}
                   for level, v in sorted(levels.items())}
            for host, levels in by.items()}
