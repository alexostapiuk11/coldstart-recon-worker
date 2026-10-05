"""Answers to reconnaissance questions R1-R9, computed from the committed
captures in `fixtures/a5/` (amendment §6). R10 comes from
scripts/a5_find_real_adapters.py and the `lora-gate-real` probe.

Computed rather than transcribed, so `docs/recon-a5.md` can be regenerated and
checked against the captures it cites.
"""

from multilora.engine import engine_facts
from multilora.gauge import running_adapters
from multilora.serving import BENCH_FLAGS, ENGINE_FLAGS, SPECIALIZE_FLAG


def _output(capture: dict) -> dict | None:
    """The worker's output: the payload on success, the diagnostics on an
    unhealthy engine, None when the job produced nothing."""
    outcome = capture["outcome"]
    return outcome.get("payload") or outcome.get("diagnostics")


def _help_text(captures, key) -> str:
    for c in captures:
        if c["label"] == "help" and _output(c):
            h = _output(c)[key]
            return h["stdout"] + h["stderr"]
    return ""


def _lora(captures):
    return [c for c in captures if c["label"].startswith("lora-") and _output(c)]


def _max_running_at_top(healthy: list[dict]) -> int | None:
    """None, not 0, when the gauge produced no sample at the top point: an
    absent observation must not read as an observed zero."""
    if not healthy:
        return None
    top = max(p["n_slots"] for p in healthy)
    seen = [p["max_distinct_running"] for p in healthy
            if p["n_slots"] == top and p["max_distinct_running"] is not None]
    return max(seen) if seen else None


def report(captures: list[dict]) -> dict:
    serve_help = _help_text(captures, "serve_help")
    bench_help = _help_text(captures, "bench_help")
    per_probe = {}
    for c in _lora(captures):
        out = _output(c)
        facts = engine_facts(out.get("log_lines") or [])
        running = [
            len(s["running"]) for s in out.get("gauge_samples", []) if s["running"] is not None
        ]
        phase = (out.get("phases") or [{}])[0]
        per_probe[c["label"]] = {
            "n_slots": c["payload"]["n_slots"],
            "healthy": bool(out.get("healthy")),
            "startup_s": out.get("startup_s"),
            "setup_s": out.get("setup_s"),
            "compile_state": facts["compile_state"],
            "kv_capacity_tokens": facts.get("kv_capacity_tokens"),
            "completions_ok": all(s == 200 for s in (out.get("completion_status") or {}).values())
            if out.get("completion_status") else None,
            "gauge_exported": running_adapters(out.get("metrics_idle") or "") is not None,
            "max_distinct_running": max(running) if running else None,
            "phase_seconds_per_request": (phase["duration_s"] / phase["num_requests"])
            if phase.get("num_requests") else None,
            "phase_arrays_complete": bool(phase) and len(phase["ttfts"]) == phase["num_requests"]
            == len(phase["output_lens"]) == len(phase["errors"]),
            "a1_prompt_tokens": out.get("a1_prompt_tokens"),
        }
    healthy = [p for p in per_probe.values() if p["healthy"]]
    return {
        "R1_in_batch_cap_is_max_loras": "--max-loras" in serve_help,
        "R2_highest_healthy_slots": max((p["n_slots"] for p in healthy), default=None),
        "R3_every_adapter_answered": all(p["completions_ok"] for p in healthy),
        "R4_bench_flags_missing": [f for f in BENCH_FLAGS if f not in bench_help],
        "R4_engine_flags_missing": [f for f in ENGINE_FLAGS if f not in serve_help],
        "R4_phase_arrays_complete": all(p["phase_arrays_complete"] for p in healthy),
        "R5_max_distinct_running_at_top": _max_running_at_top(healthy),
        "R6_kv_reported_with_lora": all(p["kv_capacity_tokens"] for p in healthy),
        "R7_gauge_exported": any(p["gauge_exported"] for p in healthy),
        "R9_specialize_flag_present": SPECIALIZE_FLAG in serve_help,
        "request_shape_prompt_tokens": sorted(
            {p["a1_prompt_tokens"] for p in healthy if p["a1_prompt_tokens"] is not None}
        ),
        "probes": per_probe,
    }
