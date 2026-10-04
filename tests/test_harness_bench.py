"""`run_bench` builds one `vllm bench serve` command and returns the tool's
saved JSON untouched. The subprocess is faked: vLLM is not installed locally.
The fake writes the result file where the command says the tool would."""

import inspect
import json
import subprocess
from pathlib import Path

import pytest

from harness.bench import RESULT_FILENAME, BenchError, bench_command, run_bench

URL = "http://127.0.0.1:8000"
SAVED = {
    "duration": 12.5,
    "completed": 2,
    "failed": 0,
    "ttfts": [0.1, 0.2],
    "itls": [[0.01], [0.02]],
    "output_lens": [2, 2],
    "errors": ["", ""],
    "a_key_from_a_future_version": {"nested": [1, 2]},
}


class FakeRun:
    def __init__(self, saved=None, returncode=0, stdout="", stderr="", write=True):
        self.saved = SAVED if saved is None else saved
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.write = write
        self.cmd = None
        self.kwargs = None

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        if self.write:
            out = Path(cmd[cmd.index("--result-dir") + 1])
            assert out.is_dir(), "run_bench must create result_dir before the tool runs"
            name = cmd[cmd.index("--result-filename") + 1]
            (out / name).write_text(json.dumps(self.saved))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _call(tmp_path, run, **kw):
    args = {
        "model": "Qwen/Qwen3-8B",
        "max_concurrency": 4,
        "num_prompts": 100,
        "dataset_args": ["--dataset-name", "random", "--random-input-len", "13"],
        "ignore_eos": True,
        "seed": 7,
        "result_dir": tmp_path / "does" / "not" / "exist",
        "run": run,
    }
    args.update(kw)
    return run_bench(URL, **args)


def _has(cmd, *seq):
    n = len(seq)
    return any(tuple(cmd[i : i + n]) == seq for i in range(len(cmd) - n + 1))


def test_the_signature_is_the_one_artifacts_4_and_5_code_against():
    params = inspect.signature(run_bench).parameters
    assert {
        "model", "lora_modules", "lora_assignment", "max_concurrency", "num_prompts",
        "dataset_args", "ignore_eos", "seed", "result_dir",
    } <= set(params)
    assert params["lora_modules"].default == ()
    assert params["lora_assignment"].default is None


def test_the_command_starts_with_the_engine_url_and_model(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert run.cmd[:7] == ["vllm", "bench", "serve", "--base-url", URL, "--model", "Qwen/Qwen3-8B"]
    assert _has(run.cmd, "--max-concurrency", "4")
    assert _has(run.cmd, "--num-prompts", "100")
    assert _has(run.cmd, "--seed", "7")


def test_warmups_ready_check_and_saving_are_pinned_on_every_run(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert _has(run.cmd, "--num-warmups", "0")
    assert _has(run.cmd, "--ready-check-timeout-sec", "0")
    assert "--save-result" in run.cmd
    assert "--save-detailed" in run.cmd
    assert _has(run.cmd, "--result-filename", RESULT_FILENAME)


def test_the_result_dir_is_created_and_the_saved_json_comes_back_unaltered(tmp_path):
    out = _call(tmp_path, FakeRun())
    assert out == SAVED
    assert (tmp_path / "does" / "not" / "exist" / RESULT_FILENAME).is_file()


def test_a_sweep_without_lora_sends_no_lora_flags(tmp_path):
    run = FakeRun()
    _call(tmp_path, run)
    assert "--lora-modules" not in run.cmd
    assert "--lora-assignment" not in run.cmd


def test_lora_names_and_assignment_reach_the_tool(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, lora_modules=["a00", "a01"], lora_assignment="round-robin")
    assert _has(run.cmd, "--lora-modules", "a00", "a01")
    assert _has(run.cmd, "--lora-assignment", "round-robin")


def test_an_assignment_without_adapters_is_refused(tmp_path):
    with pytest.raises(ValueError, match="base model"):
        _call(tmp_path, FakeRun(), lora_assignment="round-robin")


@pytest.mark.parametrize("ignore_eos", [True, False])
def test_ignore_eos_is_a_flag_only_when_asked_for(tmp_path, ignore_eos):
    run = FakeRun()
    _call(tmp_path, run, ignore_eos=ignore_eos)
    assert ("--ignore-eos" in run.cmd) is ignore_eos


def test_dataset_and_extra_args_pass_through_in_order(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, extra_args=["--percentile-metrics", "ttft,tpot,itl,e2el"])
    assert _has(run.cmd, "--dataset-name", "random", "--random-input-len", "13")
    assert run.cmd[-2:] == ["--percentile-metrics", "ttft,tpot,itl,e2el"]


@pytest.mark.parametrize(
    ("where", "bad"),
    [("dataset_args", ["--save-result"]), ("extra_args", ["--max-concurrency=8"])],
)
def test_a_flag_run_bench_owns_is_refused_wherever_it_appears(tmp_path, where, bad):
    with pytest.raises(ValueError, match="sets itself"):
        _call(tmp_path, FakeRun(), **{where: bad})


def test_a_failed_tool_raises_with_its_exit_code_and_last_output(tmp_path):
    run = FakeRun(returncode=1, stderr="Traceback\nValueError: no pandas", write=False)
    with pytest.raises(BenchError, match="exited 1") as e:
        _call(tmp_path, run)
    assert "no pandas" in str(e.value)


def test_a_tool_that_writes_nothing_raises(tmp_path):
    with pytest.raises(BenchError, match="wrote no"):
        _call(tmp_path, FakeRun(write=False))


def test_a_stale_result_file_is_refused(tmp_path):
    out = tmp_path / "r"
    out.mkdir()
    (out / RESULT_FILENAME).write_text("{}")
    with pytest.raises(ValueError, match="stale"):
        _call(tmp_path, FakeRun(), result_dir=out)


def test_a_timeout_raises_bench_error(tmp_path):
    def run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"], output="partial progress")

    with pytest.raises(BenchError, match="within 3 s") as e:
        _call(tmp_path, run, timeout=3)
    assert "partial progress" in str(e.value)


def test_the_subprocess_is_run_without_check_and_with_output_captured(tmp_path):
    run = FakeRun()
    _call(tmp_path, run, timeout=60)
    assert run.kwargs == {"capture_output": True, "text": True, "check": False, "timeout": 60}


@pytest.mark.parametrize(("c", "n"), [(0, 10), (4, 0)])
def test_zero_concurrency_or_prompts_is_refused(c, n, tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        bench_command(
            URL, model="m", lora_modules=(), lora_assignment=None, max_concurrency=c,
            num_prompts=n, dataset_args=[], ignore_eos=True, seed=0, result_dir=tmp_path,
        )
