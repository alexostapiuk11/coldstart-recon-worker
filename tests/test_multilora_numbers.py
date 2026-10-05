import pytest

from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse, gate_verdict
from multilora.campaign import priming_payloads, priming_verdict, run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.numbers import END, START, block_in, numbers_block, replace_block
from multilora.records import InstanceRecord, build_record
from multilora.stub import StubInstanceEndpoint, StubModel
from tests.conftest import example_prereg

A4 = {"gpu_hourly_rate": 1.0, "n_models": 20, "reference": {"regime": "low", "s": 1.1},
      "rows": [{"regime": "low", "s": 1.1, "dedicated_cost_per_tenant_month": 730.0,
                "swapped_cost_per_tenant_month": 120.0, "sleep_mode_cost_per_tenant_month": None}]}


@pytest.fixture(scope="module")
def stores(tmp_path_factory):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    tmp = tmp_path_factory.mktemp("n")
    out = {}
    for name, schedule in (("campaign", campaign_schedule(prereg)), ("gate", gate_schedule(prereg))):
        store = JsonlStore(tmp / f"{name}.jsonl", InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=4).run), store, prereg)
        out[name] = store.read_all()
    return prereg, out


def test_the_block_is_regenerated_identically(stores):
    prereg, s = stores
    analysis = analyse(s["campaign"], s["gate"], prereg, a4=A4, iterations=200)
    block = numbers_block(analysis)
    assert block.startswith(START) and block.endswith(END)
    assert "| Equivalence gate | pass, n = 24 instances |" in block
    assert "| Cost per tenant per month, adapter |" in block and "an upper bound" in block
    post = f"# Title\n\n{START}\nstale\n{END}\n\nText."
    updated = replace_block(post, block)
    assert block_in(updated) == block
    assert updated.endswith("\n\nText.")


def test_the_gate_verdict_alone_matches_the_full_analysis(stores):
    prereg, s = stores
    alone = gate_verdict(s["gate"], prereg, iterations=200)
    full = analyse(s["campaign"], s["gate"], prereg, iterations=200)["gate"]
    assert alone == full


def test_priming_starts_each_point_twice_with_no_timed_phases(prereg):
    pairs = priming_payloads(prereg)
    assert len(pairs) == 2 * len(prereg.sweep)
    assert all(p["phases"] == [] for _, p in pairs)
    assert [s.block_index for s, _ in pairs[:2]] == [0, 1]


def test_priming_passes_only_when_every_second_start_is_warm(prereg):
    def records(model):
        endpoint = StubInstanceEndpoint(model, seed=1)
        sub = PayloadStubSubmitter(endpoint.run)
        return [build_record(s, p["run_id"], sub.submit_payload(p)) for s, p in priming_payloads(prereg)]

    good = priming_verdict(records(StubModel()))
    assert all(v["ok"] for v in good.values())
    bad = priming_verdict(records(StubModel(cold_compile_every=2)))
    assert not all(v["ok"] for v in bad.values())


def test_a_gate_with_too_few_instances_is_insufficient_not_a_crash(stores):
    prereg, s = stores
    res = gate_verdict(s["gate"][:10], prereg, iterations=200)
    assert res["verdict"] == "insufficient" and res["n"] == 10
    assert gate_verdict([], prereg)["verdict"] == "insufficient"
