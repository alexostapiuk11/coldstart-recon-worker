"""Write pre-registration step 2's values from the rules. Spends nothing.

    .venv/bin/python scripts/a4_step2.py values --rate <dollars per GPU-hour> \\
        --provenance "<where and when the rate was read>" --date YYYY-MM-DD
    .venv/bin/python scripts/a4_step2.py replay --cells data/a4/cells.jsonl [--cells ...] \\
        [--swaps data/a4/swaps.jsonl]

`values` runs after the reconnaissance record and the screen are committed,
and before the first measurement run. It reads fixtures/a4/recon-report.json
and data/a4/screen.json, applies placement/step2.py's rules, and writes
placement/registered.py, data/a4/designs/{cells,swaps[,sleep]}.json and the
"Step 2, part 2" section of docs/experiment-a4.md. It refuses to overwrite.

`replay` runs after the cell and swap campaigns. The validation trace's load
is a fraction of the measured solo saturation, and which pre-registered draw
is used depends on whether the simulator, given the measured curve and swaps,
predicts its replay can finish within a job and genuinely swaps. So it reduces
both, writes data/a4/designs/replay.json, and records every draw it tried in
data/a4/designs/replay-check.json. If no draw is feasible it stops.
"""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.stats import median
from placement.inputs import (
    colocated_surface,
    eviction_seconds,
    load_records,
    solo_curve,
    swap_distribution,
)
from placement.registration import SECTION, design_files, render_doc, render_module, values
from placement.sim import Engines
from placement.step2 import CELL_MIN_VALID, measurement_design
from placement.validation import validation_trace

REPO = Path(__file__).resolve().parents[1]
REPORT = Path("fixtures/a4/recon-report.json")
SCREEN = Path("data/a4/screen.json")
MODULE = Path("placement/registered.py")
DESIGNS = Path("data/a4/designs")
DOC = Path("docs/experiment-a4.md")


def _write_new(path: Path, text: str) -> None:
    if path.exists():
        raise SystemExit(f"{path} exists; step 2's values are written once. Remove it only if "
                         "nothing has been measured under it, and say so in the commit")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"wrote {path}")


def write_values(root: Path, rate: float, provenance: str, date: str) -> dict:
    report = json.loads((root / REPORT).read_text())
    screen = json.loads((root / SCREEN).read_text())
    measurement = measurement_design(report)
    v = values(measurement, screen, rate=rate, provenance=provenance)
    doc = (root / DOC).read_text()
    if SECTION in doc:
        raise SystemExit(f"{DOC} already has the step 2 values section")
    _write_new(root / MODULE, render_module(v, date))
    for name, design in design_files(measurement).items():
        _write_new(root / DESIGNS / f"{name}.json", json.dumps(design, indent=1) + "\n")
    (root / DOC).write_text(doc.rstrip("\n") + "\n\n" + render_doc(v, date))
    print(f"appended the step 2 values section to {DOC}")
    return v


def replay_swap_seconds(measurement: dict, swaps) -> float:
    """What one swap costs the replay: the median simulated swap, plus the
    page-cache eviction a cold replay pays before each swap-in."""
    cold = measurement["eviction_works"]
    simulated = swap_distribution(swaps, cold=cold, compiled=False)
    return median(list(simulated.samples)) + eviction_seconds(swaps, cold=cold)


def write_replay(root: Path, cell_stores: list[str], swap_stores: list[str]) -> dict:
    report = json.loads((root / REPORT).read_text())
    measurement = measurement_design(report)
    cells = load_records([root / s for s in cell_stores])
    warm = {"min_repeats": CELL_MIN_VALID, "require_warm_compile": True}
    curve = solo_curve(cells, levels=measurement["solo_levels"], **warm)
    surface = colocated_surface(cells, own_levels=measurement["own_levels"],
                                neighbour_levels=measurement["neighbour_levels"], **warm)
    swap_s = replay_swap_seconds(measurement, load_records([root / s for s in swap_stores]))
    trace, checks = validation_trace(measurement, Engines(curve, surface), swap_s)
    design = dataclasses.asdict(trace)
    _write_new(root / DESIGNS / "replay.json", json.dumps(design, indent=1) + "\n")
    _write_new(root / DESIGNS / "replay-check.json",
               json.dumps({"swap_s": swap_s, "checks": checks}, indent=1) + "\n")
    for c in checks:
        print(f"  seed {c['seed']}: {c['requests']} requests, {c['predicted_swaps']} swaps, last "
              f"done {c['predicted_last_done_s']:.0f} s, {c['ok_bins']} bins with a median: "
              f"{'feasible' if c['feasible'] else 'not feasible'}")
    print(f"validation trace: {len(design['trace'])} requests over {design['until']:.0f} s, "
          f"cap {design['max_in_flight']} in flight, cold={design['cold']}")
    return design


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=str(REPO))
    sub = ap.add_subparsers(dest="command", required=True)
    v = sub.add_parser("values")
    v.add_argument("--rate", type=float, required=True)
    v.add_argument("--provenance", required=True)
    # Required, not today's date: the date is part of the record, and a
    # default would stamp whatever day the script happened to be re-run.
    v.add_argument("--date", required=True)
    r = sub.add_parser("replay")
    r.add_argument("--cells", action="append", required=True)
    r.add_argument("--swaps", action="append")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.command == "values":
        return write_values(root, args.rate, args.provenance, args.date)
    return write_replay(root, args.cells, args.swaps or ["data/a4/swaps.jsonl"])


if __name__ == "__main__":
    main()
