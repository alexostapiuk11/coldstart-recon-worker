"""The post's numbers, generated from `data/a3/analysis.json`.

The post carries a table between two markers. `scripts/a3_numbers.py` rewrites
it from the analysis, and tests/test_a3_post.py fails if the table in the post
differs from a fresh generation, so no number can be typed by hand or left
stale after a re-analysis (artifact 5's pattern).

Rates are shown as percentages and effects as percentage points, the scale the
hypotheses are registered on (amendment §4f).
"""

START = "<!-- a3-numbers:start -->"
END = "<!-- a3-numbers:end -->"


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def pp(x: float) -> str:
    return f"{100 * x:+.1f} pp"


def ci_pct(ci: dict) -> str:
    return f"{pct(ci['point'])} (95% interval {pct(ci['lo'])} to {pct(ci['hi'])})"


def ci_pp(ci: dict) -> str:
    return f"{pp(ci['point'])} (95% interval {pp(ci['lo'])} to {pp(ci['hi'])})"


def usd(x) -> str:
    return "unbounded" if x is None else f"${x:.5f}"


def numbers_block(a: dict) -> str:
    h = a["hypotheses"]
    rates = a["cell_rates"]["failure"]
    ranks = a["ranked_cells"]
    eff = a["effects"]["failure"]
    cost = a["cost"]
    rows = [
        ("Model and setting", (f"`{a['model']}`, temperature {a['settings']['temperature']}, "
                               f"reasoning {a['settings']['reasoning_effort']}")),
        ("Design", f"{a['S']} scenarios × 8 cells × {a['N']} repetitions"),
        ("Failure rate, baseline cell (low-terse-loose)", ci_pct(rates["low-terse-loose"])),
        (f"Failure rate, best cell ({ranks['best']})", ci_pct(rates[ranks["best"]])),
        (f"Failure rate, worst cell ({ranks['worst']})", ci_pct(rates[ranks["worst"]])),
        ("Rich descriptions at low tool count", ci_pp(eff["at:richness:count:low"])),
        ("Rich descriptions at high tool count", ci_pp(eff["at:richness:count:high"])),
        ("H1, richness × count interaction", f"{ci_pp(h['H1'])}, {h['H1']['verdict']}"),
        ("H2, strictness on malformed + wrong-parameter rate",
         f"{ci_pp(h['H2'])}, {h['H2']['verdict']}"),
        (("H2, strictness on wrong-tool rate (90% interval, margin "
          f"±{100 * h['H2']['equivalence']['margin']:.0f} pp)"),
         (f"{pp(h['H2']['equivalence']['point'])} ({pp(h['H2']['equivalence']['lo'])} to "
          f"{pp(h['H2']['equivalence']['hi'])})")),
        ("H3, tool count on wrong-tool rate", f"{ci_pp(h['H3'])}, {h['H3']['verdict']}"),
        ("H4, identical retries, opaque minus actionable",
         f"{ci_pp(h['H4'])}, {h['H4']['verdict']}" if h["H4"].get("testable")
         else f"not testable: {h['H4']['reason']}"),
        ("H5, tool count against the rerun A/A contrast",
         f"{ci_pp(h['H5'])}, {h['H5']['verdict']}"),
        ("Ever-flip fraction", ci_pct(a["flakiness"]["ever_flip"])),
        ("Cost per successful call, baseline cell, retrying up to 3 times",
         usd(cost["low-terse-loose"]["retry"]["point"])),
        (f"Cost per successful call, best cell ({ranks['best']}), retrying up to 3 times",
         usd(cost[ranks["best"]]["retry"]["point"])),
    ]
    if a.get("spend"):
        rows.append(("Spend, billed", f"${a['spend']['billed_usd']:.2f}"))
    lines = ["| quantity | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join([START] + lines + [END])


def block_in(text: str) -> str:
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("the post has no a3-numbers block")
    return text[start:end + len(END)]


def replace_block(text: str, block: str) -> str:
    return text.replace(block_in(text), block)
