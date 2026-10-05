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

import contextlib
import itertools
import signal
import threading
import time

import requests

REST = "https://rest.runpod.io/v1"
RELEASE_DEADLINE_SECONDS = 300.0
PIN_DEADLINE_SECONDS = 120.0
BACKOFF_CAP_SECONDS = 30.0
_MAX_BACKOFF_EXPONENT = 10


class PinRefused(RuntimeError):
    """The endpoint is not in the state a pinned run needs; nothing was written."""


class PinFailed(RuntimeError):
    """The pin could not be confirmed; workersMin may or may not have been written."""


class ReleaseFailed(RuntimeError):
    """workersMin could not be confirmed back at 0; a worker may still be billing."""


class EndpointReadError(RuntimeError):
    """The endpoint could not be read; says nothing about whether anything was written.

    Neutral on purpose: the same read happens before any write (a refusal,
    nothing changed) and after the pin's write (workersMin may be N), so the
    caller, not the reader, decides what the failure means.
    """

    def __init__(self, message: str, *, status: int | None):
        super().__init__(message)
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status is None or _transient(self.status)


class _Retryable(Exception):
    pass


def _transient(status: int) -> bool:
    return status == 409 or status >= 500


def _is_int(value, expected: int) -> bool:
    # `False == 0` and `0.0 == 0` in Python: a JSON `false` or `0.0` in
    # workersMin would read as "released" and pass a check that proves nothing.
    return type(value) is int and value == expected


@contextlib.contextmanager
def _term_and_hangup_deferred():
    """Record SIGTERM and SIGHUP for the duration instead of acting on them.

    Yields a list that holds the first signal number received, if any; the
    caller raises it once its critical section is done and the previous
    handlers are back. Swallowing the signal (SIG_IGN) was rejected: a caller
    looping over several paid repeats would see a normal return after an
    explicit kill and start the next pin.

    Only on the main thread: `signal.signal` raises anywhere else, and a
    handler can only fire on the main thread anyway.
    """
    received: list[int] = []
    if threading.current_thread() is not threading.main_thread():
        yield received
        return

    def record(signum, frame):
        if not received:
            received.append(signum)

    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    for signum in previous:
        signal.signal(signum, record)
    try:
        yield received
    finally:
        for signum, handler in previous.items():
            # getsignal() is None for a handler not installed from Python.
            signal.signal(signum, signal.SIG_DFL if handler is None else handler)


def _backoff(attempt: int) -> float:
    return min(2.0 ** min(attempt, _MAX_BACKOFF_EXPONENT), BACKOFF_CAP_SECONDS)


class WorkerPin:
    """Hold `workersMin == N` on an endpoint whose owner set `workersMax == N`.

    As a context manager it preflights, pins, and releases on every exit:
    normal, exception, `SystemExit` from `unwind_on_hangup_and_term()`, and a
    pin that failed half way. Plain try/finally in each caller was rejected:
    one forgotten release leaves a GPU billing until someone notices.
    """

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
            raise EndpointReadError(
                f"GET endpoint {self._id} returned {r.status_code}, so its workersMin and "
                "workersMax are unknown and nothing built on them can be trusted",
                status=r.status_code)
        try:
            ep = r.json()
        except ValueError as e:
            raise EndpointReadError(
                f"GET endpoint {self._id} returned a {r.status_code} that was not JSON ({e}); "
                "its workersMin and workersMax are unknown", status=None) from e
        if not isinstance(ep, dict):
            raise EndpointReadError(
                f"GET endpoint {self._id} returned {str(ep)[:80]!r}, not an endpoint object "
                "(a gateway page?); its workersMin and workersMax are unknown", status=None)
        return ep

    def preflight(self) -> dict:
        try:
            ep = self.endpoint()
        except EndpointReadError as e:
            raise PinRefused(f"{e}. Nothing was written; the run was refused rather than "
                             "started blind") from e
        problems = []
        if not _is_int(ep.get("workersMin"), 0):
            problems.append(
                f"workersMin is {ep.get('workersMin')!r}, not 0: something already holds "
                "workers, and this run would release them when it ends")
        if not _is_int(ep.get("workersMax"), self._workers):
            problems.append(
                f"workersMax is {ep.get('workersMax')!r}, not {self._workers}: a fixed-capacity "
                "run needs the ceiling equal to the pin, or the platform can add workers under "
                "load. workersMax is the owner's to set; this code never writes it")
        if problems:
            raise PinRefused("; ".join(problems))
        self._workers_max = ep["workersMax"]
        return ep

    def _pin_once(self) -> dict:
        r = self._session.post(self._url("/update"), headers=self._headers,
                               json={"workersMin": self._workers}, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the pin POST returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise PinFailed(
                f"the pin POST returned {r.status_code}, which retrying will not fix: the "
                "workers were not pinned, and a run started anyway would measure a fleet "
                "it did not hold")
        try:
            ep = self.endpoint()
        except EndpointReadError as e:
            if e.retryable:
                raise _Retryable(str(e)) from e
            raise
        if not _is_int(ep.get("workersMin"), self._workers):
            raise _Retryable(f"the re-read after the pin shows workersMin "
                             f"{ep.get('workersMin')!r}, not {self._workers}")
        return ep

    def pin(self) -> dict:
        """Write `workersMin = N` and prove it with a re-read, retrying to a deadline.

        RunPod answers 409 for a while after any configuration change, and the
        owner has just set `workersMax` by hand, so the first write often meets
        that window. Five quick attempts (15 s of backoff, as recon's `_call`
        has) were rejected: that is shorter than the window. The deadline
        bounds the waiting, not each HTTP call's own 30 s timeout.
        """
        deadline = self._clock() + PIN_DEADLINE_SECONDS
        for attempt in itertools.count():
            try:
                return self._pin_once()
            except (PinFailed, EndpointReadError):
                raise
            except Exception as e:
                wait = _backoff(attempt)
                if self._clock() + wait > deadline:
                    raise PinFailed(
                        f"could not pin workersMin to {self._workers} on endpoint {self._id} "
                        f"within {PIN_DEADLINE_SECONDS:.0f} s (last: {e}). RunPod answers 409 "
                        "for a while after a configuration change, including the owner's "
                        "manual one, so that is the likely cause. The context manager "
                        "releases workersMin before this error reaches you; if you called "
                        "pin() directly, call release() now") from e
                self._sleep(wait)

    def _release_once(self) -> dict:
        r = self._session.post(self._url("/update"), headers=self._headers,
                               json={"workersMin": 0}, timeout=30)
        if _transient(r.status_code):
            raise _Retryable(f"the release POST returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise ReleaseFailed(self._manual(f"the release POST returned {r.status_code}"))
        try:
            ep = self.endpoint()
        except EndpointReadError as e:
            if e.retryable:
                raise _Retryable(f"the verifying re-read failed: {e}") from e
            raise ReleaseFailed(self._manual(f"the verifying re-read: {e}")) from e
        if not _is_int(ep.get("workersMin"), 0):
            # Possibly propagation lag after an accepted write; POST again.
            raise _Retryable(f"the re-read shows workersMin {ep.get('workersMin')!r}")
        return ep

    def _manual(self, cause: str) -> str:
        return (f"RELEASE FAILED: could not confirm workersMin is 0 on endpoint {self._id} "
                f"(last: {cause}). Set it to 0 by hand now; a pinned worker bills "
                "continuously whether or not anything is running on it")

    def release(self) -> dict:
        """Set `workersMin` to 0 and prove it by re-reading, or fail loudly.

        The release and its verifying re-read are retried together on 409,
        5xx, any unexpected exception from the HTTP layer and a re-read that
        does not yet show 0, until RELEASE_DEADLINE_SECONDS. Reusing recon's
        five-attempt `_call` was rejected: its 15 s of backoff is shorter than
        the 409 window that follows every configuration change, and the
        release always follows one. A refusal retrying cannot fix (another
        4xx) fails at once. The deadline bounds the waiting, not each HTTP
        call's own 30 s timeout, so the worst case is a little over it.

        It is hard to cut short from outside. SIGTERM and SIGHUP are recorded,
        not acted on, while it runs (main thread only): a first one raising
        SystemExit from `unwind_on_hangup_and_term()`'s handler in the middle
        of a 409 sleep would abandon the release with workers still pinned.
        Once the release is confirmed and the handlers are restored, the
        recorded signal is raised as `SystemExit(128 + signum)`, so a caller
        looping over repeats stops after an explicit kill instead of
        starting the next pin. A KeyboardInterrupt is remembered the same
        way and re-raised after, unless a signal was also recorded. A release
        error is raised in preference to either, with the signal noted in
        its message. Small windows remain just before the handlers are
        swapped in, and SIGKILL always gets through: release by hand.
        """
        deadline = self._clock() + RELEASE_DEADLINE_SECONDS
        interrupted = None
        failure = None
        with _term_and_hangup_deferred() as received:
            for attempt in itertools.count():
                try:
                    ep = self._release_once()
                    break
                except KeyboardInterrupt as e:
                    interrupted = e
                    if self._clock() >= deadline:
                        failure = "interrupted until the deadline"
                        break
                except ReleaseFailed:
                    raise
                except Exception as e:  # noqa: BLE001 - any error must retry; the deadline bounds it
                    wait = _backoff(attempt)
                    if self._clock() + wait > deadline:
                        failure = str(e)
                        break
                    try:
                        self._sleep(wait)
                    except KeyboardInterrupt as ki:
                        interrupted = ki
        if failure is not None:
            # Raised outside the handler so the exception already unwinding
            # through __exit__ (the run's own failure) stays its __context__,
            # not the last retryable noise.
            raise ReleaseFailed(self._manual(failure) + self._signal_note(received))
        if self._workers_max is not None and ep.get("workersMax") != self._workers_max:
            changed = RuntimeError(
                f"workersMax is {ep.get('workersMax')!r} after the run but was "
                f"{self._workers_max!r} at preflight. workersMin is back to 0, but this code "
                "never writes workersMax, so something else changed the cost ceiling during "
                "the run: treat its evidence as collected under a ceiling nobody checked"
                + self._signal_note(received))
            if interrupted is not None:
                raise changed from interrupted
            raise changed
        if received:
            raise SystemExit(128 + received[0])
        if interrupted is not None:
            raise interrupted
        return ep

    @staticmethod
    def _signal_note(received: list) -> str:
        if not received:
            return ""
        return (f" (signal {received[0]} also arrived during the release and is "
                "reported by this error instead of an exit)")

    def _release_while_unwinding(self, original: BaseException | None) -> None:
        """Release during an unwind; the exit a signal already started keeps its code.

        A signal recorded during the release becomes a SystemExit, which
        would replace the body's SystemExit and change the exit status the
        first signal chose. Any other unwinding exception is superseded: an
        explicit kill outranks it.
        """
        try:
            self.release()
        except SystemExit:
            if not isinstance(original, SystemExit):
                raise

    def __enter__(self):
        self.preflight()
        try:
            self.pin()
        except BaseException as e:
            self._release_while_unwinding(e)
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            self.release()
        else:
            self._release_while_unwinding(exc)
        return False


def _exit_on_signal(signum, frame):
    for other in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(other, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def unwind_on_hangup_and_term() -> None:
    """Make SIGTERM and SIGHUP unwind through a `with WorkerPin(...)` release.

    By default both end the process without unwinding, leaving workers pinned
    and billing. Raising SystemExit from a handler turns them into an ordinary
    unwind; the first one ignores any that follow, and `release()` ignores
    both while it runs, so a later signal cannot cut the bounded release
    short. `kill -9` cannot be handled: release by hand.
    """
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on_signal)
