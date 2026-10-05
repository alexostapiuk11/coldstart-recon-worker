"""The engine's own count of requests in flight, from its Prometheus endpoint.

A co-located measurement is only valid if the neighbour engine was carrying
its load for the whole measured run. The neighbour's bench client cannot say
so: it reports what it sent, not what the engine was running at each instant.
vLLM 0.27.1 exports `vllm:num_requests_running` on `/metrics`
(vllm/v1/metrics/loggers.py at the v0.27.1 tag), so the measured run samples
it on the neighbour and keeps the samples.
"""

import threading
import time
from collections.abc import Callable
from typing import Self

import requests

__all__ = ["RUNNING_METRIC", "RunningSampler", "read_running", "running_from_text", "wait_running"]

RUNNING_METRIC = "vllm:num_requests_running"
REQUEST_TIMEOUT_S = 2.0


def running_from_text(text: str) -> float | None:
    """Sum of every `vllm:num_requests_running` series; None if there is none.

    Summed over label sets because one engine can export one series per
    engine core; a single series is the case seen on one GPU.
    """
    values = []
    for line in text.splitlines():
        if line.startswith(RUNNING_METRIC) and not line.startswith("#"):
            name = line.split("{", 1)[0].split(" ", 1)[0]
            if name == RUNNING_METRIC:
                values.append(float(line.rsplit(" ", 1)[1]))
    return sum(values) if values else None


def read_running(base_url: str, *, get: Callable = requests.get) -> dict:
    try:
        r = get(f"{base_url}/metrics", timeout=REQUEST_TIMEOUT_S)
        r.raise_for_status()
        return {"running": running_from_text(r.text), "error": None}
    except Exception as e:  # noqa: BLE001 -- an unreadable endpoint is a sample, not a crash
        return {"running": None, "error": repr(e)[:200]}


def wait_running(
    base_url: str,
    *,
    at_least: float,
    timeout_s: float,
    poll_s: float = 0.25,
    get: Callable = requests.get,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Wait until the engine runs `at_least` requests, so the measured run
    starts under the neighbour's full load rather than its ramp-up."""
    t0 = clock()
    last = None
    while True:
        last = read_running(base_url, get=get)
        elapsed = clock() - t0
        if last["running"] is not None and last["running"] >= at_least:
            return {"reached": True, "seconds": elapsed, "last": last}
        if elapsed >= timeout_s:
            return {"reached": False, "seconds": elapsed, "last": last}
        sleep(poll_s)


class RunningSampler:
    """Samples `vllm:num_requests_running` on a background thread while in a `with`."""

    def __init__(
        self,
        base_url: str,
        interval: float = 0.5,
        *,
        get: Callable = requests.get,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.base_url = base_url
        self.interval = interval
        self.samples: list[dict] = []
        self._get = get
        self._clock = clock
        self._t0 = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        k = 0
        while True:
            started = self._clock()
            self.samples.append({"t_s": started - self._t0, **read_running(self.base_url, get=self._get)})
            k += 1
            if self._stop.wait(max(0.0, self._t0 + k * self.interval - self._clock())):
                return

    def __enter__(self) -> Self:
        self._t0 = self._clock()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + REQUEST_TIMEOUT_S + 1.0)

    def values(self) -> list[float]:
        return [s["running"] for s in self.samples if s["running"] is not None]
