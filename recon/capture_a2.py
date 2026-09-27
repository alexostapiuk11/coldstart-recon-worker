"""Artifact 2 reconnaissance: Q1 (replica-count control) and Q2 (distinct
workers under concurrent load -- genuine cold start, or warm-host restart).

Spec §9. Saves every platform response verbatim into fixtures/a2_recon/ and
publishes nothing. Like recon/capture.py it imports only the standard library
and `requests`, so a reader can reproduce the committed fixtures without
installing this repository's packages; the retry loop is therefore a
deliberate third copy (coldstart/runpod_submitter.py explains the second).

WHAT IS ASSUMED, AND HOW THE CAPTURE CHECKS IT. Known from committed evidence:
`POST {REST}/endpoints/{id}/update` changes endpoint configuration
(recon/README.md, the flashboot fix); `workersMin` and `workersMax` are endpoint
fields (coldstart/preflight.py, docs/experiment.md); `/run` and `/status/{job}`
behave as recon/capture.py found. NOT known: `GET {API}/{id}/health` as a way to
observe worker counts -- every `/health` in this repository is vLLM's own local
check. The capture polls it anyway and records whatever comes back, a 404
included, because "the platform does not expose worker counts" is itself a Q1
finding, and job-level workerIds remain as a fallback observation of scale.

It never writes `workersMax`: that is the cost ceiling, and it belongs to the
human who provisioned the endpoint. It raises `workersMin` only inside the scale
phase, restores it to 0 in a `finally`, and re-reads the endpoint to prove the
restore landed -- a pinned worker bills by the second whether or not anything
runs on it.

PROTOCOL
  preflight  GET the endpoint. Refuse unless flashboot is false, workersMin is 0
             and workersMax >= WORKERS >= 2.
  burst1     Submit WORKERS jobs back to back, ALL before any is polled, so the
             platform must start more than one worker if it ever will (Q2a).
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

import json
import os
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
OUT = Path("fixtures") / "a2_recon"


class RefuseToSpend(RuntimeError):
    """The endpoint is not configured for this capture. Nothing was submitted
    and nothing was changed."""


class Capture:
    def __init__(self, endpoint_id, api_key, out=OUT, workers=WORKERS,
                 session=requests, clock=time.time, sleep=time.sleep, attempts=5):
        if workers < 2:
            raise ValueError(
                f"workers={workers}; a burst needs at least 2 jobs, because one "
                "worker cannot demonstrate that the platform starts DISTINCT "
                "workers, which is the first half of Q2"
            )
        self._id = endpoint_id
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._out = Path(out)
        self._out.mkdir(parents=True, exist_ok=True)
        self._log = self._out / "capture.jsonl"
        self._workers = workers
        self._session = session
        self._clock = clock
        self._sleep = sleep
        self._attempts = attempts

    def _record(self, method, url, body, response):
        # The request HEADERS are never written: they carry the API key, and
        # this directory is committed as fixtures.
        try:
            payload = response.json()
        except ValueError:
            payload = getattr(response, "text", None)
        entry = {"t": self._clock(), "method": method, "url": url, "request": body,
                 "status_code": response.status_code, "response": payload}
        with self._log.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return payload

    def _call(self, method, url, body=None, require_ok=True):
        for attempt in range(self._attempts):
            if method == "GET":
                r = self._session.get(url, headers=self._headers, timeout=30)
            else:
                r = self._session.post(url, headers=self._headers, json=body, timeout=30)
            payload = self._record(method, url, body, r)
            # 409 follows any endpoint config change for a while and 5xx shows
            # up under load; both are transient. Every attempt is recorded, so
            # the retry is visible in the evidence rather than hidden by it.
            if (r.status_code == 409 or r.status_code >= 500) and attempt < self._attempts - 1:
                self._sleep(2**attempt)
                continue
            if require_ok and not 200 <= r.status_code < 300:
                raise RuntimeError(f"{method} {url} returned {r.status_code}: {payload!r}")
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
        if problems:
            raise RefuseToSpend("refusing to spend:\n  " + "\n  ".join(problems))
        return ep

    def _submit(self) -> str:
        return self._call("POST", f"{API}/{self._id}/run", {"input": {"recon": True}})["id"]

    def _await(self, job_id: str) -> dict:
        deadline = self._clock() + JOB_TIMEOUT_SECONDS
        while True:
            status = self._call("GET", f"{API}/{self._id}/status/{job_id}")
            if status.get("status") in TERMINAL_STATES or self._clock() >= deadline:
                return status
            self._sleep(POLL_SECONDS)

    def burst(self, label: str) -> list[str]:
        # Every job is submitted before any is polled. Polling job 1 to
        # completion first would serialise the burst -- artifact 1's design,
        # and the reason it could never see a second worker.
        ids = [self._submit() for _ in range(self._workers)]
        for i, job_id in enumerate(ids):
            status = self._await(job_id)
            (self._out / f"{label}_{i}.json").write_text(json.dumps(status, indent=2))
        return ids

    def _set_workers_min(self, n: int) -> None:
        self._call("POST", f"{REST}/endpoints/{self._id}/update", {"workersMin": n})

    def _observe(self, seconds: float) -> None:
        deadline = self._clock() + seconds
        while self._clock() < deadline:
            self._call("GET", f"{API}/{self._id}/health", require_ok=False)
            self._sleep(POLL_SECONDS)

    def scale(self) -> None:
        self._set_workers_min(self._workers)
        self._observe(SCALE_OBSERVE_SECONDS)
        self._set_workers_min(0)
        self._observe(SCALE_OBSERVE_SECONDS)

    def restore(self) -> None:
        self._set_workers_min(0)
        if self.endpoint().get("workersMin") != 0:
            raise RuntimeError(
                "RESTORE FAILED: workersMin is not 0 after the capture. Set it to "
                "0 by hand now -- a pinned worker bills continuously whether or "
                "not anything is running on it"
            )

    def run(self) -> None:
        # Preflight sits OUTSIDE the try: a refusal changed nothing, so there
        # is nothing to restore, and restoring would be a write to an endpoint
        # the capture just declined to touch.
        self.preflight()
        try:
            self.burst("burst1")
            self._sleep(IDLE_WAIT_SECONDS)
            self.burst("burst2")
            self.scale()
        finally:
            self.restore()


def main(argv: list[str]) -> None:
    key = os.environ["RUNPOD_API_KEY"]
    # Deliberately NOT artifact 1's RUNPOD_ENDPOINT_ID. This capture changes
    # workersMin on the endpoint it is pointed at; an inherited variable would
    # point it at artifact 1's pinned endpoint. Preflight would refuse that one
    # (workersMax 1), but the name makes the intent unmistakable first.
    endpoint = os.environ["RUNPOD_A2_ENDPOINT_ID"]
    capture = Capture(endpoint, key)
    if "--preflight-only" in argv:
        print(json.dumps(capture.preflight(), indent=2))
        return
    capture.run()


if __name__ == "__main__":
    main(sys.argv[1:])
