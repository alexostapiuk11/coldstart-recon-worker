"""Samples vLLM's LoRA gauge on a fixed interval while load runs (amendment §3a).

A background thread scrapes `/metrics` every `interval` seconds and records the
running adapter set against whichever phase the caller says is current. The
caller owns phase boundaries; the sampler never guesses them. A scrape that
fails is recorded as `running: None` rather than skipped, so a gap in the
manipulation check is visible in the record.
"""

import threading
import time
from collections.abc import Callable
from typing import Self

from multilora.gauge import running_adapters


class GaugeSampler:
    def __init__(
        self,
        fetch_metrics: Callable[[], str],
        interval: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        if interval <= 0:
            raise ValueError(f"interval must be positive, got {interval}")
        self._fetch = fetch_metrics
        self._interval = interval
        self._clock = clock
        self._phase: int | None = None
        self._samples: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_phase(self, phase_index: int | None) -> None:
        """`None` between phases: nothing is recorded while no phase runs."""
        with self._lock:
            self._phase = phase_index

    def sample_once(self) -> None:
        with self._lock:
            phase = self._phase
        if phase is None:
            return
        try:
            running = running_adapters(self._fetch())
        except Exception:  # noqa: BLE001 -- a failed scrape is a recorded gap
            running = None
        with self._lock:
            self._samples.append({"phase_index": phase, "t": self._clock(), "running": running})

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            self.sample_once()

    def __enter__(self) -> Self:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5 * self._interval + 5)

    @property
    def samples(self) -> list[dict]:
        with self._lock:
            return list(self._samples)
