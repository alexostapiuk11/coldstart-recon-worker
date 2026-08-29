from itertools import pairwise

from coldstart.analysis.metrics import derive
from coldstart.schema import RunRecord
from coldstart.stubs import stub_engine
from coldstart.stubs.stub_endpoint import StubEndpoint
from coldstart.vllm_logs import parse_engine_log


def test_stub_returns_a_bundle_shaped_like_the_real_one():
    ep = StubEndpoint(seed=1)
    result = ep.run(arm="A", run_id="run-1")
    assert result["healthy"] is True
    assert len(result["warmup"]) == 10
    assert result["log_lines"], "stub must replay the real captured log"
    assert "clock_B" in result


def test_stub_warmup_carries_t_dispatch_mono_with_real_gaps_between_requests():
    """B5: a dispatch offset exactly equal to the previous request's
    t_dispatch_mono + end_to_end would BE the summing inference, not a
    measurement of it."""
    warmup = StubEndpoint(seed=1).run(arm="A", run_id="run-1")["warmup"]
    for w in warmup:
        assert "t_dispatch_mono" in w
    for prev, nxt in pairwise(warmup):
        assert nxt["t_dispatch_mono"] > prev["t_dispatch_mono"] + prev["end_to_end"]


def test_arms_produce_different_weight_times():
    ep = StubEndpoint(seed=1)
    a = ep.run(arm="A", run_id="r1")["synthetic_truth"]["t_weights"]
    b = ep.run(arm="B", run_id="r2")["synthetic_truth"]["t_weights"]
    assert a > b, "cold arm must be slower in the stub's ground truth"


def test_same_seed_reproduces():
    assert (
        StubEndpoint(seed=5).run(arm="A", run_id="r")["synthetic_truth"]
        == StubEndpoint(seed=5).run(arm="A", run_id="r")["synthetic_truth"]
    )


# --- the S4 bracket the real probe produces must exist here too -------------


def test_stub_emits_the_s4_bracket_marks():
    """Task 11's probe emits S4_start/S4_end and derive() reads them. A stub
    without them would leave t_s4_bracket None on every GPU-free row, so the
    bracket would never be exercised off-GPU."""
    marks = {m["stage"] for m in StubEndpoint(seed=1).run(arm="A", run_id="r")["clock_B"]["marks"]}
    for stage in (
        "S1_imports_done",
        "S2_acquisition_start",
        "S3_load_done",
        "S4_start",
        "S4_end",
        "S5_ready",
        "S6_request1_dispatch",
        "S6_first_token",
        "S7_warmup_done",
    ):
        assert stage in marks, f"missing {stage}"


def test_s4_end_precedes_s5_ready():
    """S5 is a separate later stage. If the stub collapsed them, the analysis
    could fold S5 into S4 off-GPU and no test would notice."""
    marks = {
        m["stage"]: m["t_mono"]
        for m in StubEndpoint(seed=1).run(arm="A", run_id="r")["clock_B"]["marks"]
    }
    assert marks["S3_load_done"] == marks["S4_start"]
    assert marks["S4_start"] < marks["S4_end"] < marks["S5_ready"]
    assert marks["S5_ready"] <= marks["S6_request1_dispatch"]


# --- the replayed log matches the arm it is standing in for -----------------


def test_cold_compile_arms_replay_the_cold_capture():
    for arm in ("A", "B"):
        result = StubEndpoint(seed=1).run(arm=arm, run_id="r")
        parsed = parse_engine_log("\n".join(result["log_lines"]))
        assert parsed.phases["S4b"] > 30.0, f"arm {arm} should replay a cold compile"


def test_warm_compile_arm_replays_the_warm_capture():
    """Arm C is the warm compile cache. The captures include a genuinely warm
    startup, so the stub replays that rather than a cold log relabelled."""
    result = StubEndpoint(seed=1).run(arm="C", run_id="r")
    parsed = parse_engine_log("\n".join(result["log_lines"]))
    assert parsed.phases["S4b"] < 1.0


def test_replay_is_independent_of_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert stub_engine.replay_log_lines(compile_warm=False)


# --- record shape parity with the real handler ------------------------------


def test_stub_result_carries_the_same_provenance_as_the_real_handler():
    result = StubEndpoint(seed=1).run(arm="C", run_id="run-42")
    assert result["run_id"] == "run-42"
    assert result["arm"] == "C"
    assert result["cache_config"]["compile_cache_warm"] is True
    assert result["compile_cache_observed"] is True


# --- the whole point: the analysis runs off-GPU -----------------------------


def _record_from_stub(result, arm, submit=0.0, job_span=400.0):
    parsed = parse_engine_log("\n".join(result["log_lines"]))
    return RunRecord(
        run_id=result["run_id"],
        run_index=0,
        arm=arm,
        clock_A={"t_submit": submit, "t_result": submit + job_span},
        clock_C={},
        clock_B=result["clock_B"],
        warmup=result["warmup"],
        engine={"s4_subphases": parsed.phases, **parsed.engine_info},
        host=result["host"],
        config=result["cache_config"],
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_derive_produces_a_complete_row_from_stub_output():
    """The GPU-free loop is only trustworthy if the analysis actually runs on
    it -- including the two quantities the probe task shipped: the S4 bracket
    and T_fast."""
    result = StubEndpoint(seed=1).run(arm="A", run_id="run-1")
    row = derive(_record_from_stub(result, "A"))
    assert row["ok"] is True
    assert row["consistent"] is True, row.get("discard_reason")
    assert row["t_s4_bracket"] is not None and row["t_s4_bracket"] > 0
    assert row["t_fast_seconds"] is not None, row.get("t_fast_reason")
    assert row["t_compile"] is not None
    assert row["kv_capacity_tokens"] > 0


def test_derive_recovers_the_compile_saving_between_arms():
    """Arm C's whole reason to exist, measured end to end with no GPU."""
    cold = derive(_record_from_stub(StubEndpoint(seed=1).run(arm="B", run_id="r1"), "B"))
    warm = derive(_record_from_stub(StubEndpoint(seed=1).run(arm="C", run_id="r2"), "C"))
    assert cold["t_compile"] > warm["t_compile"]
