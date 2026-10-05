"""Host-speed calibration before each repeat (amendment 2026-10-05, fourth)."""

import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common
import a2_validate as v

from autoscale.service import ServiceCurve
from autoscale.sim import run_fixed_capacity
from autoscale.validation import (
    CALIBRATION_LEVELS,
    EngineRun,
    engine_trajectories,
    host_scaled_curve,
    validate_engine_arrivals,
)
from harness.open_loop import Outcome

CURVE = ServiceCurve(points=[(0, 0.3, 0.0, 0.0), (1, 0.3, 50.0, 1.0), (64, 0.44, 2300.0, 1.0),
                             (128, 0.6, 3400.0, 1.0)], measured=True)
UNTIL = 200.0


def test_the_calibration_constants_are_the_amendments():
    assert CALIBRATION_LEVELS == (64.0, 128.0)
    assert (common.CALIBRATION_SETTLE_S, common.CALIBRATION_MEASURE_S,
            common.CALIBRATION_MIN_REQUESTS) == (10.0, 60.0, 500)


def test_the_curve_is_scaled_by_the_64_ratio_below_and_the_128_ratio_above():
    scaled = host_scaled_curve(CURVE, (0.95, 0.90))
    assert scaled.measured is True
    assert scaled.latency_at(1) == pytest.approx(0.3 * 0.95)
    assert scaled.latency_at(64) == pytest.approx(0.44 * 0.95)
    assert scaled.latency_at(128) == pytest.approx(0.6 * 0.90)
    # between the two calibrated levels the scaled endpoints are interpolated linearly
    assert scaled.latency_at(96) == pytest.approx((0.44 * 0.95 + 0.6 * 0.90) / 2)
    assert scaled.points[2][2] == pytest.approx(2300.0 / 0.95)  # throughput moves the other way


@pytest.mark.parametrize("bad", [(0.0, 1.0), (1.0, -0.1), (float("nan"), 1.0), (1.0, float("inf"))])
def test_a_ratio_that_is_not_a_positive_finite_number_is_refused(bad):
    with pytest.raises(ValueError, match="ratio"):
        host_scaled_curve(CURVE, bad)


def _schedule(seed=3, rate=40.0, until=170.0):
    rng = random.Random(seed)
    t, out = 0.0, []
    while True:
        t += rng.expovariate(rate)
        if t > until:
            return out
        out.append(t)


def _runs_on_a_fast_host(ratios):
    """Real latencies produced by the host-scaled model, on the schedule's arrivals."""
    s = _schedule()
    sim = run_fixed_capacity(s, 1, host_scaled_curve(CURVE, (0.9, 0.85)), UNTIL)
    by_arrival = dict(sim.completed_requests())
    lat = tuple(by_arrival[t] for t in s)
    return [EngineRun(sent=tuple(s), received=tuple(t + 100.0 for t in s), latencies=lat,
                      replicas=1, until=UNTIL, host_ids=(f"w{k}",), host_ratios=ratios)
            for k in range(3)]


def test_the_gate_predicts_each_repeat_on_its_own_host_speed():
    assert validate_engine_arrivals(_runs_on_a_fast_host((0.9, 0.85)), CURVE).misses == 0
    unscaled = validate_engine_arrivals(_runs_on_a_fast_host(None), CURVE)
    assert unscaled.misses > unscaled.compared / 2  # the first attempt's failure, in miniature
    real, pred = engine_trajectories(_runs_on_a_fast_host((0.9, 0.85))[0], CURVE)
    assert [b.p50 for b in real] == pytest.approx([b.p50 for b in pred], abs=1e-9)


def _rows(n, *, latency=0.4, status=200, start=12.0):
    return [{"start": start, "end": start + latency, "status": status,
             "server_latency_s": latency if status == 200 else None, "error": None}
            for _ in range(n)]


def test_calibrate_reports_medians_ratios_and_the_measured_window():
    def fake(send, concurrency, seconds):
        assert seconds == common.CALIBRATION_SETTLE_S + common.CALIBRATION_MEASURE_S
        settling = _rows(50, latency=9.0, start=2.0)  # inside the settle window: not measured
        return settling + _rows(600, latency=0.44 * 0.95 if concurrency == 64 else 0.6 * 0.9)
    cal = common.calibrate(lambda i: (200, {}), CURVE, closed_loop_fn=fake)
    assert cal["void"] == []
    assert cal["ratios"] == pytest.approx([0.95, 0.90])
    assert cal["levels"]["64"]["measured"] == 600 and cal["levels"]["64"]["settling"] == 50


def test_too_few_requests_or_any_non_200_voids_the_calibration():
    def thin(send, concurrency, seconds):
        return _rows(400)
    cal = common.calibrate(lambda i: (200, {}), CURVE, closed_loop_fn=thin)
    assert cal["ratios"] is None and any("fewer than 500" in r for r in cal["void"])

    def failing(send, concurrency, seconds):
        return _rows(600) + _rows(1, status=502)
    cal = common.calibrate(lambda i: (200, {}), CURVE, closed_loop_fn=failing)
    assert cal["ratios"] is None and any("not 200" in r for r in cal["void"])


def test_closed_loop_keeps_the_requested_number_outstanding():
    import threading
    import time
    live, peak, lock = [0], [0], threading.Lock()

    def send(i):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.01)
        with lock:
            live[0] -= 1
        return 200, {common.SERVER_LATENCY: "10.0"}

    rows = common.closed_loop(send, 4, 0.3)
    assert peak[0] == 4 and len(rows) > 40
    assert all(r["status"] == 200 and r["server_latency_s"] == pytest.approx(0.01) for r in rows)


# --- run_repeat: calibration between warm-up and replay ---------------------------------


class FakePin:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(tmp_path, calibration, replays):
    s = _schedule()

    def replay_fn(schedule, send):
        replays.append(1)
        return [Outcome(i, t, t, 0.5, 200,
                               {common.WORKER: "w1", common.SERVER_LATENCY: "400",
                                common.SERVER_RECEIVED: f"{100 + t:.6f}"})
                for i, t in enumerate(schedule)]

    return v.run_repeat(k=1, schedule=s, pin=FakePin(), send=lambda i: (200, {}),
                        warm_fn=lambda send, out: ["w1"], replay_fn=replay_fn,
                        calibrate_fn=lambda send: calibration, endpoint_id="ep",
                        template_id="t", replicas=1, until=UNTIL, now=lambda: "now",
                        path=tmp_path / "repeat-1.json.gz")


def test_a_valid_calibration_is_recorded_and_the_replay_runs(tmp_path):
    replays = []
    cal = {"levels": {}, "ratios": [0.95, 0.9], "void": []}
    rec = _run(tmp_path, cal, replays)
    assert replays == [1] and rec["calibration"] == cal and rec["void"] == []
    assert v.read_record(tmp_path / "repeat-1.json.gz")["calibration"]["ratios"] == [0.95, 0.9]


def test_a_void_calibration_writes_a_void_record_and_skips_the_replay(tmp_path):
    replays = []
    cal = {"levels": {}, "ratios": None, "void": ["calibration level 64: fewer than 500"]}
    rec = _run(tmp_path, cal, replays)
    assert replays == [] and rec["void"] == cal["void"]
    assert v.read_record(tmp_path / "repeat-1.json.gz")["void"] == cal["void"]


def test_judge_refuses_records_without_a_calibration(tmp_path):
    rec = {"schema_version": 2, "repeat": 1, "void": [], "server_received_s": []}
    v.write_record(v.prepare_slot(tmp_path, 1), rec)
    for k in (2, 3):
        v.write_record(v.prepare_slot(tmp_path, k), {**rec, "repeat": k})
    with pytest.raises(SystemExit, match="calibration"):
        v.judge(tmp_path, CURVE)
