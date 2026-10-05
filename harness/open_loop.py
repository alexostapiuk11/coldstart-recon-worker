"""Open-loop HTTP replay: send each request at its scheduled time, whatever the server does.

Open loop means the schedule, not the server, decides when each request
leaves: a slow response never delays the next send. That is what makes a
real run comparable to the simulator fed the same arrival times; a closed
loop (`vllm bench serve --max-concurrency`) lets the server's speed shape the
arrivals and confounds the two.

One dispatcher thread sleeps until each scheduled time and hands the request
to a pool. Each worker thread stamps `sent` immediately before the request
leaves, so if the pool is exhausted, the delay shows as send jitter, which the
caller checks (`max_jitter`; artifact 2's gate refuses a run above 0.5 s). It
is not hidden inside a latency. Every request yields an `Outcome`: a failure
is an outcome with an error, never a missing row, because a dropped row
would shrink exactly the bins where the server was struggling.

Times are seconds on `clock` relative to t0, the moment the schedule's zero
is placed (`start_delay` after the call, so the pool is up before the first
send).
"""

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import pairwise

import requests

__all__ = ["Outcome", "http_sender", "max_jitter", "replay"]


@dataclass(frozen=True)
class Outcome:
    index: int
    scheduled: float
    sent: float | None
    latency: float | None
    status: int | None
    headers: dict = field(default_factory=dict)
    error: str | None = None


def max_jitter(outcomes: Sequence[Outcome]) -> float:
    return max((abs(o.sent - o.scheduled) for o in outcomes if o.sent is not None), default=0.0)


def replay(schedule: Sequence[float], send: Callable[[int], tuple[int, dict]], *,
           max_in_flight: int = 1024, start_delay: float = 0.5,
           clock=time.monotonic, sleep=time.sleep) -> list[Outcome]:
    times = list(schedule)
    if any(t < 0 for t in times):
        raise ValueError("the schedule has a negative time; t=0 is the schedule's start")
    if any(b < a for a, b in pairwise(times)):
        raise ValueError(
            "the schedule is not ascending; replay sends in list order, so an out-of-order "
            "entry would be sent late and recorded as jitter the driver caused"
        )
    t0 = clock() + start_delay
    results: list[Outcome | None] = [None] * len(times)

    def one(i: int, scheduled: float) -> None:
        sent = clock() - t0
        try:
            status, headers = send(i)
        except Exception as e:  # noqa: BLE001 -- every failure is data, kept per request
            results[i] = Outcome(i, scheduled, sent, None, None, {}, f"{type(e).__name__}: {e}"[:300])
            return
        results[i] = Outcome(i, scheduled, sent, clock() - t0 - sent, status, dict(headers))

    with ThreadPoolExecutor(max_workers=max_in_flight) as pool:
        for i, scheduled in enumerate(times):
            wait = t0 + scheduled - clock()
            if wait > 0:
                sleep(wait)
            pool.submit(one, i, scheduled)
    return [r for r in results if r is not None]


def http_sender(url: str, *, payload: dict, headers: dict, timeout: float,
                keep_headers: Sequence[str] = (), session_factory=requests.Session):
    """A `send(i)` that POSTs `payload` to `url`, one keep-alive session per thread."""
    local = threading.local()
    keep = tuple(h.lower() for h in keep_headers)

    def send(i: int) -> tuple[int, dict]:
        session = getattr(local, "session", None)
        if session is None:
            session = local.session = session_factory()
        r = session.post(url, json=payload, headers=headers, timeout=timeout)
        got = {k.lower(): v for k, v in r.headers.items()}
        return r.status_code, {h: got[h] for h in keep if h in got}

    return send
