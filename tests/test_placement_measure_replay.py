"""The trace-replay driver, on fake engines that take real (short) time.

The driver runs threads, so these tests use the real clock with durations of
hundredths of a second, and assert orders and counts rather than exact times.
"""

import contextlib
import threading
import time

import pytest
from a4_fakes import FakeServer

from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement_measure import jobs
from placement_measure import replay as replay_module
from placement_measure.campaigns import REPLAY_CONDITION, ReplayDesign
from placement_measure.engine import EngineSpec
from placement_measure.jobs import measure_job
from placement_measure.records import build_record
from placement_measure.replay import ReplayDeps, ReplaySpec, complete, prompt_ids, replay

TENANTS = tuple(EngineSpec(m, f"r{i}", 0.92, 2048, 256)
                for i, m in enumerate(("Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base",
                                       "Qwen/Qwen3-4B-Instruct-2507")))


class TimedEngines:
    """`served` that sleeps `startup_s` before answering, like an engine
    loading, and counts how many engines are up at once."""

    def __init__(self, startup_s=0.05, healthy=None):
        self.startup_s, self.healthy = startup_s, healthy or {}
        self.started: list[FakeServer] = []
        self.up = 0
        self.most_up = 0
        self.lock = threading.Lock()

    @contextlib.contextmanager
    def served(self, model, *, args, env, port=8000, health_timeout=900.0):
        assert env.get("HF_HUB_OFFLINE") == "1"
        time.sleep(self.startup_s)
        server = FakeServer(model, args, port, self.healthy.get(model, True), [])
        with self.lock:
            self.started.append(server)
            self.up += 1
            self.most_up = max(self.most_up, self.up)
        try:
            yield server
        finally:
            with self.lock:
                self.up -= 1


class Completions:
    """`complete` that takes `service_s` and records which model answered."""

    def __init__(self, service_s=0.03, fail_model=None):
        self.service_s, self.fail_model = service_s, fail_model
        self.calls: list[tuple[str, int, int]] = []

    def __call__(self, base_url, model, ids, max_tokens):
        self.calls.append((model, len(ids), max_tokens))
        time.sleep(self.service_s)
        failed = model == self.fail_model
        return {"ok": not failed, "status": 500 if failed else 200,
                "completion_tokens": None if failed else max_tokens,
                "error": "boom" if failed else None}


def _deps(engines=None, completions=None):
    return ReplayDeps(
        served=(engines or TimedEngines()).served, complete=completions or Completions(),
        read_memory=lambda: {"used_mib": 500},
        wait_for_release=lambda target, timeout_s: {"released": True, "seconds": 0.0},
        make_cold=lambda paths: {"requested": True}, weight_files=lambda *a: [],
    )


def _spec(schedule, *, max_in_flight=8, until=None, cold=False):
    return ReplaySpec(tenants=TENANTS, schedule=tuple(schedule),
                      until=until if until is not None else schedule[-1][0] + 1.0,
                      input_len=12, output_len=4, max_in_flight=max_in_flight, cold=cold,
                      seed=7, hf_home="/vol/hf", release_tolerance_mib=512,
                      release_timeout_s=60)


def _soon(seconds=30.0):
    return time.monotonic() + seconds


def test_swaps_follow_the_simulators_rule_and_latency_counts_the_wait():
    engines, completions = TimedEngines(startup_s=0.05), Completions(service_s=0.03)
    # Tenant 1 at 0.10 forces a swap; tenant 0 at 0.11 waits through it and
    # forces the swap back once tenant 1's request has drained; tenant 2 at
    # 0.40 forces a third.
    schedule = [(0.0, 0), (0.02, 0), (0.10, 1), (0.11, 0), (0.40, 2)]
    out = replay(_spec(schedule, cold=True), deadline=_soon(),
                 deps=_deps(engines, completions))
    assert out["healthy"] and out["failure"] is None and not out["deadline_hit"]
    assert [(s["from"], s["to"]) for s in out["swaps"]] == [(0, 1), (1, 0), (0, 2)]
    assert all(s["cache"] == {"requested": True} for s in out["swaps"])
    assert all(x is not None for x in out["done"]) and all(out["ok"])
    # Request 2 waited for a whole engine start before it was even sent.
    assert out["sent"][2] - out["arrived"][2] >= engines.startup_s
    # Request 3 (tenant 0) was sent only after the swap back had completed.
    assert out["sent"][3] >= out["swaps"][1]["ready"]
    assert [m for m, _, _ in completions.calls] == [
        TENANTS[0].model, TENANTS[0].model, TENANTS[1].model, TENANTS[0].model, TENANTS[2].model]
    # One GPU: an engine is never started before the previous one stopped.
    assert engines.most_up == 1


def test_arrivals_land_on_the_schedule():
    schedule = [(0.1 * i, 0) for i in range(6)]
    out = replay(_spec(schedule), deadline=_soon(), deps=_deps())
    jitter = max(a - t for a, (t, _) in zip(out["arrived"], schedule, strict=True))
    assert 0.0 <= jitter < 0.08


def test_the_cap_queues_requests_in_the_driver():
    completions = Completions(service_s=0.03)
    out = replay(_spec([(0.0, 0), (0.0, 0), (0.0, 0)], max_in_flight=1), deadline=_soon(),
                 deps=_deps(completions=completions))
    sent = out["sent"]
    assert sent == sorted(sent) and sent[2] - sent[0] >= 2 * completions.service_s * 0.9


def test_the_deadline_stops_the_replay_and_leaves_the_rest_unfinished():
    schedule = [(0.0, 0), (0.05, 0), (5.0, 0)]
    out = replay(_spec(schedule), deadline=time.monotonic() + 0.3, deps=_deps())
    assert out["deadline_hit"] and out["sent"][2] is None and out["unsent"] == 1
    assert out["done"][0] is not None


def test_a_deadline_mid_swap_waits_for_the_swap_and_stops_its_engine():
    engines = TimedEngines(startup_s=0.3)
    out = replay(_spec([(0.0, 1)]), deadline=time.monotonic() + 0.45, deps=_deps(engines))
    assert out["deadline_hit"] and not out["engine_left_running"]
    assert len(out["swaps"]) == 1 and engines.up == 0


def test_an_incoming_engine_that_never_comes_up_ends_the_replay_as_a_failure():
    engines = TimedEngines(healthy={TENANTS[1].model: False})
    out = replay(_spec([(0.0, 0), (0.05, 1), (0.1, 0)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and "never answered /health" in out["failure"]
    assert out["done"][1] is None and engines.up == 0


def test_a_first_engine_that_never_comes_up_replays_nothing():
    engines = TimedEngines(healthy={TENANTS[0].model: False})
    out = replay(_spec([(0.0, 0)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and out["unsent"] == 1 and engines.up == 0


def test_an_errored_request_is_recorded_not_dropped():
    out = replay(_spec([(0.0, 0), (0.0, 1)]), deadline=_soon(),
                 deps=_deps(completions=Completions(fail_model=TENANTS[1].model)))
    assert out["ok"] == [True, False] and out["errors"][1] == "boom"
    assert out["done"][1] is not None


def test_prompts_are_fixed_by_the_seed_and_distinct_per_request():
    assert prompt_ids(7, 3, 16) == prompt_ids(7, 3, 16)
    assert prompt_ids(7, 3, 16) != prompt_ids(7, 4, 16)
    assert len(prompt_ids(7, 0, 1024)) == 1024


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_a_completion_must_return_exactly_the_tokens_asked_for():
    seen = {}

    def post(url, json, timeout):
        seen.update(json)
        return Resp(200, {"usage": {"completion_tokens": json["max_tokens"]}})

    assert complete("http://e", "m", [1, 2], 4, post=post)["ok"]
    assert seen["ignore_eos"] is True and seen["prompt"] == [1, 2]
    short = complete("http://e", "m", [1], 4,
                     post=lambda url, json, timeout: Resp(200, {"usage": {"completion_tokens": 2}}))
    assert not short["ok"]
    assert not complete("http://e", "m", [1], 4, post=lambda *a, **k: Resp(503, {}))["ok"]

    def broken(*a, **k):
        raise ConnectionError("refused")

    assert "refused" in complete("http://e", "m", [1], 4, post=broken)["error"]


@pytest.mark.parametrize("schedule, reason", [
    ([(0.2, 0), (0.1, 0)], "ascending"),
    ([(0.0, 3)], "tenant 3"),
    ([(5.0, 0)], "past until"),
    ([], "empty"),
])
def test_a_malformed_spec_is_refused(schedule, reason):
    with pytest.raises(ValueError, match=reason):
        ReplaySpec(tenants=TENANTS, schedule=tuple(schedule), until=1.0, input_len=1,
                   output_len=1, max_in_flight=1, cold=False, seed=0, hf_home="/h",
                   release_tolerance_mib=1, release_timeout_s=1)


def _design(**over):
    fields = {"tenants": tuple(t.model for t in TENANTS), "trace": ((0.0, 0), (0.05, 1)),
              "until": 1.0, "input_len": 12, "output_len": 4, "max_in_flight": 8, "cold": False,
              "repeats": 3, "seed": 7}
    return ReplayDesign(**{**fields, **over})


def test_every_repeat_of_a_replay_design_sends_the_same_trace():
    design = _design()
    runs = design.schedule()
    assert [r.condition for r in runs] == [REPLAY_CONDITION] * 3
    a, b = (design.payload(r, f"id{i}") for i, r in enumerate(runs[:2]))
    assert {**a, "run_id": None} == {**b, "run_id": None}
    with pytest.raises(ValueError):
        design.payload(ScheduledRun(0, 0, "swap:a>b:cold"), "x")


def test_a_replay_job_round_trips_and_its_record_reads_ok():
    design = _design()
    payload = design.payload(design.schedule()[0], "r1")
    sub = PayloadStubSubmitter(lambda p: measure_job(
        p, replay_deps=_deps(), host=lambda: {"host_id": "h", "runpod_pod_id": None}))
    outcome = sub.submit_payload(payload)
    assert outcome.error is None and outcome.payload["run_id"] == "r1"
    record = build_record(ScheduledRun(0, 0, REPLAY_CONDITION), "r1", outcome, kind="replay",
                          source="stub")
    assert record.outcome == "ok"


def test_a_replay_with_an_errored_request_or_cut_short_is_a_failed_record():
    run = ScheduledRun(0, 0, REPLAY_CONDITION)
    errored = {"healthy": True, "failure": None, "deadline_hit": False, "ok": [True, False]}
    cut = {"healthy": True, "failure": None, "deadline_hit": True, "ok": [True]}
    for output, reason in ((errored, "did not complete cleanly"), (cut, "job budget")):
        outcome = PayloadStubSubmitter(lambda p, o=output: o).submit_payload({})
        record = build_record(run, "r", outcome, kind="replay", source="stub")
        assert record.outcome == "failed" and reason in record.failure


class StopFails(TimedEngines):
    """An engine whose stop raises, as a wedged process might."""

    @contextlib.contextmanager
    def served(self, model, **kw):
        with super().served(model, **kw) as server:
            def stop():
                raise RuntimeError("stop wedged")

            server.stop = stop
            yield server


def test_a_teardown_that_raises_still_releases_the_engine():
    engines = StopFails()
    out = replay(_spec([(0.0, 0), (0.05, 1)]), deadline=_soon(), deps=_deps(engines))
    assert not out["healthy"] and "stop wedged" in out["failure"]
    assert engines.up == 0


def test_an_engine_whose_record_cannot_be_built_is_stopped(monkeypatch):
    engines = TimedEngines()

    def unreadable(*args):
        raise ValueError("unreadable log")

    monkeypatch.setattr(replay_module, "_engine_part", unreadable)
    with pytest.raises(ValueError, match="unreadable log"):
        replay(_spec([(0.0, 0)]), deadline=_soon(), deps=_deps(engines))
    assert engines.up == 0


def test_the_replay_job_reserves_time_for_a_mid_swap_wait():
    # The deadline leaves room for the wait and the teardown after it.
    assert jobs.TEARDOWN_RESERVE_S + replay_module.SWAP_WAIT_S < 1800 / 2


def test_a_cold_swap_times_its_eviction_apart_from_the_swap():
    from a4_fakes import Clock, FakeEngines, memory_script

    from placement_measure.gpu_memory import read_memory, wait_for_release
    from placement_measure.swap import SwapDeps, measure_swap

    clock = Clock()
    run = memory_script([500, 9000, 500])

    def make_cold(paths):
        clock.t += 2.5
        return {"requested": True}

    deps = SwapDeps(served=FakeEngines(clock).served, read_memory=lambda: read_memory(run=run),
                    wait_for_release=lambda t, timeout_s: wait_for_release(
                        t, timeout_s=timeout_s, run=run, clock=clock, sleep=clock.sleep),
                    make_cold=make_cold, weight_files=lambda *a: [], clock=clock)
    out = measure_swap(TENANTS[0], TENANTS[1], cold=True, hf_home="/h", release_tolerance_mib=512,
                       release_timeout_s=60, deps=deps)
    assert out["cache_s"] == pytest.approx(2.5)
    assert out["swap_s"] == pytest.approx(out["teardown_s"] + out["release"]["seconds"]
                                          + out["b"]["startup_s"])
