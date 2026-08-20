import statistics

from coldstart.checks import check_consistency, compute_residual
from coldstart.schema import RunRecord

FAST_TOLERANCE = 0.10  # fixed before data — see spec 7


def _marks(record: RunRecord) -> dict[str, float]:
    return {m["stage"]: m["t_mono"] for m in record.clock_B.get("marks", [])}


def ceiling_bound(t_weights: float, t_total: float) -> float:
    """Largest fraction of T_total removable if T_weights went to zero.

    Conceptually this is (weights share of T_process) x (T_process share of
    T_total), but T_process cancels, so it is written in the reduced form. The
    unreduced version took a T_process argument that could not affect the
    result — a parameter no test could ever pin.
    """
    return t_weights / t_total


def derive(record: RunRecord) -> dict:
    if record.status["outcome"] != "ok":
        return {"ok": False, "arm": record.arm, "consistent": False}

    m = _marks(record)
    t_process = m["S6_first_token"]
    t_total = record.clock_A["t_result"] - record.clock_A["t_submit"]
    # check_consistency returns a 3-field ConsistencyResult, so attribute access
    # rather than tuple unpacking — see Task 10.
    checked = check_consistency(t_total=t_total, t_process=t_process)
    consistent, reason = checked.ok, checked.reason

    warmup = record.warmup
    steady = statistics.median(w["end_to_end"] for w in warmup[-3:]) if warmup else None
    threshold = steady * (1.0 + FAST_TOLERANCE) if steady else None
    fast_index = None
    if threshold is not None:
        for w in warmup:
            if w["end_to_end"] <= threshold:
                fast_index = w["req_index"]
                break

    # T_weights = S2 + S3 (spec, stage taxonomy). The volume arms may memory-map
    # weights, fusing acquisition and HBM load with no clean boundary between
    # them, which is exactly why the pair is the primary unit rather than S2
    # alone. If the engine did not delineate the load boundary at all, the phase
    # is reported merged rather than silently widened to S5_ready — widening it
    # would swallow the whole of S4, including the compile term.
    t_acq_start = m.get("S2_acquisition_start")
    t_load_done = m.get("S3_load_done")
    t_ready = m.get("S5_ready")
    merged = []
    if t_acq_start is not None and t_load_done is not None:
        t_weights = t_load_done - t_acq_start
    else:
        t_weights = None
        merged.append("S3")
    t_s2_to_ready = (
        t_ready - t_acq_start if t_acq_start is not None and t_ready is not None else None
    )

    blocks = record.engine.get("kv_cache_blocks")
    block_size = record.engine.get("block_size")
    kv_tokens = blocks * block_size if blocks and block_size else None

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
        "warmup_penalty": (warmup[0]["end_to_end"] / steady) if warmup and steady else None,
        "time_to_fast_index": fast_index,
        "kv_cache_blocks": blocks,
        "kv_capacity_tokens": kv_tokens,
        "consistent": consistent,
        "inconsistency_reason": reason,
    }
