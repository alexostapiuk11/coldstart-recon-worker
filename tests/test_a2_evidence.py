"""Derived evidence: load-balancer throughput and routing, stalls, host speed."""

import pytest

from autoscale import a2_evidence as ev


def _row(i, sent, latency, worker="w1", server_ms="300", status=200):
    return {"index": i, "scheduled": sent, "sent": sent, "latency": latency, "status": status,
            "headers": {"x-a2-worker": worker, "x-a2-server-latency-ms": server_ms}}


def test_delivered_rate_counts_intervals_between_completions_not_completions():
    # 11 completions 0.1 s apart span 1.0 s and enclose 10 intervals: 10/s, not 11/s
    rows = [_row(i, i * 0.1, 0.5) for i in range(11)]  # completions 0.5 .. 1.5 s
    assert ev.delivered_rate(rows) == pytest.approx(10.0)


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
    assert ev.delivered_rate(rows) == pytest.approx(10.0)


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


def test_per_worker_concurrency_touching_intervals_do_not_overlap():
    # first request's server interval is [0.0, 1.0]; the second's starts exactly where
    # that ends. Return leg 0.0 so the client-side end is the server-side end.
    rows = [_row(0, 0.0, 1.0, "w1", "1000"), _row(1, 1.0, 1.0, "w1", "1000")]
    got = ev.per_worker_concurrency(rows, return_leg_s=0.0)
    assert got["w1"]["max"] == 1


def test_per_worker_concurrency_mean_is_the_time_weighted_level():
    # w1 intervals [0, 2] and [1, 3]: level 1 on [0,1], 2 on [1,2], 1 on [2,3]
    # area = 1 + 2 + 1 = 4 over a span of 3 s -> 4/3
    rows = [_row(0, 0.0, 2.0, "w1", "2000"), _row(1, 1.0, 2.0, "w1", "2000")]
    got = ev.per_worker_concurrency(rows, return_leg_s=0.0)
    assert got["w1"]["max"] == 2
    assert got["w1"]["mean"] == pytest.approx(4 / 3)


def _validation_record(received, latency, status=None, client=None):
    n = len(received)
    return {"server_received_s": received, "server_latency_s": latency,
            "status": status or [200] * n, "client_latency_s": client or [None] * n}


def test_engine_occupancy_counts_requests_in_flight_at_each_arrival_including_itself():
    # intervals [0, 2], [1, 2], [1.5, 3.5], [2, 3]: at 2.0 the first two have ended
    rec = _validation_record([0.0, 1.0, 1.5, 2.0], [2.0, 1.0, 2.0, 1.0])
    got = ev.engine_occupancy(rec)
    assert [(t, n) for t, n, _ in got] == [(0.0, 1), (1.0, 2), (1.5, 3), (2.0, 2)]
    assert [lat for _, _, lat in got] == [2.0, 1.0, 2.0, 1.0]


def test_engine_occupancy_skips_requests_without_a_stamp_or_a_200():
    rec = _validation_record([0.0, None, 0.5, 0.6], [1.0, 1.0, None, 1.0],
                             status=[200, 200, 200, 400])
    assert [(t, n) for t, n, _ in ev.engine_occupancy(rec)] == [(0.0, 1)]


def test_engine_occupancy_refuses_a_record_with_no_stamped_request():
    with pytest.raises(ValueError, match="stamp"):
        ev.engine_occupancy(_validation_record([None], [0.3]))


def test_stall_breakdown_separates_time_outside_the_engine_from_engine_backlog():
    # client latencies 0.5, 2.5, 3.0, 4.0; server 0.3, 2.0, 0.5, 1.6
    rec = {"client_latency_s": [0.5, 2.5, 3.0, 4.0, None],
           "server_latency_s": [0.3, 2.0, 0.5, 1.6, None],
           "status": [200, 200, 200, 200, 502]}
    got = ev.stall_breakdown(rec, threshold_s=2.0, server_backlog_s=1.5)
    assert got["completed"] == 4
    assert got["share_client_over"] == pytest.approx(3 / 4)
    # client - server: 0.2, 0.5, 2.5, 2.4 -> two over 2 s
    assert got["share_client_minus_server_over"] == pytest.approx(2 / 4)
    # of the three over 2 s client-side, server 2.0 and 1.6 exceed 1.5
    assert got["share_of_slow_with_server_over"] == pytest.approx(2 / 3)
