import pytest

from multilora.budget import estimate, instance_seconds
from tests.conftest import example_prereg

TIMINGS = {
    1: {"setup_s": 5.0, "warm_startup_s": 40.0, "seconds_per_request": 0.01},
    16: {"setup_s": 20.0, "warm_startup_s": 45.0, "seconds_per_request": 0.012},
    64: {"setup_s": 60.0, "warm_startup_s": 55.0, "seconds_per_request": 0.016},
}
COLD = {1: 90.0, 16: 95.0, 64: 110.0}


def test_instance_time_is_setup_startup_warmup_and_four_phases(prereg):
    expected = 5.0 + 40.0 + prereg.warmup_requests_per_adapter * 1 * 0.01 + 4 * 640 * 0.01
    assert instance_seconds(1, prereg, TIMINGS) == pytest.approx(expected)


def test_unmeasured_points_interpolate_in_log2(prereg):
    at_4 = instance_seconds(4, prereg, TIMINGS)
    assert instance_seconds(1, prereg, TIMINGS) < at_4 < instance_seconds(16, prereg, TIMINGS)


def test_within_the_cap_nothing_is_cut():
    res = estimate(example_prereg(gpu_hourly_rate=0.5), TIMINGS, cold_startup_s=COLD, cap_usd=20.0)
    assert res["include_control"] and res["include_diagnostic"]
    assert len(res["steps"]) == 1 and not res["over_cap"]


def test_over_the_cap_the_control_goes_first_then_the_diagnostic():
    pricey = example_prereg(gpu_hourly_rate=1.0)
    full = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=1e9)["usd"]
    res = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=full * 0.93)
    assert [s["step"] for s in res["steps"]][:2] == ["as registered", "control cut"]
    assert res["include_control"] is False
    tight = estimate(pricey, TIMINGS, cold_startup_s=COLD, cap_usd=1.0)
    assert tight["include_diagnostic"] is False and tight["over_cap"] is True
