from collections import Counter

import pytest

from harness.store import JsonlStore
from tests.a3_examples import library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.formulation import CELLS, parse_cell
from toolcall.guard import (
    GuardedClient,
    SpendCapReached,
    SpendGuard,
    bound_held,
    call_bound_usd,
    check_estimate,
)
from toolcall.prices import cost_usd
from toolcall.providers import ModelSettings, ScriptedClient, openai_parse
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.responses import openai_call, openai_text
from toolcall.stub import StubModel

MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
LIB = library()
SCS = scenarios(synthetic_suite(6, 2))


def _stub_client():
    return ScriptedClient(MINI, StubModel(LIB, SCS, seed=1))


def test_each_block_is_every_condition_once_in_a_shuffled_order():
    sched = campaign.schedule(CELLS, SCS, reps=3, seed=4)
    assert len(sched) == 3 * 8 * len(SCS)
    for b in range(3):
        block = [s.condition for s in sched if s.block_index == b]
        assert sorted(block) == sorted(campaign.condition(c, s.id) for c in CELLS for s in SCS)
    firsts = [[s.condition for s in sched if s.block_index == b][:5] for b in range(3)]
    assert firsts[0] != firsts[1]


def test_a_campaign_stores_one_graded_record_per_scheduled_call(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    client = _stub_client()
    campaign.single_turn(campaign.schedule(CELLS, SCS, 2, 1), client, SCS, LIB, store,
                         phase="campaign")
    records = store.read_all()
    assert len(records) == 2 * 8 * len(SCS)
    r = records[0]
    assert r.request == client.sent[0]
    assert r.grade["category"] and r.cost_usd > 0 and r.returned_model == r.model
    assert r.rendered_tools == [t["name"] for t in r.request["tools"]]


def test_a_returned_model_that_differs_from_the_pin_fails_the_record(tmp_path):
    other = ScriptedClient(MINI, lambda body: openai_text("hi", model="gpt-5.4-mini"))
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1), other, SCS, LIB, store,
                         phase="campaign")
    r = store.read_all()[0]
    assert r.grade["category"] == "API_ERROR" and "model mismatch" in r.error


def test_a_provider_exception_is_a_recorded_api_error_with_the_request_kept(tmp_path):
    def fail(body):
        raise ConnectionError("reset by peer")

    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1),
                         ScriptedClient(MINI, fail), SCS, LIB, store, phase="campaign")
    r = store.read_all()[0]
    assert r.grade["category"] == "API_ERROR" and r.request is not None and r.usage is None


def test_resume_skips_done_runs_and_refuses_a_drifted_schedule(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 2, 1)
    campaign.single_turn(sched[:10], _stub_client(), SCS, LIB, store, phase="campaign")
    campaign.single_turn(sched, _stub_client(), SCS, LIB, store, phase="campaign", resume=True)
    assert sorted(r.run_index for r in store.read_all()) == list(range(len(sched)))
    with pytest.raises(ValueError, match="resume"):
        campaign.single_turn(campaign.schedule(CELLS, SCS, 2, 99), _stub_client(), SCS, LIB,
                             store, phase="campaign", resume=True)


def test_the_spend_guard_stops_the_campaign_and_keeps_what_ran(tmp_path):
    first = cost_usd(MINI.model, openai_parse(openai_call("x", {})).usage)
    guard = SpendGuard(approved_usd=first * 30)
    client = GuardedClient(_stub_client(), guard, openai_parse)
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 2, 1)
    with pytest.raises(SpendCapReached):
        campaign.single_turn(sched, client, SCS, LIB, store, phase="campaign")
    assert 0 < len(store.read_all()) == guard.calls < len(sched)
    assert guard.spent <= guard.approved


def test_check_estimate_needs_an_approval_that_covers_it():
    with pytest.raises(SpendCapReached, match="finite positive"):
        check_estimate(1.0, 0.0)
    with pytest.raises(SpendCapReached, match="exceeds"):
        check_estimate(2.0, 1.0)
    check_estimate(1.0, 1.0)


def test_an_unreadable_response_is_a_recorded_api_error_and_the_campaign_goes_on(tmp_path):
    def unreadable(body):
        return {**openai_text("x"), "output": [{"type": "function_call"}]}

    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS[:1], SCS[:2], 1, 1)
    campaign.single_turn(sched, ScriptedClient(MINI, unreadable), SCS, LIB, store,
                         phase="campaign")
    records = store.read_all()
    assert len(records) == len(sched) == 2
    for r in records:
        assert r.grade["category"] == "API_ERROR"
        assert r.error.startswith("unparseable response: KeyError")
        assert r.response is not None and r.request is not None
        assert r.returned_model is None and r.usage is None


def test_recovery_runs_store_every_turn(tmp_path):
    rec = [s for s in SCS if s.recovery]
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    cells = [parse_cell("low-terse-loose")]
    campaign.recovery_runs(campaign.schedule(cells, rec, 2, 3, formats=["actionable", "opaque"]),
                           _stub_client(), rec, LIB, store)
    records = store.read_all()
    assert Counter(r.fmt for r in records) == {"actionable": 2 * len(rec),
                                               "opaque": 2 * len(rec)}
    assert all(r.turns and r.cost_usd > 0 for r in records)


def test_cost_comes_from_usage_and_the_pinned_price():
    usage = {"input": 2000, "cached": 1000, "cache_write": 0, "output": 100, "reasoning": 0}
    assert cost_usd("gpt-5.4-mini-2026-03-17", usage) == pytest.approx(
        (1000 * 0.75 + 1000 * 0.075 + 100 * 4.5) / 1e6)
    with pytest.raises(KeyError, match="no pinned price"):
        cost_usd("gpt-9", usage)


def test_the_per_call_bound_is_never_below_what_a_call_costs(tmp_path):
    client = _stub_client()
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, SCS, 1, 1), client, SCS, LIB, store,
                         phase="campaign")
    for r in store.read_all():
        assert bound_held(MINI, r.request, r.usage)
        assert call_bound_usd(MINI, r.request) >= r.cost_usd
