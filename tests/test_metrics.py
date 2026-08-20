import pytest

from coldstart.analysis.metrics import (
    ceiling_bound,
    derive,
    steady_state_latency,
    time_to_fast_index,
    warmup_penalty,
)
from coldstart.checks import DiscardReason
from coldstart.schema import RunRecord

# Distinct per-request values with a non-flat tail, so the last-three window,
# the median (vs. max), and warmup[0] (vs. warmup[1]) are each pinned by a
# formula that no other formula over the same list would also satisfy.
# Last three (idx 7, 8, 9) = [4.0, 3.2, 2.0] -> median (steady) = 3.2.
_WARMUP_LATENCIES = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 3.4, 4.0, 3.2, 2.0]


def make(arm="A", t_submit=0.0, t_result=150.0, marks=None, warmup=None):
    marks = marks or [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 130.0},
    ]
    warmup = warmup or [
        {"req_index": i, "ttft": 0.5, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)
    ]
    return RunRecord(
        run_id="r",
        run_index=0,
        arm=arm,
        clock_A={"t_submit": t_submit, "t_result": t_result},
        clock_C={},
        clock_B={"t0_wall": 0.0, "marks": marks},
        warmup=warmup,
        engine={"kv_cache_blocks": 8192, "block_size": 16},
        host={"host_id": "h1"},
        config={},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_t_process_is_t0_to_first_token():
    d = derive(make())
    assert d["t_process"] == 102.0


def test_t_total_is_submit_to_result():
    assert derive(make())["t_total"] == 150.0


def test_residual_is_the_difference():
    assert derive(make())["t_platform"] == pytest.approx(48.0)


def test_kv_capacity_is_blocks_times_block_size():
    assert derive(make())["kv_capacity_tokens"] == 8192 * 16


def test_steady_state_and_warmup_penalty():
    d = derive(make())
    assert d["steady_state_latency"] == pytest.approx(3.2)
    assert d["warmup_penalty"] == pytest.approx(10.0 / 3.2)


def test_time_to_fast_index_uses_the_registered_tolerance():
    # steady=3.2, threshold=3.2*1.1=3.52. idx6=3.4 is the first value <= 3.52.
    # A tolerance of 0.0 would instead land on idx8 (3.2); 10.0 would land on
    # idx0 (10.0) — see test_time_to_fast_index_* below for those directly.
    d = derive(make())
    assert d["time_to_fast_index"] == 6


def test_inconsistent_run_is_flagged_not_silently_kept():
    d = derive(make(t_result=50.0))
    assert d["consistent"] is False
    assert d["t_platform"] is None
    assert d["inconsistency_reason"] is not None
    assert d["discard_reason"] == DiscardReason.PROCESS_EXCEEDS_TOTAL


def test_residual_below_rtt_floor_is_flagged_inconsistent():
    # t_process=102.0 (default marks), t_result=102.03 -> residual=0.03,
    # below the 0.05 rtt floor.
    d = derive(make(t_result=102.03))
    assert d["consistent"] is False
    assert d["t_platform"] is None
    assert d["discard_reason"] == DiscardReason.RESIDUAL_BELOW_RTT_FLOOR


def test_failed_run_is_not_processed_and_keeps_its_classification():
    rec = make()
    rec.host = {"host_id": "h9", "triple_index": 2}
    rec.status = {
        "outcome": "failed",
        "failure_class": "oom",
        "failure_detail": "CUDA out of memory",
    }
    d = derive(rec)
    assert d == {
        "ok": False,
        "arm": "A",
        "host_id": "h9",
        "triple_index": 2,
        "consistent": False,
        "failure_class": "oom",
    }


def test_failed_run_guard_is_not_a_noop():
    # Guards against `if False:` replacing the outcome check: with a broken
    # guard, this failed run would fall through to the ok-run path (which the
    # default fixture's marks/clocks would happily compute), producing a
    # 20-key "ok": True row instead of the 6-key failure row asserted above.
    rec = make()
    rec.status = {"outcome": "failed", "failure_class": None, "failure_detail": None}
    d = derive(rec)
    assert d["ok"] is False
    assert "t_total" not in d


def test_t_weights_is_s2_plus_s3_and_stops_at_the_load_boundary():
    """T_weights is S2+S3 (spec, stage taxonomy) — it must NOT run to S5_ready.

    S5_ready is on the far side of all of S4: device init, compilation, memory
    profiling, KV allocation, graph capture. Measuring to S5 would fold the
    compile term into the weights term, and arms B and C differ *only* in the
    compile term — so the harness would credit weight caching with the entire
    compile-cache saving. That is the one confusion this experiment exists to
    prevent, so it gets a test.
    """
    d = derive(make())
    assert d["t_weights"] == pytest.approx(50.0)  # 54.0 - 4.0, not 100.0 - 4.0


def test_t_weights_is_none_when_the_load_boundary_was_not_delineated():
    """Merged phases are reported merged, never guessed apart — spec, stage taxonomy."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S3_load_done"]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["t_s2_to_ready"] == pytest.approx(96.0)
    assert d["merged_phases"] == ["S3"]


def test_t_weights_is_none_when_the_acquisition_start_was_not_delineated():
    """A missing S2 mark is a different defect from a missing S3 mark and must
    be named correctly — not folded into the same 'S3' label."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S2_acquisition_start"]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["t_s2_to_ready"] is None
    assert d["merged_phases"] == ["S2"]


def test_t_weights_negative_is_flagged_inconsistent_not_corrected():
    """S3_load_done preceding S2_acquisition_start is impossible, not a sign
    error. `abs()`-ing it would silently publish a wrong number."""
    marks = [
        {"stage": "S2_acquisition_start", "t_mono": 60.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
    ]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["consistent"] is False
    assert d["merged_phases"] == []  # both marks were present; the value was just invalid


def test_t_weights_exceeding_t_process_is_flagged_inconsistent():
    """A weights phase longer than the process containing it is impossible."""
    marks = [
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 500.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
    ]
    d = derive(make(marks=marks))
    assert d["t_weights"] is None
    assert d["consistent"] is False


def test_returned_row_carries_identity_and_reason():
    rec = make()
    rec.host = {"host_id": "h7", "triple_index": 3}
    d = derive(rec)
    assert d["arm"] == "A"
    assert d["host_id"] == "h7"
    assert d["triple_index"] == 3
    assert d["inconsistency_reason"] is None


def test_kv_capacity_is_zero_not_none_when_blocks_report_zero():
    """kv_cache_blocks == 0 is a real, alarming engine state — distinct from
    the engine not reporting the field at all."""
    rec = make()
    rec.engine = {"kv_cache_blocks": 0, "block_size": 16}
    d = derive(rec)
    assert d["kv_cache_blocks"] == 0
    assert d["kv_capacity_tokens"] == 0


def test_kv_capacity_is_none_when_engine_omits_the_fields():
    rec = make()
    rec.engine = {}
    d = derive(rec)
    assert d["kv_cache_blocks"] is None
    assert d["kv_capacity_tokens"] is None


def test_missing_process_mark_raises_with_run_identity():
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S6_first_token"]
    rec = make(marks=marks)
    rec.run_id = "run-42"
    with pytest.raises(KeyError) as exc_info:
        derive(rec)
    message = str(exc_info.value)
    assert "run-42" in message
    assert "A" in message


def test_ceiling_bound_is_the_share_removable():
    assert ceiling_bound(t_weights=40.0, t_total=200.0) == pytest.approx(0.20)


def test_ceiling_bound_rejects_zero_total():
    with pytest.raises(ValueError):
        ceiling_bound(t_weights=10.0, t_total=0.0)


def test_ceiling_bound_rejects_weights_exceeding_total():
    with pytest.raises(ValueError):
        ceiling_bound(t_weights=300.0, t_total=200.0)


# --- direct tests for the extracted warmup-trio functions (I10) ---
# These pin the definitions themselves, independent of RunRecord plumbing —
# and are what Task 11's worker/probe.py is meant to import instead of
# re-deriving the same formulas.


def test_steady_state_latency_is_median_of_last_three():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)]
    assert steady_state_latency(warmup) == pytest.approx(3.2)


def test_steady_state_latency_is_none_for_empty_warmup():
    assert steady_state_latency([]) is None


def test_warmup_penalty_is_first_over_steady():
    warmup = [{"req_index": 0, "end_to_end": 9.6}, {"req_index": 1, "end_to_end": 3.2}]
    assert warmup_penalty(warmup, steady=3.2) == pytest.approx(3.0)


def test_warmup_penalty_is_none_when_steady_is_zero():
    warmup = [{"req_index": 0, "end_to_end": 5.0}]
    assert warmup_penalty(warmup, steady=0.0) is None


def test_time_to_fast_index_returns_first_index_within_tolerance():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate([10.0, 3.4, 3.2])]
    assert time_to_fast_index(warmup, steady=3.2, tolerance=0.10) == 1


def test_time_to_fast_index_zero_tolerance_moves_the_index():
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate([10.0, 3.4, 3.2])]
    assert time_to_fast_index(warmup, steady=3.2, tolerance=0.0) == 2


def test_time_to_fast_index_is_none_when_steady_is_none():
    assert time_to_fast_index([{"req_index": 0, "end_to_end": 1.0}], steady=None) is None
