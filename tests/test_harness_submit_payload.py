import copy

from harness.runpod.submitter import RunPodSubmitter

COMPLETED = {
    "id": "job-7",
    "status": "COMPLETED",
    "delayTime": 1200,
    "executionTime": 90000,
    "workerId": "worker-xyz",
    "output": {"healthy": True, "host": {"host_id": "container-1"}, "phases": []},
}


class FakeTransport:
    def __init__(self, status):
        self._status = status
        self.started = []

    def start(self, payload):
        self.started.append(payload)
        return self._status["id"]

    def status(self, job_id):
        return self._status


def _submitter(status):
    transport = FakeTransport(status)
    clock = iter([10.0, 25.0])
    sub = RunPodSubmitter(transport, clock=lambda: next(clock), sleep=lambda s: None)
    return sub, transport


def test_the_payload_is_sent_verbatim():
    sub, transport = _submitter(COMPLETED)
    payload = {"run_id": "r1", "condition": "sweep-N16", "n_slots": 16, "phases": []}
    sub.submit_payload(payload)
    assert transport.started == [payload]


def test_a_completed_job_returns_the_output_with_platform_identity_attached():
    sub, _ = _submitter(COMPLETED)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.error is None
    assert outcome.clock_A == {"t_submit": 10.0, "t_result": 25.0}
    assert outcome.payload["host"]["host_id"] == "worker-xyz"
    assert outcome.payload["host"]["container_host_id"] == "container-1"
    assert outcome.payload["host"]["job_id"] == "job-7"
    assert "clock_C" in outcome.payload


def test_an_unhealthy_engine_keeps_its_output_as_diagnostics():
    status = copy.deepcopy(COMPLETED)
    status["output"]["healthy"] = False
    status["output"]["log_lines"] = ["CUDA out of memory"]
    sub, _ = _submitter(status)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.payload is None
    assert "health check timed out" in outcome.error
    assert outcome.diagnostics["log_lines"] == ["CUDA out of memory"]


def test_a_failed_job_is_data_not_an_exception():
    status = {"id": "job-8", "status": "FAILED", "error": "worker exited"}
    sub, _ = _submitter(status)
    outcome = sub.submit_payload({"run_id": "r1"})
    assert outcome.payload is None
    assert "FAILED" in outcome.error


def test_artifact_ones_submit_is_now_the_two_field_payload():
    sub, transport = _submitter(COMPLETED)
    sub.submit(arm="B", run_id="run-9")
    assert transport.started == [{"arm": "B", "run_id": "run-9"}]
