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
- The engine's output is decoded with `errors="replace"`, and the log reader
  records any failure instead of dying silently. The probe's strict decoding
  lets one invalid byte kill its reader thread; the pipe then fills, the engine
  blocks writing to it, never answers `/health`, and the log that would explain
  why is empty. A replacement character in a log line costs nothing; a dead
  reader costs the whole run.
- Running in its own session means the engine no longer receives signals aimed
  at the caller's process group: a SIGTERM to the caller leaves the engine
  running. Accepted. On a serverless worker the container tears everything
  down, and locally the `finally` in `served` is what stops it, so only a
  caller killed outright (SIGKILL) can leave one behind.
- A port that something already answers on is refused before spawning. The
  health check would otherwise talk to whatever owns the port and report
  someone else's engine as this one.
"""

import contextlib
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

    One object carries the address, the verdict and the evidence, because the
    caller needs all three at once: `base_url` to send load to, `healthy` to
    know whether to, and `log_lines` for artifact 5 to read the KV-cache line
    from. Returning a bare URL and a separate log handle was rejected: the two
    would have to be kept in step across an exception.

    `log_lines` grows while the engine runs. It is the complete log only when
    `drain_completed` is True; read that flag before trusting the log's tail.
    `cmd` is the exact argument list that was executed, including the `--port`
    that `served` added.
    """

    def __init__(
        self,
        proc: subprocess.Popen[str],
        *,
        cmd: list[str],
        base_url: str,
        term_grace: float,
        clock: Callable[[], float],
    ) -> None:
        self.cmd = cmd
        self.base_url = base_url
        self.healthy = False
        self.log_lines: list[str] = []
        self._proc = proc
        self._term_grace = term_grace
        self._clock = clock
        self._teardown_s: float | None = None
        self._drain_eof = False
        self._drain_error: Exception | None = None
        self._drain = threading.Thread(target=self._drain_stdout, daemon=True)
        self._drain.start()

    def _drain_stdout(self) -> None:
        try:
            for line in self._proc.stdout:
                self.log_lines.append(line.rstrip("\n"))
            self._drain_eof = True
        except Exception as exc:  # noqa: BLE001 -- a reader thread has no caller to raise to
            # Record it where `drain_error` and `drain_completed` can report
            # it, then keep emptying the pipe: a reader that stops reading
            # blocks the engine on a full pipe and turns a logging fault into
            # a failed run.
            self._drain_error = exc
            self._discard_rest()

    def _discard_rest(self) -> None:
        # Best effort: the first error is already recorded.
        with contextlib.suppress(Exception):
            for _ in self._proc.stdout:
                pass

    @property
    def returncode(self) -> int | None:
        """None while the engine runs; its exit status once it has exited.

        A property over `Popen.poll()` rather than a stored value, so a caller
        asking "is it still up?" gets the live answer, and the tests for the
        process-exit paths do not need to know about `Popen`.
        """
        return self._proc.poll()

    @property
    def drain_error(self) -> Exception | None:
        """The exception that stopped the log reader appending, if any."""
        return self._drain_error

    @property
    def drain_completed(self) -> bool:
        """True only if the log reader reached EOF without error.

        EOF arrives once every process holding the engine's stdout has exited,
        so True means `log_lines` is complete. It is False while the engine
        runs, if `stop()` gave up waiting for the reader (a grandchild that
        called `setsid` escapes the group kill by design and keeps the pipe
        open), or if the reader failed (`drain_error`). "The thread is no
        longer alive" was rejected as the definition: a reader that died on an
        exception is not alive either, and reporting its truncated log as
        complete is the failure this flag exists to expose.
        """
        return self._drain_eof and self._drain_error is None

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

        Teardown signals the whole process group at once rather than going
        through vLLM's own parent-led shutdown, where the API server stops
        its workers in turn. What that does to the last lines of the log and
        to the time taken is inferred from how signals work, not verified
        against vLLM. Artifact 4 should treat the float as "time until the
        parent exited" and nothing finer.

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
        # drain thread finishes appending before anyone reads log_lines. A
        # grandchild that called setsid survived the sweep above and holds the
        # pipe open: the join then times out and `drain_completed` is False.
        self._drain.join(timeout=DRAIN_JOIN_SECONDS)
        return self._teardown_s


def _wait_healthy(
    server: Server,
    timeout: float,
    health_ok: Callable[[str], bool],
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
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
    already stopped when it is yielded, so `.log_lines` is complete unless
    `.drain_completed` says otherwise.

    That stop happens inside `__enter__`, before the yield. A caller timing
    the `with` statement's entry on the unhealthy path therefore measures the
    health wait PLUS teardown: up to `term_grace` seconds and the log reader's
    join (15 s) on top. Stopping after the yield was rejected because the
    caller would then be handed a running engine it has no reason to touch.

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
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
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
