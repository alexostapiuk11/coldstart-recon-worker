import pytest

from autoscale.events import Event, EventQueue


def test_events_pop_in_time_order_not_insertion_order():
    q = EventQueue()
    q.push(Event(time=3.0, kind="c"))
    q.push(Event(time=1.0, kind="a"))
    q.push(Event(time=2.0, kind="b"))

    assert len(q) == 3
    assert [q.pop().kind for _ in range(3)] == ["a", "b", "c"]
    assert len(q) == 0


def test_ties_break_on_insertion_order_so_runs_are_reproducible():
    """Two events at the identical timestamp is not exotic -- an arrival and a
    replica becoming ready can land on the same float. `Event` has no
    `__lt__` (a frozen dataclass gets one only with `order=True`), so without
    the counter a tie would fall through to an unsupported `Event < Event`
    comparison -- reached only when the heap's sift actually has to compare
    the tied pair, so it would crash on some heap shapes and not on others:
    an intermittent bug, not a reliable one. Adding `order=True` instead of
    the counter would stop the crash, but by comparing `kind` (the field
    after `time`) whenever times tie -- trading the crash for a silent
    dependency on dataclass field order, exactly the determinism bug this
    queue exists to avoid."""
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


def test_pushing_positive_infinity_raises_instead_of_pinning_the_clock():
    """+inf currently sails through as an ordinary push, pops last, and sets
    `now` to +inf -- after which every later, finite push looks like a
    backwards-clock violation instead of naming the real problem: an event
    that would never fire."""
    q = EventQueue()

    with pytest.raises(ValueError, match="infinite"):
        q.push(Event(time=float("inf"), kind="a"))


def test_pushing_negative_infinity_raises_by_design_not_by_coincidence():
    """-inf is currently rejected only because -inf < 0.0 happens to be true
    in the backwards-clock check -- an accident, not a guard. It should be
    rejected by the same explicit finiteness check as +inf and NaN."""
    q = EventQueue()

    with pytest.raises(ValueError, match="infinite"):
        q.push(Event(time=float("-inf"), kind="a"))
