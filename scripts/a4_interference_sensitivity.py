"""Exploratory: how large can the co-location penalty be before the co-located fleet grows? Spends
nothing; changes no registered value.

    PYTHONPATH=. .venv/bin/python scripts/a4_interference_sensitivity.py \\
        [--out data/a4/exploratory/interference-sensitivity.json] [--repetitions 6] [--workers 4]

The measured surface has neighbour levels 0, 16, 32 and 64; the simulator interpolates linearly
between 0 and 16 (`placement/colocated.py`), where lightly loaded tenants sit. This re-sizes the
reference skew (s = 1.0) in both regimes with the surface changed:
  - registered: as analysed;
  - step: any busy neighbour (level 1 and up) costs what level 16 costs, the worst reading of the
    unmeasured range;
  - x4 and x8: the step surface with every busy-neighbour latency multiplied.
The point windows come from the cached sweep, so no pilot is re-run. Six repetitions, not 30:
this reads where the fleet changes, not a published number.
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import a4_sweep

from harness.stats import median
from placement import registered as R
from placement.colocated import ColocatedSurface
from placement.evaluate import evaluate_point
from placement.inputs import colocated_surface, load_records, solo_curve, swap_distribution
from placement.sim import Engines
from placement.sizing import sized_fleet
from placement.step2 import CELL_MIN_VALID, REFERENCE, SweepChoice, sweep_design

CELLS = ["data/a4/cells.jsonl", "data/a4/cells-ramp-1a.jsonl", "data/a4/cells-ramp-1b.jsonl",
         "data/a4/cells-ramp-1c-retry.jsonl", "data/a4/cells-ramp-1d-retry.jsonl",
         "data/a4/cells-ramp-1e.jsonl"]
VARIANTS = (("registered", None), ("step", 1), ("x4", 4), ("x8", 8))

_STATE: dict = {}


def _surface(base: ColocatedSurface, factor: int | None) -> ColocatedSurface:
    if factor is None:
        return base
    neighbour = (base.neighbour[0], 1.0) + base.neighbour[1:]
    latency = tuple((row[0], row[1] * factor) + tuple(v * factor for v in row[1:])
                    for row in base.latency)
    return ColocatedSurface(own=base.own, neighbour=neighbour, latency=latency, measured=True)


def _prepare() -> None:
    reg = {k: getattr(R, k) for k in dir(R) if k.isupper()}
    cells = load_records([REPO / s for s in CELLS])
    swaps = load_records([REPO / "data/a4/swaps.jsonl"])
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=reg["SOLO_LEVELS"], min_repeats=CELL_MIN_VALID, **warm)
    base = colocated_surface(cells, own_levels=reg["OWN_LEVELS"],
                             neighbour_levels=reg["NEIGHBOUR_LEVELS"],
                             min_repeats=CELL_MIN_VALID, **warm)
    swap_time = swap_distribution(swaps, cold=reg["EVICTION_WORKS"], compiled=False)
    design = sweep_design(SweepChoice(reg["OFFERED_GPUS"], reg["SLO_SWAP_MULTIPLE"]),
                          median(list(swap_time.samples)))
    registered_engines = Engines(solo=solo, colocated=base)
    cached = a4_sweep.evaluations_for(design, registered_engines, swap_time,
                                      REPO / "build/a4-sweep", 1)
    _STATE.update(
        design=design, swap_time=swap_time, solo=solo, base=base,
        scenario=a4_sweep.scenario_for(design, registered_engines),
        points={e.point.regime: e.point for e in cached if e.point.s == REFERENCE["s"]})


def _run(job: tuple[str, int | None, str, int]) -> dict:
    name, factor, regime, repetitions = job
    s = _STATE
    engines = Engines(solo=s["solo"], colocated=_surface(s["base"], factor))
    ev = evaluate_point(s["points"][regime], s["scenario"], engines, s["swap_time"], repetitions,
                        s["design"].seed, s["design"].slo_seconds)
    sized = sized_fleet(ev, list(range(repetitions)), s["design"].slo_seconds)
    return {"variant": name, "regime": regime, "sized": sized}


def main(argv=None) -> list[dict]:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="data/a4/exploratory/interference-sensitivity.json")
    ap.add_argument("--repetitions", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    _prepare()
    jobs = [(name, factor, regime, args.repetitions)
            for name, factor in VARIANTS for regime in sorted(_STATE["points"])]
    # Each worker prepares its own state: macOS starts workers by spawn, not fork.
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_prepare) as pool:
        rows = list(pool.map(_run, jobs))
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"point": {"s": REFERENCE["s"]}, "repetitions": args.repetitions, "rows": rows}
    out.write_text(json.dumps(payload, indent=1) + "\n")
    for r in rows:
        print(f"{r['variant']:10s} {r['regime']:7s} {r['sized']}")
    return rows


if __name__ == "__main__":
    main()
