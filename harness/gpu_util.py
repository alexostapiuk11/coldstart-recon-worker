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

Why the median: one run's samples include the ramp at its start and the
drain at its end. The median is the steady middle; a mean would be pulled by
the edges, and artifact 1's rule is that a mean is never published for skewed
data.
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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def command(self) -> list[str]:
        return list(self._cmd)

    def sample_once(self) -> dict:
        t = self._clock() - self._t0
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
        sample = {"t_s": t, "raw": raw, "util_pct": util}
        if error is not None:
            sample["error"] = error
        self.samples.append(sample)
        return sample

    def _loop(self) -> None:
        while True:
            self.sample_once()
            if self._stop.wait(self.interval):
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
            self._thread.join(timeout=self.interval + QUERY_TIMEOUT_S + 1.0)

    def median_fraction(self) -> float | None:
        """Median of the readable samples, as a fraction; None if there are none."""
        values = [s["util_pct"] for s in self.samples if s["util_pct"] is not None]
        if not values:
            return None
        return median(values) / 100.0

    def summary(self) -> dict:
        return {
            "gpu_util": self.median_fraction(),
            "interval_s": self.interval,
            "n_samples": len(self.samples),
            "n_valid": sum(1 for s in self.samples if s["util_pct"] is not None),
            "samples": list(self.samples),
        }
