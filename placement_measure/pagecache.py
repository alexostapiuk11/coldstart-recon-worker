"""Whether a swap-in's weights are read from storage or from the host's page cache.

A twenty-model fleet's weights do not fit in host memory, and a three-model
validation set's do (amendment §5). Measured with the cache warm, swaps would
look faster than the simulated fleet's. So every swap records the cache state
it ran in, and can ask for the weights to be evicted first.

Two eviction methods, tried in order, each recorded:

- `drop_caches`: write "3" to /proc/sys/vm/drop_caches after a sync. Needs
  root and a writable /proc/sys, which a container may not have.
- `fadvise`: `posix_fadvise(POSIX_FADV_DONTNEED)` on every weight file. Needs
  no privilege, but whether it evicts pages of a file on RunPod's network
  volume is UNVERIFIED; reconnaissance reads `Cached:` from /proc/meminfo
  before and after to see.

Neither is assumed to work. The answer is a reconnaissance result.
"""

import contextlib
import os
from collections.abc import Callable
from pathlib import Path

__all__ = ["cached_kib", "make_cold", "weight_files"]

MEMINFO = "/proc/meminfo"
DROP_CACHES = "/proc/sys/vm/drop_caches"
# Linux only; None elsewhere (the macOS test host), where fadvise is reported
# as unavailable rather than faked.
POSIX_FADVISE = getattr(os, "posix_fadvise", None)


def cached_kib(path: str = MEMINFO) -> int | None:
    """The kernel's `Cached:` figure, in KiB; None if it cannot be read."""
    try:
        for line in Path(path).read_text().splitlines():
            if line.startswith("Cached:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def weight_files(hf_home: str, model: str, revision: str) -> list[str]:
    """The checkpoint's safetensors files in the Hugging Face cache, resolved.

    The cache stores a snapshot as symlinks into `blobs/`; the page cache holds
    the blobs, so those are what get evicted.
    """
    org, name = model.split("/", 1)
    snapshot = Path(hf_home) / "hub" / f"models--{org}--{name}" / "snapshots" / revision
    return sorted(str(p.resolve()) for p in snapshot.glob("*.safetensors"))


def _drop_all(drop_path: str, sync: Callable[[], None]) -> dict:
    try:
        sync()
        Path(drop_path).write_text("3\n")
    except OSError as e:
        return {"method": "drop_caches", "ok": False, "error": repr(e)[:200]}
    return {"method": "drop_caches", "ok": True, "error": None}


def _fadvise_all(paths, fadvise: Callable | None) -> dict:
    if fadvise is None:
        return {"method": "fadvise", "ok": False, "error": "os.posix_fadvise is unavailable",
                "files": 0}
    errors = []
    for path in paths:
        fd = None
        try:
            fd = os.open(path, os.O_RDONLY)
            fadvise(fd, 0, 0, getattr(os, "POSIX_FADV_DONTNEED", 4))
        except OSError as e:
            errors.append(f"{path}: {e!r}"[:200])
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
    return {"method": "fadvise", "ok": not errors and bool(paths), "errors": errors,
            "files": len(paths)}


def make_cold(
    paths,
    *,
    meminfo: str = MEMINFO,
    drop_path: str = DROP_CACHES,
    sync: Callable[[], None] = os.sync,
    fadvise: Callable | None = POSIX_FADVISE,
) -> dict:
    """Try both evictions and record what the kernel's cache did.

    `cached_kib_before` and `cached_kib_after` are the evidence: a method can
    report success and evict nothing, which is exactly the network-volume case
    that is unverified.
    """
    paths = list(paths)
    before = cached_kib(meminfo)
    attempts = [_drop_all(drop_path, sync), _fadvise_all(paths, fadvise)]
    after = cached_kib(meminfo)
    return {
        "requested": True,
        "files": paths,
        "attempts": attempts,
        "cached_kib_before": before,
        "cached_kib_after": after,
    }
