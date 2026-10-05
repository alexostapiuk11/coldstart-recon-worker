"""WorkerPin: pin workersMin to N, always release, never touch workersMax."""

import os
import signal
import threading

import pytest
import requests

from harness.runpod import pinning
from harness.runpod.pinning import (
    EndpointReadError,
    PinFailed,
    PinRefused,
    ReleaseFailed,
    WorkerPin,
    unwind_on_hangup_and_term,
)

EID = "ep-lb"
RELEASE = {"workersMin": 0}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("WorkerPin touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    yield
    for signum, handler in saved.items():
        signal.signal(signum, handler)


class Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Scripted steps: None = behave normally, int = that status, Exception = raise it,
    dict = a 200 with that body (GET only), Resp = returned as is."""

    def __init__(self, endpoint=None, post_script=(), get_script=(), ignore_release=False,
                 on_post=None):
        self.endpoint = dict(endpoint or {"id": EID, "workersMin": 0, "workersMax": 2})
        self.post_script = list(post_script)
        self.get_script = list(get_script)
        self.ignore_release = ignore_release
        self.on_post = on_post
        self.calls = []

    def posts(self, body=None):
        return [c for c in self.calls if c[0] == "POST" and (body is None or c[2] == body)]

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        assert headers["Authorization"].startswith("Bearer ")
        if self.on_post:
            self.on_post(json)
        if self.post_script:
            step = self.post_script.pop(0)
            if isinstance(step, BaseException):
                raise step
            if step is not None:
                return Resp(step, {"error": "scripted"})
        if not (self.ignore_release and json == RELEASE):
            self.endpoint.update(json)
        return Resp(200, dict(self.endpoint))

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        if self.get_script:
            step = self.get_script.pop(0)
            if isinstance(step, BaseException):
                raise step
            if isinstance(step, Resp):
                return step
            if isinstance(step, dict):
                return Resp(200, step)
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


def _pinned(session, clock=None):
    p = _pin(session, clock)
    p.preflight()
    p.pin()
    return p


# --- preflight ------------------------------------------------------------

def test_preflight_requires_workers_min_zero_and_workers_max_equal_to_n():
    _pin(FakeSession()).preflight()
    with pytest.raises(PinRefused, match="workersMax"):
        _pin(FakeSession({"workersMin": 0, "workersMax": 3})).preflight()
    with pytest.raises(PinRefused, match="workersMin"):
        _pin(FakeSession({"workersMin": 1, "workersMax": 2})).preflight()


@pytest.mark.parametrize("endpoint", [
    {"workersMin": False, "workersMax": 2},
    {"workersMin": 0.0, "workersMax": 2},
    {"workersMin": 0, "workersMax": 2.0},
    {"workersMin": 0, "workersMax": True},
])
def test_preflight_does_not_read_false_or_floats_as_integers(endpoint):
    with pytest.raises(PinRefused):
        _pin(FakeSession(endpoint), workers=1 if endpoint["workersMax"] is True else 2).preflight()


def test_a_failed_preflight_read_is_a_refusal_that_says_nothing_was_written():
    with pytest.raises(PinRefused, match="Nothing was written") as err:
        _pin(FakeSession(get_script=[404])).preflight()
    assert isinstance(err.value.__cause__, EndpointReadError)


# --- pin ------------------------------------------------------------------

def test_the_context_pins_then_releases_and_never_writes_workers_max():
    s = FakeSession()
    with _pin(s):
        assert s.endpoint["workersMin"] == 2
    assert s.endpoint["workersMin"] == 0
    assert all("workersMax" not in (body or {}) for _, _, body in s.calls)


def test_a_pin_re_read_that_cannot_be_read_is_a_neutral_error_and_is_still_released():
    # Preflight read is normal; the re-read after the pin's write is refused.
    s = FakeSession(get_script=[None, 403])
    with pytest.raises(EndpointReadError, match="403") as err, _pin(s):
        pass
    assert not isinstance(err.value, PinRefused)
    assert s.endpoint["workersMin"] == 0


def test_pin_survives_a_409_window_far_longer_than_fifteen_seconds():
    s = FakeSession(post_script=[409] * 6)
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    assert p.pin()["workersMin"] == 2
    assert clock.slept == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
    assert sum(clock.slept) > 15


def test_pin_retries_a_lagging_re_read():
    s = FakeSession(get_script=[None, {"workersMin": 0, "workersMax": 2}])
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    assert p.pin()["workersMin"] == 2
    assert len(s.posts({"workersMin": 2})) == 2
    assert clock.slept == [1.0]


def test_pin_gives_up_at_its_deadline_naming_the_409_window_and_the_release():
    s = FakeSession(post_script=[409] * 1000)
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    with pytest.raises(PinFailed, match="409") as err:
        p.pin()
    assert "releases workersMin" in str(err.value)
    assert clock.t <= pinning.PIN_DEADLINE_SECONDS
    assert clock.t >= pinning.PIN_DEADLINE_SECONDS - pinning.BACKOFF_CAP_SECONDS


def test_the_context_releases_when_the_pin_runs_out_of_time():
    s = FakeSession(post_script=[409] * 8)
    with pytest.raises(PinFailed), _pin(s):
        pass
    assert s.endpoint["workersMin"] == 0
    assert s.posts(RELEASE)


def test_a_pin_refusal_retrying_cannot_fix_fails_at_once():
    s = FakeSession(post_script=[403])
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    with pytest.raises(PinFailed, match="403"):
        p.pin()
    assert clock.slept == []


# --- release --------------------------------------------------------------

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


def test_release_retries_through_409s():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.post_script = [409, 409]
    assert p.release()["workersMin"] == 0
    assert len(s.posts(RELEASE)) == 3
    assert clock.slept == [1.0, 2.0]


def test_release_retries_a_re_read_that_still_shows_the_pin():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.get_script = [{"workersMin": 2, "workersMax": 2}]
    assert p.release()["workersMin"] == 0
    assert len(s.posts(RELEASE)) == 2
    assert clock.slept == [1.0]


def test_release_does_not_read_false_as_released():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.get_script = [{"workersMin": False, "workersMax": 2}]
    p.release()
    assert len(s.posts(RELEASE)) == 2


def test_release_retries_a_5xx_on_the_release_post():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.post_script = [503]
    assert p.release()["workersMin"] == 0
    assert clock.slept == [1.0]


@pytest.mark.parametrize("bad", [Resp(200, ["not", "an", "endpoint"]),
                                 Resp(200, ValueError("<html>")), 502])
def test_release_retries_a_re_read_that_is_not_an_endpoint(bad):
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.get_script = [bad]
    assert p.release()["workersMin"] == 0
    assert clock.slept == [1.0]


def test_release_gives_up_loudly_only_at_the_deadline():
    s = FakeSession(ignore_release=True)
    clock = Clock()
    p = _pin(s, clock)
    p.preflight()
    p.pin()
    with pytest.raises(ReleaseFailed, match="Set it to 0 by hand"):
        p.release()
    assert 270.0 <= clock.t <= 300.0
    assert max(clock.slept) == 30.0


def test_the_backoff_exponent_is_capped():
    assert pinning._backoff(10_000) == 30.0


def test_a_refusal_that_retrying_cannot_fix_fails_at_once():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.post_script = [403]
    with pytest.raises(ReleaseFailed, match="403"):
        p.release()
    assert clock.slept == []


def test_a_4xx_on_the_verifying_re_read_fails_at_once():
    s = FakeSession()
    clock = Clock()
    p = _pinned(s, clock)
    s.get_script = [403]
    with pytest.raises(ReleaseFailed, match="403"):
        p.release()
    assert clock.slept == []


def test_a_changed_workers_max_is_reported_after_release():
    s = FakeSession()
    p = _pinned(s)
    s.endpoint["workersMax"] = 5
    with pytest.raises(RuntimeError, match="workersMax is 5"):
        p.release()
    assert s.endpoint["workersMin"] == 0


@pytest.mark.parametrize("exc", [requests.ConnectionError("reset"), OSError("EPIPE"),
                                 ValueError("surprise")])
def test_exceptions_during_release_are_retried(exc):
    s = FakeSession()
    p = _pinned(s)
    s.post_script = [exc]
    assert p.release()["workersMin"] == 0


def test_a_release_failure_keeps_the_bodys_exception_as_context():
    s = FakeSession(ignore_release=True)
    with pytest.raises(ReleaseFailed) as err, _pin(s):
        raise RuntimeError("the measurement broke")
    assert isinstance(err.value.__context__, RuntimeError)
    assert "the measurement broke" in str(err.value.__context__)


# --- signals --------------------------------------------------------------

def test_a_signal_during_release_lets_it_finish_then_exits_with_the_signals_code():
    unwind_on_hangup_and_term()
    handler = signal.getsignal(signal.SIGTERM)
    fired = []

    def on_post(body):
        if body == RELEASE and not fired:
            fired.append(1)
            os.kill(os.getpid(), signal.SIGTERM)
            os.kill(os.getpid(), signal.SIGHUP)

    s = FakeSession(post_script=[409], on_post=on_post)
    with pytest.raises(SystemExit) as err, _pin(s):
        pass
    assert fired
    assert err.value.code == 128 + signal.SIGTERM == 143
    assert s.endpoint["workersMin"] == 0
    assert signal.getsignal(signal.SIGTERM) is handler


def test_a_signal_during_release_supersedes_an_ordinary_body_exception():
    unwind_on_hangup_and_term()
    s = FakeSession(on_post=lambda body: body == RELEASE and os.kill(os.getpid(), signal.SIGTERM))
    with pytest.raises(SystemExit) as err, _pin(s):
        raise RuntimeError("the measurement broke")
    assert err.value.code == 143
    assert isinstance(err.value.__context__, RuntimeError)
    assert s.endpoint["workersMin"] == 0


def test_the_first_signal_unwinds_and_a_second_during_release_keeps_its_code():
    unwind_on_hangup_and_term()
    s = FakeSession()
    state = {"released_posts": 0}

    def on_post(body):
        if body == RELEASE:
            state["released_posts"] += 1
            os.kill(os.getpid(), signal.SIGTERM)

    s.on_post = on_post
    with pytest.raises(SystemExit) as err, _pin(s):
        os.kill(os.getpid(), signal.SIGHUP)
        pytest.fail("the signal handler should have raised SystemExit")
    assert err.value.code == 128 + signal.SIGHUP
    assert state["released_posts"] == 1
    assert s.endpoint["workersMin"] == 0
    # The first signal's handler left both ignored, and release() restored that.
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_IGN
    assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN


def test_a_signal_outranks_a_keyboard_interrupt_during_release():
    unwind_on_hangup_and_term()
    s = FakeSession(on_post=lambda body: body == RELEASE and os.kill(os.getpid(), signal.SIGHUP))
    p = _pinned(s)
    s.post_script = [KeyboardInterrupt()]
    with pytest.raises(SystemExit) as err:
        p.release()
    assert err.value.code == 128 + signal.SIGHUP
    assert s.endpoint["workersMin"] == 0


def test_a_release_error_is_raised_in_preference_to_a_deferred_signal_and_notes_it():
    unwind_on_hangup_and_term()
    s = FakeSession(ignore_release=True,
                    on_post=lambda body: body == RELEASE and os.kill(os.getpid(), signal.SIGTERM))
    p = _pinned(s)
    with pytest.raises(ReleaseFailed, match="signal 15 also arrived"):
        p.release()


def test_release_restores_the_previous_handlers_even_when_it_fails():
    marker = signal.getsignal(signal.SIGTERM)
    s = FakeSession(ignore_release=True)
    p = _pinned(s)
    with pytest.raises(ReleaseFailed):
        p.release()
    assert signal.getsignal(signal.SIGTERM) is marker


def test_a_keyboard_interrupt_during_release_is_deferred_until_it_finishes():
    s = FakeSession()
    p = _pinned(s)
    s.post_script = [KeyboardInterrupt()]
    with pytest.raises(KeyboardInterrupt):
        p.release()
    assert s.endpoint["workersMin"] == 0


def test_a_keyboard_interrupt_during_a_backoff_sleep_is_deferred_too():
    s = FakeSession()
    interrupts = [KeyboardInterrupt()]

    def sleep(_):
        if interrupts:
            raise interrupts.pop()

    p = WorkerPin(EID, "key", workers=2, session=s, clock=Clock().clock, sleep=sleep)
    p.preflight()
    p.pin()
    s.post_script = [409]
    with pytest.raises(KeyboardInterrupt):
        p.release()
    assert s.endpoint["workersMin"] == 0


def test_release_works_off_the_main_thread_without_touching_signals():
    s = FakeSession()
    p = _pinned(s)
    out = []

    def run():
        try:
            out.append(p.release())
        except BaseException as e:  # noqa: BLE001 - the thread must report, not die
            out.append(e)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    assert out[0]["workersMin"] == 0


def test_a_changed_workers_max_keeps_the_bodys_exception_as_visible_context():
    s = FakeSession()
    with pytest.raises(RuntimeError, match="workersMax is 5") as err, _pin(s):
        s.endpoint["workersMax"] = 5
        raise RuntimeError("the measurement broke")
    assert err.value.__suppress_context__ is False
    assert str(err.value.__context__) == "the measurement broke"
    assert s.endpoint["workersMin"] == 0
