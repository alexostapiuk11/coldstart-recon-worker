import pytest

from coldstart.analysis.metrics import (
    ceiling_bound,
    derive,
    steady_state_latency,
    t_fast_seconds,
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


# Default per-run S4 sub-phase durations. Sum = 34.0; with the default
# S4_start=54.0/S4_end=90.0 bracket (36.0), that leaves a genuine 2.0s
# unattributed remainder -- deliberately nonzero, matching the spec's "the
# waterfall never sums to a suspiciously exact 100%". S4b (compilation) is
# the largest sub-phase by construction, since it's the one B3 exists to
# surface.
_S4_SUBPHASES = {"S4a": 3.0, "S4b": 20.0, "S4c": 4.0, "S4d": 2.0, "S4e": 5.0}


def make(arm="A", t_submit=0.0, t_result=150.0, marks=None, warmup=None, s4_subphases=...):
    marks = marks or [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S4_start", "t_mono": 54.0},
        {"stage": "S4_end", "t_mono": 90.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 130.0},
    ]
    warmup = warmup or [
        {"req_index": i, "ttft": 0.5, "end_to_end": v} for i, v in enumerate(_WARMUP_LATENCIES)
    ]
    # `...` (not None) is the "use the default" sentinel, so a caller can
    # still pass s4_subphases=None or ={} to explicitly test "engine omitted
    # the field entirely" without that colliding with "use the default".
    if s4_subphases is ...:
        s4_subphases = dict(_S4_SUBPHASES)
    engine = {"kv_cache_blocks": 8192, "block_size": 16}
    if s4_subphases is not None:
        engine["s4_subphases"] = s4_subphases
    return RunRecord(
        run_id="r",
        run_index=0,
        arm=arm,
        clock_A={"t_submit": t_submit, "t_result": t_result},
        clock_C={},
        clock_B={"t0_wall": 0.0, "marks": marks},
        warmup=warmup,
        engine=engine,
        host={"host_id": "h1"},
        config={},
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def test_t_process_is_t0_to_first_token():
    d = derive(make())
    assert d["t_process"] == 102.0


def test_t_total_job_is_the_raw_uncorrected_submit_to_result_span():
    """`t_total_job` is real data (the driver's submit-to-job-return span) and
    must be published even though it is not T_total — see B1."""
    assert derive(make())["t_total_job"] == pytest.approx(150.0)


def test_t_total_is_corrected_by_subtracting_the_warmup_tail():
    """B1: `t_result` is stamped after all ten warmup requests (S7), not at
    first token (S6) — the spec's T_total boundary. derive() must correct
    for that by subtracting the clock-B warmup-tail duration
    (S7_warmup_done - S6_first_token = 130.0 - 102.0 = 28.0) from the raw
    clock-A span (150.0), landing on 122.0.

    This fixture's marks (S5_ready/S6_request1_dispatch = 100.0 vs.
    S6_first_token = 102.0) are deliberately distinct, so a mutant that
    subtracts the wrong pair of marks (e.g. S7 - S5_ready = 30.0, or
    S7 - S6_request1_dispatch = 30.0) would land on 120.0, not 122.0, and a
    mutant that drops the correction entirely would land on 150.0, and a
    mutant that flips the sign would land on 178.0. All three are wrong
    against this literal.
    """
    assert derive(make())["t_total"] == pytest.approx(122.0)


def test_residual_is_the_difference():
    # t_platform = t_total(122.0, corrected) - t_process(102.0) = 20.0.
    assert derive(make())["t_platform"] == pytest.approx(20.0)


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
    # t_process=102.0 (default marks), warmup-tail correction=28.0 (default
    # marks), so t_total = (t_result - 0.0) - 28.0. Setting t_result=130.03
    # lands t_total at 102.03 -> residual=0.03, below the 0.05 rtt floor.
    # (Before the B1 fix this fixture used t_result=102.03 directly against
    # the uncorrected t_total; that value now lands t_total at 74.03, which
    # trips PROCESS_EXCEEDS_TOTAL instead — recalibrated here for the
    # correction.)
    d = derive(make(t_result=130.03))
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
    # full "ok": True row instead of the 6-key failure row asserted above.
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
    # S2/S3 marks were both present -- the value was just invalid -- but this
    # minimal fixture also omits S4_start/S4_end, so those are genuinely
    # merged (recorded, not substituted with S5_ready - S3_load_done).
    assert d["merged_phases"] == ["S4_start", "S4_end"]


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


def test_missing_s7_warmup_done_leaves_t_total_uncorrected_and_flagged():
    """A run that reached first token (S6) and then failed or was cut off
    mid-warmup, before S7_warmup_done was marked, is a real, expected state
    (not a defect to paper over). Falling back to the raw, uncorrected span
    here would silently reintroduce B1 for exactly the runs most likely to
    be anomalous, so this must not compute t_total at all -- it must be
    flagged, not guessed.
    """
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S7_warmup_done"]
    d = derive(make(marks=marks))
    assert d["t_total"] is None
    assert d["t_total_job"] == pytest.approx(150.0)  # raw span still published
    assert d["consistent"] is False
    assert d["t_platform"] is None
    assert d["inconsistency_reason"] is not None
    assert d["discard_reason"] == DiscardReason.MISSING_WARMUP_END


def test_negative_correction_term_raises_loudly():
    """S7_warmup_done preceding S6_first_token is impossible on a monotonic
    clock B -- corrupted data, not a borderline measurement. It must not be
    folded quietly into "just another inconsistent run": it raises, the same
    way a missing required mark does.
    """
    marks = [
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 90.0},
    ]
    rec = make(marks=marks)
    rec.run_id = "run-99"
    with pytest.raises(ValueError) as exc_info:
        derive(rec)
    message = str(exc_info.value)
    assert "run-99" in message
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


def test_steady_state_latency_routes_through_stats_median_and_rejects_nan():
    """steady_state_latency must go through coldstart.analysis.stats.median,
    not statistics.median -- the one median in the pipeline that used to
    skip both the shared quantile function every other aggregate uses and
    its non-finite validation. A `statistics.median` implementation would
    silently sort a NaN into the result (Python's `<` against NaN is always
    False, so it can land anywhere) instead of raising."""
    warmup = [{"req_index": i, "end_to_end": v} for i, v in enumerate([1.0, 2.0, float("nan")])]
    with pytest.raises(ValueError, match="non-finite"):
        steady_state_latency(warmup)


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


# --- B3/B2 fix: the S4 bracket, its sub-phases, t_compile, and s4_unattributed ---
# Default fixture: S3_load_done=54.0, S4_start=54.0, S4_end=90.0, S5_ready=100.0,
# subphases S4a=3.0 S4b=20.0 S4c=4.0 S4d=2.0 S4e=5.0 (sum=34.0).
# t_s4_bracket = 90.0 - 54.0 = 36.0
# s4_unattributed = 36.0 - 34.0 = 2.0  (deliberately nonzero and small)
# t_s1 = 4.0, t_s5 = 100.0 - 90.0 = 10.0, t_s6 = 102.0 - 100.0 = 2.0


def test_t_s4_bracket_is_s4_end_minus_s4_start():
    assert derive(make())["t_s4_bracket"] == pytest.approx(36.0)


def test_t_s4_bracket_is_none_when_s4_start_missing_and_recorded_merged():
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S4_start"]
    d = derive(make(marks=marks))
    assert d["t_s4_bracket"] is None
    assert "S4_start" in d["merged_phases"]


def test_t_s4_bracket_is_none_when_s4_end_missing_and_recorded_merged():
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S4_end"]
    d = derive(make(marks=marks))
    assert d["t_s4_bracket"] is None
    assert "S4_end" in d["merged_phases"]


def test_t_s4_bracket_never_substitutes_s5_ready_minus_s3_load_done():
    """S5_ready - S3_load_done (100.0 - 54.0 = 46.0) folds all of S5 (a
    health-poll interval, per spec) into S4 and is NOT the bracket -- see
    the spec's Attribution caveat. With S4_start/S4_end absent, the bracket
    must be None, never silently computed as 46.0."""
    marks = [
        m
        for m in make().clock_B["marks"]
        if m["stage"] not in ("S4_start", "S4_end")
    ]
    d = derive(make(marks=marks))
    assert d["t_s4_bracket"] is None
    assert d["t_s4_bracket"] != pytest.approx(46.0)


def test_t_s4_bracket_negative_is_flagged_inconsistent_not_corrected():
    marks = [
        {"stage": "S4_start", "t_mono": 95.0},
        {"stage": "S4_end", "t_mono": 90.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
    ]
    d = derive(make(marks=marks))
    assert d["t_s4_bracket"] is None
    assert d["consistent"] is False


def test_s4_subphases_are_extracted_into_explicit_fields():
    d = derive(make())
    assert d["t_s4a"] == pytest.approx(3.0)
    assert d["t_s4b"] == pytest.approx(20.0)
    assert d["t_s4c"] == pytest.approx(4.0)
    assert d["t_s4d"] == pytest.approx(2.0)
    assert d["t_s4e"] == pytest.approx(5.0)


def test_a_single_undelineated_subphase_is_none_not_zero_and_recorded_merged():
    """S4d absent from the engine's log for this run is a genuinely
    different fact from S4d having taken 0.0 seconds -- conflating the two
    (the .get(k, 0.0) bug) understates S4 the same way clamping a negative
    unattributed term would."""
    subphases = {k: v for k, v in _S4_SUBPHASES.items() if k != "S4d"}
    d = derive(make(s4_subphases=subphases))
    assert d["t_s4d"] is None
    assert d["merged_phases"] == ["S4d"]


def test_all_subphases_absent_when_engine_omits_the_field_entirely():
    d = derive(make(s4_subphases=None))
    assert d["t_s4a"] is None
    assert d["t_s4b"] is None
    assert d["t_s4c"] is None
    assert d["t_s4d"] is None
    assert d["t_s4e"] is None
    assert d["merged_phases"] == ["S4a", "S4b", "S4c", "S4d", "S4e"]
    # bracket is still measured independently of the sub-phase parser.
    assert d["t_s4_bracket"] == pytest.approx(36.0)
    # unattributed collapses to the whole bracket, honestly, rather than
    # raising or silently reporting 0.0 sub-phases as real zeros.
    assert d["s4_unattributed"] == pytest.approx(36.0)


def test_t_compile_is_sourced_from_s4b():
    """B3: t_compile is what economics.compile_cache_term has been waiting
    for -- see test_t_compile_feeds_compile_cache_term below for the wiring."""
    assert derive(make())["t_compile"] == pytest.approx(20.0)


def test_t_compile_is_none_when_s4b_is_undelineated():
    subphases = {k: v for k, v in _S4_SUBPHASES.items() if k != "S4b"}
    assert derive(make(s4_subphases=subphases))["t_compile"] is None


def test_t_compile_feeds_compile_cache_term():
    """B3 end to end: derive() now produces the two inputs
    economics.compile_cache_term needs, where previously nothing did."""
    from coldstart.analysis.economics import compile_cache_term

    cold = derive(make(arm="B", s4_subphases={**_S4_SUBPHASES, "S4b": 20.0}))
    warm = derive(make(arm="C", s4_subphases={**_S4_SUBPHASES, "S4b": 3.0}))
    saved = compile_cache_term(s4b_cold=cold["t_compile"], s4b_warm=warm["t_compile"])
    assert saved == pytest.approx(17.0)


def test_s4_unattributed_is_bracket_minus_identified_subphases():
    """Must be computed from t_s4_bracket (36.0), not from t_process
    (102.0) -- the two differ by 66.0 in this fixture specifically so a
    mutant reading t_process instead of the bracket cannot pass by
    accident: t_process - sum(subphases) = 102 - 34 = 68, not 2.0."""
    assert derive(make())["s4_unattributed"] == pytest.approx(2.0)


def test_s4_unattributed_is_none_when_bracket_is_none():
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S4_start"]
    assert derive(make(marks=marks))["s4_unattributed"] is None


def test_s4_unattributed_negative_is_flagged_inconsistent_not_corrected():
    """Identified sub-phases summing to more than the bracket that is
    supposed to contain them is impossible -- the same discipline
    derive() already applies to a negative t_weights."""
    subphases = {"S4a": 10.0, "S4b": 10.0, "S4c": 10.0, "S4d": 10.0, "S4e": 10.0}  # sum=50 > 36
    d = derive(make(s4_subphases=subphases))
    assert d["s4_unattributed"] is None
    assert d["consistent"] is False
    assert d["inconsistency_reason"] is not None


def test_t_s1_is_the_imports_done_mark():
    assert derive(make())["t_s1"] == pytest.approx(4.0)


def test_t_s5_is_ready_minus_s4_end():
    assert derive(make())["t_s5"] == pytest.approx(10.0)


def test_t_s5_is_none_when_s4_end_missing():
    """t_s5 must not fall back to S3_load_done either -- same discipline as
    the bracket itself."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S4_end"]
    assert derive(make(marks=marks))["t_s5"] is None


def test_t_s6_is_first_token_minus_request1_dispatch():
    assert derive(make())["t_s6"] == pytest.approx(2.0)


# --- B5 fix: t_fast_seconds ---
#
# The default `make()` fixture's warmup records (like every real record
# recorded before Task 11 ships) carry no `t_dispatch_mono`, so
# `d["t_fast_seconds"]` is None on all the tests above that use it
# unmodified -- pinned explicitly below rather than left as an accidental
# side effect of those tests never checking it.


def test_t_fast_seconds_is_none_when_dispatch_offset_absent():
    """The field Task 11's probe will add (`t_dispatch_mono`) is absent from
    every real run and every fixture above today. `t_fast_seconds` must be
    `None` with the reason visible in the row -- never silently inferred by
    summing `end_to_end`, which would assume zero gap between requests
    (an assumption, not a measurement)."""
    d = derive(make())
    assert d["t_fast_seconds"] is None
    assert d["t_fast_reason"] is not None
    assert "t_dispatch_mono" in d["t_fast_reason"]


def test_t_fast_seconds_is_none_when_warmup_is_empty():
    """No warmup requests means no steady state, so `time_to_fast_index` is
    already `None` -- `t_fast_seconds` must follow it to `None` rather than
    raising on an empty warmup list. `make(warmup=[])` would not exercise
    this (its `warmup or [...]` default treats `[]` as falsy and silently
    substitutes the standard fixture), so the record is built and then
    mutated directly instead."""
    rec = make()
    rec.warmup = []
    d = derive(rec)
    assert d["time_to_fast_index"] is None
    assert d["t_fast_seconds"] is None
    assert d["t_fast_reason"] is not None


def test_t_fast_seconds_is_none_when_s7_warmup_done_missing():
    """Same discipline as `t_total` (B1): a run cut off before
    `S7_warmup_done` cannot have its warmup-tail correction computed for
    `T_fast` either, and must be flagged rather than guessed."""
    marks = [m for m in make().clock_B["marks"] if m["stage"] != "S7_warmup_done"]
    d = derive(make(marks=marks))
    assert d["t_total"] is None  # already covered by test_missing_s7_warmup_done_*
    assert d["t_fast_seconds"] is None
    assert "S7_warmup_done" in d["t_fast_reason"]


def test_t_fast_seconds_uses_recorded_dispatch_offsets_not_summed_end_to_end():
    """A fixture where dispatch offsets equal the cumulative sum of prior
    `end_to_end` values could not tell a real per-request measurement apart
    from the summing inference this fix removes -- both would compute the
    same number. This fixture instead bakes a deliberate 0.3s gap between
    every request's completion and the next request's dispatch (driver-side
    overhead between sequential requests), so the two would disagree.

    Hand-computed dispatch offsets (start=100.0, gap=0.3, e2e from
    `_WARMUP_LATENCIES`): [100.0, 110.3, 119.6, 127.9, 135.2, 141.5, 146.8,
    150.5, 154.8, 158.3]. `steady_state_latency` (median of the last three
    end_to_end, [4.0, 3.2, 2.0]) is 3.2, threshold 3.52, so
    `time_to_fast_index` is 6 (e2e=3.4). Fast completion on clock B =
    dispatch[6] (146.8) + end_to_end[6] (3.4) = 150.2. `S7_warmup_done` is
    the last request's own completion, dispatch[9] (158.3) + end_to_end[9]
    (2.0) = 160.3. With t_submit=0.0, t_result=260.0
    (t_total_job=260.0): tail = 160.3 - 150.2 = 10.1, so
    t_fast_seconds = 260.0 - 10.1 = 249.9.
    """
    dispatch = [100.0, 110.3, 119.6, 127.9, 135.2, 141.5, 146.8, 150.5, 154.8, 158.3]
    warmup = [
        {"req_index": i, "ttft": 0.5, "end_to_end": e2e, "t_dispatch_mono": d}
        for i, (e2e, d) in enumerate(zip(_WARMUP_LATENCIES, dispatch, strict=True))
    ]
    marks = [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S4_start", "t_mono": 54.0},
        {"stage": "S4_end", "t_mono": 90.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 102.0},
        {"stage": "S7_warmup_done", "t_mono": 160.3},
    ]
    d = derive(make(marks=marks, warmup=warmup, t_submit=0.0, t_result=260.0))
    assert d["time_to_fast_index"] == 6
    assert d["t_fast_seconds"] == pytest.approx(249.9)
    assert d["t_fast_reason"] is None
    # Sanity: T_fast >= T_total holds (spec 7), and neither collapses to the
    # other -- a mutant that returned t_total_job or t_total unmodified
    # would land on 260.0 or 201.7, not 249.9.
    assert d["t_fast_seconds"] >= d["t_total"]
    assert d["t_total"] == pytest.approx(201.7)


def test_t_fast_less_than_t_total_raises_loudly():
    """Spec 7: T_fast >= T_total always. This fixture deliberately corrupts
    S6_first_token to an implausibly late 200.0 while the fast-tolerance
    request (index 6, e2e=3.4) is dispatched at 50.0 and so completes at
    53.4 -- well before the recorded first-token mark. That ordering is
    impossible under honest instrumentation, and derive() must raise rather
    than publish a T_fast smaller than T_total.
    """
    marks = [
        {"stage": "S1_imports_done", "t_mono": 4.0},
        {"stage": "S2_acquisition_start", "t_mono": 4.0},
        {"stage": "S3_load_done", "t_mono": 54.0},
        {"stage": "S4_start", "t_mono": 54.0},
        {"stage": "S4_end", "t_mono": 90.0},
        {"stage": "S5_ready", "t_mono": 100.0},
        {"stage": "S6_request1_dispatch", "t_mono": 100.0},
        {"stage": "S6_first_token", "t_mono": 200.0},
        {"stage": "S7_warmup_done", "t_mono": 210.0},
    ]
    warmup = [
        {"req_index": i, "ttft": 0.5, "end_to_end": v, "t_dispatch_mono": 50.0}
        for i, v in enumerate(_WARMUP_LATENCIES)
    ]
    rec = make(marks=marks, warmup=warmup, t_submit=0.0, t_result=300.0)
    rec.run_id = "run-corrupt"
    with pytest.raises(ValueError, match="T_fast"):
        derive(rec)


def test_t_fast_seconds_pure_function_negative_tail_raises():
    """Direct test of the extracted function: a fast-index completion after
    `S7_warmup_done` is impossible on a monotonic clock, the same
    discipline as every other "impossible" case in this module."""
    warmup = [{"req_index": 0, "ttft": 0.5, "end_to_end": 5.0, "t_dispatch_mono": 100.0}]
    with pytest.raises(ValueError, match="negative"):
        t_fast_seconds(warmup, fast_index=0, t_total_job=200.0, t_warmup_done_mono=104.0)


def test_t_fast_seconds_pure_function_reason_is_none_only_when_value_is_not():
    """`reason` and `value` are mutually exclusive -- a caller should never
    have to check both to know which branch fired."""
    value, reason = t_fast_seconds([], fast_index=None, t_total_job=1.0, t_warmup_done_mono=None)
    assert value is None
    assert reason is not None


def test_kv_capacity_uses_the_engine_reported_token_count():
    """vLLM 0.27.1 reports "GPU KV cache size: N tokens" directly and emits no
    block count or block size (fixtures/README.md Q1). The capacity must be
    read from that, not left None because it cannot be reconstructed."""
    rec = make()
    rec.engine = {"kv_capacity_tokens": 35792}
    d = derive(rec)
    assert d["kv_capacity_tokens"] == 35792
    assert d["kv_cache_blocks"] is None


def test_directly_reported_capacity_wins_over_reconstruction():
    """The engine's own statement of capacity beats blocks x block_size, which
    exists only for versions that report the parts instead of the total."""
    rec = make()
    rec.engine = {"kv_capacity_tokens": 35792, "kv_cache_blocks": 8192, "block_size": 16}
    assert derive(rec)["kv_capacity_tokens"] == 35792


def test_directly_reported_zero_capacity_is_zero_not_none():
    rec = make()
    rec.engine = {"kv_capacity_tokens": 0}
    assert derive(rec)["kv_capacity_tokens"] == 0


def test_arm_state_mismatch_is_discarded_with_its_own_reason():
    """Arm C configured warm but observed cold means VLLM_CACHE_ROOT did not
    reach the engine, so arm C silently ran as arm B. The campaign would
    report a compile effect near zero and look entirely healthy."""
    record = make()
    record.arm = "C"
    record.config = {"arm": "C", "compile_cache_warm": True}
    record.engine = dict(record.engine, compile_cache_observed=False)
    d = derive(record)
    assert d["consistent"] is False
    assert d["discard_reason"] == DiscardReason.ARM_STATE_MISMATCH


def test_matching_arm_state_is_left_alone():
    record = make()
    record.arm = "C"
    record.config = {"arm": "C", "compile_cache_warm": True}
    record.engine = dict(record.engine, compile_cache_observed=True)
    assert derive(record)["consistent"] is True


def test_cold_arm_observing_a_warm_cache_is_also_a_mismatch():
    """The leak direction that actually happened in reconnaissance: a cold arm
    finding a previous run's compiled artifacts."""
    record = make()
    record.arm = "A"
    record.config = {"arm": "A", "compile_cache_warm": False}
    record.engine = dict(record.engine, compile_cache_observed=True)
    d = derive(record)
    assert d["consistent"] is False
    assert d["discard_reason"] == DiscardReason.ARM_STATE_MISMATCH


def test_absent_arm_state_is_not_a_mismatch():
    """Fixtures and stub rows carry neither field. Absence is unknown, not
    a violation -- inventing one would discard every historical record."""
    record = make()
    record.config = {}
    record.engine = dict(record.engine)
    record.engine.pop("compile_cache_observed", None)
    assert derive(record)["consistent"] is True
