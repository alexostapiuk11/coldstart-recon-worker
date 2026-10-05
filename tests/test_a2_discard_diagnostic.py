"""The discard diagnostic replays the sweep run for run."""

import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_discard_diagnostic as diag

from autoscale import sweep
from autoscale.coldstart_ecdf import LagDistribution
from autoscale.controller import Decision
from autoscale.service import SERVICE_CURVE_PLACEHOLDER, ServiceCurve
from autoscale.traffic import spike_shape


@pytest.fixture
def short_sweep(monkeypatch):
    monkeypatch.setattr(sweep, "REPETITIONS", 3)
    # 0.25 additional replicas, the regime this was tuned at: the parity check
    # needs both kept and discarded runs, and the amended default (0.5) keeps
    # every run of this short sweep.
    shape = spike_shape(SERVICE_CURVE_PLACEHOLDER, "step", additional_replicas=0.25)
    return shape, LagDistribution([45.0, 90.0, 200.0])


def test_the_replay_matches_run_sweep_run_for_run(short_sweep):
    shape, lags = short_sweep
    signals = ("in_flight_concurrency", "queue_depth", "utilization")
    points, discards = sweep.run_sweep(
        sweep.SweepConfig(shape=shape, lags=lags, curve=SERVICE_CURVE_PLACEHOLDER, arm="A",
                          until=diag.UNTIL),
        seed=diag.SEED, allow_unmeasured=True, signals=signals)
    rows = diag.replay(shape, lags, SERVICE_CURVE_PLACEHOLDER, signals)

    assert len(rows) == 3 * (19 + 17 + 19)
    assert Counter(f"{r['signal']}:{r['outcome']}" for r in rows if r["outcome"] != "kept") \
        == Counter(discards)
    assert diag.policy_points(rows) == points
    # Both outcomes occur, so the comparison above is not vacuous.
    assert discards and points


def test_the_recording_controller_decides_exactly_as_the_controller_does():
    ctl = diag.RecordingController(scale_up_at=4.0, scale_down_at=1.0, cooldown=30.0,
                                   max_replicas=3)
    assert ctl.decide(2.0, replicas=1, now=5.0) is Decision.HOLD
    assert ctl.decide(float("inf"), replicas=1, now=10.0) is Decision.UP
    assert ctl.decide(9.0, replicas=2, now=20.0) is Decision.HOLD  # cooldown
    assert ctl.decide(5.0, replicas=2, now=45.0) is Decision.UP
    assert ctl.first_cross_at == 10.0 and ctl.first_up_at == 10.0
    assert ctl.max_signal == 9.0  # +inf is not a load
    assert (ctl.evaluations, ctl.at_or_above_up) == (4, 3)


def test_summarize_counts_outcomes_per_policy():
    rows = [
        {"signal": "queue_depth", "up": 1.0, "down": 0.0, "rep": 0, "outcome": "kept",
         "scale_ups": 1, "first_up_at": 100.0, "max_signal": 3.0,
         "share_at_or_above_up": 0.5, "peak_serving": 2},
        {"signal": "queue_depth", "up": 1.0, "down": 0.0, "rep": 1,
         "outcome": "replica_never_served", "scale_ups": 1, "first_up_at": 380.0,
         "max_signal": 1.0, "share_at_or_above_up": 0.1, "peak_serving": 1},
        {"signal": "queue_depth", "up": 1.0, "down": 0.0, "rep": 2,
         "outcome": "no_scaling_action", "scale_ups": 0, "first_up_at": None,
         "max_signal": 0.0, "share_at_or_above_up": 0.0, "peak_serving": 1},
    ]
    (t,) = diag.summarize(rows)
    assert (t["kept"], t["runs"]) == (1, 3)
    assert t["outcomes"] == {"kept": 1, "no_scaling_action": 1, "replica_never_served": 1}
    assert t["median_first_up_at"] == 240.0  # over the two runs that scaled
    assert t["median_max_signal"] == 1.0


def test_littles_law_settles_below_the_cap_or_at_it():
    curve = ServiceCurve(points=[(1, 0.5, 2.0, 1.0), (100, 1.0, 100.0, 1.0)], measured=True)
    light = diag.littles_law_in_flight(curve, rate=10.0)
    assert light == pytest.approx(10.0 * curve.latency_at(light), rel=1e-6)
    assert light < 100
    assert diag.littles_law_in_flight(curve, rate=500.0) == 100
