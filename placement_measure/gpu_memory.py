"""GPU memory readings, and the wait until a stopped engine's memory is free.

`harness.serve.Server.stop()` returns when the `vllm serve` parent has exited,
and says explicitly that it does not measure memory release: the driver frees
a dead process's memory shortly after, and how shortly is part of what a swap
costs (amendment §5). This module measures that part. It reads `memory.used`,
not `utilization.gpu`: artifact 2's pilot found utilisation reads 100% at any
load, and it says nothing about whether the card has room for the next engine.

A failed query is data, as in `harness.gpu_util`: an unreadable card is a
sample with `used_mib` None and an `error`, never an invented number.
"""

import subprocess
import time
from collections.abc import Callable

__all__ = ["QUERY", "read_memory", "wait_for_release"]

QUERY = ("nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits")
QUERY_TIMEOUT_S = 5.0


def read_memory(*, gpu_index: int = 0, run: Callable = subprocess.run) -> dict:
    cmd = [*QUERY, f"--id={gpu_index}"]
    try:
        proc = run(cmd, capture_output=True, text=True, check=False, timeout=QUERY_TIMEOUT_S)
        raw = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return {"used_mib": None, "total_mib": None, "raw": raw,
                    "error": f"exit {proc.returncode}: {(proc.stderr or '').strip()[:200]}"}
        used, total = (float(part) for part in raw.split(","))
    except Exception as e:  # noqa: BLE001 -- an unreadable card is a sample, not a crash
        return {"used_mib": None, "total_mib": None, "raw": locals().get("raw", ""),
                "error": repr(e)[:200]}
    return {"used_mib": used, "total_mib": total, "raw": raw, "error": None}


def wait_for_release(
    target_used_mib: float,
    *,
    timeout_s: float,
    poll_s: float = 0.25,
    gpu_index: int = 0,
    run: Callable = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll until `memory.used` is at or below `target_used_mib`.

    The caller sets the target from a reading taken before the engine started
    plus a tolerance, because the card's idle usage is not zero and differs
    between hosts. Returns `released`, the `seconds` from the call to the first
    reading at or below target (or to the timeout), and every sample. A timeout
    is `released: False`, not an exception: the swap's record keeps it and the
    analysis decides, rather than the job dying with nothing stored.
    """
    t0 = clock()
    samples = []
    while True:
        reading = read_memory(gpu_index=gpu_index, run=run)
        now = clock() - t0
        samples.append({"t_s": now, **reading})
        used = reading["used_mib"]
        if used is not None and used <= target_used_mib:
            return {"released": True, "seconds": now, "target_used_mib": target_used_mib,
                    "samples": samples}
        if now >= timeout_s:
            return {"released": False, "seconds": now, "target_used_mib": target_used_mib,
                    "samples": samples}
        sleep(poll_s)
