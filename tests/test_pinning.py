"""WorkerPin: pin workersMin to N, always release, never touch workersMax."""

import pytest
import requests

from harness.runpod.pinning import PinRefused, ReleaseFailed, WorkerPin

EID = "ep-lb"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("WorkerPin touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


class Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, endpoint=None, post_script=(), get_script=(), ignore_release=False):
        self.endpoint = dict(endpoint or {"id": EID, "workersMin": 0, "workersMax": 2})
        self.post_script = list(post_script)
        self.get_script = list(get_script)
        self.ignore_release = ignore_release
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        assert headers["Authorization"].startswith("Bearer ")
        if self.post_script:
            step = self.post_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is not None:
                return Resp(step, {"error": "scripted"})
        if not (self.ignore_release and json == {"workersMin": 0}):
            self.endpoint.update(json)
        return Resp(200, dict(self.endpoint))

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        if self.get_script:
            step = self.get_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is not None:
                return Resp(step, {"error": "scripted"})
        return Resp(200, dict(self.endpoint))


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _pin(session, clock=None, workers=2):
    clock = clock or Clock()
    return WorkerPin(EID, "key", workers=workers, session=session, clock=clock.clock,
                     sleep=clock.sleep)


def test_preflight_requires_workers_min_zero_and_workers_max_equal_to_n():
    _pin(FakeSession()).preflight()
    with pytest.raises(PinRefused, match="workersMax"):
        _pin(FakeSession({"workersMin": 0, "workersMax": 3})).preflight()
    with pytest.raises(PinRefused, match="workersMin"):
        _pin(FakeSession({"workersMin": 1, "workersMax": 2})).preflight()


def test_the_context_pins_then_releases_and_never_writes_workers_max():
    s = FakeSession()
    with _pin(s):
        assert s.endpoint["workersMin"] == 2
    assert s.endpoint["workersMin"] == 0
    assert all("workersMax" not in (body or {}) for _, _, body in s.calls)


def test_release_runs_when_the_body_raises():
    s = FakeSession()
    with pytest.raises(RuntimeError, match="boom"), _pin(s):
        raise RuntimeError("boom")
    assert s.endpoint["workersMin"] == 0


def test_release_runs_on_system_exit_from_a_signal():
    s = FakeSession()
    with pytest.raises(SystemExit), _pin(s):
        raise SystemExit(143)
    assert s.endpoint["workersMin"] == 0


def test_a_pin_that_fails_after_writing_is_still_released():
    s = FakeSession(get_script=[None, 500, 500, 500, 500, 500])
    with pytest.raises(PinRefused, match="500"), _pin(s):
        pass
    assert s.endpoint["workersMin"] == 0


def test_release_retries_through_409s_and_a_lagging_re_read():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [409, 409]
    s.get_script = [None]
    ep = p.release()
    assert ep["workersMin"] == 0


def test_release_gives_up_loudly_at_the_deadline():
    s = FakeSession(ignore_release=True)
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    p.pin()
    with pytest.raises(ReleaseFailed, match="Set it to 0 by hand"):
        p.release()
    assert clock.t <= 300.0 + 30.0


def test_a_refusal_that_retrying_cannot_fix_fails_at_once():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [403]
    with pytest.raises(ReleaseFailed, match="403"):
        p.release()


def test_a_changed_workers_max_is_reported_after_release():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.endpoint["workersMax"] = 5
    with pytest.raises(RuntimeError, match="workersMax is 5"):
        p.release()
    assert s.endpoint["workersMin"] == 0


def test_connection_errors_during_release_are_retried():
    s = FakeSession()
    p = _pin(s)
    p.preflight()
    p.pin()
    s.post_script = [requests.ConnectionError("reset")]
    assert p.release()["workersMin"] == 0
