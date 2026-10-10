"""The post's numbers, generated from `data/a3/analysis.json`.

The post carries a table between two markers. `scripts/a3_numbers.py` rewrites
it from the analysis, and tests/test_a3_post.py fails if the table in the post
differs from a fresh generation, so no number can be typed by hand or left
stale after a re-analysis (artifact 5's pattern).

Rates are shown as percentages and effects as percentage points, the scale the
hypotheses are registered on (amendment §4f). Every interval's level is read
from that interval's own alpha, and the baseline cell and the retry cap from the
analysis, so none of them is typed here.
"""

START = "<!-- a3-numbers:start -->"
END = "<!-- a3-numbers:end -->"


def pct(x: float) -> str:
    return f"{round(100 * x, 1) + 0.0:.1f}%"  # + 0.0: a rounded -0.0 prints as 0.0


def pp(x: float) -> str:
    return f"{round(100 * x, 1) + 0.0:+.1f} pp"


def usd(x) -> str:
    return "unbounded" if x is None else f"${x:.5f}"


def level(alpha: float) -> str:
    return f"{100 * (1 - alpha):g}% interval"


def _alpha(ci: dict, alpha) -> float:
    alpha = ci.get("alpha", alpha)
    if alpha is None:
        raise ValueError(f"an interval without an alpha cannot be labelled: {ci}")
    return alpha


def ci_pct(ci: dict, alpha=None) -> str:
    return (f"{pct(ci['point'])} ({level(_alpha(ci, alpha))} "
            f"{pct(ci['lo'])} to {pct(ci['hi'])})")


def ci_pp(ci: dict, alpha=None) -> str:
    return (f"{pp(ci['point'])} ({level(_alpha(ci, alpha))} "
            f"{pp(ci['lo'])} to {pp(ci['hi'])})")


def ci_usd(ci: dict) -> str:
    return f"{usd(ci['point'])} ({level(_alpha(ci, None))} {usd(ci['lo'])} to {usd(ci['hi'])})"


def _h2_row(h2: dict) -> str:
    text = f"{ci_pp(h2)}, {h2['verdict']}"
    if h2.get("failed_part"):
        text += f" (the {h2['failed_part']} part failed)"
    return text


def _h5_rows(h5: dict) -> list[tuple[str, str]]:
    if not h5.get("testable", True):
        return [("H5, absolute count effect minus absolute rerun A/A contrast",
                 f"not testable: {h5['reason']}")]
    return [
        ("H5, absolute count effect minus absolute rerun A/A contrast", f"{ci_pp(h5)}, {h5['verdict']}"),
        ("H5, count effect alone", ci_pp(h5["count_effect"], h5["alpha"])),
    ]


def numbers_block(a: dict) -> str:
    if "NOT_DATA" in a:
        raise ValueError(f"NOT_DATA analysis ({a['NOT_DATA']}): a numbers block states "
                         "measured values, and a stub analysis has none")
    h = a["hypotheses"]
    rates = a["cell_rates"]["failure"]
    ranks = a["ranked_cells"]
    eff = a["effects"]["failure"]
    cost = a["cost"]
    base, cap = a["baseline_cell"], a["retry_cap"]
    equiv = h["H2"]["equivalence"]
    rows = [
        ("Model and setting", (f"`{a['model']}`, temperature {a['settings']['temperature']}, "
                               f"reasoning {a['settings']['reasoning_effort']}")),
        ("Design", f"{a['S']} scenarios × 8 cells × {a['N']} repetitions"),
        ("Scenarios dropped from the analysis", str(len(a["dropped_scenarios"]))),
    ]
    if a["analysable_below_s_floor"]:
        rows.append(("Scenario floor",
                     f"below the pre-registered scenario floor: {a['S']} analysable"))
    if a.get("h5_dropped_scenarios"):
        rows.append(("Scenarios dropped from H5 only", str(len(a["h5_dropped_scenarios"]))))
    rows += [
        (f"Failure rate, baseline cell ({base})", ci_pct(rates[base])),
        (f"Failure rate, best cell ({ranks['best']})", ci_pct(rates[ranks["best"]])),
        (f"Failure rate, worst cell ({ranks['worst']})", ci_pct(rates[ranks["worst"]])),
        ("Rich descriptions at low tool count", ci_pp(eff["at:richness:count:low"])),
        ("Rich descriptions at high tool count", ci_pp(eff["at:richness:count:high"])),
        ("H1, richness × count interaction", f"{ci_pp(h['H1'])}, {h['H1']['verdict']}"),
        ("H2, strictness on malformed + wrong-parameter rate", _h2_row(h["H2"])),
        ((f"H2, strictness on wrong-tool rate ({level(equiv['alpha'])}, margin "
          f"±{100 * equiv['margin']:g} pp)"),
         (f"{ci_pp(equiv)}, equivalence {'passes' if equiv['passes'] else 'fails'}")),
        ("H3, tool count on wrong-tool rate", f"{ci_pp(h['H3'])}, {h['H3']['verdict']}"),
        ("H4, identical retries, opaque minus actionable",
         f"{ci_pp(h['H4'])}, {h['H4']['verdict']}" if h["H4"].get("testable")
         else f"not testable: {h['H4']['reason']}"),
        *_h5_rows(h["H5"]),
        ("Ever-flip fraction", ci_pct(a["flakiness"]["ever_flip"])),
        (f"Cost per successful call, baseline cell, retrying up to {cap} times",
         ci_usd(cost[base]["retry"])),
        (f"Cost per successful call, best cell ({ranks['best']}), retrying up to {cap} times",
         ci_usd(cost[ranks["best"]]["retry"])),
    ]
    if a.get("spend"):
        rows.append(("Spend, billed", f"${a['spend']['billed_usd']:.2f}"))
    lines = ["| quantity | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join([START] + lines + [END])


def block_in(text: str) -> str:
    """The one block between the markers, markers included. Exactly one start
    and one end marker, in that order: a second pair, or a prose mention of a
    marker, would make a replacement guess which block is meant."""
    starts, ends = text.count(START), text.count(END)
    if starts == 0 and ends == 0:
        raise ValueError("the post has no a3-numbers block")
    if starts != 1 or ends != 1:
        found = (f"{starts} start marker{'s' * (starts != 1)} and "
                 f"{ends} end marker{'s' * (ends != 1)}")
        if starts > 1 or ends > 1:
            raise ValueError(f"the post has {found}; exactly one of each is allowed")
        raise ValueError(f"the post has {found} ({'no end marker' if ends == 0 else 'no start marker'})")
    start, end = text.index(START), text.index(END)
    if end < start:
        raise ValueError("the a3-numbers end marker comes before its start marker")
    return text[start:end + len(END)]


def replace_block(text: str, block: str) -> str:
    if not (block.startswith(START) and block.endswith(END)):
        raise ValueError("the new block must start with the start marker and end with the end "
                         "marker")
    if block.count(START) != 1 or block.count(END) != 1:
        raise ValueError("the new block must contain exactly one start marker and one end "
                         "marker")
    old = block_in(text)
    start = text.index(old)
    return text[:start] + block + text[start + len(old):]
