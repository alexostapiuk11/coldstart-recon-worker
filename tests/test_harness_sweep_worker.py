"""One sweep run inside the worker, with the bench and the sampler faked."""

import json

import pytest

from harness.bench import BenchError
from harness.sweep_worker import (
    E2EL_PERCENTILES,
    PROMPT_EXACT,
    PROMPT_RANDOM_FALLBACK,
    WARMUP_SEED_OFFSET,
    PromptPlan,
    choose_prompt_path,
    exact_dataset_args,
    max_num_seqs_from_log,
    random_dataset_args,
    run_one,
    run_summary,
    successful_requests,
    write_exact_prompt_dataset,
)

PROMPT = "Explain what a key-value cache does, in two sentences."
URL = "http://127.0.0.1:8000"


def raw_result(n=4, *, ttft=0.1, itl=0.02, out=16, duration=2.0, **over):
    raw = {
        "duration": duration,
        "completed": n,
        "failed": 0,
        "num_prompts": n,
        "max_concurrency": 2,
        "output_throughput": n * out / duration,
        "input_lens": [13] * n,
        "ttfts": [ttft] * n,
        "itls": [[itl] * (out - 1)] * n,
        "output_lens": [out] * n,
        "errors": [""] * n,
        "generated_texts": ["x"] * n,
        "start_times": [0.0] * n,
        "median_e2el_ms": (ttft + itl * (out - 1)) * 1000,
    }
    raw.update(over)
    return raw


class FakeBench:
    def __init__(self, results=None, fail=None):
        self.calls = []
        self.results = results or {}
        self.fail = fail or {}

    def __call__(self, base_url, **kw):
        self.calls.append(kw)
        name = kw["result_dir"].name
        if name in self.fail:
            raise BenchError(self.fail[name])
        return self.results.get(name, raw_result())


class FakeSampler:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        self.log.append("enter")
        return self

    def __exit__(self, *exc):
        self.log.append("exit")

    def summary(self):
        return {"gpu_util": 0.6, "n_samples": 3, "n_valid": 3, "interval_s": 0.5, "samples": []}


PLAN = PromptPlan(PROMPT_EXACT, ("--dataset-name", "custom"), 13)


def test_the_exact_prompt_file_is_pinned_byte_for_byte(tmp_path):
    path = write_exact_prompt_dataset(PROMPT, tmp_path)
    assert path.read_bytes() == (
        b'{"prompt": "Explain what a key-value cache does, in two sentences."}\n'
    )


def test_the_exact_prompt_flags_are_pinned():
    assert exact_dataset_args("/w/prompt.jsonl", output_len=16) == [
        "--dataset-name", "custom",
        "--dataset-path", "/w/prompt.jsonl",
        "--custom-output-len", "16",
        "--skip-chat-template",
    ]


def test_the_fallback_flags_are_pinned():
    assert random_dataset_args(input_len=13, output_len=16) == [
        "--dataset-name", "random",
        "--random-input-len", "13",
        "--random-output-len", "16",
        "--random-range-ratio", "0",
        "--random-prefix-len", "0",
    ]


def test_a_probe_the_engine_received_at_the_right_length_keeps_the_exact_path(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1)})
    counted = []

    def count_tokens(prompt):
        counted.append(prompt)
        return 13

    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=count_tokens,
    )
    assert plan.path == PROMPT_EXACT
    assert plan.prompt_tokens == 13
    assert list(plan.dataset_args) == exact_dataset_args(tmp_path / "prompt.jsonl", output_len=16)
    assert counted == [PROMPT]
    probe = bench.calls[0]
    assert (probe["num_prompts"], probe["max_concurrency"]) == (1, 1)
    # the probe sends exactly what the measured runs will send, or "exact" would
    # describe a different request from the one measured
    assert probe["dataset_args"] == list(plan.dataset_args)
    assert probe["ignore_eos"] is True
    assert probe["model"] == "m"


def test_a_failing_probe_falls_back_to_random_at_the_same_length(tmp_path):
    bench = FakeBench(fail={"prompt-probe": "exited 1: pandas is not installed"})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK
    assert list(plan.dataset_args) == random_dataset_args(input_len=13, output_len=16)
    assert "pandas" in plan.probe_error


def test_a_probe_whose_prompt_arrived_at_another_length_falls_back(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1, input_lens=[27])})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK
    assert "[27]" in plan.probe_error


def test_the_failure_rule_drops_errors_zero_ttfts_and_empty_outputs():
    raw = raw_result(5)
    raw["errors"][1] = "boom"
    raw["ttfts"] = [0.1, 0.1, 0.0, 0.1, 0.1]
    raw["output_lens"] = [16, 16, 16, 0, 16]
    raw.update(completed=2, failed=3)
    ok = successful_requests(raw)
    assert ok["n_failed"] == 3
    assert ok["e2e_s"] == pytest.approx([0.1 + 0.02 * 15] * 2)


def test_a_disagreement_with_the_tools_own_counts_is_refused():
    raw = raw_result(4)
    raw["errors"][0] = "boom"
    with pytest.raises(ValueError, match="miscounting"):
        successful_requests(raw)


def test_a_result_saved_without_detail_is_refused():
    raw = raw_result(2)
    del raw["itls"]
    with pytest.raises(ValueError, match="save-detailed"):
        successful_requests(raw)


def test_the_summary_is_compact_and_carries_the_three_curve_values():
    plan = PromptPlan(PROMPT_EXACT, ("--dataset-name", "custom"), 13)
    gpu = {"gpu_util": 0.6, "samples": [{"t_s": 0.0, "raw": "60", "util_pct": 60.0}]}
    s = run_summary(raw_result(4, ttft=0.1, itl=0.02, out=16, duration=2.0), gpu=gpu, plan=plan,
                    warmup=None)
    assert s["latency_s"] == pytest.approx(0.1 + 0.02 * 15)
    assert s["ttft_median_s"] == pytest.approx(0.1)
    assert s["throughput_tps"] == pytest.approx(4 * 16 / 2.0)
    assert s["gpu_util"] == 0.6
    assert s["prompt_path"] == PROMPT_EXACT
    assert s["bench_median_e2el_s"] == pytest.approx(s["latency_s"])
    assert s["input_lens_unique"] == [13]
    assert "ttfts" not in s and "ttfts" not in s["bench_scalars"]
    assert s["bench_scalars"]["output_throughput"] == pytest.approx(32.0)
    json.dumps(s)


def test_a_run_where_nothing_succeeded_is_refused():
    raw = raw_result(3)
    raw["ttfts"] = [0.0] * 3
    raw.update(completed=0, failed=3)
    with pytest.raises(ValueError, match="no request succeeded"):
        run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None)


def test_error_samples_are_deduplicated_and_capped_at_three():
    raw = raw_result(6)
    raw["errors"] = ["", "e1", "e1", "e2", "e3", "e4"]
    raw["ttfts"][1:] = [0.0] * 5
    raw.update(completed=1, failed=5)
    s = run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None, max_failed=5)
    assert s["error_samples"] == ["e1", "e2", "e3"]


def test_one_run_warms_up_then_measures_with_the_sampler_around_the_measurement_only(tmp_path):
    log = []
    bench = FakeBench()

    def recording_bench(base_url, **kw):
        log.append(kw["result_dir"].name)
        return bench(base_url, **kw)

    s = run_one(
        URL, model="m", level=8, num_prompts=160, warmup_prompts=8, plan=PLAN, seed=11,
        workdir=tmp_path, run_bench=recording_bench, sampler_factory=lambda: FakeSampler(log),
    )
    assert log == ["warmup", "enter", "measured", "exit"]
    warm, measured = bench.calls
    assert warm["max_concurrency"] == measured["max_concurrency"] == 8
    assert (warm["num_prompts"], measured["num_prompts"]) == (8, 160)
    assert warm["seed"] == 11 + WARMUP_SEED_OFFSET and measured["seed"] == 11
    assert measured["extra_args"] == list(E2EL_PERCENTILES)
    assert "extra_args" not in warm
    assert measured["ignore_eos"] is True
    assert s["warmup"] == {"num_prompts": 8, "completed": 4, "failed": 0}
    assert s["gpu_util"] == 0.6


def test_the_raw_bench_json_is_kept_only_when_asked_for(tmp_path):
    bench = FakeBench()
    kw = {"model": "m", "level": 2, "num_prompts": 100, "warmup_prompts": 0, "plan": PLAN,
          "seed": 1, "run_bench": bench, "sampler_factory": lambda: FakeSampler([])}
    assert "raw_bench" not in run_one(URL, workdir=tmp_path / "a", **kw)
    kept = run_one(URL, workdir=tmp_path / "b", keep_raw=True, **kw)
    assert kept["raw_bench"] == raw_result()


def test_no_warmup_when_none_is_asked_for(tmp_path):
    bench = FakeBench()
    s = run_one(
        URL, model="m", level=2, num_prompts=100, warmup_prompts=0, plan=PLAN, seed=1,
        workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
    )
    assert len(bench.calls) == 1
    assert s["warmup"] is None


def test_a_spent_budget_refuses_to_start_a_bench_run(tmp_path):
    bench = FakeBench()
    with pytest.raises(BenchError, match="budget is spent"):
        run_one(
            URL, model="m", level=2, num_prompts=100, warmup_prompts=2, plan=PLAN, seed=1,
            workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
            deadline=10.0, clock=lambda: 11.0,
        )
    assert bench.calls == []


def test_the_run_value_is_the_median_not_the_mean_or_the_max():
    # Five requests with distinct latencies and TTFTs; one outlier pulls the
    # mean and the max away from the median.
    ttfts = [0.1, 0.2, 0.3, 0.4, 5.0]
    raw = raw_result(5, itl=0.0, out=2, duration=2.0, ttfts=ttfts,
                     itls=[[0.0]] * 5, output_lens=[2] * 5, input_lens=[13] * 5)
    s = run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None)
    assert s["latency_s"] == pytest.approx(0.3)
    assert s["ttft_median_s"] == pytest.approx(0.3)


def test_throughput_counts_only_successful_output_tokens():
    # Request 1 carries an error but a non-zero output length and TTFT, so only
    # the error field marks it failed; its tokens must not reach the numerator.
    raw = raw_result(4, out=16, duration=2.0)
    raw["errors"][1] = "boom"
    raw.update(completed=3, failed=1)
    s = run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None, max_failed=1)
    assert s["throughput_tps"] == pytest.approx(3 * 16 / 2.0)


def test_a_probe_the_tool_did_not_complete_falls_back_even_if_the_length_matches(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1, completed=0, failed=1)})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK


def test_the_summary_records_the_path_that_was_actually_used():
    fallback = PromptPlan(PROMPT_RANDOM_FALLBACK, ("--dataset-name", "random"), 13, "why")
    s = run_summary(raw_result(4), gpu={"gpu_util": 0.6}, plan=fallback, warmup=None)
    assert s["prompt_path"] == PROMPT_RANDOM_FALLBACK
    assert s["prompt"]["path"] == PROMPT_RANDOM_FALLBACK
    assert s["prompt"]["probe_error"] == "why"


def test_the_warmup_never_shares_a_seed_with_the_measured_run(tmp_path):
    bench = FakeBench()
    run_one(
        URL, model="m", level=2, num_prompts=100, warmup_prompts=2, plan=PLAN, seed=11,
        workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
    )
    warm, measured = bench.calls
    assert warm["seed"] != measured["seed"]
    assert WARMUP_SEED_OFFSET != 0


NON_DEFAULT = (
    "(APIServer pid=130) INFO 08-28 23:28:00 [api_utils.py:273] non-default args: "
    "{'model_tag': 'Qwen/Qwen3-8B', 'model': 'Qwen/Qwen3-8B', 'max_model_len': 8192, "
    "'max_num_seqs': 256}"
)
DEFAULTED = "DEBUG 10-04 [arg_utils.py:2797] Defaulting max_num_seqs to 256 for openai-api-server"


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ([NON_DEFAULT], (256, "non-default-args")),
        ([DEFAULTED], (256, "debug-default")),
        ([DEFAULTED.replace("256", "128"), NON_DEFAULT], (256, "non-default-args")),
        (["INFO GPU KV cache size: 35,792 tokens"], (None, None)),
    ],
)
def test_max_num_seqs_is_read_from_the_log_and_never_assumed(lines, expected):
    assert max_num_seqs_from_log(lines) == expected


# ---------------------------------------------------------------- probe budget (I1)


def test_the_probe_is_bounded_by_what_is_left_of_the_jobs_budget(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1)})
    choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13, deadline=100.0, clock=lambda: 40.0,
    )
    assert bench.calls[0]["timeout"] == 60.0


def test_without_a_deadline_the_probe_has_no_timeout(tmp_path):
    bench = FakeBench({"prompt-probe": raw_result(1)})
    choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13,
    )
    assert bench.calls[0]["timeout"] is None


def test_a_probe_that_timed_out_falls_back_and_keeps_the_reason(tmp_path):
    bench = FakeBench(fail={"prompt-probe": "vllm bench serve did not finish within 60 s"})
    plan = choose_prompt_path(
        URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
        run_bench=bench, count_tokens=lambda p: 13, deadline=100.0, clock=lambda: 40.0,
    )
    assert plan.path == PROMPT_RANDOM_FALLBACK
    assert "did not finish within 60 s" in plan.probe_error


def test_a_spent_budget_stops_before_the_probe_instead_of_becoming_a_fallback(tmp_path):
    bench = FakeBench()
    with pytest.raises(BenchError, match="budget is spent"):
        choose_prompt_path(
            URL, model="m", prompt=PROMPT, output_len=16, workdir=tmp_path,
            run_bench=bench, count_tokens=lambda p: 13, deadline=10.0, clock=lambda: 11.0,
        )
    assert bench.calls == []


# ------------------------------------------------- the measured run's timeout (I4b)


def test_each_bench_runs_gets_what_is_left_of_the_budget_when_it_starts(tmp_path):
    bench = FakeBench()
    clock = iter([10.0, 40.0])
    run_one(
        URL, model="m", level=2, num_prompts=100, warmup_prompts=2, plan=PLAN, seed=1,
        workdir=tmp_path, run_bench=bench, sampler_factory=lambda: FakeSampler([]),
        deadline=100.0, clock=lambda: next(clock),
    )
    warm, measured = bench.calls
    assert warm["timeout"] == 90.0
    assert measured["timeout"] == 60.0


# ------------------------------------------------------ failed requests (I2, M5)


def _with_one_failure(n=5):
    raw = raw_result(n)
    raw["errors"][1] = "boom"
    raw["ttfts"][1] = 0.0
    raw.update(completed=n - 1, failed=1)
    return raw


def test_a_run_with_any_failed_request_is_an_error_not_a_summary_of_the_survivors():
    with pytest.raises(ValueError, match="1 of 5 requests failed") as e:
        run_summary(_with_one_failure(), gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None)
    assert "median of the survivors would understate" in str(e.value)


def test_a_failure_budget_lets_a_run_through_and_still_records_its_count():
    s = run_summary(
        _with_one_failure(), gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None, max_failed=1
    )
    assert (s["completed"], s["failed"]) == (4, 1)


def test_more_failures_than_the_budget_is_still_an_error():
    raw = _with_one_failure()
    raw["errors"][2], raw["ttfts"][2] = "boom", 0.0
    raw.update(completed=3, failed=2)
    with pytest.raises(ValueError, match="2 of 5 requests failed"):
        run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None, max_failed=1)


def test_the_prompt_lengths_reported_are_those_of_requests_that_succeeded():
    raw = _with_one_failure()
    raw["input_lens"][1] = 999  # a failed request: no usage chunk, the tool's own count
    s = run_summary(raw, gpu={"gpu_util": 0.1}, plan=PLAN, warmup=None, max_failed=1)
    assert s["input_lens_unique"] == [13]


# ------------------------------------------- GPU utilisation over the measured span (C1)

SAMPLER_T0 = 90.0


def _gpu_summary(samples, *, t0=SAMPLER_T0, t_exit_s=20.0):
    readable = sorted(sample["util_pct"] for sample in samples)
    return {
        "gpu_util": readable[len(readable) // 2] / 100.0,
        "t0_monotonic": t0,
        "t_exit_s": t_exit_s,
        "interval_s": 0.5,
        "samples": samples,
    }


def _idle_busy_idle():
    """Ten idle samples while the tool starts up, four busy ones while its four
    requests run, three idle ones while it writes its JSON: the whole-call median
    is idle, which is the reading this change exists to avoid."""
    def at(t, pct):
        return {"t_s": t, "query_s": 0.05, "raw": str(pct), "util_pct": float(pct)}

    return (
        [at(t, 0) for t in range(10)]
        + [at(t, 90) for t in (10.1, 10.6, 11.1, 11.6)]
        + [at(t, 0) for t in (12.5, 13.0, 13.5)]
    )


def _timed_raw(**over):
    # four requests of 0.1 + 15 * 0.02 = 0.4 s, started at 100.0 .. 101.5 on the
    # tool's clock: the span is [100.0, 101.9], i.e. 10.0 .. 11.9 s after the sampler
    return raw_result(4, start_times=[100.0, 100.5, 101.0, 101.5], **over)


def test_the_reported_utilisation_is_the_median_over_the_measured_span_not_the_whole_call():
    s = run_summary(_timed_raw(), gpu=_gpu_summary(_idle_busy_idle()), plan=PLAN, warmup=None)
    assert s["gpu_util"] == pytest.approx(0.90)
    assert s["gpu_util_windowed"] is True
    assert s["gpu_util_whole_call"] == 0.0
    assert (s["gpu_util_n_in_span"], s["gpu_util_n_outside_span"]) == (4, 13)


def test_a_failed_request_does_not_stretch_the_span():
    raw = _timed_raw()
    raw["errors"][0], raw["ttfts"][0] = "boom", 0.0
    raw["start_times"][0] = 91.0  # a failed request started long before the others
    raw.update(completed=3, failed=1)
    s = run_summary(raw, gpu=_gpu_summary(_idle_busy_idle()), plan=PLAN, warmup=None, max_failed=1)
    assert s["gpu_util"] == pytest.approx(0.90)
    assert s["gpu_util_n_in_span"] == 3


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.pop("start_times"),
        lambda raw: raw.update(start_times=[100.0, 100.5]),
        lambda raw: raw.update(start_times=[None] * 4),
    ],
    ids=["absent", "wrong length", "not numbers"],
)
def test_without_the_tools_start_times_the_whole_call_median_is_reported_as_such(mutate):
    raw = _timed_raw()
    mutate(raw)
    s = run_summary(raw, gpu=_gpu_summary(_idle_busy_idle()), plan=PLAN, warmup=None)
    assert s["gpu_util"] == 0.0
    assert s["gpu_util_whole_call"] == 0.0
    assert s["gpu_util_windowed"] is False
    assert "start_times" in s["gpu_util_window_note"]
    assert "gpu_util_n_in_span" not in s


def test_a_summary_without_an_absolute_start_is_reported_unwindowed():
    s = run_summary(_timed_raw(), gpu={"gpu_util": 0.6}, plan=PLAN, warmup=None)
    assert s["gpu_util"] == 0.6
    assert s["gpu_util_windowed"] is False
    assert "t0_monotonic" in s["gpu_util_window_note"]


def test_clocks_that_do_not_agree_are_reported_not_papered_over():
    gpu = _gpu_summary(_idle_busy_idle(), t0=5_000_000.0)
    s = run_summary(_timed_raw(), gpu=gpu, plan=PLAN, warmup=None)
    assert s["gpu_util_windowed"] is False
    assert s["gpu_util"] == s["gpu_util_whole_call"]
    assert "clock" in s["gpu_util_window_note"]


def test_a_span_holding_no_readable_sample_reports_none_not_the_idle_median():
    sparse = [{"t_s": 1.0, "query_s": 0.05, "raw": "0", "util_pct": 0.0}]
    s = run_summary(_timed_raw(), gpu=_gpu_summary(sparse), plan=PLAN, warmup=None)
    assert s["gpu_util"] is None
    assert s["gpu_util_windowed"] is True
    assert s["gpu_util_whole_call"] == 0.0


def test_one_run_hands_the_samplers_summary_to_the_windowing(tmp_path):
    bench = FakeBench({"measured": _timed_raw()})

    class TimedSampler(FakeSampler):
        def summary(self):
            return _gpu_summary(_idle_busy_idle())

    s = run_one(
        URL, model="m", level=2, num_prompts=4, warmup_prompts=0, plan=PLAN, seed=1,
        workdir=tmp_path, run_bench=bench, sampler_factory=lambda: TimedSampler([]),
    )
    assert s["gpu_util"] == pytest.approx(0.90)
    assert s["gpu"]["t0_monotonic"] == SAMPLER_T0
