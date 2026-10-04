"""run_sweep runs the headline signals by default and any named set on request."""

import pytest

from autoscale import sweep
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.service import ServiceCurve

CURVE = ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (8, 0.5, 300.0, 1.0)],
                     measured=True)


def _config():
    return sweep.SweepConfig(
        shape=SpikeShape(kind="step", baseline_rate=5.0, k=2.0, ramp=0.0, sustain=20.0),
        lags=LagDistribution(samples=[2.0]), curve=CURVE, arm="test", until=60.0,
    )


@pytest.fixture(autouse=True)
def _few_reps(monkeypatch):
    monkeypatch.setattr(sweep, "REPETITIONS", 1)


def test_default_signals_are_the_headline_three():
    points, discards = sweep.run_sweep(_config(), seed=1)
    seen = {p.signal for p in points} | {d.partition(":")[0] for d in discards}
    assert seen <= {"queue_depth", "in_flight_concurrency", "utilization"}
    assert "utilization_throughput" not in seen


def test_named_signals_are_run_and_nothing_else():
    points, discards = sweep.run_sweep(_config(), seed=1, signals=("utilization_throughput",))
    seen = {p.signal for p in points} | {d.partition(":")[0] for d in discards}
    assert seen == {"utilization_throughput"}


def test_an_unknown_signal_is_refused_before_anything_runs():
    with pytest.raises(KeyError, match="no_such_signal"):
        sweep.run_sweep(_config(), seed=1, signals=("no_such_signal",))
