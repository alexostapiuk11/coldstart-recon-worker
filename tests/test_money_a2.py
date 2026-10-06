"""Artifact 2's money: dollars per million requests and per spike, at a published rate."""

import json
import math
from pathlib import Path

import pytest

from autoscale.money_a2 import (
    Assumptions,
    billed_hourly_rate,
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
    a = Assumptions(gpu_hourly_rate=1.1, spikes_per_day=24.0)
    # The rate is what RunPod billed, measured from its billing API's rows.
    assert a.provenance == {"gpu_hourly_rate": "measured: billed",
                            "spikes_per_day": "illustrative"}


def test_the_billed_rate_is_total_dollars_over_total_time_billed():
    rows = [{"amount": 1.0, "timeBilledMs": 3_600_000},
            {"amount": 0.5, "timeBilledMs": 1_800_000},
            {"amount": 0.2, "timeBilledMs": 360_000}]
    # $1.70 over 5,760 s; not the mean of the rows' own rates ($1.00, $1.00, $2.00)
    assert billed_hourly_rate(rows) == pytest.approx(1.7 / 5760 * 3600)


@pytest.mark.parametrize("rows", [[], [{"amount": 1.0, "timeBilledMs": 0}],
                                  [{"amount": 0.0, "timeBilledMs": 1000}],
                                  [{"amount": -1.0, "timeBilledMs": 1000}],
                                  [{"amount": math.nan, "timeBilledMs": 1000}]])
def test_the_billed_rate_refuses_rows_that_cannot_price_an_hour(rows):
    with pytest.raises(ValueError, match="billed"):
        billed_hourly_rate(rows)


def test_the_committed_billing_rows_bill_about_1_108_an_hour():
    rec = json.loads((REPO / "data" / "a2" / "billing-endpoints.json").read_text())
    assert billed_hourly_rate(rec["artifact_2_rows"]) == pytest.approx(1.1085, abs=5e-5)


def test_the_rate_file_holds_context_not_the_rate():
    rec = json.loads((REPO / "data" / "a2" / "gpu-rate.json").read_text())
    # No typed rate: the analysis derives it from the billing rows.
    assert "gpu_hourly_rate" not in rec
    assert rec["gpu"] == "NVIDIA GeForce RTX 4090"
    assert rec["reported_cost_per_hr"] == 0.74
    assert rec["reported_cost_per_hr_provenance"] == "reported"
    assert "on-demand" in rec["reported_cost_per_hr_note"]
    assert "billing-endpoints.json" in rec["billed_rate"]


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


def test_the_rate_file_carries_the_list_price_it_was_checked_against():
    rec = json.loads((REPO / "data" / "a2" / "gpu-rate.json").read_text())
    assert rec["list_price_hourly"] == 1.10
    assert rec["list_price_source"] == "https://www.runpod.io/pricing"
    assert rec["list_price_read_on"] == "2026-10-05"
    assert rec["list_price_hourly"] > rec["reported_cost_per_hr"]
