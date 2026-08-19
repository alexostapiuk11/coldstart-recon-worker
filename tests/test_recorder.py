import pytest

from coldstart.recorder import StageRecorder


def test_marks_are_monotonic_and_relative_to_t0():
    r = StageRecorder(clock=iter([100.0, 100.5, 101.25]).__next__)
    r.start()
    r.mark("S1")
    r.mark("S2")
    b = r.bundle()
    assert b["marks"] == [{"stage": "S1", "t_mono": 0.5}, {"stage": "S2", "t_mono": 1.25}]


def test_duration_between_two_stages():
    r = StageRecorder(clock=iter([10.0, 12.0, 15.0]).__next__)
    r.start()
    r.mark("S1")
    r.mark("S2")
    assert r.duration("S1", "S2") == 3.0


def test_mark_before_start_is_an_error():
    r = StageRecorder()
    with pytest.raises(RuntimeError):
        r.mark("S1")


def test_duplicate_stage_is_an_error():
    r = StageRecorder(clock=iter([0.0, 1.0, 2.0]).__next__)
    r.start()
    r.mark("S1")
    with pytest.raises(ValueError):
        r.mark("S1")


def test_t0_wall_is_captured_for_cross_clock_correlation():
    r = StageRecorder(clock=iter([0.0, 1.0]).__next__, wall_clock=lambda: 1700000000.0)
    r.start()
    r.mark("S1")
    assert r.bundle()["t0_wall"] == 1700000000.0


def test_at_raises_for_an_unmarked_stage():
    r = StageRecorder(clock=iter([0.0, 1.0]).__next__)
    r.start()
    r.mark("S1")
    with pytest.raises(KeyError):
        r.at("S2")
