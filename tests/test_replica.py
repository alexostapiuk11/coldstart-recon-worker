import pytest

from autoscale.replica import Replica, ReplicaState


def test_a_replica_starts_absent_and_becomes_serving_after_its_lag():
    r = Replica(replica_id=1, started_at=10.0, lag=39.4)

    assert r.state_at(10.0) is ReplicaState.STARTING
    assert r.state_at(49.3) is ReplicaState.STARTING
    assert r.state_at(49.4) is ReplicaState.SERVING


def test_a_replica_is_absent_before_it_was_ever_started():
    r = Replica(replica_id=1, started_at=10.0, lag=39.4)
    assert r.state_at(9.9) is ReplicaState.ABSENT


def test_ready_at_is_start_plus_lag():
    assert Replica(replica_id=1, started_at=10.0, lag=39.4).ready_at == pytest.approx(49.4)


def test_there_is_no_degraded_state():
    """Artifact 1 measured the degraded window at ~0.1 s: T_fast is request 1
    for all three arms and per-arm steady-state medians differ by 0.6 ms. The
    binary model is a measured finding, not a convenience -- see spec section 6.
    A future stack that reports ready before warmup completes needs this state
    back, and that is a spec change, not a quiet addition here."""
    assert [s.name for s in ReplicaState] == ["ABSENT", "STARTING", "SERVING"]


def test_a_negative_lag_is_refused():
    with pytest.raises(ValueError, match="negative"):
        Replica(replica_id=1, started_at=0.0, lag=-1.0)


def test_host_id_is_carried_for_validation_runs():
    """Spec section 10: a scale-up onto a host without the image costs ~2266 s,
    not 39-96 s. Without the host recorded, a platform event is
    indistinguishable from a simulator bug after the fact."""
    r = Replica(replica_id=1, started_at=0.0, lag=39.4, host_id="qerlaykt4q0ves")
    assert r.host_id == "qerlaykt4q0ves"
    assert Replica(replica_id=2, started_at=0.0, lag=39.4).host_id is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_lag_is_rejected(bad):
    """NaN compares False against every ordering check in state_at, and +-inf
    poisons ready_at's addition -- either way a non-finite lag would silently
    produce a replica that is never absent, starting, or serving instead of
    raising here."""
    with pytest.raises(ValueError, match="not finite"):
        Replica(replica_id=1, started_at=0.0, lag=bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_started_at_is_rejected(bad):
    """Same failure mode as a non-finite lag, on the other operand of
    ready_at's addition."""
    with pytest.raises(ValueError, match="not finite"):
        Replica(replica_id=1, started_at=bad, lag=39.4)


def test_state_at_rejects_nan():
    """`t < self.started_at` and `t < self.ready_at` are both False for NaN,
    so without this guard a NaN query would fall through to SERVING -- a
    confident, wrong answer -- instead of raising."""
    r = Replica(replica_id=1, started_at=10.0, lag=39.4)
    with pytest.raises(ValueError, match="NaN"):
        r.state_at(float("nan"))


def test_replica_is_frozen():
    """A mutable Replica would let `lag` or `started_at` be rewritten after
    __post_init__ already validated them, making the finiteness and
    negative-lag guards above tamper-evident only at construction time."""
    r = Replica(replica_id=1, started_at=0.0, lag=39.4)
    with pytest.raises(AttributeError):
        r.lag = -1.0
    with pytest.raises(AttributeError):
        r.started_at = -1.0
