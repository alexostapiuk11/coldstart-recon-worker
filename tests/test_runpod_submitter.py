import pytest
import requests

from coldstart.runpod_submitter import HttpTransport, RunPodSubmitter

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


class _FakeResponse:
    """Stands in for a `requests.Response` in HttpTransport tests."""

    def __init__(self, status_code, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json


class _FakeSession:
    """Stands in for the `requests` module: HttpTransport calls
    `session.get`/`session.post` exactly as it would call the module-level
    functions. get and post are queued separately so a test can script a
    submit-then-poll sequence without one call stealing the other's response.
    """

    def __init__(self, get_responses=(), post_responses=()):
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses)
        self.get_calls = 0
        self.post_calls = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_calls += 1
        return self._post_responses.pop(0)

    def get(self, url, headers=None, timeout=None):
        self.get_calls += 1
        return self._get_responses.pop(0)


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


def test_missing_status_key_polls_until_timeout():
    """A status payload with no `status` key at all can't be classified as
    terminal -- `.get("status")` returns None, which is not in
    TERMINAL_STATES -- so it falls through to the poll loop and eventually
    times out rather than being silently treated as success or raising a
    KeyError. This is the intended fail-safe for a malformed or unexpected
    platform response."""
    weird = {"id": "job-1"}
    sub = RunPodSubmitter(
        transport=FakeTransport([weird]),
        clock=iter([0.0, 1.0]).__next__,
        poll_interval=0.0,
        job_timeout=0.0,
    )
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "timed out" in outcome.error


def test_poll_timeout_with_simulated_elapsed_time_exceeding_budget():
    """Exercises the timeout path over several real polls of simulated
    elapsed time, not just the trivial job_timeout=0.0 case. `poll_clock` is
    a separate injectable from `clock` (which supplies only the two
    clock_A stamps) precisely so this is testable -- see the comment on
    RunPodSubmitter._poll_clock."""
    running = {"id": "job-1", "status": "IN_PROGRESS"}
    t = FakeTransport([running, running, running])
    sub = RunPodSubmitter(
        transport=t,
        clock=iter([100.0, 200.0]).__next__,
        poll_interval=0.0,
        job_timeout=10.0,
        poll_clock=iter([0.0, 4.0, 9.0, 15.0]).__next__,
    )
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "timed out" in outcome.error


def test_http_transport_status_retries_transient_5xx_then_succeeds():
    session = _FakeSession(
        get_responses=[_FakeResponse(500), _FakeResponse(200, {"status": "COMPLETED"})]
    )
    transport = HttpTransport("ep", "key", attempts=3, session=session, sleep=lambda s: None)
    result = transport.status("job-1")
    assert result == {"status": "COMPLETED"}
    assert session.get_calls == 2


def test_transient_polling_blip_does_not_fail_a_job_that_would_have_completed():
    """CRITICAL fix: previously status() had no retry, so a single transient
    5xx or network blip on any one of up to job_timeout/poll_interval polls
    would raise, be caught by submit()'s broad except, and permanently record
    a paid -- possibly successful -- job as failed. status() now retries
    exactly as start() does."""
    session = _FakeSession(
        post_responses=[_FakeResponse(200, {"id": "job-1"})],
        get_responses=[_FakeResponse(500), _FakeResponse(200, COMPLETED)],
    )
    transport = HttpTransport("ep", "key", attempts=3, session=session, sleep=lambda s: None)
    sub = RunPodSubmitter(transport=transport, clock=iter([100.0, 200.0]).__next__,
                          poll_interval=0.0)
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.error is None
    assert outcome.payload is not None


def test_http_transport_status_exhausting_retries_is_captured_as_data_not_raised():
    session = _FakeSession(
        post_responses=[_FakeResponse(200, {"id": "job-1"})],
        get_responses=[_FakeResponse(500), _FakeResponse(500)],
    )
    transport = HttpTransport("ep", "key", attempts=2, session=session, sleep=lambda s: None)
    sub = RunPodSubmitter(transport=transport, clock=iter([100.0, 200.0]).__next__,
                          poll_interval=0.0)
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert outcome.error is not None


def test_job_timeout_budget_exceeds_the_endpoint_execution_timeout():
    """The client budget covers queue delay PLUS execution; the endpoint's
    executionTimeoutMs bounds execution alone. A client budget at or below it
    expires while a job is still queuing and records a healthy run as failed
    -- observed on the first priming run, delayTime 1898s vs execution 140s.
    """
    import inspect

    default = inspect.signature(RunPodSubmitter).parameters["job_timeout"].default
    endpoint_execution_timeout_s = 1800.0  # executionTimeoutMs on the pinned endpoint
    assert default > endpoint_execution_timeout_s * 2, (
        f"job_timeout {default}s leaves no room for queue delay above the "
        f"endpoint's {endpoint_execution_timeout_s}s execution budget"
    )
