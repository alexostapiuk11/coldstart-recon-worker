"""The driver retries, once, a 502 that the load balancer returned without reaching a worker."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common

from harness.open_loop import Outcome

W = {common.WORKER: "w1", common.SERVER_LATENCY: "300"}


def _scripted(*responses):
    calls = []
    answers = list(responses)

    def send(i):
        calls.append(i)
        return answers.pop(0)
    return send, calls


def test_a_workerless_502_is_retried_once_and_marked():
    send, calls = _scripted((502, {}), (200, dict(W)))
    status, headers = common.retry_lb_502(send)(7)
    assert (status, calls) == (200, [7, 7])
    assert headers[common.WORKER] == "w1"
    assert headers[common.RETRY_MARK].startswith("502:")


def test_a_second_502_is_returned_not_retried_again():
    send, calls = _scripted((502, {}), (502, {}))
    status, headers = common.retry_lb_502(send)(3)
    assert (status, calls) == (502, [3, 3])
    assert common.RETRY_MARK in headers


def test_a_502_from_a_worker_is_not_retried():
    send, calls = _scripted((502, dict(W)))
    status, headers = common.retry_lb_502(send)(1)
    assert (status, calls) == (502, [1]) and common.RETRY_MARK not in headers


def test_other_failures_and_successes_are_not_retried():
    for answer in ((503, {}), (504, {}), (500, {}), (200, dict(W))):
        send, calls = _scripted(answer)
        status, headers = common.retry_lb_502(send)(0)
        assert (status, calls) == (answer[0], [0]) and common.RETRY_MARK not in headers


def test_the_shared_sender_retries(monkeypatch):
    send, calls = _scripted((502, {}), (200, dict(W)))
    monkeypatch.setattr(common, "http_sender", lambda *a, **kw: send)
    status, _ = common.sender("ep", "key")(5)
    assert status == 200 and calls == [5, 5]


def _o(i, status, headers):
    return Outcome(i, float(i), float(i), 0.5, status, headers)


def test_summarize_counts_retried_requests_and_judges_the_final_status():
    outs = [_o(0, 200, dict(W)), _o(1, 200, {**W, common.RETRY_MARK: "502:0.240"}),
            _o(2, 502, {common.RETRY_MARK: "502:0.200"})]
    s = common.summarize(outs)
    assert s["lb_502_retried"] == 2
    assert s["non_200"] == 1  # the one whose retry also failed


def test_the_validation_record_counts_retries_and_voids_only_a_failed_retry():
    import a2_validate as v
    ok = [_o(0, 200, dict(W)), _o(1, 200, {**W, common.RETRY_MARK: "502:0.240"})]
    kw = {"repeat": 1, "schedule": [0.0, 1.0], "host_ids": ["w1"], "endpoint_id": "ep",
          "template_id": "t", "started_at": "now", "replicas": 2, "until": 400.0}
    rec = v.record_from(ok, **kw)
    assert rec["void"] == [] and rec["lb_502_retried"] == [1]
    bad = [ok[0], _o(1, 502, {common.RETRY_MARK: "502:0.240"})]
    rec = v.record_from(bad, **kw)
    assert rec["void"] and rec["lb_502_retried"] == [1]
