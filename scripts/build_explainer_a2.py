"""Assemble artifact 2's learning page from committed data.

The sibling of scripts/build_explainer.py, adapted rather than imported from: that
script reads artifact 1's campaign and is tied to matplotlib charts, and this one
reads artifact 2's analysis files. Artifact 1's explainer is untouched.

Substitutions, every one a derivation and none a transcription:

    {{key}}            a number on explainer_a2/numbers.json, formatted by its spec
    {{def:term}}       a term's definition, verbatim from explainer_a2/terms.json
    {{checkpoint:N}}   module N's checkpoint, read from docs/learning/plan.md
    {{selfcheck:N}}    spec 13b's self-check question N, read from the design spec
    {{data}}           the JSON the widgets run on, built from the committed files
    {{inline:name}}    a file from explainer_a2/ (the widget code), pasted in

An unknown placeholder fails the build. Nothing numeric reaches the page except
through here, and the widget code reads its numbers from {{data}}.

    .venv/bin/python scripts/build_explainer_a2.py --out build/explainer_a2/index.html
"""

import argparse
import html as html_mod
import json
import re
import statistics
import sys
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from autoscale.figures_a2_post import SYMLOG_LINTHRESH_S
from autoscale.frontier import PolicyPoint, iso_cost_budget, pareto_frontier
from autoscale.traffic import saturation_rps
from autoscale.validation import (
    BAND_EDGE_TOLERANCE_SECONDS,
    CALIBRATION_LEVELS,
    MAX_MISS_FRACTION,
    MIN_COMPARED_BINS,
)

A2 = REPO / "explainer_a2"
PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")
SPEC = "docs/superpowers/specs/2026-08-17-autoscaling-signal-comparison-design.md"

# The four sweeps the page offers, in display order. The labels carry the shape of
# the spike and the cold-start arm; the keys are frontier-sweep.json's own.
SWEEPS = (
    ("arm A", "step, arm A"),
    ("arm C", "step, arm C"),
    ("ramp arm A", "ramp, arm A"),
    ("ramp arm C", "ramp, arm C"),
)
SIGNAL_ORDER = ("queue_depth", "in_flight_concurrency", "utilization")
# Where in the 400 s window the toy's spike begins. The toy's own choice: the
# artifact's simulator does not publish one in the committed files read here.
TOY_SPIKE_START_S = 30.0
# Requests waiting per serving replica at which the toy adds a replica. 8 is a
# member of the queue-depth grid in frontier-sweep.json's identity; the toy runs
# one policy, so it carries one threshold.
TOY_UP_AT = 8.0
# Probes whose steps the Little's Law table reads. Probe 1 is the capped pair of
# workers. Probes 2 and 3 are the same endpoint type uncapped, whose low-rate
# steps were all served by one worker. Probes 4 and 5 carry no per-worker
# in-flight counts in post-analysis.json (only probes 1 to 3 are reconstructed).
# Self-check 7 in the design spec (section 13b): two policies as (cost, damage). The
# page's exercise runs on these; tests/test_explainer_a2_numbers.py checks them
# against the spec's own wording.
EXERCISE = ((100, 50), (120, 40))
# How many reruns the Monte Carlo's "many" button and its histogram draw. A design
# choice of the page: large enough that the miss share settles to a whole percent.
MC_RUNS = 1000
CAPPED_PROBE = "1"
UNCAPPED_PROBES = ("2", "3")


def read_json(rel: str, repo: Path = REPO):
    return json.loads((Path(repo) / rel).read_text())


def analysis(repo: Path = REPO) -> dict:
    return read_json("data/a2/post-analysis.json", repo)


def curve_file(repo: Path = REPO) -> dict:
    return read_json("data/a2/service-curve.json", repo)


def sweep_file(repo: Path = REPO) -> dict:
    return read_json("data/a2/frontier-sweep.json", repo)


# --- numbers -----------------------------------------------------------------

KEYS: dict = json.loads((A2 / "numbers.json").read_text())
TERMS: dict[str, str] = json.loads((A2 / "terms.json").read_text())


def _dig(obj, path: str):
    for part in path.split("/"):
        obj = obj[part]
    return obj


def _points(rows):
    return [
        PolicyPoint(cost_samples=tuple(c), p99_samples=tuple(p), signal=s, scale_up_at=u,
                    scale_down_at=d, rep_indices=tuple(r))
        for c, p, s, u, d, r in rows
    ]


def sweep_frontiers(repo: Path, key: str) -> dict:
    """{signal: [PolicyPoint]} frontier of one sweep, by the repo's own functions."""
    pts = _points(sweep_file(repo)["sources"][key])
    return {s: pareto_frontier([p for p in pts if p.signal == s]) for s in SIGNAL_ORDER}


def curve_levels(repo: Path) -> list[dict]:
    return curve_file(repo)["levels"]


def _level(repo: Path, c: int) -> dict:
    return next(lv for lv in curve_levels(repo) if lv["concurrency"] == c)


def c_lat_first(repo):
    return curve_levels(repo)[0]["latency_s"]


def c_lat_last(repo):
    return curve_levels(repo)[-1]["latency_s"]


def c_lat_ratio(repo):
    return c_lat_last(repo) / c_lat_first(repo)


def c_tps_first(repo):
    return curve_levels(repo)[0]["throughput_tps"]


def c_tps_last(repo):
    return curve_levels(repo)[-1]["throughput_tps"]


def c_tps_ratio(repo):
    return c_tps_last(repo) / c_tps_first(repo)


def c_per_request_first(repo):
    lv = curve_levels(repo)[0]
    return lv["throughput_tps"] / lv["concurrency"]


def c_per_request_last(repo):
    lv = curve_levels(repo)[-1]
    return lv["throughput_tps"] / lv["concurrency"]


def c_levels_count(repo):
    return len(curve_levels(repo))


def c_top_level(repo):
    return curve_levels(repo)[-1]["concurrency"]


def c_runs_per_level(repo):
    return curve_levels(repo)[0]["n_runs"]


def c_excluded_level(repo):
    return curve_file(repo)["excluded_levels"][0]["concurrency"]


def c_excluded_runs(repo):
    return curve_file(repo)["excluded_levels"][0]["n_runs"]


def c_excluded_requests(repo):
    """The request count the failed level reports, parsed from the curve file's own
    reason string ("0 of 5120 requests served"), so it is read and not retyped."""
    reason = curve_file(repo)["excluded_levels"][0]["reason"]
    return int(re.search(r"0 of (\d+) requests served", reason).group(1))


def c_lat_64(repo):
    return _level(repo, 64)["latency_s"]


def c_tps_64(repo):
    return _level(repo, 64)["throughput_tps"]


def p1_step(repo, step: str) -> dict:
    return analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["steps"][step]


def p1_cap(repo):
    """The per-worker peak in flight that probe 1 reconstructs: the most common
    maximum over its workers and steps. The post says every peak was this value
    except one reading that is one higher."""
    peaks = [w["max"] for s in analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["steps"]
             .values() for w in s["per_worker_concurrency"].values()]
    return statistics.mode(peaks)


def p1_peak_over(repo):
    peaks = [w["max"] for s in analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["steps"]
             .values() for w in s["per_worker_concurrency"].values()]
    return max(peaks)


def p1_workers(repo):
    return analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["workers"]


def p1_ceiling_in_flight(repo):
    return p1_cap(repo) * p1_workers(repo)


def p1_ceiling_rps(repo):
    return p1_ceiling_in_flight(repo) / 0.31


def p1_mean_per_worker(repo):
    conc = p1_step(repo, "50")["per_worker_concurrency"]
    return sum(w["mean"] for w in conc.values()) / len(conc)


def p1_cap_share(repo):
    conc = p1_step(repo, "50")["per_worker_concurrency"]
    return sum(w["mean"] for w in conc.values()) / p1_ceiling_in_flight(repo)


def p1_total_in_flight(repo):
    conc = p1_step(repo, "50")["per_worker_concurrency"]
    return sum(w["mean"] for w in conc.values())


def p1_time_in_engine(repo):
    return p1_total_in_flight(repo) / p1_step(repo, "50")["delivered_rate_rps"]


def p1_w1(repo):
    return p1_step(repo, "50")["per_worker_concurrency"]["worker 1"]["mean"]


def p1_w2(repo):
    return p1_step(repo, "50")["per_worker_concurrency"]["worker 2"]["mean"]


def p1_delivered_median(repo):
    steps = analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["steps"]
    return statistics.median(s["delivered_rate_rps"] for s in steps.values())


def p1_offered_steps(repo):
    steps = sorted(int(k) for k in analysis(repo)["load_balancer"]["probes"][CAPPED_PROBE]["steps"])
    return steps


def cap_cost_check(repo):
    """Where 3,095 comes from: one replica for the whole window, plus one more at
    every cooldown from the first evaluation up to the cap, none removed. This is
    the formula post-analysis.json states in words (`cap_cost_definition`)."""
    ident = sweep_file(repo)["identity"]
    until, every, cool, cap = (ident[k] for k in ("until", "evaluate_every", "cooldown",
                                                  "max_replicas"))
    return until + sum(until - every - k * cool for k in range(cap - 1))


def util_policies(repo):
    return analysis(repo)["simulator"]["h2_censoring"]["per_sweep"]["arm A"]["utilization_policies"]


def util_all_at_cap(repo):
    per = analysis(repo)["simulator"]["h2_censoring"]["per_sweep"]
    return sum(1 for s in per.values() if s["every_utilization_run_at_cap_cost"])


def policies_per_sweep(repo):
    rows = sweep_file(repo)["sources"]["arm A"]
    return len(rows)


def policies_by_signal(repo, signal):
    return sum(1 for r in sweep_file(repo)["sources"]["arm A"] if r[2] == signal)


def policies_queue(repo):
    return policies_by_signal(repo, "queue_depth")


def policies_flight(repo):
    return policies_by_signal(repo, "in_flight_concurrency")


def policies_util(repo):
    return policies_by_signal(repo, "utilization")


def saturation(repo):
    from autoscale.measured_curve import load_measured_curve

    return saturation_rps(load_measured_curve(REPO / "data/a2/service-curve.json").curve)


def toy_baseline(repo):
    return sweep_file(repo)["identity"]["baseline_fraction"] * saturation(repo)


def toy_peak(repo):
    ident = sweep_file(repo)["identity"]
    return toy_baseline(repo) + ident["additional_replicas"] * saturation(repo)


def toy_peak_x(repo):
    return toy_peak(repo) / saturation(repo)


def toy_baseline_pct(repo):
    return sweep_file(repo)["identity"]["baseline_fraction"] * 100


def toy_extra(repo):
    return sweep_file(repo)["identity"]["additional_replicas"]


def toy_extra_pct(repo):
    return (toy_peak_x(repo) - 1) * 100


def sid(repo, key):
    return sweep_file(repo)["identity"][key]


def sweep_sustain(repo):
    return sid(repo, "sustain")


def sweep_every(repo):
    return sid(repo, "evaluate_every")


def sweep_cooldown(repo):
    return sid(repo, "cooldown")


def sweep_cap(repo):
    return sid(repo, "max_replicas")


def sweep_until(repo):
    return sid(repo, "until")


def sweep_reps(repo):
    return sid(repo, "repetitions")


def sweep_budget(repo):
    return analysis(repo)["simulator"]["h2_censoring"]["cap_cost_replica_s"]


def other_cost(repo, sweep):
    return analysis(repo)["simulator"]["h2_noise"]["per_sweep"][sweep][
        "others_highest_frontier_cost_replica_s"]


def other_cost_a(repo):
    return other_cost(repo, "arm A")


def other_cost_c(repo):
    return other_cost(repo, "arm C")


def other_cost_ra(repo):
    return other_cost(repo, "ramp arm A")


def other_cost_rc(repo):
    return other_cost(repo, "ramp arm C")


def at_cap(repo, sweep, field):
    return analysis(repo)["simulator"]["h2_noise"]["per_sweep"][sweep]["at_cap_policy_p99_s"][field]


def spread_a(repo):
    return at_cap(repo, "arm A", "max") - at_cap(repo, "arm A", "min")


def spread_c(repo):
    return at_cap(repo, "arm C", "max") - at_cap(repo, "arm C", "min")


def spread_ra(repo):
    return at_cap(repo, "ramp arm A", "max") - at_cap(repo, "ramp arm A", "min")


def spread_rc(repo):
    return at_cap(repo, "ramp arm C", "max") - at_cap(repo, "ramp arm C", "min")


def margin_ms(repo, sweep, key):
    return analysis(repo)["simulator"]["h2_noise"]["per_sweep"][sweep][key] * 1000


def margin_worse_a(repo):
    return margin_ms(repo, "arm A", "h2_margin_s")


def margin_better_a(repo):
    return margin_ms(repo, "arm A", "margin_vs_best_other_s")


def validation_pct_off(repo, attempt):
    """How far the real median latency sat from the prediction, in percent, from
    the typical per-bin ratio (real over predicted). Below 1 is below."""
    ratio = analysis(repo)["validation"][attempt]["typical_residual"]["median_ratio_real_over_predicted"]
    return abs(1 - ratio) * 100


def pct_off_engine(repo):
    return validation_pct_off(repo, "engine")


def pct_off_calibrated(repo):
    return validation_pct_off(repo, "calibrated")


def factor_engine(repo):
    """Prediction over real for attempt 1: the host factor that makes the Monte
    Carlo's model as wrong as attempt 1's was (prediction = truth x this)."""
    return 1 / analysis(repo)["validation"]["engine"]["typical_residual"][
        "median_ratio_real_over_predicted"]


def factor_calibrated(repo):
    return 1 / analysis(repo)["validation"]["calibrated"]["typical_residual"][
        "median_ratio_real_over_predicted"]


def allowed_misses(repo):
    return int(MAX_MISS_FRACTION * analysis(repo)["validation"]["engine"]["compared"])


def mc_truth(repo):
    """The synthetic bins' true p50: the mean of the calibrated repeats' server p50s."""
    reps = analysis(repo)["validation"]["calibrated"]["per_repeat"]
    return statistics.mean(r["server_p50_s"] for r in reps)


def mc_spread(repo):
    """The real repeats' relative spread, estimated from what post-analysis.json
    keeps: per judged bin, the sample standard deviation of the three calibrated
    repeats' residuals, then the median over bins, over the true p50 above.

    An estimate, and a generous one. Each repeat is held to its own prediction,
    so the residuals' spread is the repeats' spread plus any difference between
    the three predictions. Rejected: going back to the three 2.4 MB record files,
    which would make the build read files this page's data contract does not
    include.
    """
    res = analysis(repo)["validation"]["calibrated"]["residuals"]
    sds = []
    for i in range(len(res[0])):
        vals = [r[i][1] for r in res if r[i][1] is not None]
        if len(vals) == 3:
            sds.append(statistics.stdev(vals))
    return statistics.median(sds) / mc_truth(repo)


def mc_spread_default(repo):
    """The slider's default: the estimate rounded to the slider's 0.1 point step."""
    return round(mc_spread(repo) * 100, 1)


def mc_perfect_miss(repo):
    """Expected miss share of a perfect model at the default spread."""
    import math

    truth, spread = mc_truth(repo), round(mc_spread(repo), 3)
    tol = 0.001
    q = 0.5 * math.erfc(tol / (spread * truth) / math.sqrt(2))
    return 2 * q**3 * 100


def mc_tol_ms(repo):
    return BAND_EDGE_TOLERANCE_SECONDS * 1000


def host_bins_judged(repo):
    return analysis(repo)["validation"]["engine"]["compared"]


def host_bins_total(repo):
    return len(analysis(repo)["validation"]["engine"]["residuals"][0])


def host_count(repo):
    return analysis(repo)["host_speed"]["hosts_in_records"]["count"]


def host_measured(repo):
    return analysis(repo)["host_speed"]["hosts_in_records"]["measured_for_speed"]


def lb_scaler_ratio(repo):
    return analysis(repo)["money"]["load_balancer_cap"]["ratio"]


def p1_server50(repo):
    return p1_step(repo, "50")["server_p50_s"]


def p1_client50(repo):
    return p1_step(repo, "50")["client_p50_s"]


def return_leg(repo):
    return analysis(repo)["load_balancer"]["per_worker_concurrency_return_leg_s"]


def c_levels_list(repo):
    cs = [str(lv["concurrency"]) for lv in curve_levels(repo)]
    return ", ".join(cs[:-1]) + " and " + cs[-1]


def curve_latency_at(repo, c: float):
    """Linear interpolation of the curve's latency, the same rule lib.js uses.
    None beyond the measured range: the page does not extrapolate."""
    lv = curve_levels(repo)
    if c < lv[0]["concurrency"] or c > lv[-1]["concurrency"]:
        return None
    for a, b in pairwise(lv):
        if a["concurrency"] <= c <= b["concurrency"]:
            f = (c - a["concurrency"]) / (b["concurrency"] - a["concurrency"])
            return a["latency_s"] + f * (b["latency_s"] - a["latency_s"])
    return lv[-1]["latency_s"]


def one_worker_rows(repo):
    """Python reference for lib.js oneWorkerRows: one row per step that one worker
    carried, in probes 2 and 3. W = mean in flight / delivered rate."""
    out = []
    probes = analysis(repo)["load_balancer"]["probes"]
    for pid in UNCAPPED_PROBES:
        for step in sorted(probes[pid]["steps"], key=int):
            st = probes[pid]["steps"][step]
            conc = st["per_worker_concurrency"]
            if len(conc) != 1:
                continue
            (only,) = conc.values()
            w = only["mean"] / st["delivered_rate_rps"]
            curve = curve_latency_at(repo, only["mean"])
            out.append({"probe": pid, "step": int(step), "L": only["mean"], "W": w,
                        "curve": curve, "diff": (w - curve) / curve})
    return out


def ow_below_min(repo):
    return min(-r["diff"] for r in one_worker_rows(repo)) * 100


def ow_below_max(repo):
    return max(-r["diff"] for r in one_worker_rows(repo)) * 100


def _exploratory_ratios(repo):
    ex = analysis(repo)["host_speed"]["exploratory"]
    return [lv["ratio"] for setting in ex.values() for host in setting.values()
            for lv in host.values()]


def hs_lo_pct(repo):
    """The smallest shortfall of the re-measured host against the curve's, percent."""
    return (1 - max(_exploratory_ratios(repo))) * 100


def hs_hi_pct(repo):
    return (1 - min(_exploratory_ratios(repo))) * 100


def grid_util(repo):
    g = sweep_file(repo)["identity"]["thresholds"]["utilization"][0]
    return ", ".join(f"{x:g}" for x in g)


def grid_flight(repo):
    g = sweep_file(repo)["identity"]["thresholds"]["in_flight_concurrency"][0]
    return ", ".join(f"{x:g}" for x in g)


def ex_a_cost(repo):
    return EXERCISE[0][0]


def ex_a_dmg(repo):
    return EXERCISE[0][1]


def ex_b_cost(repo):
    return EXERCISE[1][0]


def ex_b_dmg(repo):
    return EXERCISE[1][1]


def ramp(repo):
    return sweep_sustain(repo) / 2


def p1_w_round(repo):
    """The engine's p50 to two places, the 0.31 s the post and the plan divide by."""
    return round(p1_server50(repo), 2)


def p1_step_mid(repo):
    return 50


def hs_lvl_lo(repo):
    return min(int(k) for k in analysis(repo)["host_speed"]["curve_latency_s"])


def hs_lvl_hi(repo):
    return max(int(k) for k in analysis(repo)["host_speed"]["curve_latency_s"])


def mc_runs(repo):
    return MC_RUNS


def symlog_lin(repo):
    return SYMLOG_LINTHRESH_S


def cal_lo(repo):
    return CALIBRATION_LEVELS[0]


def cal_hi(repo):
    return CALIBRATION_LEVELS[1]


def min_bins(repo):
    return MIN_COMPARED_BINS


def toy_up_at(repo):
    return TOY_UP_AT


def fmt_value(value, spec: str) -> str:
    """Format one resolved number. The spec is a short code: d (integer, commas),
    f<n> (n decimals, commas), pct<n> (a 0-1 fraction as a percent) and ms<n>."""
    if spec == "s":
        return str(value)
    if spec == "d":
        return f"{round(value):,}"
    if spec.startswith("f"):
        return f"{value:,.{int(spec[1:])}f}"
    if spec.startswith("pct"):
        return f"{value * 100:.{int(spec[3:] or 0)}f}%"
    if spec.startswith("ms"):
        return f"{value * 1000:,.{int(spec[2:] or 0)}f} ms"
    raise ValueError(f"unknown format {spec!r}")


def resolve_raw(key: str, repo: Path = REPO):
    if key not in KEYS:
        raise KeyError(f"{key!r} is not on the key list; add it to explainer_a2/numbers.json")
    spec = KEYS[key]
    src = spec["src"]
    if src == "analysis":
        return _dig(analysis(repo), spec["path"])
    if src == "curve":
        return _dig(curve_file(repo), spec["path"])
    if src == "sweep":
        return _dig(sweep_file(repo), spec["path"])
    if src in ("computed", "const"):
        return globals()[spec["fn"]](repo)
    raise ValueError(f"{key}: unknown source {src!r}")


def resolve(key: str, repo: Path = REPO) -> str:
    return fmt_value(resolve_raw(key, repo), KEYS[key]["fmt"])


# --- the page's data blob ----------------------------------------------------


def _worker_means(step: dict) -> dict:
    return {w: c["mean"] for w, c in step["per_worker_concurrency"].items()}


def build_blob(repo: Path = REPO) -> dict:
    """Everything the widgets run on, from the committed files. Floats keep their
    full repr, so the page's frontier arithmetic sees the same numbers Python's does."""
    a = analysis(repo)
    curve = curve_file(repo)
    sweeps = sweep_file(repo)
    ident = sweeps["identity"]
    lb = a["load_balancer"]["probes"]

    levels = []
    for lv in curve["levels"]:
        levels.append({
            "c": lv["concurrency"], "lat": lv["latency_s"],
            "lat_lo": lv["latency_s_range"][0], "lat_hi": lv["latency_s_range"][1],
            "tps": lv["throughput_tps"], "tps_lo": lv["throughput_tps_range"][0],
            "tps_hi": lv["throughput_tps_range"][1], "util": lv["gpu_util"],
            "rps": lv["request_throughput"],
        })
    excl = curve["excluded_levels"][0]

    probes = {}
    for pid in (CAPPED_PROBE, *UNCAPPED_PROBES):
        probes[pid] = {}
        for step, s in lb[pid]["steps"].items():
            probes[pid][step] = {
                "offered": int(step), "lambda": s["delivered_rate_rps"],
                "server_p50": s["server_p50_s"], "client_p50": s["client_p50_s"],
                "workers": _worker_means(s),
            }

    sweep_blobs = []
    iso = a["simulator"]["h2_censoring"]["cap_cost_replica_s"]
    for key, label in SWEEPS:
        pts = _points(sweeps["sources"][key])
        policies = {s: [[p.cost, p.p99, p.scale_up_at, p.scale_down_at]
                        for p in pts if p.signal == s] for s in SIGNAL_ORDER}
        fronts = {s: pareto_frontier([p for p in pts if p.signal == s]) for s in SIGNAL_ORDER}
        sweep_blobs.append({
            "key": key, "label": label, "policies": policies,
            "budget_rule": iso_cost_budget(fronts),
            "reached_post": {s: v["p99_s"] for s, v in a["simulator"]["sweeps"][key][
                "reached"].items()},
            "margin_vs_better_s": a["simulator"]["h2_noise"]["per_sweep"][key][
                "margin_vs_best_other_s"],
            "margin_vs_worse_s": a["simulator"]["h2_noise"]["per_sweep"][key]["h2_margin_s"],
        })

    mc_bins = a["validation"]["engine"]["compared"]
    blob = {
        "curve": {"levels": levels, "max_num_seqs": curve["max_num_seqs"],
                  "excluded": {"c": excl["concurrency"], "runs": excl["n_runs"],
                               "requests": c_excluded_requests(repo), "reason": excl["reason"]}},
        "cap_example": {"in_flight": p1_ceiling_in_flight(repo), "w": round(p1_server50(repo), 2)},
        "exercise": {"a": list(EXERCISE[0]), "b": list(EXERCISE[1])},
        "probes": probes,
        "return_leg_s": a["load_balancer"]["per_worker_concurrency_return_leg_s"],
        "toy": {
            "sat": saturation(repo), "base": toy_baseline(repo), "peak_x": toy_peak_x(repo),
            "sustain": ident["sustain"], "until": ident["until"],
            "eval_every": ident["evaluate_every"], "cooldown": ident["cooldown"],
            "max_replicas": ident["max_replicas"], "spike_start": TOY_SPIKE_START_S,
            "up_at": TOY_UP_AT,
            "lag_A": a["simulator"]["cold_start"]["A"]["median"],
            "lag_C": a["simulator"]["cold_start"]["C"]["median"],
        },
        "grids": {"util": ident["thresholds"]["utilization"][0],
                  "flight": ident["thresholds"]["in_flight_concurrency"][0]},
        "budget": iso,
        "sweeps": sweep_blobs,
        "mc": {
            "bins": mc_bins, "truth": mc_truth(repo), "spread_default": mc_spread_default(repo),
            "tol": mc_tol_ms(repo) / 1000,
            "min_bins": MIN_COMPARED_BINS, "runs": MC_RUNS, "max_miss_fraction": MAX_MISS_FRACTION,
            "factor_engine": factor_engine(repo), "factor_calibrated": factor_calibrated(repo),
        },
        "validation": {
            name: {
                "residuals": a["validation"][name]["residuals"],
                "misses": a["validation"][name]["misses"],
                "compared": a["validation"][name]["compared"],
                "max_miss_s": a["validation"][name]["max_miss_seconds"],
                "median_ratio": a["validation"][name]["typical_residual"][
                    "median_ratio_real_over_predicted"],
            } for name in ("engine", "calibrated")
        },
        "host_speed": a["host_speed"],
    }
    return blob


def blob_json(blob: dict) -> str:
    # `</` would end the script element early; `\/` is the same string to JSON.
    return json.dumps(blob, separators=(",", ":")).replace("</", "<\\/")


# --- plan and spec text ------------------------------------------------------

_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d+\+?)\s*\|\s*(.+?)\s*\|\s*$")


def plan_section(repo: Path = REPO) -> str:
    text = (Path(repo) / "docs/learning/plan.md").read_text()
    start = text.index("# Learning plan — artifact 2")
    rest = text[start + 1:]
    nxt = re.search(r"\n# Learning plan —", rest)
    return text[start: start + 1 + (nxt.start() if nxt else len(rest))]


def plan_checkpoints(repo: Path = REPO) -> dict[int, str]:
    """Module number to the checkpoint cell's raw markdown, from the plan's table."""
    out = {}
    for line in plan_section(repo).splitlines():
        m = _ROW.match(line)
        if m:
            out[int(m.group(1))] = m.group(5)
    return out


def md_inline(text: str) -> str:
    """Escape, then turn `code` into <code>. The plan's checkpoint cells use only
    that and **bold**, which is dropped: bold in a table cell marks the row, and
    the page's checkpoint box has its own emphasis."""
    esc = html_mod.escape(text.replace("**", ""), quote=False)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)


def spec_selfchecks(repo: Path = REPO) -> dict[int, str]:
    text = (Path(repo) / SPEC).read_text()
    block = text[text.index("### Self-check questions"):]
    block = block[: block.index("\n---")]
    return {int(m.group(1)): m.group(2).strip()
            for m in re.finditer(r"^(\d+)\.\s+(.+)$", block, re.MULTILINE)}


# --- jargon gate and glossary ------------------------------------------------

_TYPOGRAPHIC = {"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-",
                "–": "-", " ": " "}


def _normalize(text: str) -> str:
    for fancy, plain in _TYPOGRAPHIC.items():
        text = text.replace(fancy, plain)
    return " ".join(text.lower().split())


def undefined_terms(html: str, terms: dict[str, str] | None = None) -> list[str]:
    """Listed terms that appear in `html` without their full definition present.

    The whole definition, not a prefix: a prefix check would pass a definition
    that opens right and ends wrong.
    """
    terms = TERMS if terms is None else terms
    hay = _normalize(html)
    return [t for t, d in terms.items() if _normalize(t) in hay and _normalize(d) not in hay]


# Regions whose text is not prose a term should be wrapped in. Beyond artifact 1's
# list: controls (a button cannot sit inside a button, and a label's text is the
# control's name), tables (they scroll in a box that would clip the floating
# definition) and links.
_PROTECTED = re.compile(
    r"<(pre|code|script|style|svg|h1|h2|h3|h4|title|summary|label|button|output|legend|option"
    r"|select|textarea|table|a|figcaption|x-plain)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>|<!--.*?-->", re.DOTALL)
# A plural is the same term, so "policies" and "replicas" open the definition too.
_ALIASES = {"policies": "policy"}


def _prose_spans(html: str):
    blocked = [m.span() for m in _PROTECTED.finditer(html)]
    for m in _TAG.finditer(html):
        if not any(s <= m.start() < e for s, e in blocked):
            blocked.append(m.span())
    blocked.sort()
    cursor = 0
    for start, end in blocked:
        if start > cursor:
            yield cursor, start
        cursor = max(cursor, end)
    if cursor < len(html):
        yield cursor, len(html)


def _term_pattern(terms: dict[str, str]) -> re.Pattern:
    alts = []
    for t in sorted([*terms, *_ALIASES], key=len, reverse=True):
        alts.append(re.escape(t).replace("'", "['’]").replace(r"\ ", r"\s+"))
    # Boundaries on both sides, so "bin" does not open inside "combine" and
    # "in flight" does not open inside "in flights". The optional s is a plural.
    return re.compile(r"(?<![\w-])(" + "|".join(alts) + r")(s|es)?(?![\w-])", re.IGNORECASE)


def glossary(html: str, terms: dict[str, str] | None = None) -> str:
    """Make every defined term in prose a button that reveals the page's own
    definition. Same mechanism as artifact 1's, with case-insensitive matching and
    plurals, because this page starts sentences with its terms."""
    terms = TERMS if terms is None else terms
    lower = {_normalize(k): v for k, v in terms.items()}
    pattern = _term_pattern(terms)

    def wrap(m: re.Match) -> str:
        shown = m.group(0)
        base = _normalize(m.group(1))
        base = _ALIASES.get(base, base)
        definition = lower.get(base)
        if definition is None:
            return shown
        return (f'<span class="gloss"><button type="button" class="term" '
                f'aria-expanded="false">{html_mod.escape(shown)}</button>'
                f'<span class="def" hidden>{html_mod.escape(definition)}</span></span>')

    out, cursor = [], 0
    for start, end in _prose_spans(html):
        out.append(html[cursor:start])
        out.append(pattern.sub(wrap, html[start:end]))
        cursor = end
    out.append(html[cursor:])
    return "".join(out)


# --- the build ---------------------------------------------------------------


def substitute(page: str, repo: Path = REPO) -> str:
    checkpoints = plan_checkpoints(repo)
    selfchecks = spec_selfchecks(repo)
    blob = None

    def sub(m: re.Match) -> str:
        nonlocal blob
        token = m.group(1).strip()
        try:
            if token == "data":
                blob = blob or build_blob(repo)
                return blob_json(blob)
            if token.startswith("inline:"):
                return (A2 / token.split(":", 1)[1]).read_text()
            if token.startswith("def:"):
                return html_mod.escape(TERMS[token.split(":", 1)[1]], quote=False)
            if token.startswith("checkpoint:"):
                return md_inline(checkpoints[int(token.split(":", 1)[1])])
            if token.startswith("selfcheck:"):
                return html_mod.escape(selfchecks[int(token.split(":", 1)[1])], quote=False)
            return resolve(token, repo)
        except (KeyError, LookupError, ValueError) as exc:
            print(f"build_explainer_a2: {token}: {exc!r}", file=sys.stderr)
            raise SystemExit(1) from exc

    return PLACEHOLDER.sub(sub, page)


def render(page: str, repo: Path = REPO) -> str:
    html = substitute(page, repo)
    # Gate first, glossary second: the gate needs each definition as contiguous
    # text, and wrapping puts markup inside it.
    missing = undefined_terms(html)
    if missing:
        print(f"build_explainer_a2: terms used without a definition: {missing}", file=sys.stderr)
        raise SystemExit(1)
    return glossary(html)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=str(A2 / "page.html"))
    ap.add_argument("--out", default=str(REPO / "build" / "explainer_a2" / "index.html"))
    args = ap.parse_args()
    html = render(Path(args.page).read_text())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"built {out} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
