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
        # A failed run keeps whatever the worker managed to report. A
        # health-timeout returns its log lines with healthy=False, and those
        # lines are the only evidence of why the engine never came up --
        # timings alone cannot distinguish a hang from a crash from a slow
        # download. Storing them costs a few KB on a run that already cost
        # real GPU time; discarding them makes the failure permanently
        # unexplainable, and failures are the rows most in need of explaining.
        diag = outcome.diagnostics or {}
        diag_lines = diag.get("log_lines") or []
        failed_engine: dict = {}
        if diag_lines:
            diag_parsed = parse_engine_log("\n".join(diag_lines))
            failed_engine = {
                **diag_parsed.engine_info,
                "log_lines": diag_lines,
                # How far startup actually got before it stalled.
                "s4_subphases": diag_parsed.phases,
                "s4_merged": diag_parsed.merged,
            }
        return RunRecord(
            run_id=run_id,
            run_index=scheduled.run_index,
            arm=scheduled.arm,
            clock_A=outcome.clock_A,
            clock_C={},
            clock_B=diag.get("clock_B", {}),
            warmup=diag.get("warmup", []),
            engine=failed_engine,
            host={},
            config={},
            status={
                "outcome": "failed",
                "failure_class": classify_failure(outcome.error).value,
                "failure_detail": outcome.error,
            },
        )

    p = outcome.payload

    # A transport-level success (outcome.error is None) is not the same thing
    # as a telemetry-complete one. worker/handler.py sets both of these
    # fields unconditionally on every real run, so either being absent here
    # means something between the engine and the store dropped data -- a
    # worker bug, a truncated payload, a `.get(..., None)` upstream
    # swallowing what should have been a KeyError.
    #
    # This cannot be left for metrics.derive()'s arm-state gate to catch by
    # itself: that gate treats an absent field as "unknown, not a violation"
    # *on purpose* -- fixtures and every historical record genuinely never
    # had these fields, and treating their absence as a mismatch would
    # discard all of them. A live run that should have both fields and is
    # missing one looks, from engine/config alone, IDENTICAL to a historical
    # row that never had them -- derive() cannot tell the two apart from the
    # record's data. Only the driver knows which situation this is, so it
    # says so explicitly: see the `arm_state_unverifiable` flag on `status`
    # below, and metrics.derive() for how it acts on that flag.
    #
    # This is still an "ok" run, not a failed one: the run completed and
    # produced real, paid-for telemetry -- t_weights, the S4 waterfall,
    # warmup latencies -- none of which depend on the two fields that are
    # missing. docs/experiment.md publishes failure rate and discard rate as
    # two distinct signals: failure means the run produced no usable result
    # (OOM, timeout, image pull, ...); discard means the run completed but
    # violates an invariant. A dropped telemetry field between engine and
    # store is the latter -- a plumbing bug, not an engine/infra failure --
    # and folding it into "failed" would both inflate the failure rate with
    # something that isn't one, and permanently throw away every other
    # metric this run measured (derive() returns a bare 6-key row for any
    # non-ok run).
    observed = p.get("compile_cache_observed")
    expected = (p.get("cache_config") or {}).get("compile_cache_warm")
    arm_state_unverifiable = observed is None or expected is None

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
            # The raw engine output this run's parsed values came from. Kept
            # because the artifact's published claim is that a reader can
            # re-derive every number from the committed records without a GPU
            # -- without these, `s4_subphases` can only be trusted, not
            # re-derived, and a parser bug found after the campaign would make
            # the whole dataset unrepeatable rather than re-parseable. It is
            # also what verifies the engine's dtype per run (spec 10). Roughly
            # 15 KB per run; a 300-run campaign stores a few MB.
            "log_lines": p.get("log_lines", []),
            "s4_subphases": parsed.phases,
            "s4_merged": parsed.merged,
            # The detector for a compile cache leaking into a cold arm: the
            # arm says what was configured, this is what was on disk BEFORE
            # the run started (worker/handler.py snapshots it ahead of
            # run_probe -- see that module for why the timing matters).
            "compile_cache_observed": observed,
            # Diagnostic only, never read by the arm-state gate: the same
            # check taken again after the run. A cold arm should flip
            # False -> True (its own compile wrote the cache); staying
            # False -> False on a cold arm means the compile never wrote a
            # cache at all, worth seeing even though it doesn't fail the
            # gate. Carried through here so it survives to the stored
            # record rather than being dropped after the handler computes
            # it.
            "compile_cache_present_after": p.get("compile_cache_present_after"),
        },
        # Copied, not aliased: the payload's dict is the endpoint's, and
        # triple_index is stamped onto the record's copy below.
        host=dict(p.get("host", {})),
        # The worker returns this as `cache_config` -- what the arm actually
        # resolved to, so the analysis can verify the arm from the record
        # rather than trusting its label.
        config=p.get("cache_config", {}),
        status={
            "outcome": "ok",
            "failure_class": None,
            "failure_detail": None,
            # Present and True only when this "ok" payload is missing
            # compile_cache_observed and/or cache_config.compile_cache_warm.
            # Absent (the ordinary case) means "known verifiable" -- only
            # the driver ever sets this key; metrics.derive() only reads it.
            # Omitted rather than always-present-and-False so every existing
            # record and fixture that predates this flag round-trips through
            # RunRecord unchanged.
            **({"arm_state_unverifiable": True} if arm_state_unverifiable else {}),
        },
    )


def run_campaign(submitter, store, arms, triples, seed, on_run=None, resume=False):
    """One record per scheduled run. Never retries in place -- see spec 6.6.

    `resume=True` skips runs already present in the store, keyed by
    `run_index`. The schedule is rebuilt from the same `arms`/`triples`/`seed`,
    so a resumed window continues the original interleaving rather than
    generating a new one -- interleaving is the design's most important
    validity property and a fresh schedule would change which arm runs when.

    Callers MUST pass the exact `arms`/`triples`/`seed` of the window being
    resumed. Nothing on disk records which schedule produced the stored rows,
    and a runner script typically takes these as command-line arguments, so a
    typo'd seed or triple count is realistic. Passed a drifted value, this
    function would otherwise splice two different interleavings into one
    store -- exactly the confound interleaving exists to prevent -- and
    nothing downstream would ever reveal it, since the resulting store still
    looks like one well-formed campaign. To turn that silent corruption into
    a loud failure, every stored row whose `run_index` falls within the
    freshly-built schedule is checked against the arm that schedule assigns
    to it; a mismatch raises `ValueError`. A stored `run_index` past the end
    of the rebuilt schedule (e.g. resuming with fewer `triples` than the
    original window) is the same class of drift and also raises.

    Off by default: silently skipping runs an operator asked for is a worse
    failure than repeating them.

    The drift guard assumes the store holds only this campaign's records. A
    store that accumulated several independent, non-resumed campaigns (which
    `resume=False` permits) would have its every record checked against this
    schedule, so a legitimate resume could be refused. Give each campaign its
    own store file.
    """
    schedule = build_schedule(arms=arms, triples=triples, seed=seed)
    done: set[int] = set()
    if resume:
        arm_by_index = {s.run_index: s.arm for s in schedule}
        for r in store.read_all():
            expected_arm = arm_by_index.get(r.run_index)
            if expected_arm is None:
                raise ValueError(
                    f"resume: stored run_index {r.run_index} falls beyond the "
                    f"rebuilt schedule, which only covers 0..{len(schedule) - 1} "
                    f"for the given arms/triples/seed. This means resume was "
                    f"called with different schedule parameters (e.g. fewer "
                    f"triples) than produced the stored data -- resume must use "
                    f"the exact arms/triples/seed of the original window."
                )
            if r.arm != expected_arm:
                raise ValueError(
                    f"resume: stored run_index {r.run_index} has arm "
                    f"{r.arm!r} on disk, but the rebuilt schedule assigns it "
                    f"arm {expected_arm!r}. This means resume was called with "
                    f"different arms/triples/seed than produced the stored "
                    f"data, which would splice two different interleavings "
                    f"together -- resume must use the exact arms/triples/seed "
                    f"of the original window."
                )
            done.add(r.run_index)
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
