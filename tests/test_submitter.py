import pytest

from coldstart.stubs.stub_endpoint import StubEndpoint
from coldstart.submitter import StubSubmitter


def test_submitter_records_clock_a_and_returns_payload():
    sub = StubSubmitter(StubEndpoint(seed=2), clock=iter([1000.0, 1120.0]).__next__)
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.clock_A == {"t_submit": 1000.0, "t_result": 1120.0}
    assert outcome.payload["healthy"] is True
    assert outcome.error is None


def test_submit_failure_is_captured_not_raised():
    class Boom:
        def run(self, arm, run_id):
            raise RuntimeError("submit failed: endpoint unreachable")

    sub = StubSubmitter(Boom(), clock=iter([0.0, 1.0]).__next__)
    outcome = sub.submit(arm="A", run_id="run-1")
    assert outcome.payload is None
    assert "submit failed" in outcome.error


def test_clock_a_is_stamped_even_when_the_run_fails():
    """A failed run still consumed wall-clock time and still counts in the
    failure-rate table -- discarding its clock A would make failures free."""

    class Boom:
        def run(self, arm, run_id):
            raise RuntimeError("health check timed out")

    sub = StubSubmitter(Boom(), clock=iter([5.0, 9.0]).__next__)
    outcome = sub.submit(arm="B", run_id="run-2")
    assert outcome.clock_A == {"t_submit": 5.0, "t_result": 9.0}


def test_run_id_is_forwarded_to_the_endpoint():
    """The arm's cache paths are namespaced by run_id, so the id the endpoint
    used must be the id the record carries -- otherwise the paths a run
    actually used cannot be reconstructed from the stored record."""
    seen = {}

    class Recording:
        def run(self, arm, run_id):
            seen["arm"], seen["run_id"] = arm, run_id
            return {"healthy": True}

    StubSubmitter(Recording(), clock=iter([0.0, 1.0]).__next__).submit(arm="C", run_id="run-77")
    assert seen == {"arm": "C", "run_id": "run-77"}


def test_a_failure_does_not_escape_to_the_caller():
    """Failures are data (spec 6.6). A raise here would abort the campaign
    mid-flight and lose every subsequent scheduled run."""

    class Boom:
        def run(self, arm, run_id):
            raise KeyboardInterrupt("not an ordinary failure")

    with pytest.raises(KeyboardInterrupt):
        StubSubmitter(Boom(), clock=iter([0.0, 1.0]).__next__).submit(arm="A", run_id="r")
