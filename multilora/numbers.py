"""The post's numbers, generated from `data/a5/analysis.json`.

The post carries a block between two markers. `scripts/a5_numbers.py`
rewrites it from the analysis and tests/test_a5_post.py fails if the block in
the post differs from a fresh generation, so a number cannot be edited by hand
or left stale after a re-analysis.
"""

from multilora.conditions import CONCENTRATED, SPREAD
from multilora.estimands import point_at

START = "<!-- a5-numbers:start -->"
END = "<!-- a5-numbers:end -->"


def _ci(ci: dict, scale: float = 1.0, unit: str = "") -> str:
    return (
        f"{ci['point'] * scale:,.1f}{unit} "
        f"(95% interval {ci['lo'] * scale:,.1f} to {ci['hi'] * scale:,.1f}{unit})"
    )


def numbers_block(analysis: dict) -> str:
    sweep = analysis["sweep"]
    top_n = sweep["points"][-1]["n_slots"]
    top = point_at(sweep, top_n)
    one = point_at(sweep, 1)
    knee = analysis["knee"]
    tenants = analysis["tenants"]
    gate = analysis["gate"]
    rows = [
        ("Equivalence gate", f"{gate['verdict']}, n = {gate['n']} instances"),
        (
            "Knee",
            f"above {top_n} slots" if knee["above_top"]
            else f"between {knee['knee']['lower']} and {knee['knee']['upper']} slots",
        ),
        (
            f"Heterogeneity cost at {top_n} slots, throughput",
            _ci(top["heterogeneity"]["throughput_tps"], unit=" tokens/s"),
        ),
        (
            f"Heterogeneity cost at {top_n} slots, TTFT p50",
            _ci(top["heterogeneity"]["ttft_p50"], scale=1000.0, unit=" ms"),
        ),
        (
            f"Registered-slot cost at {top_n} slots, throughput",
            _ci(top["registered_slot"]["throughput_tps"], unit=" tokens/s"),
        ),
        (
            "Throughput at 1 slot",
            f"{one['median'][CONCENTRATED]['throughput_tps']:,.0f} tokens/s",
        ),
        (
            f"Spread throughput at {top_n} slots",
            f"{top['median'][SPREAD]['throughput_tps']:,.0f} tokens/s",
        ),
        (
            "KV capacity, 1 slot to top",
            f"{one['memory']['kv_tokens']:,.0f} to {top['memory']['kv_tokens']:,.0f} tokens",
        ),
    ]
    if tenants["feasible"]:
        rows.append(
            ("Tenants per GPU", f"{tenants['tenants']} (bound by {tenants['binding']}; a lower bound)")
        )
    else:
        rows.append(("Tenants per GPU", f"infeasible: {tenants['reason']}"))
    for row in analysis.get("cost_table", []):
        label = f"Cost per tenant per month, {row['strategy']}"
        suffix = " (an upper bound)" if row.get("upper_bound") else ""
        rows.append((label, f"${row['cost']:,.2f}{suffix}"))
    body = ["| quantity | value |", "|---|---|", *[f"| {k} | {v} |" for k, v in rows]]
    return "\n".join([START, *body, END])


def replace_block(post: str, block: str) -> str:
    start, end = post.index(START), post.index(END) + len(END)
    return post[:start] + block + post[end:]


def block_in(post: str) -> str:
    start, end = post.index(START), post.index(END) + len(END)
    return post[start:end]
