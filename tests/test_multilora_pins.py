"""The measurement endpoint's pin set: artifact 1's five fields, with the
platform's own cache off and no warm worker kept, and the GPU the
pre-registration names. Written by scripts/a5_pins.py from the live endpoint."""

from pathlib import Path

from multilora.cli import PIN_KEYS
from multilora.pins import PINNED

REPO = Path(__file__).resolve().parents[1]


def test_the_pin_set_is_the_five_fields_with_the_platform_cache_off():
    assert sorted(PINNED) == sorted(PIN_KEYS)
    assert PINNED["flashboot"] is False
    assert PINNED["workersMin"] == 0


def test_the_pinned_gpu_is_the_one_the_preregistration_names():
    # The pre-registration wraps the GPU name across a line and must not be edited.
    doc = " ".join((REPO / "docs" / "experiment-a5.md").read_text().split())
    assert all(gpu in doc for gpu in PINNED["gpuTypeIds"])
