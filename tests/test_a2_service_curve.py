"""Artifact 2's adapter from the sweep's tuples to a `ServiceCurve`."""

import copy
import json
import sys
from pathlib import Path

import pytest
import requests
from sweep_fakes import FakeEngine, model_latency

from harness.submit import PayloadStubSubmitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

import a2_service_curve as a2
import run_service_sweep as rss
import sweep_handler


def _row(concurrency, latency, tps, util, run_ids):
    """A level row as `CurveReduction.to_dict` writes it: value plus min..max per field."""
    return {
        "concurrency": concurrency,
        "n_runs": len(run_ids),
        "n_failed": 0,
        "run_ids": run_ids,
        "latency_s": latency,
        "latency_s_range": [latency - 0.02, latency + 0.03],
        "throughput_tps": tps,
        "throughput_tps_range": [tps - 1.0, tps + 2.0],
        "gpu_util": util,
        "gpu_util_range": [util - 0.01, min(1.0, util + 0.005)],
        "ttft_median_s": 0.05,
        "ttft_median_s_range": [0.04, 0.06],
    }


def _doc(source="runpod", max_num_seqs=(256,), top=64):
    return {
        "source": source,
        "points": [[1, 0.31, 51.6, 0.15], [top, 0.95, 1077.9, 0.99]],
        "levels": [
            _row(1, 0.31, 51.6, 0.15, ["r1a", "r1b", "r1c"]),
            _row(top, 0.95, 1077.9, 0.99, [f"r{top}a", f"r{top}b", f"r{top}c"]),
        ],
        "statistic": "per run: ...",
        "prompt_path": "exact",
        "served_cmd": ["vllm", "serve", "m", "--port", "8000", "--max-num-seqs", "256"],
        "engine": {"max_num_seqs": list(max_num_seqs), "max_num_seqs_source": ["non-default-args"]},
    }


def _runs(doc, request_throughput):
    """Stored sweep runs for `doc`, as JSONL dicts; `request_throughput` maps level -> value
    (a list gives one value per run, None omits the scalar)."""
    out = []
    for row in doc["levels"]:
        value = request_throughput.get(row["concurrency"])
        values = value if isinstance(value, list) else [value] * len(row["run_ids"])
        for run_id, v in zip(row["run_ids"], values, strict=True):
            scalars = {"duration": 9.0} if v is None else {"duration": 9.0, "request_throughput": v}
            out.append({"run_id": run_id, "level": row["concurrency"], "outcome": "ok",
                        "summary": {"bench_scalars": scalars}})
    return out


def test_a_measured_sweep_becomes_a_measured_curve_with_its_cap_recorded():
    curve, meta = a2.build_service_curve(_doc())
    assert curve.measured is True
    assert curve.points == ((1, 0.31, 51.6, 0.15), (64, 0.95, 1077.9, 0.99))
    assert meta["max_num_seqs"] == 256
    assert meta["max_num_seqs_source"] == "non-default-args"
    assert meta["top_level_above_max_num_seqs"] is False


def test_a_top_level_above_the_engines_limit_is_flagged():
    _, meta = a2.build_service_curve(_doc(top=512))
    assert meta["top_level_above_max_num_seqs"] is True


def test_a_stub_sweep_converts_but_is_never_measured():
    curve, meta = a2.build_service_curve(_doc(source="stub"))
    assert curve.measured is False
    assert meta["measured"] is False


@pytest.mark.parametrize("source", [None, "", "RunPod", "local"])
def test_only_the_exact_source_runpod_is_measured(source):
    doc = _doc()
    if source is None:
        del doc["source"]
    else:
        doc["source"] = source
    curve, meta = a2.build_service_curve(doc)
    assert curve.measured is False
    assert meta["measured"] is False


@pytest.mark.parametrize("values", [(), (None,), (256, 512)])
def test_max_num_seqs_must_be_exactly_one_recorded_value(values):
    with pytest.raises(ValueError, match="max_num_seqs"):
        a2.build_service_curve(_doc(max_num_seqs=values))


def test_a_curve_with_no_engine_block_is_refused():
    doc = _doc()
    del doc["engine"]
    with pytest.raises(ValueError, match="max_num_seqs"):
        a2.build_service_curve(doc)


def test_service_curve_validation_still_applies():
    doc = _doc()
    doc["points"][1][3] = 1.2
    with pytest.raises(ValueError, match="outside"):
        a2.build_service_curve(doc)


def test_the_per_level_intervals_are_carried_through_beside_the_points():
    doc = _doc()
    _, meta = a2.build_service_curve(doc)
    assert [i["concurrency"] for i in meta["intervals"]] == [1, 64]
    low = meta["intervals"][0]
    assert low["latency_s_range"] == [0.31 - 0.02, 0.31 + 0.03]
    assert low["throughput_tps_range"] == [51.6 - 1.0, 51.6 + 2.0]
    assert low["gpu_util_range"] == doc["levels"][0]["gpu_util_range"]
    assert low["ttft_median_s_range"] == [0.04, 0.06]
    assert meta["intervals"][1]["latency_s_range"] == doc["levels"][1]["latency_s_range"]


def test_a_level_without_an_interval_is_refused():
    doc = _doc()
    del doc["levels"][1]["latency_s_range"]
    with pytest.raises(ValueError, match="latency_s_range"):
        a2.build_service_curve(doc)


def test_an_interval_that_excludes_its_own_point_is_refused():
    doc = _doc()
    doc["levels"][0]["latency_s_range"] = [0.5, 0.6]
    with pytest.raises(ValueError, match="outside its own"):
        a2.build_service_curve(doc)


def test_levels_that_do_not_line_up_with_the_points_are_refused():
    doc = _doc()
    doc["levels"][1]["concurrency"] = 32
    with pytest.raises(ValueError, match="level rows"):
        a2.build_service_curve(doc)


def test_littles_law_ratio_is_computed_and_reported_per_level():
    doc = _doc()
    # c/latency: 1/0.31 = 3.2258, 64/0.95 = 67.368. Bench measured 3.0 and 80.0 req/s.
    runs = _runs(doc, {1: 3.0, 64: [79.0, 80.0, 81.0]})
    _, meta = a2.build_service_curve(doc, runs=runs)
    low, high = meta["littles_law"]
    assert low["concurrency"] == 1
    assert low["c_over_latency"] == pytest.approx(1 / 0.31)
    assert low["request_throughput"] == pytest.approx(3.0)
    assert low["ratio"] == pytest.approx((1 / 0.31) / 3.0)
    assert high["request_throughput"] == pytest.approx(80.0)  # median of the three runs
    assert high["ratio"] == pytest.approx((64 / 0.95) / 80.0)
    assert high["ratio"] < 1 < low["ratio"]


def test_littles_law_ratio_reads_a_level_row_that_carries_the_throughput():
    doc = _doc()
    doc["levels"][0]["request_throughput"] = 3.1
    _, meta = a2.build_service_curve(doc)
    assert meta["littles_law"][0]["request_throughput"] == pytest.approx(3.1)
    assert meta["littles_law"][0]["ratio"] == pytest.approx((1 / 0.31) / 3.1)
    assert meta["littles_law"][1]["ratio"] is None


def test_littles_law_is_unavailable_not_invented_when_the_throughput_is_missing():
    doc = _doc()
    _, meta = a2.build_service_curve(doc)  # no runs, no row value
    for row in meta["littles_law"]:
        assert row["request_throughput"] is None
        assert row["ratio"] is None
        assert "request_throughput" in row["unavailable"]
    # Present at one level only: the other stays unavailable, nothing is borrowed.
    _, meta = a2.build_service_curve(doc, runs=_runs(doc, {1: 3.0, 64: None}))
    assert meta["littles_law"][0]["ratio"] is not None
    assert meta["littles_law"][1]["ratio"] is None


def test_a_level_with_one_run_missing_the_scalar_is_unavailable_not_averaged_over_the_rest():
    doc = _doc()
    runs = _runs(doc, {1: [3.0, None, 3.2], 64: 80.0})
    _, meta = a2.build_service_curve(doc, runs=runs)
    assert meta["littles_law"][0]["ratio"] is None
    assert meta["littles_law"][1]["ratio"] is not None


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_nonsense_request_throughput_is_unavailable_not_a_ratio(bad):
    doc = _doc()
    _, meta = a2.build_service_curve(doc, runs=_runs(doc, {1: bad, 64: 80.0}))
    assert meta["littles_law"][0]["ratio"] is None
    assert meta["littles_law"][1]["ratio"] is not None


def test_a_skewed_latency_distribution_is_not_a_refusal():
    # Disclosure, not a gate: a ratio far from 1 still builds the curve.
    doc = _doc()
    curve, meta = a2.build_service_curve(doc, runs=_runs(doc, {1: 0.1, 64: 500.0}))
    assert curve.measured is True
    assert meta["littles_law"][0]["ratio"] > 10
    assert meta["littles_law"][1]["ratio"] < 0.2


def test_the_inputs_are_not_mutated():
    doc = _doc()
    before = copy.deepcopy(doc)
    a2.build_service_curve(doc, runs=_runs(doc, {1: 3.0, 64: 80.0}))
    assert doc == before


def test_the_written_file_loads_back_as_the_same_curve(tmp_path):
    (tmp_path / "sweep.json").write_text(json.dumps(_doc()))
    a2.main(["--curve", str(tmp_path / "sweep.json"), "--out", str(tmp_path / "a2.json")])
    curve = a2.load_service_curve(tmp_path / "a2.json")
    assert curve == a2.build_service_curve(_doc())[0]


def test_main_prints_and_writes_the_ratio_from_the_store(tmp_path, capsys):
    doc = _doc()
    (tmp_path / "sweep.json").write_text(json.dumps(doc))
    store = tmp_path / "store.jsonl"
    store.write_text("".join(json.dumps(r) + "\n" for r in _runs(doc, {1: 3.0, 64: 80.0})))
    a2.main(["--curve", str(tmp_path / "sweep.json"), "--store", str(store),
             "--out", str(tmp_path / "a2.json")])
    out = capsys.readouterr().out
    assert "c=1 " in out and "ratio=1.08" in out  # (1/0.31)/3.0
    written = json.loads((tmp_path / "a2.json").read_text())
    assert written["littles_law"][1]["ratio"] == pytest.approx((64 / 0.95) / 80.0)
    assert written["intervals"][0]["latency_s_range"] == doc["levels"][0]["latency_s_range"]


def test_main_says_unavailable_when_there_is_no_throughput_to_compare(tmp_path, capsys):
    (tmp_path / "sweep.json").write_text(json.dumps(_doc()))
    a2.main(["--curve", str(tmp_path / "sweep.json"), "--out", str(tmp_path / "a2.json")])
    assert "ratio=unavailable" in capsys.readouterr().out


def test_end_to_end_from_the_stub_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "post", None)
    monkeypatch.setenv("MODEL_ID", "Qwen/Qwen3-8B")
    monkeypatch.delenv("MODEL_REVISION", raising=False)
    monkeypatch.delenv("MAX_MODEL_LEN", raising=False)
    engine = FakeEngine()
    submit = PayloadStubSubmitter(
        lambda p: sweep_handler.handler({"input": p}, deps=engine.deps(sweep_handler.Deps))
    ).submit_payload
    doc = rss.run_sweep(
        submit_payload=submit, store_path=tmp_path / "s.jsonl", out_path=tmp_path / "c.json",
        levels=[1, 4, 16], seed=7, source="stub", serve_args=["--max-num-seqs", "256"],
    )
    curve, meta = a2.build_service_curve(doc)
    assert curve.measured is False
    assert curve.latency_at(4) == pytest.approx(model_latency(4, 1))
    assert meta["max_num_seqs"] == 256
    # The real reduction's rows carry real intervals: three repeats differ by 0.002 s each.
    assert meta["intervals"][1]["latency_s_range"] == pytest.approx(
        [model_latency(4, 0), model_latency(4, 2)]
    )
    # The fake bench writes no request_throughput, so the store cannot answer: unavailable.
    runs = [json.loads(line) for line in (tmp_path / "s.jsonl").read_text().splitlines()]
    _, meta = a2.build_service_curve(doc, runs=runs)
    assert all(row["ratio"] is None for row in meta["littles_law"])
