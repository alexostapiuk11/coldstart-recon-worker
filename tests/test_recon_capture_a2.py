"""The artifact-2 reconnaissance capture, proven without a network.

Every property tested here is one whose failure costs money or corrupts the
evidence: a capture that spends against a misconfigured endpoint, leaves a
worker pinned and billing, writes the API key into a committed fixture, or
polls before every job of a burst is submitted (which would serialise the
burst and answer Q2 about the wrong experiment).
"""

import itertools
import json
import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "recon"))

import capture_a2

EID = "ep-test"
KEY = "sk-THIS-MUST-NEVER-REACH-DISK"
GOOD_ENDPOINT = {"id": EID, "flashboot": False, "workersMin": 0, "workersMax": 2}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    """Scripted RunPod. `endpoint` is mutated by /update, as the real one is."""

    def __init__(self, endpoint=None, health_status=200, health_raises=False,
                 ignore_release=False):
        self.endpoint = dict(endpoint or GOOD_ENDPOINT)
        self.health_status = health_status
        self.health_raises = health_raises
        self.ignore_release = ignore_release
        self.calls = []
        self._jobs = itertools.count(1)

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url, None))
        if url.endswith(f"/endpoints/{EID}"):
            return FakeResponse(200, dict(self.endpoint))
        if url.endswith("/health"):
            if self.health_raises:
                raise requests.ConnectionError("health endpoint dropped the connection")
            if self.health_status != 200:
                return FakeResponse(self.health_status, {"error": "not found"})
            return FakeResponse(200, {"workers": {"running": self.endpoint["workersMin"]}})
        if "/status/" in url:
            job = url.rsplit("/", 1)[1]
            return FakeResponse(200, {
                "id": job, "status": "COMPLETED", "workerId": f"w-{job}",
                "delayTime": 100, "executionTime": 5000,
                "output": {"log_lines": ["torch.compile took 1.00 s in total"]},
            })
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers, json, timeout):
        self.calls.append(("POST", url, json))
        if url.endswith("/run"):
            return FakeResponse(200, {"id": f"job{next(self._jobs)}"})
        if url.endswith("/update"):
            if not (self.ignore_release and json.get("workersMin") == 0):
                self.endpoint.update(json)
            return FakeResponse(200, dict(self.endpoint))
        raise AssertionError(f"unexpected POST {url}")


def _capture(tmp_path, session):
    return capture_a2.Capture(
        EID, KEY, out=tmp_path / "a2_recon", workers=2, session=session,
        clock=itertools.count(0, 50).__next__, sleep=lambda s: None,
    )


def _posts(session, suffix):
    return [body for method, url, body in session.calls if method == "POST" and url.endswith(suffix)]


@pytest.mark.parametrize("override, word", [
    ({"flashboot": True}, "flashboot"),
    ({"workersMin": 1}, "workersMin"),
    ({"workersMax": 1}, "workersMax"),
])
def test_it_refuses_to_spend_against_a_misconfigured_endpoint(tmp_path, override, word):
    """FlashBoot on measures RunPod's cache instead of a cold start;
    workersMin > 0 keeps a worker warm between bursts; workersMax below the
    burst size makes the burst a queue. Each produces a plausible, wrong
    answer to Q2. Nothing may be submitted or updated."""
    session = FakeSession(dict(GOOD_ENDPOINT, **override))
    with pytest.raises(capture_a2.RefuseToSpend, match=word):
        _capture(tmp_path, session).run()
    assert [c for c in session.calls if c[0] == "POST"] == []


def test_a_burst_submits_every_job_before_polling_any(tmp_path):
    """Polling job 1 to completion before submitting job 2 serialises the
    burst, which reproduces artifact 1's one-worker result by construction
    and answers Q2 about the wrong experiment."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    first_burst = session.calls[: next(
        i for i, c in enumerate(session.calls) if "/status/" in c[1]
    )]
    assert sum(1 for c in first_burst if c[1].endswith("/run")) == 2


def test_the_scale_phase_pins_then_releases_then_restores(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert _posts(session, "/update") == [
        {"workersMin": 2}, {"workersMin": 0}, {"workersMin": 0},
    ]


def test_workers_max_is_never_written(tmp_path):
    """workersMax is the cost ceiling the operator chose. A capture that
    raised it would be spending beyond what was authorised."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert all("workersMax" not in body for body in _posts(session, "/update"))


def test_workers_min_is_restored_when_a_phase_fails(tmp_path):
    """A pinned worker bills by the second whether or not anything runs on it.
    The failure must still propagate -- a swallowed error would read as a
    completed capture."""
    session = FakeSession(health_raises=True)
    with pytest.raises(requests.ConnectionError):
        _capture(tmp_path, session).run()
    assert session.endpoint["workersMin"] == 0


def test_a_restore_that_does_not_land_is_loud(tmp_path):
    session = FakeSession(ignore_release=True)
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        _capture(tmp_path, session).run()


def test_the_api_key_never_reaches_disk(tmp_path):
    """Everything under the output directory is destined for fixtures/, which
    is committed. Request headers carry the key and are never recorded."""
    _capture(tmp_path, FakeSession()).run()
    for path in (tmp_path / "a2_recon").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text(), f"{path.name} contains the API key"


def test_every_platform_response_is_recorded(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    lines = (tmp_path / "a2_recon" / "capture.jsonl").read_text().splitlines()
    assert len(lines) == len(session.calls)
    entry = json.loads(lines[0])
    assert set(entry) == {"t", "method", "url", "request", "status_code", "response"}


def test_a_missing_health_endpoint_is_recorded_not_fatal(tmp_path):
    """`GET /v2/{id}/health` is the one platform call this repository has
    never exercised. If it does not exist, that is a Q1 finding -- worker
    counts are not observable that way -- and the job-level workerIds remain.
    It must not abort the capture."""
    session = FakeSession(health_status=404)
    _capture(tmp_path, session).run()
    entries = [json.loads(l) for l in
               (tmp_path / "a2_recon" / "capture.jsonl").read_text().splitlines()]
    assert any(e["url"].endswith("/health") and e["status_code"] == 404 for e in entries)


def test_each_job_status_is_saved_verbatim(tmp_path):
    _capture(tmp_path, FakeSession()).run()
    saved = sorted(p.name for p in (tmp_path / "a2_recon").glob("burst*.json"))
    assert saved == ["burst1_0.json", "burst1_1.json", "burst2_0.json", "burst2_1.json"]
    assert json.loads((tmp_path / "a2_recon" / "burst1_0.json").read_text())["workerId"]


def test_a_burst_of_one_is_refused(tmp_path):
    """One worker cannot demonstrate that the platform starts DISTINCT
    workers, which is the whole of Q2's first half."""
    with pytest.raises(ValueError, match="at least 2"):
        capture_a2.Capture(EID, KEY, out=tmp_path, workers=1, session=FakeSession())
