"""The sweep's RunPod handler, driven against a fake engine and bench."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sweep_fakes import (
    KV_LINE,
    NON_DEFAULT_LINE,
    PROMPT_TOKENS,
    FakeEngine,
    model_latency,
    model_util,
)

from harness.scheduler import ScheduledRun
from harness.service_sweep import build_sweep_record, job_payload
from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import sweep_handler


@pytest.fixture(autouse=True)
def endpoint_env(monkeypatch):
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.setenv("MODEL_REVISION", "b968826d9c46dd6066d109eabc6255188de91218")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")


def _payload(level=8, repeat=0, run_id="rid", **over):
    p = job_payload(
        ScheduledRun(run_index=3, block_index=repeat, condition=f"c{level}"), run_id,
        serve_args=["--max-num-seqs", "256"], output_len=16, job_budget_s=1800, seed=100,
    )
    p.update(over)
    return p


def _run(engine, payload):
    return sweep_handler.handler({"input": payload}, deps=engine.deps(sweep_handler.Deps))


def test_the_prompt_is_artifact_ones_byte_for_byte():
    import probe

    assert sweep_handler.A1_PROMPT == probe.PROMPT


def test_a_healthy_run_returns_a_compact_summary_and_the_engine_facts():
    engine = FakeEngine()
    out = _run(engine, _payload(level=8))
    assert out["healthy"] is True
    assert out["run_error"] is None
    assert (out["run_id"], out["level"], out["repeat"]) == ("rid", 8, 0)
    assert out["run"]["latency_s"] == pytest.approx(model_latency(8))
    assert out["run"]["gpu_util"] == pytest.approx(model_util(8))
    assert out["run"]["prompt_path"] == "exact"
    assert out["run"]["input_lens_unique"] == [PROMPT_TOKENS]
    assert out["run"]["gpu_util_windowed"] is True
    assert out["run"]["gpu_util_whole_call"] == pytest.approx(model_util(8))
    assert out["engine"]["max_num_seqs"] == 256
    assert out["engine"]["max_num_seqs_source"] == "non-default-args"
    assert out["engine"]["kv_capacity_tokens"] == 35792
    assert out["teardown_s"] == 1.5
    text = json.dumps(out)
    assert '"ttfts"' not in text and '"itls"' not in text, "per-request arrays leaked"
    assert len(text) < 20_000


def test_serve_args_are_the_endpoints_fixed_flags_then_the_jobs():
    engine = FakeEngine()
    _run(engine, _payload())
    assert engine.served_calls == [{
        "model": "Qwen/Qwen3-8B",
        "args": ["--revision", "b968826d9c46dd6066d109eabc6255188de91218",
                 "--max-model-len", "8192", "--max-num-seqs", "256"],
        "env": {},
    }]


def test_a_job_may_not_override_a_flag_the_endpoint_owns():
    with pytest.raises(ValueError, match="endpoint environment owns"):
        _run(FakeEngine(), _payload(serve_args=["--max-model-len=4096"]))


def test_the_bench_sequence_is_probe_warmup_then_one_measured_run():
    engine = FakeEngine()
    _run(engine, _payload(level=8))
    names = [c["result_dir"].name for c in engine.bench_calls]
    assert names == ["prompt-probe", "warmup", "measured"]
    measured = engine.bench_calls[-1]
    assert (measured["max_concurrency"], measured["num_prompts"]) == (8, 160)
    assert measured["timeout"] is not None, "the measured run must be bounded by the job budget"
    probe = engine.bench_calls[0]
    # a hung probe would hold the job until the platform killed it and returned
    # nothing, so it is bounded by the same budget: 1800 s less the reserve
    assert 0 < probe["timeout"] <= 1800 - sweep_handler.TEARDOWN_RESERVE_S


def test_an_unhealthy_engine_returns_its_log_and_runs_no_load():
    engine = FakeEngine(healthy=False)
    out = _run(engine, _payload())
    assert out["healthy"] is False
    assert any("KV cache size" in line for line in out["log_lines"])
    assert engine.bench_calls == []


def test_a_failed_measurement_still_returns_the_log_and_stops_the_engine():
    engine = FakeEngine(fail_measured_at=(8, 0))
    out = _run(engine, _payload(level=8))
    assert out["healthy"] is True
    assert out["run"] is None
    assert out["run_error"].startswith("BenchError")
    assert out["log_lines"]
    assert engine.servers[0].stops >= 1


def test_a_probe_that_cannot_send_the_prompt_falls_back_and_says_so():
    out = _run(FakeEngine(probe_ok=False), _payload())
    assert out["run"]["prompt_path"] == "random-fallback"
    assert "pandas" in out["run"]["prompt"]["probe_error"]


def test_a_budget_spent_on_startup_is_a_run_error_not_a_platform_kill():
    out = _run(FakeEngine(), _payload(job_budget_s=60))
    assert out["run"] is None
    assert "budget is spent" in out["run_error"]


def test_a_run_with_failed_requests_is_a_run_error_the_handler_reports_like_any_other():
    out = _run(FakeEngine(failed_requests=3), _payload(level=8))
    assert out["healthy"] is True
    assert out["run"] is None
    assert "3 of 160 requests failed" in out["run_error"]
    assert "understate" in out["run_error"]
    assert out["log_lines"]


def test_the_output_becomes_an_ok_record_through_the_stub_submitter():
    engine = FakeEngine()
    payload = _payload(level=4)
    outcome = PayloadStubSubmitter(lambda p: _run(engine, p)).submit_payload(payload)
    rec = build_sweep_record(ScheduledRun(3, 0, "c4"), "rid", outcome)
    assert rec.outcome == "ok"
    assert rec.latency_s == pytest.approx(model_latency(4))
    assert rec.engine["max_num_seqs"] == 256


def test_an_unhealthy_output_becomes_a_health_timeout_record():
    engine = FakeEngine(healthy=False)
    outcome = PayloadStubSubmitter(lambda p: _run(engine, p)).submit_payload(_payload(level=4))
    rec = build_sweep_record(ScheduledRun(3, 0, "c4"), "rid", outcome)
    assert rec.outcome == "failed"
    assert rec.status["failure_class"] == "health_timeout"
    assert rec.engine["log_lines"]


def test_an_ordinary_job_runs_no_diagnostics_and_keeps_no_raw_json():
    engine = FakeEngine()
    out = _run(engine, _payload())
    assert "diagnostics" not in out
    assert "raw_bench" not in out["run"]
    assert engine.commands == []


def test_a_diagnostic_job_answers_the_first_paid_runs_questions():
    engine = FakeEngine()
    out = _run(engine, _payload(diagnostics=True))
    diag = out["diagnostics"]
    assert diag["bench_help"]["cmd"] == ["vllm", "bench", "serve", "--help"]
    assert "--save-detailed" in diag["bench_help"]["stdout"]
    assert diag["nvidia_smi"]["stdout"] == "42"
    assert isinstance(diag["pandas_importable"], bool)
    clocks = diag["clocks"]
    assert set(clocks["monotonic"]) >= {"implementation", "resolution", "monotonic", "adjustable"}
    assert set(clocks["perf_counter"]) >= {"implementation", "resolution"}
    assert clocks["child_cmd"][-1].endswith("print(time.perf_counter())")
    assert diag["prompt_in_log"] is False
    assert out["run"]["raw_bench"]["ttfts"], "the diagnostic job keeps the saved JSON"


def test_the_clock_diagnostic_says_whether_another_process_shares_the_monotonic_epoch():
    def child_on_the_same_clock(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, f"{time.monotonic()!r}\n", "")

    def child_on_another_clock(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "12.5\n", "")

    def child_that_fails(cmd, **kwargs):
        raise OSError("no python")

    same = sweep_handler.collect_diagnostics(child_on_the_same_clock, [])["clocks"]
    assert same["child_perf_counter_between"] is True
    assert same["monotonic_before_child"] <= same["child_perf_counter"] <= same[
        "monotonic_after_child"
    ]
    other = sweep_handler.collect_diagnostics(child_on_another_clock, [])["clocks"]
    assert other["child_perf_counter"] == 12.5
    assert other["child_perf_counter_between"] is False
    broken = sweep_handler.collect_diagnostics(child_that_fails, [])["clocks"]
    assert broken["child_perf_counter"] is None
    assert broken["child_perf_counter_between"] is None


def test_an_unhealthy_diagnostic_job_still_reports_the_tools_help():
    out = _run(FakeEngine(healthy=False), _payload(diagnostics=True))
    assert out["healthy"] is False
    assert out["diagnostics"]["bench_help"]["returncode"] == 0


def test_model_id_is_required(monkeypatch):
    monkeypatch.delenv("MODEL_ID")
    with pytest.raises(KeyError):
        _run(FakeEngine(), _payload())


def _huge_log(n_middle=5000):
    """A log whose startup facts and the prompt sit in the MIDDLE, where a
    head-and-tail cap would drop them, so only extraction inside the handler
    can still report them."""
    head = [f"head {i}" for i in range(sweep_handler.LOG_HEAD_LINES)]
    middle = [f"request {i}" for i in range(n_middle)]
    middle[n_middle // 2 : n_middle // 2] = [
        NON_DEFAULT_LINE, KV_LINE, f"INFO request prompt={sweep_handler.A1_PROMPT!r}",
    ]
    tail = [f"tail {i}" for i in range(sweep_handler.LOG_TAIL_LINES)]
    return head + middle + tail


def test_a_huge_log_is_returned_as_its_head_and_tail_with_the_true_count():
    log = _huge_log()
    out = _run(FakeEngine(log_lines=log), _payload())
    head, tail = sweep_handler.LOG_HEAD_LINES, sweep_handler.LOG_TAIL_LINES
    assert out["log_truncated"] is True
    assert out["log_lines_total"] == len(log)
    assert out["log_head_lines"] == head
    assert out["log_lines"] == log[:head] + log[-tail:]
    assert len(json.dumps(out)) < 200_000, "the cap must bound the job output"


def test_facts_from_the_dropped_middle_of_the_log_are_still_extracted():
    out = _run(FakeEngine(log_lines=_huge_log()), _payload(diagnostics=True))
    assert not any("max_num_seqs" in line for line in out["log_lines"])
    assert out["engine"]["max_num_seqs"] == 256
    assert out["engine"]["kv_capacity_tokens"] == 35792
    assert out["diagnostics"]["prompt_in_log"] is True


def test_a_log_that_fits_is_returned_whole_and_not_flagged():
    engine = FakeEngine()
    out = _run(engine, _payload())
    assert out["log_lines"] == engine.servers[0].log_lines
    assert out["log_truncated"] is False
    assert out["log_lines_total"] == len(out["log_lines"])


def test_a_log_of_exactly_head_plus_tail_lines_is_not_truncated():
    n = sweep_handler.LOG_HEAD_LINES + sweep_handler.LOG_TAIL_LINES
    log = [f"line {i}" for i in range(n)]
    out = _run(FakeEngine(log_lines=log), _payload())
    assert out["log_lines"] == log
    assert out["log_truncated"] is False


def test_an_unhealthy_engines_huge_log_is_capped_the_same_way():
    log = _huge_log()
    out = _run(FakeEngine(healthy=False, log_lines=log), _payload(diagnostics=True))
    assert out["healthy"] is False
    assert out["log_truncated"] is True
    assert out["log_lines_total"] == len(log)
    assert out["log_lines"][-1] == log[-1] and out["log_lines"][0] == log[0]
    assert out["diagnostics"]["prompt_in_log"] is True


def test_one_enormous_log_line_cannot_defeat_the_line_cap():
    log = ["start", "x" * 5_000_000, "end"]
    out = _run(FakeEngine(log_lines=log), _payload())
    assert len(out["log_lines"]) == 3
    assert all(len(line) <= sweep_handler.LOG_LINE_CHARS + 100 for line in out["log_lines"])
    assert len(json.dumps(out)) < 200_000
