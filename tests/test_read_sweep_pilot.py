"""scripts/read_sweep_pilot.py against a stub pilot store: the pilot is written by
the real driver (`run_sweep`) and the real handler over the shared fakes, so the
reader is checked against the record shape the code actually stores, not against
a hand-built dict that could drift from it."""

import json
import sys
from pathlib import Path

import pytest
import requests
from sweep_fakes import FakeEngine

from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

import read_sweep_pilot as reader
import run_service_sweep as rss
import sweep_handler


@pytest.fixture(autouse=True)
def an_offline_container_environment(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the stub pilot touched the network")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.setenv("MODEL_REVISION", "b968826d9c46dd6066d109eabc6255188de91218")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")


def _pilot(tmp_path, engine=None, **kw):
    engine = engine or FakeEngine()

    def worker(payload):
        return sweep_handler.handler({"input": payload}, deps=engine.deps(sweep_handler.Deps))

    args = {
        "submit_payload": PayloadStubSubmitter(worker).submit_payload,
        "store_path": tmp_path / "pilot.jsonl",
        "out_path": tmp_path / "curve.json",
        "levels": [1, 8],
        "repeats": 1,
        "min_repeats": 1,
        "seed": 20261004,
        "source": "stub",
        "serve_args": ["--max-num-seqs", "256"],
        "diagnostics": True,
    }
    args.update(kw)
    rss.run_sweep(**args)
    return tmp_path / "pilot.jsonl"


def test_each_run_gets_a_block_that_answers_the_checklists_questions(tmp_path, capsys):
    reader.main([str(_pilot(tmp_path))])
    out = capsys.readouterr().out
    assert out.count("--- run ") == 2
    assert " c=1 ok" in out and " c=8 ok" in out
    # serve command pins and the engine's own non-default-args line
    assert "serve cmd pins: {'--max-num-seqs': True, '--no-enable-prefix-caching': True}" in out
    assert "engine: {'max_num_seqs': 256, 'max_num_seqs_source': 'non-default-args'" in out
    # the fake's help text lists two flags only, so every other one is reported missing
    assert "bench --help missing flags: [" in out
    assert "'--max-concurrency'" not in out.split("bench --help missing flags:")[1].split("\n")[0]
    # the reconstruction agrees with the tool's median, and the GPU figure was windowed
    assert "(gap +0.00 ms)" in out
    assert "windowed: True" in out
    assert "samples in span 1 outside 0" in out
    # the fakes' saved JSON has no request_throughput and their engine log's
    # non-default-args line does not mention prefix caching: the reader must say so
    assert "saved JSON missing keys: ['request_throughput']" in out
    assert "non-default args line has prefix caching off: False" in out
    assert "requests: completed" in out and "failed 0" in out
    assert "clock_A submit-to-result" in out


def test_each_run_prints_the_measured_startup_teardown_and_whether_the_log_drained(tmp_path, capsys):
    reader.main([str(_pilot(tmp_path))])
    out = capsys.readouterr().out
    timing = [line for line in out.splitlines() if line.startswith("  timing:")]
    assert len(timing) == 2
    assert all("teardown 1.5 s" in line and "log drained: True" in line for line in timing)
    assert all("startup " in line and "startup None" not in line for line in timing)


def test_a_log_that_did_not_drain_is_said_so_with_its_error(tmp_path, capsys):
    engine = FakeEngine(drain_completed=False, drain_error=OSError("pipe"))
    reader.main([str(_pilot(tmp_path, engine))])
    assert "log drained: False (OSError('pipe'))" in capsys.readouterr().out


def test_a_failed_run_still_prints_its_timing(tmp_path, capsys):
    with pytest.raises(ValueError, match="no successful run"):
        _pilot(tmp_path, FakeEngine(healthy=False))
    reader.main([str(tmp_path / "pilot.jsonl")])
    assert "  timing: startup" in capsys.readouterr().out


def test_a_run_without_diagnostics_has_no_saved_json_and_the_reader_says_absent(
    tmp_path, capsys
):
    reader.main([str(_pilot(tmp_path, diagnostics=False))])
    out = capsys.readouterr().out
    assert out.count("--- run ") == 2
    assert "saved JSON missing keys: absent" in out
    assert "--diagnostics" in out.split("saved JSON missing keys:")[1].split("\n")[0]


def test_a_summary_without_the_tools_median_prints_absent_not_a_traceback(tmp_path, capsys):
    store = _pilot(tmp_path)
    rows = [json.loads(line) for line in store.read_text().splitlines()]
    for row in rows:
        del row["summary"]["bench_median_e2el_s"]
    store.write_text("".join(json.dumps(r) + "\n" for r in rows))
    reader.main([str(store)])
    out = capsys.readouterr().out
    assert "tool median_e2el absent" in out
    assert "gap" not in out.split("tool median_e2el absent")[1].split("\n")[0]


def test_a_failed_run_prints_its_detail_and_the_engine_facts_and_no_summary(tmp_path, capsys):
    # The reduction at the end of the pilot refuses (a level has no successful run),
    # after the store is written; the store is what the reader reads.
    with pytest.raises(ValueError, match="level 1 has 0 successful runs"):
        _pilot(tmp_path, FakeEngine(fail_measured_at=(1, 0)))
    reader.main([str(tmp_path / "pilot.jsonl")])
    out = capsys.readouterr().out
    block = out.split("--- run ")[1:]
    failed = [b for b in block if " failed " in b.splitlines()[0]]
    assert len(failed) == 1
    assert "this run has no result" in failed[0]
    assert "engine: {" in failed[0]
    assert "latency " not in failed[0], "a failed run has no summary to read"


def test_a_missing_or_empty_store_is_refused_not_read_as_a_pass(tmp_path):
    with pytest.raises(SystemExit, match="does not exist"):
        reader.main([str(tmp_path / "nope.jsonl")])
    (tmp_path / "empty.jsonl").write_text("")
    with pytest.raises(SystemExit, match="holds no runs"):
        reader.main([str(tmp_path / "empty.jsonl")])
