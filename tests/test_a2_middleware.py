"""The ASGI middleware that stamps worker id and server latency on every response."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))

from a2_middleware import SERVER_LATENCY_HEADER, WORKER_HEADER, WorkerHeaders


class Clock:
    def __init__(self, *ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0)


def _run(app, scope):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent


async def _app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b"{}"})


def test_the_wire_names_are_pinned_lowercase():
    assert WORKER_HEADER == b"x-a2-worker"
    assert SERVER_LATENCY_HEADER == b"x-a2-server-latency-ms"


def test_http_responses_carry_the_worker_and_the_server_latency():
    mw = WorkerHeaders(_app, clock=Clock(10.0, 10.25), worker_id="pod-abc")
    start = _run(mw, {"type": "http"})[0]
    headers = dict(start["headers"])
    assert headers[WORKER_HEADER] == b"pod-abc"
    assert headers[SERVER_LATENCY_HEADER] == b"250.000"
    assert headers[b"content-type"] == b"application/json"


def test_the_body_passes_through_untouched():
    mw = WorkerHeaders(_app, clock=Clock(0.0, 0.1), worker_id="w")
    assert _run(mw, {"type": "http"})[1] == {"type": "http.response.body", "body": b"{}"}


def test_non_http_scopes_are_passed_through_without_headers():
    seen = []

    async def lifespan_app(scope, receive, send):
        seen.append(scope["type"])

    _run(WorkerHeaders(lifespan_app, worker_id="w"), {"type": "lifespan"})
    assert seen == ["lifespan"]


def test_the_worker_id_falls_back_to_the_pod_then_the_host(monkeypatch):
    monkeypatch.setenv("RUNPOD_POD_ID", "pod-1")
    assert WorkerHeaders(_app).worker_id == "pod-1"
    monkeypatch.delenv("RUNPOD_POD_ID")
    monkeypatch.setenv("HOSTNAME", "host-9")
    assert WorkerHeaders(_app).worker_id == "host-9"


def test_starlette_style_construction_with_app_keyword_works():
    assert WorkerHeaders(app=_app, worker_id="w").app is _app
