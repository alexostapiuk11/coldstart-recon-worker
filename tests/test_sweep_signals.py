"""run_sweep runs the headline signals by default and any named set on request."""

import pytest

from autoscale import sweep
from autoscale.arrivals import SpikeShape
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.service import ServiceCurve
from autoscale.signals import SENSITIVITY_SIGNALS, SIGNALS
from autoscale.thresholds import SENSITIVITY_THRESHOLDS, THRESHOLDS

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
    # Equality, not a subset: a sweep that ran nothing would satisfy `<=`.
    assert seen == {"queue_depth", "in_flight_concurrency", "utilization"}


def test_named_signals_are_run_and_nothing_else():
    points, discards = sweep.run_sweep(_config(), seed=1, signals=("utilization_throughput",))
    seen = {p.signal for p in points} | {d.partition(":")[0] for d in discards}
    assert seen == {"utilization_throughput"}


def test_an_unknown_signal_is_refused_before_anything_runs(monkeypatch):
    calls = []
    real = sweep.run_with_policy
    monkeypatch.setattr(sweep, "run_with_policy", lambda *a, **k: calls.append(1) or real(*a, **k))
    # A valid name first: a check done per signal inside the loop would run it.
    with pytest.raises(KeyError, match="no_such_signal"):
        sweep.run_sweep(_config(), seed=1, signals=("utilization_throughput", "no_such_signal"))
    assert calls == []


def test_a_signal_with_no_grid_is_refused_and_says_so(monkeypatch):
    monkeypatch.setattr(sweep, "SENSITIVITY_THRESHOLDS", {})
    with pytest.raises(KeyError, match="no threshold grid"):
        sweep.run_sweep(_config(), seed=1, signals=("utilization_throughput",))


def test_an_empty_signal_list_is_refused():
    with pytest.raises(ValueError, match="empty"):
        sweep.run_sweep(_config(), seed=1, signals=())


def test_a_duplicated_signal_is_refused():
    with pytest.raises(ValueError, match="more than once"):
        sweep.run_sweep(_config(), seed=1, signals=("utilization", "utilization"))


def test_a_bare_string_is_refused_rather_than_split_into_characters():
    with pytest.raises(ValueError, match="bare string"):
        sweep.run_sweep(_config(), seed=1, signals="utilization")


def test_the_sensitivity_registries_cannot_replace_a_pre_registered_one():
    """`run_sweep` merges the two grid dicts; a shared key would let the
    sensitivity grid silently overwrite a pre-registered one."""
    assert set(SIGNALS).isdisjoint(SENSITIVITY_SIGNALS)
    assert set(THRESHOLDS).isdisjoint(SENSITIVITY_THRESHOLDS)
