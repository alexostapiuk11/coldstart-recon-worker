import pytest

from autoscale.controller import Controller, Decision


def test_no_action_below_the_scale_up_threshold():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=4.9, replicas=2, now=0.0) is Decision.HOLD


def test_scale_up_when_the_signal_crosses():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=5.0, replicas=2, now=0.0) is Decision.UP


def test_cooldown_suppresses_a_second_action():
    """Without a cooldown a policy fires on every evaluation while the signal
    stays high, launching a replica per tick and making every signal look
    identically aggressive. Real autoscalers have one; modeling them without it
    would idealize away the constraint the comparison is about."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)

    assert c.decide(signal_value=9.0, replicas=2, now=0.0) is Decision.UP
    assert c.decide(signal_value=9.0, replicas=3, now=29.9) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=3, now=30.0) is Decision.UP


def test_scale_down_below_the_low_threshold():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=0.5, replicas=3, now=0.0) is Decision.DOWN


def test_never_scales_below_one_replica():
    """Scale-to-zero would make the next request pay a full cold start and turn
    the comparison into a measurement of the idle timeout instead of the signal."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=0.0, replicas=1, now=0.0) is Decision.HOLD


def test_never_scales_above_the_cap():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=4)
    assert c.decide(signal_value=100.0, replicas=4, now=0.0) is Decision.HOLD


def test_an_infinite_signal_scales_up():
    """Zero serving replicas reports infinite pressure (Task 8). The controller
    must act on it rather than propagating a NaN through the comparison."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    assert c.decide(signal_value=float("inf"), replicas=1, now=0.0) is Decision.UP


def test_inverted_thresholds_are_refused():
    with pytest.raises(ValueError, match="scale_down_at"):
        Controller(scale_up_at=1.0, scale_down_at=5.0, cooldown=30.0, max_replicas=10)


# --- Self-review additions -------------------------------------------------
#
# A NaN signal compares False against every threshold, so an unguarded
# controller would silently HOLD forever while the fleet drowns -- the exact
# silent-wrong-answer this repo treats as the cardinal sin. These pin the
# guards that keep bad state out of the controller and prevent NaN from ever
# reaching a comparison.


def test_nan_signal_value_is_rejected():
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    with pytest.raises(ValueError, match="signal_value"):
        c.decide(signal_value=float("nan"), replicas=2, now=0.0)


def test_nan_signal_value_is_rejected_even_during_cooldown():
    """The NaN check must happen before the cooldown short-circuit, not after,
    so a NaN signal never gets a free pass just because the controller
    recently acted."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)
    c.decide(signal_value=9.0, replicas=2, now=0.0)
    with pytest.raises(ValueError, match="signal_value"):
        c.decide(signal_value=float("nan"), replicas=3, now=1.0)


def test_negative_cooldown_is_refused():
    with pytest.raises(ValueError, match="cooldown"):
        Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=-1.0, max_replicas=10)


def test_infinite_cooldown_is_refused():
    with pytest.raises(ValueError, match="cooldown"):
        Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=float("inf"), max_replicas=10)


def test_nan_cooldown_is_refused():
    with pytest.raises(ValueError, match="cooldown"):
        Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=float("nan"), max_replicas=10)


def test_max_replicas_below_min_replicas_is_refused():
    with pytest.raises(ValueError, match="max_replicas"):
        Controller(
            scale_up_at=5.0,
            scale_down_at=1.0,
            cooldown=30.0,
            max_replicas=2,
            min_replicas=3,
        )


def test_non_finite_scale_up_at_is_refused():
    with pytest.raises(ValueError, match="scale_up_at"):
        Controller(scale_up_at=float("inf"), scale_down_at=1.0, cooldown=30.0, max_replicas=10)


def test_non_finite_scale_down_at_is_refused():
    with pytest.raises(ValueError, match="scale_down_at"):
        Controller(scale_up_at=5.0, scale_down_at=float("nan"), cooldown=30.0, max_replicas=10)


def test_a_hold_does_not_reset_the_cooldown():
    """Repeated HOLD decisions while the signal stays high must not push the
    cooldown window back -- the window is anchored to the last actual action,
    not to the last time decide() was called."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)

    assert c.decide(signal_value=9.0, replicas=2, now=0.0) is Decision.UP
    assert c.decide(signal_value=9.0, replicas=3, now=10.0) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=3, now=20.0) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=3, now=29.9) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=3, now=30.0) is Decision.UP


def test_a_hold_from_no_prior_action_does_not_start_a_cooldown():
    """A signal that never crosses a threshold must never suppress a later
    action -- only an actual UP/DOWN starts the cooldown clock."""
    c = Controller(scale_up_at=5.0, scale_down_at=1.0, cooldown=30.0, max_replicas=10)

    assert c.decide(signal_value=3.0, replicas=2, now=0.0) is Decision.HOLD
    assert c.decide(signal_value=3.0, replicas=2, now=0.1) is Decision.HOLD
    assert c.decide(signal_value=9.0, replicas=2, now=0.2) is Decision.UP
