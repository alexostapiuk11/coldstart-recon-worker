import statistics
from typing import TypedDict

from coldstart.checks import DiscardReason, check_consistency, compute_residual
from coldstart.schema import RunRecord

FAST_TOLERANCE = 0.10  # fixed before data — see spec 7


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
    t_total: float
    t_process: float
    t_platform: float | None
    t_weights: float | None
    t_s2_to_ready: float | None
    merged_phases: list[str]
    s4_subphases: dict
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
    t_total = record.clock_A["t_result"] - record.clock_A["t_submit"]
    checked = check_consistency(t_total=t_total, t_process=t_process)
    # Carry all three ConsistencyResult fields through: discard_reason is a
    # closed enum specifically so a downstream reader can tabulate discards
    # by class instead of substring-matching the free-form `reason` string.
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
        "t_process": t_process,
        "t_platform": compute_residual(t_total, t_process) if consistent else None,
        "t_weights": t_weights,
        "t_s2_to_ready": t_s2_to_ready,
        "merged_phases": merged,
        "s4_subphases": record.engine.get("s4_subphases", {}),
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
