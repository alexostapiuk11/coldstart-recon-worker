import pytest
from a4_fakes import Clock, memory_script

from placement_measure.gpu_memory import read_memory, wait_for_release


def test_memory_reads_used_and_total():
    assert read_memory(run=memory_script([1234]))["used_mib"] == 1234.0


def test_an_unreadable_card_is_a_sample_not_a_crash():
    reading = read_memory(run=memory_script([None]))
    assert reading["used_mib"] is None
    assert "NVML" in reading["error"]


def test_release_waits_until_memory_falls_to_the_target():
    clock = Clock(0.0)
    out = wait_for_release(
        1000, timeout_s=10, poll_s=0.25, run=memory_script([9000, 9000, 4000, 900]),
        clock=clock, sleep=clock.sleep,
    )
    assert out["released"]
    assert out["seconds"] == pytest.approx(0.75)
    assert len(out["samples"]) == 4


def test_release_that_never_comes_is_recorded_not_raised():
    clock = Clock(0.0)
    out = wait_for_release(1000, timeout_s=1.0, run=memory_script([9000]), clock=clock,
                           sleep=clock.sleep)
    assert not out["released"]
    assert out["seconds"] >= 1.0
