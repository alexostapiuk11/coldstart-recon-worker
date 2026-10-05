"""The sleep-mode arm as a measurement job, and cell designs that name cells
outside the grid's product: the held-out cells and any top-up."""

import pytest
from a4_fakes import Clock, FakeEngines
from test_placement_measure_recon import Resp, _deps

from harness.scheduler import ScheduledRun
from harness.submit import PayloadStubSubmitter
from placement_measure.campaigns import CellDesign, SleepDesign, parse_sleep, sleep_condition
from placement_measure.jobs import measure_job, sleep_switch
from placement_measure.prereg import SLEEP_GMU
from placement_measure.records import build_record

A, B = "Qwen/Qwen3-4B", "Qwen/Qwen3-4B-Base"


def _host():
    return {"host_id": "h1", "runpod_pod_id": None}


def _timed_deps(clock, statuses=None):
    """Recon fakes whose endpoints take time: sleep 2 s, wake 3 s, a
    completion 0.5 s. `statuses` overrides the HTTP status per URL suffix."""
    deps = _deps(clock, FakeEngines(clock))
    cost = {"sleep?level=1": 2.0, "wake_up": 3.0, "completions": 0.5}
    statuses = statuses or {}

    def post(url, **kw):
        suffix = next(k for k in cost if url.endswith(k))
        clock.t += cost[suffix]
        return Resp(status=statuses.get(suffix, 200))

    deps.post = post
    return deps


def _payload():
    design = SleepDesign(a=A, b=B, repeats=2, seed=5)
    return design.payload(design.schedule()[0], "r1")


def test_the_condition_round_trips_and_a_malformed_one_is_refused():
    assert parse_sleep(sleep_condition(A, B)) == (A, B)
    for bad in ("sleep:ab", f"swap:{A}>{B}", "sleep:>b"):
        with pytest.raises(ValueError):
            parse_sleep(bad)


def test_a_sleep_design_starts_both_engines_in_sleep_mode():
    design = SleepDesign(a=A, b=B, repeats=3, seed=5)
    assert len(design.schedule()) == 3
    p = _payload()
    assert p["kind"] == "sleep" and p["run_id"] == "r1"
    for side in ("a", "b"):
        assert p[side]["gpu_memory_utilization"] == SLEEP_GMU
        assert "--enable-sleep-mode" in p[side]["extra_args"]


def test_the_switch_is_bs_sleep_plus_as_wake_through_the_json_round_trip():
    clock = Clock()
    sub = PayloadStubSubmitter(lambda p: measure_job(p, recon_deps=_timed_deps(clock),
                                                     host=_host, clock=clock))
    outcome = sub.submit_payload(_payload())
    assert outcome.error is None
    out = outcome.payload
    assert out["switch_s"] == pytest.approx(2.0 + 3.0)
    assert out["first_request_after_wake_s"] == pytest.approx(0.5)
    assert out["run_id"] == "r1" and out["kind"] == "sleep"
    record = build_record(ScheduledRun(0, 0, sleep_condition(A, B)), "r1", outcome,
                          kind="sleep", source="stub")
    assert record.outcome == "ok"


def test_a_wake_that_fails_is_no_switch_and_a_failed_record():
    clock = Clock()
    out = measure_job(_payload(), recon_deps=_timed_deps(clock, {"wake_up": 404}),
                      host=_host, clock=clock)
    assert out["switch_s"] is None and "did not answer 200" in out["failure"]
    record = build_record(ScheduledRun(0, 0, sleep_condition(A, B)), "r1",
                          PayloadStubSubmitter(lambda p: out).submit_payload({}),
                          kind="sleep", source="stub")
    assert record.outcome == "failed" and "did not answer 200" in record.failure


def test_an_engine_that_never_came_up_is_reported_as_unhealthy():
    steps = {"a": {"healthy": True}, "b": {"healthy": False}}
    out = sleep_switch(steps)
    assert out["healthy"] is False and out["switch_s"] is None
    assert "never answered /health" in out["failure"]


def _cells(**over):
    fields = {"measured_model": A, "neighbour_model": B, "own_levels": (2, 8),
              "neighbour_levels": (0, 8), "solo": False, "input_len": 768, "output_len": 256,
              "repeats": 2, "seed": 3}
    return CellDesign(**{**fields, **over})


def test_extra_cells_join_the_grid_once():
    design = _cells(extra_cells=("pair:o3:n12", "pair:o2:n8"))
    assert design.conditions() == ["pair:o2:n0", "pair:o2:n8", "pair:o8:n0", "pair:o8:n8",
                                   "pair:o3:n12"]


def test_a_design_of_extra_cells_alone_is_a_top_up():
    top_up = _cells(own_levels=(), neighbour_levels=(), extra_cells=("pair:o8:n8", "solo:o2"))
    assert top_up.conditions() == ["pair:o8:n8", "solo:o2"]
    assert top_up.payload(ScheduledRun(0, 0, "solo:o2"), "r")["b"] is None


def test_a_malformed_extra_cell_or_an_empty_design_is_refused():
    with pytest.raises(ValueError):
        _cells(extra_cells=("o3:n12",))
    with pytest.raises(ValueError, match="nothing"):
        _cells(own_levels=(), neighbour_levels=()).conditions()
