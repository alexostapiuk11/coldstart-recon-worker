"""Artifact 3's test helpers: the synthetic suite, re-exported. NOT DATA."""

from toolcall.scenarios import scenario_from_dict
from toolcall.stub_suite import (  # noqa: F401
    FLIGHT,
    MISC,
    RECOVERY,
    SMALLTALK,
    TRAVEL,
    library,
    scenarios,
    synthetic_suite,
    write_suite,
)


def scenario(d=FLIGHT):
    return scenario_from_dict(d, library())


def example_prereg(**overrides):
    """Values for tests only. The real ones live in toolcall/prereg_values.py."""
    from toolcall.prereg import Preregistration
    from toolcall.providers import ModelSettings

    values = {
        "primary": ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0,
                                 reasoning_effort="none"),
        "slice_models": (
            ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0, reasoning_effort="none"),
            ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools"),
        ),
        "baseline_cell": "low-terse-loose",
        "band": (0.10, 0.90),
        "pilot_reps": 10,
        "pilot_cost_scenarios": 10,
        "pilot_cost_reps": 5,
        "delta2": 0.02,
        "identical_retry_floor": 0.05,
        "n_floor": 5,
        "n_cap": 20,
        "s_floor": 24,
        "alpha": 0.05,
        "iterations": 300,
        "bootstrap_seed": 7,
        "schedule_seed": 11,
        "retry_cap": 3,
        "turn_budget": 3,
        "normalizer_version": 1,
    }
    values.update(overrides)
    return Preregistration(**values)
