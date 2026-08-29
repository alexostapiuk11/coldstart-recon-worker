"""Replays the real captured engine logs so the parser sees reality, not invention."""

from pathlib import Path

# Anchored to the repository, not the working directory: these tests and the
# driver both run from elsewhere, and a relative path would resolve differently
# depending on the caller.
_CAPTURES = Path(__file__).resolve().parents[2] / "fixtures" / "vllm_logs"

# The reconnaissance runs reused one worker, so the captures happen to contain
# both a cold compile (startup_0, torch.compile 38.96 s) and a warm one
# (startup_1, 0.30 s) under otherwise identical configuration. The stub replays
# whichever actually matches the arm rather than relabelling one log as both --
# arm C would otherwise be a cold capture wearing a warm arm's name, and no
# off-GPU test could tell the compile-cache saving from a mislabel.
COLD_COMPILE_CAPTURE = _CAPTURES / "startup_0.log"
WARM_COMPILE_CAPTURE = _CAPTURES / "startup_1.log"


def replay_log_lines(compile_warm: bool = False) -> list[str]:
    """Lines of the capture matching this arm's compile-cache state."""
    fixture = WARM_COMPILE_CAPTURE if compile_warm else COLD_COMPILE_CAPTURE
    if not fixture.exists():
        raise FileNotFoundError(
            f"{fixture} missing -- run recon/capture.py (Task 6) before using the stub"
        )
    return fixture.read_text().splitlines()
