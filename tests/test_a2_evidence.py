"""Derived evidence: load-balancer throughput and routing, stalls, host speed."""

import pytest

from autoscale import a2_evidence as ev


def _row(i, sent, latency, worker="w1", server_ms="300", status=200):
    return {"index": i, "scheduled": sent, "sent": sent, "latency": latency, "status": status,
            "headers": {"x-a2-worker": worker, "x-a2-server-latency-ms": server_ms}}


def test_delivered_rate_counts_completions_over_their_span():
    rows = [_row(i, i * 0.1, 0.5) for i in range(11)]  # completions 0.5 .. 1.5 s
    assert ev.delivered_rate(rows) == pytest.approx(11 / 1.0)


def test_per_worker_concurrency_reconstructs_server_side_occupancy():
    # two overlapping requests on w1, one on w2; server interval ends return_leg_s before
    # the client saw the response and lasts the server latency
    rows = [_row(0, 0.0, 1.1, "w1", "1000"), _row(1, 0.2, 1.1, "w1", "1000"),
            _row(2, 0.0, 1.1, "w2", "1000")]
    got = ev.per_worker_concurrency(rows, return_leg_s=0.1)
    assert got["w1"]["max"] == 2 and got["w2"]["max"] == 1
    assert got["w1"]["requests"] == 2


def test_stall_share_is_the_fraction_of_requests_slower_than_two_seconds():
    record = {"client_latency_s": [0.5, 2.5, 3.0, None, 0.4], "status": [200] * 5}
    assert ev.stall_share(record, threshold_s=2.0) == pytest.approx(2 / 4)


def test_host_speed_table_divides_each_hosts_medians_by_the_curve():
    curve = {32: 0.4, 64: 0.5, 128: 0.6}
    runs = [{"level": 64, "latency_s": 0.45, "outcome": "ok", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 0.47, "outcome": "ok", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 0.49, "outcome": "ok", "host": {"host_id": "h"}}]
    table = ev.host_speed_table(runs, curve)
    assert table["h"][64]["ratio"] == pytest.approx(0.47 / 0.5)
    assert table["h"][64]["n"] == 3


def test_delivered_rate_refuses_fewer_than_two_completions():
    with pytest.raises(ValueError, match="fewer than two"):
        ev.delivered_rate([_row(0, 0.0, 0.5)])


def test_delivered_rate_excludes_non_200_rows():
    rows = [_row(i, i * 0.1, 0.5) for i in range(11)]
    rows.append(_row(11, 0.0, 30.0, status=503))  # would stretch the span if counted
    assert ev.delivered_rate(rows) == pytest.approx(11 / 1.0)


def test_delivered_rate_with_only_failures_refuses():
    rows = [_row(0, 0.0, 0.5, status=503), _row(1, 0.1, 0.5, status=503)]
    with pytest.raises(ValueError, match="fewer than two"):
        ev.delivered_rate(rows)


def test_per_worker_concurrency_excludes_non_200_rows():
    rows = [_row(0, 0.0, 1.1, "w1", "1000"), _row(1, 0.2, 1.1, "w1", "1000", status=503),
            _row(2, 0.0, 1.1, "w2", "1000", status=500)]
    got = ev.per_worker_concurrency(rows, return_leg_s=0.1)
    assert got["w1"]["requests"] == 1 and got["w1"]["max"] == 1
    assert "w2" not in got


def test_stall_share_with_no_completed_requests_refuses():
    record = {"client_latency_s": [None, None, 3.0], "status": [0, 0, 503]}
    with pytest.raises(ValueError, match="no completed requests"):
        ev.stall_share(record, threshold_s=2.0)


def test_host_speed_table_excludes_runs_that_are_not_ok():
    curve = {64: 0.5}
    runs = [{"level": 64, "latency_s": 0.45, "outcome": "ok", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 9.0, "outcome": "timeout", "host": {"host_id": "h"}},
            {"level": 64, "latency_s": 9.0, "outcome": "error", "host": {"host_id": "bad"}}]
    table = ev.host_speed_table(runs, curve)
    assert table["h"][64]["n"] == 1
    assert table["h"][64]["median_s"] == pytest.approx(0.45)
    assert "bad" not in table
