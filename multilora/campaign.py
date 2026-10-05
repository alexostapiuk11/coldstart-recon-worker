"""Artifact 5's use of the harness campaign loop: what one job asks the worker
to do, and how its outcome becomes a stored record."""

from harness.campaign import run_campaign
from harness.scheduler import ScheduledRun
from multilora.conditions import (
    GATE,
    SWEEP,
    condition_name,
    parse_condition,
    phase_plan,
    real_name,
    registered_adapters,
)
from multilora.prereg import Preregistration
from multilora.records import build_record


def job_payload(scheduled, run_id: str, prereg: Preregistration) -> dict:
    condition = parse_condition(scheduled.condition, prereg)
    return {
        "run_id": run_id,
        "run_index": scheduled.run_index,
        "condition": condition.name,
        "n_slots": condition.n_slots,
        "registered": list(registered_adapters(condition, prereg)),
        "specialize_active_lora": condition.specialize_active_lora,
        "disable_log_stats": condition.disable_log_stats,
        "phases": [
            {"phase_index": p.phase_index, "regime": p.regime, "adapters": list(p.adapters)}
            for p in phase_plan(condition, prereg, scheduled.run_index)
        ],
        "concurrency": prereg.concurrency,
        "requests_per_phase": prereg.requests_per_phase,
        "warmup_requests_per_adapter": prereg.warmup_requests_per_adapter,
        "scrape_interval_s": prereg.scrape_interval_s,
        "adapter_seed": prereg.schedule_seed,
        "dataset_args": list(prereg.bench_dataset_args),
        "real_adapters": [
            {"name": real_name(i), "repo": repo, "revision": revision}
            for i, (repo, revision) in enumerate(prereg.real_adapters)
        ]
        if condition.kind == GATE
        else [],
    }


def run(schedule, submitter, store, prereg: Preregistration, *, resume=False, on_run=None):
    """`submitter` is anything with `submit_payload(payload) -> SubmitOutcome`:
    the harness RunPod submitter, or `harness.submit.PayloadStubSubmitter`
    around `multilora.stub.StubInstanceEndpoint.run`."""
    return run_campaign(
        schedule,
        lambda scheduled, run_id: submitter.submit_payload(job_payload(scheduled, run_id, prereg)),
        build_record,
        store,
        index_of=lambda r: r.run_index,
        condition_of=lambda r: r.condition,
        on_run=on_run,
        resume=resume,
    )


def priming_payloads(prereg: Preregistration) -> list[tuple[ScheduledRun, dict]]:
    """Two untimed starts per sweep point (amendment §3d). The compile cache is
    keyed on max_loras, so each point compiles on its first start; the second
    must then read warm. Priming runs go to their own store and are never data."""
    out = []
    index = 0
    for n in prereg.sweep:
        for attempt in (0, 1):
            scheduled = ScheduledRun(index, attempt, condition_name(SWEEP, n))
            payload = job_payload(scheduled, f"prime-N{n}-{attempt}", prereg)
            payload["phases"] = []
            payload["warmup_requests_per_adapter"] = 1
            out.append((scheduled, payload))
            index += 1
    return out


def priming_verdict(records) -> dict:
    """Per sweep point: the second start must be warm. Anything else means the
    campaign would open on cold compiles, and must not start."""
    by_n: dict[str, dict] = {}
    for rec in records:
        state = rec.engine.get("compile_state") if rec.outcome == "ok" else "failed"
        by_n.setdefault(rec.condition, {})[rec.block_index] = state
    return {
        cond: {"first": s.get(0), "second": s.get(1), "ok": s.get(1) == "warm"}
        for cond, s in by_n.items()
    }
