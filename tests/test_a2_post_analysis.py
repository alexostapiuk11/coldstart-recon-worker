"""data/a2/post-analysis.json is what the script computes from committed data, byte for byte."""

import gzip
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
A = REPO / "data" / "a2" / "post-analysis.json"


def _analysis() -> dict:
    return json.loads(A.read_text())


def _script():
    """The analysis script as a module (it is a script, not a package member)."""
    spec = importlib.util.spec_from_file_location(
        "a2_post_analysis", REPO / "scripts" / "a2_post_analysis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_raw_worker_ids() -> set[str]:
    """Every raw RunPod worker id the probe evidence names, found in the data and
    not typed in: the steps' x-a2-worker headers, each summary's warmup.worker_share
    keys, its per-step worker_share keys and its `workers` list."""
    ids: set[str] = set()
    for probe in sorted((REPO / "data" / "a2" / "lb-probes").iterdir()):
        for step in probe.glob("step-*.jsonl.gz"):
            with gzip.open(step, "rt") as fh:
                for line in fh:
                    w = (json.loads(line).get("headers") or {}).get("x-a2-worker")
                    if w:
                        ids.add(w)
        summary = json.loads((probe / "summary.json").read_text())
        ids.update(summary.get("workers") or ())
        ids.update((summary.get("warmup") or {}).get("worker_share") or ())
        for step in summary["steps"].values():
            ids.update(step.get("worker_share") or ())
    return ids


def test_a_fresh_run_reproduces_the_committed_analysis(tmp_path):
    out = tmp_path / "a.json"
    subprocess.run([sys.executable, str(REPO / "scripts" / "a2_post_analysis.py"), "--out",
                    str(out)], check=True, cwd=REPO, env={"PYTHONDONTWRITEBYTECODE": "1",
                                                          "PATH": "/usr/bin:/bin"})
    assert out.read_bytes() == A.read_bytes()


def test_the_analysis_has_every_section_the_post_cites():
    a = _analysis()
    assert set(a) >= {"validation", "load_balancer", "host_speed", "simulator", "spend"}
    assert a["validation"]["engine"]["outcome"] == "failed"
    assert a["validation"]["calibrated"]["outcome"] == "failed"
    assert set(a["simulator"]["h3"]) == {"0.88", "1", "1.12"}
    assert a["spend"] is None
    assert "UNVALIDATED" in a["_provenance"]["label"]


def test_the_headline_gaps_are_the_committed_sweeps():
    g = _analysis()["simulator"]["gaps"]["1"]
    got = {tag: round(g[tag]["point"], 4) for tag in g}
    assert got == {"arm A": 0.0821, "arm C": 3.9550, "ramp arm A": 8.2488,
                   "ramp arm C": 10.8734}


def test_both_attempts_miss_as_their_verdicts_say():
    v = _analysis()["validation"]
    assert (v["engine"]["misses"], v["engine"]["compared"]) == (34, 37)
    assert (v["calibrated"]["misses"], v["calibrated"]["compared"]) == (37, 37)
    assert v["engine"]["void_repeats"] == 1 and v["calibrated"]["void_repeats"] == 0
    # The residual's sign is the finding: attempt 1 predicted too slow (real < predicted),
    # attempt 2 too fast (real > predicted).
    assert v["engine"]["typical_residual"]["median_ratio_real_over_predicted"] < 1
    assert v["calibrated"]["typical_residual"]["median_ratio_real_over_predicted"] > 1


def test_probe_1_delivered_about_17_per_second_whatever_was_offered():
    steps = _analysis()["load_balancer"]["probes"]["1"]["steps"]
    for rate in ("25", "50"):
        assert 16 < steps[rate]["delivered_rate_rps"] < 18, rate


def test_no_raw_runpod_worker_id_is_published_for_the_probes():
    a = _analysis()
    for probe in a["load_balancer"]["probes"].values():
        for step in probe["steps"].values():
            labels = set(step["worker_share"]) | set(step.get("per_worker_concurrency") or {})
            assert all(w.startswith("worker ") for w in labels), labels
    raw_ids = _all_raw_worker_ids()
    assert len(raw_ids) >= 4, "the guard found too few ids to be checking anything"
    text = A.read_text()
    leaked = sum(1 for raw in raw_ids if raw in text)
    assert leaked == 0, f"{leaked} raw worker id(s) appear in post-analysis.json (ids not printed)"


def test_the_signed_hypotheses_come_out_as_computed():
    s = _analysis()["simulator"]
    assert s["h1"]["overall"] is False
    assert s["h2"]["per_sweep"] == {"arm A": True, "arm C": False, "ramp arm A": False,
                                    "ramp arm C": False}
    assert s["h2"]["overall"] is False
    assert s["h4"] == {"arm A": False, "arm C": False, "overall": False}
    assert all(s["h3"][f]["holds"] is False for f in ("0.88", "1", "1.12"))


def test_spend_is_null_beside_a_reason():
    a = _analysis()
    assert a["spend"] is None
    assert "Task 13" in a["spend_why"]


def test_the_default_output_path_does_not_depend_on_the_working_directory():
    mod = _script()
    assert mod.OUT == REPO / "data" / "a2" / "post-analysis.json"


def test_probe_1_records_the_errors_at_100_per_second():
    steps = _analysis()["load_balancer"]["probes"]["1"]["steps"]
    assert steps["100"]["errors"] == 449
    assert steps["25"]["errors"] == 0 and steps["50"]["errors"] == 0


def test_the_502_source_names_the_probes_the_data_has_them_on():
    lb = _analysis()["load_balancer"]["lb_502_first_attempt_s"]
    assert sorted(lb["probes"]) == ["3", "4", "5"]
    assert "probes 3, 4, 5" in lb["source"]


def test_the_censoring_reading_is_backed_by_the_numbers_beside_it():
    c = _analysis()["simulator"]["h2_censoring"]
    assert (c["curve_gpu_util_min_over_measured_levels"]
            > c["highest_utilization_scale_up_threshold"])
    assert f"{c['highest_utilization_scale_up_threshold']:g}" in c["reading"]
    assert "above the highest utilisation scale-up threshold" in c["reading"]


def test_the_censoring_reading_is_refused_when_the_curve_is_not_above_the_thresholds():
    mod = _script()
    with pytest.raises(SystemExit, match="utilisation controller"):
        mod._censoring_reading(min_util=0.9, highest_threshold=0.95, all_at_cap=True)
    assert "above the highest" in mod._censoring_reading(
        min_util=1.0, highest_threshold=0.95, all_at_cap=True)


def test_a_single_element_is_named_when_it_is_not_single():
    mod = _script()
    assert mod._only(["h"], "host ids of a repeat", "the calibration would be filed "
                     "under the wrong host") == "h"
    with pytest.raises(SystemExit, match="filed under the wrong host"):
        mod._only(["a", "b"], "host ids of a repeat", "the calibration would be filed "
                  "under the wrong host")


def test_sweeps_seed_their_traces_by_threshold_not_by_signal():
    """The reason at-cap utilisation policies, which run one fleet, differ in p99."""
    from autoscale import sweep
    params = list(inspect.signature(sweep._derive_seed).parameters)
    assert params == ["seed", "up", "down", "rep"]
    assert sweep._derive_seed(1, 0.65, 0.15, 0) != sweep._derive_seed(1, 0.70, 0.15, 0)


def test_h2_noise_is_recorded_per_sweep_from_the_at_cap_policies():
    n = _analysis()["simulator"]["h2_noise"]
    assert set(n["per_sweep"]) == {"arm A", "arm C", "ramp arm A", "ramp arm C"}
    assert "_derive_seed" in n["_note"]
    for tag, s in n["per_sweep"].items():
        spread = s["at_cap_policy_p99_s"]
        assert spread["count"] >= 2, tag
        assert spread["min"] <= spread["median"] <= spread["max"], tag
    a = n["per_sweep"]["arm A"]
    # utilisation 14.526 against in-flight 14.483 and queue depth 14.444
    assert a["h2_margin_s"] == pytest.approx(0.0429, abs=5e-4)
    assert a["margin_vs_best_other_s"] == pytest.approx(0.0821, abs=5e-4)
    assert a["margin_inside_at_cap_spread"] is True


def test_the_h2_margin_is_utilisation_minus_the_closest_other_signal_signed():
    sims = _analysis()["simulator"]
    for tag, s in sims["h2_noise"]["per_sweep"].items():
        reached = {k: v["p99_s"] for k, v in sims["sweeps"][tag]["reached"].items()}
        others = [v for k, v in reached.items() if k != "utilization"]
        assert s["h2_margin_s"] == pytest.approx(reached["utilization"] - max(others))
        assert s["margin_vs_best_other_s"] == pytest.approx(reached["utilization"] - min(others))
        # H2 holds exactly when that margin clears the one-millisecond tie
        assert (s["h2_margin_s"] > s["tie_seconds"]) == sims["h2"]["per_sweep"][tag]


def test_the_iso_cost_slice_is_computed_not_assumed_to_leave_the_others_unconstrained():
    n = _analysis()["simulator"]["h2_noise"]["per_sweep"]
    for tag, s in n.items():
        assert isinstance(s["iso_cost_slice_constrains_others"], bool), tag
        assert s["others_highest_frontier_cost_replica_s"] is not None


def test_the_arms_measured_cold_starts_are_recorded_and_arm_a_is_slower_than_arm_c():
    cs = _analysis()["simulator"]["cold_start"]
    assert set(cs) == {"A", "C"}
    for arm, s in cs.items():
        assert s["n"] > 0, arm
        assert s["p10"] <= s["median"] <= s["p90"], arm
    assert cs["A"]["median"] > cs["C"]["median"]
    assert "data/campaign.jsonl" in _analysis()["_provenance"]["inputs"]


def test_the_money_section_prices_the_default_cap_at_the_committed_rate():
    a = _analysis()
    m = a["money"]
    rate = json.loads((REPO / "data" / "a2" / "gpu-rate.json").read_text())
    assert m["gpu_hourly_rate"] == rate["gpu_hourly_rate"] == 0.74
    assert m["gpu_rate_provenance"] == "measured"
    assert m["spikes_per_day"] == 24.0 and m["spikes_per_day_provenance"] == "illustrative"
    assert "billing" in m["gpu_rate_caveat"]
    cap = m["load_balancer_cap"]
    probes = a["load_balancer"]["probes"]
    assert cap["workers"] == probes["1"]["workers"] == probes["3"]["workers"] == 2
    assert cap["scaler_4"]["delivered_rate_rps"] == pytest.approx(17.1, abs=0.05)
    assert cap["scaler_128"]["delivered_rate_rps"] == probes["3"]["steps"]["300"][
        "delivered_rate_rps"]
    assert cap["scaler_4"]["dollars_per_million"] == round(2 * 0.74 / (
        cap["scaler_4"]["delivered_rate_rps"] * 3600) * 1e6, 2)
    assert cap["scaler_4"]["dollars_per_million"] > 10 * cap["scaler_128"]["dollars_per_million"]
    assert cap["ratio"] == pytest.approx(cap["scaler_128"]["delivered_rate_rps"]
                                         / cap["scaler_4"]["delivered_rate_rps"])


def test_the_money_section_prices_the_signals_on_arm_a_and_labels_them_unvalidated():
    a = _analysis()
    sig = a["money"]["signal_choice"]
    reached = a["simulator"]["sweeps"]["arm A"]["reached"]
    assert sig["sweep"] == "arm A"
    assert {s: v["replica_seconds"] for s, v in sig["per_signal"].items()} == {
        s: v["cost_replica_s"] for s, v in reached.items()}
    p99s = [v["p99_s"] for v in reached.values()]
    spread_ms = round((max(p99s) - min(p99s)) * 1000)
    assert sig["p99_spread_s"] == max(p99s) - min(p99s)
    assert sig["label"] == ("UNVALIDATED: simulator failed validation twice; "
                            f"p99s differ by {spread_ms} ms")
    assert sig["per_signal"]["queue_depth"]["dollars_per_spike"] == 0.18
    assert sig["per_signal"]["utilization"]["dollars_per_day"] == pytest.approx(15.27, abs=0.01)


def test_the_rate_file_is_a_listed_input_and_the_endpoint_id_is_not_republished():
    a = _analysis()
    assert "data/a2/gpu-rate.json" in a["_provenance"]["inputs"]
    assert "un0lhqt51q1bvp" not in A.read_text()
