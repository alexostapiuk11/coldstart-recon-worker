import statistics
from typing import TypedDict

from coldstart.checks import DiscardReason, check_consistency, compute_residual
from coldstart.schema import RunRecord

FAST_TOLERANCE = 0.10  # fixed before data — see spec 7

# The five named S4 sub-phases, spec stage taxonomy. Order matters for the
# waterfall (chronological: device init -> compile -> memory profiling ->
# KV allocation -> graph capture), not just for iteration.
S4_SUBPHASE_KEYS = ("S4a", "S4b", "S4c", "S4d", "S4e")


class DerivedRow(TypedDict, total=False):
    """One derived row: the interface between the harness and every published
    figure. `total=False` because a failed run (six keys: ok, arm, host_id,
    triple_index, consistent, failure_class) and an ok run (twenty keys) are
    genuinely different contracts, not a partially-filled version of each
    other — see `derive`.
    """

    ok: bool
    arm: str
    host_id: str | None
    triple_index: int | None
    failure_class: str | None
    t_total: float | None
    t_total_job: float
    t_process: float
    t_platform: float | None
    t_weights: float | None
    t_s2_to_ready: float | None
    merged_phases: list[str]
    s4_subphases: dict
    t_s1: float | None
    t_s4_bracket: float | None
    t_s4a: float | None
    t_s4b: float | None
    t_s4c: float | None
    t_s4d: float | None
    t_s4e: float | None
    t_compile: float | None
    s4_unattributed: float | None
    t_s5: float | None
    t_s6: float | None
    warmup: list[dict]
    steady_state_latency: float | None
    warmup_penalty: float | None
    time_to_fast_index: int | None
    kv_cache_blocks: int | None
    kv_capacity_tokens: int | None
    consistent: bool
    inconsistency_reason: str | None
    discard_reason: DiscardReason | None


def _marks(record: RunRecord) -> dict[str, float]:
    return {m["stage"]: m["t_mono"] for m in record.clock_B.get("marks", [])}


def _require_mark(marks: dict[str, float], stage: str, record: RunRecord) -> float:
    """Fail loudly, but never anonymously — mid-campaign a bare KeyError gives
    no way to find the offending run."""
    try:
        return marks[stage]
    except KeyError as exc:
        raise KeyError(
            f"run {record.run_id!r} (arm {record.arm!r}): missing required stage mark {stage!r}"
        ) from exc


def steady_state_latency(warmup: list[dict]) -> float | None:
    """Median end-to-end latency of the last three warmup requests — spec 7.

    Extracted as a named function (rather than inlined in `derive`) because
    the plan reuses this exact definition in `worker/probe.py` (Task 11);
    importing it from here keeps the two sites from drifting apart.
    """
    if not warmup:
        return None
    return statistics.median(w["end_to_end"] for w in warmup[-3:])


def warmup_penalty(warmup: list[dict], steady: float | None) -> float | None:
    """Ratio of the first warmup request's latency to steady state.

    Undefined when steady state is exactly zero — an implausible latency
    reading that must not be silently reported as "no penalty" (that would
    conflate it with the "no warmup data" case) nor crash the batch with a
    ZeroDivisionError. Both are treated as None; the `consistent`/reason
    machinery is not extended to warmup data, so there is nowhere else to
    surface the anomaly.
    """
    if not warmup or steady is None or steady <= 0:
        return None
    return warmup[0]["end_to_end"] / steady


def time_to_fast_index(
    warmup: list[dict], steady: float | None, tolerance: float = FAST_TOLERANCE
) -> int | None:
    """First request index whose latency lands within `tolerance` of steady state."""
    if steady is None:
        return None
    threshold = steady * (1.0 + tolerance)
    for w in warmup:
        if w["end_to_end"] <= threshold:
            return w["req_index"]
    return None


def ceiling_bound(t_weights: float, t_total: float) -> float:
    """Largest fraction of T_total removable if T_weights went to zero."""
    if t_total <= 0:
        raise ValueError(f"t_total must be positive, got {t_total}")
    if not (0 <= t_weights <= t_total):
        raise ValueError(f"t_weights {t_weights} must be within [0, t_total={t_total}]")
    return t_weights / t_total


def derive(record: RunRecord) -> DerivedRow:
    if record.status["outcome"] != "ok":
        # A failed run never reaches stage marks or clocks, but it still
        # needs to be countable by arm and by host — that's what feeds the
        # failure-rate tables and keeps FailureClass reachable from analysis.
        return {
            "ok": False,
            "arm": record.arm,
            "host_id": record.host.get("host_id"),
            "triple_index": record.host.get("triple_index"),
            "consistent": False,
            "failure_class": record.status.get("failure_class"),
        }

    m = _marks(record)
    t_process = _require_mark(m, "S6_first_token", record)

    # `t_result` is stamped by the driver after the worker job returns — that
    # is after all ten warmup requests (S7), not at first token (S6), the
    # spec's T_total boundary (spec 7: "T_total | clock A, submit -> first
    # token of request 1"). Left uncorrected, T_platform silently absorbs
    # requests 2-10 plus the result round trip: this was B1. `t_total_job` is
    # that raw span; it is real data and stays in the published row, but it
    # is not T_total.
    t_total_job = record.clock_A["t_result"] - record.clock_A["t_submit"]

    # Correct it by subtracting the clock-B duration from first token to end
    # of job: T_total = (t_result - t_submit) - (S7_warmup_done -
    # S6_first_token). Spec 6.5 rule 1 forbids subtracting a clock-B
    # *timestamp* from a clock-A *timestamp* to obtain a duration — that is
    # an absolute cross-clock comparison, and it is what the rule and rule
    # 2's single named exception (T_platform) are guarding. This is a
    # different operation: both operands here are *durations*, each already
    # computed from timestamps within one clock domain (t_total_job from
    # clock A alone; the warmup tail from clock B alone), combined only
    # after that. It does not compare absolute readings across clocks and
    # does not add a second cross-domain subtraction — T_platform is still
    # computed exactly once below, from this corrected T_total.
    t_warmup_end = m.get("S7_warmup_done")
    if t_warmup_end is None:
        # A run that reached first token and then failed or was cut off
        # mid-warmup, before S7 was marked, is a real, expected state — not
        # a defect to paper over. Falling back to the uncorrected
        # t_total_job here would silently reintroduce B1 for exactly the
        # runs most likely to be anomalous, so instead: no T_total is
        # computed at all, the run is flagged inconsistent with a
        # tabulatable, dedicated discard reason, and t_total_job (still
        # real) is the only span published for it.
        t_total: float | None = None
        consistent = False
        reason: str | None = (
            f"run {record.run_id!r} (arm {record.arm!r}): S7_warmup_done missing, "
            "cannot compute the T_total warmup-tail correction"
        )
        discard_reason: DiscardReason | None = DiscardReason.MISSING_WARMUP_END
    else:
        warmup_tail = t_warmup_end - t_process
        if warmup_tail < 0:
            # S7 preceding S6 is impossible on a monotonic clock B — this is
            # corrupted data, not a borderline measurement, so (like a
            # missing required mark above) it must not be folded quietly
            # into "just another inconsistent run".
            raise ValueError(
                f"run {record.run_id!r} (arm {record.arm!r}): negative T_total "
                f"correction term {warmup_tail}: S7_warmup_done precedes S6_first_token, "
                "which is impossible on a monotonic clock"
            )
        t_total = t_total_job - warmup_tail
        checked = check_consistency(t_total=t_total, t_process=t_process)
        # Carry all three ConsistencyResult fields through: discard_reason is
        # a closed enum specifically so a downstream reader can tabulate
        # discards by class instead of substring-matching the free-form
        # `reason` string.
        #
        # This check is now *tighter* than before the B1 fix. Uncorrected,
        # t_total included the full warmup tail (tens of seconds in these
        # fixtures), so t_process could never realistically approach it and
        # "t_process must not exceed t_total" was nearly impossible to trip.
        # With the correction applied, t_total is t_process plus only the
        # true platform residual, so this same check now actually catches
        # clock skew and submit/result bookkeeping bugs that the inflated
        # t_total was masking.
        consistent, reason, discard_reason = checked.ok, checked.reason, checked.discard_reason

    # T_weights = S2 + S3 (spec, stage taxonomy). The volume arms may memory-map
    # weights, fusing acquisition and HBM load with no clean boundary between
    # them, which is exactly why the pair is the primary unit rather than S2
    # alone. If the engine did not delineate the load boundary at all, the phase
    # is reported merged rather than silently widened to S5_ready — widening it
    # would swallow the whole of S4, including the compile term.
    t_acq_start = m.get("S2_acquisition_start")
    t_load_done = m.get("S3_load_done")
    t_ready = m.get("S5_ready")
    merged: list[str] = []
    if t_acq_start is None:
        merged.append("S2")
    if t_load_done is None:
        merged.append("S3")

    t_weights: float | None
    if merged:
        t_weights = None
    else:
        t_weights = t_load_done - t_acq_start
        # A stage duration is an intra-clock quantity, so it earns the same
        # discipline compute_residual applies on the cross-clock path: a
        # negative or out-of-bounds duration means the run is broken, not
        # that the number needs correcting (e.g. abs()) before publication.
        if t_weights < 0:
            consistent = False
            reason = (
                f"t_weights {t_weights} is negative: S3_load_done precedes S2_acquisition_start"
            )
            t_weights = None
        elif t_weights > t_process:
            consistent = False
            reason = f"t_weights {t_weights} exceeds t_process {t_process}"
            t_weights = None

    t_s2_to_ready = (
        t_ready - t_acq_start if t_acq_start is not None and t_ready is not None else None
    )

    # S4 bracket (B2/B3 fix). No mark delineated S4 before this fix; the
    # tempting substitute S5_ready - S3_load_done is NOT the bracket -- S5
    # is a separate, later stage (spec, stage taxonomy: "S5 ready: engine up
    # -> server reports healthy", a health-poll interval), so that
    # substitution would fold all of S5 into S4 and misattribute exactly the
    # quantity this fix exists to get right. The mark contract
    # (S4_start/S4_end) is added here for analysis; the probe that emits
    # them (Task 11) is not yet built, so both marks are legitimately
    # absent on every real run today -- handled the same way a missing
    # S2/S3 mark already is, never substituted.
    t_s4_start = m.get("S4_start")
    t_s4_end = m.get("S4_end")
    if t_s4_start is None:
        merged.append("S4_start")
    if t_s4_end is None:
        merged.append("S4_end")

    t_s4_bracket: float | None
    if t_s4_start is None or t_s4_end is None:
        t_s4_bracket = None
    else:
        t_s4_bracket = t_s4_end - t_s4_start
        # Same discipline as t_weights above: a stage duration is an
        # intra-clock quantity, so a negative one means the run is broken,
        # not that it needs correcting before publication.
        if t_s4_bracket < 0:
            consistent = False
            reason = f"t_s4_bracket {t_s4_bracket} is negative: S4_end precedes S4_start"
            t_s4_bracket = None

    # S4 sub-phases (S4a-S4e), extracted from the pinned engine version's
    # parsed startup log into explicit fields — B3. A sub-phase this engine
    # version did not delineate is absent, not zero: the same merged_phases
    # policy already applied to S2/S3 above, not a silent .get(k, 0.0).
    raw_subphases = record.engine.get("s4_subphases") or {}
    subphase_values: dict[str, float | None] = {}
    for key in S4_SUBPHASE_KEYS:
        if key in raw_subphases:
            subphase_values[key] = raw_subphases[key]
        else:
            subphase_values[key] = None
            merged.append(key)

    # T_compile — spec stage taxonomy: "S4b, cold minus warm, the
    # compile-cache term". This field is the per-run S4b duration;
    # economics.compile_cache_term(s4b_cold, s4b_warm) combines two arms'
    # medians of it into the actual contrast. Before this fix nothing
    # produced either input (B3).
    t_compile = subphase_values["S4b"]

    identified_sum = sum(v for v in subphase_values.values() if v is not None)
    s4_unattributed: float | None
    if t_s4_bracket is None:
        s4_unattributed = None
    else:
        s4_unattributed = t_s4_bracket - identified_sum
        # Same discipline as t_weights and t_s4_bracket above: the
        # identified sub-phases not fitting inside the bracket that is
        # supposed to contain them means the decomposition is broken for
        # this run, not that the remainder needs clamping to zero.
        if s4_unattributed < 0:
            consistent = False
            reason = (
                f"s4_unattributed {s4_unattributed} is negative: identified S4 "
                f"sub-phases ({identified_sum}) exceed the S4 bracket ({t_s4_bracket})"
            )
            s4_unattributed = None

    t_s1 = m.get("S1_imports_done")
    # S5 starts at "engine up", i.e. S4_end -- not S3_load_done, for the
    # same reason the bracket above never substitutes it.
    t_s5 = t_ready - t_s4_end if (t_ready is not None and t_s4_end is not None) else None
    t_s6_dispatch = m.get("S6_request1_dispatch")
    t_s6 = t_process - t_s6_dispatch if t_s6_dispatch is not None else None

    blocks = record.engine.get("kv_cache_blocks")
    block_size = record.engine.get("block_size")
    # `is not None` rather than truthiness: kv_cache_blocks == 0 is a real
    # (and alarming) engine state, not the same thing as "not reported".
    kv_tokens = blocks * block_size if blocks is not None and block_size is not None else None

    warmup = record.warmup
    steady = steady_state_latency(warmup)
    penalty = warmup_penalty(warmup, steady)
    fast_index = time_to_fast_index(warmup, steady)

    return {
        "ok": True,
        "arm": record.arm,
        "host_id": record.host.get("host_id"),
        "triple_index": record.host.get("triple_index"),
        "t_total": t_total,
        "t_total_job": t_total_job,
        "t_process": t_process,
        "t_platform": compute_residual(t_total, t_process) if consistent else None,
        "t_weights": t_weights,
        "t_s2_to_ready": t_s2_to_ready,
        "merged_phases": merged,
        "s4_subphases": record.engine.get("s4_subphases", {}),
        "t_s1": t_s1,
        "t_s4_bracket": t_s4_bracket,
        "t_s4a": subphase_values["S4a"],
        "t_s4b": subphase_values["S4b"],
        "t_s4c": subphase_values["S4c"],
        "t_s4d": subphase_values["S4d"],
        "t_s4e": subphase_values["S4e"],
        "t_compile": t_compile,
        "s4_unattributed": s4_unattributed,
        "t_s5": t_s5,
        "t_s6": t_s6,
        "warmup": warmup,
        "steady_state_latency": steady,
        "warmup_penalty": penalty,
        "time_to_fast_index": fast_index,
        "kv_cache_blocks": blocks,
        "kv_capacity_tokens": kv_tokens,
        "consistent": consistent,
        "inconsistency_reason": reason,
        "discard_reason": discard_reason,
    }
