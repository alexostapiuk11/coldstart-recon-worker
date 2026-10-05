import pytest

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.campaign import run
from multilora.cli import (
    STOP_EXIT_CODE,
    ConsecutiveFailureGuard,
    guard_against_silent_restart,
    pins_from_endpoint,
    require_credentials,
    stop_after_consecutive_failures,
)
from multilora.conditions import gate_schedule
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint
from tests.conftest import example_prereg

ENDPOINT = {
    "flashboot": False, "gpuTypeIds": ["NVIDIA GeForce RTX 4090"], "networkVolumeId": "vol",
    "templateId": "tpl", "workersMin": 0, "name": "a5", "workersMax": 1,
}


def test_credentials_are_required():
    with pytest.raises(SystemExit, match="RUNPOD_ENDPOINT_ID"):
        require_credentials({"RUNPOD_API_KEY": "k"})
    assert require_credentials({"RUNPOD_API_KEY": "k", "RUNPOD_ENDPOINT_ID": "e"}) == ("k", "e")


def test_a_populated_store_needs_resume_or_force():
    guard_against_silent_restart(0, "s", resume=False, force=False)
    guard_against_silent_restart(5, "s", resume=True, force=False)
    guard_against_silent_restart(5, "s", resume=False, force=True)
    with pytest.raises(SystemExit, match="5 record"):
        guard_against_silent_restart(5, "s", resume=False, force=False)


def test_pins_are_the_five_fields_and_refuse_flashboot():
    assert pins_from_endpoint(ENDPOINT) == {k: ENDPOINT[k] for k in (
        "flashboot", "gpuTypeIds", "networkVolumeId", "templateId", "workersMin")}
    with pytest.raises(ValueError, match="flashboot"):
        pins_from_endpoint({**ENDPOINT, "flashboot": True})
    with pytest.raises(ValueError, match="workersMin"):
        pins_from_endpoint({**ENDPOINT, "workersMin": 1})
    with pytest.raises(ValueError, match="lacks"):
        pins_from_endpoint({"flashboot": False})


# The larger gate (Amendment 3, docs/experiment-a5.md) lost 52 instances in a
# row to one host whose driver could not run the image: the runner had no
# stop, and kept submitting. These pin the stop it has now.

def test_the_failure_guard_trips_at_the_threshold_of_consecutive_failures():
    guard = ConsecutiveFailureGuard(3)
    assert [guard.observe(o) for o in ("failed", "failed")] == [False, False]
    assert guard.observe("failed") is True


def test_an_ok_instance_resets_the_failure_streak():
    guard = ConsecutiveFailureGuard(2)
    assert guard.observe("failed") is False
    assert guard.observe("ok") is False
    assert guard.observe("failed") is False
    assert guard.observe("failed") is True


@pytest.mark.parametrize("bad", [0, -1, 1.5, "3", True, None])
def test_the_failure_threshold_must_be_a_positive_int(bad):
    with pytest.raises(ValueError, match="positive int"):
        ConsecutiveFailureGuard(bad)


BAD_HOST = {"host_id": "bad-host", "driver_version": "570.195.03", "runpod_pod_id": "pod-x"}


def _worker_failing_at(indices):
    """The stub worker, except that the chosen run indices come back the way
    the bad host's did: an engine that never became healthy."""
    endpoint = StubInstanceEndpoint(seed=0)

    def worker(payload):
        if payload["run_index"] in indices:
            return {
                "healthy": False,
                "host": BAD_HOST,
                "log_lines": ["Error 804: forward compatibility was attempted on non supported HW"],
            }
        return endpoint.run(payload)

    return worker


def test_a_streak_of_failures_stops_the_run_and_resume_continues_it(tmp_path, capsys):
    prereg = example_prereg(gate_instances=24)
    schedule = gate_schedule(prereg)
    store = JsonlStore(tmp_path / "gate.jsonl", InstanceRecord)
    # One isolated failure (2) must not stop the run; three in a row (5, 6, 7) must.
    with pytest.raises(SystemExit) as stop:
        run(schedule, PayloadStubSubmitter(_worker_failing_at({2, 5, 6, 7, 8, 9})), store,
            prereg, on_run=stop_after_consecutive_failures(3))
    assert stop.value.code == STOP_EXIT_CODE == 3
    stored = store.read_all()
    assert [r.run_index for r in stored] == list(range(8))
    assert [r.run_index for r in stored if r.outcome != "ok"] == [2, 5, 6, 7]
    message = capsys.readouterr().out
    assert "run_index 5..7" in message and "health_timeout" in message
    assert "host_id=bad-host" in message and "driver_version=570.195.03" in message
    assert "--resume" in message and "30 s" in message

    before = store.path.read_text()
    run(schedule, PayloadStubSubmitter(_worker_failing_at(set())), store, prereg, resume=True,
        on_run=stop_after_consecutive_failures(3))
    assert store.path.read_text().startswith(before)
    resumed = store.read_all()
    assert [r.run_index for r in resumed] == list(range(24))
    assert all(r.outcome == "ok" for r in resumed[8:])
