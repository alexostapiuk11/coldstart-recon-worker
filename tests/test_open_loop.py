"""replay(): one schedule, sent on its own clock, every outcome kept."""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness import open_loop
from harness.open_loop import Outcome, http_sender, max_jitter, replay


def test_outcomes_come_back_in_schedule_order_with_send_times_near_schedule():
    schedule = [i * 0.01 for i in range(40)]
    outs = replay(schedule, lambda i: (200, {}), max_in_flight=8, start_delay=0.05)
    assert [o.index for o in outs] == list(range(40))
    assert all(isinstance(o, Outcome) and o.status == 200 for o in outs)
    assert max_jitter(outs) < 0.2
    assert all(o.latency is not None and o.latency >= 0 for o in outs)


def test_a_failed_send_is_kept_as_an_error_not_dropped():
    def send(i):
        if i == 2:
            raise ConnectionError("reset by peer")
        return (200, {})

    outs = replay([0.0, 0.01, 0.02, 0.03], send, max_in_flight=2, start_delay=0.01)
    assert len(outs) == 4
    assert outs[2].status is None and outs[2].latency is None
    assert "ConnectionError: reset by peer" in outs[2].error


def test_an_unsorted_schedule_is_refused():
    with pytest.raises(ValueError, match="ascending"):
        replay([0.0, 0.5, 0.2], lambda i: (200, {}))


def test_a_negative_time_is_refused():
    with pytest.raises(ValueError, match="negative"):
        replay([-0.1, 0.0], lambda i: (200, {}))


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("x-a2-worker", "w-local")
        self.send_header("x-a2-server-latency-ms", "12.5")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/completions"
    srv.shutdown()
    srv.server_close()


def test_http_sender_returns_status_and_the_kept_headers(server):
    send = http_sender(server, payload={"x": 1}, headers={"Authorization": "Bearer k"},
                       timeout=5.0, keep_headers=("x-a2-worker", "x-a2-server-latency-ms"))
    status, headers = send(0)
    assert status == 200
    assert headers == {"x-a2-worker": "w-local", "x-a2-server-latency-ms": "12.5"}


def test_replay_through_http_sender_end_to_end(server):
    send = http_sender(server, payload={}, headers={}, timeout=5.0, keep_headers=("x-a2-worker",))
    outs = replay([i * 0.005 for i in range(50)], send, max_in_flight=16, start_delay=0.05)
    assert sum(o.status == 200 for o in outs) == 50
    assert {o.headers["x-a2-worker"] for o in outs} == {"w-local"}


def test_dispatched_sits_between_scheduled_and_sent():
    outs = replay([i * 0.01 for i in range(10)], lambda i: (200, {}), max_in_flight=4,
                  start_delay=0.05)
    assert all(o.dispatched is not None and o.scheduled - 0.01 <= o.dispatched <= o.sent + 1e-3
               for o in outs)


def test_a_non_finite_time_is_refused():
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="NaN or infinite"):
            replay([0.0, bad], lambda i: (200, {}))


def test_a_pool_with_no_workers_is_refused():
    with pytest.raises(ValueError, match="max_in_flight"):
        replay([0.0], lambda i: (200, {}), max_in_flight=0)


def test_a_send_returning_none_headers_is_an_error_row_not_a_missing_one():
    outs = replay([0.0, 0.01], lambda i: (200, None), start_delay=0.01)
    assert len(outs) == 2
    assert all(o.status is None and o.error and "TypeError" in o.error for o in outs)


def test_a_send_raising_systemexit_is_an_error_row_not_a_missing_one():
    def send(i):
        if i == 1:
            raise SystemExit(3)
        return (200, {})

    outs = replay([0.0, 0.01, 0.02], send, start_delay=0.01)
    assert [o.index for o in outs] == [0, 1, 2]
    assert outs[1].status is None and "SystemExit" in outs[1].error
    assert outs[0].status == 200 and outs[2].status == 200


def test_a_row_that_somehow_goes_missing_raises_instead_of_shrinking_the_run(monkeypatch):
    class _DropsEverything:
        def __init__(self, max_workers):
            pass

        def submit(self, fn, *args):
            pass

        def shutdown(self, wait=True, cancel_futures=False):
            pass

    monkeypatch.setattr(open_loop, "ThreadPoolExecutor", _DropsEverything)
    with pytest.raises(RuntimeError, match=r"3 of 3 requests left no outcome row"):
        replay([0.0, 0.1, 0.2], lambda i: (200, {}), start_delay=0.0)


def test_an_interrupt_in_the_dispatcher_reraises_without_draining_the_backlog():
    calls = []

    def interrupting_sleep(seconds):
        calls.append(seconds)
        if len(calls) == 100:
            raise KeyboardInterrupt

    # 200 requests, each send 0.3 s, 2 workers; the interrupt lands after 100 are queued, so
    # draining that backlog would take ~15 s.
    # The schedule sits in the future so the injected sleep (which does not sleep) is
    # called on every entry and the dispatcher outruns the pool.
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        replay([5.0 + i * 0.001 for i in range(200)], lambda i: (time.sleep(0.3), (200, {}))[1],
               max_in_flight=2, start_delay=0.0, sleep=interrupting_sleep)
    assert time.monotonic() - started < 1.0


def test_a_pool_smaller_than_peak_rate_times_latency_shows_as_send_jitter():
    def send(i):
        time.sleep(0.05)
        return (200, {})

    outs = replay([i * 0.01 for i in range(20)], send, max_in_flight=1, start_delay=0.02)
    assert len(outs) == 20
    assert max_jitter(outs) > 0.3


class _FakeResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = {"X-A2-Worker": "w"}


class _FakeSession:
    def post(self, *args, **kwargs):
        return _FakeResponse()


def test_http_sender_makes_one_session_per_thread_and_reuses_it():
    made = []

    def factory():
        made.append(_FakeSession())
        return made[-1]

    send = http_sender("http://x", payload={}, headers={}, timeout=1.0,
                       keep_headers=("x-a2-worker",), session_factory=factory)
    barrier = threading.Barrier(3)

    def work():
        barrier.wait()  # all three alive at once, so no thread object is reused
        for i in range(5):
            assert send(i) == (200, {"x-a2-worker": "w"})

    threads = [threading.Thread(target=work) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(made) == 3
