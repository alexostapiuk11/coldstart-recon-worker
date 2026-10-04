"""Start `vllm serve` on a port, wait for health, tear it down on request.

Lifted from `worker/probe.py`'s lifecycle. The probe itself stays frozen: it
is artifact 1's measured path, excerpted by the explainer and reproducible at
the `artifact-1-published` tag. What is shared is the lifecycle, not artifact
1's warm-up trio. The probe is one function that starts, measures and stops,
so another artifact has no point at which to run its own load; `served` yields
the running engine and the caller measures whatever it measures inside the
`with` block.

Kept from the probe: port 8000 by default, a 0.25 s health poll with a 2 s
request timeout, a 900 s health budget, stdout and stderr merged and
line-buffered, the environment overrides merged into a copy of the parent's
environment (never applied to `os.environ`), a daemon thread draining the log,
and terminate -> wait 30 s -> kill on teardown.

Changed from the probe, on purpose:

- The engine runs in its own session and is signalled by process group.
  Whether vLLM's worker processes exit when the API-server parent receives
  SIGTERM is unverified. A surviving engine core would keep the GPU's memory
  into the next job on a reused serverless worker, and that job would start
  its engine on a card that is already partly full.
- The health wait stops as soon as the process exits. The probe polls a dead
  process for the whole 900 s, paying fifteen minutes of GPU time to learn
  what the exit code already said.
- An unhealthy engine is stopped and then YIELDED with `healthy=False` and its
  log lines; it does not raise. Those lines are the only evidence of why the
  engine never came up. Raising would make every caller rebuild the capture,
  and artifact 5's instance runner already reads them off the yielded object.
- A port that something already answers on is refused before spawning. The
  health check would otherwise talk to whatever owns the port and report
  someone else's engine as this one.
"""

import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager

import requests

HEALTH_POLL_SECONDS = 0.25
HEALTH_REQUEST_TIMEOUT_SECONDS = 2.0
TERM_GRACE_SECONDS = 30.0
DRAIN_JOIN_SECONDS = 15.0


def _health_ok(url: str) -> bool:
    try:
        return requests.get(url, timeout=HEALTH_REQUEST_TIMEOUT_SECONDS).status_code == 200
    except requests.RequestException:
        return False


def _refuse_port_in_args(args: Sequence[str]) -> None:
    for arg in args:
        if arg == "--port" or arg.startswith("--port="):
            raise ValueError(
                f"args contains {arg!r}, but served() passes --port itself from its "
                "`port` argument; two --port flags leave the engine on whichever one "
                "argparse keeps, while the health check and base_url use the other"
            )


def _refuse_busy_port(port: int) -> None:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return
    raise RuntimeError(
        f"something is already answering on 127.0.0.1:{port}; the health check "
        "would talk to it and report another process's engine as this one. Stop "
        "it, or pass a different port"
    )


class Server:
    """A started engine, healthy or not, as `served` yields it.

    `log_lines` grows while the engine runs; read it after `stop()` (or after
    the `with` block) for the complete log. `cmd` is the exact argument list
    that was executed, including the `--port` that `served` added.
    """

    def __init__(self, proc, *, cmd, base_url, term_grace, clock):
        self.cmd = cmd
        self.base_url = base_url
        self.healthy = False
        self.log_lines: list[str] = []
        self._proc = proc
        self._term_grace = term_grace
        self._clock = clock
        self._teardown_s: float | None = None
        self._drain = threading.Thread(target=self._drain_stdout, daemon=True)
        self._drain.start()

    def _drain_stdout(self) -> None:
        for line in self._proc.stdout:
            self.log_lines.append(line.rstrip("\n"))

    @property
    def returncode(self) -> int | None:
        """None while the engine runs; its exit status once it has exited."""
        return self._proc.poll()

    @property
    def drain_completed(self) -> bool:
        """False if the log reader was still running when `stop()` gave up
        waiting for it, in which case `log_lines` may be missing its tail."""
        return not self._drain.is_alive()

    def _signal_group(self, sig: int) -> None:
        try:
            os.killpg(self._proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            # The group is already gone. macOS reports a group holding only
            # zombies as EPERM rather than ESRCH; either way nothing is left
            # to signal.
            pass

    def stop(self) -> float:
        """Stop the engine and return how long that took, in seconds.

        The float measures from this call until the `vllm serve` parent
        process has exited: SIGTERM to the whole process group, up to
        `term_grace` seconds of waiting, then SIGKILL to the group if the
        parent is still alive. After the parent exits, the group is swept with
        SIGKILL so no straggling child keeps the GPU.

        It does NOT measure GPU memory release. The driver frees a process's
        memory shortly after the process dies, and how shortly is exactly what
        artifact 4's swap handler measures by polling the device after this
        returns. Folding a poll in here would hard-code one artifact's
        definition of "torn down" into everyone's.

        Idempotent: a second call signals nothing and returns the first call's
        value, so a caller can time teardown inside the `with` block and the
        block's own exit does no harm. An engine that had already exited
        returns roughly 0.0.
        """
        if self._teardown_s is not None:
            return self._teardown_s
        t0 = self._clock()
        if self._proc.poll() is None:
            self._signal_group(signal.SIGTERM)
            try:
                self._proc.wait(timeout=self._term_grace)
            except subprocess.TimeoutExpired:
                self._signal_group(signal.SIGKILL)
                self._proc.wait()
        self._teardown_s = self._clock() - t0
        self._signal_group(signal.SIGKILL)
        # stdout reaches EOF only once every writer is gone; join so the
        # drain thread finishes appending before anyone reads log_lines.
        self._drain.join(timeout=DRAIN_JOIN_SECONDS)
        return self._teardown_s


def _wait_healthy(server: Server, timeout: float, health_ok, clock, sleep) -> bool:
    url = f"{server.base_url}/health"
    deadline = clock() + timeout
    while clock() < deadline:
        if server.returncode is not None:
            return False
        if health_ok(url):
            return True
        sleep(HEALTH_POLL_SECONDS)
    return False


@contextmanager
def served(
    model: str,
    *,
    args: Sequence[str],
    env: Mapping[str, str] | None,
    port: int = 8000,
    health_timeout: float = 900.0,
    executable: str = "vllm",
    term_grace: float = TERM_GRACE_SECONDS,
    health_ok: Callable[[str], bool] = _health_ok,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Server]:
    """Run `vllm serve model --port port *args` for the duration of the block.

    `env` is a dict of OVERRIDES, merged over a copy of `os.environ` for the
    engine process only. A full replacement environment was rejected: every
    caller would have to remember PATH, CUDA and HF variables, and the one that
    forgot would fail on a paid GPU. `os.environ` itself is never touched,
    because a serverless worker is reused across jobs and a mutated environment
    would carry one job's paths into the next.

    Yields a `Server`. Check `.healthy` before sending load: an engine that
    never answered `/health` within `health_timeout`, or exited first, is
    already stopped when it is yielded, so `.log_lines` is complete.

    The engine is always stopped on exit, including when the block raises.
    `executable`, `term_grace`, `health_ok`, `clock` and `sleep` exist for
    tests; production callers pass none of them.
    """
    args = list(args)
    _refuse_port_in_args(args)
    _refuse_busy_port(port)
    merged = os.environ.copy()
    merged.update(env or {})
    cmd = [executable, "serve", model, "--port", str(port), *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=merged,
        start_new_session=True,
    )
    server = Server(
        proc, cmd=cmd, base_url=f"http://127.0.0.1:{port}", term_grace=term_grace, clock=clock
    )
    try:
        server.healthy = _wait_healthy(server, health_timeout, health_ok, clock, sleep)
        if not server.healthy:
            server.stop()
        yield server
    finally:
        server.stop()
