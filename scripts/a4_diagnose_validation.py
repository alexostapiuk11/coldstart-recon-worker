"""Exploratory diagnosis of the validation gate's verdict. Spends nothing; changes no registered value.

    PYTHONPATH=. .venv/bin/python scripts/a4_diagnose_validation.py [--out data/a4/exploratory/validation-diagnosis.json]

Re-runs the gate's prediction (`placement.validation.predict`) on the three stored replays with the
inputs varied one at a time, to ask what the miss is made of:
  1. the solo service curve sped up uniformly (a host-speed difference between the curve's pod and
     the replay pod);
  2. the swap time charged per swap, over the range seen in this experiment's pods;
  3. each repeat held to its own prediction, charged at that repeat's own median real swap time
     (artifact 2's per-repeat construction, `autoscale.validation_band.compare_per_repeat`).
The committed verdict is `data/a4/analysis.json`; this script never writes it.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from autoscale.service import ServiceCurve
from autoscale.validation_band import compare_per_repeat, trajectory
from harness.stats import median
from placement import registered as R
from placement.inputs import (
    colocated_surface,
    eviction_seconds,
    load_records,
    solo_curve,
    swap_distribution,
)
from placement.sim import Engines
from placement.step2 import (
    CELL_MIN_VALID,
    EDGE_TOLERANCE_S,
    MAX_MISS_FRACTION,
    MIN_COMPARED_BINS,
    VALIDATION_BIN_S,
    VALIDATION_REPEATS,
)
from placement.validation import predict, replay_run, validate

CELL_STORES = ["data/a4/cells.jsonl", "data/a4/cells-ramp-1a.jsonl", "data/a4/cells-ramp-1b.jsonl",
               "data/a4/cells-ramp-1c-retry.jsonl", "data/a4/cells-ramp-1d-retry.jsonl",
               "data/a4/cells-ramp-1e.jsonl"]


def _row(v: dict) -> dict:
    lat = v["latency"]
    return {"agreeing": lat["agreeing"], "compared": lat["compared"],
            "max_miss_s": round(lat["max_miss_seconds"], 1), "latency": lat["outcome"],
            "swaps_predicted": v["swaps"]["predicted"], "swaps_real": v["swaps"]["real"]}


def diagnose() -> dict:
    cells = load_records([REPO / s for s in CELL_STORES])
    swaps = load_records([REPO / "data/a4/swaps.jsonl"])
    replays = load_records([REPO / "data/a4/replay.jsonl"])
    warm = {"require_warm_compile": True}
    solo = solo_curve(cells, levels=R.SOLO_LEVELS, min_repeats=CELL_MIN_VALID, **warm)
    surface = colocated_surface(cells, own_levels=R.OWN_LEVELS, neighbour_levels=R.NEIGHBOUR_LEVELS,
                                min_repeats=CELL_MIN_VALID, **warm)
    campaign_swap_s = median(list(swap_distribution(swaps, cold=R.EVICTION_WORKS,
                                                    compiled=False).samples))
    gate_swap_s = campaign_swap_s + eviction_seconds(swaps, cold=R.EVICTION_WORKS)

    def scaled(k: float) -> ServiceCurve:
        return ServiceCurve(points=[(c, lat / k, tps * k, util) for c, lat, tps, util in solo.points],
                            measured=True)

    ok = [r for r in replays if r.outcome == "ok"]
    own_swaps = [[s["ready"] - s["swap_start"] for s in r.output["swaps"]] for r in ok]
    out = {
        "campaign_swap_median_s": round(campaign_swap_s, 2),
        "replay_swap_seconds": [[round(x, 1) for x in d] for d in own_swaps],
        "replay_swap_median_s": [round(statistics.median(d), 2) for d in own_swaps],
        "replay_pods": [(r.output.get("host") or {}).get("runpod_pod_id") for r in ok],
        "solo_curve_pods": sorted({(r.output.get("host") or {}).get("runpod_pod_id") for r in cells
                                   if r.outcome == "ok" and r.condition.startswith("solo:")}),
    }
    out["as_gated"] = _row(validate(replays, Engines(solo=solo, colocated=surface), gate_swap_s))
    out["curve_speed"] = {f"{k:.2f}": _row(validate(replays, Engines(solo=scaled(k), colocated=surface),
                                                    gate_swap_s))
                          for k in (1.00, 1.05, 1.10, 1.20, 1.30)}
    out["swap_cost"] = {f"{s:.0f}": _row(validate(replays, Engines(solo=solo, colocated=surface), s))
                        for s in (38, 33, 30, 28, 26, 25, 24, 22)}

    engines = Engines(solo=solo, colocated=surface)
    pairs, bins = [], []
    for rec, d in zip(ok, own_swaps, strict=True):
        run = replay_run(rec)
        real = trajectory(run.schedule, run.windowed_latencies(), until=run.until,
                          bin_seconds=VALIDATION_BIN_S)
        pred, _, _ = predict(run.schedule, run.tenants, run.until, engines, statistics.median(d))
        pairs.append((real, pred))
    v = compare_per_repeat(pairs, min_repeats=VALIDATION_REPEATS, min_compared_bins=MIN_COMPARED_BINS,
                           max_miss_fraction=MAX_MISS_FRACTION, edge_tolerance_seconds=EDGE_TOLERANCE_S)
    out["per_repeat_calibrated"] = {"outcome": v.outcome, "compared": v.compared,
                                    "agreeing": v.agreeing, "max_miss_s": round(v.max_miss_seconds, 1),
                                    "detail": v.detail}
    for i in range(len(pairs[0][0])):
        rr = [p[0][i] for p in pairs]
        pp = [p[1][i] for p in pairs]
        if all(x.status == "ok" for x in rr + pp):
            bins.append({"start": rr[0].start, "real_p50": [round(x.p50, 2) for x in rr],
                         "predicted_p50": [round(x.p50, 2) for x in pp]})
    out["per_repeat_bins"] = bins
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default="data/a4/exploratory/validation-diagnosis.json")
    args = ap.parse_args(argv)
    result = diagnose()
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {args.out}")
    print(f"as gated: {result['as_gated']}")
    print(f"per-repeat calibrated: {result['per_repeat_calibrated']['outcome']}, "
          f"{result['per_repeat_calibrated']['agreeing']}/{result['per_repeat_calibrated']['compared']} "
          f"agree, max miss {result['per_repeat_calibrated']['max_miss_s']} s")


if __name__ == "__main__":
    main()
