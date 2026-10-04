"""GPU utilisation, sampled from nvidia-smi while a bench run is in flight.

Owner decision 3 (2026-10-04): `utilization.gpu` every 0.5 s in a background
thread for the duration of each run; per run, the median as a fraction 0-1;
the raw samples kept with the run.

Why nvidia-smi: it is already in the image (worker/handler.py reads the GPU
name with it) and needs no new dependency. NVML bindings (pynvml) were
rejected as a new package in an image whose pip state artifact 1 pinned, and
vLLM's `/metrics` exports KV-cache usage, which is a memory fraction, not
compute. `utilization.gpu` is the share of the sample period in which at
least one kernel ran. It saturates well before throughput does -- the
censoring artifact 2's H2 is about -- so it is reported as read and never
rescaled.

Why the median: a mean would be pulled by the ramp and the drain, and artifact
1's rule is that a mean is never published for skewed data. The median is NOT
a "steady middle" by itself, though. The sampler wraps the whole `vllm bench
serve` subprocess, and that process idles the GPU before its first request
(imports, tokenizer load, dataset sampling) and after its last (metrics, JSON
write); in a short run those idle samples are a large share of the total, and
the median slides down the busy distribution or becomes the idle value. So the
figure a run reports is the median of the samples taken between its first
successful request's start and its last one's end (`median_in_window`), with
the whole-call median kept beside it. The window comes from the tool's own
per-request times; see `harness.sweep_worker.run_summary`.
"""

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Self

from harness.stats import median

QUERY = ("nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits")
DEFAULT_INTERVAL_S = 0.5
QUERY_TIMEOUT_S = 5.0
# How far outside the sampler's lifetime a request span may lie before the two
# clocks are judged not to share an epoch. The tool runs entirely inside the
# `with` block, so any real span is inside it; a second absorbs rounding.
CLOCK_SLACK_S = 1.0


def _parse_percent(raw: str) -> tuple[float | None, str | None]:
    lines = raw.splitlines()
    if len(lines) != 1:
        return None, f"expected one line for one GPU, got {len(lines)}"
    try:
        value = float(lines[0])
    except ValueError:
        return None, f"not a number: {lines[0]!r}"
    if not 0.0 <= value <= 100.0:
        return None, f"outside 0-100: {value!r}"
    return value, None


class GpuUtilSampler:
    """Samples one GPU's utilisation on a background thread while in a `with`.

    The first sample is taken as the block is entered, so even a run shorter
    than one interval gets a reading. A query that fails, times out or prints
    something unparseable becomes a sample with `util_pct` None and an
    `error`, kept with the raw text: an unreadable GPU must never be the
    reason a measured run is thrown away, and a gap must never be filled with
    an invented number.
    """

    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL_S,
        *,
        gpu_index: int = 0,
        run: Callable = subprocess.run,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.interval = interval
        self.samples: list[dict] = []
        self._cmd = [*QUERY, f"--id={gpu_index}"]
        self._run = run
        self._clock = clock
        self._t0 = clock()
        self._t_exit_s: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def command(self) -> list[str]:
        """The exact nvidia-smi argument list, public so a diagnostic job can run
        the same query by hand and compare its output with what was sampled."""
        return list(self._cmd)

    def sample_once(self) -> dict:
        """One reading, appended to `samples` and returned.

        `t_s` is when the query started, counted from entry to the block, and
        `query_s` how long it took: nvidia-smi's own reading covers a window
        that ends somewhere inside that call, so a reader judging how far a
        sample can be trusted against a time boundary needs the duration, and
        a boundary closer than `query_s` is not resolved. Failure is data (see
        the class docstring), not an exception.
        """
        started = self._clock()
        try:
            proc = self._run(
                self._cmd, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_S
            )
            raw = (proc.stdout or "").strip()
            if proc.returncode == 0:
                util, error = _parse_percent(raw)
            else:
                util, error = None, f"exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"
        except Exception as e:  # noqa: BLE001 -- see the class docstring
            raw, util, error = "", None, repr(e)[:200]
        sample = {
            "t_s": started - self._t0,
            "query_s": self._clock() - started,
            "raw": raw,
            "util_pct": util,
        }
        if error is not None:
            sample["error"] = error
        self.samples.append(sample)
        return sample

    def _loop(self) -> None:
        # Waits for the next point of a grid at t0 + k * interval rather than a
        # fixed interval after each sample: nvidia-smi takes tens of
        # milliseconds, and a fixed gap would stretch the real period by that
        # much every time, so a long run would hold fewer samples than its
        # length promises. A query that overruns a grid point waits 0 (the
        # point is skipped over, not caught up).
        k = 0
        while True:
            self.sample_once()
            k += 1
            if self._stop.wait(max(0.0, self._t0 + k * self.interval - self._clock())):
                return

    def __enter__(self) -> Self:
        self._t0 = self._clock()
        self._t_exit_s = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + QUERY_TIMEOUT_S + 1.0)
        self._t_exit_s = self._clock() - self._t0

    @property
    def thread_stopped(self) -> bool:
        """False while the sampling thread is alive, including after an exit whose
        join timed out: such a sampler can still append to `samples`, so its
        summary is not final."""
        return self._thread is None or not self._thread.is_alive()

    def median_fraction(self) -> float | None:
        """Median of the readable samples, as a fraction; None if there are none."""
        values = [s["util_pct"] for s in self.samples if s["util_pct"] is not None]
        if not values:
            return None
        return median(values) / 100.0

    def summary(self) -> dict:
        """What a run keeps: the whole-call median, the raw samples, and what a
        reader needs to place them in time.

        `gpu_util` here is the median over EVERY sample, the idle tool startup
        and teardown included; `harness.sweep_worker.run_summary` derives the
        figure a run reports from `samples`. `t0_monotonic` is the clock reading
        at entry on the sampler's own clock (`time.monotonic`), the zero of every
        sample's `t_s`, so the samples can be compared with times the bench
        tool recorded in another process; `t_exit_s` is when the block ended.
        `thread_stopped` False means the join timed out.
        """
        return {
            "gpu_util": self.median_fraction(),
            "t0_monotonic": self._t0,
            "t_exit_s": self._t_exit_s,
            "thread_stopped": self.thread_stopped,
            "interval_s": self.interval,
            "n_samples": len(self.samples),
            "n_valid": sum(1 for s in self.samples if s["util_pct"] is not None),
            "samples": list(self.samples),
        }


def median_in_window(gpu: dict, start: float, end: float) -> dict:
    """Median utilisation, as a fraction, of the samples taken in [start, end].

    `gpu` is a `GpuUtilSampler.summary()`; `start` and `end` are readings of
    the sampler's own clock (`time.monotonic`), which is how the bench tool's
    per-request times are compared with it: on Linux CPython's `monotonic` and
    `perf_counter` both read CLOCK_MONOTONIC, one system-wide clock. That is
    not something this code can check across processes, so it checks what it
    can: a span that lies outside the sampler's whole lifetime cannot be on
    the same clock, and raises rather than guess.

    A sample belongs to the span by the time its query started, so a sample
    within `query_s` of an edge can be on either side of the true boundary.
    Returns the median (None if no readable sample is inside; never the
    whole-call value, which is the idle-diluted figure this exists to avoid),
    and the counts of readable samples inside and outside the span.
    """
    if "t0_monotonic" not in gpu:
        raise ValueError(
            "the GPU summary has no t0_monotonic, so its samples cannot be placed on the "
            "bench tool's clock; a median over a guessed window would be worse than none"
        )
    t0, t_exit = gpu["t0_monotonic"], gpu.get("t_exit_s")
    if start < t0 - CLOCK_SLACK_S or (t_exit is not None and end > t0 + t_exit + CLOCK_SLACK_S):
        raise ValueError(
            f"the requests ran over [{start}, {end}] but the sampler ran over "
            f"[{t0}, {None if t_exit is None else t0 + t_exit}]; a span outside the "
            "sampler's lifetime means the two processes' clocks do not share an epoch, "
            "and picking samples by time would pick the wrong ones"
        )
    readable = [s for s in gpu["samples"] if s["util_pct"] is not None]
    inside = [s["util_pct"] for s in readable if start <= t0 + s["t_s"] <= end]
    return {
        "gpu_util": median(inside) / 100.0 if inside else None,
        "n_in_span": len(inside),
        "n_outside_span": len(readable) - len(inside),
    }
