import math

import pytest

from multilora.economics import (
    HOURS_PER_MONTH,
    SECONDS_PER_MONTH,
    cost_per_tenant_month,
    tenant_peak_rate,
    tenants_per_gpu,
    three_way_table,
)
from tests.conftest import example_prereg


def test_peak_rate_scales_the_monthly_average():
    assert tenant_peak_rate(SECONDS_PER_MONTH, 3.0) == pytest.approx(3.0)


def test_slots_bind_when_throughput_and_memory_are_ample(prereg):
    res = tenants_per_gpu(
        slots_below_knee=16, request_rate=100.0, ttft_p95=0.5, max_concurrency=4000, prereg=prereg
    )
    assert res["binding"] == "slots" and res["tenants"] == 16
    assert not res["memory_binds"]


def test_throughput_binds_for_a_busy_tenant():
    busy = example_prereg(requests_per_tenant_month=SECONDS_PER_MONTH * 2.0, peak_to_average=1.0)
    res = tenants_per_gpu(
        slots_below_knee=64, request_rate=20.0, ttft_p95=0.5, max_concurrency=4000, prereg=busy
    )
    assert res["bounds"]["throughput"] == 10
    assert res["binding"] == "throughput"


def test_memory_is_littles_law_on_the_operating_point(prereg):
    res = tenants_per_gpu(
        slots_below_knee=64, request_rate=100.0, ttft_p95=0.5, max_concurrency=32, prereg=prereg
    )
    peak = tenant_peak_rate(prereg.requests_per_tenant_month, prereg.peak_to_average)
    assert res["bounds"]["memory"] == math.floor(32 * 100.0 / (prereg.concurrency * peak))
    assert res["memory_binds"]


def test_an_slo_miss_is_infeasible_not_zero(prereg):
    res = tenants_per_gpu(
        slots_below_knee=8, request_rate=100.0, ttft_p95=9.0, max_concurrency=4000, prereg=prereg
    )
    assert res["feasible"] is False and res["tenants"] is None


def test_cost_is_a_month_of_gpu_over_tenants():
    assert cost_per_tenant_month(2.0, 4) == pytest.approx(2.0 * HOURS_PER_MONTH / 4)
    with pytest.raises(ValueError):
        cost_per_tenant_month(2.0, 0)


def _a4(**row_overrides) -> dict:
    row = {
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
        **row_overrides,
    }
    return {
        "gpu_hourly_rate": 1.0,
        "n_models": 20,
        "reference": {"regime": "low-locality", "s": 1.1},
        "rows": [row, {**row, "s": 0.8, "dedicated_cost_per_tenant_month": 999.0}],
    }


def test_the_table_reads_artifact_fours_reference_row(prereg):
    table = three_way_table(16, prereg, _a4())
    assert [r["strategy"] for r in table] == ["dedicated", "swapped", "adapter"]
    assert table[0]["cost"] == 730.0
    assert table[0]["source"] == "artifact 4, low-locality regime, s = 1.1"
    assert table[-1]["upper_bound"] is True


def test_a_measured_sleep_mode_arm_becomes_a_fourth_row(prereg):
    table = three_way_table(16, prereg, _a4(sleep_mode_cost_per_tenant_month=60.0))
    assert [r["strategy"] for r in table] == ["dedicated", "swapped", "sleep mode", "adapter"]


def test_a_malformed_artifact_four_file_is_refused(prereg):
    with pytest.raises(ValueError, match="lack"):
        three_way_table(16, prereg, {"gpu_hourly_rate": 1.0})
    bad = _a4()
    bad["reference"] = {"regime": "high-locality", "s": 1.1}
    with pytest.raises(ValueError, match="matches 0 rows"):
        three_way_table(16, prereg, bad)
    with pytest.raises(ValueError, match="swapped_cost"):
        three_way_table(16, prereg, _a4(swapped_cost_per_tenant_month=None))
    with pytest.raises(ValueError, match="one rate"):
        three_way_table(16, prereg, {**_a4(), "gpu_hourly_rate": 2.5})
