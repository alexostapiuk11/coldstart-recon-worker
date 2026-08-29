"""End-to-end orchestration: schedule -> submit -> record -> store."""

import uuid

from coldstart.checks import classify_failure
from coldstart.scheduler import build_schedule
from coldstart.schema import RunRecord
from coldstart.vllm_logs import parse_engine_log


def _new_run_id() -> str:
    """Generated before the job is submitted, not after it returns.

    The arm's cache paths are namespaced by this id (`CacheConfig.env`), so it
    has to exist before the endpoint runs. Adopting the platform's job id
    afterwards would leave the record naming a different id than the one whose
    directories the run actually used, and `cache_config`'s promise that the
    configuration is reproducible from a stored `RunRecord.run_id` would be
    false. `run_id` must also contain no "/" -- `CacheConfig.env` rejects that,
    and a uuid4 hex string cannot produce one.
    """
    return uuid.uuid4().hex


def _record_from(scheduled, run_id: str, outcome) -> RunRecord:
    if outcome.error is not None:
        return RunRecord(
            run_id=run_id,
            run_index=scheduled.run_index,
            arm=scheduled.arm,
            clock_A=outcome.clock_A,
            clock_C={},
            clock_B={},
            warmup=[],
            engine={},
            host={},
            config={},
            status={
                "outcome": "failed",
                "failure_class": classify_failure(outcome.error).value,
                "failure_detail": outcome.error,
            },
        )

    p = outcome.payload
    parsed = parse_engine_log("\n".join(p.get("log_lines", [])))
    return RunRecord(
        run_id=run_id,
        run_index=scheduled.run_index,
        arm=scheduled.arm,
        clock_A=outcome.clock_A,
        clock_C=p.get("clock_C", {}),
        clock_B=p.get("clock_B", {}),
        warmup=p.get("warmup", []),
        engine={
            **parsed.engine_info,
            "s4_subphases": parsed.phases,
            "s4_merged": parsed.merged,
            # The detector for a compile cache leaking into a cold arm: the
            # arm says what was configured, this says what was on disk.
            "compile_cache_observed": p.get("compile_cache_observed"),
        },
        # Copied, not aliased: the payload's dict is the endpoint's, and
        # triple_index is stamped onto the record's copy below.
        host=dict(p.get("host", {})),
        # The worker returns this as `cache_config` -- what the arm actually
        # resolved to, so the analysis can verify the arm from the record
        # rather than trusting its label.
        config=p.get("cache_config", {}),
        status={"outcome": "ok", "failure_class": None, "failure_detail": None},
    )


def run_campaign(submitter, store, arms, triples, seed, on_run=None, resume=False):
    """One record per scheduled run. Never retries in place -- see spec 6.6.

    `resume=True` skips runs already present in the store, keyed by
    `run_index`. The schedule is rebuilt from the same `arms`/`triples`/`seed`,
    so a resumed window continues the original interleaving rather than
    generating a new one -- interleaving is the design's most important
    validity property and a fresh schedule would change which arm runs when.

    Off by default: silently skipping runs an operator asked for is a worse
    failure than repeating them.
    """
    schedule = build_schedule(arms=arms, triples=triples, seed=seed)
    done: set[int] = set()
    if resume:
        done = {r.run_index for r in store.read_all()}
    for scheduled in schedule:
        if scheduled.run_index in done:
            continue
        run_id = _new_run_id()
        outcome = submitter.submit(arm=scheduled.arm, run_id=run_id)
        record = _record_from(scheduled, run_id, outcome)
        record.host["triple_index"] = scheduled.triple_index
        store.append(record)
        if on_run:
            on_run(record)
    return store
