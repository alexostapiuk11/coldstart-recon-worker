"""Pin a serverless endpoint's standing workers, and always release them.

Reconnaissance (docs/recon-a2.md) showed `workersMin` pins workers through
`POST /endpoints/{id}/update`, acknowledged synchronously, and that a pinned
worker bills by the second whether or not anything runs on it. This is the
pin a measurement holds for its duration, then releases.

`workersMax` is never written: it is the cost ceiling, set by the person who
provisioned the endpoint. A fixed-capacity run needs `workersMax == N` so the
platform cannot add workers under load, so the preflight requires it and the
release checks it did not change.

The release copies recon/capture_a2.py's semantics; recon keeps its own copy
because it imports nothing from this repository by design. The release and
its verifying re-read are retried together until a deadline, because RunPod
answers 409 for a while after any configuration change and the release
always follows one. "The POST returned 200" is not proof: only a re-read
showing 0 is. A refusal retrying cannot fix fails at once, with the manual
remedy in the message.
"""

import itertools
import signal
import time

import requests

REST = "https://rest.runpod.io/v1"
RELEASE_DEADLINE_SECONDS = 300.0
BACKOFF_CAP_SECONDS = 30.0
PIN_ATTEMPTS = 5


class PinRefused(RuntimeError):
    """The endpoint is not in the state a pinned run needs; nothing was written."""


class ReleaseFailed(RuntimeError):
    """workersMin could not be confirmed back at 0; a worker may still be billing."""


class _Retryable(Exception):
    pass


def _transient(status: int) -> bool:
    return status == 409 or status >= 500


class WorkerPin:
    def __init__(self, endpoint_id: str, api_key: str, *, workers: int, session=requests,
                 clock=time.monotonic, sleep=time.sleep):
        if type(workers) is not int or workers < 1:
            raise ValueError(f"workers is {workers!r}; a pin is a positive int of workers")
        self._id = endpoint_id
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._workers = workers
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._workers_max = None

    @property
    def workers(self) -> int:
        return self._workers

    def _url(self, suffix: str = "") -> str:
        return f"{REST}/endpoints/{self._id}{suffix}"

    def endpoint(self) -> dict:
        r = self._session.get(self._url(), headers=self._headers, timeout=30)
        if not 200 <= r.status_code < 300:
            raise PinRefused(f"GET endpoint {self._id} returned {r.status_code}")
        return r.json()

    def preflight(self) -> dict:
        ep = self.endpoint()
        problems = []
        if ep.get("workersMin") != 0:
            problems.append(
                f"workersMin is {ep.get('workersMin')!r}, not 0: something already holds "
                "workers, and this run would release them when it ends")
        if ep.get("workersMax") != self._workers:
            problems.append(
                f"workersMax is {ep.get('workersMax')!r}, not {self._workers}: a fixed-capacity "
                "run needs the ceiling equal to the pin, or the platform can add workers under "
                "load. workersMax is the owner's to set; this code never writes it")
        if problems:
            raise PinRefused("; ".join(problems))
        self._workers_max = ep["workersMax"]
        return ep

    def pin(self) -> dict:
        for attempt in range(PIN_ATTEMPTS):
            r = self._session.post(self._url("/update"), headers=self._headers,
                                   json={"workersMin": self._workers}, timeout=30)
            if _transient(r.status_code) and attempt < PIN_ATTEMPTS - 1:
                self._sleep(2.0**attempt)
                continue
            if not 200 <= r.status_code < 300:
                raise RuntimeError(f"the pin POST returned {r.status_code}")
            break
        ep = self.endpoint()
        if ep.get("workersMin") != self._workers:
            raise RuntimeError(
                f"the re-read after the pin shows workersMin {ep.get('workersMin')!r}, not "
                f"{self._workers}; the run would measure a fleet it did not pin")
        return ep

    def _release_once(self) -> dict:
        r = self._session.post(self._url("/update"), headers=self._headers,
                               json={"workersMin": 0}, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the release POST returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise ReleaseFailed(self._manual(f"the release POST returned {r.status_code}"))
        r = self._session.get(self._url(), headers=self._headers, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the verifying re-read returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise ReleaseFailed(self._manual(f"the verifying re-read returned {r.status_code}"))
        try:
            ep = r.json()
        except ValueError as e:
            raise _Retryable(f"the verifying re-read was not JSON ({e})") from e
        if not isinstance(ep, dict):
            raise _Retryable(f"the verifying re-read was not an endpoint object: {str(ep)[:80]!r}")
        if ep.get("workersMin") != 0:
            # Possibly propagation lag after an accepted write; POST again.
            raise _Retryable(f"the re-read shows workersMin {ep.get('workersMin')!r}")
        return ep

    def _manual(self, cause: str) -> str:
        return (f"RELEASE FAILED: could not confirm workersMin is 0 on endpoint {self._id} "
                f"(last: {cause}). Set it to 0 by hand now; a pinned worker bills "
                "continuously whether or not anything is running on it")

    def release(self) -> dict:
        deadline = self._clock() + RELEASE_DEADLINE_SECONDS
        for attempt in itertools.count():
            try:
                ep = self._release_once()
                break
            except (_Retryable, requests.RequestException) as e:
                wait = min(2.0**attempt, BACKOFF_CAP_SECONDS)
                if self._clock() + wait > deadline:
                    raise ReleaseFailed(self._manual(str(e))) from e
                self._sleep(wait)
        if self._workers_max is not None and ep.get("workersMax") != self._workers_max:
            raise RuntimeError(
                f"workersMax is {ep.get('workersMax')!r} after the run but was "
                f"{self._workers_max!r} at preflight. workersMin is back to 0, but this code "
                "never writes workersMax, so something else changed the cost ceiling during "
                "the run: treat its evidence as collected under a ceiling nobody checked")
        return ep

    def __enter__(self):
        self.preflight()
        try:
            self.pin()
        except BaseException:
            self.release()
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def _exit_on_signal(signum, frame):
    for other in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(other, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def unwind_on_hangup_and_term() -> None:
    """Make SIGTERM and SIGHUP unwind through a `with WorkerPin(...)` release.

    By default both end the process without unwinding, leaving workers pinned
    and billing. Raising SystemExit from a handler turns them into an ordinary
    unwind; the first one ignores any that follow, so a second signal cannot
    cut the bounded release short. `kill -9` cannot be handled: release by hand.
    """
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on_signal)
