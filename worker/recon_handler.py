"""Reconnaissance handler. Captures raw engine output. Measures nothing."""

import os
import subprocess
import threading
import time

import requests
import runpod

MODEL = os.environ["MODEL_ID"]
PORT = 8000


def _wait_healthy(timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)
    return False


def handler(job):
    lines: list[str] = []
    proc = subprocess.Popen(
        ["vllm", "serve", MODEL, "--port", str(PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def drain():
        for line in proc.stdout:
            lines.append(line.rstrip("\n"))

    drain_thread = threading.Thread(target=drain, daemon=True)
    drain_thread.start()

    healthy = False
    completion = None
    try:
        healthy = _wait_healthy()
        if healthy:
            r = requests.post(
                f"http://127.0.0.1:{PORT}/v1/completions",
                json={"model": MODEL, "prompt": "Hello", "max_tokens": 4},
                timeout=120,
            )
            completion = r.json()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        # stdout reaches EOF only once the process is gone; join so the drain
        # thread finishes appending before we read `lines`.
        drain_thread.join(timeout=15)

    return {
        "healthy": healthy,
        "log_lines": lines,
        "completion": completion,
        "drain_completed": not drain_thread.is_alive(),
        "env": {
            "MODEL_ID": MODEL,
            "VLLM_CACHE_ROOT": os.environ.get("VLLM_CACHE_ROOT"),
            "HOME": os.environ.get("HOME"),
        },
        "cache_dirs": {
            p: sorted(os.listdir(p))[:50]
            for p in ["/root/.cache", "/root/.cache/vllm"]
            if os.path.isdir(p)
        },
    }


runpod.serverless.start({"handler": handler})
