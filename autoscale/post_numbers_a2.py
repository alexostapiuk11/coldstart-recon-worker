"""Every number artifact 2's post quotes, formatted once from `data/a2/post-analysis.json`.

The post quotes each of these strings verbatim, and a test written with the
post fails if any is missing from it. A number typed into prose by hand drifts
from the data the first time the analysis is re-run; a number rendered here
cannot. `placement/post_numbers.py` does the same for artifact 4.

Formats are fixed here, not at the call site, so one quantity is never written
two ways in one post: seconds take three decimals below 1 s and two from there
up, percentages are whole numbers, rates take one decimal, counts are integers
with a thousands comma, dollars (once `spend` exists) take cents.

`numbers` is pure. It takes the loaded analysis rather than a path because the
alternative, reading the file here, would make the formatting untestable
against a doctored analysis (a partial H3, a utilisation run below the cap).

Every simulator number below belongs to a section the analysis labels
UNVALIDATED, because the simulator failed validation twice. The key names carry
no such flag; the post's prose does.
"""

from statistics import median, mode

__all__ = ["numbers"]

# The analysis names a sweep "arm A" (step shape) or "ramp arm A" (ramp shape);
# the post's keys read step_a / ramp_c. The mapping lives here so a renamed
# sweep in the analysis fails loudly (KeyError) rather than silently dropping
# its numbers.
_SWEEP_KEY = {"arm A": "step_a", "arm C": "step_c", "ramp arm A": "ramp_a", "ramp arm C": "ramp_c"}
_SIGNALS = ("queue_depth", "in_flight_concurrency", "utilization")


def _secs(x: float) -> str:
    return f"{x:.3f}" if x < 1 else f"{x:.2f}"


def _s(x: float) -> str:
    return f"{_secs(x)} s"


def _s_span(lo: float, hi: float) -> str:
    """'0.050–1.06 s': one unit at the end, not two."""
    return f"{_secs(lo)}–{_secs(hi)} s"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _rate(x: float) -> str:
    return f"{x:.1f} req/s"


def _count(x: float) -> str:
    return f"{round(x):,}"


def _replica_s(x: float) -> str:
    return f"{_count(x)} replica-seconds"


def _span(values: list[float], spec: str) -> str:
    """min–max with en dash; one value when both ends format alike.

    Compared after formatting, not before: 0.8745 and 0.8666 are different
    floats but the same quoted "0.87", and "0.87–0.87" reads as a typo.
    """
    lo, hi = f"{min(values):{spec}}", f"{max(values):{spec}}"
    return lo if lo == hi else f"{lo}–{hi}"


def _verdict(holds: bool) -> str:
    return "holds" if holds else "fails"


def _spend_numbers(spend: dict) -> dict[str, str]:
    """Hook for the measured-spend keys, which Task 13 defines.

    Raising rather than returning {} is deliberate: an empty return would let
    the post be written and pass its number test while quoting no dollar figure
    for money that was actually spent.
    """
    raise NotImplementedError(
        "analysis['spend'] is set but its keys are defined by Task 13 of the publication "
        "plan, which has not landed: post_numbers_a2 would otherwise emit no spend numbers "
        "and the post would omit the cost of the experiment")


def _validation(v: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag, attempt in (("attempt1", v["engine"]), ("attempt2", v["calibrated"])):
        out[f"{tag}_misses"] = f"{attempt['misses']} of {attempt['compared']} judged bins"
        out[f"{tag}_max_miss"] = _s(attempt["max_miss_seconds"])
        out[f"{tag}_void_repeats"] = str(attempt["void_repeats"])
    # The ratio is real / predicted: the engine's first attempt ran FASTER than
    # the prediction (ratio < 1), the calibrated attempt SLOWER (ratio > 1).
    # One "percent off" key would hide that the two misses point opposite ways.
    out["attempt1_engine_faster_pct"] = _pct(
        1 - v["engine"]["typical_residual"]["median_ratio_real_over_predicted"])
    out["attempt2_engine_slower_pct"] = _pct(
        v["calibrated"]["typical_residual"]["median_ratio_real_over_predicted"] - 1)
    return out


def _calibrated_host(host_speed: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    (host, by_level), = host_speed["calibrated_ratios_by_host"].items()
    out["attempt2_host_id"] = host
    for level, ratios in by_level.items():
        out[f"attempt2_host_ratio_{level}"] = _span(ratios, ".2f")
        out[f"host_{host}_ratio_{level}"] = out[f"attempt2_host_ratio_{level}"]
    return out


def _host_speed(h: dict) -> dict[str, str]:
    out = _calibrated_host(h)
    hosts = sorted({x for ids in h["curve_hosts"].values() for x in ids})
    out["curve_host_id"] = ", ".join(hosts)
    for store, by_host in h["exploratory"].items():
        (host, by_level), = by_host.items()
        out[f"{store}_host_id"] = host
        for level, r in by_level.items():
            out[f"{store}_ratio_{level}"] = f"{r['ratio']:.2f}"
            out[f"{store}_faster_pct_{level}"] = _pct(1 - r["ratio"])
    return out


def _probe1(probe: dict) -> dict[str, str]:
    steps = probe["steps"]
    out = {
        "lb_ceiling_rate": _rate(median(s["delivered_rate_rps"] for s in steps.values())),
    }
    offered = [str(k) for k in sorted(steps, key=int)]
    out["lb_ceiling_offered"] = f"{', '.join(offered[:-1])} and {offered[-1]} req/s"
    for step, s in steps.items():
        out[f"probe1_client_p50_{step}"] = _s(s["client_p50_s"])
        out[f"probe1_server_p50_{step}"] = _s(s["server_p50_s"])
    # One reconstructed reading (step 100, worker 2) says 5 while every other
    # reading, across steps and workers, says 4. The in-flight intervals are
    # rebuilt from stamped latencies and an assumed 0.1 s return leg, so a
    # boundary-adjacent pair can overlap by one; the mode is the honest figure
    # and the post should not claim the lone 5 as a property of the worker.
    peaks = [w["max"] for s in steps.values() for w in s["per_worker_concurrency"].values()]
    out["probe1_peak_per_worker"] = str(mode(peaks))
    return out


def _probes_2_to_5(probes: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    p2, p3, p4, p5 = (probes[k]["steps"] for k in ("2", "3", "4", "5"))
    out["probe2_non_200_total"] = str(sum(s["non_200"] for s in p2.values()))
    for step in ("300", "450"):
        out[f"offered_{step}"] = f"{step} req/s"
        out[f"probe2_delivered_{step}"] = _rate(p2[step]["delivered_rate_rps"])
        out[f"probe3_delivered_{step}"] = _rate(p3[step]["delivered_rate_rps"])
    for step in sorted(p3, key=int):
        out[f"probe3_worker1_share_{step}"] = _pct(p3[step]["worker_share"]["worker 1"])
    conc = p3["450"]["per_worker_concurrency"]
    out["probe3_peak_worker1_450"] = str(conc["worker 1"]["max"])
    out["probe3_peak_worker2_450"] = str(conc["worker 2"]["max"])
    for step in ("150", "180"):
        out[f"probe4_delivered_{step}"] = _rate(p4[step]["delivered_rate_rps"])
    for step in ("180", "210"):
        out[f"probe5_delivered_{step}"] = _rate(p5[step]["delivered_rate_rps"])
    return out


def _load_balancer(lb: dict) -> dict[str, str]:
    out = _probe1(lb["probes"]["1"])
    out.update(_probes_2_to_5(lb["probes"]))
    shares = [r["share_over_threshold"] for r in lb["stall_share"]["repeats"]]
    out["stall_share_range"] = f"{_pct(min(shares))}–{_pct(max(shares))}"
    for r in lb["stall_share"]["repeats"]:
        out[f"stall_share_repeat_{r['repeat']}"] = _pct(r["share_over_threshold"])
    f = lb["lb_502_first_attempt_s"]
    out["lb_502_first_attempt_count"] = _count(f["count"])
    out["lb_502_first_attempt_median"] = _s(f["median"])
    out["lb_502_first_attempt_max"] = _s(f["max"])
    return out


def _h3(h3: dict) -> dict[str, str]:
    out = {}
    for factor, h in h3.items():
        key = f"h3_x{factor.replace('.', '')}"
        if not h["evaluable"]:
            out[key] = "not evaluable"
        elif h["partial"]:
            out[key] = "partial"
        else:
            out[key] = _verdict(h["holds"])
    return out


def _censoring(c: dict) -> dict[str, str]:
    sweeps = c["per_sweep"].values()
    counts = {s["utilization_policies"] for s in sweeps}
    if len(counts) != 1 or not all(s["every_utilization_run_at_cap_cost"] for s in sweeps):
        raise ValueError(
            "utilisation policies are not all at the cap in every sweep, or the sweeps differ "
            "in how many there are: the post's 'N of N at the cap' sentence would overstate the "
            "censoring, so the key is refused until the analysis gives a per-sweep count")
    n = counts.pop()
    return {
        "utilization_policies_at_cap": f"{n} of {n}",
        "utilization_scale_up_max_threshold": f"{c['highest_utilization_scale_up_threshold']:g}",
        "curve_gpu_util": f"{c['curve_gpu_util_min_over_measured_levels']:.1f}",
    }


def _simulator(sim: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for factor, by_sweep in sim["gaps"].items():
        fk = f"x{factor.replace('.', '')}"
        for sweep, g in by_sweep.items():
            out[f"gap_{fk}_{_SWEEP_KEY[sweep]}"] = _s(g["point"])
            if factor == "1":
                out[f"gap_{fk}_{_SWEEP_KEY[sweep]}_interval"] = _s_span(g["lo"], g["hi"])
    out["h1"] = _verdict(sim["h1"]["overall"])
    out["h2"] = _verdict(sim["h2"]["overall"])
    out.update(_h3(sim["h3"]))
    out["h4"] = _verdict(sim["h4"]["overall"])
    out["h2_sensitivity"] = _verdict(sim["h2_sensitivity"]["overall"])
    for sweep, held in sim["h2"]["per_sweep"].items():
        out[f"h2_{_SWEEP_KEY[sweep]}"] = _verdict(held)
    budgets = {_count(s["budget_replica_s"]) for s in sim["sweeps"].values()}
    if len(budgets) != 1:
        raise ValueError(
            f"the four sweeps' iso-cost budgets differ ({sorted(budgets)}), so one 'budget' "
            "sentence in the post would be wrong for some sweep; quote them per sweep instead")
    out["budget"] = f"{budgets.pop()} replica-seconds"
    for sweep, s in sim["sweeps"].items():
        for signal in _SIGNALS:
            r = s["reached"][signal]
            out[f"reached_{_SWEEP_KEY[sweep]}_{signal}_p99"] = _s(r["p99_s"])
            out[f"reached_{_SWEEP_KEY[sweep]}_{signal}_cost"] = _replica_s(r["cost_replica_s"])
    out.update(_censoring(sim["h2_censoring"]))
    out["repetitions"] = str(sim["identity"]["repetitions"])
    out["max_replicas"] = str(sim["identity"]["max_replicas"])
    return out


def numbers(analysis: dict) -> dict[str, str]:
    out = _validation(analysis["validation"])
    out.update(_load_balancer(analysis["load_balancer"]))
    out.update(_host_speed(analysis["host_speed"]))
    out.update(_simulator(analysis["simulator"]))
    if analysis["spend"] is not None:
        out.update(_spend_numbers(analysis["spend"]))
    return out
