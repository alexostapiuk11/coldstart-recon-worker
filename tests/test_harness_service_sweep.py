"""The sweep's local side: schedule, payload, record, and the curve reduction."""

import json

import pytest

from harness.scheduler import ScheduledRun
from harness.service_sweep import (
    STATISTIC,
    SweepRun,
    build_sweep_record,
    condition_for,
    job_payload,
    level_of,
    num_prompts_for,
    reduce_curve,
    sweep_schedule,
    validate_levels,
)
from harness.submit import UNHEALTHY_ERROR, SubmitOutcome

CLOCK_A = {"t_submit": 0.0, "t_result": 9.0}


def test_conditions_round_trip_and_reject_anything_else():
    assert condition_for(16) == "c16"
    assert level_of("c16") == 16
    with pytest.raises(ValueError, match="not a sweep level"):
        level_of("A")


@pytest.mark.parametrize(
    ("levels", "match"),
    [([1], "at least two"), ([2, 1], "ascending"), ([1, 1, 2], "ascending"),
     ([0, 4], "positive integer"), ([1, True], "positive integer"), ([1, 2.5], "positive")],
)
def test_bad_levels_are_refused_before_anything_is_spent(levels, match):
    with pytest.raises(ValueError, match=match):
        validate_levels(levels)


def test_three_repeats_per_level_interleaved_by_seed():
    levels = [1, 2, 4, 8, 16, 32, 64]
    schedule = sweep_schedule(levels, seed=20261004)
    assert len(schedule) == 3 * len(levels)
    for block in range(3):
        in_block = [s for s in schedule if s.block_index == block]
        assert sorted(level_of(s.condition) for s in in_block) == levels
    for level in levels:
        idx = [s.run_index for s in schedule if s.condition == condition_for(level)]
        assert idx != list(range(idx[0], idx[0] + 3)), f"all repeats of {level} back to back"
    assert sweep_schedule(levels, seed=20261004) == schedule
    assert sweep_schedule(levels, seed=1) != schedule


def test_prompts_scale_with_the_level_above_a_floor():
    assert num_prompts_for(1) == 100
    assert num_prompts_for(8) == 160
    assert num_prompts_for(64) == 1280
    assert num_prompts_for(4, waves=10, minimum=5) == 40


def test_the_job_payload_carries_one_level_and_repeat():
    p = job_payload(
        ScheduledRun(5, 1, "c8"), "rid", serve_args=["--max-num-seqs", "256"],
        output_len=16, job_budget_s=1800, seed=100,
    )
    assert p == {
        "run_id": "rid", "run_index": 5, "level": 8, "repeat": 1,
        "serve_args": ["--max-num-seqs", "256"], "num_prompts": 160, "warmup_prompts": 8,
        "output_len": 16, "job_budget_s": 1800, "seed": 105, "diagnostics": False,
    }
    json.dumps(p)


def _summary(latency=0.5, util=0.4, path="exact"):
    return {
        "latency_s": latency, "ttft_median_s": 0.05, "throughput_tps": 32.0,
        "gpu_util": util, "prompt_path": path, "completed": 100, "failed": 0,
    }


def _ok_output(run_id="rid", level=8, run=None, repeat=0, **over):
    out = {
        "healthy": True, "run_id": run_id, "level": level, "repeat": repeat,
        "run": _summary() if run is None else run, "run_error": None,
        "served_cmd": ["vllm", "serve", "m", "--port", "8000"],
        "engine": {"max_num_seqs": 256, "kv_capacity_tokens": 35792},
        "log_lines": ["INFO GPU KV cache size: 35,792 tokens"],
        "host": {"host_id": "w1"}, "clock_C": {"delay_ms": 10},
    }
    out.update(over)
    return out


def test_an_ok_job_becomes_an_ok_record_with_the_curve_fields_on_top():
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(repeat=1), error=None),
    )
    assert (rec.outcome, rec.level, rec.repeat, rec.run_index) == ("ok", 8, 1, 5)
    assert (rec.latency_s, rec.throughput_tps, rec.gpu_util) == (0.5, 32.0, 0.4)
    assert rec.prompt_path == "exact"
    assert rec.engine["max_num_seqs"] == 256
    assert rec.engine["log_lines"] == ["INFO GPU KV cache size: 35,792 tokens"]
    assert rec.clock_C == {"delay_ms": 10}
    assert SweepRun.from_dict(json.loads(json.dumps(rec.to_dict()))) == rec


def test_a_truncated_log_is_recorded_as_truncated_with_its_true_total():
    """The handler keeps a head and a tail of the engine log. A record that kept
    only the lines would show 800 of 2000 with no sign the middle was cut."""
    out = _ok_output(
        repeat=1, log_lines=["head"] * 400 + ["tail"] * 400,
        log_lines_total=2000, log_truncated=True, log_head_lines=400,
    )
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.engine["log_truncated"] is True
    assert rec.engine["log_lines_total"] == 2000
    assert rec.engine["log_head_lines"] == 400
    assert len(rec.engine["log_lines"]) == 800


def test_a_failed_job_keeps_the_log_cap_flags_too():
    diag = {
        "healthy": False, "log_lines": ["x"] * 800, "served_cmd": ["vllm"],
        "log_lines_total": 5000, "log_truncated": True, "log_head_lines": 400,
    }
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c1"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=None, error=UNHEALTHY_ERROR, diagnostics=diag),
    )
    assert (rec.engine["log_truncated"], rec.engine["log_lines_total"]) == (True, 5000)


def test_an_untruncated_log_says_so():
    out = _ok_output(repeat=1, log_lines_total=1, log_truncated=False, log_head_lines=1)
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.engine["log_truncated"] is False
    assert rec.engine["log_lines_total"] == 1


def test_an_older_handler_output_stores_the_cap_flags_as_none_not_invented_values():
    """No `log_*` flags in the output: whether the log was cut is unknown, and a
    stored False or a total of len(log_lines) would claim it was not."""
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(repeat=1), error=None),
    )
    for key in ("log_truncated", "log_lines_total", "log_head_lines"):
        assert key in rec.engine and rec.engine[key] is None


def test_the_source_is_stored_on_the_record_when_the_driver_names_one():
    """A stub record must say it is a stub on its own, so a later reduction
    cannot be talked into labelling it measured."""
    ok = SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(repeat=1), error=None)
    assert build_sweep_record(ScheduledRun(5, 1, "c8"), "rid", ok, source="stub").source == "stub"
    assert build_sweep_record(ScheduledRun(5, 1, "c8"), "rid", ok).source is None
    failed = SubmitOutcome(clock_A=CLOCK_A, payload=None, error=UNHEALTHY_ERROR, diagnostics={})
    assert build_sweep_record(ScheduledRun(0, 0, "c1"), "rid", failed, source="runpod").source == "runpod"


def test_diagnostics_are_carried_into_the_record_when_the_worker_sends_them():
    out = _ok_output(repeat=1, diagnostics={"pandas_importable": False})
    rec = build_sweep_record(
        ScheduledRun(5, 1, "c8"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.diagnostics == {"pandas_importable": False}


def test_an_unhealthy_engine_is_a_failed_record_that_keeps_its_log():
    diag = {"healthy": False, "log_lines": ["CUDA out of memory"], "served_cmd": ["vllm"]}
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c1"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=None, error=UNHEALTHY_ERROR, diagnostics=diag),
    )
    assert rec.outcome == "failed"
    assert rec.status["failure_class"] == "health_timeout"
    assert rec.engine["log_lines"] == ["CUDA out of memory"]
    assert rec.latency_s is None


def test_a_failed_measurement_on_a_healthy_engine_is_a_failed_record():
    out = _ok_output(level=1, run=None)
    out["run"] = None
    out["run_error"] = "BenchError: vllm bench serve exited 1"
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c1"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=out, error=None)
    )
    assert rec.outcome == "failed"
    assert "exited 1" in rec.status["failure_detail"]
    assert rec.engine["log_lines"]


def test_an_answer_for_another_repeat_is_refused():
    with pytest.raises(ValueError, match="repeat"):
        build_sweep_record(
            ScheduledRun(0, 2, "c8"), "rid",
            SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(repeat=1), error=None),
        )
    with pytest.raises(ValueError, match="repeat"):
        build_sweep_record(
            ScheduledRun(0, 2, "c8"), "rid",
            SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(repeat=None), error=None),
        )


def test_timings_and_the_log_readers_state_are_stored_on_every_kind_of_record():
    timing = {"startup_s": 88.5, "teardown_s": 3.25, "drain_completed": False,
              "drain_error": "OSError('x')"}
    expected = {"startup_s": 88.5, "teardown_s": 3.25, "drain_completed": False,
                "drain_error": "OSError('x')"}

    def stored(rec):
        return {k: getattr(rec, k) for k in expected}

    ok = build_sweep_record(
        ScheduledRun(0, 0, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(**timing), error=None),
    )
    assert stored(ok) == expected
    no_run = _ok_output(run=None, run_error="BenchError: x", **timing)
    no_run["run"] = None
    failed = build_sweep_record(
        ScheduledRun(0, 0, "c8"), "rid", SubmitOutcome(clock_A=CLOCK_A, payload=no_run, error=None)
    )
    assert stored(failed) == expected
    unhealthy = build_sweep_record(
        ScheduledRun(0, 0, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=None, error=UNHEALTHY_ERROR,
                      diagnostics={"healthy": False, "log_lines": [], **timing}),
    )
    assert stored(unhealthy) == expected
    assert SweepRun.from_dict(json.loads(json.dumps(ok.to_dict()))) == ok


def test_a_record_with_no_timings_stores_none_not_zero():
    rec = build_sweep_record(
        ScheduledRun(0, 0, "c8"), "rid",
        SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(), error=None),
    )
    assert (rec.startup_s, rec.teardown_s, rec.drain_completed, rec.drain_error) == (
        None, None, None, None
    )


def test_an_answer_for_another_run_is_refused():
    with pytest.raises(ValueError, match="another run"):
        build_sweep_record(
            ScheduledRun(0, 0, "c8"), "rid",
            SubmitOutcome(clock_A=CLOCK_A, payload=_ok_output(run_id="other"), error=None),
        )


_NO_FIELD = object()


def _rec(level, repeat, *, latency=0.5, tps=32.0, util=0.4, path="exact", outcome="ok",
         cmd=("vllm", "serve", "m"), mns=256, windowed=_NO_FIELD, rt=_NO_FIELD):
    ok = outcome == "ok"
    summary = {} if windowed is _NO_FIELD else {"gpu_util_windowed": windowed}
    if rt is not _NO_FIELD:
        summary["bench_scalars"] = {} if rt is None else {"request_throughput": rt}
    return SweepRun(
        run_id=f"r{level}-{repeat}", run_index=0, condition=condition_for(level), level=level,
        repeat=repeat, outcome=outcome,
        latency_s=latency if ok else None, ttft_median_s=0.05 if ok else None,
        throughput_tps=tps if ok else None, gpu_util=util if ok else None,
        prompt_path=path if ok else None, served_cmd=list(cmd),
        summary=summary,
        engine={"max_num_seqs": mns, "kv_capacity_tokens": 35792},
    )


def _three(level, latencies, **kw):
    return [_rec(level, i, latency=lat, **kw) for i, lat in enumerate(latencies)]


def test_each_level_is_the_median_of_its_run_medians_with_the_min_max_interval():
    records = _three(1, [0.31, 0.30, 0.35], util=0.2) + _three(4, [0.40, 0.38, 0.39], util=0.6)
    red = reduce_curve(records)
    assert red.points == [(1, 0.31, 32.0, 0.2), (4, 0.39, 32.0, 0.6)]
    assert red.levels[0]["latency_s_range"] == [0.30, 0.35]
    assert red.levels[1]["n_runs"] == 3
    doc = red.to_dict()
    assert doc["statistic"] == STATISTIC
    assert doc["points"] == [[1, 0.31, 32.0, 0.2], [4, 0.39, 32.0, 0.6]]
    assert doc["engine"]["max_num_seqs"] == [256]
    json.dumps(doc)


def test_failed_runs_are_counted_and_left_out_of_the_statistics():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3) + [_rec(2, 3, outcome="failed")]
    red = reduce_curve(records)
    assert red.levels[1]["n_failed"] == 1
    assert red.levels[1]["n_runs"] == 3


def test_a_level_short_of_its_repeats_is_refused_unless_the_caller_lowers_the_bar():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 2)
    with pytest.raises(ValueError, match="level 2 has 2 successful runs"):
        reduce_curve(records)
    assert reduce_curve(records, min_repeats=2).levels[1]["n_runs"] == 2


def test_mixed_prompt_paths_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, path="random-fallback")
    with pytest.raises(ValueError, match="prompt paths"):
        reduce_curve(records)


def test_each_level_carries_the_median_request_throughput_of_its_runs():
    records = (_three(1, [0.3] * 3, rt=3.0)
               + [_rec(2, i, latency=0.4, rt=v) for i, v in enumerate([79.0, 81.0, 80.0])])
    red = reduce_curve(records)
    assert [row["request_throughput"] for row in red.levels] == [3.0, 80.0]
    assert red.to_dict()["levels"][1]["request_throughput"] == 80.0


def test_a_level_whose_run_lacks_the_throughput_carries_none_not_a_median_of_the_rest():
    records = (_three(1, [0.3] * 3, rt=3.0)
               + [_rec(2, 0, rt=80.0), _rec(2, 1, rt=None), _rec(2, 2)])
    assert [row["request_throughput"] for row in reduce_curve(records).levels] == [3.0, None]


def test_the_mixed_method_refusal_does_not_offer_a_single_level_re_run():
    records = _three(1, [0.3] * 3, windowed=True) + _three(2, [0.4] * 3, windowed=False)
    with pytest.raises(ValueError) as e:
        reduce_curve(records)
    text = str(e.value)
    assert "whole campaign" in text and "new store" in text
    assert "runs that differ" not in text, "a re-run of a subset cannot be reduced"


def test_the_short_level_refusal_names_the_options_that_can_be_carried_out():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 2)
    with pytest.raises(ValueError) as e:
        reduce_curve(records)
    text = str(e.value)
    assert "whole campaign" in text and "min-repeats 2" in text and "disclose" in text
    assert "its own" not in text and "Re-run the level" not in text


def test_mixed_serve_commands_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, cmd=("vllm", "serve", "other"))
    with pytest.raises(ValueError, match="serve commands"):
        reduce_curve(records)


def test_mixed_gpu_utilisation_methods_are_refused():
    records = _three(1, [0.3] * 3, windowed=True) + _three(2, [0.4] * 3, windowed=True)
    assert reduce_curve(records).levels[0]["n_runs"] == 3, "all windowed is one method"
    records[3].summary["gpu_util_windowed"] = False
    with pytest.raises(ValueError, match="would mix two measurements"):
        reduce_curve(records)


def test_a_run_that_never_says_how_its_utilisation_was_measured_is_not_pooled_with_ones_that_do():
    older = _three(1, [0.3] * 3)  # no gpu_util_windowed in the summary: unknown
    newer = _three(2, [0.4] * 3, windowed=False)
    with pytest.raises(ValueError, match="would mix two measurements"):
        reduce_curve(older + newer)
    with pytest.raises(ValueError, match="would mix two measurements"):
        reduce_curve(_three(2, [0.4] * 3, windowed=True) + older)
    assert reduce_curve(older + _three(2, [0.4] * 3)).levels[1]["n_runs"] == 3, (
        "an all-unknown store (written before the field existed) is one method, not a mix"
    )
    assert reduce_curve(_three(1, [0.3] * 3, windowed=False) + newer).levels[1]["n_runs"] == 3


@pytest.mark.parametrize(
    ("windowed", "label"), [(True, "windowed"), (False, "whole-call"), (_NO_FIELD, "unrecorded")]
)
def test_the_curve_says_which_utilisation_method_its_runs_agreed_on(windowed, label):
    records = _three(1, [0.3] * 3, windowed=windowed) + _three(2, [0.4] * 3, windowed=windowed)
    red = reduce_curve(records)
    assert red.gpu_util_method == label
    assert red.to_dict()["gpu_util_method"] == label


def test_a_failed_run_does_not_count_towards_the_utilisation_methods():
    records = _three(1, [0.3] * 3, windowed=True) + _three(2, [0.4] * 3, windowed=True)
    records.append(_rec(2, 3, outcome="failed", windowed=False))
    assert reduce_curve(records).levels[1]["n_failed"] == 1


def test_a_missing_utilisation_is_refused_rather_than_invented():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3)
    records[0].gpu_util = None
    with pytest.raises(ValueError, match="utilisation"):
        reduce_curve(records)


def test_two_campaigns_in_one_store_are_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3) + [_rec(1, 0)]
    with pytest.raises(ValueError, match="more than one campaign"):
        reduce_curve(records)


def test_a_requested_level_with_no_runs_is_refused():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3)
    with pytest.raises(ValueError, match=r"levels \[4\]"):
        reduce_curve(records, expected_levels=[1, 2, 4])


def test_a_single_level_or_an_empty_store_is_refused():
    with pytest.raises(ValueError, match="no successful run"):
        reduce_curve([])
    with pytest.raises(ValueError, match="at least two"):
        reduce_curve(_three(1, [0.3] * 3))


def test_engine_facts_report_every_distinct_value_including_absence():
    records = _three(1, [0.3] * 3) + _three(2, [0.4] * 3, mns=None)
    assert reduce_curve(records).engine["max_num_seqs"] == [256, None]


_HASHSEED_SCRIPT = """
import json
from harness.service_sweep import SweepRun, condition_for, reduce_curve, sweep_schedule

levels = [1, 2, 4, 8, 16, 32, 64]
schedule = sweep_schedule(levels, seed=20261004)
records = [
    SweepRun(
        run_id=f"r{s.run_index}", run_index=s.run_index, condition=s.condition,
        level=int(s.condition[1:]), repeat=s.block_index, outcome="ok",
        latency_s=0.1 * (s.run_index % 7) + 0.01 * int(s.condition[1:]),
        ttft_median_s=0.05, throughput_tps=32.0, gpu_util=0.4, prompt_path="exact",
        served_cmd=["vllm", "serve", "m"], engine={"max_num_seqs": 256},
    )
    for s in schedule
]
print(json.dumps({
    "schedule": [[s.run_index, s.block_index, s.condition] for s in schedule],
    "curve": reduce_curve(records, expected_levels=levels).to_dict(),
}, sort_keys=True))
"""


def test_schedule_and_reduction_do_not_depend_on_the_hash_seed():
    """Set and dict order depends on PYTHONHASHSEED; a result that does would not reproduce."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    outputs = []
    for hashseed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hashseed, "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run(
            [sys.executable, "-c", _HASHSEED_SCRIPT],
            cwd=root, env=env, capture_output=True, text=True, check=False,
        )
        assert done.returncode == 0, done.stderr
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["schedule"]
