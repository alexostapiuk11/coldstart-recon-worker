"""Artifact 2 reconnaissance: Q1 (replica-count control) and Q2 (distinct
workers under concurrent load -- genuine cold start, or warm-host restart).

Spec §9. Saves every platform response into fixtures/a2_recon/ and publishes
nothing. Responses are kept verbatim except for secrets (see `redact`). Like
recon/capture.py it imports only the standard library and `requests`, so a
reader can reproduce the committed fixtures without installing this
repository's packages; the retry loop is therefore a deliberate third copy
(coldstart/runpod_submitter.py explains the second).

WHAT IS ASSUMED, AND HOW THE CAPTURE CHECKS IT. Known from committed evidence:
`POST {REST}/endpoints/{id}/update` changes endpoint configuration
(recon/README.md, the flashboot fix); `workersMin`, `workersMax` and
`idleTimeout` are endpoint fields (coldstart/preflight.py, docs/experiment.md);
`/run` and `/status/{job}` behave as recon/capture.py found. NOT known:
`GET {API}/{id}/health` as a way to observe worker counts -- every `/health` in
this repository is vLLM's own local check. The capture polls it anyway and
records whatever comes back, a 404 or a dropped connection included, because
"the platform does not expose worker counts" is itself a Q1 finding, and
job-level workerIds remain as a fallback observation of scale.

It never writes `workersMax`: that is the cost ceiling, and it belongs to the
human who provisioned the endpoint. It raises `workersMin` only inside the scale
phase, restores it to 0 in a `finally` with its own retry budget, and re-reads
the endpoint to prove the restore landed -- a pinned worker bills by the second
whether or not anything runs on it. `--restore` repeats that release alone, for
when the capture could not.

PROTOCOL
  preflight  GET the endpoint. Refuse unless flashboot is false, workersMin is 0,
             workersMax >= WORKERS >= 2 and idleTimeout < IDLE_WAIT_SECONDS.
  burst1     Submit WORKERS jobs back to back, ALL before any is polled, so the
             platform must start more than one worker if it ever will (Q2a).
             Poll them round-robin until each is terminal or past its deadline.
  idle       Wait IDLE_WAIT_SECONDS -- far past the 5 s idleTimeout -- so every
             container from burst1 terminates. Without this, burst2 would reuse
             live containers and measure container survival, not host affinity.
  burst2     The same again. A workerId repeated from burst1 is a host the
             platform re-allocated after termination: a warm-host candidate
             (docs/experiment.md saw 23 of 27 runs on one host). Its engine log
             says whether the container was cold (full torch.compile) and its
             delayTime whether an image was pulled.
  scale      Set workersMin = WORKERS, poll health for SCALE_OBSERVE_SECONDS; set
             workersMin = 0, poll again (Q1: acknowledgement and time to effect).
"""

import itertools
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

import requests

API = "https://api.runpod.ai/v2"
REST = "https://rest.runpod.io/v1"
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
WORKERS = 2
IDLE_WAIT_SECONDS = 60.0
SCALE_OBSERVE_SECONDS = 600.0
POLL_SECONDS = 5.0
# Artifact 1's first priming run spent 1898 s in `delayTime` alone pulling the
# image to a cold host; a shorter budget records a healthy run as a timeout.
JOB_TIMEOUT_SECONDS = 5400.0
# The release gets its own budget, far longer than the generic retry's 15 s:
# RunPod answers 409 for a while after ANY configuration change, and the
# release always follows one (the pin). Five minutes of a pinned worker is the
# price of not handing the operator a false RESTORE FAILED.
RESTORE_DEADLINE_SECONDS = 300.0
RESTORE_BACKOFF_CAP_SECONDS = 30.0
# Anchored to the repository, not the working directory: run from anywhere
# else, a relative path would leave the evidence where nobody commits it.
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "a2_recon"
REDACTED = "<redacted>"
SECRET_PATTERN = re.compile(r"\bhf_[A-Za-z0-9]{20,}\b|\brpa_[A-Za-z0-9]{20,}\b")


class RefuseToSpend(RuntimeError):
    """The endpoint or the output directory is not fit for this capture.
    Nothing was submitted and nothing was changed."""


class JobTimedOut(RuntimeError):
    """A job was not terminal by its deadline. Its last status is saved as
    `<label>.timeout.json`, and no later phase runs."""


class _Retryable(Exception):
    """A release step the platform may yet accept: 409, 5xx, or a re-read
    that does not show workersMin 0 yet."""


class _Rejected(Exception):
    """A release step the platform refused outright (another 4xx). Retrying
    for five minutes would only delay telling the operator to act."""


def redact(value, secret):
    """Replace secrets in a JSON-shaped value with "<redacted>".

    This is the one deliberate exception to capturing verbatim: the output
    directory is meant to be committed as fixtures. The endpoint read may
    return its template, whose `env` may hold HF_TOKEN, and a token can surface
    in an engine log line. Any key named `env` is dropped whole, at any depth,
    rather than scrubbing the variables known to be secret -- the next secret
    someone adds to the template would not be on that list.

    In strings, only the secret itself is replaced, never the string around
    it: a vLLM log line is the evidence Task 4 parses (compile time, KV
    tokens, version, weights download), and blanking a whole line for one
    token in it would destroy that. The API key is replaced wherever it
    appears. A Hugging Face (`hf_`) or RunPod (`rpa_`) token is recognised by
    shape: the prefix, then at least 20 letters or digits, bounded as a whole
    word. The token alphabet has no underscore, so a snake_case identifier
    such as `hf_transfer` or `hf_overrides` cannot match, and the 20-character
    floor keeps short identifiers out. Real token lengths were NOT verified
    here; the floor was chosen well below any plausible length, so the pattern
    errs toward redacting. Scrubbing by hand before commit was rejected: it is
    the step that gets skipped, and a leaked token in git history outlives any
    fix. The README's grep, with the same patterns, is a second check, not the
    first.
    """
    if isinstance(value, dict):
        return {k: REDACTED if k == "env" else redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, REDACTED)
        return SECRET_PATTERN.sub(REDACTED, value)
    return value


def _transient(status_code: int) -> bool:
    # 409 follows any endpoint config change for a while and 5xx shows up
    # under load; both are transient.
    return status_code == 409 or status_code >= 500


class Capture:
    """One run of the Q1/Q2 protocol against one endpoint.

    A class rather than recon/capture.py's module functions because the run
    carries state that later steps depend on -- the preflight reading of
    workersMax that the restore re-checks, and the open evidence log -- and
    because this script WRITES endpoint configuration: every test must inject
    the session, clock and sleep, so the pin, the failures and the restore
    are proven without a network, a wait or a bill. Module globals read from
    the environment at import, as recon/capture.py does, were rejected for
    exactly that reason.
    """

    def __init__(self, endpoint_id, api_key, out=OUT, workers=WORKERS,
                 session=requests, clock=time.time, sleep=time.sleep, attempts=5):
        if workers < 2:
            raise ValueError(
                f"workers={workers}; a burst needs at least 2 jobs, because one "
                "worker cannot demonstrate that the platform starts DISTINCT "
                "workers, which is the first half of Q2"
            )
        self._id = endpoint_id
        self._key = api_key
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._out = Path(out)
        # No log until run() opens one: --preflight-only and --restore write
        # nothing to disk, so "free" is true of the filesystem as well.
        self._log = None
        self._preflight_workers_max = None
        self._workers = workers
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._attempts = attempts

    def redact(self, value):
        return redact(value, self._key)

    def _record(self, method, url, body, t_sent, response=None, error=None):
        # `t` is when the answer (or the failure) came back, as it always was;
        # `t_sent` is when the request left, so the gap is the call's latency.
        # The request HEADERS are never written: they carry the API key.
        entry = {"t": self._clock(), "t_sent": t_sent, "method": method, "url": url,
                 "request": body}
        payload = None
        if error is not None:
            entry["error"] = f"{type(error).__name__}: {error}"
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = getattr(response, "text", None)
            entry["status_code"] = response.status_code
            entry["response"] = payload
        if self._log is not None:
            with self._log.open("a") as f:
                f.write(json.dumps(self.redact(entry)) + "\n")
        return payload

    def _send(self, method, url, body=None):
        """One HTTP request, recorded whether it answers or raises."""
        t_sent = self._clock()
        try:
            if method == "GET":
                r = self._session.get(url, headers=self._headers, timeout=30)
            else:
                r = self._session.post(url, headers=self._headers, json=body, timeout=30)
        except requests.RequestException as e:
            self._record(method, url, body, t_sent, error=e)
            raise
        return r, self._record(method, url, body, t_sent, response=r)

    def _call(self, method, url, body=None, require_ok=True):
        for attempt in range(self._attempts):
            r, payload = self._send(method, url, body)
            # Every attempt is recorded, so the retry is visible in the
            # evidence rather than hidden by it.
            if _transient(r.status_code) and attempt < self._attempts - 1:
                self._sleep(2**attempt)
                continue
            if require_ok and not 200 <= r.status_code < 300:
                raise RuntimeError(
                    f"{method} {url} returned {r.status_code}: {self.redact(payload)!r}. "
                    "Stopping the capture: every later phase would run against a "
                    "state this call did not establish, and its evidence would not "
                    "mean what the protocol says it means"
                )
            return payload
        raise RuntimeError("unreachable: retry loop exited without returning")

    def endpoint(self) -> dict:
        return self._call("GET", f"{REST}/endpoints/{self._id}")

    def preflight(self) -> dict:
        ep = self.endpoint()
        problems = []
        if ep.get("flashboot") is not False:
            problems.append(
                f"flashboot is {ep.get('flashboot')!r}; it caches worker state to "
                "accelerate cold starts, so Q2 would measure RunPod's cache"
            )
        if ep.get("workersMin") != 0:
            problems.append(
                f"workersMin is {ep.get('workersMin')!r}; a standing worker is "
                "warm between bursts and hides the cold start Q2 asks about"
            )
        workers_max = ep.get("workersMax")
        if not isinstance(workers_max, int) or workers_max < self._workers:
            problems.append(
                f"workersMax is {workers_max!r}, below the burst of {self._workers}; "
                "the burst would queue on one worker and reproduce artifact 1's "
                "result by construction"
            )
        idle = ep.get("idleTimeout")
        if (not isinstance(idle, (int, float)) or isinstance(idle, bool)
                or idle >= IDLE_WAIT_SECONDS):
            problems.append(
                f"idleTimeout is {idle!r}, not below the {IDLE_WAIT_SECONDS:.0f} s "
                "wait between bursts; burst1's containers could still be alive "
                "when burst2 arrives, so burst2 would measure container survival "
                "rather than host affinity"
            )
        if problems:
            raise RefuseToSpend("refusing to spend:\n  " + "\n  ".join(problems))
        self._preflight_workers_max = workers_max
        return ep

    def _submit(self) -> str:
        return self._call("POST", f"{API}/{self._id}/run", {"input": {"recon": True}})["id"]

    def _save(self, name: str, payload) -> None:
        (self._out / name).write_text(json.dumps(self.redact(payload), indent=2))

    def burst(self, label: str) -> list[str]:
        # Every job is submitted before any is polled. Polling job 1 to
        # completion first would serialise the burst -- artifact 1's design,
        # and the reason it could never see a second worker.
        jobs = []
        for _ in range(self._workers):
            job_id = self._submit()
            jobs.append((job_id, self._clock() + JOB_TIMEOUT_SECONDS))
        # Round-robin, not one job awaited after another: RunPod keeps an
        # async job's result only for a limited window after it finishes, so a
        # job that finished early could expire while the loop sat on a slower
        # one. Moderate confidence: that is our reading of the platform's
        # documentation, and the window's length has not been verified here.
        pending = dict(enumerate(jobs))
        timed_out = []
        while pending:
            for i, (job_id, deadline) in list(pending.items()):
                status = self._call("GET", f"{API}/{self._id}/status/{job_id}")
                if status.get("status") in TERMINAL_STATES:
                    self._save(f"{label}_{i}.json", status)
                elif self._clock() >= deadline:
                    # Not `<label>.json`: a non-terminal status is not a result.
                    self._save(f"{label}_{i}.timeout.json", status)
                    timed_out.append(f"{job_id} ({status.get('status')!r})")
                else:
                    continue
                del pending[i]
            if pending:
                self._sleep(POLL_SECONDS)
        if timed_out:
            raise JobTimedOut(
                f"{label}: {', '.join(timed_out)} not terminal after "
                f"{JOB_TIMEOUT_SECONDS:.0f} s; last statuses saved as "
                f"{label}_N.timeout.json. Stopping: a later phase would share the "
                "platform with a job that may still hold a worker, and would "
                "measure that instead of what the protocol intends"
            )
        return [job_id for job_id, _ in jobs]

    def _set_workers_min(self, n: int) -> None:
        self._call("POST", f"{REST}/endpoints/{self._id}/update", {"workersMin": n})

    def _observe(self, seconds: float) -> None:
        deadline = self._clock() + seconds
        while self._clock() < deadline:
            try:
                self._call("GET", f"{API}/{self._id}/health", require_ok=False)
            except requests.RequestException:
                # Already recorded as an error row by _send. One dropped
                # connection must not end a 20-minute window whose other polls
                # are the evidence; a run of them is itself a finding.
                pass
            self._sleep(POLL_SECONDS)

    def scale(self) -> None:
        self._set_workers_min(self._workers)
        self._observe(SCALE_OBSERVE_SECONDS)
        self._set_workers_min(0)
        self._observe(SCALE_OBSERVE_SECONDS)

    def _release_once(self) -> dict:
        r, _ = self._send("POST", f"{REST}/endpoints/{self._id}/update", {"workersMin": 0})
        if _transient(r.status_code):
            raise _Retryable(f"the release POST returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise _Rejected(f"the release POST returned {r.status_code}")
        r, ep = self._send("GET", f"{REST}/endpoints/{self._id}")
        if _transient(r.status_code):
            raise _Retryable(f"the verifying re-read returned {r.status_code}")
        if not 200 <= r.status_code < 300:
            raise _Rejected(f"the verifying re-read returned {r.status_code}")
        if not isinstance(ep, dict):
            # A 2xx that is not the endpoint's JSON (a gateway's HTML page)
            # proves nothing about workersMin; read again.
            raise _Retryable(f"the verifying re-read was not JSON: {str(ep)[:80]!r}")
        if ep.get("workersMin") != 0:
            # Possibly propagation lag after an accepted write; POST again.
            raise _Retryable(f"the re-read shows workersMin {ep.get('workersMin')!r}")
        return ep

    def restore(self) -> dict:
        """Set workersMin to 0 and prove it by re-reading, or fail loudly.

        The release and its verifying re-read are retried together, on 409,
        5xx, any `requests.RequestException` and a re-read that does not yet
        show 0, until RESTORE_DEADLINE_SECONDS. Reusing `_call`'s five attempts
        was rejected: its 15 s of backoff is shorter than the 409 window that
        follows every configuration change, and the release always follows
        one. A refusal that retrying cannot fix (another 4xx) fails at once.
        """
        deadline = self._clock() + RESTORE_DEADLINE_SECONDS
        for attempt in itertools.count():
            try:
                ep = self._release_once()
                break
            except _Rejected as e:
                raise self._restore_failed(e) from e
            except (_Retryable, requests.RequestException) as e:
                wait = min(2.0**attempt, RESTORE_BACKOFF_CAP_SECONDS)
                if self._clock() + wait > deadline:
                    raise self._restore_failed(e) from e
                self._sleep(wait)
        if (self._preflight_workers_max is not None
                and ep.get("workersMax") != self._preflight_workers_max):
            raise RuntimeError(
                f"workersMax is {ep.get('workersMax')!r} after the capture but was "
                f"{self._preflight_workers_max!r} at preflight. workersMin is back "
                "to 0, but this script never writes workersMax, so something else "
                "changed the endpoint's cost ceiling during the run: find out what, "
                "and treat this run's scale evidence as collected under a ceiling "
                "nobody checked"
            )
        return ep

    def _restore_failed(self, cause: Exception) -> RuntimeError:
        return RuntimeError(
            f"RESTORE FAILED: could not confirm workersMin is 0 on endpoint {self._id} "
            f"(last: {cause}). Set it to 0 by hand now, or run "
            "`.venv/bin/python recon/capture_a2.py --restore` -- a pinned worker "
            "bills continuously whether or not anything is running on it"
        )

    def _open_evidence(self) -> None:
        if self._out.exists() and any(self._out.iterdir()):
            raise RefuseToSpend(
                f"{self._out} already holds files; appending would mix two runs' "
                "evidence in one capture.jsonl, with nothing in the rows to say "
                "which run each came from. Move it aside, or commit it and point "
                "this run at a new directory"
            )
        self._out.mkdir(parents=True, exist_ok=True)
        self._log = self._out / "capture.jsonl"

    def run(self) -> None:
        self._open_evidence()
        # Preflight sits OUTSIDE the try: a refusal changed nothing, so there
        # is nothing to restore, and restoring would be a write to an endpoint
        # the capture just declined to touch.
        self.preflight()
        # Jobs already submitted are NOT cancelled when a phase fails: a cancel
        # is one more platform write this script would have to prove. What a
        # stranded job can spend is bounded by the endpoint's own execution
        # timeout (executionTimeoutMs), which the operator set at provisioning.
        try:
            self.burst("burst1")
            self._sleep(IDLE_WAIT_SECONDS)
            self.burst("burst2")
            self.scale()
        finally:
            # If a phase failed, its exception is in flight here. If restore
            # then fails too, Python chains the phase error as the context of
            # restore's own, so the traceback shows both: the phase error, then
            # "During handling of the above exception..." and RESTORE FAILED.
            # Catching one to raise the other was rejected: whichever was
            # dropped is evidence the operator needs.
            self.restore()


def _exit_on_signal(signum, frame):
    """Unwind on the first SIGTERM or SIGHUP, and ignore any that follow.

    A closing terminal often sends more than one signal. Without the ignore,
    a second would raise SystemExit again from inside the `finally` restore
    that the first began, and cut it short with the worker still pinned.
    Ignoring is safe because the restore is bounded (RESTORE_DEADLINE_SECONDS)
    and `kill -9` still ends the process -- after which `--restore` releases.
    """
    for other in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(other, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def _unwind_on_hangup_and_term() -> None:
    """Make SIGTERM and SIGHUP unwind through run()'s `finally` restore.

    Ctrl-C already does: SIGINT raises KeyboardInterrupt, which unwinds. A
    `kill` (SIGTERM) or a closed terminal (SIGHUP) ends the process by
    default WITHOUT unwinding, leaving workersMin pinned and billing. Raising
    SystemExit from a handler turns both into an ordinary unwind. Rejected:
    `atexit`, which a signal death skips as well; and ignoring SIGHUP, which
    keeps the run alive but leaves the operator no clean way to stop it.
    """
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _exit_on_signal)


def main(argv: list[str], session=requests, out: Path = OUT, clock=time.time,
         sleep=time.sleep) -> None:
    _unwind_on_hangup_and_term()
    key = os.environ["RUNPOD_API_KEY"]
    # Deliberately NOT artifact 1's RUNPOD_ENDPOINT_ID. This capture changes
    # workersMin on the endpoint it is pointed at; an inherited variable would
    # point it at artifact 1's pinned endpoint. Preflight would refuse that one
    # (workersMax 1), but the name makes the intent unmistakable first.
    endpoint = os.environ["RUNPOD_A2_ENDPOINT_ID"]
    capture = Capture(endpoint, key, out=out, session=session, clock=clock, sleep=sleep)
    if "--preflight-only" in argv:
        print(json.dumps(capture.redact(capture.preflight()), indent=2))
        print("preflight passed; nothing was submitted, changed or recorded")
        return
    if "--restore" in argv:
        print(json.dumps(capture.redact(capture.restore()), indent=2))
        print(f"restored: workersMin is 0 on endpoint {endpoint}")
        return
    capture.run()


if __name__ == "__main__":
    main(sys.argv[1:])
