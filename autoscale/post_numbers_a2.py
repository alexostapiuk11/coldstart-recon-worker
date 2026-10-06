"""Every number artifact 2's post quotes, formatted once from `data/a2/post-analysis.json`.

The post quotes each of these strings verbatim, and a test written with the
post fails if any is missing from it. A number typed into prose by hand drifts
from the data the first time the analysis is re-run; a number rendered here
cannot. `placement/post_numbers.py` does the same for artifact 4.

A value short enough to occur anywhere ("0", "128", "fails") is formatted as the
phrase that quotes it ("no repeat was void", "H3 fails"), or as its table row, so it
occurs once in the post and the verbatim check can fail for it; a test of the
post refuses a value under six characters that does not occur exactly once.

Formats are fixed here, not at the call site, so one quantity is never written
two ways in one post: seconds take three decimals below 1 s and two from there
up, percentages are whole numbers, rates take one decimal, counts are integers
with a thousands comma, dollars take cents (four decimals below a cent, so a real
cost never prints as "$0.00").

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
# The money keys name the signals the way the post's prose does.
_MONEY_SIGNAL_KEY = {"queue_depth": "queue_depth", "in_flight_concurrency": "in_flight",
                     "utilization": "utilization"}
# How the post's tables label each sweep in their first column.
_SWEEP_LABEL = {"arm A": "step, arm A", "arm C": "step, arm C", "ramp arm A": "ramp, arm A",
                "ramp arm C": "ramp, arm C"}
_ATTEMPT_WORD = {"attempt1": "one", "attempt2": "two"}
_SMALL_WORD = {1: "one", 2: "two", 3: "three"}


def _secs(x: float) -> str:
    """Three decimals below one second, two from there up, chosen AFTER rounding.

    0.9996 rounds to 1.000 at three decimals, which would print as "1.000" and
    break the one-format-per-magnitude rule. Rejected: choosing the decimals
    from the unrounded value. The magnitude decides, so -6.198 prints like 6.198.
    """
    return f"{x:.3f}" if abs(round(x, 3)) < 1 else f"{x:.2f}"


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


def _dollars(x: float) -> str:
    """Cents, or four decimals below a cent; positive amounts only.

    Chosen after rounding, as `_secs` does: 0.00996 rounds to 0.01 and prints "$0.01".
    A zero or negative amount is refused: a free price is a broken reading, and "$0.00"
    would state it as a fact.
    """
    if not x > 0:
        raise ValueError(f"a dollar amount must be positive to be quoted, got {x!r}; "
                         "printing it would state a free or negative price")
    return f"${x:,.2f}" if round(x, 2) >= 0.01 else f"${x:.4f}"


def _span(values: list[float], spec: str) -> str:
    """min–max with en dash; one value when both ends format alike.

    Compared after formatting, not before: 0.8745 and 0.8666 are different
    floats but the same quoted "0.87", and "0.87–0.87" reads as a typo.
    """
    lo, hi = f"{min(values):{spec}}", f"{max(values):{spec}}"
    return lo if lo == hi else f"{lo}–{hi}"


def _count_span(values, unit: str = "") -> str:
    """Counts as min–max, one value when both ends format alike, then the unit once."""
    lo, hi = _count(min(values)), _count(max(values))
    return (lo if lo == hi else f"{lo}–{hi}") + (f" {unit}" if unit else "")


def _pct_span(values) -> str:
    """Whole percentages as min–max, the stall-share range's format ('21%–35%')."""
    lo, hi = _pct(min(values)), _pct(max(values))
    return lo if lo == hi else f"{lo}–{hi}"


def _and(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


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


def _void_phrase(n: int) -> str:
    """'no repeat was void', 'one repeat was void', '3 repeats were void'."""
    if n == 0:
        return "no repeat was void"
    return "one repeat was void" if n == 1 else f"{n} repeats were void"


def _sweep_label(sweep: str) -> str:
    _sweep_key(sweep)  # refuses an unknown sweep with its consequence
    return _SWEEP_LABEL[sweep]


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


def _money(m: dict) -> dict[str, str]:
    """The default cap's cost (measured rate and throughput) and the signal choice's (UNVALIDATED)."""
    cap = m["load_balancer_cap"]
    out = {
        "money_rate": f"{_dollars(m['gpu_hourly_rate'])}/h",
        "spikes_per_day": f"{_count(m['spikes_per_day'])} per day",
        "money_per_million_scaler4": _dollars(cap["scaler_4"]["dollars_per_million"]),
        "money_per_million_scaler128": _dollars(cap["scaler_128"]["dollars_per_million"]),
        "money_scaler_ratio": f"{round(cap['ratio'])}×",
        "money_list_rate": f"{_dollars(m['list_price_hourly'])}/h",
        "money_list_ratio": f"{m['list_over_reported']:.1f}×",
    }
    sig = m["signal_choice"]
    if "UNVALIDATED" not in sig["label"]:
        raise ValueError(f"the signal-choice dollars carry the label {sig['label']!r}, which "
                         "does not say UNVALIDATED; they come from a simulator that failed "
                         "validation twice and the post must say so beside them")
    out["money_signal_label"] = sig["label"]
    out["money_p99_spread_step_a"] = (
        f"reached p99s are within {round(sig['p99_spread_s'] * 1000)} ms of each other")
    for signal, row in sig["per_signal"].items():
        if signal not in _MONEY_SIGNAL_KEY:
            raise ValueError(f"the money section prices a signal {signal!r} that has no post key "
                             f"(known: {sorted(_MONEY_SIGNAL_KEY)}); its dollars would be "
                             "dropped from the post without notice")
        k = _MONEY_SIGNAL_KEY[signal]
        out[f"money_spike_{k}_step_a"] = _dollars(row["dollars_per_spike"])
        out[f"money_day_{k}_step_a"] = _dollars(row["dollars_per_day"])
    return out


def _validation(v: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag, attempt in (("attempt1", v["engine"]), ("attempt2", v["calibrated"])):
        out[f"{tag}_misses"] = f"{attempt['misses']} of {attempt['compared']} judged bins"
        out[f"{tag}_max_miss"] = _s(attempt["max_miss_seconds"])
        out[f"{tag}_void_repeats"] = _void_phrase(attempt["void_repeats"])
        occ = attempt["engine_in_flight"]["per_repeat"]
        out[f"{tag}_engine_over_cap_range"] = _pct_span(
            [r["share_of_arrivals_over_cap"] for r in occ])
        out[f"{tag}_engine_max_in_flight"] = (
            f"{_count_span([r['max_in_flight'] for r in occ])} in attempt {_ATTEMPT_WORD[tag]}")
    # The ratio is real / predicted latency: the first attempt's real latency was
    # BELOW the prediction (ratio < 1), the calibrated attempt's ABOVE it (ratio > 1).
    # One "percent off" key would hide that the two misses point opposite ways, and
    # "faster"/"slower" would call a latency ratio a speed (see `_below_pct`).
    out["attempt1_min_residual"] = _s(v["engine"]["residual_min_s"])
    void = _only(v["engine"]["void_repeat_detail"], "void repeats in attempt 1",
                 "the post's count of unstamped responses names one void repeat")
    out["attempt1_void_200_without_stamp"] = _count(void["responses_200_without_engine_arrival"])
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
    # One key per ratio. Rejected: a second, host-named copy of each: the post quotes the
    # ratio once, beside `attempt2_host_id`, and a duplicate key only re-checks one string.
    for level, ratios in by_level.items():
        out[f"attempt2_host_ratio_{level}"] = f"{_span(ratios, '.2f')} at {level}"
    return out


def _host_speed(h: dict) -> dict[str, str]:
    out = _calibrated_host(h)
    out["hosts_in_records"] = (f"{_count(h['hosts_in_records']['count'])} hosts appear in the "
                               "curve, host re-measurement and validation records")
    out["hosts_measured_for_speed"] = (
        f"{_count(h['hosts_in_records']['measured_for_speed'])} of them were measured for speed")
    out["engine_version"] = f"vLLM {h['engine_version']}"
    band = h["attempt1_at_100_in_flight"]
    out["attempt1_in_flight_band"] = f"{band['band'][0]} to {band['band'][1]}"
    out["attempt1_latency_at_100"] = _s(band["median_server_latency_s"])
    out["maxseqs128_latency_at_100"] = _s(band["maxseqs128_interpolated_s"])
    out["curve_latency_at_100"] = _s(band["curve_interpolated_s"])
    hosts = sorted({x for ids in h["curve_hosts"].values() for x in ids})
    out["curve_host_id"] = ", ".join(hosts)
    # One table row per level, `--max-num-seqs` 128's cell then 256's: "0.90 (10% lower)" on
    # its own occurs twice in that table and "10%" many times in the post.
    stores = ("maxseqs128", "maxseqs256")
    if set(h["exploratory"]) != set(stores):
        raise ValueError(f"the host re-measurement has stores {sorted(h['exploratory'])}, not "
                         f"{list(stores)}; the post's two-column table would mislabel a column")
    cells: dict[str, list[str]] = {}
    for store in stores:
        host, by_level = _only(h["exploratory"][store].items(), f"hosts in the {store} store",
                               f"the {store} ratios would describe a mix of machines under "
                               "one host id")
        out[f"{store}_host_id"] = host
        for level, r in by_level.items():
            pct = _below_pct(r["ratio"], f"{store} at concurrency {level}")
            cells.setdefault(level, []).append(f"{r['ratio']:.2f} ({pct} lower)")
    for level, row in cells.items():
        if len(row) != len(stores):
            raise ValueError(f"concurrency {level} was re-measured in {len(row)} of the "
                             f"{len(stores)} settings; its table row would have an empty cell")
        out[f"remeasure_row_{level}"] = f"| {level} | {' | '.join(row)} |"
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
    typical, top = modes[0], max(peaks)
    out["probe1_peak_per_worker"] = f"per-worker peak in flight was {typical}"
    if top > typical:
        c = peaks.count(top)
        out["probe1_peak_per_worker_max"] = (
            f"except {_SMALL_WORD.get(c, str(c))} reading{'s' if c > 1 else ''} of {top}")
    else:
        out["probe1_peak_per_worker_max"] = "with no reading above it"
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
    out["probe2_non_200_total"] = f"{_count(sum(s['non_200'] for s in p2.values()))} such 502s"
    for step in ("300", "450"):
        out[f"offered_{step}"] = f"{step} req/s"
        out[f"probe2_delivered_{step}"] = _rate(p2[step]["delivered_rate_rps"])
        out[f"probe3_delivered_{step}"] = _rate(p3[step]["delivered_rate_rps"])
    # The whole sequence is one key: three "100%"s in a row are indistinguishable apart.
    order = sorted(p3, key=int)
    out["probe3_worker1_share_by_step"] = (
        f"from {order[0]} to {order[-1]} req/s: "
        + ", ".join(_pct(p3[step]["worker_share"]["worker 1"]) for step in order))
    conc = p3["450"]["per_worker_concurrency"]
    if not {"worker 1", "worker 2"} <= set(conc):
        raise ValueError(f"probe 3 step 450 names workers {sorted(conc)}, not 'worker 1' and "
                         "'worker 2'; the two peaks the post compares would be the wrong pair")
    w1, w2 = conc["worker 1"]["max"], conc["worker 2"]["max"]
    out["probe3_peaks_450"] = (f"both workers reach {w1} in flight" if w1 == w2 else
                               f"worker 1 reach {w1} and worker 2 reach {w2} in flight")
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
    # The range deliberately includes the void repeat: dropping it would narrow the range to
    # two repeats and hide that one was void; the post says which, and what voided it.
    stall = lb["stall_share"]
    voids = [f"repeat {r['repeat']} was void: " + _and(
                 [f"{c} requests got {s}s" for s, c in sorted(r["non_200_status"].items())])
             for r in stall["repeats"] if r["void"]]
    out["stall_share_includes_void_repeat"] = "; ".join(voids) if voids else "no repeat was void"
    refused = [r for r in stall["repeats"] if r["refused_for_send_jitter"]]
    if refused:
        out["stall_jitter_refused"] = (
            f"repeat{'s' if len(refused) > 1 else ''} "
            f"{_and([str(r['repeat']) for r in refused])} "
            f"{'were' if len(refused) > 1 else 'was'} refused for send jitter "
            f"({_and([_s(r['max_send_jitter_s']) for r in refused])})")
    out["stall_server_backlog_s"] = _s(stall["server_backlog_s"])
    # One table row per repeat: over 2 s client-side, over 2 s outside the engine, and of
    # those over 2 s the share also backlogged in the engine. A lone "35%" cell would also
    # match the range "21%–35%", so the row is the key.
    for r in stall["repeats"]:
        out[f"stall_row_repeat_{r['repeat']}"] = (
            f"| {r['repeat']} | {_pct(r['share_over_threshold'])} | "
            f"{_pct(r['share_client_minus_server_over_threshold'])} | "
            f"{_pct(r['share_of_over_threshold_with_server_over'])} |")
    out["probes_1_to_3_distinct_workers"] = f"{_count(lb['probes_1_to_3_distinct_workers'])} workers in all"
    f = lb["lb_502_first_attempt_s"]
    out["lb_502_first_attempt_count"] = f"{_count(f['count'])} first attempts"
    out["lb_502_first_attempt_median"] = _s(f["median"])
    out["lb_502_first_attempt_max"] = _s(f["max"])
    for speed in ("fast", "slow"):
        out[f"lb_502_{speed}"] = (f"{_count(f[speed]['count'])} failed after "
                                  f"{_s_span(f[speed]['min'], f[speed]['max'])}")
    p2 = lb["probe2_502_s"]
    non_200 = sum(s["non_200"] for s in lb["probes"]["2"]["steps"].values())
    if p2["count"] != non_200:
        raise ValueError(f"probe 2 has {p2['count']} load-balancer 502s but {non_200} "
                         "non-200s; the post calls every probe-2 failure such a 502")
    out["probe2_502_span"] = _s_span(p2["min"], p2["max"])
    return out


_H3_HEADLINE = {"not evaluable": "H3 is not evaluable", "partial": "H3 holds only in part",
                "holds": "H3 holds", "fails": "H3 fails"}


def _h3(h3: dict) -> dict[str, str]:
    """Per engine speed, the table cell after its row label ("x1.00 | fails"); and the headline
    verdict, the committed curve's (factor 1), as "H3 fails"."""
    out = {}
    for factor, h in h3.items():
        if not h["evaluable"]:
            word = "not evaluable"
        elif h["partial"]:
            word = "partial"
        else:
            word = _verdict(h["holds"])
        out[f"h3_x{factor.replace('.', '')}"] = f"x{float(factor):.2f} | {word}"
        if factor == "1":
            out["h3"] = _H3_HEADLINE[word]
    if "h3" not in out:
        raise ValueError(f"H3 has no verdict at the committed curve's speed (factors "
                         f"{sorted(h3)}); the post's headline verdict would be missing")
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
        "utilization_scale_up_max_threshold":
            f"the highest of which is {c['highest_utilization_scale_up_threshold']:g}",
        "curve_gpu_util": f"GPU utilisation reads {c['curve_gpu_util_min_over_measured_levels']:.1f}",
    }


def _h2_noise(noise: dict) -> dict[str, str]:
    """The margins H2 rests on, beside the spread of utilisation's own identical-fleet runs."""
    out: dict[str, str] = {}
    constrained, at_cap = [], set()
    for sweep, n in noise["per_sweep"].items():
        k = _sweep_key(sweep)
        spread = n["at_cap_policy_p99_s"]
        out[f"h2_margin_{k}"] = _ms_signed(n["h2_margin_s"])
        out[f"h2_margin_vs_best_other_{k}"] = _ms_signed(n["margin_vs_best_other_s"])
        at_cap.add(spread["count"])
        out[f"utilization_at_cap_p99_spread_{k}"] = _s_span(spread["min"], spread["max"])
        out[f"utilization_at_cap_p99_median_{k}"] = _s(spread["median"])
        out[f"others_highest_frontier_cost_{k}"] = _replica_s(
            n["others_highest_frontier_cost_replica_s"])
        if n["iso_cost_slice_constrains_others"]:
            constrained.append(_sweep_label(sweep))
    # The post's table names the count once, in its header; per-sweep counts that differed
    # would make that header wrong for some row.
    if len(at_cap) != 1:
        raise ValueError(f"the sweeps have different numbers of at-cap utilisation policies "
                         f"({sorted(at_cap)}); the table header's one count would be wrong for "
                         "some sweep")
    out["utilization_at_cap_policies"] = f"utilisation's {_count(at_cap.pop())} at-cap policies"
    # One sentence over all four sweeps. Sweep labels contain commas, so a list of them is
    # joined with semicolons.
    out["iso_cost_slice_constrains_others"] = (
        f"The slice constrains them in {len(constrained)} "
        f"sweep{'s' if len(constrained) > 1 else ''}: {'; '.join(constrained)}"
        if constrained else "In no sweep does the slice constrain either of them")
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
        out[f"cold_start_n_{arm.lower()}"] = f"{_count(sim['cold_start'][arm]['n'])} for arm {arm}"
    out["campaign_runs"] = f"of its {_count(sim['campaign_runs'])} cold starts"
    out["h1"] = f"H1 {_verdict(sim['h1']['overall'])}"
    out["h2"] = f"H2 {_verdict(sim['h2']['overall'])}"
    out.update(_h3(sim["h3"]))
    out["h4"] = f"H4 {_verdict(sim['h4']['overall'])}"
    out["h2_sensitivity"] = f"on the sensitivity arm it {_verdict(sim['h2_sensitivity']['overall'])}"
    # The per-sweep table's row label, then the verdict cell: "step, arm A | holds".
    for sweep, held in sim["h2"]["per_sweep"].items():
        out[f"h2_{_sweep_key(sweep)}"] = f"{_sweep_label(sweep)} | {_verdict(held)}"
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
    costs = {s: [sw["reached"][s]["cost_replica_s"] for sw in sim["sweeps"].values()]
             for s in _SIGNALS}
    out["queue_depth_cost_span"] = _count_span(costs["queue_depth"], "replica-seconds")
    out["others_cost_span"] = _count_span(
        costs["in_flight_concurrency"] + costs["utilization"], "replica-seconds")
    out.update(_censoring(sim["h2_censoring"]))
    out.update(_h2_noise(sim["h2_noise"]))
    out["repetitions"] = f"{sim['identity']['repetitions']} repetitions per policy"
    out["max_replicas"] = f"up to {sim['identity']['max_replicas']} replicas"
    return out


def numbers(analysis: dict) -> dict[str, str]:
    out = _validation(analysis["validation"])
    out.update(_load_balancer(analysis["load_balancer"]))
    out.update(_host_speed(analysis["host_speed"]))
    out.update(_simulator(analysis["simulator"]))
    out.update(_money(analysis["money"]))
    if analysis["spend"] is not None:
        out.update(_spend_numbers(analysis["spend"]))
    return out
