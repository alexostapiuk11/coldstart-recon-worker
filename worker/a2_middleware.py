"""ASGI middleware that stamps the serving worker and its own latency on responses.

Loaded into vLLM 0.27.1 with `--middleware a2_middleware.WorkerHeaders`
(PYTHONPATH=/opt in the image). vLLM adds a class with `app.add_middleware()`,
which constructs it as `WorkerHeaders(app=...)`.

Why it exists: a RunPod load-balancing endpoint routes requests to workers
and documents no header saying which one served a request. The open-loop
gate needs that per request: spec §10 requires the host of every replica, and
a request served by a worker outside the pinned set voids the run. It also
needs the engine's own latency, which is what the simulator models, separate
from the WAN and load-balancer time a client-side clock adds.

Raw ASGI, stdlib only, rather than Starlette's BaseHTTPMiddleware: that
wrapper buffers streaming responses and has its own cost per request, and the
measurement must add as little as possible to what it measures.
`x-a2-server-latency-ms` runs from the request reaching this layer to the
response starting. For a non-streaming completion, the response starts after
generation finishes, so it is the request's whole time inside the server.
"""

import os
import time

WORKER_HEADER = b"x-a2-worker"
SERVER_LATENCY_HEADER = b"x-a2-server-latency-ms"


class WorkerHeaders:
    """Add the worker id and server latency headers to every HTTP response.

    The latency is the time to the response start, so for a streaming
    response it is time to first byte, not the whole generation. A request
    whose app raises before responding carries no headers at all; the
    driver treats a response without them as a failed request, which voids
    the run rather than letting an unattributed request count.

    Construction raises when no worker id can be found, rather than falling
    back to a shared placeholder: every worker would then report the same id,
    and the driver would count one worker where two answered.
    """

    def __init__(self, app, *, clock=time.perf_counter, worker_id=None):
        self.app = app
        self._clock = clock
        self.worker_id = (worker_id or os.environ.get("RUNPOD_POD_ID")
                          or os.environ.get("HOSTNAME"))
        if not self.worker_id:
            raise RuntimeError(
                "neither RUNPOD_POD_ID nor HOSTNAME is set, so this worker has no id: two "
                "workers would share one id, and the warm-up could never see the pinned "
                "fleet. Set one of them in the worker's environment")
        self._worker = self.worker_id.encode()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        t0 = self._clock()

        async def stamped(message):
            if message.get("type") == "http.response.start":
                ms = (self._clock() - t0) * 1000.0
                headers = [*message.get("headers", []), (WORKER_HEADER, self._worker),
                           (SERVER_LATENCY_HEADER, f"{ms:.3f}".encode())]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, stamped)
