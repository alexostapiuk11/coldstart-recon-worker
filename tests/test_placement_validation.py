"""The validation gate on hand-built replay records whose latencies are the
simulator's own, offset per repeat, so the verdict is known in advance; and
one cross-check that the real driver and the simulator swap alike."""

import random
import time

import pytest
from test_placement_measure_replay import TENANTS, Completions, TimedEngines, _deps

from autoscale.service import ServiceCurve
from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement import validation
from placement.colocated import ColocatedSurface
from placement.fleet import Gpu, Placement
from placement.resample import EmpiricalDistribution
from placement.sim import Engines, simulate
from placement.validation import check_repeats, predict, replay_run, validate
from placement_measure.records import A4Run
from placement_measure.replay import ReplaySpec, replay

CURVE = ServiceCurve(points=[(1, 0.5, 2.0, 0.3), (8, 0.6, 13.0, 1.0)], measured=True)
SURFACE = ColocatedSurface(own=(1, 8), neighbour=(0, 8), latency=((0.5, 0.6), (0.6, 0.7)),
                           measured=True)
ENGINES = Engines(CURVE, SURFACE)
SWAP_S = 20.0
UNTIL = 400.0
# Tenant 0 every 0.4 s, so a 10 s bin holds 25 requests (the p50 floor is 20);
# tenant 1 and tenant 2 each force a swap and the swap back.
SCHEDULE = sorted([(round(0.4 * i, 3), 0) for i in range(900)]
                  + [(100.0 + 0.5 * i, 1) for i in range(20)]
                  + [(220.0 + 0.5 * i, 2) for i in range(20)])


def _simulated():
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    result = simulate(SCHEDULE, placement, ENGINES,
                      EmpiricalDistribution(samples=(SWAP_S,), measured=True), 0.0,
                      random.Random(0))
    # Keyed by (arrival, tenant): tenants 0 and 1 both arrive at 100.0 s.
    by_request = dict(zip(zip(result.arrivals, result.models, strict=True), result.latencies,
                          strict=True))
    return [by_request[(t, m)] for t, m in SCHEDULE], result.swaps


def _record(i, latencies, swaps, *, jitter=0.0, host="h"):
    arrived = [t + jitter for t, _ in SCHEDULE]
    output = {"schedule": [[t, m] for t, m in SCHEDULE], "until": UNTIL, "arrived": arrived,
              "done": [a + lat for a, lat in zip(arrived, latencies, strict=True)],
              "swaps": [{}] * swaps, "host": {"host_id": f"{host}{i}"}}
    return A4Run(run_id=f"r{i}", run_index=i, condition="replay", block_index=i, kind="replay",
                 outcome="ok", failure=None, clock_A={}, output=output, source="stub")


def _records(offsets=(-0.01, 0.0, 0.01), bias=0.0, swaps=None):
    latencies, sim_swaps = _simulated()
    return [_record(i, [lat + off + bias for lat in latencies],
                    sim_swaps if swaps is None else swaps)
            for i, off in enumerate(offsets)]


def test_the_prediction_is_the_simulators_replay_of_the_trace():
    bins, swaps, last_done = predict([t for t, _ in SCHEDULE], [m for _, m in SCHEDULE], UNTIL,
                                     ENGINES, SWAP_S)
    # Tenant 0 keeps arriving while tenants 1 and 2 are served, so the GPU
    # swaps back and forth: the thrash the simulator models.
    assert swaps == _simulated()[1] > 4
    assert len(bins) == 14  # 400 s in 30 s bins
    assert last_done == max(t + lat for (t, _), lat in zip(SCHEDULE, _simulated()[0], strict=True))


def test_reality_that_matches_the_simulator_passes():
    result = validate(_records(), ENGINES, SWAP_S)
    assert result["outcome"] == "passed", result["latency"]["detail"]
    n = _simulated()[1]
    assert result["swaps"] == {"predicted": n, "real": [n, n, n], "agree": True}
    assert result["latency"]["compared"] >= 10 and result["hosts"] == ["h0", "h1", "h2"]


def test_reality_two_seconds_slower_fails_on_latency():
    result = validate(_records(bias=2.0), ENGINES, SWAP_S)
    assert result["outcome"] == "failed" and result["latency"]["outcome"] == "failed"


def test_a_swap_count_outside_the_slack_fails_even_when_latency_agrees():
    n = _simulated()[1]
    result = validate(_records(swaps=n + 2), ENGINES, SWAP_S)
    assert result["latency"]["outcome"] == "passed" and result["outcome"] == "failed"
    assert validate(_records(swaps=n + 1), ENGINES, SWAP_S)["outcome"] == "passed"


def test_the_gate_needs_exactly_three_repeats_of_one_trace():
    runs = [replay_run(r) for r in _records()]
    with pytest.raises(ValueError, match="exactly 3"):
        check_repeats(runs[:2])
    other = _records()[0]
    other.output["schedule"][5][0] += 0.001
    with pytest.raises(ValueError, match="ONE trace"):
        check_repeats([replay_run(other), *runs[1:]])


def test_a_replay_that_lagged_the_schedule_is_refused():
    latencies, swaps = _simulated()
    late = _record(0, latencies, swaps, jitter=0.6)
    with pytest.raises(ValueError, match="lag the schedule"):
        check_repeats([replay_run(late), *(replay_run(r) for r in _records()[1:])])


def test_only_an_ok_replay_record_qualifies():
    failed = _records()[0]
    failed.outcome = "failed"
    with pytest.raises(ValueError, match="not an ok replay"):
        replay_run(failed)


def test_a_request_finishing_after_the_window_is_cut():
    run = replay_run(_records()[0])
    for t, lat, cut in zip(run.schedule, run.latencies, run.windowed_latencies(), strict=True):
        assert (cut is None) == (t + lat > UNTIL)
    # Strictly after the window: a request finishing exactly at `until` counts,
    # as in the simulator's `event.time > until`.
    late = replay_run(_record(0, [UNTIL + 1.0] * len(SCHEDULE), 4))
    assert set(late.windowed_latencies()) == {None}


def test_the_cut_is_on_the_schedules_clock_so_jitter_cannot_censor_one_side():
    latencies, swaps = _simulated()
    # The last request finishes 0.2 s before the window ends, on schedule.
    t_last = SCHEDULE[-1][0]
    latencies = [*latencies[:-1], UNTIL - t_last - 0.2]
    # Handled 0.4 s late, it actually finishes 0.2 s after the window. On the
    # schedule's clock, the one the prediction uses, it is still inside.
    late = replay_run(_record(0, latencies, swaps, jitter=0.4))
    assert late.windowed_latencies()[-1] is not None


def test_the_real_driver_and_the_simulator_make_the_same_swaps():
    """The driver restates the simulator's swap rule; this holds them to each
    other on one GPU, with every duration scaled down a thousand-fold."""
    scale = 1000.0
    # Groups at least 40 s apart (40 ms here), so no two events race.
    groups = [(0.0, 0), (60.0, 1), (120.0, 0), (200.0, 2), (260.0, 1)]
    schedule = [(round(start + 1.0 * i, 3) / scale, m) for start, m in groups for i in range(10)]
    spec = ReplaySpec(tenants=TENANTS, schedule=tuple(schedule), until=0.4, input_len=4,
                      output_len=4, max_in_flight=8, cold=False, seed=1, hf_home="/h",
                      release_tolerance_mib=512, release_timeout_s=60)
    out = replay(spec, deadline=time.monotonic() + 30,
                 deps=_deps(TimedEngines(startup_s=SWAP_S / scale),
                            Completions(service_s=0.5 / scale)))
    placement = Placement("swap", (Gpu("pool", (0,)),), pool_models=(0, 1, 2))
    sim = simulate([(t * scale, m) for t, m in schedule], placement, ENGINES,
                   EmpiricalDistribution(samples=(SWAP_S,), measured=True), 0.0, random.Random(0))
    assert len(out["swaps"]) == sim.swaps == 4
    assert [(s["from"], s["to"]) for s in out["swaps"]] == [(0, 1), (1, 0), (0, 2), (2, 1)]


def test_a_stub_replay_round_trips_into_a_qualifying_record():
    from placement_measure.jobs import measure_job
    from placement_measure.records import build_record

    payload = {"kind": "replay", "run_id": "r", "job_budget_s": 1800,
               "tenants": [t.to_dict() for t in TENANTS], "schedule": [[0.0, 0], [0.02, 1]],
               "until": 1.0, "input_len": 4, "output_len": 4, "max_in_flight": 4, "cold": False,
               "seed": 1, "hf_home": "/h", "release_tolerance_mib": 512, "release_timeout_s": 60}
    outcome = PayloadStubSubmitter(lambda p: measure_job(
        p, replay_deps=_deps(), host=lambda: {"host_id": "h9", "runpod_pod_id": None})
    ).submit_payload(payload)
    record = build_record(ScheduledRun(0, 0, "replay"), "r", outcome, kind="replay", source="stub")
    run = validation.replay_run(record)
    assert run.schedule == (0.0, 0.02) and run.tenants == (0, 1) and run.host_id == "h9"
    assert run.swaps == 1 and all(lat is not None for lat in run.latencies)


def _measurement():
    from a4_examples import example_report

    from placement.step2 import measurement_design

    return measurement_design(example_report())


def test_the_trace_is_the_first_registered_draw_whose_replay_is_feasible():
    from placement import step2
    from placement.validation import validation_trace

    # A 4B-like curve: about 4 s per request alone, 22 s at 128 in flight.
    curve = ServiceCurve(points=[(1, 4.0, 0.25, 0.3), (8, 4.5, 1.8, 0.6), (16, 5.0, 3.2, 0.8),
                                 (32, 6.5, 4.9, 0.9), (64, 11.0, 5.8, 1.0), (128, 22.0, 5.8, 1.0)],
                         measured=True)
    design, checks = validation_trace(_measurement(), Engines(curve, SURFACE), swap_s=39.0)
    assert checks[-1]["feasible"] and all(not c["feasible"] for c in checks[:-1])
    assert checks[0]["seed"] == step2.VALIDATION_SEEDS[0]
    assert design == step2.validation_design(_measurement(), curve, checks[-1]["seed"])
    last = checks[-1]
    assert last["predicted_last_done_s"] <= step2.VALIDATION_DRAIN_LIMIT_S
    assert last["predicted_swaps"] >= step2.VALIDATION_MIN_SWAPS and last["ok_bins"] >= 10


def test_a_trace_no_registered_load_can_replay_in_a_job_stops():
    from placement.step2 import NotDecidable
    from placement.validation import validation_trace

    with pytest.raises(NotDecidable, match="no pre-registered validation draw is feasible"):
        validation_trace(_measurement(), ENGINES, swap_s=400.0)
