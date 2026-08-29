"""Clock A against the live RunPod endpoint.

Shapes the platform's response into the payload `driver._record_from` expects,
so the driver is identical whether it is fed by the stub or by the real thing.
"""

import time

import requests

from coldstart.runpod_api import extract_lifecycle, extract_worker_id
from coldstart.submitter import SubmitOutcome

API = "https://api.runpod.ai/v2"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class HttpTransport:
    """The real endpoint. Retries the transient rejections, as recon/capture.py does."""

    def __init__(self, endpoint_id: str, api_key: str, attempts: int = 5):
        self._url = f"{API}/{endpoint_id}"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._attempts = attempts

    def start(self, payload: dict) -> str:
        for attempt in range(self._attempts):
            r = requests.post(f"{self._url}/run", headers=self._headers,
                              json={"input": payload}, timeout=30)
            # 409 is returned for a window after any endpoint config change and
            # 5xx shows up under load. Both are transient; a campaign of
            # hundreds of jobs cannot abort on one of them.
            if r.status_code == 409 or r.status_code >= 500:
                if attempt == self._attempts - 1:
                    r.raise_for_status()
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()["id"]
        raise RuntimeError("unreachable: retry loop exited without returning")

    def status(self, job_id: str) -> dict:
        r = requests.get(f"{self._url}/status/{job_id}", headers=self._headers, timeout=30)
        r.raise_for_status()
        return r.json()


class RunPodSubmitter:
    """Clock A. Same interface as StubSubmitter -- submit(arm, run_id)."""

    def __init__(self, transport, clock=time.monotonic, poll_interval: float = 5.0,
                 job_timeout: float = 1800.0, sleep=time.sleep):
        self._transport = transport
        self._clock = clock
        self._poll_interval = poll_interval
        self._job_timeout = job_timeout
        self._sleep = sleep

    def _await_terminal(self, job_id: str) -> dict:
        deadline = time.monotonic() + self._job_timeout
        while True:
            status = self._transport.status(job_id)
            if status.get("status") in TERMINAL:
                return status
            if time.monotonic() >= deadline:
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
