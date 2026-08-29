"""Clock A against the live RunPod endpoint.

Shapes the platform's response into the payload `driver._record_from` expects,
so the driver is identical whether it is fed by the stub or by the real thing.
"""

import time

import requests

from coldstart.runpod_api import TERMINAL_STATES, extract_lifecycle, extract_worker_id
from coldstart.submitter import SubmitOutcome

API = "https://api.runpod.ai/v2"


class HttpTransport:
    """The real endpoint. Retries the transient rejections, as recon/capture.py does.

    The retry pattern below is a deliberate duplicate of recon/capture.py's,
    not a shared import: recon/capture.py is a frozen reproduction script for
    the committed fixtures that intentionally imports only stdlib plus
    requests, so a reader can reproduce those fixtures without installing this
    package. Coupling it to coldstart would break that.
    """

    def __init__(self, endpoint_id: str, api_key: str, attempts: int = 5,
                 session=requests, sleep=time.sleep):
        self._url = f"{API}/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._attempts = attempts
        # `requests` the module exposes top-level get/post functions with the
        # same signature a caller would use on a `requests.Session()`, so it
        # doubles as the default "session" here. Tests substitute a fake.
        self._session = session
        self._sleep = sleep

    def _send_with_retry(self, send) -> "requests.Response":
        """Retry the transient rejections for one HTTP call. Shared by
        start() and status() -- `_await_terminal` polls status() up to
        `job_timeout / poll_interval` times per job, so a single transient
        blip on any one poll must not be fatal to a job that would otherwise
        have completed successfully.
        """
        for attempt in range(self._attempts):
            r = send()
            # 409 is returned for a window after any endpoint config change and
            # 5xx shows up under load. Both are transient; a campaign of
            # hundreds of jobs cannot abort on one of them.
            if r.status_code == 409 or r.status_code >= 500:
                if attempt == self._attempts - 1:
                    r.raise_for_status()
                self._sleep(2**attempt)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("unreachable: retry loop exited without returning")

    def start(self, payload: dict) -> str:
        r = self._send_with_retry(
            lambda: self._session.post(
                f"{self._url}/run", headers=self._headers,
                json={"input": payload}, timeout=30,
            )
        )
        return r.json()["id"]

    def status(self, job_id: str) -> dict:
        r = self._send_with_retry(
            lambda: self._session.get(
                f"{self._url}/status/{job_id}", headers=self._headers, timeout=30
            )
        )
        return r.json()


class RunPodSubmitter:
    """Clock A. Same interface as StubSubmitter -- submit(arm, run_id).

    `job_timeout` covers the WHOLE job: the platform's queue delay plus its
    execution. That is a different budget from the endpoint's own
    `executionTimeoutMs`, which bounds execution alone, and it has to be
    larger -- the delay can dwarf the execution when a worker must pull the
    image cold.

    Measured on the first priming run: `delayTime` 1898s against
    `executionTime` 140s. The client's old 1800s budget expired while the job
    was still queuing, so a run that completed healthily was recorded as
    `failed`. During a campaign that inflates the failure rate with runs that
    actually worked, discards paid GPU time, and stores a clock-A span that
    measures the client's patience rather than the job.
    """

    def __init__(self, transport, clock=time.monotonic, poll_interval: float = 5.0,
                 job_timeout: float = 5400.0, sleep=time.sleep, poll_clock=time.monotonic):
        self._transport = transport
        self._clock = clock
        self._poll_interval = poll_interval
        self._job_timeout = job_timeout
        self._sleep = sleep
        # Deliberately a separate injectable from `clock`: `clock` supplies
        # exactly the two clock_A stamps (t_submit, t_result) callers pass a
        # short fixed sequence for; `_await_terminal` can call the polling
        # clock an unbounded number of times per job (once for the deadline,
        # then once per poll), which would exhaust that sequence. Keeping
        # them separate lets tests simulate elapsed polling time -- including
        # a real timeout after several polls -- without touching clock_A's
        # two-value contract.
        self._poll_clock = poll_clock

    def _await_terminal(self, job_id: str) -> dict:
        deadline = self._poll_clock() + self._job_timeout
        while True:
            status = self._transport.status(job_id)
            if status.get("status") in TERMINAL_STATES:
                return status
            if self._poll_clock() >= deadline:
                raise TimeoutError(f"job {job_id} timed out after {self._job_timeout}s")
            self._sleep(self._poll_interval)

    def _payload_from(self, status: dict) -> dict:
        state = status.get("status")
        if state != "COMPLETED":
            raise RuntimeError(f"job ended {state}: {status.get('error') or 'no detail'}")
        output = dict(status.get("output") or {})
        if not output.get("healthy"):
            # The job completed but the engine never answered its health check.
            # Phrased to match checks.classify_failure's HEALTH_TIMEOUT needle.
            raise RuntimeError("health check timed out: probe reported unhealthy")

        output["clock_C"] = extract_lifecycle(status)
        host = dict(output.get("host") or {})
        # The platform's worker identity is stable across the container
        # restarts a reused serverless worker performs; the container hostname
        # is not. Within-host pairing needs the stable one.
        worker_id = extract_worker_id(status)
        if worker_id:
            # container_host_id is only added when there is a distinct
            # platform identity to pair it against. Without a worker_id there
            # is exactly one identity known for this run (whatever host_id
            # the output already carries); setting container_host_id to a
            # copy of it would misleadingly imply two identities that do not,
            # in fact, differ.
            host["container_host_id"] = host.get("host_id")
            host["host_id"] = worker_id
        host["job_id"] = status.get("id")
        output["host"] = host
        return output

    def submit(self, arm: str, run_id: str) -> SubmitOutcome:
        t_submit = self._clock()
        try:
            job_id = self._transport.start({"arm": arm, "run_id": run_id})
            payload = self._payload_from(self._await_terminal(job_id))
            error = None
        except Exception as e:  # noqa: BLE001 -- failures are data (spec 6.6)
            payload, error = None, str(e)
        t_result = self._clock()
        return SubmitOutcome(
            clock_A={"t_submit": t_submit, "t_result": t_result},
            payload=payload,
            error=error,
        )
