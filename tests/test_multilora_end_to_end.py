"""The whole GPU-free path: schedule -> stub worker -> harness loop -> store ->
analysis. The stub's timing model has known costs, so the analysis must
recover them. Nothing here is data."""

import pytest

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.estimands import instance_rows, point_at
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint, StubModel
from tests.conftest import example_prereg

A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


def _collect(tmp_path, prereg, model, name):
    store = JsonlStore(tmp_path / f"{name}.jsonl", InstanceRecord)
    schedule = gate_schedule(prereg) if name == "gate" else campaign_schedule(prereg)
    run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(model, seed=1).run), store, prereg)
    return store.read_all()


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    prereg = example_prereg(knee_threshold=0.08)
    tmp = tmp_path_factory.mktemp("a5")
    records = _collect(tmp, prereg, StubModel(), "campaign")
    gate = _collect(tmp, prereg, StubModel(), "gate")
    return prereg, records, analyse(records, gate, prereg, a4=A4, iterations=300)


def test_every_scheduled_instance_is_stored(result):
    prereg, records, _ = result
    assert len(records) == 11 * prereg.instances_per_condition


def test_the_gate_passes_when_synthetic_and_real_are_the_same_model(result):
    assert result[2]["gate"]["verdict"] == "pass"


def test_heterogeneity_costs_throughput_and_grows_with_slots(result):
    sweep = result[2]["sweep"]
    costs = [point_at(sweep, n)["heterogeneity"]["throughput_tps"]["point"] for n in (2, 8, 64)]
    assert costs[0] < 0 and costs[0] > costs[1] > costs[2]


def test_the_recovered_heterogeneity_cost_matches_the_model_at_the_top(result):
    point = point_at(result[2]["sweep"], 64)
    conc = point["median"]["concentrated"]["throughput_tps"]
    expected = conc * ((1 - 0.05 * 6) * (1 - 0.01) - 1)
    assert point["heterogeneity"]["throughput_tps"]["point"] == pytest.approx(expected, rel=0.05)


def test_the_slot_overhead_diagnostic_recovers_most_of_the_slot_cost(result):
    by_n = {o["n_slots"]: o for o in result[2]["sweep"]["slot_overhead"]}
    overhead = by_n[64]["throughput_tps"]["point"]
    base = StubModel().base_tps
    assert overhead == pytest.approx(-base * 0.06 * 0.8, rel=0.25)


def test_memory_shrinks_with_slots_but_does_not_bind_at_this_shape(result):
    sweep = result[2]["sweep"]
    assert point_at(sweep, 64)["memory"]["kv_tokens"] < point_at(sweep, 1)["memory"]["kv_tokens"]
    assert point_at(sweep, 64)["memory"]["max_concurrency_request_shape"] > 64


def test_tenants_and_the_cost_table_are_produced(result):
    out = result[2]
    assert out["tenants"]["feasible"]
    assert out["tenants"]["tenants"] <= out["knee"]["slots_below_knee"]
    assert [r["strategy"] for r in out["cost_table"]] == ["dedicated", "swapped", "adapter"]


def test_failures_and_cold_compiles_are_counted_not_dropped(tmp_path):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    records = _collect(tmp_path, prereg, StubModel(fail_every=10, cold_compile_every=7), "campaign")
    parts = instance_rows(records, prereg)
    n = len(records)
    assert len(parts.failed) == n // 10
    assert len(parts.discarded) > 0
    assert all(r["exclusion_reason"] == "missing_compile_warm" for r in parts.discarded)
    assert len(parts.publishable) + len(parts.discarded) + len(parts.failed) == n



def test_the_analysis_is_json_with_string_keys_only(result):
    """data/a5/analysis.json is what the post and figures read. An integer key
    would silently become a string on the round trip and break every lookup."""
    import json

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert isinstance(key, str), f"non-string key {key!r}"
                walk(value)
        elif isinstance(obj, list | tuple):
            for value in obj:
                walk(value)

    walk(result[2])
    json.dumps(result[2])


def test_publishable_counts_flag_a_condition_below_the_floor(tmp_path):
    from multilora.estimands import publishable_counts

    prereg = example_prereg(include_diagnostic=False, include_control=False)
    records = _collect(tmp_path, prereg, StubModel(fail_every=3), "campaign")
    counts = publishable_counts(records, prereg)
    assert set(counts) == {f"sweep-N{n}" for n in prereg.sweep}
    assert all(c["failed"] > 0 for c in counts.values())
    assert any(not c["meets_floor"] for c in counts.values())
