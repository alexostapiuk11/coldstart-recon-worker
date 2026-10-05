"""Engine facts read from one instance's startup log.

KV capacity, version and model come from the harness parser unchanged. Two
facts are added for artifact 5:

- Whether the torch.compile cache was warm (amendment §3d). The compile cache
  is keyed on `max_loras`, so each sweep point has its own directory under one
  root, and a directory-exists check would read warm for every point after the
  first priming run. The log is per instance and cannot be fooled that way.
- The cache directory the engine used, which carries the configuration hash,
  recorded so a surprising instance can be traced to the cache it hit.
"""

import re

from harness.vllm_logs import parse_engine_log

# Artifact 1's priming criterion (docs/experiment.md): a warm compile cache
# brings `torch.compile took ... s in total` under one second. Its committed
# logs show 38.96 s cold and 0.29-0.30 s warm.
WARM_S4B_MAX_SECONDS = 1.0

_CACHE_DIR = re.compile(r"Using cache directory: (?P<path>\S+)")


def compile_state(s4b_seconds: float | None) -> str:
    if s4b_seconds is None:
        return "unknown"
    return "warm" if s4b_seconds < WARM_S4B_MAX_SECONDS else "cold"


def engine_facts(log_lines: list[str]) -> dict:
    text = "\n".join(log_lines)
    parsed = parse_engine_log(text)
    s4b = parsed.phases.get("S4b")
    m = _CACHE_DIR.search(text)
    return {
        **parsed.engine_info,
        "s4b_seconds": s4b,
        "compile_state": compile_state(s4b),
        "cache_dir": m.group("path") if m else None,
    }
