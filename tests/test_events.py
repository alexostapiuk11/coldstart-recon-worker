import pytest

from autoscale.events import Event, EventQueue


def test_events_pop_in_time_order_not_insertion_order():
    q = EventQueue()
    q.push(Event(time=3.0, kind="c"))
    q.push(Event(time=1.0, kind="a"))
    q.push(Event(time=2.0, kind="b"))

    assert [q.pop().kind for _ in range(3)] == ["a", "b", "c"]


def test_ties_break_on_insertion_order_so_runs_are_reproducible():
    """Two events at the identical timestamp is not exotic -- an arrival and a
    replica becoming ready can land on the same float. Without a deterministic
    tiebreak the heap order depends on the payload's comparison, which for
    dataclasses is field order, which makes a run's outcome depend on an
    unrelated attribute."""
    q = EventQueue()
    q.push(Event(time=1.0, kind="first"))
    q.push(Event(time=1.0, kind="second"))

    assert [q.pop().kind for _ in range(2)] == ["first", "second"]


def test_clock_never_moves_backwards():
    q = EventQueue()
    q.push(Event(time=5.0, kind="a"))
    q.pop()

    with pytest.raises(ValueError, match="backwards"):
        q.push(Event(time=4.0, kind="b"))


def test_popping_an_empty_queue_returns_none():
    assert EventQueue().pop() is None


def test_now_tracks_the_last_popped_event():
    q = EventQueue()
    q.push(Event(time=2.5, kind="a"))
    assert q.now == 0.0
    q.pop()
    assert q.now == 2.5


def test_pushing_a_nan_time_raises_instead_of_silently_reordering():
    """NaN compares False against everything, including itself, so the
    backwards-clock check can't catch it by comparison alone -- a NaN would
    otherwise sail into the heap and land wherever heapify puts it, silently
    reordering pops instead of failing loudly."""
    q = EventQueue()

    with pytest.raises(ValueError, match="NaN"):
        q.push(Event(time=float("nan"), kind="a"))
