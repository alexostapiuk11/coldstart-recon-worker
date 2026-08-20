import pytest

from coldstart.analysis.metrics import ceiling_bound, derive
from coldstart.schema import RunRecord


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
        {"req_index": i, "ttft": 0.5, "end_to_end": 2.0 if i >= 3 else 6.0} for i in range(10)
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
    assert d["steady_state_latency"] == 2.0
    assert d["warmup_penalty"] == 3.0


def test_inconsistent_run_is_flagged_not_silently_kept():
    d = derive(make(t_result=50.0))
    assert d["consistent"] is False
    assert d["t_platform"] is None


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
    assert "S3" in d["merged_phases"]


def test_ceiling_bound_is_the_share_removable():
    assert ceiling_bound(t_weights=40.0, t_total=200.0) == pytest.approx(0.20)
