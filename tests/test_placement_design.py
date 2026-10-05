import pytest

from placement.design import Design
from placement.placeholders import (
    PLACEHOLDER_DESIGN,
    PLACEHOLDER_ENGINES,
    PLACEHOLDER_SWAP_TIME,
)

VALID = {
    "n_models": 20, "offered_gpus": 4.0, "hot_fraction": 0.7, "warmup": 120.0,
    "mean_burst": 30.0, "duty": 0.2, "skews": (0.6, 1.0), "regimes": ("spread",),
    "repetitions": 30, "slo_seconds": 4.0, "pilot_traces": 1200, "seed": 1,
    "preregistered": True,
}


def test_a_valid_design_constructs():
    assert Design(**VALID).skews == (0.6, 1.0)


@pytest.mark.parametrize(
    "change",
    [
        {"skews": (1.0, 0.6)},
        {"skews": (0.6, 0.6)},
        {"regimes": ()},
        {"regimes": ("spiky",)},
        {"slo_seconds": 0.0},
        {"slo_seconds": float("nan")},
    ],
)
def test_a_design_that_would_misplace_the_crossover_is_refused(change):
    with pytest.raises(ValueError):
        Design(**{**VALID, **change})


def test_every_placeholder_says_it_is_one():
    """The sweep's refusal rests on these flags. A placeholder flagged as
    measured would produce a result indistinguishable from a real one."""
    assert not PLACEHOLDER_ENGINES.solo.measured
    assert not PLACEHOLDER_ENGINES.colocated.measured
    assert not PLACEHOLDER_ENGINES.measured
    assert not PLACEHOLDER_SWAP_TIME.measured
    assert not PLACEHOLDER_DESIGN.preregistered
