"""The payload stub is what every GPU-free test of a payload-taking worker
runs through, so it must fail in the same places the real submitter does."""

from pathlib import Path

import pytest

from harness.failures import FailureClass, classify_failure
from harness.runpod.submitter import RunPodSubmitter
from harness.submit import UNHEALTHY_ERROR, PayloadStubSubmitter


def _clock():
    ticks = iter([1.0, 4.0])
    return lambda: next(ticks)


def test_a_healthy_output_is_the_payload_and_clock_a_brackets_it():
    seen = []

    def worker(payload):
        seen.append(payload)
        return {"healthy": True, "echo": payload["x"]}

    outcome = PayloadStubSubmitter(worker, clock=_clock()).submit_payload({"x": 7})
    assert seen == [{"x": 7}]
    assert outcome.error is None
    assert outcome.payload == {"healthy": True, "echo": 7}
    assert outcome.clock_A == {"t_submit": 1.0, "t_result": 4.0}


def test_an_unhealthy_output_is_a_failure_with_the_output_kept():
    output = {"healthy": False, "log_lines": ["CUDA out of memory"]}
    outcome = PayloadStubSubmitter(lambda p: output, clock=_clock()).submit_payload({})
    assert outcome.payload is None
    assert outcome.error == UNHEALTHY_ERROR
    assert outcome.diagnostics == output
    assert classify_failure(outcome.error) is FailureClass.HEALTH_TIMEOUT


def test_an_output_without_healthy_counts_as_unhealthy():
    outcome = PayloadStubSubmitter(lambda p: {"run": {}}, clock=_clock()).submit_payload({})
    assert outcome.error == UNHEALTHY_ERROR


def test_a_worker_exception_is_data_not_a_raise():
    def worker(payload):
        raise RuntimeError("engine exploded")

    outcome = PayloadStubSubmitter(worker, clock=_clock()).submit_payload({})
    assert outcome.payload is None
    assert outcome.error == "engine exploded"
    assert outcome.clock_A == {"t_submit": 1.0, "t_result": 4.0}


def test_a_payload_the_real_transport_could_not_send_fails_here():
    outcome = PayloadStubSubmitter(lambda p: {"healthy": True}, clock=_clock()).submit_payload(
        {"path": Path("/tmp/x")}
    )
    assert outcome.payload is None
    assert "not JSON serializable" in outcome.error


def test_the_payload_arrives_as_json_would_deliver_it():
    seen = []
    PayloadStubSubmitter(lambda p: seen.append(p) or {"healthy": True}).submit_payload(
        {"levels": (1, 2)}
    )
    assert seen == [{"levels": [1, 2]}]


def test_keyboard_interrupt_still_escapes():
    def worker(payload):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        PayloadStubSubmitter(worker).submit_payload({})


def test_the_unhealthy_text_matches_the_real_submitters():
    class Transport:
        def start(self, payload):
            return "job-1"

        def status(self, job_id):
            return {"id": job_id, "status": "COMPLETED", "output": {"healthy": False}}

    real = RunPodSubmitter(Transport(), sleep=lambda s: None).submit_payload({})
    assert real.error == UNHEALTHY_ERROR
