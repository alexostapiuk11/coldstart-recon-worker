import pytest

from coldstart.checks import (
    _SIGNATURES,
    FailureClass,
    check_consistency,
    classify_failure,
    compute_residual,
)


def test_residual_is_total_minus_process():
    assert compute_residual(t_total=100.0, t_process=70.0) == 30.0


def test_consistency_passes_when_process_fits_inside_total():
    ok, reason = check_consistency(t_total=100.0, t_process=70.0, rtt_floor=0.5)
    assert ok is True
    assert reason is None


def test_consistency_fails_when_process_exceeds_total():
    ok, reason = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    assert ok is False
    assert "exceeds" in reason


def test_consistency_fails_when_residual_is_below_the_rtt_floor():
    ok, reason = check_consistency(t_total=70.2, t_process=70.0, rtt_floor=0.5)
    assert ok is False
    assert "rtt_floor" in reason


def test_negative_residual_is_never_silently_returned():
    with pytest.raises(ValueError):
        compute_residual(t_total=50.0, t_process=70.0)


def test_failure_classification():
    assert classify_failure("CUDA out of memory") is FailureClass.OOM
    assert classify_failure("health check timed out") is FailureClass.HEALTH_TIMEOUT
    assert classify_failure("could not download weights") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("image pull backoff") is FailureClass.IMAGE_PULL
    assert classify_failure("no workers available") is FailureClass.PROVISIONING_TIMEOUT
    assert classify_failure("failed to initialize") is FailureClass.ENGINE_INIT
    assert classify_failure("first token timed out") is FailureClass.TTFT_TIMEOUT
    assert classify_failure("submit failed") is FailureClass.SUBMIT_ERROR
    assert classify_failure("something nobody predicted") is FailureClass.UNKNOWN


def test_every_failure_class_except_unknown_is_reachable():
    """A taxonomy with unreachable members is a taxonomy that lies about coverage.

    Without this, deleting a signature row is invisible: the deleted class simply
    stops being produced and every other test still passes.
    """
    reachable = {classify_failure(n) for _, needles in _SIGNATURES for n in needles}
    assert reachable == set(FailureClass) - {FailureClass.UNKNOWN}
