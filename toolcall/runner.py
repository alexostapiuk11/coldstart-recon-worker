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
rule (`analysis.ranked_cells`), so those phases cannot start before it ends.

Headroom. `SpendGuard.before` refuses a call when spent + bound x (1 +
SDK_MAX_RETRIES) would pass the approval, so an approval equal to the estimate
would stop a phase before its last calls. The phase therefore also needs
`headroom_usd`: the dearest worst-case bound among its first-turn request
bodies (doubled for recovery, whose later turns carry the history).

Resuming. A resumed paid phase seeds its guard with what its stored records
already cost (`stored_spend_usd`), so the approved amount caps the whole phase
across resumes. The seed is never less than what the guard charged for a stored
record. One thing it cannot see: a conversation cut off by `SpendCapReached`
stores nothing (toolcall/campaign.py), so its paid turns are counted by the
session that ran them but not by a later resume's seed.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

from harness.store import JsonlStore
from toolcall import campaign
from toolcall.analysis import ranked_cells
from toolcall.formulation import BASELINE, CELLS, Formulation, parse_cell, render
from toolcall.guard import (
    SDK_MAX_RETRIES,
    TOKENIZER_FACTOR,
    GuardedClient,
    SpendGuard,
    call_bound_usd,
    check_estimate,
)
from toolcall.prices import PRICES
from toolcall.providers import PARSE, Client, ScriptedClient
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.stub import StubModel

FORMATS = ("actionable", "opaque")
OUTPUT_TOKENS_ESTIMATE = 200
THINKING_TOKENS_ESTIMATE = 300  # Sonnet 5.5 with between_tools; amendment §8's assumption
CHARS_PER_TOKEN = 4.0  # an estimate, not a bound; the guard's bound is in toolcall.guard
RECOVERY_TURNS_ESTIMATE = 3
PHASES = ("pilot-baseline", "pilot-cells", "pilot-slice", "pilot-recovery", "campaign",
          "recovery", "slice", "exploratory")


class Job(NamedTuple):
    name: str  # the store's name
    settings: object
    cells: list
    scenarios: list
    reps: int
    formats: tuple | None
    offset: int  # added to the schedule seed


class Plan(NamedTuple):
    calls: int
    estimate_usd: float
    headroom_usd: float


def estimate_call_usd(settings, tools: list[dict], user_message: str) -> float:
    """An upper-leaning estimate from the size of what will be sent. The guard
    then meters the real usage; this only decides whether to start."""
    chars = len(json.dumps(tools)) + len(user_message) + 400
    tokens_in = chars / CHARS_PER_TOKEN * TOKENIZER_FACTOR[settings.provider]
    out = OUTPUT_TOKENS_ESTIMATE + (THINKING_TOKENS_ESTIMATE if settings.thinking else 0)
    p = PRICES[settings.model]
    return (tokens_in * p.input + out * p.output) / 1e6


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
    a call whose post raised was charged the bound times 1 + SDK_MAX_RETRIES."""
    return sum(_recovery_charge(r, settings) if isinstance(r, RecoveryRecord)
               else _call_charge(r, settings) for r in records)


def _store(root: Path, name: str, cls):
    return JsonlStore(root / f"{name}.jsonl", cls)


def _client(settings, library, scenarios, stub: bool, sdk=None):
    if stub:
        if settings.provider != "openai":
            settings = replace(settings, provider="openai", thinking=None,
                               reasoning_effort="none")
        return ScriptedClient(settings, StubModel(library, scenarios, seed=0,
                                                  model=settings.model))
    return Client(settings, sdk=sdk)


def _plan(job: Job, library) -> Plan:
    """Calls, estimated USD, and the dearest worst-case bound of one first-turn
    request, built by the real client's request builder."""
    builder = Client(job.settings)
    total, calls, worst = 0.0, 0, 0.0
    n = job.reps * (len(job.formats) * RECOVERY_TURNS_ESTIMATE if job.formats else 1)
    for cell in job.cells:
        for s in job.scenarios:
            tools = render(s, library, cell)
            total += n * estimate_call_usd(job.settings, tools, s.user_message)
            calls += n
            body = builder.request(tools, [{"role": "user", "text": s.user_message}])
            worst = max(worst, call_bound_usd(job.settings, body) * (1 + SDK_MAX_RETRIES))
    return Plan(calls, total, worst * (2 if job.formats else 1))


def _announce(phase, models, plan: Plan, approved, seed, say):
    msg = (f"{phase} on {models}: {plan.calls:,} calls, estimated ${plan.estimate_usd:.2f}"
           f" + ${plan.headroom_usd:.2f} guard headroom; approved ${approved:.2f}")
    if seed:
        msg += f"; resuming with ${seed:.2f} already spent by this phase's stored records"
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
    ranks = ranked_cells(done, p)
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


def run_phase(phase: str, prereg, library, scenarios, root, *, approved_usd: float = 0.0,
              stub: bool = False, resume: bool = False, say=print, sdk=None) -> dict:
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; one of {PHASES}")
    root = Path(root)
    jobs = _jobs(phase, prereg, library, scenarios, root)
    plans = [_plan(job, library) for job in jobs]
    plan = Plan(sum(x.calls for x in plans), sum(x.estimate_usd for x in plans),
                max((x.headroom_usd for x in plans), default=0.0))
    seed = 0.0
    if resume and not stub:
        for job in jobs:
            cls = RecoveryRecord if job.formats else CallRecord
            seed += stored_spend_usd(_store(root, job.name, cls).read_all(), job.settings)
    _announce(phase, ", ".join(sorted({j.settings.model for j in jobs})), plan, approved_usd,
              seed, say)
    guard = None
    if not stub:
        check_estimate(plan.estimate_usd + plan.headroom_usd, approved_usd)
        guard = SpendGuard(approved_usd, spent=seed)  # one guard for every job of the phase
    out = {"phase": phase, "calls_planned": plan.calls, "estimate_usd": plan.estimate_usd,
           "headroom_usd": plan.headroom_usd, "stores": []}
    for job in jobs:
        client = _client(job.settings, library, scenarios, stub, sdk)
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
    return out
