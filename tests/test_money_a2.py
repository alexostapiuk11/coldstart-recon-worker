"""Artifact 2's money: dollars per million requests and per spike, at a published rate."""

import json
import math
from pathlib import Path

import pytest

from autoscale.money_a2 import (
    Assumptions,
    dollars_per_day,
    dollars_per_million_requests,
    dollars_per_spike,
)

REPO = Path(__file__).resolve().parents[1]


def test_dollars_per_million_requests_at_a_rate():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    # two workers for one hour at 17 req/s
    assert dollars_per_million_requests(a, workers=2, rate=17.0) == round(
        2 * 0.74 / (17.0 * 3600) * 1e6, 2)


def test_dollars_per_spike_from_replica_seconds():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    assert dollars_per_spike(a, replica_seconds=3600.0) == 0.74


def test_assumptions_refuse_non_positive_rates():
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        Assumptions(gpu_hourly_rate=0.0, spikes_per_day=24.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_assumptions_refuse_a_bad_rate_or_spike_count_naming_the_field(bad):
    with pytest.raises(ValueError, match="gpu_hourly_rate"):
        Assumptions(gpu_hourly_rate=bad, spikes_per_day=24.0)
    with pytest.raises(ValueError, match="spikes_per_day"):
        Assumptions(gpu_hourly_rate=0.74, spikes_per_day=bad)


def test_the_refusal_names_the_consequence():
    with pytest.raises(ValueError, match="dollar"):
        Assumptions(gpu_hourly_rate=-0.74, spikes_per_day=24.0)


@pytest.mark.parametrize("bad", [0, -2, 0.0, math.nan, math.inf, True, 1.5])
def test_million_request_cost_refuses_a_bad_worker_count(bad):
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    with pytest.raises(ValueError, match="workers"):
        dollars_per_million_requests(a, workers=bad, rate=17.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_million_request_cost_refuses_a_bad_rate(bad):
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    with pytest.raises(ValueError, match="rate"):
        dollars_per_million_requests(a, workers=2, rate=bad)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_spike_cost_refuses_bad_replica_seconds(bad):
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    with pytest.raises(ValueError, match="replica_seconds"):
        dollars_per_spike(a, replica_seconds=bad)


def test_each_assumption_carries_its_provenance():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    assert a.provenance == {"gpu_hourly_rate": "measured", "spikes_per_day": "illustrative"}


def test_the_committed_rate_file_is_what_the_analysis_will_read():
    rec = json.loads((REPO / "data" / "a2" / "gpu-rate.json").read_text())
    assert rec["gpu_hourly_rate"] == 0.74
    assert rec["provenance"] == "measured"
    assert rec["gpu"] == "NVIDIA GeForce RTX 4090"
    # the billing record is named as the authority over this rate
    assert "billing" in rec["caveat"] and "1.106" in rec["caveat"]


def test_a_positive_cost_below_a_cent_is_not_rounded_to_zero():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    # one replica-second is $0.000206: four decimals, never a free spike
    assert dollars_per_spike(a, replica_seconds=1.0) == 0.0002


def test_dollars_per_day_is_the_unrounded_spike_cost_times_the_spikes():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    # 880 replica-seconds is $0.1809 a spike: $4.34 a day, not 24 x the rounded $0.18
    assert dollars_per_spike(a, replica_seconds=880.0) == 0.18
    assert dollars_per_day(a, replica_seconds_per_spike=880.0) == 4.34


def test_dollars_per_day_refuses_bad_replica_seconds():
    a = Assumptions(gpu_hourly_rate=0.74, spikes_per_day=24.0)
    with pytest.raises(ValueError, match="replica_seconds"):
        dollars_per_day(a, replica_seconds_per_spike=math.nan)
