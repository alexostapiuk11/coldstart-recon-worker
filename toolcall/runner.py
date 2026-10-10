"""Every paid phase, as one function each, so scripts/a3_run.py stays thin and
the same code path runs on the stub (`stub=True`) as on the real providers.

Each phase builds its schedule from the pre-registration, estimates its cost
from the request bodies it will send, refuses to start unless the author's
approved amount covers the estimate plus the spend guard's headroom, and wraps
the client in one spend guard shared by every job of the phase.

| phase           | cells                       | scenarios                | repetitions  |
|-----------------|-----------------------------|--------------------------|--------------|
| pilot-baseline  | baseline                    | every candidate          | pilot_reps   |
| pilot-cells     | all eight                   | first pilot_cost_scenarios | pilot_cost_reps |
| pilot-slice     | high-rich-strict, baseline  | first 5, per slice model | 1            |
| pilot-recovery  | baseline                    | first 5 with recovery    | 1 per format |
| campaign        | all eight                   | included                 | reps         |
| recovery        | baseline, best              | included with recovery   | recovery_reps per format |
| slice           | best, worst                 | included, per slice model | slice_reps  |
| exploratory     | best, constrained decoding  | included                 | reps         |

"best" and "worst" come from the campaign's own records by the pre-registered
rule, over the same analysable scenarios `analysis.analyse` ranks on
(`analysis.ranked_analysable_cells`), so those phases cannot start before the
campaign ends and cannot pick cells the analysis would not.

Recovery conversations. `recovery.converse` makes up to TURN_BUDGET + 1
attempts, so a recovery phase plans that many calls per conversation, as a
maximum. Attempt k carries the history of k earlier turns (each an assistant
message and a tool result), and is priced and bounded accordingly.

Headroom. `SpendGuard.before` refuses a call when spent + bound x (1 +
SDK_MAX_RETRIES) would pass the approval, so an approval equal to the estimate
would stop a phase before its last calls. The phase therefore also needs
`headroom_usd`: the dearest worst-case bound of any request it can send. For
single-turn jobs that is the dearest first-turn body. For recovery it is a
synthetic final-turn body: the first body plus TURN_BUDGET rounds of an
assistant message of `max_output_tokens x ASSISTANT_CHARS_PER_TOKEN`
characters and the scenario's largest tool result.

Resuming. A paid phase writes a durable ledger, `<root>/<phase>.spend.jsonl`
(toolcall.guard.SpendLedger): every call's worst case is fsynced before the
post and settled after. Paid turns that never reach a store (a conversation
cut off by the cap, a crash between post and store write) are in the ledger
and in no store, so a resume seeds its guard with
`max(ledger.total(), stored_spend_usd(stores))`. The stores are the cross-check
floor: if they say more than the ledger (a phase run before ledgers existed),
the ledger is topped up to match. The approved amount then caps the whole phase
across any number of resumes.

One run at a time. The ledger holds an exclusive `flock` on
`<root>/<phase>.spend.lock` from before the stores or the seed are read until
the phase ends, so a second run of the same phase (a resume started twice) is
refused instead of seeding from the same total and spending the approval again.

Reuse. Without `resume`, a phase refuses to start if any of its stores or its
ledger is non-empty. A stub rehearsal marks its directory with a `STUB` file; a
paid run refuses such a directory, and a stub run refuses a directory that has
stores but no marker, so rehearsal records can never seed or be mixed with paid
spend. The store paths are the same either way.
"""

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

from harness.store import JsonlStore
from toolcall import campaign
from toolcall.analysis import ranked_analysable_cells
from toolcall.campaign import _check_same_run
from toolcall.formulation import BASELINE, CELLS, Formulation, parse_cell, render
from toolcall.guard import (
    INPUT_OVERHEAD_TOKENS,
    SDK_MAX_RETRIES,
    TOKENIZER_FACTOR,
    GuardedClient,
    SpendGuard,
    SpendGuardError,
    SpendLedger,
    call_bound_usd,
    check_estimate,
)
from toolcall.mock_tools import FORMATS, reply
from toolcall.prices import PRICES
from toolcall.providers import (
    ANTHROPIC,
    OPENAI,
    PARSE,
    Client,
    ModelSettings,
    ScriptedClient,
)
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.recovery import TURN_BUDGET
from toolcall.scenarios import Scenario
from toolcall.stub import StubModel

OUTPUT_TOKENS_ESTIMATE = 200
THINKING_TOKENS_ESTIMATE = 300  # Sonnet 5.5 with between_tools; amendment §8's assumption
CHARS_PER_TOKEN = 4.0  # an estimate, not a bound; the guard's bound is in toolcall.guard
# The headroom's synthetic assistant message: more characters per output token
# than any tokenizer produces on JSON arguments, so it is a ceiling, not a guess.
ASSISTANT_CHARS_PER_TOKEN = 6
ATTEMPTS = TURN_BUDGET + 1  # what recovery.converse can make per conversation
RECOVERY_PHASES = ("pilot-recovery", "recovery")
STUB_MARKER = "STUB"
PHASES = ("pilot-baseline", "pilot-cells", "pilot-slice", "pilot-recovery", "campaign",
          "recovery", "slice", "exploratory")


class Job(NamedTuple):
    name: str  # the store's name
    settings: ModelSettings
    cells: list[Formulation]
    scenarios: list[Scenario]
    reps: int
    formats: tuple[str, ...] | None  # set: recovery conversations
    offset: int  # added to the schedule seed


class Plan(NamedTuple):
    calls: int  # a maximum: a conversation can end before its last attempt
    estimate_usd: float
    headroom_usd: float


def estimate_call_usd(settings, tools: list[dict], user_message: str,
                      history_tokens: float = 0.0) -> float:
    """An upper-leaning estimate from the size of what will be sent, with
    `history_tokens` more input for a later recovery turn. The guard then
    meters the real usage; this only decides whether to start."""
    try:
        p = PRICES[settings.model]
    except KeyError:
        raise SpendGuardError(
            f"no pinned price for {settings.model!r}; add it with its source first") from None
    chars = len(json.dumps(tools)) + len(user_message)
    tokens_in = (chars / CHARS_PER_TOKEN * TOKENIZER_FACTOR[settings.provider]
                 + INPUT_OVERHEAD_TOKENS + history_tokens)
    out = OUTPUT_TOKENS_ESTIMATE + (THINKING_TOKENS_ESTIMATE if settings.thinking else 0)
    return (tokens_in * p.input + out * p.output) / 1e6


def tool_result_chars(scenario: Scenario, library) -> int:
    """The longest thing the mock tool says in this scenario's recovery: its
    error or contradiction (either format) or its success result."""
    rec = scenario.recovery
    if rec is None:
        return 0
    failing = max(len(reply(rec, fmt, 0, "", {}, library).content) for fmt in FORMATS)
    return max(failing, len(json.dumps(rec.success_result, sort_keys=True)))


def _bound_of(request, settings, what: str) -> float:
    if request is None:
        raise ValueError(f"{what} has no stored request, so its guard charge cannot be rebuilt; "
                         "the stored spend would be understated")
    return call_bound_usd(settings, request)


def _call_charge(r: CallRecord, settings) -> float:
    if r.cost_usd is not None:  # metered: the guard added exactly this
        return r.cost_usd
    what = f"call record {r.run_index}"
    if r.response is not None:  # unmetered: no usable usage, charged one bound
        return _bound_of(r.request, settings, what)
    # the post raised: charged the worst case, one bound per possible SDK attempt
    return _bound_of(r.request, settings, what) * (1 + SDK_MAX_RETRIES)


def _recovery_charge(r: RecoveryRecord, settings) -> float:
    total = r.cost_usd  # the metered turns
    for i, t in enumerate(r.turns):
        what = f"recovery record {r.run_index}, turn {i}"
        if "response" not in t:  # the post raised
            total += _bound_of(t.get("request"), settings, what) * (1 + SDK_MAX_RETRIES)
            continue
        usage = (t.get("parsed") or {}).get("usage")
        if not usage or (usage["input"] == 0 and usage["output"] == 0):
            total += _bound_of(t.get("request"), settings, what)
    return total


def stored_spend_usd(records, settings) -> float:
    """What the spend guard charged for `records`, rebuilt from the records alone.
    Metered calls cost their `cost_usd`; an unmetered call was charged its bound;
    a call whose post raised was charged the bound times 1 + SDK_MAX_RETRIES.
    A floor, not the whole story: turns that never reached a store are in the
    spend ledger only."""
    return sum(_recovery_charge(r, settings) if isinstance(r, RecoveryRecord)
               else _call_charge(r, settings) for r in records)


def _store(root: Path, name: str, cls):
    return JsonlStore(root / f"{name}.jsonl", cls)


def _ledger_path(root: Path, phase: str) -> Path:
    return root / f"{phase}.spend.jsonl"


def _effective(settings: ModelSettings, stub: bool) -> ModelSettings:
    """The settings the client actually runs: the stub only speaks OpenAI's shape."""
    if stub and settings.provider != "openai":
        return replace(settings, provider="openai", thinking=None, reasoning_effort="none")
    return settings


def _client(settings, library, scenarios, stub: bool, sdks=None):
    settings = _effective(settings, stub)
    if stub:
        return ScriptedClient(settings, StubModel(library, scenarios, seed=0,
                                                  model=settings.model))
    return Client(settings, sdk=(sdks or {}).get(settings.provider))


def _worst_assistant_raw(settings: ModelSettings, tool_name: str, k: int) -> list:
    """One assistant turn as the transcript would echo it, as long as the model
    can possibly write: `max_output_tokens x ASSISTANT_CHARS_PER_TOKEN` characters."""
    arguments = {"q": "x" * (settings.max_output_tokens * ASSISTANT_CHARS_PER_TOKEN)}
    if settings.provider == "openai":
        return [{"type": "function_call", "id": f"fc_{k}", "call_id": f"call_{k}",
                 "name": tool_name, "arguments": json.dumps(arguments), "status": "completed"}]
    return [{"type": "tool_use", "id": f"toolu_{k}", "name": tool_name, "input": arguments}]


def _final_turn_body(builder: Client, tools: list[dict], scenario: Scenario, library) -> dict:
    """The largest request a recovery conversation can send: attempt TURN_BUDGET,
    behind TURN_BUDGET rounds of a maximal assistant message and the scenario's
    largest tool result, built by the real request builder."""
    result = "r" * tool_result_chars(scenario, library)
    transcript = [{"role": "user", "text": scenario.user_message}]
    for k in range(TURN_BUDGET):
        transcript += [
            {"role": "assistant", "raw": _worst_assistant_raw(builder.settings,
                                                              tools[0]["name"], k)},
            {"role": "tool", "call_id": f"call_{k}", "content": result, "is_error": True},
        ]
    return builder.request(tools, transcript)


def _plan(job: Job, library) -> Plan:
    """Calls (at most), estimated USD, and the dearest worst-case bound of any
    request the job can send, built by the real client's request builder."""
    builder = Client(job.settings)
    formats = job.formats or (None,)
    attempts = ATTEMPTS if job.formats else 1
    total, calls, worst = 0.0, 0, 0.0
    for cell in job.cells:
        for s in job.scenarios:
            tools = render(s, library, cell)
            # attempt k also carries k rounds of an assistant turn and a tool result
            per_round = OUTPUT_TOKENS_ESTIMATE + tool_result_chars(s, library) / CHARS_PER_TOKEN
            for k in range(attempts):
                total += job.reps * len(formats) * estimate_call_usd(
                    job.settings, tools, s.user_message, history_tokens=k * per_round)
            calls += job.reps * len(formats) * attempts
            body = (_final_turn_body(builder, tools, s, library) if job.formats else
                    builder.request(tools, [{"role": "user", "text": s.user_message}]))
            worst = max(worst, call_bound_usd(job.settings, body) * (1 + SDK_MAX_RETRIES))
    return Plan(calls, total, worst)


def plan_cost(settings: ModelSettings, library, scenarios, cells, reps: int
              ) -> tuple[int, float, float]:
    """`(calls, estimate_usd, headroom_usd)` for single-turn calls of `reps`
    repetitions of every scenario in every cell: the same planning a phase does,
    for a script that runs one job outside the phases (scripts/a3_diagnose.py).
    The approval must cover `estimate_usd + headroom_usd`."""
    plan = _plan(Job("plan", settings, list(cells), list(scenarios), reps, None, 0), library)
    return plan.calls, plan.estimate_usd, plan.headroom_usd


def _announce(phase, models, plan: Plan, approved, seed, recovery, say, stub=False):
    spend = "stub: no spend" if stub else f"approved ${approved:.2f}"
    msg = (f"{phase} on {models}: {plan.calls:,} calls, estimated ${plan.estimate_usd:.2f}"
           f" + ${plan.headroom_usd:.2f} guard headroom; {spend}")
    if recovery:
        msg += "; calls are a maximum, a conversation can end before its last attempt"
    if seed:
        msg += f"; resuming with ${seed:.2f} already charged to this phase (ledger)"
    say(msg)


def _jobs(phase, prereg, library, scenarios, root) -> list[Job]:
    by_id = {s.id: s for s in scenarios}
    candidates = sorted(scenarios, key=lambda s: s.id)
    p = prereg
    if not phase.startswith("pilot"):
        p.require_step2()
        included = [by_id[i] for i in p.included]
    if phase == "pilot-baseline":
        return [Job("pilot-baseline", p.primary, [parse_cell(p.baseline_cell)], candidates,
                    p.pilot_reps, None, 1)]
    if phase == "pilot-cells":
        return [Job("pilot-cells", p.primary, list(CELLS), candidates[:p.pilot_cost_scenarios],
                    p.pilot_cost_reps, None, 2)]
    if phase == "pilot-slice":
        return [Job(f"pilot-slice-{m.model}", m, [Formulation("high", "rich", "strict"), BASELINE],
                    [s for s in candidates if not s.no_call_expected][:5], 1, None, 3)
                for m in p.slice_models]
    if phase == "pilot-recovery":
        return [Job("pilot-recovery", p.primary, [BASELINE],
                    [s for s in candidates if s.recovery][:5], 1, FORMATS, 4)]
    if phase == "campaign":
        return [Job("campaign", p.primary, list(CELLS), included, p.reps, None, 0)]
    done = JsonlStore(root / "campaign.jsonl", CallRecord).read_all()
    if not done:
        raise ValueError(f"{phase} needs the campaign's records to pick the cells")
    ranks = ranked_analysable_cells(done, p.included, p)
    best, worst = parse_cell(ranks["best"]), parse_cell(ranks["worst"])
    if phase == "recovery":
        cells = [BASELINE] if best == BASELINE else [BASELINE, best]
        return [Job("recovery", p.primary, cells, [s for s in included if s.recovery],
                    p.recovery_reps, FORMATS, 5)]
    if phase == "slice":
        return [Job(f"slice-{m.model}", m, [best, worst], included, p.slice_reps, None, 6)
                for m in p.slice_models]
    return [Job("exploratory", replace(p.primary, constrained=True), [best], included, p.reps,
                None, 7)]


def _check_directory(root: Path, stub: bool) -> None:
    if not stub and (root / STUB_MARKER).exists():
        raise ValueError(f"{root} holds a stub rehearsal ({STUB_MARKER} marker): its records "
                         "are not paid spend. Use another directory for the paid run.")
    if stub and not (root / STUB_MARKER).exists() and any(root.glob("*.jsonl")):
        raise ValueError(f"{root} has stores but no {STUB_MARKER} marker, so it is not a stub "
                         "rehearsal. Rehearse in an empty directory.")


def _refuse_reuse(root: Path, phase: str, jobs: list[Job], stub: bool) -> None:
    paths = [root / f"{job.name}.jsonl" for job in jobs]
    if not stub:
        paths.append(_ledger_path(root, phase))
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            raise ValueError(f"{path}: store exists; pass resume or move it")


def _preflight_stores(root: Path, jobs: list[Job], stub: bool) -> None:
    """Every job's store must be resumable BEFORE the first post, so a bad second
    job cannot be found out after the first has already spent."""
    for job in jobs:
        settings = _effective(job.settings, stub)
        if job.formats:
            stored = _store(root, job.name, RecoveryRecord).read_all()
            _check_same_run(stored, model=settings.model, settings=settings.to_dict())
        else:
            stored = _store(root, job.name, CallRecord).read_all()
            _check_same_run(stored, model=settings.model, settings=settings.to_dict(),
                            phase=job.name)


def _check_sdks(jobs: list[Job], sdks) -> None:
    if sdks is None:  # each client builds its provider's real SDK itself
        return
    for provider in sorted({job.settings.provider for job in jobs} - set(sdks)):
        raise ValueError(f"no SDK for provider {provider!r}: pass sdks={{{provider!r}: ...}}")


API_KEY_ENV = {OPENAI: "OPENAI_API_KEY", ANTHROPIC: "ANTHROPIC_API_KEY"}


def _real_sdks(jobs: list[Job]) -> dict[str, object]:
    """For a paid phase given no SDKs: check each provider's API key is set and
    build its real SDK now, once, shared by that provider's jobs. Run before the
    ledger is created or anything is reserved: a missing key or package makes
    every post fail, and the guard charges a failed post at its worst case, so
    finding out per call would book phantom spend and store API_ERROR records."""
    providers = sorted({job.settings.provider for job in jobs})
    for provider in providers:
        if not os.environ.get(API_KEY_ENV[provider], "").strip():
            raise ValueError(f"{API_KEY_ENV[provider]} is not set in the environment "
                             f"(or is empty), and the phase would call {provider}")
    first = {job.settings.provider: job.settings for job in jobs}
    return {provider: Client(first[provider]).build_sdk() for provider in providers}


def _check_approval(phase: str, prereg, approved_usd: float) -> None:
    """From step 2 on, the pre-registration holds the author's approved amount
    for the whole experiment; one phase may not be approved for more than it.
    (Each phase's approval caps that phase alone. Keeping the sum over phases
    within `prereg.approved_usd` is the job of the script that runs them, plan 3's
    `scripts/a3_run.py`; this only stops any single phase from exceeding it.)"""
    cap = prereg.approved_usd
    if phase.startswith("pilot") or cap is None:
        return
    if approved_usd > cap:
        raise ValueError(
            f"{phase}: approved_usd {approved_usd} is above the pre-registered {cap} "
            "(prereg.approved_usd); lower it, or amend the pre-registration first")


def _seed(root: Path, jobs: list[Job], ledger: SpendLedger) -> float:
    """What the phase has already spent: the ledger's total, floored by what the
    stores say. A store that says more (a phase run before ledgers existed) tops
    the ledger up, so the ledger stays the authoritative total from here on."""
    stored = sum(
        stored_spend_usd(_store(root, job.name,
                                RecoveryRecord if job.formats else CallRecord).read_all(),
                         job.settings)
        for job in jobs)
    spent = ledger.total()
    if stored > spent:
        gap = stored - spent
        ledger.settle(ledger.reserve(gap), gap)
    return ledger.total()


def run_phase(phase: str, prereg, library, scenarios, root, *, approved_usd: float = 0.0,
              stub: bool = False, resume: bool = False, say=print,
              sdks: dict[str, object] | None = None) -> dict:
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; one of {PHASES}")
    if phase in RECOVERY_PHASES and prereg.turn_budget != TURN_BUDGET:
        raise ValueError(
            f"{phase}: the pre-registered turn_budget is {prereg.turn_budget} but "
            f"toolcall.recovery.TURN_BUDGET, which converse actually runs, is {TURN_BUDGET}; "
            "the recovery phases would measure something other than what was registered")
    root = Path(root)
    _check_directory(root, stub)
    jobs = _jobs(phase, prereg, library, scenarios, root)
    if stub:
        return _run(phase, prereg, library, scenarios, root, jobs, None, approved_usd, True,
                    resume, say, sdks)
    _check_approval(phase, prereg, approved_usd)
    if sdks is None:
        sdks = _real_sdks(jobs)
    _check_sdks(jobs, sdks)
    # The ledger's lock is what makes one run at a time: taken here, before the
    # stores or the seed are read, and released when the phase ends or dies.
    with SpendLedger(_ledger_path(root, phase), label=phase) as ledger:
        return _run(phase, prereg, library, scenarios, root, jobs, ledger, approved_usd, False,
                    resume, say, sdks)


def _run(phase, prereg, library, scenarios, root, jobs, ledger, approved_usd, stub, resume, say,
         sdks) -> dict:
    if resume:
        _preflight_stores(root, jobs, stub)
    else:
        _refuse_reuse(root, phase, jobs, stub)
    plans = [_plan(job, library) for job in jobs]
    plan = Plan(sum(x.calls for x in plans), sum(x.estimate_usd for x in plans),
                max((x.headroom_usd for x in plans), default=0.0))
    guard = None
    seed = 0.0
    if not stub:
        # Refuse on the approval before the ledger is read or written.
        check_estimate(plan.estimate_usd + plan.headroom_usd, approved_usd)
        seed = _seed(root, jobs, ledger) if resume else 0.0
        guard = SpendGuard(approved_usd, spent=seed, ledger=ledger)  # one for every job
    _announce(phase, ", ".join(sorted({j.settings.model for j in jobs})), plan, approved_usd,
              seed, any(j.formats for j in jobs), say, stub)
    if stub:
        root.mkdir(parents=True, exist_ok=True)
        (root / STUB_MARKER).touch()
    out = {"phase": phase, "calls_planned": plan.calls, "estimate_usd": plan.estimate_usd,
           "headroom_usd": plan.headroom_usd, "stores": []}
    for job in jobs:
        client = _client(job.settings, library, scenarios, stub, sdks)
        if guard is not None:
            client = GuardedClient(client, guard, PARSE[client.settings.provider])
        sched = campaign.schedule(job.cells, job.scenarios, job.reps,
                                  prereg.schedule_seed + job.offset, formats=job.formats)
        if job.formats:
            store = _store(root, job.name, RecoveryRecord)
            campaign.recovery_runs(sched, client, job.scenarios, library, store, resume=resume)
        else:
            store = _store(root, job.name, CallRecord)
            campaign.single_turn(sched, client, job.scenarios, library, store, phase=job.name,
                                 resume=resume)
        out["stores"].append(str(store.path))
    if guard is not None:
        out["spent_usd"] = guard.spent - seed
        out["resumed_spent_usd"] = seed
        out["ledger"] = str(ledger.path)
    return out
