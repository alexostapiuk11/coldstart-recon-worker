"""The LB probe and its shared pieces, with no network."""

import sys
from pathlib import Path

import pytest
import requests

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common
import a2_lb_probe as probe

from harness.open_loop import Outcome


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the probe test touched the network")
    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)


def test_the_url_and_payload_match_the_curves_request_shape():
    assert common.lb_url("abc123") == "https://abc123.api.runpod.ai/v1/completions"
    p = common.payload()
    assert len(p["prompt"]) == 13 and all(isinstance(t, int) for t in p["prompt"])
    assert p["max_tokens"] == 16 and p["ignore_eos"] is True
    assert "temperature" not in p and p["model"] == "Qwen/Qwen3-8B"


def test_constant_rate_spaces_requests_evenly():
    s = common.constant_rate(4.0, 2.0)
    assert s == (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75)


def _o(i, status=200, worker="w1", client=0.5, server_ms="300.0", sent=None):
    sent = i * 0.1 if sent is None else sent
    headers = {} if worker is None else {common.WORKER: worker, common.SERVER_LATENCY: server_ms}
    return Outcome(i, i * 0.1, sent, client if status else None, status, headers,
                   None if status else "err")


def test_summarize_counts_shares_latencies_and_jitter():
    outs = [_o(0), _o(1, worker="w2"), _o(2, worker="w2"), _o(3, status=503), _o(4, sent=0.9)]
    s = common.summarize(outs)
    assert s["requests"] == 5 and s["non_200"] == 1
    assert s["worker_share"] == {"w1": 0.5, "w2": 0.5}
    assert s["client_p50_s"] == pytest.approx(0.5)
    assert s["server_p50_s"] == pytest.approx(0.3)
    assert s["client_minus_server_p50_s"] == pytest.approx(0.2)
    assert s["max_jitter_s"] == pytest.approx(0.5)


class FakeReplay:
    """Answers each warm-up chunk from a script of worker ids."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.kwargs = []

    def __call__(self, schedule, send, **kw):
        self.kwargs.append(kw)
        workers = self.chunks.pop(0)
        return [Outcome(i, t, t, 0.3, 200 if w else 503, {common.WORKER: w} if w else {})
                for i, (t, w) in enumerate(zip(schedule, workers * len(schedule)))]


def test_warm_up_returns_once_all_workers_answered_cleanly_long_enough():
    rep = FakeReplay([["w1"], ["w1", "w2"], ["w1", "w2"], ["w1", "w2"], ["w1", "w2"],
                      ["w1", "w2"], ["w1", "w2"], ["w1", "w2"]])
    ids = common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                         max_seconds=600.0, chunk_seconds=5.0, replay_fn=rep)
    assert ids == ["w1", "w2"]
    assert rep.kwargs[0] == {"max_in_flight": 64, "start_delay": 0.1}


def test_warm_up_refuses_more_workers_than_pinned():
    rep = FakeReplay([["w1", "w2", "w3"]])
    with pytest.raises(RuntimeError, match="3 distinct workers"):
        common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                       max_seconds=600.0, chunk_seconds=5.0, replay_fn=rep)


def test_warm_up_gives_up_at_its_limit():
    rep = FakeReplay([["w1"]] * 10)
    with pytest.raises(TimeoutError, match="1 of 2"):
        common.warm_up(lambda i: (200, {}), workers=2, rps=2.0, min_clean=30.0,
                       max_seconds=20.0, chunk_seconds=5.0, replay_fn=rep)


def test_acceptance_reads_the_amendments_three_conditions():
    ok = {"non_200": 0, "errors": 0, "worker_share": {"a": 0.5, "b": 0.5}, "max_jitter_s": 0.1}
    assert probe.accept(ok, workers=2) == (True, [])
    bad = {"non_200": 2, "errors": 0, "worker_share": {"a": 0.8, "b": 0.2}, "max_jitter_s": 0.4}
    passed, why = probe.accept(bad, workers=2)
    assert not passed and len(why) == 3


def test_the_ladder_and_thresholds_are_the_amendments():
    assert probe.RATES == (25.0, 50.0, 100.0, 200.0, 300.0, 450.0)
    assert probe.STEP_SECONDS == 30.0
    assert probe.MIN_WORKER_SHARE == 0.35 and probe.MAX_JITTER_S == 0.25
