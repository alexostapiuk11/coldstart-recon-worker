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

from statistics import median, multimode

__all__ = ["numbers"]

# The analysis names a sweep "arm A" (step shape) or "ramp arm A" (ramp shape);
# the post's keys read step_a / ramp_c. The mapping lives here so a renamed
# sweep in the analysis fails loudly (`_sweep_key`) rather than silently dropping
# its numbers.
_SWEEP_KEY = {"arm A": "step_a", "arm C": "step_c", "ramp arm A": "ramp_a", "ramp arm C": "ramp_c"}
_SIGNALS = ("queue_depth", "in_flight_concurrency", "utilization")


def _secs(x: float) -> str:
    """Three decimals below one second, two from there up, chosen AFTER rounding.

    0.9996 rounds to 1.000 at three decimals, which would print as "1.000" and
    break the one-format-per-magnitude rule. Rejected: choosing the decimals
    from the unrounded value.
    """
    return f"{x:.3f}" if round(x, 3) < 1 else f"{x:.2f}"


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


def _ms_signed(x: float) -> str:
    """Seconds as signed whole milliseconds: '+43 ms', '-3,955 ms'."""
    return f"{x * 1000:+,.0f} ms"


def _only(items, what: str, consequence: str):
    """The one element of `items`, or a ValueError naming what was found and what breaks.

    Rejected: `(x,) = items`, whose "too many values to unpack" names neither the
    analysis' content nor the number that would have been mislabelled.
    """
    items = list(items)
    if len(items) != 1:
        raise ValueError(f"expected exactly one of {what}, found {len(items)} ({items!r}); "
                         f"{consequence}")
    return items[0]


def _sweep_key(sweep: str) -> str:
    if sweep not in _SWEEP_KEY:
        raise ValueError(
            f"the analysis names a sweep {sweep!r} that has no post key (known: "
            f"{sorted(_SWEEP_KEY)}); its numbers would be dropped from the post without "
            "notice, so the mapping must be extended first")
    return _SWEEP_KEY[sweep]


def _below_pct(ratio: float, what: str) -> str:
    """How much LOWER a latency was than its reference: 1 - ratio, ratio < 1 only.

    A latency ratio is not a speed: 0.86 of the latency is 14% lower latency, not
    "14% faster" (which would be 1/0.86 - 1 = 16%). The key says "below" so the
    number states what it is. A ratio at or above 1 would print a zero or negative
    percentage under a "below" label, so it is refused.
    """
    if not ratio < 1:
        raise ValueError(
            f"{what}: latency ratio {ratio:.4f} is not below 1, so 1 - ratio is not "
            "'percent below' and would print a zero or negative percentage under a "
            "'below' label; the key for the other direction is the one to use")
    return _pct(1 - ratio)


def _above_pct(ratio: float, what: str) -> str:
    """How much HIGHER a latency was than its reference: ratio - 1, ratio > 1 only."""
    if not ratio > 1:
        raise ValueError(
            f"{what}: latency ratio {ratio:.4f} is not above 1, so ratio - 1 is not "
            "'percent above' and would print a zero or negative percentage under an "
            "'above' label; the key for the other direction is the one to use")
    return _pct(ratio - 1)


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
    # The ratio is real / predicted latency: the first attempt's real latency was
    # BELOW the prediction (ratio < 1), the calibrated attempt's ABOVE it (ratio > 1).
    # One "percent off" key would hide that the two misses point opposite ways, and
    # "faster"/"slower" would call a latency ratio a speed (see `_below_pct`).
    out["attempt1_latency_below_prediction_pct"] = _below_pct(
        v["engine"]["typical_residual"]["median_ratio_real_over_predicted"], "attempt 1")
    out["attempt2_latency_above_prediction_pct"] = _above_pct(
        v["calibrated"]["typical_residual"]["median_ratio_real_over_predicted"], "attempt 2")
    return out


def _calibrated_host(host_speed: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    host, by_level = _only(host_speed["calibrated_ratios_by_host"].items(),
                           "hosts with calibrated ratios",
                           "attempt 2's per-host ratio would describe a mix of machines "
                           "under one host id")
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
        host, by_level = _only(by_host.items(), f"hosts in the {store} store",
                               f"the {store} ratios would describe a mix of machines under "
                               "one host id")
        out[f"{store}_host_id"] = host
        for level, r in by_level.items():
            out[f"{store}_ratio_{level}"] = f"{r['ratio']:.2f}"
            out[f"{store}_latency_below_curve_pct_{level}"] = _below_pct(
                r["ratio"], f"{store} at concurrency {level}")
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
    modes = multimode(peaks)
    if len(modes) != 1:
        raise ValueError(
            f"probe 1's per-worker peaks have a tie for the most common value ({sorted(modes)}); "
            "picking one would present an arbitrary reading as the typical peak, so the key is "
            "refused until the analysis settles which is typical")
    out["probe1_peak_per_worker"] = str(modes[0])
    out["probe1_peak_per_worker_max"] = str(max(peaks))
    # The 100 req/s step ended on client-side errors (the driver could not start a new
    # thread); the post has to say the step is incomplete.
    out["probe1_errors_100"] = _count(steps["100"]["errors"])
    return out


def _probes_2_to_5(probes: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    absent = [k for k in ("2", "3", "4", "5") if k not in probes]
    if absent:
        raise ValueError(f"the analysis has no probe(s) {absent}; the deliveries and routing "
                         "the post quotes from them would be missing, not zero")
    p2, p3, p4, p5 = (probes[k]["steps"] for k in ("2", "3", "4", "5"))
    out["probe2_non_200_total"] = str(sum(s["non_200"] for s in p2.values()))
    for step in ("300", "450"):
        out[f"offered_{step}"] = f"{step} req/s"
        out[f"probe2_delivered_{step}"] = _rate(p2[step]["delivered_rate_rps"])
        out[f"probe3_delivered_{step}"] = _rate(p3[step]["delivered_rate_rps"])
    for step in sorted(p3, key=int):
        out[f"probe3_worker1_share_{step}"] = _pct(p3[step]["worker_share"]["worker 1"])
    conc = p3["450"]["per_worker_concurrency"]
    if not {"worker 1", "worker 2"} <= set(conc):
        raise ValueError(f"probe 3 step 450 names workers {sorted(conc)}, not 'worker 1' and "
                         "'worker 2'; the two peaks the post compares would be the wrong pair")
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
    # The range deliberately includes the void repeat (2 requests without a 200): dropping
    # it would narrow 26%-35%-21% to two repeats and hide that one was void; the post says
    # which it did.
    voids = [f"repeat {r['repeat']} (void: {'; '.join(r['void'])})"
             for r in lb["stall_share"]["repeats"] if r["void"]]
    out["stall_share_includes_void_repeat"] = (
        "yes, " + ", ".join(voids) if voids else "no, every repeat is complete")
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


def _h2_noise(noise: dict) -> dict[str, str]:
    """The margins H2 rests on, beside the spread of utilisation's own identical-fleet runs."""
    out: dict[str, str] = {}
    constrained = []
    for sweep, n in noise["per_sweep"].items():
        k = _sweep_key(sweep)
        spread = n["at_cap_policy_p99_s"]
        out[f"h2_margin_{k}"] = _ms_signed(n["h2_margin_s"])
        out[f"h2_margin_vs_best_other_{k}"] = _ms_signed(n["margin_vs_best_other_s"])
        out[f"utilization_at_cap_policies_{k}"] = _count(spread["count"])
        out[f"utilization_at_cap_p99_spread_{k}"] = _s_span(spread["min"], spread["max"])
        out[f"utilization_at_cap_p99_median_{k}"] = _s(spread["median"])
        out[f"others_highest_frontier_cost_{k}"] = _replica_s(
            n["others_highest_frontier_cost_replica_s"])
        out[f"iso_cost_slice_constrains_others_{k}"] = (
            "yes" if n["iso_cost_slice_constrains_others"] else "no")
        if n["iso_cost_slice_constrains_others"]:
            constrained.append(k)
    out["iso_cost_slice_constrains_others"] = (
        "yes, in " + ", ".join(constrained) if constrained else "no")
    return out


def _simulator(sim: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for factor, by_sweep in sim["gaps"].items():
        fk = f"x{factor.replace('.', '')}"
        for sweep, g in by_sweep.items():
            out[f"gap_{fk}_{_sweep_key(sweep)}"] = _s(g["point"])
            if factor == "1":
                out[f"gap_{fk}_{_sweep_key(sweep)}_interval"] = _s_span(g["lo"], g["hi"])
    for arm in ("A", "C"):
        out[f"cold_start_median_{arm.lower()}"] = _s(sim["cold_start"][arm]["median"])
    out["h1"] = _verdict(sim["h1"]["overall"])
    out["h2"] = _verdict(sim["h2"]["overall"])
    out.update(_h3(sim["h3"]))
    out["h4"] = _verdict(sim["h4"]["overall"])
    out["h2_sensitivity"] = _verdict(sim["h2_sensitivity"]["overall"])
    for sweep, held in sim["h2"]["per_sweep"].items():
        out[f"h2_{_sweep_key(sweep)}"] = _verdict(held)
    budgets = {_count(s["budget_replica_s"]) for s in sim["sweeps"].values()}
    if len(budgets) != 1:
        raise ValueError(
            f"the four sweeps' iso-cost budgets differ ({sorted(budgets)}), so one 'budget' "
            "sentence in the post would be wrong for some sweep; quote them per sweep instead")
    out["budget"] = f"{budgets.pop()} replica-seconds"
    for sweep, s in sim["sweeps"].items():
        for signal in _SIGNALS:
            r = s["reached"][signal]
            out[f"reached_{_sweep_key(sweep)}_{signal}_p99"] = _s(r["p99_s"])
            out[f"reached_{_sweep_key(sweep)}_{signal}_cost"] = _replica_s(r["cost_replica_s"])
    out.update(_censoring(sim["h2_censoring"]))
    out.update(_h2_noise(sim["h2_noise"]))
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
