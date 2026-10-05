"""Compute the campaign's cost from reconnaissance timings (amendment §6).

    .venv/bin/python scripts/a5_budget.py

Reads the reconnaissance captures in fixtures/a5/ (the final 0.80 set, for warm
timings) and fixtures/a5/budget-085/ (for cold startups), and
multilora/prereg_values.py. Prints the inputs it used, then the estimate and
whether the gauge control and the diagnostic fit under $20.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from multilora.budget import estimate
from multilora.prereg_values import PREREG
from multilora.recon_report import report

DIR = Path(__file__).resolve().parents[1] / "fixtures" / "a5"
# The same rule as scripts/a5_recon_report.py's loader: these two files in the
# capture directory are not captures.
SKIP = {"recon_report.json", "real_adapter_candidates.json"}
COLD_POINTS = (1, 16, 64)


def _captures(directory: Path) -> list[dict]:
    return [
        json.loads(p.read_text()) for p in sorted(directory.glob("*.json")) if p.name not in SKIP
    ]


def _output(capture: dict) -> dict:
    outcome = capture["outcome"]
    return outcome.get("payload") or outcome.get("diagnostics") or {}


def main() -> int:
    final = _captures(DIR)
    probes = report(final)["probes"]
    raw = {c["label"]: _output(c) for c in final}
    timings = {}
    for label, p in probes.items():
        if label.endswith("-restart"):
            # Deviation (b) from the plan: seconds_per_request is computed from
            # the raw capture's first phase, unrounded, instead of being read
            # from a stored report, so the budget does not depend on the
            # precision a report file keeps. At 1 slot it is about 0.005 s per
            # request, which rounding to 2 decimals would turn into 0.0.
            phase = raw[label]["phases"][0]
            timings[p["n_slots"]] = {
                "setup_s": p["setup_s"],
                "warm_startup_s": p["startup_s"],
                "seconds_per_request": phase["duration_s"] / phase["num_requests"],
            }
    # Deviation (a) from the plan: cold startups come from the 0.85 set
    # (fixtures/a5/budget-085/), not from the final 0.80 set's '-first' probes.
    # The final set has no cold starts: the compile cache on the network volume
    # already existed, and every one of its probes reads compile_state 'warm'
    # (docs/recon-a5.md, R8). Caveats, from the same record:
    # - the 0.85 N1-first loaded a compile cache left by the out-of-memory
    #   attempt at 0.92 (oom-attempt-1), so it is not a fresh compile; it is the
    #   only N1 cold-ish startup that reached health, and cold[1] is likely an
    #   underestimate of a fresh compile;
    # - that compile cost does not depend on the memory budget is expected, not
    #   measured: no point was compiled cold at two budgets.
    probes_085 = report(_captures(DIR / "budget-085"))["probes"]
    cold = {n: probes_085[f"lora-N{n}-first"]["startup_s"] for n in COLD_POINTS}
    print(json.dumps({"inputs": {"timings": timings, "cold_startup_s": cold}}, indent=1))
    result = estimate(PREREG, timings, cold_startup_s=cold)
    print(json.dumps(result, indent=1))
    return 1 if result["over_cap"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
