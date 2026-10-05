"""The exploratory service-speed check changes the engine and nothing else."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_sensitivity_service_speed as sens

from autoscale.measured_curve import DEFAULT_PATH, load_measured_curve
from autoscale.traffic import spike_shape


def test_the_traffic_stays_the_committed_curves_and_only_the_service_is_scaled():
    committed = load_measured_curve(REPO / DEFAULT_PATH).curve
    for factor in sens.FACTORS:
        for tag, shape, service, arm, label in sens.configs(committed, factor):
            kind = "ramp" if tag.startswith("ramp") else "step"
            assert shape == spike_shape(committed, kind=kind)
            assert service.latency_at(128) == pytest.approx(committed.latency_at(128) * factor)
            assert service.latency_at(1) == pytest.approx(committed.latency_at(1) * factor)
            assert service.measured is True


def test_it_runs_the_four_headline_sweeps_at_both_factors():
    assert sens.FACTORS == (0.88, 1.12)
    assert [t for t, *_ in sens.HEADLINE] == ["arm A", "arm C", "ramp arm A", "ramp arm C"]
