"""The `vllm serve` lifecycle, proven against a fake engine.

vLLM is not installed locally, and these tests must not need it. A fake
`vllm` executable is written into tmp_path and put first on PATH: it prints
startup lines in the engine's own wording, serves `/health` on the port it was
given, and misbehaves on request (never healthy, exits early, ignores SIGTERM,
spawns a child) so each failure path runs against a real process.
"""

import inspect
import os
import signal
import socket
import subprocess
import sys
import time

import pytest
import requests

from harness import serve
from harness.serve import served

KV_LINE = "INFO GPU KV cache size: 43,040 tokens"

FAKE_VLLM = r'''
import http.server
import os
import signal
import subprocess
import sys
import time

argv = sys.argv[1:]
assert argv[0] == "serve", argv
port = int(argv[argv.index("--port") + 1])
mode = os.environ.get("FAKE_VLLM_MODE", "healthy")
print("ARGV " + " ".join(argv), flush=True)
for key in filter(None, os.environ.get("FAKE_VLLM_ECHO", "").split(",")):
    print(f"ENV {key}={os.environ.get(key)}", flush=True)
print("INFO fake engine starting", flush=True)
print("INFO GPU KV cache size: 43,040 tokens", flush=True)
print("INFO torch.compile took 0.30 s in total", flush=True)
if mode == "exit":
    sys.exit(3)
if mode == "stubborn":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if mode == "child":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(os.environ["FAKE_VLLM_CHILD_PID"], "w") as f:
        f.write(str(child.pid))
if mode == "never_healthy":
    time.sleep(600)
    sys.exit(0)
if mode == "binary":
    # Invalid UTF-8, then enough output to fill a 64 KB pipe several times
    # over: an engine whose log reader died would block here and never serve.
    sys.stdout.buffer.write(b"INFO before \xff\xfe bad bytes\n")
    for i in range(500):
        sys.stdout.buffer.write(b"INFO filler %d " % i + b"x" * 200 + b"\n")
    sys.stdout.buffer.flush()
if mode == "sticky_child":
    code = (
        "import os, signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "open(os.environ['FAKE_VLLM_CHILD_PID'], 'w').write(str(os.getpid()))\n"
        "time.sleep(600)\n"
    )
    subprocess.Popen([sys.executable, "-c", code])
if mode == "tail":
    def goodbye(*_):
        for i in range(20):
            print(f"TAIL {i}", flush=True)
        os._exit(0)
    signal.signal(signal.SIGTERM, goodbye)


class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", port), Health).serve_forever()
'''


@pytest.fixture(autouse=True)
def fake_vllm(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "vllm"
    exe.write_text(f"#!{sys.executable}\n{FAKE_VLLM}")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return exe


@pytest.fixture
def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    ).stdout.strip()
    return bool(stat) and not stat.startswith("Z")


def test_the_signature_is_the_one_artifacts_4_and_5_code_against():
    params = inspect.signature(served).parameters
    assert {"model", "args", "env", "port", "health_timeout"} <= set(params)
    assert params["port"].default == 8000
    assert params["health_timeout"].default == 900.0
    assert params["args"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["env"].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_healthy_engine_yields_its_url_and_its_startup_log(port):
    with served("m", args=["--revision", "r1"], env={}, port=port, health_timeout=30) as server:
        assert server.healthy is True
        assert server.base_url == f"http://127.0.0.1:{port}"
        assert requests.get(f"{server.base_url}/health", timeout=2).status_code == 200
        assert server.cmd == ["vllm", "serve", "m", "--port", str(port), "--revision", "r1"]
    assert f"ARGV serve m --port {port} --revision r1" in server.log_lines
    assert KV_LINE in server.log_lines
    assert server.drain_completed


@pytest.mark.parametrize("bad", [["--port", "9000"], ["--port=9000"]])
def test_a_port_in_args_is_refused_because_served_adds_its_own(bad, port):
    with pytest.raises(ValueError, match="passes --port itself"), served(
        "m", args=bad, env={}, port=port
    ):
        pass


def test_env_is_merged_over_the_parent_environment_and_never_applied_to_it(port, monkeypatch):
    monkeypatch.setenv("FROM_PARENT", "parent")
    monkeypatch.delenv("OVERRIDE", raising=False)
    env = {"FAKE_VLLM_ECHO": "FROM_PARENT,OVERRIDE", "OVERRIDE": "mine"}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
    assert "ENV FROM_PARENT=parent" in server.log_lines
    assert "ENV OVERRIDE=mine" in server.log_lines
    assert "OVERRIDE" not in os.environ


def test_an_engine_that_never_answers_is_yielded_unhealthy_with_its_log(port):
    env = {"FAKE_VLLM_MODE": "never_healthy"}
    with served("m", args=[], env=env, port=port, health_timeout=1.0) as server:
        assert server.healthy is False
        assert server.returncode is not None, "an unhealthy engine is stopped before the yield"
        assert KV_LINE in server.log_lines


def test_the_wait_ends_as_soon_as_the_engine_exits(port):
    started = time.monotonic()
    with served("m", args=[], env={"FAKE_VLLM_MODE": "exit"}, port=port, health_timeout=60) as s:
        assert s.healthy is False
        assert s.returncode == 3
        assert KV_LINE in s.log_lines
    assert time.monotonic() - started < 10, "waited out the health budget on a dead process"


def test_stop_is_idempotent_and_returns_the_teardown_seconds(port):
    with served("m", args=[], env={}, port=port, health_timeout=30) as server:
        first = server.stop()
        assert server.returncode is not None
        assert first >= 0.0
        assert server.stop() == first
    assert server.stop() == first


def test_the_whole_process_group_is_killed(port, tmp_path):
    pid_file = tmp_path / "child.pid"
    env = {"FAKE_VLLM_MODE": "child", "FAKE_VLLM_CHILD_PID": str(pid_file)}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
        child = int(pid_file.read_text())
        assert _alive(child)
    deadline = time.monotonic() + 5
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(child), "a child of the engine outlived teardown and would hold the GPU"


def test_an_engine_that_ignores_sigterm_is_killed_after_the_grace_period(port):
    env = {"FAKE_VLLM_MODE": "stubborn"}
    with served("m", args=[], env=env, port=port, health_timeout=30, term_grace=0.5) as server:
        assert server.healthy
        took = server.stop()
    assert 0.5 <= took < 10
    assert server.returncode == -signal.SIGKILL


def test_an_exception_in_the_block_still_stops_the_engine(port):
    with (
        pytest.raises(RuntimeError, match="caller failed"),
        served("m", args=[], env={}, port=port, health_timeout=30) as server,
    ):
        assert server.healthy
        raise RuntimeError("caller failed")
    assert server.returncode is not None


def test_a_port_that_already_answers_is_refused_before_spawning(port):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
        listener.listen()
        with pytest.raises(RuntimeError, match="already answering"), served(
            "m", args=[], env={}, port=port
        ):
            pass


def _read_pid(pid_file) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return int(pid_file.read_text())
        except (FileNotFoundError, ValueError):
            time.sleep(0.02)
    raise AssertionError("the fake engine's child never reported its pid")


def _slow_log(monkeypatch, *, delay=0.05, fail_on=None):
    """Make the log list slow (or failing) so the drain thread lags the process."""

    class SlowList(list):
        def append(self, item):
            if fail_on is not None and fail_on in item:
                raise ValueError("log sink refused a line")
            time.sleep(delay)
            super().append(item)

    original = serve.Server.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.log_lines = SlowList(self.log_lines)

    monkeypatch.setattr(serve.Server, "__init__", init)


def test_undecodable_engine_output_does_not_stop_the_log_reader(port):
    env = {"FAKE_VLLM_MODE": "binary"}
    with served("m", args=[], env=env, port=port, health_timeout=10) as server:
        assert server.healthy is True, "the engine blocked on a full pipe nobody was reading"
    assert KV_LINE in server.log_lines, "lines before the bad bytes were lost"
    assert any(line.startswith("INFO before") for line in server.log_lines)
    assert any(line.startswith("INFO filler 499 ") for line in server.log_lines)
    assert server.drain_completed is True
    assert server.drain_error is None


def test_a_failing_log_reader_is_recorded_not_reported_as_complete(port, monkeypatch):
    _slow_log(monkeypatch, delay=0.0, fail_on="KV cache")
    env = {"FAKE_VLLM_MODE": "binary"}  # >64 KB follows the line the sink refuses
    with served("m", args=[], env=env, port=port, health_timeout=10) as server:
        assert server.healthy is True, "a failed log reader must keep emptying the pipe"
    assert isinstance(server.drain_error, ValueError)
    assert server.drain_completed is False, "a log with a hole was reported complete"
    assert KV_LINE not in server.log_lines


def test_a_child_that_ignores_sigterm_is_swept_after_the_parent_exits(port, tmp_path):
    pid_file = tmp_path / "child.pid"
    env = {"FAKE_VLLM_MODE": "sticky_child", "FAKE_VLLM_CHILD_PID": str(pid_file)}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
        child = _read_pid(pid_file)
        try:
            server.stop()
            deadline = time.monotonic() + 5
            while _alive(child) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _alive(child), "SIGTERM-proof child survived: the post-exit sweep is gone"
        finally:
            if _alive(child):
                os.kill(child, signal.SIGKILL)
    assert server.drain_completed


def test_stop_returns_only_after_the_engines_last_words_are_in_the_log(port, monkeypatch):
    _slow_log(monkeypatch)
    env = {"FAKE_VLLM_MODE": "tail"}
    with served("m", args=[], env=env, port=port, health_timeout=30) as server:
        assert server.healthy
        server.stop()
        assert "TAIL 19" in server.log_lines, "stop() returned before the log reader caught up"
        assert server.drain_completed


class _FakeTime:
    """A clock that only moves when sleep is called, and records every sleep."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_the_health_budget_is_spent_in_poll_steps_on_the_injected_clock(port):
    fake = _FakeTime()
    urls = []

    def never(url):
        urls.append(url)
        return False

    env = {"FAKE_VLLM_MODE": "never_healthy"}
    with served(
        "m", args=[], env=env, port=port, health_timeout=10.0,
        health_ok=never, clock=fake.clock, sleep=fake.sleep,
    ) as server:  # fmt: skip
        assert server.healthy is False
    assert fake.sleeps == [serve.HEALTH_POLL_SECONDS] * 40
    assert set(urls) == {f"http://127.0.0.1:{port}/health"}
    assert len(urls) == 40


def test_the_wait_returns_on_the_first_answering_poll(port):
    fake = _FakeTime()
    answers = iter([False, False, True])
    env = {"FAKE_VLLM_MODE": "never_healthy"}
    with served(
        "m", args=[], env=env, port=port, health_timeout=10.0,
        health_ok=lambda url: next(answers), clock=fake.clock, sleep=fake.sleep,
    ) as server:  # fmt: skip
        assert server.healthy is True
    assert len(fake.sleeps) == 2
