"""Every phase of the paid path, on the stub and through a fake SDK.

The fake SDK stands where `openai.OpenAI()` would: an object whose
`responses.create(**body)` returns something with `.model_dump()`. It proves the
non-stub path builds the real client, meters spend, and refuses to start
without an approval that covers its own estimate plus the guard's headroom."""

import json
from types import SimpleNamespace

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall.formulation import CELLS
from toolcall.guard import SDK_MAX_RETRIES, SpendCapReached, call_bound_usd
from toolcall.providers import ModelSettings
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.responses import openai_call
from toolcall.runner import PHASES, estimate_call_usd, run_phase, stored_spend_usd

LIB = library()
SCS = scenarios(synthetic_suite(60, 6))
STEP2 = {"included": tuple(s.id for s in SCS), "reps": 5, "recovery_reps": 5, "slice_reps": 5,
         "approved_usd": 50.0}
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
BODY = {"input": "x" * 400}
WORST = 1 + SDK_MAX_RETRIES


def _quiet(_msg):
    pass


def test_every_phase_runs_on_the_stub_in_order(tmp_path):
    prereg = example_prereg(**STEP2, iterations=100)
    for phase in PHASES:
        out = run_phase(phase, prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
        assert out["stores"], phase
    campaign = JsonlStore(tmp_path / "campaign.jsonl", CallRecord).read_all()
    assert len(campaign) == 8 * len(SCS) * 5
    rec = JsonlStore(tmp_path / "recovery.jsonl", RecoveryRecord).read_all()
    assert {r.fmt for r in rec} == {"actionable", "opaque"}
    explo = JsonlStore(tmp_path / "exploratory.jsonl", CallRecord).read_all()
    assert all(t["strict"] for t in explo[0].request["tools"])
    assert (tmp_path / "slice-claude-sonnet-5-5.jsonl").exists()


def test_campaign_phases_refuse_to_start_before_step_two(tmp_path):
    with pytest.raises(ValueError, match="step 2"):
        run_phase("campaign", example_prereg(), LIB, SCS, tmp_path, stub=True, say=_quiet)


def test_phases_after_the_campaign_need_its_records(tmp_path):
    with pytest.raises(ValueError, match="needs the campaign"):
        run_phase("slice", example_prereg(**STEP2), LIB, SCS, tmp_path, stub=True, say=_quiet)


class FakeSDK:
    def __init__(self):
        self.bodies = []
        self.responses = SimpleNamespace(create=self._create)

    def _response(self, body):
        return openai_call(body["tools"][0]["name"], {}, model=body["model"])

    def _create(self, **body):
        self.bodies.append(body)
        resp = self._response(body)
        return SimpleNamespace(model_dump=lambda **kw: resp)


class FlakySDK(FakeSDK):
    """Every 5th call raises a transport error, every 7th returns no usage."""

    def _create(self, **body):
        n = len(self.bodies) + 1
        if n % 5 == 0:
            self.bodies.append(body)
            raise ConnectionError("reset")
        return super()._create(**body)

    def _response(self, body):
        resp = super()._response(body)
        if len(self.bodies) % 7 == 0:
            del resp["usage"]
        return resp


def test_a_paid_phase_needs_an_approval_covering_its_estimate(tmp_path):
    prereg = example_prereg()
    with pytest.raises(SpendCapReached, match="finite positive"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, sdk=FakeSDK(), say=_quiet)
    with pytest.raises(SpendCapReached, match="exceeds"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=0.0001,
                  sdk=FakeSDK(), say=_quiet)


def test_a_paid_phase_runs_through_the_sdk_and_meters_what_it_spends(tmp_path):
    sdk = FakeSDK()
    said = []
    out = run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                    sdk=sdk, say=said.append)
    assert len(sdk.bodies) == len(SCS) * 10 == out["calls_planned"]
    assert 0 < out["spent_usd"] <= 20.0
    assert said[0].startswith(f"pilot-baseline on gpt-5.4-mini-2026-03-17: {len(SCS) * 10:,} calls")
    assert "guard headroom" in said[0]


def test_an_approval_equal_to_the_estimate_is_refused_for_want_of_guard_headroom(tmp_path):
    prereg = example_prereg()
    dry = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "dry", stub=True, say=_quiet)
    est, headroom = dry["estimate_usd"], dry["headroom_usd"]
    assert headroom > 0
    with pytest.raises(SpendCapReached, match="exceeds"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "at-estimate",
                  approved_usd=est, sdk=FakeSDK(), say=_quiet)
    sdk = FakeSDK()
    out = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "paid",
                    approved_usd=est + headroom, sdk=sdk, say=_quiet)
    assert len(sdk.bodies) == out["calls_planned"] == len(SCS) * 10
    assert out["headroom_usd"] == pytest.approx(headroom) and out["spent_usd"] < est + headroom


def test_the_headroom_is_the_dearest_first_turn_bound_times_the_retries_and_doubles_for_recovery(
        tmp_path):
    prereg = example_prereg()
    base = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    rec = run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    from toolcall.formulation import BASELINE, render
    from toolcall.providers import Client

    client = Client(prereg.primary)

    def bound(s):
        body = client.request(render(s, LIB, BASELINE), [{"role": "user", "text": s.user_message}])
        return call_bound_usd(prereg.primary, body) * WORST

    assert base["headroom_usd"] == pytest.approx(max(bound(s) for s in SCS))
    first5 = [s for s in sorted(SCS, key=lambda s: s.id) if s.recovery][:5]
    assert rec["headroom_usd"] == pytest.approx(2 * max(bound(s) for s in first5))


def test_the_estimate_grows_with_what_is_sent_and_with_thinking():
    prereg = example_prereg()
    small = estimate_call_usd(prereg.primary, [], "hi")
    big = estimate_call_usd(prereg.primary, [{"description": "x" * 4000}], "hi")
    sonnet = estimate_call_usd(prereg.slice_models[1], [{"description": "x" * 4000}], "hi")
    assert small < big < sonnet


# --- stored spend and resuming ----------------------------------------------------


def _call_record(**kw):
    values = {"run_index": 0, "block_index": 0, "condition": "c|s", "run_id": "r",
              "phase": "p", "model": MINI.model, "returned_model": None, "cell": "c",
              "scenario_id": "s", "settings": MINI.to_dict(), "request": BODY,
              "response": None, "error": None, "clock_A": {}, "grade": {}, "usage": None,
              "cost_usd": None, "rendered_tools": []}
    values.update(kw)
    return CallRecord(**values)


def _recovery_record(turns, cost):
    return RecoveryRecord(
        run_index=0, block_index=0, condition="c|s|opaque", run_id="r", phase="recovery",
        model=MINI.model, cell="c", scenario_id="s", error_kind="k", fmt="opaque",
        settings=MINI.to_dict(), turns=turns, first_grade=None, injected=True, recovered=False,
        turns_to_recovery=None, identical_retry=None, gave_up=False, hallucinated_success=False,
        budget_exhausted=False, excluded=None, cost_usd=cost)


def test_stored_spend_charges_metered_unmetered_and_failed_records_as_the_guard_did():
    bound = call_bound_usd(MINI, BODY)
    metered = _call_record(response={"ok": 1}, usage={"input": 1}, cost_usd=0.01)
    unmetered = _call_record(response={"ok": 1}, unmetered=True)
    failed = _call_record(error="ConnectionError: reset")
    assert stored_spend_usd([metered, unmetered, failed], MINI) == pytest.approx(
        0.01 + bound + bound * WORST)
    assert stored_spend_usd([], MINI) == 0.0


def test_a_failed_call_record_without_its_request_cannot_be_priced():
    with pytest.raises(ValueError, match="request"):
        stored_spend_usd([_call_record(error="boom", request=None)], MINI)


def test_stored_spend_charges_a_recovery_conversation_turn_by_turn():
    bound = call_bound_usd(MINI, BODY)
    metered = {"input": 10, "output": 5}
    zeros = {"input": 0, "output": 0}
    turns = [
        {"request": BODY, "response": {}, "parsed": {"usage": metered}},
        {"request": BODY, "response": {}, "parsed": {"usage": zeros}},
        {"request": BODY, "response": {}, "error": "unparseable response: KeyError: 'x'"},
        {"request": BODY, "error": "ConnectionError: reset"},
    ]
    assert stored_spend_usd([_recovery_record(turns, 0.02)], MINI) == pytest.approx(
        0.02 + bound + bound + bound * WORST)


@pytest.mark.parametrize("phase", ["pilot-baseline", "pilot-recovery"])
def test_stored_spend_reproduces_what_the_guard_charged_on_a_flaky_run(tmp_path, phase):
    prereg = example_prereg()
    out = run_phase(phase, prereg, LIB, SCS, tmp_path, approved_usd=20.0, sdk=FlakySDK(),
                    say=_quiet)
    store_cls = RecoveryRecord if phase == "pilot-recovery" else CallRecord
    records = JsonlStore(tmp_path / f"{phase}.jsonl", store_cls).read_all()
    assert any(getattr(r, "unmetered", False) or getattr(r, "unmetered_turns", 0)
               for r in records)
    assert stored_spend_usd(records, prereg.primary) == pytest.approx(out["spent_usd"])


def _truncate(path, keep):
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:keep]) + "\n")
    return lines


def test_a_resumed_paid_phase_continues_under_the_same_approval(tmp_path):
    prereg = example_prereg()
    first = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                      sdk=FakeSDK(), say=_quiet)
    store = tmp_path / "pilot-baseline.jsonl"
    lines = _truncate(store, 100)
    seed = sum(json.loads(x)["cost_usd"] for x in lines[:100])
    sdk, said = FakeSDK(), []
    out = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                    sdk=sdk, say=said.append)
    assert len(sdk.bodies) == first["calls_planned"] - 100
    assert out["spent_usd"] == pytest.approx(first["spent_usd"] - seed)
    assert "already spent" in said[0] and f"${seed:.2f}" in said[0]
    assert len(store.read_text().splitlines()) == first["calls_planned"]


def test_a_resumed_paid_phase_whose_stored_spend_is_near_the_approval_stops_early(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, sdk=FakeSDK(),
              say=_quiet)
    store = tmp_path / "pilot-baseline.jsonl"
    lines = _truncate(store, 100)
    first = json.loads(lines[0])
    first["cost_usd"] = 20.0 - 1e-6  # what the earlier session spent, near the approval
    store.write_text("\n".join([json.dumps(first, sort_keys=True), *lines[1:100]]) + "\n")
    sdk = FakeSDK()
    with pytest.raises(SpendCapReached, match="stopping"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                  sdk=sdk, say=_quiet)
    assert sdk.bodies == []
    assert len(store.read_text().splitlines()) == 100


def test_step_two_is_computed_from_the_pilot(tmp_path):
    from toolcall.selection import step2_proposal

    prereg = example_prereg()
    for phase in ("pilot-baseline", "pilot-cells", "pilot-slice", "pilot-recovery"):
        run_phase(phase, prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    pilot = {
        "baseline": JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all(),
        "cells": JsonlStore(tmp_path / "pilot-cells.jsonl", CallRecord).read_all(),
        "recovery": JsonlStore(tmp_path / "pilot-recovery.jsonl", RecoveryRecord).read_all(),
        "slice": {m.model: JsonlStore(tmp_path / f"pilot-slice-{m.model}.jsonl",
                                      CallRecord).read_all() for m in prereg.slice_models},
    }
    p = step2_proposal(pilot, SCS, prereg)
    assert p["candidates"] == len(SCS)
    assert 0 < len(p["included"]) < len(SCS)
    assert prereg.n_floor <= p["reps"] <= prereg.n_cap
    assert set(p["usd_per_call_by_cell"]) == {c.name for c in CELLS}
    assert p["usd_per_call_by_cell"]["high-rich-strict"] > p["usd_per_call_by_cell"][
        "low-terse-loose"]
    assert p["estimate_usd"] > 0 and "**total" in p["budget_table"]
