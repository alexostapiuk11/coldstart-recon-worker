"""Run it on your own agent: your tools, your scenarios, your failure taxonomy.

The adoption path (August §7). Point it at a directory of tool-library files
and a directory of scenario files in this repository's format, and it runs the
baseline formulation only -- your tools as you list them, terse or rich and
loose or strict as you choose -- and reports how the calls break down across
the six categories. The factorial is optional; this is the easy default.
"""

from collections import Counter, defaultdict

from harness.store import JsonlStore
from toolcall import campaign
from toolcall.effects import wilson
from toolcall.formulation import Formulation
from toolcall.grader import CATEGORIES, EXCLUDED
from toolcall.records import CallRecord
from toolcall.scenarios import load_scenarios
from toolcall.tools import load_library

INTERVENTION = {
    "MALFORMED": "schema strictness, output format constraints",
    "SPURIOUS": "description scoping, explicit guidance on when not to call",
    "MISSING": "tool discoverability, description richness",
    "WRONG_TOOL": "disambiguation between similar tools, fewer tools in context",
    "WRONG_PARAMS": "typing strictness, parameter naming and descriptions",
}


def diagnose(client, tools_dir, scenarios_dir, store_path, *, reps: int,
             richness: str = "rich", strictness: str = "strict", seed: int = 0) -> dict:
    library = load_library(tools_dir)
    scenarios = load_scenarios(scenarios_dir, library, factorial=False)
    cell = Formulation("low", richness, strictness)
    store = JsonlStore(store_path, CallRecord)
    campaign.single_turn(campaign.schedule([cell], scenarios, reps, seed), client, scenarios,
                         library, store, phase="diagnose")
    return summarise(store.read_all())


def summarise(records) -> dict:
    graded = [r for r in records if r.grade["category"] not in EXCLUDED]
    counts = Counter(r.grade["category"] for r in graded)
    n = len(graded)
    by_scenario: dict = defaultdict(Counter)
    for r in graded:
        by_scenario[r.scenario_id][r.grade["category"]] += 1
    rows = []
    for cat in CATEGORIES:
        k = counts.get(cat, 0)
        lo, hi = wilson(k, n) if n else (None, None)
        rows.append({"category": cat, "calls": k, "share": k / n if n else None,
                     "pooled_wilson_lo": lo, "pooled_wilson_hi": hi,
                     "points_at": INTERVENTION.get(cat, "")})
    return {"graded": n,
            "excluded": Counter(r.grade["category"] for r in records
                                if r.grade["category"] in EXCLUDED),
            "categories": rows,
            "by_scenario": {s: dict(c) for s, c in sorted(by_scenario.items())},
            "note": "Pooled Wilson intervals treat repetitions of one scenario as independent, "
                    "which they are not; read the per-scenario breakdown before trusting them."}


def report(summary: dict) -> str:
    lines = [f"{summary['graded']} graded calls; excluded: {dict(summary['excluded']) or 0}",
             "", "| category | calls | share | what it points at |", "|---|---|---|---|"]
    for r in summary["categories"]:
        share = "" if r["share"] is None else f"{100 * r['share']:.1f}%"
        lines.append(f"| {r['category']} | {r['calls']} | {share} | {r['points_at']} |")
    lines += ["", summary["note"]]
    return "\n".join(lines)
