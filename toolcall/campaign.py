"""Single-turn and recovery runs, through the harness campaign loop.

A condition is one (cell, scenario) pair; a block is one repetition of every
condition, in an order `harness.scheduler.build_schedule` shuffles per block.
So repetitions of one condition are spread across the whole run rather than
fired back to back, and a provider-side change mid-run lands on every cell
alike rather than on whichever cell happened to be running.

`run_campaign` never retries a run in place and refuses a resume whose
schedule drifted (harness/campaign.py). Each phase and model gets its own store.
"""

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
            parsed = PARSE[provider](response)
            if parsed.model != model:
                error = f"model mismatch: asked for {model}, response names {parsed.model}"
        g = grade(parsed, by_id[sid], library, names, error=error)
        usage = parsed.usage if parsed else None
        return CallRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase=phase, model=model,
            returned_model=parsed.model if parsed else None, cell=cell.name,
            scenario_id=sid, settings=client.settings.to_dict(), request=request,
            response=response, error=error, clock_A=outcome.clock_A, grade=g.to_dict(),
            usage=usage, cost_usd=cost_usd(model, usage) if usage else None,
            rendered_tools=names,
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=on_run, resume=resume,
    )


def recovery_runs(schedule_, client, scenarios, library, store, *, resume: bool = False,
                  on_run=None):
    by_id = {s.id: s for s in scenarios}

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
        cost = sum(
            cost_usd(model, t["parsed"]["usage"]) for t in conv.turns if "parsed" in t
        )
        return RecoveryRecord(
            run_index=scheduled.run_index, block_index=scheduled.block_index,
            condition=scheduled.condition, run_id=run_id, phase="recovery", model=model,
            cell=cell.name, scenario_id=sid, error_kind=by_id[sid].recovery.error_kind,
            fmt=fmt, settings=client.settings.to_dict(), turns=conv.turns,
            first_grade=conv.first_grade, injected=conv.injected, recovered=conv.recovered,
            turns_to_recovery=conv.turns_to_recovery, identical_retry=conv.identical_retry,
            gave_up=conv.gave_up, hallucinated_success=conv.hallucinated_success,
            budget_exhausted=conv.budget_exhausted, excluded=conv.excluded, cost_usd=cost,
        )

    return run_campaign(
        schedule_, submit, build, store,
        index_of=lambda r: r.run_index, condition_of=lambda r: r.condition,
        on_run=on_run, resume=resume,
    )
