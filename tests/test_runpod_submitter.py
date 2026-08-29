import pytest

from coldstart.runpod_submitter import RunPodSubmitter

COMPLETED = {
    "id": "job-1",
    "status": "COMPLETED",
    "delayTime": 8577,
    "executionTime": 150577,
    "workerId": "iiewfw59dqskoe",
    "output": {
        "healthy": True,
        "run_id": "run-1",
        "arm": "A",
        "log_lines": ["Model loading took 15.27 GiB and 36.4 seconds"],
        "warmup": [{"req_index": 0, "t_dispatch_mono": 1.0, "ttft": 0.5, "end_to_end": 2.0}],
        "clock_B": {"t0_wall": 0.0, "marks": [{"stage": "S1_imports_done", "t_mono": 1.0}]},
        "host": {"host_id": "container-abc", "gpu_model": "NVIDIA GeForce RTX 4090"},
        "cache_config": {"arm": "A", "weights_source": "hub", "compile_cache_warm": False},
        "compile_cache_observed": False,
    },
}


class FakeTransport:
    """Stands in for the RunPod HTTP API."""

    def __init__(self, statuses, job_id="job-1"):
        self._statuses = list(statuses)
        self._job_id = job_id
        self.started = []

    def start(self, payload):
        self.started.append(payload)
        return self._job_id

    def status(self, job_id):
        return self._statuses.pop(0) if len(self._statuses) > 1 else self._statuses[0]


def _submitter(transport, **kw):
    return RunPodSubmitter(
        transport=transport, clock=iter([100.0, 260.0]).__next__, poll_interval=0.0, **kw
    )


def test_submits_arm_and_run_id_as_job_input():
    t = FakeTransport([COMPLETED])
    _submitter(t).submit(arm="A", run_id="run-1")
    assert t.started == [{"arm": "A", "run_id": "run-1"}]


def test_records_clock_a_around_the_whole_job():
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    assert outcome.clock_A == {"t_submit": 100.0, "t_result": 260.0}
    assert outcome.error is None


def test_clock_c_is_attached_from_the_status_payload():
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    assert outcome.payload["clock_C"] == {"delay_ms": 8577, "execution_ms": 150577}


def test_platform_worker_id_becomes_the_host_id():
    """The container hostname changes when a reused worker restarts its
    container; the platform's workerId does not. Within-host pairing needs the
    identity that is stable across a worker's lifetime."""
    outcome = _submitter(FakeTransport([COMPLETED])).submit(arm="A", run_id="run-1")
    host = outcome.payload["host"]
    assert host["host_id"] == "iiewfw59dqskoe"
    assert host["container_host_id"] == "container-abc"


def test_polls_until_terminal():
    running = {"id": "job-1", "status": "IN_PROGRESS"}
    t = FakeTransport([running, running, COMPLETED])
    outcome = _submitter(t).submit(arm="A", run_id="run-1")
    assert outcome.error is None


def test_platform_failure_is_captured_as_data():
    failed = {"id": "job-1", "status": "FAILED", "error": "worker exited"}
    outcome = _submitter(FakeTransport([failed])).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "worker exited" in outcome.error


def test_unhealthy_probe_is_a_failure_not_a_publishable_run():
    """The job completed, but the engine never became healthy. Recording it as
    ok would put a run with no stage marks into the publishable set."""
    unhealthy = dict(COMPLETED, output=dict(COMPLETED["output"], healthy=False))
    outcome = _submitter(FakeTransport([unhealthy])).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "health check timed out" in outcome.error


def test_poll_timeout_is_captured_as_data():
    running = {"id": "job-1", "status": "IN_PROGRESS"}
    sub = RunPodSubmitter(
        transport=FakeTransport([running]),
        clock=iter([0.0, 1.0]).__next__,
        poll_interval=0.0,
        job_timeout=0.0,
    )
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "timed out" in outcome.error


def test_transport_exception_does_not_escape():
    class Broken:
        def start(self, payload):
            raise RuntimeError("submit failed: connection reset")

    outcome = _submitter(Broken()).submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "submit failed" in outcome.error


def test_keyboard_interrupt_still_escapes():
    class Stopped:
        def start(self, payload):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _submitter(Stopped()).submit(arm="A", run_id="run-1")
