"""Which curve the artifact-2 scripts run on, and that a cache cannot cross curves."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_gap_noise_floor as noise
import a2_regime_probe as probe
import a2_render_figures as render

from autoscale.frontier import PolicyPoint
from autoscale.service import SERVICE_CURVE_PLACEHOLDER


def _pp(signal):
    return PolicyPoint(cost_samples=(1.0,), p99_samples=(1.0,), signal=signal,
                       scale_up_at=1.0, scale_down_at=0.0, rep_indices=(0,))


def test_by_signal_orders_keys_by_signal_order_then_name():
    points = [_pp("utilization"), _pp("utilization_throughput"), _pp("queue_depth"),
              _pp("in_flight_concurrency")]
    assert list(render._by_signal(points)) == [
        "queue_depth", "in_flight_concurrency", "utilization", "utilization_throughput"]


def test_curve_label_names_the_measured_file_or_the_placeholder():
    assert render.curve_label(None) == "placeholder"
    assert render.curve_label(Path("data/a2/service-curve.json")) == "data/a2/service-curve.json"


def test_a_cache_from_the_other_curve_is_refused():
    with pytest.raises(SystemExit, match="placeholder"):
        render.check_cache_curve({"curve": "placeholder"}, "data/a2/service-curve.json")
    with pytest.raises(SystemExit, match="does not say"):
        render.check_cache_curve({}, "data/a2/service-curve.json")
    render.check_cache_curve({"curve": "placeholder"}, "placeholder")


def test_the_sweep_is_unmeasured_only_on_the_placeholder(monkeypatch):
    seen = {}

    def fake_run_sweep(config, seed, allow_unmeasured=False, signals=None):
        seen["allow"], seen["curve"], seen["signals"] = allow_unmeasured, config.curve, signals
        return [], []

    monkeypatch.setattr(render, "run_sweep", fake_run_sweep)
    from autoscale.coldstart_ecdf import LagDistribution
    from autoscale.traffic import spike_shape
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step")
    render._sweep("x", shape, LagDistribution([60.0]), "A", SERVICE_CURVE_PLACEHOLDER)
    assert seen["allow"] is True and seen["curve"] is SERVICE_CURVE_PLACEHOLDER
    assert seen["signals"] is None
    render._sweep("x", shape, LagDistribution([60.0]), "A", SERVICE_CURVE_PLACEHOLDER,
                  signals=("utilization_throughput",))
    assert seen["signals"] == ("utilization_throughput",)


@pytest.mark.parametrize("module", [render, noise, probe])
def test_curve_and_placeholder_flags_are_exclusive(module):
    with pytest.raises(SystemExit):
        module.parse_args(["--placeholder", "--curve", "x.json"])
    assert module.parse_args([]).placeholder is False
    assert module.parse_args(["--placeholder"]).placeholder is True
