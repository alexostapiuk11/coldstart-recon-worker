"""The sweep end to end with no network: the local driver, the harness
campaign loop and store, the payload stub submitter, the real sweep handler,
and a fake engine whose timing model the curve must recover."""

import json
import sys
from pathlib import Path

import pytest
import requests
from sweep_fakes import KV_LINE, NON_DEFAULT_LINE, FakeEngine, model_latency, model_util

from harness.runpod.preflight import PreflightError
from harness.service_sweep import SweepRun, reduce_curve
from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_service_sweep as rss
import sweep_handler

LEVELS = [1, 2, 4, 8]
FAKE_KEY = "fake-key-not-a-real-credential"


@pytest.fixture(autouse=True)
def no_network_and_an_endpoint_env(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the stub sweep touched the network")

    monkeypatch.setattr(requests, "get", refuse)
    monkeypatch.setattr(requests, "post", refuse)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.setenv("MODEL_REVISION", "b968826d9c46dd6066d109eabc6255188de91218")
    monkeypatch.setenv("MAX_MODEL_LEN", "8192")


def _submitter(engine, payloads=None):
    def worker(payload):
        if payloads is not None:
            payloads.append(payload)
        return sweep_handler.handler({"input": payload}, deps=engine.deps(sweep_handler.Deps))

    return PayloadStubSubmitter(worker).submit_payload


def _sweep(tmp_path, engine, **kw):
    args = {
        "submit_payload": _submitter(engine),
        "store_path": tmp_path / "sweep.jsonl",
        "out_path": tmp_path / "curve.json",
        "levels": LEVELS,
        "seed": 20261004,
        "source": "stub",
        "serve_args": ["--max-num-seqs", "256"],
    }
    args.update(kw)
    return rss.run_sweep(**args)


def _rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "sweep.jsonl").read_text().splitlines()]


def test_the_curve_recovers_the_timing_model_with_three_interleaved_repeats(tmp_path):
    payloads = []
    engine = FakeEngine()
    doc = _sweep(tmp_path, engine, submit_payload=_submitter(engine, payloads))
    assert [p[0] for p in doc["points"]] == LEVELS
    for (c, latency, tps, util), row in zip(doc["points"], doc["levels"], strict=True):
        assert latency == pytest.approx(model_latency(c, repeat=1)), "median of three repeats"
        assert row["latency_s_range"] == pytest.approx(
            [model_latency(c, 0), model_latency(c, 2)]
        )
        assert tps == pytest.approx(16 * c / model_latency(c, 1))
        assert util == pytest.approx(model_util(c))
        assert row["n_runs"] == 3
    assert doc["source"] == "stub"
    assert doc["prompt_path"] == "exact"
    assert doc["engine"]["max_num_seqs"] == [256]
    assert len(payloads) == 3 * len(LEVELS)
    assert [p["num_prompts"] for p in payloads if p["level"] == 8] == [160] * 3
    on_disk = json.loads((tmp_path / "curve.json").read_text())
    assert on_disk["points"] == doc["points"]


def test_the_curve_file_holds_exactly_what_the_reducer_returns(tmp_path):
    """The file is what artifact 2 reads. Compared against the reducer run
    independently on the stored runs, so a script that rounded, re-ordered or
    re-derived a number on its way to disk fails here even where the timing
    model's own numbers would still agree."""
    _sweep(tmp_path, FakeEngine())
    stored = JsonlStore(tmp_path / "sweep.jsonl", SweepRun).read_all()
    reduction = reduce_curve(stored, min_repeats=3, expected_levels=LEVELS)
    on_disk = json.loads((tmp_path / "curve.json").read_text())
    assert on_disk["points"] == [list(p) for p in reduction.points]
    assert on_disk["levels"] == [dict(row) for row in reduction.levels]
    for row in on_disk["levels"]:
        assert row["latency_s_range"][0] <= row["latency_s"] <= row["latency_s_range"][1]
        assert row["latency_s_range"][0] < row["latency_s_range"][1], "the interval is real"
    assert on_disk["prompt_path"] == reduction.prompt_path
    assert on_disk["served_cmd"] == list(reduction.served_cmd)


def test_every_run_is_stored_in_schedule_order(tmp_path):
    _sweep(tmp_path, FakeEngine())
    rows = _rows(tmp_path)
    assert [r["run_index"] for r in rows] == list(range(12))
    assert all(r["outcome"] == "ok" for r in rows)
    levels_in_order = [r["level"] for r in rows]
    assert levels_in_order != sorted(levels_in_order), "repeats were not interleaved"


def test_the_store_is_a_harness_jsonl_store_of_sweep_runs(tmp_path):
    """The file must round-trip through `harness.store.JsonlStore` with
    `SweepRun` as its record class -- the append-only discipline and the
    truncated-line diagnostic live there, and a second hand-rolled writer
    would lose both."""
    _sweep(tmp_path, FakeEngine())
    records = JsonlStore(tmp_path / "sweep.jsonl", SweepRun).read_all()
    assert len(records) == 12
    assert all(isinstance(r, SweepRun) for r in records)
    assert [r.to_dict() for r in records] == _rows(tmp_path)
    (tmp_path / "sweep.jsonl").write_text('{"run_id": "cut mid-write')
    with pytest.raises(ValueError, match="not valid JSON"):
        JsonlStore(tmp_path / "sweep.jsonl", SweepRun).read_all()


def test_the_driver_opens_its_store_through_the_harness_with_the_sweep_record_class(
    monkeypatch, tmp_path
):
    """Both the campaign's writes and the reducer's reads go through
    `harness.store.JsonlStore(path, SweepRun)`. Spied on rather than inferred
    from the file's bytes, because a hand-rolled writer can produce the same
    bytes and still lose the truncated-line diagnostic and the append-only
    rule."""
    opened = []

    class Spy(JsonlStore):
        def __init__(self, path, record_cls):
            opened.append((Path(path), record_cls))
            super().__init__(path, record_cls)

    monkeypatch.setattr(rss, "JsonlStore", Spy)
    _sweep(tmp_path, FakeEngine(), levels=[1, 8], repeats=1, min_repeats=1)
    assert opened, "the driver never opened a harness store"
    assert {record_cls for _, record_cls in opened} == {SweepRun}
    assert {path for path, _ in opened} == {tmp_path / "sweep.jsonl"}
    assert len(opened) >= 2, "campaign writes and reducer reads should each open one"


def test_reducing_a_store_with_a_line_cut_mid_write_names_the_line_and_writes_no_curve(tmp_path):
    _sweep(tmp_path, FakeEngine(), levels=[1, 8], repeats=1, min_repeats=1)
    with (tmp_path / "sweep.jsonl").open("a") as f:
        f.write('{"run_id": "cut mid-wri')
    out = tmp_path / "again.json"
    with pytest.raises(ValueError, match=r"line 3 is not valid JSON"):
        rss.main(["--reduce-only", "--store", str(tmp_path / "sweep.jsonl"), "--out", str(out)])
    assert not out.exists()


def test_the_stored_engine_log_is_the_handlers_head_and_tail_not_the_whole_log(tmp_path):
    """The handler now caps `log_lines` at a head and a tail. The store keeps
    what the handler returns, so a long engine log costs bounded space per
    run, and the engine facts read from the full log before the cap still
    reach the curve."""
    log = [f"INFO engine line {i}" for i in range(2000)]
    # The facts the reducer reads come from the full log, so put them in the
    # middle, where the head/tail cut drops them from `log_lines`.
    log[1000], log[1001] = NON_DEFAULT_LINE, KV_LINE
    engine = FakeEngine(log_lines=log)
    doc = _sweep(tmp_path, engine, levels=[1, 8], repeats=1, min_repeats=1)
    for row in _rows(tmp_path):
        kept = row["engine"]["log_lines"]
        assert len(kept) == sweep_handler.LOG_HEAD_LINES + sweep_handler.LOG_TAIL_LINES
        assert kept[0] == "INFO engine line 0"
        assert kept[-1] == "INFO engine line 1999"
        assert NON_DEFAULT_LINE not in kept, "the middle was cut"
    assert doc["engine"]["max_num_seqs"] == [256], "read from the full log, before the cut"


def test_an_interrupted_campaign_resumes_where_it_stopped(tmp_path):
    engine = FakeEngine()
    calls = []
    real = _submitter(engine)

    def flaky(payload):
        calls.append(payload["run_index"])
        if payload["run_index"] == 5 and calls.count(5) == 1:
            raise KeyboardInterrupt
        return real(payload)

    with pytest.raises(KeyboardInterrupt):
        _sweep(tmp_path, engine, submit_payload=flaky)
    doc = _sweep(tmp_path, engine, submit_payload=flaky, resume=True)
    assert calls == list(range(12))[:6] + list(range(5, 12))
    assert len(doc["points"]) == len(LEVELS)


@pytest.mark.parametrize(
    ("drift", "match"),
    [
        ({"seed": 7}, "different schedule parameters"),
        ({"levels": [1, 2, 4, 16]}, "different schedule parameters"),
        ({"repeats": 2}, "beyond the rebuilt schedule|different schedule parameters"),
    ],
    ids=["seed", "levels", "repeats"],
)
def test_resume_refuses_a_schedule_that_drifted_and_submits_nothing(tmp_path, drift, match):
    """The guard that stops two interleavings being spliced into one store.
    Run a campaign to completion, then resume it with one schedule parameter
    changed: it must raise before a single new job is submitted."""
    _sweep(tmp_path, FakeEngine())
    stored_before = (tmp_path / "sweep.jsonl").read_text()
    submitted = []

    def spy(payload):
        submitted.append(payload)
        raise AssertionError("a drifted resume submitted a job")

    with pytest.raises(ValueError, match=match):
        _sweep(tmp_path, FakeEngine(), submit_payload=spy, resume=True, **drift)
    assert submitted == []
    assert (tmp_path / "sweep.jsonl").read_text() == stored_before


def test_a_failed_run_is_stored_and_its_level_refused_until_the_bar_is_lowered(tmp_path):
    engine = FakeEngine(fail_measured_at=(4, 1))
    with pytest.raises(ValueError, match="level 4 has 2 successful runs"):
        _sweep(tmp_path, engine)
    rows = _rows(tmp_path)
    assert sum(r["outcome"] == "failed" for r in rows) == 1
    doc = rss.reduce_store(tmp_path / "sweep.jsonl", tmp_path / "curve.json", min_repeats=2,
                           meta={"source": "stub", "levels_requested": LEVELS})
    row4 = next(r for r in doc["levels"] if r["concurrency"] == 4)
    assert (row4["n_runs"], row4["n_failed"]) == (2, 1)


def test_a_diagnostic_pilot_stores_the_in_container_answers(tmp_path):
    doc = _sweep(tmp_path, FakeEngine(), levels=[1, 8], repeats=1, min_repeats=1,
                 diagnostics=True)
    rows = _rows(tmp_path)
    assert all("--save-detailed" in r["diagnostics"]["bench_help"]["stdout"] for r in rows)
    assert all(r["summary"]["raw_bench"]["itls"] for r in rows)
    assert [p[0] for p in doc["points"]] == [1, 8]


def test_an_ordinary_sweep_asks_for_no_diagnostics_and_stores_none(tmp_path):
    payloads = []
    engine = FakeEngine()
    _sweep(tmp_path, engine, submit_payload=_submitter(engine, payloads),
           levels=[1, 8], repeats=1, min_repeats=1)
    assert [p["diagnostics"] for p in payloads] == [False, False]
    assert all(r["diagnostics"] == {} for r in _rows(tmp_path))
    assert all("raw_bench" not in r["summary"] for r in _rows(tmp_path))


def test_the_pin_set_lives_in_the_script_and_requires_a_template():
    pins = rss.sweep_pins("tmpl-123")
    assert pins["templateId"] == "tmpl-123"
    assert pins["executionTimeoutMs"] == rss.EXECUTION_TIMEOUT_S * 1000
    assert pins["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090"]
    assert pins["networkVolumeId"] == "9c7ut2slrd"
    assert set(pins) == {"gpuTypeIds", "networkVolumeId", "executionTimeoutMs", "templateId"}
    with pytest.raises(ValueError, match="template id is required"):
        rss.sweep_pins("")


def test_the_execution_timeout_the_endpoint_is_pinned_to_is_the_budget_the_worker_gets(tmp_path):
    payloads = []
    engine = FakeEngine()
    _sweep(tmp_path, engine, submit_payload=_submitter(engine, payloads),
           levels=[1, 2], repeats=1, min_repeats=1)
    assert {p["job_budget_s"] for p in payloads} == {rss.EXECUTION_TIMEOUT_S}
    assert rss.sweep_pins("t")["executionTimeoutMs"] == rss.EXECUTION_TIMEOUT_S * 1000


@pytest.mark.parametrize("template_args", [[], ["--template-id", ""]], ids=["absent", "empty"])
def test_a_missing_or_empty_template_id_is_refused_before_any_request(
    monkeypatch, template_args
):
    """Without a template pin the preflight would accept an endpoint running
    any image and any start command. The refusal must come before the GET."""
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    with pytest.raises(ValueError, match="template id is required"):
        rss.main(["--preflight-only", *template_args])


def test_preflight_only_makes_exactly_one_get_and_spends_nothing(monkeypatch, capsys):
    gets = []

    def one_get(url, **kwargs):
        gets.append((url, kwargs))

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return rss.sweep_pins("tmpl")

        return Response()

    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.setattr(requests, "get", one_get)
    monkeypatch.setattr(rss, "RunPodSubmitter", None)  # constructing one would TypeError
    monkeypatch.setattr(rss, "run_sweep", None)
    rss.main(["--preflight-only", "--template-id", "tmpl"])
    out = capsys.readouterr()
    assert "matches the sweep pin set" in out.out
    assert [url for url, _ in gets] == ["https://rest.runpod.io/v1/endpoints/ep"]
    assert FAKE_KEY not in out.out + out.err


def test_a_drifted_endpoint_is_refused_before_any_job(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    drifted = {**rss.sweep_pins("tmpl"), "executionTimeoutMs": 600000}
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: drifted)
    built = []
    monkeypatch.setattr(rss, "RunPodSubmitter", lambda *a, **k: built.append(a))
    with pytest.raises(PreflightError, match="executionTimeoutMs"):
        rss.main(["--template-id", "tmpl", "--levels", "1,2", "--seed", "1",
                  "--store", str(tmp_path / "s.jsonl"), "--out", str(tmp_path / "c.json")])
    assert built == [], "a submitter was built for a drifted endpoint"
    assert not (tmp_path / "s.jsonl").exists()


def test_an_endpoint_on_another_template_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: rss.sweep_pins("someone-elses"))
    with pytest.raises(PreflightError, match="templateId"):
        rss.main(["--preflight-only", "--template-id", "tmpl"])


@pytest.mark.parametrize("missing", ["RUNPOD_API_KEY", "RUNPOD_SWEEP_ENDPOINT_ID"])
def test_missing_credentials_refuse_to_start(monkeypatch, missing):
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.delenv(missing)
    with pytest.raises(SystemExit, match=missing):
        rss.main(["--preflight-only", "--template-id", "tmpl"])


@pytest.mark.parametrize("flags", [[], ["--diagnostics"]], ids=["ordinary", "diagnostics"])
def test_the_command_line_drives_the_whole_chain_and_passes_its_flags_on(
    monkeypatch, tmp_path, capsys, flags
):
    """`main` against a fake endpoint: the preflight passes, jobs go to the
    in-process worker, and `--diagnostics`, `--serve-args` and `--resume`
    reach the payloads. The curve is labelled `runpod` because that is the
    submitter `main` chose."""
    engine = FakeEngine()
    payloads = []
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: rss.sweep_pins("tmpl"))
    monkeypatch.setattr(rss, "HttpTransport", lambda ep, key: (ep, key))
    monkeypatch.setattr(
        rss, "RunPodSubmitter", lambda transport: type(
            "S", (), {"submit_payload": staticmethod(_submitter(engine, payloads))}
        )()
    )
    argv = ["--template-id", "tmpl", "--levels", "1,2", "--seed", "5", "--repeats", "2",
            "--min-repeats", "2", "--serve-args", "--max-num-seqs 256",
            "--store", str(tmp_path / "s.jsonl"), "--out", str(tmp_path / "c.json"), *flags]
    rss.main(argv)
    assert [p["diagnostics"] for p in payloads] == [bool(flags)] * 4
    assert {tuple(p["serve_args"]) for p in payloads} == {("--max-num-seqs", "256")}
    doc = json.loads((tmp_path / "c.json").read_text())
    assert doc["source"] == "runpod"
    assert [p[0] for p in doc["points"]] == [1, 2]
    out = capsys.readouterr().out
    assert "[run   3]" in out and "[done] 2 levels" in out
    assert FAKE_KEY not in out
    before = len(payloads)
    rss.main([*argv, "--resume"])
    assert len(payloads) == before, "a finished campaign resumed must submit nothing"


def test_a_paid_run_without_its_required_arguments_refuses_after_the_free_preflight(
    monkeypatch,
):
    monkeypatch.setenv("RUNPOD_API_KEY", FAKE_KEY)
    monkeypatch.setenv("RUNPOD_SWEEP_ENDPOINT_ID", "ep")
    monkeypatch.setattr(rss, "fetch_endpoint", lambda ep, key: rss.sweep_pins("tmpl"))
    with pytest.raises(SystemExit):
        rss.main(["--template-id", "tmpl", "--levels", "1,2"])


def test_reduce_only_rebuilds_the_curve_from_a_store_with_no_credentials_or_network(
    monkeypatch, tmp_path
):
    _sweep(tmp_path, FakeEngine(), out_path=tmp_path / "first.json")
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("RUNPOD_SWEEP_ENDPOINT_ID", raising=False)
    rss.main(["--reduce-only", "--levels", "1,2,4,8", "--store", str(tmp_path / "sweep.jsonl"),
              "--out", str(tmp_path / "again.json")])
    first = json.loads((tmp_path / "first.json").read_text())
    again = json.loads((tmp_path / "again.json").read_text())
    assert again["points"] == first["points"]
    assert again["levels"] == first["levels"]
