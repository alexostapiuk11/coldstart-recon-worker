"""The post's headline numbers, formatted once from `data/a4/analysis.json`.

The post quotes each of these strings verbatim, and `tests/test_a4_post.py`
(written at publication) fails if any is missing from `docs/post-a4.md`. A
number typed by hand drifts from the data the first time the data is
re-analysed; a number rendered here cannot. Artifact 1 holds its explainer to
`explainer/numbers.json` the same way.

Formats are fixed here, not at the call site: two decimal places for dollars,
one for seconds, whole percentages.
"""

from placement.fleet import STRATEGIES

__all__ = ["numbers"]


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def _s(x: float) -> str:
    return f"{x:.1f} s"


def _rule(segments: list[dict]) -> str:
    parts = []
    for seg in segments:
        span = (f"s = {seg['from_s']}" if seg["from_s"] == seg["to_s"]
                else f"s = {seg['from_s']}–{seg['to_s']}")
        parts.append(f"{span}: {' = '.join(seg['cheapest']) or 'none meets the SLO'}")
    return "; ".join(parts)


def numbers(analysis: dict) -> dict[str, str]:
    out: dict[str, str] = {
        "slo": _s(analysis["design"]["slo_seconds"]),
        "offered_gpus": f"{analysis['design']['offered_gpus']:g} GPUs",
        "gpu_hourly_rate": _usd(analysis["rate"]["gpu_hourly_rate"]),
        "repetitions": str(analysis["design"]["repetitions"]),
    }
    for regime, r in analysis["regimes"].items():
        out[f"{regime}_decision_rule"] = _rule(r["decision_rule"])
        if r["gaps"]:
            out[f"{regime}_gaps"] = "; ".join(f"s = {g['s']}: {g['reason']}" for g in r["gaps"])
        between = r["crossover"]["between"]
        out[f"{regime}_crossover"] = ("no crossover in the swept range" if not between else
                                      "; ".join(f"between s = {a} and s = {b}" for a, b in between))
    ref = analysis["reference"]
    point = next(p for p in analysis["regimes"][ref["regime"]]["points"] if p["s"] == ref["s"])
    if point["evaluable"]:
        for strategy in STRATEGIES:
            v = point["strategies"][strategy]
            if v is not None:
                out[f"ref_{strategy}_gpus"] = f"{v['m']} GPUs"
                out[f"ref_{strategy}_per_tenant"] = _usd(v["cost_per_tenant_month"])
                out[f"ref_{strategy}_per_million_tokens"] = _usd(v["cost_per_million_tokens"])
        if point["dedicate_over_cheapest_per_month"] is not None:
            out["ref_dedicate_over_cheapest"] = _usd(point["dedicate_over_cheapest_per_month"])
        agg = point["aggregate_rule"].get("swap")
        if agg is not None and agg["coldest_decile_breach"] is not None:
            out["ref_swap_aggregate_gpus"] = f"{agg['m']} GPUs"
            out["ref_swap_aggregate_coldest_breach"] = f"{agg['coldest_decile_breach']:.0%}"
    inputs = analysis["inputs"]
    out["swap_median"] = _s(inputs["swaps"]["simulated"]["p50"])
    if inputs.get("sleep_mode"):
        out["sleep_switch_median"] = _s(inputs["sleep_mode"]["p50"])
    out["kv_split_ceiling"] = f"{inputs['kv']['split_ceiling']} requests"
    if inputs["kv"]["solo_ceiling"] is not None:
        out["kv_solo_ceiling"] = f"{inputs['kv']['solo_ceiling']} requests"
    v = analysis["validation"]
    out["validation_outcome"] = v["outcome"]
    if "latency" in v:
        misses = v["latency"]["compared"] - v["latency"]["agreeing"]
        out["validation_bins"] = f"{misses} of {v['latency']['compared']} judged bins"
    passed = sum(c["passed"] for c in analysis["held_out"])
    out["held_out"] = f"{passed} of {len(analysis['held_out'])} held-out cells"
    return out
