"""Single-turn and recovery runs, through the harness campaign loop.

A condition is one (cell, scenario) pair; a block is one repetition of every
condition, in an order `harness.scheduler.build_schedule` shuffles per block.
So repetitions of one condition are spread across the whole run rather than
fired back to back, and a provider-side change mid-run lands on every cell
alike rather than on whichever cell happened to be running.

`run_campaign` never retries a run in place and refuses a resume whose
schedule drifted (harness/campaign.py). Each phase and model gets its own store.
A resume also refuses a store written under another model, settings or phase:
two runs of different things would otherwise be spliced into one condition.

Two failure rules:

- After `CONSECUTIVE_FAILURE_LIMIT` API_ERROR records in a row the campaign
  raises `SystematicFailure`. A bad key, an unsupported parameter or a retired
  model would otherwise drain the approval with no data. The failed records
  stay stored, and any other record resets the count.
- A `SpendCapReached` raised mid-conversation discards that conversation's paid
  turns: nothing is stored for it, and a resume redoes it from turn 0. The
  guard has counted what those turns cost, so the spend record stays true.
"""

import hashlib
import json
import time

from harness.campaign import run_campaign
from harness.scheduler import build_schedule
from harness.submit import SubmitOutcome
from toolcall.formulation import Formulation, parse_cell, render
from toolcall.grader import grade
from toolcall.guard import SpendCapReached
from toolcall.prices import cost_usd
from toolcall.providers import PARSE
from toolcall.records import CallRecord, RecoveryRecord
from toolcall.recovery import converse

CONSECUTIVE_FAILURE_LIMIT = 10


class SystematicFailure(RuntimeError):
    """Too many API_ERROR records in a row to be chance."""


def _last_error(record) -> str:
    if isinstance(record, CallRecord):
        return record.error or record.grade["detail"]
    errors = [t["error"] for t in record.turns if "error" in t]
    return errors[-1] if errors else "no error recorded"


def _is_api_error(record) -> bool:
    if isinstance(record, CallRecord):
        return record.grade["category"] == "API_ERROR"
    return record.excluded == "API_ERROR"


def _fail_fast(on_run):
    """`on_run`, then a count of consecutive API_ERROR records that stops the run."""
    state = {"streak": 0}

    def watch(record):
        if on_run:
            on_run(record)
        if not _is_api_error(record):
            state["streak"] = 0
            return
        state["streak"] += 1
        if state["streak"] >= CONSECUTIVE_FAILURE_LIMIT:
            raise SystematicFailure(
                f"{state['streak']} API_ERROR records in a row; the last was: "
                f"{_last_error(record)}"
            )

    return watch


def _check_same_run(stored, *, model: str, settings: dict, phase: str | None = None) -> None:
    for r in stored:
        if r.model != model or r.settings != settings or (phase is not None
                                                          and r.phase != phase):
            raise ValueError(
                f"resume: stored run {r.run_index} was made with model {r.model!r}, "
                f"settings {r.settings} and phase {r.phase!r}; this run has model "
                f"{model!r}, settings {settings}"
                + (f" and phase {phase!r}" if phase is not None else "")
                + ". Resuming would put two different runs in one condition."
            )


def condition(cell: Formulation, scenario_id: str, fmt: str | None = None) -> str:
    return "|".join([cell.name, scenario_id] + ([fmt] if fmt else []))


def schedule(cells, scenarios, reps: int, seed: int, formats=None):
    """`formats` set: a recovery schedule, one condition per format as well."""
    conds = [
        condition(c, s.id, f)
        for c in cells
        for s in scenarios
        for f in (formats or [None])
    ]
    return build_schedule(conds, reps, seed)


def _split(cond: str) -> tuple[Formulation, str, str | None]:
    parts = cond.split("|")
    return parse_cell(parts[0]), parts[1], (parts[2] if len(parts) == 3 else None)


def single_turn(schedule_, client, scenarios, library, store, *, phase: str,
                resume: bool = False, on_run=None):
    by_id = {s.id: s for s in scenarios}
    provider = client.settings.provider
    rendered_cache: dict = {}
    if resume:
        _check_same_run(store.read_all(), model=client.settings.model,
                        settings=client.settings.to_dict(), phase=phase)

    def tools_for(cond):
        if cond not in rendered_cache:
            cell, sid, _ = _split(cond)
            rendered_cache[cond] = render(by_id[sid], library, cell)
        return rendered_cache[cond]

    def submit(scheduled, run_id):
        _, sid, _ = _split(scheduled.condition)
        tools = tools_for(scheduled.condition)
        body = client.request(tools, [{"role": "user", "text": by_id[sid].user_message}])
        t_submit = time.time()
        try:
            response = client.post(body)
        except SpendCapReached:
            raise
        except Exception as e:  # noqa: BLE001 -- a provider failure is a recorded outcome
            return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()}, None,
                                 f"{type(e).__name__}: {e}", {"request": body})
        return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()},
                             {"request": body, "response": response}, None)

    def build(scheduled, run_id, outcome):
        cell, sid, _ = _split(scheduled.condition)
        tools = tools_for(scheduled.condition)
        names = [t["name"] for t in tools]
        model = client.settings.model
        error, parsed, response = outcome.error, None, None
        request = (outcome.payload or outcome.diagnostics or {}).get("request")
        if outcome.payload is not None:
            response = outcome.payload["response"]
            try:
                parsed = PARSE[provider](response)
            except SpendCapReached:
                raise
            except Exception as e:  # noqa: BLE001 -- a malformed response is data, not a crash
                # The guard has already charged the call, so the spend is counted.
                error = f"unparseable response: {type(e).__name__}: {e}"
            if parsed is not None and parsed.model != model:
                error = f"model mismatch: asked for {model}, response names {parsed.model}"
        usage = parsed.usage if parsed else None
        # The parsers' placeholder for a missing usage is all zeros; that is not
        # a measurement of a free call. A call that returned nothing parseable
        # was charged by the guard too, so it is unmetered for the same reason.
        unmetered = usage is None or (usage["input"] == 0 and usage["output"] == 0)
        if unmetered:
            usage = None
            if error is None and parsed is not None:
                # An otherwise valid response that reports no tokens: billed (the
                # guard charged it one bound) but with no cost to put in the cost
                # analysis, which refuses a graded call without one. So it is
                # excluded as API_ERROR, never graded; the response stays stored.
                error = ("response carries no usable usage (all zero), so the call "
                         "cannot be metered and is excluded (a paid call is charged "
                         "one bound by the spend guard)")
        g = grade(parsed, by_id[sid], library, names, error=error)
        return CallRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase=phase, model=model,
            returned_model=parsed.model if parsed else None, cell=cell.name,
            scenario_id=sid, settings=client.settings.to_dict(), request=request,
            response=response, error=error, clock_A=outcome.clock_A, grade=g.to_dict(),
            usage=usage, cost_usd=cost_usd(model, usage) if usage else None,
            rendered_tools=names, unmetered=unmetered,
            request_sha256=(hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
                            if request is not None else None),
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=_fail_fast(on_run), resume=resume,
    )


def recovery_runs(schedule_, client, scenarios, library, store, *, resume: bool = False,
                  on_run=None):
    by_id = {s.id: s for s in scenarios}
    if resume:
        _check_same_run(store.read_all(), model=client.settings.model,
                        settings=client.settings.to_dict())

    def submit(scheduled, run_id):
        cell, sid, fmt = _split(scheduled.condition)
        t_submit = time.time()
        conv = converse(client, by_id[sid], library, cell, fmt)
        return SubmitOutcome({"t_submit": t_submit, "t_result": time.time()},
                             {"conversation": conv}, None)

    def build(scheduled, run_id, outcome):
        cell, sid, fmt = _split(scheduled.condition)
        conv = outcome.payload["conversation"]
        model = client.settings.model

        def metered(t):
            u = t["parsed"]["usage"] if "parsed" in t else None
            return u is not None and (u["input"] != 0 or u["output"] != 0)

        cost = sum(cost_usd(model, t["parsed"]["usage"]) for t in conv.turns if metered(t))
        return RecoveryRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase="recovery", model=model,
            cell=cell.name, scenario_id=sid, error_kind=by_id[sid].recovery.error_kind,
            fmt=fmt, settings=client.settings.to_dict(), turns=conv.turns,
            first_grade=conv.first_grade, injected=conv.injected, recovered=conv.recovered,
            turns_to_recovery=conv.turns_to_recovery, identical_retry=conv.identical_retry,
            gave_up=conv.gave_up, hallucinated_success=conv.hallucinated_success,
            budget_exhausted=conv.budget_exhausted, excluded=conv.excluded, cost_usd=cost,
            returned_models=[t["parsed"]["model"] for t in conv.turns if "parsed" in t],
            unmetered_turns=sum(1 for t in conv.turns if not metered(t)),
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=_fail_fast(on_run), resume=resume,
    )
