"""The artifact-2 reconnaissance capture, proven without a network.

Every property tested here is one whose failure costs money or corrupts the
evidence: a capture that spends against a misconfigured endpoint, leaves a
worker pinned and billing, writes the API key into a committed fixture, or
polls before every job of a burst is submitted (which would serialise the
burst and answer Q2 about the wrong experiment).
"""

import itertools
import json
import signal
import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "recon"))

import capture_a2

EID = "ep-test"
KEY = "sk-THIS-MUST-NEVER-REACH-DISK"
HF_TOKEN = "hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7"
RPA_TOKEN = "rpa_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"
GOOD_ENDPOINT = {"id": EID, "flashboot": False, "workersMin": 0, "workersMax": 2,
                 "idleTimeout": 5}
COMPILE_LINE = "torch.compile took 1.00 s in total"
# Real vLLM lines of the kind Task 4 parses, with `hf_` in them but no secret.
WEIGHTS_LINE = "Time spent downloading weights for Qwen/Qwen3-8B via hf_transfer: 41.2 seconds"
OVERRIDES_LINE = "Initializing an LLM engine with config: model='Qwen/Qwen3-8B', hf_overrides={}"


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class HtmlResponse:
    """A gateway's error page served with a 2xx: not JSON at all."""

    status_code = 200
    text = "<html><body>502 Bad Gateway</body></html>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


class FakeSession:
    """Scripted RunPod. `endpoint` is mutated by /update, as the real one is.

    `scripts` maps "run", "update" or "endpoint" to an iterator of steps, one
    consumed per such call: None behaves normally, an int answers with that
    status code and changes nothing, a response object is returned as-is and
    changes nothing, an exception is raised. An exhausted script behaves
    normally.
    """

    def __init__(self, endpoint=None, health_status=200, health_raises=False,
                 ignore_release=False, scripts=None, status_code=200,
                 slow_jobs=None, never_finish=(), log_lines=None):
        self.endpoint = dict(endpoint or GOOD_ENDPOINT)
        self.health_status = health_status
        self.health_raises = health_raises
        self.ignore_release = ignore_release
        self.scripts = {name: iter(steps) for name, steps in (scripts or {}).items()}
        self.status_code = status_code
        self.slow_jobs = dict(slow_jobs or {})
        self.never_finish = set(never_finish)
        self.log_lines = log_lines or [COMPILE_LINE]
        self.calls = []
        self._jobs = itertools.count(1)

    def _step(self, name):
        step = next(self.scripts[name], None) if name in self.scripts else None
        if isinstance(step, BaseException):
            raise step
        return step

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url, None))
        if url.endswith(f"/endpoints/{EID}"):
            code = self._step("endpoint")
            if isinstance(code, int):
                return FakeResponse(code, {"error": "scripted"})
            if code is not None:
                return code
            return FakeResponse(200, json.loads(json.dumps(self.endpoint)))
        if url.endswith("/health"):
            if self.health_raises:
                raise requests.ConnectionError("health endpoint dropped the connection")
            if self.health_status != 200:
                return FakeResponse(self.health_status, {"error": "not found"})
            return FakeResponse(200, {"workers": {"running": self.endpoint["workersMin"]}})
        if "/status/" in url:
            job = url.rsplit("/", 1)[1]
            if self.status_code != 200:
                return FakeResponse(self.status_code, {"error": "no such job"})
            if job in self.never_finish or self.slow_jobs.get(job, 0) > 0:
                self.slow_jobs[job] = self.slow_jobs.get(job, 0) - 1
                return FakeResponse(200, {"id": job, "status": "IN_PROGRESS"})
            return FakeResponse(200, {
                "id": job, "status": "COMPLETED", "workerId": f"w-{job}",
                "delayTime": 100, "executionTime": 5000,
                "output": {"log_lines": list(self.log_lines)},
            })
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers, json, timeout):
        self.calls.append(("POST", url, json))
        if url.endswith("/run"):
            code = self._step("run")
            if code is not None:
                return FakeResponse(code, {"error": "scripted"})
            return FakeResponse(200, {"id": f"job{next(self._jobs)}"})
        if url.endswith("/update"):
            code = self._step("update")
            if isinstance(code, int):
                return FakeResponse(code, {"error": "scripted"})
            if code is not None:
                return code
            if not (self.ignore_release and json.get("workersMin") == 0):
                self.endpoint.update(json)
            return FakeResponse(200, dict(self.endpoint))
        raise AssertionError(f"unexpected POST {url}")


class FakeClock:
    """Time that moves only when the capture reads it (by one tick) or sleeps.

    Each sleep is logged with the number of platform calls made before it, so
    a test can say which calls a sleep fell between. Real time is never spent.
    """

    def __init__(self, session):
        self.now = 0.0
        self.session = session
        self.sleeps = []

    def clock(self):
        self.now += 1.0
        return self.now

    def sleep(self, seconds):
        self.sleeps.append((seconds, len(self.session.calls)))
        self.now += seconds


def _capture(tmp_path, session, clock=None):
    clock = clock or FakeClock(session)
    return capture_a2.Capture(
        EID, KEY, out=tmp_path / "a2_recon", workers=2, session=session,
        clock=clock.clock, sleep=clock.sleep,
    )


def _posts(session, suffix):
    return [body for method, url, body in session.calls if method == "POST" and url.endswith(suffix)]


def _urls(session):
    return [url for _, url, _ in session.calls]


def _runs(session):
    return [i for i, url in enumerate(_urls(session)) if url.endswith("/run")]


def _chain(exc):
    seen = []
    while exc is not None:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


def _entries(tmp_path):
    log = tmp_path / "a2_recon" / "capture.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()]


def _pinned_then_release_fails(*restore_steps):
    """The pin lands, then the scale phase's release is rejected, so the
    endpoint is left at workersMin 2 when the `finally` restore begins --
    the failure that bills. `restore_steps` script the restore's POSTs."""
    return {"update": itertools.chain([None, 400], restore_steps)}


# --- preflight ------------------------------------------------------------


@pytest.mark.parametrize("override, word", [
    ({"flashboot": True}, "flashboot"),
    ({"workersMin": 1}, "workersMin"),
    ({"workersMax": 1}, "workersMax"),
    ({"idleTimeout": 60}, "idleTimeout"),
    ({"idleTimeout": None}, "idleTimeout"),
])
def test_it_refuses_to_spend_against_a_misconfigured_endpoint(tmp_path, override, word):
    """FlashBoot on measures RunPod's cache instead of a cold start;
    workersMin > 0 keeps a worker warm between bursts; workersMax below the
    burst size makes the burst a queue; an idleTimeout not below the idle
    wait lets burst2 reuse burst1's live containers. Each produces a
    plausible, wrong answer to Q2. Nothing may be submitted or updated."""
    session = FakeSession(dict(GOOD_ENDPOINT, **override))
    with pytest.raises(capture_a2.RefuseToSpend, match=word):
        _capture(tmp_path, session).run()
    assert [c for c in session.calls if c[0] == "POST"] == []


def test_a_burst_of_one_is_refused(tmp_path):
    """One worker cannot demonstrate that the platform starts DISTINCT
    workers, which is the whole of Q2's first half."""
    with pytest.raises(ValueError, match="at least 2"):
        capture_a2.Capture(EID, KEY, out=tmp_path, workers=1, session=FakeSession())


# --- protocol order -------------------------------------------------------


def test_every_burst_submits_all_its_jobs_before_polling_any(tmp_path):
    """Polling job 1 to completion before submitting job 2 serialises the
    burst, which reproduces artifact 1's one-worker result by construction
    and answers Q2 about the wrong experiment. Checked for both bursts."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    urls, runs = _urls(session), _runs(session)
    assert len(runs) == 4
    for first, last in [(runs[0], runs[1]), (runs[2], runs[3])]:
        assert not any("/status/" in url for url in urls[first:last])
    assert any("/status/" in url for url in urls[runs[1]:runs[2]])


def test_a_burst_polls_its_jobs_round_robin(tmp_path):
    """Awaiting job 1 to completion before polling job 2 lets a job that
    finished early sit unread while a slow one runs, and RunPod keeps an
    async result only for a limited window."""
    session = FakeSession(slow_jobs={"job1": 3})
    _capture(tmp_path, session).run()
    polls = [url.rsplit("/", 1)[1] for url in _urls(session) if "/status/" in url]
    burst1 = polls[: polls.index("job3")]
    last_job1 = len(burst1) - 1 - burst1[::-1].index("job1")
    assert burst1.index("job2") < last_job1


def test_the_idle_wait_falls_between_the_bursts(tmp_path):
    """Without it burst2 lands on burst1's still-live containers and measures
    container survival, not host affinity."""
    session = FakeSession()
    clock = FakeClock(session)
    _capture(tmp_path, session, clock).run()
    urls, runs = _urls(session), _runs(session)
    last_burst1_poll = max(i for i, url in enumerate(urls[: runs[2]]) if "/status/" in url)
    assert any(
        seconds == capture_a2.IDLE_WAIT_SECONDS and last_burst1_poll < position <= runs[2]
        for seconds, position in clock.sleeps
    )


def test_the_scale_phase_pins_then_releases_then_restores(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert _posts(session, "/update") == [
        {"workersMin": 2}, {"workersMin": 0}, {"workersMin": 0},
    ]


def test_health_is_observed_while_pinned(tmp_path):
    """The pinned window is Q1's evidence: what the platform reports while
    workersMin is raised. A capture that released straight after pinning
    would pay for the pin and observe nothing."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    updates = [i for i, (_, url, _) in enumerate(session.calls) if url.endswith("/update")]
    pin, release = updates[0], updates[1]
    assert session.calls[pin][2] == {"workersMin": 2}
    assert any(url.endswith("/health") for url in _urls(session)[pin:release])


def test_workers_max_is_never_written(tmp_path):
    """workersMax is the cost ceiling the operator chose. A capture that
    raised it would be spending beyond what was authorised."""
    session = FakeSession()
    _capture(tmp_path, session).run()
    assert all("workersMax" not in body for body in _posts(session, "/update"))


# --- transient and fatal responses ----------------------------------------


def test_a_409_is_retried(tmp_path):
    """RunPod answers 409 for a while after any configuration change. A
    capture that aborted on one would waste the burst it had begun."""
    session = FakeSession(scripts={"run": [409]})
    _capture(tmp_path, session).run()
    assert len(_runs(session)) == 5
    assert any(e["url"].endswith("/run") and e["status_code"] == 409 for e in _entries(tmp_path))
    assert len(list((tmp_path / "a2_recon").glob("burst*.json"))) == 4


def test_a_failed_status_poll_aborts_and_restores(tmp_path):
    """A status the platform will not return is a job this capture cannot
    account for. Carrying on would run burst2 beside it."""
    session = FakeSession(status_code=404)
    with pytest.raises(RuntimeError, match="returned 404"):
        _capture(tmp_path, session).run()
    assert len(_runs(session)) == 2
    assert _posts(session, "/update")[-1] == {"workersMin": 0}


def test_a_timed_out_job_is_saved_as_a_timeout_and_stops_the_run(tmp_path):
    """A job still running at its deadline has no result. Writing its last
    status as `burst1_0.json` would present a non-terminal status as one, and
    running burst2 beside it would put a third job on the platform."""
    session = FakeSession(never_finish={"job1"})
    clock = FakeClock(session)
    with pytest.raises(capture_a2.JobTimedOut, match="burst1"):
        _capture(tmp_path, session, clock).run()
    out = tmp_path / "a2_recon"
    assert sorted(p.name for p in out.glob("burst*")) == ["burst1_0.timeout.json", "burst1_1.json"]
    assert json.loads((out / "burst1_0.timeout.json").read_text())["status"] == "IN_PROGRESS"
    assert clock.now >= capture_a2.JOB_TIMEOUT_SECONDS
    assert len(_runs(session)) == 2
    assert _posts(session, "/update") == [{"workersMin": 0}]


def test_a_health_error_is_recorded_and_the_window_continues(tmp_path):
    """One dropped connection on `/health` must not abort a 20-minute
    observation window whose other polls are the evidence."""
    session = FakeSession(health_raises=True)
    _capture(tmp_path, session).run()
    errors = [e for e in _entries(tmp_path) if e["url"].endswith("/health")]
    assert len(errors) > 2
    assert all("ConnectionError" in e["error"] for e in errors)
    assert session.endpoint["workersMin"] == 0


def test_a_missing_health_endpoint_is_recorded_not_fatal(tmp_path):
    """`GET /v2/{id}/health` is the one platform call this repository has
    never exercised. If it does not exist, that is a Q1 finding -- worker
    counts are not observable that way -- and the job-level workerIds remain.
    It must not abort the capture."""
    session = FakeSession(health_status=404)
    _capture(tmp_path, session).run()
    assert any(e["url"].endswith("/health") and e["status_code"] == 404 for e in _entries(tmp_path))


# --- restore --------------------------------------------------------------


def test_workers_min_is_restored_when_a_phase_fails(tmp_path):
    """The failure must still propagate -- a swallowed error would read as a
    completed capture -- and the restore must still be attempted."""
    session = FakeSession(scripts={"run": [requests.ConnectionError("run dropped")]})
    with pytest.raises(requests.ConnectionError, match="run dropped"):
        _capture(tmp_path, session).run()
    assert _posts(session, "/update") == [{"workersMin": 0}]
    assert session.endpoint["workersMin"] == 0


def test_a_phase_failure_while_pinned_is_restored(tmp_path):
    """A pinned worker bills by the second whether or not anything runs on
    it. This is the failure that costs: the endpoint is at workersMin 2."""
    session = FakeSession(scripts=_pinned_then_release_fails())
    with pytest.raises(RuntimeError, match="returned 400") as caught:
        _capture(tmp_path, session).run()
    assert "RESTORE FAILED" not in str(caught.value)
    assert session.endpoint["workersMin"] == 0


def test_restore_survives_a_dropped_connection(tmp_path):
    session = FakeSession(scripts=_pinned_then_release_fails(
        requests.ConnectionError("restore dropped")))
    with pytest.raises(RuntimeError, match="returned 400"):
        _capture(tmp_path, session).run()
    assert session.endpoint["workersMin"] == 0


def test_restore_outlasts_the_old_retry_budget(tmp_path):
    """The generic retry gives up after five attempts and 15 s of backoff.
    RunPod answers 409 for a while after ANY configuration change -- and the
    restore always follows one."""
    session = FakeSession(scripts=_pinned_then_release_fails(*[409] * 8))
    clock = FakeClock(session)
    with pytest.raises(RuntimeError, match="returned 400"):
        _capture(tmp_path, session, clock).run()
    assert len(_posts(session, "/update")) == 2 + 8 + 1
    assert session.endpoint["workersMin"] == 0
    # An uncapped doubling would spend the budget on a few long waits and
    # re-check a billing endpoint less and less often.
    first_restore_post = [i for i, url in enumerate(_urls(session)) if url.endswith("/update")][2]
    restore_sleeps = [s for s, position in clock.sleeps if position > first_restore_post]
    assert len(restore_sleeps) == 8
    assert max(restore_sleeps) <= capture_a2.RESTORE_BACKOFF_CAP_SECONDS


def test_a_rejected_restore_fails_at_once(tmp_path):
    """A 400 will not turn into a 200 by waiting. Retrying it for five
    minutes would only delay telling the operator the endpoint may bill."""
    session = FakeSession(scripts={"update": [None, None, 400]})
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        _capture(tmp_path, session).run()
    assert len(_posts(session, "/update")) == 2 + 1


def test_a_lagging_re_read_is_released_again(tmp_path):
    """An accepted write can take a moment to show on a re-read. That is not
    a failure: release again and re-read."""
    lagging = FakeResponse(200, dict(GOOD_ENDPOINT, workersMin=2))
    session = FakeSession(scripts={"endpoint": [None, lagging]})
    _capture(tmp_path, session).run()
    assert _posts(session, "/update") == [{"workersMin": n} for n in (2, 0, 0, 0)]
    assert session.endpoint["workersMin"] == 0


def test_a_re_read_that_is_not_json_is_a_restore_failure(tmp_path):
    """A gateway can answer 2xx with an HTML page. That proves nothing about
    workersMin; it must end in RESTORE FAILED, not an AttributeError that
    does not tell the operator to look."""
    session = FakeSession(scripts={"endpoint": itertools.chain(
        [None], itertools.repeat(HtmlResponse()))})
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        _capture(tmp_path, session).run()


def test_a_restore_that_never_succeeds_names_the_recovery_command(tmp_path):
    """The operator has to act, and the phase error that started it must not
    be lost: both have to reach the traceback."""
    session = FakeSession(scripts=_pinned_then_release_fails(*itertools.repeat(409, 1000)))
    with pytest.raises(RuntimeError, match="RESTORE FAILED") as caught:
        _capture(tmp_path, session).run()
    assert "--restore" in str(caught.value)
    assert any("returned 400" in str(e) for e in _chain(caught.value)[1:])
    assert session.endpoint["workersMin"] == 2


def test_a_failed_verification_read_is_a_restore_failure(tmp_path):
    """The release is only known to have landed once the endpoint is re-read.
    A re-read that fails leaves the operator not knowing whether it bills,
    and a bare Timeout would not tell them to look."""
    session = FakeSession(scripts={"endpoint": itertools.chain(
        [None], itertools.repeat(requests.Timeout("read timed out")))})
    with pytest.raises(RuntimeError, match="RESTORE FAILED") as caught:
        _capture(tmp_path, session).run()
    assert isinstance(caught.value.__cause__, requests.Timeout)


def test_a_restore_that_does_not_land_is_loud(tmp_path):
    session = FakeSession(ignore_release=True)
    with pytest.raises(RuntimeError, match="RESTORE FAILED"):
        _capture(tmp_path, session).run()


def test_restore_checks_workers_max_is_unchanged(tmp_path):
    """The capture never writes workersMax. If it changed anyway, the run's
    evidence was collected under a cost ceiling nobody checked."""

    class CeilingMoves(FakeSession):
        def post(self, url, headers, json, timeout):
            response = super().post(url, headers, json, timeout)
            if json == {"workersMin": 2}:
                self.endpoint["workersMax"] = 5
            return response

    session = CeilingMoves()
    with pytest.raises(RuntimeError, match="workersMax"):
        _capture(tmp_path, session).run()
    assert session.endpoint["workersMin"] == 0


# --- the evidence directory -----------------------------------------------


def test_out_is_anchored_to_the_repository():
    """Relative to the working directory, a run from anywhere but the repo
    root would scatter the evidence where nobody commits it."""
    assert REPO / "fixtures" / "a2_recon" == capture_a2.OUT


def test_a_non_empty_output_directory_is_refused(tmp_path):
    out = tmp_path / "a2_recon"
    out.mkdir()
    (out / "capture.jsonl").write_text("an earlier run\n")
    session = FakeSession()
    with pytest.raises(capture_a2.RefuseToSpend, match="mix"):
        _capture(tmp_path, session).run()
    assert session.calls == []
    assert (out / "capture.jsonl").read_text() == "an earlier run\n"


def test_every_platform_response_is_recorded(tmp_path):
    session = FakeSession()
    _capture(tmp_path, session).run()
    entries = _entries(tmp_path)
    assert len(entries) == len(session.calls)
    assert set(entries[0]) == {"t", "t_sent", "method", "url", "request", "status_code", "response"}
    assert entries[0]["t_sent"] <= entries[0]["t"]


def test_each_job_status_is_saved_verbatim(tmp_path):
    _capture(tmp_path, FakeSession()).run()
    saved = sorted(p.name for p in (tmp_path / "a2_recon").glob("burst*.json"))
    assert saved == ["burst1_0.json", "burst1_1.json", "burst2_0.json", "burst2_1.json"]
    assert json.loads((tmp_path / "a2_recon" / "burst1_0.json").read_text())["workerId"]


def test_no_secret_reaches_disk(tmp_path):
    """Everything under the output directory is destined for fixtures/, which
    is committed. Request headers carry the key and are never recorded; the
    endpoint read returns its template, whose env holds the HF token; and a
    token can surface in a log line."""
    endpoint = dict(GOOD_ENDPOINT, template={"id": "t", "env": [f"HF_TOKEN={HF_TOKEN}"]})
    session = FakeSession(endpoint, log_lines=[
        f"login {HF_TOKEN}", f"auth {KEY}", f"api {RPA_TOKEN}.",
        WEIGHTS_LINE, OVERRIDES_LINE, COMPILE_LINE])
    _capture(tmp_path, session).run()
    out = tmp_path / "a2_recon"
    for path in out.rglob("*"):
        if path.is_file():
            text = path.read_text()
            for secret in (KEY, HF_TOKEN, RPA_TOKEN):
                assert secret not in text, f"{path.name} contains {secret[:4]}..."
    # The secret is replaced where it sits; the line around it, and every line
    # merely mentioning `hf_`, is evidence Task 4 parses and survives intact.
    assert json.loads((out / "burst1_0.json").read_text())["output"]["log_lines"] == [
        "login <redacted>", "auth <redacted>", "api <redacted>.",
        WEIGHTS_LINE, OVERRIDES_LINE, COMPILE_LINE]
    assert _entries(tmp_path)[0]["response"]["template"]["env"] == "<redacted>"


# --- the command line -----------------------------------------------------


@pytest.fixture
def main_env(monkeypatch):
    """Fake credentials, and signal handlers captured rather than installed
    into the test process."""
    monkeypatch.setenv("RUNPOD_API_KEY", KEY)
    monkeypatch.setenv("RUNPOD_A2_ENDPOINT_ID", EID)
    installed = {}
    monkeypatch.setattr(capture_a2.signal, "signal",
                        lambda signum, handler: installed.__setitem__(signum, handler))
    return installed


def test_a_sigterm_while_pinned_still_restores(tmp_path, main_env):
    """By default SIGTERM and SIGHUP end the process without unwinding, so
    the `finally` restore never runs and the pin keeps billing."""

    class KilledWhilePinned(FakeSession):
        def post(self, url, headers, json, timeout):
            response = super().post(url, headers, json, timeout)
            if json == {"workersMin": 2}:
                main_env[signal.SIGTERM](signal.SIGTERM, None)
            return response

    session = KilledWhilePinned()
    clock = FakeClock(session)
    with pytest.raises(SystemExit):
        capture_a2.main([], session=session, out=tmp_path / "a2_recon",
                        clock=clock.clock, sleep=clock.sleep)
    # A closing terminal often sends more than one signal. After the first,
    # both are ignored, so a second cannot interrupt the restore it started.
    assert main_env == {signal.SIGTERM: signal.SIG_IGN, signal.SIGHUP: signal.SIG_IGN}
    assert session.endpoint["workersMin"] == 0


def test_preflight_only_records_nothing(tmp_path, main_env, capsys):
    out = tmp_path / "a2_recon"
    endpoint = dict(GOOD_ENDPOINT, template={"env": [f"HF_TOKEN={HF_TOKEN}"]})
    session = FakeSession(endpoint)
    capture_a2.main(["--preflight-only"], session=session, out=out)
    assert not out.exists()
    assert [c[0] for c in session.calls] == ["GET"]
    printed = capsys.readouterr().out
    assert EID in printed
    assert HF_TOKEN not in printed


def test_the_restore_flag_only_releases(tmp_path, main_env, capsys):
    """The recovery command after a RESTORE FAILED: it must do nothing but
    release, and must not need the evidence directory to be empty."""
    out = tmp_path / "a2_recon"
    session = FakeSession(dict(GOOD_ENDPOINT, workersMin=2))
    capture_a2.main(["--restore"], session=session, out=out)
    assert session.endpoint["workersMin"] == 0
    assert [(m, body) for m, _, body in session.calls] == [
        ("POST", {"workersMin": 0}), ("GET", None)]
    assert not out.exists()
    assert '"workersMin": 0' in capsys.readouterr().out
