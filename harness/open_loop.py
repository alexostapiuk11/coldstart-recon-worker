"""Open-loop HTTP replay: send each request at its scheduled time, whatever the server does.

Open loop means the schedule, not the server, decides when each request
leaves: a slow response never delays the next send. That is what makes a
real run comparable to the simulator fed the same arrival times; a closed
loop (`vllm bench serve --max-concurrency`) lets the server's speed shape the
arrivals and confounds the two.

One dispatcher thread sleeps until each scheduled time and hands the request
to a pool. Each worker thread stamps `sent` immediately before the request
leaves, so if the pool is exhausted, the delay shows as send jitter, which the
caller checks (`max_jitter`; artifact 2's gate refuses a run above 0.5 s; the LB probe's own acceptance bar is 0.25 s). It
is not hidden inside a latency. Every request yields an `Outcome`: a failure
is an outcome with an error, never a missing row, because a dropped row
would shrink exactly the bins where the server was struggling.

Times are seconds on `clock` relative to t0, the moment the schedule's zero
is placed (`start_delay` after the call, so the pool is up before the first
send).

Rejected alternatives:
- asyncio + aiohttp: a new dependency for a driver that a bounded thread pool
  already serves at the validation peak.
- `vllm bench serve --request-rate`: it draws its own Poisson stream and cannot
  replay a fixed schedule.
- one thread per request: the thread count is then unbounded, so a slow server
  would exhaust the driver's memory instead of showing as send jitter. A bounded
  pool turns the same overload into a number the gate can refuse.
"""

import math
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
    """One request's fate. Every time is seconds on the replay clock relative to t0.

    `scheduled` is the schedule's time, `dispatched` is when the dispatcher
    handed the request to the pool, `sent` is when a worker thread was about
    to send it, and `latency` is `sent` to the response fully read (headers and
    body). A jitter failure splits into dispatcher lateness (`dispatched -
    scheduled`) and pool pickup (`sent - dispatched`). `dispatched` is last and
    defaulted so a caller building an Outcome by hand need not know it. A
    failed request has `status` and `latency` None and its reason in `error`.
    """

    index: int
    scheduled: float
    sent: float | None
    latency: float | None
    status: int | None
    headers: dict = field(default_factory=dict)
    error: str | None = None
    dispatched: float | None = None


def max_jitter(outcomes: Sequence[Outcome]) -> float:
    return max((abs(o.sent - o.scheduled) for o in outcomes if o.sent is not None), default=0.0)


def replay(schedule: Sequence[float], send: Callable[[int], tuple[int, dict]], *,
           max_in_flight: int = 1024, start_delay: float = 0.5,
           clock=time.monotonic, sleep=time.sleep) -> list[Outcome]:
    """Send request i at `schedule[i]` seconds after t0; return one Outcome per entry, in order.

    `max_in_flight` caps the pool, so size it as peak rate x worst-case latency.
    The default 1024 covers about 450 req/s up to roughly 2.3 s of latency. A
    pool that is too small does not fail: the requests queue and each leaves
    late, which shows as send jitter, and the gate refuses a run above 0.5 s.

    If the dispatcher is interrupted (Ctrl-C, or any BaseException) the queued
    requests are cancelled and the exception re-raised at once, so the
    caller's cleanup (releasing pinned workers) is not held up behind a backlog.
    Requests already in flight cannot be cancelled; they finish within the
    sender's timeout, and their rows are lost with the exception. Waiting for
    the whole queue instead (the `with ThreadPoolExecutor` default) was
    rejected: it blocked an interrupt for minutes.
    """
    times = list(schedule)
    if not all(math.isfinite(t) for t in times):
        raise ValueError(
            "the schedule has a NaN or infinite time; it compares false against every "
            "ordering check, so replay would sleep on it or send it at a meaningless moment"
        )
    if any(t < 0 for t in times):
        raise ValueError("the schedule has a negative time; t=0 is the schedule's start")
    if any(b < a for a, b in pairwise(times)):
        raise ValueError(
            "the schedule is not ascending; replay sends in list order, so an out-of-order "
            "entry would be sent late and recorded as jitter the driver caused"
        )
    if max_in_flight < 1:
        raise ValueError(
            f"max_in_flight is {max_in_flight}; a pool needs at least one worker, "
            "and with none no request would ever be sent"
        )
    t0 = clock() + start_delay
    results: list[Outcome | None] = [None] * len(times)

    def one(i: int, scheduled: float, dispatched: float) -> None:
        sent = clock() - t0
        try:
            status, headers = send(i)
            results[i] = Outcome(i, scheduled, sent, clock() - t0 - sent, status,
                                 dict(headers), None, dispatched)
        except BaseException as e:  # noqa: BLE001 -- a row must never vanish, whatever was raised
            results[i] = Outcome(i, scheduled, sent, None, None, {},
                                 f"{type(e).__name__}: {e}"[:300], dispatched)

    pool = ThreadPoolExecutor(max_workers=max_in_flight)
    try:
        for i, scheduled in enumerate(times):
            wait = t0 + scheduled - clock()
            if wait > 0:
                sleep(wait)
            pool.submit(one, i, scheduled, clock() - t0)
        # Inside the try: an interrupt during the final drain (everything dispatched, the
        # pool still saturated) must cancel the queued requests too, or they keep going out.
        pool.shutdown(wait=True)
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    missing = sum(r is None for r in results)
    if missing:
        raise RuntimeError(
            f"{missing} of {len(times)} requests left no outcome row; keeping the rest would "
            "return a short run that silently shrinks exactly the bins where the server struggled"
        )
    return results  # type: ignore[return-value]  # no None remains, checked above


def http_sender(url: str, *, payload: dict, headers: dict, timeout: float,
                keep_headers: Sequence[str] = (), session_factory=requests.Session):
    """A `send(i)` that POSTs `payload` to `url`, one keep-alive session per thread.

    A `requests.Session` is not documented as thread-safe, and one shared
    session would also serialise on its connection pool; a session per thread
    keeps each connection alive across that thread's requests. Returns the
    status and only the response headers named in `keep_headers` (lower-cased).
    """
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
