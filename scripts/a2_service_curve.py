"""Artifact 2's side of the service-curve sweep: tuples in, `ServiceCurve` out.

    .venv/bin/python scripts/a2_service_curve.py \\
        --curve data/a2/service-sweep-curve.json --out data/a2/service-curve.json

The harness reduction emits plain tuples so that no artifact's types leak into
another's (artifact 5 bans `autoscale`). This adapter is where artifact 2
takes them: it builds a `ServiceCurve`, which re-validates every point, and it
records `max_num_seqs`, which docs/recon-a2.md requires the pilot sweep to
record rather than assume -- the curve's top level becomes the simulator's
per-replica admission cap, and whether that cap is the engine's own limit or
something below it changes what the cap means.

`measured` is True only for a curve whose `source` is "runpod". A stub curve
still converts, so the GPU-free tests exercise this path, but as
`measured=False`, the flag artifact 2's figures already print as NOT MEASURED.
A curve with no `source` at all is also not measured: the flag is earned by
the one positive value, never defaulted into.

`ServiceCurve` holds only points, but figure 4 draws an interval per level
(spec section 11), so the output JSON carries the reduction's per-level
min..max ranges beside the points (`intervals`). Dropping them here would
leave the figure to recompute them from a store it should not need to read.

Little's-law disclosure. The curve's latency is a MEDIAN, and
`autoscale/traffic.py` takes saturation as max(c / latency_at(c)); Little's
law gives c = throughput x MEAN latency. Latency is right-skewed, so the
median sits below the mean and c / median_latency overstates the rate the
engine sustained. `--store` (default: the store the curve file names) lets the
adapter compare c / latency_s with the bench tool's own `request_throughput`
per level and print the ratio. It is DISCLOSURE, not a gate: nobody knows yet
what ratio is too far from 1, and a made-up threshold would refuse a good
sweep or bless a bad one. A level whose throughput cannot be found is reported
as unavailable; it is never filled from a neighbour or recomputed from other
fields.
"""

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoscale.service import ServiceCurve
from harness.stats import median

# The reduction's per-level interval fields, and the point column each bounds.
# ttft is carried too (it is not a curve column) so the figure can show it.
_INTERVAL_FIELDS = ("latency_s", "throughput_tps", "gpu_util", "ttft_median_s")
_BOUNDS_POINT_COLUMN = {"latency_s": 1, "throughput_tps": 2, "gpu_util": 3}


def max_num_seqs_of(curve_doc: dict) -> tuple[int, str]:
    """The one max_num_seqs every successful run reported, and where it was read."""
    engine = curve_doc.get("engine") or {}
    values = engine.get("max_num_seqs") or []
    sources = engine.get("max_num_seqs_source") or []
    if len(values) != 1 or values[0] is None:
        raise ValueError(
            f"the sweep's runs reported max_num_seqs {values!r}, not exactly one value; "
            "docs/recon-a2.md requires it recorded, and the curve's top level cannot "
            "be read as a per-replica cap without it. Pass --max-num-seqs explicitly "
            "in the sweep's --serve-args so the engine logs it"
        )
    return values[0], sources[0] if len(sources) == 1 else "mixed"


def intervals_of(curve_doc: dict) -> list[dict]:
    """One `{concurrency, <field>_range}` entry per level, in the points' order.

    Refuses a level with a missing or malformed range, and a range that does
    not contain its own point: figure 4 would draw a whisker that excludes the
    value it is a whisker for, or no whisker at all, and neither looks wrong
    on the page. The alternative, passing `levels` through untouched, would
    let a reduction that stopped writing ranges produce an adapter output
    that still looks complete.
    """
    points, levels = curve_doc["points"], curve_doc["levels"]
    if [row["concurrency"] for row in levels] != [p[0] for p in points]:
        raise ValueError(
            f"the sweep's level rows are at concurrencies {[r['concurrency'] for r in levels]} "
            f"but its points are at {[p[0] for p in points]}; pairing a point with another "
            "level's interval would draw the wrong error bar on every level after the mismatch"
        )
    out = []
    for row, point in zip(levels, points, strict=True):
        entry = {"concurrency": row["concurrency"]}
        for name in _INTERVAL_FIELDS:
            key = f"{name}_range"
            rng = row.get(key)
            if not isinstance(rng, (list, tuple)) or len(rng) != 2 or not rng[0] <= rng[1]:
                raise ValueError(
                    f"level {row['concurrency']} has {key}={rng!r}, not a [min, max] pair; "
                    "figure 4 needs an interval per level (spec section 11) and would draw "
                    "this level without one"
                )
            column = _BOUNDS_POINT_COLUMN.get(name)
            if column is not None and not rng[0] <= point[column] <= rng[1]:
                raise ValueError(
                    f"level {row['concurrency']}: the point's {name}={point[column]!r} is "
                    f"outside its own {key}={list(rng)!r}; the median of the run medians "
                    "cannot leave their min..max, so the points and the intervals come "
                    "from different reductions"
                )
            entry[key] = list(rng)
        out.append(entry)
    return out


def _usable(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _level_request_throughput(row: dict, runs) -> tuple[float | None, str | None]:
    """(value, None) or (None, why-not): the level's measured request_throughput.

    Every stored run of the level must have a usable one, because the latency
    it is compared with is a median over those same runs; a median over the
    survivors would be a different set of runs. A zero, negative or non-finite
    value is data corruption and is reported as unavailable: dividing by it
    would print an infinite or negative ratio that looks like a finding.
    """
    if row.get("request_throughput") is not None:
        values = [row["request_throughput"]]
    elif runs is None:
        return None, "the curve rows carry no request_throughput and no store was given"
    else:
        by_id = {r.get("run_id"): r for r in runs}
        values = []
        for run_id in row["run_ids"]:
            scalars = ((by_id.get(run_id) or {}).get("summary") or {}).get("bench_scalars") or {}
            values.append(scalars.get("request_throughput"))
        if None in values:
            return None, (
                f"run {row['run_ids'][values.index(None)]!r} has no stored request_throughput "
                "in its bench scalars; the median over only the runs that kept it would "
                "describe a different set of runs than the latency"
            )
    bad = [v for v in values if not _usable(v)]
    if bad:
        return None, (
            f"request_throughput {bad[0]!r} is not a positive finite number; "
            "a ratio computed from it would be meaningless"
        )
    return median(values), None


def littles_law_rows(curve_doc: dict, runs=None) -> list[dict]:
    """Per level: c / latency_s beside the measured request_throughput, and their ratio.

    ratio = (c / latency_s) / request_throughput, so above 1 means the median
    latency sits below the mean and saturation computed from the curve
    overstates what the engine sustained. The bench tool's request_throughput
    is completed / duration over the whole run, ramp-up and drain included, so
    even a perfectly symmetric latency distribution would not give exactly 1;
    the ratio is evidence to read, not an equality to test.
    """
    out = []
    for row in curve_doc["levels"]:
        c, latency = row["concurrency"], row["latency_s"]
        throughput, why = _level_request_throughput(row, runs)
        c_over_latency = c / latency
        out.append({
            "concurrency": c,
            "latency_s": latency,
            "c_over_latency": c_over_latency,
            "request_throughput": throughput,
            "ratio": None if throughput is None else c_over_latency / throughput,
            "unavailable": why,
        })
    return out


def build_service_curve(curve_doc: dict, runs=None) -> tuple[ServiceCurve, dict]:
    """`runs`: the sweep's stored records as dicts, for the Little's-law comparison only."""
    max_num_seqs, source = max_num_seqs_of(curve_doc)
    intervals = intervals_of(curve_doc)
    curve = ServiceCurve(
        points=[tuple(p) for p in curve_doc["points"]],
        measured=curve_doc.get("source") == "runpod",
    )
    meta = {
        "measured": curve.measured,
        "points": [list(p) for p in curve.points],
        "intervals": intervals,
        "littles_law": littles_law_rows(curve_doc, runs),
        "levels": curve_doc["levels"],
        "statistic": curve_doc["statistic"],
        "prompt_path": curve_doc["prompt_path"],
        "served_cmd": curve_doc["served_cmd"],
        "max_num_seqs": max_num_seqs,
        "max_num_seqs_source": source,
        "top_level_above_max_num_seqs": curve.max_measured_concurrency > max_num_seqs,
        "sweep_source": curve_doc.get("source"),
    }
    return curve, meta


def load_service_curve(path) -> ServiceCurve:
    doc = json.loads(Path(path).read_text())
    return ServiceCurve(points=[tuple(p) for p in doc["points"]], measured=doc["measured"])


def _read_runs(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--curve", required=True, help="run_service_sweep.py's --out file")
    ap.add_argument("--store", help="the sweep's JSONL store; default: the one the curve names")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    curve_doc = json.loads(Path(args.curve).read_text())
    store = args.store or curve_doc.get("store")
    runs = _read_runs(store) if store and Path(store).exists() else None
    curve, meta = build_service_curve(curve_doc, runs)
    meta["source_curve"] = args.curve
    meta["source_store"] = store if runs is not None else None
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    label = "MEASURED" if curve.measured else "NOT MEASURED (stub)"
    print(f"[a2] {len(curve.points)} points, max_num_seqs={meta['max_num_seqs']}, {label}")
    if meta["top_level_above_max_num_seqs"]:
        print(f"[a2] WARNING: top level {curve.max_measured_concurrency} is above max_num_seqs")
    print("[a2] Little's law, c / median latency vs the bench tool's request_throughput "
          "(ratio > 1: the median latency is below the mean; disclosure, not a gate):")
    for row in meta["littles_law"]:
        ratio = "unavailable" if row["ratio"] is None else f"{row['ratio']:.2f}"
        seen = "n/a" if row["request_throughput"] is None else f"{row['request_throughput']:.2f}"
        print(f"[a2]   c={row['concurrency']:<4} c/latency={row['c_over_latency']:.2f} req/s "
              f"bench={seen} req/s ratio={ratio}")


if __name__ == "__main__":
    main()
