"""docs/experiment-a2.md's 2026-10-04 amendment states what the code runs."""

import re
from pathlib import Path

from autoscale import validation_schedule as vs
from autoscale.measured_curve import IDLE_CONCURRENCY
from autoscale.thresholds import SENSITIVITY_THRESHOLDS

DOC = (Path(__file__).resolve().parents[1] / "docs" / "experiment-a2.md").read_text()
SECTION = DOC.split("## Amendment, 2026-10-04: the measured curve and the validation operating point", 1)


def _section() -> str:
    assert len(SECTION) == 2, "the 2026-10-04 amendment is missing"
    return SECTION[1].split("\n## ", 1)[0]


def test_the_operating_point_matches_the_constants():
    s = _section()
    assert f"**{vs.VALIDATION_REPLICAS} replicas**" in s
    assert f"until **{vs.VALIDATION_UNTIL:g} s**" in s
    assert f"drain **{vs.VALIDATION_DRAIN_SECONDS:g} s**" in s
    assert f"seed **{vs.VALIDATION_SEED}**" in s
    assert "**server-side latency**" in s
    assert f"**{vs.WARMUP_RPS:g} req/s**" in s


def test_the_absolute_rates_are_stated():
    s = _section()
    for label in ("saturation", "baseline", "peak"):
        assert re.search(rf"{label}[^\n]*\*\*\d+\.\d req/s\*\*", s), label


def test_the_idle_point_and_the_sensitivity_signal_are_stated():
    s = _section()
    assert f"concurrency {IDLE_CONCURRENCY:g}" in s and "0%" in s
    assert "`utilization_throughput`" in s
    up, down = SENSITIVITY_THRESHOLDS["utilization_throughput"]
    assert ", ".join(f"{v:g}" for v in up) in s
    assert ", ".join(f"{v:g}" for v in down) in s


def test_the_void_run_and_probe_rules_are_stated():
    s = _section()
    assert "void" in s and "non-200" in s
    assert "P1" in s and "P8" in s
