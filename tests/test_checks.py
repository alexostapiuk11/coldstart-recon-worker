import json

import pytest

from coldstart.checks import (
    _SIGNATURES,
    DiscardReason,
    FailureClass,
    check_consistency,
    classify_failure,
    compute_residual,
)


def test_residual_is_total_minus_process():
    assert compute_residual(t_total=100.0, t_process=70.0) == 30.0


def test_consistency_passes_when_process_fits_inside_total():
    result = check_consistency(t_total=100.0, t_process=70.0, rtt_floor=0.5)
    assert result.ok is True
    assert result.reason is None
    assert result.discard_reason is None
    assert bool(result) is True


def test_consistency_fails_when_process_exceeds_total():
    result = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    assert result.ok is False
    assert "exceeds" in result.reason
    assert result.discard_reason is DiscardReason.PROCESS_EXCEEDS_TOTAL
    assert bool(result) is False


def test_consistency_fails_when_residual_is_below_the_rtt_floor():
    result = check_consistency(t_total=70.2, t_process=70.0, rtt_floor=0.5)
    assert result.ok is False
    assert "rtt_floor" in result.reason
    assert result.discard_reason is DiscardReason.RESIDUAL_BELOW_RTT_FLOOR
    assert bool(result) is False


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
    reachable = {classify_failure(n.text) for _, needles in _SIGNATURES for n in needles}
    assert reachable == set(FailureClass) - {FailureClass.UNKNOWN}


# --- C1: non-finite / negative clock readings must raise, not be silently
# accepted. NaN compares False against every operator, so without an
# explicit isfinite guard `residual < 0`, `t_process > t_total`, and
# `< rtt_floor` all fall through to the accept path.


@pytest.mark.parametrize(
    "t_total,t_process",
    [
        (float("nan"), 10.0),
        (100.0, float("nan")),
        (float("inf"), 10.0),
        (100.0, float("inf")),
        (100.0, -5.0),
        (-5.0, 100.0),
    ],
)
def test_compute_residual_rejects_non_finite_and_negative_inputs(t_total, t_process):
    with pytest.raises(ValueError):
        compute_residual(t_total=t_total, t_process=t_process)


@pytest.mark.parametrize(
    "t_total,t_process",
    [
        (float("nan"), 10.0),
        (100.0, float("nan")),
        (float("inf"), 10.0),
        (100.0, -5.0),
    ],
)
def test_check_consistency_rejects_non_finite_and_negative_inputs(t_total, t_process):
    with pytest.raises(ValueError):
        check_consistency(t_total=t_total, t_process=t_process, rtt_floor=0.5)


# --- C2: DEFAULT_RTT_FLOOR must actually be exercised by at least one test
# that omits the rtt_floor kwarg.


def test_check_consistency_uses_default_rtt_floor_when_not_supplied():
    below = check_consistency(t_total=100.04, t_process=100.0)
    assert below.ok is False

    above = check_consistency(t_total=100.06, t_process=100.0)
    assert above.ok is True


# --- I3: pin the accept/reject boundary exactly at rtt_floor.


def test_check_consistency_boundary_at_exactly_rtt_floor():
    result = check_consistency(t_total=100.5, t_process=100.0, rtt_floor=0.5)
    assert result.ok is True


def test_check_consistency_boundary_just_below_rtt_floor():
    result = check_consistency(t_total=100.49, t_process=100.0, rtt_floor=0.5)
    assert result.ok is False


def test_check_consistency_boundary_just_above_rtt_floor():
    result = check_consistency(t_total=100.51, t_process=100.0, rtt_floor=0.5)
    assert result.ok is True


# --- I5: the bare "oom" needle must be word-boundary anchored, not a raw
# substring match.


def test_oom_needle_does_not_match_substring_inside_another_word():
    assert classify_failure("no room left on device") is FailureClass.UNKNOWN


def test_oom_needle_does_not_match_inside_unrelated_word():
    assert classify_failure("vroom vroom, engines starting") is FailureClass.UNKNOWN


# --- I4: row order in _SIGNATURES is a priority policy (root cause beats
# symptom); pin it with a deliberately multi-signal string.


def test_signature_priority_prefers_root_cause_over_symptom():
    detail = "EngineCore failed to initialize: CUDA out of memory"
    assert classify_failure(detail) is FailureClass.OOM


# --- I7: classification must be case-insensitive.


def test_classify_failure_is_case_insensitive():
    assert classify_failure("ERROR: Out Of Memory") is FailureClass.OOM


# --- I6: every needle must have a real (non-reachability-test) assertion.
# 8 of the 15 needles are already exercised by test_failure_classification
# and the priority/case tests above; these cover the remaining 7.
#
# These wrapper strings are synthetic — real engine failure text arrives
# with the Task 6 reconnaissance fixtures. They only confirm the needle is
# wired to its class, not that the wrapping is realistic.


def test_classify_failure_covers_needles_not_exercised_elsewhere():
    assert classify_failure("worker exited: oom") is FailureClass.OOM
    assert classify_failure("probe failed: health timeout") is FailureClass.HEALTH_TIMEOUT
    assert classify_failure("error: failed to fetch") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("pull error: hf hub unreachable") is FailureClass.WEIGHT_ACQUISITION
    assert classify_failure("registry error: manifest unknown") is FailureClass.IMAGE_PULL
    assert (
        classify_failure("scheduler: provisioning timed out")
        is FailureClass.PROVISIONING_TIMEOUT
    )
    assert classify_failure("startup: engine init failed") is FailureClass.ENGINE_INIT


# --- I9: check_consistency and compute_residual must agree at the boundary
# where t_process == t_total (residual is exactly zero, not negative).


def test_process_equal_to_total_is_a_zero_residual_not_a_violation():
    assert compute_residual(t_total=100.0, t_process=100.0) == 0.0
    result = check_consistency(t_total=100.0, t_process=100.0, rtt_floor=0.0)
    assert result.ok is True


# --- I10: discard reasons are a closed enum, not free-form prose swappable
# without a test noticing. Already pinned per-branch above; this locks the
# two members can't be confused with each other.


def test_discard_reasons_are_distinct_enum_members():
    exceeds = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    below_floor = check_consistency(t_total=70.2, t_process=70.0, rtt_floor=0.5)
    assert exceeds.discard_reason is not below_floor.discard_reason
    # check_consistency itself only ever produces these two — DiscardReason
    # also has MISSING_WARMUP_END, produced directly by metrics.derive() for
    # a run that never reaches check_consistency at all (see coldstart/checks.py).
    assert {exceeds.discard_reason, below_floor.discard_reason} == {
        DiscardReason.PROCESS_EXCEEDS_TOTAL,
        DiscardReason.RESIDUAL_BELOW_RTT_FLOOR,
    }
    assert {exceeds.discard_reason, below_floor.discard_reason} < set(DiscardReason)


# --- I8: ConsistencyResult must be falsy exactly when the run is invalid,
# so `if check_consistency(...):` cannot silently accept a violation.


def test_check_consistency_result_is_falsy_when_invalid():
    result = check_consistency(t_total=60.0, t_process=70.0, rtt_floor=0.5)
    assert not result


def test_check_consistency_result_is_truthy_when_valid():
    result = check_consistency(t_total=100.0, t_process=70.0, rtt_floor=0.5)
    assert result


# --- M11: StrEnum must serialize identically via str() and json.dumps().


def test_failure_class_str_and_json_serialization_agree():
    assert str(FailureClass.OOM) == "oom"
    assert f"{FailureClass.OOM}" == "oom"
    assert json.dumps(FailureClass.OOM) == '"oom"'


# --- M12: classify_failure's None path must actually be exercised.


def test_classify_failure_handles_none_detail():
    assert classify_failure(None) is FailureClass.UNKNOWN


# --- M13: the rtt_floor violation message must show both operands, not
# just the floor, so a marginal miss can be told apart from a gross one.


def test_rtt_floor_violation_message_includes_residual_and_floor():
    t_total, t_process, rtt_floor = 70.2, 70.0, 0.5
    residual = compute_residual(t_total=t_total, t_process=t_process)
    result = check_consistency(t_total=t_total, t_process=t_process, rtt_floor=rtt_floor)
    assert str(residual) in result.reason
    assert str(rtt_floor) in result.reason
