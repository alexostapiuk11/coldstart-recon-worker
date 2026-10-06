"""Numbers the post derives from committed load-balancer, validation and host evidence.

Pure functions over the records' plain dicts, so the post analysis
(scripts/a2_post_analysis.py) and its tests share one implementation. Nothing
here is pre-registered: these are the evidence behind the post's findings
about RunPod's load balancer and host speed, and the post says so.
"""

import bisect
import statistics
from collections import defaultdict

__all__ = ["delivered_rate", "engine_occupancy", "host_speed_table", "per_worker_concurrency",
           "stall_breakdown", "stall_share"]

WORKER = "x-a2-worker"
SERVER_LATENCY = "x-a2-server-latency-ms"


def delivered_rate(rows) -> float:
    """Completions per second over the span of completion times, 200s only.

    Completions, not sends: the first probe offered 25-100 req/s and the path
    delivered ~17/s, which a send count would hide.

    n completions between the first and the last enclose n - 1 intervals, so
    the rate is (n - 1) / span. n / span overstates by one interval's worth,
    which made probe 5 "deliver" 210.8 req/s against 210 offered, more than
    was sent. Rejected: n / span, for exactly that overshoot.
    """
    done = sorted(r["sent"] + r["latency"] for r in rows
                  if r.get("status") == 200 and r.get("latency") is not None)
    if len(done) < 2:
        raise ValueError("fewer than two completions; a rate needs a span")
    return (len(done) - 1) / (done[-1] - done[0])


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


def stall_breakdown(record, *, threshold_s: float, server_backlog_s: float) -> dict:
    """How much of a completed request's client-side delay was spent outside the engine.

    A request can take over `threshold_s` client-side for two reasons: it waited
    outside the engine (in the load balancer, or on the way), or it waited inside
    the engine behind a burst the load balancer had just released. The first is
    client minus server latency; the second shows as a long server latency.
    Returns, over completed (200) requests with both latencies: the share over
    `threshold_s` client-side (as `stall_share`), the share whose client minus
    server latency is over `threshold_s`, and, of the requests over `threshold_s`
    client-side, the share whose server latency is over `server_backlog_s`.
    Rejected: reporting the client-side share alone as "held by the load
    balancer", which counts engine backlog as load-balancer time.
    """
    rows = [(c, s) for c, s, st in zip(record["client_latency_s"], record["server_latency_s"],
                                       record["status"], strict=True)
            if st == 200 and c is not None and s is not None]
    if not rows:
        raise ValueError("no completed request carries both latencies; a share of nothing "
                         "is not zero")
    slow = [(c, s) for c, s in rows if c > threshold_s]
    return {
        "completed": len(rows),
        "share_client_over": len(slow) / len(rows),
        "share_client_minus_server_over": sum(1 for c, s in rows if c - s > threshold_s)
        / len(rows),
        "share_of_slow_with_server_over": (sum(1 for _, s in slow if s > server_backlog_s)
                                           / len(slow)) if slow else None,
    }


def engine_occupancy(record) -> list[tuple[float, int, float]]:
    """(engine arrival, requests in flight on the engine at that arrival, server latency).

    Each stamped request (a 200 with an engine-arrival stamp and a server
    latency) occupies the engine over [received, received + server latency].
    At each arrival, the count is the requests that have arrived by then (the
    arriving one included) minus those that have finished by then; a request
    finishing exactly at an arrival has finished. "In flight" here is what the
    engine holds, running or queued behind its own `--max-num-seqs`, which is
    what lets the count exceed that cap. Sorted by arrival.
    """
    rows = sorted((t, lat) for t, lat, st in zip(record["server_received_s"],
                                                 record["server_latency_s"],
                                                 record["status"], strict=True)
                  if st == 200 and t is not None and lat is not None)
    if not rows:
        raise ValueError("no 200 carries an engine-arrival stamp and a server latency, so "
                         "there is no occupancy to reconstruct")
    starts = [t for t, _ in rows]
    ends = sorted(t + lat for t, lat in rows)
    return [(t, bisect.bisect_right(starts, t) - bisect.bisect_right(ends, t), lat)
            for t, lat in rows]


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
