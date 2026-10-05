"""replay(): one schedule, sent on its own clock, every outcome kept."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

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
