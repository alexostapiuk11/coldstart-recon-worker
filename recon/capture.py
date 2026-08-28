"""Reconnaissance capture. Submits a few jobs and saves everything verbatim.

Publishes nothing. The sample is far too small and the config is not frozen.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

API = "https://api.runpod.ai/v2"
KEY = os.environ["RUNPOD_API_KEY"]
ENDPOINT = os.environ["RUNPOD_ENDPOINT_ID"]
OUT = Path("fixtures")


def submit(payload: dict, attempts: int = 5) -> str:
    """Submit one job, retrying the transient rejections.

    The endpoint answers 409 for a while after any config change, and 5xx shows
    up under load. Both are transient, and a campaign submitting hundreds of
    jobs cannot abort on one of them the way a single unguarded raise would.
    """
    for attempt in range(attempts):
        r = requests.post(
            f"{API}/{ENDPOINT}/run",
            headers={"Authorization": f"Bearer {KEY}"},
            json={"input": payload},
            timeout=30,
        )
        if r.status_code == 409 or r.status_code >= 500:
            if attempt == attempts - 1:
                r.raise_for_status()
            backoff = 2**attempt
            print(f"[recon] submit got {r.status_code}, retrying in {backoff}s", flush=True)
            time.sleep(backoff)
            continue
        r.raise_for_status()
        return r.json()["id"]
    raise RuntimeError("unreachable: retry loop exited without returning")


def poll(job_id: str, timeout=1800) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(
            f"{API}/{ENDPOINT}/status/{job_id}",
            headers={"Authorization": f"Bearer {KEY}"},
            timeout=30,
        )
        r.raise_for_status()
        last = r.json()
        if last.get("status") in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}:
            return last
        time.sleep(5)
    return last or {"status": "POLL_TIMEOUT"}


def main(n: int) -> None:
    (OUT / "vllm_logs").mkdir(parents=True, exist_ok=True)
    (OUT / "runpod_api").mkdir(parents=True, exist_ok=True)
    for i in range(n):
        print(f"[recon] submitting {i + 1}/{n}", flush=True)
        job_id = submit({"recon": True})
        status = poll(job_id)
        (OUT / "runpod_api" / f"status_{i}.json").write_text(json.dumps(status, indent=2))
        out = (status.get("output") or {})
        lines = out.get("log_lines") or []
        (OUT / "vllm_logs" / f"startup_{i}.log").write_text("\n".join(lines))
        print(f"[recon] {job_id} status={status.get('status')} log_lines={len(lines)}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
