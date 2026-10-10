"""Every phase of the paid path, on the stub and through fake SDKs.

A fake SDK stands where `openai.OpenAI()` or `anthropic.Anthropic()` would: an
object whose `responses.create(**body)` / `messages.create(**body)` returns
something with `.model_dump()`. It proves the non-stub path builds the real
client, meters spend, writes a durable ledger, and refuses to start without an
approval that covers its own estimate plus the guard's headroom."""

import errno
import fcntl
import json
import sys
from types import SimpleNamespace

import pytest

from harness.store import JsonlStore
from tests.a3_examples import example_prereg, library, scenarios, synthetic_suite
from toolcall import guard as guard_module
from toolcall.formulation import BASELINE, CELLS, render
from toolcall.guard import (
    INPUT_OVERHEAD_TOKENS,
    SDK_MAX_RETRIES,
    LedgerWriteError,
    SpendCapReached,
    SpendGuard,
    SpendGuardError,
    SpendLedger,
    call_bound_usd,
)
from toolcall.mock_tools import FORMATS
from toolcall.prices import cost_usd
from toolcall.providers import ModelSettings
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.recovery import TURN_BUDGET
from toolcall.responses import anthropic_call, openai_call
from toolcall.runner import (
    PHASES,
    THINKING_TOKENS_ESTIMATE,
    estimate_call_usd,
    plan_cost,
    run_phase,
    stored_spend_usd,
    tool_result_chars,
)

LIB = library()
SCS = scenarios(synthetic_suite(60, 6))
STEP2 = {"included": tuple(s.id for s in SCS), "reps": 5, "recovery_reps": 5, "slice_reps": 5,
         "approved_usd": 50.0}
MINI = ModelSettings("openai", "gpt-5.4-mini-2026-03-17", 0.0, reasoning_effort="none")
SONNET = ModelSettings("anthropic", "claude-sonnet-5-5", None, thinking="between_tools")
BODY = {"input": "x" * 400}
WORST = 1 + SDK_MAX_RETRIES
ATTEMPTS = TURN_BUDGET + 1


def _quiet(_msg):
    pass


def _ledger_path(root, phase):
    return root / f"{phase}.spend.jsonl"


def _ledger_total(root, phase):
    with SpendLedger(_ledger_path(root, phase)) as ledger:
        return ledger.total()


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
    assert (tmp_path / "STUB").exists()
    assert not list(tmp_path.glob("*.spend.jsonl"))  # a rehearsal spends nothing


def test_campaign_phases_refuse_to_start_before_step_two(tmp_path):
    with pytest.raises(ValueError, match="step 2"):
        run_phase("campaign", example_prereg(), LIB, SCS, tmp_path, stub=True, say=_quiet)


def test_phases_after_the_campaign_need_its_records(tmp_path):
    with pytest.raises(ValueError, match="needs the campaign"):
        run_phase("slice", example_prereg(**STEP2), LIB, SCS, tmp_path, stub=True, say=_quiet)


class FakeSDK:
    """An OpenAI SDK. `usage` is (input, output) tokens per call."""

    def __init__(self, usage=(1000, 40), arguments=None):
        self.bodies = []
        self.usage = usage
        self.arguments = arguments
        self.responses = SimpleNamespace(create=self._create)

    def _response(self, body):
        return openai_call(body["tools"][0]["name"], {}, model=body["model"],
                           input_tokens=self.usage[0], output_tokens=self.usage[1],
                           raw_arguments=self.arguments)

    def _create(self, **body):
        self.bodies.append(body)
        resp = self._response(body)
        return SimpleNamespace(model_dump=lambda **kw: resp)

    def priced_usd(self):
        """What this SDK's own usage figures cost, whatever the guard believes."""
        usage = {"input": self.usage[0], "cached": 0, "cache_write": 0,
                 "output": self.usage[1], "reasoning": 0}
        return len(self.bodies) * cost_usd(MINI.model, usage)


class FakeAnthropicSDK:
    def __init__(self):
        self.bodies = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **body):
        self.bodies.append(body)
        resp = anthropic_call(body["tools"][0]["name"], {}, model=body["model"])
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


class CrashSDK(FakeSDK):
    """Raises a KeyboardInterrupt on the nth call: the process dies mid-call."""

    def __init__(self, crash_on, **kw):
        super().__init__(**kw)
        self.crash_on = crash_on

    def _create(self, **body):
        if len(self.bodies) + 1 == self.crash_on:
            self.bodies.append(body)
            raise KeyboardInterrupt
        return super()._create(**body)


def _both():
    return {"openai": FakeSDK(), "anthropic": FakeAnthropicSDK()}


def test_a_paid_phase_needs_an_approval_covering_its_estimate(tmp_path):
    prereg = example_prereg()
    with pytest.raises(SpendCapReached, match="finite positive"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, sdks={"openai": FakeSDK()},
                  say=_quiet)
    with pytest.raises(SpendCapReached, match="exceeds"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=0.0001,
                  sdks={"openai": FakeSDK()}, say=_quiet)


def test_a_paid_phase_runs_through_the_sdk_and_meters_what_it_spends(tmp_path):
    sdk = FakeSDK()
    said = []
    out = run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                    sdks={"openai": sdk}, say=said.append)
    assert len(sdk.bodies) == len(SCS) * 10 == out["calls_planned"]
    assert 0 < out["spent_usd"] <= 20.0
    assert out["spent_usd"] == pytest.approx(sdk.priced_usd())
    assert said[0].startswith(f"pilot-baseline on gpt-5.4-mini-2026-03-17: {len(SCS) * 10:,} calls")
    assert "guard headroom" in said[0]


def test_an_approval_equal_to_the_estimate_is_refused_for_want_of_guard_headroom(tmp_path):
    prereg = example_prereg()
    dry = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "dry", stub=True, say=_quiet)
    est, headroom = dry["estimate_usd"], dry["headroom_usd"]
    assert headroom > 0
    with pytest.raises(SpendCapReached, match="exceeds"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "at-estimate",
                  approved_usd=est, sdks={"openai": FakeSDK()}, say=_quiet)
    sdk = FakeSDK()
    out = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "paid",
                    approved_usd=est + headroom, sdks={"openai": sdk}, say=_quiet)
    assert len(sdk.bodies) == out["calls_planned"] == len(SCS) * 10
    assert out["headroom_usd"] == pytest.approx(headroom) and out["spent_usd"] < est + headroom


def test_plan_cost_matches_the_phase_it_mirrors(tmp_path):
    prereg = example_prereg()
    dry = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    calls, est, headroom = plan_cost(prereg.primary, LIB, SCS, [BASELINE], 10)
    assert calls == dry["calls_planned"] == len(SCS) * 10
    assert est == pytest.approx(dry["estimate_usd"])
    assert headroom == pytest.approx(dry["headroom_usd"]) and headroom > 0
    assert plan_cost(prereg.primary, LIB, SCS, [BASELINE], 20)[1] == pytest.approx(2 * est)


def test_the_single_turn_headroom_is_the_dearest_first_turn_bound_times_the_retries(tmp_path):
    prereg = example_prereg()
    base = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    from toolcall.providers import Client

    client = Client(prereg.primary)

    def bound(s):
        body = client.request(render(s, LIB, BASELINE), [{"role": "user", "text": s.user_message}])
        return call_bound_usd(prereg.primary, body) * WORST

    assert base["headroom_usd"] == pytest.approx(max(bound(s) for s in SCS))


# --- the estimate -----------------------------------------------------------------


def test_the_estimate_grows_with_what_is_sent():
    small = estimate_call_usd(MINI, [], "hi")
    big = estimate_call_usd(MINI, [{"description": "x" * 4000}], "hi")
    sonnet = estimate_call_usd(SONNET, [{"description": "x" * 4000}], "hi")
    assert small < big < sonnet


def test_the_thinking_term_alone_is_priced_as_output_tokens():
    # ModelSettings refuses an Anthropic setting without thinking, so the
    # no-thinking twin is duck-typed: the estimate reads only these fields.
    twin = SimpleNamespace(**{**SONNET.to_dict(), "thinking": None})
    tools = [{"description": "x" * 4000}]
    gap = estimate_call_usd(SONNET, tools, "hi") - estimate_call_usd(twin, tools, "hi")
    assert gap == pytest.approx(THINKING_TOKENS_ESTIMATE * 10.00 / 1e6)


def test_the_estimate_includes_the_guards_input_overhead_and_later_turn_history():
    empty = estimate_call_usd(MINI, [], "")
    assert empty == pytest.approx(
        ((len("[]") / 4.0 + INPUT_OVERHEAD_TOKENS) * 0.75 + 200 * 4.50) / 1e6)
    assert estimate_call_usd(MINI, [], "", history_tokens=1000) == pytest.approx(
        empty + 1000 * 0.75 / 1e6)


def test_an_unpriced_model_in_the_estimate_is_a_guard_error():
    odd = ModelSettings("openai", "gpt-unpriced", 0.0, reasoning_effort="none")
    with pytest.raises(SpendGuardError, match="no pinned price"):
        estimate_call_usd(odd, [], "hi")


def test_the_tool_result_allowance_is_the_scenarios_largest_mock_text():
    s = next(s for s in SCS if s.recovery)
    rec = s.recovery
    assert tool_result_chars(s, LIB) >= len(json.dumps(rec.success_result, sort_keys=True))
    from toolcall.mock_tools import reply

    assert tool_result_chars(s, LIB) >= max(
        len(reply(rec, f, 0, "", {}, LIB).content) for f in FORMATS)
    assert tool_result_chars(next(s for s in SCS if not s.recovery), LIB) == 0


# --- recovery: the real attempt cap and the real size of a late turn ----------------


def test_recovery_plans_the_real_attempt_cap_and_prices_later_turns_with_history(tmp_path):
    prereg = example_prereg()
    out = run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)
    assert out["calls_planned"] == 5 * len(FORMATS) * ATTEMPTS
    first_turns = sum(
        estimate_call_usd(prereg.primary, render(s, LIB, BASELINE), s.user_message)
        for s in sorted(SCS, key=lambda s: s.id) if s.recovery
    )
    first5 = [s for s in sorted(SCS, key=lambda s: s.id) if s.recovery][:5]
    flat = sum(estimate_call_usd(prereg.primary, render(s, LIB, BASELINE), s.user_message)
               for s in first5) * len(FORMATS) * ATTEMPTS
    assert first_turns > 0 and out["estimate_usd"] > flat  # history makes late turns dearer


def test_identical_wrong_retries_make_at_most_the_planned_posts(tmp_path):
    sdk = FakeSDK(arguments=json.dumps({"q": "wrong"}))
    said = []
    out = run_phase("pilot-recovery", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                    sdks={"openai": sdk}, say=said.append)
    assert len(sdk.bodies) <= out["calls_planned"] == 5 * len(FORMATS) * ATTEMPTS
    assert len(sdk.bodies) == out["calls_planned"]  # every conversation ran to its cap
    assert "maximum" in said[0]
    recs = JsonlStore(tmp_path / "pilot-recovery.jsonl", RecoveryRecord).read_all()
    assert recs and all(r.budget_exhausted for r in recs)


def test_no_guard_check_ever_asks_for_more_than_the_recovery_headroom(tmp_path, monkeypatch):
    prereg = example_prereg()
    asked = []
    real_before = SpendGuard.before

    def spy(self, bound_usd):
        asked.append(bound_usd)
        return real_before(self, bound_usd)

    monkeypatch.setattr(SpendGuard, "before", spy)
    # arguments of max_output_tokens x 4 characters on every turn, never accepted
    sdk = FakeSDK(arguments=json.dumps({"q": "x" * (prereg.primary.max_output_tokens * 4)}))
    out = run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                    sdks={"openai": sdk}, say=_quiet)
    assert len(asked) == len(sdk.bodies) == out["calls_planned"]
    assert max(asked) <= out["headroom_usd"]
    assert max(asked) > min(asked) * 1.5  # the late turns really were the big ones


# --- stored spend and the ledger ---------------------------------------------------


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
def test_stored_spend_and_the_ledger_both_reproduce_what_the_guard_charged(tmp_path, phase):
    prereg = example_prereg()
    out = run_phase(phase, prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                    sdks={"openai": FlakySDK()}, say=_quiet)
    store_cls = RecoveryRecord if phase == "pilot-recovery" else CallRecord
    records = JsonlStore(tmp_path / f"{phase}.jsonl", store_cls).read_all()
    assert any(getattr(r, "unmetered", False) or getattr(r, "unmetered_turns", 0)
               for r in records)
    assert stored_spend_usd(records, prereg.primary) == pytest.approx(out["spent_usd"])
    assert _ledger_total(tmp_path, phase) == pytest.approx(out["spent_usd"])
    assert out["ledger"] == str(_ledger_path(tmp_path, phase))


def test_a_crash_after_the_ledger_reserved_a_call_is_counted_at_its_worst_case(tmp_path):
    sdk = CrashSDK(crash_on=3)
    with pytest.raises(KeyboardInterrupt):
        run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert len(sdk.bodies) == 3
    worst = call_bound_usd(MINI, sdk.bodies[2]) * WORST
    metered = 2 * cost_usd(MINI.model, {"input": 1000, "cached": 0, "cache_write": 0,
                                        "output": 40, "reasoning": 0})
    assert _ledger_total(tmp_path, "pilot-baseline") == pytest.approx(metered + worst)
    # the stores know nothing of the third call; the ledger does
    stored = JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all()
    assert len(stored) == 2 and stored_spend_usd(stored, MINI) == pytest.approx(metered)


def test_a_resume_after_a_crash_starts_from_the_ledger_not_from_the_stores(tmp_path):
    prereg = example_prereg()
    with pytest.raises(KeyboardInterrupt):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": CrashSDK(crash_on=101)}, say=_quiet)
    before = _ledger_total(tmp_path, "pilot-baseline")
    stored = JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all()
    assert len(stored) == 100 and before > stored_spend_usd(stored, MINI)
    sdk, said = FakeSDK(), []
    out = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                    sdks={"openai": sdk}, say=said.append)
    assert len(sdk.bodies) == out["calls_planned"] - 100  # the interrupted call is redone
    assert out["resumed_spent_usd"] == pytest.approx(before)
    assert out["spent_usd"] == pytest.approx(sdk.priced_usd())
    assert "already charged to this phase (ledger)" in said[0] and f"${before:.2f}" in said[0]
    assert _ledger_total(tmp_path, "pilot-baseline") == pytest.approx(
        before + sdk.priced_usd())
    assert len((tmp_path / "pilot-baseline.jsonl").read_text().splitlines()) == out[
        "calls_planned"]


def test_stored_records_with_no_ledger_seed_the_ledger_at_their_cost(tmp_path):
    prereg = example_prereg()
    first = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                      sdks={"openai": FakeSDK()}, say=_quiet)
    _ledger_path(tmp_path, "pilot-baseline").unlink()  # a phase run before ledgers existed
    lines = (tmp_path / "pilot-baseline.jsonl").read_text().splitlines()
    (tmp_path / "pilot-baseline.jsonl").write_text("\n".join(lines[:100]) + "\n")
    seed = sum(json.loads(x)["cost_usd"] for x in lines[:100])
    out = run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                    sdks={"openai": FakeSDK()}, say=_quiet)
    assert out["resumed_spent_usd"] == pytest.approx(seed)
    assert _ledger_total(tmp_path, "pilot-baseline") == pytest.approx(first["spent_usd"])


def test_a_resumed_paid_phase_whose_stored_spend_is_near_the_approval_stops_early(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
              sdks={"openai": FakeSDK()}, say=_quiet)
    store = tmp_path / "pilot-baseline.jsonl"
    lines = store.read_text().splitlines()
    first = json.loads(lines[0])
    first["cost_usd"] = 20.0 - 1e-6  # the stores say the earlier session spent this
    store.write_text("\n".join([json.dumps(first, sort_keys=True), *lines[1:100]]) + "\n")
    _ledger_path(tmp_path, "pilot-baseline").unlink()
    sdk = FakeSDK()
    with pytest.raises(SpendCapReached, match="stopping"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == [] and len(store.read_text().splitlines()) == 100


def test_resuming_under_one_approval_never_spends_past_it(tmp_path):
    """The reviewer's probe: a recovery conversation cut off by the cap stores
    nothing, so only the ledger remembers what it cost. Each resume used to
    redo it and pay again."""
    prereg = example_prereg()
    dry = run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path / "dry", stub=True, say=_quiet)
    approved = dry["estimate_usd"] + dry["headroom_usd"]
    real, tripped = 0.0, []
    for session in (1, 2, 3, 4):
        sdk = FakeSDK(usage=(12000, 40))  # far dearer than the estimate assumed
        try:
            run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path / "paid",
                      approved_usd=approved, sdks={"openai": sdk}, resume=session > 1,
                      say=_quiet)
            tripped.append(False)
        except SpendCapReached:
            tripped.append(True)
        real += sdk.priced_usd()
        assert real <= approved, f"session {session} took the real spend past the approval"
    assert tripped[0]  # the cap really did stop session 1
    total = _ledger_total(tmp_path / "paid", "pilot-recovery")
    assert total >= real - 1e-9  # the ledger never sees less than was spent
    stored = JsonlStore(tmp_path / "paid" / "pilot-recovery.jsonl", RecoveryRecord).read_all()
    assert total > stored_spend_usd(stored, prereg.primary)  # the cut-off turns


# --- refusing silent reuse -----------------------------------------------------------


def test_a_run_without_resume_refuses_a_phase_that_already_has_a_store(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
              sdks={"openai": FakeSDK()}, say=_quiet)
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="store exists; pass resume or move it"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == [] and len((tmp_path / "pilot-baseline.jsonl").read_text().splitlines()) \
        == len(SCS) * 10
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "stub", stub=True, say=_quiet)
    with pytest.raises(ValueError, match="store exists; pass resume or move it"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "stub", stub=True, say=_quiet)


def test_a_run_without_resume_refuses_a_phase_that_only_has_a_ledger(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
              sdks={"openai": FakeSDK()}, say=_quiet)
    (tmp_path / "pilot-baseline.jsonl").unlink()  # the stores were moved; the spend was not
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="store exists; pass resume or move it"):
        run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == []


def test_a_paid_run_refuses_a_stub_directory_and_a_stub_run_refuses_a_paid_one(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "rehearsal", stub=True, say=_quiet)
    sdk = FakeSDK()
    for resume in (False, True):  # a resume once accepted stub records as real spend
        with pytest.raises(ValueError, match="stub rehearsal"):
            run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "rehearsal",
                      approved_usd=20.0, resume=resume, sdks={"openai": sdk}, say=_quiet)
    with pytest.raises(ValueError, match="stub rehearsal"):  # even a different phase's
        run_phase("pilot-cells", prereg, LIB, SCS, tmp_path / "rehearsal", approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == []

    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "paid", approved_usd=20.0,
              sdks={"openai": FakeSDK()}, say=_quiet)
    assert not (tmp_path / "paid" / "STUB").exists()
    with pytest.raises(ValueError, match="stores but no STUB marker"):
        run_phase("pilot-cells", prereg, LIB, SCS, tmp_path / "paid", stub=True, say=_quiet)
    assert not (tmp_path / "paid" / "pilot-cells.jsonl").exists()


def test_a_poisoned_store_of_the_second_job_makes_no_post_at_all(tmp_path):
    prereg = example_prereg()
    run_phase("pilot-slice", prereg, LIB, SCS, tmp_path, approved_usd=20.0, sdks=_both(),
              say=_quiet)
    nano = tmp_path / "pilot-slice-gpt-5.4-nano-2026-03-17.jsonl"
    sonnet = tmp_path / "pilot-slice-claude-sonnet-5-5.jsonl"
    nano.write_text("\n".join(nano.read_text().splitlines()[:3]) + "\n")
    bad = json.loads(sonnet.read_text().splitlines()[0])
    bad["model"] = MINI.model
    sonnet.write_text(json.dumps(bad, sort_keys=True) + "\n")
    sdks = _both()
    with pytest.raises(ValueError, match="resume: stored run"):
        run_phase("pilot-slice", prereg, LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
                  sdks=sdks, say=_quiet)
    assert sdks["openai"].bodies == [] and sdks["anthropic"].bodies == []


# --- one SDK per provider --------------------------------------------------------------


def test_a_paid_multi_model_phase_shares_one_guard_and_one_ledger(tmp_path, monkeypatch):
    made = []
    real_init = guard_module.SpendGuard.__init__

    def counting(self, *a, **k):
        made.append(self)
        real_init(self, *a, **k)

    monkeypatch.setattr(guard_module.SpendGuard, "__init__", counting)
    prereg = example_prereg()
    sdks = _both()
    out = run_phase("pilot-slice", prereg, LIB, SCS, tmp_path, approved_usd=20.0, sdks=sdks,
                    say=_quiet)
    assert len(made) == 1
    assert len(sdks["openai"].bodies) == len(sdks["anthropic"].bodies) == 10 == \
        out["calls_planned"] // 2
    assert all(b["model"] == "claude-sonnet-5-5" for b in sdks["anthropic"].bodies)
    stored = sum(
        stored_spend_usd(JsonlStore(tmp_path / f"pilot-slice-{m.model}.jsonl",
                                    CallRecord).read_all(), m)
        for m in prereg.slice_models)
    assert made[0].spent == pytest.approx(out["spent_usd"]) == pytest.approx(stored)
    assert _ledger_total(tmp_path, "pilot-slice") == pytest.approx(stored)
    assert out["spent_usd"] > 10 * 0.0009  # the dearer Sonnet calls are in it too


def test_a_missing_provider_sdk_refuses_before_any_post(tmp_path):
    openai = FakeSDK()
    with pytest.raises(ValueError, match="anthropic"):
        run_phase("pilot-slice", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": openai}, say=_quiet)
    assert openai.bodies == []
    assert not list(tmp_path.glob("*.jsonl"))


def test_the_stub_never_touches_an_sdk_it_is_given(tmp_path):
    sdks = _both()
    run_phase("pilot-slice", example_prereg(), LIB, SCS, tmp_path, stub=True, sdks=sdks,
              say=_quiet)
    assert sdks["openai"].bodies == [] and sdks["anthropic"].bodies == []


@pytest.mark.parametrize("stub", [True, False])
@pytest.mark.parametrize("phase", ["pilot-recovery", "recovery"])
def test_recovery_phases_refuse_a_turn_budget_the_code_does_not_run(tmp_path, phase, stub):
    prereg = example_prereg(**STEP2, turn_budget=TURN_BUDGET + 2)
    sdk = FakeSDK()
    with pytest.raises(ValueError, match=rf"turn_budget is {TURN_BUDGET + 2} .*is {TURN_BUDGET}"):
        run_phase(phase, prereg, LIB, SCS, tmp_path, approved_usd=20.0, stub=stub,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == [] and list(tmp_path.iterdir()) == []  # nothing posted, nothing written
    # the other phases never run a conversation, so they do not care
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, stub=True, say=_quiet)


# --- one run at a time, and a ledger that cannot be written stops the run -------------------


def test_a_paid_run_refuses_a_phase_whose_lock_is_held(tmp_path):
    prereg = example_prereg()
    sdk = FakeSDK()
    with (tmp_path / "pilot-baseline.spend.lock").open("a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for resume in (False, True):
            with pytest.raises(SpendCapReached,
                               match=r"another run of pilot-baseline holds .*pilot-baseline.spend.lock"):
                run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                          resume=resume, sdks={"openai": sdk}, say=_quiet)
        # another phase's ledger is not in the way
        run_phase("pilot-recovery", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": FakeSDK()}, say=_quiet)
    assert sdk.bodies == [] and not (tmp_path / "pilot-baseline.jsonl").exists()
    # the holder let go: the phase runs
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path, approved_usd=20.0,
              sdks={"openai": sdk}, say=_quiet)
    assert len(sdk.bodies) == len(SCS) * 10


def test_the_lock_is_held_while_the_phase_runs_and_released_when_it_ends(tmp_path):
    seen = []

    class Probe(FakeSDK):
        def _create(self, **body):
            try:  # a second run, mid-phase, in the same process
                run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path,
                          approved_usd=20.0, resume=True, sdks={"openai": FakeSDK()}, say=_quiet)
                seen.append("ran")
            except SpendCapReached as e:
                seen.append(str(e))
            return super()._create(**body)

    run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
              sdks={"openai": Probe()}, say=_quiet)
    assert seen and all("another run of pilot-baseline holds" in m for m in seen)
    run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
              resume=True, sdks={"openai": FakeSDK()}, say=_quiet)  # released at the end
    # and when a phase dies, too
    with pytest.raises(KeyboardInterrupt):
        run_phase("pilot-cells", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": CrashSDK(crash_on=2)}, say=_quiet)
    run_phase("pilot-cells", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0, resume=True,
              sdks={"openai": FakeSDK()}, say=_quiet)


def _fail_nth(monkeypatch, key, n):
    """Make the nth ledger line carrying `key` fail with ENOSPC."""
    seen = {"n": 0}
    real = SpendLedger._append

    def append(self, entry):
        if key in entry:
            seen["n"] += 1
            if seen["n"] == n:
                raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, entry)

    monkeypatch.setattr(SpendLedger, "_append", append)


def test_a_ledger_that_cannot_reserve_stops_the_run_it_does_not_become_data(tmp_path,
                                                                            monkeypatch):
    _fail_nth(monkeypatch, "reserve", 6)
    sdk = FakeSDK()
    with pytest.raises(LedgerWriteError, match="No space left"):
        run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    lines = (tmp_path / "pilot-baseline.spend.jsonl").read_text().splitlines()
    reserved = [x for x in lines if '"reserve"' in x]
    assert len(reserved) == 5 == len(sdk.bodies)  # a post only ever follows a written reserve
    stored = JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all()
    assert len(stored) == 5 and not any(r.error for r in stored)  # no OSError row


def test_a_ledger_that_cannot_settle_stops_the_run_and_counts_the_call_at_worst(tmp_path,
                                                                                monkeypatch):
    _fail_nth(monkeypatch, "settle", 4)
    sdk = FakeSDK()
    with pytest.raises(LedgerWriteError):
        run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert len(sdk.bodies) == 4
    stored = JsonlStore(tmp_path / "pilot-baseline.jsonl", CallRecord).read_all()
    assert len(stored) == 3 and not any(r.error for r in stored)
    worst = call_bound_usd(MINI, sdk.bodies[3]) * WORST
    each = cost_usd(MINI.model, {"input": 1000, "cached": 0, "cache_write": 0, "output": 40,
                                 "reasoning": 0})
    assert _ledger_total(tmp_path, "pilot-baseline") == pytest.approx(3 * each + worst)


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


def test_a_stub_run_says_no_spend_instead_of_an_approval(tmp_path):
    said = []
    run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, stub=True,
              say=said.append)
    assert said[0].startswith(f"pilot-baseline on gpt-5.4-mini-2026-03-17: {len(SCS) * 10:,} calls")
    assert "guard headroom; stub: no spend" in said[0]
    assert "approved" not in said[0]


def _campaign_with_one_dead_scenario_cell(root):
    """A stub campaign in which every repetition of one scenario in one cell is an
    API_ERROR: that scenario has no graded call there, so the analysis drops it."""
    from toolcall.analysis import analyse

    prereg = example_prereg(**STEP2, iterations=100)
    src = root / "src"
    run_phase("campaign", prereg, LIB, SCS, src, stub=True, say=_quiet)
    calls = JsonlStore(src / "campaign.jsonl", CallRecord).read_all()
    dst = root / "dst"
    dst.mkdir()
    store = JsonlStore(dst / "campaign.jsonl", CallRecord)
    for r in calls:
        if r.scenario_id == SCS[0].id and r.cell == "high-rich-strict":
            r.grade = dict(r.grade, category="API_ERROR", detail="the post failed")
        store.append(r)
    (dst / "STUB").touch()
    return prereg, dst, analyse


def _stored_campaign(dst):
    return JsonlStore(dst / "campaign.jsonl", CallRecord).read_all()


@pytest.mark.parametrize("phase", ["recovery", "slice", "exploratory"])
def test_later_phases_start_and_pick_the_cells_the_analysis_ranks(tmp_path, phase):
    from toolcall.formulation import parse_cell
    from toolcall.runner import _jobs

    prereg, dst, analyse = _campaign_with_one_dead_scenario_cell(tmp_path)
    ranks = analyse(_stored_campaign(dst), [], SCS, prereg)["ranked_cells"]
    run_phase(phase, prereg, LIB, SCS, dst, stub=True, say=_quiet)  # used to raise
    cells = {c.name for job in _jobs(phase, prereg, LIB, SCS, dst) for c in job.cells}
    best, worst = parse_cell(ranks["best"]).name, parse_cell(ranks["worst"]).name
    assert best in cells
    if phase == "slice":
        assert worst in cells


def test_the_runner_and_the_analysis_rank_the_same_cells(tmp_path):
    from toolcall.analysis import ranked_analysable_cells

    prereg, dst, analyse = _campaign_with_one_dead_scenario_cell(tmp_path)
    done = _stored_campaign(dst)
    assert analyse(done, [], SCS, prereg)["ranked_cells"] == ranked_analysable_cells(
        done, prereg.included, prereg)


def test_a_paid_phase_without_its_api_key_refuses_before_anything_is_reserved(
        tmp_path, monkeypatch):
    """No key: every post would fail, and the guard would charge each at its worst
    case as phantom spend. The refusal comes before the ledger is even created."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  say=_quiet)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        run_phase("pilot-slice", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
                  say=_quiet)  # empty counts as unset (and openai is not set either)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("package", "phase"), [("openai", "pilot-baseline"),
                                                ("anthropic", "pilot-slice")])
def test_a_paid_phase_without_its_sdk_package_refuses_before_anything_is_reserved(
        tmp_path, monkeypatch, package, phase):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setitem(sys.modules, package, None)  # `from <package> import ...` fails
    with pytest.raises(ValueError, match=rf"install the {package} package"):
        run_phase(phase, example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0, say=_quiet)
    assert list(tmp_path.iterdir()) == []


def test_the_stub_and_given_sdks_skip_the_key_and_package_checks(tmp_path, monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setitem(sys.modules, "openai", None)
    run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path / "stub", stub=True,
              say=_quiet)
    out = run_phase("pilot-baseline", example_prereg(), LIB, SCS, tmp_path / "fake",
                    approved_usd=20.0, sdks={"openai": FakeSDK()}, say=_quiet)
    assert out["spent_usd"] > 0


def test_the_real_sdks_are_built_before_the_first_post(tmp_path, monkeypatch):
    """With sdks=None the phase builds each provider's SDK itself, eagerly, before
    the ledger exists, and the clients then use those same objects."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    sdks = _both()
    built, ledger_there, seen_at_first_post = [], [], []

    def fake_build(self):
        built.append(self.settings.provider)
        ledger_there.append((tmp_path / "pilot-slice.spend.jsonl").exists())
        return sdks[self.settings.provider]

    def watch(sdk, namespace):
        inner = getattr(sdk, namespace).create

        def create(**body):
            seen_at_first_post.append(sorted(set(built)))
            return inner(**body)

        getattr(sdk, namespace).create = create

    watch(sdks["openai"], "responses")
    watch(sdks["anthropic"], "messages")
    monkeypatch.setattr("toolcall.providers.Client.build_sdk", fake_build)
    run_phase("pilot-slice", example_prereg(), LIB, SCS, tmp_path, approved_usd=20.0,
              say=_quiet)
    assert seen_at_first_post[0] == ["anthropic", "openai"]
    assert ledger_there[:2] == [False, False]  # both built before the ledger was created
    assert sdks["openai"].bodies and sdks["anthropic"].bodies


def test_a_phase_refuses_an_approval_above_the_preregistered_one(tmp_path):
    prereg = example_prereg(**{**STEP2, "approved_usd": 5.0})
    sdk = FakeSDK()
    with pytest.raises(ValueError, match=r"approved_usd 6.0 .*pre-registered 5.0"):
        run_phase("campaign", prereg, LIB, SCS, tmp_path, approved_usd=6.0,
                  sdks={"openai": sdk}, say=_quiet)
    assert sdk.bodies == [] and list(tmp_path.iterdir()) == []
    # the pilot comes before step 2: nothing is registered yet to be above
    run_phase("pilot-baseline", prereg, LIB, SCS, tmp_path / "pilot", approved_usd=20.0,
              sdks={"openai": FakeSDK()}, say=_quiet)
