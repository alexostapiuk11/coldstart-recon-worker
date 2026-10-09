import hashlib
import json
from collections import Counter

import pytest

from harness.store import JsonlStore
from tests.a3_examples import library, scenarios, synthetic_suite
from toolcall import campaign
from toolcall.formulation import CELLS, parse_cell, render
from toolcall.grader import grade
from toolcall.guard import (
    GuardedClient,
    SpendCapReached,
    SpendGuard,
    bound_held,
    call_bound_usd,
    check_estimate,
)
from toolcall.prices import cost_usd
from toolcall.providers import PARSE, ModelSettings, ScriptedClient, openai_parse, openai_request
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


def _no_usage(body):
    return {k: v for k, v in openai_text("x").items() if k != "usage"}


def _rec_setup():
    rec = [s for s in SCS if s.recovery]
    cells = [parse_cell("low-terse-loose")]
    return rec, cells


def test_a_stored_call_regrades_to_the_same_grade_from_its_stored_response(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS, SCS, 1, 2), _stub_client(), SCS, LIB, store,
                         phase="campaign")
    by_id = {s.id: s for s in SCS}
    records = store.read_all()
    assert len(records) == 8 * len(SCS)
    for r in records:
        parsed = PARSE[MINI.provider](r.response)
        again = grade(parsed, by_id[r.scenario_id], LIB, r.rendered_tools, error=r.error)
        assert again.to_dict() == r.grade


def test_the_request_hash_pins_the_bytes_that_were_sent(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    client = _stub_client()
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1), client, SCS, LIB, store,
                         phase="campaign")
    r = store.read_all()[0]
    assert r.request_sha256 == hashlib.sha256(json.dumps(client.sent[0]).encode()).hexdigest()


def test_missing_usage_is_unmetered_not_free(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1),
                         ScriptedClient(MINI, _no_usage), SCS, LIB, store, phase="campaign")
    r = store.read_all()[0]
    assert r.grade["category"] == "API_ERROR"
    assert r.unmetered and r.usage is None and r.cost_usd is None and r.response is not None
    store2 = JsonlStore(tmp_path / "d.jsonl", CallRecord)
    campaign.single_turn(campaign.schedule(CELLS[:1], SCS[:1], 1, 1), _stub_client(), SCS, LIB,
                         store2, phase="campaign")
    assert not store2.read_all()[0].unmetered


def test_recovery_missing_usage_is_counted_as_unmetered_turns(tmp_path):
    rec, cells = _rec_setup()
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    campaign.recovery_runs(campaign.schedule(cells, rec[:1], 1, 3, formats=["opaque"]),
                           ScriptedClient(MINI, _no_usage), rec, LIB, store)
    r = store.read_all()[0]
    assert r.excluded == "API_ERROR" and r.unmetered_turns == 1 and r.cost_usd == 0


def test_recovery_provider_errors_are_unmetered_turns(tmp_path):
    def fail(body):
        raise ConnectionError("reset by peer")

    rec, cells = _rec_setup()
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    campaign.recovery_runs(campaign.schedule(cells, rec[:1], 1, 3, formats=["opaque"]),
                           ScriptedClient(MINI, fail), rec, LIB, store)
    r = store.read_all()[0]
    assert r.excluded == "API_ERROR" and r.unmetered_turns == 1 and r.returned_models == []


def test_recovery_checks_the_pin_on_every_turn(tmp_path):
    rec, cells = _rec_setup()
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    other = ScriptedClient(MINI, lambda body: openai_text("hi", model="gpt-5.4-mini"))
    campaign.recovery_runs(campaign.schedule(cells, rec[:1], 1, 3, formats=["opaque"]),
                           other, rec, LIB, store)
    r = store.read_all()[0]
    assert r.excluded == "API_ERROR" and r.returned_models == ["gpt-5.4-mini"]
    assert "model mismatch" in r.turns[-1]["error"]
    assert r.unmetered_turns == 0 and r.cost_usd > 0


def test_a_recovery_record_written_before_the_new_fields_still_loads():
    loaded = RecoveryRecord.from_dict({
        **{k: None for k in ("first_grade", "turns_to_recovery", "identical_retry", "excluded")},
        "run_index": 0, "block_index": 0, "condition": "c", "run_id": "r", "phase": "recovery",
        "model": "m", "cell": "c", "scenario_id": "s", "error_kind": "e", "fmt": "opaque",
        "settings": {}, "turns": [], "injected": False, "recovered": False, "gave_up": False,
        "hallucinated_success": False, "budget_exhausted": False, "cost_usd": 0.0,
    })
    assert loaded.returned_models == [] and loaded.unmetered_turns == 0


def _always_fails(body):
    raise ConnectionError("401 bad key")


def test_a_campaign_stops_after_ten_consecutive_api_errors(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 1, 1)
    assert len(sched) > campaign.CONSECUTIVE_FAILURE_LIMIT == 10
    with pytest.raises(campaign.SystematicFailure, match="ConnectionError: 401 bad key"):
        campaign.single_turn(sched, ScriptedClient(MINI, _always_fails), SCS, LIB, store,
                             phase="campaign")
    assert len(store.read_all()) == 10


def test_a_success_resets_the_consecutive_failure_count(tmp_path):
    calls = {"n": 0}

    def flaky(body):
        calls["n"] += 1
        if calls["n"] % 10 == 0:
            return openai_text("hi")
        raise ConnectionError("reset by peer")

    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 1, 1)
    campaign.single_turn(sched, ScriptedClient(MINI, flaky), SCS, LIB, store, phase="campaign")
    assert len(store.read_all()) == len(sched)


def test_recovery_stops_after_ten_consecutive_api_errors(tmp_path):
    rec, cells = _rec_setup()
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    sched = campaign.schedule(cells, rec, 6, 3, formats=["actionable", "opaque"])
    assert len(sched) > 10
    with pytest.raises(campaign.SystematicFailure, match="401 bad key"):
        campaign.recovery_runs(sched, ScriptedClient(MINI, _always_fails), rec, LIB, store)
    assert len(store.read_all()) == 10


def test_resume_refuses_a_store_made_under_other_settings_model_or_phase(tmp_path):
    store = JsonlStore(tmp_path / "c.jsonl", CallRecord)
    sched = campaign.schedule(CELLS, SCS, 1, 1)
    campaign.single_turn(sched[:3], _stub_client(), SCS, LIB, store, phase="campaign")
    warmer = ModelSettings("openai", MINI.model, 0.7, reasoning_effort="none")
    other_model = ModelSettings("openai", "gpt-5.4-nano-2026-03-17", 0.0,
                                reasoning_effort="none")
    for settings, phase in ((warmer, "campaign"), (other_model, "campaign"), (MINI, "slice")):
        client = ScriptedClient(settings, StubModel(LIB, SCS, seed=1, model=settings.model))
        with pytest.raises(ValueError, match="resume"):
            campaign.single_turn(sched, client, SCS, LIB, store, phase=phase, resume=True)
    assert len(store.read_all()) == 3


def test_recovery_resume_refuses_a_store_made_under_other_settings(tmp_path):
    rec, cells = _rec_setup()
    store = JsonlStore(tmp_path / "r.jsonl", RecoveryRecord)
    sched = campaign.schedule(cells, rec, 1, 3, formats=["opaque"])
    campaign.recovery_runs(sched[:1], _stub_client(), rec, LIB, store)
    warmer = ModelSettings("openai", MINI.model, 0.7, reasoning_effort="none")
    with pytest.raises(ValueError, match="resume"):
        campaign.recovery_runs(sched, ScriptedClient(warmer, StubModel(LIB, SCS, seed=1)), rec,
                               LIB, store, resume=True)


@pytest.mark.parametrize("constrained", [False, True])
def test_the_stub_reads_every_cell_back_from_its_rendering(constrained):
    settings = ModelSettings("openai", MINI.model, 0.0, reasoning_effort="none",
                             constrained=constrained)
    stub = StubModel(LIB, SCS, seed=1)
    for scenario in SCS:
        for cell in CELLS:
            body = openai_request(settings, render(scenario, LIB, cell),
                                  [{"role": "user", "text": scenario.user_message}])
            assert stub._cell(body["tools"]) == cell, (scenario.id, cell.name, constrained)
