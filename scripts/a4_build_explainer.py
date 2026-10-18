"""Build artifact 4's private explainer page from its template and the committed data.

    PYTHONPATH=. .venv/bin/python scripts/a4_build_explainer.py [--check]

`explainer/a4/page.template.html` holds the prose and the interactives; every number the
page shows comes from the JSON this script embeds, read from `data/a4/analysis.json`,
`data/a4/exploratory/*.json` and the registered constants. Prose that quotes a number
binds it with `data-v="path"`, so the number cannot drift from the data. `--check` writes
nothing and exits 1 if `explainer/a4/page.html` is not what the template and data build,
the same discipline `tests/test_a4_post.py` holds the post to.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from placement import registered as R
from placement_measure.prereg import SOLO_GMU, SPLIT_GMU

TEMPLATE = REPO / "explainer" / "a4" / "page.template.html"
PAGE = REPO / "explainer" / "a4" / "page.html"
MARK = "__DATA__"


def _strategy(view: dict | None) -> dict | None:
    if view is None:
        return None
    return {"m": view["m"], "cost_per_tenant": view["cost_per_tenant_month"],
            "cost_per_mtok": view["cost_per_million_tokens"],
            "agg_p99": view["aggregate_p99"]["point"], "decile_p99": view["decile_p99"],
            "hit_rate": view["hit_rate"], "swaps_per_hour": view["swaps_per_hour"]}


def _regime(body: dict) -> dict:
    points = []
    for p in body["points"]:
        if not p["evaluable"]:
            points.append({"s": p["s"], "evaluable": False})
            continue
        points.append({"s": p["s"], "evaluable": True, "cheapest": p["cheapest"],
                       "strategies": {k: _strategy(v) for k, v in p["strategies"].items()},
                       "aggregate_rule": {k: (None if v is None else
                                              {"m": v["m"], "decile_p99": v["decile_p99"]})
                                          for k, v in p["aggregate_rule"].items()},
                       "dedicate_over_cheapest": p["dedicate_over_cheapest_per_month"]})
    return {"rule": body["decision_rule"], "gaps": body["gaps"], "points": points}


def data() -> dict:
    analysis = json.loads((REPO / "data/a4/analysis.json").read_text())
    sens = json.loads((REPO / "data/a4/exploratory/interference-sensitivity.json").read_text())
    diag = json.loads((REPO / "data/a4/exploratory/validation-diagnosis.json").read_text())
    inputs = analysis["inputs"]
    return {
        "slo": analysis["design"]["slo_seconds"],
        "rate": analysis["rate"]["gpu_hourly_rate"],
        "hours_month": 730,
        "repetitions": analysis["design"]["repetitions"],
        "n_models": analysis["design"]["n_models"],
        "saturation_rps": inputs["saturation_rps"],
        "reference": analysis["reference"],
        "swap": {"n": inputs["swaps"]["simulated"]["n"],
                 "median": inputs["swaps"]["simulated"]["p50"], "stages": inputs["stages"]["stages"]},
        "a1": {"stages": inputs["a1_reference"]["stages"], "model": inputs["a1_reference"]["model"],
               "n": inputs["a1_reference"]["n"]},
        "sleep": {"n": inputs["sleep_mode"]["n"], "p50": inputs["sleep_mode"]["p50"]},
        "surface": inputs["surface"],
        "kv": {**inputs["kv"], "solo_gmu": SOLO_GMU, "split_gmu": SPLIT_GMU,
               "input_len": R.INPUT_LEN, "output_len": R.OUTPUT_LEN,
               "request_tokens": R.INPUT_LEN + R.OUTPUT_LEN},
        "regimes": {k: _regime(v) for k, v in analysis["regimes"].items()},
        "held_out": analysis["held_out"],
        "sens": sens,
        "validation": {k: analysis["validation"][k] for k in ("outcome", "latency", "swaps", "requests")},
        "diag": {"campaign_swap_median_s": diag["campaign_swap_median_s"],
                 "replay_swap_median_s": diag["replay_swap_median_s"],
                 "swap_cost": diag["swap_cost"], "curve_speed": diag["curve_speed"],
                 "per_repeat_calibrated": diag["per_repeat_calibrated"],
                 "per_repeat_bins": diag["per_repeat_bins"]},
    }


def build() -> str:
    template = TEMPLATE.read_text()
    if template.count(MARK) != 1:
        raise SystemExit(f"{TEMPLATE} must contain {MARK} exactly once")
    blob = json.dumps(data(), separators=(",", ":"), sort_keys=True)
    return template.replace(MARK, blob.replace("</", "<\\/"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    page = build()
    if args.check:
        if not PAGE.exists() or PAGE.read_text() != page:
            print("explainer/a4/page.html is stale: rebuild with scripts/a4_build_explainer.py")
            return 1
        print("explainer/a4/page.html: identical")
        return 0
    PAGE.write_text(page)
    print(f"wrote {PAGE.relative_to(REPO)} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
