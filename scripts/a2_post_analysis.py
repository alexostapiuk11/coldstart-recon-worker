"""Every number artifact 2's post quotes, reduced once from committed evidence.

Writes `data/a2/post-analysis.json`. The post, its number formatter and its
figures read that file and nothing else, so a number in the post can be traced
to one line of one file, and a fresh run of this script must reproduce it byte
for byte (tests/test_a2_post_analysis.py). Rejected: letting each figure or
paragraph recompute what it needs, which is how two places come to quote two
roundings of one number, or the same name for two different numbers.

Inputs are committed files only (listed in the output's `_provenance`): the two
validation attempts' verdicts and records, the earlier one-replica repeats, the
five load-balancer probes, the exploratory host-speed stores and service-speed
sensitivity, the headline x1.00 frontier sweep, and the committed service curve
with its source store. Nothing is re-swept and nothing is bootstrapped: the
sweep and its gap intervals are read from their caches, and the only replays
are the validation gate's own (`autoscale.validation.engine_trajectories`, one
fixed-capacity run per repeat), which take under a second. Where the committed
data cannot give a number the post might want, the value is `null` beside a
`<key>_why` string, never an estimate.

The `simulator` section is from a simulator that FAILED its pre-registered
validation twice. It is labelled so here and must be labelled so wherever it is
quoted. H1, H2 and H4 there use the definitions the owner signed after the
x1.00 frontiers were seen (`autoscale/hypotheses.py`).
"""

import argparse
import gzip
import json
import math
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import a2_render_figures as render

from autoscale import hypotheses as hyp
from autoscale.a2_evidence import (
    delivered_rate,
    host_speed_table,
    per_worker_concurrency,
    stall_share,
)
from autoscale.frontier import (
    COMPARED_SIGNALS,
    gap_at_iso_cost,
    h3_verdict,
    iso_cost_budget,
    pareto_frontier,
)
from autoscale.measured_curve import load_measured_curve
from autoscale.validation import EngineRun, engine_trajectories, validate_engine_arrivals

A2 = Path("data/a2")
OUT = A2 / "post-analysis.json"
ATTEMPTS = {"engine": A2 / "validation-engine", "calibrated": A2 / "validation-calibrated"}
ONE_REPLICA = A2 / "validation"
PROBES = A2 / "lb-probes"
EXPLORATORY = A2 / "exploratory"
SWEEP = A2 / "frontier-sweep.json"
SENSITIVITY = EXPLORATORY / "sensitivity-service-speed.json"
CURVE = A2 / "service-curve.json"
HOST_LEVELS = (32, 64, 128)
HEADLINE = ("arm A", "arm C", "ramp arm A", "ramp arm C")
STEP_RAMP = {"arm A": ("arm A", "ramp arm A"), "arm C": ("arm C", "ramp arm C")}
# Probes 1-3 ran two workers; 1 shows the per-worker cap, 2 and 3 the fill-first routing.
CONCURRENCY_PROBES = ("1", "2", "3")
RETURN_LEG_S = 0.1
STALL_THRESHOLD_S = 2.0
WORKER = "x-a2-worker"
RETRY_MARK = "a2-driver-lb-retry"  # scripts/a2_lb_common.RETRY_MARK, "<status>:<seconds>"
LB_RETRY_STATUS = 502
UNVALIDATED = "simulator section: UNVALIDATED (failed validation twice)"
# A utilisation policy's cost equals the cap cost to this relative tolerance (the
# sums differ only in float accumulation order, ~1e-14 relative).
CAP_COST_RELATIVE_TOLERANCE = 1e-9


def _read_gz_json(path: Path):
    with gzip.open(REPO / path, "rt") as fh:
        return json.load(fh)


def _read_json(path: Path):
    return json.loads((REPO / path).read_text())


def _rel(paths) -> list[str]:
    return sorted(str(p) for p in paths)


# --- validation -----------------------------------------------------------------------


def _engine_run(record: dict) -> EngineRun:
    """An EngineRun from a record, calibrated or not.

    Mirrors `scripts/a2_validate._engine_runs`, which is not called because it
    refuses a record without host calibration -- correctly, for the gate it
    serves, and fatally for attempt 1, which was judged on the uncalibrated
    curve. Rejected: relaxing that refusal in a2_validate, which would let the
    calibrated gate judge an uncalibrated repeat.
    """
    received = [t if st == 200 else None
                for t, st in zip(record["server_received_s"], record["status"], strict=True)]
    latencies = [lat if st == 200 else None
                 for lat, st in zip(record["server_latency_s"], record["status"], strict=True)]
    ratios = (record.get("calibration") or {}).get("ratios")
    return EngineRun(sent=record["sent"], received=received, latencies=latencies,
                     replicas=record["replicas"], until=record["until"],
                     host_ids=tuple(record["host_ids"]),
                     host_ratios=tuple(ratios) if ratios else None)


def _check_verdict(name: str, recomputed, verdict: dict) -> None:
    """Refuse when the replay does not reproduce the committed verdict.

    The residuals are rebuilt from the records; if the rebuild judged
    differently from `verdict.json`, its residuals describe some other
    comparison and the post would quote them under the committed verdict's name.
    """
    got = (recomputed.outcome, recomputed.compared, recomputed.agreeing,
           recomputed.max_miss_seconds)
    want = (verdict["outcome"], verdict["compared"], verdict["agreeing"],
            verdict["max_miss_seconds"])
    if got != want:
        raise SystemExit(
            f"validation attempt {name!r}: replaying its records gives (outcome, compared, "
            f"agreeing, max miss) {got}, but its verdict.json says {want}. The residuals "
            "would describe a different comparison from the published verdict, so nothing "
            "is written")


def _typical_residual(verdicts, pairs) -> dict:
    """Median over judged bins of the per-bin median (over repeats) of real/predicted p50.

    Judged bins whose repeats all have an ok p50 on both sides only: a
    censoring-disagreement bin has no ratio (one side is backlogged), and it is
    counted, not guessed. The median across repeats first, then across bins, so
    one repeat's burst cannot set a bin's value. Rejected: the mean, for the
    house reason (right-skewed data), and pooling every repeat-bin pair, which
    would weight a bin by how many repeats happened to be ok in it.
    """
    judged = [i for i, v in enumerate(verdicts)
              if v.verdict in ("inside", "outside", "censoring_disagreement")]
    per_bin = []
    for i in judged:
        reals = [real[i] for real, _ in pairs]
        preds = [pred[i] for _, pred in pairs]
        if all(b.status == "ok" for b in (*reals, *preds)):
            per_bin.append(statistics.median(r.p50 / p.p50 for r, p in zip(reals, preds,
                                                                            strict=True)))
    if not per_bin:
        return {"median_ratio_real_over_predicted": None,
                "median_ratio_real_over_predicted_why": "no judged bin has an ok p50 on both "
                "sides in every repeat", "bins_judged": len(judged), "bins_used": 0}
    return {"median_ratio_real_over_predicted": statistics.median(per_bin),
            "range_over_bins": [min(per_bin), max(per_bin)],
            "bins_judged": len(judged), "bins_used": len(per_bin),
            "definition": "per judged bin with an ok p50 on both sides in all three repeats: "
                          "median over repeats of real p50 / predicted p50; then the median "
                          "and min..max of that over bins"}


def validation_section(curve, inputs: list) -> dict:
    out = {}
    for name, d in ATTEMPTS.items():
        verdict = _read_json(d / "verdict.json")
        records = []
        for k in (1, 2, 3):
            path = d / f"repeat-{k}.json.gz"
            inputs.append(path)
            records.append(_read_gz_json(path))
        voids = sorted((REPO / d).glob("repeat-*.void.json.gz"))
        inputs.extend(d / v.name for v in voids)
        inputs.append(d / "verdict.json")
        runs = [_engine_run(r) for r in records]
        pairs = [engine_trajectories(r, curve.curve) for r in runs]
        result = validate_engine_arrivals(runs, curve.curve)
        _check_verdict(name, result, verdict)
        per_repeat = []
        for pr in verdict["per_repeat"]:
            row = {"repeat": pr["repeat"], "host_ids": pr["host_ids"],
                   "server_p50_s": pr["server_p50_s"], "client_p50_s": pr["client_p50_s"],
                   "never_reached": pr["never_reached"], "lb_502_retried": pr["lb_502_retried"]}
            if "host_ratios" in pr:
                row["host_ratios"] = pr["host_ratios"]
            per_repeat.append(row)
        residuals = [[[r.start, (r.p50 - p.p50) if r.status == p.status == "ok" else None]
                      for r, p in zip(real, pred, strict=True)] for real, pred in pairs]
        out[name] = {
            "outcome": verdict["outcome"], "detail": verdict["detail"],
            "compared": verdict["compared"], "misses": verdict["misses"],
            "agreeing": verdict["agreeing"], "max_miss_seconds": verdict["max_miss_seconds"],
            "max_miss_is_censoring": verdict["max_miss_is_censoring"],
            "void_repeats": len(voids),
            "typical_residual": _typical_residual(result.bins, pairs),
            "per_repeat": per_repeat,
            "residuals": residuals,
            "residuals_definition": "per repeat, [bin start s, real p50 - predicted p50 s or "
                                    "null unless both sides ok], 10 s bins by engine arrival",
        }
    return out


# --- load balancer --------------------------------------------------------------------


def _probe_rows(probe: Path, rate: str) -> list[dict]:
    with gzip.open(REPO / probe / f"step-{rate}.jsonl.gz", "rt") as fh:
        return [json.loads(line) for line in fh]


def _worker_labels(steps: dict, summary_workers) -> dict:
    """Raw RunPod worker id -> "worker N", numbered by first request.

    Steps in ascending offered rate, rows in file order; a worker named only in
    the summary is numbered after those. The raw ids are not published:
    they name live RunPod workers and add nothing a reader can use.
    """
    labels: dict[str, str] = {}
    for rate in sorted(steps, key=float):
        for row in steps[rate]:
            w = (row.get("headers") or {}).get(WORKER)
            if w and w not in labels:
                labels[w] = f"worker {len(labels) + 1}"
    for w in summary_workers or ():
        if w not in labels:
            labels[w] = f"worker {len(labels) + 1}"
    return labels


def _first_attempt_s(row) -> float | None:
    mark = (row.get("headers") or {}).get(RETRY_MARK)
    if mark is None:
        return None
    status, _, seconds = mark.partition(":")
    if int(status) != LB_RETRY_STATUS:
        raise SystemExit(f"retry mark {mark!r} is not a {LB_RETRY_STATUS}; the driver only "
                         "retries a load-balancer 502, so the row cannot be read as one")
    return float(seconds)


def load_balancer_section(inputs: list) -> dict:
    probes = {}
    retries: dict[str, dict[str, list[float]]] = {}
    for probe in sorted((REPO / PROBES).iterdir()):
        n = probe.name.removeprefix("probe-")
        rel = PROBES / probe.name
        summary = _read_json(rel / "summary.json")
        inputs.append(rel / "summary.json")
        rows = {}
        for rate in summary["steps"]:
            rows[rate] = _probe_rows(rel, rate)
            inputs.append(rel / f"step-{rate}.jsonl.gz")
        labels = _worker_labels(rows, summary.get("workers"))
        steps = {}
        for rate, stats in summary["steps"].items():
            step = {k: v for k, v in stats.items() if k != "worker_share"}
            step["worker_share"] = {labels[w]: s for w, s in stats["worker_share"].items()}
            step["delivered_rate_rps"] = delivered_rate(rows[rate])
            if n in CONCURRENCY_PROBES:
                step["per_worker_concurrency"] = {
                    labels[w]: c for w, c in
                    per_worker_concurrency(rows[rate], return_leg_s=RETURN_LEG_S).items()}
            got = [s for s in (_first_attempt_s(r) for r in rows[rate]) if s is not None]
            if got:
                retries.setdefault(n, {})[rate] = got
            steps[rate] = step
        probes[n] = {"status": summary["status"], "workers": len(labels), "steps": steps}

    stall = []
    for path in sorted((REPO / ONE_REPLICA).glob("repeat-*.json.gz")):
        rel = ONE_REPLICA / path.name
        inputs.append(rel)
        rec = _read_gz_json(rel)
        ok = sum(1 for x, st in zip(rec["client_latency_s"], rec["status"], strict=True)
                 if x is not None and st == 200)
        stall.append({"repeat": rec["repeat"], "completed": ok, "void": rec["void"],
                      "share_over_threshold": stall_share(rec, threshold_s=STALL_THRESHOLD_S)})

    every = sorted(s for steps in retries.values() for got in steps.values() for s in got)
    return {
        "probes": probes,
        "per_worker_concurrency_return_leg_s": RETURN_LEG_S,
        "per_worker_concurrency_note": "server intervals reconstructed: each ends return_leg_s "
                                       "before the client saw the response and lasts the "
                                       "stamped server latency (autoscale.a2_evidence)",
        "stall_share": {"threshold_s": STALL_THRESHOLD_S,
                        "source": str(ONE_REPLICA) + " (one-replica repeats, client latency)",
                        "repeats": stall},
        "lb_502_first_attempt_s": {
            "probes": retries,
            "count": len(every),
            "min": every[0] if every else None,
            "median": statistics.median(every) if every else None,
            "max": every[-1] if every else None,
            "source": f"the {RETRY_MARK} header value '502:<seconds>' on rows of probes 3-5",
        },
        "lb_502_first_attempt_validation_s": None,
        "lb_502_first_attempt_validation_s_why":
            "the validation records keep only the indices of retried requests "
            "(lb_502_retried), not the retry header's value, so the first attempt's "
            "duration was not recorded for any validation repeat",
    }


# --- host speed -----------------------------------------------------------------------


def host_speed_section(curve, inputs: list) -> dict:
    doc = _read_json(CURVE)
    inputs.append(CURVE)
    latency = {int(c): lat for c, lat, _t, _u in curve.measured_points
               if int(c) in HOST_LEVELS}
    store = Path(doc["source_store"])
    inputs.append(store)
    curve_hosts: dict[str, set] = {}
    for line in (REPO / store).read_text().splitlines():
        r = json.loads(line)
        if r.get("outcome") == "ok" and int(r["level"]) in HOST_LEVELS:
            curve_hosts.setdefault(str(int(r["level"])), set()).add(r["host"]["host_id"])
    tables = {}
    for setting in ("maxseqs128", "maxseqs256"):
        path = EXPLORATORY / f"{setting}.jsonl"
        inputs.append(path)
        runs = [json.loads(line) for line in (REPO / path).read_text().splitlines()]
        # The run-to-run range beside the median, so the host-speed figure can draw
        # min..max bars from this file; host_speed_table reports the median only.
        spread: dict[tuple[str, int], list[float]] = {}
        for r in runs:
            if r.get("outcome") == "ok":
                key = (r["host"]["host_id"], int(r["level"]))
                spread.setdefault(key, []).append(r["latency_s"] / latency[key[1]])
        tables[setting] = {
            host: {str(level): {**row, "ratio_min": min(spread[(host, level)]),
                                "ratio_max": max(spread[(host, level)])}
                   for level, row in levels.items()}
            for host, levels in host_speed_table(runs, latency).items()}
    calibrated: dict[str, dict[str, list[float]]] = {}
    for k in (1, 2, 3):
        rec = _read_gz_json(ATTEMPTS["calibrated"] / f"repeat-{k}.json.gz")
        (host,) = rec["host_ids"]
        for level, entry in rec["calibration"]["levels"].items():
            calibrated.setdefault(host, {}).setdefault(level, []).append(entry["ratio"])
    return {
        "curve_latency_s": {str(c): latency[c] for c in sorted(latency)},
        "curve_hosts": {level: sorted(h) for level, h in curve_hosts.items()},
        "curve_hosts_source": str(store) + " (ok runs; the curve file names no host)",
        "exploratory": tables,
        "calibrated_ratios_by_host": calibrated,
        "calibrated_ratios_note": "per calibrated validation repeat, in repeat order: the "
                                  "host's median server latency over the curve's at that "
                                  "concurrency",
        "note": "hosts are the RunPod worker ids the findings doc already names; host ids are "
                "published, probe worker ids are not",
    }


# --- simulator ------------------------------------------------------------------------


def _compared(points) -> dict:
    by = render._by_signal(points)
    return {s: pareto_frontier(by[s]) for s in sorted(COMPARED_SIGNALS)}


def _reached(frontiers: dict, budget: float) -> dict:
    """Per signal: the reached p99 and the policy that reaches it (cheapest on a tie)."""
    p99 = hyp.reached_p99(frontiers, budget)
    out = {}
    for s, f in frontiers.items():
        best = min((p for p in f if p.cost <= budget and p.p99 == p99[s]),
                   key=lambda p: p.cost)
        out[s] = {"p99_s": p99[s], "cost_replica_s": best.cost, "n": best.n,
                  "scale_up_at": best.scale_up_at, "scale_down_at": best.scale_down_at}
    return out


def _gap_fields(g: dict) -> dict:
    if "point" not in g:
        return {"refused": g["refused"]}
    return {k: g[k] for k in ("point", "lo", "hi", "budget", "paired_repetitions")}


def _verdict_dict(v) -> dict:
    return {"holds": v.holds, "partial": v.partial, "evaluable": v.evaluable,
            "detail": v.detail}


def _h3(gaps: dict):
    return h3_verdict(
        step_gap_a=gaps["arm A"]["point"], step_gap_c=gaps["arm C"]["point"],
        ramp_gap_a=gaps["ramp arm A"]["point"], ramp_gap_c=gaps["ramp arm C"]["point"],
        step_gap_a_interval=(gaps["arm A"]["lo"], gaps["arm A"]["hi"]),
        ramp_gap_a_interval=(gaps["ramp arm A"]["lo"], gaps["ramp arm A"]["hi"]))


def _cap_cost(identity: dict) -> float:
    """Replica-seconds of a fleet that scales up at every chance until the cap.

    One initial replica for the whole window, then one more at each cooldown
    from the first evaluation after t=0 (t = evaluate_every) until
    max_replicas, none ever removed; each replica is billed from launch to the
    window's end (autoscale/sim.py, autoscale/controller.py).
    """
    until, every = identity["until"], identity["evaluate_every"]
    cooldown, cap = identity["cooldown"], identity["max_replicas"]
    return until + sum(until - every - k * cooldown for k in range(cap - 1))


def _censoring(sources: dict, identity: dict, curve) -> dict:
    """H2's mechanism, descriptively: does every utilisation policy sit at the replica cap?"""
    cap = _cap_cost(identity)
    per = {}
    for tag in HEADLINE:
        util = [p for p in sources[tag] if p.signal == "utilization"]
        costs = [c for p in util for c in p.cost_samples]
        top = max(c for p in sources[tag] if p.signal in COMPARED_SIGNALS
                  for c in p.cost_samples)
        per[tag] = {
            "utilization_policies": len(util),
            "utilization_cost_min": min(costs), "utilization_cost_max": max(costs),
            "highest_cost_any_compared_policy": top,
            "every_utilization_run_at_cap_cost": all(
                math.isclose(c, cap, rel_tol=CAP_COST_RELATIVE_TOLERANCE) for c in costs),
        }
    util_levels = [u for c, _lat, _t, u in curve.measured_points]
    return {
        "cap_cost_replica_s": cap,
        "cap_cost_definition": "one initial replica for the window plus one more at every "
                               "cooldown from the first evaluation (t = evaluate_every) up "
                               "to max_replicas, none removed: until + sum over k = 0.."
                               "max_replicas-2 of (until - evaluate_every - k * cooldown)",
        "max_replicas": identity["max_replicas"],
        "per_sweep": per,
        "curve_gpu_util_min_over_measured_levels": min(util_levels),
        "highest_utilization_scale_up_threshold": max(identity["thresholds"]["utilization"][0]),
        "reading": "the curve reads GPU utilisation 1.0 at every measured level, above every "
                   "scale-up threshold, so the utilisation controller scales up at every "
                   "chance; every utilisation run's cost equals the cap cost",
    }


def simulator_section(curve, inputs: list) -> dict:
    sources, _swept, gaps1, raw = render._load(REPO / SWEEP)
    inputs.append(SWEEP)
    sens = _read_json(SENSITIVITY)
    inputs.append(SENSITIVITY)
    identity = raw["identity"]

    frontiers = {tag: _compared(sources[tag]) for tag in HEADLINE}
    for tag in HEADLINE:
        f = frontiers[tag]
        point = gap_at_iso_cost(f, cost=iso_cost_budget(f))
        if not math.isclose(point, gaps1[tag]["point"], rel_tol=1e-12):
            raise SystemExit(
                f"{tag}: the frontier gap recomputed from {SWEEP}'s points is {point}, but its "
                f"cached gap is {gaps1[tag]['point']}; the per-sweep reached p99s below would "
                "not be the slice the published gap was taken on")

    gaps = {"1": {t: _gap_fields(gaps1[t]) for t in HEADLINE}}
    h3 = {"1": _verdict_dict(_h3(gaps1))}
    for factor in sorted(sens, key=float):
        g = sens[factor]["gaps"]
        gaps[factor] = {t: _gap_fields(g[t]) for t in HEADLINE}
        h3[factor] = sens[factor]["h3"]
        if all("point" in g[t] for t in HEADLINE) and _verdict_dict(_h3(g)) != h3[factor]:
            raise SystemExit(f"x{factor}: h3_verdict on the committed gaps disagrees with the "
                             f"verdict stored in {SENSITIVITY}; one of them is stale")

    sweeps = {}
    for tag in HEADLINE:
        f = frontiers[tag]
        budget = iso_cost_budget(f)
        sweeps[tag] = {"budget_replica_s": budget, "reached": _reached(f, budget),
                       "ranking": hyp.ranking(f), "h1": hyp.h1_holds_on(f),
                       "h2": hyp.h2_worst_on(f)}
    h1_step = {arm: sweeps[arm]["h1"] for arm in ("arm A", "arm C")}
    h2_all = {tag: sweeps[tag]["h2"] for tag in HEADLINE}
    h4 = {arm: hyp.h4_holds_on(frontiers[step], frontiers[ramp])
          for arm, (step, ramp) in STEP_RAMP.items()}

    sensitivity = {}
    for tag in HEADLINE:
        # Swapped as a2_render_figures builds its sensitivity set: the headline points
        # minus utilisation, plus the throughput-fraction arm, which then stands in the
        # "utilization" slot so hypotheses' signal set is unchanged.
        thru = [p for p in sources[f"sensitivity {tag}"]
                if p.signal == "utilization_throughput"]
        f = {**{s: v for s, v in frontiers[tag].items() if s != "utilization"},
             "utilization": pareto_frontier(thru)}
        budget = iso_cost_budget(f)
        sensitivity[tag] = {"budget_replica_s": budget, "reached": _reached(f, budget),
                            "h2": hyp.h2_worst_on(f)}

    return {
        "label": UNVALIDATED,
        "gaps": gaps,
        "h3": h3,
        "sweeps": sweeps,
        "h1": {"per_sweep": {t: sweeps[t]["h1"] for t in HEADLINE}, **h1_step,
               "overall": all(h1_step.values()),
               "definition": "holds only if it holds on both step arms"},
        "h2": {"per_sweep": h2_all, "overall": all(h2_all.values()),
               "definition": "holds only if it holds on both arms and both shapes"},
        "h4": {**h4, "overall": all(h4.values())},
        "h2_sensitivity": {
            "per_sweep": sensitivity,
            "overall": all(s["h2"] for s in sensitivity.values()),
            "definition": "H2 with utilization_throughput (the 'sensitivity <sweep>' sources) "
                          "in utilisation's place; queue depth and in-flight frontiers are the "
                          "headline's, and the iso-cost budget is recomputed for the set"},
        "h2_censoring": _censoring(sources, identity, curve),
        "identity": {k: identity[k] for k in ("seed", "repetitions", "until", "max_replicas",
                                              "cooldown", "evaluate_every")},
    }


def build() -> dict:
    curve = load_measured_curve(REPO / CURVE)
    inputs: list = []
    analysis = {
        "validation": validation_section(curve, inputs),
        "load_balancer": load_balancer_section(inputs),
        "host_speed": host_speed_section(curve, inputs),
        "simulator": simulator_section(curve, inputs),
        "spend": None,
    }
    analysis["_provenance"] = {"inputs": sorted(set(_rel(inputs))), "label": UNVALIDATED,
                               "script": "scripts/a2_post_analysis.py"}
    return analysis


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    out = Path(args.out)
    text = json.dumps(build(), indent=1, sort_keys=True, allow_nan=False) + "\n"
    out.write_text(text)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
